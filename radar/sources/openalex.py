"""OpenAlex: abstracts and open-access PDF links, plus title search for the resolver."""
from __future__ import annotations

from typing import Any, Iterable

from radar import http
from radar.models import Paper
from radar.text import clean_doi, inverted_index_to_text

API = "https://api.openalex.org"


def _pdf_url(w: dict[str, Any]) -> str | None:
    for loc in [w.get("best_oa_location"), w.get("primary_location"), *(w.get("locations") or [])]:
        if loc and loc.get("pdf_url"):
            return loc["pdf_url"]
    return None


def enrich_by_doi(papers: Iterable[Paper], mailto: str) -> int:
    """Fill missing abstracts / pdf urls for papers with a DOI. Returns count enriched."""
    todo = {p.doi: p for p in papers if p.doi and (not p.abstract or not p.pdf_url)}
    if not todo:
        return 0
    dois = list(todo)
    n = 0
    for i in range(0, len(dois), 40):
        chunk = dois[i : i + 40]
        flt = "doi:" + "|".join(f"https://doi.org/{d}" for d in chunk)
        r = http.get(f"{API}/works", params={"filter": flt, "per-page": 50, "mailto": mailto,
                                              "select": "doi,abstract_inverted_index,best_oa_location,primary_location,locations"})
        if r is None:
            continue
        for w in r.json().get("results") or []:
            d = clean_doi(w.get("doi"))
            p = todo.get(d or "")
            if not p:
                continue
            if not p.abstract:
                p.abstract = inverted_index_to_text(w.get("abstract_inverted_index"))
            if not p.pdf_url:
                p.pdf_url = _pdf_url(w)
            n += 1
    return n


def work_to_paper(w: dict[str, Any], src: str = "manual") -> Paper:
    doi = clean_doi(w.get("doi"))
    ids = w.get("ids") or {}
    loc = w.get("primary_location") or {}
    source = loc.get("source") or {}
    venue = source.get("display_name") or ""
    stype = source.get("type") or ""
    kind = "pub" if w.get("type") == "article" and stype == "journal" else ("wp" if "working" in venue.lower() or stype == "repository" else "unknown")
    arxiv_id = None
    if loc.get("landing_page_url") and "arxiv.org" in loc["landing_page_url"]:
        arxiv_id = loc["landing_page_url"].rsplit("/", 1)[-1]
        kind = "wp"
    pid = f"doi:{doi}" if doi else (f"arxiv:{arxiv_id}" if arxiv_id else f"openalex:{w.get('id','').rsplit('/',1)[-1]}")
    authors = [a.get("author", {}).get("display_name") for a in w.get("authorships") or []]
    pub = None
    if w.get("publication_date"):
        from datetime import date
        try:
            pub = date.fromisoformat(w["publication_date"])
        except Exception:
            pub = None
    return Paper(
        id=pid, kind=kind, source=src, venue=venue, title=w.get("title") or w.get("display_name") or "",
        authors=[a for a in authors if a], abstract=inverted_index_to_text(w.get("abstract_inverted_index")),
        doi=doi, arxiv_id=arxiv_id, url=loc.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else ""),
        pdf_url=_pdf_url(w), published=pub,
    )


def search_title(title: str, mailto: str) -> Paper | None:
    r = http.get(f"{API}/works", params={"search": title, "per-page": 3, "mailto": mailto})
    if r is None:
        return None
    from radar.text import title_key
    want = title_key(title)
    for w in r.json().get("results") or []:
        if title_key(w.get("title") or "") == want:
            return work_to_paper(w)
    results = r.json().get("results") or []
    # accept the top hit only if the titles are near-identical in both directions
    if results:
        top = results[0]
        a, b = set(want.split()), set(title_key(top.get("title") or "").split())
        if a and b and len(a & b) / len(a) >= 0.9 and len(a & b) / len(b) >= 0.9:
            return work_to_paper(top)
    return None


def fetch_search(entry: dict, cfg, since, known) -> list[Paper]:
    """Keyword catch-all: recent works matching each phrase, any venue OpenAlex indexes.

    OpenAlex's "created" filter is paid, so this uses publication date with a wide window and
    relies on id-based dedup; a phrase hit that is already in the database is skipped.
    """
    from datetime import timedelta

    window_start = (since - timedelta(days=int(entry.get("window_days", 30)))).isoformat()
    fields = entry.get("fields", "20|33")  # 20 = Economics, Econometrics and Finance; 33 = Social Sciences
    out: list[Paper] = []
    seen: set[str] = set()
    for phrase in entry.get("phrases") or []:
        r = http.get(f"{API}/works", params={
            "search": f'"{phrase}"' if " " in phrase and not phrase.startswith('"') else phrase,
            "filter": f"from_publication_date:{window_start},topics.field.id:{fields},type:article|preprint|report",
            "per-page": int(entry.get("per_phrase", 50)), "sort": "publication_date:desc", "mailto": cfg.contact_email,
        })
        if r is None:
            continue
        for w in r.json().get("results") or []:
            p = work_to_paper(w, src=entry["id"])
            if not p.title or p.id in seen or known(p.id):
                continue
            seen.add(p.id)
            p.venue = p.venue or "OpenAlex"
            out.append(p)
    return out
