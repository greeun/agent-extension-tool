"""Tests for Section 4 — commands and agents scanners.

Both share `_scan_md_dir` + `_extract_md_description`; verifying one of
each is enough to catch the factory wiring.
"""
from __future__ import annotations

from pathlib import Path

import axt


def _write_md(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_extract_description_from_frontmatter():
    raw = '---\ndescription: "Run a thing"\nother: yes\n---\n# Heading\n'
    assert axt._extract_md_description(raw) == "Run a thing"


def test_extract_description_from_first_line_when_no_frontmatter():
    raw = "# Heading\n\nThis is the body of the file.\n"
    # First non-#, non--- line.
    assert axt._extract_md_description(raw) == "This is the body of the file."


def test_extract_description_empty():
    assert axt._extract_md_description("") == ""


def test_extract_description_truncates_long_first_line():
    raw = "Some " + "very " * 30 + "long line"
    desc = axt._extract_md_description(raw)
    assert len(desc) == 80


def test_list_commands_scans_project_dir(tmp_path: Path, monkeypatch):
    # Isolate from real home — point claude_dir + installed_plugins at empty tmp.
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "nohome",
        settings=tmp_path / "nohome" / "settings.json",
        installed_plugins=tmp_path / "nohome" / "installed_plugins.json",
    ))
    proj = tmp_path / "proj"
    _write_md(proj / ".claude" / "commands" / "deploy.md", '---\ndescription: "Deploy app"\n---\n')
    _write_md(proj / ".claude" / "commands" / "test.md", "# Test runner\n\nRun the suite.\n")
    cmds = axt.list_commands(project_dir=proj)
    by_name = {c.name: c for c in cmds}
    assert "deploy" in by_name and "test" in by_name
    assert by_name["deploy"].description == "Deploy app"
    assert by_name["deploy"].source == "project"
    assert "Run the suite" in by_name["test"].description


def test_list_commands_ignores_non_md(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "nohome",
        settings=tmp_path / "nohome" / "settings.json",
        installed_plugins=tmp_path / "nohome" / "installed_plugins.json",
    ))
    proj = tmp_path / "proj"
    _write_md(proj / ".claude" / "commands" / "a.md", "alpha")
    _write_md(proj / ".claude" / "commands" / "b.txt", "ignored")
    (proj / ".claude" / "commands" / "subdir").mkdir(parents=True)
    cmds = axt.list_commands(project_dir=proj)
    names = sorted(c.name for c in cmds)
    assert names == ["a"]


def test_list_all_agents_user_and_project(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setattr("axt.HOME", fake_home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=fake_home / ".claude",
        settings=fake_home / ".claude" / "settings.json",
        installed_plugins=fake_home / ".claude" / "plugins" / "installed_plugins.json",
    ))
    _write_md(fake_home / ".claude" / "agents" / "user-agent.md", '---\ndescription: "user-level"\n---\n')
    _write_md(fake_home / ".agents" / "dotagent.md", '---\ndescription: "dotfile"\n---\n')
    proj = tmp_path / "proj"
    _write_md(proj / ".claude" / "agents" / "proj-agent.md", '---\ndescription: "project"\n---\n')

    agents = axt.list_all_agents(project_dir=proj)
    by_name = {a.name: a for a in agents}
    assert "user-agent" in by_name
    assert "dotagent" in by_name
    assert "proj-agent" in by_name
    assert by_name["user-agent"].source == "user"
    assert by_name["proj-agent"].source == "project"


# ── _extract_md_description: frontmatter present but no description key ───────


def test_extract_description_frontmatter_without_desc_falls_through():
    raw = '---\nname: thing\nmodel: opus\n---\nActual body line.\n'
    # Frontmatter has no `description:`, so the regex match fails and we fall to
    # the generic "first non-#, non--- line" scan — which sees the frontmatter
    # body line `name: thing` first (the scan doesn't skip the fence interior).
    assert axt._extract_md_description(raw) == "name: thing"


# ── _scan_md_dir edge cases (via list_commands) ──────────────────────────────


def test_list_commands_missing_dir_returns_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "nohome",
        settings=tmp_path / "nohome" / "settings.json",
        installed_plugins=tmp_path / "nohome" / "installed_plugins.json",
    ))
    # No project_dir and no user commands dir → empty.
    assert axt.list_commands() == []


