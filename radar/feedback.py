"""Ratings: parse feedback lines, record them, and summarise."""
from __future__ import annotations

import re
from typing import Any

from radar.db import DB

LINE_RE = re.compile(r"^[\s*_>#\-]*(good|bad|missed)\b[\s*_]*[:\-–]?\s*(.*?)[\s*_]*$", re.I)
QUOTE_RE = re.compile(r"^(>|On .* wrote:|Am .* schrieb|-{2,}\s*Original|From: )", re.I)
REF_RE = re.compile(r"#?\bR?(\d{1,6})\b", re.I)
URL_RE = re.compile(r"https?://\S+")
DOI_RE = re.compile(r"10\.\d{4,9}/\S+")


def parse_feedback(text: str) -> list[tuple[str, list[str], str]]:
    """Return [(label, refs, note)] from free text, one per line starting with good/bad/missed.

    Tolerates markdown emphasis from email replies, stops at quoted email text, and lets a
    `missed:` line carry its URL on the following lines.
    """
    out = []
    lines = []
    for line in text.splitlines():
        if QUOTE_RE.match(line.strip()):
            break  # the rest is the quoted digest email
        lines.append(line)
    for i, line in enumerate(lines):
        m = LINE_RE.match(line)
        if not m:
            continue
        label, rest = m.group(1).lower(), m.group(2).strip()
        if label == "missed":
            urls = URL_RE.findall(rest) + DOI_RE.findall(rest)
            if not urls:  # look ahead for the link on the next lines
                for nxt in lines[i + 1 : i + 4]:
                    if LINE_RE.match(nxt):
                        break
                    urls += URL_RE.findall(nxt) + DOI_RE.findall(nxt)
                    if urls:
                        break
            note = URL_RE.sub("", rest)
            note = DOI_RE.sub("", note).strip(" -–:;,*")
            out.append((label, [u.rstrip(".,;)*") for u in urls] or [rest], note))
            continue
        refs = ["R" + r for r in REF_RE.findall(rest)]
        note = REF_RE.sub("", rest)
        note = re.sub(r"^[\s,;*_]*(because|since|as)?\s*", "", note, flags=re.I).strip(" -–:;,*_")
        if refs:
            out.append((label, refs, note))
    return out


def apply_ratings(db: DB, label: str, refs: list[str], note: str, origin: str) -> list[str]:
    done = []
    for ref in refs:
        row = db.resolve_ref(ref)
        if row is None:
            continue
        db.add_feedback(int(row["seq"]), label, note, origin)
        done.append(f"R{row['seq']}")
    return done


def stats(db: DB) -> dict[str, Any]:
    rows = db.all_feedback()
    counts = {"good": 0, "bad": 0, "missed": 0}
    for r in rows:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    shown = db.conn.execute("SELECT COUNT(*) FROM papers WHERE digested_on IS NOT NULL").fetchone()[0]
    return {"ratings": counts, "papers_in_digests": shown}
