"""Integration tests — two or more axt modules meeting on a real filesystem.

Layer contract (tests/doc/TEST_DEDUP_POLICY.md §2): every assertion here is
about the **resulting state on disk** (or the in-memory state a later read of
that disk produces). Exit codes and stdout shapes belong to `test_cli.py`;
curses rendering belongs to `test_tui.py`. A CLI entry point or a TUI key
handler is used here only as the *driver* that makes the modules interact.

Determinism: every test isolates `axt.PATHS`, `axt.HOME` and the cwd under
`tmp_path`. Nothing reads the developer's real `~/.claude`.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

import axt


# ─── shared helpers ──────────────────────────────────────────────────────────


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Drive the real CLI entry point, swallowing its console output.

    Output is captured so it does not pollute pytest's report; assertions in
    this file are about disk state, never about these strings.
    """
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = axt.main(argv)
    return code, out.getvalue(), err.getvalue()


def _fs_snapshot(root: Path) -> list[tuple]:
    """(relpath, mode, size, mtime_ns) for every entry under `root`.

    `lstat` + `followlinks=False` so a symlink is compared as a symlink and a
    dangling one does not raise.
    """
    entries: list[tuple] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            st = p.lstat()
            entries.append((os.path.relpath(p, root), st.st_mode, st.st_size, st.st_mtime_ns))
    return sorted(entries)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _assistant(session: str, model: str, ts: str, **tok) -> dict:
    return {
        "type": "assistant",
        "sessionId": session,
        "timestamp": ts,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": tok.get("input", 0),
                "output_tokens": tok.get("output", 0),
                "cache_creation_input_tokens": tok.get("cw", 0),
                "cache_read_input_tokens": tok.get("cr", 0),
            },
        },
    }


def _seed_vault_skill(vault: Path, name: str = "alpha") -> Path:
    d = vault / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: A skill\n---\nbody\n")
    return d


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-001 — vault ↔ .axt-profile.json ↔ project symlinks
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(sys.platform == "win32", reason="vault linking is POSIX-only")
def test_project_status_does_not_touch_the_filesystem(tmp_path: Path, monkeypatch):
    """`project status` is a read-only diff: it must not create the missing
    link nor rewrite the profile.

    US-PRJ04 AC1. Prevents: a "status" command that quietly repairs what it
    reports, so the user can never inspect a drifted project before deciding
    whether to sync it.
    """
    # TC-INT-004 (US-PRJ04 AC1)
    vault = tmp_path / "vault"
    _seed_vault_skill(vault, "alpha")
    _seed_vault_skill(vault, "beta")
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=vault, claude_dir=tmp_path / "claude"))
    monkeypatch.chdir(proj)

    # Profile declares two skills; only `alpha` is linked on disk.
    axt.write_profile(proj, axt.AxtProfile(skills=("alpha", "beta")))
    (proj / ".claude" / "skills").mkdir(parents=True)
    os.symlink(vault / "skills" / "alpha", proj / ".claude" / "skills" / "alpha")

    before = _fs_snapshot(proj)
    with redirect_stdout(io.StringIO()):
        axt.cli_project_status(argparse.Namespace())  # driver; its output is api-layer
    after = _fs_snapshot(proj)

    assert before == after
    assert not (proj / ".claude" / "skills" / "beta").exists()
    assert axt.read_profile(proj).skills == ("alpha", "beta")


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-002 — vault ↔ global link ↔ ~/.agents mirror
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(sys.platform == "win32", reason="vault linking is POSIX-only")
def test_cli_mirror_agents_round_trips_into_enriched_listing(tmp_path: Path, monkeypatch):
    """What `vault link-global --mirror-agents` writes is what
    `list_vault_items_with_project_state` reads back.

    US-VLT06 AC1 + US-VLT02 AC3. Prevents: the CLI writing the mirror to one
    path while the enrichment looks in another (e.g. `<agents>/alpha` vs
    `<agents>/skills/alpha`), which would leave the TUI's mirror column
    permanently `○` no matter how often the user toggles it.
    """
    # TC-INT-008 (US-VLT06 AC1, US-VLT02 AC3)
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    claude = home / ".claude"
    proj = tmp_path / "proj"
    proj.mkdir()
    item_path = _seed_vault_skill(vault, "alpha")
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=vault, vault_skills=vault / "skills",
        claude_dir=claude, skills=claude / "skills",
    ))
    monkeypatch.chdir(proj)

    assert _run_cli(["vault", "link-global", "skill", "alpha", "--mirror-agents"])[0] == 0

    def _alpha():
        items = axt.list_vault_items_with_project_state(
            vault, proj, global_dir=claude, agents_dir=home / ".agents")
        return next(i for i in items if i.name == "alpha")

    linked = _alpha()
    assert linked.is_global_linked is True
    assert linked.is_agents_linked is True
    # The mirror points at the vault content, not through ~/.claude/skills.
    assert os.path.realpath(home / ".agents" / "skills" / "alpha") == os.path.realpath(item_path)

    assert _run_cli(["vault", "unlink-global", "skill", "alpha", "--mirror-agents"])[0] == 0

    unlinked = _alpha()
    assert unlinked.is_global_linked is False
    assert unlinked.is_agents_linked is False
    # Both links are gone but the stored skill survives.
    assert not (claude / "skills" / "alpha").exists()
    assert not (home / ".agents" / "skills" / "alpha").is_symlink()
    assert (item_path / "SKILL.md").exists()


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-003 — migrate_to_vault
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need elevation")
def test_migrate_broken_set_matches_find_broken_links(tmp_path: Path):
    """`migrate_to_vault(...).broken` and `find_broken_links()` report the same
    dangling links, in the same `type:name` vocabulary, and neither deletes
    them.

    US-VLT01 AC2 + US-SYS05 AC2. Prevents: the two reporters drifting apart, so
    the empty-state hint says "3 broken links" while the migrate summary says
    0 (or vice versa) and the user cannot tell which to believe.
    """
    # TC-INT-011 (US-VLT01 AC2, US-SYS05 AC2)
    claude = tmp_path / "claude"
    vault = tmp_path / "vault"
    gone = tmp_path / "gone"
    for sub in ("skills", "commands", "agents"):
        (claude / sub).mkdir(parents=True)
    os.symlink(gone / "s", claude / "skills" / "dead-skill")
    os.symlink(gone / "c.md", claude / "commands" / "dead-cmd")
    os.symlink(gone / "a.md", claude / "agents" / "dead-agent")
    # One healthy item so the migration is not a pure no-op.
    real = claude / "skills" / "healthy"
    real.mkdir()
    (real / "SKILL.md").write_text("---\ndescription: ok\n---\n")

    found_before = axt.find_broken_links(claude)
    result = axt.migrate_to_vault(claude, vault)

    assert sorted(result.broken) == found_before
    assert set(result.broken) == {"skill:dead-skill", "command:dead-cmd", "agent:dead-agent"}
    assert result.moved == ("skill:healthy",)
    # Nothing was deleted: the three dangling links survive the migration and
    # the second scan agrees with the first.
    assert (claude / "skills" / "dead-skill").is_symlink()
    assert (claude / "commands" / "dead-cmd").is_symlink()
    assert (claude / "agents" / "dead-agent").is_symlink()
    assert axt.find_broken_links(claude) == found_before


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-004 — marketplace registry ↔ vault install
# ═════════════════════════════════════════════════════════════════════════════


