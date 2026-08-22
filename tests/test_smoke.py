"""Smoke tests — the post-install critical path only.

Scope (TEST_DEDUP_POLICY.md §2 → smoke layer): *does it come up after a fresh
install?* Entry point, version wiring, parser tree, survival on a machine with
no `~/.claude`, TUI start/stop, packaging. Per-command exit codes and output
contracts belong to `tests/test_cli.py`; domain rules belong to the per-domain
unit files; TUI key dispatch belongs to `tests/test_tui.py`.

Every test keeps the user's real `~/.claude` / `~/.axt` / `~/.config/axt` out of
the picture — read-only where a test has to look at them (TC-SMOKE-016), never
written.
"""
from __future__ import annotations

import io
import os
import re
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import axt

REPO_ROOT = Path(axt.__file__).resolve().parent.parent


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Invoke axt.main(argv) capturing stdout/stderr (same shape as test_cli)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = axt.main(argv)
    return code, out.getvalue(), err.getvalue()


def _toml_section(name: str) -> list[str]:
    """Raw lines of one `[section]` of pyproject.toml.

    tomllib only exists on 3.11+ and the package targets 3.9, so the smoke
    tests read the file the same way the version-drift guard does."""
    lines = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            inside = stripped == f"[{name}]"
            continue
        if inside:
            out.append(line)
    return out


def _subparser_choices(parser) -> dict:
    """`{name: subparser}` for a parser's subcommand group, {} when it is a leaf."""
    import argparse
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _leaf_subcommands(parser, prefix: str = "") -> list[str]:
    """Every runnable command path in the argparse tree ('vault add', 'tui', …)."""
    choices = _subparser_choices(parser)
    if not choices:
        return [prefix]
    leaves: list[str] = []
    for name, sub in choices.items():
        leaves.extend(_leaf_subcommands(sub, f"{prefix} {name}".strip()))
    return leaves


# ─── 1. Entry point (SC-SMOKE-001) ───────────────────────────────────────────


def test_console_script_entry_point_is_declared():
    """`pip install` only creates the `axt` command if pyproject declares it.
    Losing this line ships a package with no runnable command — and nothing in
    the test suite would otherwise notice."""
    # TC-SMOKE-001
    scripts = {}
    for line in _toml_section("project.scripts"):
        if "=" in line:
            key, _, value = line.partition("=")
            scripts[key.strip()] = value.strip().strip('"')
    assert scripts.get("axt") == "axt:main", scripts


def test_declared_entry_point_resolves():
    """Resolve the `module:attr` string pyproject actually declares, the way
    the console script does. Moving `main` (or breaking the package mirror
    that re-exports it) leaves the declaration pointing at nothing."""
    # TC-SMOKE-002
    import importlib
    declared = ""
    for line in _toml_section("project.scripts"):
        if line.strip().startswith("axt"):
            declared = line.partition("=")[2].strip().strip('"')
    assert declared, "no `axt` entry point declared in pyproject.toml"
    module_name, _, attr = declared.partition(":")
    entry = getattr(importlib.import_module(module_name), attr)
    assert callable(entry)
    assert entry is axt.cli.main  # the same function the CLI tests drive


# ─── 3. Parser tree (SC-SMOKE-003) ───────────────────────────────────────────


def test_parser_registers_all_twelve_command_groups():
    """Every command group must be wired into the parser. A subparser lost in
    a refactor makes `axt <group>` an "invalid choice" for users while the
    handler code still sits in the module, looking healthy.

    (The api layer asserts the same groups reach `--help`; here it is the tree
    itself, which is what breaks first.)"""
    # TC-SMOKE-010
    assert set(_subparser_choices(axt.build_parser())) == {
        "tui", "context", "market", "mcp", "hook", "plan",
        "plugin", "project", "skill", "usage", "vault", "update",
    }


def test_leaf_subcommand_count_matches_features_inventory():
    """FEATURES.md publishes the subcommand count; the parser is the truth.
    When they drift, either a command was added without documenting it or one
    was dropped without noticing. Table-vs-table checks like this are the
    explicit exception in TEST_DEDUP_POLICY.md §3."""
    # TC-SMOKE-011
    documented = re.search(r"(\d+)개 서브명령",
                           (REPO_ROOT / "FEATURES.md").read_text(encoding="utf-8"))
    assert documented, "FEATURES.md no longer states a subcommand count"
    expected = int(documented.group(1))
    if not axt.is_symlink_supported():
        expected -= 2  # `skill link` / `skill unlink` are not registered
    leaves = _leaf_subcommands(axt.build_parser())
    assert len(leaves) == expected, sorted(leaves)


# ─── 4. Empty environment, read-only commands (SC-SMOKE-004) ─────────────────

_READ_ONLY_COMMANDS: tuple[list[str], ...] = (
    ["market", "list"],
    ["plugin", "list"],
    ["skill", "list"],
    ["mcp", "list"],
    ["hook", "list"],
    ["vault", "list"],
    ["usage", "today", "--timezone", "UTC"],
    ["plan", "overview"],
    ["context"],
)


