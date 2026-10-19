"""Tests for adding and editing entries (editor.py and the /entry/new and /edit routes).

Every test here works on a private copy of the data folder, so the real
data files and database are never changed, however a test goes.
"""
import re
import shutil

import pytest

import editor


@pytest.fixture()
def workspace(tmp_path, build_db):
    """A copy of data/ (without the built database) plus a database built from it."""
    data = tmp_path / "data"
    shutil.copytree(build_db.HERE, data, ignore=shutil.ignore_patterns("*.db", "*.tmp", "__pycache__"))
    db = build_db.main(tmp_path / "guide.db", data)
    return data, db


@pytest.fixture()
def edit_client(app, workspace, monkeypatch):
    """A test client whose app reads and writes the private copy."""
    data, db = workspace
    monkeypatch.setattr(app, "DATA_DIR", str(data))
    monkeypatch.setattr(app, "DB_PATH", str(db))
    monkeypatch.setattr(app, "EDITING", "local")
    return app.app.test_client()


def form_for(client, path):
    """Load a form page and return its fields' current values, CSRF token included.

    Reading the values back from the rendered page (rather than building them by
    hand) also checks that the form shows what is stored."""
    page = client.get(path).get_data(as_text=True)
    values = {"csrf": re.search(r'name="csrf" value="([^"]+)"', page).group(1)}
    for name in ("name", "summary", "tip"):
        m = re.search(rf'name="{name}" value="([^"]*)"', page)
        values[name] = m.group(1).replace("&#39;", "'").replace("&amp;", "&") if m else ""
    for name in ("body", "story"):
        m = re.search(rf'name="{name}"[^>]*>(.*?)</textarea>', page, re.S)
        values[name] = m.group(1).replace("&#39;", "'").replace("&amp;", "&") if m else ""
    values["category"] = re.search(r'<option value="(\w)" selected', page).group(1) if 'selected' in page else "P"
    book = re.search(r'name="book">\s*(?:<option[^>]*>[^<]*</option>\s*)*?<option value="(\d)" selected', page)
    values["book"] = book.group(1) if book else "1"
    values["books"] = re.findall(r'name="books" value="(\d)" checked', page)
    return values


NEW = {
    "name": "Zarquon's Singing Fish",
    "category": "S",
    "book": "2",
    "books": ["2", "3"],
    "summary": "A fish that sings at Milliways, badly.",
    "body": "A small fish with a large voice.\n\n\n\nIt knows one song about Marvin.",
    "story": "It is not\nin the books at all.",
    "tip": "Bring earplugs.",
}


# --- Adding --------------------------------------------------------------------

def test_add_entry_writes_files_and_rebuilds(edit_client, workspace):
    data, _ = workspace
    token = form_for(edit_client, "/entry/new")["csrf"]
    response = edit_client.post("/entry/new", data={**NEW, "csrf": token})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/entry/zarquon-s-singing-fish")

    page = edit_client.get("/entry/zarquon-s-singing-fish").get_data(as_text=True)
    assert "Added Zarquon&#39;s Singing Fish to the Guide." in page
    assert "A small fish with a large voice." in page
    # The new entry's text names Marvin, so the build links it up.
    assert 'class="xref" href="/entry/marvin"' in page

    refs = (data / "references.txt").read_text(encoding="utf-8")
    assert "=== Zarquon's Singing Fish | S | 2\nA fish that sings at Milliways, badly.\n\n" in refs
    # Extra blank lines between paragraphs were reduced to one.
    assert "large voice.\n\nIt knows" in refs
    details = (data / "details.txt").read_text(encoding="utf-8")
    # The line break typed into the story became a space, because story is one line.
    assert "=== Zarquon's Singing Fish\nbooks: 2,3\nstory: It is not in the books at all.\ntip: Bring earplugs.\n" in details


def test_new_entry_name_is_prefilled_from_search(edit_client):
    page = edit_client.get("/entry/new?name=Hrung").get_data(as_text=True)
    assert 'name="name" value="Hrung"' in page


