"""Fetch step and the end-to-end daily run."""
from __future__ import annotations

import traceback
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from radar import http
from radar.config import Config
from radar.db import DB
from radar.models import Paper
from radar.sources import fetch_journal, fetch_working_papers
from radar.sources.openalex import enrich_by_doi


def today(cfg: Config) -> date:
    return datetime.now(ZoneInfo(cfg.settings.timezone)).date()


def since_date(cfg: Config, db: DB) -> date:
    floor = today(cfg) - timedelta(days=cfg.settings.lookback_days)
    last = db.get_state("last_fetch")
    if last:
        try:
            return max(floor, date.fromisoformat(last) - timedelta(days=1))
        except ValueError:
            pass
    return floor


def fetch(cfg: Config, db: DB, log: Callable[[str], None] = print) -> dict[str, Any]:
    http.configure(cfg.user_agent)
    since = since_date(cfg, db)
    known = lambda pid: db.find_by_id(pid) is not None  # noqa: E731
    summary: dict[str, Any] = {"since": since.isoformat(), "sources": {}, "new": 0}
    collected: list[Paper] = []
    for entry in cfg.working_papers:
        try:
            papers = fetch_working_papers(entry, cfg, since, known)
            summary["sources"][entry["id"]] = len(papers)
            collected.extend(papers)
        except Exception as e:
            summary["sources"][entry["id"]] = f"error: {e}"
            log(f"[fetch] {entry['id']} failed: {e}")
    for j in cfg.journals:
        try:
            papers = fetch_journal(j, cfg, since)
            summary["sources"][j["name"]] = len(papers)
            collected.extend(papers)
        except Exception as e:
            summary["sources"][j["name"]] = f"error: {e}"
            log(f"[fetch] {j['name']} failed: {e}")
    # abstracts for journal articles mostly come from OpenAlex
    fresh = [p for p in collected if db.find_by_id(p.id) is None]
    try:
        summary["enriched"] = enrich_by_doi(fresh, cfg.contact_email)
    except Exception as e:
        log(f"[fetch] OpenAlex enrichment failed: {e}")
    # journal abstracts often reach OpenAlex a few days late: retry for unscreened rows
    try:
        summary["re_enriched"] = reenrich_missing(db, cfg.contact_email)
    except Exception as e:
        log(f"[fetch] re-enrichment failed: {e}")
    new = 0
    for p in collected:
        _, inserted = db.upsert_paper(p)
        new += int(inserted)
    summary["new"] = new
    db.set_state("last_fetch", today(cfg).isoformat())
    db.log_run("fetch", f"new={new} since={since}")
    return summary


def alert(cfg: Config, db: DB, gh, screen_result: dict[str, Any]) -> None:
    """Open one GitHub issue (label: alert) when screening fails outright; close it when it recovers."""
    failed = screen_result.get("scored", 0) == 0 and screen_result.get("errors") and screen_result.get("unscreened_left", 0) > 0
    open_issue = db.get_state("alert_issue")
    if failed and not open_issue:
        reason = screen_result["errors"][0]
        from radar import llm
        if llm.is_auth_error(reason):
            hint = ("The Claude Code login used by the radar has expired. On the machine that runs it, run "
                    "`bin/claude-login.sh` (opens a browser), then rerun the job: `launchctl kickstart gui/$(id -u)/com.paper-radar` "
                    "on macOS, or `bin/daily.sh` by hand.")
        elif llm.is_setup_error(reason):
            hint = ("The Claude Code executable could not be found. Run `curl -fsSL https://claude.ai/install.sh | bash` "
                    "(or set RADAR_CLAUDE_BIN), check with `uv run radar doctor`, then rerun the job.")
        else:
            hint = ("Probably transient (network, rate limit). The job retries automatically at 13:00; "
                    "if this issue is still open tomorrow, check the log: `~/Library/Logs/paper-radar.log` on macOS, "
                    "`~/.local/state/paper-radar/daily.log` on Linux.")
        body = f"Every screening call failed today, so no digest was produced.\n\n```\n{reason[:600]}\n```\n\n{hint}"
        if gh is not None:
            gh.ensure_label("alert", "d93f0b", "radar needs attention")
            issue = gh.create_issue("Radar needs attention: screening failed", body, labels=["alert"])
            db.set_state("alert_issue", str(issue["number"]))
        try:  # local ping as well
            import subprocess
            subprocess.run(["osascript", "-e", 'display notification "Screening failed; see GitHub alert issue" with title "paper-radar"'], timeout=10)
        except Exception:
            pass
    elif not failed and open_issue and screen_result.get("scored", 0) > 0 and gh is not None:
        try:
            gh.comment(int(open_issue), "Screening works again; closing.")
            gh.close(int(open_issue))
        except Exception:
            pass
        db.set_state("alert_issue", "")