def _empty_env(tmp_path: Path, monkeypatch) -> Path:
    """A machine that has never run Claude Code: every axt path points below a
    tmp dir that does not exist. Returns the cwd the commands run from."""
    monkeypatch.setenv("NO_COLOR", "1")
    home = tmp_path / "home"
    nothing = home / ".claude"
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=nothing,
        claude_config=home / ".claude.json",
        settings=nothing / "settings.json",
        known_marketplaces=nothing / "plugins" / "known_marketplaces.json",
        installed_plugins=nothing / "plugins" / "installed_plugins.json",
        blocklist=nothing / "plugins" / "blocklist.json",
        plugin_cache=nothing / "plugins" / "cache",
        marketplaces=nothing / "plugins" / "marketplaces",
        skills=nothing / "skills",
        projects=nothing / "projects",
        stats_cache=nothing / "stats-cache.json",
        usage_snapshot=nothing / "usage-snapshot.json",
        axt_dir=home / ".axt",
        vault=home / ".axt" / "vault",
        vault_skills=home / ".axt" / "vault" / "skills",
        vault_commands=home / ".axt" / "vault" / "commands",
        vault_agents=home / ".axt" / "vault" / "agents",
    ))
    # Read directly from module constants rather than PATHS.
    monkeypatch.setattr("axt.CLAUDE_CONFIG_FILE", home / ".claude.json")
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "axt-config.json")
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "usage-cache")
    monkeypatch.setattr("axt._onboarded_marker_path", lambda: tmp_path / "onboarded")
    # External commands: a fresh machine may have neither claude nor git.
    monkeypatch.setattr("axt.get_claude_version", lambda: "test")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def test_extension_queries_survive_a_missing_claude_dir(tmp_path: Path, monkeypatch):
    """With no `~/.claude` at all, every extension listing must return an empty
    state instead of crashing (US-SYS05 AC3) — this is exactly what a new user
    sees on their first run."""
    # TC-SMOKE-012
    _empty_env(tmp_path, monkeypatch)
    expected = {
        ("market", "list"): "No marketplaces registered",
        ("plugin", "list"): "No plugins installed",
        ("skill", "list"): "No skills found",
        # MCP has no true empty state: the built-in servers are always listed
        # (opt-in, so they render as available-but-off).
        ("mcp", "list"): "built-in",
        ("hook", "list"): "No hooks found.",
        ("vault", "list"): "Vault is empty",
    }
    for argv, hint in expected.items():
        code, out, err = _run(list(argv))
        assert code == 0, (argv, err)
        assert hint in out, (argv, out)


def test_context_analysis_survives_a_missing_claude_dir(tmp_path: Path, monkeypatch):
    """Context analysis walks a dozen optional sources; with none of them
    present it must still render its report off the two fixed sources rather
    than dividing by zero or tripping over a missing directory."""
    # TC-SMOKE-014
    _empty_env(tmp_path, monkeypatch)
    code, out, _ = _run(["context"])
    assert code == 0
    assert "Context Usage" in out
    assert "Cost Impact" in out


def test_read_only_commands_emit_no_traceback(tmp_path: Path, monkeypatch):
    """A stack trace on stderr means an unhandled exception escaped. Even when
    the exit code happens to be 0, that output is the signature of a bug the
    user is being asked to read."""
    # TC-SMOKE-015
    _empty_env(tmp_path, monkeypatch)
    for argv in _READ_ONLY_COMMANDS:
        _, _, err = _run(list(argv))
        assert "Traceback (most recent call last)" not in err, (argv, err)


def _entry_marker(path: Path):
    """(kind, mtime, size) for one path, or 'absent'/'unreadable'."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unreadable"
    return (os.path.isdir(path), st.st_mtime_ns, st.st_size)


def _dir_snapshot(path: Path):
    """Recursive snapshot of a directory: each entry mapped to its marker.

    Recursive, not shallow: rewriting `cache/claude-usage.json` in place leaves
    the parent directory's own mtime untouched, so a one-level snapshot would
    pass while the real cache was being clobbered."""
    if not path.exists():
        return "absent"
    return {str(p.relative_to(path)): _entry_marker(p) for p in sorted(path.rglob("*"))}


def test_read_only_commands_do_not_touch_the_real_home(tmp_path: Path, monkeypatch):
    """Every path seam is patched, so nothing may land in the user's real
    config. A handler that reaches for a module constant instead of the
    injected path writes to the developer's own `~/.config/axt` — invisible
    until it corrupts real data.

    Only axt-owned locations are compared: a Claude Code session running in
    another window writes to `~/.claude/projects` constantly, and that is not
    this test's business."""
    # TC-SMOKE-016
    real_axt_config = Path(axt.AXT_CONFIG_DIR)
    real_home = Path(axt.HOME)
    watched_dirs = [real_axt_config, real_home / ".axt"]
    watched_files = [
        real_home / ".claude.json",
        real_home / ".claude" / "settings.json",
        real_home / ".claude" / "plugins" / "installed_plugins.json",
        real_home / ".claude" / "plugins" / "known_marketplaces.json",
    ]
    before_dirs = [_dir_snapshot(d) for d in watched_dirs]
    before_files = [_entry_marker(f) for f in watched_files]

    _empty_env(tmp_path, monkeypatch)
    for argv in _READ_ONLY_COMMANDS:
        _run(list(argv))

    assert [_dir_snapshot(d) for d in watched_dirs] == before_dirs
    assert [_entry_marker(f) for f in watched_files] == before_files


