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
