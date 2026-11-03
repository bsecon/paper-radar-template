"""Turn a URL, DOI, arXiv id, or free text into a Paper record."""
from __future__ import annotations

import re

from radar import http
from radar.models import Paper
from radar.sources import arxiv, crossref, openalex
from radar.sources.ideas import paper_from_ideas
from radar.text import clean_doi, find_identifiers, strip_html

IDEAS_PATTERNS = [
    # (regex on the url/text, IDEAS path template, canonical id template)
    (re.compile(r"nber\.org/(?:papers|system/files/working_papers)/w(\d+)", re.I), "/p/nbr/nberwo/{0}.html", "nber:w{0}"),
    (re.compile(r"(?:docs\.iza\.org/dp|iza\.org/(?:en/)?publications/dp/)(\d+)", re.I), "/p/iza/izadps/dp{0}.html", "iza:dp{0}"),
    (re.compile(r"cepr\.org/publications/dp(\d+)", re.I), "/p/cpr/ceprdp/{0}.html", "cepr:dp{0}"),
    (re.compile(r"ideas\.repec\.org(/p/[a-z]+/[a-z]+/[A-Za-z0-9_.\-]+\.html)", re.I), "{0}", None),
    (re.compile(r"econpapers\.repec\.org/paper/([a-z]+)([a-z]+)/([A-Za-z0-9_.\-]+)\.htm", re.I), "/p/{0}/{1}/{2}.html", None),
]

META_RE = re.compile(r'<meta\s+(?:name|property)="([^"]+)"\s+content="([^"]*)"', re.I)
META_RE2 = re.compile(r'<meta\s+content="([^"]*)"\s+(?:name|property)="([^"]+)"', re.I)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def _page_meta(url: str) -> dict[str, list[str]]:
    try:
        r = http.get(url, retries=1)
    except Exception:
        return {}
    if r is None or "html" not in r.headers.get("content-type", ""):
        return {}
    meta: dict[str, list[str]] = {}
    for k, v in META_RE.findall(r.text):
        meta.setdefault(k.lower(), []).append(strip_html(v))
    for v, k in META_RE2.findall(r.text):
        meta.setdefault(k.lower(), []).append(strip_html(v))
    m = TITLE_RE.search(r.text)
    if m:
        meta.setdefault("page_title", []).append(strip_html(m.group(1)))
    return meta


def _from_meta(url: str, meta: dict[str, list[str]]) -> Paper | None:
    title = (meta.get("citation_title") or meta.get("dc.title") or meta.get("og:title") or [None])[0]
    if not title:
        return None
    authors = meta.get("citation_author") or []
    if not authors and meta.get("citation_authors"):
        authors = [a.strip() for a in meta["citation_authors"][0].split(";") if a.strip()]
    doi = clean_doi((meta.get("citation_doi") or [None])[0])
    abstract = (meta.get("citation_abstract") or meta.get("dc.description") or meta.get("description") or meta.get("og:description") or [""])[0]
    pdf = (meta.get("citation_pdf_url") or [None])[0]
    venue = (meta.get("citation_journal_title") or meta.get("citation_publisher") or [""])[0]
    pid = f"doi:{doi}" if doi else f"url:{url}"
    return Paper(id=pid, kind="unknown", source="manual", venue=venue, title=title, authors=authors,
                 abstract=abstract, doi=doi, url=url, pdf_url=pdf)


def _from_pdf(url: str, mailto: str) -> Paper | None:
    """A bare PDF link (working paper series without a landing page): read the first page for the title."""
    import io

    data = http.get_bytes(url, 40_000_000)
    if not data:
        return None
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        meta_title = (reader.metadata.title or "").strip() if reader.metadata else ""
        pages = [(reader.pages[i].extract_text() or "") for i in range(min(3, len(reader.pages)))]
    except Exception:
        return None
    first = [ln.strip() for ln in pages[0].splitlines() if ln.strip()] if pages else []
    title_lines: list[str] = []
    banner: list[str] = []
    authors_line = ""
    for ln in first[:8]:
        looks_like_authors = bool(re.search(r"\band\b|,", ln)) and len(ln.split()) <= 14 and ln[:1].isupper() and title_lines
        if looks_like_authors:
            authors_line = ln
            break
        if ln.isupper() and len(ln) > 3:
            banner.append(ln.title())  # series banner, e.g. RUHR ECONOMIC PAPERS
            continue
        title_lines.append(ln)
        if len(" ".join(title_lines)) > 160:
            break
    title = meta_title if 10 < len(meta_title) < 300 and not meta_title.lower().endswith(".pdf") else " ".join(title_lines).strip()
    if not title:
        return None
    oa = openalex.search_title(title, mailto)
    if oa:
        oa.pdf_url = oa.pdf_url or url
        oa.url = oa.url or url
        return oa
    text = "\n".join(pages)
    m = re.search(r"abstract\s*[:.]?\s*(.{200,2500}?)(?:\n\s*(?:keywords|jel)\b|\Z)", text, re.I | re.S)
    abstract = strip_html(m.group(1)) if m else ""
    authors = [a.strip() for a in re.split(r",|\band\b", authors_line) if a.strip()] if authors_line else []
    venue = " ".join(banner)[:80]
    return Paper(id=f"url:{url}", kind="wp", source="manual", venue=venue, title=title, authors=authors,
                 abstract=abstract, url=url, pdf_url=url)


