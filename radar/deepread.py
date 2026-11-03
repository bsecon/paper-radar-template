"""Full-paper reads for the top papers of the day."""
from __future__ import annotations

from typing import Any

from radar import http, llm
from radar.config import Config
from radar.db import DB, row_authors
from radar.models import DeepRead
from radar.text import short_authors

INSTRUCTIONS = """You are reading one economics paper for a researcher whose profile follows. Write a compact
research note for them: the question, data, method, main finding with magnitudes, how it relates to
their own work (name the specific paper of theirs when there is a clear link), and a one-line verdict
on whether it deserves a full read now. Be concrete and skeptical; do not pad. Return only the JSON."""

MAX_PDF_BYTES = 25_000_000


def _user(row: Any, text: str) -> str:
    header = (
        f"Title: {row['title']}\nAuthors: {short_authors(row_authors(row), 10)}\nVenue: {row['venue']}\n"
        f"Abstract: {row['abstract'] or '(none)'}\n"
    )
    if row["note"]:
        header += f"\nThe researcher sent this paper in themselves with the note: {row['note']}\n"
    if text:
        return header + "\n# Full text (extracted from the PDF, may be imperfect)\n\n" + text
    return header + "\nOnly the abstract is available; say so in the note where it limits you."


def deep_read_one(cfg: Config, db: DB, row: Any) -> DeepRead | None:
    pdf = http.get_bytes(row["pdf_url"], MAX_PDF_BYTES) if row["pdf_url"] else None
    text = llm.pdf_text(pdf) if pdf else ""
    system = f"{INSTRUCTIONS}\n\n# Researcher profile\n\n{cfg.profile_text()}"
    data = llm.generate(cfg, model=cfg.settings.deep_read_model, system=system, user=_user(row, text),
                        schema=llm.schema_for(DeepRead), effort=cfg.settings.deep_read_effort)
    res = DeepRead.model_validate(data)
    stored = res.model_dump()
    stored["full_text"] = bool(text)
    db.set_deep_read(int(row["seq"]), stored)
    return res


def candidates(cfg: Config, db: DB) -> list[Any]:
    rows = db.undigested()
    manual = [r for r in rows if r["manual"] and not r["deep_read"]]
    top = [r for r in rows if not r["manual"] and not r["deep_read"] and (r["score"] or 0) >= cfg.settings.deep_read_threshold]
    top.sort(key=lambda r: -(r["score"] or 0))
    return manual + top[: cfg.settings.max_deep_reads]


def deep_read(cfg: Config, db: DB, limit: int | None = None) -> dict[str, Any]:
    n = 0
    errors = []
    for row in candidates(cfg, db)[:limit]:
        try:
            if deep_read_one(cfg, db, row):
                n += 1
        except Exception as e:  # keep the digest going
            db.set_deep_read(int(row["seq"]), {"error": str(e)[:300]})
            errors.append(f"R{row['seq']}: {str(e)[:120]}")
    out: dict[str, Any] = {"deep_reads": n}
    if errors:
        out["errors"] = errors
    return out
