"""Chaos layer — deterministic fault injection and recovery.

Layer Owner (tests/doc/TEST_DEDUP_POLICY.md §2): "결함 주입 후 복원력".

Shared success criterion (US-SYS05 AC4): one broken item must not make the rest
unusable.

Determinism: every fixture lives under `tmp_path`; nothing touches the real
`~/.claude`. Faults are injected explicitly — `write_json_atomic` internals
raising `OSError`, `subprocess.run` raising `FileNotFoundError`, truncated JSON
written to real temp files, `os.chmod(0o000)`. Permission tests fail loudly
(never skip quietly) when run as root, because chmod-based injection is inert
there and a silent skip would read as a pass. Thread tests install a
`threading.excepthook` so an exception escaping a worker is recorded instead of
being printed to stderr and passing.
"""
from __future__ import annotations

import curses
import errno
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import axt
import axt.tui.tabs as tabs

from axt.tui.tabs import _kick_update_check as REAL_KICK_UPDATE_CHECK  # noqa: E402


# ─── helpers ─────────────────────────────────────────────────────────────────


def _make_stdscr(rows: int = 30, cols: int = 140):
    scr = MagicMock()
    scr.getmaxyx.return_value = (rows, cols)
    scr.calls = []
    scr.addnstr.side_effect = lambda *a: scr.calls.append(a)
    return scr


def _flat(scr) -> str:
    return "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))


def _isolate(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=home / ".claude",
        claude_config=home / ".claude.json",
        settings=home / ".claude" / "settings.json",
        known_marketplaces=home / ".claude" / "plugins" / "known_marketplaces.json",
        installed_plugins=home / ".claude" / "plugins" / "installed_plugins.json",
        marketplaces=home / ".claude" / "plugins" / "marketplaces",
        skills=home / ".claude" / "skills",
        projects=tmp_path / "projects",
        vault=tmp_path / "vault",
        vault_skills=tmp_path / "vault" / "skills",
        vault_commands=tmp_path / "vault" / "commands",
        vault_agents=tmp_path / "vault" / "agents",
    ))
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", tmp_path / "axtcfg")
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "axtcfg" / "config.json")
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "axtcfg" / "cache")
    monkeypatch.chdir(tmp_path)
    return home


def _require_non_root() -> None:
    """chmod-based fault injection is a no-op for root, so say so loudly."""
    if hasattr(os, "getuid") and os.getuid() == 0:
        pytest.fail("running as root makes chmod fault injection inert — run as a normal user")


def _skill_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text("---\nname: s\ndescription: d\nversion: 1.0.0\n---\nbody\n")
    return path


