"""Tests for the bulletins plugin."""
import json

import pytest

from core.events import EventBus
from core.storage import PluginStorage
from core.user import User
from plugins.bulletins import BulletinsPlugin


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
    def __init__(self, root):
        self.storage = FakeStorage(root)
        self.events = EventBus()
        self.sent = []

    async def send(self, session, text):
        self.sent.append(text)

    def keys_for(self, name, defaults):
        from core.keys import load_keys
        return load_keys(self.root_plugins, name, defaults)


class FakeSession:
    def __init__(self, user, inputs=None, height=24):
        self.user = user
        self.is_active = True
        self.terminal_height = height
        self.username = user.username if user else "anon"
        import asyncio
        self.reader = None
        self._inputs = list(inputs or [])


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "data"
    bbs = FakeBBS(root)
    # keys file location expected by keys_for: <root>/../plugins/... — instead
    # point loader at a plugins dir we create under tmp for determinism.
    plugdir = tmp_path / "plugins" / "bulletins"
    plugdir.mkdir(parents=True)
    (plugdir / "keys").write_text("N, NEXT\nP, PREVIOUS\nQ, QUIT\n", encoding="utf-8")
    bbs.root_plugins = tmp_path / "plugins"

    plugin = BulletinsPlugin()
    plugin.on_load(bbs)
    # sample content
    cdir = root / "bulletins" / "bulletins"
    (cdir / "01-welcome.txt").write_text("Welcome!\r\nEnjoy.\r\n", encoding="utf-8")
    (cdir / "02-rules.txt").write_text(
        "Rules:\r\n" + ("line\r\n" * 40), encoding="utf-8"
    )  # long -> pager path
    meta = {"title": "Secret Ops", "requires": ["sysop"]}
    (cdir / "03-secret.txt").write_text("hidden\r\n", encoding="utf-8")
    (cdir / "03-secret.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return bbs, plugin


def test_scan_titles_and_meta(env):
    bbs, plugin = env
    cats = {b["id"]: b for b in plugin.scan()}
    assert cats["01-welcome"]["title"] == "01-welcome"      # no meta -> filename
    assert cats["02-rules"]["requires"] == []
    assert cats["03-secret"]["title"] == "Secret Ops"
    assert cats["03-secret"]["requires"] == ["sysop"]


def test_visible_for_gates_by_group(env):
    bbs, plugin = env
    plain = User(username="joe", display_name="", password_hash="x")
    boss = User(username="sys", display_name="", password_hash="x",
                groups=["user", "sysop"])
    ids_plain = {b["id"] for b in plugin.visible_for(plain)}
    assert "01-welcome" in ids_plain and "03-secret" not in ids_plain
    assert "03-secret" in {b["id"] for b in plugin.visible_for(boss)}


def test_unseen_mark_seen_roundtrip(env):
    bbs, plugin = env
    u = User(username="joe", display_name="", password_hash="x")
    before = plugin.unseen(u)
    assert "01-welcome" in before and "02-rules" in before
    plugin.mark_seen(u, ["01-welcome"])
    after = plugin.unseen(u)
    assert "01-welcome" not in after
    # persisted
    seen = json.loads((bbs.storage.dir("bulletins") / "seen.json").read_text())
    assert seen["joe"] == ["01-welcome"]


def test_logon_step_shows_unseen_and_marks_seen(env):
    bbs, plugin = env
    u = User(username="kate", display_name="", password_hash="x")
    s = FakeSession(u)
    import asyncio
    asyncio.run(plugin.on_session_start(s))
    out = "".join(bbs.sent)
    assert "Welcome!" in out and "Rules:" in out
    # now everything visible is marked seen
    assert plugin.unseen(u) == []


def test_manual_read_does_not_mark_seen(env):
    bbs, plugin = env
    u = User(username="mike", display_name="", password_hash="x")
    s = FakeSession(u)
    import asyncio
    asyncio.run(plugin.run_menu(s))  # Q immediately (no reader -> empty input quits)
    assert plugin.unseen(u) != []     # untouched


def test_events_fire_on_display(env):
    bbs, plugin = env
    u = User(username="ann", display_name="", password_hash="x")
    fired = []
    bbs.events.on("bulletins:read", lambda data: fired.append(data["id"]))
    s = FakeSession(u)
    import asyncio
    asyncio.run(plugin.on_session_start(s))
    assert "01-welcome" in fired and "02-rules" in fired
