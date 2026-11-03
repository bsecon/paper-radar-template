"""Intake from GitHub issues: papers you send in, and ratings on digest issues."""
from __future__ import annotations

import re
from typing import Any

from radar.config import Config
from radar.db import DB
from radar.feedback import apply_ratings, parse_feedback
from radar.github import GitHub
from radar.models import Paper
from radar.resolve import resolve
from radar.text import URL_RE, short_authors

MISSED_RE = re.compile(r"\bmissed\b", re.I)


def _note_from(text: str) -> str:
    t = URL_RE.sub("", text)
    t = MISSED_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip()[:400]


def add_paper(cfg: Config, db: DB, text: str, missed: bool = False, origin: str = "cli") -> tuple[int | None, bool, str, Paper | None]:
    """Resolve free text into a paper and store it as manual. Returns (seq, inserted, how, paper)."""
    paper, how = resolve(text, cfg.contact_email)
    if paper is None:
        url = (URL_RE.findall(text) or [None])[0]
        if not url:
            return None, False, how, None
        paper = Paper(id=f"url:{url}", kind="unknown", source="manual", title=url, url=url)
    paper.manual = True
    paper.missed = missed
    paper.source = "manual"
    paper.note = _note_from(text)
    seq, inserted = db.upsert_paper(paper)
    if missed:
        db.add_feedback(seq, "missed", paper.note, origin)
    return seq, inserted, how, paper


def process_issues(cfg: Config, db: DB, gh: GitHub) -> list[str]:
    """Open issues without the digest label are papers to add."""
    log: list[str] = []
    for issue in gh.list_issues(state="open"):
        labels = {l["name"] for l in issue.get("labels", [])}
        if cfg.settings.digest_label in labels:
            continue
        text = f"{issue.get('title') or ''}\n{issue.get('body') or ''}"
        missed = bool(MISSED_RE.search(text))
        seq, inserted, how, paper = add_paper(cfg, db, text, missed=missed, origin=f"issue#{issue['number']}")
        if seq is None:
            gh.comment(issue["number"], "I could not find a paper reference in this issue (no URL, DOI, or arXiv id). Edit it or open a new one.")
            log.append(f"#{issue['number']}: nothing to resolve")
            continue
        row = db.get(seq)
        status = "added" if inserted else "already known, marked as sent by you"
        msg = (f"**{status}** as R{seq} ({how}).\n\n**{row['title']}**  \n{short_authors(__import__('json').loads(row['authors']))}"
               f" · {row['venue'] or 'venue unknown'}\n\n")
        if row["score"] is not None:
            msg += f"The screener had scored it {row['score']}/10 ({row['category']}): {row['reason']}\n\n"
        if missed:
            msg += "Recorded as **missed**: it will be used as a positive example in future screening.\n\n"
        msg += "It will appear in the next digest with a full read."
        gh.comment(issue["number"], msg)
        gh.close(issue["number"], labels=sorted(labels | {cfg.settings.paper_label}))
        log.append(f"#{issue['number']}: R{seq} {status}")
    return log


def process_ratings(cfg: Config, db: DB, gh: GitHub) -> list[str]:
    """Comments on digest issues carry ratings."""
    since = db.get_state("ratings_since")
    log: list[str] = []
    newest = since
    for issue in gh.list_issues(state="all", labels=cfg.settings.digest_label, since=since):
        for c in gh.issue_comments(issue["number"], since=since):
            if c.get("user", {}).get("type") == "Bot":
                continue
            created = c.get("created_at")
            if since and created and created <= since:
                continue
            body = c.get("body") or ""
            if body.startswith("Recorded:"):
                continue
            recorded: list[str] = []
            for label, refs, note in parse_feedback(body):
                if label == "missed":
                    for ref in refs:
                        seq, inserted, how, _ = add_paper(cfg, db, ref + " " + note, missed=True, origin=f"comment#{c['id']}")
                        if seq is not None:
                            recorded.append(f"missed R{seq}")
                else:
                    done = apply_ratings(db, label, refs, note, origin=f"comment#{c['id']}")
                    recorded.extend(f"{label} {d}" for d in done)
            if recorded:
                gh.comment(issue["number"], "Recorded: " + ", ".join(recorded))
                log.append(f"#{issue['number']} comment {c['id']}: " + ", ".join(recorded))
            if created and (newest is None or created > newest):
                newest = created
    if newest:
        db.set_state("ratings_since", newest)
    return log
