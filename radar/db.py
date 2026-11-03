"""SQLite storage. One file, committed to the repo so the cloud job keeps state."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from radar.models import Paper
from radar.text import title_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    venue TEXT,
    title TEXT NOT NULL,
    title_key TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT '[]',
    abstract TEXT NOT NULL DEFAULT '',
    doi TEXT,
    arxiv_id TEXT,
    repec_handle TEXT,
    url TEXT,
    pdf_url TEXT,
    published TEXT,
    jel TEXT NOT NULL DEFAULT '[]',
    manual INTEGER NOT NULL DEFAULT 0,
    missed INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    score INTEGER,
    category TEXT,
    reason TEXT,
    topics TEXT,
    screened_at TEXT,
    deep_read TEXT,
    digested_on TEXT,
    published_match INTEGER,
    bib_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_papers_title_key ON papers(title_key);
CREATE INDEX IF NOT EXISTS idx_papers_kind ON papers(kind);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);

CREATE TABLE IF NOT EXISTS aliases (
    paper_seq INTEGER NOT NULL,
    source TEXT NOT NULL,
    ext_id TEXT NOT NULL,
    seen TEXT NOT NULL,
    UNIQUE(source, ext_id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_seq INTEGER NOT NULL,
    label TEXT NOT NULL,          -- good | bad | missed
    note TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'cli',
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT NOT NULL,
    step TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---- state -----------------------------------------------------------
    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def log_run(self, step: str, detail: str = "") -> None:
        with self.tx() as c:
            c.execute("INSERT INTO runs(started, step, detail) VALUES(?,?,?)", (now_iso(), step, detail))

    # ---- papers ----------------------------------------------------------
    def find_by_title(self, title: str, kind: str | None = None) -> sqlite3.Row | None:
        tk = title_key(title)
        if not tk:
            return None
        if kind:
            return self.conn.execute("SELECT * FROM papers WHERE title_key=? AND kind=?", (tk, kind)).fetchone()
        return self.conn.execute("SELECT * FROM papers WHERE title_key=?", (tk,)).fetchone()

    def find_by_id(self, pid: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()

    def get(self, seq: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM papers WHERE seq=?", (seq,)).fetchone()

    def resolve_ref(self, ref: str) -> sqlite3.Row | None:
        """Accept 'R12', '12', a DOI, an arXiv id, or a paper id."""
        r = ref.strip().lstrip("#")
        if r.upper().startswith("R") and r[1:].isdigit():
            return self.get(int(r[1:]))
        if r.isdigit():
            return self.get(int(r))
        row = self.find_by_id(r)
        if row:
            return row
        return self.conn.execute(
            "SELECT * FROM papers WHERE doi=? OR arxiv_id=? OR url=? LIMIT 1", (r.lower(), r, r)
        ).fetchone()

    def upsert_paper(self, p: Paper) -> tuple[int, bool]:
        """Insert a paper unless an equivalent one exists.

        Returns (seq, inserted). Equivalence: same id, or same normalised title
        with the same kind (a working paper and its journal version stay separate
        rows so we can report "now published").
        """
        existing = self.find_by_id(p.id)
        if existing is None:
            existing = self.find_by_title(p.title, kind=p.kind if p.kind != "unknown" else None)
        with self.tx() as c:
            if existing is not None:
                seq = int(existing["seq"])
                # fill gaps from the new sighting
                updates: dict[str, Any] = {}
                if not existing["abstract"] and p.abstract:
                    updates["abstract"] = p.abstract
                if not existing["pdf_url"] and p.pdf_url:
                    updates["pdf_url"] = p.pdf_url
                if not existing["doi"] and p.doi:
                    updates["doi"] = p.doi
                if existing["jel"] == "[]" and p.jel:
                    updates["jel"] = json.dumps(p.jel)
                if p.manual and not existing["manual"]:
                    updates["manual"] = 1
                if p.missed and not existing["missed"]:
                    updates["missed"] = 1
                if p.note and not existing["note"]:
                    updates["note"] = p.note
                if updates:
                    sets = ", ".join(f"{k}=?" for k in updates)
                    c.execute(f"UPDATE papers SET {sets} WHERE seq=?", (*updates.values(), seq))
                c.execute(
                    "INSERT OR IGNORE INTO aliases(paper_seq, source, ext_id, seen) VALUES(?,?,?,?)",
                    (seq, p.source, p.id, now_iso()),
                )
                return seq, False
            cur = c.execute(
                """INSERT INTO papers(id, kind, source, venue, title, title_key, authors, abstract, doi,
                   arxiv_id, repec_handle, url, pdf_url, published, jel, manual, missed, note, first_seen)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    p.id, p.kind, p.source, p.venue, p.title, title_key(p.title), json.dumps(p.authors),
                    p.abstract, p.doi, p.arxiv_id, p.repec_handle, p.url, p.pdf_url,
                    p.published.isoformat() if p.published else None, json.dumps(p.jel),
                    int(p.manual), int(p.missed), p.note, now_iso(),
                ),
            )
            return int(cur.lastrowid), True

    def unscreened(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM papers WHERE screened_at IS NULL AND manual=0 ORDER BY seq"
        ).fetchall()

    def set_screen(self, seq: int, score: int, category: str, reason: str, topics: list[str]) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE papers SET score=?, category=?, reason=?, topics=?, screened_at=? WHERE seq=?",
                (score, category, reason, json.dumps(topics), now_iso(), seq),
            )

    def set_deep_read(self, seq: int, data: dict[str, Any]) -> None:
        with self.tx() as c:
            c.execute("UPDATE papers SET deep_read=? WHERE seq=?", (json.dumps(data), seq))

    def set_fields(self, seq: int, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE papers SET {sets} WHERE seq=?", (*fields.values(), seq))

    def undigested(self) -> list[sqlite3.Row]:
        """Everything screened (or manual) that has not been in a digest yet."""
        return self.conn.execute(
            "SELECT * FROM papers WHERE digested_on IS NULL AND (screened_at IS NOT NULL OR manual=1) ORDER BY score DESC, seq"
        ).fetchall()

    def mark_digested(self, seqs: list[int], day: date) -> None:
        if not seqs:
            return
        with self.tx() as c:
            c.executemany("UPDATE papers SET digested_on=? WHERE seq=?", [(day.isoformat(), s) for s in seqs])

    def working_papers_matching(self, title: str) -> list[sqlite3.Row]:
        tk = title_key(title)
        return self.conn.execute("SELECT * FROM papers WHERE title_key=? AND kind='wp'", (tk,)).fetchall()

    # ---- feedback --------------------------------------------------------
    def add_feedback(self, seq: int, label: str, note: str = "", origin: str = "cli") -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO feedback(paper_seq, label, note, origin, created) VALUES(?,?,?,?,?)",
                (seq, label, note, origin, now_iso()),
            )

    def feedback_examples(self, label: str, limit: int = 8) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT p.*, f.note AS fb_note, f.created AS fb_created FROM feedback f
               JOIN papers p ON p.seq=f.paper_seq WHERE f.label=? ORDER BY f.created DESC LIMIT ?""",
            (label, limit),
        ).fetchall()

    def all_feedback(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT p.seq, p.title, p.venue, p.score, p.reason, p.abstract, f.label, f.note, f.created
               FROM feedback f JOIN papers p ON p.seq=f.paper_seq ORDER BY f.created"""
        ).fetchall()

    # ---- search ----------------------------------------------------------
    def search(self, q: str, limit: int = 20) -> list[sqlite3.Row]:
        like = f"%{q}%"
        return self.conn.execute(
            """SELECT * FROM papers WHERE title LIKE ? OR abstract LIKE ? OR authors LIKE ? OR deep_read LIKE ?
               ORDER BY COALESCE(score, -1) DESC, seq DESC LIMIT ?""",
            (like, like, like, like, limit),
        ).fetchall()

    def kept(self) -> list[sqlite3.Row]:
        """Papers worth keeping in the library: sent by you, rated good, or above threshold."""
        return self.conn.execute(
            """SELECT p.* FROM papers p WHERE p.manual=1 OR p.score >= (SELECT CAST(value AS INTEGER) FROM state WHERE key='show_threshold')
               OR p.seq IN (SELECT paper_seq FROM feedback WHERE label IN ('good','missed'))
               ORDER BY p.seq"""
        ).fetchall()


def row_authors(row: Any) -> list[str]:
    try:
        return json.loads(row["authors"] or "[]")
    except Exception:
        return []


def row_json(row: Any, col: str) -> Any:
    try:
        return json.loads(row[col]) if row[col] else None
    except Exception:
        return None