def test_vault_install_resolves_source_through_registry_install_location(tmp_path: Path, monkeypatch):
    """A marketplace registered with `dir:` keeps its external path in the
    registry, and `vault install` must resolve the plugin source under THAT
    path.

    US-VLT04 AC3 + US-MKT01 AC1·AC3. Prevents: `dir:` marketplaces being
    second-class — install silently looking under `~/.claude/plugins/
    marketplaces/<name>/`, which for an external directory does not exist, so
    every install from a local marketplace fails.
    """
    # TC-INT-012 (US-VLT04 AC3, US-MKT01 AC1·AC3) — spec gap G-2.
    external = tmp_path / "external-mkt"
    (external / ".claude-plugin").mkdir(parents=True)
    (external / ".claude-plugin" / "marketplace.json").write_text(json.dumps({
        "name": "external-mkt",
        "plugins": [{"name": "pkg", "source": "./plugins/pkg"}],
    }))
    pkg = external / "plugins" / "pkg"
    (pkg / ".claude-plugin").mkdir(parents=True)
    (pkg / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "pkg", "version": "1.0.0",
    }))
    (pkg / "SKILL.md").write_text("---\nname: pkg\ndescription: from marketplace\n---\n")

    km = tmp_path / "km.json"
    vault = tmp_path / "vault"
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=km,
        marketplaces=tmp_path / "mks",          # empty — the trap
        vault=vault, vault_skills=vault / "skills",
        vault_commands=vault / "commands", vault_agents=vault / "agents",
    ))

    assert _run_cli(["market", "add", f"dir:{external}"])[0] == 0
    registry = json.loads(km.read_text())
    assert registry["external-mkt"]["installLocation"] == str(external)

    _run_cli(["vault", "install", "external-mkt", "pkg", "-t", "skill"])

    installed = axt.list_vault_items(vault)
    assert [(i.name, i.type) for i in installed] == [("pkg", "skill")]
    assert (vault / "skills" / "pkg" / "SKILL.md").exists()


def test_failed_vault_install_leaves_vault_unchanged(tmp_path: Path, monkeypatch):
    """An install against an unknown marketplace must not leave a partial
    directory behind.

    US-VLT04 AC1·AC2 + US-VLT02 AC2. Prevents: a half-copied extension
    appearing in `vault list` (and then in `vault link-global`) as if it were
    a working install.
    """
    # TC-INT-014 (US-VLT04 AC1·AC2, US-VLT02 AC2)
    vault = tmp_path / "vault"
    for sub in ("skills", "commands", "agents"):
        (vault / sub).mkdir(parents=True)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json",
        marketplaces=tmp_path / "mks",
        vault=vault, vault_skills=vault / "skills",
        vault_commands=vault / "commands", vault_agents=vault / "agents",
    ))

    before = _fs_snapshot(vault)
    _run_cli(["vault", "install", "no-such-mkt", "pkg", "-t", "skill"])
    after = _fs_snapshot(vault)

    assert before == after
    assert axt.list_vault_items(vault) == []


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-005 — plugin state fan-out
# ═════════════════════════════════════════════════════════════════════════════


