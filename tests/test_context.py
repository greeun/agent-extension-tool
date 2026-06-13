"""Tests for Section 8 — context source collection and analysis."""
from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import axt


def _mk_entry(model: str, timestamp: str) -> axt.UnifiedUsageEntry:
    return axt.UnifiedUsageEntry(
        platform="claude", model=model, timestamp=timestamp,
        session_id="s", project_path="p",
        input_tokens=1, output_tokens=1, cache_write_tokens=0, cache_read_tokens=0,
    )


def _write_transcript(path: Path, model: str, timestamp: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "type": "assistant", "timestamp": timestamp,
        "message": {"model": model, "usage": {"input_tokens": 1, "output_tokens": 1}},
    }) + "\n")


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


def test_context_source_scope_classification(tmp_path: Path, monkeypatch):
    """Project files are scope='project'; global/user/fixed sources stay 'global'."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    proj = tmp_path / "proj"
    proj.mkdir()
    (home / "CLAUDE.md").write_text("Global guidance.")
    (proj / "CLAUDE.md").write_text("Project guidance.")
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj, installed_plugins_path=tmp_path / "ip.json",
    )
    by_name = {s.name: s for s in sources}
    assert by_name["CLAUDE.md (project)"].scope == "project"
    assert by_name["CLAUDE.md (global)"].scope == "global"
    # Fixed baseline sources are always global; git-status follows the project.
    assert by_name["System Prompt"].scope == "global"
    assert by_name["User Context"].scope == "global"
    assert by_name["Git Status"].scope == "project"


def test_context_rows_group_by_scope_project_first(tmp_path: Path, monkeypatch):
    """_context_rows splits a category into (category, scope) rows and orders
    every project row ahead of every global row."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    proj = tmp_path / "proj"
    proj.mkdir()
    (home / "CLAUDE.md").write_text("Global guidance, fairly long " * 5)
    (proj / "CLAUDE.md").write_text("Project guidance.")
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")

    analysis = axt.analyze_context(
        home_dir=home, project_dir=proj,
        installed_plugins_path=tmp_path / "ip.json", model="claude-opus-4-8",
    )
    rows = axt._context_rows(analysis)
    # claude-md appears twice — once per scope — not collapsed into one row.
    claude_rows = [r for r in rows if r.category == "claude-md"]
    assert {r.scope for r in claude_rows} == {"project", "global"}
    # No global row precedes any project row.
    scopes = [r.scope for r in rows]
    last_project = max((i for i, s in enumerate(scopes) if s == "project"), default=-1)
    first_global = min((i for i, s in enumerate(scopes) if s == "global"), default=len(scopes))
    assert last_project < first_global


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


def test_detect_current_model_prefers_most_recent_entry(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    entries = [
        _mk_entry("claude-opus-4-6", "2026-05-01T00:00:00Z"),
        _mk_entry("claude-opus-4-8", "2026-05-30T00:00:00Z"),
    ]
    assert axt.detect_current_model(entries) == "claude-opus-4-8"


def test_detect_current_model_skips_unknown_and_synthetic(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    entries = [
        _mk_entry("claude-opus-4-8", "2026-05-01T00:00:00Z"),
        _mk_entry("unknown", "2026-05-30T00:00:01Z"),
        _mk_entry("<synthetic>", "2026-05-30T00:00:02Z"),
    ]
    # Falls back past the trailing non-real models to the real one.
    assert axt.detect_current_model(entries) == "claude-opus-4-8"


def test_detect_current_model_env_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    entries = [_mk_entry("claude-opus-4-8", "2026-05-30T00:00:00Z")]
    assert axt.detect_current_model(entries) == "claude-sonnet-4-6"


def test_detect_current_model_scans_transcripts(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    projects = tmp_path / "projects"
    f = projects / "proj" / "sess.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text("\n".join(json.dumps(r) for r in [
        {"type": "assistant", "timestamp": "2026-05-30T00:00:00Z",
         "message": {"model": "claude-opus-4-8", "usage": {"input_tokens": 1, "output_tokens": 1}}},
    ]) + "\n")
    monkeypatch.setattr("axt.core.PATHS", SimpleNamespace(projects=projects))
    # No entries passed → must discover the model from the newest transcript.
    assert axt.detect_current_model() == "claude-opus-4-8"


