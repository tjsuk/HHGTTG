"""The Hitchhiker's Guide to the Galaxy: a Flask edition.

How it fits together
--------------------
* All content lives in one SQLite file, data/guide.db. It is *built*, not edited:
  data/build_db.py reads the plain-text files in data/ and writes a fresh database.
  This app only ever reads it, so the text files stay the single source of truth.
* Each page is a Flask route that runs a few SQL queries and hands the rows to a
  Jinja template in templates/. All pages share templates/base.html, which draws
  the device casing, screen and keypad.
* static/guide.js adds optional touches (starfield, typewriter text, instant
  filtering). Every page works without JavaScript; the scripts only enhance it.

Run:  flask --app app run   (or: python app.py, or double-click start.bat)
"""
import os
import random
import re
import sqlite3

from urllib.parse import urlencode

from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for
from markupsafe import Markup, escape

# --- Settings ----------------------------------------------------------------
# Each setting reads an environment variable first, so the tests (or a different
# deployment) can change it without editing code.

# Where the database lives. The default is resolved from this file's location,
# not the current directory, so the app works whichever folder it is started from.
DB_PATH = os.environ.get(
    "GUIDE_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "guide.db")
)

# Amazon Associates settings: which Amazon store the links go to, and the
# tracking ID that credits purchases to the account.
AMAZON_DOMAIN = os.environ.get("AMAZON_DOMAIN", "www.amazon.co.uk")
AMAZON_TAG = os.environ.get("AMAZON_TAG", "tsmith0d")

# Product kinds in the order the shop page lists them, with their headings.
# A dict keeps insertion order, so this also sets the order of the sections.
PRODUCT_KINDS = {
    "book": "The novels",
    "collection": "Collections",
    "audio": "Radio and audio",
    "screen": "Television and film",
    "extra": "Extras",
}

app = Flask(__name__)


# --- Helpers available inside templates --------------------------------------

@app.template_global()
def amazon_url(search: str) -> str:
    """Build an Amazon search link that carries the associate tag.

    Why a search link and not a product link: product IDs (ASINs) differ between
    Amazon stores and editions, and a wrong ID gives a dead page. A search for the
    title always lands somewhere useful, and Amazon still credits the tag.
    urlencode() escapes characters such as & and ' so titles cannot break the URL.
    """
    return f"https://{AMAZON_DOMAIN}/s?" + urlencode({"k": search, "tag": AMAZON_TAG})


# --- Database connection -----------------------------------------------------

def db() -> sqlite3.Connection:
    """Return this request's database connection, opening it on first use.

    Flask's `g` object lives for one request, so each request gets its own
    connection (SQLite connections must not be shared between threads), and a
    page that runs several queries reuses the same one.

    The connection is opened read-only (mode=ro) because the app never writes:
    a bug cannot damage the data, and only build_db.py changes the file.
    """
    if "db" not in g:
        g.db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        # Row lets templates use row["name"] or row.name instead of row[1].
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    """Close the request's connection when the request ends, even after an error."""
    con = g.pop("db", None)
    if con is not None:
        con.close()


@app.context_processor
def lookups():
    """Values every template can use without each route passing them in.

    Categories and books are tiny tables used by the index filters and the
    footer, so it is simpler to query them here than in every route.
    """
    return {
        "categories": db().execute("SELECT code, name FROM categories ORDER BY rowid").fetchall(),
        "books": db().execute("SELECT number, title, author, year FROM books ORDER BY number").fetchall(),
        "entry_count": db().execute("SELECT COUNT(*) FROM entries").fetchone()[0],
    }


@app.template_filter("autolink")
def autolink(text: str, links) -> Markup:
    """Escape text, then turn mentions of other entries into links.

    Used in templates as {{ text|autolink(mentions) }}, where `mentions` is the
    list of entries this entry refers to (worked out at build time).

    The order of steps matters for safety:
    1. Escape the whole text first, so any < or & in the data is shown as text,
       never run as HTML.
    2. Only then insert our own <a> tags, and mark the result as safe Markup.

    Longest names go first in the pattern, so "Prehistoric Earth" is linked as
    one name instead of "Prehistoric " plus a link to "Earth". The lookarounds
    (?<![\\w']) and (?![\\w]) stop matches inside longer words ("Marvinesque").
    """
    html = str(escape(text))
    targets = sorted(links, key=lambda r: len(r["name"]), reverse=True)
    if not targets:
        return Markup(html)
    # Keys are the *escaped* names, because we are searching escaped text:
    # "Somebody Else's Problem field" appears as "Somebody Else&#39;s ..." here.
    by_name = {str(escape(r["name"])): r["slug"] for r in targets}
    pattern = re.compile(
        r"(?<![\w'])(" + "|".join(re.escape(n) for n in by_name) + r")(?![\w])"
    )
    html = pattern.sub(
        lambda m: f'<a class="xref" href="{url_for("entry", slug=by_name[m.group(1)])}">{m.group(1)}</a>',
        html,
    )
    return Markup(html)