def test_plugin_hook_toggle_is_refused_and_writes_nothing(tmp_path: Path, monkeypatch):
    """A plugin-provided hook shows up in `hook list` but refusing to toggle it
    must leave every settings file byte-identical.

    US-PLG06 AC2 + US-HK03 AC1·AC2. Prevents: a refusal that has already
    written `disabledHooks` into the user's settings — the message says "read
    only" while the file has grown an entry that shadows nothing.
    """
    # TC-INT-017 (US-PLG06 AC2, US-HK03 AC1·AC2)
    install = tmp_path / "plug"
    (install / "hooks").mkdir(parents=True)
    (install / "hooks" / "hooks.json").write_text(json.dumps({
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "plug-start"}]}]},
    }))
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({
        "version": 2,
        "plugins": {"pg@mk": [{"scope": "user", "installPath": str(install),
                               "version": "1.0.0", "installedAt": "", "lastUpdated": ""}]},
    }))
    user_settings = tmp_path / "settings.json"
    user_settings.write_text(json.dumps({
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "user-start"}]}]},
    }, indent=2) + "\n")
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    proj_settings = proj / ".claude" / "settings.json"
    proj_settings.write_text(json.dumps({"other": "untouched"}, indent=2) + "\n")

    hooks = axt.list_hooks(user_settings_path=user_settings, project_dir=proj,
                           installed_plugins_path=ip)
    plugin_hooks = [h for h in hooks if h.source == "plugin"]
    assert [h.command for h in plugin_hooks] == ["plug-start"]

    user_before = user_settings.read_bytes()
    proj_before = proj_settings.read_bytes()
    plugin_file_before = (install / "hooks" / "hooks.json").read_bytes()

    ok, msg = axt._toggle_hook_scope(plugin_hooks[0], "global")

    assert ok is False
    assert msg == "Plugin hooks are read-only (manage them in the plugin)"
    assert user_settings.read_bytes() == user_before
    assert proj_settings.read_bytes() == proj_before
    assert (install / "hooks" / "hooks.json").read_bytes() == plugin_file_before


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-006 — settings scope merge
# ═════════════════════════════════════════════════════════════════════════════


def _seed_three_scopes(tmp_path: Path, monkeypatch, *, glob, proj_val, local) -> Path:
    """global / project / project-local settings on disk. `None` omits the key."""
    home_settings = tmp_path / "global-settings.json"
    home_settings.write_text(json.dumps(
        {"enabledPlugins": {} if glob is None else {"pg@mk": glob}}))
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text(json.dumps(
        {"enabledPlugins": {} if proj_val is None else {"pg@mk": proj_val}}))
    if local is not None:
        (proj / ".claude" / "settings.local.json").write_text(json.dumps(
            {"enabledPlugins": {"pg@mk": local}}))
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({
        "version": 2,
        "plugins": {"pg@mk": [{"scope": "user", "installPath": str(tmp_path / "plug"),
                               "version": "1.0.0", "installedAt": "", "lastUpdated": ""}]},
    }))
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        settings=home_settings, installed_plugins=ip,
        known_marketplaces=tmp_path / "km.json"))
    monkeypatch.chdir(proj)
    return proj


def _resolved_active_count() -> int:
    """The activation verdict the product actually computes.

    `axt plugin list` is the only place in the codebase that merges the plugin
    scopes into a single enabled/disabled answer, so it is the driver here; the
    assertion is about the verdict, not the wording.
    """
    _, out, _ = _run_cli(["plugin", "list"])
    return int(out.rsplit("(", 1)[1].split(" active", 1)[0])


def test_project_explicit_false_overrides_global_true(tmp_path: Path, monkeypatch):
    """An explicit `false` in project settings turns the plugin off even when
    global says `true`.

    US-PLG01 AC2 ("project settings > global settings"). Prevents: a team
    disabling a plugin in the checked-in project settings and it staying on for
    everyone whose global settings enable it — precedence, not a logical OR.
    """
    # TC-INT-020 (US-PLG01 AC2) — spec gap G-4: axt/cli.py uses
    # `gv is True or pv is True`.
    _seed_three_scopes(tmp_path, monkeypatch, glob=True, proj_val=False, local=None)
    assert _resolved_active_count() == 0


def test_unset_plugin_flag_stays_distinct_from_explicit_false(tmp_path: Path, monkeypatch):
    """"Never configured" and "explicitly disabled" are different values across
    the two scope files.

    US-PLG01 AC3. Prevents: normalizing a missing key to `False`, which would
    collapse the `·` (unset) and `○` (off) markers into one and hide the fact
    that a scope has no opinion — the difference that makes precedence
    meaningful at all.
    """
    # TC-INT-021 (US-PLG01 AC3)
    proj = _seed_three_scopes(tmp_path, monkeypatch, glob=None, proj_val=None, local=None)

    glob_map = axt.read_enabled_plugins(axt.PATHS.settings)
    proj_map = axt.read_enabled_plugins(axt.project_settings_path())
    assert glob_map.get("pg@mk") is None
    assert proj_map.get("pg@mk") is None

    (proj / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"pg@mk": False}}))
    proj_map = axt.read_enabled_plugins(axt.project_settings_path())
    glob_map = axt.read_enabled_plugins(axt.PATHS.settings)
    assert proj_map.get("pg@mk") is False
    assert glob_map.get("pg@mk") is None
    assert proj_map.get("pg@mk") is not glob_map.get("pg@mk")


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-007 — usage JSONL → adapter → pricing → cache
# ═════════════════════════════════════════════════════════════════════════════


