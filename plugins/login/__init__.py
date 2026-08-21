"""
Modulo BBS -- login / auth plugin.

Owns the entire authentication experience: the login screen, new-user
registration, optional two-factor (TOTP) setup and verification, and the
``user:login`` / ``user:logout`` / ``auth:register`` / ``auth:login_failed``
events.

Per the plugin spec the *core* owns the User model and storage; this plugin
owns the auth *flows* and keeps its own runtime data (TOTP secrets) in its
``data/`` directory.
"""

from __future__ import annotations

import asyncio

from plugins.base import Plugin
from .totp import TOTPFlow, TOTPManager


class LoginPlugin(Plugin):
    """Handles login, registration and optional two-factor authentication."""

    name = "login"
    version = "1.0.0"
    description = "Login, registration and two-factor authentication."
    menu_label = "Login / Identity"
    menu_key = ""                    # auth is entered programmatically, not hotkeyed
    menu_order = 0                   # auth runs first in the main flow

    def __init__(self):
        self.bbs = None
        self.totp = TOTPManager()

    # -- lifecycle ----------------------------------------------------------

    def on_load(self, bbs) -> None:
        """Store the core BBS reference (event bus, users, session mgmt)."""
        self.bbs = bbs

    async def on_session_start(self, session) -> bool:
        """Drive the interactive login until the user authenticates or leaves.

        This is a coroutine because the flow performs asynchronous I/O against
        the session. An async-aware core should ``await`` it.
        """
        return await self.login(session)

    def on_session_end(self, session) -> None:
        """Log the disconnect if the user was still authenticated."""
        if getattr(session, "authenticated", False):
            user = getattr(session, "user", None)
            if user is not None and self.bbs is not None:
                self.bbs.events.emit(
                    "user:logout", {"session": session, "user": user}
                )
            session.authenticated = False
            session.user = None
            session.username = ""

    def handle_command(self, session, command) -> bool:
        """Handle menu-level auth commands.

        * ``Q`` / ``LOGOUT`` -- log out (emit ``user:logout``) and return to the
          main menu (returns False).
        * ``R`` / ``REGISTER`` -- begin registration as a background task.
        * anything else -- stay in the plugin (returns True).

        ``handle_command`` is synchronous per the plugin contract, so the
        interactive flows are run as asyncio tasks for single-keystroke entry.
        The full interactive login is normally driven via :meth:`on_session_start`.
        """
        if self.bbs is None:
            return False
        cmd = (command or "").strip().upper()
        if cmd in ("Q", "QUIT", "LOGOUT", "EXIT", "OFF"):
            user = getattr(session, "user", None)
            if getattr(session, "authenticated", False) and user is not None:
                self.bbs.events.emit(
                    "user:logout", {"session": session, "user": user}
                )
            session.authenticated = False
            session.user = None
            session.username = ""
            return False
        if cmd in ("R", "REGISTER", "REG"):
            asyncio.create_task(self.register(session))
            return True
        return True

    # -- entry points (also convenient for tests & routing) -----------------

    async def login(self, session) -> bool:
        """Run the login flow; True once the user is authenticated."""
        from .login import LoginFlow
        return await LoginFlow(self.bbs, self.totp).run(session)

    async def register(self, session) -> bool:
        """Run the registration flow; True after a successful signup."""
        from .registration import RegistrationFlow
        return await RegistrationFlow(self.bbs, self.totp).run(session)

    async def setup_totp(self, session, user=None, secret: str | None = None) -> bool:
        """Enrol ``user`` for TOTP (confirming code required)."""
        return await TOTPFlow(self.bbs, self.totp).setup(session, user, secret=secret)

    # -- convenience --------------------------------------------------------

    @property
    def session_user_field(self) -> str:
        """Name of the Session attribute holding the logged-in user."""
        return "user"


__all__ = ["LoginPlugin"]