def test_detect_current_model_fallback_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.setattr("axt.core.PATHS", SimpleNamespace(projects=tmp_path / "empty"))
    assert axt.detect_current_model() == axt.DEFAULT_MODEL
    assert axt.DEFAULT_MODEL == "claude-opus-4-8"


def test_detect_current_model_scopes_to_project_dir(tmp_path: Path, monkeypatch):
    """The session in *this* project dir wins over a globally more-recent
    transcript from a different project (concurrent session contamination)."""
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    import os as _os
    projects = tmp_path / "projects"
    cwd = tmp_path / "myproj"
    enc = str(cwd).replace("/", "-").replace(".", "-")
    _write_transcript(projects / enc / "s.jsonl", "claude-opus-4-8", "2026-05-30T00:00:00Z")
    other = projects / "-some-other-proj" / "s.jsonl"
    _write_transcript(other, "claude-opus-4-7", "2026-05-30T00:00:00Z")
    _os.utime(other, (3_000_000_000, 3_000_000_000))  # globally newest
    monkeypatch.setattr("axt.core.PATHS", SimpleNamespace(projects=projects))

    assert axt.detect_current_model(project_dir=cwd) == "claude-opus-4-8"
    # Proof the scoping matters: unscoped picks the contaminating session.
    assert axt.detect_current_model() == "claude-opus-4-7"


def test_detect_current_model_project_dir_without_transcripts_falls_back(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    projects = tmp_path / "projects"
    _write_transcript(projects / "-some-proj" / "s.jsonl", "claude-opus-4-7", "2026-05-30T00:00:00Z")
    monkeypatch.setattr("axt.core.PATHS", SimpleNamespace(projects=projects))
    # cwd has no transcript dir → fall back to the global most-recent.
    assert axt.detect_current_model(project_dir=tmp_path / "no-session") == "claude-opus-4-7"


def test_detect_current_model_synthetic_only_transcript_falls_back(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    projects = tmp_path / "projects"
    f = projects / "proj" / "sess.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text("\n".join(json.dumps(r) for r in [
        {"type": "assistant", "timestamp": "2026-05-30T00:00:00Z",
         "message": {"model": "<synthetic>", "usage": {"input_tokens": 1, "output_tokens": 1}}},
    ]) + "\n")
    monkeypatch.setattr("axt.core.PATHS", SimpleNamespace(projects=projects))
    # Newest transcript carries no real model → fall through to the default.
    assert axt.detect_current_model() == axt.DEFAULT_MODEL


def test_analyze_context_default_model_is_current(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    proj = tmp_path / "proj"; proj.mkdir()
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    analysis = axt.analyze_context(
        home_dir=home, project_dir=proj, installed_plugins_path=tmp_path / "ip.json",
    )
    assert analysis.model == axt.DEFAULT_MODEL


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


# ── token estimation: CJK / Japanese coverage ───────────────────────────────


def test_estimate_tokens_japanese_hiragana():
    # Hiragana counts as CJK (1/1.5). 3 chars → ceil(3/1.5) = 2.
    assert axt.estimate_tokens("ひらが") == 2


def test_estimate_tokens_cjk_han():
    # Han ideographs are CJK. 6 chars → ceil(6/1.5) = 4.
    assert axt.estimate_tokens("漢字漢字漢字") == 4


# ── _safe_read_text / _safe_listdir ──────────────────────────────────────────


def test_safe_read_text_missing_returns_none(tmp_path: Path):
    assert axt._safe_read_text(tmp_path / "nope.txt") is None


def test_safe_read_text_directory_returns_none(tmp_path: Path):
    d = tmp_path / "adir"
    d.mkdir()
    # is_file() is False for a directory.
    assert axt._safe_read_text(d) is None


def test_safe_read_text_reads_file(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("hello")
    assert axt._safe_read_text(p) == "hello"


def test_safe_listdir_missing_returns_empty(tmp_path: Path):
    assert axt._safe_listdir(tmp_path / "nope") == []


def test_safe_read_text_undecodable_returns_none(tmp_path: Path):
    p = tmp_path / "binary.bin"
    # Invalid UTF-8 byte sequence triggers UnicodeDecodeError → None.
    p.write_bytes(b"\xff\xfe\x00\x80garbage")
    assert axt._safe_read_text(p) is None


# ── _truncate_memory ─────────────────────────────────────────────────────────


def test_truncate_memory_line_limit():
    content = "\n".join(f"line{i}" for i in range(500))
    out = axt._truncate_memory(content)
    assert out.count("\n") == axt.MEMORY_LINE_LIMIT - 1  # 200 lines → 199 newlines
    assert "line0" in out
    assert "line200" not in out


def test_truncate_memory_byte_limit():
    # One huge single line exceeding the byte budget — the while-loop trims it.
    content = "X" * (axt.MEMORY_BYTE_LIMIT + 5000)
    out = axt._truncate_memory(content)
    assert len(out.encode("utf-8")) <= axt.MEMORY_BYTE_LIMIT


# ── get_claude_version / get_git_status error handling ───────────────────────


def test_get_claude_version_handles_oserror(monkeypatch):
    import subprocess

    def _raise(*a, **k):
        raise OSError("no claude binary")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert axt.get_claude_version() == "unknown"


def test_get_claude_version_handles_timeout(monkeypatch):
    import subprocess

    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd=a[0], timeout=3)

    monkeypatch.setattr(subprocess, "run", _raise)
    assert axt.get_claude_version() == "unknown"


def test_get_git_status_handles_oserror(monkeypatch, tmp_path: Path):
    import subprocess

    def _raise(*a, **k):
        raise OSError("git missing")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert axt.get_git_status(tmp_path) == ""


def _fake_proc(stdout: str):
    import subprocess

    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def test_get_claude_version_returns_stdout(monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_proc("1.2.3 (Claude Code)\n"))
    assert axt.get_claude_version() == "1.2.3 (Claude Code)"


def test_get_claude_version_blank_stdout_falls_back(monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_proc("   \n"))
    assert axt.get_claude_version() == "unknown"


def test_get_git_status_returns_stdout(monkeypatch, tmp_path: Path):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_proc("On branch main\n"))
    assert axt.get_git_status(tmp_path) == "On branch main"


