# Modulo BBS — Plugin Development Guide

## Overview

Modulo uses a plugin architecture. Every feature (message boards, file areas, chat, etc.) is a plugin that registers with the core. This guide explains how to write your own plugins.

## Quick Start

### 1. Create the Plugin Directory

```bash
mkdir -p plugins/myplugin
```

### 2. Write the Plugin Class

```python
# plugins/myplugin/__init__.py
from plugins.base import Plugin

class MyPlugin(Plugin):
    name = "myplugin"
    version = "1.0.0"
    menu_label = "[X] My Plugin"
    menu_key = "X"
    
    def on_load(self, bbs):
        self.bbs = bbs
        # Register event handlers
        bbs.events.on("user:login", self.on_user_login)
    
    def on_session_start(self, session):
        pass
    
    def on_session_end(self, session):
        pass
    
    def handle_command(self, session, command):
        """Handle input while this plugin is active."""
        if command.strip().upper() == "QUIT":
            return False  # Return to main menu
        self.bbs.send(session, f"You said: {command}\r\n")
        return True  # Stay in plugin
```

### 3. Enable the Plugin

Add to `config.yaml`:
```yaml
plugins:
  enabled:
    - myplugin
```

### 4. Restart the Server

The plugin appears in the main menu automatically.

## Plugin Interface

### Required Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Unique identifier (lowercase, no spaces) |
| `version` | `str` | Semver version string |
| `menu_label` | `str` | Text shown in main menu |
| `menu_key` | `str` | Single character hotkey |

### Lifecycle Methods

| Method | When Called | Purpose |
|--------|------------|---------|
| `on_load(bbs)` | Server startup | Register events, load config |
| `on_unload()` | Server shutdown | Cleanup resources |
| `on_session_start(session)` | User connects | Per-session init |
| `on_session_end(session)` | User disconnects | Cleanup session data |
| `handle_command(session, cmd)` | User types input | Process commands |

### The `bbs` Object

Available after `on_load(bbs)`:

```python
# Send data to a user
bbs.send(session, "Hello!\r\n")
bbs.send_bytes(session, b"\x1b[32mGreen text\x1b[0m\r\n")

# Broadcast to all users
bbs.broadcast("System message!\r\n")

# Persistent storage
bbs.storage.get("myplugin", "key")        # Read
bbs.storage.set("myplugin", "key", value)  # Write
bbs.storage.list("myplugin")               # List keys

# Event bus
bbs.events.emit("my:event", {"data": 123})
bbs.events.on("other:event", handler)

# User management
user = bbs.users.get("dave")
bbs.users.list()
bbs.users.create(username, password, display_name)

# Active sessions
bbs.sessions.active  # List of active Session objects
bbs.sessions.count   # Number of active sessions
```

## Command Handling

### Returning from a Plugin

`handle_command()` returns a boolean:
- `True` — stay in the plugin, keep handling commands
- `False` — return to main menu

### Command Parsing

```python
def handle_command(self, session, command):
    parts = command.strip().split()
    if not parts:
        return True
    
    cmd = parts[0].upper()
    args = parts[1:]
    
    if cmd == "HELP":
        self.show_help(session)
    elif cmd == "READ":
        self.read_post(session, args)
    elif cmd == "POST":
        self.create_post(session, args)
    elif cmd == "QUIT":
        return False
    else:
        self.bbs.send(session, f"Unknown command: {cmd}\r\n")
    
    return True
```

## Storage API

### Key-Value Storage

Simple key-value pairs:
```python
# Store a value
bbs.storage.set("myplugin", "counter", 42)

# Retrieve a value
count = bbs.storage.get("myplugin", "counter", default=0)

# List all keys
keys = bbs.storage.list("myplugin")

# Delete a key
bbs.storage.delete("myplugin", "counter")
```

### Complex Data

Store dicts/lists as JSON:
```python
import json

post = {
    "id": 1,
    "author": "dave",
    "subject": "Hello",
    "body": "First post!",
    "timestamp": "2026-08-21T12:00:00Z"
}

bbs.storage.set("messageboard", "post_1", post)
```

### File-Based Storage

For large data, use the filesystem directly:
```python
from pathlib import Path

plugin_dir = Path("data/myplugin")
plugin_dir.mkdir(exist_ok=True)

# Write a file
(plugin_dir / "config.json").write_text(json.dumps(config))

# Read a file
config = json.loads((plugin_dir / "config.json").read_text())
```

## Event System

### Emitting Events

```python
# Simple event
bbs.events.emit("myplugin:new_post", {"post_id": 42})

# Event with session context
bbs.events.emit("myplugin:user_action", {
    "session": session,
    "action": "read",
    "target": "post_42"
})
```

