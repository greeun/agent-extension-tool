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
