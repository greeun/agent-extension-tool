"""Tests for Section 3 (Settings).

Behaviors mirrored from src/core/settings.ts:
  - read_*: missing file → returns {}
  - set_*_enabled / set_*_favorite / set_marked_for_update: idempotent; preserves
    sibling keys (otherKey)
  - remove_plugin_from_settings: deletes only the targeted key
  - falsy operations (favorite=False, marked=False) DELETE rather than set false
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import axt


# ── read_enabled_plugins ─────────────────────────────────────────────────────


def test_read_enabled_plugins_missing_file(tmp_path: Path):
    assert axt.read_enabled_plugins(tmp_path / "nope.json") == {}


def test_read_enabled_plugins_returns_bool_map(seeded_settings: Path):
    assert axt.read_enabled_plugins(seeded_settings) == {"alpha": True, "beta": False}


def test_read_enabled_plugins_corrupt_file(tmp_path: Path):
    p = tmp_path / "settings.json"
    p.write_text('"not an object"')
    assert axt.read_enabled_plugins(p) == {}


# ── set_plugin_enabled ───────────────────────────────────────────────────────


def test_set_plugin_enabled_creates_file(tmp_settings: Path):
    axt.set_plugin_enabled(tmp_settings, "new", True)
    assert json.loads(tmp_settings.read_text()) == {"enabledPlugins": {"new": True}}


def test_set_plugin_enabled_preserves_other_keys(seeded_settings: Path):
    axt.set_plugin_enabled(seeded_settings, "gamma", True)
    data = json.loads(seeded_settings.read_text())
    assert data["otherKey"] == "preserved"
    assert data["enabledPlugins"]["alpha"] is True
    assert data["enabledPlugins"]["gamma"] is True


def test_set_plugin_enabled_toggle(seeded_settings: Path):
    axt.set_plugin_enabled(seeded_settings, "alpha", False)
    assert axt.read_enabled_plugins(seeded_settings)["alpha"] is False


# ── remove_plugin_from_settings ──────────────────────────────────────────────


def test_remove_plugin_from_settings(seeded_settings: Path):
    axt.remove_plugin_from_settings(seeded_settings, "alpha")
    enabled = axt.read_enabled_plugins(seeded_settings)
    assert "alpha" not in enabled
    assert enabled.get("beta") is False  # untouched


def test_remove_plugin_from_settings_missing_key_noop(seeded_settings: Path):
    axt.remove_plugin_from_settings(seeded_settings, "nonexistent")
    # Sibling keys intact.
    assert axt.read_enabled_plugins(seeded_settings) == {"alpha": True, "beta": False}


def test_remove_plugin_from_settings_missing_file(tmp_path: Path):
    # Must not raise even when the file doesn't exist; it creates an empty one.
    p = tmp_path / "settings.json"
    axt.remove_plugin_from_settings(p, "alpha")
    assert p.exists()
    assert json.loads(p.read_text()) == {}


# ── favorite plugins ─────────────────────────────────────────────────────────


def test_read_favorite_plugins_missing(tmp_path: Path):
    assert axt.read_favorite_plugins(tmp_path / "nope.json") == {}


def test_set_plugin_favorite_true(seeded_settings: Path):
    axt.set_plugin_favorite(seeded_settings, "beta", True)
    assert axt.read_favorite_plugins(seeded_settings) == {"alpha": True, "beta": True}


def test_set_plugin_favorite_false_deletes(seeded_settings: Path):
    """favorite=False removes the entry (TS parity)."""
    axt.set_plugin_favorite(seeded_settings, "alpha", False)
    assert axt.read_favorite_plugins(seeded_settings) == {}


# ── marked for update ────────────────────────────────────────────────────────


def test_read_marked_for_update_missing(tmp_path: Path):
    assert axt.read_marked_for_update(tmp_path / "nope.json") == {}


def test_set_marked_for_update_true(seeded_settings: Path):
    axt.set_marked_for_update(seeded_settings, "alpha", True)
    assert axt.read_marked_for_update(seeded_settings) == {"alpha": True, "beta": True}


def test_set_marked_for_update_false_deletes(seeded_settings: Path):
    axt.set_marked_for_update(seeded_settings, "beta", False)
    assert axt.read_marked_for_update(seeded_settings) == {}


# ── extra marketplaces ───────────────────────────────────────────────────────


def test_read_extra_marketplaces(seeded_settings: Path):
    extras = axt.read_extra_marketplaces(seeded_settings)
    assert "custom" in extras
    assert extras["custom"]["source"]["repo"] == "org/custom"


def test_read_extra_marketplaces_missing(tmp_path: Path):
    assert axt.read_extra_marketplaces(tmp_path / "nope.json") == {}


def test_read_extra_marketplaces_non_dict_value_returns_empty(tmp_path: Path):
    """A truthy-but-non-dict extraKnownMarketplaces (e.g. a list) yields {}."""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"extraKnownMarketplaces": ["not", "a", "dict"]}))
    assert axt.read_extra_marketplaces(p) == {}


def test_read_extra_marketplaces_filters_non_dict_entries(tmp_path: Path):
    p = tmp_path / "settings.json"
    p.write_text(
        json.dumps(
            {
                "extraKnownMarketplaces": {
                    "valid": {"source": {"source": "git", "url": "https://x"}},
                    "garbage": "not a dict",
                }
            }
        )
    )
    extras = axt.read_extra_marketplaces(p)
    assert "valid" in extras
    assert "garbage" not in extras


# ── backup is created on overwrite ───────────────────────────────────────────


def test_settings_write_creates_bak(seeded_settings: Path):
    axt.set_plugin_enabled(seeded_settings, "alpha", False)
    backup = seeded_settings.with_suffix(seeded_settings.suffix + ".bak")
    assert backup.exists()
    # Backup has the *previous* content.
    assert json.loads(backup.read_text())["enabledPlugins"]["alpha"] is True
