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


def test_filter_by_date_string_no_bounds_returns_all():
    """No since/until → early return of the same list (line 2334)."""
    entries = [_entry("a", "2026-04-29T01:00:00Z"), _entry("b", "2026-04-30T01:00:00Z")]
    out = axt.filter_by_date_string(entries, None, None)
    assert out is entries


def test_filter_by_timestamp_ms_skips_unparseable(monkeypatch):
    """An entry whose timestamp won't parse is dropped, not crashed on
    (line 2316)."""
    entries = [
        _entry("good", "2026-04-30T01:00:00Z"),
        _entry("bad", "totally-not-a-timestamp"),
    ]
    since = axt._ts_ms("2026-04-30T00:00:00Z")
    until = axt._ts_ms("2026-04-30T23:59:59Z")
    filtered = axt.filter_by_timestamp_ms(entries, since, until)
    assert [e.session_id for e in filtered] == ["good"]


# ─── _ts_ms edge cases ───────────────────────────────────────────────────────


def test_ts_ms_empty_string_returns_none():
    """Empty input short-circuits to None (line 2251)."""
    assert axt._ts_ms("") is None


def test_ts_ms_malformed_returns_none():
    """Unparseable ISO string hits the except branch (lines 2258-2259)."""
    assert axt._ts_ms("not-an-iso-timestamp") is None


def test_ts_ms_roundtrip_with_z_suffix():
    # Sanity: a valid Z-suffixed timestamp parses to a positive epoch ms.
    ms = axt._ts_ms("2026-04-29T00:00:00Z")
    assert ms == 1777420800000


# ─── parse_claude_jsonl extra branches ───────────────────────────────────────


def test_parse_claude_jsonl_skips_blank_lines_and_non_dict_message(tmp_path: Path):
    """Blank lines (2272) and a record whose `message` is not a dict (2281)
    are both skipped without raising."""
    f = tmp_path / "proj" / "sess.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text(
        "\n"  # blank line → line 2272 continue
        "   \n"  # whitespace-only line → also 2272
        + json.dumps({"type": "assistant", "message": "a string not a dict"})  # 2281
        + "\n"
        + json.dumps({
            "type": "assistant",
            "sessionId": "s1",
            "timestamp": "2026-04-29T10:00:00Z",
            "message": {"model": "m", "usage": {"input_tokens": 7}},
        })
        + "\n"
    )
    entries = axt.parse_claude_jsonl(f)
    assert len(entries) == 1
    assert entries[0].input_tokens == 7


# ─── Cache helpers ───────────────────────────────────────────────────────────


def test_file_mtime_ms_missing_file_returns_zero(tmp_path: Path):
    """A nonexistent path returns 0.0 instead of raising (lines 2359-2360)."""
    assert axt._file_mtime_ms(tmp_path / "no-such-file") == 0.0


def test_file_mtime_ms_existing_file_is_positive(tmp_path: Path):
    f = tmp_path / "f.txt"
    f.write_text("x")
    assert axt._file_mtime_ms(f) > 0


def test_is_cache_valid_bad_last_updated_returns_false():
    """An unparseable lastUpdated is treated as invalid (line 2381)."""
    assert axt.is_cache_valid({"lastUpdated": "garbage"}) is False


def test_is_cache_valid_missing_last_updated_returns_false():
    assert axt.is_cache_valid({}) is False


def test_is_cache_valid_fresh_timestamp_is_valid():
    from datetime import datetime, timezone
    fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    assert axt.is_cache_valid({"lastUpdated": fresh}) is True


def test_load_all_claude_usage_empty_dir_no_jsonl(tmp_path: Path, monkeypatch):
    """A projects dir that exists but has no `*/*.jsonl` returns [] (line 2453)."""
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    projects = tmp_path / "projects"
    (projects / "empty").mkdir(parents=True)  # dir exists, no jsonl inside
    assert axt.load_all_claude_usage(projects) == []


def test_load_all_claude_usage_per_file_cache_hit_skips_reparse(tmp_path: Path, monkeypatch):
    """On a second pass within the same projectsDir but force_refresh (so the
    whole-cache validity gate is bypassed), an unchanged file is skipped via
    its mtime (line 2465: `continue`)."""
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    projects = tmp_path / "projects"
    f = projects / "proj" / "s.jsonl"
    _write_jsonl(f, [{
        "type": "assistant", "sessionId": "1", "timestamp": "2026-04-29T10:00:00Z",
        "message": {"model": "m", "usage": {"input_tokens": 5}},
    }])
    first = axt.load_all_claude_usage(projects, force_refresh=True)
    assert len(first) == 1
    # force_refresh again: whole-cache gate skipped, but the file's mtime is
    # unchanged so parse_claude_jsonl is NOT re-run — the cached entry is used.
    second = axt.load_all_claude_usage(projects, force_refresh=True)
    assert len(second) == 1
    assert second[0].input_tokens == 5


