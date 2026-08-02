"""Tests for Section 5 — marketplace registry.

Network and `git clone` paths are exercised by mocking subprocess and urllib.
Tests that only touch the registry JSON (list/parse/remove without owned dir)
are pure file-system.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
import urllib.error
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


def test_list_marketplaces_skips_entry_with_non_dict_source(tmp_path: Path):
    # Entry is a dict, but its `source` field is not a dict -> skipped (line 1883).
    km = tmp_path / "km.json"
    km.write_text(json.dumps({
        "good": {
            "source": {"source": "github", "repo": "o/r"},
            "installLocation": "/x",
            "lastUpdated": "",
        },
        "broken": {
            "source": "github:o/r",  # string, not the expected object
            "installLocation": "/y",
            "lastUpdated": "",
        },
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


def test_get_local_version_missing_entry(tmp_path: Path):
    # Name not present in registry -> entry is None (not a dict) -> "?" (line 2002).
    km = tmp_path / "km.json"
    km.write_text("{}")
    assert axt.get_local_version(km, "absent") == "?"


def test_get_local_version_non_dict_entry(tmp_path: Path):
    # Entry present but not a dict -> "?" (line 2002).
    km = tmp_path / "km.json"
    km.write_text(json.dumps({"x": "not-an-object"}))
    assert axt.get_local_version(km, "x") == "?"


def test_get_local_version_git_repo_short_hash(tmp_path: Path, monkeypatch):
    # installLocation is a git repo -> _git_short_hash result is returned (line 2008-2009).
    install = tmp_path / "install"
    (install / ".git").mkdir(parents=True)
    _seed_github_entry(tmp_path / "km.json", install)
    monkeypatch.setattr(axt, "_git", lambda args, cwd=None: (0, "feed1234\n", ""))
    assert axt.get_local_version(tmp_path / "km.json", "x") == "feed1234"


def test_get_local_version_git_repo_short_hash_error(tmp_path: Path, monkeypatch):
    # git repo but rev-parse fails -> RuntimeError swallowed -> "error" (line 2010-2011).
    install = tmp_path / "install"
    (install / ".git").mkdir(parents=True)
    _seed_github_entry(tmp_path / "km.json", install)
    monkeypatch.setattr(axt, "_git", lambda args, cwd=None: (1, "", "fatal: bad object"))
    assert axt.get_local_version(tmp_path / "km.json", "x") == "error"


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


# ─── helpers for network/git/tarball mocking ─────────────────────────────────


class _FakeResponse(io.BytesIO):
    """Context-manager-capable fake urllib response wrapping raw bytes."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _make_tarball_bytes(top: str, files: dict[str, str]) -> bytes:
    """Build a real .tar.gz where every file lives under a single `top/` dir,
    mimicking GitHub's `owner-repo-sha/` archive layout."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        # Add the top-level directory entry.
        dir_info = tarfile.TarInfo(name=top)
        dir_info.type = tarfile.DIRTYPE
        dir_info.mode = 0o755
        tf.addfile(dir_info)
        for rel, content in files.items():
            raw = content.encode("utf-8")
            info = tarfile.TarInfo(name=f"{top}/{rel}")
            info.size = len(raw)
            tf.addfile(info, io.BytesIO(raw))
    return buf.getvalue()


def _http_error(code: int = 404, reason: str = "Not Found") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.github.com/x", code=code, msg=reason, hdrs=None, fp=None
    )


# ─── _git subprocess wrapper ─────────────────────────────────────────────────


def test_git_returns_proc_fields(monkeypatch):
    class _Proc:
        returncode = 0
        stdout = "out-data"
        stderr = "err-data"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())
    code, out, err = axt._git(["git", "status"])
    assert (code, out, err) == (0, "out-data", "err-data")


def test_git_binary_missing_returns_127(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("no git here")

    monkeypatch.setattr(subprocess, "run", boom)
    code, out, err = axt._git(["git", "status"])
    assert code == 127
    assert out == ""
    assert "git not found on PATH" in err


def test_git_short_hash_failure_raises(monkeypatch):
    monkeypatch.setattr(axt, "_git", lambda args, cwd=None: (1, "", "fatal: bad rev"))
    with pytest.raises(RuntimeError, match="git rev-parse failed"):
        axt._git_short_hash("/some/dir")


def test_git_short_hash_empty_raises(monkeypatch):
    monkeypatch.setattr(axt, "_git", lambda args, cwd=None: (0, "   \n", ""))
    with pytest.raises(RuntimeError, match="returned empty"):
        axt._git_short_hash("/some/dir")


# ─── _fetch_github_head_sha ──────────────────────────────────────────────────


def test_fetch_github_head_sha_success(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResponse(b"  abcdef1234567890\n"),
    )
    assert axt._fetch_github_head_sha("o/r") == "abcdef1234567890"


def test_fetch_github_head_sha_http_error(monkeypatch):
    def boom(req, timeout=None):
        raise _http_error(404, "Not Found")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RuntimeError, match="GitHub API error: 404"):
        axt._fetch_github_head_sha("o/missing")


def test_fetch_github_head_sha_url_error(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.URLError("dns failure")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(RuntimeError, match="GitHub API error"):
        axt._fetch_github_head_sha("o/r")


# ─── download_and_extract_tarball ────────────────────────────────────────────


def test_download_and_extract_tarball_success(tmp_path: Path, monkeypatch):
    sha = "deadbeefcafe0001"
    monkeypatch.setattr(axt, "_fetch_github_head_sha", lambda repo: sha)
    tar_bytes = _make_tarball_bytes(
        f"owner-repo-{sha[:7]}",
        {"README.md": "hello", "sub/plugin.json": '{"name":"p"}'},
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResponse(tar_bytes),
    )
    dest = tmp_path / "install"
    returned = axt.download_and_extract_tarball("owner/repo", dest)
    assert returned == sha
    # Files from inside the single top dir landed directly under dest.
    assert (dest / "README.md").read_text() == "hello"
    assert (dest / "sub" / "plugin.json").read_text() == '{"name":"p"}'
    # The .gcs-sha marker holds the full sha.
    assert (dest / axt.GCS_SHA_FILE).read_text() == sha


def test_download_and_extract_tarball_overwrites_existing(tmp_path: Path, monkeypatch):
    sha = "1111222233334444"
    monkeypatch.setattr(axt, "_fetch_github_head_sha", lambda repo: sha)
    tar_bytes = _make_tarball_bytes(f"x-{sha[:7]}", {"new.txt": "fresh"})
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResponse(tar_bytes),
    )
    dest = tmp_path / "install"
    dest.mkdir()
    (dest / "stale.txt").write_text("old")
    axt.download_and_extract_tarball("o/r", dest)
    assert not (dest / "stale.txt").exists()  # prior content wiped
    assert (dest / "new.txt").read_text() == "fresh"


def test_download_and_extract_tarball_http_error_leaves_dest(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(axt, "_fetch_github_head_sha", lambda repo: "0" * 16)

    def boom(req, timeout=None):
        raise _http_error(500, "Server Error")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    dest = tmp_path / "install"
    dest.mkdir()
    (dest / "keep.txt").write_text("untouched")
    with pytest.raises(RuntimeError, match="Tarball download failed: 500"):
        axt.download_and_extract_tarball("o/r", dest)
    # Download failed before extraction, so existing dest is left intact.
    assert (dest / "keep.txt").read_text() == "untouched"


def test_download_and_extract_tarball_url_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(axt, "_fetch_github_head_sha", lambda repo: "0" * 16)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(RuntimeError, match="Tarball download failed"):
        axt.download_and_extract_tarball("o/r", tmp_path / "install")


def test_download_and_extract_tarball_empty_archive(tmp_path: Path, monkeypatch):
    sha = "abc1230000000000"
    monkeypatch.setattr(axt, "_fetch_github_head_sha", lambda repo: sha)
    # Archive containing only files at root (no top-level directory entry).
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        raw = b"loose"
        info = tarfile.TarInfo(name="loose.txt")
        info.size = len(raw)
        tf.addfile(info, io.BytesIO(raw))
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResponse(buf.getvalue()),
    )
    with pytest.raises(RuntimeError, match="extracted empty"):
        axt.download_and_extract_tarball("o/r", tmp_path / "install")


def test_download_and_extract_tarball_rejects_path_traversal(tmp_path: Path, monkeypatch):
    sha = "beadfeed00000000"
    monkeypatch.setattr(axt, "_fetch_github_head_sha", lambda repo: sha)
    # A member whose name escapes the extraction dir via `../`.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        raw = b"pwned"
        info = tarfile.TarInfo(name="../evil.txt")
        info.size = len(raw)
        tf.addfile(info, io.BytesIO(raw))
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResponse(buf.getvalue()),
    )
    with pytest.raises(RuntimeError, match="Unsafe"):
        axt.download_and_extract_tarball("o/r", tmp_path / "install")
    # Extraction aborted before the copy step, so dest was never created.
    assert not (tmp_path / "install").exists()


# ─── add_marketplace (git URL construction + clone) ──────────────────────────


def test_add_marketplace_git_url_passthrough(tmp_path: Path):
    km = tmp_path / "km.json"
    mks = tmp_path / "marketplaces"
    captured = {}

    def fake_git(args, cwd=None):
        captured["args"] = args
        return (0, "", "")

    src = axt.MarketplaceSource(kind="git", url="https://gitlab.com/x/y.git")
    with patch.object(axt, "_git", fake_git):
        axt.add_marketplace(km, mks, "mine", src)
    # Bare git URL is passed through verbatim (no .git suffix munging).
    assert captured["args"][-2] == "https://gitlab.com/x/y.git"
    assert captured["args"][-1] == str(mks / "mine")
    data = json.loads(km.read_text())
    assert data["mine"]["source"]["url"] == "https://gitlab.com/x/y.git"
    assert data["mine"]["installLocation"] == str(mks / "mine")


def test_add_marketplace_unknown_kind_raises(tmp_path: Path):
    km = tmp_path / "km.json"
    src = axt.MarketplaceSource(kind="weird")
    with pytest.raises(ValueError, match="Unknown source kind"):
        axt.add_marketplace(km, tmp_path / "m", "x", src)
    assert not km.exists()


def test_add_marketplace_git_clone_failure_no_registry_write(tmp_path: Path):
    km = tmp_path / "km.json"
    src = axt.MarketplaceSource(kind="git", url="https://example.com/x.git")
    with patch.object(axt, "_git", return_value=(1, "", "fatal: auth failed")):
        with pytest.raises(RuntimeError, match="git clone failed"):
            axt.add_marketplace(km, tmp_path / "m", "x", src)
    assert not km.exists()


# ─── get_marketplace_version (git + github branches) ─────────────────────────


def _seed_github_entry(km: Path, install: Path, repo: str = "o/r") -> None:
    km.write_text(json.dumps({
        "x": {
            "source": {"source": "github", "repo": repo},
            "installLocation": str(install),
            "lastUpdated": "",
        }
    }))


def test_get_marketplace_version_git_updatable(tmp_path: Path, monkeypatch):
    install = tmp_path / "install"
    (install / ".git").mkdir(parents=True)
    _seed_github_entry(tmp_path / "km.json", install)

    calls = []

    def fake_git(args, cwd=None):
        calls.append(args)
        if "rev-parse" in args and "HEAD" in args:
            return (0, "aaaaaaa\n", "")
        if "fetch" in args:
            return (0, "", "")
        if "rev-parse" in args and "@{u}" in args:
            return (0, "bbbbbbb\n", "")
        return (1, "", "unexpected")

    monkeypatch.setattr(axt, "_git", fake_git)
    info = axt.get_marketplace_version(tmp_path / "km.json", "x")
    assert info.current == "aaaaaaa"
    assert info.remote == "bbbbbbb"
    assert info.updatable is True
    assert info.error is None


def test_get_marketplace_version_git_up_to_date(tmp_path: Path, monkeypatch):
    install = tmp_path / "install"
    (install / ".git").mkdir(parents=True)
    _seed_github_entry(tmp_path / "km.json", install)

    def fake_git(args, cwd=None):
        if "fetch" in args:
            return (0, "", "")
        if "@{u}" in args:
            return (0, "samehash\n", "")
        return (0, "samehash\n", "")

    monkeypatch.setattr(axt, "_git", fake_git)
    info = axt.get_marketplace_version(tmp_path / "km.json", "x")
    assert info.current == info.remote == "samehash"
    assert info.updatable is False


def test_get_marketplace_version_git_fetch_failure(tmp_path: Path, monkeypatch):
    install = tmp_path / "install"
    (install / ".git").mkdir(parents=True)
    _seed_github_entry(tmp_path / "km.json", install)

    def fake_git(args, cwd=None):
        if "rev-parse" in args and "HEAD" in args:
            return (0, "current1\n", "")
        if "fetch" in args:
            return (1, "", "fatal: could not fetch")
        return (0, "x\n", "")

    monkeypatch.setattr(axt, "_git", fake_git)
    info = axt.get_marketplace_version(tmp_path / "km.json", "x")
    assert info.error == "fatal: could not fetch"
    assert info.updatable is False
    assert info.current == "?"


def test_get_marketplace_version_git_no_upstream(tmp_path: Path, monkeypatch):
    install = tmp_path / "install"
    (install / ".git").mkdir(parents=True)
    _seed_github_entry(tmp_path / "km.json", install)

    def fake_git(args, cwd=None):
        if "rev-parse" in args and "HEAD" in args:
            return (0, "cur1234\n", "")
        if "fetch" in args:
            return (0, "", "")
        if "@{u}" in args:
            return (1, "", "")  # empty stderr -> falls back to "no upstream"
        return (0, "", "")

    monkeypatch.setattr(axt, "_git", fake_git)
    info = axt.get_marketplace_version(tmp_path / "km.json", "x")
    assert info.current == "cur1234"
    assert info.remote == "?"
    assert info.error == "no upstream"
    assert info.updatable is False


def test_get_marketplace_version_git_rev_parse_raises(tmp_path: Path, monkeypatch):
    install = tmp_path / "install"
    (install / ".git").mkdir(parents=True)
    _seed_github_entry(tmp_path / "km.json", install)
    # First rev-parse (HEAD) fails -> _git_short_hash raises RuntimeError.
    monkeypatch.setattr(axt, "_git", lambda args, cwd=None: (1, "", "fatal: bad object"))
    info = axt.get_marketplace_version(tmp_path / "km.json", "x")
    assert info.current == "?"
    assert info.error and "git rev-parse failed" in info.error


def test_get_marketplace_version_github_no_git_dir(tmp_path: Path, monkeypatch):
    install = tmp_path / "install"
    install.mkdir()
    (install / axt.GCS_SHA_FILE).write_text("localsha1234567890")
    _seed_github_entry(tmp_path / "km.json", install)
    monkeypatch.setattr(axt, "_fetch_github_head_sha", lambda repo: "remotesha999999999")
    info = axt.get_marketplace_version(tmp_path / "km.json", "x")
    assert info.current == "localsh"
    assert info.remote == "remotes"
    assert info.updatable is True


def test_get_marketplace_version_github_network_error(tmp_path: Path, monkeypatch):
    install = tmp_path / "install"
    install.mkdir()
    (install / axt.GCS_SHA_FILE).write_text("localsha1234567890")
    _seed_github_entry(tmp_path / "km.json", install)

    def boom(repo):
        raise RuntimeError("GitHub API error: 503 Unavailable")

    monkeypatch.setattr(axt, "_fetch_github_head_sha", boom)
    info = axt.get_marketplace_version(tmp_path / "km.json", "x")
    assert info.current == "?"
    assert info.remote == "?"
    assert info.error and "503" in info.error
    assert info.updatable is False


def test_get_marketplace_version_non_git_non_github(tmp_path: Path):
    install = tmp_path / "install"
    install.mkdir()
    # git source kind but no .git dir, no repo => the dead-end branch.
    (tmp_path / "km.json").write_text(json.dumps({
        "x": {
            "source": {"source": "git", "url": "https://e.com/x.git"},
            "installLocation": str(install),
            "lastUpdated": "",
        }
    }))
    info = axt.get_marketplace_version(tmp_path / "km.json", "x")
    assert info.error == "Non-git source without .git directory"
    assert info.updatable is False


# ─── sync_marketplace ────────────────────────────────────────────────────────


def test_sync_marketplace_missing(tmp_path: Path):
    (tmp_path / "km.json").write_text("{}")
    with pytest.raises(KeyError, match="not found"):
        axt.sync_marketplace(tmp_path / "km.json", "nope")


def test_sync_marketplace_directory_noop(tmp_path: Path):
    target = tmp_path / "local"
    target.mkdir()
    km = tmp_path / "km.json"
    km.write_text(json.dumps({
        "x": {
            "source": {"source": "directory", "path": str(target)},
            "installLocation": str(target),
            "lastUpdated": "old",
        }
    }))
    result = axt.sync_marketplace(km, "x")
    assert result.before == result.after == "local"
    assert result.updated is False
    # lastUpdated bumped despite no content change.
    assert json.loads(km.read_text())["x"]["lastUpdated"] != "old"


def test_sync_marketplace_git_hard_syncs_to_upstream(tmp_path: Path, monkeypatch):
    """Git installs sync via fetch + reset --hard @{u} (NOT pull --ff-only):
    the install dir is a managed cache Claude Code's own updater dirties."""
    install = tmp_path / "install"
    (install / ".git").mkdir(parents=True)
    _seed_github_entry(tmp_path / "km.json", install)

    state = {"hash": "before1"}

    def fake_git(args, cwd=None):
        if "rev-parse" in args:
            return (0, state["hash"] + "\n", "")
        if "fetch" in args:
            return (0, "", "")
        if "reset" in args:
            assert "--hard" in args and "@{u}" in args
            state["hash"] = "after22"  # reset moves HEAD to upstream
            return (0, "HEAD is now at after22\n", "")
        return (1, "", "unexpected")

    monkeypatch.setattr(axt, "_git", fake_git)
    result = axt.sync_marketplace(tmp_path / "km.json", "x")
    assert result.before == "before1"
    assert result.after == "after22"
    assert result.updated is True


