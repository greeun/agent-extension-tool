"""Tests for Section 1 (Constants & Paths).

These tests reload the axt module under various env vars to verify the
resolution rules. The module captures env values at import time (mirrors
the TS implementation), so we use `importlib.reload` rather than deleting
from `sys.modules` — preserving the module object's identity so that
other test files that already did `import axt` keep referencing the same
object after our reload.
"""
from __future__ import annotations

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


def test_codex_home_env_overrides(clean_env, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "/custom/codex")
    axt = _reload_axt()
    assert axt.CODEX_DIR == Path("/custom/codex")
    assert axt.PATHS.codex_sessions == Path("/custom/codex/sessions")


def test_gemini_cli_home_points_above_dotgemini(clean_env, monkeypatch):
    """Mirror the TS quirk: GEMINI_CLI_HOME is the parent of .gemini."""
    monkeypatch.setenv("GEMINI_CLI_HOME", "/custom/parent")
    axt = _reload_axt()
    assert axt.GEMINI_DIR == Path("/custom/parent/.gemini")
    assert axt.PATHS.gemini_tmp == Path("/custom/parent/.gemini/tmp")


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
    axt = _reload_axt()
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        axt.PATHS.claude_dir = Path("/nope")  # type: ignore[misc]


def test_vault_subdirs_under_axt_dir(clean_env, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: Path("/h")))
    axt = _reload_axt()
    assert axt.PATHS.vault == Path("/h/.axt/vault")
    assert axt.PATHS.vault_skills == Path("/h/.axt/vault/skills")
    assert axt.PATHS.vault_commands == Path("/h/.axt/vault/commands")
    assert axt.PATHS.vault_agents == Path("/h/.axt/vault/agents")


def test_cursor_db_path_under_dotcursor(clean_env, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: Path("/h")))
    axt = _reload_axt()
    assert axt.PATHS.cursor_tracking_db == Path(
        "/h/.cursor/ai-tracking/ai-code-tracking.db"
    )
