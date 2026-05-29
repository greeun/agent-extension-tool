"""Tests for Section 4 — plugin loader/registry."""
from __future__ import annotations

import json
from pathlib import Path

import axt


def _write_installed(ip_path: Path, plugins: dict) -> None:
    ip_path.parent.mkdir(parents=True, exist_ok=True)
    ip_path.write_text(json.dumps({"version": 2, "plugins": plugins}, indent=2))


def _write_manifest(install_path: Path, manifest: dict, *, modern: bool = True) -> None:
    if modern:
        target = install_path / ".claude-plugin" / "plugin.json"
    else:
        target = install_path / "plugin.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest))


def test_list_installed_plugins_empty(tmp_path: Path):
    assert axt.list_installed_plugins(tmp_path / "missing.json") == []


def test_list_installed_plugins_parses_id_and_marketplace(tmp_path: Path):
    install = tmp_path / "myplugin"
    _write_manifest(install, {"name": "myplugin", "description": "Does things", "version": "1.2.3"})
    _write_installed(
        tmp_path / "installed.json",
        {
            "myplugin@official": [
                {
                    "scope": "global",
                    "installPath": str(install),
                    "version": "1.0.0",
                    "installedAt": "2026-01-01T00:00:00Z",
                    "lastUpdated": "2026-02-01T00:00:00Z",
                }
            ]
        },
    )
    plugins = axt.list_installed_plugins(tmp_path / "installed.json")
    assert len(plugins) == 1
    p = plugins[0]
    assert p.id == "myplugin@official"
    assert p.name == "myplugin"
    assert p.marketplace == "official"
    assert p.version == "1.0.0"
    assert p.description == "Does things"


def test_list_installed_plugins_no_marketplace_suffix(tmp_path: Path):
    _write_installed(
        tmp_path / "installed.json",
        {"local": [{"scope": "local", "installPath": "/x", "version": "0", "installedAt": "", "lastUpdated": ""}]},
    )
    p = axt.list_installed_plugins(tmp_path / "installed.json")[0]
    assert p.id == "local"
    assert p.name == "local"
    assert p.marketplace == "unknown"


def test_list_installed_plugins_falls_back_to_root_manifest(tmp_path: Path):
    install = tmp_path / "legacy"
    _write_manifest(install, {"name": "legacy", "description": "old layout"}, modern=False)
    _write_installed(
        tmp_path / "ip.json",
        {"legacy@m": [{"scope": "g", "installPath": str(install), "version": "1", "installedAt": "", "lastUpdated": ""}]},
    )
    p = axt.list_installed_plugins(tmp_path / "ip.json")[0]
    assert p.description == "old layout"


def test_normalize_manifest_author_object(tmp_path: Path):
    install = tmp_path / "p"
    _write_manifest(install, {"name": "p", "author": {"name": "Alice", "url": "https://a"}})
    _write_installed(
        tmp_path / "ip.json",
        {"p@m": [{"scope": "g", "installPath": str(install), "version": "1", "installedAt": "", "lastUpdated": ""}]},
    )
    p = axt.list_installed_plugins(tmp_path / "ip.json")[0]
    assert p.author == "Alice"


def test_get_plugin_info_found_and_not_found(tmp_path: Path):
    install = tmp_path / "p"
    _write_manifest(install, {"name": "p"})
    _write_installed(
        tmp_path / "ip.json",
        {"p@m": [{"scope": "g", "installPath": str(install), "version": "1", "installedAt": "", "lastUpdated": ""}]},
    )
    assert axt.get_plugin_info(tmp_path / "ip.json", "p@m") is not None
    assert axt.get_plugin_info(tmp_path / "ip.json", "missing@m") is None


def test_add_installed_plugin(tmp_path: Path):
    ip = tmp_path / "ip.json"
    axt.add_installed_plugin(ip, plugin_id="x@y", version="2.0", install_path="/tmp/x", scope="user")
    data = json.loads(ip.read_text())
    assert data["plugins"]["x@y"][0]["version"] == "2.0"
    assert data["plugins"]["x@y"][0]["installPath"] == "/tmp/x"
    assert data["plugins"]["x@y"][0]["scope"] == "user"


