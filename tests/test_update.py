import json
import subprocess
from pathlib import Path

import axt
from axt.update import (
    UpdateStatus, UpdateResult, Updater,
    check_all_updates, apply_updates,
)


def test_update_installed_plugin_preserves_installed_at_and_bumps_updated(tmp_path):
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "foo@mk": [{
                "scope": "user",
                "installPath": "/old/foo/0.1.0",
                "version": "0.1.0",
                "installedAt": "2026-01-01T00:00:00.000Z",
                "lastUpdated": "2026-01-01T00:00:00.000Z",
                "gitCommitSha": "a" * 40,
            }]
        },
    }))
    axt.update_installed_plugin(
        ip, "foo@mk",
        version="0.2.0", git_commit_sha="b" * 40,
        install_path="/new/foo/0.2.0",
    )
    entry = json.loads(ip.read_text())["plugins"]["foo@mk"][0]
    assert entry["version"] == "0.2.0"
    assert entry["gitCommitSha"] == "b" * 40
    assert entry["installPath"] == "/new/foo/0.2.0"
    assert entry["scope"] == "user"                       # preserved
    assert entry["installedAt"] == "2026-01-01T00:00:00.000Z"  # preserved
    assert entry["lastUpdated"] != "2026-01-01T00:00:00.000Z"  # bumped


def test_add_installed_plugin_writes_git_commit_sha(tmp_path):
    ip = tmp_path / "installed_plugins.json"
    axt.add_installed_plugin(
        ip, plugin_id="bar@mk", version="1.0.0",
        install_path="/p/bar/1.0.0", scope="user", git_commit_sha="c" * 40,
    )
    entry = json.loads(ip.read_text())["plugins"]["bar@mk"][0]
    assert entry["gitCommitSha"] == "c" * 40


def test_update_installed_plugin_creates_entry_when_absent(tmp_path):
    """When plugin_id has no prior entry, default scope='user' and set a fresh installedAt."""
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({"version": 2, "plugins": {}}))
    axt.update_installed_plugin(
        ip, "new@mk",
        version="1.0.0", git_commit_sha="e" * 40,
        install_path="/p/new/1.0.0",
    )
    entry = json.loads(ip.read_text())["plugins"]["new@mk"][0]
    assert entry["scope"] == "user"          # default when absent
    assert entry["version"] == "1.0.0"
    assert entry["gitCommitSha"] == "e" * 40
    assert entry["installPath"] == "/p/new/1.0.0"
    assert entry["installedAt"]              # fresh timestamp set
    assert entry["lastUpdated"]              # set


def test_check_all_updates_isolates_a_raising_updater(monkeypatch):
    boom = Updater(item_type="boom", tier=1,
                   check_all=lambda: (_ for _ in ()).throw(RuntimeError("nope")),
                   apply_one=None)
    ok = Updater(item_type="ok", tier=1,
                 check_all=lambda: [UpdateStatus("ok", "x", 1, "1", "1", False)],
                 apply_one=None)
    monkeypatch.setattr("axt.update.UPDATERS", [boom, ok])
    out = check_all_updates()
    types = {s.item_type: s for s in out}
    assert types["ok"].name == "x"
    assert types["boom"].error and "nope" in types["boom"].error  # captured, not raised


def test_marketplace_updater_check_and_apply(monkeypatch, tmp_path):
    from axt.core import MarketplaceInfo, MarketplaceSource, VersionInfo, SyncMarketplaceResult
    mk = MarketplaceInfo("m1", MarketplaceSource("github", repo="o/r"), "/loc", "2026-01-01")
    monkeypatch.setattr("axt.update.list_marketplaces", lambda p: [mk])
    monkeypatch.setattr("axt.update.get_marketplace_version",
                        lambda p, n: VersionInfo(current="aaaa", remote="bbbb", updatable=True))
    out = check_all_updates(types=["marketplace"])
    assert out[0].item_type == "marketplace" and out[0].updatable is True

    monkeypatch.setattr("axt.update.sync_marketplace",
                        lambda p, n: SyncMarketplaceResult(before="aaaa", after="bbbb", updated=True))
    res = apply_updates([("marketplace", "m1")])
    assert res[0].updated is True and res[0].after == "bbbb"