# ─── 5. Empty environment, writing commands (SC-SMOKE-005) ───────────────────


def test_project_init_then_status_on_an_empty_environment(tmp_path: Path, monkeypatch):
    """The first thing a new user does in a repo: create the profile and read
    it back. `init` must write where `status` looks — a mismatch leaves
    `status` reporting "no profile" right after one was created."""
    # TC-SMOKE-017
    work = _empty_env(tmp_path, monkeypatch)
    code, out, _ = _run(["project", "init"])
    assert code == 0
    assert (work / ".axt-profile.json").exists()
    code2, _, err2 = _run(["project", "status"])
    assert code2 == 0, err2


# ─── 6. TUI start / stop (SC-SMOKE-006) ──────────────────────────────────────


def test_tui_failure_without_a_tty_has_no_traceback():
    """Piping `axt` (CI, `axt | less`) can't initialize curses. The failure has
    to read as a message, not as a crash dump."""
    # TC-SMOKE-020
    err = io.StringIO()
    with redirect_stderr(err):
        code = axt.launch_tui()
    assert code == 1
    assert "Traceback (most recent call last)" not in err.getvalue()


def test_launch_tui_returns_zero_when_the_loop_quits(tmp_path: Path, monkeypatch):
    """The whole launch path — `launch_tui` → `curses.wrapper` → `_tui_loop` —
    must come back with exit 0 when the user presses `q`. Key dispatch itself
    is covered in test_tui.py; what is checked here is the wiring between the
    three, which a headless environment can otherwise never exercise."""
    # TC-SMOKE-021
    _empty_env(tmp_path, monkeypatch)
    scr = MagicMock()
    scr.getmaxyx.return_value = (30, 120)
    keys = iter([ord("q")])
    scr.getch.side_effect = lambda: next(keys)
    monkeypatch.setattr("curses.curs_set", lambda *a: None)
    monkeypatch.setattr("curses.set_escdelay", lambda *a: None, raising=False)
    monkeypatch.setattr("axt.tui.loop.tui_init_colors", lambda *a, **k: None)
    # The launch primes a background vault scan in a daemon thread; stub it so
    # the smoke test stays single-threaded and deterministic.
    monkeypatch.setattr("axt.tui.loop._prime_vault_scan", lambda *a, **k: None)
    entered = []
    monkeypatch.setattr("curses.wrapper",
                        lambda fn: entered.append(True) or fn(scr))
    assert axt.launch_tui("dark") == 0
    assert entered == [True]  # the loop really ran, the 0 isn't from a skip


# ─── 8. Packaging (SC-SMOKE-008) ─────────────────────────────────────────────


def test_runtime_dependencies_are_empty():
    """axt is stdlib-only by design (US-SYS07 AC1). A dependency added here
    turns every install into a resolvable-versions problem; optional extras
    (dev, windows-curses) are deliberately not part of this check."""
    # TC-SMOKE-023
    declared = [line for line in _toml_section("project")
                if line.strip().startswith("dependencies")]
    assert declared, "[project] no longer declares `dependencies`"
    assert declared[0].split("=", 1)[1].strip() == "[]", declared[0]


def test_pricing_table_ships_as_package_data_and_loads():
    """`pricing.json` lives next to the code but is only installed because
    pyproject declares it as package data. Without that declaration the wheel
    installs fine and then prices every model at zero at runtime — a failure
    that no test touching the source tree can see, so the declaration itself
    is asserted here alongside a real reload."""
    # TC-SMOKE-024
    declaration = [line for line in _toml_section("tool.setuptools")
                   if line.strip().startswith("package-data")]
    assert declaration, "[tool.setuptools] no longer declares package-data"
    assert "pricing.json" in declaration[0]

    pricing_file = Path(axt.core._PRICING_FILE)
    assert pricing_file.exists()
    assert pricing_file.parent == Path(axt.core.__file__).resolve().parent

    axt.reload_pricing_table()
    p = axt.get_model_pricing("claude-opus-4-8")
    assert p is not None, "the shipped pricing table did not load"
    assert (p.input, p.output, p.cache_write, p.cache_read) == (5.00, 25.00, 6.25, 0.50)
