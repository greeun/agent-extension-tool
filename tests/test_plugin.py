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
