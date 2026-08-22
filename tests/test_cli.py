"""Smoke + targeted tests for Section 10 — CLI argparse + handlers."""
from __future__ import annotations

import io
import json
import os
import re
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


def test_version_string_is_declared_once_per_place_and_they_agree():
    """The version literal is repeated in pyproject.toml and in three modules
    (the wildcard-import layering gives each one its own `__version__`). A
    bump that misses one ships a CLI or tab bar showing the old number, so
    pin them together here rather than finding out at release time."""
    root = Path(axt.__file__).resolve().parent.parent
    declared = {}
    for rel, pattern in (
        ("pyproject.toml", r'^version = "([^"]+)"'),
        ("axt/__init__.py", r'^__version__ = "([^"]+)"'),
        ("axt/core.py", r'^__version__ = "([^"]+)"'),
        ("axt/tui/widgets.py", r'^__version__ = "([^"]+)"'),
    ):
        text = (root / rel).read_text(encoding="utf-8")
        m = re.search(pattern, text, re.MULTILINE)
        assert m, f"{rel}: no version literal found"
        declared[rel] = m.group(1)
    assert len(set(declared.values())) == 1, f"version drift: {declared}"
    assert declared["axt/__init__.py"] == axt.__version__


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
    monkeypatch.setattr("axt.launch_tui", lambda *a, **k: called.append(True) or 0)
    code, _, _ = _run([])
    assert code == 0
    assert called == [True]


def test_tui_explicit(monkeypatch):
    called = []
    monkeypatch.setattr("axt.launch_tui", lambda *a, **k: called.append(True) or 0)
    code, _, _ = _run(["tui"])
    assert code == 0
    assert called == [True]


def test_cli_theme_flag_overrides(monkeypatch):
    """`axt --theme light` (no subcommand) launches the TUI with the light
    theme; an explicit --theme beats whatever is saved in config."""
    seen = []
    monkeypatch.setattr("axt.launch_tui", lambda *a, **k: seen.append(a[0] if a else None) or 0)
    code, _, _ = _run(["--theme", "light"])
    assert code == 0
    assert seen == ["light"]


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
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        skills=home / ".claude" / "skills",
        vault=tmp_path / "vault",
        installed_plugins=tmp_path / "ip.json",
    ))
    monkeypatch.chdir(home)  # empty cwd — no project skills
    code, out, _ = _run(["skill", "list"])
    assert code == 0
    assert "No skills found" in out


def test_skill_list_includes_vault_only(tmp_path: Path, monkeypatch):
    """CLI skill list mirrors the TUI Skills sub-tab: vault-stored skills
    nothing links to appear with source `vault`."""
    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    vault = tmp_path / "vault"
    v = vault / "skills" / "vault-only"
    v.mkdir(parents=True)
    (v / "SKILL.md").write_text("---\ndescription: v\n---")
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        skills=home / ".claude" / "skills",
        vault=vault,
        installed_plugins=tmp_path / "ip.json",
    ))
    monkeypatch.chdir(home)
    code, out, _ = _run(["skill", "list"])
    assert code == 0
    assert "vault-only" in out


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
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
        claude_config=tmp_path / ".claude.json",
    ))
    code, out, _ = _run(["mcp", "list"])
    assert code == 0
    # No configured servers, but built-ins are always available and listed.
    assert "computer-use" in out
    assert "built-in" in out


def test_mcp_info_missing(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
        claude_config=tmp_path / ".claude.json",
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


def test_color_enabled_respects_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert axt._color_enabled() is False


def test_budget_bar_zero_budget_is_empty():
    assert axt.budget_bar(50.0, 0) == ""


def test_budget_bar_warning_and_over_budget():
    assert "⚠" in axt.budget_bar(85.0, 100.0)    # 85% → warning band
    assert "⛔" in axt.budget_bar(150.0, 100.0)   # over budget → stop


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
    monkeypatch.setattr("axt.launch_tui", lambda *a, **k: 0)
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
        installed_plugins=tmp_path / "ip.json", settings=tmp_path / "s.json",
        claude_config=tmp_path / ".claude.json"))
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
        installed_plugins=tmp_path / "ip.json", settings=tmp_path / "s.json",
        claude_config=tmp_path / ".claude.json"))
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
    assert "Cache Saved:" in out


def test_usage_today_json_with_data(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "today", "--timezone", "UTC", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["sessions"] >= 1
    assert "cost" in data
    assert data["cacheSavings"]["usd"] > 0


def test_usage_week_table_with_data(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "week", "--timezone", "UTC"])
    assert code == 0
    assert "Week:" in out
    assert "Total" in out
    assert "Cache saved" in out


def test_usage_week_csv_with_data_has_row(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "week", "--timezone", "UTC", "--csv"])
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "date,sessions,input_tokens,output_tokens,cache_write_tokens,cache_read_tokens,cost_usd,cost_krw,cache_savings_usd"
    assert any(line.startswith("2026-05-20") for line in lines[1:])  # a data row


def test_usage_blocks_with_data(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "blocks", "--timezone", "UTC"])
    assert code == 0
    assert "Block" in out
    assert "Cache W" in out
    assert "Cache R" in out


def test_usage_month_with_data_shows_cache_breakdown(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "month", "--timezone", "UTC"])
    assert code == 0
    assert "Cache Write:" in out
    assert "Cache Read:" in out
    assert "Cache Saved:" in out


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


def test_market_add_github_uses_repo_name(tmp_path: Path, monkeypatch):
    # add_marketplace would clone over the network; stub it so we test the
    # name-derivation branch (repo basename) hermetically.
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json", marketplaces=tmp_path / "mks"))
    monkeypatch.setattr("axt.add_marketplace", lambda *a, **k: None)
    code, out, _ = _run(["market", "add", "github:owner/my-repo"])
    assert code == 0
    assert "my-repo" in out


