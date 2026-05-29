"""Tests for Section 4 — MCP servers extracted from plugin manifests."""
from __future__ import annotations

import json
from pathlib import Path

import axt


def _make_plugin(install_path: Path, manifest: dict) -> None:
    (install_path / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (install_path / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest))


def test_list_mcp_servers_empty(tmp_path: Path):
    assert axt.list_mcp_servers([]) == []


def test_list_mcp_servers_basic(tmp_path: Path):
    install = tmp_path / "p1"
    _make_plugin(install, {"name": "p1", "mcpServers": {
        "srvA": {"command": "node", "args": ["server.js"], "env": {"FOO": "bar"}},
        "srvB": {"command": "python", "args": [], "env": {}},
    }})
    servers = axt.list_mcp_servers([{"id": "p1@m", "installPath": str(install)}])
    assert len(servers) == 2
    by_name = {s.name: s for s in servers}
    assert by_name["srvA"].command == "node"
    assert by_name["srvA"].args_list == ["server.js"]
    assert by_name["srvA"].env_dict == {"FOO": "bar"}
    assert by_name["srvA"].plugin_id == "p1@m"
    assert by_name["srvB"].command == "python"


def test_list_mcp_servers_no_mcp_block(tmp_path: Path):
    install = tmp_path / "p"
    _make_plugin(install, {"name": "p"})
    assert axt.list_mcp_servers([{"id": "p@m", "installPath": str(install)}]) == []


def test_list_mcp_servers_accepts_plugininfo(tmp_path: Path):
    install = tmp_path / "p"
    _make_plugin(install, {"name": "p", "mcpServers": {"s": {"command": "x"}}})
    info = axt.PluginInfo(
        id="p@m",
        name="p",
        marketplace="m",
        version="1",
        install_path=str(install),
        scope="g",
        installed_at="",
        last_updated="",
    )
    servers = axt.list_mcp_servers([info])
    assert servers[0].name == "s"
    assert servers[0].command == "x"
    assert servers[0].args_list == []
    assert servers[0].env_dict == {}


def test_list_mcp_servers_missing_manifest_skipped(tmp_path: Path):
    # No manifest file at all.
    servers = axt.list_mcp_servers([{"id": "p@m", "installPath": str(tmp_path / "nowhere")}])
    assert servers == []


def test_list_mcp_servers_skips_plugin_without_install_path():
    """A plugin entry lacking installPath is skipped (can't locate manifest)."""
    assert axt.list_mcp_servers([{"id": "p@m"}]) == []


def test_list_mcp_servers_skips_non_dict_server_definition(tmp_path: Path):
    """A non-dict server definition inside mcpServers is ignored; valid ones
    are still collected."""
    install = tmp_path / "plug"
    _make_plugin(install, {"mcpServers": {
        "bad": "not-a-dict",
        "good": {"command": "node", "args": ["s.js"]},
    }})
    servers = axt.list_mcp_servers([{"id": "p@m", "installPath": str(install)}])
    names = [s.name for s in servers]
    assert "good" in names
    assert "bad" not in names
