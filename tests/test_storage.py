"""Tests for core.storage.PluginStorage (bbs.storage).

Covers data-directory creation, the default plugins/ root, custom roots,
and rejection of unsafe plugin names (traversal, absolute paths, bad
characters). Self-contained: asyncio.run per test, no pytest-asyncio.
"""

import tempfile
from pathlib import Path

import pytest

from core.app import BBSApp
from core.storage import PluginStorage, StorageError


def test_dir_creates_plugin_data_directory():
    with tempfile.TemporaryDirectory() as tmp:
        ps = PluginStorage(tmp)
        d = ps.dir("messageboard")
        assert d == Path(tmp) / "messageboard" / "data"
        assert d.is_dir()


def test_dir_is_lazy_but_stable():
    """Repeated calls return the same path and never clobber content."""
    with tempfile.TemporaryDirectory() as tmp:
        ps = PluginStorage(tmp)
        first = ps.dir("myplugin")
        (first / "boards.json").write_text("{}", encoding="utf-8")
        second = ps.dir("myplugin")
        assert first == second
        assert (second / "boards.json").exists()


def test_default_root_is_project_plugins_dir():
    ps = PluginStorage()
    expected = Path(__file__).resolve().parent.parent / "plugins"
    assert ps.plugins_dir == expected


def test_rejects_traversal_and_bad_names():
    ps = PluginStorage(tempfile.gettempdir())
    for bad in ("../evil", "foo/bar", "", "MessageBoard", "a b", "..", "."):
        with pytest.raises(StorageError):
            ps.dir(bad)


def test_bbs_app_exposes_storage():
    with tempfile.TemporaryDirectory() as tmp:
        app = BBSApp(users_dir=Path(tmp) / "users")
        d = app.storage.dir("login")
        assert d.name == "data"
        assert d.parent.name == "login"