def test_market_add_git_uses_custom_name(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json", marketplaces=tmp_path / "mks"))
    monkeypatch.setattr("axt.add_marketplace", lambda *a, **k: None)
    code, out, _ = _run(["market", "add", "git:https://example.com/x.git"])
    assert code == 0
    assert "custom-marketplace" in out


def test_market_list_reports_version_errors(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json", marketplaces=tmp_path / "mks"))
    target = tmp_path / "mk"
    target.mkdir()
    _run(["market", "add", f"dir:{target}"])

    def boom(*a, **k):
        raise RuntimeError("version probe failed")
    monkeypatch.setattr("axt.get_marketplace_version", boom)
    code, out, _ = _run(["market", "list"])
    assert code == 0
    assert "error(s)" in out  # the pooled-error section rendered


def test_market_sync_named_updated(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json", marketplaces=tmp_path / "mks"))
    target = tmp_path / "mk"
    target.mkdir()
    _run(["market", "add", f"dir:{target}"])
    monkeypatch.setattr("axt.sync_marketplace",
                        lambda *a, **k: axt.SyncMarketplaceResult(before="1.0", after="1.1", updated=True))
    code, out, _ = _run(["market", "sync", "mk"])
    assert code == 0
    assert "1.0" in out and "1.1" in out


def test_market_sync_named_up_to_date(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json", marketplaces=tmp_path / "mks"))
    target = tmp_path / "mk"
    target.mkdir()
    _run(["market", "add", f"dir:{target}"])
    monkeypatch.setattr("axt.sync_marketplace",
                        lambda *a, **k: axt.SyncMarketplaceResult(before="1.0", after="1.0", updated=False))
    code, out, _ = _run(["market", "sync", "mk"])
    assert code == 0
    assert "up to date" in out


def test_market_sync_unknown_name_errors_via_main(tmp_path: Path, monkeypatch):
    """A handler raising (KeyError 'not found') is caught by main → exit 1 +
    stderr ✗ message (covers the top-level error handler)."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json", marketplaces=tmp_path / "mks"))
    code, out, err = _run(["market", "sync", "ghost"])
    assert code == 1
    assert "✗" in err


def _plan_overview_out(tmp_path: Path, monkeypatch, *, output_tokens: int,
                       elapsed: int, total: int) -> str:
    """Run `plan overview` over one synthetic usage entry with the billing
    period pinned.

    The projection is `cost / elapsed * total`, so leaving the real clock in
    play makes the over/under-budget branch depend on today's day of month —
    and on the first day of a cycle `elapsed` is 0 and the projection
    collapses to $0. Pinning the period is what makes these assertions mean
    what they say."""
    entry = axt.UnifiedUsageEntry(
        platform="claude", model="claude-opus-4-7", timestamp="2026-05-01T00:00:00Z",
        session_id="s", project_path="p", input_tokens=0, output_tokens=output_tokens,
        cache_write_tokens=0, cache_read_tokens=0)
    monkeypatch.setattr("axt.load_unified_usage", lambda **kw: [entry])
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr("axt.PATHS", axt.Paths(projects=tmp_path / "projects"))
    monkeypatch.setattr("axt.cli.get_days_in_billing_period",
                        lambda start, now=None: (elapsed, total))
    code, out, _ = _run(["plan", "overview"])
    assert code == 0
    return out


def test_plan_overview_over_budget_warns(tmp_path: Path, monkeypatch):
    """When projected cost exceeds the plan budget, overview shows the overage
    warning branch. 5M opus output tokens = $125 over 10 of 30 days, so the
    projection is $375 against the $200 max-20x budget."""
    out = _plan_overview_out(tmp_path, monkeypatch,
                             output_tokens=5_000_000, elapsed=10, total=30)
    assert "초과" in out  # over-budget warning
    assert "$375" in out
    assert "(10일 경과)" in out


def test_plan_overview_under_budget_has_no_warning(tmp_path: Path, monkeypatch):
    """The other side of the same branch: the same $125 spread over 25 of 30
    days projects to $150, under budget, so no overage marker."""
    out = _plan_overview_out(tmp_path, monkeypatch,
                             output_tokens=5_000_000, elapsed=25, total=30)
    assert "초과" not in out
    assert "$150" in out


def test_plugin_info_enabled_and_disabled_states(tmp_path: Path, monkeypatch):
    ip, _ = _install_plugin(tmp_path)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"enabledPlugins": {"myplug@official": True}}))
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"myplug@official": False}}))
    monkeypatch.chdir(proj)
    monkeypatch.setattr("axt.PATHS", axt.Paths(installed_plugins=ip, settings=settings))
    code, out, _ = _run(["plugin", "info", "myplug@official"])
    assert code == 0
    assert "enabled" in out and "disabled" in out


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_project_sync_links_profile_entries(tmp_path: Path, monkeypatch):
    paths = _vault_paths(tmp_path)
    _seed_vault_skill(paths.vault)
    monkeypatch.setattr("axt.PATHS", paths)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    axt.write_profile(proj, axt.AxtProfile(skills=("alpha",)))
    code, out, _ = _run(["project", "sync"])
    assert code == 0
    assert "+" in out  # alpha linked
    assert (proj / ".claude" / "skills" / "alpha").is_symlink()


def test_skill_link_handler_rejects_unsupported_platform(tmp_path: Path, monkeypatch):
    """The link/unlink subcommands are only built when symlinks are supported,
    so the handler's own platform guard is tested by calling it directly."""
    import argparse
    monkeypatch.setattr("axt.PATHS", axt.Paths(skills=tmp_path / "skills"))
    monkeypatch.setattr("axt.is_symlink_supported", lambda: False)
    code = axt.cli_skill_link(argparse.Namespace(path=str(tmp_path), name=None))
    assert code == 1


def test_skill_unlink_handler_rejects_unsupported_platform(tmp_path: Path, monkeypatch):
    import argparse
    monkeypatch.setattr("axt.PATHS", axt.Paths(skills=tmp_path / "skills"))
    monkeypatch.setattr("axt.is_symlink_supported", lambda: False)
    code = axt.cli_skill_unlink(argparse.Namespace(name="whatever"))
    assert code == 1


def test_usage_today_model_filter(tmp_path: Path, monkeypatch):
    """--model filters entries; a non-matching filter yields the no-data path."""
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "today", "--timezone", "UTC", "--model", "no-such-model"])
    assert code == 0
    assert "No usage data" in out  # filtered out → empty


def test_usage_blocks_active_filter(tmp_path: Path, monkeypatch):
    _stub_usage(tmp_path, monkeypatch, day="2026-05-20")
    code, out, _ = _run(["usage", "blocks", "--timezone", "UTC", "--active"])
    assert code == 0
    assert "Block" in out


@pytest.mark.skipif(sys.platform == "win32", reason="vault unsupported on Windows")
def test_vault_migrate_reports_skipped(tmp_path: Path, monkeypatch):
    """A global item already present in the vault is reported as skipped."""
    paths = _vault_paths(tmp_path)
    # same-named skill in BOTH global and vault → migrate skips it
    for base in (paths.claude_dir / "skills" / "dup", paths.vault / "skills" / "dup"):
        base.mkdir(parents=True)
        (base / "SKILL.md").write_text("---\ndescription: x\n---\n")
    monkeypatch.setattr("axt.PATHS", paths)
    code, out, _ = _run(["vault", "migrate"])
    assert code == 0
    assert "already in vault" in out  # skipped branch


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


# ─── mcp enable / disable ────────────────────────────────────────────────────


def test_mcp_disable_writes_project_list(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".claude.json"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr("axt.PATHS", axt.Paths(claude_config=cfg))
    monkeypatch.chdir(project)
    code, out, _ = _run(["mcp", "disable", "ctx7"])
    assert code == 0
    assert "disabled" in out
    assert json.loads(cfg.read_text())["projects"][str(project)]["disabledMcpServers"] == ["ctx7"]


def test_mcp_enable_removes_name(tmp_path: Path, monkeypatch):
    cfg = tmp_path / ".claude.json"
    project = tmp_path / "proj"
    project.mkdir()
    cfg.write_text(json.dumps({"projects": {str(project): {"disabledMcpServers": ["ctx7"]}}}))
    monkeypatch.setattr("axt.PATHS", axt.Paths(claude_config=cfg))
    monkeypatch.chdir(project)
    code, out, _ = _run(["mcp", "enable", "ctx7"])
    assert code == 0
    assert "enabled" in out
    assert "disabledMcpServers" not in json.loads(cfg.read_text())["projects"][str(project)]


# ─── hook list / enable / disable ────────────────────────────────────────────


def _hooks_paths(tmp_path: Path):
    return axt.Paths(
        settings=tmp_path / "settings.json",
        installed_plugins=tmp_path / "installed_plugins.json",
    )


def test_hook_list_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", _hooks_paths(tmp_path))
    monkeypatch.chdir(tmp_path)
    code, out, _ = _run(["hook", "list"])
    assert code == 0
    assert "No hooks found." in out


def test_hook_disable_then_enable_by_index(tmp_path: Path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "echo bye"}]}]}
    }))
    monkeypatch.setattr("axt.PATHS", _hooks_paths(tmp_path))
    monkeypatch.chdir(tmp_path)

    code, out, _ = _run(["hook", "disable", "0"])
    assert code == 0 and "disabled" in out
    data = json.loads(settings.read_text())
    assert "Stop" not in data.get("hooks", {})
    assert data["disabledHooks"]["Stop"][0]["hooks"][0]["command"] == "echo bye"

    # Index 0 is now the parked hook; re-enable it.
    code, out, _ = _run(["hook", "enable", "0"])
    assert code == 0 and "enabled" in out
    data = json.loads(settings.read_text())
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo bye"


