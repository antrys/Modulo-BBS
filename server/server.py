"""
Main BBS Telnet Server.
Async multi-node server with telnet protocol handling.
"""

import asyncio
import logging
import re
import signal
import sys
import uuid
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.telnet_protocol import TelnetNegotiator, ANSI
from server.session import Session, SessionState
from tools.blockletters import render as block_render

logger = logging.getLogger("bbs.server")


class BBSServer:
    """Async telnet BBS server.

    The server owns the transport and the core MODULO banner. Authentication
    and post-login features are supplied by plugins loaded onto the shared
    ``bbs`` application object (see :class:`core.app.BBSApp`).
    """

    def __init__(self, bbs=None, host: str = "127.0.0.1", port: int = 6400,
                 max_nodes: int = 8, plain_text: bool = False):
        if bbs is None:
            from core.app import BBSApp
            bbs = BBSApp(max_nodes=max_nodes)
        self.bbs = bbs
        bbs.server = self
        self.session_manager = bbs.session_manager
        self.max_nodes = bbs.session_manager.max_nodes
        self.host = host
        self.port = port
        self.plain_text = plain_text
        self._server: asyncio.Server | None = None
        self._running = False

    async def start(self):
        """Start the BBS server."""
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port,
            reuse_address=True,
        )
        self._running = True

        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        logger.info(f"BBS Server listening on {addrs}")
        logger.info(f"Max nodes: {self.max_nodes}")
        mode = " (plain text)" if self.plain_text else ""
        print(f"\n{'='*60}")
        print(f"  NETRUNNER BBS Server v0.1{mode}")
        print(f"  Listening on {addrs}")
        print(f"  Max nodes: {self.max_nodes}")
        print(f"{'='*60}\n")

        # Handle graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        async with self._server:
            await self._server.serve_forever()

    async def stop(self):
        """Gracefully stop the server."""
        logger.info("Shutting down BBS server...")
        self._running = False

        for session in list(self.session_manager.active_sessions):
            if session.writer:
                try:
                    await self._send(session, "\r\n\r\n[BBS shutting down. Goodbye!]\r\n")
                    session.writer.close()
                    await session.writer.wait_closed()
                except Exception:
                    pass

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        logger.info("Server stopped.")

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter):
        """Handle a new incoming connection."""
        addr = writer.get_extra_info('peername')
        session_id = str(uuid.uuid4())[:8]

        logger.info(f"Connection from {addr} (id={session_id})")

        session = await self.session_manager.create_session(
            session_id, addr, reader, writer
        )

        negotiator = TelnetNegotiator()

        try:
            if self.session_manager.active_count > self.max_nodes:
                await self._send(session, "\r\n[All nodes busy. Try again later.]\r\n")
                writer.close()
                await writer.wait_closed()
                await self.session_manager.remove_session(session_id)
                return

            session.state = SessionState.NEGOTIATING
            await self._send_raw(session, negotiator.initial_negotiation())

            session.state = SessionState.LOGIN
            await self._login_flow(session, negotiator)

        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            logger.info(f"Connection lost: {session_id}")
        except Exception as e:
            logger.error(f"Error in session {session_id}: {e}", exc_info=True)
        finally:
            # Give every plugin a chance to clean up (e.g. the login plugin
            # emits user:logout when an authenticated session disconnects).
            for plugin in self.bbs.plugins:
                try:
                    result = plugin.on_session_end(session)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass
            await self.session_manager.remove_session(session_id)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"Session {session_id} closed")

    async def _login_flow(self, session: Session, negotiator: TelnetNegotiator):
        """Handle authentication by delegating to the login plugin.

        The MODULO banner is core (kept here): it is shown before the login
        plugin takes over the entire interactive auth experience. Once the
        user authenticates, control passes to the (plugin-aware) main menu.
        """
        # Send clear screen then banner
        await self._send(session, "\033[2J\033[1;1H")
        await self._send(session, self._get_banner(session))
        session.state = SessionState.LOGIN

        plugin = self._find_login_plugin()
        if plugin is None:
            logger.error("No 'login' plugin loaded; cannot authenticate.")
            return

        authenticated = False
        try:
            result = plugin.on_session_start(session)
            if asyncio.iscoroutine(result):
                authenticated = bool(await result)
            else:
                authenticated = bool(result)
        except Exception:
            logger.exception("Login plugin on_session_start failed")

        if authenticated and session.is_active:
            session.state = SessionState.MAIN_MENU
            await self._main_menu(session, negotiator)

    # -- banner / menu rendering ------------------------------------------

    def _get_banner(self, session: Session) -> str:
        """Generate the core MODULO banner. Returns string with \r\n endings."""
        w = min(session.terminal_width, 60)
        bar = "=" * w

        # Block letters using tools/blockletters.py - safe CP437 chars only
        art_text = block_render("MODULO", size="small", fill="#", blank=" ")
        art_lines = art_text.split("\n")

        # ANSI color shortcuts
        C = ANSI.BRIGHT_CYAN
        B = ANSI.BOLD
        G = ANSI.BRIGHT_GREEN
        W = ANSI.BRIGHT_WHITE
        D = ANSI.BRIGHT_BLACK
        R = ANSI.RESET

        # Build lines with \r\n endings, ANSI color applied per line
        lines = []
        lines.append(C + B + bar + R)
        for art in art_lines:
            lines.append(C + B + art + R)
        lines.append(C + B + bar + R)
        lines.append("")
        lines.append(D + f"  Node {session.node_id} | {session.terminal_type} ({session.terminal_width}x{session.terminal_height})" + R)
        lines.append("")
        lines.append(W + "  Welcome to Modulo BBS" + R)
        lines.append(D + "  A retro bulletin board system with a modern twist." + R)
        lines.append(D + "  Version 0.1-alpha | Python " + sys.version.split()[0] + R)
        lines.append("")
        lines.append(G + f"  Active nodes: {self.session_manager.active_count}/{self.max_nodes}" + R)
        lines.append("")

        # Join with \r\n for proper terminal display
        return "\r\n".join(lines)

    def _get_main_menu(self, session: Session) -> str:
        """Render the post-login main menu: plugin options + built-ins."""
        w = min(session.terminal_width, 60)
        bar = "=" * w
        C = ANSI.BRIGHT_CYAN
        B = ANSI.BOLD
        W = ANSI.BRIGHT_WHITE
        R = ANSI.RESET

        lines = [C + B + bar + R, C + B + "  Main Menu" + R, C + B + bar + R, ""]
        for plugin in self._menuable_plugins():
            label = getattr(plugin, "menu_label", "") or plugin.name
            lines.append(C + f"  [{plugin.menu_key.upper()}] {label}" + R)
        lines.append(C + "  [3] System Info" + R)
        lines.append(C + "  [Q] Disconnect" + R)
        lines.append("")
        lines.append(W + "  Select: " + R)
        return "\r\n".join(lines)

    # -- plugin helpers ----------------------------------------------------

    def _find_login_plugin(self):
        """Return the plugin whose ``name`` is ``"login"``, or None."""
        for p in self.bbs.plugins:
            if getattr(p, "name", None) == "login":
                return p
        return None

    def _menuable_plugins(self):
        """Plugins that appear as hotkey-selectable main-menu items."""
        items = [p for p in self.bbs.plugins if getattr(p, "menu_key", "")]
        items.sort(key=lambda p: (getattr(p, "menu_order", 100), p.menu_key.upper()))
        return items

    async def _run_plugin(self, plugin, session: Session,
                          negotiator: TelnetNegotiator):
        """Enter a menu plugin: run its session-start hook, then its command
        loop until ``handle_command`` returns False (returns to the menu)."""
        try:
            result = plugin.on_session_start(session)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("plugin %s on_session_start failed", plugin.name)

        while session.is_active:
            try:
                data = await asyncio.wait_for(
                    session.reader.read(1024),
                    timeout=300
                )
            except asyncio.TimeoutError:
                await self._send(session, "\r\n\r\n[Idle timeout. Goodbye!]\r\n")
                break

            if not data:
                break

            session.touch()
            session.bytes_received += len(data)

            clean_data, responses = negotiator.process_data(data)
            if responses:
                for resp in responses:
                    await self._send_raw(session, resp)

            if clean_data:
                text = clean_data.decode('latin-1', errors='replace')
                try:
                    stay = bool(plugin.handle_command(session, text))
                except Exception:
                    logger.exception("plugin %s handle_command failed", plugin.name)
                    stay = False
                if not stay:
                    break

    async def _main_menu(self, session: Session, negotiator: TelnetNegotiator):
        """Main menu loop: plugin options plus built-in System Info/Disconnect."""
        await self._send(session, self._get_main_menu(session))
        while session.is_active:
            try:
                data = await asyncio.wait_for(
                    session.reader.read(1024),
                    timeout=300
                )
            except asyncio.TimeoutError:
                await self._send(session, "\r\n\r\n[Idle timeout. Goodbye!]\r\n")
                break

            if not data:
                break

            session.touch()
            session.bytes_received += len(data)

            clean_data, responses = negotiator.process_data(data)

            if responses:
                for resp in responses:
                    await self._send_raw(session, resp)

            session.terminal_width, session.terminal_height = negotiator.window_size
            session.terminal_type = negotiator.terminal_type

            if clean_data:
                text = clean_data.decode('latin-1', errors='replace')
                await self._handle_input(session, text, negotiator)

    async def _handle_input(self, session: Session, text: str,
                             negotiator: TelnetNegotiator):
        """Process user input at the main menu: plugins then built-ins."""
        choice = text.strip().upper()

        if choice in ("Q", "QUIT", "EXIT", "OFF", "BYE"):
            await self._send(session, "\r\nGoodbye! Thanks for calling.\r\n")
            session.state = SessionState.DISCONNECTED
            return

        if choice in ("3", "INFO", "SYSTEM", "?"):
            info = (
                "\r\n--- System Information ---\r\n"
                f"  Name:     Modulo BBS\r\n"
                f"  Version:  0.1-alpha\r\n"
                f"  Runtime:  Python {sys.version.split()[0]}\r\n"
                f"  Nodes:    {self.session_manager.active_count}/{self.max_nodes}\r\n"
                f"  Protocol: Telnet (RFC 854/855)\r\n"
                f"  Session:  {session.session_id} @ Node {session.node_id}\r\n"
                f"  Terminal: {session.terminal_type}\r\n"
                "\r\n  [Press any key to return]"
            )
            await self._send(session, info)
            await self._send(session, self._get_main_menu(session))
            return

        for plugin in self._menuable_plugins():
            if choice == plugin.menu_key.upper():
                await self._run_plugin(plugin, session, negotiator)
                if session.is_active:
                    session.state = SessionState.MAIN_MENU
                    await self._send(session, self._get_main_menu(session))
                return

        await self._send(session, "\r\nInvalid selection.\r\n")
        await self._send(session, self._get_main_menu(session))

    async def _send(self, session: Session, text: str):
        """Send text to a session. Strips ANSI in plain_text mode."""
        if not session.writer or session.writer.is_closing():
            return
        if self.plain_text:
            text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
        data = text.encode('latin-1', errors='replace')
        session.writer.write(data)
        await session.writer.drain()
        session.bytes_sent += len(data)

    async def _send_raw(self, session: Session, data: bytes):
        """Send raw bytes to a session."""
        if not session.writer or session.writer.is_closing():
            return
        session.writer.write(data)
        await session.writer.drain()
        session.bytes_sent += len(data)


async def main():
    """Entry point for the BBS server."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    host = "127.0.0.1"
    port = 6400
    max_nodes = 8
    plain_text = False

    if '--port' in sys.argv:
        idx = sys.argv.index('--port')
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    if '--host' in sys.argv:
        idx = sys.argv.index('--host')
        if idx + 1 < len(sys.argv):
            host = sys.argv[idx + 1]

    if '--nodes' in sys.argv:
        idx = sys.argv.index('--nodes')
        if idx + 1 < len(sys.argv):
            max_nodes = int(sys.argv[idx + 1])

    if '--plain' in sys.argv:
        plain_text = True

    from core.app import BBSApp
    from core.loader import PluginLoader

    bbs = BBSApp(max_nodes=max_nodes)
    bbs.plugins = await PluginLoader().load(bbs)

    server = BBSServer(bbs=bbs, host=host, port=port, plain_text=plain_text)
    await server.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass