"""Tests for the doors plugin."""
import json

import pytest

from core.events import EventBus
from core.storage import PluginStorage
from core.user import User
from plugins.doors import DoorsPlugin


class FakeStorage:
    def __init__(self, root):
        self.root = root
        self._made = set()

    def dir(self, name):
        d = self.root / name
        if name not in self._made:
            d.mkdir(parents=True, exist_ok=True)
            self._made.add(name)
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


def _make_plugin(tmp_path, catalog, keys_text):
    root = tmp_path / "data"
    bbs = FakeBBS(root, tmp_path / "plugins")
    d = bbs.storage.dir("doors")
    (d / "doors.json").write_text(json.dumps(catalog), encoding="utf-8")
    pdir = tmp_path / "plugins" / "doors"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "keys").write_text(keys_text, encoding="utf-8")
    plugin = DoorsPlugin()
    plugin.on_load(bbs)
    return bbs, plugin


def test_catalog_sample_created_when_missing(tmp_path):
    bbs = FakeBBS(tmp_path / "d1", tmp_path / "p1")
    plugin = DoorsPlugin()
    plugin.on_load(bbs)
    cj = bbs.storage.dir("doors") / "doors.json"
    assert cj.exists() and len(plugin.catalog) >= 1


def test_keys_map_and_unknown_door_skipped(tmp_path):
    catalog = [
        {"id": "tradewars", "name": "TW", "requires": []},
        {"id": "lord", "name": "LORD", "requires": []},
    ]
    keys = "T, tradewars\nX, nosuchdoor\n"
    bbs, plugin = _make_plugin(tmp_path, catalog, keys)
    # unknown door id skipped; tradewars bound
    assert plugin.keys == {"T": "tradewars"}
    assert plugin.door_by_id("lord") is not None  # in catalog but unbound


def test_disabled_by_omission_hides_door(tmp_path):
    catalog = [
        {"id": "tradewars", "name": "TW", "requires": []},
        {"id": "lord", "name": "LORD", "requires": []},
    ]
    # lord omitted from keys -> hidden even though in catalog
    bbs, plugin = _make_plugin(tmp_path, catalog, "T, tradewars\n")
    plain = User(username="joe", display_name="", password_hash="x")
    vis = [d["id"] for d in plugin.visible_doors(plain)]
    assert vis == ["tradewars"]


def test_group_gate_hides_door(tmp_path):
    catalog = [{"id": "vip", "name": "VIP Room", "requires": ["veterans"]}]
    bbs, plugin = _make_plugin(tmp_path, catalog, "V, vip\n")
    plain = User(username="j", display_name="", password_hash="x")
    vet = User(username="v", display_name="", password_hash="x",
               groups=["user", "veterans"])
    assert plugin.visible_doors(plain) == []
    assert [d["id"] for d in plugin.visible_doors(vet)] == ["vip"]


def test_launch_event_fires(tmp_path):
    catalog = [{"id": "tw", "name": "TW", "requires": []}]
    bbs, plugin = _make_plugin(tmp_path, catalog, "T, tw\n")
    fired = []
    bbs.events.on("doors:launch", lambda data: fired.append(data["door_id"]))

    class S:
        is_active = True
        user = User(username="x", display_name="", password_hash="x")

    import asyncio

    asyncio.run(plugin._launch(S(), {"id": "tw", "name": "TW"}))
    assert fired == ["tw"]