def test_hook_disable_out_of_range(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", _hooks_paths(tmp_path))
    monkeypatch.chdir(tmp_path)
    code, out, _ = _run(["hook", "disable", "5"])
    assert code == 1


def test_hook_disable_refuses_plugin_hook(tmp_path: Path, monkeypatch):
    install = tmp_path / "plug"
    (install / "hooks").mkdir(parents=True)
    (install / "hooks" / "hooks.json").write_text(json.dumps(
        {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "p"}]}]}}))
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({"version": 2, "plugins": {
        "p@m": [{"scope": "user", "installPath": str(install), "version": "1", "installedAt": "", "lastUpdated": ""}]
    }}))
    monkeypatch.setattr("axt.PATHS", axt.Paths(settings=tmp_path / "nope.json", installed_plugins=ip))
    monkeypatch.chdir(tmp_path)
    code, out, _ = _run(["hook", "disable", "0"])
    assert code == 1
    assert "read-only" in out


# ─── usage / list output helpers (C1 / C2 refactor) ──────────────────────────


def _ce(model: str, inp: int, out: int):
    return axt.ClaudeUsageEntry(
        model=model, input_tokens=inp, output_tokens=out,
        cache_creation_tokens=0, cache_read_tokens=0,
        session_id="s", project_path="/p", timestamp="2026-06-01T00:00:00Z",
    )


def test_entries_cost_empty_is_zero():
    assert axt._entries_cost([]) == 0


def test_entries_cost_is_additive():
    # Independent of the pricing table values: cost(a+b) == cost(a)+cost(b).
    entries = [_ce("claude-opus-4-8", 1000, 500), _ce("claude-sonnet-4-6", 2000, 0)]
    assert axt._entries_cost(entries) == sum(axt._entries_cost([e]) for e in entries)


def test_print_count_footer(capsys):
    axt._print_count_footer(3, "hook")
    assert capsys.readouterr().out == "\n 3 hook(s)\n"


def test_print_count_footer_with_suffix(capsys):
    axt._print_count_footer(2, "extension", suffix=" in vault")
    assert capsys.readouterr().out == "\n 2 extension(s) in vault\n"


def test_print_list_header(capsys):
    axt._print_list_header("Name  Type", 10)
    out = capsys.readouterr().out
    assert "Name  Type" in out
    assert "─" * 10 in out


# ═════════════════════════════════════════════════════════════════════════════
# Gap-code (Phase C): api-layer TCs from tests/doc/testcases/api-testcases.md.
# Every test below verifies the CLI *contract* — argument validation, exit
# code, stdout/stderr shape, --json/--csv schema. Domain parsing rules stay
# with their unit tests (TEST_DEDUP_POLICY.md §2).
# ═════════════════════════════════════════════════════════════════════════════


def _run_expect_exit(argv: list[str]) -> tuple[int, str, str]:
    """Like `_run`, but for argv that argparse rejects before dispatch.

    argparse calls `sys.exit(2)` itself, so `main` never returns — the code
    has to come off the SystemExit. Returns (exit_code, stdout, stderr)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        with pytest.raises(SystemExit) as excinfo:
            axt.main(argv)
    return excinfo.value.code, out.getvalue(), err.getvalue()


def _subparser_choices(parser) -> dict:
    """The `{name: subparser}` map of a parser's subcommand group ({} if none).

    argparse exposes no public accessor for the tree, so the tests that assert
    which subcommands exist have to read `_SubParsersAction.choices`."""
    import argparse
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _tree_snapshot(root: Path) -> dict[str, str]:
    """Every path under `root` mapped to a marker of what it is.

    Used by the read-only-command tests: comparing two snapshots catches a
    handler that creates, deletes, or rewrites anything it shouldn't."""
    snap: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            snap[rel] = f"symlink:{os.readlink(p)}"
        elif p.is_dir():
            snap[rel] = "dir"
        else:
            snap[rel] = f"file:{p.read_bytes()!r}"
    return snap


# ─── Argparse contract: exit code 2 ──────────────────────────────────────────


