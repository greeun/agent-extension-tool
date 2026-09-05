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


# ─── Cross-agent (.agents/skills) mirror ─────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_agents_mirrors_skill_pointing_at_vault(tmp_path: Path):
    vault = _make_vault(tmp_path)
    agents = tmp_path / ".agents"
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    ok, _ = axt.link_to_agents(agents, skill)
    link = agents / "skills" / "myskill"
    assert ok
    assert link.is_symlink()
    # Points straight at the vault content, not through .claude/skills.
    assert os.path.realpath(link) == os.path.realpath(skill.path)


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_agents_refuses_non_skill(tmp_path: Path):
    vault = _make_vault(tmp_path)
    cmd = next(i for i in axt.list_vault_items(vault) if i.type == "command")
    ok, msg = axt.link_to_agents(tmp_path / ".agents", cmd)
    assert not ok and "Only skills" in msg
    assert not (tmp_path / ".agents").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_agents_guarded_by_skill_lock(tmp_path: Path):
    vault = _make_vault(tmp_path)
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / axt.SKILL_LOCK_NAME).write_text("{}")
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    ok, msg = axt.link_to_agents(agents, skill)
    assert not ok and axt.SKILL_LOCK_NAME in msg
    assert not (agents / "skills" / "myskill").exists()
    # force overrides the guard.
    ok, _ = axt.link_to_agents(agents, skill, force=True)
    assert ok and (agents / "skills" / "myskill").is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_agents_refuses_real_dir_collision(tmp_path: Path):
    vault = _make_vault(tmp_path)
    agents = tmp_path / ".agents"
    (agents / "skills" / "myskill").mkdir(parents=True)
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    with pytest.raises(FileExistsError):
        axt.link_to_agents(agents, skill)


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_unlink_from_agents_only_removes_matching_link(tmp_path: Path):
    vault = _make_vault(tmp_path)
    agents = tmp_path / ".agents"
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    axt.link_to_agents(agents, skill)
    ok, _ = axt.unlink_from_agents(agents, skill)
    assert ok
    assert not (agents / "skills" / "myskill").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_unlink_from_agents_leaves_foreign_symlink(tmp_path: Path):
    vault = _make_vault(tmp_path)
    agents = tmp_path / ".agents"
    (agents / "skills").mkdir(parents=True)
    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    os.symlink(foreign, agents / "skills" / "myskill")
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    ok, msg = axt.unlink_from_agents(agents, skill)
    assert not ok and "points elsewhere" in msg
    assert (agents / "skills" / "myskill").is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_list_vault_items_enriches_is_agents_linked(tmp_path: Path):
    vault = _make_vault(tmp_path)
    agents = tmp_path / ".agents"
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    axt.link_to_agents(agents, skill)
    items = axt.list_vault_items_with_project_state(
        vault, tmp_path / "proj", agents_dir=agents
    )
    s = next(i for i in items if i.name == "myskill")
    assert s.is_agents_linked is True


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_is_agents_linked_false_for_foreign_symlink(tmp_path: Path):
    vault = _make_vault(tmp_path)
    agents = tmp_path / ".agents"
    (agents / "skills").mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    os.symlink(other, agents / "skills" / "myskill")
    items = axt.list_vault_items_with_project_state(
        vault, tmp_path / "proj", agents_dir=agents
    )
    s = next(i for i in items if i.name == "myskill")
    assert s.is_agents_linked is False


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


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_list_with_project_state_global_dir_enrichment(tmp_path: Path):
    """Passing global_dir enriches items with global-link state. The listing
    stays vault-only: items existing only in the global tree are NOT merged
    in (they belong to the Skills/Commands/Agents sub-tabs)."""
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    gd = tmp_path / "global"
    gd.mkdir()
    # vault skill linked into the global dir → is_global_linked True
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    axt.link_to_global(gd, skill)
    # a global skill that is NOT in the vault → must NOT appear
    extra = gd / "skills" / "global-only"
    extra.mkdir(parents=True)
    (extra / "SKILL.md").write_text("---\ndescription: g\n---\n")
    enriched = axt.list_vault_items_with_project_state(vault, proj, global_dir=gd)
    myskill = next(i for i in enriched if i.name == "myskill")
    assert myskill.is_global_linked is True
    assert not any(i.name == "global-only" for i in enriched)
    # Every row is vault-backed; plugins never appear here.
    assert all(i.in_vault for i in enriched)
    assert not any(i.type == "plugin" for i in enriched)


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


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_project_rejects_real_file_collision(tmp_path: Path):
    """If a REAL (non-symlink) file already occupies the link path, linking
    must raise rather than clobber it."""
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    real = proj / ".claude" / "skills" / "myskill"
    real.mkdir(parents=True)
    (real / "real.txt").write_text("not a symlink")
    with pytest.raises(FileExistsError):
        axt.link_to_project(proj, skill)


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_project_replaces_stale_symlink(tmp_path: Path):
    """A pre-existing symlink at the target is replaced (not an error)."""
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    sub = proj / ".claude" / "skills"
    sub.mkdir(parents=True)
    os.symlink(tmp_path / "somewhere-else", sub / "myskill")  # stale link
    axt.link_to_project(proj, skill)  # should unlink stale + relink
    assert (sub / "myskill").is_symlink()
    assert os.readlink(sub / "myskill") == skill.path


