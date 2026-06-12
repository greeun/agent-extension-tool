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


def test_list_mcp_servers_default_scope_is_plugin(tmp_path: Path):
    install = tmp_path / "p"
    _make_plugin(install, {"mcpServers": {"s": {"command": "x"}}})
    s = axt.list_mcp_servers([{"id": "p@m", "installPath": str(install)}])[0]
    assert s.scope == "plugin"
    assert s.transport == "stdio"
    assert s.url == ""
    assert s.disabled is False


def test_list_mcp_servers_detects_http_plugin_server(tmp_path: Path):
    """A plugin-defined http server is routed to transport=http with a url."""
    install = tmp_path / "p"
    _make_plugin(install, {"mcpServers": {"h": {"type": "http", "url": "https://h/mcp"}}})
    s = axt.list_mcp_servers([{"id": "p@m", "installPath": str(install)}])[0]
    assert s.transport == "http"
    assert s.url == "https://h/mcp"
    assert s.command == ""
    assert s.scope == "plugin"


# ─── collect_mcp_servers: plugin + user/project/.mcp.json config sources ──────


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


def test_collect_mcp_servers_empty_everything(tmp_path: Path):
    assert axt.collect_mcp_servers(
        [], claude_config_path=tmp_path / "missing.json", project_dir=tmp_path
    ) == []


def test_collect_user_scope_stdio(tmp_path: Path):
    cfg = tmp_path / ".claude.json"
    _write_json(cfg, {"mcpServers": {
        "context7": {"command": "npx", "args": ["-y", "ctx7"], "env": {"K": "v"}},
    }})
    servers = axt.collect_mcp_servers([], claude_config_path=cfg, project_dir=tmp_path)
    assert len(servers) == 1
    s = servers[0]
    assert s.name == "context7"
    assert s.scope == "user"
    assert s.transport == "stdio"
    assert s.command == "npx"
    assert s.args_list == ["-y", "ctx7"]
    assert s.env_dict == {"K": "v"}
    assert s.disabled is False


def test_collect_http_transport_from_type(tmp_path: Path):
    cfg = tmp_path / ".claude.json"
    _write_json(cfg, {"mcpServers": {
        "notion": {"type": "http", "url": "https://mcp.notion.com/mcp"},
    }})
    s = axt.collect_mcp_servers([], claude_config_path=cfg, project_dir=tmp_path)[0]
    assert s.transport == "http"
    assert s.url == "https://mcp.notion.com/mcp"
    assert s.command == ""
    assert s.scope == "user"


def test_collect_sse_transport(tmp_path: Path):
    cfg = tmp_path / ".claude.json"
    _write_json(cfg, {"mcpServers": {"r": {"type": "sse", "url": "https://x/sse"}}})
    s = axt.collect_mcp_servers([], claude_config_path=cfg, project_dir=tmp_path)[0]
    assert s.transport == "sse"
    assert s.url == "https://x/sse"


def test_collect_url_without_type_infers_http(tmp_path: Path):
    cfg = tmp_path / ".claude.json"
    _write_json(cfg, {"mcpServers": {"r": {"url": "https://x/mcp"}}})
    s = axt.collect_mcp_servers([], claude_config_path=cfg, project_dir=tmp_path)[0]
    assert s.transport == "http"
    assert s.url == "https://x/mcp"


def test_collect_project_scope(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = tmp_path / ".claude.json"
    _write_json(cfg, {"projects": {str(proj): {
        "mcpServers": {"lazyweb": {"command": "node"}},
    }}})
    s = axt.collect_mcp_servers([], claude_config_path=cfg, project_dir=proj)[0]
    assert s.name == "lazyweb"
    assert s.scope == "project"
    # A different project dir must NOT see it.
    other = axt.collect_mcp_servers([], claude_config_path=cfg, project_dir=tmp_path)
    assert other == []


def test_collect_mcp_json_file_scope(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "filesrv": {"command": "python", "args": ["s.py"]},
    }}))
    cfg = tmp_path / ".claude.json"
    _write_json(cfg, {})
    s = axt.collect_mcp_servers([], claude_config_path=cfg, project_dir=proj)[0]
    assert s.name == "filesrv"
    assert s.scope == "project-file"
    assert s.command == "python"


