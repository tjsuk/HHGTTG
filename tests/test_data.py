"""Integrity checks on the built database: every entry complete, every reference valid."""


def test_every_entry_has_all_text(con):
    rows = con.execute("SELECT name, summary, body, story, tip FROM entries").fetchall()
    for r in rows:
        for field in ("summary", "body", "story", "tip"):
            assert r[field].strip(), f"{r['name']} has an empty {field}"


def test_slugs_are_unique_and_url_safe(con):
    slugs = [r[0] for r in con.execute("SELECT slug FROM entries")]
    assert len(slugs) == len(set(slugs))
    for s in slugs:
        assert s and all(c.isalnum() or c == "-" for c in s), s


def test_every_entry_appears_in_its_first_book(con):
    missing = con.execute(
        """SELECT name FROM entries e WHERE NOT EXISTS
           (SELECT 1 FROM entry_books eb WHERE eb.entry_id = e.id AND eb.book = e.book)"""
    ).fetchall()
    assert missing == []


def test_first_book_is_the_earliest_appearance(con):
    wrong = con.execute(
        """SELECT name FROM entries e
           WHERE e.book != (SELECT MIN(book) FROM entry_books eb WHERE eb.entry_id = e.id)"""
    ).fetchall()
    assert [r[0] for r in wrong] == []


def test_every_entry_has_a_drawing(con):
    rows = con.execute(
        """SELECT e.name, COALESCE(e.art, c.art) AS art FROM entries e
           JOIN categories c ON c.code = e.category"""
    ).fetchall()
    for r in rows:
        assert r["art"] and "<" in r["art"], f"{r['name']} has no drawing"


def test_featured_flag_matches_own_art(con):
    mismatched = con.execute(
        "SELECT name FROM entries WHERE featured != (art IS NOT NULL)"
    ).fetchall()
    assert mismatched == []


def test_art_has_no_scripts(con):
    arts = [r[0] for r in con.execute("SELECT art FROM entries WHERE art IS NOT NULL")]
    arts += [r[0] for r in con.execute("SELECT art FROM categories")]
    for art in arts:
        lowered = art.lower()
        assert "<script" not in lowered and "onload" not in lowered and "javascript:" not in lowered


def test_every_book_has_a_synopsis_and_a_product(con):
    for b in con.execute("SELECT number, synopsis FROM books"):
        assert len(b["synopsis"]) > 100, f"book {b['number']} synopsis is too short"
        product = con.execute(
            "SELECT 1 FROM products WHERE kind = 'book' AND book = ?", (b["number"],)
        ).fetchone()
        assert product, f"book {b['number']} has no Amazon product"


def test_products_are_complete(con):
    for p in con.execute("SELECT * FROM products"):
        assert p["title"].strip() and p["search"].strip() and p["description"].strip()
        assert p["kind"] in {"book", "collection", "audio", "screen", "extra"}


def test_links_point_to_real_entries(con):
    orphans = con.execute(
        """SELECT COUNT(*) FROM entry_links l
           WHERE l.to_id NOT IN (SELECT id FROM entries) OR l.from_id NOT IN (SELECT id FROM entries)"""
    ).fetchone()[0]
    assert orphans == 0
    self_links = con.execute("SELECT COUNT(*) FROM entry_links WHERE from_id = to_id").fetchone()[0]
    assert self_links == 0
