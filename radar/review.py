"""Weekly review: propose profile edits from ratings, and evaluate the screener."""
from __future__ import annotations

import difflib
import json
from typing import Any

from pydantic import BaseModel, Field

from radar import llm
from radar.config import Config
from radar.db import DB
from radar.text import truncate


class ProfileProposal(BaseModel):
    rationale: str = Field(description="What the ratings suggest, in a short paragraph")
    changes: list[str] = Field(description="Bullet list of concrete edits made to the profile")
    proposed_profile: str = Field(description="The full revised profile.md text")


REVIEW_INSTRUCTIONS = """You maintain a researcher's screening profile for a paper radar. You get the current
profile.md and the researcher's ratings (good = correctly shown, bad = should not have been shown,
missed = the researcher found it elsewhere and wanted it). Propose a revised profile that would have
produced those ratings: sharpen topic definitions, add or remove authors, add exclusions, adjust
adjacent topics. Keep the file structure and tone; keep everything the ratings do not contradict.
Do not invent topics the ratings do not support. Return only the JSON."""


def _ratings_text(db: DB) -> str:
    rows = db.all_feedback()
    if not rows:
        return "No ratings yet."
    lines = []
    for r in rows:
        lines.append(f"- [{r['label'].upper()}] {r['title']} ({r['venue']}); screener score {r['score']} "
                     f"reason: {r['reason'] or 'n/a'}. Abstract: {truncate(r['abstract'], 400)}"
                     + (f" Researcher note: {r['note']}" if r["note"] else ""))
    return "\n".join(lines)


def propose(cfg: Config, db: DB) -> ProfileProposal:
    data = llm.generate(cfg, model=cfg.settings.review_model, system=REVIEW_INSTRUCTIONS,
                        user=f"# Current profile.md\n\n{cfg.profile_text()}\n\n# Ratings\n\n{_ratings_text(db)}",
                        schema=llm.schema_for(ProfileProposal), max_tokens=32000)
    return ProfileProposal.model_validate(data)


def review(cfg: Config, db: DB, apply: bool = False, post_issue: bool = True) -> dict[str, Any]:
    prop = propose(cfg, db)
    current = cfg.profile_text()
    diff = "".join(difflib.unified_diff(current.splitlines(True), prop.proposed_profile.splitlines(True), "profile.md", "profile.proposed.md"))
    proposed_path = cfg.root / "profile.proposed.md"
    proposed_path.write_text(prop.proposed_profile, encoding="utf-8")
    result: dict[str, Any] = {"rationale": prop.rationale, "changes": prop.changes, "proposed": str(proposed_path)}
    if apply:
        cfg.profile_path.write_text(prop.proposed_profile, encoding="utf-8")
        proposed_path.unlink(missing_ok=True)
        result["applied"] = True
    elif post_issue:
        from radar.github import GitHub
        gh = GitHub()
        body = (f"{prop.rationale}\n\n" + "\n".join(f"- {c}" for c in prop.changes)
                + f"\n\n```diff\n{diff[:50000]}\n```\n\nApply with `radar review --apply`, or edit `profile.md` by hand and delete `profile.proposed.md`.")
        issue = gh.create_issue("Profile review: proposed edits from your ratings", body, labels=["review"])
        result["issue"] = issue.get("html_url")
    return result


def evaluate(cfg: Config, db: DB) -> dict[str, Any]:
    """Re-screen every rated paper with the current profile and count hits and misses."""
    from radar import screen

    rows = db.all_feedback()
    if not rows:
        return {"note": "no ratings to evaluate against"}
    thr = cfg.settings.show_threshold
    tp = fn = tn = fp = 0
    details = []
    for r in rows:
        paper = db.get(int(r["seq"]))
        res = screen.score_one(cfg, db, paper)
        want = r["label"] in ("good", "missed")
        shown = res.score >= thr  # type: ignore[attr-defined]
        if want and shown:
            tp += 1
        elif want and not shown:
            fn += 1
        elif not want and shown:
            fp += 1
        else:
            tn += 1
        details.append({"seq": r["seq"], "label": r["label"], "new_score": res.score, "title": truncate(r["title"], 80)})  # type: ignore[attr-defined]
    return {"threshold": thr, "would_show_wanted": tp, "would_hide_wanted": fn, "would_hide_unwanted": tn, "would_show_unwanted": fp, "details": details}
