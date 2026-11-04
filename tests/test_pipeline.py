import json
from datetime import date
from pathlib import Path

from radar.config import load_config
from radar.db import DB
from radar.digest import render
from radar.feedback import parse_feedback
from radar.library import bib_entry, bib_key, update_bib
from radar.linking import link_published
from radar.models import Paper


def _cfg(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    cfg = load_config(root)
    cfg.root = tmp_path  # keep the test's db and outputs out of the repo
    (tmp_path / "config").mkdir()
    (tmp_path / "profile.md").write_text("profile", encoding="utf-8")
    return cfg


def test_upsert_dedups_by_title_within_kind_and_links_published(tmp_path):
    cfg = _cfg(tmp_path)
    db = DB(cfg.db_path)
    wp = Paper(id="nber:w1", kind="wp", source="nber", venue="NBER", title="Who Marries Whom and Why", authors=["A"], abstract="x")
    seq, ins = db.upsert_paper(wp)
    assert ins
    again = Paper(id="repec:RePEc:nbr:nberwo:1", kind="wp", source="nep-dem", venue="NEP", title="Who marries whom and why?", authors=["A"])
    seq2, ins2 = db.upsert_paper(again)
    assert (seq2, ins2) == (seq, False)
    pub = Paper(id="doi:10.1/x", kind="pub", source="journal:1", venue="JPE", title="Who Marries Whom and Why", authors=["A"], doi="10.1/x")
    seq3, ins3 = db.upsert_paper(pub)
    assert ins3 and seq3 != seq
    db.set_screen(seq, 9, "core", "core topic", ["sorting"])
    db.set_screen(seq3, 9, "core", "core topic", ["sorting"])
    assert link_published(db) == 1
    text, seqs = render(cfg, db, date(2026, 9, 11))
    assert "Now published" in text and f"R{seq}" in text
    assert set(seqs) == {seq, seq3}


def test_parse_feedback_lines():
    fb = parse_feedback("good: R12 R15\nbad R3 because too theoretical\nmissed: https://arxiv.org/abs/2608.17446 great paper\nrandom text")
    assert fb[0] == ("good", ["R12", "R15"], "")
    assert fb[1] == ("bad", ["R3"], "too theoretical")
    assert fb[2][0] == "missed" and fb[2][1] == ["https://arxiv.org/abs/2608.17446"] and fb[2][2] == "great paper"


def test_bib(tmp_path):
    cfg = _cfg(tmp_path)
    db = DB(cfg.db_path)
    seq, _ = db.upsert_paper(Paper(id="doi:10.1/y", kind="pub", source="j", venue="Econometrica", title="Assortative Matching and Search",
                                   authors=["Robert Shimer", "Lones Smith"], doi="10.1/y", published=date(2000, 3, 1)))
    db.set_screen(seq, 10, "core", "r", [])
    row = db.get(seq)
    key = bib_key(row, set())
    assert key == "shimer2000assortative"
    assert "journal = {Econometrica}" in bib_entry(row, key)
    assert update_bib(cfg, db) == 1
    assert update_bib(cfg, db) == 0
    assert "@article{shimer2000assortative" in cfg.bib_path.read_text()


def test_parse_feedback_from_email_reply():
    body = """good: *R1495*
*missed: have you seen this paper: *
https://www.rwi-essen.de/fileadmin/user_upload/RWI/Publikationen/Ruhr_Economic_Papers/REP_26_1228.pdf

Am Fr., 30. Okt. 2026 um 13:02 Uhr schrieb github-actions[bot] <
***@***.***>:

> good: R999
"""
    fb = parse_feedback(body)
    assert fb[0] == ("good", ["R1495"], "")
    assert fb[1][0] == "missed"
    assert fb[1][1] == ["https://www.rwi-essen.de/fileadmin/user_upload/RWI/Publikationen/Ruhr_Economic_Papers/REP_26_1228.pdf"]
    assert fb[1][2] == "have you seen this paper"
    assert len(fb) == 2  # the quoted R999 is ignored


def test_stored_token_falls_back_to_file(tmp_path, monkeypatch):
    from radar import llm
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(llm, "IS_MAC", False)
    assert llm.stored_token() is None
    f = llm.token_file(); f.parent.mkdir(parents=True); f.write_text("sk-ant-oat-test\n")
    assert llm.stored_token() == "sk-ant-oat-test"


def test_always_show_is_parsed_and_matched():
    from radar.screen import always_show_match, always_show_names
    profile = "## Core\n- x\n\n## Always show\n\nPapers by or with: Pierre-André Chiappori, Rune Vejlin,\nLones Smith and Robert Shimer.\n\n## My own papers\n- y\n"
    names = always_show_names(profile)
    assert names == ["Pierre-André Chiappori", "Rune Vejlin", "Lones Smith", "Robert Shimer"]
    assert always_show_match(names, ["Jesper Bagger", "Vejlin, Rune"]) == "Vejlin, Rune"
    assert always_show_match(names, ["P. A. Chiappori"]) == "P. A. Chiappori"
    assert always_show_match(names, ["Adam Smith"]) is None
    assert always_show_names("## Always show\n\n<!-- Papers by or with: Jane Doe -->\n") == []
