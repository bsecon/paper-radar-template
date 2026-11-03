"""arXiv Atom API for the econ categories."""
from __future__ import annotations

from datetime import date

import feedparser

from radar import http
from radar.models import Paper
from radar.text import strip_html

API = "http://export.arxiv.org/api/query"


def _parse(feed, venue: str, src: str) -> list[Paper]:
    out: list[Paper] = []
    for e in feed.entries:
        aid = e.get("id", "").rsplit("/abs/", 1)[-1]
        aid = aid.split("v")[0] if aid and aid[0].isdigit() else aid
        if not aid:
            continue
        t = e.get("published_parsed")
        pub = date(t.tm_year, t.tm_mon, t.tm_mday) if t else None
        cats = [c.get("term") for c in e.get("tags", []) if c.get("term")]
        jel = [c for c in cats if len(c) == 3 and c[0].isalpha() and c[1:].isdigit()]
        out.append(
            Paper(
                id=f"arxiv:{aid}", kind="wp", source=src, venue=venue, title=strip_html(e.get("title", "")),
                authors=[a.get("name") for a in e.get("authors", []) if a.get("name")],
                abstract=strip_html(e.get("summary", "")), arxiv_id=aid,
                url=f"https://arxiv.org/abs/{aid}", pdf_url=f"https://arxiv.org/pdf/{aid}", published=pub, jel=jel,
            )
        )
    return out


def fetch(entry: dict, cfg, since: date, known) -> list[Paper]:
    cats = entry.get("categories") or ["econ.GN"]
    q = " OR ".join(f"cat:{c}" for c in cats)
    r = http.get(API, params={"search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": 200})
    if r is None:
        return []
    papers = _parse(feedparser.parse(r.content), entry.get("venue", "arXiv"), entry["id"])
    return [p for p in papers if not p.published or p.published >= since]


def by_id(arxiv_id: str, src: str = "manual") -> Paper | None:
    r = http.get(API, params={"id_list": arxiv_id})
    if r is None:
        return None
    papers = _parse(feedparser.parse(r.content), "arXiv", src)
    return papers[0] if papers else None