### Listening for Events

```python
def on_load(self, bbs):
    # Listen for events from other plugins
    bbs.events.on("user:login", self.handle_login)
    bbs.events.on("chat:message", self.handle_chat)
    
    # Listen for your own events
    bbs.events.on("myplugin:new_post", self.notify_mods)

def handle_login(self, event):
    username = event["user"].username
    self.bbs.broadcast(f"{username} has logged in.\r\n")
```

### Event Naming Convention

```
<namespace>:<action>

Examples:
user:login
user:logout
chat:message
messageboard:new_post
files:upload
system:shutdown
```

## UI Patterns

### Sending Formatted Text

```python
from shared.telnet_protocol import ANSI

# Colored text
self.bbs.send(session, f"{ANSI.BRIGHT_GREEN}Success!{ANSI.RESET}\r\n")

# Bold
self.bbs.send(session, f"{ANSI.BOLD}Important:{ANSI.RESET} read this\r\n")

# Clear screen
self.bbs.send(session, f"\033[2J\033[1;1H")
```

### Menu Display

```python
def show_menu(self, session):
    menu = (
        "\r\n"
        "=== My Plugin ===\r\n"
        "\r\n"
        "  [R] Read Posts\r\n"
        "  [P] New Post\r\n"
        "  [S] Search\r\n"
        "  [Q] Back to Main Menu\r\n"
        "\r\n"
        "  Select: "
    )
    self.bbs.send(session, menu)
```

### Pagination

```python
def show_list(self, session, items, page=0, per_page=10):
    start = page * per_page
    end = start + per_page
    page_items = items[start:end]
    
    for item in page_items:
        self.bbs.send(session, f"  {item['id']}. {item['subject']}\r\n")
    
    if end < len(items):
        self.bbs.send(session, "\r\n  [N] Next page\r\n")
    if page > 0:
        self.bbs.send(session, "  [P] Previous page\r\n")
```

## Best Practices

### 1. Don't Block the Event Loop

All I/O must be async:
```python
# Good
async def load_data(self):
    data = await self.bbs.storage.async_get("key")

# Bad — blocks all other sessions
def load_data(self):
    data = open("file.txt").read()
```

### 2. Clean Up on Unload

```python
def on_unload(self):
    # Close database connections
    # Cancel background tasks
    # Remove event listeners
    pass
```

### 3. Handle Edge Cases

```python
def handle_command(self, session, command):
    if not command.strip():
        self.show_menu(session)
        return True
    
    # Validate input
    if len(command) > 1000:
        self.bbs.send(session, "Command too long.\r\n")
        return True
    
    # Handle unknown commands gracefully
    try:
        self.process_command(session, command)
    except Exception as e:
        logger.error(f"Command error: {e}")
        self.bbs.send(session, "An error occurred.\r\n")
    
    return True
```

### 4. Log Important Events

```python
import logging

logger = logging.getLogger("myplugin")

def on_load(self, bbs):
    logger.info("MyPlugin loaded")
    
def handle_command(self, session, command):
    logger.debug(f"Session {session.session_id}: {command}")
```

### 5. Test with the AsyncSSH Client

Quick test without Syncterm:
```bash
python3 -c "
import asyncio, asyncssh
class S(asyncssh.SSHClientSession):
    def data_received(self, data, d):
        print(data.decode('latin-1', errors='replace'), end='')
async def run():
    async with asyncssh.connect('127.0.0.1', 6422, known_hosts=None) as c:
        ch, s = await c.create_session(S, term_type='xterm')
        await asyncio.sleep(1)
        ch.write('X\r\n')  # Select your plugin
        await asyncio.sleep(1)
        ch.write('QUIT\r\n')
        await asyncio.sleep(1)
asyncio.run(run())
"
```

## Example: Minimal Plugin

```python
# plugins/hello/__init__.py
from plugins.base import Plugin

class HelloPlugin(Plugin):
    name = "hello"
    version = "1.0.0"
    menu_label = "[H] Hello World"
    menu_key = "H"
    
    def on_load(self, bbs):
        self.bbs = bbs
        self.greetings = 0
    
    def handle_command(self, session, command):
        cmd = command.strip().upper()
        
        if cmd == "QUIT":
            return False
        
        if cmd == "HELLO":
            self.greetings += 1
            self.bbs.send(session, 
                f"Hello, {session.username or 'stranger'}! "
                f"(greeting #{self.greetings})\r\n")
        elif cmd == "COUNT":
            self.bbs.send(session, 
                f"Total greetings: {self.greetings}\r\n")
        else:
            self.bbs.send(session, 
                "Commands: HELLO, COUNT, QUIT\r\n")
        
        return True
```
