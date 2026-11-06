"""Render the daily digest and post it as a GitHub issue."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from radar.config import Config
from radar.db import DB, row_authors, row_json
from radar.text import short_authors, truncate

MAX_ISSUE_BODY = 60000


def _line(row: Any, with_score: bool = True) -> str:
    authors = short_authors(row_authors(row), 3)
    title = row["title"].replace("[", "(").replace("]", ")")
    if row["url"] and title == row["url"]:
        title = "unresolved link (edit the issue with a DOI or arXiv id)"
    link = f"[{title}]({row['url']})" if row["url"] else title
    pdf = f" · [pdf]({row['pdf_url']})" if row["pdf_url"] else ""
    when = row["published"] or ""
    parts = [f"**R{row['seq']}** {link}", authors]
    if row["venue"]:
        parts.append(f"*{row['venue']}*")
    if when:
        parts.append(when)
    s = "- " + " · ".join(parts) + pdf
    if with_score and row["score"] is not None:
        s += f"  \n  score {row['score']} ({row['category']}): {row['reason']}"
    return s


def _deep_block(row: Any) -> str:
    dr = row_json(row, "deep_read") or {}
    if not dr or dr.get("error"):
        return ""
    src = "full text" if dr.get("full_text") else "abstract only"
    dr = {k: (" ".join(v.split()) if isinstance(v, str) else v) for k, v in dr.items()}  # keep each field on one line
    return (
        f"  - **Question:** {dr.get('question','')}\n"
        f"  - **Data:** {dr.get('data','')}\n"
        f"  - **Method:** {dr.get('method','')}\n"
        f"  - **Finding:** {dr.get('finding','')}\n"
        f"  - **Relation to my work:** {dr.get('relation','')}\n"
        f"  - **Verdict:** {dr.get('verdict','')} *({src})*"
    )


def render(cfg: Config, db: DB, day: date) -> tuple[str, list[int]]:
    thr = cfg.settings.show_threshold
    rows = db.undigested()
    manual = [r for r in rows if r["manual"]]
    auto = [r for r in rows if not r["manual"]]
    shown = [r for r in auto if (r["score"] or 0) >= thr]
    near = [r for r in auto if 4 <= (r["score"] or 0) < thr]
    top = [r for r in shown if r["deep_read"]]
    rest = [r for r in shown if not r["deep_read"]]
    wps = [r for r in rest if r["kind"] == "wp"]
    pubs = [r for r in rest if r["kind"] == "pub"]
    other = [r for r in rest if r["kind"] not in ("wp", "pub")]
    # only announce a published version when the working paper was itself worth showing
    now_pub = []
    for r in auto:
        wp = db.get(int(r["published_match"])) if r["published_match"] else None
        if wp and (wp["manual"] or (wp["score"] or 0) >= thr):
            now_pub.append(r)

    out = [f"# Radar digest {day.isoformat()}", ""]
    n_wp = sum(1 for r in auto if r["kind"] == "wp")
    n_pub = sum(1 for r in auto if r["kind"] == "pub")
    out.append(f"Screened {len(auto)} new items ({n_wp} working papers, {n_pub} journal articles); {len(shown)} above threshold {thr}.")
    out.append("")

    if manual:
        out.append("## Sent by you")
        for r in manual:
            out.append(_line(r, with_score=False))
            if r["note"]:
                out.append(f"  - *Your note:* {r['note']}")
            blk = _deep_block(r)
            if blk:
                out.append(blk)
        out.append("")

    if top:
        out.append("## Top picks")
        for r in top:
            out.append(_line(r))
            blk = _deep_block(r)
            if blk:
                out.append(blk)
        out.append("")

    def grouped(title: str, items: list[Any]) -> None:
        if not items:
            return
        out.append(f"## {title}")
        by_venue: dict[str, list[Any]] = defaultdict(list)
        for r in items:
            by_venue[r["venue"] or "other"].append(r)
        for venue in sorted(by_venue):
            out.append(f"### {venue}")
            for r in sorted(by_venue[venue], key=lambda x: -(x["score"] or 0)):
                out.append(_line(r))
        out.append("")

    grouped("New working papers", wps)
    grouped("Newly published", pubs)
    grouped("Other", other)

    if now_pub:
        out.append("## Now published")
        for r in now_pub:
            wp = db.get(int(r["published_match"]))
            out.append(_line(r, with_score=False) + (f"  \n  working paper version: R{wp['seq']} ({wp['venue']})" if wp else ""))
        out.append("")

    if near:
        out.append("<details><summary>Near misses (score 4-5), " + str(len(near)) + " papers</summary>")
        out.append("")
        for r in sorted(near, key=lambda x: -(x["score"] or 0)):
            out.append(f"- R{r['seq']} [{truncate(r['title'], 120)}]({r['url']}) · {r['venue']} · {r['score']}: {truncate(r['reason'], 120)}")
        out.append("")
        out.append("</details>")
        out.append("")

    out.append("---")
    out.append("Rate by commenting on this issue, one line each: `good: R12 R15`, `bad: R3 because too theoretical`, "
               "`missed: https://... ` for a paper I should have shown. Open a new issue with a link to send a paper in.")
    return "\n".join(out), [int(r["seq"]) for r in rows]


def publish(cfg: Config, db: DB, day: date, post_issue: bool = True) -> dict[str, Any]:
    text, seqs = render(cfg, db, day)
    if not seqs:
        return {"papers": 0, "note": "nothing new; no digest written"}
    cfg.digests_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.digests_dir / f"{day.isoformat()}.md"
    path.write_text(text, encoding="utf-8")
    result: dict[str, Any] = {"path": str(path), "papers": len(seqs)}
    if post_issue and seqs:
        from radar.github import GitHub
        gh = GitHub()
        gh.ensure_label(cfg.settings.digest_label, "0e8a16", "daily paper digest")
        gh.ensure_label(cfg.settings.paper_label, "1d76db", "paper sent in for the radar")
        body = text
        if len(body) > MAX_ISSUE_BODY:
            body = body[:MAX_ISSUE_BODY] + f"\n\n… truncated; full digest in `digests/{day.isoformat()}.md`."
        issue = gh.create_issue(f"Radar digest {day.isoformat()}", body, labels=[cfg.settings.digest_label])
        result["issue"] = issue.get("html_url")
    db.mark_digested(seqs, day)
    return result
