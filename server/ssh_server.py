"""
SSH transport for NetRunner BBS.
Uses asyncssh to provide SSH access alongside telnet.
Supports "no auth" mode (public access without credentials).
SyncTERM/cryptlib compatible: RSA host key, SHA-1 KEX, CBC ciphers, raw bytes.
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
    """AsyncSSH session that bridges to the BBS session logic.
    Uses encoding=None (raw bytes) for CP437 compatibility."""

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
        return True

    def session_started(self):
        logger.info(f"session_started: {self._session.session_id if self._session else '???'}")
        asyncio.ensure_future(self._safe_shell_loop())

    async def _safe_shell_loop(self):
        try:
            await self._shell_loop()
        except Exception as e:
            logger.error(f"Shell loop crashed: {e}", exc_info=True)
            await self._cleanup()

    def data_received(self, data, datatype):
        # With encoding=None, data is bytes
        self._input_queue.put_nowait(data)

    async def _shell_loop(self):
        logger.info("shell_loop: start")
        if not self._chan or not self._session:
            logger.warning("shell_loop: chan or session is None")
            return
        try:
            node_id = self.bbs.session_manager._assign_node()
            self._session.node_id = node_id
            self.bbs.session_manager.sessions[self._session.session_id] = self._session
            logger.info(f"shell_loop: node {node_id}")
        except RuntimeError as e:
            logger.warning(f"shell_loop: node assign failed: {e}")
            await self._send(b"\r\n[All nodes busy.]\r\n")
            self._chan.close()
            return

        self._session.state = SessionState.LOGIN
        await self._send(b"\033[2J\033[1;1H")
        await self._send(self.bbs._get_banner(self._session).encode('latin-1'))
        self._session.state = SessionState.MAIN_MENU
        logger.info("shell_loop: banner sent, waiting for input")

        while self._session.is_active:
            try:
                data = await self._input_queue.get()
            except Exception as e:
                logger.error(f"queue get failed: {e}")
                break
            if data is None:
                logger.info("shell_loop: got None (EOF), exiting")
                break
            logger.info(f"shell_loop: got {len(data)} bytes")
            self._session.touch()
            self._session.bytes_received += len(data)
            # Decode bytes to str for menu processing
            text = data.decode('latin-1', errors='replace') if isinstance(data, bytes) else data
            await self._handle_input(text)

        logger.info("shell_loop: exiting")
        await self._cleanup()

    async def _handle_input(self, text: str):
        choice = text.strip().upper()

        if choice == '1':
            self._session.authenticated = True
            self._session.username = "TestUser"
            msg = f"\r\n{ANSI.BRIGHT_GREEN}Login successful! Welcome, {self._session.username}.{ANSI.RESET}\r\n"
            await self._send(msg.encode('latin-1'))
            await self._send(self.bbs._get_banner(self._session).encode('latin-1'))

        elif choice == '2':
            msg = f"\r\n{ANSI.BRIGHT_YELLOW}Registration not yet implemented.{ANSI.RESET}\r\n"
            await self._send(msg.encode('latin-1'))
            await self._send(self.bbs._get_banner(self._session).encode('latin-1'))

        elif choice == '3':
            info = (
                "\r\n--- System Information ---\r\n"
                f"  Name:     NetRunner BBS\r\n"
                f"  Version:  0.1-alpha\r\n"
                f"  Runtime:  Python {sys.version.split()[0]}\r\n"
                f"  Nodes:    {self.bbs.session_manager.active_count}/{self.bbs.max_nodes}\r\n"
                f"  Protocol: SSH (asyncssh, cryptlib compat)\r\n"
                f"  Session:  {self._session.session_id} @ Node {self._session.node_id}\r\n"
                f"  Terminal: {self._session.terminal_type}\r\n"
                "\r\n  [Press any key to return]"
            )
            await self._send(info.encode('latin-1'))

        elif choice == 'Q':
            await self._send(b"\r\nGoodbye! Thanks for calling.\r\n")
            self._session.state = SessionState.DISCONNECTED
            if self._chan and not self._chan.is_closing():
                self._chan.close()
            return

        else:
            await self._send(b"\r\nInvalid selection.\r\n")
            await self._send(self.bbs._get_banner(self._session).encode('latin-1'))

    async def _send(self, data: bytes):
        if not self._chan or self._chan.is_closing():
            return
        self._chan.write(data)
        self._session.bytes_sent += len(data)

    async def _cleanup(self):
        if self._session:
            logger.info(f"SSH session {self._session.session_id} closed")
            await self.bbs.session_manager.remove_session(self._session.session_id)
            self._session = None

    def eof_received(self):
        logger.info("EOF received — ignoring")
        return True  # Keep channel half-open

    def connection_lost(self, exc):
        if self._session:
            self._session.state = SessionState.DISCONNECTED
        self._input_queue.put_nowait(None)


class BBSSSHServer(asyncssh.SSHServer):
    """SSH server that accepts all connections (no auth)."""

    def __init__(self, bbs_server):
        self.bbs = bbs_server

    def session_requested(self):
        return BBSSSHSession(self.bbs)

    def begin_auth(self, username):
        return False

    def password_auth_supported(self):
        return False

    def public_key_auth_supported(self):
        return False


async def start_ssh_server(bbs_server, host: str = "127.0.0.1", port: int = 6422):
    """Start the SSH BBS server with SyncTERM/cryptlib compatibility."""
    if asyncssh is None:
        logger.error("asyncssh not installed. Run: pip install asyncssh")
        return

    # Use RSA host key (cryptlib needs RSA, not ed25519)
    rsa_key_path = Path(__file__).parent.parent / "keys" / "ssh_host_rsa_key"
    if rsa_key_path.exists():
        host_key = asyncssh.read_private_key(str(rsa_key_path))
    else:
        rsa_key_path.parent.mkdir(exist_ok=True)
        host_key = asyncssh.generate_private_key('ssh-rsa', key_size=2048)
        host_key.write_private_key(str(rsa_key_path))
        logger.info(f"Generated RSA host key: {rsa_key_path}")

    def server_factory():
        return BBSSSHServer(bbs_server)

    server = await asyncssh.create_server(
        server_factory,
        host,
        port,
        server_host_keys=[host_key],
        kex_algs=[
            'diffie-hellman-group14-sha1',
            'diffie-hellman-group-exchange-sha1',
            'ecdh-sha2-nistp256',
            'diffie-hellman-group14-sha256',
            'diffie-hellman-group16-sha512',
        ],
        encryption_algs=[
            'aes128-cbc', 'aes256-cbc',
            'aes128-ctr', 'aes256-ctr',
            '3des-cbc',
        ],
        mac_algs=['hmac-sha1', 'hmac-sha2-256'],
        line_editor=False,
        encoding=None,  # Raw bytes for CP437 support
    )

    addrs = ", ".join(str(s.getsockname()) for s in server._sockets)
    logger.info(f"BBS SSH Server listening on {addrs}")
    print(f"  SSH on {addrs} (no auth, cryptlib compat)")

    async with server:
        await server.wait_closed()