# ─── Unified loader + adapter ────────────────────────────────────────────────


def test_claude_to_unified_and_back_roundtrip():
    ce = _entry("s9", "2026-04-29T10:00:00Z", input=10, output=20, cw=30, cr=40)
    uni = axt.claude_to_unified(ce)
    assert uni.platform == "claude"
    assert uni.cache_write_tokens == 30
    assert uni.cache_read_tokens == 40
    back = axt._unified_to_claude(uni)
    assert back == ce


def test_load_unified_usage_sorts_and_normalizes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    projects = tmp_path / "projects"
    _write_jsonl(projects / "p" / "s.jsonl", [
        {"type": "assistant", "sessionId": "late", "timestamp": "2026-04-30T10:00:00Z",
         "message": {"model": "m", "usage": {"input_tokens": 2}}},
        {"type": "assistant", "sessionId": "early", "timestamp": "2026-04-29T10:00:00Z",
         "message": {"model": "m", "usage": {"input_tokens": 1}}},
    ])
    out = axt.load_unified_usage(claude_projects_dir=projects)
    assert [e.session_id for e in out] == ["early", "late"]
    assert all(e.platform == "claude" for e in out)


def test_load_unified_usage_swallows_oserror(tmp_path: Path, monkeypatch):
    """If the underlying loader raises OSError, load_unified_usage returns []
    rather than propagating (lines 2621-2622)."""
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")

    def boom(*args, **kwargs):
        raise OSError("disk gone")

    monkeypatch.setattr("axt.load_all_claude_usage", boom)
    assert axt.load_unified_usage(claude_projects_dir=tmp_path) == []


# ─── compute_blocks extra branches ───────────────────────────────────────────


def test_compute_blocks_skips_entry_with_bad_timestamp():
    """An entry whose timestamp is unparseable is dropped; only the good
    entry forms a block (line 2785)."""
    good = _entry("s", "2026-04-29T12:30:00Z", input=50)
    bad = _entry("s", "broken-timestamp", input=999)
    blocks = axt.compute_blocks([good, bad], "UTC")
    assert len(blocks) == 1
    assert blocks[0].total_tokens == 50


def test_compute_blocks_active_block_has_burn_rate():
    """An entry inside the current 5-hour window yields an active block with a
    positive burn rate (lines 2810-2811)."""
    from datetime import datetime, timedelta, timezone
    # Anchor the entry inside the CURRENT 5h UTC block (blocks align to
    # 00/05/10/15/20:00 UTC). `now - 10min` is flaky for 10 minutes after each
    # boundary, when that timestamp falls into the *previous*, now-inactive
    # window.
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    block_idx = int((now - midnight).total_seconds() // (5 * 3600))
    window_start = midnight + timedelta(hours=5 * block_idx)
    iso = (window_start + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    e = _entry("s", iso, input=600)
    blocks = axt.compute_blocks([e], "UTC")
    assert len(blocks) == 1
    b = blocks[0]
    assert b.is_active is True
    assert b.burn_rate_per_min is not None
    assert b.burn_rate_per_min > 0
    assert b.total_tokens == 600


def test_compute_blocks_inactive_block_has_no_burn_rate():
    """A historical window is inactive and reports no burn rate."""
    e = _entry("s", "2020-01-01T12:30:00Z", input=100)
    blocks = axt.compute_blocks([e], "UTC")
    assert blocks[0].is_active is False
    assert blocks[0].burn_rate_per_min is None


def test_compute_blocks_cost_uses_model_pricing_not_hardcoded_opus():
    """Block cost must come from the per-model pricing table, so a Sonnet
    block is priced at Sonnet rates — not the old hardcoded Opus rates."""
    e = _entry("s", "2026-04-29T12:30:00Z", model="claude-sonnet-4-6",
               input=1_000_000, output=1_000_000)
    blocks = axt.compute_blocks([e], "UTC")
    assert len(blocks) == 1
    # sonnet-4-6: input 3.00 + output 15.00 per million = 18.00
    # (hardcoded Opus rates would have yielded 15.00 + 75.00 = 90.00).
    assert blocks[0].cost == pytest.approx(18.0)


def test_compute_blocks_cost_sums_per_entry_across_models():
    """A block mixing models sums each entry's own model rate."""
    entries = [
        _entry("s", "2026-04-29T12:00:00Z", model="claude-opus-4-7", input=1_000_000),
        _entry("s", "2026-04-29T12:10:00Z", model="claude-haiku-4-5", input=1_000_000),
    ]
    blocks = axt.compute_blocks(entries, "UTC")
    assert len(blocks) == 1  # both fall in the 10:00–15:00 window
    # opus input 15.00 + haiku input 0.80
    assert blocks[0].cost == pytest.approx(15.80)
