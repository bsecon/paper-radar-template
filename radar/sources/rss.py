"""RSS / RDF feeds: NBER, CEPR, RePEc NEP reports, and any generic feed."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import feedparser

from radar import http
from radar.models import Paper
from radar.text import clean_doi, find_identifiers, repec_authors, split_authors, strip_html


def _entry_date(e: Any) -> date | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = e.get(key)
        if t:
            return date(t.tm_year, t.tm_mon, t.tm_mday)
    return None


def _creators(e: Any) -> list[str]:
    names: list[str] = []
    for a in e.get("authors") or []:
        n = a.get("name") if isinstance(a, dict) else None
        if n:
            names.append(n)
    if not names and e.get("author"):
        names = [e["author"]]
    return names


def parse_nber(e: Any, venue: str, src: str) -> Paper | None:
    title = strip_html(e.get("title", ""))
    authors: list[str] = []
    if " -- by " in title:
        title, by = title.split(" -- by ", 1)
        authors = split_authors(by)
    link = (e.get("link") or "").split("#")[0]
    ids = find_identifiers(link)
    num = ids.get("nber")
    if not num:
        return None
    return Paper(
        id=f"nber:{num}", kind="wp", source=src, venue=venue, title=title.strip(), authors=authors,
        abstract=strip_html(e.get("summary") or e.get("description") or ""), url=link,
        pdf_url=f"https://www.nber.org/system/files/working_papers/{num}/{num}.pdf",
        published=_entry_date(e),
    )


def parse_cepr(e: Any, venue: str, src: str) -> Paper | None:
    title = strip_html(e.get("title", ""))
    m = re.match(r"(DP\d+)\s+(.*)", title)
    dp = None
    if m:
        dp, title = m.group(1), m.group(2)
    link = e.get("link") or ""
    if not dp:
        m2 = re.search(r"/dp(\d+)", link, re.I)
        dp = f"DP{m2.group(1)}" if m2 else None
    if not dp:
        return None
    creators = _creators(e)
    authors = split_authors(creators[0]) if len(creators) == 1 else creators
    return Paper(
        id=f"cepr:{dp.lower()}", kind="wp", source=src, venue=venue, title=title.strip(), authors=authors,
        abstract=strip_html(e.get("summary") or e.get("description") or ""), url=link, published=_entry_date(e),
    )


def parse_nep(e: Any, venue: str, src: str) -> Paper | None:
    link = e.get("link") or ""
    ids = find_identifiers(link)
    handle = ids.get("repec_handle")
    title = strip_html(e.get("title", ""))
    if not handle or not title:
        return None
    authors = repec_authors(_creators(e))
    pid = f"repec:{handle}"
    # arXiv and NBER papers in NEP get their canonical ids so they merge with direct feeds
    if handle.startswith("RePEc:arx:papers:"):
        pid = f"arxiv:{handle.rsplit(':', 1)[-1]}"
    elif handle.startswith("RePEc:nbr:nberwo:"):
        pid = f"nber:w{handle.rsplit(':', 1)[-1]}"
    elif handle.startswith("RePEc:cpr:ceprdp:"):
        pid = f"cepr:dp{handle.rsplit(':', 1)[-1]}"
    elif handle.startswith("RePEc:iza:izadps:"):
        pid = f"iza:{handle.rsplit(':', 1)[-1].lower()}"
    ideas_url = "https://ideas.repec.org/cgi-bin/h.cgi?h=" + handle
    return Paper(
        id=pid, kind="wp", source=src, venue=venue, title=title, authors=authors,
        abstract=strip_html(e.get("summary") or e.get("description") or ""), repec_handle=handle,
        url=ideas_url, published=_entry_date(e),
    )


def parse_generic(e: Any, venue: str, src: str) -> Paper | None:
    title = strip_html(e.get("title", ""))
    link = e.get("link") or ""
    if not title:
        return None
    ids = find_identifiers(" ".join([link, e.get("id", ""), e.get("summary", "")]))
    doi = clean_doi(ids.get("doi"))
    pid = f"doi:{doi}" if doi else f"url:{link}"
    return Paper(
        id=pid, kind="wp", source=src, venue=venue, title=title, authors=_creators(e),
        abstract=strip_html(e.get("summary") or e.get("description") or ""), doi=doi, url=link,
        published=_entry_date(e),
    )


PARSERS = {"nber": parse_nber, "cepr": parse_cepr, "nep": parse_nep, "generic": parse_generic}


def fetch(entry: dict, cfg, since: date, known) -> list[Paper]:
    r = http.get(entry["url"])
    if r is None:
        return []
    feed = feedparser.parse(r.content)
    parser = PARSERS[entry.get("parser", "generic")]
    out: list[Paper] = []
    for e in feed.entries:
        try:
            p = parser(e, entry.get("venue", entry["id"]), entry["id"])
        except Exception:
            p = None
        if p is None:
            continue
        # NEP item dates are the paper's creation month, not the report date; rely on id dedup there
        if entry.get("parser") != "nep" and p.published and p.published < since:
            continue
        out.append(p)
    return out
