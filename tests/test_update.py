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
