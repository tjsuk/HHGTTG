"""Add and edit Guide entries from the web forms.

Why this edits the text files instead of the database
-----------------------------------------------------
The text files in data/ are the source of truth: start.bat rebuilds guide.db
from them every time it runs. If the forms wrote only to the database, every
change would be wiped on the next start. So saving an entry:

1. rewrites that entry's block in data/references.txt and data/details.txt
   (and follows a rename through products.txt and the drawing's file name),
2. rebuilds guide.db with data/build_db.py,
3. and if the rebuild fails for any reason, puts every file back exactly as
   it was, so a bad save can never leave the data broken.

Everything else in the files (comments, other entries, their order) is left
alone, so the files stay easy to read and compare after edits.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import threading
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parent


def _load_build_db():
    # data/ is a folder of data files, not a Python package, so load the build
    # script by its path (the tests do the same).
    spec = importlib.util.spec_from_file_location("build_db", ROOT / "data" / "build_db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_db = _load_build_db()

# Only one save may run at a time. Flask can serve requests on several threads,
# and two saves interleaving their file writes could corrupt a file.
_lock = threading.Lock()

CATEGORY_CODES = [code for code, _ in build_db.CATEGORIES]
BOOK_NUMBERS = [number for number, *_ in build_db.BOOKS]
MAX_NAME = 80
# Slugs the app uses for its own pages under /entry/, so no entry may take them.
RESERVED_SLUGS = {"new"}


class EntryError(Exception):
    """A save that could not be completed. `errors` lists what to fix."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class Entry:
    """One entry as the form sees it: all the fields a person can edit."""

    name: str = ""
    category: str = "P"
    book: int = 1                      # the book it first appears in
    books: list[int] = field(default_factory=list)  # every book it appears in
    summary: str = ""
    body: str = ""                     # paragraphs separated by blank lines
    story: str = ""
    tip: str = ""

    @property
    def slug(self) -> str:
        return build_db.slug(self.name)


# --- Reading ------------------------------------------------------------------

def load(data_dir: pathlib.Path, name: str) -> Entry | None:
    """Read one entry from the text files, or None if there is no such entry."""
    for n, cat, book, summary, body in build_db.parse(_read(data_dir / "references.txt")):
        if n == name:
            details = build_db.parse_details(_read(data_dir / "details.txt")).get(name, {})
            return Entry(
                name=n, category=cat, book=book, books=details.get("books", [book]),
                summary=summary, body=body, story=details.get("story", ""), tip=details.get("tip", ""),
            )
    return None


def existing_names(data_dir: pathlib.Path) -> list[str]:
    return [n for n, *_ in build_db.parse(_read(data_dir / "references.txt"))]


# --- Cleaning and checking form input -------------------------------------------

def clean(entry: Entry) -> Entry:
    """Tidy what was typed, so small slips do not become errors.

    * Windows line endings become plain newlines.
    * Summary, story and tip are stored one per line in the text files, so any
      line breaks typed into them become spaces.
    * Runs of blank lines in the body become a single blank line, because a
      blank line is what separates paragraphs.
    * The first book is always included in the list of books it appears in.
    """
    def one_line(s: str) -> str:
        return " ".join(s.split())

    body = entry.body.replace("\r\n", "\n").replace("\r", "\n")
    body = "\n".join(line.rstrip() for line in body.split("\n")).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return Entry(
        name=one_line(entry.name),
        category=entry.category,
        book=entry.book,
        books=sorted(set(entry.books) | {entry.book}),
        summary=one_line(entry.summary),
        body=body,
        story=one_line(entry.story),
        tip=one_line(entry.tip),
    )


def validate(entry: Entry, names: list[str], old_name: str | None) -> list[str]:
    """Return a list of problems, in plain words. An empty list means it can be saved.

    Some rules protect the text-file format: "|" separates fields in a header,
    and lines starting with "===" or "#" mean "new entry" and "comment" to the
    parser, so they cannot appear inside an entry's text.
    """
    errors = []
    if not entry.name:
        errors.append("Give the entry a name.")
    elif len(entry.name) > MAX_NAME:
        errors.append(f"Keep the name to {MAX_NAME} characters or fewer.")
    elif "|" in entry.name or entry.name.startswith(("#", "=")):
        errors.append('The name cannot contain "|" or start with "#" or "=".')
    elif not entry.slug:
        errors.append("The name needs at least one letter or number.")
    elif entry.slug in RESERVED_SLUGS:
        errors.append(f'"{entry.name}" is reserved by the Guide. Choose another name.')
    else:
        # Names must be unique, and so must their slugs, because the slug is
        # the entry's web address: "Tea!" and "Tea" would both be /entry/tea.
        others = [n for n in names if n != old_name]
        if any(n.lower() == entry.name.lower() for n in others):
            errors.append(f'There is already an entry called "{entry.name}".')
        elif any(build_db.slug(n) == entry.slug for n in others):
            errors.append(f'The name "{entry.name}" is too close to an existing entry\'s name.')

    if entry.category not in CATEGORY_CODES:
        errors.append("Choose a category.")
    if entry.book not in BOOK_NUMBERS:
        errors.append("Choose the book it first appears in.")
    elif min(entry.books) < entry.book:
        errors.append("The first book must be the earliest book it appears in.")
    if any(b not in BOOK_NUMBERS for b in entry.books):
        errors.append("Choose books from 1 to 6.")

    for label, value in (("summary", entry.summary), ("Guide entry", entry.body),
                         ("story", entry.story), ("tip", entry.tip)):
        if not value:
            errors.append(f"Write the {label}.")
    if entry.summary.startswith(("===", "#")):
        errors.append('The summary cannot start with "===" or "#".')
    for line in entry.body.split("\n"):
        if line.startswith(("===", "#")):
            errors.append('No line in the Guide entry can start with "===" or "#".')
            break
    return errors


