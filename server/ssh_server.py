"""
SSH transport for NetRunner BBS.
Uses asyncssh to provide SSH access alongside telnet.
Supports "no auth" mode (public access without credentials).
"""

import asyncio
import logging
import sys
from pathlib import Path

try:
    import asyncssh
except ImportError:
    asyncssh = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.telnet_protocol import ANSI
from server.session import Session, SessionState

logger = logging.getLogger("bbs.ssh")


class BBSSSHSession(asyncssh.SSHServerSession):
    """AsyncSSH session that bridges to the BBS session logic."""

    def __init__(self, bbs_server):
        self.bbs = bbs_server
        self._chan = None
        self._session: Session | None = None
        self._input_queue: asyncio.Queue = asyncio.Queue()

    def connection_made(self, chan):
        self._chan = chan
        peer = chan.get_extra_info('peername')
        addr = (peer[0], peer[1]) if peer else ('0.0.0.0', 0)
        session_id = f"ssh-{id(self) & 0xFFFFFF:06x}"
        logger.info(f"SSH connection from {addr} (id={session_id})")
        self._session = Session(
            session_id=session_id, node_id=0, address=addr,
            terminal_type="SSH", terminal_width=80, terminal_height=24,
        )

    def pty_requested(self, term_type, term_size, term_modes):
        if self._session:
            if term_size[0] > 0:
                self._session.terminal_width = term_size[0]
            if term_size[1] > 0:
                self._session.terminal_height = term_size[1]
            self._session.terminal_type = term_type or "SSH"
        return True

    def shell_requested(self):
        # Accept the shell; output happens in session_started()
        return True

    def session_started(self):
        # Channel fully open — now we can send output
        asyncio.ensure_future(self._shell_loop())

    def data_received(self, data, datatype):
        # data is a str (utf-8 encoding is the default)
        self._input_queue.put_nowait(data)

    async def _shell_loop(self):
        if not self._chan or not self._session:
            return
        try:
            node_id = self.bbs.session_manager._assign_node()
            self._session.node_id = node_id
            self.bbs.session_manager.sessions[self._session.session_id] = self._session
        except RuntimeError:
            await self._send("\r\n[All nodes busy. Try again later.]\r\n")
            self._chan.close()
            return

        self._session.state = SessionState.LOGIN
        await self._send("\033[2J\033[1;1H")
        await self._send(self.bbs._get_banner(self._session))
        self._session.state = SessionState.MAIN_MENU

        while self._session.is_active:
            try:
                data = await self._input_queue.get()
            except Exception:
                break
            if data is None:
                break
            self._session.touch()
            self._session.bytes_received += len(data)
            await self._handle_input(data)

        await self._cleanup()

    async def _handle_input(self, text: str):
        choice = text.strip().upper()

        if choice == '1':
            self._session.authenticated = True
            self._session.username = "TestUser"
            await self._send(f"\r\n{ANSI.BRIGHT_GREEN}Login successful! Welcome, {self._session.username}.{ANSI.RESET}\r\n")
            await self._send(self.bbs._get_banner(self._session))

        elif choice == '2':
            await self._send(f"\r\n{ANSI.BRIGHT_YELLOW}Registration not yet implemented.{ANSI.RESET}\r\n")
            await self._send(self.bbs._get_banner(self._session))

        elif choice == '3':
            info = (
                "\r\n--- System Information ---\r\n"
                f"  Name:     NetRunner BBS\r\n"
                f"  Version:  0.1-alpha\r\n"
                f"  Runtime:  Python {sys.version.split()[0]}\r\n"
                f"  Nodes:    {self.bbs.session_manager.active_count}/{self.bbs.max_nodes}\r\n"
                f"  Protocol: SSH (asyncssh)\r\n"
                f"  Session:  {self._session.session_id} @ Node {self._session.node_id}\r\n"
                f"  Terminal: {self._session.terminal_type}\r\n"
                "\r\n  [Press any key to return]"
            )
            await self._send(info)

        elif choice == 'Q':
            await self._send("\r\nGoodbye! Thanks for calling.\r\n")
            self._session.state = SessionState.DISCONNECTED
            return

        else:
            await self._send("\r\nInvalid selection.\r\n")
            await self._send(self.bbs._get_banner(self._session))

    async def _send(self, text: str):
        if not self._chan or self._chan.is_closing():
            return
        self._chan.write(text)
        self._session.bytes_sent += len(text.encode('utf-8', errors='replace'))

    async def _cleanup(self):
        if self._session:
            logger.info(f"SSH session {self._session.session_id} closed")
            await self.bbs.session_manager.remove_session(self._session.session_id)
            self._session = None

    def eof_received(self):
        self._input_queue.put_nowait(None)
        return False

    def connection_lost(self, exc):
        if self._session:
            self._session.state = SessionState.DISCONNECTED


class BBSSSHServer(asyncssh.SSHServer):
    """SSH server that accepts all connections (no auth)."""

    def __init__(self, bbs_server):
        self.bbs = bbs_server

    def get_server_host_keys(self):
        key_path = Path(__file__).parent.parent / "keys" / "ssh_host_key"
        if key_path.exists():
            return [asyncssh.read_private_key(str(key_path))]
        else:
            key_path.parent.mkdir(exist_ok=True)
            key = asyncssh.generate_private_key('ssh-ed25519')
            key.write_private_key(str(key_path))
            logger.info(f"Generated SSH host key: {key_path}")
            return [key]

    def session_requested(self):
        return BBSSSHSession(self.bbs)

    def begin_auth(self, username):
        return False

    def password_auth_supported(self):
        return False

    def public_key_auth_supported(self):
        return False


async def start_ssh_server(bbs_server, host: str = "127.0.0.1", port: int = 6422):
    """Start the SSH BBS server."""
    if asyncssh is None:
        logger.error("asyncssh not installed. Run: pip install asyncssh")
        return

    key_path = Path(__file__).parent.parent / "keys" / "ssh_host_key"
    if key_path.exists():
        host_key = asyncssh.read_private_key(str(key_path))
    else:
        key_path.parent.mkdir(exist_ok=True)
        host_key = asyncssh.generate_private_key('ssh-ed25519')
        host_key.write_private_key(str(key_path))
        logger.info(f"Generated SSH host key: {key_path}")

    def server_factory():
        return BBSSSHServer(bbs_server)

    server = await asyncssh.create_server(
        server_factory,
        host,
        port,
        server_host_keys=[host_key],
        line_editor=False,
    )

    addrs = ", ".join(str(s.getsockname()) for s in server._sockets)
    logger.info(f"BBS SSH Server listening on {addrs}")
    print(f"  SSH on {addrs} (no auth)")

    async with server:
        await server.wait_closed()
