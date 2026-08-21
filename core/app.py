"""Application object for Modulo BBS core.

The ``BBSApp`` is the central object that the transport server and every
plugin share. It owns the core services (event bus, user manager, session
manager), the list of loaded plugins, and a reference to the running server
so it can push bytes to a session (via ``bbs.send``). Plugins receive this
object from ``Plugin.on_load(bbs)``.

Per the plugin spec the plugin exposes the bus and manager as ``bbs.events``
and ``bbs.users``; the longer ``event_bus`` / ``user_manager`` / ``session_manager``
attribute names are kept on the same object for clarity.
"""

from __future__ import annotations

from typing import Any

from core.events import EventBus
from core.user import UserManager
from server.session import Session, SessionManager


class BBSApp:
    """Core application object shared by the server and all plugins."""

    def __init__(self, max_nodes: int = 8, users_dir=None, plugins=None):
        self.event_bus = EventBus()
        self.session_manager = SessionManager(max_nodes)
        self.user_manager = UserManager(users_dir)
        self.plugins: list[Any] = list(plugins) if plugins else []
        # Reference to the running transport server (telnet/SSH). Set when
        # the server is constructed so ``send`` can reuse its transport logic.
        self.server: Any = None

    # -- convenience aliases used by plugins -------------------------------

    @property
    def events(self) -> EventBus:
        """Plugins fire/subscribe events via ``bbs.events``."""
        return self.event_bus

    @property
    def users(self) -> UserManager:
        """Plugins manage accounts via ``bbs.users``."""
        return self.user_manager

    async def send(self, session: Session, text: str) -> None:
        """Send ``text`` to ``session``.

        Prefers delegating to the running server's ``_send`` so ANSI stripping
        (plain-text mode) and writer lifecycle checks stay consistent. Falls
        back to writing directly to ``session.writer`` (tests / headless
        sessions that have no attached server).
        """
        if self.server is not None and hasattr(self.server, "_send"):
            await self.server._send(session, text)
            return
        writer = getattr(session, "writer", None)
        if writer is None:
            return
        writer.write(text.encode("latin-1", errors="replace"))
        await writer.drain()


__all__ = ["BBSApp"]