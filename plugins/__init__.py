"""
Modulo BBS plugin system.

Plugins are self-contained modules that extend the BBS. Each plugin
subclasses :class:`Plugin` and the loader discovers them by scanning
the ``plugins/`` directory, importing each package, and collecting the
exported ``Plugin`` subclass.
"""

from .base import Plugin

__all__ = ["Plugin"]