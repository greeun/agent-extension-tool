"""Tests for Section 9 — project usage index."""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

import pytest

import axt


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_scan_project_usage_from_profile_only(tmp_path: Path):
    # Set up filesystem: a project dir with a .axt-profile.json
    project = tmp_path / "Users" / "me" / "myproj"
    project.mkdir(parents=True)
    profile = axt.AxtProfile(skills=("alpha",), commands=("deploy.md",), agents=(), plugins=("p@m",))
    axt.write_profile(project, profile)

    # Encode the project path the way Claude Code does: `/` → `-`, `.` → `-`.
    encoded = str(project).replace("/", "-")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    # The "encoded" directory is what scan_project_usage walks.
    # We don't actually need a fake directory at that name; the scanner
    # decodes it back to project path via filesystem walk.
    (projects_dir / encoded).mkdir()

    # Patch HOME so the decoder walks under tmp_path.
    index = axt.scan_project_usage(projects_dir, tmp_path / "vault")

    # `alpha` skill should be indexed from the profile.
    assert axt.get_project_count(index, "skill", "alpha") == 1
    refs = axt.get_projects(index, "skill", "alpha")
    assert refs[0].name == "myproj"


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_scan_project_usage_indexes_symlinks(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    vault = tmp_path / "vault"
    (vault / "skills" / "myskill").mkdir(parents=True)

    # Project has a symlink under .claude/skills pointing to vault.
    (project / ".claude" / "skills").mkdir(parents=True)
    os.symlink(vault / "skills" / "myskill", project / ".claude" / "skills" / "myskill")

    # Encoded projects dir.
    encoded = str(project).replace("/", "-")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / encoded).mkdir()

    index = axt.scan_project_usage(projects_dir, vault)
    assert axt.get_project_count(index, "skill", "myskill") == 1


def test_get_project_count_unknown_key():
    assert axt.get_project_count({}, "skill", "nope") == 0


def test_get_projects_unknown_key():
    assert axt.get_projects({}, "skill", "nope") == []


def test_scan_project_usage_missing_dir(tmp_path: Path):
    """No projects dir → empty index, no error."""
    assert axt.scan_project_usage(tmp_path / "nope", tmp_path / "vault") == {}


def test_decode_project_dir_name_walks_filesystem(tmp_path: Path):
    """`-tlog-net` should decode to the real `tlog.net` (or `tlog/net`) dir."""
    # Set up a real path: tmp_path / tlog.net.
    target = tmp_path / "tlog.net"
    target.mkdir()
    encoded = "-" + str(target)[1:].replace("/", "-").replace(".", "-")
    decoded = axt._decode_project_dir_name(encoded, fs_root="/")
    assert decoded == str(target)


def test_decode_project_dir_name_without_dash_prefix():
    assert axt._decode_project_dir_name("no-leading-dash") is None


def test_decode_project_dir_name_unreadable_root():
    assert axt._decode_project_dir_name("-foo", fs_root="/no/such/root/xyz") is None


def test_decode_project_dir_name_no_match(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert axt._decode_project_dir_name("-zzz-nomatch", fs_root=str(empty)) is None


def test_decode_project_dir_name_match_is_not_a_dir(tmp_path: Path):
    (tmp_path / "afile").write_text("x")  # matches segment but isn't a dir
    assert axt._decode_project_dir_name("-afile", fs_root=str(tmp_path)) is None


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin on Windows")
def test_scan_project_usage_full_mode_indexes_enabled_plugins(tmp_path: Path):
    """mode='full' also scans project settings.json; only ENABLED plugins are
    indexed (disabled ones are skipped)."""
    project = tmp_path / "fullproj"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"on@m": True, "off@m": False}}))
    encoded = str(project).replace("/", "-")
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / encoded).mkdir()
    index = axt.scan_project_usage(projects_dir, tmp_path / "vault", mode="full")
    assert axt.get_project_count(index, "plugin", "on@m") == 1
    assert axt.get_project_count(index, "plugin", "off@m") == 0


def test_scan_counts_and_format_summary():
    idx: dict = {}
    ref = axt.ProjectRef(path="/x", name="x")
    axt._add_to_index(idx, "skill", "a", ref)
    axt._add_to_index(idx, "skill", "b", ref)
    axt._add_to_index(idx, "agent", "c", ref)
    counts = axt.scan_counts_by_type(idx)
    assert counts["skill"] == 2 and counts["agent"] == 1 and counts["command"] == 0
    title = axt.format_scan_summary(idx, style="title")
    assert "skill:2" in title and "cmd:0" in title and "agent:1" in title
    toast = axt.format_scan_summary(idx, style="toast")
    assert "2 skill" in toast and " · " in toast


def test_scan_counts_by_type_handles_unexpected_type():
    idx: dict = {}
    axt._add_to_index(idx, "weird", "x", axt.ProjectRef(path="/x", name="x"))
    assert axt.scan_counts_by_type(idx)["weird"] == 1