def test_sync_marketplace_git_fetch_failure(tmp_path: Path, monkeypatch):
    install = tmp_path / "install"
    (install / ".git").mkdir(parents=True)
    _seed_github_entry(tmp_path / "km.json", install)

    def fake_git(args, cwd=None):
        if "rev-parse" in args:
            return (0, "before1\n", "")
        if "fetch" in args:
            return (1, "", "fatal: could not read from remote")
        return (0, "", "")

    monkeypatch.setattr(axt, "_git", fake_git)
    with pytest.raises(RuntimeError, match="git fetch failed"):
        axt.sync_marketplace(tmp_path / "km.json", "x")
    # lastUpdated NOT bumped on failure (write never reached).
    assert json.loads((tmp_path / "km.json").read_text())["x"]["lastUpdated"] == ""


def test_sync_marketplace_git_dirty_tree_hard_syncs(tmp_path: Path):
    """Regression (claude-hud): Claude Code's updater overwrites marketplace
    files in place WITHOUT committing, so the git tree is dirty and
    `pull --ff-only` refused to merge. Sync must discard those updater
    artifacts and hard-sync the tree to upstream."""
    import subprocess

    def run(*args, cwd):
        subprocess.run(args, cwd=cwd, check=True, capture_output=True)

    origin = tmp_path / "origin"
    origin.mkdir()
    run("git", "init", "-q", cwd=origin)
    run("git", "config", "user.email", "t@t", cwd=origin)
    run("git", "config", "user.name", "t", cwd=origin)
    (origin / "f.txt").write_text("v1\n")
    run("git", "add", "f.txt", cwd=origin)
    run("git", "commit", "-q", "-m", "v1", cwd=origin)

    install = tmp_path / "install"
    run("git", "clone", "-q", str(origin), str(install), cwd=tmp_path)
    run("git", "config", "user.email", "t@t", cwd=install)
    run("git", "config", "user.name", "t", cwd=install)

    # Upstream advances…
    (origin / "f.txt").write_text("v2\n")
    run("git", "commit", "-q", "-am", "v2", cwd=origin)
    # …while Claude Code's updater dirties the local tree (no commit).
    (install / "f.txt").write_text("overwritten-in-place\n")

    _seed_github_entry(tmp_path / "km.json", install)
    result = axt.sync_marketplace(tmp_path / "km.json", "x")
    assert result.updated is True
    assert (install / "f.txt").read_text() == "v2\n"


