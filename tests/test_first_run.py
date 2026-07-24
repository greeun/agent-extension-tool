from __future__ import annotations

from pathlib import Path

import pytest

import axt


def test_is_first_run_true_when_marker_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("axt.core.AXT_CONFIG_DIR", tmp_path)
    assert axt.is_first_run() is True


def test_mark_onboarded_creates_marker_and_flips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("axt.core.AXT_CONFIG_DIR", tmp_path)
    assert axt.is_first_run() is True
    axt.mark_onboarded()
    assert (tmp_path / "onboarded").exists()
    assert axt.is_first_run() is False


def test_mark_onboarded_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("axt.core.AXT_CONFIG_DIR", tmp_path)
    axt.mark_onboarded()
    axt.mark_onboarded()  # must not raise
    assert axt.is_first_run() is False


def test_mark_onboarded_swallows_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Point at a path whose parent cannot be created (a file, not a dir).
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setattr("axt.core.AXT_CONFIG_DIR", blocker / "sub")
    axt.mark_onboarded()  # must not raise
    assert axt.is_first_run() is True  # marker never created
