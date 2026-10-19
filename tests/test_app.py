"""Tests for the Flask routes, the autolink filter and the Amazon links."""
from urllib.parse import parse_qs, urlparse

import pytest


@pytest.mark.parametrize(
    "path",
    ["/", "/index", "/index?cat=S", "/index?book=4", "/index?q=towel", "/books", "/book/1", "/book/6",
     "/shop", "/entry/marvin", "/entry/42", "/entry/somebody-else-s-problem-field"],
)
def test_pages_load(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert b"Amazon Associate" in response.data


@pytest.mark.parametrize("path", ["/entry/no-such-thing", "/book/0", "/book/7", "/api/entries/nope"])
def test_missing_pages_return_404(client, path):
    assert client.get(path).status_code == 404


def test_404_page_uses_the_guide_layout(client):
    response = client.get("/entry/no-such-thing")
    assert b"Entry not found" in response.data


def test_index_lists_every_entry(client, con):
    total = con.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    page = client.get("/index").get_data(as_text=True)
    # Count the list items, not every /entry/ link: the page also has "Add an entry".
    assert page.count("<li data-text=") == total


def test_index_filters_by_category(client, con):
    species = con.execute("SELECT COUNT(*) FROM entries WHERE category = 'S'").fetchone()[0]
    page = client.get("/index?cat=S").get_data(as_text=True)
    assert page.count("<li data-text=") == species
    assert "Babel Fish" in page and "Arthur Dent" not in page


def test_index_book_filter_uses_all_appearances(client):
    # Marvin first appears in book 1 but also appears in book 4
    page = client.get("/index?book=4").get_data(as_text=True)
    assert "/entry/marvin" in page
    assert "/entry/fenchurch" in page


def test_index_text_filter_searches_story_text(client):
    page = client.get("/index?q=sofa").get_data(as_text=True)
    assert "/entry/chesterfield-sofa" in page


def test_search_opens_exact_match_case_insensitively(client):
    response = client.get("/search?q=towels")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/entry/towels")


def test_search_falls_back_to_filtered_index(client):
    response = client.get("/search?q=whale")
    assert response.status_code == 302
    assert "/index?q=whale" in response.headers["Location"]


def test_empty_search_goes_to_index(client):
    response = client.get("/search?q=")
    assert response.headers["Location"].endswith("/index")


def test_random_redirects_to_an_entry(client):
    response = client.get("/random")
    assert response.status_code == 302
    assert "/entry/" in response.headers["Location"]


def test_entry_page_shows_all_sections(client):
    page = client.get("/entry/marvin").get_data(as_text=True)
    for heading in ("In the story", "Hitchhiker's tip", "Appears in", "Get it on Amazon"):
        assert heading in page
    assert "<svg" in page


def test_entry_page_cross_links_mentions(client):
    page = client.get("/entry/marvin").get_data(as_text=True)
    assert 'class="xref" href="/entry/heart-of-gold"' in page


def test_book_page_lists_debuts_and_returning(client):
    page = client.get("/book/4").get_data(as_text=True)
    assert "First appearing here" in page and "/entry/fenchurch" in page
    assert "Returning" in page and "/entry/arthur-dent" in page


def test_api_entries(client):
    data = client.get("/api/entries?cat=F").get_json()
    assert data and all(row["category"] == "F" for row in data)


def test_api_entry_includes_books_and_mentions(client):
    data = client.get("/api/entries/arthur-dent").get_json()
    assert data["name"] == "Arthur Dent"
    assert data["books"] == [1, 2, 3, 4, 5, 6]
    assert "fenchurch" in data["mentions"]


# --- autolink filter ---------------------------------------------------------

def test_autolink_links_longest_name_first(app):
    links = [{"name": "Earth", "slug": "earth"}, {"name": "Prehistoric Earth", "slug": "prehistoric-earth"}]
    with app.app.test_request_context():
        html = str(app.autolink("They were stranded on Prehistoric Earth.", links))
    assert html.count("<a ") == 1
    assert 'href="/entry/prehistoric-earth">Prehistoric Earth</a>' in html


def test_autolink_escapes_text(app):
    with app.app.test_request_context():
        html = str(app.autolink("<script>alert(1)</script> Marvin", [{"name": "Marvin", "slug": "marvin"}]))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="/entry/marvin"' in html


def test_autolink_handles_apostrophes(app):
    links = [{"name": "Somebody Else's Problem field", "slug": "somebody-else-s-problem-field"}]
    with app.app.test_request_context():
        html = str(app.autolink("Hidden by a Somebody Else's Problem field.", links))
    assert 'href="/entry/somebody-else-s-problem-field"' in html


def test_autolink_without_links_only_escapes(app):
    with app.app.test_request_context():
        assert str(app.autolink("Tea & biscuits", [])) == "Tea &amp; biscuits"


# --- Amazon links ------------------------------------------------------------

def test_amazon_url_carries_tag_and_encodes_search(app):
    url = urlparse(app.amazon_url("So Long & Thanks"))
    assert url.scheme == "https" and url.netloc == "www.amazon.co.uk" and url.path == "/s"
    query = parse_qs(url.query)
    assert query == {"k": ["So Long & Thanks"], "tag": ["tsmith0d"]}


def test_shop_links_are_tagged_sponsored_and_open_new_tab(client, con):
    page = client.get("/shop").get_data(as_text=True)
    total = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    assert page.count('class="buy"') == total
    assert page.count("tag=tsmith0d") == total
    assert page.count('rel="sponsored noopener"') == total
    assert page.count('target="_blank"') == total


def test_book_page_has_amazon_link(client):
    page = client.get("/book/2").get_data(as_text=True)
    assert "Find this book on Amazon" in page and "tag=tsmith0d" in page


def test_entry_shows_its_own_product_first(client):
    page = client.get("/entry/towels").get_data(as_text=True)
    first_buy = page.index('class="buy"')
    assert page.index("A towel worthy of the Guide") > first_buy
    assert page.index("A towel worthy of the Guide") < page.index("The Restaurant at the End of the Universe ↗")