# ── rich collection: every dynamic category populated ────────────────────────


def _isolate_paths(tmp_path: Path, monkeypatch) -> None:
    """Point PATHS/HOME at empty tmp so list_* helpers don't read real home."""
    nohome = tmp_path / "nohome"
    monkeypatch.setattr("axt.HOME", nohome)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=nohome / ".claude",
        settings=nohome / ".claude" / "settings.json",
        installed_plugins=nohome / ".claude" / "plugins" / "installed_plugins.json",
        skills=nohome / ".claude" / "skills",
    ))


def test_collect_context_memory_and_settings(tmp_path: Path, monkeypatch):
    _isolate_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "M file.py")

    home = tmp_path / "home"
    proj = tmp_path / "proj"
    proj.mkdir(parents=True)

    # Global settings file.
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text('{"enabledPlugins": {}}')

    # Memory dir (encoded project path under home/.claude/projects).
    project_key = str(proj).replace("/", "-").lstrip("-")
    mem_dir = home / ".claude" / "projects" / project_key / "memory"
    mem_dir.mkdir(parents=True)
    (mem_dir / "MEMORY.md").write_text("# Memory index\n- topic one\n")
    (mem_dir / "branching.md").write_text("Work on develop branch.")

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj,
        installed_plugins_path=tmp_path / "ip.json",
    )
    by_cat: dict[str, list] = {}
    for s in sources:
        by_cat.setdefault(s.category, []).append(s)

    settings_srcs = by_cat["settings"]
    assert any("settings.json (global)" in s.name for s in settings_srcs)

    memory_srcs = by_cat["memory"]
    names = {s.name for s in memory_srcs}
    assert "MEMORY.md" in names
    assert "Memory: branching" in names
    # Seeded memory has non-trivial content → positive token estimate.
    assert all(s.estimated_tokens > 0 for s in memory_srcs)

    # git-status fixed source carries the stubbed status text.
    git_srcs = by_cat["git-status"]
    assert "M file.py" in (git_srcs[0].content or "")


