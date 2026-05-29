"""Tests for the axt package mirror system (axt/__init__.py).

The mirror re-exports submodule globals onto the `axt` namespace and proxies
attribute writes/deletes back to the owning submodule. This is what makes
`monkeypatch.setattr("axt.PATHS", ...)` visible to code that reads `PATHS`
from inside its home submodule — so a regression here would silently break
patching across the whole suite.
"""
from __future__ import annotations

import pytest

import axt


def test_getattr_fallback_resolves_late_submodule_attribute():
    """A name added to a submodule AFTER import is still reachable via the
    package __getattr__ fallback (normal lookup misses → submodule scan)."""
    axt.core.__dict__["_axt_late_probe"] = 4242
    try:
        assert axt._axt_late_probe == 4242
    finally:
        axt.core.__dict__.pop("_axt_late_probe", None)


def test_getattr_unknown_name_raises_attributeerror():
    with pytest.raises(AttributeError):
        _ = axt.this_attribute_does_not_exist_anywhere_xyz


def test_delattr_proxy_removes_from_owning_submodule():
    """`del axt.X` must remove X from the submodule that defines it, not just
    the package facade."""
    axt.core.__dict__["_axt_del_probe"] = 1
    del axt._axt_del_probe
    assert "_axt_del_probe" not in vars(axt.core)


def test_setattr_proxy_writes_through_to_submodule():
    """`axt.X = v` (the mechanism behind monkeypatch.setattr) writes through to
    the submodule that owns X, so submodule-internal reads see the new value."""
    original = axt.core.PATHS
    sentinel = axt.Paths()
    try:
        axt.PATHS = sentinel
        assert axt.core.PATHS is sentinel  # write reached the submodule
    finally:
        axt.PATHS = original
        assert axt.core.PATHS is original