def test_link_to_global_rejects_plugin(tmp_path: Path):
    item = axt.VaultItem(name="p", type="plugin", path="", description="")
    with pytest.raises(ValueError):
        axt.link_to_global(tmp_path, item)


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_sync_project_reports_missing_vault_item(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    axt.write_profile(proj, axt.AxtProfile(skills=("ghost",)))  # not in vault
    result = axt.sync_project(proj, vault)
    assert any("ghost" in e for e in result.errors)


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_sync_project_removes_orphaned_symlink(tmp_path: Path):
    """A vault-pointing symlink not declared in the profile is unlinked."""
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    sub = proj / ".claude" / "skills"
    sub.mkdir(parents=True)
    axt.write_profile(proj, axt.AxtProfile())  # declares nothing
    os.symlink(vault / "skills" / "myskill", sub / "myskill")  # orphan into vault
    result = axt.sync_project(proj, vault)
    assert any("myskill" in u for u in result.unlinked)
    assert not (sub / "myskill").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_sync_project_leaves_foreign_symlink(tmp_path: Path):
    """A symlink that does NOT point into the vault is left untouched."""
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    sub = proj / ".claude" / "skills"
    sub.mkdir(parents=True)
    foreign_target = tmp_path / "elsewhere"
    foreign_target.mkdir()
    axt.write_profile(proj, axt.AxtProfile())
    os.symlink(foreign_target, sub / "external")
    result = axt.sync_project(proj, vault)
    assert all("external" not in u for u in result.unlinked)
    assert (sub / "external").is_symlink()  # untouched


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


# ─── Project-local sources for import_to_vault ───────────────────────────────


def _make_project_local_skill(proj: Path, name: str = "proj-skill") -> Path:
    skill = proj / ".claude" / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A project-local skill\n---\nbody"
    )
    return skill


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_list_with_project_state_excludes_project_local_items(tmp_path: Path):
    """The Vault listing is vault-only: a real project-local skill never
    promoted to the vault must NOT appear (it belongs to the Skills sub-tab)."""
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    _make_project_local_skill(proj, name="local-only")
    enriched = axt.list_vault_items_with_project_state(vault, proj)
    assert not any(i.name == "local-only" for i in enriched)


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


# ─── AxtProfile / description / version parser edges ─────────────────────────


def test_profile_from_json_non_dict_is_empty():
    p = axt.AxtProfile.from_json("not-a-dict")
    assert p.skills == () and p.commands == () and p.agents == () and p.plugins == ()


def test_profile_from_json_non_dict_extensions_is_empty():
    p = axt.AxtProfile.from_json({"extensions": "bad"})
    assert p.skills == () and p.plugins == ()