def test_collect_context_with_plugin_skills_mcp_commands_agents(tmp_path: Path, monkeypatch):
    """Exercise plugins/skills/mcp/commands/agents collection branches at once."""
    import json

    home = tmp_path / "home"
    proj = tmp_path / "proj"
    (proj / ".claude" / "commands").mkdir(parents=True)
    (proj / ".claude" / "agents").mkdir(parents=True)
    (proj / ".claude" / "skills" / "proj-skill").mkdir(parents=True)

    # Project command + agent + skill.
    (proj / ".claude" / "commands" / "deploy.md").write_text('---\ndescription: "Deploy"\n---\n')
    (proj / ".claude" / "agents" / "helper.md").write_text('---\ndescription: "Helper agent"\n---\n')
    (proj / ".claude" / "skills" / "proj-skill" / "SKILL.md").write_text(
        '---\nname: ProjSkill\ndescription: A handy skill.\n---\nbody\n'
    )

    # Installed plugin (enabled) with an MCP server in its manifest.
    install = tmp_path / "plug"
    (install / ".claude-plugin").mkdir(parents=True)
    (install / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "myplug", "description": "A plugin", "version": "1.0.0",
        "mcpServers": {"srv1": {"command": "run-srv"}},
    }))
    ip = tmp_path / "ip.json"
    ip.write_text(json.dumps({
        "version": 2,
        "plugins": {"myplug@mkt": [{"scope": "user", "installPath": str(install),
                                    "version": "1.0.0", "installedAt": "", "lastUpdated": ""}]},
    }))

    # Global settings enabling the plugin (read at home/.claude/settings.json).
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"myplug@mkt": True}}))

    # Isolate PATHS so list_all_skills/list_commands user dirs are empty,
    # but installed_plugins/settings point at our seeds.
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=home / ".claude",
        settings=home / ".claude" / "settings.json",
        installed_plugins=ip,
        skills=home / ".claude" / "skills",
    ))
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj, installed_plugins_path=ip,
    )
    cats = {}
    for s in sources:
        cats.setdefault(s.category, []).append(s)

    # Skills: project skill present, name read from SKILL.md frontmatter.
    skill_srcs = cats.get("skills", [])
    assert any("proj-skill" in s.name for s in skill_srcs)
    assert any("ProjSkill" in (s.content or "") for s in skill_srcs)

    # MCP server from the plugin manifest.
    assert any("srv1" in s.name for s in cats.get("mcp-tools", []))

    # Plugins category lists the enabled plugin.
    assert any(s.name == "myplug" for s in cats.get("plugins", []))

    # Commands + agents from the project.
    assert any(s.name == "deploy" for s in cats.get("commands", []))
    assert any(s.name == "helper" for s in cats.get("agents", []))


def test_collect_context_includes_sessionstart_hook(tmp_path: Path, monkeypatch):
    """Only SessionStart / UserPromptSubmit hooks contribute to the hooks category."""
    import json

    home = tmp_path / "home"
    proj = tmp_path / "proj"
    proj.mkdir(parents=True)
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "echo start"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
        }
    }))

    _isolate_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj, installed_plugins_path=tmp_path / "ip.json",
    )
    hook_srcs = [s for s in sources if s.category == "hooks"]
    # SessionStart is included; the Stop hook is filtered out.
    assert len(hook_srcs) == 1
    assert "SessionStart" in hook_srcs[0].name
    assert hook_srcs[0].estimated_tokens == axt.FIXED_HOOK_OUTPUT_TOKENS


# ── add_context_hints: remaining branches ───────────────────────────────────


def test_add_context_hints_memory_old_and_recent(tmp_path: Path):
    import os
    import time

    old = tmp_path / "old.md"
    old.write_text("stale memory content " * 20)
    # Set mtime to ~100 days ago.
    hundred_days = time.time() - 100 * 86400
    os.utime(old, (hundred_days, hundred_days))

    recent = tmp_path / "recent.md"
    recent.write_text("fresh memory content " * 20)

    sources = [
        axt.ContextSource(name="Old", category="memory", path=str(old), chars=0,
                          estimated_tokens=300, percentage=0, actionable=True),
        axt.ContextSource(name="Recent", category="memory", path=str(recent), chars=0,
                          estimated_tokens=300, percentage=0, actionable=True),
    ]
    axt.add_context_hints(sources)
    assert "not modified in" in sources[0].hint
    assert ">90 days" in sources[0].hint
    # Recent file: no staleness hint, but >100 tok generic hint applies.
    assert "not modified" not in (sources[1].hint or "")
    assert sources[1].hint == "300 tok"