def test_first_book_is_always_in_the_books_list(edit_client, workspace):
    data, _ = workspace
    token = form_for(edit_client, "/entry/new")["csrf"]
    edit_client.post("/entry/new", data={**NEW, "books": [], "csrf": token})
    assert "books: 2\n" in (data / "details.txt").read_text(encoding="utf-8")


# --- Editing -------------------------------------------------------------------

def test_edit_form_shows_current_values(edit_client):
    values = form_for(edit_client, "/entry/marvin/edit")
    assert values["name"] == "Marvin"
    assert values["category"] == "P"
    assert values["books"] == ["1", "2", "3", "4"]
    assert "brain the size of a planet" in values["body"]


def test_edit_changes_only_that_entry(edit_client, workspace):
    data, _ = workspace
    before = (data / "references.txt").read_text(encoding="utf-8")
    values = form_for(edit_client, "/entry/marvin/edit")
    values["summary"] = "A robot with feelings, mostly bad ones."
    response = edit_client.post("/entry/marvin/edit", data=values)
    assert response.status_code == 302

    after = (data / "references.txt").read_text(encoding="utf-8")
    assert "A robot with feelings, mostly bad ones." in after
    # Every other line of the file is unchanged.
    changed = [line for line in after.split("\n") if line not in before.split("\n")]
    assert changed == ["A robot with feelings, mostly bad ones."]
    page = edit_client.get("/entry/marvin").get_data(as_text=True)
    assert "Saved your changes to Marvin." in page


def test_rename_follows_through_products_and_art(edit_client, workspace):
    data, _ = workspace
    values = form_for(edit_client, "/entry/marvin/edit")
    values["name"] = "Marvin the Paranoid Android"
    response = edit_client.post("/entry/marvin/edit", data=values)
    assert response.headers["Location"].endswith("/entry/marvin-the-paranoid-android")

    assert edit_client.get("/entry/marvin").status_code == 404
    page = edit_client.get("/entry/marvin-the-paranoid-android").get_data(as_text=True)
    assert "A Marvin figure" in page  # the product followed the rename
    assert (data / "art" / "marvin-the-paranoid-android.svg").exists()  # so did the drawing
    assert not (data / "art" / "marvin.svg").exists()
    assert "Marvin the Paranoid Android" in (data / "details.txt").read_text(encoding="utf-8")


def test_editing_a_missing_entry_is_404(edit_client):
    assert edit_client.get("/entry/no-such-thing/edit").status_code == 404


# --- Validation ------------------------------------------------------------------

@pytest.mark.parametrize(
    "changes, message",
    [
        ({"name": ""}, "Give the entry a name."),
        ({"name": "Marvin"}, "There is already an entry called"),
        ({"name": "marvin"}, "There is already an entry called"),
        ({"name": "Heart-of-Gold"}, "too close to an existing entry"),
        ({"name": "A | B"}, 'cannot contain "|"'),
        ({"name": "New"}, "reserved by the Guide"),
        ({"category": "X"}, "Choose a category."),
        ({"book": "9"}, "Choose the book it first appears in."),
        ({"book": "3", "books": ["2", "3"]}, "first book must be the earliest"),
        ({"summary": ""}, "Write the summary."),
        ({"tip": "  "}, "Write the tip."),
        ({"body": "Fine.\n\n=== Sneaky | P | 1"}, 'can start with "===" or "#"'),
        ({"body": "Fine.\n# not a comment"}, 'can start with "===" or "#"'),
    ],
)
def test_invalid_entries_are_rejected_and_nothing_changes(edit_client, workspace, changes, message):
    data, _ = workspace
    before = {p.name: p.read_text(encoding="utf-8") for p in data.glob("*.txt")}
    token = form_for(edit_client, "/entry/new")["csrf"]
    response = edit_client.post("/entry/new", data={**NEW, **changes, "csrf": token})
    assert response.status_code == 400
    page = response.get_data(as_text=True)
    assert "The entry was not saved." in page
    assert message.replace("'", "&#39;").replace('"', "&#34;") in page or message in page
    # What was typed is kept in the form.
    assert "Bring earplugs." in page or changes.get("tip") is not None
    after = {p.name: p.read_text(encoding="utf-8") for p in data.glob("*.txt")}
    assert after == before


