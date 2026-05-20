"""Tests for Section 6 — Codex + Gemini parsers and rate-limit extraction."""
from __future__ import annotations

import json
from pathlib import Path

import axt


# ─── Codex ───────────────────────────────────────────────────────────────────


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_parse_codex_file(tmp_path: Path):
    f = tmp_path / "proj-x" / "sess001.jsonl"
    _write_jsonl(f, [
        {"type": "session_meta", "timestamp": "2026-04-29T00:00:00Z",
         "payload": {"model": "gpt-5.3-codex", "session_id": "codex-001"}},
        {"type": "event_msg", "timestamp": "2026-04-29T01:00:00Z",
         "payload": {"type": "token_count", "info": {
             "last_token_usage": {
                 "input_tokens": 100,
                 "cached_input_tokens": 80,
                 "output_tokens": 50,
                 "reasoning_output_tokens": 10,
             }
         }}},
    ])
    entries = axt.parse_codex_file(f)
    assert len(entries) == 1
    e = entries[0]
    assert e.platform == "codex"
    assert e.model == "gpt-5.3-codex"
    assert e.session_id == "codex-001"
    assert e.input_tokens == 100
    assert e.output_tokens == 50
    assert e.cache_read_tokens == 80
    assert e.reasoning_tokens == 10
    assert e.cache_write_tokens == 0
    assert e.project_path == "proj-x"


def test_parse_codex_file_skips_non_token_count_events(tmp_path: Path):
    f = tmp_path / "p" / "s.jsonl"
    _write_jsonl(f, [
        {"type": "session_meta", "payload": {"model": "gpt-5"}},
        {"type": "event_msg", "payload": {"type": "user_message", "text": "hi"}},
    ])
    assert axt.parse_codex_file(f) == []


def test_extract_codex_rate_limit(tmp_path: Path):
    f = tmp_path / "p" / "s.jsonl"
    _write_jsonl(f, [
        {"type": "session_meta", "payload": {"model": "gpt-5"}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 1}
        }, "rate_limits": {"primary": {
            "used_percent": 42.0,
            "window_minutes": 300,
            "resets_at": "2026-04-29T15:00:00Z",
        }}}},
    ])
    rl = axt.extract_codex_rate_limit(f)
    assert rl is not None
    assert rl.platform == "codex"
    assert rl.used_percent == 42.0
    assert rl.window_minutes == 300
    assert rl.resets_at == "2026-04-29T15:00:00Z"


def test_extract_codex_rate_limit_picks_most_recent(tmp_path: Path):
    """Should scan from end-of-file backwards and pick the FIRST hit."""
    f = tmp_path / "p" / "s.jsonl"
    _write_jsonl(f, [
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 1}
        }, "rate_limits": {"primary": {"used_percent": 10}}}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 1}
        }, "rate_limits": {"primary": {"used_percent": 99}}}},
    ])
    rl = axt.extract_codex_rate_limit(f)
    assert rl is not None and rl.used_percent == 99


def test_extract_codex_rate_limit_missing_file(tmp_path: Path):
    assert axt.extract_codex_rate_limit(tmp_path / "nope.jsonl") is None


def test_load_codex_usage_filters_by_date(tmp_path: Path):
    sessions = tmp_path / "sessions"
    _write_jsonl(sessions / "p" / "a.jsonl", [
        {"type": "session_meta", "payload": {"model": "gpt-5"}},
        {"type": "event_msg", "timestamp": "2026-04-29T01:00:00Z",
         "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 1}}}},
        {"type": "event_msg", "timestamp": "2026-04-30T01:00:00Z",
         "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 2}}}},
    ])
    entries = axt.load_codex_usage(sessions, since="2026-04-30")
    assert len(entries) == 1
    assert entries[0].input_tokens == 2


def test_load_codex_usage_missing_dir(tmp_path: Path):
    assert axt.load_codex_usage(tmp_path / "nope") == []


# ─── Gemini ──────────────────────────────────────────────────────────────────


def test_parse_gemini_json(tmp_path: Path):
    f = tmp_path / "myproj" / "chats" / "session-abc.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({
        "sessionId": "gem-001",
        "messages": [
            {"role": "user", "content": "hi"},  # ignored
            {
                "role": "gemini",
                "timestamp": "2026-04-29T01:00:00Z",
                "model": "gemini-2.5-pro",
                "tokens": {
                    "input": 150,
                    "output": 45,
                    "cached": 100,
                    "thoughts": 20,
                    "tool": 5,
                    "total": 320,
                },
            },
        ],
    }))
    entries = axt.parse_gemini_file(f)
    assert len(entries) == 1
    e = entries[0]
    assert e.platform == "gemini"
    assert e.model == "gemini-2.5-pro"
    assert e.session_id == "gem-001"
    assert e.input_tokens == 150
    assert e.cache_read_tokens == 100
    assert e.reasoning_tokens == 20
    assert e.tool_tokens == 5
    assert e.project_path == "myproj"