def reenrich_missing(db: DB, mailto: str) -> int:
    rows = db.conn.execute("SELECT * FROM papers WHERE screened_at IS NULL AND doi IS NOT NULL AND (abstract='' OR pdf_url IS NULL)").fetchall()
    if not rows:
        return 0
    papers = [Paper(id=r["id"], kind=r["kind"], source=r["source"], title=r["title"], doi=r["doi"], abstract=r["abstract"], pdf_url=r["pdf_url"]) for r in rows]
    enrich_by_doi(papers, mailto)
    n = 0
    for r, p in zip(rows, papers):
        fields = {}
        if p.abstract and not r["abstract"]:
            fields["abstract"] = p.abstract
        if p.pdf_url and not r["pdf_url"]:
            fields["pdf_url"] = p.pdf_url
        if fields:
            db.set_fields(int(r["seq"]), **fields)
            n += 1
    return n


def pending_work(db: DB) -> bool:
    """True if a previous run left papers unscreened or an alert open (used by the afternoon retry)."""
    return bool(db.unscreened()) or bool(db.get_state("alert_issue"))


def run(cfg: Config, db: DB, post_issue: bool = True, log: Callable[[str], None] = print) -> dict[str, Any]:
    """fetch -> intake -> screen -> deep read -> link -> digest -> library."""
    from radar import deepread, digest, intake, library, linking, screen
    from radar.github import GitHub

    report: dict[str, Any] = {}
    steps: list[tuple[str, Callable[[], Any]]] = []

    def gh_or_none():
        try:
            return GitHub()
        except Exception as e:
            log(f"[github] unavailable: {e}")
            return None

    steps.append(("fetch", lambda: fetch(cfg, db, log)))

    def do_intake():
        gh = gh_or_none()
        if gh is None:
            return "skipped (no GitHub access)"
        return {"issues": intake.process_issues(cfg, db, gh), "ratings": intake.process_ratings(cfg, db, gh)}

    steps.append(("intake", do_intake))
    def do_screen():
        res = screen.screen(cfg, db)
        alert(cfg, db, gh_or_none(), res)
        return res

    steps.append(("screen", do_screen))
    steps.append(("deep_read", lambda: deepread.deep_read(cfg, db)))
    steps.append(("link", lambda: linking.link_published(db)))
    steps.append(("digest", lambda: digest.publish(cfg, db, today(cfg), post_issue=post_issue)))
    steps.append(("bib", lambda: library.update_bib(cfg, db)))

    def do_pdfs():
        got, skipped = library.sync_pdfs(cfg, db)
        return {"downloaded": got, "no_pdf_or_failed": skipped, "dir": str(cfg.pdf_dir)}

    steps.append(("pdfs", do_pdfs))
    steps.append(("index", lambda: str(library.write_index(cfg, db))))
    for name, fn in steps:
        try:
            report[name] = fn()
            log(f"[{name}] {report[name]}")
        except Exception as e:
            report[name] = f"error: {e}"
            log(f"[{name}] failed: {e}\n{traceback.format_exc()}")
    return report
