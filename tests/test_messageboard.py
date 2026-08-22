"""Tests for the messageboard plugin (storage + gating + plugin wiring)."""
import json

import pytest

from core.events import EventBus
from core.storage import PluginStorage
from core.user import User
from plugins.messageboard import MessageBoardPlugin
from plugins.messageboard.boards import BoardStore, can_delete, load_boards


@pytest.fixture
def store(tmp_path):
    return BoardStore(tmp_path / "messageboard")


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


def _plugin(tmp_path):
    bbs = FakeBBS(tmp_path / "data", tmp_path / "plugins")
    pdir = tmp_path / "plugins" / "messageboard"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "keys").write_text("L, LIST\nP, POST\nQ, QUIT\n", encoding="utf-8")
    plugin = MessageBoardPlugin()
    plugin.on_load(bbs)
    return bbs, plugin


# -- storage -----------------------------------------------------------------

def test_add_list_delete_roundtrip(store):
    m1 = store.add_message("general", "dave", "Hello", "first post")
    m2 = store.add_message("general", "alice", "Re: Hello", "hi back")
    assert m1["id"] == 1 and m2["id"] == 2
    msgs = store.list_messages("general")
    assert [m["id"] for m in msgs] == [1, 2]
    assert msgs[0]["author"] == "dave"
    assert store.delete_message("general", 1) is True
    assert [m["id"] for m in store.list_messages("general")] == [2]
    assert store.get_message("general", 1) is None


def test_delete_missing_message_returns_false(store):
    assert store.delete_message("general", 99) is False


def test_timestamp_present(store):
    m = store.add_message("general", "a", "s", "b")
    assert "timestamp" in m and len(m["timestamp"]) > 10


# -- boards config -------------------------------------------------------------

def test_load_boards_creates_default(tmp_path):
    boards = load_boards(tmp_path)
    assert boards[0]["id"] == "general"
    # persisted for the next load
    again = load_boards(tmp_path)
    assert again == boards


def test_visible_boards_respects_requires(tmp_path):
    bbs, plugin = _plugin(tmp_path)
    plugin.boards = [
        {"id": "general", "name": "General", "requires": []},
        {"id": "vip", "name": "VIP", "requires": ["veterans"]},
    ]
    plain = User(username="joe", display_name="", password_hash="x")
    vet = User(username="v", display_name="", password_hash="x",
               groups=["user", "veterans"])
    assert [b["id"] for b in plugin.visible_boards(plain)] == ["general"]
    assert {b["id"] for b in plugin.visible_boards(vet)} == {"general", "vip"}


def test_plugin_wiring_on_load(tmp_path):
    bbs, plugin = _plugin(tmp_path)
    assert plugin.name == "messageboard"
    assert plugin.menu_key == "M"
    assert plugin.keys.get("QUIT") == "Q"   # loaded via keys file


# -- delete permission -----------------------------------------------------------

def test_can_delete_own_message():
    u = User(username="joe", display_name="", password_hash="x")
    msg = {"author": "joe"}
    assert can_delete(u, msg) is True


def test_cannot_delete_others_without_mod():
    u = User(username="mallory", display_name="", password_hash="x")
    msg = {"author": "joe"}
    assert can_delete(u, msg) is False


def test_moderator_group_can_delete_any():
    mod = User(username="m", display_name="", password_hash="x",
               groups=["user", "moderator"])
    msg = {"author": "joe"}
    assert can_delete(mod, msg) is True