def test_jsonl_entry_becomes_cost_through_adapter_and_pricing(tmp_path: Path, monkeypatch):
    """One JSONL record on disk carries all four token types through the
    loader, the unified adapter and the pricing table into a dollar figure.

    US-USG06 AC1. Prevents: a token type being dropped at any hop — the cache
    encoder, `claude_to_unified`, or `TokenUsage` — which would understate the
    bill while every individual unit test still passed.
    """
    # TC-INT-022 (US-USG06 AC1)
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    projects = tmp_path / "claude_projects"
    _write_jsonl(projects / "projA" / "s1.jsonl", [
        _assistant("s1", "claude-sonnet-5", "2026-04-29T10:00:00Z",
                   input=1_000_000, output=1_000_000, cw=1_000_000, cr=1_000_000),
    ])

    entries = axt.load_all_claude_usage(projects)
    assert len(entries) == 1
    uni = axt.claude_to_unified(entries[0])
    cost = axt.calculate_cost(
        axt.TokenUsage(uni.input_tokens, uni.output_tokens,
                       uni.cache_write_tokens, uni.cache_read_tokens),
        uni.model,
    )
    # claude-sonnet-5: 3.00 + 15.00 + 3.75 + 0.30 per 1M tokens.
    assert cost == pytest.approx(22.05)


def test_v1_cache_is_discarded_and_the_rebuilt_cache_is_reusable(tmp_path: Path, monkeypatch):
    """A stale (v1) or corrupt cache on disk is rebuilt into a v2 cache that a
    *second* load can actually serve from.

    US-USG08 AC2·AC3. Prevents: a rebuild that writes a cache the decoder
    cannot read back — every `axt usage` invocation would silently re-parse
    every JSONL file, and the caching feature would be dead weight nobody
    notices.
    """
    # TC-INT-024 (US-USG08 AC2·AC3)
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    projects = tmp_path / "projects"
    jsonl = projects / "projA" / "s.jsonl"
    _write_jsonl(jsonl, [
        _assistant("real", "claude-sonnet-5", "2026-04-29T10:00:00Z", input=11, output=13),
    ])
    cache_file = tmp_path / "cache" / "claude-usage.json"
    cache_file.parent.mkdir(parents=True)

    def _seed_and_load(payload: str) -> list:
        cache_file.write_text(payload)
        return axt.load_all_claude_usage(projects)

    v1 = json.dumps({
        "version": 1,
        "lastUpdated": "2099-01-01T00:00:00.000Z",
        "projectsDir": str(projects),
        "files": {str(jsonl): {"mtime": 1.0, "entries": [
            {"model": "ghost", "sessionId": "ghost", "projectPath": "projA",
             "timestamp": "2020-01-01T00:00:00Z", "inputTokens": 999,
             "outputTokens": 0, "cacheCreationTokens": 0, "cacheReadTokens": 0},
        ]}},
    })
    from_v1 = _seed_and_load(v1)
    assert [(e.session_id, e.input_tokens) for e in from_v1] == [("real", 11)]
    rebuilt = json.loads(cache_file.read_text())
    assert rebuilt["version"] == 2
    assert rebuilt["models"] == ["claude-sonnet-5"] and rebuilt["sessions"] == ["real"]

    # The rebuilt cache serves the next load unchanged.
    served = axt.load_all_claude_usage(projects)
    assert [(e.session_id, e.input_tokens, e.output_tokens) for e in served] == [("real", 11, 13)]

    # A truncated cache takes the same recovery path.
    from_corrupt = _seed_and_load('{"version": 2, "files": {"a": ')
    assert [(e.session_id, e.input_tokens) for e in from_corrupt] == [("real", 11)]
    assert json.loads(cache_file.read_text())["version"] == 2


def test_unpriced_model_contributes_zero_and_is_reported(tmp_path: Path, monkeypatch):
    """A model missing from `pricing.json` adds $0 to the total and shows up in
    `find_unpriced_models`, starting from the JSONL on disk.

    US-USG06 AC2·AC3. Prevents: a new model shipping and every cost report
    quietly understating spend with nothing on screen to say why.
    """
    # TC-INT-025 (US-USG06 AC2·AC3)
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    projects = tmp_path / "projects"
    _write_jsonl(projects / "projA" / "s.jsonl", [
        _assistant("s1", "claude-unknown-9", "2026-04-29T10:00:00Z",
                   input=1_000_000, output=1_000_000),
        _assistant("s2", "claude-haiku-4-5", "2026-04-29T11:00:00Z",
                   input=1_000_000, output=1_000_000),
    ])

    entries = axt.load_all_claude_usage(projects)
    unified = [axt.claude_to_unified(e) for e in entries]
    total = sum(
        axt.calculate_cost(
            axt.TokenUsage(u.input_tokens, u.output_tokens,
                           u.cache_write_tokens, u.cache_read_tokens),
            u.model)
        for u in unified
    )

    # claude-haiku-4-5: 1.00 + 5.00 per 1M; the unknown model adds nothing.
    assert total == pytest.approx(6.0)
    assert axt.find_unpriced_models(unified) == {"claude-unknown-9": 1}


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-008 — context collection across 12 categories
# ═════════════════════════════════════════════════════════════════════════════


