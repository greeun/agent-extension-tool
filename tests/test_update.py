import json
import axt


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
