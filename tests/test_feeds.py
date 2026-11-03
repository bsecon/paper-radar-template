from pathlib import Path

import feedparser

from radar.sources.rss import parse_cepr, parse_nber, parse_nep

FIX = Path(__file__).parent / "fixtures"


def test_parse_nber():
    feed = feedparser.parse((FIX / "nber.xml").read_text())
    p = parse_nber(feed.entries[0], "NBER", "nber")
    assert p.id == "nber:w35670"
    assert p.title == "Air Pollution and Learning"
    assert p.authors[0] == "A. Patrick Behrer"
    assert p.pdf_url.endswith("w35670.pdf")


def test_parse_cepr():
    feed = feedparser.parse((FIX / "cepr.xml").read_text())
    p = parse_cepr(feed.entries[0], "CEPR", "cepr")
    assert p.id == "cepr:dp21920"
    assert p.title.startswith("Immigration and Child Mortality")
    assert "Katherine Eriksson" in p.authors


def test_parse_nep_maps_known_series_to_canonical_ids():
    feed = feedparser.parse((FIX / "nep.xml").read_text())
    ps = [parse_nep(e, "NEP", "nep-mic") for e in feed.entries]
    ids = {p.id for p in ps if p}
    assert "cepr:dp19247" in ids
    assert "arxiv:2608.17446" in ids
    p = next(p for p in ps if p and p.id == "cepr:dp19247")
    assert p.authors == ["Heiko Karle", "Heiner Schumacher", "Rune Volund"]