def _full_context_disk_state(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    """A disk state that produces at least one source in each of the twelve
    context categories."""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (home / ".claude").mkdir(parents=True)
    proj.mkdir()

    # claude-md
    (proj / "CLAUDE.md").write_text("Project guidance.\n")
    # settings (global x2 + project x2)
    (home / ".claude" / "settings.json").write_text(json.dumps({
        "enabledPlugins": {"pg@mk": True},
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]},
    }))
    (home / ".claude" / "settings.local.json").write_text("{}")
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text("{}")
    (proj / ".claude" / "settings.local.json").write_text("{}")
    # memory
    mem = home / ".claude" / "projects" / axt._encode_project_dir_name(proj) / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("# Memory index\n- a note\n")
    # skills / commands / agents
    (proj / ".claude" / "skills" / "sk").mkdir(parents=True)
    (proj / ".claude" / "skills" / "sk" / "SKILL.md").write_text(
        "---\nname: sk\ndescription: a skill\n---\nbody")
    (proj / ".claude" / "commands").mkdir(parents=True)
    (proj / ".claude" / "commands" / "cmd.md").write_text("---\ndescription: a command\n---\n")
    (proj / ".claude" / "agents").mkdir(parents=True)
    (proj / ".claude" / "agents" / "ag.md").write_text("---\ndescription: an agent\n---\n")
    # mcp-tools
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"srv": {"command": "run"}}}))
    # plugins (enabled above)
    install = tmp_path / "plug"
    (install / ".claude-plugin").mkdir(parents=True)
    (install / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "pg", "version": "1.0.0", "description": "A plugin"}))
    ip = tmp_path / "ip.json"
    ip.write_text(json.dumps({
        "version": 2,
        "plugins": {"pg@mk": [{"scope": "user", "installPath": str(install),
                               "version": "1.0.0", "installedAt": "", "lastUpdated": ""}]},
    }))

    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=home / ".claude",
        claude_config=home / ".claude.json",
        settings=home / ".claude" / "settings.json",
        installed_plugins=ip,
        skills=home / ".claude" / "skills",
    ))
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: " M a.py\n")
    return home, proj, ip


def test_one_disk_state_populates_all_twelve_context_categories(tmp_path: Path, monkeypatch):
    """Every category advertised in `CATEGORY_LABELS` is reachable from a
    single realistic disk state.

    US-CTX01 AC1. Prevents: a category that only ever appears in its own unit
    test — e.g. a collector block whose guard can never be satisfied alongside
    the others — leaving a silent hole in the token accounting.
    """
    # TC-INT-026 (US-CTX01 AC1)
    home, proj, ip = _full_context_disk_state(tmp_path, monkeypatch)

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj, installed_plugins_path=ip)

    assert {s.category for s in sources} == set(axt.CATEGORY_LABELS)
    fixed = {s.name: s for s in sources if s.category in ("system-prompt", "user-context")}
    assert fixed["System Prompt"].estimated_tokens == 4200
    assert fixed["User Context"].estimated_tokens == 280
    assert len([s for s in sources if s.category == "system-prompt"]) == 1
    assert len([s for s in sources if s.category == "user-context"]) == 1
    assert len([s for s in sources if s.category == "settings"]) == 4


@pytest.mark.skipif(sys.platform == "win32", reason=".agents layout is POSIX-only here")
def test_context_excludes_both_agents_trees_in_one_state(tmp_path: Path, monkeypatch):
    """With look-alike items in `.claude/` and `.agents/` side by side, only
    the `.claude/` ones are counted — for skills and agents alike.

    US-CTX03 AC1·AC2. Prevents: a fix to one of the two exclusion rules
    regressing the other, since both flow through the same
    `include_agents_dir=False` argument.
    """
    # TC-INT-027 (US-CTX03 AC1·AC2)
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (home / ".claude").mkdir(parents=True)
    (proj / ".claude" / "skills" / "keep").mkdir(parents=True)
    (proj / ".claude" / "skills" / "keep" / "SKILL.md").write_text(
        "---\nname: keep\ndescription: counted\n---\n")
    (proj / ".claude" / "agents").mkdir(parents=True)
    (proj / ".claude" / "agents" / "keep.md").write_text("---\ndescription: counted\n---\n")
    # Traps: home-level and project-level .agents trees.
    (home / ".agents" / "skills" / "trap").mkdir(parents=True)
    (home / ".agents" / "skills" / "trap" / "SKILL.md").write_text(
        "---\nname: trap\ndescription: not counted\n---\n")
    (proj / ".agents" / "agents").mkdir(parents=True)
    (proj / ".agents" / "agents" / "trap.md").write_text("---\ndescription: not counted\n---\n")
    (proj / ".agents" / "trap.md").write_text("---\ndescription: not counted\n---\n")

    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=home / ".claude",
        settings=home / ".claude" / "settings.json",
        installed_plugins=tmp_path / "ip.json",
        skills=home / ".claude" / "skills",
    ))
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    monkeypatch.chdir(proj)

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj, installed_plugins_path=tmp_path / "ip.json")

    assert {s.name for s in sources if s.category == "skills"} == {"keep"}
    assert {s.name for s in sources if s.category == "agents"} == {"keep"}
    assert all("trap" not in s.name for s in sources)


def test_disabling_an_mcp_server_removes_it_from_context_accounting(tmp_path: Path, monkeypatch):
    """`mcp disable` propagates all the way into the context analyzer: the
    server leaves `mcp-tools` and the total shrinks.

    US-CTX03 AC4 + US-MCP03 AC1. Prevents: the Context tab still charging the
    user for tool definitions they turned off — the optimization the tab exists
    to recommend would look like it did nothing.
    """
    # TC-INT-028 (US-CTX03 AC4, US-MCP03 AC1)
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (home / ".claude").mkdir(parents=True)
    proj.mkdir()
    (home / ".claude.json").write_text(json.dumps({
        "mcpServers": {"a": {"command": "run-a"}, "b": {"command": "run-b"}},
    }))
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=home / ".claude",
        claude_config=home / ".claude.json",
        settings=home / ".claude" / "settings.json",
        installed_plugins=tmp_path / "ip.json",
        skills=home / ".claude" / "skills",
    ))
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    monkeypatch.chdir(proj)

    def _collect():
        return axt.collect_context_sources(
            home_dir=home, project_dir=proj, installed_plugins_path=tmp_path / "ip.json")

    before = _collect()
    assert {s.name for s in before if s.category == "mcp-tools"} == {"a", "b"}
    total_before = sum(s.estimated_tokens for s in before)

    axt.set_mcp_disabled("b", disabled=True)

    after = _collect()
    assert {s.name for s in after if s.category == "mcp-tools"} == {"a"}
    assert sum(s.estimated_tokens for s in after) < total_before
    # The registration itself is untouched — only this project's switch moved.
    assert set(json.loads((home / ".claude.json").read_text())["mcpServers"]) == {"a", "b"}


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-009 — update orchestration
# ═════════════════════════════════════════════════════════════════════════════


