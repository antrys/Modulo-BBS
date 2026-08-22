"""Tests for the files plugin."""
import json

import pytest

from core.events import EventBus
from core.user import User
from plugins.files import FilesPlugin
from plugins.files.areas import AreaStore, load_areas


class FakeStorage:
    def __init__(self, root):
        self.root = root

    def dir(self, name):
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        return d


class FakeBBS:
    def __init__(self, root, plugdir):
        self.storage = FakeStorage(root)
        self.events = EventBus()
        self.sent = []
        self.root_plugins = plugdir

    async def send(self, session, text):
        self.sent.append(text)

    def keys_for(self, name, defaults):
        from core.keys import load_keys

        return load_keys(self.root_plugins, name, defaults)


@pytest.fixture
def store(tmp_path):
    return AreaStore(tmp_path / "files")


def test_load_areas_creates_default(tmp_path):
    areas = load_areas(tmp_path)
    assert areas[0]["id"] == "main"
    assert load_areas(tmp_path) == areas  # persisted


def test_add_list_get_delete_roundtrip(store):
    r1 = store.add_file("main", "prog.zip", 1024, "dave", "A program")
    r2 = store.add_file("main", "game.zip", 2048, "alice", "A game")
    assert (r1["id"], r2["id"]) == (1, 2)
    recs = store.list_files("main")
    assert [r["name"] for r in recs] == ["prog.zip", "game.zip"]
    got = store.get_file("main", 2)
    assert got["uploader"] == "alice"
    assert store.delete_file("main", 1) is True
    assert store.get_file("main", 1) is None
    assert store.delete_file("main", 99) is False


def test_plugin_visible_areas_gating(tmp_path):
    bbs = FakeBBS(tmp_path / "data", tmp_path / "plugins")
    pdir = tmp_path / "plugins" / "files"
    pdir.mkdir(parents=True)
    (pdir / "keys").write_text("L, LIST\nQ, QUIT\n", encoding="utf-8")
    plugin = FilesPlugin()
    plugin.on_load(bbs)
    plugin.areas = [
        {"id": "main", "name": "Main", "requires": []},
        {"id": "vip", "name": "VIP", "requires": ["veterans"]},
    ]
    plain = User(username="j", display_name="", password_hash="x")
    vet = User(username="v", display_name="", password_hash="x",
               groups=["user", "veterans"])
    assert [a["id"] for a in plugin.visible_areas(plain)] == ["main"]
    assert {a["id"] for a in plugin.visible_areas(vet)} == {"main", "vip"}


def test_can_delete_own_vs_moderator(store):
    store.add_file("main", "x.zip", 10, "joe", "")
    joe = User(username="joe", display_name="", password_hash="x")
    mallory = User(username="m", display_name="", password_hash="x")
    mod = User(username="mod", display_name="", password_hash="x",
               groups=["user", "moderator"])
    rec = store.get_file("main", 1)
    assert store.can_delete(joe, rec) is True      # own upload
    assert store.can_delete(mallory, rec) is False
    assert store.can_delete(mod, rec) is True      # moderator group


def test_plugin_menu_metadata(tmp_path):
    bbs = FakeBBS(tmp_path / "data", tmp_path / "plugins")
    plugin = FilesPlugin()
    plugin.on_load(bbs)
    assert (plugin.menu_key, plugin.name) == ("F", "files")