def test_collect_disabled_flag(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg = tmp_path / ".claude.json"
    _write_json(cfg, {
        "mcpServers": {"context7": {"command": "npx"}},
        "projects": {str(proj): {"disabledMcpServers": ["context7"]}},
    })
    s = axt.collect_mcp_servers([], claude_config_path=cfg, project_dir=proj)[0]
    assert s.disabled is True


def test_collect_combines_plugin_and_config_sources(tmp_path: Path):
    install = tmp_path / "p1"
    _make_plugin(install, {"name": "p1", "mcpServers": {"plugsrv": {"command": "node"}}})
    cfg = tmp_path / ".claude.json"
    _write_json(cfg, {"mcpServers": {"usersrv": {"command": "npx"}}})
    servers = axt.collect_mcp_servers(
        [{"id": "p1@m", "installPath": str(install)}],
        claude_config_path=cfg, project_dir=tmp_path,
    )
    assert {s.name for s in servers} == {"plugsrv", "usersrv"}
    assert {s.scope for s in servers} == {"plugin", "user"}


def test_collect_missing_config_returns_plugin_only(tmp_path: Path):
    install = tmp_path / "p1"
    _make_plugin(install, {"name": "p1", "mcpServers": {"plugsrv": {"command": "node"}}})
    servers = axt.collect_mcp_servers(
        [{"id": "p1@m", "installPath": str(install)}],
        claude_config_path=tmp_path / "nope.json", project_dir=tmp_path,
    )
    assert [s.name for s in servers] == ["plugsrv"]
    assert servers[0].scope == "plugin"


def test_collect_tolerates_malformed_config(tmp_path: Path):
    cfg = tmp_path / ".claude.json"
    cfg.write_text("[1, 2, 3]")  # valid JSON but not an object
    assert axt.collect_mcp_servers([], claude_config_path=cfg, project_dir=tmp_path) == []


# ─── set_mcp_disabled: project-scoped disabledMcpServers toggle ───────────────


def test_set_mcp_disabled_adds_name(tmp_path: Path):
    cfg = tmp_path / ".claude.json"
    proj = tmp_path / "proj"
    proj.mkdir()
    axt.set_mcp_disabled("ctx7", disabled=True, claude_config_path=cfg, project_dir=proj)
    data = json.loads(cfg.read_text())
    assert data["projects"][str(proj)]["disabledMcpServers"] == ["ctx7"]


def test_set_mcp_disabled_then_reflected_in_collect(tmp_path: Path):
    cfg = tmp_path / ".claude.json"
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg.write_text(json.dumps({"mcpServers": {"ctx7": {"command": "node"}}}))
    axt.set_mcp_disabled("ctx7", disabled=True, claude_config_path=cfg, project_dir=proj)
    s = axt.collect_mcp_servers([], claude_config_path=cfg, project_dir=proj)[0]
    assert s.name == "ctx7" and s.disabled is True


def test_set_mcp_enable_removes_name_and_prunes_key(tmp_path: Path):
    cfg = tmp_path / ".claude.json"
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg.write_text(json.dumps({"projects": {str(proj): {"disabledMcpServers": ["ctx7"], "other": 1}}}))
    axt.set_mcp_disabled("ctx7", disabled=False, claude_config_path=cfg, project_dir=proj)
    entry = json.loads(cfg.read_text())["projects"][str(proj)]
    assert "disabledMcpServers" not in entry
    assert entry["other"] == 1  # unrelated keys preserved


def test_set_mcp_disabled_idempotent(tmp_path: Path):
    cfg = tmp_path / ".claude.json"
    proj = tmp_path / "proj"
    proj.mkdir()
    axt.set_mcp_disabled("a", disabled=True, claude_config_path=cfg, project_dir=proj)
    axt.set_mcp_disabled("a", disabled=True, claude_config_path=cfg, project_dir=proj)
    names = json.loads(cfg.read_text())["projects"][str(proj)]["disabledMcpServers"]
    assert names == ["a"]


def test_set_mcp_disabled_tolerates_malformed_config(tmp_path: Path):
    cfg = tmp_path / ".claude.json"
    proj = tmp_path / "proj"
    proj.mkdir()
    cfg.write_text("[1, 2, 3]")  # valid JSON, not an object
    axt.set_mcp_disabled("a", disabled=True, claude_config_path=cfg, project_dir=proj)
    assert json.loads(cfg.read_text())["projects"][str(proj)]["disabledMcpServers"] == ["a"]