def test_unknown_command_exits_with_code_2(monkeypatch):
    """An unknown top-level command must exit 2 (argparse usage error), not 1
    (handler error) and not 0. Shell callers branch on that number, so a
    handler that swallowed the error into `return 1` would look like a failed
    operation rather than a typo."""
    # TC-API-001
    monkeypatch.setenv("NO_COLOR", "1")
    code, _, err = _run_expect_exit(["totally-not-a-command"])
    assert code == 2
    assert "usage:" in err


def test_missing_required_argument_exits_2(monkeypatch):
    """A subcommand invoked without its required positional exits 2 before any
    handler runs — prevents a regression where `nargs="?"` creeps onto an
    argument the handler then dereferences as None."""
    # TC-API-002
    monkeypatch.setenv("NO_COLOR", "1")
    for argv in (["market", "add"], ["plugin", "info"]):
        code, _, err = _run_expect_exit(argv)
        assert code == 2, argv
        assert "usage:" in err, argv


def test_invalid_choice_exits_2(monkeypatch):
    """`choices=` violations are caught by argparse (exit 2), not by the
    handler. Guards US-UPD04 AC2 and the vault `-t` enum."""
    # TC-API-003
    monkeypatch.setenv("NO_COLOR", "1")
    for argv in (["update", "bogus-type"], ["vault", "add", "p", "-t", "bogus"]):
        code, _, err = _run_expect_exit(argv)
        assert code == 2, argv
        assert "invalid choice" in err, argv


def test_command_group_without_subcommand_exits_2(monkeypatch):
    """Groups declared `required=True` must fail loudly when called bare
    instead of printing help and exiting 0 — otherwise `axt market` in a
    script silently succeeds while doing nothing."""
    # TC-API-004
    monkeypatch.setenv("NO_COLOR", "1")
    for argv in (["market"], ["vault"]):
        code, _, err = _run_expect_exit(argv)
        assert code == 2, argv
        assert "usage:" in err, argv


def test_invalid_theme_value_exits_2(monkeypatch):
    """--theme is a closed enum; a typo must not fall through to the TUI with
    an unknown palette name."""
    # TC-API-010
    monkeypatch.setenv("NO_COLOR", "1")
    launched = []
    monkeypatch.setattr("axt.launch_tui", lambda *a, **k: launched.append(a) or 0)
    code, _, err = _run_expect_exit(["--theme", "bogus"])
    assert code == 2
    assert "invalid choice" in err
    assert launched == []  # the TUI must not open on a rejected flag


def test_plugin_enable_invalid_scope_exits_2(monkeypatch):
    """--scope is global|project; anything else must be rejected by argparse
    rather than silently defaulting to global and writing the wrong file."""
    # TC-API-039
    monkeypatch.setenv("NO_COLOR", "1")
    code, _, err = _run_expect_exit(["plugin", "enable", "p@m", "--scope", "bogus"])
    assert code == 2
    assert "invalid choice" in err


# ─── Top-level error handling / help ─────────────────────────────────────────


def test_market_add_invalid_source_errors_on_stderr_only(tmp_path: Path, monkeypatch):
    """A handler raising ValueError must exit 1 with the `✗` line on *stderr*
    and nothing on stdout — piping `axt … | jq` must never receive an error
    decoration in the data stream."""
    # TC-API-005
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json", marketplaces=tmp_path / "mks"))
    code, out, err = _run(["market", "add", "nonsense"])
    assert code == 1
    assert "✗" in err
    assert "✗" not in out


def test_help_lists_all_twelve_command_groups(monkeypatch):
    """`--help` must advertise every command group. A subparser that is
    registered but missing from help is invisible to users; one that was never
    registered breaks the command outright. Both show up here."""
    # TC-API-008
    monkeypatch.setenv("NO_COLOR", "1")
    code, out, _ = _run_expect_exit(["--help"])
    assert code == 0
    for cmd in ("tui", "context", "market", "mcp", "hook", "plan",
                "plugin", "project", "skill", "usage", "vault", "update"):
        assert cmd in out, cmd


# ─── mcp ─────────────────────────────────────────────────────────────────────


def test_mcp_info_remote_server_shows_url_not_command(tmp_path: Path, monkeypatch):
    """A remote (http/sse) server has no command line — `info` must print its
    URL and must not print an empty `Command:` line, which would read as a
    misconfigured server."""
    # TC-API-024
    monkeypatch.setenv("NO_COLOR", "1")
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"mcpServers": {
        "remote1": {"type": "http", "url": "https://mcp.example.com/sse"},
    }}))
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json", settings=tmp_path / "s.json",
        claude_config=cfg))
    monkeypatch.chdir(tmp_path)
    code, out, _ = _run(["mcp", "info", "remote1"])
    assert code == 0
    assert "URL: https://mcp.example.com/sse" in out
    assert "Command:" not in out


# ─── hook ────────────────────────────────────────────────────────────────────


def test_hook_disable_already_disabled_is_a_noop(tmp_path: Path, monkeypatch):
    """Disabling an already-parked hook must report `already disabled`, exit 0,
    and leave the settings file byte-identical — a second disable that moved
    the entry again would duplicate or drop the definition."""
    # TC-API-030
    monkeypatch.setenv("NO_COLOR", "1")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "disabledHooks": {
            "Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "echo bye"}]}]
        }
    }))
    before = settings.read_bytes()
    monkeypatch.setattr("axt.PATHS", _hooks_paths(tmp_path))
    monkeypatch.chdir(tmp_path)
    code, out, _ = _run(["hook", "disable", "0"])
    assert code == 0
    assert "already disabled" in out
    assert settings.read_bytes() == before


# ─── plan ────────────────────────────────────────────────────────────────────


def test_plan_set_auto_reenables_autodetect(tmp_path: Path, monkeypatch):
    """`plan set <name>` pins the plan (auto-detect off); `plan set auto` must
    turn it back on. Without this the only way back to auto-detection would be
    editing config.json by hand."""
    # TC-API-033
    monkeypatch.setenv("NO_COLOR", "1")
    _isolate_usage(tmp_path, monkeypatch)
    # detect_claude_plan() reads the module-level CLAUDE_CONFIG_FILE, not
    # PATHS — point it at a nonexistent tmp file so the user's real
    # ~/.claude.json is never read and the branch is deterministic.
    monkeypatch.setattr("axt.CLAUDE_CONFIG_FILE", tmp_path / "no-claude.json")
    _run(["plan", "set", "max20"])
    assert axt.load_config(tmp_path / "config.json").auto_detect_plan is False
    code, out, _ = _run(["plan", "set", "auto"])
    assert code == 0
    assert "Auto-detect enabled" in out
    assert axt.load_config(tmp_path / "config.json").auto_detect_plan is True


