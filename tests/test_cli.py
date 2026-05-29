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


# ─── Gap helpers ─────────────────────────────────────────────────────────────


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _isolate_usage(tmp_path: Path, monkeypatch, projects: Path | None = None) -> Path:
    """Point usage/plan handlers at empty tmp paths so no real ~/.claude is read.

    usage/plan handlers only touch PATHS.projects, AXT_CONFIG_PATH, and the
    usage cache dir — isolate all three so the tests are hermetic."""
    proj = projects or (tmp_path / "projects")
    monkeypatch.setattr("axt.PATHS", axt.Paths(projects=proj))
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    return proj


def _vault_paths(tmp_path: Path) -> "axt.Paths":
    """A fully-isolated vault layout. The Paths sub-fields (vault_skills etc.)
    default to the real ~/.axt, so they MUST be set explicitly or vault `add`
    would write into the user's real vault."""
    vault = tmp_path / "vault"
    return axt.Paths(
        claude_dir=tmp_path / "claude",
        vault=vault,
        vault_skills=vault / "skills",
        vault_commands=vault / "commands",
        vault_agents=vault / "agents",
    )


def _seed_vault_skill(vault: Path, name: str = "alpha") -> None:
    d = vault / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\ndescription: x\n---\n")


# ─── plan ──────────────────────────────────────────────────────────────────


def test_plan_set_then_overview_roundtrip(tmp_path: Path, monkeypatch):
    """`plan set` persists the plan to config.json; `plan overview` reads it
    back and renders the plan label. Guards the config write+read contract."""
    _isolate_usage(tmp_path, monkeypatch)
    code, out, _ = _run(["plan", "set", "max20"])
    assert code == 0
    assert "set to" in out and "max20" in out
    assert (tmp_path / "config.json").exists()
    code2, out2, _ = _run(["plan", "overview"])
    assert code2 == 0
    assert "max20" in out2  # label echoes the plan we just set


# ─── plugin info / remove ────────────────────────────────────────────────────


def _install_plugin(tmp_path: Path, pid: str = "myplug@official") -> tuple[Path, Path]:
    install = tmp_path / "plug"
    (install / ".claude-plugin").mkdir(parents=True)
    (install / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": pid.split("@")[0], "version": "1.0.0"})
    )
    ip = tmp_path / "ip.json"
    ip.write_text(json.dumps({"version": 2, "plugins": {
        pid: [{"scope": "user", "installPath": str(install), "version": "1.0.0",
               "installedAt": "2026-01-01T00:00:00Z", "lastUpdated": "2026-01-01T00:00:00Z"}]
    }}))
    return ip, install


def test_plugin_info_not_found(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json", settings=tmp_path / "s.json"))
    code, out, _ = _run(["plugin", "info", "ghost@m"])
    assert code == 1
    assert "not found" in out


def test_plugin_info_found_shows_details(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ip, _ = _install_plugin(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=ip, settings=tmp_path / "s.json"))
    code, out, _ = _run(["plugin", "info", "myplug@official"])
    assert code == 0
    assert "myplug" in out
    assert "1.0.0" in out
    assert "official" in out


def test_plugin_remove_deletes_dir_and_registry(tmp_path: Path, monkeypatch):
    """`plugin remove` must rmtree the install dir AND drop it from the
    registry — a regression that skips either leaves a dangling install."""
    monkeypatch.chdir(tmp_path)
    ip, install = _install_plugin(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=ip, settings=tmp_path / "s.json"))
    assert install.exists()
    code, out, _ = _run(["plugin", "remove", "myplug@official"])
    assert code == 0
    assert "removed" in out
    assert not install.exists()
    assert axt.get_plugin_info(ip, "myplug@official") is None


def test_plugin_remove_not_found(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json", settings=tmp_path / "s.json"))
    code, out, _ = _run(["plugin", "remove", "ghost@m"])
    assert code == 1
    assert "not found" in out


# ─── project add / remove / sync ─────────────────────────────────────────────


def test_project_add_item_not_in_vault(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=tmp_path / "vault"))
    monkeypatch.chdir(tmp_path)
    code, out, _ = _run(["project", "add", "skill", "ghost"])
    assert code == 0  # missing items are reported but don't fail the batch
    assert "not found in vault" in out


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_project_add_then_remove_roundtrip(tmp_path: Path, monkeypatch):
    paths = _vault_paths(tmp_path)
    _seed_vault_skill(paths.vault)
    monkeypatch.setattr("axt.PATHS", paths)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    code, out, _ = _run(["project", "add", "skill", "alpha"])
    assert code == 0
    link = proj / ".claude" / "skills" / "alpha"
    assert link.is_symlink()
    code2, out2, _ = _run(["project", "remove", "skill", "alpha"])
    assert code2 == 0
    assert "Unlinked" in out2
    assert not link.exists()


