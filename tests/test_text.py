from radar.text import find_identifiers, fix_mojibake, inverted_index_to_text, split_authors, title_key


def test_title_key_ignores_case_punctuation_and_stopwords():
    a = title_key("The Marriage Market, Labor Supply, and Education Choice")
    b = title_key("Marriage market labor supply & education choice!")
    assert a == b == "marriage market labor supply education choice"


def test_find_identifiers():
    ids = find_identifiers("see https://doi.org/10.1086/722564. and arXiv:2608.17446v2 https://www.nber.org/papers/w35670")
    assert ids["doi"] == "10.1086/722564"
    assert ids["arxiv_id"] == "2608.17446"
    assert ids["nber"] == "w35670"
    assert ids["url"].startswith("https://doi.org/")


def test_inverted_index():
    assert inverted_index_to_text({"who": [0], "marries": [1], "whom": [2]}) == "who marries whom"


def test_split_authors():
    assert split_authors("A. Patrick Behrer, Joshua Goodman, J. Parker Goyer") == ["A. Patrick Behrer", "Joshua Goodman", "J. Parker Goyer"]
    assert split_authors("Karle, Heiko & Schumacher, Heiner") == ["Karle, Heiko", "Schumacher, Heiner"]


def test_fix_mojibake():
    assert fix_mojibake("Samuel LÃ¼thi") == "Samuel Lüthi"
    assert fix_mojibake("Jakob Søgaard") == "Jakob Søgaard"