# ─── project ─────────────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_project_status_does_not_mutate_filesystem(tmp_path: Path, monkeypatch):
    """`status` is the pre-flight for `sync` (US-PRJ04 AC1): it must report the
    drift, never repair it. A snapshot around the call catches a handler that
    starts creating the missing symlinks."""
    # TC-API-048
    monkeypatch.setenv("NO_COLOR", "1")
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    axt.write_profile(proj, axt.AxtProfile(skills=("alpha", "beta")))
    (proj / ".claude" / "skills").mkdir(parents=True)
    tgt = tmp_path / "alpha-src"
    tgt.mkdir()
    os.symlink(tgt, proj / ".claude" / "skills" / "alpha")
    before = _tree_snapshot(proj)
    code, out, _ = _run(["project", "status"])
    assert code == 0
    assert "missing" in out  # beta is reported, not repaired
    assert _tree_snapshot(proj) == before


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_project_add_accepts_multiple_names(tmp_path: Path, monkeypatch):
    """`project add <type> <names...>` takes a batch (US-PRJ02 AC1). A regression
    to a single positional would silently link only the first name."""
    # TC-API-050
    monkeypatch.setenv("NO_COLOR", "1")
    paths = _vault_paths(tmp_path)
    _seed_vault_skill(paths.vault, "alpha")
    _seed_vault_skill(paths.vault, "beta")
    monkeypatch.setattr("axt.PATHS", paths)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    code, out, _ = _run(["project", "add", "skill", "alpha", "beta"])
    assert code == 0
    assert (proj / ".claude" / "skills" / "alpha").is_symlink()
    assert (proj / ".claude" / "skills" / "beta").is_symlink()
    assert out.count("✓") == 2  # one confirmation line per name


# ─── skill ───────────────────────────────────────────────────────────────────


def test_skill_link_subcommands_absent_when_symlinks_unsupported(monkeypatch):
    """On a platform without symlinks the link/unlink subcommands must not be
    registered at all (US-LNK02 AC2), so `axt skill --help` never advertises a
    command that can only fail. The handler's own guard is tested separately."""
    # TC-API-057
    monkeypatch.setattr("axt.is_symlink_supported", lambda: False)
    skill_group = _subparser_choices(axt.build_parser())["skill"]
    assert set(_subparser_choices(skill_group)) == {"list"}


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_skill_link_missing_path_exits_1(tmp_path: Path, monkeypatch):
    """Linking a path that doesn't exist must fail (US-LNK02 AC3) instead of
    creating a broken symlink that later shows up as a phantom skill."""
    # TC-API-058
    monkeypatch.setenv("NO_COLOR", "1")
    skills = tmp_path / "skills"
    monkeypatch.setattr("axt.PATHS", axt.Paths(skills=skills))
    missing = tmp_path / "no-such-dir"
    code, out, err = _run(["skill", "link", str(missing)])
    assert code == 1
    assert "✗" in err or "✗" in out
    assert not (skills / "no-such-dir").exists()
    assert not (skills / "no-such-dir").is_symlink()


# ─── usage: filters ──────────────────────────────────────────────────────────

# The `today` window is `since = until = _today_in_tz(tz)`, so these tests pin
# that seam to a fixed date and give every entry a *naive* timestamp — the same
# instant the date cutoff parses to, on any host timezone. Without both, the
# assertions would depend on the wall clock (and on the machine's tz offset).

_USAGE_DAY = "2026-03-01"
_USAGE_TS = "2026-03-01T00:00:00"


