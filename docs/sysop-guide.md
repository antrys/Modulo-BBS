# Modulo BBS — SysOp Guide

## Quick Start

### Running the Server

```bash
cd /home/dave/projects/bbs
python3 run_server.py --port 6400 --ssh-port 6422 --plain
```

Flags:
- `--host HOST` — bind address (default: `127.0.0.1`, use `0.0.0.0` for LAN)
- `--port PORT` — telnet port (default: 6400)
- `--ssh-port PORT` — SSH port (default: 6422)
- `--nodes N` — max simultaneous connections (default: 8)
- `--plain` — strip ANSI codes (for debugging)

### Connecting

**Telnet:**
```
telnet localhost 6400
```

**SSH (no auth):**
```
ssh -p 6422 localhost
```

**Syncterm:**
- Telnet: Address=`localhost`, Port=`6400`, ConnectionType=Telnet
- SSH: Address=`127.0.0.1`, Port=`6422`, ConnectionType=SSH (no auth)

### Stopping the Server

Press `Ctrl+C` or:
```bash
kill $(lsof -t -i:6400) $(lsof -t -i:6422)
```

## User Management

### Creating Users

Users are stored in `users/` at the project root. Each user is a JSON file:
```json
{
    "username": "dave",
    "password_hash": "bcrypt_hash_here",
    "display_name": "Dave",
    "created": "2026-08-21T00:00:00Z",
    "flags": ["sysop"]
}
```

### User Flags

| Flag | Description |
|------|-------------|
| `sysop` | Full system access |
| `admin` | User management, system config |
| `mod` | Message board moderation |
| `user` | Standard access (default for new accounts) |

### Password Policy

Passwords are bcrypt-hashed. Minimum 6 characters. The server never stores plaintext.

## Plugin Management

### Enabling/Disabling Plugins

Edit `config.yaml`:
```yaml
plugins:
  enabled:
    - messageboard    # ✓ active
    - files           # ✓ active
    - bulletin        # ✓ active
    # - chat          # ✗ disabled
```

Restart the server after changes.

### Plugin Directory

Each plugin lives in `plugins/<name>/`:
```
plugins/
├── base.py           # Plugin interface
├── messageboard/
│   ├── __init__.py   # Plugin class
│   ├── models.py     # Data models
│   └── ui.py         # Menu/rendering
└── ...
```

## Monitoring

### Server Logs

Logs go to stdout (and can be redirected):
```bash
python3 run_server.py 2>&1 | tee bbs.log
```

Log levels:
- `INFO` — connections, disconnections, menu selections
- `DEBUG` — detailed protocol negotiation, byte counts
- `WARNING` — node exhaustion, failed auth
- `ERROR` — crashes, unhandled exceptions

### Active Sessions

Check connected users:
```bash
# Via SSH
ssh -p 6422 localhost <<< "3"

# Or check logs for "shell_loop: node N"
```

### Node Usage

The server tracks node usage:
```
Active nodes: 3/8
```

When all nodes are full, new connections get "All nodes busy" and are disconnected.

## Backups

### What to Back Up

- `users/` — all user accounts (one JSON file per user)
- `plugins/*/data/` — plugin runtime data (messages, uploads, chat logs)
- `keys/` — SSH host keys (regenerate if lost, but clients will need to re-accept)
- `config.yaml` — server configuration

### Backup Command

```bash
tar czf modulo-backup-$(date +%Y%m%d).tar.gz \
    users/ plugins/*/data/ keys/ config.yaml
```

## Troubleshooting

### "Connection refused" on port 6400/6422

Server isn't running. Start it:
```bash
python3 run_server.py --host 0.0.0.0 --port 6400 --ssh-port 6422
```

### SSH handshake fails (Syncterm error -20)

Algorithm mismatch. Ensure `config.yaml` has cryptlib-compatible algorithms. See `docs/architecture.md` for the correct `create_server()` call.

### Banner garbled in Syncterm

Use `--plain` flag or ensure terminal is set to CP437. The banner uses only safe ASCII characters (`#`, letters, spaces).

### Node exhaustion

Increase `--nodes` or disconnect idle users. Check logs for which nodes are occupied.

### Plugin not loading

Check:
1. Plugin directory exists under `plugins/`
2. `__init__.py` exports a `Plugin` subclass
3. Plugin is listed in `config.yaml` under `plugins.enabled`
4. No import errors in logs

## Security Notes

### SSH Transport

- Host key: RSA 2048-bit (PEM format)
- Algorithms: SHA-1 KEX, CBC ciphers (cryptlib compatible)
- Authentication: none (no-auth mode)

This is adequate for a local/enthusiast BBS. For public-facing deployments, consider:
- Adding password authentication
- Upgrading to AES-CTR + HMAC-SHA256
- Implementing fail2ban or rate limiting

### Telnet Transport

**No encryption.** Passwords sent in plaintext. Use only on trusted networks. SSH is preferred.

### File Permissions

```bash
chmod 700 users/ plugins/*/data/   # User + plugin data
chmod 600 keys/*         # SSH keys
chmod 644 config.yaml    # Config (readable, not writable by others)
```
