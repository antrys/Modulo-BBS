# Modulo BBS — Plugin System Specification

*First draft — 2026-08-21*

## Overview

Modulo BBS uses a plugin-based architecture. Every feature (message boards, file areas, chat, etc.) is a plugin that registers with the core. The core provides session management, user model, event bus, and transport. Plugins provide everything else.

## Design Principles

1. **Core is minimal** — session management, user model, event bus, transport
2. **Plugins are replaceable** — swap the menu system, auth flow, or message board without touching core
3. **Events are the nervous system** — core fires lifecycle events, plugins listen and react
4. **Storage is convention-based** — `data/<plugin_name>/` for each plugin, do whatever inside
5. **Everything references the User model** — plugins don't re-invent user data

## Architecture Layers

```
┌─────────────────────────────────────────────────┐
│                   Transport                      │
│              (telnet / SSH / API)                │
├─────────────────────────────────────────────────┤
│                    Core                          │
│  Session Manager │ User Model │ Event Bus       │
├─────────────────────────────────────────────────┤
│                  Plugins                         │
│  Auth │ Menu │ MessageBoard │ Files │ Chat │ .. │
├─────────────────────────────────────────────────┤
│                  Storage                         │
│          data/<plugin_name>/                     │
└─────────────────────────────────────────────────┘
```

## Core Components

### Session Manager

Manages connected users. Each connection gets a `Session` object.

```python
class Session:
    session_id: str
    node_id: int
    state: SessionState          # CONNECTED → LOGIN → MAIN_MENU → IN_PLUGIN → DISCONNECTED
    transport: str               # "telnet" | "ssh" | "api"
    user: User | None            # Set after authentication
    authenticated: bool
    terminal_type: str
    terminal_width: int
    terminal_height: int
    bytes_sent: int
    bytes_received: int
    connected_at: datetime
    last_active: datetime
```

### User Model

Core owns the User model. Every plugin references it.

```python
class User:
    username: str                # Unique, immutable
    display_name: str            # How they appear to others
    password_hash: str           # bcrypt
    email: str
    created: datetime
    last_login: datetime
    flags: list[str]             # ["sysop", "mod", "user"]
    stats: dict                  # Per-plugin stats (posts, files, etc.)
    preferences: dict            # Theme, notifications, etc.
```

**Core provides:**
- `bbs.users.get(username)` → User
- `bbs.users.create(username, password, display_name)` → User
- `bbs.users.update(username, **fields)` → User
- `bbs.users.delete(username)` → bool
- `bbs.users.list()` → list[User]
- `user.has_flag("mod")` → bool
- `user.has_permission("messageboard:delete")` → bool

**Core owns:** `data/users/` directory

### Auth System (Dual-Layer)

| Layer | Owner | Responsibility |
|-------|-------|----------------|
| User model + storage | Core | Data structure, CRUD, session binding |
| Auth flows | Plugin | Login screen, registration, password handling |

**Why split:** The User model is infrastructure — everything depends on it. Auth flows (how you authenticate) are replaceable. Someone can swap passwords for OAuth without breaking the User model.

**Auth plugin interface:**
```python
class AuthPlugin(Plugin):
    def handle_login(self, session) -> bool:
        """Show login screen, collect credentials, validate.
        Set session.user on success. Return False if user disconnects."""
        pass
    
    def handle_registration(self, session) -> bool:
        """Show registration screen, collect info, create user.
        Return False if user disconnects."""
        pass
    
    def handle_password_change(self, session, user) -> bool:
        """Optional: password change flow."""
        pass
```

**Core's only auth check:**
```python
if not session.authenticated:
    # Run auth plugin
    auth_plugin.handle_login(session)
```

### Event Bus

The nervous system. Core fires events, plugins listen. This is how the core maintains observability when plugins replace core components.

```python
# Emit an event
bbs.events.emit("user:login", {"user": user, "session": session})

# Listen for events
bbs.events.on("user:login", handle_login)

# Listen once
bbs.events.once("session:disconnect", cleanup)

# Remove listener
bbs.events.off("user:login", handle_login)
```

#### Core Lifecycle Events (always fired, can't be suppressed)

