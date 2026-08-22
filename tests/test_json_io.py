"""Tests for Section 2 (JSON I/O).

Atomicity guarantees we care about:
  1. read_json: missing file + fallback → returns fallback (no raise)
  2. read_json: missing file + no fallback → FileNotFoundError
  3. write_json_atomic: creates parent dirs
  4. write_json_atomic: pre-existing file backed up to .bak
  5. write_json_atomic: writes via tempfile + replace (no partial files)
  6. write_json_atomic: preserves unicode (ensure_ascii=False)
  7. write_json_atomic: leaves no .tmp-* litter on success
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import axt


def test_read_json_returns_parsed_data(tmp_path: Path):
    p = tmp_path / "data.json"
    p.write_text('{"a": 1, "b": [2, 3]}')
    assert axt.read_json(p) == {"a": 1, "b": [2, 3]}


def test_read_json_missing_with_fallback(tmp_path: Path):
    assert axt.read_json(tmp_path / "nope.json", fallback={}) == {}
    assert axt.read_json(tmp_path / "nope.json", fallback=[]) == []
    # Falsy fallback must still be respected (no truthy check on fallback).
    assert axt.read_json(tmp_path / "nope.json", fallback=None) is None
    assert axt.read_json(tmp_path / "nope.json", fallback=0) == 0


def test_read_json_missing_without_fallback_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        axt.read_json(tmp_path / "nope.json")


def test_write_json_atomic_creates_parents(tmp_path: Path):
    target = tmp_path / "deep" / "deeper" / "data.json"
    axt.write_json_atomic(target, {"hello": "world"})
    assert target.exists()
    assert json.loads(target.read_text()) == {"hello": "world"}


def test_write_json_atomic_backs_up_existing(tmp_path: Path):
    target = tmp_path / "data.json"
    target.write_text('{"old": true}')
    axt.write_json_atomic(target, {"new": True})
    assert json.loads(target.read_text()) == {"new": True}
    backup = target.with_suffix(target.suffix + ".bak")
    assert backup.exists()
    assert json.loads(backup.read_text()) == {"old": True}


def test_write_json_atomic_preserves_unicode(tmp_path: Path):
    target = tmp_path / "korean.json"
    axt.write_json_atomic(target, {"name": "한글", "emoji": "✓"})
    raw = target.read_text(encoding="utf-8")
    assert "한글" in raw
    assert "\\u" not in raw  # not escaped — readable output


def test_write_json_atomic_trailing_newline(tmp_path: Path):
    target = tmp_path / "nl.json"
    axt.write_json_atomic(target, {"a": 1})
    assert target.read_text().endswith("\n")


def test_write_json_atomic_no_tmp_litter(tmp_path: Path):
    target = tmp_path / "data.json"
    axt.write_json_atomic(target, {"a": 1})
    tmp_files = [p for p in tmp_path.iterdir() if p.name.startswith(".tmp-")]
    assert tmp_files == []


def test_write_json_atomic_pretty_indent(tmp_path: Path):
    target = tmp_path / "pretty.json"
    axt.write_json_atomic(target, {"nested": {"a": 1}})
    raw = target.read_text()
    # Pretty-printed: a newline + spaces precede each key. We just check that
    # the file is multi-line rather than the single-line minimal encoding.
    assert raw.count("\n") >= 3


def test_read_json_after_write_roundtrip(tmp_path: Path):
    target = tmp_path / "rt.json"
    data = {"list": [1, 2, 3], "nested": {"k": "v"}, "unicode": "한글"}
    axt.write_json_atomic(target, data)
    assert axt.read_json(target) == data


# ─── read_json_dict (object-or-empty guard) ──────────────────────────────────


def test_read_json_dict_missing_returns_empty(tmp_path: Path):
    assert axt.read_json_dict(tmp_path / "nope.json") == {}


def test_read_json_dict_non_object_returns_empty(tmp_path: Path):
    p = tmp_path / "v.json"
    p.write_text("[1, 2, 3]")
    assert axt.read_json_dict(p) == {}
    p.write_text('"a string"')
    assert axt.read_json_dict(p) == {}
    p.write_text("42")
    assert axt.read_json_dict(p) == {}


def test_read_json_dict_object_passthrough(tmp_path: Path):
    p = tmp_path / "obj.json"
    p.write_text('{"a": 1, "b": {"c": 2}}')
    assert axt.read_json_dict(p) == {"a": 1, "b": {"c": 2}}


# ─── Gap-code additions (Phase C, Agent C) ───────────────────────────────────


def test_read_json_corrupt_file_with_fallback_returns_fallback(tmp_path: Path):
    """A truncated/garbage JSON file must degrade to the caller's fallback.

    US-SYS05 AC1: "read_json(path, fallback=...) returns the fallback on a
    parse failure." Prevents: one half-written settings/registry file taking
    down every axt command that touches it (the whole point of the fallback
    parameter is that callers do not have to wrap each read in try/except).
    """
    # TC-UNIT-013 (US-SYS05 AC1)
    p = tmp_path / "broken.json"
    p.write_text("{not json")
    assert axt.read_json(p, fallback=[]) == []
    assert axt.read_json(p, fallback={}) == {}
    # Truncated mid-write (the realistic crash shape) behaves the same.
    p.write_text('{"enabledPlugins": {"a": tr')
    assert axt.read_json(p, fallback={"enabledPlugins": {}}) == {"enabledPlugins": {}}


def test_write_json_atomic_failed_replace_leaves_original_intact(tmp_path: Path, monkeypatch):
    """When the final rename fails, the pre-existing file keeps its old bytes.

    US-SYS04 AC3. Prevents: a disk-full / permission failure mid-write leaving
    `settings.json` empty or half-written — the exact loss the temp-file +
    os.replace dance exists to avoid.
    """
    # TC-UNIT-018 (US-SYS04 AC3)
    target = tmp_path / "data.json"
    original = '{"keep": "me"}'
    target.write_text(original)

    def boom(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        axt.write_json_atomic(target, {"clobbered": True})

    assert target.read_text() == original
    # And the staging file is cleaned up rather than left as litter.
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp-")] == []