def test_apply_updates_touches_tier1_only(tmp_path: Path, monkeypatch):
    """Applying the tier-1 targets advances the git-backed skill and leaves
    every tier-2 item byte-identical on disk.

    US-UPD02 AC1. Prevents: `--apply` reaching past its declared tier — an MCP
    config rewrite or a non-git command being clobbered is exactly the
    "don't touch what you can't safely update" contract users rely on.
    """
    # TC-INT-029 (US-UPD02 AC1)
    home = tmp_path / "home"
    claude = home / ".claude"
    (claude / "skills").mkdir(parents=True)
    (claude / "commands").mkdir(parents=True)

    # tier 1: a real git repo cloned from a local origin (no network).
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("git", "init", "-q", cwd=origin)
    _git("git", "config", "user.email", "t@t", cwd=origin)
    _git("git", "config", "user.name", "t", cwd=origin)
    (origin / "SKILL.md").write_text("---\nname: gs\ndescription: v1\n---\n")
    _git("git", "add", "SKILL.md", cwd=origin)
    _git("git", "commit", "-q", "-m", "v1", cwd=origin)

    work = tmp_path / "gitskill"
    _git("git", "clone", "-q", str(origin), str(work), cwd=tmp_path)
    os.symlink(work, claude / "skills" / "gs")

    (origin / "SKILL.md").write_text("---\nname: gs\ndescription: v2\n---\n")
    _git("git", "commit", "-q", "-am", "v2", cwd=origin)

    # tier 2: a plain (non-git) command file and an MCP registration.
    cmd = claude / "commands" / "c1.md"
    cmd.write_text("---\ndescription: plain command\n---\nbody\n")
    claude_json = home / ".claude.json"
    claude_json.write_text(json.dumps({"mcpServers": {"srv": {"command": "npx",
                                                              "args": ["pkg@1.2.3"]}}}))

    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=claude, claude_config=claude_json,
        settings=claude / "settings.json",
        installed_plugins=tmp_path / "ip.json",
        known_marketplaces=tmp_path / "km.json",
        skills=claude / "skills",
    ))
    # Never spawn the real `claude` binary (tier 3 is not under test here).
    monkeypatch.setattr("axt.update._claude_version", lambda: "9.9.9")

    cmd_before = (cmd.read_bytes(), cmd.lstat().st_mtime_ns)
    mcp_before = claude_json.read_bytes()

    statuses = axt.check_all_updates()
    by_key = {(s.item_type, s.name): s for s in statuses}
    assert by_key[("skill", "gs")].tier == 1
    assert by_key[("skill", "gs")].updatable is True
    assert by_key[("command", "c1")].tier == 2
    assert by_key[("mcp", "srv")].tier == 2
    assert by_key[("mcp", "srv")].updatable is False

    tier1 = [(s.item_type, s.name) for s in statuses if s.tier == 1 and s.updatable]
    results = axt.apply_updates(tier1)

    assert [r.updated for r in results] == [True]
    assert "v2" in (work / "SKILL.md").read_text()
    assert (cmd.read_bytes(), cmd.lstat().st_mtime_ns) == cmd_before
    assert claude_json.read_bytes() == mcp_before


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-010 — scan_project_usage modes
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need elevation")
def test_full_scan_is_default_scan_plus_exactly_the_plugin_entries(tmp_path: Path):
    """`mode="full"` is a strict superset of `mode="default"`, and the extra
    keys are precisely the plugin entries.

    US-VLT07 AC2. Prevents: the wider mode *replacing* rather than extending
    the default index — a past bug where re-scanning silently shrank the
    stored index and made the Vault tab's `Used` column read `─` for skills
    that were in use.
    """
    # TC-INT-034 (US-VLT07 AC2)
    vault = tmp_path / "vault"
    (vault / "skills" / "alpha").mkdir(parents=True)
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # A: declares alpha in its profile.
    a = tmp_path / "projA"
    a.mkdir()
    axt.write_profile(a, axt.AxtProfile(skills=("alpha",)))
    # B: links alpha into .claude/skills.
    b = tmp_path / "projB"
    (b / ".claude" / "skills").mkdir(parents=True)
    os.symlink(vault / "skills" / "alpha", b / ".claude" / "skills" / "alpha")
    # C: only enables a plugin.
    c = tmp_path / "projC"
    (c / ".claude").mkdir(parents=True)
    (c / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"pg@mk": True}}))
    for p in (a, b, c):
        (projects_dir / str(p).replace("/", "-")).mkdir()

    default_index = axt.scan_project_usage(projects_dir, vault, mode="default")
    full_index = axt.scan_project_usage(projects_dir, vault, mode="full")

    assert set(default_index) <= set(full_index)
    assert set(full_index) - set(default_index) == {"plugin:pg@mk"}
    assert axt.get_project_count(default_index, "skill", "alpha") == 2
    assert axt.get_project_count(default_index, "plugin", "pg@mk") == 0
    assert axt.get_project_count(full_index, "plugin", "pg@mk") == 1


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-011 — TUI key handler → core → disk
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(sys.platform == "win32", reason="vault linking is POSIX-only")
def test_discarded_pending_toggle_never_reaches_disk(tmp_path: Path, monkeypatch):
    """`p` then `Esc` leaves the project tree byte-identical — no symlink, no
    `.axt-profile.json`.

    US-VLT09 AC3. Prevents: `p` applying eagerly and `Esc` only clearing the
    UI marker, so a keystroke the user explicitly cancelled has already
    rewritten their project.
    """
    # TC-INT-037 (US-VLT09 AC3)
    vault = tmp_path / "vault"
    _seed_vault_skill(vault, "alpha")
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    monkeypatch.setattr("axt.HOME", tmp_path / "home")
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=vault, claude_dir=tmp_path / "claude"))
    monkeypatch.chdir(proj)

    state = axt.TuiState()
    state.stdscr_callbacks = None
    state.vault_items = axt.list_vault_items_with_project_state(
        vault, proj, global_dir=tmp_path / "claude")

    before = _fs_snapshot(proj)
    axt.handle_vault_input(state, ord("p"))
    assert state.vault_pending_project == {"alpha"}
    assert _fs_snapshot(proj) == before  # pending is UI-only

    msg = axt.handle_vault_input(state, 27)  # Esc

    assert msg == "Discarded pending changes"
    assert state.vault_pending_project == set()
    assert _fs_snapshot(proj) == before
    assert not (proj / ".axt-profile.json").exists()
    assert not (proj / ".claude" / "agents").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need elevation")
