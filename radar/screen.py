"""Screening: score every new paper against profile.md, in groups of a few papers per call."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field

from radar import llm
from radar.config import Config
from radar.db import DB, row_authors, row_json
from radar.models import ScreenResult
from radar.text import last_name, short_authors, truncate

INSTRUCTIONS = """You screen new economics papers for one researcher. You get the researcher's profile,
examples of past ratings, and then a numbered list of papers (title, authors, venue, abstract, JEL codes).
For every paper, score how much this researcher would want to see it in a daily digest.

Scoring guide:
- 9-10: squarely in a core topic, or by an always-show author, and looks substantive.
- 7-8: core topic but narrower, or adjacent topic done very well, or a method the researcher would use.
- 5-6: adjacent; worth a glance in a quiet week.
- 3-4: loosely related; would only matter with a specific angle.
- 0-2: unrelated.
Category: core / adjacent / methods (mainly useful for its econometrics or modelling) / skip.
Be calibrated: most papers in a broad feed are 0-4. Do not inflate scores for famous venues.
Author matches count: if an author is on the always-show list, score at least 7.
Return one result per paper, with the paper's ref exactly as given. Return only the JSON."""


ALWAYS_SHOW_MIN = 7


def always_show_names(profile: str) -> list[str]:
    """Names listed under the profile's '## Always show' heading (comma/newline separated)."""
    m = re.search(r"^##\s*Always show\s*$(.*?)(?=^##\s|\Z)", profile, re.M | re.S)
    if not m:
        return []
    body = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S)
    body = re.sub(r"(?i)papers by or with\s*:", "", body)
    names = [n.strip(" .\n-*") for n in re.split(r",|\n|\band\b", body)]
    return [n for n in names if len(n.split()) >= 2]


def _key(name: str) -> tuple[str, str]:
    """(last name, first initial), ascii lower-case; handles 'First Last' and 'Last, First'."""
    a = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().strip()
    if "," in a:
        last, first = (p.strip() for p in a.split(",", 1))
    else:
        parts = a.split()
        last, first = (parts[-1], parts[0]) if len(parts) > 1 else (a, "")
    return last.lower(), (first[:1].lower() if first else "")


def always_show_match(names: list[str], authors: list[str]) -> str | None:
    """The first author that matches an always-show name (same last name, same first initial if both known)."""
    keys = [_key(n) for n in names]
    for author in authors:
        last, ini = _key(author)
        for klast, kini in keys:
            if last == klast and (not ini or not kini or ini == kini):
                return author
    return None


class ScoredPaper(ScreenResult):
    ref: str = Field(description="The paper ref exactly as given, e.g. R12")


class ScreenBatch(BaseModel):
    results: list[ScoredPaper]


def _examples_block(db: DB) -> str:
    parts = []
    for label, header in (("good", "Rated GOOD (should be shown)"),
                          ("missed", "MISSED (researcher found these elsewhere and wanted them)"),
                          ("bad", "Rated BAD (should not have been shown)")):
        rows = db.feedback_examples(label, limit=8)
        if not rows:
            continue
        parts.append(f"### {header}")
        for r in rows:
            note = f" Note: {r['fb_note']}" if r["fb_note"] else ""
            parts.append(f"- {r['title']} ({r['venue']}). {truncate(r['abstract'], 300)}{note}")
    return "\n".join(parts) if parts else "No ratings yet."


def system_prompt(cfg: Config, db: DB) -> str:
    return f"{INSTRUCTIONS}\n\n# Researcher profile\n\n{cfg.profile_text()}\n\n# Past ratings\n\n{_examples_block(db)}"


def paper_block(row: Any) -> str:
    jel = row_json(row, "jel") or []
    kind = {"wp": "working paper", "pub": "journal article"}.get(row["kind"], "paper")
    return (
        f"## R{row['seq']}\nType: {kind}\nVenue: {row['venue']}\nTitle: {row['title']}\n"
        f"Authors: {short_authors(row_authors(row), 8)}\nJEL: {', '.join(jel) or 'n/a'}\n"
        f"Abstract: {truncate(row['abstract'], 2000) or '(no abstract available; judge from the title)'}\n"
    )


def screen_group(cfg: Config, db: DB, system: str, rows: list[Any], always: list[str] | None = None) -> int:
    user = "Score these papers.\n\n" + "\n".join(paper_block(r) for r in rows)
    data = llm.generate(cfg, model=cfg.settings.screen_model, system=system, user=user,
                        schema=llm.schema_for(ScreenBatch), effort=cfg.settings.screen_effort)
    batch = ScreenBatch.model_validate(data)
    by_ref = {r.ref.upper().lstrip("#"): r for r in batch.results}
    n = 0
    for row in rows:
        res = by_ref.get(f"R{row['seq']}")
        if res is None:
            continue
        score, reason = res.score, res.reason
        hit = always_show_match(always or [], row_authors(row))
        if hit and score < ALWAYS_SHOW_MIN:  # the model treats the list as a hint; the profile means it as a rule
            score, reason = ALWAYS_SHOW_MIN, f"Always-show author {hit}. {reason}"
        db.set_screen(int(row["seq"]), score, res.category, reason, res.topics)
        n += 1
    return n


def screen(cfg: Config, db: DB, limit: int | None = None) -> dict[str, Any]:
    rows = db.unscreened()
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        return {"scored": 0, "calls": 0}
    if cfg.settings.backend != "api":
        try:
            llm.claude_bin(cfg)
        except Exception as e:
            return {"scored": 0, "calls": 0, "unscreened_left": len(rows), "errors": [str(e)[:200]]}
    system = system_prompt(cfg, db)
    always = always_show_names(cfg.profile_text())
    size = max(1, cfg.settings.screen_group_size)
    scored = calls = 0
    errors: list[str] = []
    for i in range(0, len(rows), size):
        group = rows[i : i + size]
        calls += 1
        try:
            scored += screen_group(cfg, db, system, group, always)
        except Exception as e:
            errors.append(str(e)[:200])
            if llm.is_auth_error(str(e)) or llm.is_setup_error(str(e)):
                break  # every further call would fail the same way
    out: dict[str, Any] = {"scored": scored, "calls": calls, "unscreened_left": len(db.unscreened())}
    if errors:
        out["failed_calls"] = len(errors)
        out["warning"] = f"{len(errors)} of {calls} screening calls failed; {out['unscreened_left']} papers left unscreened"
        out["errors"] = errors[:5]
    return out


def score_one(cfg: Config, db: DB, row: Any) -> ScreenResult:
    """Used by `radar eval`: re-score one paper with the current profile without storing it."""
    system = system_prompt(cfg, db)
    data = llm.generate(cfg, model=cfg.settings.screen_model, system=system, user="Score these papers.\n\n" + paper_block(row),
                        schema=llm.schema_for(ScreenBatch), effort=cfg.settings.screen_effort)
    batch = ScreenBatch.model_validate(data)
    return batch.results[0]