def find_entries(cat: str = "", book: int | None = None, q: str = ""):
    """Return index rows matching any combination of category, book and text.

    The SQL is assembled from optional pieces. "WHERE 1=1" is a neutral start so
    every filter can be appended as " AND ..." without special-casing the first.
    User input only ever goes in as ? parameters, never pasted into the SQL
    string, which is what prevents SQL injection.
    """
    sql = "SELECT slug, name, category, book, summary, featured FROM entries e WHERE 1=1"
    args: list = []
    if cat:
        sql += " AND category = ?"
        args.append(cat)
    if book:
        # Filter on entry_books (every book an entry appears in), not entries.book
        # (only its first book), so "Book 4" also lists Arthur, Ford and Marvin.
        sql += " AND EXISTS (SELECT 1 FROM entry_books eb WHERE eb.entry_id = e.id AND eb.book = ?)"
        args.append(book)
    if q:
        # LIKE with % on both sides means "contains". The same term is checked
        # against four columns, so it is added to args four times.
        sql += " AND (name LIKE ? OR summary LIKE ? OR body LIKE ? OR story LIKE ?)"
        args += [f"%{q}%"] * 4
    # COLLATE NOCASE sorts "the Guide" next to "The Guide", not after all capitals.
    sql += " ORDER BY name COLLATE NOCASE"
    return db().execute(sql, args).fetchall()


# --- Pages -------------------------------------------------------------------

@app.route("/")
def cover():
    """The closed device with DON'T PANIC on the lid."""
    return render_template("cover.html")


@app.route("/index")
def index():
    """The list of entries. Filters come from the query string (?cat=S&book=2&q=...),
    so every filtered view has its own URL that can be bookmarked or shared."""
    cat = request.args.get("cat", "")
    book = request.args.get("book", type=int)  # type=int turns bad input into None
    q = request.args.get("q", "").strip()
    return render_template(
        "index.html", entries=find_entries(cat, book, q), cat=cat, book=book, q=q
    )


@app.route("/entry/<slug>")
def entry(slug: str):
    """One entry, with everything related to it.

    Several small queries are easier to read and change than one huge join, and
    with a local SQLite file each takes well under a millisecond.
    """
    # The entry itself, plus its category's name and fallback drawing.
    row = db().execute(
        """SELECT e.*, c.name AS category_name, c.art AS category_art,
                  b.title AS book_title, b.author AS book_author
           FROM entries e
           JOIN categories c ON c.code = e.category
           JOIN books b ON b.number = e.book
           WHERE e.slug = ?""",
        (slug,),
    ).fetchone()
    if row is None:
        abort(404)
    # Every book it appears in.
    appears = db().execute(
        """SELECT b.number, b.title FROM entry_books eb JOIN books b ON b.number = eb.book
           WHERE eb.entry_id = ? ORDER BY b.number""",
        (row["id"],),
    ).fetchall()
    # Entries this one mentions (links go out from here): used by autolink.
    mentions = db().execute(
        """SELECT e.slug, e.name FROM entry_links l JOIN entries e ON e.id = l.to_id
           WHERE l.from_id = ? ORDER BY e.name COLLATE NOCASE""",
        (row["id"],),
    ).fetchall()
    # Entries that mention this one (links come in): the same table read backwards.
    mentioned_in = db().execute(
        """SELECT e.slug, e.name FROM entry_links l JOIN entries e ON e.id = l.from_id
           WHERE l.to_id = ? ORDER BY e.name COLLATE NOCASE""",
        (row["id"],),
    ).fetchall()
    # Products for this entry, plus the novels it appears in.
    # "ORDER BY p.entry_id IS NULL" is 0 for entry-specific products and 1 for
    # the rest, so the entry's own product (say, a towel for Towels) comes first.
    products = db().execute(
        """SELECT p.* FROM products p
           WHERE p.entry_id = ?
              OR p.book IN (SELECT book FROM entry_books WHERE entry_id = ?)
           ORDER BY p.entry_id IS NULL, p.book, p.id""",
        (row["id"], row["id"]),
    ).fetchall()
    return render_template(
        "entry.html", e=row, appears=appears, mentions=mentions, mentioned_in=mentioned_in,
        products=products,
    )


