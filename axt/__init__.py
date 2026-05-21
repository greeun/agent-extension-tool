"""axt — Agent eXtension Tool.

Public API re-exported from ``_core``. Phase C keeps the package shell
intentionally thin: the ``axt`` package and the ``axt._core`` submodule
share the same module namespace, so ``axt.X`` and ``axt._core.X`` refer
to the same slot. This preserves the legacy "everything lives on the
``axt`` module" contract that tests rely on (including ``monkeypatch``
patches against ``axt.PATHS`` / ``axt.AXT_CONFIG_DIR`` etc.).

Subsequent Phase C tasks (C2–C5) will split ``_core`` into per-domain
modules; this file is the only place that needs to change when that
happens.
"""

import importlib as _importlib
import sys as _sys

from axt import _core as _core

# --- Share _core's namespace with the package namespace.
#
# Tests patch attributes on the `axt` module (e.g.
# `monkeypatch.setattr("axt.PATHS", ...)`) and expect those patches to be
# visible from code that reads the same global from inside _core. The
# simplest robust way to make that work is to mirror _core's globals onto
# axt's globals at import time AND to keep them in sync by routing the
# package's __dict__ to point at _core's __dict__.
#
# We can't legally set `axt.__dict__ = _core.__dict__` (modules use a
# read-only dict slot), so we mirror eagerly here and provide a
# `__getattr__` fallback for anything added to _core after this point.
for _name in list(vars(_core).keys()):
    if _name in {"__name__", "__loader__", "__spec__", "__file__",
                 "__package__", "__path__", "__builtins__", "__doc__"}:
        continue
    globals()[_name] = vars(_core)[_name]
del _name

# Explicit re-export for the console-script entry point (`axt = "axt:main"`).
from axt._core import main  # noqa: E402,F401

__version__ = "2.0.0"


def __getattr__(name: str):
    """Fallback for names not mirrored above (defensive).

    Called only when normal attribute lookup on the package fails.
    """
    try:
        return getattr(_core, name)
    except AttributeError:
        raise AttributeError(f"module 'axt' has no attribute {name!r}") from None


def _reload_core() -> None:
    """Re-execute _core (re-reading env vars, etc.) and remirror into axt.

    Tests call ``importlib.reload(axt)`` to pick up env-var changes that
    influence module-level constants like ``CLAUDE_DIR``. Since those
    constants live in ``_core``, reloading just ``axt/__init__.py`` is not
    enough — we must reload ``_core`` first, then refresh the mirror.
    This helper is invoked from the top of ``__init__.py`` when the module
    is being re-executed (detected via the presence of ``__version__`` in
    the existing module dict).
    """
    _importlib.reload(_core)
    for _n in list(vars(_core).keys()):
        if _n in {"__name__", "__loader__", "__spec__", "__file__",
                  "__package__", "__path__", "__builtins__", "__doc__"}:
            continue
        globals()[_n] = vars(_core)[_n]


# If this is a reload (detected by the presence of __version__ in our
# globals before the assignment above takes effect again on the new run),
# Python has already re-executed the file from the top. The mirror loop
# at the top of this file picks up _core's current values — but _core
# itself was NOT reloaded. So a test that did `monkeypatch.setenv(...);
# importlib.reload(axt)` would see stale values. To handle that case,
# re-mirror _core *after* reloading it, but only when this run is a
# reload (the previous run already installed _reload_core in globals).
if "__axt_loaded__" in globals():
    _reload_core()
globals()["__axt_loaded__"] = True


# Mirror attribute writes onto _core so test patches like
# ``monkeypatch.setattr("axt.PATHS", ...)`` are observed by code that
# reads ``PATHS`` from inside _core's module globals.
_this_module = _sys.modules[__name__]


def _install_write_proxy() -> None:
    """Wrap the module class so __setattr__ mirrors writes onto _core.

    We carefully avoid touching dunder attributes (which would re-route
    things like ``__class__``, ``__name__`` and cause recursion).
    """
    base_cls = type(_this_module)
    # Idempotent: if we already installed the proxy, leave it alone.
    if getattr(base_cls, "_axt_proxy_installed", False):
        return

    _MIRRORED_DUNDERS_SKIP = {
        "__class__", "__dict__", "__doc__", "__file__", "__loader__",
        "__name__", "__package__", "__path__", "__spec__",
    }

    class _AxtPackageModule(base_cls):  # type: ignore[misc,valid-type]
        _axt_proxy_installed = True

        def __setattr__(self, name, value):  # type: ignore[override]
            if (
                name not in _MIRRORED_DUNDERS_SKIP
                and name in vars(_core)
            ):
                # Use vars() (a direct dict assignment) to avoid going
                # through any __setattr__ on _core itself.
                vars(_core)[name] = value
            base_cls.__setattr__(self, name, value)

        def __delattr__(self, name):  # type: ignore[override]
            if name not in _MIRRORED_DUNDERS_SKIP and name in vars(_core):
                vars(_core).pop(name, None)
            try:
                base_cls.__delattr__(self, name)
            except AttributeError:
                pass

    _this_module.__class__ = _AxtPackageModule


_install_write_proxy()
