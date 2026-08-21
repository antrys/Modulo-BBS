# Modulo BBS — Architecture

## Overview

Modulo is a modular, plugin-based Bulletin Board System built in Python 3.11+ with asyncio. It supports multiple transports (telnet, SSH) and exposes an API for external tooling.

## Design Principles

1. **Unix philosophy** — each module does one thing well
2. **Plugin architecture** — features are plugins, not hardcoded
3. **API-first** — everything accessible via HTTP API for external tools
4. **Transport-agnostic** — core logic doesn't know or care about telnet vs SSH
5. **CP437 native** — raw bytes throughout, no UTF-8 mangling

## Directory Structure

```
modulo-bbs/
├── core/                    # Session, user model, event bus, transport
│   ├── session.py           # Session state machine + node tracking
│   ├── user.py              # User model + CRUD
│   ├── events.py            # Event bus
│   └── transport/           # Telnet + SSH implementations
│       ├── telnet.py
│       └── ssh.py
├── plugins/                 # All plugins (self-contained)
│   ├── base.py              # Plugin interface
│   ├── auth/                # Authentication (login, register)
│   ├── messageboard/        # Message boards + threads
│   ├── files/               # File areas + transfers
│   ├── bulletin/            # System bulletins + news
│   ├── chat/                # Inter-node live chat
│   └── doors/               # Door game loader
├── shared/                  # Shared utilities
│   ├── telnet_protocol.py   # RFC 854/855, ANSI codes
│   └── blockletters.py      # ASCII art renderer
├── tools/                   # Dev + ops tools
├── docs/                    # Documentation
├── keys/                    # SSH host keys (gitignored)
├── users/                   # User data (core-owned)
├── run_server.py            # Entry point
├── config.yaml              # Server configuration
├── LICENSE                  # Apache 2.0
├── TRADEMARK.md             # Trademark policy
└── .gitignore
```

Each plugin at `plugins/<name>/` is self-contained: code, screens, data — everything in one place. Like WordPress. Standard layout: `screens/` for display templates, `data/` for runtime data, `*.py` for code.

## Core Components

### Session (`core/session.py`)

Manages connected users. Each connection gets a `Session` object that tracks:
- State (CONNECTED → LOGIN → MAIN_MENU → IN_PLUGIN → DISCONNECTED)
- Node number (1-N, where N = max_nodes)
- Terminal info (type, width, height)
- User identity (once authenticated)
- Byte counters + idle timer

Sessions are protocol-agnostic — telnet and SSH both create Session objects.

### Menu System (`core/menu.py`)

Hierarchical menu navigation. Each menu level is a list of `(key, label, handler)` tuples. Plugins register their menu items at load time.

```
Main Menu
├── [M] Message Board    → plugin: messageboard
├── [F] Files            → plugin: files
├── [B] Bulletins        → plugin: bulletin
├── [C] Chat             → plugin: chat
├── [U] User Profile     → plugin: usermgmt
├── [I] System Info      → built-in
└── [Q] Disconnect       → built-in
```

### Event Bus (`core/events.py`)

Publish/subscribe system for inter-module communication. Plugins emit events and subscribe to events without knowing about each other.

```python
# Emit an event
bbs.events.emit("user:login", {"user": user, "session": session})

# Listen for events
bbs.events.on("chat:message", handle_chat_message)
```

Events are async — handlers run in the event loop.

### Transport Layer (`core/transport/`)

Implements network protocols. Each transport:
1. Accepts connections
2. Performs protocol negotiation (telnet IAC / SSH handshake)
3. Creates a Session object
4. Bridges I/O between the network and the session

Adding a new transport (e.g., WebSocket) means implementing this interface.

## Plugin System

### Plugin Base Class (`plugins/base.py`)

```python
class Plugin:
    """Base class for all Modulo plugins."""
    
    name: str              # Unique identifier ("messageboard")
    version: str           # Semver ("1.0.0")
    menu_label: str        # Display text ("[M] Message Board")
    menu_key: str          # Hotkey ("M")
    
    def on_load(self, bbs):
        """Called once at startup. Register event handlers, etc."""
        pass
    
    def onUnload(self):
        """Called when plugin is being removed."""
        pass
    
    def on_session_start(self, session):
        """Called when a user connects."""
        pass
    
    def on_session_end(self, session):
        """Called when a user disconnects."""
        pass
    
    def handle_command(self, session, command):
        """Handle a command while this plugin is active."""
        pass
```

### Plugin Lifecycle

1. Server starts → scans `plugins/` directory
2. Each plugin's `__init__.py` exports a `Plugin` subclass
3. Core calls `plugin.on_load(bbs)` — plugin registers commands, events
4. Core adds plugin's menu item to main menu
5. User selects plugin → core calls `plugin.on_session_start(session)`
6. Plugin handles commands via `handle_command(session, cmd)`
7. User exits plugin → core calls `plugin.on_session_end(session)`
8. Server shutdown → core calls `plugin.on_unload()` for each plugin

### Plugin Storage

Each plugin gets its own subdirectory under `data/`:
```
data/
├── users/              # User accounts
├── messageboard/       # Message board data
├── files/              # File transfers
├── bulletins/          # System bulletins
└── chat/               # Chat logs
```

Plugins use `bbs.storage.get(plugin_name, key)` and `bbs.storage.set(plugin_name, key, value)` for persistence. Storage backend is pluggable (default: JSON files, SQLite available).

## API Layer

### Internal Python API

Plugins interact with the core via the `bbs` object:
- `bbs.send(session, data)` — send bytes to a user
- `bbs.broadcast(message)` — send to all connected users
- `bbs.storage.get/set` — persistent storage
- `bbs.events.emit/on` — event bus
- `bbs.users.get(username)` — user lookup
- `bbs.sessions.active` — list of active sessions

### External HTTP API

REST + WebSocket API for web frontends, mobile apps, CLI tools.

```
GET  /api/health              → Server status
GET  /api/sessions            → Active sessions
POST /api/auth/login          → Authenticate
GET  /api/messages            → Read messages
POST /api/messages            → Post message
GET  /api/files               → List files
WS   /ws/chat                 → Real-time chat
```

API authentication via API keys (not session passwords).

## Data Model

### User
```json
{
    "username": "dave",
    "password_hash": "...",
    "display_name": "Dave",
    "created": "2026-08-21T00:00:00Z",
    "last_login": "2026-08-21T12:00:00Z",
    "flags": ["sysop"],
    "stats": {
        "posts": 42,
        "files_uploaded": 5,
        "files_downloaded": 12,
        "time_online": 3600
    }
}
```

### Message
```json
{
    "id": 1,
    "board": "general",
    "author": "dave",
    "subject": "Welcome!",
    "body": "...",
    "timestamp": "2026-08-21T12:00:00Z",
    "parent_id": null,
    "tags": ["announcement"]
}
```

## Configuration

`config.yaml` — server settings, plugin options, API keys.

```yaml
server:
  host: "0.0.0.0"
  telnet_port: 6400
  ssh_port: 6422
  max_nodes: 8
  
auth:
  method: "local"  # local, ldap, oauth
  
plugins:
  enabled:
    - messageboard
    - files
    - bulletin
    - chat
    - usermgmt
  
api:
  enabled: true
  port: 8080
  keys:
    - name: "web-frontend"
      key: "..."
      permissions: ["read", "write"]
```
