"""Plugin loader for Modulo BBS.

Discovers plugins by scanning ``plugins/<name>/__init__.py``, imports each
package, finds the exported :class:`Plugin` subclass, instantiates it, and
runs ``on_load(bbs)`` with the shared application object. A broken plugin is
logged and skipped so a single bad plugin can never prevent the server from
starting.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
from typing import Any

from plugins.base import Plugin

logger = logging.getLogger("modulo.core.loader")


class PluginLoader:
    """Find and load Modulo BBS plugins from a ``plugins/`` directory.

    ``on_load`` may be sync or async; the loader awaits any coroutine it
    returns, per the await-if-coroutine rule in ``plugins.base``.
    """

    def __init__(self, plugins_dir=None):
        """Initialize the loader.

        Args:
            plugins_dir: Directory to scan for ``<name>/__init__.py`` plugin
                packages. Defaults to ``<project root>/plugins/``.
        """
        if plugins_dir is None:
            plugins_dir = Path(__file__).resolve().parent.parent / "plugins"
        self.plugins_dir = Path(plugins_dir)

    async def load(self, bbs) -> list[Plugin]:
        """Scan, import, instantiate and load every discoverable plugin.

        Returns the list of successfully loaded plugin instances in
        directory-name order. A plugin that fails to import, exposes no
        ``Plugin`` subclass, or raises during construction / ``on_load`` is
        logged and skipped.
        """
        loaded: list[Plugin] = []
        if not self.plugins_dir.is_dir():
            logger.warning("Plugin directory not found: %s", self.plugins_dir)
            return loaded

        for init_path in sorted(self.plugins_dir.glob("*/__init__.py")):
            package = f"plugins.{init_path.parent.name}"
            plugin = await self._load_one(package, bbs)
            if plugin is not None:
                loaded.append(plugin)
        return loaded

    async def _load_one(self, package: str, bbs) -> Plugin | None:
        """Load a single plugin package; return its instance or None."""
        try:
            module = importlib.import_module(package)
        except Exception:
            logger.exception("Failed to import plugin %r; skipping", package)
            return None

        cls = self._find_plugin_class(module)
        if cls is None:
            logger.warning(
                "No Plugin subclass found in %r; skipping", package
            )
            return None

        try:
            plugin = cls()
            # on_load may be sync or async (await-if-coroutine rule,
            # see plugins.base) -- await it when it returns a coroutine.
            result: Any = plugin.on_load(bbs)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("Failed to load plugin %r (on_load); skipping", package)
            return None
        return plugin

    @staticmethod
    def _find_plugin_class(module: Any) -> type[Plugin] | None:
        """Return the first real ``Plugin`` subclass exported by ``module``.

        Walks the module's attributes and returns the first class that is a
        subclass of :class:`Plugin` other than ``Plugin`` itself. Non-plugin
        attributes (imports, helpers) are ignored.
        """
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, Plugin)
                and attr is not Plugin
            ):
                return attr
        return None


__all__ = ["PluginLoader"]