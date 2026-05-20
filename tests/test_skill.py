"""Tests for Section 4 — skill scanner."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import axt


def test_list_skills_missing_dir(tmp_path: Path):
    assert axt.list_skills(tmp_path / "nope") == []


def test_list_skills_finds_directories(tmp_path: Path):
    skills = tmp_path / "skills"
    (skills / "alpha").mkdir(parents=True)
    (skills / "beta").mkdir()
    (skills / ".hidden").mkdir()
    (skills / "readme.md").write_text("nope")  # not a dir, skipped
    found = axt.list_skills(skills)
    names = sorted(s.name for s in found)
    assert names == ["alpha", "beta"]
    for s in found:
        assert s.source == "user"
        assert s.is_symlink is False


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks require admin on Windows")
def test_list_skills_records_symlink_target(tmp_path: Path):
    target = tmp_path / "actual" / "myskill"
    target.mkdir(parents=True)
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    os.symlink(str(target), str(skills_dir / "myskill"))
    found = axt.list_skills(skills_dir)
    assert len(found) == 1
    assert found[0].is_symlink is True
    assert found[0].target == str(target)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks require admin on Windows")
def test_link_skill_creates_symlink(tmp_path: Path):
    target = tmp_path / "src"
    target.mkdir()
    skills_dir = tmp_path / "skills"
    axt.link_skill(skills_dir, target)
    link = skills_dir / "src"
    assert link.is_symlink()
    assert Path(os.readlink(link)) == target


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks require admin on Windows")
def test_link_skill_with_custom_name(tmp_path: Path):
    target = tmp_path / "real"
    target.mkdir()
    skills_dir = tmp_path / "skills"
    axt.link_skill(skills_dir, target, name="custom-name")
    assert (skills_dir / "custom-name").is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks require admin on Windows")
def test_unlink_skill_removes_symlink(tmp_path: Path):
    target = tmp_path / "src"
    target.mkdir()
    skills_dir = tmp_path / "skills"
    axt.link_skill(skills_dir, target, name="link")
    axt.unlink_skill(skills_dir, "link")
    assert not (skills_dir / "link").exists()
    assert target.exists()  # target untouched


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only behavior")
def test_unlink_skill_refuses_real_directory(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    (skills_dir / "real").mkdir(parents=True)
    with pytest.raises(ValueError, match="not a symlink"):
        axt.unlink_skill(skills_dir, "real")


def test_is_symlink_supported_matches_platform():
    assert axt.is_symlink_supported() is (sys.platform != "win32")
