"""Source fetchers. Each exposes fetch(cfg_entry, cfg, since) -> list[Paper]."""
from __future__ import annotations

from datetime import date
from typing import Callable

from radar.models import Paper
from radar.sources import arxiv, crossref, ideas, openalex, rss

FETCHERS: dict[str, Callable] = {
    "rss": rss.fetch,
    "arxiv": arxiv.fetch,
    "ideas_series": ideas.fetch,
    "openalex_search": openalex.fetch_search,
}


def fetch_working_papers(entry: dict, cfg, since: date, known) -> list[Paper]:
    fn = FETCHERS[entry["type"]]
    return fn(entry, cfg, since, known)


def fetch_journal(entry: dict, cfg, since: date) -> list[Paper]:
    return crossref.fetch_journal(entry, cfg, since)


__all__ = ["fetch_working_papers", "fetch_journal", "Paper"]
