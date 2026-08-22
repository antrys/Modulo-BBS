"""Per-plugin data-directory storage for Modulo BBS core.

Every plugin owns ``plugins/<name>/data/`` for its runtime data (JSON,
SQLite, flat files -- whatever it wants). This module hands out that
directory as a :class:`~pathlib.Path`, creating it on first access, so a
plugin never hard-codes paths and never writes outside its own sandbox.

Deliberately minimal: there is no key-value layer. Plugins compose standard
``pathlib`` / ``json`` calls against the returned Path -- simple, inspectable,
and identical to how core itself stores users (one JSON file per record).

Accessed by plugins as ``bbs.storage.dir(plugin_name)``.
"""

from __future__ import annotations

import re
from pathlib import Path

# Conservative alphabet for plugin names used as directory names -- same
# rule as usernames. Prevents traversal ("../core") and absolute paths.
_PLUGIN_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


class StorageError(Exception):
    """Raised for invalid plugin names or unusable storage roots."""


class PluginStorage:
    """Resolve and create per-plugin data directories under ``plugins/``."""

    def __init__(self, plugins_dir: str | Path | None = None):
        if plugins_dir is None:
            # Default: "<project root>/plugins" (two levels up from here).
            plugins_dir = Path(__file__).resolve().parent.parent / "plugins"
        self.plugins_dir = Path(plugins_dir)

    def dir(self, plugin_name: str) -> Path:
        """Return (and create) the data directory for ``plugin_name``.

        The directory is ``<plugins_dir>/<plugin_name>/data/`` and is created
        lazily so a plugin's first write always succeeds. Raises
        :class:`StorageError` for names outside the permitted alphabet.
        """
        if not isinstance(plugin_name, str) or not _PLUGIN_NAME_RE.match(
            plugin_name
        ):
            raise StorageError(
                f"Invalid plugin name {plugin_name!r}: must match "
                f"{_PLUGIN_NAME_RE.pattern}"
            )
        path = self.plugins_dir / plugin_name / "data"
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise StorageError(f"Cannot create data dir for {plugin_name!r}: {e}") from e
        return path


__all__ = ["PluginStorage", "StorageError"]