def test_profile_with_added_present_returns_self():
    p = axt.AxtProfile(skills=("a",))
    assert p.with_added("skills", "a") is p  # no-op short-circuit


def test_profile_with_removed_absent_returns_self():
    p = axt.AxtProfile(skills=("a",))
    assert p.with_removed("skills", "ghost") is p  # no-op short-circuit


def test_parse_yaml_single_quoted_multiline():
    """A single-quoted scalar spanning lines joins with a space."""
    fm = "description: 'line one\n  line two'"
    assert axt.parse_yaml_description(fm) == "line one line two"


def test_read_description_for_item_skill_without_md_returns_empty(tmp_path: Path):
    d = tmp_path / "skill"
    d.mkdir()  # no index.md / SKILL.md
    assert axt._read_description_for_item(d, "skill") == ""


def test_read_version_without_frontmatter_returns_empty(tmp_path: Path):
    f = tmp_path / "x.md"
    f.write_text("no frontmatter at all\n")
    assert axt._read_version(f) == ""


# ─── shared scan primitives (P1 refactor) ────────────────────────────────────


def test_linkable_types_pairs():
    assert axt.LINKABLE_TYPES == (
        ("skills", "skill"),
        ("commands", "command"),
        ("agents", "agent"),
    )


def test_iter_item_entries_missing_dir(tmp_path: Path):
    assert axt._iter_item_entries(tmp_path / "nope") == []


def test_iter_item_entries_sorted_skips_dotfiles(tmp_path: Path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "b.md").write_text("x")
    (d / "a.md").write_text("x")
    (d / ".hidden.md").write_text("x")
    assert [p.name for p in axt._iter_item_entries(d)] == ["a.md", "b.md"]


def test_entry_is_item_skill_requires_dir_with_manifest(tmp_path: Path):
    d = tmp_path / "myskill"
    d.mkdir()
    f = tmp_path / "x.md"
    f.write_text("x")
    bare = tmp_path / "not-a-skill"
    bare.mkdir()
    (d / "SKILL.md").write_text("---\ndescription: d\n---")
    assert axt._entry_is_item(d, "skill") is True
    assert axt._entry_is_item(f, "skill") is False
    assert axt._entry_is_item(bare, "skill") is False


def test_entry_is_item_command_requires_md_file(tmp_path: Path):
    md = tmp_path / "c.md"
    md.write_text("x")
    txt = tmp_path / "c.txt"
    txt.write_text("x")
    d = tmp_path / "d"
    d.mkdir()
    assert axt._entry_is_item(md, "command") is True
    assert axt._entry_is_item(txt, "command") is False
    assert axt._entry_is_item(d, "command") is False


def test_make_vault_item_applies_flags(tmp_path: Path):
    f = tmp_path / "c.md"
    f.write_text("x")
    item = axt._make_vault_item(f, "command", in_vault=True, is_linked=True)
    assert (item.name, item.type, item.path) == ("c.md", "command", str(f))
    assert item.in_vault is True
    assert item.is_linked is True
    assert item.is_global_linked is False   # default preserved


def test_move_path_file_rename(tmp_path: Path):
    src = tmp_path / "a.md"
    src.write_text("data")
    dest = tmp_path / "b.md"
    axt._move_path(src, dest, is_dir=False)
    assert not src.exists()
    assert dest.read_text() == "data"


def test_move_path_dir_rename(tmp_path: Path):
    src = tmp_path / "sd"
    src.mkdir()
    (src / "f.txt").write_text("x")
    dest = tmp_path / "dd"
    axt._move_path(src, dest, is_dir=True)
    assert not src.exists()
    assert (dest / "f.txt").read_text() == "x"


def test_move_path_fallback_when_rename_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    src = tmp_path / "a.md"
    src.write_text("data")
    dest = tmp_path / "b.md"

    def boom(*a, **k):
        raise OSError("cross-device link not permitted")

    monkeypatch.setattr("axt.core.os.rename", boom)
    axt._move_path(src, dest, is_dir=False)   # falls back to copy2 + unlink
    assert not src.exists()
    assert dest.read_text() == "data"