def test_sync_marketplace_github_tarball(tmp_path: Path, monkeypatch):
    install = tmp_path / "install"
    install.mkdir()
    (install / axt.GCS_SHA_FILE).write_text("oldsha00000000000")
    _seed_github_entry(tmp_path / "km.json", install)

    def fake_dl(repo, dest):
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / axt.GCS_SHA_FILE).write_text("newsha11111111111")
        return "newsha11111111111"

    monkeypatch.setattr(axt, "download_and_extract_tarball", fake_dl)
    result = axt.sync_marketplace(tmp_path / "km.json", "x")
    assert result.before == "oldsha0"
    assert result.after == "newsha1"
    assert result.updated is True
    assert json.loads((tmp_path / "km.json").read_text())["x"]["lastUpdated"] != ""


def test_sync_marketplace_unsyncable(tmp_path: Path):
    install = tmp_path / "install"
    install.mkdir()
    # git kind, no .git dir, no github repo => cannot sync.
    (tmp_path / "km.json").write_text(json.dumps({
        "x": {
            "source": {"source": "git", "url": "https://e.com/x.git"},
            "installLocation": str(install),
            "lastUpdated": "keep",
        }
    }))
    with pytest.raises(RuntimeError, match="not a git repo and not a github source"):
        axt.sync_marketplace(tmp_path / "km.json", "x")
    assert json.loads((tmp_path / "km.json").read_text())["x"]["lastUpdated"] == "keep"
