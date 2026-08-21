"""
SSH transport for NetRunner BBS.
Uses asyncssh to provide SSH access alongside telnet.
Supports "no auth" mode (public access without credentials).
SyncTERM/cryptlib compatible: RSA host key, SHA-1 KEX, CBC ciphers, raw bytes.

Authentication and the post-login experience are delegated to the loaded
plugins exactly like the telnet server: the MODULO banner is core (kept
here), then the ``login`` plugin's ``on_session_start`` drives the entire
auth flow, and after login the (plugin-aware) main menu is shown. The SSH
session bridges the asyncssh channel to the shared :class:`server.session.Session`
object (providing ``reader`` / ``writer`` so ``bbs.send`` and the login plugin's
line-reading terminal work unchanged over SSH).
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

from server.session import Session, SessionState

logger = logging.getLogger("bbs.ssh")


class _SSHWriter:
    """Expose a stream-writer surface (``write``/``is_closing``/``drain``)
    over an asyncssh channel so the core ``bbs.send`` / ``server._send``
    transport path works for SSH sessions too (the login plugin and menu
    plugins send text through those paths)."""

    def __init__(self, chan):
        self._chan = chan

    def write(self, data):
        self._chan.write(data)

    def is_closing(self):
        return self._chan.is_closing()

    async def drain(self):
        # asyncssh buffers and flushes internally; nothing to await here.
        return None


class BBSSSHSession(asyncssh.SSHServerSession):
    """AsyncSSH session that bridges to the BBS session logic.
    Uses encoding=None (raw bytes) for CP437 compatibility."""

    def __init__(self, bbs):
        # ``bbs`` is the shared BBSApp (same object the telnet server uses).
        self.bbs = bbs
        self._chan = None
        self._session: Session | None = None
        # StreamReader fed by data_received so the login plugin can read
        # CRLF-terminated lines via ``session.reader.readline()``.
        self._reader: asyncio.StreamReader | None = None

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
        # Wire transport so plugins send via bbs.send / server._send and read
        # via session.reader, exactly like a telnet session.
        self._reader = asyncio.StreamReader()
        self._session.reader = self._reader
        self._session.writer = _SSHWriter(chan)

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
        # With encoding=None, data is bytes. Normalise line endings so the
        # login / menu line readers see clean \n-terminated lines from any
        # client (SyncTERM sends bare \r on Enter).
        if self._reader is None:
            return
        raw = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        self._reader.feed_data(raw)

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

        # Core MODULO banner, then hand the whole auth experience to the
        # login plugin (same flow as the telnet server's _login_flow).
        self._session.state = SessionState.LOGIN
        await self._send(b"\033[2J\033[1;1H")
        await self._send(self._get_banner().encode('latin-1'))
        logger.info("shell_loop: banner sent, running login plugin")

        authenticated = False
        plugin = self._find_login_plugin()
        if plugin is None:
            logger.error("No 'login' plugin loaded; cannot authenticate.")
        else:
            try:
                result = plugin.on_session_start(self._session)
                if asyncio.iscoroutine(result):
                    authenticated = bool(await result)
                else:
                    authenticated = bool(result)
            except Exception:
                logger.exception("login plugin on_session_start failed")

        if not authenticated or not self._session.is_active:
            await self._send(b"\r\nGoodbye! Thanks for calling.\r\n")
            if self._chan and not self._chan.is_closing():
                self._chan.close()
            logger.info("shell_loop: not authenticated, closing")
            await self._cleanup()
            return

        # Login success (the plugin sets state to MAIN_MENU on success) ->
        # show the plugin-aware main menu.
        if self._session.state == SessionState.LOGIN:
            self._session.state = SessionState.MAIN_MENU
        await self._main_menu()

        logger.info("shell_loop: exiting")
        await self._cleanup()

    async def _main_menu(self):
        """Post-login main menu: plugin options plus built-ins, driven over
        the SSH reader/writer."""
        await self._send(self._get_menu().encode('latin-1'))
        while self._session.is_active:
            try:
                data = await asyncio.wait_for(
                    self._reader.read(1024), timeout=300
                )
            except asyncio.TimeoutError:
                await self._send(b"\r\n\r\n[Idle timeout. Goodbye!]\r\n")
                break
            if not data:
                break
            self._session.touch()
            self._session.bytes_received += len(data)
            text = data.decode('latin-1', errors='replace')
            if not await self._handle_menu_input(text):
                break

    async def _handle_menu_input(self, text: str) -> bool:
        """Process one main-menu selection. Returns False to end the session
        (disconnect), True to stay at the menu."""
        choice = text.strip().upper()

        if choice in ("Q", "QUIT", "EXIT", "OFF", "BYE"):
            await self._send(b"\r\nGoodbye! Thanks for calling.\r\n")
            self._session.state = SessionState.DISCONNECTED
            if self._chan and not self._chan.is_closing():
                self._chan.close()
            return False

        if choice in ("3", "INFO", "SYSTEM", "?"):
            info = (
                "\r\n--- System Information ---\r\n"
                f"  Name:     Modulo BBS\r\n"
                f"  Version:  0.1-alpha\r\n"
                f"  Runtime:  Python {sys.version.split()[0]}\r\n"
                f"  Nodes:    {self.bbs.session_manager.active_count}"
                f"/{self.bbs.session_manager.max_nodes}\r\n"
                f"  Protocol: SSH (asyncssh, cryptlib compat)\r\n"
                f"  Session:  {self._session.session_id} @ Node {self._session.node_id}\r\n"
                f"  Terminal: {self._session.terminal_type}\r\n"
                "\r\n  [Press any key to return]"
            )
            await self._send(info.encode('latin-1'))
            await self._send(self._get_menu().encode('latin-1'))
            return True

        for plugin in self._menuable_plugins():
            if choice == plugin.menu_key.upper():
                await self._run_plugin(plugin)
                if self._session.is_active:
                    self._session.state = SessionState.MAIN_MENU
                    await self._send(self._get_menu().encode('latin-1'))
                else:
                    return False
                return True

        await self._send(b"\r\nInvalid selection.\r\n")
        await self._send(self._get_menu().encode('latin-1'))
        return True

    async def _run_plugin(self, plugin):
        """Enter a menu plugin: run its session-start hook, then its command
        loop until ``handle_command`` returns False (returns to the menu)."""
        try:
            result = plugin.on_session_start(self._session)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("plugin %s on_session_start failed", plugin.name)

        while self._session.is_active:
            try:
                data = await asyncio.wait_for(
                    self._reader.read(1024), timeout=300
                )
            except asyncio.TimeoutError:
                await self._send(b"\r\n\r\n[Idle timeout. Goodbye!]\r\n")
                break
            if not data:
                break
            self._session.touch()
            self._session.bytes_received += len(data)
            text = data.decode('latin-1', errors='replace')
            try:
                stay = bool(plugin.handle_command(self._session, text))
            except Exception:
                logger.exception("plugin %s handle_command failed", plugin.name)
                stay = False
            if not stay:
                break

    # -- banner / menu / plugin helpers -----------------------------------

    def _core_server(self):
        """The running transport server (the telnet BBSServer, set as
        ``bbs.server``) that renders the core MODULO banner and menu; or None
        when SSH runs standalone."""
        try:
            return self.bbs.server
        except AttributeError:
            return None

    def _get_banner(self) -> str:
        """Core MODULO banner (shared with the telnet server) or a minimal
        fallback when no core server is attached."""
        srv = self._core_server()
        if srv is not None and hasattr(srv, "_get_banner"):
            return srv._get_banner(self._session)
        w = min(self._session.terminal_width, 60)
        bar = "=" * w
        return "\r\n".join([
            f"{bar}",
            f"  MODULO",
            f"{bar}",
            "",
            f"  Welcome to Modulo BBS",
            f"  Node {self._session.node_id} | {self._session.terminal_type}",
        ])

    def _get_menu(self) -> str:
        """Plugin-aware main menu (shared with the telnet server) or a
        minimal fallback when no core server is attached."""
        srv = self._core_server()
        if srv is not None and hasattr(srv, "_get_main_menu"):
            return srv._get_main_menu(self._session)
        lines = ["  Main Menu", ""]
        for p in self._menuable_plugins():
            label = getattr(p, "menu_label", "") or p.name
            lines.append(f"  [{p.menu_key.upper()}] {label}")
        lines.append("  [3] System Info")
        lines.append("  [Q] Disconnect")
        lines.append("")
        lines.append("  Select: ")
        return "\r\n".join(lines)

    def _find_login_plugin(self):
        """Return the plugin whose ``name`` is ``\"login\"``, or None."""
        for p in self.bbs.plugins:
            if getattr(p, "name", None) == "login":
                return p
        return None

    def _menuable_plugins(self):
        """Plugins that appear as hotkey-selectable main-menu items."""
        srv = self._core_server()
        if srv is not None and hasattr(srv, "_menuable_plugins"):
            return srv._menuable_plugins()
        items = [p for p in self.bbs.plugins if getattr(p, "menu_key", "")]
        items.sort(key=lambda p: (getattr(p, "menu_order", 100), p.menu_key.upper()))
        return items

    async def _send(self, data: bytes):
        if not self._chan or self._chan.is_closing():
            return
        self._chan.write(data)
        if self._session:
            self._session.bytes_sent += len(data)

    async def _cleanup(self):
        if self._session:
            logger.info(f"SSH session {self._session.session_id} closed")
            # Give every plugin a chance to clean up (e.g. the login plugin
            # emits user:logout when an authenticated session disconnects).
            for plugin in self.bbs.plugins:
                try:
                    result = plugin.on_session_end(self._session)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass
            await self.bbs.session_manager.remove_session(self._session.session_id)
            self._session = None

    def eof_received(self):
        logger.info("EOF received — ignoring")
        return True  # Keep channel half-open

    def connection_lost(self, exc):
        if self._session:
            self._session.state = SessionState.DISCONNECTED
        if self._reader is not None:
            self._reader.feed_eof()


class BBSSSHServer(asyncssh.SSHServer):
    """SSH server that accepts all connections (no auth) and wires each
    session to the shared BBSApp (plugins drive auth and the main menu)."""

    def __init__(self, bbs):
        self.bbs = bbs

    def session_requested(self):
        return BBSSSHSession(self.bbs)

    def begin_auth(self, username):
        return False

    def password_auth_supported(self):
        return False

    def public_key_auth_supported(self):
        return False


async def start_ssh_server(bbs, host: str = "127.0.0.1", port: int = 6422):
    """Start the SSH BBS server with SyncTERM/cryptlib compatibility.

    ``bbs`` is the shared :class:`core.app.BBSApp` (same object handed to the
    telnet server); its loaded plugins drive authentication and the menu.
    """
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
        return BBSSHServer(bbs)

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