# ─── Broken symlink detection ────────────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_migrate_reports_broken_symlink_not_skipped(tmp_path: Path):
    global_dir = tmp_path / "global"
    (global_dir / "commands").mkdir(parents=True)
    # Dangling symlink: target does not exist (mirrors a deleted vault).
    link = global_dir / "commands" / "commit.md"
    os.symlink(tmp_path / "gone" / "commit.md", link)
    vault = tmp_path / "vault"

    result = axt.migrate_to_vault(global_dir, vault)
    assert "command:commit.md" in result.broken
    assert "command:commit.md" not in result.moved
    assert "command:commit.md" not in result.skipped
    # Detection only — the broken link is left in place, not deleted.
    assert link.is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
def test_find_broken_links(tmp_path: Path):
    claude = tmp_path / ".claude"
    (claude / "commands").mkdir(parents=True)
    (claude / "agents").mkdir(parents=True)
    os.symlink(tmp_path / "missing" / "a.md", claude / "commands" / "a.md")
    (claude / "agents" / "real.md").write_text("body")  # healthy, ignored
    assert axt.find_broken_links(claude) == ["command:a.md"]


def test_find_broken_links_missing_dirs(tmp_path: Path):
    assert axt.find_broken_links(tmp_path / "nope") == []


# ─── Gap-code additions (Phase C, Agent C) ───────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_unlink_from_global_keeps_vault_content(tmp_path: Path):
    """Deactivating globally removes only the symlink — the vault keeps the
    real content (and every other link to it).

    US-VLT05 AC2. Prevents: `unlink-global` following the symlink and deleting
    the stored extension, which would silently destroy the user's only copy
    and break every project still linking it.
    """
    # TC-UNIT-047 (US-VLT05 AC2)
    vault = _make_vault(tmp_path)
    global_dir = tmp_path / "global"
    proj = tmp_path / "proj"
    proj.mkdir()
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    axt.link_to_global(global_dir, skill)
    axt.link_to_project(proj, skill)

    axt.unlink_from_global(global_dir, skill)

    assert not (global_dir / "skills" / "myskill").exists()
    stored = vault / "skills" / "myskill"
    assert stored.is_dir() and not stored.is_symlink()
    assert (stored / "SKILL.md").read_text().startswith("---")
    # A second, independent link to the same vault item is untouched.
    assert (proj / ".claude" / "skills" / "myskill").is_symlink()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_agents_force_overrides_lock_without_removing_it(tmp_path: Path):
    """`--force-agents` mirrors into a lock-managed `.agents` tree, but leaves
    the third-party installer's `.skill-lock.json` in place.

    US-VLT06 AC3. Prevents two regressions: force silently doing nothing (the
    guard is checked before `force`), and force "taking ownership" by deleting
    the lock file — which would make the other installer overwrite our mirror
    on its next run with no warning.
    """
    # TC-UNIT-051 (US-VLT06 AC3)
    vault = _make_vault(tmp_path)
    agents = tmp_path / ".agents"
    agents.mkdir()
    lock = agents / axt.SKILL_LOCK_NAME
    lock.write_text('{"owner": "vercel-labs/skills"}')
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")

    ok, msg = axt.link_to_agents(agents, skill, force=True)

    link = agents / "skills" / "myskill"
    assert ok is True
    assert "myskill" in msg
    assert link.is_symlink()
    # Mirror points at the vault content, exactly as the unforced path does.
    assert os.path.realpath(link) == os.path.realpath(skill.path)
    # The installer's marker survives — axt does not claim the tree.
    assert lock.exists() and lock.read_text() == '{"owner": "vercel-labs/skills"}'


# ─── Project-level .agents/skills mirror (agentsMirror profile entries) ──────


