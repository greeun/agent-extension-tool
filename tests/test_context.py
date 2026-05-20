"""Tests for Section 8 — context source collection and analysis."""
from __future__ import annotations

import json
from pathlib import Path

import axt


def test_estimate_tokens_empty():
    assert axt.estimate_tokens("") == 0


def test_estimate_tokens_ascii_only():
    # 35 chars → ceil(35/3.5) = 10
    assert axt.estimate_tokens("a" * 35) == 10


def test_estimate_tokens_korean():
    # Each Korean char is 1/1.5 ≈ 0.67 tokens.
    # 3 Korean chars → ceil(3/1.5) = 2
    assert axt.estimate_tokens("한글로") == 2


def test_estimate_tokens_mixed():
    # 3 Korean (~2) + 7 ASCII (~2) = ceil(2/1.5 + 7/3.5) = ceil(2 + 2) = 4
    assert axt.estimate_tokens("한글로 hello!") == 4


def test_collect_context_minimum(tmp_path: Path, monkeypatch):
    """Collecting in an empty project produces at least the 4 fixed sources."""
    home = tmp_path / "home"
    home.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    ip = tmp_path / "installed_plugins.json"

    # Avoid spawning real git/claude.
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0-test")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj, installed_plugins_path=ip,
    )
    categories = {s.category for s in sources}
    # Always present (fixed sources).
    assert "system-prompt" in categories
    assert "git-status" in categories
    assert "user-context" in categories
    # Percentages sum to ~100%.
    pct_sum = sum(s.percentage for s in sources)
    assert abs(pct_sum - 100.0) < 0.5


def test_collect_context_with_claude_md(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.md").write_text("Project guidance here.")
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj, installed_plugins_path=tmp_path / "ip.json",
    )
    claude_mds = [s for s in sources if s.category == "claude-md"]
    assert len(claude_mds) == 1
    assert "CLAUDE.md (project)" in claude_mds[0].name


def test_analyze_context_includes_cost_impact(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")

    analysis = axt.analyze_context(
        home_dir=home, project_dir=proj,
        installed_plugins_path=tmp_path / "ip.json",
        model="claude-opus-4-7",
        avg_turns_per_session=10,
        avg_sessions_per_day=2,
    )
    assert analysis.total_tokens > 0
    assert analysis.context_window_size == 1_000_000
    assert 0 < analysis.used_percent < 100
    assert analysis.cost_impact.model == "claude-opus-4-7"
    # 9 turn-reads + 1 write, with positive token total.
    assert analysis.cost_impact.per_session_cost > 0


def test_add_context_hints_classifies_categories():
    sources = [
        axt.ContextSource(name="System Prompt", category="system-prompt", path="", chars=0,
                          estimated_tokens=4200, percentage=0, actionable=False, hint=None, content=None),
        axt.ContextSource(name="Big CLAUDE.md", category="claude-md", path="", chars=0,
                          estimated_tokens=900, percentage=0, actionable=True, hint=None, content=None),
        axt.ContextSource(name="Small Skill", category="skills", path="", chars=0,
                          estimated_tokens=20, percentage=0, actionable=True, hint=None, content=None),
        axt.ContextSource(name="MCP X", category="mcp-tools", path="", chars=0,
                          estimated_tokens=5, percentage=0, actionable=False, hint=None, content=None),
    ]
    axt.add_context_hints(sources)
    assert "fixed" in sources[0].hint
    assert "review for unnecessary sections" in sources[1].hint
    assert sources[3].hint == "deferred — minimal context impact"


def test_build_system_prompt_preview_contains_version():
    out = axt.build_system_prompt_preview("0.5.1")
    assert "v0.5.1" in out
    assert "Tool definitions" in out


def test_build_user_context_preview_lists_environment(tmp_path: Path):
    out = axt.build_user_context_preview(tmp_path / "home", tmp_path / "proj")
    assert "homeDir" in out
    assert "projectDir" in out
    assert "currentDate" in out


def test_build_hook_preview():
    h = axt.HookInfo(event="SessionStart", matcher="*", source="user", source_path="/x",
                     type="command", command="echo hi", timeout=5000)
    out = axt.build_hook_preview(h)
    assert "Hook: SessionStart" in out
    assert "Command: echo hi" in out
    assert "Timeout: 5000ms" in out


def test_category_labels_complete():
    """Every category in source code should have a human-readable label."""
    expected = {"system-prompt", "claude-md", "settings", "memory", "skills",
                "mcp-tools", "plugins", "hooks", "commands", "agents",
                "git-status", "user-context"}
    assert set(axt.CATEGORY_LABELS.keys()) == expected