| Event | When | Data |
|-------|------|------|
| `session:connect` | User connects | `{session}` |
| `session:disconnect` | User disconnects | `{session}` |
| `user:login` | Authenticated | `{session, user}` |
| `user:logout` | Logged out | `{session, user}` |
| `menu:open` | Menu displayed | `{session, menu_name}` |
| `menu:select` | User selected option | `{session, option, menu_name}` |
| `command:pre` | Before command executes | `{session, command, plugin}` |
| `command:post` | After command executes | `{session, command, plugin, result}` |

#### Plugin Events (fired by plugins)

| Event | Plugin | Data |
|-------|--------|------|
| `messageboard:post` | messageboard | `{session, post}` |
| `messageboard:reply` | messageboard | `{session, reply, parent}` |
| `files:upload` | files | `{session, filename, size}` |
| `files:download` | files | `{session, filename}` |
| `chat:message` | chat | `{session, channel, message}` |
| `auth:register` | auth | `{session, user}` |
| `auth:login_failed` | auth | `{session, username, reason}` |

#### Event Flow Example

```
User presses "M" in main menu
  ↓
Core emits: menu:select {session, option: "M", menu: "main"}
  ↓
  ├→ Messageboard plugin handles it (shows message board)
  ├→ Stats plugin increments menu_selections counter
  └→ Audit log plugin records it
  ↓
Core emits: menu:open {session, menu: "messageboard"}
```

**Key insight:** Even if a plugin replaces the menu system, the core still fires `menu:select`. Instrumentation works regardless of which plugin handles the UI.

## Plugin System

### Plugin Base Class

```python
class Plugin:
    """Base class for all Modulo BBS plugins."""
    
    name: str              # Unique identifier ("messageboard")
    version: str           # Semver ("1.0.0")
    description: str       # Human-readable description
    menu_label: str        # Display text ("[M] Message Board")
    menu_key: str          # Hotkey ("M")
    menu_order: int        # Sort order in main menu (lower = higher)
    
    def on_load(self, bbs):
        """Called once at startup. Register event handlers."""
        pass
    
    def on_unload(self):
        """Called when plugin is being removed."""
        pass
    
    def on_session_start(self, session):
        """Called when a user connects."""
        pass
    
    def on_session_end(self, session):
        """Called when a user disconnects."""
        pass
    
    def handle_command(self, session, command) -> bool:
        """Handle a command while this plugin is active.
        Return True to stay in plugin, False to return to menu."""
        pass
```

### Plugin Lifecycle

1. Server starts → scans `plugins/` directory
2. Each plugin's `__init__.py` exports a `Plugin` subclass
3. Core calls `plugin.on_load(bbs)` — plugin registers commands, events
4. Core adds plugin's menu item to main menu
5. User selects plugin → core emits `menu:select`, calls `plugin.on_session_start(session)`
6. Plugin handles commands via `handle_command(session, cmd)`
7. User exits plugin → core calls `plugin.on_session_end(session)`
8. Server shutdown → core calls `plugin.on_unload()` for each plugin

### Plugin Directory Structure

Each plugin is a self-contained directory at `plugins/<name>/`. Code, data, screens — everything lives in one place. Like WordPress.

### Standard Plugin Directory Layout

```
plugins/
├── base.py                    # Plugin interface
├── login/                     # Login plugin (example)
│   ├── __init__.py            # Plugin class
│   ├── login.py               # Login logic
│   ├── totp.py                # TOTP support
│   ├── screens/               # ← Display templates (sysops edit here)
│   │   ├── login.txt
│   │   ├── register.txt
│   │   └── totp.txt
│   └── data/                  # Runtime data
│       └── totp_secrets.json
├── messageboard/
│   ├── __init__.py
│   ├── screens/
│   │   ├── board_list.txt
│   │   ├── thread_view.txt
│   │   └── post_editor.txt
│   └── data/
│       ├── boards.json
│       └── posts/
└── files/
    ├── __init__.py
    ├── screens/
    │   ├── file_list.txt
    │   └── upload.txt
    └── data/
        └── uploads/
```

**Convention:**
- `screens/` — display templates (sysops edit these to customize look)
- `data/` — runtime data (JSON, SQLite, files)
- `*.py` — plugin code