def test_profile_agents_mirror_roundtrip_and_omitted_when_empty(tmp_path: Path):
    """`agentsMirror` is serialized only when used, so a profile without
    mirrors keeps its pre-existing shape; a profile with mirrors reads back."""
    axt.write_profile(tmp_path, axt.AxtProfile(skills=("a",)))
    raw = json.loads((tmp_path / axt.VAULT_PROFILE_NAME).read_text())
    assert "agentsMirror" not in raw["extensions"]

    axt.write_profile(tmp_path, axt.AxtProfile(skills=("a",), agents_mirror=("a", "b")))
    raw = json.loads((tmp_path / axt.VAULT_PROFILE_NAME).read_text())
    assert raw["extensions"]["agentsMirror"] == ["a", "b"]
    got = axt.read_profile(tmp_path)
    assert got is not None and got.agents_mirror == ("a", "b")


def test_profile_without_agents_mirror_key_reads_as_empty(tmp_path: Path):
    """Profiles written before the key existed must still load."""
    (tmp_path / axt.VAULT_PROFILE_NAME).write_text(json.dumps(
        {"extensions": {"skills": ["a"], "commands": [], "agents": [], "plugins": []}}
    ))
    got = axt.read_profile(tmp_path)
    assert got is not None
    assert got.skills == ("a",) and got.agents_mirror == ()