def test_project_sync_already_in_sync(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=tmp_path / "vault"))
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    axt.write_profile(proj, axt.AxtProfile())  # empty profile → nothing to do
    code, out, _ = _run(["project", "sync"])
    assert code == 0
    assert "Already in sync" in out


# ─── skill link / unlink ─────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_skill_link_then_unlink(tmp_path: Path, monkeypatch):
    skills = tmp_path / "skills"
    monkeypatch.setattr("axt.PATHS", axt.Paths(skills=skills))
    target = tmp_path / "my-skill"
    target.mkdir()
    (target / "SKILL.md").write_text("---\ndescription: x\n---\n")
    code, out, _ = _run(["skill", "link", str(target)])
    assert code == 0
    assert (skills / "my-skill").is_symlink()
    code2, out2, _ = _run(["skill", "unlink", "my-skill"])
    assert code2 == 0
    assert not (skills / "my-skill").exists()


# ─── usage ───────────────────────────────────────────────────────────────────


def test_usage_today_no_data(tmp_path: Path, monkeypatch):
    _isolate_usage(tmp_path, monkeypatch)
    code, out, _ = _run(["usage", "today"])
    assert code == 0
    assert "No usage data" in out


def test_usage_month_no_data_runs(tmp_path: Path, monkeypatch):
    _isolate_usage(tmp_path, monkeypatch)
    code, out, _ = _run(["usage", "month"])
    assert code == 0
    assert "Month:" in out


def test_usage_session_not_found(tmp_path: Path, monkeypatch):
    _isolate_usage(tmp_path, monkeypatch)
    code, out, _ = _run(["usage", "session", "deadbeef"])
    assert code == 1
    assert "not found" in out


def test_usage_week_json_empty_is_valid_json(tmp_path: Path, monkeypatch):
    """--json must emit a parseable array even with no data (machine-consumable
    contract — a stray header line would break downstream parsing)."""
    _isolate_usage(tmp_path, monkeypatch)
    code, out, _ = _run(["usage", "week", "--json"])
    assert code == 0
    assert json.loads(out) == []


def test_usage_week_csv_emits_header(tmp_path: Path, monkeypatch):
    _isolate_usage(tmp_path, monkeypatch)
    code, out, _ = _run(["usage", "week", "--csv"])
    assert code == 0
    assert out.splitlines()[0].startswith("date,sessions,")


def test_usage_blocks_no_data_runs(tmp_path: Path, monkeypatch):
    _isolate_usage(tmp_path, monkeypatch)
    code, out, _ = _run(["usage", "blocks"])
    assert code == 0
    assert "Block" in out  # header renders even with zero blocks


def test_usage_session_with_data_reports_totals(tmp_path: Path, monkeypatch):
    """Session lookup matches by id prefix and aggregates tokens — exercises
    the aggregate_by_session + cost pipeline deterministically (date-agnostic)."""
    projects = tmp_path / "projects"
    _write_jsonl(projects / "proj-a" / "s.jsonl", [{
        "type": "assistant", "sessionId": "sess-1234",
        "timestamp": "2026-04-29T10:00:00.000Z",
        "message": {"model": "claude-opus-4-7", "usage": {
            "input_tokens": 100, "output_tokens": 500,
            "cache_creation_input_tokens": 2000, "cache_read_input_tokens": 5000}},
    }])
    _isolate_usage(tmp_path, monkeypatch, projects=projects)
    code, out, _ = _run(["usage", "session", "sess-12"])  # prefix match
    assert code == 0
    assert "sess-1234" in out
    assert "Messages:" in out


# ─── vault add / migrate / link-global ───────────────────────────────────────