def test_add_context_hints_hooks_and_git_and_top_skill():
    sources = [
        axt.ContextSource(name="Hook A", category="hooks", path="", chars=0,
                          estimated_tokens=200, percentage=0, actionable=False),
        axt.ContextSource(name="Git", category="git-status", path="", chars=0,
                          estimated_tokens=150, percentage=0, actionable=False),
        axt.ContextSource(name="BigSkill", category="skills", path="", chars=0,
                          estimated_tokens=5000, percentage=0, actionable=True),
        axt.ContextSource(name="Cmd", category="commands", path="", chars=0,
                          estimated_tokens=250, percentage=0, actionable=True),
        axt.ContextSource(name="TinyCmd", category="commands", path="", chars=0,
                          estimated_tokens=5, percentage=0, actionable=True),
    ]
    axt.add_context_hints(sources)
    assert sources[0].hint == "~200 tok estimated output"
    assert sources[1].hint == "150 tok (fixed)"
    # BigSkill is among the top-3 token consumers.
    assert "top context consumer" in sources[2].hint
    # Generic command hint fires above 100 tok, stays None below.
    assert sources[3].hint == "250 tok"
    assert sources[4].hint is None


def test_add_context_hints_memory_unreadable_mtime_only_token_hint(tmp_path: Path, monkeypatch):
    """When stat() raises, the staleness branch is skipped but the >100 tok hint still applies."""
    src = axt.ContextSource(name="Mem", category="memory", path=str(tmp_path / "gone.md"),
                            chars=0, estimated_tokens=300, percentage=0, actionable=True)

    real_stat = Path.stat

    def _boom(self, *a, **k):
        if str(self).endswith("gone.md"):
            raise OSError("stat failed")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", _boom)
    axt.add_context_hints([src])
    assert src.hint == "300 tok"


def test_collect_context_swallows_helper_oserrors(tmp_path: Path, monkeypatch):
    """Each list_* helper raising OSError is caught; collection still yields fixed sources."""
    home = tmp_path / "home"
    home.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()

    def _raise(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr("axt.list_all_skills", _raise)
    monkeypatch.setattr("axt.list_installed_plugins", _raise)
    monkeypatch.setattr("axt.list_hooks", _raise)
    monkeypatch.setattr("axt.list_commands", _raise)
    monkeypatch.setattr("axt.list_all_agents", _raise)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj, installed_plugins_path=tmp_path / "ip.json",
    )
    cats = {s.category for s in sources}
    # Dynamic categories were skipped due to OSError; fixed ones survive.
    assert "skills" not in cats
    assert "commands" not in cats
    assert {"system-prompt", "git-status", "user-context"} <= cats


def test_add_context_hints_small_claude_md_no_hint():
    sources = [
        axt.ContextSource(name="Small CLAUDE.md", category="claude-md", path="", chars=0,
                          estimated_tokens=100, percentage=0, actionable=True),
    ]
    axt.add_context_hints(sources)
    # <=500 tok claude-md gets no hint.
    assert sources[0].hint is None


# ── build_hook_preview: minimal hook ─────────────────────────────────────────


def test_build_hook_preview_mcp_fields():
    h = axt.HookInfo(event="Stop", matcher="", source="user", source_path="/x",
                     type="mcp_tool", server="srv", tool="run")
    out = axt.build_hook_preview(h)
    assert "Type: mcp_tool" in out
    assert "MCP Server: srv" in out
    assert "Tool: run" in out
    # Empty matcher → no "Matcher:" line.
    assert "Matcher:" not in out


def test_build_hook_preview_http_url_line():
    h = axt.HookInfo(event="UserPromptSubmit", matcher="*", source="user", source_path="/x",
                     type="http", url="https://hooks.example/run")
    out = axt.build_hook_preview(h)
    assert "URL: https://hooks.example/run" in out


def test_collect_context_skips_disabled_plugin(tmp_path: Path, monkeypatch):
    """A disabled plugin must not appear in the plugins category (continue branch)."""
    import json

    home = tmp_path / "home"
    proj = tmp_path / "proj"
    proj.mkdir(parents=True)

    install = tmp_path / "plug"
    (install / ".claude-plugin").mkdir(parents=True)
    (install / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": "offplug", "description": "Disabled", "version": "1.0.0",
    }))
    ip = tmp_path / "ip.json"
    ip.write_text(json.dumps({
        "version": 2,
        "plugins": {"offplug@mkt": [{"scope": "user", "installPath": str(install),
                                     "version": "1.0.0", "installedAt": "", "lastUpdated": ""}]},
    }))
    (home / ".claude").mkdir(parents=True)
    # Plugin present but disabled.
    (home / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"offplug@mkt": False}}))

    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=home / ".claude",
        settings=home / ".claude" / "settings.json",
        installed_plugins=ip,
        skills=home / ".claude" / "skills",
    ))
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj, installed_plugins_path=ip,
    )
    assert [s for s in sources if s.category == "plugins"] == []
