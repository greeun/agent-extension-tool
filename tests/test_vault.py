"""Tests for Section 5 — vault YAML parsing + link/unlink/sync/migrate/import.

Symlink-touching tests are skipped on Windows (TS parity: vault refuses
to link on win32).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

import axt


# ─── parse_yaml_description ──────────────────────────────────────────────────


def test_parse_yaml_plain():
    assert axt.parse_yaml_description("description: Hello world") == "Hello world"


def test_parse_yaml_double_quoted_singleline():
    fm = 'description: "Quoted \\"value\\""'
    assert axt.parse_yaml_description(fm) == 'Quoted "value"'


def test_parse_yaml_double_quoted_multiline():
    fm = 'description: "first\nsecond line"'
    assert axt.parse_yaml_description(fm) == "first second line"


def test_parse_yaml_double_quoted_line_continuation():
    """trailing backslash joins without space (e.g. `pale\\` + `ttes`)."""
    fm = 'description: "pale\\\nttes"'
    # Inner backslash followed by newline = continuation.
    assert axt.parse_yaml_description(fm) == "palettes"


def test_parse_yaml_single_quoted():
    fm = "description: 'It''s simple'"
    assert axt.parse_yaml_description(fm) == "It's simple"


def test_parse_yaml_block_literal():
    fm = "description: |\n  Line one\n  Line two\n"
    assert axt.parse_yaml_description(fm) == "Line one Line two"


def test_parse_yaml_block_folded():
    fm = "description: >\n  Line one\n  Line two\n"
    assert axt.parse_yaml_description(fm) == "Line one Line two"


def test_parse_yaml_block_dedents_to_common():
    fm = "description: |\n    deep\n    deep two\n"
    assert axt.parse_yaml_description(fm) == "deep deep two"


def test_parse_yaml_empty_value():
    assert axt.parse_yaml_description("description:") == ""
    assert axt.parse_yaml_description("description: ") == ""


def test_parse_yaml_missing_key():
    assert axt.parse_yaml_description("name: foo\nversion: 1") == ""


def test_parse_yaml_crlf():
    fm = "description: hello\r\nother: x"
    assert axt.parse_yaml_description(fm) == "hello"


# ─── Profile read/write ──────────────────────────────────────────────────────


def test_empty_profile():
    p = axt.empty_profile()
    assert p.skills == ()
    assert p.commands == ()
    assert p.agents == ()
    assert p.plugins == ()


def test_write_then_read_profile(tmp_path: Path):
    axt.write_profile(tmp_path, axt.AxtProfile(skills=("a", "b"), commands=("c",)))
    got = axt.read_profile(tmp_path)
    assert got is not None
    assert got.skills == ("a", "b")
    assert got.commands == ("c",)


def test_read_profile_missing(tmp_path: Path):
    assert axt.read_profile(tmp_path) is None


def test_profile_with_added_is_idempotent():
    p = axt.empty_profile().with_added("skills", "x").with_added("skills", "x")
    assert p.skills == ("x",)


def test_profile_with_removed():
    p = axt.AxtProfile(skills=("a", "b", "c"))
    assert p.with_removed("skills", "b").skills == ("a", "c")


# ─── list_vault_items ────────────────────────────────────────────────────────


def _make_vault(tmp_path: Path) -> Path:
    """Create a vault with one of each item type, all with frontmatter."""
    vault = tmp_path / "vault"
    (vault / "skills" / "myskill").mkdir(parents=True)
    (vault / "skills" / "myskill" / "SKILL.md").write_text(
        "---\nname: myskill\ndescription: A skill\n---\nbody"
    )
    (vault / "commands").mkdir(parents=True)
    (vault / "commands" / "deploy.md").write_text(
        '---\ndescription: "Deploy app"\n---\n'
    )
    (vault / "agents").mkdir(parents=True)
    (vault / "agents" / "reviewer.md").write_text(
        "---\ndescription: |\n  Reviews code carefully\n---\n"
    )
    return vault


def test_list_vault_items_returns_all_three_types(tmp_path: Path):
    vault = _make_vault(tmp_path)
    items = axt.list_vault_items(vault)
    by_name = {i.name: i for i in items}
    assert set(by_name) == {"myskill", "deploy.md", "reviewer.md"}
    assert by_name["myskill"].type == "skill"
    assert by_name["myskill"].description == "A skill"
    assert by_name["deploy.md"].description == "Deploy app"
    assert by_name["reviewer.md"].description == "Reviews code carefully"
    for item in items:
        assert item.in_vault is True
        assert item.is_linked is False


def test_list_vault_items_missing_dir(tmp_path: Path):
    assert axt.list_vault_items(tmp_path / "nope") == []


def test_list_vault_items_skips_dotfiles_and_non_md(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "commands").mkdir(parents=True)
    (vault / "commands" / ".hidden.md").write_text("---")
    (vault / "commands" / "good.md").write_text("---\ndescription: ok\n---")
    (vault / "commands" / "ignored.txt").write_text("nope")
    items = axt.list_vault_items(vault)
    names = sorted(i.name for i in items)
    assert names == ["good.md"]


# ─── Symlink ops ─────────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_project_creates_symlink_and_updates_profile(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    items = axt.list_vault_items(vault)
    skill = next(i for i in items if i.type == "skill")
    axt.link_to_project(proj, skill)
    link = proj / ".claude" / "skills" / "myskill"
    assert link.is_symlink()
    profile = axt.read_profile(proj)
    assert profile is not None and "myskill" in profile.skills


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_project_refuses_real_file(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    (proj / ".claude" / "skills" / "myskill").mkdir(parents=True)
    skill = next(i for i in axt.list_vault_items(vault) if i.name == "myskill")
    with pytest.raises(FileExistsError):
        axt.link_to_project(proj, skill)


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_unlink_from_project_removes_symlink_and_profile_entry(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    axt.link_to_project(proj, skill)
    axt.unlink_from_project(proj, skill)
    assert not (proj / ".claude" / "skills" / "myskill").exists()
    profile = axt.read_profile(proj)
    assert profile is not None
    assert "myskill" not in profile.skills


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_unlink_global(tmp_path: Path):
    vault = _make_vault(tmp_path)
    global_dir = tmp_path / "global"
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    axt.link_to_global(global_dir, skill)
    assert (global_dir / "skills" / "myskill").is_symlink()
    axt.unlink_from_global(global_dir, skill)
    assert not (global_dir / "skills" / "myskill").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_sync_project_links_declared_and_unlinks_orphans(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    # Declare myskill in profile but no symlink exists yet.
    axt.write_profile(proj, axt.AxtProfile(skills=("myskill",)))

    # And create a stale symlink to a vault item NOT declared.
    (proj / ".claude" / "skills").mkdir(parents=True)
    stale_target = vault / "skills" / "myskill"
    os.symlink(stale_target, proj / ".claude" / "skills" / "myskill.bak")
    # Manually add an orphan that points into vault — sync should unlink.
    # (We don't add to profile, so it's an orphan.)

    result = axt.sync_project(proj, vault)
    assert any("skill:myskill" == x for x in result.linked)
    # Verify link materialized.
    assert (proj / ".claude" / "skills" / "myskill").is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_sync_project_reports_missing_in_vault(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    axt.write_profile(proj, axt.AxtProfile(skills=("does-not-exist",)))
    result = axt.sync_project(proj, vault)
    assert any("does-not-exist" in e for e in result.errors)


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_migrate_to_vault_moves_global_items(tmp_path: Path):
    global_dir = tmp_path / "global"
    (global_dir / "skills" / "alpha").mkdir(parents=True)
    (global_dir / "skills" / "alpha" / "SKILL.md").write_text("---\ndescription: a\n---")
    (global_dir / "commands").mkdir(parents=True)
    (global_dir / "commands" / "b.md").write_text("body")
    vault = tmp_path / "vault"

    result = axt.migrate_to_vault(global_dir, vault)
    moved = set(result.moved)
    assert "skill:alpha" in moved
    assert "command:b.md" in moved
    assert (vault / "skills" / "alpha" / "SKILL.md").exists()
    assert (vault / "commands" / "b.md").exists()
    assert not (global_dir / "skills" / "alpha").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_migrate_skips_existing(tmp_path: Path):
    global_dir = tmp_path / "global"
    (global_dir / "commands").mkdir(parents=True)
    (global_dir / "commands" / "dup.md").write_text("global version")
    vault = tmp_path / "vault"
    (vault / "commands").mkdir(parents=True)
    (vault / "commands" / "dup.md").write_text("vault version")
    result = axt.migrate_to_vault(global_dir, vault)
    assert "command:dup.md" in result.skipped


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_import_to_vault_moves_and_leaves_symlink(tmp_path: Path):
    global_dir = tmp_path / "global"
    (global_dir / "commands").mkdir(parents=True)
    src = global_dir / "commands" / "x.md"
    src.write_text("original")
    vault = tmp_path / "vault"
    item = axt.VaultItem(name="x.md", type="command", path=str(src), description="", in_vault=False)
    axt.import_to_vault(global_dir, vault, item)
    dest = vault / "commands" / "x.md"
    assert dest.exists()
    assert dest.read_text() == "original"
    assert src.is_symlink()
    assert os.readlink(src) == str(dest)


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_import_to_vault_fails_if_exists(tmp_path: Path):
    global_dir = tmp_path / "global"
    (global_dir / "commands").mkdir(parents=True)
    (global_dir / "commands" / "x.md").write_text("a")
    vault = tmp_path / "vault"
    (vault / "commands").mkdir(parents=True)
    (vault / "commands" / "x.md").write_text("b")
    item = axt.VaultItem(name="x.md", type="command", path=str(global_dir / "commands" / "x.md"), description="", in_vault=False)
    with pytest.raises(FileExistsError):
        axt.import_to_vault(global_dir, vault, item)


# ─── Plugin / non-linkable types ─────────────────────────────────────────────


def test_link_to_project_rejects_plugin(tmp_path: Path):
    item = axt.VaultItem(name="p", type="plugin", path="", description="")
    with pytest.raises(ValueError):
        axt.link_to_project(tmp_path, item)


def test_link_to_project_rejects_unknown_type(tmp_path: Path):
    item = axt.VaultItem(name="x", type="not-a-real-type", path="", description="")
    with pytest.raises(ValueError):
        axt.link_to_project(tmp_path, item)


# ─── Enriched listing ────────────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_list_with_project_state_marks_linked(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    items = axt.list_vault_items(vault)
    skill = next(i for i in items if i.type == "skill")
    axt.link_to_project(proj, skill)
    enriched = axt.list_vault_items_with_project_state(vault, proj)
    skill_enriched = next(i for i in enriched if i.name == "myskill")
    assert skill_enriched.is_linked is True


def test_list_with_project_state_includes_plugins(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    plugin = axt.PluginRef(id="p@m", name="p", description="P plugin")
    enriched = axt.list_vault_items_with_project_state(vault, proj, installed_plugins=[plugin])
    plugin_items = [i for i in enriched if i.type == "plugin"]
    assert len(plugin_items) == 1
    assert plugin_items[0].name == "p"
    assert plugin_items[0].description == "P plugin"
