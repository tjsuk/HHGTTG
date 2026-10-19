"""Build guide.db (SQLite) from the plain-text data files and the art/ folder.

Why build a database from text files, instead of editing the database directly?
* Text files are easy to read, edit and compare in any editor or version control.
* The build checks the data (unknown categories, missing details, typos in names)
  and stops with a clear message, so mistakes never reach the app.
* Work that only needs doing once, such as finding cross-references between
  entries, happens here rather than on every page view.

Inputs (all in this folder):
    references.txt   name, category, first book, summary and Guide entry
    details.txt      every book each entry appears in, its story, and a tip
    books.txt        a synopsis for each book
    products.txt     products to link to on Amazon
    art/*.svg        line drawings, named by entry slug, plus category-<code>.svg

Output: guide.db, rebuilt from scratch every time.

Run from anywhere:  python data/build_db.py   (start.bat runs it for you)
"""
import os
import pathlib
import re
import sqlite3
import time

# Paths are worked out from this file's location, so the script works whatever
# the current directory is (start.bat, PyCharm and the tests all run it differently).
HERE = pathlib.Path(__file__).resolve().parent
DB = HERE / "guide.db"

# Fixed reference data. These rarely change, so they live in code rather than in
# a data file. The numbers are used throughout the text files ("| P | 3").
BOOKS = [
    (1, "The Hitchhiker's Guide to the Galaxy", "Douglas Adams", 1979),
    (2, "The Restaurant at the End of the Universe", "Douglas Adams", 1980),
    (3, "Life, the Universe and Everything", "Douglas Adams", 1982),
    (4, "So Long, and Thanks for All the Fish", "Douglas Adams", 1984),
    (5, "Mostly Harmless", "Douglas Adams", 1992),
    (6, "And Another Thing...", "Eoin Colfer", 2009),
]
# Single-letter codes keep the headers in references.txt short. The order here
# is the order of the filter chips on the index page.
CATEGORIES = [
    ("P", "People & Beings"),
    ("W", "Places"),
    ("S", "Species"),
    ("T", "Ships & Technology"),
    ("F", "Food & Drink"),
    ("I", "Ideas & Events"),
]

# The database layout. Comments inside the SQL explain columns whose purpose
# is not obvious from the name. The indexes speed up the lookups the app
# does most: filtering by category or book, and finding incoming links.
SCHEMA = """
CREATE TABLE books (
    number    INTEGER PRIMARY KEY,
    title     TEXT NOT NULL,
    author    TEXT NOT NULL,
    year      INTEGER NOT NULL,
    synopsis  TEXT NOT NULL
);
CREATE TABLE categories (
    code    TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    art     TEXT NOT NULL             -- fallback drawing for entries without their own
);
CREATE TABLE entries (
    id        INTEGER PRIMARY KEY,
    slug      TEXT NOT NULL UNIQUE,   -- URL-safe name: "Heart of Gold" -> "heart-of-gold"
    name      TEXT NOT NULL UNIQUE,
    category  TEXT NOT NULL REFERENCES categories(code),
    book      INTEGER NOT NULL REFERENCES books(number),  -- the book it first appears in
    summary   TEXT NOT NULL,
    body      TEXT NOT NULL,      -- the Guide entry; paragraphs separated by blank lines
    story     TEXT NOT NULL,      -- what happens to it in the novels
    tip       TEXT NOT NULL,      -- a one-line hitchhiker's tip
    art       TEXT,               -- inner SVG markup for viewBox 0 0 200 100, or NULL to use the category art
    featured  INTEGER NOT NULL DEFAULT 0  -- 1 when it has its own drawing (marked with a diamond)
);
CREATE INDEX ix_entries_category ON entries(category);
CREATE INDEX ix_entries_book ON entries(book);

-- Every book an entry appears in (entries.book is the first).
-- A separate table, because one entry can appear in many books: this is the
-- standard way to store a one-to-many list in a relational database.
CREATE TABLE entry_books (
    entry_id  INTEGER NOT NULL REFERENCES entries(id),
    book      INTEGER NOT NULL REFERENCES books(number),
    PRIMARY KEY (entry_id, book)
);
CREATE INDEX ix_entry_books_book ON entry_books(book);

-- Cross-references: entry from_id mentions entry to_id by name in its text.
-- Read forwards it gives "mentions"; read backwards it gives "mentioned in".
CREATE TABLE entry_links (
    from_id   INTEGER NOT NULL REFERENCES entries(id),
    to_id     INTEGER NOT NULL REFERENCES entries(id),
    PRIMARY KEY (from_id, to_id)
);
CREATE INDEX ix_entry_links_to ON entry_links(to_id);

-- Products sold on Amazon. Only the search terms are stored; the app adds the
-- store and associate tag, so changing the tag needs no rebuild.
CREATE TABLE products (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,      -- book, collection, audio, screen, extra
    title        TEXT NOT NULL,
    search       TEXT NOT NULL,
    book         INTEGER REFERENCES books(number),   -- shown on that book's page
    entry_id     INTEGER REFERENCES entries(id),     -- shown on that entry's page
    description  TEXT NOT NULL
);
CREATE INDEX ix_products_book ON products(book);
CREATE INDEX ix_products_entry ON products(entry_id);
"""

