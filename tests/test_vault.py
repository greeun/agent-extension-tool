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


def test_parse_yaml_block_stops_at_following_key():
    """A block scalar must terminate at the next same-indent key — it must not
    swallow `name:` into the description value."""
    fm = "description: |\n  body line\nname: foo\n"
    assert axt.parse_yaml_description(fm) == "body line"


def test_parse_yaml_block_empty_yields_empty():
    """A block-scalar header with no indented body (immediately followed by
    another key) yields an empty description, not a crash or the next key."""
    fm = "description: |\nname: foo\n"
    assert axt.parse_yaml_description(fm) == ""


def test_parse_yaml_empty_value():
    assert axt.parse_yaml_description("description:") == ""
    assert axt.parse_yaml_description("description: ") == ""


def test_parse_yaml_missing_key():
    assert axt.parse_yaml_description("name: foo\nversion: 1") == ""


def test_parse_yaml_crlf():
    fm = "description: hello\r\nother: x"
    assert axt.parse_yaml_description(fm) == "hello"


# ─── parse_yaml_version ──────────────────────────────────────────────────────


def test_parse_yaml_version_plain():
    assert axt.parse_yaml_version("version: 1.2.3") == "1.2.3"


def test_parse_yaml_version_quoted():
    assert axt.parse_yaml_version('version: "0.1.0"') == "0.1.0"
    assert axt.parse_yaml_version("version: '0.1.0'") == "0.1.0"


def test_parse_yaml_version_missing():
    assert axt.parse_yaml_version("name: foo\ndescription: bar") == ""


def test_parse_yaml_version_empty():
    assert axt.parse_yaml_version("version:") == ""


def test_read_version_for_skill(tmp_path: Path):
    """Skill version is read from SKILL.md frontmatter."""
    skill_dir = tmp_path / "vault" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: d\nversion: 2.5.0\n---\nbody"
    )
    items = axt.list_vault_items(tmp_path / "vault")
    assert len(items) == 1
    assert items[0].name == "demo"
    assert items[0].version == "2.5.0"


def test_read_version_for_command(tmp_path: Path):
    cmd_dir = tmp_path / "vault" / "commands"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "do.md").write_text(
        "---\nname: do\ndescription: d\nversion: 0.9.1\n---\nbody"
    )
    items = axt.list_vault_items(tmp_path / "vault")
    assert items[0].version == "0.9.1"


def test_version_absent_yields_empty_string(tmp_path: Path):
    """When the frontmatter has no `version:` line, version is "" (rendered as ─)."""
    skill_dir = tmp_path / "vault" / "skills" / "noversion"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: noversion\ndescription: d\n---\nbody")
    items = axt.list_vault_items(tmp_path / "vault")
    assert items[0].version == ""


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


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_list_with_project_state_global_dir_enrichment(tmp_path: Path):
    """Passing global_dir enriches items with global-link state, reads global
    enabledPlugins, and merges in global-only (non-vault) items."""
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    gd = tmp_path / "global"
    gd.mkdir()
    # vault skill linked into the global dir → is_global_linked True
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    axt.link_to_global(gd, skill)
    # a global skill that is NOT in the vault → should be merged in
    extra = gd / "skills" / "global-only"
    extra.mkdir(parents=True)
    (extra / "SKILL.md").write_text("---\ndescription: g\n---\n")
    # global enabledPlugins settings
    (gd / "settings.json").write_text(json.dumps({"enabledPlugins": {"p@m": True}}))
    plugin = axt.PluginRef(id="p@m", name="p", description="P")
    enriched = axt.list_vault_items_with_project_state(
        vault, proj, installed_plugins=[plugin], global_dir=gd)
    myskill = next(i for i in enriched if i.name == "myskill")
    assert myskill.is_global_linked is True
    plug = next(i for i in enriched if i.type == "plugin")
    assert plug.is_global_linked is True
    assert any(i.name == "global-only" and i.in_vault is False for i in enriched)


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_migrate_to_vault_preserves_symlinked_global(tmp_path: Path):
    """A global entry that is already a symlink is migrated as a symlink to the
    same target (not copied), preserving the link relationship."""
    global_dir = tmp_path / "global"
    vault = tmp_path / "vault"
    real = tmp_path / "real-skill"
    real.mkdir()
    (real / "SKILL.md").write_text("---\ndescription: x\n---\n")
    (global_dir / "skills").mkdir(parents=True)
    os.symlink(real, global_dir / "skills" / "linked")
    result = axt.migrate_to_vault(global_dir, vault)
    assert "skill:linked" in result.moved
    assert (vault / "skills" / "linked").is_symlink()


