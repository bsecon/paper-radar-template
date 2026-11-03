"""Crossref: new journal articles by ISSN, and DOI lookups."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from radar import http
from radar.models import Paper
from radar.text import clean_doi, strip_html

API = "https://api.crossref.org"


def _paper_from_work(w: dict[str, Any], venue: str, src: str, kind: str = "pub") -> Paper | None:
    doi = clean_doi(w.get("DOI"))
    titles = w.get("title") or []
    if not doi or not titles:
        return None
    title = strip_html(titles[0])
    authors = []
    for a in w.get("author") or []:
        name = " ".join(x for x in [a.get("given"), a.get("family")] if x) or a.get("name")
        if name:
            authors.append(name)
    pub = None
    for key in ("published-online", "published-print", "created", "issued"):
        parts = (w.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            p = parts[0] + [1, 1]
            try:
                pub = date(int(p[0]), int(p[1]), int(p[2]))
                break
            except Exception:
                continue
    container = (w.get("container-title") or [venue])[0] if w.get("container-title") else venue
    ctype = w.get("type", "")
    return Paper(
        id=f"doi:{doi}", kind=kind if kind != "unknown" else ("pub" if ctype == "journal-article" else "unknown"),
        source=src, venue=container or venue, title=title, authors=authors,
        abstract=_clean_abstract(w.get("abstract")), doi=doi, url=f"https://doi.org/{doi}", published=pub,
    )


def fetch_journal(entry: dict, cfg, since: date) -> list[Paper]:
    issn = entry["issn"]
    r = http.get(
        f"{API}/journals/{issn}/works",
        params={
            "filter": f"from-created-date:{since.isoformat()},type:journal-article",
            "rows": 200, "sort": "created", "order": "desc", "mailto": cfg.contact_email,
            "select": "DOI,title,author,abstract,container-title,created,published-online,published-print,issued,type",
        },
    )
    if r is None:
        return []
    items = (r.json().get("message") or {}).get("items") or []
    out: list[Paper] = []
    for w in items:
        p = _paper_from_work(w, entry["name"], f"journal:{issn}")
        if p and not _looks_like_front_matter(p.title):
            p.venue = entry["name"]
            out.append(p)
    return out


def _clean_abstract(a: str | None) -> str:
    t = strip_html(a or "")
    return re.sub(r"^(abstract|summary)\s*[:.]?\s*", "", t, flags=re.I)


def _looks_like_front_matter(title: str) -> bool:
    t = title.lower()
    return t in {"front matter", "back matter", "issue information", "editorial board", "erratum", "corrigendum", "masthead"} or t.startswith("issue information") or t.startswith("front matter")


def by_doi(doi: str, src: str = "manual") -> Paper | None:
    doi = clean_doi(doi) or ""
    r = http.get(f"{API}/works/{doi}", params={"mailto": "paper-radar"}, ok_404=True)
    if r is None:
        return None
    w = (r.json() or {}).get("message") or {}
    return _paper_from_work(w, "", src, kind="unknown")
