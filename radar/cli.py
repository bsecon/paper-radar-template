"""Command line: radar <command>."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from radar.config import load_config
from radar.db import DB, row_authors
from radar.text import short_authors


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str) if not isinstance(obj, str) else obj)


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252; titles are not
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="radar", description="Daily radar for new economics papers.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fetch", help="poll all sources and store new papers")
    sub.add_parser("intake", help="process GitHub issues (papers sent in) and digest comments (ratings)")
    p = sub.add_parser("screen", help="score unscreened papers with Claude")
    p.add_argument("--limit", type=int, default=None, help="only this many papers (for testing)")
    p = sub.add_parser("deepread", help="full reads for the top papers and papers you sent in")
    p.add_argument("--limit", type=int, default=None)
    sub.add_parser("doctor", help="check the Claude binary, GitHub access, and sources config")
    p = sub.add_parser("digest", help="write today's digest (and post it as an issue)")
    p.add_argument("--no-issue", action="store_true")
    p.add_argument("--date", default=None)
    p = sub.add_parser("run", help="the whole daily pipeline")
    p.add_argument("--no-issue", action="store_true")
    p.add_argument("--if-pending", action="store_true", help="only run if an earlier run left work undone (retry slot)")

    p = sub.add_parser("add", help="send a paper in: URL, DOI, arXiv id, or a title")
    p.add_argument("text", nargs="+")
    p.add_argument("--missed", action="store_true", help="the radar should have shown this one")
    p = sub.add_parser("rate", help="rate papers: radar rate good R12 R15 [--note ...]")
    p.add_argument("label", choices=["good", "bad", "missed"])
    p.add_argument("refs", nargs="+")
    p.add_argument("--note", default="")
    p = sub.add_parser("search", help="search stored papers")
    p.add_argument("query", nargs="+")
    p = sub.add_parser("show", help="show one paper: radar show R12")
    p.add_argument("ref")
    p = sub.add_parser("library", help="library maintenance")
    p.add_argument("action", choices=["sync", "bib", "index"])
    p.add_argument("--limit", type=int, default=None)
    p = sub.add_parser("review", help="propose profile edits from your ratings (weekly)")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-issue", action="store_true")
    sub.add_parser("eval", help="re-screen rated papers and report hits and misses")
    sub.add_parser("stats", help="counts")

    a = ap.parse_args(argv)
    cfg = load_config()
    db = DB(cfg.db_path)
    db.set_state("show_threshold", str(cfg.settings.show_threshold))
    try:
        dispatch(a, cfg, db)
    finally:
        db.close()


def dispatch(a, cfg, db) -> None:
    from radar import pipeline

    if a.cmd == "fetch":
        _print(pipeline.fetch(cfg, db))
    elif a.cmd == "intake":
        from radar import intake
        from radar.github import GitHub
        gh = GitHub()
        _print({"issues": intake.process_issues(cfg, db, gh), "ratings": intake.process_ratings(cfg, db, gh)})
    elif a.cmd == "screen":
        from radar import screen
        _print(screen.screen(cfg, db, limit=a.limit))
    elif a.cmd == "deepread":
        from radar import deepread
        _print(deepread.deep_read(cfg, db, limit=a.limit))
    elif a.cmd == "doctor":
        _print(doctor(cfg, db))
    elif a.cmd == "digest":
        from radar import digest
        day = date.fromisoformat(a.date) if a.date else pipeline.today(cfg)
        _print(digest.publish(cfg, db, day, post_issue=not a.no_issue))
    elif a.cmd == "run":
        if a.if_pending and not pipeline.pending_work(db):
            print("nothing pending; skipping retry run")
            return
        _print(pipeline.run(cfg, db, post_issue=not a.no_issue))
    elif a.cmd == "add":
        from radar import http, intake
        http.configure(cfg.user_agent)
        seq, inserted, how, paper = intake.add_paper(cfg, db, " ".join(a.text), missed=a.missed)
        if seq is None:
            print(f"could not resolve ({how})")
            sys.exit(1)
        row = db.get(seq)
        print(f"R{seq} {'added' if inserted else 'already known'} ({how}): {row['title']} · {short_authors(row_authors(row))} · {row['venue']}")
    elif a.cmd == "rate":
        from radar.feedback import apply_ratings
        done = apply_ratings(db, a.label, a.refs, a.note, origin="cli")
        print(f"recorded {a.label}: {', '.join(done) or 'nothing matched'}")
    elif a.cmd == "search":
        for r in db.search(" ".join(a.query)):
            print(f"R{r['seq']:<6} {r['score'] if r['score'] is not None else '-':>2}  {r['title'][:90]}  · {r['venue']}")
    elif a.cmd == "show":
        r = db.resolve_ref(a.ref)
        if not r:
            print("not found")
            sys.exit(1)
        d = dict(r)
        d["authors"] = row_authors(r)
        _print(d)
    elif a.cmd == "library":
        from radar import http, library
        http.configure(cfg.user_agent)
        if a.action == "sync":
            got, skipped = library.sync_pdfs(cfg, db, limit=a.limit)
            print(f"downloaded {got}, skipped {skipped} (no pdf url or download failed) into {cfg.pdf_dir}")
        elif a.action == "bib":
            print(f"added {library.update_bib(cfg, db)} entries to {cfg.bib_path}")
        else:
            print(library.write_index(cfg, db))
    elif a.cmd == "review":
        from radar import review
        _print(review.review(cfg, db, apply=a.apply, post_issue=not a.no_issue))
    elif a.cmd == "eval":
        from radar import review
        _print(review.evaluate(cfg, db))
    elif a.cmd == "stats":
        from radar.feedback import stats
        n = db.conn.execute("SELECT kind, COUNT(*) FROM papers GROUP BY kind").fetchall()
        _print({"papers": {k: v for k, v in n}, **stats(db), "pending_batch": db.get_state("pending_batch") or None})


def doctor(cfg, db) -> dict:
    import shutil
    from radar import llm
    out: dict = {"root": str(cfg.root), "backend": cfg.settings.backend}
    try:
        out["claude_bin"] = llm.claude_bin(cfg)
    except Exception as e:
        out["claude_bin"] = f"MISSING: {e}"
    out["gh"] = shutil.which("gh") or "MISSING (needed for issues/digests)"
    try:
        from radar.github import GitHub
        gh = GitHub()
        out["github_repo"] = gh.repo
    except Exception as e:
        out["github_repo"] = f"MISSING: {e}"
    out["sources"] = {"working_papers": len(cfg.working_papers), "journals": len(cfg.journals)}
    out["papers_in_db"] = db.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    out["unscreened"] = len(db.unscreened())
    return out


if __name__ == "__main__":
    main()
