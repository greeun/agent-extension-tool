"""Smoke + targeted tests for Section 10 — CLI argparse + handlers."""
from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

import axt


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Capture stdout/stderr while invoking axt.main with given argv."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = axt.main(argv)
    return code, out.getvalue(), err.getvalue()


# ─── Parser tree ─────────────────────────────────────────────────────────────


def test_build_parser_returns_axt_program():
    parser = axt.build_parser()
    assert parser.prog == "axt"


def test_version_flag():
    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit) as e:
            axt.main(["--version"])
    assert e.value.code == 0
    assert axt.__version__ in out.getvalue()


def test_help_flag_lists_subcommands():
    out = io.StringIO()
    with redirect_stdout(out):
        with pytest.raises(SystemExit):
            axt.main(["--help"])
    text = out.getvalue()
    for cmd in ("market", "mcp", "plan", "plugin", "project", "skill", "usage", "vault", "context"):
        assert cmd in text


def test_unknown_command_returns_error():
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        with pytest.raises(SystemExit):
            axt.main(["totally-not-a-command"])


# ─── No-arg / tui ────────────────────────────────────────────────────────────


def test_no_args_invokes_tui(monkeypatch):
    """No-arg invocation calls launch_tui(); under tests we stub it."""
    called = []
    monkeypatch.setattr("axt.launch_tui", lambda: called.append(True) or 0)
    code, _, _ = _run([])
    assert code == 0
    assert called == [True]


def test_tui_explicit(monkeypatch):
    called = []
    monkeypatch.setattr("axt.launch_tui", lambda: called.append(True) or 0)
    code, _, _ = _run(["tui"])
    assert code == 0
    assert called == [True]


def test_tui_launch_outside_terminal_fails_gracefully():
    """launch_tui() should return 1 (not crash) when curses can't init."""
    # The tests run without a real TTY, so curses.wrapper raises curses.error.
    # We verify that's converted into a clean exit code 1 with stderr msg.
    err = io.StringIO()
    with redirect_stderr(err):
        code = axt.launch_tui()
    assert code == 1
    assert "TUI failed to start" in err.getvalue() or "curses" in err.getvalue().lower()


# ─── market ──────────────────────────────────────────────────────────────────


def test_market_list_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json",
        marketplaces=tmp_path / "mks",
    ))
    code, out, _ = _run(["market", "list"])
    assert code == 0
    assert "No marketplaces registered" in out


def test_market_add_directory(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json",
        marketplaces=tmp_path / "mks",
    ))
    target = tmp_path / "local-mk"
    target.mkdir()
    code, out, _ = _run(["market", "add", f"dir:{target}"])
    assert code == 0
    assert "registered" in out


def test_market_remove_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json",
        marketplaces=tmp_path / "mks",
    ))
    code, out, err = _run(["market", "remove", "nope"])
    assert code == 1
    assert "nope" in err or "nope" in out


# ─── plugin ──────────────────────────────────────────────────────────────────


def test_plugin_list_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
    ))
    code, out, _ = _run(["plugin", "list"])
    assert code == 0
    assert "No plugins installed" in out


def test_plugin_enable_writes_settings(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(settings=tmp_path / "settings.json"))
    code, out, _ = _run(["plugin", "enable", "myplugin@m"])
    assert code == 0
    data = json.loads((tmp_path / "settings.json").read_text())
    assert data["enabledPlugins"]["myplugin@m"] is True


def test_plugin_enable_scope_global_default(tmp_path: Path, monkeypatch):
    """Default --scope is global; writes to PATHS.settings, not project."""
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr("axt.PATHS", axt.Paths(settings=tmp_path / "settings.json"))
    monkeypatch.chdir(project)
    code, out, _ = _run(["plugin", "enable", "myplugin@m"])
    assert code == 0
    assert "(global)" in out
    g = json.loads((tmp_path / "settings.json").read_text())
    assert g["enabledPlugins"]["myplugin@m"] is True
    assert not (project / ".claude" / "settings.json").exists()