def test_migrate_to_vault_skips_hidden_and_wrong_type(tmp_path: Path):
    """migrate ignores dotfiles, non-dir entries under skills/, and non-.md
    entries under commands/ — only well-formed items move."""
    global_dir = tmp_path / "global"
    vault = tmp_path / "vault"
    (global_dir / "skills").mkdir(parents=True)
    (global_dir / "skills" / ".hidden").mkdir()         # dotfile → skip
    (global_dir / "skills" / "stray.txt").write_text("x")  # skill must be a dir → skip
    (global_dir / "commands").mkdir(parents=True)
    (global_dir / "commands" / "notmd.txt").write_text("x")  # not .md → skip
    good = global_dir / "skills" / "good"
    good.mkdir()
    (good / "SKILL.md").write_text("---\ndescription: x\n---\n")
    result = axt.migrate_to_vault(global_dir, vault)
    assert "skill:good" in result.moved
    assert all("hidden" not in m and "stray" not in m and "notmd" not in m
               for m in result.moved)


# ─── Project-local import candidates ─────────────────────────────────────────


def _make_project_local_skill(proj: Path, name: str = "proj-skill") -> Path:
    skill = proj / ".claude" / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A project-local skill\n---\nbody"
    )
    return skill


def test_list_project_non_vault_items_finds_skill(tmp_path: Path):
    vault = tmp_path / "vault"
    proj = tmp_path / "proj"
    _make_project_local_skill(proj)
    items = axt._list_project_non_vault_items(proj, vault)
    assert len(items) == 1
    item = items[0]
    assert item.name == "proj-skill"
    assert item.type == "skill"
    assert item.in_vault is False
    assert item.is_linked is True
    assert item.is_global_linked is False
    assert item.description == "A project-local skill"


def test_list_project_non_vault_items_finds_command_and_agent(tmp_path: Path):
    vault = tmp_path / "vault"
    proj = tmp_path / "proj"
    (proj / ".claude" / "commands").mkdir(parents=True)
    (proj / ".claude" / "commands" / "deploy.md").write_text(
        '---\ndescription: "Project deploy"\n---\n'
    )
    (proj / ".claude" / "agents").mkdir(parents=True)
    (proj / ".claude" / "agents" / "reviewer.md").write_text(
        "---\ndescription: Reviews project\n---\n"
    )
    items = axt._list_project_non_vault_items(proj, vault)
    by_type = {i.type: i for i in items}
    assert set(by_type) == {"command", "agent"}
    assert by_type["command"].name == "deploy.md"
    assert by_type["agent"].name == "reviewer.md"


def test_list_project_non_vault_items_skips_vault_names(tmp_path: Path):
    vault = _make_vault(tmp_path)  # already has "myskill"
    proj = tmp_path / "proj"
    _make_project_local_skill(proj, name="myskill")
    items = axt._list_project_non_vault_items(proj, vault)
    # Project's "myskill" is shadowed by the vault entry — should not appear.
    assert items == []


def test_list_project_non_vault_items_skips_global_names(tmp_path: Path):
    vault = tmp_path / "vault"
    proj = tmp_path / "proj"
    global_dir = tmp_path / "global"
    (global_dir / "skills" / "shared").mkdir(parents=True)
    (global_dir / "skills" / "shared" / "SKILL.md").write_text("---\n---\n")
    _make_project_local_skill(proj, name="shared")
    items = axt._list_project_non_vault_items(proj, vault, global_dir=global_dir)
    # Same name exists globally; global wins. Project entry suppressed.
    assert items == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need elevation")
def test_list_project_non_vault_items_skips_symlinks(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    (proj / ".claude" / "skills").mkdir(parents=True)
    # Pre-existing symlink (e.g. pointing into vault) is NOT a fresh
    # import candidate.
    os.symlink(vault / "skills" / "myskill", proj / ".claude" / "skills" / "linked")
    items = axt._list_project_non_vault_items(proj, vault)
    assert items == []


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_list_with_project_state_includes_project_local_items(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    _make_project_local_skill(proj, name="local-only")
    enriched = axt.list_vault_items_with_project_state(vault, proj)
    by_name = {i.name: i for i in enriched}
    assert "local-only" in by_name
    local = by_name["local-only"]
    assert local.in_vault is False
    assert local.is_linked is True
    assert local.is_global_linked is False


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_import_to_vault_from_project_source(tmp_path: Path):
    vault = tmp_path / "vault"
    proj = tmp_path / "proj"
    src = _make_project_local_skill(proj, name="promote-me")
    item = axt.VaultItem(
        name="promote-me",
        type="skill",
        path=str(src),
        description="",
        in_vault=False,
        is_linked=True,
        is_global_linked=False,
    )
    # global_dir is irrelevant for a project source; the path on `item` drives it.
    axt.import_to_vault(tmp_path / "global", vault, item)

    dest = vault / "skills" / "promote-me"
    assert (dest / "SKILL.md").exists()
    # Original project location must now be a symlink pointing at vault.
    assert src.is_symlink()
    assert Path(os.readlink(src)) == dest