def test_parse_gemini_jsonl_uses_first_record_only(tmp_path: Path):
    f = tmp_path / "p" / "chats" / "session-1.jsonl"
    f.parent.mkdir(parents=True)
    # Only first record is read (TS parity).
    f.write_text(
        json.dumps({"sessionId": "x", "messages": [
            {"role": "gemini", "timestamp": "2026-04-29T01:00:00Z", "model": "g",
             "tokens": {"input": 10, "output": 20, "cached": 0, "thoughts": 0, "tool": 0, "total": 30}}
        ]}) + "\n"
        + json.dumps({"sessionId": "y", "messages": []}) + "\n"
    )
    entries = axt.parse_gemini_file(f)
    assert len(entries) == 1
    assert entries[0].session_id == "x"


def test_parse_gemini_skips_non_gemini_role(tmp_path: Path):
    f = tmp_path / "p" / "chats" / "session-1.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"messages": [
        {"role": "user", "tokens": {"input": 1, "output": 1, "cached": 0, "thoughts": 0, "tool": 0, "total": 2}},
        {"role": "system"},
    ]}))
    assert axt.parse_gemini_file(f) == []


def test_load_gemini_usage_globs_chats_dirs(tmp_path: Path):
    base = tmp_path / "tmp"
    for proj in ("a", "b"):
        (base / proj / "chats").mkdir(parents=True)
        (base / proj / "chats" / "session-1.json").write_text(json.dumps({
            "sessionId": f"sess-{proj}",
            "messages": [{
                "role": "gemini",
                "timestamp": "2026-04-30T01:00:00Z",
                "model": "g",
                "tokens": {"input": 1, "output": 1, "cached": 0, "thoughts": 0, "tool": 0, "total": 2},
            }],
        }))
    entries = axt.load_gemini_usage(base)
    assert {e.session_id for e in entries} == {"sess-a", "sess-b"}


def test_load_gemini_usage_filters_by_date(tmp_path: Path):
    base = tmp_path / "tmp"
    (base / "p" / "chats").mkdir(parents=True)
    (base / "p" / "chats" / "session-1.json").write_text(json.dumps({
        "messages": [
            {"role": "gemini", "timestamp": "2026-04-29T01:00:00Z", "model": "g",
             "tokens": {"input": 1, "output": 0, "cached": 0, "thoughts": 0, "tool": 0, "total": 1}},
            {"role": "gemini", "timestamp": "2026-04-30T01:00:00Z", "model": "g",
             "tokens": {"input": 2, "output": 0, "cached": 0, "thoughts": 0, "tool": 0, "total": 2}},
        ],
    }))
    entries = axt.load_gemini_usage(base, since="2026-04-30")
    assert len(entries) == 1
    assert entries[0].input_tokens == 2


def test_load_gemini_usage_missing_dir(tmp_path: Path):
    assert axt.load_gemini_usage(tmp_path / "nope") == []


# ─── Unified loader ──────────────────────────────────────────────────────────


def test_load_unified_usage_combines_platforms(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    claude_dir = tmp_path / "claude"
    _write_jsonl(claude_dir / "p" / "s.jsonl", [{
        "type": "assistant", "sessionId": "cl-1", "timestamp": "2026-04-29T10:00:00Z",
        "message": {"model": "claude-opus-4-7", "usage": {"input_tokens": 1}},
    }])
    codex_dir = tmp_path / "codex"
    _write_jsonl(codex_dir / "p" / "s.jsonl", [
        {"type": "session_meta", "payload": {"model": "gpt-5"}},
        {"type": "event_msg", "timestamp": "2026-04-30T10:00:00Z",
         "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 1}}}},
    ])
    gemini_dir = tmp_path / "gemini"
    (gemini_dir / "p" / "chats").mkdir(parents=True)
    (gemini_dir / "p" / "chats" / "session-1.json").write_text(json.dumps({
        "messages": [{
            "role": "gemini", "timestamp": "2026-05-01T10:00:00Z", "model": "gemini-2.5-pro",
            "tokens": {"input": 1, "output": 0, "cached": 0, "thoughts": 0, "tool": 0, "total": 1},
        }],
    }))

    all_entries = axt.load_unified_usage(
        claude_projects_dir=claude_dir,
        codex_sessions_dir=codex_dir,
        gemini_tmp_dir=gemini_dir,
    )
    platforms = [e.platform for e in all_entries]
    assert "claude" in platforms and "codex" in platforms and "gemini" in platforms
    # Sorted by timestamp ascending.
    assert [e.timestamp for e in all_entries] == sorted([e.timestamp for e in all_entries])


def test_load_unified_usage_platform_filter(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "cache")
    claude_dir = tmp_path / "claude"
    _write_jsonl(claude_dir / "p" / "s.jsonl", [{
        "type": "assistant", "sessionId": "c", "timestamp": "2026-04-29T10:00:00Z",
        "message": {"model": "m", "usage": {"input_tokens": 1}},
    }])
    only_claude = axt.load_unified_usage(
        claude_projects_dir=claude_dir,
        codex_sessions_dir=tmp_path / "codex",
        gemini_tmp_dir=tmp_path / "gemini",
        platform="claude",
    )
    assert all(e.platform == "claude" for e in only_claude)
