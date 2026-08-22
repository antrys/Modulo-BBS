"""Tests for the per-plugin keybinding loader (core/keys.py)."""
from core.app import BBSApp
from core.keys import load_keys


DEFAULTS = {"QUIT": "Q", "LIST": "L", "POST": "P"}


def _write_keys(tmp_path, plugin_name, text):
    pdir = tmp_path / "plugins" / plugin_name
    pdir.mkdir(parents=True)
    (pdir / "keys").write_text(text, encoding="utf-8")
    return tmp_path / "plugins"


def test_no_file_returns_defaults(tmp_path):
    result = load_keys(tmp_path / "plugins", "messageboard", DEFAULTS)
    assert result == {"QUIT": "Q", "LIST": "L", "POST": "P"}


def test_disabled_by_omission(tmp_path):
    # Only QUIT is listed: LIST and POST are disabled (omitted from result).
    plugins = _write_keys(tmp_path, "messageboard", "# keep quit only\nQ, QUIT\n")
    result = load_keys(plugins, "messageboard", DEFAULTS)
    assert result == {"QUIT": "Q"}


def test_sysop_rebinds_key(tmp_path):
    plugins = _write_keys(
        tmp_path,
        "messageboard",
        "X, QUIT\nK, LIST\nJ, POST\n",
    )
    result = load_keys(plugins, "messageboard", DEFAULTS)
    assert result == {"QUIT": "X", "LIST": "K", "POST": "J"}


def test_unknown_name_warned_and_skipped(tmp_path):
    plugins = _write_keys(tmp_path, "messageboard", "Q, QUIT\nZ, FROBNICATE\n")
    result = load_keys(plugins, "messageboard", DEFAULTS)
    assert result == {"QUIT": "Q"}  # FROBNICATE not in defaults -> ignored


def test_comments_blanks_and_case(tmp_path):
    plugins = _write_keys(
        tmp_path,
        "messageboard",
        "# comment line\r\n\r\n   \r\nq, quit\r\nl , list \r\n",
    )
    result = load_keys(plugins, "messageboard", DEFAULTS)
    # keys and names normalise to uppercase; whitespace tolerated
    assert result == {"QUIT": "Q", "LIST": "L"}


def test_unparseable_line_skipped(tmp_path):
    plugins = _write_keys(
        tmp_path,
        "messageboard",
        "Q, QUIT\ngarbage-line-no-comma\nP, POST\n",
    )
    result = load_keys(plugins, "messageboard", DEFAULTS)
    assert result == {"QUIT": "Q", "POST": "P"}


def test_unreadable_file_falls_back_to_defaults(tmp_path, monkeypatch):
    plugins = _write_keys(tmp_path, "messageboard", "Q, QUIT\n")
    import core.keys as keys_mod

    def fake_read_text(self, *a, **k):
        raise OSError("boom")

    monkeypatch.setattr(keys_mod.Path, "read_text", fake_read_text)
    result = load_keys(plugins, "messageboard", DEFAULTS)
    assert result == DEFAULTS  # graceful fallback


def test_bbsapp_keys_for(tmp_path, monkeypatch):
    app = BBSApp()
    seen = {}

    def fake_load(plugins_dir, name, defaults):
        seen["dir"] = str(plugins_dir)
        seen["name"] = name
        return dict(defaults)

    monkeypatch.setattr("core.keys.load_keys", fake_load)
    result = app.keys_for("messageboard", {"QUIT": "Q"})
    assert result == {"QUIT": "Q"}
    assert seen["name"] == "messageboard"
    assert seen["dir"].endswith("plugins")