def test_remove_installed_plugin(tmp_path: Path):
    ip = tmp_path / "ip.json"
    axt.add_installed_plugin(ip, plugin_id="x@y", version="1", install_path="/x", scope="g")
    axt.add_installed_plugin(ip, plugin_id="z@y", version="1", install_path="/z", scope="g")
    axt.remove_installed_plugin(ip, "x@y")
    data = json.loads(ip.read_text())
    assert "x@y" not in data["plugins"]
    assert "z@y" in data["plugins"]


def test_find_plugin_source_dir(tmp_path: Path):
    mk = tmp_path / "marketplace"
    target = mk / "plugins" / "foo"
    (target / ".claude-plugin").mkdir(parents=True)
    (target / ".claude-plugin" / "plugin.json").write_text("{}")
    found = axt.find_plugin_source_dir(mk, "foo")
    assert found == target

    # Fall back to root layout.
    mk2 = tmp_path / "mk2"
    (mk2 / "bar").mkdir(parents=True)
    (mk2 / "bar" / "plugin.json").write_text("{}")
    assert axt.find_plugin_source_dir(mk2, "bar") == mk2 / "bar"

    assert axt.find_plugin_source_dir(mk2, "nonexistent") is None


# ─── find_plugin_source_dir: additional candidate layouts ────────────────────


def test_find_plugin_source_dir_marketplace_root_modern(tmp_path: Path):
    # Plugin manifest sits directly at the marketplace root (modern layout).
    mk = tmp_path / "single"
    (mk / ".claude-plugin").mkdir(parents=True)
    (mk / ".claude-plugin" / "plugin.json").write_text("{}")
    assert axt.find_plugin_source_dir(mk, "anything") == mk


def test_find_plugin_source_dir_direct_child_modern(tmp_path: Path):
    # `<mk>/<name>/.claude-plugin/plugin.json` (no `plugins/` segment).
    mk = tmp_path / "mk"
    child = mk / "baz"
    (child / ".claude-plugin").mkdir(parents=True)
    (child / ".claude-plugin" / "plugin.json").write_text("{}")
    assert axt.find_plugin_source_dir(mk, "baz") == child


def test_find_plugin_source_dir_empty_marketplace(tmp_path: Path):
    mk = tmp_path / "empty"
    mk.mkdir()
    assert axt.find_plugin_source_dir(mk, "whatever") is None


# ─── set_plugin_enabled ──────────────────────────────────────────────────────


def test_set_plugin_enabled_creates_bucket(tmp_path: Path):
    settings = tmp_path / "settings.json"
    axt.set_plugin_enabled(settings, "p@m", True)
    data = json.loads(settings.read_text())
    assert data["enabledPlugins"]["p@m"] is True


def test_set_plugin_enabled_toggles_existing(tmp_path: Path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "enabledPlugins": {"p@m": True},
        "otherKey": "preserved",
    }))
    axt.set_plugin_enabled(settings, "p@m", False)
    data = json.loads(settings.read_text())
    assert data["enabledPlugins"]["p@m"] is False
    # Unrelated keys are preserved across the write.
    assert data["otherKey"] == "preserved"


def test_set_plugin_enabled_coerces_to_bool(tmp_path: Path):
    settings = tmp_path / "settings.json"
    axt.set_plugin_enabled(settings, "p@m", 1)
    data = json.loads(settings.read_text())
    assert data["enabledPlugins"]["p@m"] is True


# ─── remove_plugin_from_settings ─────────────────────────────────────────────


def test_remove_plugin_from_settings_removes_key(tmp_path: Path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "enabledPlugins": {"a@m": True, "b@m": False},
        "favoritePlugins": {"a@m": True},
    }))
    axt.remove_plugin_from_settings(settings, "a@m")
    data = json.loads(settings.read_text())
    assert "a@m" not in data["enabledPlugins"]
    assert data["enabledPlugins"]["b@m"] is False
    # Only enabledPlugins is touched; favorites left untouched.
    assert data["favoritePlugins"] == {"a@m": True}


def test_remove_plugin_from_settings_missing_key_noop(tmp_path: Path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"enabledPlugins": {"keep@m": True}}))
    axt.remove_plugin_from_settings(settings, "absent@m")
    data = json.loads(settings.read_text())
    assert data["enabledPlugins"] == {"keep@m": True}


def test_remove_plugin_from_settings_no_enabled_block(tmp_path: Path):
    # No enabledPlugins block at all -> no crash, settings round-tripped.
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"someOtherKey": 42}))
    axt.remove_plugin_from_settings(settings, "x@m")
    data = json.loads(settings.read_text())
    assert data["someOtherKey"] == 42


