import json
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