def test_profile_with_added_removed_agents_mirror():
    p = axt.empty_profile().with_added("agents_mirror", "x").with_added("agents_mirror", "x")
    assert p.agents_mirror == ("x",)
    assert p.with_removed("agents_mirror", "x").agents_mirror == ()
    # Other keys untouched by the new field.
    assert p.with_added("skills", "s").agents_mirror == ("x",)


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_project_agents_mirrors_and_records_profile(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    ok, msg = axt.link_to_project_agents(proj, skill)
    assert ok, msg
    link = proj / ".agents" / "skills" / "myskill"
    assert link.is_symlink()
    assert os.path.realpath(link) == os.path.realpath(skill.path)
    prof = axt.read_profile(proj)
    assert prof is not None and prof.agents_mirror == ("myskill",)
    # `.claude/skills` is NOT touched — that is link_to_project's job.
    assert not (proj / ".claude" / "skills" / "myskill").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_project_agents_guard_leaves_profile_untouched(tmp_path: Path):
    """A `.skill-lock.json` skip must not declare a mirror that does not exist,
    or `sync` would keep trying (and failing) to create it."""
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    (proj / ".agents").mkdir(parents=True)
    (proj / ".agents" / axt.SKILL_LOCK_NAME).write_text("{}")
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    ok, msg = axt.link_to_project_agents(proj, skill)
    assert not ok and axt.SKILL_LOCK_NAME in msg
    assert axt.read_profile(proj) is None
    ok, _ = axt.link_to_project_agents(proj, skill, force=True)
    assert ok
    assert axt.read_profile(proj).agents_mirror == ("myskill",)


def test_link_to_project_agents_refuses_non_skill(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    cmd = next(i for i in axt.list_vault_items(vault) if i.type == "command")
    ok, msg = axt.link_to_project_agents(proj, cmd)
    assert not ok and "Only skills" in msg
    assert axt.read_profile(proj) is None


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_link_to_project_agents_refuses_when_project_agents_is_home(tmp_path: Path, monkeypatch):
    """Running from HOME, `<cwd>/.agents` IS `~/.agents`; the global mirror
    owns that tree, so the project path must refuse rather than double-manage."""
    vault = _make_vault(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("axt.core.HOME", home)
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    ok, msg = axt.link_to_project_agents(home, skill)
    assert not ok and "~/.agents" in msg
    assert not (home / ".agents").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_unlink_from_project_agents_removes_link_and_profile_entry(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    axt.link_to_project_agents(proj, skill)
    ok, _ = axt.unlink_from_project_agents(proj, skill)
    assert ok
    assert not (proj / ".agents" / "skills" / "myskill").exists()
    assert axt.read_profile(proj).agents_mirror == ()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_unlink_from_project_agents_drops_entry_but_keeps_foreign_link(tmp_path: Path):
    """Un-declaring is the user's intent, so the profile entry goes even when
    the symlink turns out to belong to someone else — that link stays."""
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    (proj / ".agents" / "skills").mkdir(parents=True)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    os.symlink(foreign, proj / ".agents" / "skills" / "myskill")
    axt.write_profile(proj, axt.AxtProfile(agents_mirror=("myskill",)))
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    ok, msg = axt.unlink_from_project_agents(proj, skill)
    assert not ok and "points elsewhere" in msg
    assert (proj / ".agents" / "skills" / "myskill").is_symlink()
    assert axt.read_profile(proj).agents_mirror == ()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_list_vault_items_enriches_is_project_agents_linked(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    axt.link_to_project_agents(proj, skill)
    items = axt.list_vault_items_with_project_state(
        vault, proj, project_agents_dir=proj / ".agents"
    )
    s = next(i for i in items if i.type == "skill")
    assert s.is_project_agents_linked is True
    assert s.is_agents_linked is False  # global tree not given → untouched
    # Without the argument the field stays at its default.
    s2 = next(i for i in axt.list_vault_items_with_project_state(vault, proj) if i.type == "skill")
    assert s2.is_project_agents_linked is False


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_sync_project_creates_declared_agents_mirror_and_removes_orphan(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    axt.write_profile(proj, axt.AxtProfile(agents_mirror=("myskill",)))
    # An orphan pointing into the vault skills dir, not declared.
    (proj / ".agents" / "skills").mkdir(parents=True)
    os.symlink(vault / "skills" / "myskill", proj / ".agents" / "skills" / "stale")
    # A foreign symlink (outside the vault) must survive.
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    os.symlink(foreign, proj / ".agents" / "skills" / "other")

    result = axt.sync_project(proj, vault)
    assert "skill:myskill (.agents)" in result.linked
    assert "skill:stale (.agents)" in result.unlinked
    assert not result.errors
    link = proj / ".agents" / "skills" / "myskill"
    assert link.is_symlink()
    assert os.path.realpath(link) == os.path.realpath(vault / "skills" / "myskill")
    assert not (proj / ".agents" / "skills" / "stale").exists()
    assert (proj / ".agents" / "skills" / "other").is_symlink()
    # Idempotent: a second run has nothing to do.
    again = axt.sync_project(proj, vault)
    assert not again.linked and not again.unlinked and not again.errors


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_sync_project_does_not_create_agents_dir_when_nothing_declared(tmp_path: Path):
    """A profile with no mirrors must not sprout an empty `.agents/` tree."""
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    axt.write_profile(proj, axt.AxtProfile(skills=("myskill",)))
    axt.sync_project(proj, vault)
    assert not (proj / ".agents").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_sync_project_reports_lock_guard_and_missing_vault_item_for_mirror(tmp_path: Path):
    vault = _make_vault(tmp_path)
    proj = tmp_path / "proj"
    (proj / ".agents").mkdir(parents=True)
    (proj / ".agents" / axt.SKILL_LOCK_NAME).write_text("{}")
    axt.write_profile(proj, axt.AxtProfile(agents_mirror=("myskill", "ghost")))
    result = axt.sync_project(proj, vault)
    assert not result.linked
    assert any(e.startswith("skill:myskill (.agents)") and axt.SKILL_LOCK_NAME in e for e in result.errors)
    assert "skill:ghost (.agents) not found in vault" in result.errors
    assert not (proj / ".agents" / "skills" / "myskill").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_sync_project_skips_agents_mirror_when_project_is_home(tmp_path: Path, monkeypatch):
    """From HOME the project `.agents` is `~/.agents`: sync must neither create
    project mirrors there nor sweep the global mirrors as orphans."""
    vault = _make_vault(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("axt.core.HOME", home)
    skill = next(i for i in axt.list_vault_items(vault) if i.type == "skill")
    axt.link_to_agents(home / ".agents", skill)  # the global mirror
    axt.write_profile(home, axt.AxtProfile(agents_mirror=("myskill",)))
    result = axt.sync_project(home, vault)
    assert (home / ".agents" / "skills" / "myskill").is_symlink()
    assert not result.linked and not result.unlinked
    assert any("~/.agents" in e for e in result.errors)