def _make_marketplace_with_plugin(tmp_path, mk="mk", plugin="foo", version="0.2.0"):
    """Create a fake cloned-marketplace tree with one plugin at `version`."""
    mk_loc = tmp_path / "marketplaces" / mk
    src = mk_loc / "plugins" / plugin / ".claude-plugin"
    src.mkdir(parents=True)
    (src / "plugin.json").write_text(json.dumps({"name": plugin, "version": version}))
    km = tmp_path / "known_marketplaces.json"
    km.write_text(json.dumps({mk: {
        "source": {"source": "github", "repo": "o/r"},
        "installLocation": str(mk_loc), "lastUpdated": "2026-01-01T00:00:00.000Z",
    }}))
    (mk_loc / ".gcs-sha").write_text("d" * 40)  # non-git source → sha from file
    return km, mk_loc


def test_plugin_apply_reinstalls_and_bumps_version(tmp_path, monkeypatch):
    km, mk_loc = _make_marketplace_with_plugin(tmp_path, version="0.2.0")
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({"version": 2, "plugins": {"foo@mk": [{
        "scope": "user", "installPath": str(tmp_path / "cache/mk/foo/0.1.0"),
        "version": "0.1.0", "installedAt": "2026-01-01T00:00:00.000Z",
        "lastUpdated": "2026-01-01T00:00:00.000Z", "gitCommitSha": "a" * 40,
    }]}}))
    cache = tmp_path / "cache"
    # PATHS is a frozen dataclass — build a fresh Paths and replace the whole
    # object; the package write-proxy propagates it to axt.update.PATHS.
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=km, installed_plugins=ip, plugin_cache=cache))

    res = axt.update.apply_updates([("plugin", "foo@mk")], no_sync=True)[0]
    assert res.updated is True and res.after == "0.2.0" and res.action == "reinstall"
    entry = json.loads(ip.read_text())["plugins"]["foo@mk"][0]
    assert entry["version"] == "0.2.0"
    assert entry["gitCommitSha"] == "d" * 40
    assert entry["installPath"] == str(cache / "mk" / "foo" / "0.2.0")
    assert (cache / "mk" / "foo" / "0.2.0" / ".claude-plugin" / "plugin.json").exists()


def test_materialize_dir_overwrites_existing_dest(tmp_path):
    from pathlib import Path
    import axt
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "new.txt").write_text("new")
    (src / "sub" / "keep.txt").write_text("keep")
    dest = tmp_path / "cache" / "plugin" / "1.0.0"
    dest.mkdir(parents=True)
    (dest / "stale.txt").write_text("stale")      # must be gone after
    axt.update._materialize_dir(src, dest)
    assert (dest / "new.txt").read_text() == "new"
    assert (dest / "sub" / "keep.txt").read_text() == "keep"
    assert not (dest / "stale.txt").exists()        # old content replaced


def test_materialize_dir_preserves_dest_when_copy_fails(tmp_path):
    """A copy failure (missing src) must leave an existing dest fully intact."""
    import pytest
    import axt
    dest = tmp_path / "cache" / "plugin" / "1.0.0"
    dest.mkdir(parents=True)
    (dest / "orig.txt").write_text("orig")
    missing_src = tmp_path / "does-not-exist"     # copytree raises
    with pytest.raises(Exception):
        axt.update._materialize_dir(missing_src, dest)
    assert (dest / "orig.txt").read_text() == "orig"   # invariant: dest untouched


def test_plugin_check_flags_version_bump(tmp_path, monkeypatch):
    km, mk_loc = _make_marketplace_with_plugin(tmp_path, version="0.2.0")
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({"version": 2, "plugins": {"foo@mk": [{
        "scope": "user", "installPath": "x", "version": "0.1.0",
        "installedAt": "2026-01-01T00:00:00.000Z", "lastUpdated": "2026-01-01T00:00:00.000Z",
        "gitCommitSha": "a" * 40,
    }]}}))
    monkeypatch.setattr("axt.PATHS", axt.Paths(known_marketplaces=km, installed_plugins=ip))
    monkeypatch.setattr("axt.update.get_marketplace_version",
                        lambda p, n: axt.core.VersionInfo(current="a", remote="a", updatable=False))
    out = axt.update.check_all_updates(types=["plugin"])
    s = [x for x in out if x.name == "foo@mk"][0]
    assert s.current == "0.1.0" and s.available == "0.2.0" and s.updatable is True