def resolve(text: str, mailto: str) -> tuple[Paper | None, str]:
    """Return (paper, how). `how` describes the path taken, for the intake comment."""
    ids = find_identifiers(text)
    if ids.get("doi"):
        p = crossref.by_doi(ids["doi"])
        if p:
            openalex.enrich_by_doi([p], mailto)
            if p.kind == "unknown":
                oa = openalex.search_title(p.title, mailto)
                if oa and oa.kind != "unknown":
                    p.kind = oa.kind
                    p.pdf_url = p.pdf_url or oa.pdf_url
            return p, "doi via Crossref"
    if ids.get("arxiv_id"):
        p = arxiv.by_id(ids["arxiv_id"])
        if p:
            return p, "arXiv id"
    if ids.get("nber"):
        # NBER blocks scripted page access; its DOI (10.3386/wNNNN) and the IDEAS mirror do not
        num = ids["nber"]
        p = crossref.by_doi(f"10.3386/{num}")
        via = "NBER DOI via Crossref"
        mirror = paper_from_ideas(f"/p/nbr/nberwo/{num[1:]}.html")
        if p is None and mirror is not None:
            p, via = mirror, "IDEAS mirror"
        if p is not None:
            if mirror is not None:
                p.abstract = p.abstract or mirror.abstract
                p.jel = p.jel or mirror.jel
                p.authors = p.authors or mirror.authors
            p.id, p.kind, p.venue = f"nber:{num}", "wp", "NBER"
            p.url = f"https://www.nber.org/papers/{num}"
            p.pdf_url = f"https://www.nber.org/system/files/working_papers/{num}/{num}.pdf"
            return p, via
    for pat, path_t, id_t in IDEAS_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        p = paper_from_ideas(path_t.format(*m.groups()))
        if p is not None:
            if id_t:
                p.id = id_t.format(*m.groups())
            return p, "IDEAS/RePEc page"
    url = ids.get("url")
    if url and url.lower().split("?")[0].endswith(".pdf"):
        p = _from_pdf(url, mailto)
        if p:
            return p, "PDF first page" + (" + OpenAlex" if not p.id.startswith("url:") else "")
    if url:
        meta = _page_meta(url)
        p = _from_meta(url, meta)
        if p and p.doi:
            cr = crossref.by_doi(p.doi)
            if cr:
                cr.url, cr.pdf_url, cr.abstract = cr.url or url, cr.pdf_url or p.pdf_url, cr.abstract or p.abstract
                openalex.enrich_by_doi([cr], mailto)
                return cr, "page metadata + Crossref"
        if p:
            oa = openalex.search_title(p.title, mailto)
            if oa:
                oa.url = oa.url or url
                oa.abstract = oa.abstract or p.abstract
                oa.pdf_url = oa.pdf_url or p.pdf_url
                oa.note = ""
                return oa, "page metadata + OpenAlex"
            return p, "page metadata"
        # LinkedIn and friends: no metadata. Try the page title, then the raw text.
        guess = (meta.get("page_title") or [""])[0]
        for cand in [guess, text]:
            cand = cand.strip()
            if len(cand) < 12:
                continue
            oa = openalex.search_title(cand[:300], mailto)
            if oa:
                oa.url = oa.url or url
                return oa, "OpenAlex title search"
        return None, "unresolved url"
    # plain text: maybe a pasted title
    if len(text.strip()) >= 12:
        oa = openalex.search_title(text.strip()[:300], mailto)
        if oa:
            return oa, "OpenAlex title search"
    return None, "nothing recognisable"
