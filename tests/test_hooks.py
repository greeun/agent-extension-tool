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


def test_extract_hooks_skips_malformed_entries(tmp_path: Path):
    """Non-dict rule, non-list hooks, and non-dict hook entries are all skipped."""
    settings = {
        "hooks": {
            "Stop": [
                "not-a-dict-rule",                              # rule not a dict → skip
                {"matcher": "*", "hooks": "not-a-list"},        # hooks not a list → skip
                {"matcher": "*", "hooks": [42, {"type": "command", "command": "ok"}]},  # non-dict hook skipped
            ]
        }
    }
    out = axt._extract_hooks(settings, "user", "/x")
    assert len(out) == 1
    assert out[0].command == "ok"


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


def test_get_hook_detail_mcp_tool():
    h = axt.HookInfo(event="Stop", matcher="*", source="user", source_path="/x", type="mcp_tool", server="srv", tool="run")
    assert axt.get_hook_detail(h) == "srv:run"


def test_get_hook_detail_unknown_type_empty():
    h = axt.HookInfo(event="Stop", matcher="*", source="user", source_path="/x", type="weird")
    assert axt.get_hook_detail(h) == ""


# ── preview_hook error branches ──────────────────────────────────────────────


def test_preview_hook_command_timeout(monkeypatch):
    import subprocess

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    h = axt.HookInfo(event="Stop", matcher="*", source="user", source_path="/x", type="command", command="sleep 999")
    res = axt.preview_hook(h, timeout_ms=2000)
    assert res.type == "command"
    assert res.error == "timeout after 2000ms"
    assert res.exit_code is None
    assert res.output is None


def test_preview_hook_command_oserror(monkeypatch):
    import subprocess

    def _raise_oserror(*args, **kwargs):
        raise OSError("sh not found")

    monkeypatch.setattr(subprocess, "run", _raise_oserror)
    h = axt.HookInfo(event="Stop", matcher="*", source="user", source_path="/x", type="command", command="whatever")
    res = axt.preview_hook(h)
    assert res.type == "command"
    assert res.error == "sh not found"
    assert res.summary == "whatever"


def test_preview_hook_command_nonzero_exit_and_stderr(tmp_path):
    h = axt.HookInfo(event="Stop", matcher="*", source="user", source_path="/x", type="command",
                     command="echo oops 1>&2; exit 3")
    res = axt.preview_hook(h)
    assert res.exit_code == 3
    assert "oops" in (res.error or "")
    assert res.output is None


def test_preview_hook_pretooluse_payload_includes_tool_name(monkeypatch):
    """PreToolUse hooks should receive a sampled tool_name on stdin (line ~878)."""
    import subprocess

    captured = {}
    real_run = subprocess.run

    def _capture(*args, **kwargs):
        captured["input"] = kwargs.get("input")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _capture)
    h = axt.HookInfo(event="PreToolUse", matcher="Write", source="user", source_path="/x",
                     type="command", command="cat")
    res = axt.preview_hook(h)
    assert res.exit_code == 0
    payload = json.loads(captured["input"])
    assert payload["tool_name"] == "Write"
    assert payload["hook_event"] == "PreToolUse"
    assert payload["tool_input"] == {}
    # Echoed back via `cat`.
    assert "Write" in (res.output or "")


def test_preview_hook_pretooluse_star_matcher_defaults_to_bash(monkeypatch):
    import subprocess

    captured = {}
    real_run = subprocess.run

    def _capture(*args, **kwargs):
        captured["input"] = kwargs.get("input")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _capture)
    h = axt.HookInfo(event="PreToolUse", matcher="*", source="user", source_path="/x",
                     type="command", command="cat")
    axt.preview_hook(h)
    assert json.loads(captured["input"])["tool_name"] == "Bash"


def test_preview_hook_prompt_returns_prompt_body():
    h = axt.HookInfo(event="UserPromptSubmit", matcher="*", source="user", source_path="/x",
                     type="prompt", prompt="Inject this instruction.")
    res = axt.preview_hook(h)
    assert res.type == "prompt"
    assert res.output == "Inject this instruction."


def test_preview_hook_agent_no_prompt_placeholder():
    h = axt.HookInfo(event="Stop", matcher="*", source="user", source_path="/x", type="agent")
    res = axt.preview_hook(h)
    assert res.type == "agent"
    assert res.output == "(no prompt)"


# ── list_hooks: plugin scope ─────────────────────────────────────────────────


def test_list_hooks_includes_plugin_hooks(tmp_path: Path):
    install = tmp_path / "plug"
    (install / "hooks").mkdir(parents=True)
    (install / "hooks" / "hooks.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "plug-cmd"}]}]}})
    )
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "p@m": [{"scope": "user", "installPath": str(install), "version": "9.9",
                     "installedAt": "", "lastUpdated": ""}]
        },
    }))
    hooks = axt.list_hooks(user_settings_path=tmp_path / "nope.json", installed_plugins_path=ip)
    assert len(hooks) == 1
    h = hooks[0]
    assert h.source == "plugin"
    assert h.command == "plug-cmd"
    assert h.matcher == "Edit"
    assert h.version == "9.9"


def test_list_hooks_plugin_path_missing_hooks_json(tmp_path: Path):
    """A plugin without hooks/hooks.json contributes nothing (continue branch)."""
    install = tmp_path / "plug"
    install.mkdir()
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "p@m": [{"scope": "user", "installPath": str(install), "version": "1",
                     "installedAt": "", "lastUpdated": ""}]
        },
    }))
    hooks = axt.list_hooks(user_settings_path=tmp_path / "nope.json", installed_plugins_path=ip)
    assert hooks == []