def test_plugin_check_missing_source_not_updatable(tmp_path, monkeypatch):
    """A plugin whose source vanished from the marketplace (upstream
    restructured into a non-plugin repo) must NOT show as updatable off the
    marketplace's git movement — _plugin_apply would fail the same way. Surface
    the source error instead of a false 'update available'. (lazyweb regression)"""
    mk_loc = tmp_path / "marketplaces" / "mk"   # cloned tree with NO plugin.json anywhere
    mk_loc.mkdir(parents=True)
    (mk_loc / "SKILL.md").write_text("now a skill pack, no plugin here")
    km = tmp_path / "known_marketplaces.json"
    km.write_text(json.dumps({"mk": {
        "source": {"source": "github", "repo": "o/r"},
        "installLocation": str(mk_loc), "lastUpdated": "2026-01-01T00:00:00.000Z",
    }}))
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({"version": 2, "plugins": {"foo@mk": [{
        "scope": "user", "installPath": "x", "version": "0.1.1",
        "installedAt": "2026-01-01T00:00:00.000Z", "lastUpdated": "2026-01-01T00:00:00.000Z",
        "gitCommitSha": "a" * 40,
    }]}}))
    monkeypatch.setattr("axt.PATHS", axt.Paths(known_marketplaces=km, installed_plugins=ip))
    # Marketplace git IS behind upstream (updatable), which used to leak into
    # the plugin row as a false "update available".
    monkeypatch.setattr("axt.update.get_marketplace_version",
                        lambda p, n: axt.core.VersionInfo(current="aaaa", remote="bbbb", updatable=True))
    s = [x for x in axt.update.check_all_updates(types=["plugin"]) if x.name == "foo@mk"][0]
    assert s.updatable is False
    assert s.error == "plugin source not found in marketplace"
    assert s.available == "?"                # never the marketplace sha


def _make_external_marketplace(tmp_path, source: dict, mk="mk", plugin="sp"):
    """Cloned-marketplace tree whose manifest declares `plugin` as coming from
    an external git `source` (url / git-subdir / github) — nothing on disk."""
    mk_loc = tmp_path / "marketplaces" / mk
    (mk_loc / ".claude-plugin").mkdir(parents=True)
    (mk_loc / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": mk, "plugins": [{"name": plugin, "source": source}]}))
    km = tmp_path / "known_marketplaces.json"
    km.write_text(json.dumps({mk: {
        "source": {"source": "github", "repo": "o/r"},
        "installLocation": str(mk_loc), "lastUpdated": "2026-01-01T00:00:00.000Z",
    }}))
    return km, mk_loc


def _write_ip_one(ip: Path, plugin_id: str, *, version: str, sha: str) -> None:
    ip.write_text(json.dumps({"version": 2, "plugins": {plugin_id: [{
        "scope": "user", "installPath": "x", "version": version,
        "installedAt": "2026-01-01T00:00:00.000Z", "lastUpdated": "2026-01-01T00:00:00.000Z",
        "gitCommitSha": sha,
    }]}}))


def test_plugin_check_external_source_compares_pinned_sha(tmp_path, monkeypatch):
    """superpowers-shaped: source is an external git repo. Updatability is the
    marketplace's pinned sha vs the installed sha — no network, no coarse
    marketplace-git-movement heuristic."""
    km, _mk = _make_external_marketplace(
        tmp_path, {"source": "url", "url": "https://x/y.git", "sha": "b" * 40})
    ip = tmp_path / "installed_plugins.json"
    monkeypatch.setattr("axt.PATHS", axt.Paths(known_marketplaces=km, installed_plugins=ip))

    _write_ip_one(ip, "sp@mk", version="1.0.0", sha="a" * 40)   # stale
    s = [x for x in axt.update.check_all_updates(types=["plugin"]) if x.name == "sp@mk"][0]
    assert s.updatable is True and s.available == "b" * 7 and s.error is None

    _write_ip_one(ip, "sp@mk", version="1.0.0", sha="b" * 40)   # matches pin
    s = [x for x in axt.update.check_all_updates(types=["plugin"]) if x.name == "sp@mk"][0]
    assert s.updatable is False and s.note == "up to date"


def test_plugin_apply_external_clones_and_records(tmp_path, monkeypatch):
    """Applying an external-sourced plugin clones upstream (mocked), materializes
    into the cache, and records the resolved sha + version."""
    km, _mk = _make_external_marketplace(
        tmp_path, {"source": "url", "url": "https://x/y.git", "sha": "b" * 40})
    ip = tmp_path / "installed_plugins.json"
    _write_ip_one(ip, "sp@mk", version="1.0.0", sha="a" * 40)
    cache = tmp_path / "cache"

    staged = tmp_path / "staged"
    (staged / ".claude-plugin").mkdir(parents=True)
    (staged / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "sp", "version": "2.0.0"}))
    monkeypatch.setattr("axt.update.clone_plugin_source",
                        lambda source, work: (staged, "b" * 40, None))
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=km, installed_plugins=ip, plugin_cache=cache))

    res = axt.update.apply_updates([("plugin", "sp@mk")], no_sync=True)[0]
    assert res.updated is True and res.after == "2.0.0" and res.action == "clone"
    entry = json.loads(ip.read_text())["plugins"]["sp@mk"][0]
    assert entry["version"] == "2.0.0" and entry["gitCommitSha"] == "b" * 40
    assert entry["installPath"] == str(cache / "mk" / "sp" / "2.0.0")
    assert (cache / "mk" / "sp" / "2.0.0" / ".claude-plugin" / "plugin.json").exists()