def test_failed_rebuild_restores_every_file(workspace, monkeypatch):
    data, db = workspace
    before = {p.name: p.read_text(encoding="utf-8") for p in data.glob("*.txt")}
    art_before = sorted(p.name for p in (data / "art").iterdir())

    def broken_build(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(editor.build_db, "main", broken_build)
    entry = editor.load(data, "Marvin")
    entry.name = "Marvin Renamed"
    with pytest.raises(editor.EntryError, match="nothing was saved"):
        editor.save(data, db, entry, "Marvin")

    assert {p.name: p.read_text(encoding="utf-8") for p in data.glob("*.txt")} == before
    assert sorted(p.name for p in (data / "art").iterdir()) == art_before


# --- Unit tests for the file-editing helpers -----------------------------------------

def test_put_block_replaces_middle_block():
    text = "# head\n\n=== A\nold a\n\n=== B\nb\n"
    out = editor._put_block(text, editor._details_header_re("A"), "=== A\nnew a\n")
    assert out == "# head\n\n=== A\nnew a\n\n=== B\nb\n"


def test_put_block_replaces_last_block():
    text = "=== A\na\n\n=== B\nold b\n"
    out = editor._put_block(text, editor._details_header_re("B"), "=== B\nnew b\n")
    assert out == "=== A\na\n\n=== B\nnew b\n"


def test_put_block_appends_new_block():
    out = editor._put_block("=== A\na\n", None, "=== B\nb\n")
    assert out == "=== A\na\n\n=== B\nb\n"


def test_header_match_needs_the_whole_name():
    # "Marvin" must not match the header of "Marvin the Paranoid Android".
    assert not editor._details_header_re("Marvin").match("=== Marvin the Paranoid Android")
    assert not editor._reference_header_re("Marvin").match("=== Marvin the Paranoid Android | P | 1")
    assert editor._reference_header_re("Marvin").match("=== Marvin | P | 1")


def test_rename_in_products_only_touches_the_entry_column():
    text = "# kind | title | search | book | entry | desc\nextra | Marvin toy | Marvin | - | Marvin | A Marvin.\n"
    out = editor._rename_in_products(text, "Marvin", "Marvin II")
    assert out == "# kind | title | search | book | entry | desc\nextra | Marvin toy | Marvin | - | Marvin II | A Marvin.\n"


# --- Protection ------------------------------------------------------------------

def test_post_without_csrf_token_is_rejected(edit_client, workspace):
    data, _ = workspace
    before = (data / "references.txt").read_text(encoding="utf-8")
    response = edit_client.post("/entry/new", data=NEW)
    assert response.status_code == 400
    assert "The form expired" in response.get_data(as_text=True)
    assert (data / "references.txt").read_text(encoding="utf-8") == before


def test_post_with_wrong_csrf_token_is_rejected(edit_client):
    form_for(edit_client, "/entry/new")  # puts a real token in the session
    assert edit_client.post("/entry/new", data={**NEW, "csrf": "forged"}).status_code == 400


def test_editing_from_another_computer_is_refused(edit_client):
    other = {"REMOTE_ADDR": "203.0.113.9"}
    assert edit_client.get("/entry/new", environ_base=other).status_code == 403
    assert edit_client.get("/entry/marvin/edit", environ_base=other).status_code == 403
    page = edit_client.get("/entry/marvin", environ_base=other).get_data(as_text=True)
    assert "/entry/marvin/edit" not in page  # no Edit link either


def test_editing_switched_off(edit_client, app, monkeypatch):
    monkeypatch.setattr(app, "EDITING", "off")
    assert edit_client.get("/entry/new").status_code == 403
    assert "Add an entry" not in edit_client.get("/index").get_data(as_text=True)


def test_editing_switched_on_allows_other_computers(edit_client, app, monkeypatch):
    monkeypatch.setattr(app, "EDITING", "on")
    assert edit_client.get("/entry/new", environ_base={"REMOTE_ADDR": "203.0.113.9"}).status_code == 200
