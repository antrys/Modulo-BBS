"""Event bus for Modulo BBS core.

The event bus is the nervous system of the BBS. The core fires lifecycle
events; plugins (and other core modules) subscribe and react asynchronously.
This keeps observability intact even when a plugin replaces a core component:
the core always fires ``command:pre`` / ``command:post``, ``menu:select`` etc.
regardless of which plugin implements the actual UI.

Usage::

    bus = EventBus()
    bus.on("user:login", on_login)
    bus.once("session:disconnect", cleanup)
    bus.off("user:login", on_login)

    # Fire-and-forget: handlers are scheduled as asyncio tasks.
    bus.emit("user:login", {"user": user, "session": session})

    # Optionally await handler completion.
    await asyncio.gather(*bus.emit("user:login", data))

Handlers may be sync or async callables; sync handlers run to completion
inside their scheduled task, async ones are awaited. The ``data`` dict is
passed as their single argument. An exception raised inside a handler is
logged and isolated: it never propagates to the emitter and never prevents
other handlers from running.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger("modulo.core.events")

# One-arg callable; sync or async. Handlers take ``data`` as their argument.
Handler = Callable[[dict[str, Any]], Any]
Data = dict[str, Any]

# Core lifecycle events -- always fired by the core, can't be suppressed.
# See docs/plugin-spec.md, "Core Lifecycle Events".
CORE_EVENTS: tuple[str, ...] = (
    "session:connect",
    "session:disconnect",
    "user:login",
    "user:logout",
    "menu:open",
    "menu:select",
    "command:pre",
    "command:post",
)


class EventBus:
    """Asynchronous publish/subscribe event bus.

    Handlers registered with :meth:`on` run on every matching :meth:`emit`;
    handlers registered with :meth:`once` run on the next matching emit and are
    then removed automatically. :meth:`off` removes a handler from both sets.
    """

    def __init__(self) -> None:
        # Permanent handlers per event, in registration order.
        self._handlers: dict[str, list[Handler]] = {}
        # One-shot handlers per event (removed before their first invocation).
        self._once: dict[str, list[Handler]] = {}

    def on(self, event: str, handler: Handler) -> None:
        """Register ``handler`` to run on every ``emit(event, ...)``."""
        self._handlers.setdefault(event, []).append(handler)

    def once(self, event: str, handler: Handler) -> None:
        """Register ``handler`` to run on the next ``emit(event, ...)`` only."""
        self._once.setdefault(event, []).append(handler)

    def off(self, event: str, handler: Handler) -> None:
        """Remove ``handler`` for ``event`` (from both one-shot and permanent)."""
        bucket = self._handlers.get(event)
        if bucket is not None:
            try:
                bucket.remove(handler)
            except ValueError:
                pass
            if not bucket:
                del self._handlers[event]
        bucket = self._once.get(event)
        if bucket is not None:
            try:
                bucket.remove(handler)
            except ValueError:
                pass
            if not bucket:
                del self._once[event]

    def emit(self, event: str, data: Data | None = None) -> list[asyncio.Task[None]]:
        """Dispatch ``event`` with ``data`` to all subscribed handlers.

        Handlers are scheduled as asyncio tasks (fire-and-forget) so ``emit``
        itself never blocks the caller. The returned list of tasks lets callers
        ``await asyncio.gather(*results)`` to wait for handler completion.
        Handlers run in registration order. One bad handler cannot break the
        others or the emitter.
        """
        data = data if data is not None else {}
        handlers: list[Handler] = list(self._handlers.get(event, ()))
        handlers.extend(self._once.pop(event, ()))
        if not handlers:
            return []

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (e.g. an emit fired before the server started):
            # fall back to scheduling on the default loop if one is available.
            try:
                loop = asyncio.get_event_loop_policy().get_event_loop()
            except RuntimeError:
                logger.warning(
                    "emit(%r) called with no event loop; %d handler(s) dropped",
                    event, len(handlers),
                )
                return []

        return [loop.create_task(_invoke(handler, event, data)) for handler in handlers]

    # -- introspection helpers -------------------------------------------------

    def handler_count(self, event: str) -> int:
        """Number of handlers subscribed to ``event`` (permanent + one-shot)."""
        return len(self._handlers.get(event, ())) + len(self._once.get(event, ()))

    def clear(self) -> None:
        """Remove every registered handler."""
        self._handlers.clear()
        self._once.clear()


async def _invoke(handler: Handler, event: str, data: Data) -> None:
    """Await a single handler, isolating and logging any exception.

    Sync handlers are called directly; async ones (or any callable returning
    an awaitable) are awaited. Either style is accepted.
    """
    try:
        result = handler(data)
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # noqa: BLE001 -- a plugin bug must not bring down the bus
        logger.exception("event %r handler %r raised an error", event, handler)