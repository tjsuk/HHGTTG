"""Shared fixtures: build a fresh database once per test run and point the app at it.

pytest loads conftest.py automatically. A *fixture* is a function that prepares
something a test needs; a test asks for it by naming it as a parameter, e.g.
`def test_pages_load(client): ...`. pytest calls the fixture and passes in the result.

Why the tests build their own database: they check the data files as they are
now (including edits not yet built), and they never overwrite data/guide.db.
"""
import importlib.util
import pathlib
import sqlite3
import sys

import pytest

# The project folder. Adding it to sys.path lets the tests `import app` no
# matter which folder pytest was started from.
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_build_db():
    """Import data/build_db.py by file path.

    data/ is a plain folder of data files, not a Python package, so a normal
    `import data.build_db` would not work. importlib loads the file directly.
    """
    spec = importlib.util.spec_from_file_location("build_db", ROOT / "data" / "build_db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def build_db():
    """The data/build_db.py module, loaded once for the whole run."""
    return _load_build_db()


@pytest.fixture(scope="session")
def db_path(build_db, tmp_path_factory):
    """A database built from the current data files into a temporary folder.

    scope="session" builds it once and shares it across all tests, which keeps
    the suite fast. That is safe because the app opens it read-only.
    """
    return build_db.main(tmp_path_factory.mktemp("db") / "guide.db")


@pytest.fixture()
def con(db_path):
    """A direct connection for tests that query the database themselves.

    Code after `yield` runs when the test finishes, so the connection is always
    closed, even if the test fails.
    """
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


@pytest.fixture()
def app(db_path, monkeypatch):
    """The app module, pointed at the test database.

    monkeypatch swaps app.DB_PATH for this test only and puts it back afterwards,
    so tests cannot affect each other or the real database. This works because
    app.db() reads DB_PATH each time it opens a connection.
    """
    import app as guide_app

    monkeypatch.setattr(guide_app, "DB_PATH", str(db_path))
    # TESTING makes Flask report errors to the test instead of returning a 500 page.
    guide_app.app.config.update(TESTING=True)
    return guide_app


@pytest.fixture()
def client(app):
    """A fake browser: client.get("/index") runs the route without starting a server."""
    return app.app.test_client()
