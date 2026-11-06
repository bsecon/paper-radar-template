"""Text helpers: normalisation, identifier extraction, abstract cleanup."""
from __future__ import annotations

import html
import re
import unicodedata

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>)\]]+)", re.I)
ARXIV_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arXiv:\s*)(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
NBER_RE = re.compile(r"nber\.org/(?:papers|system/files/working_papers)/(w\d+)", re.I)
REPEC_RE = re.compile(r"RePEc:[A-Za-z0-9]+:[A-Za-z0-9]+:[A-Za-z0-9_.\-]+")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
JEL_RE = re.compile(r"\b([A-Z]\d{2})\b")
TAG_RE = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    s = TAG_RE.sub(" ", s or "")
    s = html.unescape(s)
    return fix_mojibake(re.sub(r"\s+", " ", s).strip())


def title_key(title: str) -> str:
    """Normalised title used to match the same paper across sources and versions."""
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c))  # drop accents, keep every alphabet
    t = t.lower()
    t = re.sub(r"[^\w ]+", " ", t).replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    words = [w for w in t.split() if w not in {"the", "a", "an", "of", "and", "on", "in", "for", "to"}]
    return " ".join(words)[:200]


MIN_KEY_WORDS = 3


def matchable_key(title: str) -> str | None:
    """A title key safe to match papers on, or None when the title is too short to be distinctive."""
    tk = title_key(title)
    return tk if len(tk.split()) >= MIN_KEY_WORDS else None


def clean_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = doi.rstrip(".,;)")
    return doi.lower() or None


def find_identifiers(text: str) -> dict[str, str]:
    """Pull DOI / arXiv / NBER / RePEc identifiers and URLs out of free text."""
    out: dict[str, str] = {}
    if m := DOI_RE.search(text):
        out["doi"] = clean_doi(m.group(1)) or ""
    if m := ARXIV_RE.search(text):
        out["arxiv_id"] = m.group(1)
    if m := NBER_RE.search(text):
        out["nber"] = m.group(1).lower()
    if m := REPEC_RE.search(text):
        out["repec_handle"] = m.group(0)
    urls = URL_RE.findall(text)
    if urls:
        out["url"] = urls[0].rstrip(".,;)")
    return out


def inverted_index_to_text(idx: dict[str, list[int]] | None) -> str:
    """OpenAlex stores abstracts as {word: [positions]}."""
    if not idx:
        return ""
    positions: list[tuple[int, str]] = []
    for word, pos in idx.items():
        positions.extend((p, word) for p in pos)
    positions.sort()
    return " ".join(w for _, w in positions)


def split_authors(s: str) -> list[str]:
    """Split 'A, B and C' / 'A & B' / 'A; B' into a list of names."""
    s = strip_html(s)
    s = re.sub(r"\s+and\s+", ";", s)
    s = s.replace(" & ", ";").replace(",", ";") if s.count(";") == 0 and s.count(",") >= 1 and " & " not in s else s.replace(" & ", ";")
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p]


def repec_authors(names: list[str]) -> list[str]:
    """RePEc gives 'Last, First'; turn into 'First Last'."""
    out = []
    for n in names:
        if "," in n:
            last, first = n.split(",", 1)
            out.append(f"{first.strip()} {last.strip()}".strip())
        else:
            out.append(n.strip())
    return out


def short_authors(authors: list[str], max_n: int = 3) -> str:
    if not authors:
        return "unknown authors"
    if len(authors) <= max_n:
        return ", ".join(authors)
    return ", ".join(authors[:max_n]) + " et al."


def last_name(author: str) -> str:
    a = author.strip()
    if "," in a:
        return a.split(",")[0].strip()
    return a.split()[-1] if a else ""


def truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def fix_mojibake(s: str) -> str:
    """Repair UTF-8 text that was re-encoded as UTF-8 once more (IDEAS/RePEc does this)."""
    if not s or not any(marker in s for marker in ("Ã", "Â", "â€", "Ã¸", "Ã¦")):
        return s
    try:
        fixed = s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
    return fixed
