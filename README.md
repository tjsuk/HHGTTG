# The Hitchhiker's Guide (Flask edition)

An unofficial, fan-made Hitchhiker's Guide to the Galaxy device, built with Flask.
Every entry lives in a SQLite database: 173 references from the six novels, each
with a one-line summary, a full Guide entry, what happens to it in the story, a
hitchhiker's tip, the books it appears in, cross-links to the entries it mentions,
and a line drawing (its own, or one for its category). Each book also has a synopsis
page. All of the text is original and written for this project; nothing is quoted
from the novels.

## Run it

On Windows, double-click **`start.bat`**. On first run it creates a virtual environment
and installs Flask. Every time, it rebuilds the database, opens your browser at
http://127.0.0.1:5000 and starts the server. Close the window to stop it.

Or by hand:

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
flask --app app run
```

Then open http://127.0.0.1:5000.

## Tests

On Windows, double-click **`test.bat`**. It installs pytest on first run, then runs
the suite. Or by hand:

```bash
pip install -r requirements-dev.txt
pytest
```

The tests build a fresh database from the data files into a temporary folder, so they
check your latest edits without touching `data/guide.db`.

| File | Checks |
| --- | --- |
| `tests/test_build_db.py` | The text parsers, slugs, cross-link detection and build validation |
| `tests/test_data.py` | Every entry is complete, has a drawing and a valid first book; products and links are sound |
| `tests/test_app.py` | Every route, filters, search, the JSON API, safe cross-linking and the tagged Amazon links |

## Project layout

| Path | What it is |
| --- | --- |
| `app.py` | The Flask app: cover, index, entries, random, search and a JSON API |
| `templates/` | Jinja templates for the device screens |
| `static/` | The device styling and small scripts (starfield, typewriter text, instant filter) |
| `start.bat` | One-click start on Windows |
| `data/references.txt` | The summary and Guide entry for every reference. Edit this to add or change entries |
| `data/details.txt` | Per entry: the books it appears in, what happens in the story, and a tip |
| `data/books.txt` | A synopsis of each book |
| `data/products.txt` | Products linked to Amazon: the books, collections, radio, screen versions and extras |
| `data/art/` | Line drawings as SVG fragments (`viewBox="0 0 200 100"`), named by entry slug |
| `data/build_db.py` | Rebuilds `data/guide.db` from the text and art |
| `data/guide.db` | The SQLite database the app reads |

## Adding an entry

1. Add a block to `data/references.txt`:

   ```text
   === Name | Category | Book
   One-line summary.

   The Guide entry, in one or more paragraphs.
   ```

   Categories: `P` People & Beings, `W` Places, `S` Species, `T` Ships & Technology,
   `F` Food & Drink, `I` Ideas & Events. Books: `1`–`5` for Douglas Adams's novels,
   `6` for Eoin Colfer's *And Another Thing...*

2. Add a matching block to `data/details.txt`:

   ```text
   === Name
   books: 1,2
   story: What happens to it in the novels.
   tip: A one-line hitchhiker's tip.
   ```

3. Optionally add a drawing at `data/art/<slug>.svg`, where the slug is the name in
   lower case with dashes (for example `heart-of-gold.svg`).
4. Rebuild the database with `python data/build_db.py` (or just run `start.bat`).
   The build checks that every entry has details, and works out the cross-links.

## Amazon links

Products from `data/products.txt` appear on book pages, on the entries they relate to,
and on the `/shop` page. Each one links to an Amazon search with the associate tag
added, and every page carries the Amazon Associates disclosure. The store and tag are
set at the top of `app.py`, and can be overridden with environment variables:

| Variable | Default |
| --- | --- |
| `AMAZON_DOMAIN` | `www.amazon.co.uk` |
| `AMAZON_TAG` | `tsmith0d` |

## Routes

| Route | Shows |
| --- | --- |
| `/` | The cover |
| `/index?cat=P&book=2&q=towel` | The index, filtered by category, book and text |
| `/entry/<slug>` | One entry, with its story, tip, appearances and cross-links |
| `/books`, `/book/<n>` | The six books, each with a synopsis, its entries and an Amazon link |
| `/shop` | Every product, grouped, with Amazon links |
| `/random` | A random entry |
| `/search?q=...` | Opens an exact match, otherwise a filtered index |
| `/api/entries`, `/api/entries/<slug>` | The same data as JSON |

## Database schema

- `books(number, title, author, year, synopsis)`
- `categories(code, name, art)`
- `entries(id, slug, name, category, book, summary, body, story, tip, art, featured)`
- `entry_books(entry_id, book)`: every book an entry appears in
- `entry_links(from_id, to_id)`: entries that mention each other by name
- `products(id, kind, title, search, book, entry_id, description)`
