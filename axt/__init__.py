"""axt — Agent eXtension Tool.

Public API re-exported from per-section submodules. Phase C keeps the
package shell intentionally thin: the ``axt`` package mirrors each
submodule's globals onto its own namespace, so ``axt.X`` and
``axt.core.X`` (or ``axt.cli.X``, etc.) refer to the same value. This
preserves the legacy "everything lives on the ``axt`` module" contract
that tests rely on (including ``monkeypatch`` patches against
``axt.PATHS`` / ``axt.AXT_CONFIG_DIR`` / module-level helpers).

Submodules are listed in :data:`_SUBMODULES` and imported in order; when
two submodules define the same name, the *later* one wins (last-write
wins). The write-proxy installed at the bottom routes attribute
assignments back to whichever submodule defined the name, so test
monkeypatches reach the place the function actually reads from.
"""

import importlib as _importlib
import sys as _sys

# Per-section submodules. C2 added ``cli``. C3 added ``tui.widgets``.
# C4 added ``tui.tabs``. C5 added ``tui.loop`` and finished the TUI
# extraction. C6 renamed ``_core`` → ``core`` — ``core.py`` carries
# Sections 1-9 (domain).
# Order matters: later entries override earlier entries when names collide.
#
# ``tui.widgets`` is loaded BEFORE ``core`` only by convention; ``core``
# no longer re-imports from it after the C5 cleanup. Loading widgets
# first keeps lower-level (curses primitive) names earlier in the
# last-write-wins chain.
# ``tui.tabs`` is loaded AFTER ``core`` because it wildcards from
# ``axt.core`` (Section 13 needs Sections 1-9 domain helpers).
# ``tui.loop`` is loaded AFTER ``tui.tabs`` because it wildcards from
# both ``tui.widgets`` and ``tui.tabs``.
# ``cli`` is last so its names win over any same-named helpers (the
# CLI module owns the user-facing ``main`` and console-output formatters).
_SUBMODULES: list[str] = ["tui.widgets", "core", "tui.tabs", "tui.loop", "cli"]

# Imported submodule objects, in the same order as _SUBMODULES. Populated
# by _load_submodules() / _reload_submodules() below.
_loaded_submodules: list = []


_PACKAGE_DUNDERS_SKIP = {
    "__name__", "__loader__", "__spec__", "__file__",
    "__package__", "__path__", "__builtins__", "__doc__",
}


def _mirror_into_package(mod) -> None:
    """Copy every public/private (non-dunder-skip) name from ``mod`` into
    this package's globals. Called once per submodule at import and on
    reload."""
    g = globals()
    for name, value in vars(mod).items():
        if name in _PACKAGE_DUNDERS_SKIP:
            continue
        g[name] = value


def _load_submodules() -> None:
    """Import each submodule in order and mirror its globals into axt."""
    _loaded_submodules.clear()
    for mod_name in _SUBMODULES:
        mod = _importlib.import_module(f"axt.{mod_name}")
        _loaded_submodules.append(mod)
        _mirror_into_package(mod)


_load_submodules()

# Explicit re-export for the console-script entry point (`axt = "axt:main"`).
# `main` is mirrored from ``axt.cli`` above; this line documents the
# contract and gives IDEs / static checkers something to find.
from axt.cli import main  # noqa: E402,F401

__version__ = "1.6.0"


def _find_submodule_with(name: str):
    """Return the most-recently-loaded submodule that defines ``name``, or
    None if no submodule defines it. ``vars(mod)`` is checked directly so
    we observe the live module dict (post-monkeypatch)."""
    for mod in reversed(_loaded_submodules):
        if name in vars(mod):
            return mod
    return None


def __getattr__(name: str):
    """Fallback for names not mirrored at import time.

    Called only when normal attribute lookup on the package fails. We
    consult submodules in reverse order so the last-defined wins,
    matching the mirror loop.
    """
    mod = _find_submodule_with(name)
    if mod is not None:
        return getattr(mod, name)
    raise AttributeError(f"module 'axt' has no attribute {name!r}")


def _reload_submodules() -> None:
    """Re-execute every submodule (re-reading env vars, etc.) and refresh
    the mirror.

    Tests call ``importlib.reload(axt)`` to pick up env-var changes that
    influence module-level constants like ``CLAUDE_DIR``. Since those
    constants live in the submodules, reloading just ``axt/__init__.py``
    is not enough — we must reload each submodule first, then refresh
    the mirror. This helper is invoked from below when this module is
    being re-executed (detected via ``__axt_loaded__`` in globals).
    """
    _loaded_submodules.clear()
    for mod_name in _SUBMODULES:
        mod = _sys.modules.get(f"axt.{mod_name}")
        if mod is None:
            mod = _importlib.import_module(f"axt.{mod_name}")
        else:
            mod = _importlib.reload(mod)
        _loaded_submodules.append(mod)
        _mirror_into_package(mod)


# Reload-detection: when ``importlib.reload(axt)`` runs the file a second
# time, the previous globals (including ``__axt_loaded__``) are still
# attached to this module — so we re-execute submodules and re-mirror.
if "__axt_loaded__" in globals():
    _reload_submodules()
globals()["__axt_loaded__"] = True


# ── Write-proxy ───────────────────────────────────────────────────────────────
#
# Mirror attribute writes onto whichever submodule defines the name, so
# test patches like ``monkeypatch.setattr("axt.PATHS", ...)`` are observed
# by code that reads ``PATHS`` from inside its home submodule's globals.
_this_module = _sys.modules[__name__]


def _install_write_proxy() -> None:
    """Wrap the module class so __setattr__ mirrors writes to submodules."""
    base_cls = type(_this_module)
    if getattr(base_cls, "_axt_proxy_installed", False):
        return

    _MIRRORED_DUNDERS_SKIP = {
        "__class__", "__dict__", "__doc__", "__file__", "__loader__",
        "__name__", "__package__", "__path__", "__spec__",
    }

    class _AxtPackageModule(base_cls):  # type: ignore[misc,valid-type]
        _axt_proxy_installed = True

        def __setattr__(self, name, value):  # type: ignore[override]
            if name not in _MIRRORED_DUNDERS_SKIP:
                # Write to every submodule that already defines this
                # name. Last-write-wins matches the mirror import order;
                # writing to all matching submodules keeps state
                # consistent even when (rarely) two submodules both
                # expose the same symbol.
                for mod in _loaded_submodules:
                    if name in vars(mod):
                        vars(mod)[name] = value
            base_cls.__setattr__(self, name, value)

        def __delattr__(self, name):  # type: ignore[override]
            if name not in _MIRRORED_DUNDERS_SKIP:
                for mod in _loaded_submodules:
                    if name in vars(mod):
                        vars(mod).pop(name, None)
            try:
                base_cls.__delattr__(self, name)
            except AttributeError:
                pass

    _this_module.__class__ = _AxtPackageModule


_install_write_proxy()
