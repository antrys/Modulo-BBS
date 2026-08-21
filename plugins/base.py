"""
Plugin base class — the interface contract every Modulo BBS plugin implements.

A plugin is a self-contained component (message board, file area, chat, auth
flow, door game, ...) that registers with the core. This class defines the
shape a plugin must present; subclasses override the class attributes and
lifecycle hooks as needed. The class is intentionally dependency-free so it
can be imported standalone by the plugin loader.

Contract
--------
Attributes
    Every subclass MUST define these metadata attributes, which the core
    reads to register and display the plugin::

        name         unique, stable identifier, e.g. "messageboard"
        version      semantic version, e.g. "1.0.0"
        description  one-line human-readable summary
        menu_label   display text shown in the main menu ("[M] Message Board")
        menu_key     single-character hotkey ("M")
        menu_order   sort position in the main menu (lower = higher)

    ``menu_label`` and ``menu_order`` default to sensible values if a plugin
    overrides them; ``name`` and ``version`` must be provided.

Lifecycle
    The core drives a plugin through its lifecycle:
        on_load           called once at startup; register events/handlers
        on_unload         called when the plugin is being removed/shutdown
        on_session_start  called when a user enters the plugin
        on_session_end    called when a user leaves the plugin
        handle_command    called for each command while the plugin is active;
                          return True to stay active, False to return to the menu

    All lifecycle hooks are optional — the defaults are safe no-ops, so a
    plugin only overrides the ones it needs.
"""

from typing import Any


class Plugin:
    """Base class for all Modulo BBS plugins."""

    # Metadata (subclasses must set name and version)
    name: str = ""             # Unique identifier ("messageboard")
    version: str = "0.0.0"     # Semver ("1.0.0")
    description: str = ""      # Human-readable description
    menu_label: str = ""       # Display text ("[M] Message Board")
    menu_key: str = ""         # Hotkey ("M")
    menu_order: int = 100      # Sort order in main menu (lower = higher)

    def on_load(self, bbs: Any) -> None:
        """Called once at startup. Register event handlers and resources.

        Args:
            bbs: The core BBS server object (event bus, storage, etc.).
        """

    def on_unload(self) -> None:
        """Called when the plugin is being removed or the server shuts down.
        Release any resources the plugin acquired during :meth:`on_load`."""

    def on_session_start(self, session: Any) -> None:
        """Called when a user connects / enters this plugin.

        Args:
            session: The active BBS session.
        """

    def on_session_end(self, session: Any) -> None:
        """Called when a user disconnects / leaves this plugin.

        Args:
            session: The session that is ending.
        """

    def handle_command(self, session: Any, command: str) -> bool:
        """Handle a command while this plugin is active.

        Args:
            session: The active BBS session.
            command: The raw command line entered by the user.

        Returns:
            True to stay in the plugin, False to return to the menu.
        """
        return False