def test_plugin_apply_external_surfaces_clone_error(tmp_path, monkeypatch):
    km, _mk = _make_external_marketplace(
        tmp_path, {"source": "url", "url": "https://x/y.git", "sha": "b" * 40})
    ip = tmp_path / "installed_plugins.json"
    _write_ip_one(ip, "sp@mk", version="1.0.0", sha="a" * 40)
    monkeypatch.setattr("axt.update.clone_plugin_source",
                        lambda source, work: (None, "", "clone failed: boom"))
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=km, installed_plugins=ip, plugin_cache=tmp_path / "cache"))
    res = axt.update.apply_updates([("plugin", "sp@mk")], no_sync=True)[0]
    assert res.updated is False and res.error == "clone failed: boom"
    # install record untouched on failure
    assert json.loads(ip.read_text())["plugins"]["sp@mk"][0]["version"] == "1.0.0"


def _git_init(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"], cwd=d, check=True)


def test_skill_updater_tiers_git_vs_nongit(tmp_path, monkeypatch):
    from axt.core import SkillInfo
    gitdir = tmp_path / "gitskill"
    _git_init(gitdir)
    plain = tmp_path / "plainskill"
    plain.mkdir()
    items = [
        SkillInfo(name="gitskill", path=str(gitdir), is_symlink=False, source="user"),
        SkillInfo(name="plainskill", path=str(plain), is_symlink=False, source="user"),
        SkillInfo(name="pluginskill", path="/x", is_symlink=False, source="plugin", plugin="p"),
    ]
    monkeypatch.setattr("axt.update.list_all_skills", lambda **k: items)
    out = {s.name: s for s in axt.update.check_all_updates(types=["skill"])}
    assert "pluginskill" not in out                     # plugin-provided excluded
    assert out["plainskill"].tier == 2 and "manual" in out["plainskill"].note
    assert out["gitskill"].tier == 1                     # inside a git repo


def test_git_updater_apply_pulls_new_commit(tmp_path, monkeypatch):
    """check reports updatable + apply fast-forwards to the remote's new commit."""
    from axt.core import SkillInfo
    remote = tmp_path / "remote"
    remote.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=remote, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "c1"], cwd=remote, check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "c2"], cwd=remote, check=True)
    items = [SkillInfo(name="s", path=str(clone), is_symlink=False, source="user")]
    monkeypatch.setattr("axt.update.list_all_skills", lambda **k: items)

    st = {x.name: x for x in axt.update.check_all_updates(types=["skill"])}["s"]
    assert st.tier == 1 and st.updatable is True and st.current != st.available

    res = axt.update.apply_updates([("skill", "s")])[0]
    assert res.updated is True and res.action == "git pull" and res.before != res.after


