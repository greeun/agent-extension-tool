"""Shared pytest fixtures for axt.

Importable as `axt` from anywhere in tests/ thanks to pyproject's
`py-modules = ["axt"]` once `pip install -e .` runs; for local CI runs
without an install we also prepend the repo dir to sys.path here.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Allow `import axt` without an editable install in the worktree.
_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test from a tmp dir.

    Several TUI/CLI code paths treat `Path.cwd()` as the project dir
    (vault link/sync, `.axt-profile.json` writes). Without this, tests
    that exercise them leave symlinks and profile files in the repo root
    (git-ignored, so the leak is silent). Tests that need a specific cwd
    still call `monkeypatch.chdir(...)` themselves, which overrides this.
    """
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Path:
    """Path to an empty settings.json under a tmp dir (file does NOT exist yet)."""
    return tmp_path / "settings.json"


@pytest.fixture
def seeded_settings(tmp_path: Path) -> Path:
    """settings.json pre-seeded with one of each known key."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "enabledPlugins": {"alpha": True, "beta": False},
                "favoritePlugins": {"alpha": True},
                "markedForUpdate": {"beta": True},
                "extraKnownMarketplaces": {
                    "custom": {"source": {"source": "github", "repo": "org/custom"}},
                },
                "otherKey": "preserved",
            },
            indent=2,
        )
        + "\n"
    )
    return path


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip env vars that influence path resolution so tests aren't host-coupled."""
    for var in (
        "CLAUDE_CONFIG_DIR",
        "XDG_CONFIG_HOME",
        "APPDATA",
    ):
        monkeypatch.delenv(var, raising=False)
