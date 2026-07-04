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