def test_git_updater_absorbs_fetch_failure(tmp_path, monkeypatch):
    """A git repo with no remote: check returns an error status, never raises."""
    from axt.core import SkillInfo
    repo = tmp_path / "noremote"
    _git_init(repo)
    items = [SkillInfo(name="s", path=str(repo), is_symlink=False, source="user")]
    monkeypatch.setattr("axt.update.list_all_skills", lambda **k: items)

    st = {x.name: x for x in axt.update.check_all_updates(types=["skill"])}["s"]
    assert st.tier == 1 and st.updatable is False
    assert st.error or st.note      # fetch/no-upstream captured, not raised


def test_command_and_agent_updaters_resolve_source_path(tmp_path, monkeypatch):
    """command/agent adapters resolve .source_path's parent dir → git-backed = tier 1."""
    from axt.core import CommandInfo, AgentInfo
    repo = tmp_path / "repo"
    _git_init(repo)
    cmd_md = repo / "cmd.md"; cmd_md.write_text("x")
    agt_md = repo / "agt.md"; agt_md.write_text("x")
    monkeypatch.setattr("axt.update.list_commands",
                        lambda **k: [CommandInfo(name="c", source="user", source_path=str(cmd_md), description="", content="")])
    monkeypatch.setattr("axt.update.list_all_agents",
                        lambda **k: [AgentInfo(name="a", source="user", source_path=str(agt_md), description="")])
    cmd = {x.name: x for x in axt.update.check_all_updates(types=["command"])}["c"]
    agt = {x.name: x for x in axt.update.check_all_updates(types=["agent"])}["a"]
    assert cmd.tier == 1 and agt.tier == 1     # both inside a git repo


def test_mcp_pin_note():
    from axt.update import _mcp_pin_note
    assert _mcp_pin_note(("-y", "server@0.4.5")) == "pinned @0.4.5"
    assert _mcp_pin_note(("-y", "server@latest")) == "floating (@latest)"
    assert _mcp_pin_note(("mcp_pkg==1.2.3",)) == "pinned ==1.2.3"
    assert _mcp_pin_note(("-m", "some_module", "serve")) == "unpinned"


def test_mcp_updater_is_report_only(monkeypatch):
    from axt.core import McpServerInfo
    srv = McpServerInfo(name="s", plugin_id="", command="npx", args=("-y", "s@0.4.5"), env=())
    monkeypatch.setattr("axt.update.collect_mcp_servers", lambda ip: [srv])
    monkeypatch.setattr("axt.update.list_installed_plugins", lambda p: [])
    out = axt.update.check_all_updates(types=["mcp"])
    assert out[0].tier == 2 and out[0].updatable is False and "0.4.5" in out[0].note
    # report-only: apply is a no-op skip
    res = axt.update.apply_updates([("mcp", "s")])
    assert res[0].action == "skipped"


def test_mcp_pin_note_edge_cases():
    from axt.update import _mcp_pin_note
    # email/URL-like args that merely contain the substrings are NOT floating
    assert _mcp_pin_note(("--user=admin@nextcloud.example.com",)) == "unpinned"
    assert _mcp_pin_note(("user@next.example.com",)) == "unpinned"
    assert _mcp_pin_note(("user@latestcorp.com",)) == "unpinned"
    # real floating tags still detected
    assert _mcp_pin_note(("-y", "server@latest")) == "floating (@latest)"
    assert _mcp_pin_note(("-y", "server@next")) == "floating (@latest)"
    # scoped npm names: no version → unpinned; with version → pinned
    assert _mcp_pin_note(("@scope/pkg",)) == "unpinned"
    assert _mcp_pin_note(("@modelcontextprotocol/server-filesystem@1.2.3",)) == "pinned @1.2.3"
    # concrete pin wins over floating regardless of order
    assert _mcp_pin_note(("a@latest", "b@1.2.3")) == "pinned @1.2.3"


