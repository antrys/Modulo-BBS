"""Tests for the chat plugin."""
import asyncio
import json

import pytest

from core.events import EventBus
from core.user import User
from plugins.chat import ChatHub, ChatPlugin


class FakeStorage:
    def __init__(self, root):
        self.root = root

    def dir(self, name):
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        return d


class FakeBBS:
    def __init__(self, tmp_path):
        self.storage = FakeStorage(tmp_path)
        self.events = EventBus()
        self.sent = []
        self.root_plugins = tmp_path / "plugins"

    async def send(self, session, text):
        self.sent.append(text)

    def keys_for(self, name, defaults):
        from core.keys import load_keys

        return load_keys(self.root_plugins, name, defaults)


class FakeSession:
    def __init__(self, user, lines=None):
        self.user = user
        self.is_active = True
        self.terminal_height = 24
        self._lines = list(lines or [])
        # Build the reader ONCE; repeated accesses must see the same stream.
        q: asyncio.Queue = asyncio.Queue()
        for ln in self._lines:
            q.put_nowait(ln.encode("latin-1") + b"\n")
        self._reader = _QReader(q)

    @property
    def reader(self):
        return self._reader


class _QReader:
    def __init__(self, q):
        self.q = q

    async def readline(self):
        return await self.q.get()


def _plugin(tmp_path):
    pdir = tmp_path / "plugins" / "chat"
    pdir.mkdir(parents=True)
    (pdir / "keys").write_text("Q, QUIT\n", encoding="utf-8")
    bbs = FakeBBS(tmp_path)
    plugin = ChatPlugin()
    plugin.on_load(bbs)
    return bbs, plugin


def test_hub_join_leave_broadcast():
    hub = ChatHub()

    class S:
        pass

    a, b = S(), S()
    qa = hub.join(a, "Alice")
    hub.join(b, "Bob")
    assert sorted(hub.names()) == ["Alice", "Bob"]
    asyncio.run(hub.broadcast(a, "<Alice> hi"))
    assert qa.qsize() == 1
    left = hub.leave(a)
    assert left == "Alice"
    assert hub.names() == ["Bob"]


def test_chat_flow_join_say_leave_events(tmp_path):
    bbs, plugin = _plugin(tmp_path)
    u = User(username="joe", display_name="", password_hash="x")
    s = FakeSession(u, lines=["hello world", "/q"])
    events = []
    bbs.events.on("chat:join", lambda d: events.append(d["who"]))
    asyncio.run(plugin.on_session_start(s))
    out = "".join(bbs.sent)
    assert "has joined the chat" in out or "=== Chat ===" in out
    assert "Left chat." in out
    assert "joe" in events


def test_quit_via_slash_and_key(tmp_path):
    bbs, plugin = _plugin(tmp_path)
    u = User(username="kate", display_name="", password_hash="x")
    # '/q' ends the flow; plain 'Q' also recognized as quit key
    for exit_line in ("/q", "Q"):
        s = FakeSession(u, lines=[exit_line])
        asyncio.run(plugin.on_session_start(s))
        assert any("Left chat." in t for t in bbs.sent)


def test_message_broadcast_reaches_listener_queue(tmp_path):
    bbs, plugin = _plugin(tmp_path)

    u1 = User(username="ann", display_name="", password_hash="x")

    class SlowSession(FakeSession):
        """Ann stays in chat (slow first line) until bob's message lands."""

        async def _wait(self):
            await asyncio.sleep(0.15)

    s1 = SlowSession(u1, lines=["hi bob", "/q"])
    # Wrap the plugin's read to pause first, simulating a human thinking.
    orig_read = plugin._read_line

    async def slow_read(session):
        await asyncio.sleep(0.1)
        return await orig_read(session)

    plugin._read_line = slow_read

    events = []
    bbs.events.on("chat:message",
                  lambda d: events.append(d["text"]))

    async def scenario():
        task = asyncio.ensure_future(plugin.on_session_start(s1))
        await asyncio.sleep(0.05)   # ann is now inside chat, blocked on read
        bbs.events.emit("chat:message", {"text": "<Bob> hey ann"})
        try:
            await asyncio.wait_for(task, timeout=3)
        except asyncio.TimeoutError:
            pass

    asyncio.run(scenario())
    out = "".join(bbs.sent)
    assert "hey ann" in out