def test_agents_scope_toggle_links_and_unlinks_without_deleting_the_file(tmp_path: Path, monkeypatch):
    """`g` on an Agents row creates a global symlink and a second `g` removes
    it — the project's real `.md` survives both.

    US-LNK04 AC1·AC3 + US-LNK03 AC1. Prevents: the unlink branch following the
    symlink and deleting the user's authored agent, the single most destructive
    failure mode of a one-key toggle.
    """
    # TC-INT-038 (US-LNK04 AC1·AC3, US-LNK03 AC1)
    home = tmp_path / "home"
    claude = home / ".claude"
    (claude / "agents").mkdir(parents=True)
    proj = tmp_path / "proj"
    (proj / ".claude" / "agents").mkdir(parents=True)
    original = proj / ".claude" / "agents" / "a1.md"
    original.write_text("---\ndescription: mine\n---\nbody\n")

    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=claude, settings=claude / "settings.json",
        installed_plugins=tmp_path / "ip.json",
        vault=tmp_path / "vault", skills=claude / "skills",
    ))
    monkeypatch.chdir(proj)

    state = axt.TuiState()
    state.stdscr_callbacks = None
    state.ext_sub_tab = "agents"
    axt._ensure_subtab_loaded(state, "agents")
    state.ext_selected["agents"] = next(
        i for i, it in enumerate(axt._subtab_view(state, "agents")) if it.name == "a1")

    linked_msg = axt._act_scope_toggle(state, None, "agents", ord("g"))
    global_link = claude / "agents" / "a1.md"
    assert linked_msg == "Linked a1 (global)"
    assert global_link.is_symlink()
    assert os.path.realpath(global_link) == os.path.realpath(original)
    assert original.is_file() and not original.is_symlink()

    # Re-select the project row (the refresh added a second, global row).
    view = axt._subtab_view(state, "agents")
    state.ext_selected["agents"] = next(
        i for i, it in enumerate(view) if it.source == "project" and it.name == "a1")
    unlinked_msg = axt._act_scope_toggle(state, None, "agents", ord("g"))

    assert unlinked_msg == "Unlinked a1 (global)"
    assert not global_link.exists() and not global_link.is_symlink()
    assert original.is_file() and not original.is_symlink()
    assert original.read_text() == "---\ndescription: mine\n---\nbody\n"


