"""Tests for Section 5 — marketplace registry.

Network and `git clone` paths are exercised by mocking subprocess and urllib.
Tests that only touch the registry JSON (list/parse/remove without owned dir)
are pure file-system.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import axt


# ─── parse_marketplace_source ────────────────────────────────────────────────


def test_parse_github_prefix():
    src = axt.parse_marketplace_source("github:owner/repo")
    assert src.kind == "github" and src.repo == "owner/repo"


def test_parse_git_prefix():
    src = axt.parse_marketplace_source("git:https://example.com/x.git")
    assert src.kind == "git" and src.url == "https://example.com/x.git"


def test_parse_dir_prefix():
    src = axt.parse_marketplace_source("dir:/abs/path")
    assert src.kind == "directory" and src.path == "/abs/path"


def test_parse_bare_owner_repo_defaults_to_github():
    src = axt.parse_marketplace_source("owner/repo")
    assert src.kind == "github" and src.repo == "owner/repo"


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        axt.parse_marketplace_source("garbage")


# ─── source.to_json / from_json round-trip ───────────────────────────────────


def test_source_roundtrip():
    src = axt.MarketplaceSource(kind="github", repo="o/r")
    assert axt.MarketplaceSource.from_json(src.to_json()) == src


# ─── list_marketplaces ───────────────────────────────────────────────────────


def test_list_marketplaces_empty(tmp_path: Path):
    assert axt.list_marketplaces(tmp_path / "km.json") == []


def test_list_marketplaces_seeded(tmp_path: Path):
    km = tmp_path / "km.json"
    km.write_text(json.dumps({
        "official": {
            "source": {"source": "github", "repo": "anthropic/claude-plugins"},
            "installLocation": "/marketplaces/official",
            "lastUpdated": "2026-01-01T00:00:00.000Z",
        },
        "local": {
            "source": {"source": "directory", "path": "/tmp/local"},
            "installLocation": "/tmp/local",
            "lastUpdated": "2026-02-01T00:00:00.000Z",
        },
    }))
    items = axt.list_marketplaces(km)
    by_name = {m.name: m for m in items}
    assert by_name["official"].source.kind == "github"
    assert by_name["official"].source.repo == "anthropic/claude-plugins"
    assert by_name["local"].source.path == "/tmp/local"


def test_list_marketplaces_skips_malformed(tmp_path: Path):
    km = tmp_path / "km.json"
    km.write_text(json.dumps({
        "good": {
            "source": {"source": "github", "repo": "o/r"},
            "installLocation": "/x",
            "lastUpdated": "",
        },
        "bad": "not-an-object",
    }))
    items = axt.list_marketplaces(km)
    assert [i.name for i in items] == ["good"]


# ─── is_git_repo / read_sha_file ─────────────────────────────────────────────


def test_is_git_repo_false(tmp_path: Path):
    assert axt.is_git_repo(tmp_path) is False


def test_is_git_repo_true(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert axt.is_git_repo(tmp_path) is True


def test_read_sha_file_missing(tmp_path: Path):
    assert axt.read_sha_file(tmp_path) is None


def test_read_sha_file_strips_whitespace(tmp_path: Path):
    (tmp_path / axt.GCS_SHA_FILE).write_text("  abc123def\n")
    assert axt.read_sha_file(tmp_path) == "abc123def"


def test_read_sha_file_empty_returns_none(tmp_path: Path):
    (tmp_path / axt.GCS_SHA_FILE).write_text("   \n")
    assert axt.read_sha_file(tmp_path) is None


# ─── add_marketplace ─────────────────────────────────────────────────────────


def test_add_marketplace_directory(tmp_path: Path):
    km = tmp_path / "km.json"
    mks = tmp_path / "marketplaces"
    target = tmp_path / "local"
    target.mkdir()
    src = axt.MarketplaceSource(kind="directory", path=str(target))
    axt.add_marketplace(km, mks, "mine", src)
    data = json.loads(km.read_text())
    assert "mine" in data
    assert data["mine"]["source"] == {"source": "directory", "path": str(target)}
    assert data["mine"]["installLocation"] == str(target)


def test_add_marketplace_directory_missing(tmp_path: Path):
    km = tmp_path / "km.json"
    src = axt.MarketplaceSource(kind="directory", path=str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError):
        axt.add_marketplace(km, tmp_path / "m", "mine", src)


def test_add_marketplace_duplicate(tmp_path: Path):
    km = tmp_path / "km.json"
    target = tmp_path / "local"
    target.mkdir()
    src = axt.MarketplaceSource(kind="directory", path=str(target))
    axt.add_marketplace(km, tmp_path / "m", "mine", src)
    with pytest.raises(ValueError, match="already exists"):
        axt.add_marketplace(km, tmp_path / "m", "mine", src)


def test_add_marketplace_github_invokes_git_clone(tmp_path: Path):
    km = tmp_path / "km.json"
    mks = tmp_path / "marketplaces"

    captured = {}

    def fake_git(args, cwd=None):
        captured["args"] = args
        captured["cwd"] = cwd
        return (0, "", "")

    src = axt.MarketplaceSource(kind="github", repo="anthropic/claude-plugins")
    with patch.object(axt, "_git", fake_git):
        axt.add_marketplace(km, mks, "official", src)

    assert captured["args"][:3] == ["git", "clone", "--depth"]
    assert captured["args"][-2] == "https://github.com/anthropic/claude-plugins.git"
    assert captured["args"][-1] == str(mks / "official")
    data = json.loads(km.read_text())
    assert data["official"]["source"]["repo"] == "anthropic/claude-plugins"


def test_add_marketplace_clone_failure(tmp_path: Path):
    km = tmp_path / "km.json"
    src = axt.MarketplaceSource(kind="github", repo="o/r")
    with patch.object(axt, "_git", return_value=(128, "", "fatal: not a repo")):
        with pytest.raises(RuntimeError, match="git clone failed"):
            axt.add_marketplace(km, tmp_path / "m", "x", src)
    assert not km.exists()  # nothing written when clone fails


# ─── remove_marketplace ──────────────────────────────────────────────────────


def test_remove_marketplace_directory_keeps_external_dir(tmp_path: Path):
    km = tmp_path / "km.json"
    mks = tmp_path / "marketplaces"
    external = tmp_path / "external"
    external.mkdir()
    src = axt.MarketplaceSource(kind="directory", path=str(external))
    axt.add_marketplace(km, mks, "mine", src)
    axt.remove_marketplace(km, mks, "mine")
    assert "mine" not in json.loads(km.read_text())
    assert external.exists()  # not under marketplaces_dir, so left alone


def test_remove_marketplace_owned_dir_deleted(tmp_path: Path):
    km = tmp_path / "km.json"
    mks = tmp_path / "marketplaces"
    mks.mkdir()
    # Seed registry manually so we don't trigger git clone.
    install_dir = mks / "owned"
    install_dir.mkdir()
    (install_dir / "file.txt").write_text("present")
    km.write_text(json.dumps({
        "owned": {
            "source": {"source": "github", "repo": "x/y"},
            "installLocation": str(install_dir),
            "lastUpdated": "",
        }
    }))
    axt.remove_marketplace(km, mks, "owned")
    assert not install_dir.exists()
    assert json.loads(km.read_text()) == {}


def test_remove_marketplace_missing(tmp_path: Path):
    km = tmp_path / "km.json"
    km.write_text("{}")
    with pytest.raises(KeyError):
        axt.remove_marketplace(km, tmp_path / "m", "nope")


# ─── get_local_version / get_marketplace_version ─────────────────────────────


def test_get_local_version_directory(tmp_path: Path):
    km = tmp_path / "km.json"
    target = tmp_path / "local"
    target.mkdir()
    km.write_text(json.dumps({
        "local": {
            "source": {"source": "directory", "path": str(target)},
            "installLocation": str(target),
            "lastUpdated": "",
        }
    }))
    assert axt.get_local_version(km, "local") == "local"


def test_get_local_version_from_sha_file(tmp_path: Path):
    install = tmp_path / "install"
    install.mkdir()
    (install / axt.GCS_SHA_FILE).write_text("abc123def4567890")
    km = tmp_path / "km.json"
    km.write_text(json.dumps({
        "x": {
            "source": {"source": "github", "repo": "o/r"},
            "installLocation": str(install),
            "lastUpdated": "",
        }
    }))
    assert axt.get_local_version(km, "x") == "abc123d"


def test_get_local_version_unknown_no_git_no_sha(tmp_path: Path):
    install = tmp_path / "install"
    install.mkdir()
    km = tmp_path / "km.json"
    km.write_text(json.dumps({
        "x": {
            "source": {"source": "github", "repo": "o/r"},
            "installLocation": str(install),
            "lastUpdated": "",
        }
    }))
    assert axt.get_local_version(km, "x") == "unknown"


def test_get_marketplace_version_missing(tmp_path: Path):
    info = axt.get_marketplace_version(tmp_path / "km.json", "nope")
    assert info.error and "not found" in info.error
    assert info.updatable is False


def test_get_marketplace_version_directory(tmp_path: Path):
    km = tmp_path / "km.json"
    km.write_text(json.dumps({
        "x": {
            "source": {"source": "directory", "path": "/tmp"},
            "installLocation": "/tmp",
            "lastUpdated": "",
        }
    }))
    info = axt.get_marketplace_version(km, "x")
    assert info.current == "local" and info.remote == "local"
    assert info.updatable is False


# ─── pooled_map ──────────────────────────────────────────────────────────────


def test_pooled_map_collects_results():
    result = axt.pooled_map([1, 2, 3, 4], lambda x: x * 10, concurrency=2)
    assert result.results == {1: 10, 2: 20, 3: 30, 4: 40}
    assert result.errors == ()


def test_pooled_map_collects_errors():
    def raises_on_two(x):
        if x == 2:
            raise RuntimeError("boom")
        return x * 100

    result = axt.pooled_map([1, 2, 3], raises_on_two, concurrency=3)
    assert result.results == {1: 100, 3: 300}
    assert len(result.errors) == 1
    assert result.errors[0].item == 2
    assert "boom" in str(result.errors[0].error)


def test_pooled_map_empty():
    result = axt.pooled_map([], lambda x: x)
    assert result.results == {}
    assert result.errors == ()


def test_pooled_map_callbacks():
    seen = []
    err_seen = []

    def maybe_fail(x):
        if x == "fail":
            raise ValueError("nope")
        return x.upper()

    axt.pooled_map(
        ["a", "b", "fail", "c"],
        maybe_fail,
        on_result=lambda item, value: seen.append((item, value)),
        on_error=lambda item, err: err_seen.append((item, str(err))),
    )
    assert sorted(seen) == [("a", "A"), ("b", "B"), ("c", "C")]
    assert err_seen == [("fail", "nope")]
