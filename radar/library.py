"""Library: BibTeX file, local PDF sync, index page, search."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from radar import http
from radar.config import Config
from radar.db import DB, row_authors, row_json
from radar.text import last_name, short_authors


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _year(row: Any) -> str:
    return (row["published"] or row["first_seen"] or "")[:4] or "n.d."


def bib_key(row: Any, existing: set[str]) -> str:
    authors = row_authors(row)
    ln = _ascii(last_name(authors[0])) if authors else "anon"
    ln = re.sub(r"[^A-Za-z]", "", ln).lower() or "anon"
    words = [w for w in re.sub(r"[^A-Za-z ]", " ", _ascii(row["title"])).lower().split() if w not in {"the", "a", "an", "of", "and", "on", "in"}]
    base = f"{ln}{_year(row)}{words[0] if words else ''}"
    key, i = base, 2
    while key in existing:
        key, i = f"{base}{i}", i + 1
    return key


def bib_entry(row: Any, key: str) -> str:
    authors = " and ".join(row_authors(row)) or "Unknown"
    title = row["title"].replace("{", "").replace("}", "")
    fields = [f"  author = {{{authors}}}", f"  title = {{{title}}}", f"  year = {{{_year(row)}}}"]
    if row["kind"] == "pub":
        etype = "article"
        fields.append(f"  journal = {{{row['venue']}}}")
    else:
        etype = "techreport"
        fields.append(f"  institution = {{{row['venue']}}}")
        fields.append("  type = {Working Paper}")
    if row["doi"]:
        fields.append(f"  doi = {{{row['doi']}}}")
    if row["url"]:
        fields.append(f"  url = {{{row['url']}}}")
    return f"@{etype}{{{key},\n" + ",\n".join(fields) + "\n}\n"


def update_bib(cfg: Config, db: DB) -> int:
    """Append BibTeX entries for kept papers that do not have one yet."""
    cfg.bib_path.parent.mkdir(parents=True, exist_ok=True)
    existing_text = cfg.bib_path.read_text(encoding="utf-8") if cfg.bib_path.exists() else ""
    keys = set(re.findall(r"@\w+\{([^,]+),", existing_text))
    db.set_state("show_threshold", str(cfg.settings.show_threshold))
    added = []
    for row in db.kept():
        if row["bib_key"]:
            continue
        key = bib_key(row, keys)
        keys.add(key)
        added.append(bib_entry(row, key))
        db.set_fields(int(row["seq"]), bib_key=key)
    if added:
        with cfg.bib_path.open("a", encoding="utf-8") as f:
            if existing_text and not existing_text.endswith("\n"):
                f.write("\n")
            f.write("\n".join(added))
    return len(added)


def pdf_name(row: Any) -> str:
    authors = row_authors(row)
    ln = re.sub(r"[^A-Za-z]", "", _ascii(last_name(authors[0]))) if authors else "Anon"
    words = re.sub(r"[^A-Za-z0-9 ]", " ", _ascii(row["title"])).split()[:6]
    return f"{_year(row)}_{ln}_{'_'.join(words)}.pdf"


def _find_pdf_url(cfg: Config, db: DB, row: Any) -> str | None:
    """NEP feed items and some journals come without a PDF link: ask the RePEc page or OpenAlex once."""
    if row["pdf_url"] is not None and row["pdf_url"] == "":
        return None  # already tried
    url = None
    handle = row["repec_handle"]
    if handle and handle.count(":") == 3:
        from radar.sources.ideas import paper_from_ideas
        _, archive, series, num = handle.split(":")
        p = paper_from_ideas(f"/p/{archive}/{series}/{num}.html")
        if p and p.pdf_url:
            url = p.pdf_url
    if not url and row["doi"]:
        from radar.models import Paper
        from radar.sources.openalex import enrich_by_doi
        p = Paper(id=row["id"], kind=row["kind"], source=row["source"], title=row["title"], doi=row["doi"], abstract="x")
        try:
            enrich_by_doi([p], cfg.contact_email)
        except Exception:
            p.pdf_url = None
        url = p.pdf_url
    db.set_fields(int(row["seq"]), pdf_url=url or "")
    return url


def sync_pdfs(cfg: Config, db: DB, limit: int | None = None) -> tuple[int, int]:
    """Download PDFs for kept papers into the library folder. Returns (downloaded, skipped)."""
    cfg.pdf_dir.mkdir(parents=True, exist_ok=True)
    got = skipped = 0
    for row in db.kept():
        if limit is not None and got >= limit:
            break
        target = cfg.pdf_dir / pdf_name(row)
        if target.exists():
            continue
        pdf_url = row["pdf_url"] or _find_pdf_url(cfg, db, row)
        if not pdf_url:
            skipped += 1
            continue
        data = http.get_bytes(pdf_url)
        if not data:
            skipped += 1
            continue
        target.write_bytes(data)
        got += 1
    return got, skipped


def write_index(cfg: Config, db: DB) -> Path:
    """library/index.md: every kept paper with links and the research note."""
    out = ["# Library", "", "Papers you sent in, rated good, or that scored above the threshold. Newest first.", ""]
    for row in reversed(db.kept()):
        dr = row_json(row, "deep_read") or {}
        pdf_local = cfg.pdf_dir / pdf_name(row)
        links = [f"[page]({row['url']})"] if row["url"] else []
        if row["pdf_url"]:
            links.append(f"[pdf]({row['pdf_url']})")
        if pdf_local.exists():
            links.append(f"[local]({pdf_local.relative_to(cfg.root) if pdf_local.is_relative_to(cfg.root) else pdf_local})")
        score = f"score {row['score']}" if row["score"] is not None else "sent by you"
        out.append(f"## R{row['seq']} · {row['title']}")
        out.append(f"{short_authors(row_authors(row), 6)} · *{row['venue']}* · {row['published'] or row['first_seen'][:10]} · {score}"
                   + (f" · bib `{row['bib_key']}`" if row["bib_key"] else "") + "  ")
        out.append(" · ".join(links))
        if dr.get("finding"):
            out.append("")
            out.append(f"> **Q:** {dr.get('question','')}  \n> **Finding:** {dr.get('finding','')}  \n> **Relation:** {dr.get('relation','')}")
        out.append("")
    path = cfg.root / "library" / "index.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path