# --- Writing --------------------------------------------------------------------

def save(data_dir: pathlib.Path, db_path: pathlib.Path, entry: Entry, old_name: str | None = None) -> Entry:
    """Add a new entry (old_name None) or replace an existing one, then rebuild.

    Raises EntryError with a list of problems if the entry is not valid or the
    rebuild fails. On any failure, every file is restored to how it was.
    """
    data_dir = pathlib.Path(data_dir)
    entry = clean(entry)
    with _lock:
        names = existing_names(data_dir)
        if old_name is not None and old_name not in names:
            raise EntryError([f'There is no entry called "{old_name}" any more.'])
        errors = validate(entry, names, old_name)
        if errors:
            raise EntryError(errors)

        paths = {key: data_dir / f"{key}.txt" for key in ("references", "details", "products")}
        # Keep the original text of every file we touch, to restore on failure.
        backup = {key: _read(path) for key, path in paths.items()}
        renamed_art: tuple[pathlib.Path, pathlib.Path] | None = None
        try:
            _write(paths["references"], _put_block(
                backup["references"], _reference_header_re(old_name), _reference_block(entry)))
            _write(paths["details"], _put_block(
                backup["details"], _details_header_re(old_name), _details_block(entry)))
            if old_name is not None and old_name != entry.name:
                # Products refer to entries by name, so follow the rename there.
                _write(paths["products"], _rename_in_products(backup["products"], old_name, entry.name))
                # Drawings are named by slug; move the file so the drawing stays attached.
                old_art = data_dir / "art" / f"{build_db.slug(old_name)}.svg"
                new_art = data_dir / "art" / f"{entry.slug}.svg"
                if old_art.exists() and old_art != new_art:
                    old_art.rename(new_art)
                    renamed_art = (new_art, old_art)
            build_db.main(db_path, data_dir)
        except Exception as exc:
            for key, path in paths.items():
                _write(path, backup[key])
            if renamed_art:
                renamed_art[0].rename(renamed_art[1])
            if isinstance(exc, EntryError):
                raise
            raise EntryError([f"The Guide could not be rebuilt, so nothing was saved: {exc}"]) from exc
    return entry


def _reference_block(e: Entry) -> str:
    return f"=== {e.name} | {e.category} | {e.book}\n{e.summary}\n\n{e.body}\n"


def _details_block(e: Entry) -> str:
    books = ",".join(str(b) for b in e.books)
    return f"=== {e.name}\nbooks: {books}\nstory: {e.story}\ntip: {e.tip}\n"


def _reference_header_re(name: str | None) -> re.Pattern | None:
    # In references.txt the header is "=== Name | Category | Book".
    return None if name is None else re.compile(r"^=== " + re.escape(name) + r" \|")


def _details_header_re(name: str | None) -> re.Pattern | None:
    # In details.txt the header is just "=== Name".
    return None if name is None else re.compile(r"^=== " + re.escape(name) + r"[ \t]*$")


def _put_block(text: str, header: re.Pattern | None, block: str) -> str:
    """Replace the block whose header matches, or append the block at the end.

    A block runs from its "=== " header line up to the next "=== " line (or the
    end of the file). Working line by line, rather than with one big regular
    expression, keeps this easy to follow and to get right.
    """
    lines = text.split("\n")
    start = None
    if header is not None:
        start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        # New entry: append after one blank line.
        return text.rstrip("\n") + "\n\n" + block
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("=== ")), len(lines))
    before = "\n".join(lines[:start])
    after = "\n".join(lines[end:])
    if after:
        # Keep one blank line between this block and the next one.
        return before + "\n" + block + "\n" + after
    return before + "\n" + block


def _rename_in_products(text: str, old: str, new: str) -> str:
    """Change the entry column (the 5th) of any product line that names `old`."""
    out = []
    for line in text.split("\n"):
        parts = line.split("|")
        if not line.startswith("#") and len(parts) == 6 and parts[4].strip() == old:
            parts[4] = f" {new} "
            line = "|".join(parts)
        out.append(line)
    return "\n".join(out)


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: pathlib.Path, text: str) -> None:
    # newline="\n" keeps Unix line endings on Windows too, matching the files'
    # existing style so version control does not see every line as changed.
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