def test_claude_code_check_and_apply(monkeypatch):
    calls = {"version": iter(["2.1.100", "2.1.100", "2.2.0"])}  # apply reads before, then after

    def fake_version():
        return next(calls["version"])

    monkeypatch.setattr("axt.update._claude_version", fake_version)
    out = axt.update.check_all_updates(types=["claude-code"])
    assert out[0].item_type == "claude-code" and out[0].current == "2.1.100" and out[0].tier == 3

    monkeypatch.setattr("axt.update._run_claude_update", lambda: (0, "updated", ""))
    res = axt.update.apply_updates([("claude-code", "claude-code")])[0]
    assert res.before == "2.1.100" and res.after == "2.2.0" and res.updated is True


# ── CLI: `axt update` ───────────────────────────────────────────────────────

import io
from contextlib import redirect_stdout


def _run_cli(argv):
    import axt
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = axt.main(argv)
    return rc, buf.getvalue()


def test_cli_update_dry_run_json(monkeypatch):
    monkeypatch.setattr("axt.cli.check_all_updates",
                        lambda types=None: [axt.update.UpdateStatus("marketplace", "m1", 1, "a", "b", True)])
    rc, out = _run_cli(["update", "--json"])
    assert rc == 0
    import json as _j
    data = _j.loads(out)
    assert data[0]["name"] == "m1" and data[0]["updatable"] is True


def test_cli_update_apply_gated_by_yes(monkeypatch):
    monkeypatch.setattr("axt.cli.check_all_updates",
                        lambda types=None: [axt.update.UpdateStatus("marketplace", "m1", 1, "a", "b", True)])
    applied = {}
    monkeypatch.setattr("axt.cli.apply_updates",
                        lambda targets, no_sync=False: (applied.setdefault("t", targets),
                                                        [axt.update.UpdateResult("marketplace", "m1", "a", "b", True, "git pull")])[1])
    rc, out = _run_cli(["update", "--apply", "--yes"])
    assert rc == 0
    assert applied["t"] == [("marketplace", "m1")]     # bulk targets tier-1 updatable


def test_cli_update_claude_code_explicit_apply(monkeypatch):
    import axt
    monkeypatch.setattr("axt.cli.check_all_updates",
        lambda types=None: [axt.update.UpdateStatus("claude-code", "claude-code", 3, "2.1.0", "?", False,
                                                     note="updates via claude update")])
    called = {}
    monkeypatch.setattr("axt.cli.apply_updates",
        lambda targets, no_sync=False: (called.setdefault("t", targets),
            [axt.update.UpdateResult("claude-code", "claude-code", "2.1.0", "2.2.0", True, "claude update")])[1])
    rc, out = _run_cli(["update", "claude-code", "--apply", "--yes"])
    assert rc == 0
    assert called["t"] == [("claude-code", "claude-code")]     # explicit tier-3 applies


def test_cli_update_bulk_apply_excludes_tier3(monkeypatch):
    import axt
    monkeypatch.setattr("axt.cli.check_all_updates",
        lambda types=None: [
            axt.update.UpdateStatus("marketplace", "m1", 1, "a", "b", True),
            axt.update.UpdateStatus("claude-code", "claude-code", 3, "2.1.0", "?", False),
        ])
    called = {}
    monkeypatch.setattr("axt.cli.apply_updates",
        lambda targets, no_sync=False: (called.setdefault("t", targets),
            [axt.update.UpdateResult("marketplace", "m1", "a", "b", True, "git pull")])[1])
    rc, out = _run_cli(["update", "--apply", "--yes"])
    assert rc == 0
    assert called["t"] == [("marketplace", "m1")]              # tier-3 NOT auto-applied in bulk


def test_cli_update_apply_decline_aborts(monkeypatch):
    import axt
    monkeypatch.setattr("axt.cli.check_all_updates",
        lambda types=None: [axt.update.UpdateStatus("marketplace", "m1", 1, "a", "b", True)])
    calls = {"n": 0}
    monkeypatch.setattr("axt.cli.apply_updates",
        lambda targets, no_sync=False: (calls.__setitem__("n", calls["n"] + 1), [])[1])
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    rc, out = _run_cli(["update", "--apply"])
    assert rc == 1 and "Aborted" in out and calls["n"] == 0     # declined → no apply


