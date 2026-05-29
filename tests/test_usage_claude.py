"""Tests for Section 6 — Claude JSONL parser, cache, and 5-hour blocks."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import axt


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_parse_claude_jsonl_extracts_assistant_records(tmp_path: Path):
    f = tmp_path / "proj" / "sess.jsonl"
    _write_jsonl(f, [
        {"type": "user", "message": {"content": "hi"}},  # ignored
        {
            "type": "assistant",
            "sessionId": "s1",
            "timestamp": "2026-04-29T10:00:00.000Z",
            "message": {
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 500,
                    "cache_creation_input_tokens": 2000,
                    "cache_read_input_tokens": 5000,
                },
            },
        },
        {"type": "assistant", "message": {}},  # no usage, skipped
    ])
    entries = axt.parse_claude_jsonl(f)
    assert len(entries) == 1
    e = entries[0]
    assert e.model == "claude-opus-4-7"
    assert e.input_tokens == 100
    assert e.output_tokens == 500
    assert e.cache_creation_tokens == 2000
    assert e.cache_read_tokens == 5000
    assert e.session_id == "s1"
    assert e.project_path == "proj"


def test_parse_claude_jsonl_skips_malformed_lines(tmp_path: Path):
    f = tmp_path / "p" / "x.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text(
        "not json\n"
        + json.dumps({"type": "assistant", "message": {"model": "m", "usage": {"input_tokens": 1}}})
        + "\n"
        + "{}invalid\n"
    )
    entries = axt.parse_claude_jsonl(f)
    assert len(entries) == 1


def test_parse_claude_jsonl_missing_file(tmp_path: Path):
    assert axt.parse_claude_jsonl(tmp_path / "absent.jsonl") == []


def test_load_all_claude_usage_cache_roundtrip(tmp_path: Path, monkeypatch):
    # Redirect cache dir to tmp so the test doesn't pollute the user's cache.
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    projects = tmp_path / "projects"
    f1 = projects / "proj-a" / "sess1.jsonl"
    _write_jsonl(f1, [{
        "type": "assistant",
        "sessionId": "s1",
        "timestamp": "2026-04-29T10:00:00.000Z",
        "message": {"model": "claude-opus-4-7", "usage": {"input_tokens": 10, "output_tokens": 20}},
    }])
    f2 = projects / "proj-b" / "sess2.jsonl"
    _write_jsonl(f2, [{
        "type": "assistant",
        "sessionId": "s2",
        "timestamp": "2026-04-30T10:00:00.000Z",
        "message": {"model": "claude-opus-4-7", "usage": {"input_tokens": 100, "output_tokens": 200}},
    }])

    first = axt.load_all_claude_usage(projects)
    assert len(first) == 2
    # Cache file written.
    assert (tmp_path / "cache" / "claude-usage.json").exists()
    # Second call hits cache (still returns the same data).
    second = axt.load_all_claude_usage(projects)
    assert len(second) == 2


def test_load_all_claude_usage_project_filter(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    projects = tmp_path / "projects"
    _write_jsonl(projects / "alpha" / "s.jsonl", [{
        "type": "assistant", "sessionId": "1", "timestamp": "2026-04-29T10:00:00Z",
        "message": {"model": "claude-opus-4-7", "usage": {"input_tokens": 1}},
    }])
    _write_jsonl(projects / "beta" / "s.jsonl", [{
        "type": "assistant", "sessionId": "2", "timestamp": "2026-04-29T10:00:00Z",
        "message": {"model": "claude-opus-4-7", "usage": {"input_tokens": 1}},
    }])
    only_alpha = axt.load_all_claude_usage(projects, project="alpha")
    assert {e.project_path for e in only_alpha} == {"alpha"}


def test_load_all_claude_usage_since_until(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    projects = tmp_path / "projects"
    _write_jsonl(projects / "p" / "s.jsonl", [
        {"type": "assistant", "sessionId": "1", "timestamp": "2026-04-29T00:00:00Z",
         "message": {"model": "m", "usage": {"input_tokens": 1}}},
        {"type": "assistant", "sessionId": "2", "timestamp": "2026-04-30T00:00:00Z",
         "message": {"model": "m", "usage": {"input_tokens": 1}}},
        {"type": "assistant", "sessionId": "3", "timestamp": "2026-05-01T00:00:00Z",
         "message": {"model": "m", "usage": {"input_tokens": 1}}},
    ])
    entries = axt.load_all_claude_usage(projects, since="2026-04-30", until="2026-04-30T23:59:59Z")
    assert {e.session_id for e in entries} == {"2"}


def test_load_all_claude_usage_missing_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    assert axt.load_all_claude_usage(tmp_path / "nope") == []


# ─── Timezone helpers ────────────────────────────────────────────────────────


def test_date_in_tz_converts_to_local_day():
    # 23:30 UTC on the 29th is already the 30th in Seoul (UTC+9).
    assert axt._date_in_tz("2026-04-29T23:30:00Z", "Asia/Seoul") == "2026-04-30"


def test_date_in_tz_invalid_timezone_falls_back_to_utc_slice():
    """A bad timezone (e.g. from a corrupt config) must not crash usage
    grouping — it falls back to the UTC date slice."""
    assert axt._date_in_tz("2026-04-29T10:00:00Z", "Not/AZone") == "2026-04-29"


def test_date_in_tz_malformed_timestamp_falls_back_to_slice():
    assert axt._date_in_tz("garbage-date", "UTC") == "garbage-da"  # iso[:10]


def test_today_in_tz_invalid_timezone_falls_back_to_utc():
    from datetime import datetime, timezone
    expected = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert axt._today_in_tz("Not/AZone") == expected


# ─── Aggregation ─────────────────────────────────────────────────────────────


def _entry(sid: str, ts: str, model: str = "m", **tokens) -> axt.ClaudeUsageEntry:
    return axt.ClaudeUsageEntry(
        model=model,
        input_tokens=tokens.get("input", 0),
        output_tokens=tokens.get("output", 0),
        cache_creation_tokens=tokens.get("cw", 0),
        cache_read_tokens=tokens.get("cr", 0),
        session_id=sid,
        project_path="p",
        timestamp=ts,
    )


def test_aggregate_daily_groups_by_date():
    entries = [
        _entry("a", "2026-04-29T01:00:00Z", input=10),
        _entry("a", "2026-04-29T02:00:00Z", input=20),
        _entry("b", "2026-04-30T01:00:00Z", input=30),
    ]
    daily = axt.aggregate_daily(entries, "UTC")
    assert len(daily) == 2
    assert daily[0].date == "2026-04-29"
    assert daily[0].input_tokens == 30
    assert daily[0].sessions == 1  # both rows are session "a"
    assert daily[1].date == "2026-04-30"


def test_aggregate_by_session():
    entries = [
        _entry("s1", "2026-04-29T01:00:00Z", input=10),
        _entry("s1", "2026-04-29T02:00:00Z", input=20),
        _entry("s2", "2026-04-30T01:00:00Z", input=30),
    ]
    sessions = {s.session_id: s for s in axt.aggregate_by_session(entries)}
    assert sessions["s1"].input_tokens == 30
    assert sessions["s1"].message_count == 2
    assert sessions["s1"].first_timestamp == "2026-04-29T01:00:00Z"
    assert sessions["s1"].last_timestamp == "2026-04-29T02:00:00Z"


def test_compute_blocks_5h_utc_aligned():
    # 12:30 UTC falls in the 10:00–15:00 window.
    e = _entry("s", "2026-04-29T12:30:00Z", input=100)
    blocks = axt.compute_blocks([e], "UTC")
    assert len(blocks) == 1
    b = blocks[0]
    assert b.start_time.startswith("2026-04-29T10:00:00")
    assert b.end_time.startswith("2026-04-29T15:00:00")
    assert b.total_tokens == 100
    assert b.duration_hours == 5


def test_compute_blocks_multiple_windows():
    entries = [
        _entry("s", "2026-04-29T01:00:00Z", input=1),  # 00:00–05:00
        _entry("s", "2026-04-29T06:00:00Z", input=2),  # 05:00–10:00
        _entry("s", "2026-04-29T11:00:00Z", input=3),  # 10:00–15:00
    ]
    blocks = axt.compute_blocks(entries, "UTC")
    assert len(blocks) == 3
    # Sorted by start time.
    assert blocks[0].start_time < blocks[1].start_time < blocks[2].start_time


def test_compute_blocks_empty_input():
    assert axt.compute_blocks([], "UTC") == []


# ─── Filters ─────────────────────────────────────────────────────────────────


def test_filter_by_timestamp_ms():
    entries = [
        _entry("a", "2026-04-29T01:00:00Z"),
        _entry("b", "2026-04-30T01:00:00Z"),
        _entry("c", "2026-05-01T01:00:00Z"),
    ]
    since = axt._ts_ms("2026-04-30T00:00:00Z")
    until = axt._ts_ms("2026-04-30T23:59:59Z")
    filtered = axt.filter_by_timestamp_ms(entries, since, until)
    assert [e.session_id for e in filtered] == ["b"]


def test_filter_by_date_string():
    entries = [
        _entry("a", "2026-04-29T01:00:00Z"),
        _entry("b", "2026-04-30T01:00:00Z"),
        _entry("c", "2026-05-01T01:00:00Z"),
    ]
    filtered = axt.filter_by_date_string(entries, "2026-04-30", "2026-04-30")
    assert [e.session_id for e in filtered] == ["b"]