def _usage_record(session: str, ts: str, *, model: str = "claude-opus-4-7",
                  inp: int = 1000) -> dict:
    return {
        "type": "assistant", "sessionId": session, "timestamp": ts,
        "message": {"model": model, "usage": {
            "input_tokens": inp, "output_tokens": 10,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
    }


def _pin_today(monkeypatch, day: str) -> None:
    monkeypatch.setattr("axt._today_in_tz", lambda tz: day)


def test_usage_today_project_filter_narrows_totals(tmp_path: Path, monkeypatch):
    """--project must restrict the aggregate to that project's entries. A flag
    that parses but never reaches the loader would report every project's
    tokens under one project's name."""
    # TC-API-064
    monkeypatch.setenv("NO_COLOR", "1")
    projects = tmp_path / "projects"
    _write_jsonl(projects / "projA" / "a.jsonl", [_usage_record("sess-a", _USAGE_TS, inp=1000)])
    _write_jsonl(projects / "projB" / "b.jsonl", [_usage_record("sess-b", _USAGE_TS, inp=7000)])
    _isolate_usage(tmp_path, monkeypatch, projects=projects)
    _pin_today(monkeypatch, _USAGE_DAY)
    code, out, _ = _run(["usage", "today", "--timezone", "UTC", "--project", "projA", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["sessions"] == 1
    assert data["inputTokens"] == 1000  # projB's 7000 must not be counted


def test_usage_filters_combine_as_and(tmp_path: Path, monkeypatch):
    """--model and --project are ANDed (US-USG02 AC3). If either were applied
    as an OR the total would include entries matching only one condition."""
    # TC-API-068
    monkeypatch.setenv("NO_COLOR", "1")
    projects = tmp_path / "projects"
    _write_jsonl(projects / "projA" / "a.jsonl", [
        _usage_record("sess-a1", _USAGE_TS, model="claude-opus-4-7", inp=1000),
        _usage_record("sess-a2", _USAGE_TS, model="claude-sonnet-4-6", inp=200),
    ])
    _write_jsonl(projects / "projB" / "b.jsonl", [
        _usage_record("sess-b1", _USAGE_TS, model="claude-opus-4-7", inp=7000)])
    _isolate_usage(tmp_path, monkeypatch, projects=projects)
    _pin_today(monkeypatch, _USAGE_DAY)
    code, out, _ = _run(["usage", "today", "--timezone", "UTC",
                         "--model", "claude-opus-4-7", "--project", "projA", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["sessions"] == 1
    assert data["inputTokens"] == 1000  # only the opus entry inside projA


def test_usage_since_until_narrow_the_window(tmp_path: Path, monkeypatch):
    """--since/--until must actually bound the query (US-USG02). They are
    currently parsed and dropped, so a user asking for one past day gets the
    default window instead of their data."""
    # TC-API-065
    monkeypatch.setenv("NO_COLOR", "1")
    projects = tmp_path / "projects"
    _write_jsonl(projects / "projA" / "a.jsonl", [
        _usage_record("sess-1", "2026-03-01T00:00:00", inp=100),
        _usage_record("sess-2", "2026-03-02T00:00:00", inp=200),
        _usage_record("sess-3", "2026-03-03T00:00:00", inp=400),
    ])
    _isolate_usage(tmp_path, monkeypatch, projects=projects)
    # A "today" with no data, so a pass can only come from --since/--until.
    _pin_today(monkeypatch, "2026-06-15")
    code, out, _ = _run(["usage", "today", "--timezone", "UTC",
                         "--since", "2026-03-01", "--until", "2026-03-01", "--json"])
    assert code == 0
    assert "No usage data" not in out, "--since/--until were ignored; the default today window was used"
    data = json.loads(out)
    assert data["sessions"] == 1
    assert data["inputTokens"] == 100


def test_usage_invalid_date_format_exits_1(tmp_path: Path, monkeypatch):
    """An unparseable --since must fail with a format hint (US-USG02 AC1).
    Silently ignoring it hands back a report for the wrong period, which the
    caller has no way to notice."""
    # TC-API-066
    monkeypatch.setenv("NO_COLOR", "1")
    _isolate_usage(tmp_path, monkeypatch)
    code, out, err = _run(["usage", "today", "--timezone", "UTC", "--since", "notadate"])
    assert code == 1
    assert "notadate" in out + err
    assert "YYYY-MM-DD" in out + err  # the format guidance the AC calls for


def test_usage_since_after_until_is_an_error(tmp_path: Path, monkeypatch):
    """An inverted range is a user mistake, not an empty result (US-USG02 AC2)
    — reporting "no data" would look like a billing anomaly."""
    # TC-API-067
    monkeypatch.setenv("NO_COLOR", "1")
    _isolate_usage(tmp_path, monkeypatch)
    code, out, err = _run(["usage", "today", "--timezone", "UTC",
                           "--since", "2026-03-10", "--until", "2026-03-01"])
    assert code == 1
    assert "2026-03-10" in out + err


# ─── usage: output formats ───────────────────────────────────────────────────


def _uentry(day: str, session: str, *, model: str = "claude-opus-4-7",
            inp: int = 1000, out: int = 2000, cw: int = 500, cr: int = 8000):
    return axt.UnifiedUsageEntry(
        platform="claude", model=model, timestamp=f"{day}T00:00:00.000Z",
        session_id=session, project_path="proj-x", input_tokens=inp,
        output_tokens=out, cache_write_tokens=cw, cache_read_tokens=cr)


def _stub_usage_entries(tmp_path: Path, monkeypatch, entries) -> None:
    """`_stub_usage` for more than one entry — the week/month windows are
    computed from the wall clock, so the loader is stubbed to keep the row set
    fixed no matter what day the suite runs on."""
    monkeypatch.setattr("axt.load_unified_usage", lambda **kw: list(entries))
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    monkeypatch.setattr("axt.PATHS", axt.Paths(projects=tmp_path / "projects"))


def test_usage_week_csv_rows_match_header_column_count(tmp_path: Path, monkeypatch):
    """Every CSV data row must have exactly as many fields as the header
    (US-USG03 AC2). A value that grows a comma (a thousands separator, a model
    list) shifts every later column in the consumer's spreadsheet."""
    # TC-API-072
    monkeypatch.setenv("NO_COLOR", "1")
    _stub_usage_entries(tmp_path, monkeypatch, [
        _uentry("2026-05-18", "s1", inp=1_500_000, out=2_500_000),
        _uentry("2026-05-19", "s2"),
        _uentry("2026-05-20", "s3"),
    ])
    code, out, _ = _run(["usage", "week", "--timezone", "UTC", "--csv"])
    assert code == 0
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 4  # header + one row per day
    width = lines[0].count(",")
    for row in lines[1:]:
        assert row.count(",") == width, row


def test_usage_week_json_and_csv_together_emit_one_format(tmp_path: Path, monkeypatch):
    """--json and --csv at once must produce exactly one machine format
    (currently JSON wins). Concatenating both would break every parser on
    either side."""
    # TC-API-073
    monkeypatch.setenv("NO_COLOR", "1")
    _stub_usage_entries(tmp_path, monkeypatch, [_uentry("2026-05-20", "s1")])
    code, out, _ = _run(["usage", "week", "--timezone", "UTC", "--json", "--csv"])
    assert code == 0
    data = json.loads(out)  # fails outright if a CSV block is mixed in
    assert isinstance(data, list) and data
    assert "date,sessions," not in out


def test_usage_session_ambiguous_prefix_lists_candidates(tmp_path: Path, monkeypatch):
    """A prefix matching several sessions must list them (US-USG05 AC3).
    Rendering the first match alone reports one session's cost under a query
    the user believes covers all of them."""
    # TC-API-079
    monkeypatch.setenv("NO_COLOR", "1")
    projects = tmp_path / "projects"
    _write_jsonl(projects / "projA" / "a.jsonl", [
        _usage_record("abc-1111", "2026-03-01T00:00:00"),
        _usage_record("abc-2222", "2026-03-02T00:00:00"),
    ])
    _isolate_usage(tmp_path, monkeypatch, projects=projects)
    code, out, err = _run(["usage", "session", "abc"])
    assert "abc-1111" in out + err
    assert "abc-2222" in out + err, "only the first match was shown; the ambiguity is invisible"


# ─── vault ───────────────────────────────────────────────────────────────────


def test_vault_add_duplicate_directory_refuses(tmp_path: Path, monkeypatch):
    """Adding a directory whose name is already in the vault must fail
    (US-VLT03 AC4) and leave the stored copy untouched — an overwrite would
    destroy a curated skill with whatever happened to be on disk."""
    # TC-API-084
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("axt.PATHS", _vault_paths(tmp_path))
    src = tmp_path / "my-skill"
    src.mkdir()
    (src / "SKILL.md").write_text("---\ndescription: v1\n---\n")
    assert _run(["vault", "add", str(src), "-t", "skill"])[0] == 0
    (src / "SKILL.md").write_text("---\ndescription: v2\n---\n")
    code, out, err = _run(["vault", "add", str(src), "-t", "skill"])
    assert code == 1
    assert "✗" in out + err
    stored = tmp_path / "vault" / "skills" / "my-skill" / "SKILL.md"
    assert "v1" in stored.read_text()


def test_vault_add_duplicate_file_refuses(tmp_path: Path, monkeypatch):
    """Same contract for the file (command/agent) branch: a name collision is
    an error, never a silent overwrite."""
    # TC-API-084
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("axt.PATHS", _vault_paths(tmp_path))
    src = tmp_path / "do-thing.md"
    src.write_text("# v1\n")
    assert _run(["vault", "add", str(src)])[0] == 0
    src.write_text("# v2\n")
    code, out, err = _run(["vault", "add", str(src)])
    assert code == 1
    assert "✗" in out + err
    assert (tmp_path / "vault" / "commands" / "do-thing.md").read_text() == "# v1\n"


def test_vault_install_unregistered_marketplace_is_distinguishable(tmp_path: Path, monkeypatch):
    """An unregistered marketplace and a missing extension are different
    mistakes (US-VLT04 AC1 vs AC2). Reporting both as "extension not found"
    sends the user hunting for a package name when they need `market add`."""
    # TC-API-086
    monkeypatch.setenv("NO_COLOR", "1")
    paths = _vault_paths(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=paths.vault, vault_skills=paths.vault_skills,
        vault_commands=paths.vault_commands, vault_agents=paths.vault_agents,
        known_marketplaces=tmp_path / "km.json",
        marketplaces=tmp_path / "marketplaces"))
    code, out, err = _run(["vault", "install", "ghost-market", "some-skill"])
    text = out + err
    assert code == 1
    assert "ghost-market" in text
    assert "not registered" in text.lower() or "available" in text.lower()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_vault_link_global_mirror_agents_points_at_vault(tmp_path: Path, monkeypatch):
    """--mirror-agents adds `~/.agents/skills/<name>` pointing straight at the
    vault copy (US-VLT06 AC1). A mirror chained through ~/.claude/skills breaks
    as soon as the global link is removed."""
    # TC-API-090
    monkeypatch.setenv("NO_COLOR", "1")
    paths = _vault_paths(tmp_path)
    _seed_vault_skill(paths.vault, "alpha")
    monkeypatch.setattr("axt.PATHS", paths)
    monkeypatch.setattr("axt.HOME", tmp_path / "home")
    code, out, _ = _run(["vault", "link-global", "skill", "alpha", "--mirror-agents"])
    assert code == 0
    mirror = tmp_path / "home" / ".agents" / "skills" / "alpha"
    assert mirror.is_symlink()
    assert os.path.realpath(mirror) == os.path.realpath(paths.vault / "skills" / "alpha")
    assert "✓" in out


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_vault_link_global_mirror_respects_skill_lock(tmp_path: Path, monkeypatch):
    """`.skill-lock.json` marks `.agents` as another installer's tree: mirroring
    must be skipped (⊘, still exit 0) unless --force-agents is given
    (US-VLT06 AC2, AC3). Writing into a locked tree makes two managers fight
    over the same symlinks."""
    # TC-API-091
    monkeypatch.setenv("NO_COLOR", "1")
    paths = _vault_paths(tmp_path)
    _seed_vault_skill(paths.vault, "alpha")
    _seed_vault_skill(paths.vault, "beta")
    monkeypatch.setattr("axt.PATHS", paths)
    home = tmp_path / "home"
    monkeypatch.setattr("axt.HOME", home)
    (home / ".agents").mkdir(parents=True)
    (home / ".agents" / ".skill-lock.json").write_text("{}")

    code, out, _ = _run(["vault", "link-global", "skill", "alpha", "--mirror-agents"])
    assert code == 0
    assert "⊘" in out
    assert not (home / ".agents" / "skills" / "alpha").exists()

    code2, out2, _ = _run(["vault", "link-global", "skill", "beta",
                           "--mirror-agents", "--force-agents"])
    assert code2 == 0
    assert (home / ".agents" / "skills" / "beta").is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_vault_unlink_global_mirror_agents_removes_both(tmp_path: Path, monkeypatch):
    """`unlink-global --mirror-agents` must clear the `.agents` mirror as well
    as the global link (US-VLT06 AC4), while the vault copy survives — a left
    over mirror keeps a "removed" skill loaded in other agent tools."""
    # TC-API-092
    monkeypatch.setenv("NO_COLOR", "1")
    paths = _vault_paths(tmp_path)
    _seed_vault_skill(paths.vault, "alpha")
    monkeypatch.setattr("axt.PATHS", paths)
    home = tmp_path / "home"
    monkeypatch.setattr("axt.HOME", home)
    _run(["vault", "link-global", "skill", "alpha", "--mirror-agents"])
    code, out, _ = _run(["vault", "unlink-global", "skill", "alpha", "--mirror-agents"])
    assert code == 0
    assert not (paths.claude_dir / "skills" / "alpha").exists()
    assert not (home / ".agents" / "skills" / "alpha").is_symlink()
    assert (paths.vault / "skills" / "alpha" / "SKILL.md").exists()


# ─── context ─────────────────────────────────────────────────────────────────


def _isolate_context(tmp_path: Path, monkeypatch) -> None:
    """Point the context analyzer at an empty tmp home so only the two fixed
    sources (system-prompt / user-context) are guaranteed present."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("axt.HOME", tmp_path / "home")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "claude",
        claude_config=tmp_path / "claude.json",
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
        projects=tmp_path / "projects",
        skills=tmp_path / "claude" / "skills"))
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr("axt.get_claude_version", lambda: "test")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")


def _context_item_rows(text: str) -> list[str]:
    """The per-source rows `--detail` adds under each category (they end in a
    token count followed by `tok`)."""
    return [ln for ln in text.splitlines() if re.search(r"\stok(\s|$)", ln)]


def test_context_detail_expands_category_items(tmp_path: Path, monkeypatch):
    """--detail must add the individual sources under each category
    (US-CTX01 AC2); without them the report says a category is expensive but
    not which file to trim."""
    # TC-API-095
    _isolate_context(tmp_path, monkeypatch)
    code_plain, plain, _ = _run(["context"])
    code_detail, detail, _ = _run(["context", "--detail"])
    assert code_plain == 0 and code_detail == 0
    assert _context_item_rows(plain) == []
    assert _context_item_rows(detail)
    assert len(detail.splitlines()) > len(plain.splitlines())


def test_context_category_filter_keeps_only_that_category(tmp_path: Path, monkeypatch):
    """--category narrows the table to one category (US-CTX01 AC3). A filter
    applied to the wrong field (or not at all) would leave every row in."""
    # TC-API-096
    _isolate_context(tmp_path, monkeypatch)
    code, out, _ = _run(["context", "--category", "system-prompt"])
    assert code == 0
    assert "System prompt" in out
    assert "User context" not in out  # the other always-present fixed category


def test_context_unknown_category_is_empty_not_an_error(tmp_path: Path, monkeypatch):
    """An unknown category name yields an empty table and exit 0 — it is a
    filter, not a validated enum, so scripts iterating category names must not
    break on one that has no sources."""
    # TC-API-096
    _isolate_context(tmp_path, monkeypatch)
    code, out, _ = _run(["context", "--category", "nope"])
    assert code == 0
    assert "System prompt" not in out
    assert "Cost Impact" in out  # the rest of the report still renders


def test_context_model_override_changes_context_window(tmp_path: Path, monkeypatch):
    """--model overrides auto-detection, and the window/percentage must follow
    it — otherwise the percentage is computed against a different model's
    window than the one reported."""
    # TC-API-097
    _isolate_context(tmp_path, monkeypatch)
    code, out, _ = _run(["context", "--model", "claude-haiku-4-5", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["model"] == "claude-haiku-4-5"
    assert data["contextWindowSize"] == 200000
    expected_pct = data["totalTokens"] / data["contextWindowSize"] * 100
    assert abs(data["usedPercent"] - expected_pct) < 0.01


# ─── update ──────────────────────────────────────────────────────────────────


def _stub_update_statuses(monkeypatch, statuses) -> None:
    monkeypatch.setattr("axt.cli.check_all_updates", lambda types=None: list(statuses))


def _no_apply(monkeypatch) -> None:
    """Make any apply attempt an immediate, loud failure."""
    def _boom(*a, **k):
        raise AssertionError("apply_updates must not run for this invocation")
    monkeypatch.setattr("axt.cli.apply_updates", _boom)


def test_update_report_groups_all_four_tiers(monkeypatch):
    """The dry-run report separates Updatable / Up to date / Manual / Delegated
    and closes with a count line (US-UPD01 AC2, AC3). Collapsing the tiers hides
    which items `--apply` would actually touch."""
    # TC-API-098
    monkeypatch.setenv("NO_COLOR", "1")
    _stub_update_statuses(monkeypatch, [
        axt.update.UpdateStatus("marketplace", "m1", 1, "1.0", "1.1", True),
        axt.update.UpdateStatus("plugin", "p@m", 1, "2.0", "2.0", False),
        axt.update.UpdateStatus("mcp", "srv", 2, "?", "?", False, note="manual"),
        axt.update.UpdateStatus("claude-code", "claude-code", 3, "2.1.0", "?", False,
                                note="updates via claude update"),
    ])
    _no_apply(monkeypatch)
    code, out, _ = _run(["update"])
    assert code == 0
    for header in ("Updatable:", "Up to date:", "Manual (report only):", "Delegated:"):
        assert header in out, header
    assert "1 updatable, 1 up to date, 1 manual, 1 delegated" in out


def test_update_without_apply_changes_nothing(tmp_path: Path, monkeypatch):
    """`axt update` is a report (US-UPD01 AC1): it must never call
    apply_updates and must not write anything."""
    # TC-API-099
    monkeypatch.setenv("NO_COLOR", "1")
    _stub_update_statuses(monkeypatch, [
        axt.update.UpdateStatus("marketplace", "m1", 1, "1.0", "1.1", True)])
    _no_apply(monkeypatch)
    before = _tree_snapshot(tmp_path)
    code, _, _ = _run(["update"])
    assert code == 0
    assert _tree_snapshot(tmp_path) == before


def test_update_unknown_type_exits_2(monkeypatch):
    """An unsupported update type is rejected by argparse (US-UPD04 AC2) — it
    must not be silently treated as `all` and sweep everything."""
    # TC-API-100
    monkeypatch.setenv("NO_COLOR", "1")
    code, _, err = _run_expect_exit(["update", "bogus"])
    assert code == 2
    assert "invalid choice" in err


def test_update_unknown_name_reports_and_fails(monkeypatch):
    """`update <type> <name>` with a name nothing matches must exit 1 with a
    notice (US-UPD04 AC3). Exiting 0 on a typo makes a CI step that "updated
    plugin X" pass without ever finding X."""
    # TC-API-101 — the TC notes the current build exits 0 with an empty report;
    # US-UPD04 AC3 is the contract, so the assertion follows the spec.
    monkeypatch.setenv("NO_COLOR", "1")
    _stub_update_statuses(monkeypatch, [
        axt.update.UpdateStatus("plugin", "real@m", 1, "1.0", "1.1", True)])
    _no_apply(monkeypatch)
    code, out, err = _run(["update", "plugin", "ghost"])
    assert code == 1
    assert "ghost" in out + err


def test_update_apply_with_no_targets_says_nothing_to_update(monkeypatch):
    """Nothing updatable is a normal outcome: exit 0 with a plain message and
    no apply pass."""
    # TC-API-106
    monkeypatch.setenv("NO_COLOR", "1")
    _stub_update_statuses(monkeypatch, [
        axt.update.UpdateStatus("marketplace", "m1", 1, "1.0", "1.0", False)])
    _no_apply(monkeypatch)
    code, out, _ = _run(["update", "--apply", "--yes"])
    assert code == 0
    assert "Nothing to update." in out


def test_update_apply_json_never_prompts(monkeypatch):
    """--json means non-interactive (US-UPD03 AC1): --apply must proceed without
    the confirmation prompt even without -y, or a pipeline hangs on stdin."""
    # TC-API-108
    monkeypatch.setenv("NO_COLOR", "1")
    _stub_update_statuses(monkeypatch, [
        axt.update.UpdateStatus("marketplace", "m1", 1, "1.0", "1.1", True)])

    def _no_input(*a, **k):
        raise AssertionError("--json must not prompt for confirmation")
    monkeypatch.setattr("builtins.input", _no_input)
    monkeypatch.setattr("axt.cli.apply_updates", lambda targets, no_sync=False: [
        axt.update.UpdateResult("marketplace", "m1", "1.0", "1.1", True, "git pull")])
    code, out, _ = _run(["update", "--apply", "--json"])
    assert code == 0
    result = json.loads(out)[0]
    assert set(result) >= {"item_type", "name", "before", "after", "updated", "action", "error"}
    assert result["updated"] is True


def test_update_apply_json_with_no_targets_emits_empty_array(monkeypatch):
    """With --json the empty case must still be valid JSON (`[]`), not the
    human "Nothing to update." line — the consumer parses stdout either way."""
    # TC-API-109
    monkeypatch.setenv("NO_COLOR", "1")
    _stub_update_statuses(monkeypatch, [])
    _no_apply(monkeypatch)
    code, out, _ = _run(["update", "--apply", "--json"])
    assert code == 0
    assert json.loads(out) == []
    assert out.strip() == "[]"
