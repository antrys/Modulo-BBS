"""Shared interactive-session driver for Modulo BBS.

The transports (telnet / SSH), the *logon* sequencer and the *mainmenu*
plugin all need to read a command from a session, send negotiation responses,
and run a plugin's interactive flow. Those helpers live here so a plugin can
drive a session identically over any transport without knowing which one is
underneath.

The core bootstrap hook (:func:`run_bootstrap`) is the single line each
transport calls after the protocol handshake: it finds the plugin named by
config key ``logon_plugin`` (default ``"logon"``) and hands the session to its
``on_session_start``. If the plugin is missing or broken it sends a minimal
notice and closes cleanly -- it never hangs.

Only :meth:`core.app.BBSApp.disconnect` closes sockets; plugins (including
the sequencer and the menu) request a disconnect through it rather than
touching writers directly.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("modulo.core.runner")

IDLE_TIMEOUT = 300  # seconds; a session idle this long is disconnected


async def read_command(bbs, session, timeout: int = IDLE_TIMEOUT) -> str | None:
    """Read and decode one chunk of input from ``session``.

    Negotiates telnet control sequences (when the session carries a
    ``negotiator``) and forwards the responses; SSH sessions carry no
    negotiator so their already-normalised bytes pass straight through.

    Returns the decoded text, or ``None`` when the connection ended or went
    idle -- the caller should tear down / return to the menu.
    """
    neg = getattr(session, "negotiator", None)
    try:
        data = await asyncio.wait_for(
            session.reader.read(1024), timeout=timeout
        )
    except asyncio.TimeoutError:
        await bbs.send(session, "\r\n\r\n[Idle timeout. Goodbye!]\r\n")
        return None
    if not data:
        return None

    session.touch()
    session.bytes_received += len(data)

    if neg is None:
        return data.decode("latin-1", errors="replace")

    clean, responses = neg.process_data(data)
    if responses:
        for resp in responses:
            await bbs.send_raw(session, resp)
    if neg is not None:
        session.terminal_width, session.terminal_height = neg.window_size
        session.terminal_type = neg.terminal_type
    if not clean:
        return ""
    return clean.decode("latin-1", errors="replace")


async def run_plugin_flow(bbs, plugin, session) -> bool:
    """Enter a menu plugin: run its session-start hook, then its command loop
    until ``handle_command`` returns False (return to the menu) or the session
    ends. Returns True if the session is still active on exit.
    """
    try:
        result = plugin.on_session_start(session)
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # noqa: BLE001
        logger.exception("plugin %s on_session_start failed", plugin.name)

    while session.is_active:
        text = await read_command(bbs, session)
        if text is None:
            return session.is_active
        if text:
            try:
                result = plugin.handle_command(session, text)
                if asyncio.iscoroutine(result):
                    result = await result
                stay = bool(result)
            except Exception:  # noqa: BLE001
                logger.exception("plugin %s handle_command failed", plugin.name)
                stay = False
            if not stay:
                break
    return session.is_active


async def run_bootstrap(bbs, session) -> None:
    """Core bootstrap hook: invoke the configured ``logon_plugin``.

    Every transport calls this once per session after the protocol handshake.
    It fires ``session:connect``, then awaits the logon plugin's
    ``on_session_start``. A missing or failing logon plugin sends a minimal
    "System unavailable." notice and closes the session via ``bbs.disconnect``
    -- never hangs.
    """
    name = (bbs.config or {}).get("logon_plugin", "logon")
    plugin = bbs.get_plugin(name)
    bbs.events.emit("session:connect", {"session": session})

    if plugin is None:
        logger.error("logon plugin %r not loaded; refusing session", name)
        await bbs.send(session, "\r\nSystem unavailable.\r\n")
        if session.is_active:
            await bbs.disconnect(session)
        return

    try:
        result = plugin.on_session_start(session)
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # noqa: BLE001
        logger.exception("logon plugin %r failed", name)
        await bbs.send(session, "\r\nSystem unavailable.\r\n")
        if session.is_active:
            await bbs.disconnect(session)