@app.route("/shop")
def shop():
    """Every product, grouped by kind in PRODUCT_KINDS order."""
    # LEFT JOIN keeps products that are not tied to any entry (entry_name is then None).
    rows = db().execute(
        """SELECT p.*, e.slug AS entry_slug, e.name AS entry_name FROM products p
           LEFT JOIN entries e ON e.id = p.entry_id ORDER BY p.id"""
    ).fetchall()
    # Grouping in Python keeps the SQL simple; there are only a couple of dozen rows.
    groups = {label: [r for r in rows if r["kind"] == kind] for kind, label in PRODUCT_KINDS.items()}
    return render_template("shop.html", groups=groups)


@app.route("/books")
def book_list():
    """The six books, each with a count of the entries that appear in it."""
    rows = db().execute(
        """SELECT b.*, (SELECT COUNT(*) FROM entry_books eb WHERE eb.book = b.number) AS entries
           FROM books b ORDER BY b.number"""
    ).fetchall()
    return render_template("books.html", rows=rows)


@app.route("/book/<int:number>")
def book(number: int):
    """One book: its synopsis, who first appears in it, who returns, and where to buy it.

    <int:number> makes Flask reject non-numbers with a 404 before this runs.
    """
    b = db().execute("SELECT * FROM books WHERE number = ?", (number,)).fetchone()
    if b is None:
        abort(404)
    # Debuts: entries whose *first* book is this one.
    debuts = db().execute(
        "SELECT slug, name, category FROM entries WHERE book = ? ORDER BY name COLLATE NOCASE", (number,)
    ).fetchall()
    # Returning: entries that appear here but first appeared in an earlier book.
    returning = db().execute(
        """SELECT e.slug, e.name FROM entries e JOIN entry_books eb ON eb.entry_id = e.id
           WHERE eb.book = ? AND e.book != ? ORDER BY e.name COLLATE NOCASE""",
        (number, number),
    ).fetchall()
    product = db().execute(
        "SELECT * FROM products WHERE book = ? AND kind = 'book'", (number,)
    ).fetchone()
    return render_template("book.html", b=b, debuts=debuts, returning=returning, product=product)


@app.route("/random")
def random_entry():
    """Redirect to a random entry.

    A redirect (rather than rendering an entry here) gives the entry its real
    URL, so Back, bookmarks and sharing all work as expected.
    """
    slugs = [r[0] for r in db().execute("SELECT slug FROM entries")]
    return redirect(url_for("entry", slug=random.choice(slugs)))


@app.route("/search")
def search():
    """The search box on every screen.

    An exact name match (any capitalisation) goes straight to that entry, which
    is what someone typing "towels" almost certainly wants. Anything else shows
    the index filtered by the text.
    """
    q = request.args.get("q", "").strip()
    if not q:
        return redirect(url_for("index"))
    exact = db().execute(
        "SELECT slug FROM entries WHERE name = ? COLLATE NOCASE", (q,)
    ).fetchone()
    if exact:
        return redirect(url_for("entry", slug=exact["slug"]))
    return redirect(url_for("index", q=q))


# --- JSON API ----------------------------------------------------------------
# The same data as JSON, for other programs (a mobile app, scripts, tests).

@app.route("/api/entries")
def api_entries():
    """Entry list with the same filters as /index."""
    rows = find_entries(
        request.args.get("cat", ""), request.args.get("book", type=int), request.args.get("q", "").strip()
    )
    # sqlite3.Row is not JSON-serialisable, so convert each row to a dict.
    return jsonify([dict(r) for r in rows])


@app.route("/api/entries/<slug>")
def api_entry(slug: str):
    """One entry, plus the books it appears in and the slugs it mentions."""
    row = db().execute("SELECT * FROM entries WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        abort(404)
    data = dict(row)
    data["books"] = [r[0] for r in db().execute(
        "SELECT book FROM entry_books WHERE entry_id = ? ORDER BY book", (row["id"],))]
    data["mentions"] = [r[0] for r in db().execute(
        "SELECT e.slug FROM entry_links l JOIN entries e ON e.id = l.to_id WHERE l.from_id = ?", (row["id"],))]
    return jsonify(data)


@app.errorhandler(404)
def not_found(_e):
    """Show missing pages inside the device instead of Flask's plain error page.
    Returning 404 as well keeps the status code correct for browsers and tests."""
    return render_template("404.html"), 404


if __name__ == "__main__":
    # debug=True reloads on code changes and shows tracebacks. Use it only on
    # your own machine: the debugger can run code, so never expose it publicly.
    app.run(debug=True)