@pytest.mark.skipif(sys.platform == "win32", reason="vault import is POSIX-only")
def test_import_of_project_item_records_it_in_the_profile(tmp_path: Path, monkeypatch):
    """`i` on a project-sourced command moves it into the vault, leaves a
    symlink behind AND records the name in `.axt-profile.json`.

    US-LNK05 AC1·AC2·AC3. Prevents: the profile entry being skipped, after
    which the very next `project sync` treats the fresh symlink as an orphan
    and unlinks the extension the user just imported.
    """
    # TC-INT-039 (US-LNK05 AC1·AC2·AC3)
    home = tmp_path / "home"
    claude = home / ".claude"
    vault = tmp_path / "vault"
    (claude / "commands").mkdir(parents=True)
    proj = tmp_path / "proj"
    (proj / ".claude" / "commands").mkdir(parents=True)
    src = proj / ".claude" / "commands" / "c1.md"
    src.write_text("---\ndescription: mine\n---\nbody\n")
    already = vault / "commands" / "vaulted.md"
    already.parent.mkdir(parents=True)
    already.write_text("---\ndescription: v\n---\n")

    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=claude, settings=claude / "settings.json",
        installed_plugins=tmp_path / "ip.json",
        vault=vault, vault_commands=vault / "commands", skills=claude / "skills",
    ))
    monkeypatch.chdir(proj)

    state = axt.TuiState()
    state.stdscr_callbacks = None
    state.ext_cache["commands"] = [axt.CommandInfo(
        name="c1", source="project", source_path=str(src), plugin=None,
        description="mine", content="", version="")]
    state.ext_selected["commands"] = 0
    msg = axt._act_import_to_vault(state, None, "commands", ord("i"))

    assert msg == "Imported 'c1.md' to vault"
    assert (vault / "commands" / "c1.md").is_file()
    assert not (vault / "commands" / "c1.md").is_symlink()
    assert src.is_symlink()
    assert os.path.realpath(src) == os.path.realpath(vault / "commands" / "c1.md")
    assert axt.read_profile(proj).commands == ("c1.md",)

    # A plugin-bundled row is refused and nothing on disk moves.
    plugin_src = tmp_path / "plug" / "commands" / "pc.md"
    plugin_src.parent.mkdir(parents=True)
    plugin_src.write_text("---\ndescription: p\n---\n")
    state.ext_cache["commands"] = [axt.CommandInfo(
        name="pg:pc", source="plugin", source_path=str(plugin_src), plugin="pg",
        description="p", content="", version="")]
    state.ext_selected["commands"] = 0
    assert axt._act_import_to_vault(state, None, "commands", ord("i")) == (
        "Plugin-bundled items stay with their plugin (not importable)")
    assert plugin_src.is_file() and not plugin_src.is_symlink()

    # An already-vaulted row is refused too.
    state.ext_cache["commands"] = [axt.CommandInfo(
        name="vaulted", source="vault", source_path=str(already), plugin=None,
        description="v", content="", version="")]
    state.ext_selected["commands"] = 0
    assert axt._act_import_to_vault(state, None, "commands", ord("i")) == "Already in vault"
    assert already.is_file() and not already.is_symlink()


# ═════════════════════════════════════════════════════════════════════════════
# SC-INT-012 — context-cache invalidation
# ═════════════════════════════════════════════════════════════════════════════


def _sentinel_analysis() -> "axt.ContextAnalysis":
    return axt.ContextAnalysis(
        total_tokens=123, context_window_size=1_000_000, used_percent=0.0123,
        model="claude-opus-4-8", sources=[],
        cost_impact=axt.CostImpact(
            model="claude-opus-4-8", cache_write_cost=0.0,
            cache_read_cost_per_turn=0.0, avg_turns_per_session=30,
            avg_sessions_per_day=5, per_session_cost=0.0, monthly_cost=0.0),
    )


@pytest.mark.skipif(sys.platform == "win32", reason="vault linking is POSIX-only")
def test_only_a_sync_that_changed_links_drops_the_context_cache(tmp_path: Path, monkeypatch):
    """A `y` sync that actually creates/removes a symlink clears
    `state.context_analysis`; a no-op sync keeps it.

    US-PRJ05 AC1·AC2. Prevents both halves of the bug: a stale analysis
    surviving a real link change (wrong numbers on screen), and a no-op sync
    invalidating anyway (a full re-analysis on every keypress).
    """
    # TC-INT-040 (US-PRJ05 AC1·AC2)
    vault = tmp_path / "vault"
    _seed_vault_skill(vault, "alpha")
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    axt.write_profile(proj, axt.AxtProfile(skills=("alpha",)))
    monkeypatch.setattr("axt.HOME", tmp_path / "home")
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=vault, claude_dir=tmp_path / "claude"))
    monkeypatch.chdir(proj)

    state = axt.TuiState()
    state.stdscr_callbacks = None
    state.vault_items = axt.list_vault_items_with_project_state(
        vault, proj, global_dir=tmp_path / "claude")

    sentinel = _sentinel_analysis()
    state.context_analysis = sentinel
    msg = axt.handle_vault_input(state, ord("y"))

    assert msg == "Sync: +1 -0 err 0"
    assert (proj / ".claude" / "skills" / "alpha").is_symlink()
    assert state.context_analysis is None

    # Already in sync → nothing changes on disk and the cache is preserved.
    state.context_analysis = sentinel
    msg = axt.handle_vault_input(state, ord("y"))

    assert msg == "Sync: +0 -0 err 0"
    assert state.context_analysis is sentinel


@pytest.mark.skipif(sys.platform == "win32", reason="vault linking is POSIX-only")
def test_migrate_with_nothing_to_move_keeps_the_context_cache(tmp_path: Path, monkeypatch):
    """`m` with every item already vaulted reports 0 moved and leaves
    `state.context_analysis` untouched.

    US-PRJ05 AC2 + US-VLT01 AC4. Prevents: an unconditional invalidation that
    forces a full context re-analysis every time the user presses `m` to check
    whether anything is left to migrate.
    """
    # TC-INT-041 (US-PRJ05 AC2, US-VLT01 AC4)
    claude = tmp_path / "claude"
    vault = tmp_path / "vault"
    stored = _seed_vault_skill(vault, "alpha")
    (claude / "skills").mkdir(parents=True)
    os.symlink(stored, claude / "skills" / "alpha")  # already in vault → skipped
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr("axt.HOME", tmp_path / "home")
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=vault, claude_dir=claude))
    monkeypatch.chdir(proj)

    state = axt.TuiState()
    state.stdscr_callbacks = None
    state.vault_items = axt.list_vault_items_with_project_state(
        vault, proj, global_dir=claude)
    sentinel = _sentinel_analysis()
    state.context_analysis = sentinel

    msg = axt.handle_vault_input(state, ord("m"))

    assert msg == "Migrated: +0 skipped 1 broken 0 err 0"
    assert state.context_analysis is sentinel
    assert (claude / "skills" / "alpha").is_symlink()
    assert (stored / "SKILL.md").exists()