def test_vault_add_missing_source(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", _vault_paths(tmp_path))
    code, out, _ = _run(["vault", "add", str(tmp_path / "nope")])
    assert code == 1
    assert "not found" in out


def test_vault_add_directory_copies_into_vault(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", _vault_paths(tmp_path))
    src = tmp_path / "my-skill"
    src.mkdir()
    (src / "SKILL.md").write_text("---\ndescription: x\n---\n")
    code, out, _ = _run(["vault", "add", str(src), "-t", "skill"])
    assert code == 0
    assert "Added skill" in out
    assert (tmp_path / "vault" / "skills" / "my-skill" / "SKILL.md").exists()


def test_vault_add_file_defaults_to_command(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", _vault_paths(tmp_path))
    src = tmp_path / "do-thing.md"
    src.write_text("# command\n")
    code, out, _ = _run(["vault", "add", str(src)])
    assert code == 0
    assert "command" in out
    assert (tmp_path / "vault" / "commands" / "do-thing.md").exists()


def test_vault_migrate_no_globals(tmp_path: Path, monkeypatch):
    paths = _vault_paths(tmp_path)
    paths.claude_dir.mkdir()
    monkeypatch.setattr("axt.PATHS", paths)
    code, out, _ = _run(["vault", "migrate"])
    assert code == 0
    assert "No extensions found" in out


def test_vault_link_global_not_in_vault(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", _vault_paths(tmp_path))
    code, out, _ = _run(["vault", "link-global", "skill", "ghost"])
    assert code == 1
    assert "not found in vault" in out


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_vault_link_global_then_unlink(tmp_path: Path, monkeypatch):
    paths = _vault_paths(tmp_path)
    _seed_vault_skill(paths.vault)
    monkeypatch.setattr("axt.PATHS", paths)
    code, out, _ = _run(["vault", "link-global", "skill", "alpha"])
    assert code == 0
    link = paths.claude_dir / "skills" / "alpha"
    assert link.is_symlink()
    code2, out2, _ = _run(["vault", "unlink-global", "skill", "alpha"])
    assert code2 == 0
    assert "Unlinked" in out2
    assert not link.exists()


def test_vault_install_missing_in_marketplace(tmp_path: Path, monkeypatch):
    paths = _vault_paths(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=paths.vault, vault_skills=paths.vault_skills,
        vault_commands=paths.vault_commands, vault_agents=paths.vault_agents,
        marketplaces=tmp_path / "marketplaces"))
    code, out, _ = _run(["vault", "install", "no-such-mkt", "no-such-pkg"])
    assert code == 1
    assert "not found" in out


# ─── market sync ─────────────────────────────────────────────────────────────


def test_market_sync_all_empty_registry(tmp_path: Path, monkeypatch):
    """`market sync` with no name iterates the (empty) registry without error."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json", marketplaces=tmp_path / "mks"))
    code, out, err = _run(["market", "sync"])
    assert code == 0


# ─── smoke: CLI entrypoints return cleanly on an empty environment ───────────


def test_smoke_usage_and_plan_default_actions(tmp_path: Path, monkeypatch):
    """`usage` and `plan` with no sub-action fall back to today/overview and
    must exit 0 on an empty environment (default-action wiring regression)."""
    _isolate_usage(tmp_path, monkeypatch)
    code_u, _, _ = _run(["usage"])
    assert code_u == 0
    code_p, _, _ = _run(["plan"])
    assert code_p == 0


def test_smoke_dunder_main_entry(monkeypatch):
    """`python -m axt` routes through axt.main; stub the TUI so it stays headless."""
    import runpy
    monkeypatch.setattr("axt.launch_tui", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["axt"])
    # __main__ calls sys.exit(main()); 0 → SystemExit(0)
    with pytest.raises(SystemExit) as e:
        runpy.run_module("axt", run_name="__main__")
    assert e.value.code == 0


# ─── data-rendering branches (with populated state) ──────────────────────────


def test_market_list_with_registered_marketplace(tmp_path: Path, monkeypatch):
    """The list table + version columns render for a registered marketplace.
    Version lookup is stubbed so the test is hermetic (no git/network)."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json", marketplaces=tmp_path / "mks"))
    target = tmp_path / "local-mk"
    target.mkdir()
    _run(["market", "add", f"dir:{target}"])
    monkeypatch.setattr("axt.get_marketplace_version",
                        lambda *a, **k: axt.VersionInfo(current="1.0", remote="1.1", updatable=True))
    code, out, _ = _run(["market", "list"])
    assert code == 0
    assert "local-mk" in out
    assert "1.0" in out and "1.1" in out
    assert "marketplace(s)" in out


def test_mcp_list_with_servers(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json", settings=tmp_path / "s.json"))
    monkeypatch.setattr("axt.list_mcp_servers", lambda _p: [
        axt.McpServerInfo(name="srv1", plugin_id="plug@m", command="node",
                          args=("server.js",), env=())])
    code, out, _ = _run(["mcp", "list"])
    assert code == 0
    assert "srv1" in out
    assert "node" in out
    assert "MCP server(s)" in out


def test_mcp_info_with_env(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json", settings=tmp_path / "s.json"))
    monkeypatch.setattr("axt.list_mcp_servers", lambda _p: [
        axt.McpServerInfo(name="srv1", plugin_id="plug@m", command="node",
                          args=("server.js",), env=(("API_KEY", "x"),))])
    code, out, _ = _run(["mcp", "info", "srv1"])
    assert code == 0
    assert "srv1" in out
    assert "API_KEY" in out  # env block rendered


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_skill_list_with_items(tmp_path: Path, monkeypatch):
    skills = tmp_path / "skills"
    (skills / "real-skill").mkdir(parents=True)
    target = tmp_path / "ext-skill"
    target.mkdir()
    os.symlink(target, skills / "linked-skill")
    monkeypatch.setattr("axt.PATHS", axt.Paths(skills=skills))
    code, out, _ = _run(["skill", "list"])
    assert code == 0
    assert "real-skill" in out
    assert "linked-skill" in out
    assert "skill(s)" in out


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_project_status_reports_linked_and_missing(tmp_path: Path, monkeypatch):
    """status must show ✓ for present symlinks and ✗ for profile entries whose
    symlink is missing, plus the plugin (in profile) branch."""
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    axt.write_profile(proj, axt.AxtProfile(skills=("alpha", "beta"), plugins=("pg",)))
    # alpha is linked, beta is not.
    (proj / ".claude" / "skills").mkdir(parents=True)
    tgt = tmp_path / "alpha-src"
    tgt.mkdir()
    os.symlink(tgt, proj / ".claude" / "skills" / "alpha")
    code, out, _ = _run(["project", "status"])
    assert code == 0
    assert "alpha" in out and "linked" in out
    assert "beta" in out and "missing" in out
    assert "pg" in out and "in profile" in out


def _stub_usage(tmp_path: Path, monkeypatch, *, day: str) -> None:
    """Isolate usage handlers and feed a fixed entry through a stubbed loader.

    The since/until date filter is exercised by test_usage_claude; here we
    bypass it (stub `load_unified_usage`) so the CLI render/aggregate/cost/
    output-format code runs deterministically regardless of the wall clock."""
    entry = axt.UnifiedUsageEntry(
        platform="claude", model="claude-opus-4-7",
        timestamp=f"{day}T00:00:00.000Z", session_id="today-sess-1",
        project_path="proj-x", input_tokens=1000, output_tokens=2000,
        cache_write_tokens=500, cache_read_tokens=8000)
    monkeypatch.setattr("axt.load_unified_usage", lambda **kw: [entry])
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    monkeypatch.setattr("axt.PATHS", axt.Paths(projects=tmp_path / "projects"))


def test_usage_today_with_data_renders_full_summary(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "today", "--timezone", "UTC"])
    assert code == 0
    assert "Today" in out
    assert "Sessions:" in out
    assert "Cost:" in out


def test_usage_today_json_with_data(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "today", "--timezone", "UTC", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["sessions"] >= 1
    assert "cost" in data


def test_usage_week_table_with_data(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "week", "--timezone", "UTC"])
    assert code == 0
    assert "Week:" in out
    assert "Total" in out


def test_usage_week_csv_with_data_has_row(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "week", "--timezone", "UTC", "--csv"])
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("date,sessions,")
    assert any(line.startswith("2026-05-20") for line in lines[1:])  # a data row


def test_usage_blocks_with_data(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "blocks", "--timezone", "UTC"])
    assert code == 0
    assert "Block" in out


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks/migrate unsupported on Windows")
def test_vault_migrate_moves_global_skill(tmp_path: Path, monkeypatch):
    paths = _vault_paths(tmp_path)
    gskill = paths.claude_dir / "skills" / "myglobal"
    gskill.mkdir(parents=True)
    (gskill / "SKILL.md").write_text("---\ndescription: x\n---\n")
    monkeypatch.setattr("axt.PATHS", paths)
    code, out, _ = _run(["vault", "migrate"])
    assert code == 0
    assert "myglobal" in out
    assert (paths.vault / "skills" / "myglobal").exists()


def test_vault_install_success(tmp_path: Path, monkeypatch):
    """install copies a resolved marketplace source into the vault. The source
    resolver is stubbed (its own logic is unit-tested elsewhere)."""
    source = tmp_path / "src-pkg"
    source.mkdir()
    (source / "SKILL.md").write_text("---\ndescription: x\n---\n")
    monkeypatch.setattr("axt.find_plugin_source_dir", lambda *a, **k: source)
    monkeypatch.setattr("axt.PATHS", _vault_paths(tmp_path))
    code, out, _ = _run(["vault", "install", "some-mkt", "src-pkg", "-t", "skill"])
    assert code == 0
    assert "Installed" in out
    assert (tmp_path / "vault" / "skills" / "src-pkg" / "SKILL.md").exists()