def test_plugin_enable_scope_project_writes_cwd(tmp_path: Path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr("axt.PATHS", axt.Paths(settings=tmp_path / "settings.json"))
    monkeypatch.chdir(project)
    code, out, _ = _run(["plugin", "enable", "myplugin@m", "--scope", "project"])
    assert code == 0
    assert "(project)" in out
    p = json.loads((project / ".claude" / "settings.json").read_text())
    assert p["enabledPlugins"]["myplugin@m"] is True
    # Global must remain untouched.
    assert not (tmp_path / "settings.json").exists()


def test_plugin_disable_scope_project_writes_cwd(tmp_path: Path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr("axt.PATHS", axt.Paths(settings=tmp_path / "settings.json"))
    monkeypatch.chdir(project)
    code, out, _ = _run(["plugin", "disable", "myplugin@m", "--scope", "project"])
    assert code == 0
    assert "(project)" in out
    p = json.loads((project / ".claude" / "settings.json").read_text())
    assert p["enabledPlugins"]["myplugin@m"] is False


def test_plugin_list_shows_split_status(tmp_path: Path, monkeypatch):
    """List shows separate global/project marks; '·' for unset entries."""
    project = tmp_path / "proj"
    project.mkdir()
    install = tmp_path / "p"
    (install / ".claude-plugin").mkdir(parents=True)
    (install / ".claude-plugin" / "plugin.json").write_text('{"name":"p","version":"1"}')
    (tmp_path / "installed_plugins.json").write_text(json.dumps({
        "version": 2,
        "plugins": {
            "p@m": [{
                "scope": "global", "installPath": str(install), "version": "1",
                "installedAt": "", "lastUpdated": "",
            }]
        },
    }))
    # Global enables it; project disables it (override).
    (tmp_path / "settings.json").write_text(json.dumps({"enabledPlugins": {"p@m": True}}))
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"p@m": False}}))
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "installed_plugins.json",
        settings=tmp_path / "settings.json",
    ))
    monkeypatch.chdir(project)
    code, out, _ = _run(["plugin", "list"])
    assert code == 0
    assert "G/P" in out
    assert "● / ○" in out  # global enabled, project disabled (override)


def test_plugin_search_prints_hint():
    code, out, _ = _run(["plugin", "search", "foo"])
    assert code == 0
    assert "axt market sync" in out


# ─── skill ───────────────────────────────────────────────────────────────────


def test_skill_list_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(skills=tmp_path / "skills"))
    code, out, _ = _run(["skill", "list"])
    assert code == 0
    assert "No standalone skills found" in out


# ─── vault ───────────────────────────────────────────────────────────────────


def test_vault_list_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=tmp_path / "vault"))
    code, out, _ = _run(["vault", "list"])
    assert code == 0
    assert "Vault is empty" in out


def test_vault_list_with_items(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "skills" / "alpha").mkdir(parents=True)
    (vault / "skills" / "alpha" / "SKILL.md").write_text("---\ndescription: x\n---\n")
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=vault))
    code, out, _ = _run(["vault", "list"])
    assert code == 0
    assert "alpha" in out
    assert "skill" in out


# ─── project ─────────────────────────────────────────────────────────────────


def test_project_init_creates_profile(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, _ = _run(["project", "init"])
    assert code == 0
    assert "Created" in out
    assert (tmp_path / ".axt-profile.json").exists()


def test_project_init_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    axt.write_profile(tmp_path, axt.AxtProfile())
    code, out, _ = _run(["project", "init"])
    assert code == 0
    assert "already exists" in out


def test_project_status_no_profile(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, _ = _run(["project", "status"])
    assert code == 1
    assert "No .axt-profile.json found" in out


# ─── mcp ─────────────────────────────────────────────────────────────────────


def test_mcp_list_no_plugins(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
    ))
    code, out, _ = _run(["mcp", "list"])
    assert code == 0
    assert "No MCP servers" in out


def test_mcp_info_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
    ))
    code, out, err = _run(["mcp", "info", "doesnotexist"])
    assert code == 1
    assert "not found" in out


# ─── context ─────────────────────────────────────────────────────────────────


def test_context_command_runs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.HOME", tmp_path / "home")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
    ))
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr("axt.get_claude_version", lambda: "test")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    code, out, _ = _run(["context"])
    assert code == 0
    assert "Context Usage" in out


def test_context_json_output(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.HOME", tmp_path / "home")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
    ))
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr("axt.get_claude_version", lambda: "test")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    code, out, _ = _run(["context", "--json"])
    assert code == 0
    data = json.loads(out)
    assert "totalTokens" in data
    assert "sources" in data
    assert "costImpact" in data


# ─── format helpers ──────────────────────────────────────────────────────────


def test_format_tokens():
    assert axt.format_tokens(500) == "500"
    assert axt.format_tokens(1_500) == "1.5K"
    assert axt.format_tokens(2_500_000) == "2.5M"


def test_format_cost():
    assert axt.format_cost(10.0, 1400) == "$10.00 / ₩14,000"


def test_render_bar_basic():
    assert axt.render_bar(5, 10) == "█████░░░░░"


def test_render_bar_clamps_filled():
    assert axt.render_bar(20, 10) == "██████████"
    assert axt.render_bar(-5, 10) == "░░░░░░░░░░"
