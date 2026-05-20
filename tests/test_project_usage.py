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