PRODUCT_KINDS = ("book", "collection", "audio", "screen", "extra")


def slug(name: str) -> str:
    """Turn a name into a URL-safe id: lower case, runs of other characters become one dash.

    "Somebody Else's Problem field" -> "somebody-else-s-problem-field".
    The same function names the art files, so a drawing is found by its entry's slug.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse(text: str):
    """Read references.txt and yield (name, category, book, summary, body) per entry.

    Format of each entry:
        === Name | Category | Book
        One-line summary.
        <blank line>
        The Guide entry, which may run to several paragraphs.

    Splitting on lines that start with "=== " gives one chunk per entry; within
    a chunk, the first blank line separates the summary from the body.
    """
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    # re.M makes ^ match at the start of every line, not just the start of the text.
    # [1:] drops whatever comes before the first "=== " (the file's header notes).
    blocks = re.split(r"^=== ", "\n".join(lines), flags=re.M)[1:]
    for block in blocks:
        header, _, rest = block.partition("\n")
        name, cat, book = (p.strip() for p in header.split("|"))
        rest = rest.strip("\n")
        summary, _, body = rest.partition("\n\n")
        yield name, cat, int(book), summary.strip(), body.strip()


def blocks(text: str):
    """Split a '=== key' file into {key: block text}, ignoring # comment lines.

    Used for details.txt (keyed by entry name) and books.txt (keyed by book number).
    """
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    out = {}
    for block in re.split(r"^=== ", "\n".join(lines), flags=re.M)[1:]:
        key, _, rest = block.partition("\n")
        out[key.strip()] = rest.strip()
    return out


def parse_details(text: str):
    """Read details.txt into {name: {"books": [...], "story": ..., "tip": ...}}.

    Each line is "field: value". split(": ", 1) splits on the first colon-space
    only, so a story that itself contains ": " stays in one piece.
    The book list goes through a set and sorted(), so "3,1,1" becomes [1, 3].
    """
    details = {}
    for name, rest in blocks(text).items():
        fields = dict(line.split(": ", 1) for line in rest.splitlines() if ": " in line)
        details[name] = {
            "books": sorted({int(b) for b in fields["books"].split(",")}),
            "story": fields["story"].strip(),
            "tip": fields["tip"].strip(),
        }
    return details


def find_links(entries):
    """Link each entry to the other entries it mentions by name.

    Rules, and why:
    * Whole names only. (?<![\\w']) and (?![\\w]) mean the name must not be part
      of a longer word, so "Marvin" does not match "Marvinesque".
    * Case-sensitive, because names are proper nouns: "Tea" the entry should not
      match every "tea" in the text.
    * Names shorter than 4 characters are skipped ("Bob", "Tea") because they
      match too much by accident. "42" is the exception: it is always meaningful.
    * An entry never links to itself.

    Returns a list of (from_name, to_name) pairs. This runs once at build time,
    which is far cheaper than searching every entry's text on every page view.
    """
    patterns = [
        (n, re.compile(r"(?<![\w'])" + re.escape(n) + r"(?![\w])"))
        for n, *_ in entries
        if len(n) >= 4 or n == "42"
    ]
    links = []
    for name, _cat, _book, summary, body, story in entries:
        text = "\n".join((summary, body, story))
        for other, pat in patterns:
            if other != name and pat.search(text):
                links.append((name, other))
    return links


def main(db_path: pathlib.Path = DB, data_dir: pathlib.Path = HERE) -> pathlib.Path:
    """Read every data file in data_dir, check it, and write a fresh database to db_path.

    Both are parameters so the tests can build from a copy of the data into a
    temporary folder, and never touch the real files. Returns the path it wrote.
    """
    db_path = pathlib.Path(db_path)
    data_dir = pathlib.Path(data_dir)
    # 1. Read all the inputs.
    art_dir = data_dir / "art"
    # {slug: svg markup}, e.g. {"marvin": "<path .../>", "category-p": "..."}
    art = {p.stem: p.read_text(encoding="utf-8").strip() for p in art_dir.glob("*.svg")}
    refs = list(parse((data_dir / "references.txt").read_text(encoding="utf-8")))
    details = parse_details((data_dir / "details.txt").read_text(encoding="utf-8"))
    synopses = {int(k): v for k, v in blocks((data_dir / "books.txt").read_text(encoding="utf-8")).items()}

    # 2. Check the data before writing anything, so a mistake stops the build
    #    with a message naming the entry, instead of producing a broken database.
    valid_cats = {c for c, _ in CATEGORIES}
    names = set()
    for name, cat, book, summary, body in refs:
        assert cat in valid_cats, f"{name}: unknown category {cat}"
        assert 1 <= book <= 6, f"{name}: unknown book {book}"
        assert summary and body, f"{name}: missing summary or body"
        assert name not in names, f"duplicate entry {name}"
        assert name in details, f"{name}: no block in details.txt"
        assert book in details[name]["books"], f"{name}: first book {book} missing from its books list"
        names.add(name)
    # Catches typos in details.txt: a misspelled name would otherwise be silently ignored.
    extra = set(details) - names
    assert not extra, f"details.txt names with no entry: {sorted(extra)}"
    assert set(synopses) == {b[0] for b in BOOKS}, "books.txt needs a synopsis for every book"

    # Combine each entry with its story (needed for link detection), sorted by
    # name so ids follow alphabetical order and builds are repeatable.
    entries = sorted(
        ((n, c, b, s, body, details[n]["story"]) for n, c, b, s, body in refs),
        key=lambda e: e[0].lower(),
    )

    # 3. Write the database into a temporary file next to the real one, then swap
    #    it into place at the end (step 5). Why not write guide.db directly?
    #    * The app may be running. With the swap, it sees either the complete old
    #      database or the complete new one, never a half-written file.
    #    * If anything fails part-way, the old database is left untouched.
    #    Starting from an empty file also means no leftover rows from removed entries.
    tmp_path = db_path.with_name(db_path.name + ".tmp")
    tmp_path.unlink(missing_ok=True)
    con = sqlite3.connect(tmp_path)
    try:
        products = _write_tables(con, data_dir, entries, details, synopses, names, art)
        total, featured = con.execute("SELECT COUNT(*), SUM(featured) FROM entries").fetchone()
        appearances = con.execute("SELECT COUNT(*) FROM entry_books").fetchone()[0]
        links = con.execute("SELECT COUNT(*) FROM entry_links").fetchone()[0]
    except BaseException:
        con.close()
        tmp_path.unlink(missing_ok=True)
        raise
    con.close()

    # 5. Swap the new database into place. os.replace is atomic: the file
    #    switches over in one step.
    _swap_into_place(tmp_path, db_path)

    # 6. Report what was built, so start.bat's window shows the build worked.
    print(
        f"Wrote {db_path.name}: {total} entries ({featured} with their own drawing), "
        f"{appearances} book appearances, {links} cross-references, {len(products)} products."
    )
    return db_path


def _swap_into_place(tmp_path: pathlib.Path, db_path: pathlib.Path, attempts: int = 20) -> None:
    """Replace db_path with tmp_path, retrying briefly if the file is in use.

    Windows refuses to replace a file that any program has open. The app opens
    the database only for the length of one request (a few milliseconds), so if
    a page happens to be loading at the moment of the swap, waiting a moment and
    trying again is enough. If it still fails, the temporary file is removed so
    nothing is left behind, and the error is passed on.
    """
    for attempt in range(attempts):
        try:
            os.replace(tmp_path, db_path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                tmp_path.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


def _write_tables(con, data_dir, entries, details, synopses, names, art):
    """Create the tables and insert every row. Returns the list of products.

    Split out of main() so main() can clean up the temporary file if anything
    in here fails (for example a product naming an entry that does not exist).
    """
    con.executescript(SCHEMA)
    # executemany inserts all rows in one call; "?" placeholders let sqlite3
    # handle quoting, so apostrophes in names cannot break the SQL.
    con.executemany(
        "INSERT INTO books VALUES (?,?,?,?,?)",
        [(n, t, a, y, synopses[n]) for n, t, a, y in BOOKS],
    )
    con.executemany(
        "INSERT INTO categories VALUES (?,?,?)",
        [(c, n, art[f"category-{c.lower()}"]) for c, n in CATEGORIES],
    )
    con.executemany(
        """INSERT INTO entries (slug, name, category, book, summary, body, story, tip, art, featured)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [
            # art.get() returns None when an entry has no drawing of its own,
            # which is stored as NULL; the app then uses the category drawing.
            (slug(n), n, c, b, s, body, story, details[n]["tip"], art.get(slug(n)), int(slug(n) in art))
            for n, c, b, s, body, story in entries
        ],
    )
    # The other tables refer to entries by numeric id, which SQLite assigned on
    # insert. Read them back as a {name: id} lookup.
    ids = dict(con.execute("SELECT name, id FROM entries"))

    # products.txt is one product per line: kind | title | search | book | entry | description,
    # with "-" for "none" in the book and entry columns.
    products = []
    for line in (data_dir / "products.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        kind, title, search, book, entry, desc = (p.strip() for p in line.split("|"))
        assert kind in PRODUCT_KINDS, f"product {title}: unknown kind {kind}"
        assert entry == "-" or entry in ids, f"product {title}: unknown entry {entry}"
        products.append((
            kind, title, search,
            None if book == "-" else int(book),
            None if entry == "-" else ids[entry],
            desc,
        ))
    con.executemany(
        "INSERT INTO products (kind, title, search, book, entry_id, description) VALUES (?,?,?,?,?,?)",
        products,
    )
    con.executemany(
        "INSERT INTO entry_books VALUES (?,?)",
        [(ids[n], b) for n in names for b in details[n]["books"]],
    )
    con.executemany(
        "INSERT INTO entry_links VALUES (?,?)",
        [(ids[a], ids[b]) for a, b in find_links(entries)],
    )
    # 4. Nothing is saved until commit.
    con.commit()
    return products


if __name__ == "__main__":
    main()
