"""Tests for Section 4 — hook extraction and preview."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import axt


def test_hook_events_match_spec():
    # 29 events (TS source of truth). FEATURES.md had said 28; the discrepancy
    # was an off-by-one in the inventory writeup — corrected during porting.
    assert len(axt.HOOK_EVENTS) == 29
    assert "SessionStart" in axt.HOOK_EVENTS
    assert "Notification" in axt.HOOK_EVENTS
    # All events are unique.
    assert len(set(axt.HOOK_EVENTS)) == len(axt.HOOK_EVENTS)


def test_extract_hooks_simple(tmp_path: Path):
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "echo hi", "timeout": 1000},
                    ],
                }
            ]
        }
    }
    out = axt._extract_hooks(settings, "user", "/x/settings.json")
    assert len(out) == 1
    h = out[0]
    assert h.event == "PreToolUse"
    assert h.matcher == "Bash"
    assert h.type == "command"
    assert h.command == "echo hi"
    assert h.timeout == 1000
    assert h.source == "user"


def test_extract_hooks_defaults_matcher_to_star(tmp_path: Path):
    settings = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "x"}]}]}}
    out = axt._extract_hooks(settings, "user", "/x")
    assert out[0].matcher == "*"


def test_extract_hooks_skips_unknown_event(tmp_path: Path):
    settings = {"hooks": {"BogusEvent": [{"matcher": "*", "hooks": [{"type": "command", "command": "x"}]}]}}
    assert axt._extract_hooks(settings, "user", "/x") == []


def test_extract_hooks_defaults_type_to_command(tmp_path: Path):
    settings = {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"command": "x"}]}]}}
    out = axt._extract_hooks(settings, "user", "/x")
    assert out[0].type == "command"


def test_extract_hooks_handles_http_and_mcp(tmp_path: Path):
    settings = {
        "hooks": {
            "PostToolUse": [{
                "matcher": "Write",
                "hooks": [
                    {"type": "http", "url": "https://example/hook"},
                    {"type": "mcp_tool", "server": "s1", "tool": "t1"},
                ],
            }]
        }
    }
    out = axt._extract_hooks(settings, "user", "/x")
    assert len(out) == 2
    assert out[0].type == "http" and out[0].url == "https://example/hook"
    assert out[1].type == "mcp_tool" and out[1].server == "s1" and out[1].tool == "t1"


def test_list_hooks_merges_three_scopes(tmp_path: Path):
    user_path = tmp_path / "user-settings.json"
    user_path.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "user"}]}]}}))
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "proj"}]}]}}))
    (proj / ".claude" / "settings.local.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "local"}]}]}}))

    hooks = axt.list_hooks(user_settings_path=user_path, project_dir=proj)
    sources = {h.source for h in hooks}
    assert sources == {"user", "project", "local"}
    commands = sorted(h.command for h in hooks if h.command)
    assert commands == ["local", "proj", "user"]


def test_list_hooks_no_user_file_returns_other_scopes(tmp_path: Path):
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "proj"}]}]}}))
    hooks = axt.list_hooks(user_settings_path=tmp_path / "nope.json", project_dir=proj)
    assert len(hooks) == 1
    assert hooks[0].source == "project"


def test_preview_hook_command_runs(tmp_path: Path):
    h = axt.HookInfo(event="SessionStart", matcher="*", source="user", source_path="/x", type="command", command="echo HELLO")
    res = axt.preview_hook(h)
    assert res.type == "command"
    assert "HELLO" in (res.output or "")
    assert res.exit_code == 0


def test_preview_hook_command_missing_command(tmp_path: Path):
    h = axt.HookInfo(event="Stop", matcher="*", source="user", source_path="/x", type="command")
    res = axt.preview_hook(h)
    assert res.summary == "(no command)"


def test_preview_hook_http_returns_formatted_body(tmp_path: Path):
    h = axt.HookInfo(event="UserPromptSubmit", matcher="*", source="user", source_path="/x", type="http", url="https://example.com/hook")
    res = axt.preview_hook(h)
    assert res.type == "http"
    assert "https://example.com/hook" in (res.output or "")
    assert "POST" in (res.output or "")


def test_preview_hook_mcp(tmp_path: Path):
    h = axt.HookInfo(event="Stop", matcher="*", source="user", source_path="/x", type="mcp_tool", server="srv", tool="t")
    res = axt.preview_hook(h)
    assert res.summary == "srv:t"
    assert "Server: srv" in (res.output or "")


def test_get_hook_detail():
    h = axt.HookInfo(event="SessionStart", matcher="*", source="user", source_path="/x", type="command", command="ls -la")
    assert axt.get_hook_detail(h) == "ls -la"
    h = axt.HookInfo(event="SessionStart", matcher="*", source="user", source_path="/x", type="http", url="https://x")
    assert axt.get_hook_detail(h) == "https://x"
    h = axt.HookInfo(event="SessionStart", matcher="*", source="user", source_path="/x", type="prompt", prompt="A very long prompt " * 10)
    assert len(axt.get_hook_detail(h)) == 60
