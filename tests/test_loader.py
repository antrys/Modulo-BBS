"""Tests for core.loader.PluginLoader.

Covers discovery of the real login plugin from the default ``plugins/``
directory, subclass detection, and graceful skipping of broken plugins
(import failure, no ``Plugin`` subclass, ``on_load`` raising). Fake plugins
are built in a throwaway directory that is exposed to ``importlib`` as the
``plugins`` package (with the real base module reachable) so nothing in the
real tree is touched or modified.
"""

import asyncio
import sys
import types
from pathlib import Path

from core.app import BBSApp
from core.loader import PluginLoader
from plugins.base import Plugin
from plugins.login import LoginPlugin

# The real plugins/ directory (so temp plugins can ``from plugins.base import Plugin``).
_REAL_PLUGINS = Path(__file__).resolve().parent.parent / "plugins"


def make_bbs(tmp_path) -> BBSApp:
    """A BBSApp bound to a throwaway users directory."""
    return BBSApp(users_dir=tmp_path / "users")


def run(coro):
    return asyncio.run(coro)


def _fake_plugins(monkeypatch, tmp_path) -> Path:
    """Build a throwaway plugins dir reachable as the ``plugins`` package.

    Returns the temp directory. ``plugins.base`` still resolves from the real
    tree via a second entry on the package path.
    """
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    pkg = types.ModuleType("plugins")
    pkg.__path__ = [str(plugins_dir), str(_REAL_PLUGINS)]
    monkeypatch.setitem(sys.modules, "plugins", pkg)
    return plugins_dir


def _write_plugin(plugins_dir: Path, name: str, source: str):
    plugin_dir = plugins_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "__init__.py").write_text(source, encoding="utf-8")


# ---------------------------------------------------------------------------
# Discovery / integration
# ---------------------------------------------------------------------------

def test_loader_discovers_and_loads_login_plugin(tmp_path):
    bbs = make_bbs(tmp_path)
    plugins = run(PluginLoader().load(bbs))     # default plugins/ directory

    login = next((p for p in plugins if p.name == "login"), None)
    assert login is not None
    assert isinstance(login, LoginPlugin)
    assert isinstance(login, Plugin)
    # on_load was called with the shared bbs object.
    assert login.bbs is bbs


def test_on_load_stores_bbs_reference(tmp_path):
    bbs = make_bbs(tmp_path)
    plugins = run(PluginLoader().load(bbs))
    login = next(p for p in plugins if p.name == "login")
    assert login.bbs is bbs


# ---------------------------------------------------------------------------
# Subclass detection
# ---------------------------------------------------------------------------

def test_find_plugin_class_ignores_base_and_non_plugins():
    mod = types.ModuleType("demo")
    mod.Plugin = Plugin                      # the base itself -> excluded
    mod.not_a_plugin = 42                    # non-class value -> ignored

    class Good(Plugin):
        name = "good"

    mod.Good = Good
    assert PluginLoader._find_plugin_class(mod) is Good


def test_find_plugin_class_returns_none_when_absent():
    mod = types.ModuleType("nope")
    mod.Plugin = Plugin
    mod.helper = lambda: None
    assert PluginLoader._find_plugin_class(mod) is None


# ---------------------------------------------------------------------------
# Graceful error handling
# ---------------------------------------------------------------------------

def test_loader_skips_plugin_without_subclass(tmp_path, monkeypatch):
    plugins_dir = _fake_plugins(monkeypatch, tmp_path)
    _write_plugin(plugins_dir, "noclass", "class NotAPlugin: pass\n")
    plugins = run(PluginLoader(plugins_dir).load(make_bbs(tmp_path)))
    assert plugins == []


def test_loader_skips_plugin_that_fails_to_import(tmp_path, monkeypatch):
    plugins_dir = _fake_plugins(monkeypatch, tmp_path)
    _write_plugin(
        plugins_dir, "broken",
        "import this_module_does_not_exist_xyz\n",
    )
    plugins = run(PluginLoader(plugins_dir).load(make_bbs(tmp_path)))
    assert plugins == []


def test_loader_skips_plugin_that_raises_on_load(tmp_path, monkeypatch):
    plugins_dir = _fake_plugins(monkeypatch, tmp_path)
    _write_plugin(
        plugins_dir, "boom",
        "from plugins.base import Plugin\n"
        "class Boom(Plugin):\n"
        "    name = 'boom'\n"
        "    def on_load(self, bbs):\n"
        "        raise RuntimeError('boom')\n",
    )
    plugins = run(PluginLoader(plugins_dir).load(make_bbs(tmp_path)))
    assert [p.name for p in plugins] == []


def test_loader_keeps_good_and_skips_broken_mix(tmp_path, monkeypatch):
    plugins_dir = _fake_plugins(monkeypatch, tmp_path)
    _write_plugin(
        plugins_dir, "good",
        "from plugins.base import Plugin\n"
        "class Good(Plugin):\n"
        "    name = 'good'\n"
        "    def on_load(self, bbs):\n"
        "        self.loaded = bbs\n",
    )
    _write_plugin(plugins_dir, "bad", "class NotAPlugin: pass\n")
    bbs = make_bbs(tmp_path)
    plugins = run(PluginLoader(plugins_dir).load(bbs))
    assert len(plugins) == 1
    assert plugins[0].name == "good"
    assert plugins[0].loaded is bbs


def test_loader_awaits_async_on_load(tmp_path, monkeypatch):
    plugins_dir = _fake_plugins(monkeypatch, tmp_path)
    _write_plugin(
        plugins_dir, "asyncp",
        "from plugins.base import Plugin\n"
        "import asyncio\n"
        "class AsyncP(Plugin):\n"
        "    name = 'asyncp'\n"
        "    async def on_load(self, bbs):\n"
        "        await asyncio.sleep(0)\n"
        "        self.loaded = bbs\n",
    )
    bbs = make_bbs(tmp_path)
    plugins = run(PluginLoader(plugins_dir).load(bbs))
    assert len(plugins) == 1
    assert plugins[0].loaded is bbs


def test_loader_returns_empty_when_directory_missing(tmp_path):
    missing = tmp_path / "no_such_plugins"
    plugins = run(PluginLoader(missing).load(make_bbs(tmp_path)))
    assert plugins == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))