def test_git_updater_ignores_ambient_config_repo(tmp_path, monkeypatch):
    """A plain skill under a git-tracked ~/.claude must NOT adopt that ambient repo."""
    import subprocess, axt
    from axt.core import SkillInfo
    claude = tmp_path / "dotclaude"
    claude.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=claude, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "c"], cwd=claude, check=True)
    skill = claude / "skills" / "foo"
    skill.mkdir(parents=True)                      # plain dir, no own .git
    monkeypatch.setattr("axt.PATHS", axt.Paths(claude_dir=claude, skills=claude / "skills"))
    monkeypatch.setattr("axt.update.list_all_skills",
                        lambda **k: [SkillInfo(name="foo", path=str(skill), is_symlink=False, source="user")])
    st = {x.name: x for x in axt.update.check_all_updates(types=["skill"])}["foo"]
    assert st.tier == 2 and "manual" in st.note    # ambient ~/.claude repo NOT adopted


def test_git_updater_still_updates_dedicated_repo(tmp_path, monkeypatch):
    """A skill whose own dir is a git repo (below the config dir) is still tier-1."""
    import subprocess, axt
    from axt.core import SkillInfo
    claude = tmp_path / "dotclaude"
    (claude / "skills").mkdir(parents=True)
    repo = claude / "skills" / "bar"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "c"], cwd=repo, check=True)
    monkeypatch.setattr("axt.PATHS", axt.Paths(claude_dir=claude, skills=claude / "skills"))
    monkeypatch.setattr("axt.update.list_all_skills",
                        lambda **k: [SkillInfo(name="bar", path=str(repo), is_symlink=False, source="user")])
    st = {x.name: x for x in axt.update.check_all_updates(types=["skill"])}["bar"]
    assert st.tier == 1                            # dedicated repo below config dir → updatable


def test_check_and_apply_path_update_roundtrip(tmp_path):
    """check_path_update/apply_path_update address an item by storage path
    (the Vault tab's entry point) — no registry lookup, symlinks resolved."""
    remote = tmp_path / "remote"
    remote.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=remote, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "c1"], cwd=remote, check=True)
    clone = tmp_path / "vault" / "skills" / "myskill"
    clone.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "c2"], cwd=remote, check=True)
    link = tmp_path / "link-to-myskill"
    link.symlink_to(clone)

    st = axt.update.check_path_update("skill", "myskill", str(link))
    assert st.tier == 1 and st.updatable is True

    res = axt.update.apply_path_update("skill", "myskill", str(link))
    assert res.updated is True and res.action == "git pull" and res.before != res.after

    st2 = axt.update.check_path_update("skill", "myskill", str(clone))
    assert st2.updatable is False and st2.note == "up to date"


def test_check_path_update_non_git(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    st = axt.update.check_path_update("skill", "plain", str(plain))
    assert st.tier == 2 and "manual" in st.note and st.updatable is False


def test_update_status_cache_roundtrip(tmp_path, monkeypatch):
    """save/load round-trips statuses + checkedAt via AXT_CONFIG_DIR/cache."""
    monkeypatch.setattr("axt.update.AXT_CONFIG_DIR", tmp_path)
    # Resolve the class at call time: test_package_mirror reloads axt.update
    # mid-suite, so the module-top UpdateStatus import can be a stale identity
    # that never compares equal to instances built inside the loader.
    US = axt.update.UpdateStatus
    sts = [
        US("plugin", "foo@mk", 1, "1", "2", True),
        US("skill", "s", 2, "local", "local", False, note="manual (non-git)"),
    ]
    axt.update.save_cached_update_statuses(sts, "2026-07-05T00:00:00.000Z")
    loaded, checked_at = axt.update.load_cached_update_statuses()
    assert loaded == sts
    assert checked_at == "2026-07-05T00:00:00.000Z"
    assert (tmp_path / "cache" / "update-status.json").exists()


def test_update_status_cache_missing_or_corrupt(tmp_path, monkeypatch):
    """Missing file and schema drift both degrade to ([], None), never raise."""
    monkeypatch.setattr("axt.update.AXT_CONFIG_DIR", tmp_path)
    assert axt.update.load_cached_update_statuses() == ([], None)
    p = tmp_path / "cache" / "update-status.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"checkedAt": "x", "statuses": [{"bogus": 1}]}')
    assert axt.update.load_cached_update_statuses() == ([], None)
    p.write_text("not json at all")
    assert axt.update.load_cached_update_statuses() == ([], None)
