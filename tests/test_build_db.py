"""Tests for the parsers and the database builder in data/build_db.py."""
import pytest


def test_slug(build_db):
    assert build_db.slug("Heart of Gold") == "heart-of-gold"
    assert build_db.slug("Somebody Else's Problem field") == "somebody-else-s-problem-field"
    assert build_db.slug("And Another Thing...") == "and-another-thing"
    assert build_db.slug("42") == "42"


def test_parse_reads_header_summary_and_paragraphs(build_db):
    text = (
        "# a comment\n"
        "=== Towels | I | 1\n"
        "The most useful thing.\n"
        "\n"
        "First paragraph.\n"
        "\n"
        "Second paragraph.\n"
    )
    [(name, cat, book, summary, body)] = list(build_db.parse(text))
    assert (name, cat, book, summary) == ("Towels", "I", 1, "The most useful thing.")
    assert body == "First paragraph.\n\nSecond paragraph."


def test_parse_details(build_db):
    text = "=== Marvin\nbooks: 3,1,1\nstory: He sulks.\ntip: Do not ask.\n"
    assert build_db.parse_details(text) == {
        "Marvin": {"books": [1, 3], "story": "He sulks.", "tip": "Do not ask."}
    }


def test_blocks_ignores_comments(build_db):
    assert build_db.blocks("# note\n=== 1\nOne.\n=== 2\nTwo.\n") == {"1": "One.", "2": "Two."}


def _entry(name, text=""):
    return (name, "P", 1, "", text, "")


def test_find_links_matches_whole_names_only(build_db):
    entries = [
        _entry("Marvin", "He rides in the Heart of Gold."),
        _entry("Heart of Gold", "Marvin sulks here. Marvinesque gloom."),
        _entry("Earth", "Prehistoric Earth is mentioned."),
        _entry("Prehistoric Earth"),
    ]
    links = set(build_db.find_links(entries))
    assert ("Marvin", "Heart of Gold") in links
    assert ("Heart of Gold", "Marvin") in links
    assert ("Earth", "Prehistoric Earth") in links
    assert ("Earth", "Earth") not in links  # never links to itself


def test_find_links_skips_short_names_except_42(build_db):
    entries = [
        _entry("Bob", ""),
        _entry("42", ""),
        _entry("Arthur Dent", "Bob says the answer is 42."),
    ]
    links = set(build_db.find_links(entries))
    assert ("Arthur Dent", "42") in links
    assert ("Arthur Dent", "Bob") not in links


def test_build_counts(con):
    assert con.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 6
    assert con.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 6
    assert con.execute("SELECT COUNT(*) FROM entries").fetchone()[0] >= 170
    assert con.execute("SELECT COUNT(*) FROM products").fetchone()[0] >= 6


def test_build_rejects_unknown_category(build_db, tmp_path, monkeypatch):
    original = build_db.parse

    def bad_parse(text):
        for name, cat, book, summary, body in original(text):
            yield name, "X" if name == "Marvin" else cat, book, summary, body

    monkeypatch.setattr(build_db, "parse", bad_parse)
    with pytest.raises(AssertionError, match="unknown category"):
        build_db.main(tmp_path / "bad.db")
