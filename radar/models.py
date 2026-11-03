"""Data models shared across the pipeline."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["wp", "pub", "unknown"]


class Paper(BaseModel):
    """A paper as seen by one source. Stored in the `papers` table."""

    id: str                      # canonical id: doi:..., arxiv:..., repec:..., url:...
    kind: Kind = "unknown"
    source: str                  # source id from sources.yml, or "manual"
    venue: str = ""              # series or journal name
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    doi: str | None = None
    arxiv_id: str | None = None
    repec_handle: str | None = None
    url: str = ""
    pdf_url: str | None = None
    published: date | None = None
    jel: list[str] = Field(default_factory=list)
    manual: bool = False
    missed: bool = False
    note: str = ""               # free text from intake (e.g. why you sent it)


class ScreenResult(BaseModel):
    """Structured output of the screening call."""

    score: int = Field(ge=0, le=10, description="Relevance to the research profile, 0-10")
    category: Literal["core", "adjacent", "methods", "skip"]
    reason: str = Field(description="One sentence, at most 30 words, on why this score")
    topics: list[str] = Field(description="Two to five short topic tags")


class DeepRead(BaseModel):
    """Structured output of the full-paper read."""

    question: str = Field(description="The research question in one sentence")
    data: str = Field(description="Data and setting in one sentence")
    method: str = Field(description="Empirical or theoretical approach in one or two sentences")
    finding: str = Field(description="Main result in one or two sentences, with magnitudes if given")
    relation: str = Field(description="How it relates to my own work, one or two sentences")
    verdict: str = Field(description="One line: why read it, or why it can wait")