def test_remove_plugin_from_settings_missing_file(tmp_path: Path):
    # Settings file does not exist -> reads {} and writes an empty file.
    settings = tmp_path / "settings.json"
    axt.remove_plugin_from_settings(settings, "x@m")
    assert json.loads(settings.read_text()) == {}


# ─── _read_plugin_manifest fallbacks (via list_installed_plugins) ────────────


def test_manifest_modern_preferred_over_root(tmp_path: Path):
    install = tmp_path / "p"
    # Modern manifest has a name; root manifest differs. Modern wins.
    _write_manifest(install, {"name": "p", "description": "modern"}, modern=True)
    _write_manifest(install, {"name": "p", "description": "root"}, modern=False)
    _write_installed(
        tmp_path / "ip.json",
        {"p@m": [{"scope": "g", "installPath": str(install), "version": "1", "installedAt": "", "lastUpdated": ""}]},
    )
    p = axt.list_installed_plugins(tmp_path / "ip.json")[0]
    assert p.description == "modern"


def test_manifest_empty_modern_falls_back_to_root(tmp_path: Path):
    install = tmp_path / "p"
    # Modern manifest exists but has neither name nor description -> fall back.
    _write_manifest(install, {"version": "9.9"}, modern=True)
    _write_manifest(install, {"name": "rooty", "description": "root desc"}, modern=False)
    _write_installed(
        tmp_path / "ip.json",
        {"p@m": [{"scope": "g", "installPath": str(install), "version": "1", "installedAt": "", "lastUpdated": ""}]},
    )
    p = axt.list_installed_plugins(tmp_path / "ip.json")[0]
    assert p.description == "root desc"


def test_manifest_missing_entirely_yields_none_fields(tmp_path: Path):
    install = tmp_path / "p"
    install.mkdir()  # no manifest at all
    _write_installed(
        tmp_path / "ip.json",
        {"p@m": [{"scope": "g", "installPath": str(install), "version": "2.0", "installedAt": "", "lastUpdated": ""}]},
    )
    p = axt.list_installed_plugins(tmp_path / "ip.json")[0]
    assert p.description is None
    assert p.author is None
    assert p.homepage is None
    assert p.repository is None
    # Registry-supplied version still flows through.
    assert p.version == "2.0"


def test_manifest_repository_object_url_extracted(tmp_path: Path):
    install = tmp_path / "p"
    _write_manifest(install, {
        "name": "p",
        "repository": {"type": "git", "url": "https://github.com/o/r"},
        "homepage": "https://example.com",
    })
    _write_installed(
        tmp_path / "ip.json",
        {"p@m": [{"scope": "g", "installPath": str(install), "version": "1", "installedAt": "", "lastUpdated": ""}]},
    )
    p = axt.list_installed_plugins(tmp_path / "ip.json")[0]
    assert p.repository == "https://github.com/o/r"
    assert p.homepage == "https://example.com"


def test_manifest_non_string_description_becomes_none(tmp_path: Path):
    install = tmp_path / "p"
    # description is a non-string -> coerced to None per list_installed_plugins.
    _write_manifest(install, {"name": "p", "description": {"text": "x"}})
    _write_installed(
        tmp_path / "ip.json",
        {"p@m": [{"scope": "g", "installPath": str(install), "version": "1", "installedAt": "", "lastUpdated": ""}]},
    )
    p = axt.list_installed_plugins(tmp_path / "ip.json")[0]
    assert p.description is None


# ─── list_installed_plugins edge cases ───────────────────────────────────────


def test_list_installed_plugins_skips_empty_entry_list(tmp_path: Path):
    _write_installed(
        tmp_path / "ip.json",
        {
            "empty@m": [],
            "good@m": [{"scope": "g", "installPath": str(tmp_path / "g"), "version": "1", "installedAt": "", "lastUpdated": ""}],
        },
    )
    (tmp_path / "g").mkdir()
    plugins = axt.list_installed_plugins(tmp_path / "ip.json")
    assert [p.id for p in plugins] == ["good@m"]


def test_list_installed_plugins_non_dict_top_level(tmp_path: Path):
    # A malformed registry that is a JSON list rather than an object.
    ip = tmp_path / "ip.json"
    ip.write_text(json.dumps(["not", "a", "dict"]))
    assert axt.list_installed_plugins(ip) == []
