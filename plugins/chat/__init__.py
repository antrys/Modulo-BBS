"""Inter-node chat for Modulo BBS.

Design (modern take on the classic teleconferencing channel):
- One global channel; every participant sees every line as it is typed
- Lines are broadcast via the event bus ("chat:message"), so the chat
  plugin itself never touches other sessions' writers -- each session's
  own input loop picks up bus messages addressed to it
- Exit via /quit (flow-owned exit convention per spec)
"""
from __future__ import annotations

import asyncio

from plugins.base import Plugin

DEFAULT_KEYS = {"QUIT": "Q"}


class ChatHub:
    """Routes chat lines from the bus to every listening session."""

    def __init__(self):
        self.listeners: dict[int, dict] = {}  # session_id -> {name, queue}

    def join(self, session, display_name) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.listeners[id(session)] = {"name": display_name, "queue": q}
        return q

    def leave(self, session) -> str | None:
        info = self.listeners.pop(id(session), None)
        return info["name"] if info else None

    async def broadcast(self, sender_session, text: str) -> None:
        dead = []
        for sid, info in self.listeners.items():
            try:
                info["queue"].put_nowait(text)
            except Exception:
                dead.append(sid)
        for sid in dead:
            self.listeners.pop(sid, None)

    def names(self) -> list[str]:
        return [i["name"] for i in self.listeners.values()]


HUB = ChatHub()  # process-wide: one chat room across all sessions/nodes


class ChatPlugin(Plugin):
    name = "chat"
    version = "1.0.0"
    description = "Inter-node chat"
    menu_label = "[C] Chat"
    menu_key = "C"
    menu_order = 50

    def __init__(self):
        self.bbs = None
        self.keys = dict(DEFAULT_KEYS)

    def on_load(self, bbs):
        self.bbs = bbs
        self.keys = bbs.keys_for("chat", DEFAULT_KEYS)
        bbs.events.on("chat:message", self._on_chat_message)

    def _on_chat_message(self, data):
        # Bus handler: fan the line out to all listeners' queues.
        import asyncio

        loop = asyncio.get_event_loop()
        loop.create_task(HUB.broadcast(None, str(data.get("text", ""))))

    def _broadcast(self, text: str) -> None:
        """Synchronous fire-and-forget broadcast helper."""
        import asyncio

        asyncio.get_event_loop().create_task(HUB.broadcast(None, text))

    async def on_session_start(self, session) -> bool:
        user = getattr(session, "user", None)
        name = user.shown_name() if user else "Guest"
        quit_k = self._k("QUIT")

        my_queue = HUB.join(session, name)
        self._broadcast(f"*** {name} has joined the chat ***")
        await self.bbs.send(
            session,
            "\r\n=== Chat ===\r\n"
            f"Type messages and press Enter. /{quit_k.lower()} or "
            f"{quit_k} to leave.\r\n"
            f"In chat: {', '.join(HUB.names())}\r\n\r\n",
        )
        self.bbs.events.emit("chat:join", {"session": session, "who": name})

        reader = getattr(session, "reader", None)
        try:
            while getattr(session, "is_active", True):
                # Drain any queued chat lines first (never cancel a pending
                # get() -- cancelling loses the item it was waiting on).
                while not my_queue.empty():
                    msg = my_queue.get_nowait()
                    await self.bbs.send(session, "\r" + msg + "\r\n")

                line_raw = await self._read_line(session)
                raw = line_raw if isinstance(line_raw, bytes) else (line_raw or "").encode("latin-1")
                line = (raw.decode("latin-1", errors="replace")
                        .strip("\r\n").strip())
                cmd = line.upper()
                if not cmd:
                    continue
                quit_forms = {f"/{quit_k.lower()}", f"/{quit_k}", quit_k}
                if cmd in quit_forms:
                    raise _LeaveChat()
                self._broadcast(f"<{name}> {line}")
                # Give broadcasts a moment to land in our own queue too.
                await asyncio.sleep(0)
                while not my_queue.empty():
                    msg = my_queue.get_nowait()
                    await self.bbs.send(session, "\r" + msg + "\r\n")
        except _LeaveChat:
            pass
        finally:
            left = HUB.leave(session)
            if left:
                self._broadcast(f"*** {left} has left the chat ***")
            await self.bbs.send(session, "\r\nLeft chat.\r\n")
        self.bbs.events.emit("chat:leave", {"session": session, "who": name})
        return False

    async def handle_command(self, session, command) -> bool:
        return (command or "").strip().upper() != self._k("QUIT")

    def _k(self, name: str) -> str:
        return self.keys.get(name, "?")

    async def _read_line(self, session):
        reader = getattr(session, "reader", None)
        if reader is None:
            await asyncio.sleep(3600)
            return ""
        return await reader.readline()


class _LeaveChat(Exception):
    pass


__all__ = ["ChatPlugin", "ChatHub"]