**Rule:** Everything for a plugin lives in `plugins/<name>/`. Don't touch `plugins/<other_name>/`.

**Exception:** Core owns `users/` at the root level since everything references users.

### Plugin Storage

Each plugin has a `data/` subdirectory for runtime data. The plugin decides what goes inside — JSON, SQLite, flat files, whatever.

```python
# Get plugin's data directory
plugin_dir = bbs.storage.dir("messageboard") → Path("plugins/messageboard/data/")

# Simple key-value (optional convenience)
bbs.storage.get("messageboard", "last_post_id") → int
bbs.storage.set("messageboard", "last_post_id", 42)
```

Plugins that need complex storage just use their `data/` directory directly. The API is optional — not required.

## Permission System

### Flags

Users have flags that determine access level:

| Flag | Description |
|------|-------------|
| `sysop` | Full system access |
| `admin` | User management, system config |
| `mod` | Content moderation |
| `user` | Standard access (default) |
| `guest` | Read-only access |

### Permissions

Plugins define their own permissions:

```python
# In messageboard plugin
"messageboard:read"      # Read posts
"messageboard:post"      # Create posts
"messageboard:delete"    # Delete any post (mod)
"messageboard:delete_own" # Delete own posts (user)
```

### Checking Permissions

```python
# In a plugin
if session.user.has_permission("messageboard:delete"):
    # Allow deletion
else:
    bbs.send(session, "Permission denied.\r\n")
```

## HTTP API (Future)

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

## Configuration

`config.yaml` — server settings, plugin options.

```yaml
server:
  host: "0.0.0.0"
  telnet_port: 6400
  ssh_port: 6422
  max_nodes: 8
  
plugins:
  enabled:
    - login
    - mainmenu
    - messageboard
    - files
    - chat
  
storage:
  backend: "json"  # json | sqlite (future)
```

## Logon Sequence (Sysop-Configurable)

The order of what a caller sees — splash screens, login, bulletins, menu — is
data, not code. Core owns the **sequence runner**; everything in the sequence
is pluggable. There is no `built-in` step type.

```yaml
logon_sequence:
  - screen:splash.txt        # sysop splash (MODULO blockletters lives here)
  - plugin:login             # auth + optional TOTP
  - screen:welcome.txt       # welcome mat
  - plugin:bulletins         # new-since-last-call (skips itself if nothing new)
  - plugin:mainmenu          # the menu is just another plugin
```

### Step types

| Step | What it does |
|------|--------------|
| `plugin:<name>` | Run the named plugin's session flow |
| `screen:<file>` | Display `screens/<file>`, no input |

Sysops reorder, remove, or duplicate steps freely. Two splash screens before
login? Add two `screen:` lines. Don't want bulletins? Delete the line.

### Why core owns the runner

1. **State machine lives in core.** The sequence is where the session
   transitions from CONNECTED → AUTHENTICATED → IN_MENU; core must gate on it.
2. **Observability.** Each step emits `logon:step {session, step, result}` so
   instrumentation sees the whole flow even when sysops reorder it.
3. **Transport consistency.** Telnet and SSH run the same sequence through one
   code path — no per-transport hardcoded flows (and one renderer kills the
   screen-width wrapping class of bugs).

### Main menu is a plugin

There is no core menu system. A `mainmenu` plugin iterates `bbs.plugins`,
sorts by `menu_order`, and renders each plugin's `menu_label` / `menu_key`
(every plugin already self-describes via the base class). Swap in a different
menu plugin and nothing else changes.

### Hard boundary: disconnect

Plugins interpret keystrokes (`Q` → return False), but closing the socket is a
core primitive: `bbs.disconnect(session)`. Plugins never touch the writer
directly, so a buggy plugin can always be cleaned up reliably by core.

## Implementation Order

1. Plugin base class + loader ✓
2. Event bus ✓
3. User model + storage ✓
4. Login plugin ✓
5. Logon sequence runner (core) + config-driven step list
6. Mainmenu plugin (extract from server.py)
7. Message board plugin
8. File transfer plugin
9. Chat plugin
10. HTTP API
