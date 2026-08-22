"""Tests for Section 1 (Constants & Paths).

These tests reload the axt module under various env vars to verify the
resolution rules. The module captures env values at import time (mirrors
the TS implementation), so we use `importlib.reload` rather than deleting
from `sys.modules` — preserving the module object's identity so that
other test files that already did `import axt` keep referencing the same
object after our reload.
"""
from __future__ import annotations

import dataclasses
import importlib
import sys
from pathlib import Path

import pytest

import axt as _axt_module


def _reload_axt():
    """Re-execute axt's top-level code with whatever env vars are set NOW.

    `importlib.reload` rebinds attributes on the existing module object,
    so anyone holding `import axt` still sees the new values.
    """
    return importlib.reload(_axt_module)


def test_default_claude_dir_is_home_dotclaude(clean_env, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: Path("/tmp/fake-home")))
    axt = _reload_axt()
    assert axt.CLAUDE_DIR == Path("/tmp/fake-home/.claude")
    assert axt.PATHS.settings == Path("/tmp/fake-home/.claude/settings.json")
    assert axt.PATHS.installed_plugins == Path(
        "/tmp/fake-home/.claude/plugins/installed_plugins.json"
    )


def test_claude_config_dir_env_overrides(clean_env, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/custom/claude")
    axt = _reload_axt()
    assert axt.CLAUDE_DIR == Path("/custom/claude")
    assert axt.PATHS.settings == Path("/custom/claude/settings.json")


def test_empty_env_var_falls_back_to_default(clean_env, monkeypatch):
    """Empty-string env var should NOT override default (treat as unset)."""
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: Path("/h")))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "")
    axt = _reload_axt()
    assert axt.CLAUDE_DIR == Path("/h/.claude")


def test_axt_config_dir_unix(clean_env, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: Path("/h")))
    axt = _reload_axt()
    assert axt.AXT_CONFIG_DIR == Path("/h/.config/axt")
    assert axt.AXT_CONFIG_PATH == Path("/h/.config/axt/config.json")


def test_axt_config_dir_xdg(clean_env, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg")
    axt = _reload_axt()
    assert axt.AXT_CONFIG_DIR == Path("/xdg/axt")


def test_paths_object_is_frozen(clean_env):
    """PATHS is a frozen dataclass — assignment must fail."""
    # Fixed: `pytest.raises(Exception)` accepted ANY failure (a typo in the
    # attribute name, an import error) as proof of frozen-ness — a false
    # positive per TEST_DEDUP_POLICY.md §4. Narrowed to the two types a
    # frozen dataclass can actually raise.
    axt = _reload_axt()
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        axt.PATHS.claude_dir = Path("/nope")  # type: ignore[misc]


def test_project_settings_path_defaults_to_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import axt
    assert axt.project_settings_path() == tmp_path / ".claude" / "settings.json"


def test_project_settings_path_explicit_cwd(tmp_path: Path):
    import axt
    assert axt.project_settings_path(tmp_path) == tmp_path / ".claude" / "settings.json"


def test_vault_subdirs_under_axt_dir(clean_env, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: Path("/h")))
    axt = _reload_axt()
    assert axt.PATHS.vault == Path("/h/.axt/vault")
    assert axt.PATHS.vault_skills == Path("/h/.axt/vault/skills")
    assert axt.PATHS.vault_commands == Path("/h/.axt/vault/commands")
    assert axt.PATHS.vault_agents == Path("/h/.axt/vault/agents")



# ─── Gap-code additions (Phase C, Agent C) ───────────────────────────────────


def test_claude_config_dir_moves_the_claude_json_file(clean_env, monkeypatch):
    """`~/.claude.json` (MCP registrations, project entries, plan tier) must
    follow CLAUDE_CONFIG_DIR too.

    Prevents: a user on a relocated config dir having axt read/write the
    home-default `~/.claude.json` while Claude Code uses the relocated one —
    `mcp disable` writes would land in a file nothing reads.
    """
    # TC-UNIT-004 (US-SYS03 AC1)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: Path("/h")))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/custom/claude")
    axt = _reload_axt()
    assert axt.CLAUDE_CONFIG_FILE == Path("/custom/claude/.claude.json")
    assert axt.PATHS.claude_config == Path("/custom/claude/.claude.json")

    # Unset → the file sits beside ~/.claude/, not inside it.
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    axt = _reload_axt()
    assert axt.CLAUDE_CONFIG_FILE == Path("/h/.claude.json")
    assert axt.PATHS.claude_config == Path("/h/.claude.json")


def test_axt_config_dir_windows_uses_appdata(clean_env, monkeypatch):
    """On win32 the axt config dir is %APPDATA%/axt, falling back to
    ~/AppData/Roaming/axt when APPDATA is unset.

    Prevents: writing the theme/plan config (and the onboarded marker) to a
    POSIX-style `~/.config/axt` on Windows, where nothing reads it back.
    """
    # TC-UNIT-007 (US-SYS03 AC2·AC3)
    try:
        monkeypatch.setattr("sys.platform", "win32")
        monkeypatch.setenv("APPDATA", "C:\\Users\\u\\AppData\\Roaming")
        axt = _reload_axt()
        assert axt.IS_WINDOWS is True
        assert axt.AXT_CONFIG_DIR == Path("C:\\Users\\u\\AppData\\Roaming") / "axt"
        assert axt.AXT_CONFIG_PATH == Path("C:\\Users\\u\\AppData\\Roaming") / "axt" / "config.json"
        # XDG_CONFIG_HOME must NOT win on Windows.
        monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg")
        axt = _reload_axt()
        assert axt.AXT_CONFIG_DIR == Path("C:\\Users\\u\\AppData\\Roaming") / "axt"

        monkeypatch.delenv("APPDATA")
        monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: Path("/h")))
        axt = _reload_axt()
        assert axt.AXT_CONFIG_DIR == Path("/h") / "AppData" / "Roaming" / "axt"
    finally:
        # Undo BEFORE reloading: a module left with IS_WINDOWS=True would make
        # every later symlink test in the session fail.
        monkeypatch.undo()
        _reload_axt()
