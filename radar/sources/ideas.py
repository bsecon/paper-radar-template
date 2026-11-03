"""IDEAS/RePEc series pages (used for IZA, which has no feed of its own)."""
from __future__ import annotations

import re
from datetime import date

from radar import http
from radar.models import Paper
from radar.text import fix_mojibake, repec_authors, strip_html

ITEM_RE = re.compile(r'<A HREF="(/p/([a-z]+)/([a-z]+)/([A-Za-z0-9_.\-]+)\.html)">([^<]+)</A>', re.I)
META_RE = re.compile(r'<META NAME="citation_([a-z_]+)" content="([^"]*)"', re.I)
ABSTRACT_RE = re.compile(r'id="abstract-body">(.*?)</div>', re.S | re.I)
JEL_RE = re.compile(r'HREF="/j/([A-Z]\d\d)\.html"', re.I)
PDF_RE = re.compile(r'(?:href|value)="(https?://[^"]+\.pdf)"', re.I)
DATE_RE = re.compile(r"Date of creation:\s*</[^>]*>\s*([A-Za-z]{3}\s+\d{4})", re.I)


def _listing(url: str) -> list[tuple[str, str, str, str]]:
    r = http.get(url)
    if r is None:
        return []
    items = []
    html = r.content.decode("utf-8", errors="replace")
    # only the chronological paper list, not the "top item" / statistics boxes above it
    start = html.find('class="list-group paperlist"')
    if start > 0:
        html = html[start:]
    for m in ITEM_RE.finditer(html):
        path, archive, series, num, title = m.groups()
        items.append((path, archive, series, num, strip_html(title)))
    # de-duplicate and keep the first (most recent) entries only
    seen, out = set(), []
    for path, archive, series, num, title in items:
        if path in seen:
            continue
        seen.add(path)
        out.append((path, archive, series, num, title))
    return out


def _paper_page(path: str, venue: str, src: str, num: str, handle: str, title: str) -> Paper:
    r = http.get("https://ideas.repec.org" + path)
    meta = {}
    abstract, jel, pdf = "", [], None
    if r is not None:
        html = r.content.decode("utf-8", errors="replace")
        # IDEAS double-encodes UTF-8; repair field by field (a whole page rarely round-trips)
        meta = {k.lower(): fix_mojibake(strip_html(v)) for k, v in META_RE.findall(html)}
        m = ABSTRACT_RE.search(html)
        abstract = fix_mojibake(strip_html(m.group(1))) if m else meta.get("abstract", "")
        jel = sorted(set(JEL_RE.findall(html)))
        pm = PDF_RE.search(html)
        pdf = pm.group(1) if pm else None
    authors = repec_authors([a.strip() for a in meta.get("authors", "").split(";") if a.strip()])
    pub = None
    if meta.get("publication_date"):
        parts = meta["publication_date"].split("/")
        try:
            pub = date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, 1)
        except Exception:
            pub = None
    pid = f"iza:{num.lower()}" if handle.startswith("RePEc:iza:") else f"repec:{handle}"
    venue = venue or meta.get("journal_title") or meta.get("publisher") or ""
    return Paper(
        id=pid, kind="wp", source=src, venue=venue, title=meta.get("title") or title, authors=authors,
        abstract=abstract, repec_handle=handle, url="https://ideas.repec.org" + path, pdf_url=pdf,
        published=pub, jel=jel,
    )


def paper_from_ideas(path: str) -> Paper | None:
    """Resolve any IDEAS paper page path like /p/nbr/nberwo/35670.html."""
    m = re.match(r"/p/([a-z]+)/([a-z]+)/([A-Za-z0-9_.\-]+)\.html", path, re.I)
    if not m:
        return None
    archive, series, num = m.groups()
    try:
        p = _paper_page(path, "", "manual", num, f"RePEc:{archive}:{series}:{num}", "")
    except Exception:
        return None
    if not p.title:
        return None
    p.venue = {"nbr": "NBER", "iza": "IZA", "cpr": "CEPR"}.get(archive, p.venue)
    return p


def fetch(entry: dict, cfg, since: date, known) -> list[Paper]:
    listing = _listing(entry["url"])
    out: list[Paper] = []
    max_new = int(entry.get("max_new", 40))
    for path, archive, series, num, title in listing[:max_new]:
        handle = f"RePEc:{archive}:{series}:{num}"
        pid = f"iza:{num.lower()}" if archive == "iza" else f"repec:{handle}"
        if known(pid):
            continue
        out.append(_paper_page(path, entry.get("venue", entry["id"]), entry["id"], num, handle, title))
    return out