def _git(*args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


def _seed_git_marketplace(tmp_path: Path, km: Path, name: str = "x"):
    """origin repo at v1 + a clone registered as a git marketplace."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("git", "init", "-q", cwd=origin)
    _git("git", "config", "user.email", "t@t", cwd=origin)
    _git("git", "config", "user.name", "t", cwd=origin)
    (origin / "f.txt").write_text("v1\n")
    _git("git", "add", "f.txt", cwd=origin)
    _git("git", "commit", "-q", "-m", "v1", cwd=origin)

    install = tmp_path / "install"
    _git("git", "clone", "-q", str(origin), str(install), cwd=tmp_path)
    _git("git", "config", "user.email", "t@t", cwd=install)
    _git("git", "config", "user.name", "t", cwd=install)

    km.parent.mkdir(parents=True, exist_ok=True)
    km.write_text(json.dumps({
        name: {"source": {"source": "github", "repo": "o/r"},
               "installLocation": str(install), "lastUpdated": ""},
    }))
    return origin, install


# ─── SC-CHAOS-001 — corrupt JSON ─────────────────────────────────────────────


def test_truncated_settings_json_reads_empty_and_refuses_to_overwrite(tmp_path):
    """A half-written settings.json reads as {} but is not rewritten from it.

    Prevents: a crash mid-write by another process bricking every axt command
    that touches settings — reads degrade so listing keeps working. Prevents
    equally: the repair silently replacing the user's real settings with a
    one-key document, since the write path cannot tell what was lost
    (US-SYS05 AC1).
    """
    # TC-CHAOS-002
    settings = tmp_path / "settings.json"
    original = '{"enabledPlugins": {"alpha": tr'
    settings.write_text(original)

    assert axt.read_enabled_plugins(settings) == {}

    # Fixed: this expected the write to succeed and yield
    # {"enabledPlugins": {"beta": True}} — i.e. to discard whatever the file
    # held. The confirmed contract is reads degrade / writes refuse; see
    # tests/doc/TRIAGE_REPORT.md C-1.
    with pytest.raises(axt.CorruptSettingsError):
        axt.set_plugin_enabled(settings, "beta", True)
    assert settings.read_text() == original, "the damaged file must stay recoverable"


def test_corrupt_installed_plugins_lists_empty_and_tui_still_renders(tmp_path, monkeypatch):
    """Three shapes of corrupt installed_plugins.json all list as [].

    Prevents: a truncated / empty / garbage registry taking down the Plugins
    sub-tab. Real corruption arrives in all three shapes, and an empty file
    decodes through the same path as garbage (US-SYS05 AC1, US-TUI06 AC1).
    """
    # TC-CHAOS-003
    home = _isolate(tmp_path, monkeypatch)
    ip = home / ".claude" / "plugins" / "installed_plugins.json"
    ip.parent.mkdir(parents=True, exist_ok=True)
    km = home / ".claude" / "plugins" / "known_marketplaces.json"
    km.write_text("{}")

    for label, payload in (("truncated", '{"version": 2, "plugins":'),
                           ("empty", ""),
                           ("garbage", "not json at all")):
        ip.write_text(payload)
        assert axt.list_installed_plugins(ip, km) == [], f"{label} form did not fall back"

    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    tabs._ensure_subtab_loaded(state, "plugins")
    scr = _make_stdscr(30, 140)
    axt.render_extensions_tab(scr, state, 2, 26, 140)
    flat = _flat(scr)
    title, _hint = tabs._empty_state_hint("plugins")
    assert title in flat, "the Plugins sub-tab did not fall back to its empty state"


def test_corrupt_known_marketplaces_lists_empty_everywhere(tmp_path, monkeypatch, capsys):
    """A corrupt marketplace registry yields [], exit 0, and a live TUI.

    Prevents: the TUI dying on launch — `_ensure_subtab_loaded` does not wrap
    `list_marketplaces`, so a parse error there reaches the main loop and kills
    the dashboard, not just one sub-tab (US-SYS05 AC1, US-MKT03 AC2).
    """
    # TC-CHAOS-004
    home = _isolate(tmp_path, monkeypatch)
    km = home / ".claude" / "plugins" / "known_marketplaces.json"
    km.parent.mkdir(parents=True, exist_ok=True)
    km.write_text('{"mine": {"source":')

    assert axt.list_marketplaces(km) == []

    rc = axt.main(["market", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No marketplaces registered." in out

    state = axt.TuiState()
    state.ext_sub_tab = "market"
    tabs._ensure_subtab_loaded(state, "market")
    assert state.ext_cache["market"] == []


def test_corrupt_project_profile_is_not_mistaken_for_an_empty_one(tmp_path, monkeypatch, capsys):
    """A corrupt .axt-profile.json reads as empty and never triggers a purge.

    Prevents the worst outcome in this family: `project sync` reading a damaged
    profile as "declares nothing", then removing every real link in
    `.claude/skills` to match. That is data loss, not a display glitch
    (US-SYS05 AC1, US-PRJ03 AC2, US-PRJ04 AC1).
    """
    # TC-CHAOS-005
    _isolate(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    (proj / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.chdir(proj)
    vault_skill = _skill_dir(tmp_path / "vault" / "skills" / "kept")
    link = proj / ".claude" / "skills" / "kept"
    os.symlink(vault_skill, link)
    (proj / ".axt-profile.json").write_text('{"skills": [')

    # Fixed: this asserted read_profile may return None/empty for a corrupt
    # file — the very confusion the test name forbids, since sync_project reads
    # an empty profile as "nothing declared" and unlinks everything. The
    # contract is that a corrupt profile is a distinct, loud signal.
    with pytest.raises(axt.CorruptSettingsError):
        axt.read_profile(proj)

    rc_status = axt.main(["project", "status"])
    capsys.readouterr()
    assert rc_status == 0, "`project status` must survive a corrupt profile"

    axt.main(["project", "sync"])
    cap = capsys.readouterr()
    assert link.is_symlink(), (
        "`project sync` treated a corrupt profile as empty and removed a real link")
    assert (cap.out + cap.err).strip(), "the corrupt profile was not reported to the user"


def test_corrupt_usage_cache_rebuilds_from_the_session_files(tmp_path, monkeypatch):
    """Truncated / v1 / wrong-dir usage caches are discarded and rebuilt.

    Prevents: a damaged cache poisoning cost reporting. The v1 case matters most
    — stale rows from the old schema must be dropped whole, not merged into v2
    output (US-USG08 AC2/AC3).
    """
    # TC-CHAOS-006
    _isolate(tmp_path, monkeypatch)
    projects = tmp_path / "projects"
    for i in range(5):
        d = projects / f"p{i}"
        d.mkdir(parents=True)
        (d / "s.jsonl").write_text(json.dumps({
            "type": "assistant", "sessionId": f"s{i}",
            "timestamp": "2026-01-05T00:00:00.000Z",
            "message": {"model": "claude-sonnet-5", "usage": {"input_tokens": 10}},
        }) + "\n")
    cache_path = tmp_path / "axtcfg" / "cache" / "claude-usage.json"

    forms = {
        "truncated": '{"version": 2, "files": {',
        "v1-schema": json.dumps({
            "version": 1, "lastUpdated": "2026-01-05T00:00:00.000Z",
            "files": {"/old/ghost.jsonl": [{"model": "ghost-model", "inputTokens": 999}]},
        }),
        "other-projects-dir": json.dumps({
            "version": 2, "lastUpdated": "2026-01-05T00:00:00.000Z",
            "projectsDir": "/somewhere/else", "models": [], "sessions": {}, "files": {},
        }),
    }
    for label, payload in forms.items():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(payload)

        entries = axt.load_all_claude_usage(projects, force_refresh=True)

        assert len(entries) == 5, f"{label}: rebuilt {len(entries)} entries, expected 5"
        assert all(e.model == "claude-sonnet-5" for e in entries), (
            f"{label}: rows from the discarded cache leaked into the result")
        rebuilt = json.loads(cache_path.read_text())
        assert rebuilt["version"] == 2, f"{label}: cache not upgraded"
        assert rebuilt["projectsDir"] == str(projects), f"{label}: projectsDir not refreshed"


# ─── SC-CHAOS-002 — broken symlinks ──────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX symlinks")
def test_broken_symlinks_do_not_stop_the_rest_of_a_migration(tmp_path, monkeypatch):
    """Healthy items still migrate when broken symlinks sit beside them.

    Prevents: one dangling link aborting the whole `vault migrate`, and the
    inverse — a "helpful" cleanup deleting the broken links instead of
    reporting them (US-VLT01 AC2/AC3).
    """
    # TC-CHAOS-008
    _isolate(tmp_path, monkeypatch)
    claude_dir = tmp_path / "home" / ".claude"
    vault = tmp_path / "vault"
    (claude_dir / "skills").mkdir(parents=True, exist_ok=True)
    (claude_dir / "commands").mkdir(parents=True, exist_ok=True)

    for name in ("ok-skill-a", "ok-skill-b"):
        _skill_dir(claude_dir / "skills" / name)
    for name in ("ok-cmd-a.md", "ok-cmd-b.md"):
        (claude_dir / "commands" / name).write_text("---\ndescription: d\n---\n")

    broken_skill = claude_dir / "skills" / "gone-skill"
    os.symlink(tmp_path / "nowhere" / "gone-skill", broken_skill)
    broken_cmd = claude_dir / "commands" / "gone-cmd.md"
    os.symlink(tmp_path / "nowhere" / "gone-cmd.md", broken_cmd)

    _skill_dir(claude_dir / "skills" / "dup-skill")
    _skill_dir(vault / "skills" / "dup-skill")   # already in the vault → skipped

    result = axt.migrate_to_vault(claude_dir, vault)

    assert len(result.moved) == 4, f"moved={result.moved}"
    assert len(result.broken) == 2, f"broken={result.broken}"
    assert len(result.skipped) == 1, f"skipped={result.skipped}"
    assert result.errors == ()
    assert broken_skill.is_symlink() and broken_cmd.is_symlink(), (
        "broken symlinks were deleted instead of reported")
    for name in ("ok-skill-a", "ok-skill-b"):
        assert (vault / "skills" / name / "SKILL.md").is_file()
    for name in ("ok-cmd-a.md", "ok-cmd-b.md"):
        assert (vault / "commands" / name).is_file()
    assert (vault / "skills" / "dup-skill" / "SKILL.md").is_file()

    # Fixed: this asserted migrate leaves a symlink at the original path. It
    # does not, by design — vault is storage and `link-global` is the separate
    # activation step (leaving a symlink is `import`'s job, not migrate's). See
    # tests/doc/SPEC_DECISIONS.md SD-002; the story was wrong, not the code.
    for name in ("ok-skill-a", "ok-skill-b"):
        assert not (claude_dir / "skills" / name).exists(), (
            f"{name} should have been moved out of ~/.claude, not copied")


# ─── SC-CHAOS-003 — missing ~/.claude ────────────────────────────────────────


READ_COMMANDS = (
    ["plugin", "list"], ["skill", "list"], ["mcp", "list"], ["hook", "list"],
    ["market", "list"], ["vault", "list"], ["usage", "today"], ["context"],
    ["project", "status"], ["update"],
)


def _empty_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "emptyhome"
    home.mkdir()
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=home / ".claude",
        claude_config=home / ".claude.json",
        settings=home / ".claude" / "settings.json",
        known_marketplaces=home / ".claude" / "plugins" / "known_marketplaces.json",
        installed_plugins=home / ".claude" / "plugins" / "installed_plugins.json",
        marketplaces=home / ".claude" / "plugins" / "marketplaces",
        skills=home / ".claude" / "skills",
        projects=home / ".claude" / "projects",
        vault=home / ".axt" / "vault",
        vault_skills=home / ".axt" / "vault" / "skills",
        vault_commands=home / ".axt" / "vault" / "commands",
        vault_agents=home / ".axt" / "vault" / "agents",
    ))
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", home / ".config" / "axt")
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", home / ".config" / "axt" / "config.json")
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", home / ".config" / "axt" / "cache")
    proj = tmp_path / "emptyproj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    # `claude --version` is a real external binary whose presence varies by
    # machine; stub only that so the sweep stays deterministic. `git status`
    # is deliberately left real — the not-a-repo path is part of the scenario.
    monkeypatch.setattr("axt.core.get_claude_version", lambda: "test")
    monkeypatch.setattr("axt.update._claude_version", lambda: None)
    return home


def test_every_read_command_survives_a_missing_claude_dir(tmp_path, monkeypatch, capsys):
    """All ten read-only commands survive with an empty-state message.

    Prevents: a brand-new user's very first `axt <anything>` ending in a
    traceback, because `~/.claude` does not exist yet (US-SYS05 AC3).
    """
    # TC-CHAOS-009
    _empty_home(tmp_path, monkeypatch)
    failures = []
    for argv in READ_COMMANDS:
        try:
            rc = axt.main(list(argv))
        except BaseException as exc:  # noqa: BLE001 — recorded, then reported below
            capsys.readouterr()
            failures.append(f"{' '.join(argv)}: raised {type(exc).__name__}: {exc}")
            continue
        cap = capsys.readouterr()
        # Fixed: this required exit 0 from every command. `project status`
        # deliberately exits 1 for "this project has no .axt-profile.json yet"
        # — a distinct state a script can branch on, printed with the exact
        # next step. That is surviving, which is what this test is about; the
        # blanket exit-0 rule was the wrong way to express it.
        allowed_rc = (0, 1) if argv == ["project", "status"] else (0,)
        if rc not in allowed_rc:
            failures.append(f"{' '.join(argv)}: exit {rc} (stderr={cap.err.strip()!r})")
        if "Traceback" in cap.err:
            failures.append(f"{' '.join(argv)}: traceback on stderr")
        if not cap.out.strip():
            failures.append(f"{' '.join(argv)}: printed nothing — no empty-state guidance")
    assert failures == [], "\n".join(failures)


def test_read_commands_create_nothing_on_disk(tmp_path, monkeypatch, capsys):
    """Read-only commands must leave the filesystem exactly as they found it.

    Prevents: a query silently materializing `~/.claude` or a cache dir, which
    turns "just looking" into a state change — and makes the missing-dir path
    untestable after the first run (US-SYS05 AC3).
    """
    # TC-CHAOS-010
    home = _empty_home(tmp_path, monkeypatch)

    def snapshot():
        out = set()
        for dirpath, dirnames, filenames in os.walk(home, followlinks=False):
            for n in list(dirnames) + list(filenames):
                out.add(os.path.join(dirpath, n))
        return out

    before = snapshot()
    for argv in READ_COMMANDS:
        axt.main(list(argv))
        capsys.readouterr()
    after = snapshot()

    assert after - before == set(), (
        f"read commands created: {sorted(after - before)}")


# ─── SC-CHAOS-004 — permission denied ────────────────────────────────────────


def test_unreadable_vault_item_does_not_hide_the_others(tmp_path, monkeypatch, capsys):
    """One 0o000 vault directory must not empty the whole listing.

    Prevents: a single unreadable item aborting enumeration, which makes the
    other extensions invisible and un-manageable. The spec leaves it open
    whether the bad item is skipped or shown without a description — what must
    hold is that the rest survive (US-SYS05 AC4).
    """
    # TC-CHAOS-011
    _require_non_root()
    _isolate(tmp_path, monkeypatch)
    vault = tmp_path / "vault"
    dirs = [_skill_dir(vault / "skills" / f"sk{i}") for i in range(5)]
    locked = dirs[2]
    os.chmod(locked, 0o000)
    try:
        items = axt.list_vault_items(vault)
        assert len(items) in (4, 5), f"{len(items)} items survived the locked entry"
        assert axt.main(["vault", "list"]) == 0
        capsys.readouterr()
    finally:
        os.chmod(locked, 0o755)


def test_unreadable_files_do_not_abort_context_collection(tmp_path, monkeypatch, capsys):
    """0o000 files inside skills/commands must not zero the context analysis.

    Prevents: one file with the wrong mode (a common outcome of a bad restore or
    a shared checkout) making the whole Context tab report nothing, which reads
    as "your context is free" (US-SYS05 AC4).
    """
    # TC-CHAOS-012
    _require_non_root()
    home = _isolate(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    monkeypatch.chdir(proj)
    for i in range(10):
        _skill_dir(proj / ".claude" / "skills" / f"sk{i}")
    (proj / ".claude" / "commands").mkdir()
    for i in range(5):
        (proj / ".claude" / "commands" / f"c{i}.md").write_text("---\ndescription: d\n---\n")
    monkeypatch.setattr("axt.core.get_git_status", lambda p: "")
    monkeypatch.setattr("axt.core.get_claude_version", lambda: "test")

    locked_skill = proj / ".claude" / "skills" / "sk3" / "SKILL.md"
    locked_cmd = proj / ".claude" / "commands" / "c1.md"
    os.chmod(locked_skill, 0o000)
    os.chmod(locked_cmd, 0o000)
    try:
        sources = axt.collect_context_sources(
            home_dir=home, project_dir=proj,
            installed_plugins_path=home / ".claude" / "plugins" / "installed_plugins.json")
        by_cat: dict[str, int] = {}
        for s in sources:
            by_cat[s.category] = by_cat.get(s.category, 0) + 1
        assert by_cat.get("skills", 0) >= 9, f"skills collapsed to {by_cat.get('skills', 0)}"
        assert by_cat.get("commands", 0) >= 4, f"commands collapsed to {by_cat.get('commands', 0)}"
        assert axt.main(["context"]) == 0
        capsys.readouterr()
    finally:
        os.chmod(locked_skill, 0o644)
        os.chmod(locked_cmd, 0o644)


def test_unreadable_project_dir_does_not_abort_the_cross_project_scan(tmp_path, monkeypatch):
    """One 0o000 project directory must not empty the usage index.

    Prevents: a single unreadable project (another user's checkout, a stale
    mount) blanking the Vault `Used` column, which is the evidence the user
    prunes extensions from (US-SYS05 AC4).
    """
    # TC-CHAOS-013
    _require_non_root()
    _isolate(tmp_path, monkeypatch)
    vault = tmp_path / "vault"
    names = [_skill_dir(vault / "skills" / f"vs{i}").name for i in range(5)]
    root = tmp_path / "code"
    root.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(exist_ok=True)
    made = []
    for i in range(10):
        p = root / f"pj{i}"
        p.mkdir()
        axt.write_profile(p, axt.AxtProfile(skills=tuple(names)))
        (projects_dir / str(p).replace("/", "-")).mkdir(exist_ok=True)
        made.append(p)

    os.chmod(made[4], 0o000)
    try:
        for mode in ("default", "full"):
            index = axt.scan_project_usage(projects_dir, vault, mode=mode)
            assert len(index) == 5, f"{mode}: index has {len(index)} entries, expected 5"
            reachable = {p.path for u in index.values() for p in u.projects}
            assert len(reachable) >= 9, f"{mode}: only {len(reachable)} projects were scanned"
    finally:
        os.chmod(made[4], 0o755)


# ─── SC-CHAOS-005 — write failures ───────────────────────────────────────────


def test_enospc_during_write_preserves_the_original_file(tmp_path, monkeypatch):
    """A disk-full serialization failure surfaces and leaves the original intact.

    Prevents: reporting a settings save as successful when it never landed —
    the user believes their configuration is stored and loses it on the next
    read (US-SYS04 AC3).
    """
    # TC-CHAOS-014
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"keep": "original"}))
    axt.write_json_atomic(target, {"keep": "original"})   # produce a good .bak

    def boom(*a, **kw):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("axt.core.json.dump", boom)

    with pytest.raises(OSError) as exc:
        axt.write_json_atomic(target, {"new": "data"})
    assert exc.value.errno == errno.ENOSPC

    assert json.loads(target.read_text()) == {"keep": "original"}
    assert list(tmp_path.glob(".tmp-*.json")) == []
    bak = target.with_suffix(".json.bak")
    if bak.exists():
        assert json.loads(bak.read_text()) == {"keep": "original"}


def test_failed_rename_leaves_no_temp_file_and_the_write_can_be_retried(tmp_path):
    """A failing `os.replace` cleans up its temp file and the retry succeeds.

    Prevents: `.tmp-*.json` droppings accumulating in the user's config dir
    every time a write fails, and a transient failure leaving the writer in a
    state it cannot recover from (US-SYS04 AC3).
    """
    # TC-CHAOS-015
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"keep": "original"}))

    with pytest.MonkeyPatch.context() as mp:
        def boom(*a, **kw):
            raise OSError(errno.EROFS, "Read-only file system")
        mp.setattr("axt.core.os.replace", boom)
        with pytest.raises(OSError) as exc:
            axt.write_json_atomic(target, {"new": "data"})
        assert exc.value.errno == errno.EROFS

    assert json.loads(target.read_text()) == {"keep": "original"}
    assert list(tmp_path.glob(".tmp-*.json")) == []

    axt.write_json_atomic(target, {"new": "data"})
    assert json.loads(target.read_text()) == {"new": "data"}


def test_unserializable_payload_does_not_destroy_the_original(tmp_path):
    """A TypeError mid-serialization leaves the original file and no temp files.

    Prevents: the cleanup path being wrong for failures that happen *after* the
    temp file is open and partially written — a different code path from the
    two I/O failures above (US-SYS04 AC3).
    """
    # TC-CHAOS-016
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"keep": "original"}))

    with pytest.raises(TypeError):
        axt.write_json_atomic(target, {"x": object()})

    assert json.loads(target.read_text()) == {"keep": "original"}
    assert list(tmp_path.glob(".tmp-*.json")) == []


# ─── SC-CHAOS-006 / 007 — external git ───────────────────────────────────────


def _seed_three_markets(tmp_path: Path, km: Path) -> None:
    local_dir = tmp_path / "localmk"
    local_dir.mkdir()
    entries = {}
    for name in ("gh-market", "gh-other"):
        install = tmp_path / "mk" / name
        (install / ".git").mkdir(parents=True)
        entries[name] = {"source": {"source": "github", "repo": f"o/{name}"},
                         "installLocation": str(install), "lastUpdated": ""}
    entries["dir-market"] = {"source": {"source": "directory", "path": str(local_dir)},
                             "installLocation": str(local_dir), "lastUpdated": ""}
    km.parent.mkdir(parents=True, exist_ok=True)
    km.write_text(json.dumps(entries))


def test_market_list_still_lists_everything_when_git_is_absent(tmp_path, monkeypatch, capsys):
    """With no git binary, `market list` exits 0 and shows all three markets.

    Prevents: a missing git turning an inventory command into a failure, and a
    git-independent `dir:` market losing its version because an unrelated
    github market could not be probed (US-MKT03 AC2, US-SYS06 AC2).
    """
    # TC-CHAOS-017
    home = _isolate(tmp_path, monkeypatch)
    km = home / ".claude" / "plugins" / "known_marketplaces.json"
    _seed_three_markets(tmp_path, km)

    def no_git(*a, **kw):
        raise FileNotFoundError(2, "No such file or directory", "git")

    monkeypatch.setattr("axt.core.subprocess.run", no_git)

    rc = axt.main(["market", "list"])
    cap = capsys.readouterr()

    assert rc == 0
    for name in ("gh-market", "gh-other", "dir-market"):
        assert name in cap.out, f"{name} missing from the listing"
    assert "Traceback" not in cap.err
    assert "local" in cap.out, "the directory market lost its version to an unrelated git failure"


def test_dirty_tree_hard_syncs_and_a_failed_sync_leaves_the_registry_untouched(tmp_path, monkeypatch):
    """Sync realigns a dirty install to upstream; a failed sync changes nothing.

    Per SPEC_DECISIONS SD-001 the install dir is a managed cache, so uncommitted
    edits there are updater artifacts and are discarded. The new ground this
    covers is the failure path: a sync that dies mid-way must not bump
    `lastUpdated` or touch the working tree, or the next run would believe it is
    current (US-MKT05 AC1/AC2/AC3).
    """
    # TC-CHAOS-018
    _isolate(tmp_path, monkeypatch)
    km = tmp_path / "km.json"
    origin, install = _seed_git_marketplace(tmp_path, km)

    (origin / "f.txt").write_text("v2\n")
    _git("git", "commit", "-q", "-am", "v2", cwd=origin)
    (install / "f.txt").write_text("overwritten-in-place\n")

    result = axt.sync_marketplace(km, "x")

    assert result.updated is True
    assert result.before != result.after
    assert (install / "f.txt").read_text() == "v2\n"
    assert json.loads(km.read_text())["x"]["lastUpdated"] != ""

    # Control: a failing fetch must leave both the tree and the registry alone.
    (origin / "f.txt").write_text("v3\n")
    _git("git", "commit", "-q", "-am", "v3", cwd=origin)
    (install / "f.txt").write_text("dirty-again\n")
    km_before = km.read_bytes()
    head_before = subprocess.run(["git", "-C", str(install), "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout

    real_git = axt.core._git

    def flaky(args, cwd=None):
        if "fetch" in args:
            return (128, "", "fatal: Could not resolve host: github.com")
        return real_git(args, cwd)

    monkeypatch.setattr("axt.core._git", flaky)
    with pytest.raises(RuntimeError, match="git fetch failed"):
        axt.sync_marketplace(km, "x")

    assert (install / "f.txt").read_text() == "dirty-again\n"
    assert km.read_bytes() == km_before, "a failed sync mutated known_marketplaces.json"
    head_after = subprocess.run(["git", "-C", str(install), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout
    assert head_after == head_before


def test_market_sync_without_git_fails_cleanly_and_spares_dir_markets(tmp_path, monkeypatch, capsys):
    """No git binary: a git market's sync exits 1 cleanly, a dir market's succeeds.

    Prevents: a missing external binary surfacing as a traceback instead of one
    diagnostic line, a failed sync corrupting the registry, and git-free
    `dir:` markets being blocked by a git problem that does not concern them
    (US-SYS06 AC2, US-MKT05 AC3/AC4).
    """
    # TC-CHAOS-019
    home = _isolate(tmp_path, monkeypatch)
    km = home / ".claude" / "plugins" / "known_marketplaces.json"
    _seed_three_markets(tmp_path, km)

    def no_git(*a, **kw):
        raise FileNotFoundError(2, "No such file or directory", "git")

    monkeypatch.setattr("axt.core.subprocess.run", no_git)

    km_before = km.read_bytes()
    rc = axt.main(["market", "sync", "gh-market"])
    cap = capsys.readouterr()

    assert rc == 1
    assert "✗" in cap.err
    assert "git" in cap.err.lower()
    assert "Traceback" not in cap.err
    assert km.read_bytes() == km_before, "a failed sync mutated the registry"

    rc_dir = axt.main(["market", "sync", "dir-market"])
    capsys.readouterr()
    assert rc_dir == 0, "a directory market needs no git and must still sync"


def test_fetch_failure_leaves_the_working_tree_and_registry_pristine(tmp_path, monkeypatch):
    """A network failure during fetch changes nothing on disk.

    Prevents: a partially-applied sync — the failure path must abort before any
    mutation, otherwise a dropped connection can leave the install dir at a
    half-applied revision while the registry claims success (US-MKT02 AC4,
    US-SYS06 AC1).
    """
    # TC-CHAOS-020
    _isolate(tmp_path, monkeypatch)
    km = tmp_path / "km.json"
    _origin, install = _seed_git_marketplace(tmp_path, km)

    def snapshot():
        out = {}
        for p in sorted(install.rglob("*")):
            if p.is_file() and ".git" not in p.parts:
                out[str(p.relative_to(install))] = p.read_bytes()
        return out

    files_before = snapshot()
    km_before = km.read_bytes()
    head_before = subprocess.run(["git", "-C", str(install), "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout

    real_git = axt.core._git

    def flaky(args, cwd=None):
        if "fetch" in args:
            return (128, "", "fatal: Could not resolve host: github.com")
        return real_git(args, cwd)

    monkeypatch.setattr("axt.core._git", flaky)

    with pytest.raises(RuntimeError) as exc:
        axt.sync_marketplace(km, "x")

    assert "git fetch failed" in str(exc.value)
    assert "Could not resolve host" in str(exc.value), "the underlying git stderr was swallowed"
    assert snapshot() == files_before
    assert km.read_bytes() == km_before
    head_after = subprocess.run(["git", "-C", str(install), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout
    assert head_after == head_before


# ─── SC-CHAOS-008 — missing `claude` binary ──────────────────────────────────


def _stub_updaters(monkeypatch):
    """Two healthy tier-1 updaters plus the real claude-code tier-3 one."""
    US = axt.update.UpdateStatus
    mk = axt.update.Updater(
        "marketplace", 1,
        lambda: [US("marketplace", "mk1", 1, "aaa1111", "bbb2222", True)], None)
    pl = axt.update.Updater(
        "plugin", 1,
        lambda: [US("plugin", "p1@mk1", 1, "1.0.0", "1.0.0", False, note="up to date")], None)
    monkeypatch.setattr("axt.update.UPDATERS", [mk, pl, axt.update.claude_code_updater])


def test_missing_claude_binary_still_produces_a_complete_dry_run_report(tmp_path, monkeypatch, capsys):
    """`claude` absent: the report still covers both tier-1 items and summarizes.

    Prevents: one tier's failure truncating the report so the user never learns
    a marketplace update is waiting. A dry run must also change nothing
    (US-UPD01 AC1/AC3, US-UPD02 AC2).
    """
    # TC-CHAOS-021
    _isolate(tmp_path, monkeypatch)
    _stub_updaters(monkeypatch)
    monkeypatch.setattr("axt.update._claude_version", lambda: None)

    rc = axt.main(["update"])
    cap = capsys.readouterr()

    assert rc == 0
    assert "claude-code" in cap.out
    assert "not found" in cap.out.lower(), "the missing binary was not reported"
    assert "mk1" in cap.out and "p1@mk1" in cap.out, "a tier-1 item vanished from the report"
    assert "updatable" in cap.out, "the summary line is missing"
    assert "Traceback" not in cap.err


def test_missing_claude_binary_apply_reports_failure_and_json_stays_machine_readable(
        tmp_path, monkeypatch, capsys):
    """`--apply` on a missing binary exits 1; `--json` never prompts and parses.

    Prevents: an unattended run reporting success for an update that could not
    happen, and `--json` blocking on an interactive confirm or emitting ANSI
    that breaks the consumer's parser (US-UPD03 AC1/AC2/AC3).
    """
    # TC-CHAOS-022
    _isolate(tmp_path, monkeypatch)
    _stub_updaters(monkeypatch)
    monkeypatch.setattr("axt.update._claude_version", lambda: None)
    monkeypatch.setattr("axt.update._run_claude_update",
                        lambda: (127, "", "No such file or directory: 'claude'"))

    prompts = []

    def no_prompt(*a, **kw):
        prompts.append(a)
        raise AssertionError("an interactive prompt was raised in a non-interactive run")

    monkeypatch.setattr("builtins.input", no_prompt)

    rc_apply = axt.main(["update", "claude-code", "--apply", "-y"])
    cap_apply = capsys.readouterr()
    assert "Traceback" not in cap_apply.err
    assert "claude" in (cap_apply.out + cap_apply.err).lower()
    assert rc_apply == 1, "a failed apply reported success"

    rc_json = axt.main(["update", "--json"])
    json_out = capsys.readouterr().out
    payload = json.loads(json_out)

    assert rc_json == 0
    assert prompts == []
    assert "\x1b[" not in json_out, "ANSI colour leaked into --json output"
    entry = next((e for e in payload if e.get("item_type") == "claude-code"), None)
    assert entry is not None, "claude-code has no machine-readable entry"
    assert entry.get("error"), "the failure is not represented in a machine-readable field"


# ─── SC-CHAOS-009 — background worker faults ─────────────────────────────────


def _raise(*a, **kw):
    raise RuntimeError("injected")


def _inject_worker_failures(monkeypatch):
    monkeypatch.setattr("axt.tui.tabs.scan_project_usage", _raise)
    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", _raise)
    monkeypatch.setattr("axt.tui.tabs.check_all_updates", _raise)
    monkeypatch.setattr("axt.tui.tabs.analyze_context", lambda **kw: None)
    monkeypatch.setattr("axt.tui.tabs.detect_current_model", lambda *a, **kw: "claude-sonnet-5")


def _capture_thread_exceptions(monkeypatch):
    """Record exceptions that escape a thread — the default hook only prints
    them to stderr, which lets a broken worker pass silently."""
    escaped: list = []
    monkeypatch.setattr(threading, "excepthook", lambda args: escaped.append(args))
    return escaped


def test_worker_exceptions_never_pin_the_loading_flags_true(tmp_path, monkeypatch):
    """All three workers reset their flag even when their job raises.

    Prevents: a stuck flag making `_has_background_work` permanently true, which
    pins the TUI to a 100ms repaint loop that burns CPU forever, and a raising
    worker taking the process down with it (US-UPD05 AC4).
    """
    # TC-CHAOS-023
    _isolate(tmp_path, monkeypatch)
    _inject_worker_failures(monkeypatch)
    escaped = _capture_thread_exceptions(monkeypatch)

    state = axt.TuiState()
    tabs._kick_vault_scan(state)
    state.vault_scan_thread.join(timeout=5)
    tabs._kick_usage_reload(state)
    state.usage_load_thread.join(timeout=5)
    REAL_KICK_UPDATE_CHECK(state, force=True)
    state.update_check_thread.join(timeout=5)

    for attr in ("vault_scan_thread", "usage_load_thread", "update_check_thread"):
        assert not getattr(state, attr).is_alive(), f"{attr} is still running"
    assert state.vault_scan_loading is False
    assert state.usage_loading is False
    assert state.update_check_loading is False

    # Control: the injection really fired (no result was produced), and nothing
    # other than the injected error escaped a thread.
    assert state.vault_usage_index == {}
    assert state.usage_entries is None
    assert state.update_statuses == {}
    for args in escaped:
        assert isinstance(args.exc_value, RuntimeError) and "injected" in str(args.exc_value), (
            f"an unexpected exception escaped a worker thread: {args.exc_value!r}")

    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = []
    axt._render_frame(_make_stdscr(30, 140), state)
    assert axt.handle_extensions_input(state, ord("]")) is not None, (
        "input handling stopped working after the worker failures")


def test_worker_failures_are_visible_to_the_user(tmp_path, monkeypatch):
    """A failed background job must show up somewhere on screen.

    Prevents: silent failure — the worst diagnostic outcome. With no signal the
    user reads an empty Used column or a missing update marker as "nothing to
    do" and never learns the scan died (US-UPD05 AC4).
    """
    # TC-CHAOS-024
    _isolate(tmp_path, monkeypatch)
    _inject_worker_failures(monkeypatch)
    _capture_thread_exceptions(monkeypatch)

    state = axt.TuiState()
    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = [
        axt.SkillInfo(name="alpha", path=str(tmp_path / "alpha"),
                      is_symlink=False, source="user", version="1.0.0"),
    ]

    def failure_signal(st, screen) -> str:
        flat = _flat(screen)
        bits = []
        if st.status and st.status_kind == "error":
            bits.append(f"status={st.status!r}")
        if "✗" in flat:
            bits.append("✗ on screen")
        if any(tok in flat.lower() for tok in ("failed", "error", "unavailable")):
            bits.append("failure wording on screen")
        if "!" in flat:
            bits.append("! marker on screen")
        return ", ".join(bits)

    missing = []
    for label, kick, thread_attr in (
        ("update check", lambda s: REAL_KICK_UPDATE_CHECK(s, force=True), "update_check_thread"),
        ("vault scan", tabs._kick_vault_scan, "vault_scan_thread"),
        ("usage load", tabs._kick_usage_reload, "usage_load_thread"),
    ):
        kick(state)
        getattr(state, thread_attr).join(timeout=5)
        scr = _make_stdscr(30, 140)
        axt._render_frame(scr, state)
        if not failure_signal(state, scr):
            missing.append(label)

    assert missing == [], (
        f"these worker failures left no trace on screen: {missing} — "
        "the user cannot tell a dead worker from an empty result")


# ─── SC-CHAOS-010 — resize ───────────────────────────────────────────────────


def test_resize_sequence_never_raises_and_restores_the_selection(tmp_path, monkeypatch):
    """Shrinking to unusable and back keeps the selection and stays in bounds.

    Prevents: a resize crashing the dashboard, drawing past the new bounds, or
    losing the user's place in a long list when a split pane is resized
    (US-TUI10 AC1/AC2).
    """
    # TC-CHAOS-025
    _isolate(tmp_path, monkeypatch)
    rows = [axt.SkillInfo(name=f"skill-{i:03d}", path=str(tmp_path / f"s{i}"),
                          is_symlink=False, source="user", version="1.0.0")
            for i in range(200)]
    state = axt.TuiState()
    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = rows
    state.ext_selected["skills"] = 150
    state.update_statuses = {}

    size = {"hw": (30, 140)}
    scr = MagicMock()
    scr.getmaxyx.side_effect = lambda: size["hw"]
    scr.calls = []
    scr.addnstr.side_effect = lambda *a: scr.calls.append(a)

    frames = []
    for hw in ((30, 140), (10, 40), (4, 20), (30, 140)):
        size["hw"] = hw
        scr.calls = []
        axt._render_frame(scr, state)
        frames.append((hw, list(scr.calls)))
        h, w = hw
        for y, x, _text, max_w, *_rest in scr.calls:
            assert 0 <= y < h and 0 <= x < w, f"{hw}: drew outside at ({y},{x})"
            assert x + max_w <= w, f"{hw}: draw runs past the edge x={x} w={max_w}"

    tiny_calls = frames[2][1]
    tiny_text = "".join(c[2] for c in tiny_calls if isinstance(c[2], str))
    assert "Terminal too small" in tiny_text
    assert len(tiny_calls) == 1, f"drew a table below the minimum size: {len(tiny_calls)} calls"

    assert state.ext_selected["skills"] == 150, "the selection was lost across the resize"
    final_text = "".join(c[2] for c in frames[3][1] if isinstance(c[2], str))
    assert "skill-150" in final_text, "the selected row is not inside the restored viewport"


def test_resize_during_search_input_preserves_the_query_buffer(tmp_path, monkeypatch):
    """A resize event must not be typed into the search box or reset it.

    Prevents: `KEY_RESIZE` leaking into the query as a character (or clearing
    it) when the terminal is resized mid-search — the user's half-typed filter
    silently changes meaning (US-TUI10 AC2, US-TUI04 AC1).

    The main loop's modal branch forwards only `KEY_RESIZE`; this pins the
    complementary invariant at the handler level, so the buffer survives even
    if that routing changes.
    """
    # TC-CHAOS-026
    _isolate(tmp_path, monkeypatch)
    rows = [axt.SkillInfo(name=f"data-{i:03d}", path=str(tmp_path / f"s{i}"),
                          is_symlink=False, source="user", version="1.0.0")
            for i in range(20)]
    state = axt.TuiState()
    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = rows
    state.update_statuses = {}

    axt.handle_extensions_input(state, ord("/"))
    for ch in "data":
        axt.handle_extensions_input(state, ord(ch))
    assert state.ext_searching is True
    assert state.ext_search["skills"] == "data"

    axt.handle_extensions_input(state, curses.KEY_RESIZE)

    assert state.ext_search["skills"] == "data", "the resize event landed in the query buffer"
    assert state.ext_searching is True, "the resize cancelled search-input mode"

    scr = _make_stdscr(24, 100)
    axt._render_frame(scr, state)
    flat = _flat(scr)
    assert "/search: data" in flat, "the search band did not redraw at the new size"