def test_list_commands_path_is_file_not_dir(tmp_path: Path, monkeypatch):
    """When .claude/commands is a FILE, scanner returns [] (not a dir branch)."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "nohome",
        settings=tmp_path / "nohome" / "settings.json",
        installed_plugins=tmp_path / "nohome" / "installed_plugins.json",
    ))
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "commands").write_text("i am a file, not a dir")
    assert axt.list_commands(project_dir=proj) == []


def test_list_commands_skips_unreadable_md(tmp_path: Path, monkeypatch):
    """A .md file that raises on read is silently skipped (OSError branch)."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "nohome",
        settings=tmp_path / "nohome" / "settings.json",
        installed_plugins=tmp_path / "nohome" / "installed_plugins.json",
    ))
    proj = tmp_path / "proj"
    _write_md(proj / ".claude" / "commands" / "good.md", '---\ndescription: "Good"\n---\n')

    real_read_text = Path.read_text

    def _boom(self, *a, **k):
        if self.name == "bad.md":
            raise OSError("permission denied")
        return real_read_text(self, *a, **k)

    # Create the bad file then patch read_text to fail only for it.
    _write_md(proj / ".claude" / "commands" / "bad.md", "x")
    monkeypatch.setattr(Path, "read_text", _boom)

    cmds = axt.list_commands(project_dir=proj)
    names = sorted(c.name for c in cmds)
    assert names == ["good"]


def test_list_commands_parses_frontmatter_version(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "nohome",
        settings=tmp_path / "nohome" / "settings.json",
        installed_plugins=tmp_path / "nohome" / "installed_plugins.json",
    ))
    proj = tmp_path / "proj"
    _write_md(
        proj / ".claude" / "commands" / "ver.md",
        '---\ndescription: "Versioned cmd"\nversion: 2.4.0\n---\nbody\n',
    )
    cmds = axt.list_commands(project_dir=proj)
    by_name = {c.name: c for c in cmds}
    assert by_name["ver"].version == "2.4.0"
    assert by_name["ver"].description == "Versioned cmd"


# ── plugin-sourced commands / agents ─────────────────────────────────────────


def _seed_plugin(tmp_path: Path, *, enabled: bool, with_command=True, with_agent=False) -> tuple[Path, Path]:
    """Create an installed plugin + settings enabling/disabling it. Returns (ip_path, settings_path)."""
    import json

    install = tmp_path / "plug"
    if with_command:
        _write_md(install / "commands" / "pcmd.md", '---\ndescription: "Plugin command"\n---\n')
    if with_agent:
        _write_md(install / "agents" / "pagent.md", '---\ndescription: "Plugin agent"\n---\n')
    install.mkdir(parents=True, exist_ok=True)

    ip = tmp_path / "installed_plugins.json"
    ip.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "myplug@mkt": [{"scope": "user", "installPath": str(install), "version": "3.1",
                            "installedAt": "", "lastUpdated": ""}]
        },
    }))
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"enabledPlugins": {"myplug@mkt": enabled}}))
    return ip, settings


def test_list_commands_includes_enabled_plugin(tmp_path: Path, monkeypatch):
    ip, settings = _seed_plugin(tmp_path, enabled=True, with_command=True)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "nohome",
        settings=settings,
        installed_plugins=ip,
    ))
    cmds = axt.list_commands()
    plugin_cmds = [c for c in cmds if c.source == "plugin"]
    assert len(plugin_cmds) == 1
    assert plugin_cmds[0].name == "myplug:pcmd"
    assert plugin_cmds[0].plugin == "myplug"
    assert plugin_cmds[0].description == "Plugin command"


def test_list_commands_skips_disabled_plugin(tmp_path: Path, monkeypatch):
    ip, settings = _seed_plugin(tmp_path, enabled=False, with_command=True)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "nohome",
        settings=settings,
        installed_plugins=ip,
    ))
    assert [c for c in axt.list_commands() if c.source == "plugin"] == []


def test_list_all_agents_includes_enabled_plugin(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    ip, settings = _seed_plugin(tmp_path, enabled=True, with_command=False, with_agent=True)
    monkeypatch.setattr("axt.HOME", fake_home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=fake_home / ".claude",
        settings=settings,
        installed_plugins=ip,
    ))
    proj = tmp_path / "proj"
    proj.mkdir()
    agents = axt.list_all_agents(project_dir=proj)
    plugin_agents = [a for a in agents if a.source == "plugin"]
    assert len(plugin_agents) == 1
    assert plugin_agents[0].name == "myplug:pagent"
    assert plugin_agents[0].description == "Plugin agent"
    assert plugin_agents[0].version == ""  # _make_agent does not propagate plugin version field here
