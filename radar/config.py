"""Repository paths, sources config, and settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def find_root() -> Path:
    env = os.environ.get("RADAR_ROOT")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for p in [here, *here.parents]:
        if (p / "config" / "sources.yml").exists():
            return p
    # fall back to the package's parent (editable install)
    return Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    lookback_days: int = 7
    show_threshold: int = 6
    deep_read_threshold: int = 8
    max_deep_reads: int = 5
    backend: str = "claude_code"          # claude_code (subscription) | api (ANTHROPIC_API_KEY)
    claude_bin: str | None = None         # path to the Claude Code executable; auto-detected if unset
    llm_timeout: int = 300                # seconds per call (a screening call takes ~15 s)
    screen_model: str = "claude-sonnet-5"
    screen_effort: str | None = "low"
    screen_group_size: int = 12           # papers per screening call
    deep_read_model: str = "claude-opus-5"
    deep_read_effort: str | None = None
    review_model: str = "claude-opus-5"
    digest_label: str = "digest"
    paper_label: str = "paper"
    timezone: str = "Europe/Copenhagen"


@dataclass
class Config:
    root: Path
    contact_email: str
    settings: Settings
    working_papers: list[dict[str, Any]] = field(default_factory=list)
    journals: list[dict[str, Any]] = field(default_factory=list)

    @property
    def db_path(self) -> Path:
        return self.root / "data" / "radar.sqlite"

    @property
    def profile_path(self) -> Path:
        return self.root / "profile.md"

    @property
    def digests_dir(self) -> Path:
        return self.root / "digests"

    @property
    def bib_path(self) -> Path:
        return self.root / "library" / "radar.bib"

    @property
    def pdf_dir(self) -> Path:
        env = os.environ.get("RADAR_LIBRARY_DIR")
        return Path(env).expanduser() if env else self.root / "library" / "pdfs"

    @property
    def user_agent(self) -> str:
        return f"paper-radar/0.1 (mailto:{self.contact_email})"

    def profile_text(self) -> str:
        return self.profile_path.read_text(encoding="utf-8")


def load_config(root: Path | None = None) -> Config:
    root = root or find_root()
    raw = yaml.safe_load((root / "config" / "sources.yml").read_text(encoding="utf-8")) or {}
    settings = Settings(**(raw.get("settings") or {}))
    return Config(
        root=root,
        contact_email=raw.get("contact_email", "paper-radar@example.org"),
        settings=settings,
        working_papers=raw.get("working_papers") or [],
        journals=raw.get("journals") or [],
    )
