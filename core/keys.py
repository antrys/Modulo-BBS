"""Per-plugin keybinding loader for Modulo BBS.

Every plugin may ship a ``keys`` file in its plugin directory binding
command names to keys, one per line::

    T, TRADEWARS
    Q, QUIT
    # comments start with #

Semantics (see docs/plugin-spec.md, "Keybindings"):

* The plugin supplies *defaults*: ``{"QUIT": "Q", "LIST": "L", ...}``.
* If the file is absent, defaults pass through unchanged.
* A name **omitted** from the file means that command is DISABLED -- the
  loader omits it from the returned mapping entirely.
* A line naming a command unknown to the defaults is ignored with a
  logged warning (fail-safe against sysop typos).
* Keys are uppercased on load; matching is case-insensitive.
* Lines starting with ``#`` are comments; blank lines are ignored;
  ``\\r\\n`` endings tolerated.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("modulo.core.keys")

_LINE_RE = re.compile(r"^\s*([^,\s]+)\s*,\s*(.+?)\s*$")


def load_keys(
    plugins_dir: Path | str,
    plugin_name: str,
    defaults: dict[str, str],
) -> dict[str, str]:
    """Load keybindings for ``plugin_name`` from ``plugins/<name>/keys``.

    Returns ``{NAME: KEY}`` with NAME uppercased. See module docstring for
    semantics. Never raises for file problems -- worst case it returns
    defaults (or a best-effort subset) and logs.
    """
    defaults = {k.upper(): v for k, v in (defaults or {}).items()}
    path = Path(plugins_dir) / plugin_name / "keys"
    if not path.is_file():
        return dict(defaults)

    bound: dict[str, str] = {}
    seen_names: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:  # unreadable -> fall back to defaults
        logger.warning("keys file %s unreadable (%s); using defaults", path, e)
        return dict(defaults)

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            logger.warning("%s:%d: unparseable line %r ignored", path, lineno, raw)
            continue
        key, name = m.group(1).upper(), m.group(2).upper()
        if name not in defaults:
            logger.warning(
                "%s:%d: unknown command %r ignored (not in defaults)", path, lineno, name
            )
            continue
        bound[name] = key
        seen_names.add(name)

    # Omitted names are disabled: only return what the file explicitly binds.
    return bound


def load_keys_or_defaults(
    plugins_dir: Path | str,
    plugin_name: str,
    defaults: dict[str, str],
) -> dict[str, str]:
    """Like :func:`load_keys`, but if no keys file exists, returns defaults.

    Convenience wrapper making the "file present => file rules; file absent
    => defaults" split explicit at the call site. Plugins that want the
    omit-means-disabled behaviour call :func:`load_keys` directly.
    """
    path = Path(plugins_dir) / plugin_name / "keys"
    if not path.is_file():
        return {k.upper(): v for k, v in (defaults or {}).items()}
    return load_keys(plugins_dir, plugin_name, defaults)
