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
from server.session import SessionManager, Session, SessionState
from tools.blockletters import render as block_render

logger = logging.getLogger("bbs.server")


class BBSServer:
    """Async telnet BBS server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 6400,
                 max_nodes: int = 8, plain_text: bool = False):
        self.host = host
        self.port = port
        self.max_nodes = max_nodes
        self.plain_text = plain_text
        self.session_manager = SessionManager(max_nodes)
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
            await self.session_manager.remove_session(session_id)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"Session {session_id} closed")

    async def _login_flow(self, session: Session, negotiator: TelnetNegotiator):
        """Handle the login/registration flow."""
        # Send clear screen then banner
        await self._send(session, "\033[2J\033[1;1H")
        banner = self._get_banner(session)
        await self._send(session, banner)

        session.state = SessionState.MAIN_MENU
        await self._main_menu(session, negotiator)

    def _get_banner(self, session: Session) -> str:
        """Generate the login banner. Returns string with \r\n line endings."""
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
        lines.append(C + "  [1] Login" + R)
        lines.append(C + "  [2] New User Registration" + R)
        lines.append(C + "  [3] System Info" + R)
        lines.append(C + "  [Q] Disconnect" + R)
        lines.append("")
        lines.append(W + "  Select: " + R)

        # Join with \r\n for proper terminal display
        return "\r\n".join(lines)

    async def _main_menu(self, session: Session, negotiator: TelnetNegotiator):
        """Main menu loop."""
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
        """Process user input at the main menu."""
        choice = text.strip().upper()

        if choice == '1':
            session.authenticated = True
            session.username = "TestUser"
            await self._send(session, f"\r\n{ANSI.BRIGHT_GREEN}Login successful! Welcome, {session.username}.{ANSI.RESET}\r\n")
            await self._send(session, self._get_banner(session))

        elif choice == '2':
            await self._send(session, f"\r\n{ANSI.BRIGHT_YELLOW}Registration not yet implemented.{ANSI.RESET}\r\n")
            await self._send(session, self._get_banner(session))

        elif choice == '3':
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

        elif choice == 'Q':
            await self._send(session, "\r\nGoodbye! Thanks for calling.\r\n")
            session.state = SessionState.DISCONNECTED
            return

        else:
            await self._send(session, "\r\nInvalid selection.\r\n")
            await self._send(session, self._get_banner(session))

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

    server = BBSServer(host=host, port=port, max_nodes=max_nodes, plain_text=plain_text)
    await server.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
