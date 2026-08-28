"""TUI tabs — TuiState + per-tab render/handle functions + dispatch tables.

This module owns Section 13 of the original monolith: every per-tab
``render_*`` / ``handle_*`` function, the tab-specific data caches that
hang off :class:`TuiState`, and the ``TAB_RENDERERS`` / ``TAB_HANDLERS``
dispatch tables consumed by the main loop (Section 14, currently in
:mod:`axt.core`).

Imports follow the C-phase layering convention:

- Widget primitives (Sections 11-12) come from :mod:`axt.tui.widgets`.
- Domain logic (Sections 1-9) comes from :mod:`axt.core` via a
  wildcard re-export, mirrored to keep the legacy bare-name references
  inside Section 13 working without touching every call-site.

The wildcard imports below run during ``axt`` package initialization
(after ``tui.widgets`` and ``core`` have populated their globals — see
``axt/__init__.py`` ``_SUBMODULES``).
"""

from __future__ import annotations

import curses
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional

# Widget primitives — bring in everything from the TUI widgets layer.
from axt.tui.widgets import *  # noqa: F401,F403
from axt.tui.widgets import (  # noqa: F401 — wildcard skips `_`-prefixed names
    _addstr_search_hl,
    _draw_cell,
    _safe_pair,
    _wrap_to_cells,
)

# Domain logic — pull from core. (After Phase C, this dependency direction
# is fine: tabs depend on domain, not the other way around.)
from axt.core import *  # noqa: F401,F403
from axt.core import (  # noqa: F401 — `_`-prefixed names that wildcard skips
    _active_plugins,
    _add_to_index,
    _date_in_tz,
    _days_ago_in_tz,
    _iso_now,
    _project_name_from_path,
    _today_in_tz,
    _ts_ms,
    _type_to_dir,
    _unified_to_claude,
)
# Update orchestration — kept as module-level names (not wildcard-imported)
# so tests can monkeypatch axt.tui.tabs.check_all_updates / apply_updates.
from axt.update import (  # noqa: F401
    check_all_updates,
    apply_updates,
    check_path_update,
    apply_path_update,
    load_cached_update_statuses,
    save_cached_update_statuses,
    UpdateStatus,
    UPDATE_STATUS_TTL_S,
)


# ── Section 13: TUI — Tabs (initial: Vault + stubs for the rest) ─────────────
#
# This release focuses on the Vault tab — the one whose Ink rendering caused
# the original "selected row disappears" bug. Other tabs are stubbed so the
# tab bar still works; their full implementations land in follow-up commits.


@dataclass
class TuiState:
    """Mutable per-session UI state. Each tab reads/writes its own bucket."""
    tab_idx: int = 0
    focused_layer: str = "mainTab"  # "mainTab" | "subTab" | "content"
    refresh_token: int = 0          # bump to force data reload
    status: str = ""
    # Render kind for `status` — "info" (dim), "ok" (green), "error" (red).
    # Set by set_status(); the status bar colors the message text with it.
    status_kind: str = "info"
    # Monotonic timestamp when `status` was last set. The main loop clears
    # `status` after STATUS_TIMEOUT_S so the shortcut hints come back.
    status_set_at: Optional[float] = None
    show_help: bool = False

    # Vault-specific state.
    vault_items: list[VaultItem] = field(default_factory=list)
    vault_selected: int = 0
    vault_filter: str = "all"        # "all" | "skill" | "command" | "agent"
    vault_sort: str = "name"         # active column key — see _SORT_COLUMNS["vault"]
    # Sort direction for `vault_sort`. None = that column's natural direction
    # (`desc_first` in _SORT_COLUMNS), so setting only the key still yields the
    # sensible order. `s` / `S` write an explicit bool.
    vault_sort_desc: Optional[bool] = None
    vault_search: str = ""
    vault_searching: bool = False    # True while user is typing in the `/` prompt
    vault_pending_project: set[str] = field(default_factory=set)   # item names toggled but not applied
    vault_pending_global: set[str] = field(default_factory=set)
    vault_marked: set[str] = field(default_factory=set)  # item names marked for bulk unlink-from-all (Space)
    vault_scan_mode: str = "default"  # "default" (profile + symlinks) | "full" (+ plugin settings)
    vault_usage_index: dict[str, Any] = field(default_factory=dict)  # type:name → ExtensionUsage
    vault_detail_focused: bool = False  # Enter → focus detail panel, Esc → blur back
    vault_detail_scroll: int = 0
    # Background cross-project scan (mirrors the Usage tab's async loader).
    # At launch the cached index paints instantly, then a daemon thread
    # re-walks ~/.claude/projects/* so the `Used` column reflects current
    # reality with no manual `f`. The main loop polls while loading is True.
    vault_scan_loading: bool = False
    vault_scan_failed: str = ""
    vault_scan_thread: Optional[Any] = None  # threading.Thread, kept generic
    vault_scanned_at: Optional[str] = None   # ISO8601 of the last completed scan

    # Extensions sub-tab state.
    ext_sub_tab: str = "vault"                     # one of EXTENSION_SUB_TABS keys
    ext_cache: dict[str, Any] = field(default_factory=dict)
    ext_selected: dict[str, int] = field(default_factory=dict)
    # Active sort key per non-vault sub-tab (mirrors `vault_sort`). Empty →
    # the first column of that sub-tab's `_SORT_COLUMNS` is the default.
    ext_sort: dict[str, str] = field(default_factory=dict)
    # Sort direction per non-vault sub-tab. A missing entry means "this
    # column's natural direction" (mirrors `vault_sort_desc`).
    ext_sort_desc: dict[str, bool] = field(default_factory=dict)
    ext_detail_focused: bool = False  # Tab → focus the bottom detail panel (plugins/mcp/hooks)
    ext_detail_scroll: int = 0
    ext_search: dict[str, str] = field(default_factory=dict)  # applied `/` query per sub-tab
    ext_searching: bool = False  # True while typing in a non-vault `/` prompt
    # Space-marked item keys per non-vault sub-tab (mirrors vault_marked).
    # Marks accumulate across sort/search changes; p/g apply to the whole set.
    ext_marked: dict[str, set[str]] = field(default_factory=dict)
    # Async update-availability check backing the non-vault `Upd` column.
    # None = never loaded; the first non-vault render kicks a background
    # check (disk cache short-circuits it while fresh — UPDATE_STATUS_TTL_S).
    update_statuses: Optional[dict[tuple[str, str], Any]] = None  # (type, name) → UpdateStatus
    update_checked_at: Optional[str] = None  # ISO8601 of the last completed check
    update_check_loading: bool = False
    # Set when a whole sweep/scan fails. Without it a dead worker renders
    # exactly like a clean empty result and the user never learns it died.
    update_check_failed: str = ""
    update_check_thread: Optional[Any] = None  # threading.Thread, kept generic

    # Usage data caches (None = not loaded yet).
    usage_entries: Optional[list] = None
    usage_config: Optional[Any] = None
    # Async-load state for the Usage tab. A background thread fills
    # `usage_entries` / `usage_config`; the main loop polls while
    # `usage_loading` is True so the next frame picks up the result.
    usage_loading: bool = False
    usage_load_failed: str = ""
    usage_load_thread: Optional[Any] = None  # threading.Thread, kept generic
    # Viewport scroll offset (lines, not pixels). Bumped by j/k/PgUp/PgDn
    # in `handle_usage_input` and clamped by `render_usage_tab` against
    # the actual line-buffer length.
    usage_scroll: int = 0
    # Cached line buffer for the body. Signature includes the identities
    # of `usage_entries` / `usage_config` plus the terminal width — when
    # any of those changes, the worker / resize triggers a fresh build.
    # Scroll keys do NOT bust this cache; they only clip the visible slice.
    usage_lines: Optional[list] = None
    usage_lines_sig: Optional[tuple] = None
    # `/`-search over the usage line buffer. Unlike the list tabs this is a
    # match-jump (preview_modal-style n/N navigation), not a filter — the
    # report's structure (charts, tables) must stay intact.
    usage_search: str = ""
    usage_searching: bool = False   # True while typing in the `/` prompt
    usage_match_idx: int = -1       # current position within the match list
    # Scroll offset when `/` was pressed — the live-jump anchor: while typing,
    # the viewport follows the first match at/after this row and falls back
    # to it when the query stops matching (or on Esc-cancel).
    usage_search_anchor: int = 0

    # Context tab.
    context_analysis: Optional[Any] = None
    context_selected: int = 0
    # Active Context sub-tab: "sources" (live context-window breakdown) or
    # "project" (per-project context files). Rate limits render above both
    # sub-tabs as a persistent strip. ←/→ at the subTab focus layer or [/] in
    # the body cycle between them — mirrors the Extensions sub-tab model.
    context_sub_tab: str = "project"
    # Shared bottom detail panel (mirrors the active sub-tab's selected row).
    # Enter focuses it (j/k / PgUp/PgDn scroll, Esc blurs — vault pattern);
    # `v` opens the full-content preview modal. Scroll resets on selection
    # move, blur, and sub-tab cycle.
    context_detail_focused: bool = False
    context_detail_scroll: int = 0
    # `/`-search over the Context sub-tab lists (mirrors ext_search).
    context_search: dict[str, str] = field(default_factory=dict)  # applied query per sub-tab
    context_searching: bool = False  # True while typing in a Context `/` prompt

    # Project context files (rendered as the Context tab's "project" sub-tab).
    # Detail-panel scroll is owned by context_detail_scroll, not here.
    project_items: Optional[list] = None
    project_selected: int = 0
    # Active `s`-cycle sort key for the Project sub-tab (mirrors ext_sort).
    project_sort: str = "tokens"

    # Bridge between handler functions and curses-bound widgets. The handlers
    # don't receive stdscr (so they remain unit-testable), so we stash a dict
    # the main loop populates. Tests leave it None → modal/editor actions
    # become no-ops, which is the desired test behavior.
    stdscr_callbacks: Optional[dict] = None


_VAULT_FILTERS = ("all", "skill", "command", "agent")
# Vault's sort cycle and its per-column ▲/▼ mark live in _SORT_COLUMNS["vault"]
# alongside every other sub-tab's (see `_VAULT_SORTS` there for the key order).

# Seconds after which `state.status` auto-clears so shortcut hints reappear.
STATUS_TIMEOUT_S: float = 5.0

# Empty-state guidance for the Extensions list sub-tabs (vault handled
# separately in render_vault_tab). Shown by _render_list_with_detail when a
# sub-tab has zero rows: a title line plus an actionable next-step hint.
# Keys are the verbatim EXTENSION_SUB_TABS ids. Hints reference real
# keybindings (see SUBTAB_KEYMAP): skills `a`=link path / `i`=import;
# commands & agents `i`=import; market `a`=add. plugins/mcp/hooks have no
# create key, so their hints point at the source of truth instead.
_EMPTY_STATE_HINTS: dict[str, tuple[str, str]] = {
    "plugins": ("No plugins installed yet.",
                "Add a marketplace on the Market sub-tab; installed plugins appear here."),
    "market": ("No marketplaces added yet.",
               "Press `a` to add one (github:user/repo, git:url, dir:/path)."),
    "skills": ("No skills found yet.",
               "Add a skill under ~/.claude/skills/, or press `a` to link an external path."),
    "commands": ("No commands found yet.",
                 "Add .md files under ~/.claude/commands/, or press `i` to import into the vault."),
    "agents": ("No agents found yet.",
               "Add .md files under ~/.claude/agents/, or press `i` to import into the vault."),
    "mcp": ("No MCP servers configured.",
            "Configure servers in ~/.claude/settings.json or .mcp.json."),
    "hooks": ("No hooks configured.",
              "Add hooks under the `hooks` key in ~/.claude/settings.json."),
}


def _empty_state_hint(key: str) -> tuple[str, str]:
    """(title, hint) shown when an Extensions sub-tab has no rows.

    Unknown keys fall back to the historical bare message with no hint, so a
    newly-added sub-tab never crashes the renderer.
    """
    return _EMPTY_STATE_HINTS.get(key, (f"No {key} found.", ""))


# Failure markers, checked before the ok-prefixes so "Sync failed: …" lands
# on "error" even though "sync" is also an ok-prefix.
_STATUS_ERROR_TOKENS = (
    "failed", "error", "not found", "unsupported", "cannot", "read-only",
)
# Leading words of state-change confirmations (link/toggle/apply/import/…).
_STATUS_OK_PREFIXES = (
    "linked", "unlinked", "enabled", "disabled", "applied", "imported",
    "migrated", "synced", "sync:", "added", "removed", "uninstalled",
    "refreshed", "opened", "saved", "theme:", "search cleared", "discarded",
)


def classify_status(msg: str) -> str:
    """Map a status message to its render kind: "error" | "ok" | "info".

    Handlers return plain strings, so the kind is derived from the text:
    failure markers → "error" (red), action confirmations → "ok" (green),
    everything else (hints, prompts, progress) → "info" (dim, as before).
    """
    low = msg.strip().lower()
    if any(tok in low for tok in _STATUS_ERROR_TOKENS):
        return "error"
    if low.startswith(_STATUS_OK_PREFIXES):
        return "ok"
    return "info"


def set_status(state: TuiState, msg: str, kind: Optional[str] = None) -> None:
    """Set the bottom-bar status message and start its auto-clear timer.

    Pass ``""`` to clear immediately. The main loop polls and clears the
    status after :data:`STATUS_TIMEOUT_S` seconds so the shortcut hints
    become visible again on narrow terminals.

    ``kind`` picks the status-bar color ("info" | "ok" | "error"); when
    omitted it is derived from the message via :func:`classify_status`.
    """
    state.status = msg
    state.status_kind = (kind or classify_status(msg)) if msg else "info"
    state.status_set_at = time.monotonic() if msg else None


def flash_status(state: TuiState, msg: str, kind: str = "info") -> None:
    """Paint a transient status line *now*, before a blocking action.

    The normal flow (`set_status` → handler return value → repaint) only
    redraws after the handler returns, so a slow synchronous op — a git
    fetch/pull during `u` update — freezes the UI with no feedback. This sets
    the status and forces one synchronous frame through the render callback the
    main loop registers in `stdscr_callbacks["render"]`. A no-op when no state
    or render callback is present (tests, headless)."""
    if state is None:
        return
    set_status(state, msg, kind)
    cb = state.stdscr_callbacks
    render = cb.get("render") if cb else None
    if render:
        try:
            render()
        except Exception:  # noqa: BLE001 — feedback paint must never break the action
            pass


def _invalidate_context(state: TuiState) -> None:
    """Mark Context analysis stale so the next Context/Usage paint re-runs
    ``analyze_context()``. Call from any branch that mutates filesystem
    state observed by the analyzer: plugin enable/disable/uninstall, skill
    link/unlink, vault link/unlink/import/migrate/sync, marketplace
    add/remove. Pure cache invalidation — the re-analysis itself happens
    lazily inside ``_ensure_context_loaded`` / ``_kick_usage_reload``.
    """
    state.context_analysis = None
    state.context_detail_focused = False
    state.context_detail_scroll = 0


def _refresh_ext(state: TuiState, sub: str) -> None:
    """Drop the cached listing for `sub`, reload it immediately, and re-anchor
    the selection on the same item by identity — the standard pair after any
    extension mutation in the Extensions tab.

    A mutation can reorder the sort or insert a new row (e.g. `g` linking a
    plugin-sourced agent into ~/.claude/agents adds an unprefixed entry that
    sorts ahead of the plugin's own `plugin:name` row), so reusing the old
    numeric selection index would silently focus a different item. Falls
    back to the stale numeric index (clamped downstream) when the previously
    selected item no longer exists, e.g. after uninstall/unlink."""
    selected_key = None
    if sub in state.ext_cache:
        view = _subtab_view(state, sub)
        idx = state.ext_selected.get(sub, 0)
        if 0 <= idx < len(view):
            selected_key = _item_key(sub, view[idx])
    state.ext_cache.pop(sub, None)
    _invalidate_context(state)
    if selected_key is not None:
        _ensure_subtab_loaded(state, sub)
        new_view = _subtab_view(state, sub)
        new_idx = next((i for i, it in enumerate(new_view) if _item_key(sub, it) == selected_key), None)
        if new_idx is not None:
            state.ext_selected[sub] = new_idx


def _vault_load(state: TuiState) -> None:
    """Refresh vault items from disk into state. Cheap — just reads metadata."""
    state.vault_items = list_vault_items_with_project_state(
        PATHS.vault,
        Path.cwd(),
        global_dir=PATHS.claude_dir,
        agents_dir=HOME / ".agents",
    )


_SCAN_CACHE_NAME = "vault-scan-index.json"


# ─── Vault scan cache policy ────────────────────────────────────────────────
#
# Cache file: <AXT_CONFIG_DIR>/cache/vault-scan-index.json
#   - POSIX:   ~/.config/axt/cache/vault-scan-index.json
#              (or $XDG_CONFIG_HOME/axt/cache/... if XDG_CONFIG_HOME is set)
#   - Windows: %APPDATA%/axt/cache/vault-scan-index.json
#   The on-disk payload carries a `"mode"` tag of either "default" or "full"
#   (see ``TuiState.vault_scan_mode``).
#
# Invalidation:
#   - Cache is best-effort and has NO TTL. It is read on vault-tab entry (and
#     at launch via ``_prime_vault_scan``) for an instant paint, then a
#     background scan refreshes it — so the cache is self-healing each session.
#   - The user can force a refresh by pressing `f` in the Vault tab (current
#     mode) or `M` (toggle mode, then re-scan).
#   - Staleness IS surfaced: the title bar appends the relative scan age
#     (``scan=default(12/40, 2m ago)``) or ``scanning…`` while a scan runs.
#
# Concurrency:
#   - Writes go through ``write_json_atomic`` (tempfile + os.replace), so
#     concurrent reads never see a partial file.
#   - No file locking — assumed single-user, single-process tool.
#
# Schema versioning:
#   - Current payload shape: ``{ "mode": str, "scannedAt": ISO8601,
#     "entries": { "<type>:<name>": {type, name, projects: [...]} } }``.
#     No ``"version"`` field today; loaders tolerate missing/extra keys.
#   - Future schema changes should add a ``"version": N`` field; loaders
#     can treat missing version as v0.
# ────────────────────────────────────────────────────────────────────────────


def _scan_cache_path() -> Path:
    return AXT_CONFIG_DIR / "cache" / _SCAN_CACHE_NAME


# Persists the result of `f`-triggered cross-project scans.
# See "Vault scan cache policy" above.
def _save_scan_cache(index: dict[str, ExtensionUsage], mode: str) -> None:
    """Persist the cross-project scan so it survives axt restarts.

    Stored as `{ mode, scannedAt, entries: { "type:name": {projects: [...]} } }`
    next to the usage caches (`~/.config/axt/cache/`).
    """
    payload = {
        "mode": mode,
        "scannedAt": _iso_now(),
        "entries": {
            key: {
                "type": usage.type,
                "name": usage.name,
                "projects": [{"path": p.path, "name": p.name} for p in usage.projects],
            }
            for key, usage in index.items()
        },
    }
    try:
        write_json_atomic(_scan_cache_path(), payload)
    except OSError:
        pass  # best-effort cache; never fail the scan


# Reads the most recent scan result. Never used as a substitute for live data —
# only populates the "Used" column.
# See "Vault scan cache policy" above.
def _load_scan_cache() -> tuple[dict[str, ExtensionUsage], str, Optional[str]]:
    """Return (index, mode, scanned_at).

    Empty index + 'default' mode + None timestamp when no cache exists yet.
    `scanned_at` is the ISO8601 stamp of the last scan, used to surface the
    cache age in the title bar.
    """
    data = read_json(_scan_cache_path(), fallback={})
    if not isinstance(data, dict):
        return {}, "default", None
    entries = data.get("entries", {})
    if not isinstance(entries, dict):
        return {}, "default", None
    index: dict[str, ExtensionUsage] = {}
    for key, value in entries.items():
        if not isinstance(value, dict):
            continue
        projects_raw = value.get("projects") or []
        projects = [
            ProjectRef(path=str(p.get("path", "")), name=str(p.get("name", "")))
            for p in projects_raw
            if isinstance(p, dict)
        ]
        index[key] = ExtensionUsage(
            type=str(value.get("type", "")),
            name=str(value.get("name", "")),
            projects=projects,
        )
    scanned_at = data.get("scannedAt")
    return index, str(data.get("mode", "default")), (
        str(scanned_at) if scanned_at else None
    )


def _vault_scan(state: TuiState) -> None:
    """Cross-project scan: walk ~/.claude/projects/* to count usage per item.
    Slower than refresh — only call on explicit user request (`f` key).
    Writes the result to disk so it survives axt restarts.
    """
    state.vault_usage_index = scan_project_usage(
        PATHS.projects, PATHS.vault, mode=state.vault_scan_mode,
    )
    state.vault_scanned_at = _iso_now()
    _save_scan_cache(state.vault_usage_index, state.vault_scan_mode)


def _kick_vault_scan(state: TuiState) -> None:
    """Background cross-project scan (mirrors ``_kick_usage_reload``).

    Idempotent: a no-op while a scan is already in flight. The previously
    loaded (cached) index stays visible until the daemon worker rebinds
    ``vault_usage_index`` with fresh data and re-persists it. The main loop
    polls while ``vault_scan_loading`` is True so the result paints without
    user input.
    """
    if state.vault_scan_loading:
        return
    state.vault_scan_loading = True
    mode = state.vault_scan_mode  # captured: the worker scans in this mode

    def _worker() -> None:
        try:
            index = scan_project_usage(PATHS.projects, PATHS.vault, mode=mode)
            state.vault_usage_index = index
            state.vault_scanned_at = _iso_now()
            _save_scan_cache(index, mode)
            state.vault_scan_failed = ""
        except Exception as exc:  # noqa: BLE001
            # An escaping exception would be printed to stderr by the default
            # thread excepthook — the same terminal curses owns, which garbles
            # the screen. Record it for the status line instead.
            state.vault_scan_failed = str(exc) or exc.__class__.__name__
        finally:
            state.vault_scan_loading = False

    t = threading.Thread(target=_worker, name="axt-vault-scan", daemon=True)
    state.vault_scan_thread = t
    t.start()


def _prime_vault_scan(state: TuiState) -> None:
    """Restore the cached scan for an instant `Used` paint, then kick a
    background refresh. Called once at TUI launch so the user sees current
    project usage without pressing `f`."""
    if not state.vault_usage_index:
        cached_index, cached_mode, cached_at = _load_scan_cache()
        if cached_index:
            state.vault_usage_index = cached_index
            state.vault_scan_mode = cached_mode
            state.vault_scanned_at = cached_at
    _kick_vault_scan(state)


# ── Async update-availability check (Upd column, non-vault sub-tabs) ────────

# Types the background sweep covers — exactly the ones the `Upd` column can
# render. mcp (report-only pins) and claude-code (binary) are excluded.
_UPDATE_CHECK_TYPES = ["marketplace", "plugin", "skill", "command", "agent"]


def _update_status_fresh(iso: Optional[str]) -> bool:
    """True while the last completed check is younger than UPDATE_STATUS_TTL_S."""
    if not iso:
        return False
    try:
        when = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return (datetime.now(timezone.utc) - when).total_seconds() < UPDATE_STATUS_TTL_S


def _bind_update_statuses(state: TuiState, statuses: list, checked_at: Optional[str]) -> None:
    state.update_statuses = {(s.item_type, s.name): s for s in statuses}
    state.update_checked_at = checked_at


def _update_check_worker(state: TuiState) -> None:
    """Body of the background check (factored out so tests can run it
    synchronously). Never raises: a failed sweep binds an empty-but-stamped
    result so the render loop does not re-kick every frame."""
    try:
        statuses = check_all_updates(types=_UPDATE_CHECK_TYPES)
        checked_at = _iso_now()
        state.update_check_failed = ""
        _bind_update_statuses(state, statuses, checked_at)
        save_cached_update_statuses(statuses, checked_at)
    except Exception as exc:  # noqa: BLE001 — a broken sweep must not kill the thread loop
        if state.update_statuses is None:
            state.update_statuses = {}
        state.update_checked_at = _iso_now()
        state.update_check_failed = str(exc) or exc.__class__.__name__
    finally:
        state.update_check_loading = False


def _kick_update_check(state: TuiState, force: bool = False) -> None:
    """Async check_all_updates for the `Upd` column (mirrors _kick_vault_scan).

    Idempotent while a check is in flight. Without `force`, the disk cache is
    restored first and a fresh timestamp (< UPDATE_STATUS_TTL_S) short-circuits
    the network sweep entirely; stale cached markers stay visible until the
    daemon worker rebinds them.
    """
    if state.update_check_loading:
        return
    if not force and state.update_statuses is None:
        cached, checked_at = load_cached_update_statuses()
        if cached:
            _bind_update_statuses(state, cached, checked_at)
    if not force and state.update_statuses is not None and _update_status_fresh(state.update_checked_at):
        return
    state.update_check_loading = True
    t = threading.Thread(target=_update_check_worker, args=(state,),
                         name="axt-update-check", daemon=True)
    state.update_check_thread = t
    t.start()


def _fmt_scan_age(iso: Optional[str]) -> str:
    """Relative age of the last scan: 'just now' / 'Nm ago' / 'Nh ago' / 'Nd ago'.
    Returns '' when the timestamp is missing or unparseable."""
    if not iso:
        return ""
    try:
        when = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return ""
    secs = (datetime.now(timezone.utc) - when).total_seconds()
    if secs < 60:
        return "just now"
    mins = int(secs // 60)
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _usage_index_drop(index: dict[str, Any], type_: str, name: str, project_path: str) -> None:
    """Remove a single project from a type:name entry in the usage index.
    Mirror of core._add_to_index for the unlink direction. Drops the entry
    entirely once its last project is gone so the 'Used' cell reverts to '─'."""
    key = f"{type_}:{name}"
    entry = index.get(key)
    if entry is None:
        return
    entry.projects = [p for p in entry.projects if p.path != project_path]
    if not entry.projects:
        del index[key]


def _vault_apply_pending(state: TuiState) -> str:
    """Commit the toggle pending state to disk (project and global symlinks)."""
    items_by_name = {i.name: i for i in state.vault_items}
    applied = 0
    errors = 0
    # The cross-project scan counts the current project iff it links/profiles
    # the item, so keep the in-memory index in sync with each project toggle —
    # otherwise the "Used" column stays stale until a manual `f` re-scan.
    cwd = Path.cwd()
    cwd_ref = ProjectRef(path=str(cwd), name=_project_name_from_path(str(cwd)))
    for name in list(state.vault_pending_project):
        item = items_by_name.get(name)
        if not item:
            state.vault_pending_project.discard(name)
            continue
        try:
            if item.is_linked:
                unlink_from_project(cwd, item)
                _usage_index_drop(state.vault_usage_index, item.type, item.name, str(cwd))
            else:
                link_to_project(cwd, item)
                _add_to_index(state.vault_usage_index, item.type, item.name, cwd_ref)
            applied += 1
        except (OSError, ValueError, FileExistsError):
            errors += 1
        state.vault_pending_project.discard(name)
    for name in list(state.vault_pending_global):
        item = items_by_name.get(name)
        if not item:
            state.vault_pending_global.discard(name)
            continue
        try:
            if item.is_global_linked:
                unlink_from_global(PATHS.claude_dir, item)
            else:
                link_to_global(PATHS.claude_dir, item)
            applied += 1
        except (OSError, ValueError, FileExistsError):
            errors += 1
        state.vault_pending_global.discard(name)
    _vault_load(state)
    if applied:
        _invalidate_context(state)
    return f"Applied {applied}" + (f", {errors} errors" if errors else "")


def _vault_toggle_mirror_global(state: TuiState, item: VaultItem) -> str:
    """`G`: activate/deactivate a skill in BOTH ~/.claude/skills and
    ~/.agents/skills at once. Immediate (like `U`), with a confirm modal —
    it does not use the pending `g` set.

    Direction keys off the combined state: when the skill is linked in both,
    deactivate both; otherwise link wherever it is missing. The .agents mirror
    stays guarded — a .skill-lock.json tree is left untouched (force is
    CLI-only via `--force-agents`), and the skip is reported."""
    if item.type != "skill":
        return "Only skills mirror to .agents/skills"
    agents_dir = HOME / ".agents"
    both_linked = item.is_global_linked and item.is_agents_linked
    action = "Deactivate" if both_linked else "Activate"
    cb = state.stdscr_callbacks
    stdscr = cb.get("stdscr") if cb else None
    if stdscr is not None:
        msg = f"{action} {item.name} in BOTH ~/.claude/skills and ~/.agents/skills?"
        if not confirm_modal(stdscr, msg, title="Confirm global+agents"):
            return "Cancelled"
    notes: list[str] = []
    try:
        if both_linked:
            unlink_from_global(PATHS.claude_dir, item)
            unlink_from_agents(agents_dir, item)
        else:
            if not item.is_global_linked:
                link_to_global(PATHS.claude_dir, item)
            if not item.is_agents_linked:
                ok, m = link_to_agents(agents_dir, item)
                if not ok:
                    notes.append(m)
    except (OSError, ValueError, FileExistsError) as exc:
        _vault_load(state)
        return f"Error: {exc}"
    _vault_load(state)
    _invalidate_context(state)
    tail = f" ({'; '.join(notes)})" if notes else ""
    return f"{action}d {item.name} in .claude + .agents{tail}"


def _vault_unlink_from_all(state: TuiState, item: VaultItem) -> str:
    """Unlink `item` from EVERY project that references it in the scan index.

    The heavier sibling of the `p` toggle, which only touches the current
    project. Project list comes from `state.vault_usage_index` (populated by
    `f`). When a stdscr is available a confirm modal lists the affected
    projects; headless callers (tests) skip straight to applying. Each project
    has its symlink removed and its `.axt-profile.json` entry dropped, and the
    in-memory + on-disk scan index is kept in sync so the `Used` column reverts.
    """
    projects = get_projects(state.vault_usage_index, item.type, item.name)
    if not projects:
        return f"{item.name!r} not used by any project (press `f` to scan)"
    cb = state.stdscr_callbacks
    stdscr = cb.get("stdscr") if cb else None
    if stdscr is not None:
        shown = "\n".join(f"  - {p.name}" for p in projects[:12])
        more = f"\n  … and {len(projects) - 12} more" if len(projects) > 12 else ""
        msg = f"Unlink {item.type}:{item.name} from {len(projects)} project(s)?\n{shown}{more}"
        if not confirm_modal(stdscr, msg, title="Confirm unlink-all"):
            return "Cancelled"
    unlinked = 0
    errors = 0
    for p in projects:
        try:
            unlink_from_project(Path(p.path), item)
            _usage_index_drop(state.vault_usage_index, item.type, item.name, p.path)
            unlinked += 1
        except (OSError, ValueError):
            errors += 1
    if unlinked:
        _save_scan_cache(state.vault_usage_index, state.vault_scan_mode)
        _invalidate_context(state)
    _vault_load(state)
    return f"Unlinked {item.name!r} from {unlinked} project(s)" + (
        f", {errors} errors" if errors else ""
    )


def _vault_unlink_marked(state: TuiState) -> str:
    """Bulk sibling of `_vault_unlink_from_all`: unlink EVERY marked item from
    every project that references it in the scan index.

    Marks come from `state.vault_marked` (toggled with Space) and are resolved
    against the full `vault_items` list, so a mark survives filter/search
    changes. Never-used items contribute nothing. When a stdscr is available
    a confirm modal lists each item and its project count; headless callers
    (tests) apply directly. The scan cache and context estimate are
    re-persisted once for the whole batch, and marks are cleared on success.
    """
    items_by_name = {i.name: i for i in state.vault_items}
    targets: list[tuple[VaultItem, list[ProjectRef]]] = []
    for name in sorted(state.vault_marked):
        item = items_by_name.get(name)
        if not item:
            continue
        projects = get_projects(state.vault_usage_index, item.type, item.name)
        if projects:
            targets.append((item, projects))
    if not targets:
        return "No marked item is used by any project (press `f` to scan)"
    total_projects = sum(len(p) for _, p in targets)
    cb = state.stdscr_callbacks
    stdscr = cb.get("stdscr") if cb else None
    if stdscr is not None:
        shown = "\n".join(
            f"  - {it.type}:{it.name} ({len(ps)} project(s))" for it, ps in targets[:12]
        )
        more = f"\n  … and {len(targets) - 12} more" if len(targets) > 12 else ""
        msg = (
            f"Unlink {len(targets)} marked item(s) from {total_projects} "
            f"project link(s)?\n{shown}{more}"
        )
        if not confirm_modal(stdscr, msg, title="Confirm unlink-marked"):
            return "Cancelled"
    unlinked = 0
    errors = 0
    for item, projects in targets:
        for p in projects:
            try:
                unlink_from_project(Path(p.path), item)
                _usage_index_drop(state.vault_usage_index, item.type, item.name, p.path)
                unlinked += 1
            except (OSError, ValueError):
                errors += 1
    if unlinked:
        _save_scan_cache(state.vault_usage_index, state.vault_scan_mode)
        _invalidate_context(state)
    state.vault_marked.clear()
    _vault_load(state)
    return f"Unlinked {len(targets)} item(s) from {unlinked} project link(s)" + (
        f", {errors} errors" if errors else ""
    )


def _vault_filtered(state: TuiState) -> list[VaultItem]:
    items = state.vault_items
    if state.vault_filter != "all":
        items = [i for i in items if i.type == state.vault_filter]
    if state.vault_search:
        q = state.vault_search.lower()
        items = [i for i in items if q in i.name.lower()]
    return _apply_sort(state, "vault", items)


def _fmt_date(d: Optional[datetime]) -> str:
    if not d:
        return "─"
    return d.strftime("%y-%m-%d %H:%M")


def _vault_pending_indicator(state: TuiState, item: VaultItem) -> tuple[str, str]:
    """Return the (project, global) cell text reflecting pending toggles.
    ● / ○ = symlink present/absent; a trailing `*` marks an unapplied toggle."""
    proj_pending = item.name in state.vault_pending_project
    glob_pending = item.name in state.vault_pending_global
    project_now = (not item.is_linked) if proj_pending else item.is_linked
    global_now = (not item.is_global_linked) if glob_pending else item.is_global_linked
    proj_cell = ("●" if project_now else "○") + (" *" if proj_pending else "")
    glob_cell = ("●" if global_now else "○") + (" *" if glob_pending else "")
    return proj_cell, glob_cell


def _activation_term(item_type: str, on: bool) -> str:
    """Human-readable activation status, distinguishing symlink vs enabledPlugins."""
    if item_type == "plugin":
        return "enabled" if on else "off"
    return "linked" if on else "not linked"


def render_vault_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    """Render the Vault tab — selected row uses curses.A_REVERSE so the
    ▸/# region never disappears."""
    if state.vault_items == [] and state.refresh_token == 0:
        _vault_load(state)
        # Try to restore the previous scan from disk so the "Used in" column
        # is populated immediately on restart (no manual `f` needed).
        if not state.vault_usage_index:
            cached_index, cached_mode, cached_at = _load_scan_cache()
            if cached_index:
                state.vault_usage_index = cached_index
                state.vault_scan_mode = cached_mode
                state.vault_scanned_at = cached_at
        state.refresh_token = 1

    # Title row with all the live mode bits.
    pending = len(state.vault_pending_project) + len(state.vault_pending_global)
    # Freshness tag: "scanning…" while a background scan is in flight, else the
    # relative age of the last completed scan. Lets the user judge staleness at
    # a glance and decide whether to press `f`.
    if state.vault_scan_loading:
        freshness = ", scanning…"
    else:
        age = _fmt_scan_age(state.vault_scanned_at)
        freshness = f", {age}" if age else ""
    scan_label = (
        f"scan={state.vault_scan_mode}"
        f"({format_scan_summary(state.vault_usage_index, style='title')}{freshness})"
        if state.vault_usage_index
        else f"scan={state.vault_scan_mode}(empty{freshness})"
    )
    title_parts = [
        f" Vault  ({len(state.vault_items)} items)",
        f"filter={state.vault_filter}",
        f"sort={subtab_sort_label(state, 'vault')}",
        scan_label,
    ]
    if state.vault_search:
        title_parts.append(f"search={state.vault_search!r}")
    if pending:
        title_parts.append(f"pending={pending}")
    # `/search:` band in the uniform slot — directly under the sub-tab
    # divider, ABOVE the title row, exactly where the other sub-tabs /
    # Context / Usage draw theirs. The trailing cursor (`_`) shows only
    # while capturing input.
    if state.vault_searching or state.vault_search:
        cursor = "_" if state.vault_searching else ""
        safe_addnstr(stdscr, y0, 0,
                     fit_cells(f" /search: {state.vault_search}{cursor}", w - 1),
                     w - 1, CP_INFO() | curses.A_BOLD)
        y0 += 1
        h -= 1
    # Draw the full-width title/status row and take the body rect below it.
    # render_title_bar uses CP_TITLE (the accent tier), so no full-width rule
    # appears under the row on light.
    table_y_top, table_h_full = render_title_bar(
        stdscr, y0, h, w, "  ".join(title_parts))

    filtered = _vault_filtered(state)
    if not filtered:
        safe_addnstr(stdscr, y0 + 2, 2, "Vault is empty or no items match the current filter.", w - 4, CP_DIM())
        safe_addnstr(stdscr, y0 + 4, 2, "Press `m` to migrate global extensions, or `F` to change filter.", w - 4, CP_DIM())
        broken = find_broken_links(PATHS.claude_dir)
        if broken:
            warn = (f"Warning: {len(broken)} broken symlink(s) in ~/.claude "
                    f"point to a missing vault. Press `m` for details.")
            safe_addnstr(stdscr, y0 + 6, 2, fit_cells(warn, w - 4), w - 4, CP_ERR() | curses.A_BOLD)
        return

    state.vault_selected = max(0, min(state.vault_selected, len(filtered) - 1))

    # ── Layout: detail panel pinned to the bottom of the list, at every width.
    # Unified with the other Extensions sub-tabs (see _render_list_with_detail)
    # so every sub-tab reads the same way. Earlier builds switched to a
    # right-side panel on wide terminals (w >= 100); that split was dropped.
    # The split uses the body rect (table_y_top / table_h_full) returned by
    # render_title_bar above — no per-renderer reserved-row arithmetic, so the
    # region always fills down to the last body row.
    detail_h = max(12, min(24, int(h * 0.45)))
    # Never let the panel eat the entire list; reserve at least 3 list rows.
    detail_h = min(detail_h, max(1, table_h_full - 3))
    table_w = w
    table_h = max(0, table_h_full - detail_h)
    detail_x = 0
    detail_w = w
    detail_y = table_y_top + table_h

    # Columns: # / Name / Ver / Type / Project / Global / Used in.
    # Every row lives in ~/.axt/vault/ (this tab lists vault storage only —
    # import candidates live on the Skills/Commands/Agents sub-tabs), so
    # there is no Vault status column here.
    # "Project" / "Global" show the *intended* state after applying pending toggles.
    no_w = max(3, len(str(len(filtered))) + 1)
    used_w = 6  # "Used" header + " N proj" data ≤ 6
    proj_w = 5  # "Proj" header (4) + "● *" data (3) ≤ 5
    glob_w = 5  # "Glob"
    type_w = 6  # "Type"
    ver_w = 8   # "Ver" header + "1.2.3" data ≤ 8
    # _draw_cell renders each column at `col.width + 2` cells (per-column
    # gap). With 7 columns + 4-cell prefix the gap cost is 4 + 2*7 = 18. We
    # subtract a few more cells of safety so wrap can't eat the last column.
    cols_fixed = no_w + ver_w + type_w + proj_w + glob_w + used_w
    name_w = max(10, table_w - cols_fixed - (4 + 2 * 7) - 4)
    columns = [
        TableColumn("no", "#", no_w),
        TableColumn("name", "Name", name_w),
        TableColumn("ver", "Ver", ver_w),
        TableColumn("type", "Type", type_w),
        TableColumn("project", "Proj", proj_w),
        TableColumn("global", "Glob", glob_w),
        TableColumn("used", "Used", used_w),
    ]
    # Append a direction arrow to the header of the column the list is sorted by
    # (the width never changes, so the glyph never shifts the data below it).
    columns = _mark_sorted_column(state, "vault", columns)
    rows: list[dict[str, str]] = []
    # The leftmost ■/□ prefix = Space selection (bulk-unlink marks). Project
    # link state lives in the Proj column (●/○ + pending *), not here.
    checked: set[int] = set()
    for i, item in enumerate(filtered):
        if item.name in state.vault_marked:
            checked.add(i)
        proj_cell, glob_cell = _vault_pending_indicator(state, item)
        used_count = (
            len(state.vault_usage_index.get(f"{item.type}:{item.name}").projects)
            if state.vault_usage_index and f"{item.type}:{item.name}" in state.vault_usage_index
            else 0
        )
        rows.append({
            "no": str(i + 1),
            "name": item.name,
            "ver": item.version or "─",
            "type": item.type,
            "project": proj_cell,
            "global": glob_cell,
            "used": f"{used_count} proj" if used_count else "─",
        })

    render_table(
        stdscr,
        table_y_top, 0, table_h, table_w,
        columns, rows,
        selected=state.vault_selected,
        checked=checked,
        header_rule=False,  # header attaches directly to the list (no ──── rule)
    )

    # Detail panel. Every row is vault-stored and symlink-activated, so no
    # Vault/Activation rows — Project/Global carry the linked state directly.
    current = filtered[state.vault_selected]
    detail_fields: list[tuple[str, str]] = [
        ("Name", current.name),
        ("Type", current.type),
        ("Version", current.version or "—"),
        ("Path", current.path),
        ("Description", current.description or "—"),
        ("Added", _fmt_date(current.created_at)),
        ("Updated", _fmt_date(current.updated_at)),
        ("Project", _activation_term(current.type, current.is_linked)),
        ("Global", _activation_term(current.type, current.is_global_linked)),
    ]
    if current.type == "skill":
        detail_fields.append(
            ("Agents", "mirrored" if current.is_agents_linked else "not mirrored")
        )
    if state.vault_usage_index:
        usage = state.vault_usage_index.get(f"{current.type}:{current.name}")
        if usage and usage.projects:
            detail_fields.append(("Used in", ", ".join(p.name for p in usage.projects[:8])))
    # Write the clamped scroll back so a held `j`/PgDn can't run the offset
    # past the content into blank space (the input handler over-increments).
    state.vault_detail_scroll = render_detail_panel(
        stdscr,
        detail_y, detail_x, detail_h, detail_w,
        title=f"{current.name} ({current.type})",
        fields=detail_fields,
        scroll=state.vault_detail_scroll,
        focused=state.vault_detail_focused,
    )


def _handle_vault_detail_keys(state: TuiState, key: int) -> Optional[str]:
    """Detail-panel focus mode: j/k (±1) and PgDn/PgUp (±10) scroll; Esc blurs."""
    if key == KEY_ESC:
        state.vault_detail_focused = False
        state.vault_detail_scroll = 0
        return None
    if key in (ord("j"), curses.KEY_DOWN):
        state.vault_detail_scroll += 1
    elif key in (ord("k"), curses.KEY_UP):
        state.vault_detail_scroll = max(0, state.vault_detail_scroll - 1)
    elif key == curses.KEY_NPAGE:
        state.vault_detail_scroll += 10
    elif key == curses.KEY_PPAGE:
        state.vault_detail_scroll = max(0, state.vault_detail_scroll - 10)
    return None


def _handle_vault_search_keys(state: TuiState, key: int) -> Optional[str]:
    """Search-input mode: Esc clears, Enter applies, Bksp deletes, ASCII appends."""
    if key == KEY_ESC:
        state.vault_searching = False
        state.vault_search = ""
        state.vault_selected = 0
        return "Search cleared"
    if is_enter(key):
        state.vault_searching = False
        state.vault_selected = 0
        return f"Searching {state.vault_search!r}" if state.vault_search else None
    if key in (curses.KEY_BACKSPACE, KEY_BACKSPACE, 8):
        state.vault_search = state.vault_search[:-1]
        state.vault_selected = 0
        return None
    if 32 <= key < 127:  # printable ASCII
        state.vault_search += chr(key)
        state.vault_selected = 0
        return None
    return None


def _handle_ext_search_keys(state: TuiState, key: int) -> Optional[str]:
    """Non-vault `/`-search input mode (mirrors _handle_vault_search_keys):
    Esc clears, Enter applies, Bksp deletes, printable ASCII appends."""
    sub = state.ext_sub_tab
    if key == KEY_ESC:
        state.ext_searching = False
        state.ext_search.pop(sub, None)
        state.ext_selected[sub] = 0
        return "Search cleared"
    if is_enter(key):
        state.ext_searching = False
        state.ext_selected[sub] = 0
        q = state.ext_search.get(sub, "")
        return f"Searching {q!r}" if q else None
    if key in (curses.KEY_BACKSPACE, KEY_BACKSPACE, 8):
        state.ext_search[sub] = state.ext_search.get(sub, "")[:-1]
        state.ext_selected[sub] = 0
        return None
    if 32 <= key < 127:  # printable ASCII
        state.ext_search[sub] = state.ext_search.get(sub, "") + chr(key)
        state.ext_selected[sub] = 0
        return None
    return None


def _vault_update_item(state: TuiState, item: Any) -> Optional[str]:
    """u=update the focused row's stored content in place (check + apply).

    Rows git-pull their storage directory (symlinks resolved first), so the
    update works regardless of link state.
    """
    if not item.path:
        return f"{item.name}: no storage path"
    name = item.name
    flash_status(state, f"Checking {name}…")
    try:
        st = check_path_update(item.type, name, item.path)
    except Exception as exc:  # noqa: BLE001 — surface as status, never crash the TUI
        return f"Update check failed: {exc}"
    if not st.updatable:
        return f"{name}: {st.error or st.note or 'up to date'}"
    flash_status(state, f"Updating {name}…")
    res = apply_path_update(item.type, name, item.path)
    _vault_load(state)
    if res.error:
        return f"Update failed: {res.error}"
    return f"Updated {name}: {res.before} → {res.after}" if res.updated else f"{name} up to date"


def handle_vault_input(state: TuiState, key: int) -> Optional[str]:
    """Vault tab key handler. Returns a status message or None."""
    # ── Tab: list ↔ detail focus toggle. Skipped during `/`-search input so
    # the search field is not derailed by a stray Tab.
    if key == KEY_TAB and not state.vault_searching:
        if state.vault_detail_focused:
            state.vault_detail_focused = False
            state.vault_detail_scroll = 0
            return None
        filtered = _vault_filtered(state)
        if filtered and state.vault_selected < len(filtered):
            state.vault_detail_focused = True
            state.vault_detail_scroll = 0
            return "Detail focused — j/k to scroll, Esc/Tab to blur"
        return None

    # ── Detail-panel focus mode: j/k scroll the panel; Esc blurs back to list.
    if state.vault_detail_focused:
        return _handle_vault_detail_keys(state, key)

    # ── Search-input mode: capture characters, respond only to Enter/Esc/Bksp.
    if state.vault_searching:
        return _handle_vault_search_keys(state, key)

    filtered = _vault_filtered(state)
    n = len(filtered)
    current = filtered[state.vault_selected] if (n and state.vault_selected < n) else None

    if key in (ord("j"), curses.KEY_DOWN):
        state.vault_selected = min(n - 1, state.vault_selected + 1) if n else 0
    elif key in (ord("k"), curses.KEY_UP):
        state.vault_selected = max(0, state.vault_selected - 1)
    elif key == curses.KEY_NPAGE:
        state.vault_selected = min(n - 1, state.vault_selected + 10) if n else 0
    elif key == curses.KEY_PPAGE:
        state.vault_selected = max(0, state.vault_selected - 10)
    elif key == ord("c"):
        # c=cycle type filter (all/skill/command/agent)
        i = _VAULT_FILTERS.index(state.vault_filter)
        state.vault_filter = _VAULT_FILTERS[(i + 1) % len(_VAULT_FILTERS)]
        state.vault_selected = 0
    elif key == ord("s"):
        # Next sort column, in table order plus the column-less Added/Updated.
        _cycle_sort_column(state, "vault")
        return f"Sort: {subtab_sort_label(state, 'vault')}"
    elif key == ord("S"):
        # Flip the active column ▲ ↔ ▼.
        _toggle_sort_direction(state, "vault")
        return f"Sort: {subtab_sort_label(state, 'vault')}"
    elif key == ord("/"):
        # Enter search-input mode.
        state.vault_searching = True
        state.vault_search = ""
        return "/: type to filter, Enter to apply, Esc to cancel"
    elif key == ord("o") and current:
        # Open a new terminal at the item's storage path (file → parent dir).
        p = Path(current.path)
        return _open_terminal_for_dir(state, str(p if p.is_dir() else p.parent))
    elif key in (ord("p"), ord("g")) and state.vault_marked:
        # Marks present → bulk: flip the pending scope toggle for every
        # marked item at once (Space multi-select + p/g; Enter applies).
        pending = (state.vault_pending_project if key == ord("p")
                   else state.vault_pending_global)
        pending ^= state.vault_marked
        scope = "project" if key == ord("p") else "global"
        return (f"Toggled {scope} pending for {len(state.vault_marked)} marked "
                f"— Enter to apply")
    elif key == ord("p") and current:
        # Toggle pending project link for the selected item.
        if current.name in state.vault_pending_project:
            state.vault_pending_project.discard(current.name)
        else:
            state.vault_pending_project.add(current.name)
        return None
    elif key == ord("g") and current:
        if current.name in state.vault_pending_global:
            state.vault_pending_global.discard(current.name)
        else:
            state.vault_pending_global.add(current.name)
        return None
    elif key == ord("G") and current:
        # G = immediate global + .agents mirror toggle for the selected skill.
        return _vault_toggle_mirror_global(state, current)
    elif key == ord(" ") and current:
        # Space = select: toggle the focused item's bulk-unlink mark, then
        # advance focus one row (clamped) so repeated Space marks consecutive
        # items instead of re-toggling the same one. Marks accumulate across
        # filter/search changes and are consumed by `U`.
        if current.name in state.vault_marked:
            state.vault_marked.discard(current.name)
            msg = f"Unmarked {current.name!r} ({len(state.vault_marked)} marked)"
        else:
            state.vault_marked.add(current.name)
            msg = f"Marked {current.name!r} for unlink ({len(state.vault_marked)} marked)"
        state.vault_selected = min(n - 1, state.vault_selected + 1)
        return msg
    elif key == ord("U") and state.vault_marked:
        # Marks present → bulk unlink every marked item from all its projects.
        # Mirrors Enter's apply-pending-else-focus split: `U` prefers the batch.
        return _vault_unlink_marked(state)
    elif key == ord("U") and current:
        # No marks → unlink the selected item from every project that uses it
        # (per the last scan). Confirms via modal; updates symlinks, profiles, index.
        return _vault_unlink_from_all(state, current)
    elif key == ord("u") and current:
        # u = update the focused row's stored content (check + apply).
        return _vault_update_item(state, current)
    elif is_enter(key) and (state.vault_pending_project or state.vault_pending_global):
        # Ask before committing pending toggles to disk. When no stdscr is
        # available (tests, headless) fall back to direct apply.
        cb = state.stdscr_callbacks
        stdscr = cb.get("stdscr") if cb else None
        if stdscr is None:
            return _vault_apply_pending(state)
        items_by_name = {i.name: i for i in state.vault_items}

        def _lines(names: set[str], linked_attr: str) -> list[str]:
            out = []
            for name in sorted(names):
                item = items_by_name.get(name)
                if not item:
                    continue
                arrow = "unlink" if getattr(item, linked_attr, False) else "link"
                out.append(f"  - {arrow} {item.type}:{name}")
            return out

        msg_lines = ["Apply pending changes?"]
        if state.vault_pending_project:
            msg_lines.append(f"Project ({len(state.vault_pending_project)}):")
            msg_lines.extend(_lines(state.vault_pending_project, "is_linked"))
        if state.vault_pending_global:
            msg_lines.append(f"Global ({len(state.vault_pending_global)}):")
            msg_lines.extend(_lines(state.vault_pending_global, "is_global_linked"))
        if confirm_modal(stdscr, "\n".join(msg_lines), title="Confirm apply"):
            return _vault_apply_pending(state)
        return "Cancelled"
    elif is_enter(key) and current:
        # No pending changes → drop focus into the detail panel for scrolling.
        state.vault_detail_focused = True
        state.vault_detail_scroll = 0
        return "Detail focused — j/k to scroll, Esc to blur"
    elif key == KEY_ESC and (
        state.vault_pending_project or state.vault_pending_global or state.vault_marked
    ):
        state.vault_pending_project.clear()
        state.vault_pending_global.clear()
        had_marks = bool(state.vault_marked)
        state.vault_marked.clear()
        return "Cleared marks" if had_marks else "Discarded pending changes"
    elif key == KEY_ESC and state.vault_search:
        # First Esc on the filtered list clears the search filter. A second
        # Esc (with no filter left) climbs up to the sub-tab — handled by
        # the layer dispatcher in axt/tui/loop.py.
        state.vault_search = ""
        state.vault_selected = 0
        return "Search cleared"
    elif key == ord("f"):
        # Re-scan in the current mode and persist to disk. Does NOT toggle
        # mode: a previous bug had `f` flip default↔full, which silently
        # shrank the index (e.g. lost plugin enabledPlugins entries) and
        # made it look like the cache was missing on the next axt run.
        try:
            _vault_scan(state)
            return (
                f"Scan ({state.vault_scan_mode}): "
                f"{format_scan_summary(state.vault_usage_index, style='toast')}  "
                f"(total {len(state.vault_usage_index)})"
            )
        except OSError as e:
            return f"Scan failed: {e}"
    elif key == ord("F"):
        # F = f's extension: toggle mode (default↔full) + re-scan + persist.
        state.vault_scan_mode = "full" if state.vault_scan_mode == "default" else "default"
        try:
            _vault_scan(state)
            return (
                f"Mode → {state.vault_scan_mode}: "
                f"{format_scan_summary(state.vault_usage_index, style='toast')}  "
                f"(total {len(state.vault_usage_index)})"
            )
        except OSError as e:
            return f"Scan failed: {e}"
    elif key == ord("m"):
        try:
            result = migrate_to_vault(PATHS.claude_dir, PATHS.vault)
            _vault_load(state)
            if result.moved:
                _invalidate_context(state)
            n_broken = len(result.broken)
            counts = (f"+{len(result.moved)} skipped {len(result.skipped)} "
                      f"broken {n_broken} err {len(result.errors)}")
            if n_broken:
                # "Warning:" prefix keeps classify_status at "info" (not a
                # green "Migrated" success) so broken links read as a problem.
                return (f"Warning: {n_broken} broken symlink(s) not migrated — "
                        f"{counts}")
            return f"Migrated: {counts}"
        except OSError as e:
            return f"Migrate failed: {e}"
    elif key == ord("y"):
        try:
            result = sync_project(Path.cwd(), PATHS.vault)
            _vault_load(state)
            if result.linked or result.unlinked:
                _invalidate_context(state)
            return f"Sync: +{len(result.linked)} -{len(result.unlinked)} err {len(result.errors)}"
        except OSError as e:
            return f"Sync failed: {e}"
    elif key == ord("r"):
        _vault_load(state)
        return "Refreshed"
    return None


def render_stub_tab(stdscr, state: TuiState, y0: int, h: int, w: int, name: str, hint: str) -> None:
    title = f" {name}"
    safe_addnstr(stdscr, y0, 0, fit_cells(title, w - 1), w - 1, CP_TITLE())
    safe_addnstr(stdscr, y0 + 2, 2, f"{name} tab — not yet implemented in the curses TUI.", w - 4, 0)
    safe_addnstr(stdscr, y0 + 3, 2, hint, w - 4, CP_DIM())
    safe_addnstr(stdscr, y0 + 5, 2, "Use the CLI for now:", w - 4, CP_INFO())
    safe_addnstr(stdscr, y0 + 6, 4, f"$ axt {name.lower()} --help", w - 6, CP_DIM())


def handle_stub_input(state: TuiState, key: int) -> Optional[str]:
    return None


# ─── BarChart widget ─────────────────────────────────────────────────────────


def render_bar_chart(
    stdscr,
    y: int,
    x: int,
    w: int,
    data: list[tuple[str, float]],
    *,
    label_w: int = 10,
    value_fmt=lambda v: f"${v:.2f}",
) -> int:
    """Render a horizontal ASCII bar chart. Returns rows used.

    `data` is a list of (label, value). Bars are scaled to the max value.
    """
    if not data:
        return 0
    max_value = max((v for _, v in data), default=1.0) or 1.0
    value_w = max(len(value_fmt(v)) for _, v in data)
    bar_w = max(4, w - label_w - value_w - 4)
    for i, (label, value) in enumerate(data):
        filled = round((value / max_value) * bar_w) if max_value > 0 else 0
        bar = render_bar(filled, bar_w)
        line = f"{fit_cells(label, label_w)} {bar} {value_fmt(value)}"
        safe_addnstr(stdscr, y + i, x, fit_cells(line, w), w, CP_INFO())
    return len(data)


def _bar_chart_lines(
    data: list[tuple[str, float]],
    w: int,
    *,
    label_w: int = 10,
    value_fmt=lambda v: f"${v:.2f}",
) -> list[tuple[int, str, int, int]]:
    """Same horizontal bar chart as `render_bar_chart` but returns line
    tuples (x=0 here; caller can nudge by setting its own x when
    extending the parent list)."""
    if not data:
        return []
    max_value = max((v for _, v in data), default=1.0) or 1.0
    value_w = max(len(value_fmt(v)) for _, v in data)
    bar_w = max(4, w - label_w - value_w - 4)
    out: list[tuple[int, str, int, int]] = []
    for label, value in data:
        filled = round((value / max_value) * bar_w) if max_value > 0 else 0
        bar = render_bar(filled, bar_w)
        line = f"{fit_cells(label, label_w)} {bar} {value_fmt(value)}"
        out.append((0, fit_cells(line, w), w, CP_INFO()))
    return out


def _date_iter(now: datetime, days: int) -> list[datetime]:
    """Last `days` days, oldest first, including today."""
    out = []
    for i in range(days - 1, -1, -1):
        out.append(now - timedelta(days=i))
    return out


# ─── Cost helpers ────────────────────────────────────────────────────────────


def _entry_cost(e: UnifiedUsageEntry) -> float:
    return calculate_cost(
        TokenUsage(
            input_tokens=e.input_tokens,
            output_tokens=e.output_tokens,
            cache_creation_tokens=e.cache_write_tokens,
            cache_read_tokens=e.cache_read_tokens,
        ),
        e.model,
    )


def _entry_cache_savings(e: UnifiedUsageEntry) -> float:
    return calculate_cache_savings(
        TokenUsage(
            input_tokens=e.input_tokens,
            output_tokens=e.output_tokens,
            cache_creation_tokens=e.cache_write_tokens,
            cache_read_tokens=e.cache_read_tokens,
        ),
        e.model,
    )


def _daily_costs(entries: list[UnifiedUsageEntry], days: int, tz: str) -> list[tuple[str, float]]:
    """Per-day cost for the last `days` days. Ordered oldest → newest."""
    today = datetime.now(timezone.utc)
    dates: list[tuple[str, float]] = []
    by_day: dict[str, float] = {}
    for e in entries:
        d = _date_in_tz(e.timestamp, tz)
        by_day[d] = by_day.get(d, 0.0) + _entry_cost(e)
    for dt in _date_iter(today, days):
        key = dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
        try:
            from zoneinfo import ZoneInfo
            key = dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")
        except Exception:
            pass
        label = key[5:]  # MM-DD
        dates.append((label, by_day.get(key, 0.0)))
    return dates


# ─── Usage tab (Claude-only) ─────────────────────────────────────────────────


def _kick_usage_reload(state: TuiState) -> None:
    """Start a background reload of Claude usage data.

    Idempotent: if a load is already in flight, this is a no-op. The
    worker thread is a daemon so it dies with the process. Previously
    loaded data in ``state.usage_entries`` stays visible while the
    refresh runs.
    """
    if state.usage_loading:
        return
    state.usage_load_failed = ""   # an explicit reload is a retry
    state.usage_loading = True
    set_status(state, "Loading Claude usage…")

    def _worker() -> None:
        try:
            config = load_config(AXT_CONFIG_PATH)
            # "This month" in the user's configured timezone, not UTC — keeps
            # the load window aligned with the tz used by the period cards.
            month_start = _today_in_tz(config.timezone)[:8] + "01"
            entries = load_unified_usage(
                claude_projects_dir=PATHS.projects,
                since=month_start,
            )
            # Prime the context cache too — `_usage_gauge_lines` reads
            # `state.context_analysis` and we don't want a synchronous
            # filesystem scan blocking the first paint. Once `entries` are
            # loaded we know the live model, so also refresh a cache that was
            # primed with a stale fallback before usage arrived. With no
            # entries there's nothing new to learn — leave a loaded cache be.
            model = detect_current_model(entries, project_dir=Path.cwd())
            cached = state.context_analysis
            if cached is None or (entries and cached.model != model):
                state.context_analysis = analyze_context(
                    home_dir=HOME,
                    project_dir=Path.cwd(),
                    installed_plugins_path=PATHS.installed_plugins,
                    model=model,
                )
            state.usage_config = config
            state.usage_entries = entries
            state.usage_load_failed = ""
            if state.status == "Loading Claude usage…":
                set_status(state, "")
        except Exception as exc:  # noqa: BLE001 — same reason as the vault scan
            # Deliberately does NOT bind an empty list: "load failed" and
            # "loaded, zero entries" must stay distinguishable, which is the
            # whole point of surfacing this.
            state.usage_load_failed = str(exc) or exc.__class__.__name__
        finally:
            state.usage_loading = False

    t = threading.Thread(target=_worker, name="axt-usage-load", daemon=True)
    state.usage_load_thread = t
    t.start()



def _fmt_quota_eta(reset_at: Optional[datetime]) -> str:
    if not reset_at:
        return "—"
    secs = int((reset_at - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "now"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h {(secs % 3600) // 60}m"
    return f"{secs // 86400}d {(secs % 86400) // 3600}h"


def _gauge_attr(pct: float) -> int:
    if pct >= 90:
        return CP_ERR()
    if pct >= 60:
        return CP_INFO()
    return CP_OK()


def _usage_gauge_lines(state: TuiState, w: int) -> list[tuple[int, str, int, int]]:
    """Build the gauge rows (Context window, 5h, 7d) as line tuples
    without drawing.

    Returns ``[(x, text, max_w, attr), ...]``. Empty list if there's
    nothing to show. Reads ``state.context_analysis`` as-is — the usage
    loader primes it in the background so the first paint never blocks
    on a synchronous filesystem scan.
    """
    analysis = state.context_analysis
    rl = read_rate_limits(PATHS.usage_snapshot)
    bar_w = min(30, max(10, w - 40))
    label_w = 10
    out: list[tuple[int, str, int, int]] = []

    if analysis is not None and analysis.context_window_size > 0:
        pct = analysis.used_percent
        filled = round(min(pct, 100) / 100 * bar_w)
        bar = render_bar(filled, bar_w)
        used_tok = format_tokens(analysis.total_tokens)
        win_tok = format_tokens(analysis.context_window_size)
        out.append((2, fit_cells(
            f"{'Context:':<{label_w}}{bar} {pct:5.1f}%  {used_tok}/{win_tok} tokens",
            w - 4), w - 4, _gauge_attr(pct)))

    if rl is None:
        out.append((2, "Rate limits: snapshot missing or stale", w - 4, CP_DIM()))
        return out

    if rl.five_hour is not None:
        pct = float(rl.five_hour)
        filled = round(pct / 100 * bar_w)
        bar = render_bar(filled, bar_w)
        out.append((2, fit_cells(
            f"{'5h:':<{label_w}}{bar} {rl.five_hour:3d}%    reset in {_fmt_quota_eta(rl.five_hour_reset_at)}",
            w - 4), w - 4, _gauge_attr(pct)))
    if rl.seven_day is not None:
        pct = float(rl.seven_day)
        filled = round(pct / 100 * bar_w)
        bar = render_bar(filled, bar_w)
        out.append((2, fit_cells(
            f"{'7d:':<{label_w}}{bar} {rl.seven_day:3d}%    reset in {_fmt_quota_eta(rl.seven_day_reset_at)}",
            w - 4), w - 4, _gauge_attr(pct)))
    return out


def _usage_period_card(entries: list[UnifiedUsageEntry], label: str) -> list[str]:
    """3-line summary card for a period (Today/Week/Month)."""
    sessions = {e.session_id for e in entries}
    cost = sum(_entry_cost(e) for e in entries)
    savings = sum(_entry_cache_savings(e) for e in entries)
    in_t = sum(e.input_tokens for e in entries)
    out_t = sum(e.output_tokens for e in entries)
    cw_t = sum(e.cache_write_tokens for e in entries)
    cr_t = sum(e.cache_read_tokens for e in entries)
    return [
        f"  {label:7s}  sessions={len(sessions):>3d}  msgs={len(entries):>4d}",
        f"           in={format_tokens(in_t):>7s}  out={format_tokens(out_t):>7s}  "
        f"cw={format_tokens(cw_t):>7s}  cr={format_tokens(cr_t):>7s}",
        f"           cost=${cost:.2f}  saved=${savings:.2f}",
    ]


def _usage_summary_lines(
    state: TuiState,
    config: Any,
    entries: list,
    w: int,
) -> list[tuple[int, str, int, int]]:
    """Build the full loaded-state line buffer for the Usage tab body
    (plan, budget bar, gauges, period cards, chart, active block,
    insights). The header is added by the caller, not here.
    """
    lines: list[tuple[int, str, int, int]] = []

    total_cost = sum(_entry_cost(e) for e in entries)
    plan = resolve_claude_plan(config)
    auto = config.auto_detect_plan and detect_claude_plan() is not None
    plan_label = (
        f"{plan.plan} (${plan.monthly_cost}/mo{' · auto' if auto else ''})"
        if plan
        else "—"
    )
    lines.append((2, fit_cells(f"Plan: {plan_label}", w - 4), w - 4, CP_TITLE()))
    lines.append((2, fit_cells(
        "Costs are API-rate estimates, not your subscription bill.",
        w - 4), w - 4, CP_DIM()))
    unpriced = find_unpriced_models(entries)
    if unpriced:
        n = sum(unpriced.values())
        names = ", ".join(sorted(unpriced))
        lines.append((2, fit_cells(
            f"⚠ {n} entries from unpriced models ({names}) — cost shown excludes them.",
            w - 4), w - 4, CP_ERR()))

    if config.monthly_budget > 0:
        bar_w = min(40, max(10, w - 30))
        pct = min(total_cost / config.monthly_budget, 1.5)
        filled = round(min(pct, 1) * bar_w)
        bar = render_bar(filled, bar_w)
        label = f"${total_cost:.2f}/${config.monthly_budget} ({pct * 100:.0f}%)"
        if pct >= 1:
            text, attr = f"{bar} {label} ⛔", CP_ERR()
        elif pct >= 0.8:
            text, attr = f"{bar} {label} ⚠", CP_TITLE()
        else:
            text, attr = f"{bar} {label}", CP_OK()
        lines.append((2, fit_cells(text, w - 4), w - 4, attr))
    lines.append((0, "", w, 0))  # gap before gauges

    lines.extend(_usage_gauge_lines(state, w))
    lines.append((0, "", w, 0))  # gap after gauges

    if not entries:
        lines.append((2, "No Claude usage data this month yet.", w - 4, CP_DIM()))
        return lines

    tz = config.timezone
    today = _today_in_tz(tz)
    # Same timezone as the per-entry dates below — a UTC cutoff here shifts
    # the week boundary by a day for tz-ahead users (e.g. KST).
    week_ago = _days_ago_in_tz(7, tz)
    today_entries = [e for e in entries if _date_in_tz(e.timestamp, tz) == today]
    week_entries = [e for e in entries if _date_in_tz(e.timestamp, tz) >= week_ago]
    month_entries = entries

    for label, eps in (("Today", today_entries), ("Week", week_entries), ("Month", month_entries)):
        for line in _usage_period_card(eps, label):
            lines.append((2, fit_cells(line, w - 4), w - 4, 0))
        lines.append((0, "", w, 0))  # gap between cards

    lines.append((2, "Last 14 days (daily cost):", w - 4, CP_TITLE()))
    chart_data = _daily_costs(entries, 14, tz)
    # Bar-chart helper returns x=0 lines; nudge them to x=4 so they
    # align with the original `render_bar_chart(... x=4, w=w-8)` layout.
    for (_x, text, _max_w, attr) in _bar_chart_lines(chart_data, w - 8):
        lines.append((4, text, w - 8, attr))
    lines.append((0, "", w, 0))

    claude_entries = [_unified_to_claude(e) for e in entries]
    blocks = compute_blocks(claude_entries, tz)
    active = next((b for b in blocks if b.is_active), None)
    if active:
        burn = format_tokens(active.burn_rate_per_min) if active.burn_rate_per_min else "—"
        lines.append((2, fit_cells(
            f"Active block: {active.start_time[11:16]}–{active.end_time[11:16]}  "
            f"tokens={format_tokens(active.total_tokens)}  burn={burn}/min",
            w - 4), w - 4, CP_OK()))
        lines.append((0, "", w, 0))

    insights = _compute_simple_insights(claude_entries)
    lines.append((2, "Insights (this month):", w - 4, CP_TITLE()))
    lines.append((2, fit_cells(
        f"  large-context sessions (>150k input tokens):  {insights['large_pct']:.1f}%",
        w - 4), w - 4, 0))
    lines.append((2, fit_cells(
        f"  parallel sessions (3+ overlapping at once):   {insights['parallel_pct']:.1f}%",
        w - 4), w - 4, 0))
    lines.append((2, fit_cells(
        f"  top model by tokens:                          "
        f"{insights['top_model'] or '—'}",
        w - 4), w - 4, 0))
    return lines


def render_usage_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    # Snapshot before kick — keeps the three render branches consistent.
    entries = state.usage_entries
    # A failed load leaves `entries` None on purpose (so it stays distinct from
    # an empty result), so the failure flag is what stops this re-kicking every
    # frame. `r` clears it to retry.
    if entries is None and not state.usage_loading and not state.usage_load_failed:
        _kick_usage_reload(state)
    config = state.usage_config or load_config(AXT_CONFIG_PATH)

    # Build (or reuse) the line buffer. Scroll keys hit this path every
    # tick, so skipping the rebuild is what keeps scrolling responsive
    # on large transcripts.
    # The tab title is a FIXED filter-bar row (vault convention) drawn below
    # the `/search:` band — NOT part of the scrollable buffer.
    sig = (id(entries), id(config), w)
    if state.usage_lines is None or state.usage_lines_sig != sig:
        lines: list[tuple[int, str, int, int]] = []
        if entries is None:
            # Show gauges even while the first load is in flight so the
            # context / rate-limit meters appear immediately.
            lines.extend(_usage_gauge_lines(state, w))
            lines.append((0, "", w, 0))
            lines.append((2, "Loading Claude usage…", w - 4, CP_DIM()))
        else:
            lines.extend(_usage_summary_lines(state, config, entries, w))
        state.usage_lines = lines
        state.usage_lines_sig = sig
    else:
        lines = state.usage_lines

    # `/search:` band (uniform slot, mirrors Vault): live `_` cursor while
    # typing, cursor-less once applied. Reserves the top row of the viewport.
    band_h = 0
    if state.usage_searching or state.usage_search:
        cursor = "_" if state.usage_searching else ""
        safe_addnstr(stdscr, y0, 0,
                     fit_cells(f" /search: {state.usage_search}{cursor}", w - 1),
                     w - 1, CP_INFO() | curses.A_BOLD)
        band_h = 1

    # Fixed title / filter-bar row (vault convention): stays visible at any
    # scroll offset; carries the search + match chips when a query is applied.
    title = " Claude usage — this month"
    if state.usage_search:
        title += f"  search={state.usage_search!r}"
        t_matches = _usage_matches(state)
        if t_matches and state.usage_match_idx >= 0:
            title += f"  match {state.usage_match_idx % len(t_matches) + 1}/{len(t_matches)}"
    safe_addnstr(stdscr, y0 + band_h, 0, fit_cells(title, w - 1), w - 1, CP_TITLE())

    body_h = h - band_h - 1
    max_scroll = max(0, len(lines) - body_h)
    if state.usage_scroll > max_scroll:
        state.usage_scroll = max_scroll
    if state.usage_scroll < 0:
        state.usage_scroll = 0

    # Highlight applied-search matches (current match reversed, others marked —
    # same palette as preview_modal's `/` search).
    q = state.usage_search.lower()
    matches = _usage_matches(state) if q else []
    cur_line = (matches[state.usage_match_idx % len(matches)]
                if matches and state.usage_match_idx >= 0 else -1)
    body_y = y0 + band_h + 1  # below the band and the fixed title row
    visible = lines[state.usage_scroll : state.usage_scroll + body_h]
    for i, (x, text, max_w, attr) in enumerate(visible):
        if not text:
            continue
        if q and q in text.lower():
            _addstr_search_hl(stdscr, body_y + i, x, text, max_w, q,
                              current=(state.usage_scroll + i == cur_line), base=attr)
        else:
            safe_addnstr(stdscr, body_y + i, x, text, max_w, attr)


def _compute_simple_insights(entries: list[ClaudeUsageEntry]) -> dict[str, Any]:
    """Lightweight stand-in for usage-insights.ts.

    Produces three signals the original Ink Insights view shows:
      • large_pct      — % of SESSIONS with >150k input tokens
      • parallel_pct   — % of MESSAGES whose timestamp falls inside a window
                         where 3+ sessions were active simultaneously
      • top_model      — model with the highest token count
    Heavy aggregates (skill/agent/plugin token-share breakdowns) require
    re-reading transcript bodies — deferred to a follow-up.
    """
    if not entries:
        return {"large_pct": 0.0, "parallel_pct": 0.0, "top_model": None}

    # large-context sessions.
    by_session: dict[str, int] = {}
    for e in entries:
        by_session[e.session_id] = by_session.get(e.session_id, 0) + e.input_tokens
    large_sessions = sum(1 for v in by_session.values() if v > 150_000)
    large_pct = (large_sessions / len(by_session)) * 100 if by_session else 0.0

    # parallel sessions: bucket entries into 5-minute windows; flag windows
    # that contain 3+ distinct session_ids.
    bucket: dict[int, set[str]] = {}
    for e in entries:
        ts = _ts_ms(e.timestamp)
        if ts is None:
            continue
        slot = ts // (5 * 60_000)
        bucket.setdefault(slot, set()).add(e.session_id)
    parallel_msgs = 0
    total_msgs = 0
    for e in entries:
        ts = _ts_ms(e.timestamp)
        if ts is None:
            continue
        total_msgs += 1
        slot = ts // (5 * 60_000)
        if len(bucket.get(slot, set())) >= 3:
            parallel_msgs += 1
    parallel_pct = (parallel_msgs / total_msgs) * 100 if total_msgs else 0.0

    # top model by token count.
    by_model: dict[str, int] = {}
    for e in entries:
        by_model[e.model] = by_model.get(e.model, 0) + e.input_tokens + e.output_tokens
    top_model = max(by_model.items(), key=lambda kv: kv[1])[0] if by_model else None

    return {"large_pct": large_pct, "parallel_pct": parallel_pct, "top_model": top_model}


def _usage_matches(state: TuiState) -> list[int]:
    """Indices into state.usage_lines whose text contains the applied query.
    Recomputed on demand — the line buffer rebuilds on resize/reload, so
    cached indices would go stale."""
    q = state.usage_search.lower()
    if not q or not state.usage_lines:
        return []
    return [i for i, (_, text, _, _) in enumerate(state.usage_lines)
            if text and q in text.lower()]


def _usage_jump_to_match(state: TuiState, matches: list[int]) -> str:
    state.usage_scroll = matches[state.usage_match_idx]
    return f"match {state.usage_match_idx + 1}/{len(matches)}"


def _usage_live_jump(state: TuiState) -> None:
    """Follow the query while typing (Vault filters live; Usage jumps live):
    viewport moves to the first match at/after the anchor, and falls back to
    the anchor when the query stops matching."""
    matches = _usage_matches(state)
    if matches:
        state.usage_match_idx = next(
            (j for j, i in enumerate(matches) if i >= state.usage_search_anchor), 0)
        state.usage_scroll = matches[state.usage_match_idx]
    else:
        state.usage_match_idx = -1
        state.usage_scroll = state.usage_search_anchor


def _handle_usage_search_keys(state: TuiState, key: int) -> Optional[str]:
    """Usage `/`-search input mode: Esc cancels (viewport back to the anchor),
    Enter applies; the viewport already followed the query live."""
    if key == KEY_ESC:
        state.usage_searching = False
        state.usage_search = ""
        state.usage_match_idx = -1
        state.usage_scroll = state.usage_search_anchor
        return "Search cleared"
    if is_enter(key):
        state.usage_searching = False
        if not state.usage_search:
            return None
        matches = _usage_matches(state)
        if not matches:
            state.usage_match_idx = -1
            return f"No match for {state.usage_search!r}"
        if state.usage_match_idx < 0:  # lines rebuilt since the last keystroke
            state.usage_match_idx = next(
                (j for j, i in enumerate(matches) if i >= state.usage_search_anchor), 0)
        return _usage_jump_to_match(state, matches)
    if key in (curses.KEY_BACKSPACE, KEY_BACKSPACE, 8):
        state.usage_search = state.usage_search[:-1]
        _usage_live_jump(state)
        return None
    if 32 <= key < 127:  # printable ASCII
        state.usage_search += chr(key)
        _usage_live_jump(state)
        return None
    return None


def handle_usage_input(state: TuiState, key: int) -> Optional[str]:
    # ── `/`-search input mode: capture characters, respond only to
    # Enter/Esc/Bksp (mirrors the list tabs' search prompts).
    if state.usage_searching:
        return _handle_usage_search_keys(state, key)
    if key == ord("/"):
        state.usage_searching = True
        state.usage_search = ""
        state.usage_match_idx = -1
        state.usage_search_anchor = state.usage_scroll
        return "/: type to search, Enter to jump, Esc to cancel"
    if key in (ord("n"), ord("N")) and state.usage_search:
        matches = _usage_matches(state)
        if not matches:
            return f"No match for {state.usage_search!r}"
        step = 1 if key == ord("n") else -1
        state.usage_match_idx = (state.usage_match_idx + step) % len(matches)
        return _usage_jump_to_match(state, matches)
    if key == KEY_ESC and state.usage_search:
        # First Esc clears the applied search; the next one climbs the focus
        # layer as usual (the loop defers to this handler — see
        # _handle_content_layer_key).
        state.usage_search = ""
        state.usage_match_idx = -1
        return "Search cleared"
    if key == ord("r"):
        _kick_usage_reload(state)
        # _kick_usage_reload already set state.status to the loading
        # message; returning None keeps that message in place (the main
        # loop only overwrites state.status when the handler returns a
        # non-None string).
        return None
    if key in (curses.KEY_DOWN, ord("j")):
        state.usage_scroll += 1
        return None
    if key in (curses.KEY_UP, ord("k")):
        state.usage_scroll = max(0, state.usage_scroll - 1)
        return None
    if key == curses.KEY_NPAGE:
        state.usage_scroll += 10
        return None
    if key == curses.KEY_PPAGE:
        state.usage_scroll = max(0, state.usage_scroll - 10)
        return None
    return None


# ─── Context tab ─────────────────────────────────────────────────────────────


def _ensure_context_loaded(state: TuiState) -> None:
    if state.context_analysis is not None:
        return
    state.context_analysis = analyze_context(
        home_dir=HOME,
        project_dir=Path.cwd(),
        installed_plugins_path=PATHS.installed_plugins,
        model=detect_current_model(state.usage_entries, project_dir=Path.cwd()),
    )


@dataclass
class _ContextCategoryRow:
    category: str
    scope: str
    label: str
    items: int
    tokens: int
    pct: float


def _context_rows(analysis: ContextAnalysis) -> list[_ContextCategoryRow]:
    """Roll context sources up per (category, scope) so the Sources table can
    show the current project's own context separately from the global baseline.
    Rows sort project-first, then by tokens desc within each scope group."""
    by_key: dict[tuple[str, str], list[ContextSource]] = {}
    for s in analysis.sources:
        by_key.setdefault((s.category, getattr(s, "scope", "global")), []).append(s)
    rows = []
    for (cat, scope), src_list in by_key.items():
        tokens = sum(s.estimated_tokens for s in src_list)
        pct = sum(s.percentage for s in src_list)
        rows.append(_ContextCategoryRow(
            category=cat,
            scope=scope,
            label=CATEGORY_LABELS.get(cat, cat),
            items=len(src_list),
            tokens=tokens,
            pct=pct,
        ))
    rows.sort(key=lambda r: (0 if r.scope == "project" else 1, -r.tokens))
    return rows


def _context_search_reset_selection(state: TuiState) -> None:
    """Reset the active Context sub-tab's selection (query edits re-anchor
    the cursor to row 0, mirroring the Extensions search)."""
    if state.context_sub_tab == "project":
        state.project_selected = 0
    else:
        state.context_selected = 0


def _handle_context_search_keys(state: TuiState, key: int) -> Optional[str]:
    """Context `/`-search input mode (mirrors _handle_ext_search_keys):
    Esc clears, Enter applies, Bksp deletes, printable ASCII appends."""
    sub = state.context_sub_tab
    if key == KEY_ESC:
        state.context_searching = False
        state.context_search.pop(sub, None)
        _context_search_reset_selection(state)
        return "Search cleared"
    if is_enter(key):
        state.context_searching = False
        _context_search_reset_selection(state)
        q = state.context_search.get(sub, "")
        return f"Searching {q!r}" if q else None
    if key in (curses.KEY_BACKSPACE, KEY_BACKSPACE, 8):
        state.context_search[sub] = state.context_search.get(sub, "")[:-1]
        _context_search_reset_selection(state)
        return None
    if 32 <= key < 127:  # printable ASCII
        state.context_search[sub] = state.context_search.get(sub, "") + chr(key)
        _context_search_reset_selection(state)
        return None
    return None


def _context_source_haystack(item: Any) -> str:
    """Searchable text for a Project sub-tab row (a ContextSource)."""
    parts = [item.name, item.category,
             CATEGORY_LABELS.get(item.category, ""),
             getattr(item, "scope", "global"), item.path or ""]
    return " ".join(p for p in parts if p).lower()


def _displayed_project_items(state: TuiState) -> list:
    """The displayed (sorted, search-filtered) Project list — the single
    ordering shared by render and the input handlers so selection indices
    stay aligned (mirrors _subtab_view)."""
    items = state.project_items or []
    q = state.context_search.get("project", "").lower()
    if q:
        items = [i for i in items if q in _context_source_haystack(i)]
    return items


def _displayed_context_rows(state: TuiState, analysis) -> list:
    """The displayed (search-filtered) Sources category rows."""
    rows = _context_rows(analysis) if analysis else []
    q = state.context_search.get("sources", "").lower()
    if q:
        rows = [r for r in rows
                if q in f"{r.label} {r.category} {r.scope}".lower()]
    return rows


def _render_rate_limit_bars(stdscr, y: int, w: int) -> int:
    """5h/7d rate-limit quotas from ~/.claude/usage-snapshot.json, drawn on a
    single line as two color-coded segments. Returns rows used (always 1)."""
    rl = read_rate_limits(PATHS.usage_snapshot)
    if rl is None:
        safe_addnstr(stdscr, y, 2, "Rate limits: snapshot missing or stale", w - 4, CP_DIM())
        return 1

    def quota_attr(pct: int) -> int:
        return CP_ERR() if pct >= 90 else CP_OK() if pct < 60 else CP_INFO()

    # Narrow bars so both quotas share one line; scale to width, clamp 6–14.
    bar_w = max(6, min(14, (w - 40) // 2))
    segments: list[tuple[str, int]] = []
    if rl.five_hour is not None:
        bar = render_bar(round((rl.five_hour / 100) * bar_w), bar_w)
        segments.append((f"5h {bar} {rl.five_hour:3d}% ({_fmt_quota_eta(rl.five_hour_reset_at)})",
                         quota_attr(rl.five_hour)))
    if rl.seven_day is not None:
        bar = render_bar(round((rl.seven_day / 100) * bar_w), bar_w)
        segments.append((f"7d {bar} {rl.seven_day:3d}% ({_fmt_quota_eta(rl.seven_day_reset_at)})",
                         quota_attr(rl.seven_day)))

    cursor = 2
    for text, attr in segments:
        if cursor >= w - 1:
            break
        safe_addnstr(stdscr, y, cursor, text, w - 1 - cursor, attr)
        cursor += cell_width(text) + 4  # 4-cell gap between the two quotas
    return 1


def _render_context_sources_table(stdscr, state: TuiState, y0: int, h: int, w: int,
                                   rows: list, focused: bool = True) -> None:
    """Render the context-sources breakdown as a full-width table.

    Detail for the selected row lives in the shared bottom panel (see
    ``_context_detail_for``), not a per-section side panel — the table claims
    the whole width. ``focused`` controls the selected-row highlight.
    """
    if h <= 0:
        return
    # Section header with counts — the same band Project draws, so both
    # sub-tabs share one rhythm below the `/search:` band. With a filter
    # applied the header shows filtered/total.
    all_rows = _context_rows(state.context_analysis) if state.context_analysis else []
    q = state.context_search.get("sources", "")
    count = f"({len(rows)}/{len(all_rows)} categories)" if q else f"({len(all_rows)} categories)"
    header = f"Context sources  {count}"
    if q:
        header += f"  search={q!r}"
    render_section_header(stdscr, y0, w, header)
    y0, h = y0 + 1, max(1, h - 1)
    if not rows:
        msg = (f'No sources match "{q}". Press Esc to clear the filter.'
               if q else "No context sources detected.")
        safe_addnstr(stdscr, y0, 2, fit_cells(msg, w - 4), w - 4, CP_DIM())
        return
    state.context_selected = max(0, min(state.context_selected, len(rows) - 1))
    columns = [
        TableColumn("label", "Category", max(15, w - 44)),
        TableColumn("scope", "Scope", 9),
        TableColumn("items", "#", 4),
        TableColumn("tokens", "Tokens", 10),
        TableColumn("pct", "%", 8),
    ]
    table_rows = [{
        "label": r.label,
        "scope": "project" if r.scope == "project" else "global",
        "items": str(r.items),
        "tokens": format_tokens(r.tokens),
        "pct": f"{r.pct:.1f}%",
    } for r in rows]
    render_table(stdscr, y0, 0, h, w, columns, table_rows,
                 selected=(state.context_selected if focused else -1),
                 show_header=True)


def _project_item_detail_fields(item) -> list[tuple[str, str]]:
    """(label, value) pairs for the focused Project files item's detail panel."""
    preview = "\n".join(item.content.splitlines()[:12]) if item.content else ""
    return [
        ("Source", item.source),
        ("Lines", str(item.lines)),
        ("Tokens", f"{format_tokens(item.estimated_tokens)} ({item.percentage:.1f}%)"),
        ("Path", item.path),
        ("Preview", preview or "—"),
    ]


def _render_project_files_table(stdscr, state: TuiState, y0: int, h: int, w: int,
                                focused: bool = False) -> None:
    """Render the per-project context file list (CLAUDE.md, settings, memory…)
    as a full-width table. Detail goes to the shared bottom panel."""
    _ensure_project_loaded(state)
    items = state.project_items or []
    render_section_header(stdscr, y0, w,
        f"Project files — {Path.cwd().name}  ({len(items)} files)")
    body_y, body_h = y0 + 1, max(1, h - 1)
    if not items:
        safe_addnstr(stdscr, body_y, 2, "No project context files found.", w - 4, CP_DIM())
        return
    state.project_selected = max(0, min(state.project_selected, len(items) - 1))
    columns = [
        TableColumn("name", "Name", max(20, w - 44)),
        TableColumn("source", "Source", 8),
        TableColumn("lines", "Lines", 6),
        TableColumn("tokens", "Tokens", 10),
        TableColumn("pct", "%", 8),
    ]
    rows_data = [{
        "name": i.name, "source": i.source, "lines": str(i.lines),
        "tokens": format_tokens(i.estimated_tokens), "pct": f"{i.percentage:.1f}%",
    } for i in items]
    render_table(stdscr, body_y, 0, body_h, w, columns, rows_data,
                 selected=(state.project_selected if focused else -1),
                 show_header=True)


def _context_detail_for(state: TuiState, analysis: ContextAnalysis,
                        rows: list) -> tuple[str, list[tuple[str, str]]]:
    """(title, fields) for the shared bottom detail panel — reflects the active
    Context sub-tab's selected row (Sources category or Project file)."""
    if state.context_sub_tab == "project":
        items = _displayed_project_items(state)
        if items and 0 <= state.project_selected < len(items):
            cur = items[state.project_selected]
            return cur.name, _project_item_detail_fields(cur)
        return "Project context", [("(empty)", "—")]
    if rows and 0 <= state.context_selected < len(rows):
        current = rows[state.context_selected]
        fields: list[tuple[str, str]] = []
        srcs = [s for s in analysis.sources
                if s.category == current.category
                and getattr(s, "scope", "global") == current.scope]
        srcs.sort(key=lambda s: s.estimated_tokens, reverse=True)
        # Uncapped: the panel is focusable/scrollable (Enter → j/k), so every
        # member is reachable. Each line carries its own usage share.
        for s in srcs:
            hint = f" ({s.hint})" if s.hint else ""
            fields.append((s.name,
                           f"{format_tokens(s.estimated_tokens)} tok  "
                           f"{s.percentage:.1f}%{hint}"))
        scope_label = "project" if current.scope == "project" else "global"
        return f"{current.label} — {scope_label}", (fields or [("(empty)", "—")])
    return "Context sources", [("(empty)", "—")]


def _render_context_page(stdscr, state: TuiState, y0: int, h: int, w: int,
                         analysis: ContextAnalysis, rows: list) -> None:
    """Render the active Context sub-tab's body: a full-width table on top and
    the shared bottom detail panel mirroring the selected row."""
    if h <= 0:
        return
    # Shared detail panel claims the bottom ~35% (Extensions-style), never
    # starving the table below a couple of rows.
    detail_h = max(7, min(14, int(h * 0.35)))
    detail_h = max(0, min(detail_h, h - 2))
    table_h = max(1, h - detail_h)

    table_focused = not state.context_detail_focused
    if state.context_sub_tab == "project":
        _render_project_files_table(stdscr, state, y0, table_h, w,
                                    focused=table_focused)
    else:
        # Empty/no-match handling lives inside the sources table renderer so
        # the section header row is always present (same rhythm as Project).
        _render_context_sources_table(stdscr, state, y0, table_h, w, rows,
                                      focused=table_focused)

    if detail_h >= 3:
        title, fields = _context_detail_for(state, analysis, rows)
        state.context_detail_scroll = render_detail_panel(
            stdscr, y0 + table_h, 0, detail_h, w, title, fields,
            scroll=state.context_detail_scroll,
            focused=state.context_detail_focused)


def render_context_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    _ensure_context_loaded(state)
    analysis = state.context_analysis
    if analysis is None:
        safe_addnstr(stdscr, y0 + 2, 2, "Loading context…", w - 4, CP_DIM())
        return

    # The `/search:` band and the `search='q'` chip both live down at the
    # list (band above the section-header filter bar, chip on it) — the tab
    # title stays free of search state.
    q = state.context_search.get(state.context_sub_tab, "")
    body_y, _ = render_title_bar(
        stdscr, y0, h, w,
        f" Context — {format_tokens(analysis.total_tokens)} / {format_tokens(analysis.context_window_size)} "
        f"({analysis.used_percent:.1f}%)  model={analysis.model}")

    # ── Rate limits: a persistent top strip shown above both sub-tabs (5h / 7d
    # quota bars under a section-header band).
    render_section_header(stdscr, body_y, w, "Rate limits")
    rl_rows = _render_rate_limit_bars(stdscr, body_y + 1, w)

    # ── Sub-tab bar (Sources / Project), mirroring the Extensions tab. A blank
    # spacer row separates it from the rate bars above; a dim rule sits below.
    bar_y = body_y + 1 + rl_rows + 1
    _render_subtab_bar(stdscr, bar_y, w, CONTEXT_SUB_TABS, state.context_sub_tab,
                       focused=(state.focused_layer == "subTab"))
    safe_addnstr(stdscr, bar_y + 1, 0, "─" * (w - 1), w - 1, CP_DIM())

    # ── Active sub-tab body between the bar and the bottom cost line.
    content_y = bar_y + 2
    # `/search:` band directly above the list (mirrors Vault / the Extensions
    # sub-tabs): live `_` cursor while typing, cursor-less once applied.
    if state.context_searching or q:
        cursor = "_" if state.context_searching else ""
        safe_addnstr(stdscr, content_y, 0, fit_cells(f" /search: {q}{cursor}", w - 1),
                     w - 1, CP_INFO() | curses.A_BOLD)
        content_y += 1
    content_bottom = y0 + h - 2  # cost line sits at h-2
    rows = _displayed_context_rows(state, analysis)
    _render_context_page(stdscr, state, content_y, max(1, content_bottom - content_y),
                         w, analysis, rows)

    # Cost impact line at the bottom.
    ci = analysis.cost_impact
    safe_addnstr(stdscr, y0 + h - 2, 0, fit_cells(
        f"  cost: cache_write=${ci.cache_write_cost:.3f}  "
        f"read/turn=${ci.cache_read_cost_per_turn:.3f}  "
        f"per_session(${ci.per_session_cost:.2f})  monthly(${ci.monthly_cost:.2f})  "
        f"[assumes {ci.avg_turns_per_session} turns × {ci.avg_sessions_per_day} sessions/day]",
        w - 1), w - 1, CP_DIM())


def _handle_context_detail_keys(state: TuiState, key: int) -> Optional[str]:
    """Detail-panel focus mode (both Context sub-tabs): j/k (±1) and
    PgDn/PgUp (±10) scroll; Esc blurs back to the table; [ / ] still cycle
    the sub-tab (blurring first so the panel doesn't go stale); r refreshes
    and blurs back to the table too."""
    if key == KEY_ESC:
        state.context_detail_focused = False
        state.context_detail_scroll = 0
        return None
    if key in (ord("["), ord("]")):
        state.context_detail_focused = False
        state.context_detail_scroll = 0
        _cycle_sub_tab(state, "context", -1 if key == ord("[") else 1)
        return f"Sub-tab: {state.context_sub_tab}"
    if key == ord("r"):
        state.context_detail_focused = False
        state.context_detail_scroll = 0
        state.context_analysis = None
        if state.context_sub_tab == "project":
            state.project_items = None
        return "Refreshed"
    if key in (ord("j"), curses.KEY_DOWN):
        state.context_detail_scroll += 1
    elif key in (ord("k"), curses.KEY_UP):
        state.context_detail_scroll = max(0, state.context_detail_scroll - 1)
    elif key == curses.KEY_NPAGE:
        state.context_detail_scroll += 10
    elif key == curses.KEY_PPAGE:
        state.context_detail_scroll = max(0, state.context_detail_scroll - 10)
    return None


def handle_context_input(state: TuiState, key: int) -> Optional[str]:
    # ── `/`-search input mode: capture characters, respond only to
    # Enter/Esc/Bksp (mirrors the Extensions sub-tab search).
    if state.context_searching:
        return _handle_context_search_keys(state, key)

    # ── Detail-panel focus mode (both sub-tabs): movement keys scroll the
    # bottom panel, Esc blurs. Sits first so list-selection keys can't move
    # the table row underneath the focused panel.
    if state.context_detail_focused:
        return _handle_context_detail_keys(state, key)

    sub = state.context_sub_tab
    # `/` starts search-input mode (both sub-tabs). The applied query filters
    # the active sub-tab's list the same way the Extensions search does.
    if key == ord("/"):
        state.context_searching = True
        state.context_search[sub] = ""
        _context_search_reset_selection(state)
        state.context_detail_scroll = 0
        return "/: type to filter, Enter to apply, Esc to cancel"
    # First Esc clears an applied search filter; the next Esc climbs a focus
    # layer as usual (the loop defers to this handler — see
    # _handle_content_layer_key).
    if key == KEY_ESC and state.context_search.get(sub):
        state.context_search.pop(sub, None)
        _context_search_reset_selection(state)
        return "Search cleared"

    # [ ] cycle Context sub-tabs in the body (mirrors Extensions). Canonical
    # ←/→ navigation lives at the subTab focus layer (see loop.py); this gives
    # a keyboard shortcut without climbing out of the content layer.
    if key == ord("["):
        _cycle_sub_tab(state, "context", -1)
        state.context_detail_scroll = 0
        return f"Sub-tab: {state.context_sub_tab}"
    if key == ord("]"):
        _cycle_sub_tab(state, "context", 1)
        state.context_detail_scroll = 0
        return f"Sub-tab: {state.context_sub_tab}"

    # Project sub-tab: route navigation/actions to the project handler
    # (j/k select, PgUp/PgDn page, Enter previews, e edits, r reloads).
    if state.context_sub_tab == "project":
        if key in (ord("j"), curses.KEY_DOWN, ord("k"), curses.KEY_UP,
                   curses.KEY_NPAGE, curses.KEY_PPAGE):
            state.context_detail_scroll = 0
        return handle_project_input(state, key)

    rows = _displayed_context_rows(state, state.context_analysis)
    n = len(rows)
    if key in (ord("j"), curses.KEY_DOWN):
        state.context_selected = min(n - 1, state.context_selected + 1) if n else 0
        state.context_detail_scroll = 0
    elif key in (ord("k"), curses.KEY_UP):
        state.context_selected = max(0, state.context_selected - 1)
        state.context_detail_scroll = 0
    elif key == curses.KEY_NPAGE:
        state.context_selected = min(n - 1, state.context_selected + 10) if n else 0
        state.context_detail_scroll = 0
    elif key == curses.KEY_PPAGE:
        state.context_selected = max(0, state.context_selected - 10)
        state.context_detail_scroll = 0
    elif key == ord("r"):
        state.context_analysis = None
        state.context_detail_scroll = 0
        return "Refreshed"
    elif key == ord("e") and state.context_analysis and state.stdscr_callbacks and 0 <= state.context_selected < n:
        # Match the detail panel's (category, scope) filter — a "project" row
        # must never open a global file (and vice versa).
        row = rows[state.context_selected]
        first = next((s for s in state.context_analysis.sources
                      if s.category == row.category
                      and getattr(s, "scope", "global") == row.scope and s.path), None)
        if first is None:
            return "No file to edit in this category"
        ok = open_in_editor(state.stdscr_callbacks["stdscr"], first.path)
        return f"Opened {first.path}" if ok else "Editor failed"
    elif is_enter(key) and 0 <= state.context_selected < n:
        state.context_detail_focused = True
        state.context_detail_scroll = 0
        return "Detail focused — j/k to scroll, Esc to blur"
    elif key == ord("v") and state.context_analysis and state.stdscr_callbacks and 0 <= state.context_selected < n:
        row = rows[state.context_selected]
        srcs = [s for s in state.context_analysis.sources
                if s.category == row.category
                and getattr(s, "scope", "global") == row.scope]
        srcs.sort(key=lambda s: s.estimated_tokens, reverse=True)
        lines = [f"{row.label} — {row.items} item(s), {format_tokens(row.tokens)} tok", ""]
        for s in srcs[:50]:
            hint = f"  ({s.hint})" if s.hint else ""
            lines.append(f"━━ {s.name} — {format_tokens(s.estimated_tokens)} tok  {s.percentage:.1f}%{hint}")
            if s.path:
                lines.append(f"   {s.path}")
            if s.content:
                lines.append("")
                lines.extend(s.content.splitlines())
            else:
                lines.append("   (content unavailable — estimated size only)")
            lines.append("")
        if len(srcs) > 50:
            lines.append(f"… {len(srcs) - 50} more source(s) not shown")
        preview_modal(state.stdscr_callbacks["stdscr"], "\n".join(lines),
                      title=row.label, heading_prefix="━━")
    return None


# ─── Project tab ─────────────────────────────────────────────────────────────


# `s`-cycle sort definitions for the Project sub-tab's column headers, mirroring
# the Extensions sub-tabs' _SORT_COLUMNS (same (key, keyfunc, reverse,
# marked_col, glyph) shape — see that comment for the field meanings). "tokens"
# is the default so the list opens biggest-consumer-first; "pct" is omitted
# because percentage is a fixed linear scaling of tokens (same total for every
# row), so it would always produce an identical order — a no-op cycle step.
_PROJECT_SORT_SPECS: tuple = (
    ("tokens",   lambda s: s.estimated_tokens,                                        True,  "tokens",   "▼"),
    ("name",     lambda s: _lc(s.name),                                               False, "name",     "▲"),
    ("category", lambda s: (_lc(s.category), _lc(s.name)),                            False, "category", "▲"),
    ("scope",    lambda s: (getattr(s, "scope", "global") != "project", _lc(s.name)),  False, "scope",    "▲"),
)


def _project_sort_spec(state: TuiState):
    keys = [s[0] for s in _PROJECT_SORT_SPECS]
    cur = state.project_sort if state.project_sort in keys else keys[0]
    return next(s for s in _PROJECT_SORT_SPECS if s[0] == cur)


def _apply_project_sort(state: TuiState, items: list) -> list:
    _, keyfunc, reverse, _, _ = _project_sort_spec(state)
    try:
        return sorted(items, key=keyfunc, reverse=reverse)
    except (TypeError, AttributeError):
        return items


def _cycle_project_sort(state: TuiState) -> None:
    """Advance state.project_sort to the next column in _PROJECT_SORT_SPECS
    and re-sort the already-loaded items in place."""
    keys = [s[0] for s in _PROJECT_SORT_SPECS]
    i = keys.index(state.project_sort) if state.project_sort in keys else 0
    state.project_sort = keys[(i + 1) % len(keys)]
    state.project_selected = 0
    if state.project_items is not None:
        state.project_items = _apply_project_sort(state, state.project_items)


def _ensure_project_loaded(state: TuiState) -> None:
    """Populate state.project_items with every ContextSource that occupies
    this session's context — not just the CLAUDE.md/settings/memory files a
    project owns, but the full baseline (system prompt, hooks, skills,
    mcp-tools, plugins, commands, agents, git-status, user-context) that
    axt would also load when run in this project. Reuses the same analysis
    the Sources sub-tab shows (collect_context_sources), just flattened to
    item level instead of rolled up by category."""
    if state.project_items is not None:
        return
    _ensure_context_loaded(state)
    state.project_items = _apply_project_sort(state, list(state.context_analysis.sources))


def _project_item_detail_fields(item) -> list[tuple[str, str]]:
    """(label, value) pairs for the focused Project item's detail panel."""
    preview = "\n".join(item.content.splitlines()[:12]) if item.content else ""
    fields: list[tuple[str, str]] = [
        ("Category", CATEGORY_LABELS.get(item.category, item.category)),
        ("Scope", "project" if getattr(item, "scope", "global") == "project" else "global"),
        ("Tokens", f"{format_tokens(item.estimated_tokens)} ({item.percentage:.1f}%)"),
    ]
    if item.hint:
        fields.append(("Hint", item.hint))
    fields.append(("Path", item.path or "—"))
    fields.append(("Preview", preview or "—"))
    return fields


def _render_project_files_table(stdscr, state: TuiState, y0: int, h: int, w: int,
                                focused: bool = False) -> None:
    """Render every context source occupying this project's session (system
    prompt, CLAUDE.md, settings, memory, skills, mcp-tools, plugins, hooks,
    commands, agents, git-status, user-context) as a full-width table.
    Detail goes to the shared bottom panel."""
    _ensure_project_loaded(state)
    all_items = state.project_items or []
    items = _displayed_project_items(state)
    q = state.context_search.get("project", "")
    # Filter bar duties (vault convention): filtered/total counts + sort +
    # search chips, so the narrowed view is never mistaken for the full list.
    count = f"({len(items)}/{len(all_items)} sources)" if q else f"({len(all_items)} sources)"
    header = f"Project context — {Path.cwd().name}  {count}  sort={_project_sort_spec(state)[0]}"
    if q:
        header += f"  search={q!r}"
    render_section_header(stdscr, y0, w, header)
    body_y, body_h = y0 + 1, max(1, h - 1)
    if not items:
        msg = (f'No sources match "{q}". Press Esc to clear the filter.'
               if q else "No project context sources found.")
        safe_addnstr(stdscr, body_y, 2, fit_cells(msg, w - 4), w - 4, CP_DIM())
        return
    state.project_selected = max(0, min(state.project_selected, len(items) - 1))
    columns = [
        TableColumn("name", "Name", max(20, w - 54)),
        TableColumn("category", "Category", 15),
        TableColumn("scope", "Scope", 8),
        TableColumn("tokens", "Tokens", 10),
        TableColumn("pct", "%", 7),
    ]
    # Mark the header of the column the list is currently sorted by (`s` cycles it).
    _, _, _, marked_col, glyph = _project_sort_spec(state)
    if marked_col:
        columns = mark_sorted_header(columns, marked_col, glyph)
    rows_data = [{
        "name": i.name,
        "category": CATEGORY_LABELS.get(i.category, i.category),
        "scope": "project" if getattr(i, "scope", "global") == "project" else "global",
        "tokens": format_tokens(i.estimated_tokens),
        "pct": f"{i.percentage:.1f}%",
    } for i in items]
    render_table(stdscr, body_y, 0, body_h, w, columns, rows_data,
                 selected=(state.project_selected if focused else -1),
                 show_header=True)


def handle_project_input(state: TuiState, key: int) -> Optional[str]:
    # Called only via handle_context_input on the "project" sub-tab. Operates
    # on the displayed (search-filtered) view so the selection index stays
    # aligned with what the table shows.
    items = _displayed_project_items(state)
    n = len(items)
    if key in (ord("j"), curses.KEY_DOWN):
        state.project_selected = min(n - 1, state.project_selected + 1) if n else 0
    elif key in (ord("k"), curses.KEY_UP):
        state.project_selected = max(0, state.project_selected - 1)
    elif key == curses.KEY_NPAGE:
        state.project_selected = min(n - 1, state.project_selected + 10) if n else 0
    elif key == curses.KEY_PPAGE:
        state.project_selected = max(0, state.project_selected - 10)
    elif key == ord("r"):
        state.project_items = None
        state.context_analysis = None
        state.context_detail_scroll = 0
        return "Refreshed"
    elif key == ord("s"):
        _cycle_project_sort(state)
        return f"Sort: {state.project_sort}"
    elif is_enter(key) and items and state.project_selected < n:
        state.context_detail_focused = True
        state.context_detail_scroll = 0
        return "Detail focused — j/k to scroll, Esc to blur"
    elif key == ord("v") and state.stdscr_callbacks and items and state.project_selected < n:
        item = items[state.project_selected]
        preview_modal(state.stdscr_callbacks["stdscr"], item.content or "", title=item.name)
    elif key == ord("e") and state.stdscr_callbacks and items and state.project_selected < n:
        item = items[state.project_selected]
        if not item.path:
            return "No file to edit for this source"
        ok = open_in_editor(state.stdscr_callbacks["stdscr"], item.path)
        return f"Opened {item.path}" if ok else "Editor failed"
    elif key == ord("d") and state.stdscr_callbacks and items and state.project_selected < n:
        item = items[state.project_selected]
        if item.category != "memory":
            return "Only memory files can be deleted here"
        stdscr = state.stdscr_callbacks["stdscr"]
        if confirm_modal(stdscr, f"Delete {item.name}?\nThis removes {item.path}.", title="Confirm delete"):
            try:
                delete_memory_file(item.path)
                state.project_items = None
                state.context_analysis = None
                return f"Deleted {item.name}"
            except (OSError, ValueError) as exc:
                return f"Delete failed: {exc}"
        return "Cancelled"
    return None


# ─── Extensions sub-tabs ─────────────────────────────────────────────────────


EXTENSION_SUB_TABS: tuple[tuple[str, str], ...] = (
    ("vault", "Vault"),
    ("skills", "Skills"),
    ("commands", "Commands"),
    ("agents", "Agents"),
    ("mcp", "MCP"),
    ("hooks", "Hooks"),
    ("plugins", "Plugins"),
    ("market", "Market"),
)

# Context sub-tabs (Rate limits renders above both as a persistent strip).
CONTEXT_SUB_TABS: tuple[tuple[str, str], ...] = (
    ("project", "Project"),
    ("sources", "Sources"),
)

# Registry: which main tabs own a sub-tab bar, plus the TuiState attribute
# that holds the active sub-tab key. Generalizes the (formerly Extensions-only)
# subTab focus layer so Context can reuse the exact same bar + navigation.
SUB_TABS_BY_TAB: dict[str, tuple[tuple[str, str], ...]] = {
    "extensions": EXTENSION_SUB_TABS,
    "context": CONTEXT_SUB_TABS,
}
_SUB_TAB_ATTR: dict[str, str] = {
    "extensions": "ext_sub_tab",
    "context": "context_sub_tab",
}


def _active_sub_tab(state: TuiState, tab_key: str) -> str:
    """Active sub-tab key for the given main tab (empty if it has none)."""
    attr = _SUB_TAB_ATTR.get(tab_key)
    return getattr(state, attr) if attr else ""


def _render_subtab_bar(stdscr, y: int, w: int, sub_tabs: tuple[tuple[str, str], ...],
                       active_key: str, *, focused: bool = False) -> None:
    """Render a sub-tab bar with a clear focus indicator.

    Shared by Extensions and Context — ``sub_tabs`` is the (key, label) tuple
    for the owning main tab.

    Layered focus (matches `render_tab_bar` so focus is unambiguous when
    switching between main-tab and sub-tab layers):
      - Bar focused:    `▶ Sub:` marker + active sub-tab is solid cyan chip
                        (pair 1 + BOLD), brackets retained for color-blind safety
      - Bar unfocused:  `  Sub:` (no marker) + active sub-tab is bold cyan text
                        with underline (no fill), brackets retained
    """
    label_attr = CP_TITLE() if focused else CP_DIM()
    marker = "▶ " if focused else "  "
    marker_attr = _safe_pair(8, curses.A_BOLD) if focused else CP_DIM()
    safe_addnstr(stdscr, y, 0, marker, w, marker_attr)
    safe_addnstr(stdscr, y, cell_width(marker), "Sub: ", w - cell_width(marker), label_attr)
    cur = cell_width(marker) + 5  # "Sub: " is 5 cells
    inactive_attr = _safe_pair(8, curses.A_BOLD) if focused else CP_DIM()
    active_attr = CP_ACTIVE_CHIP() if focused else _safe_pair(8, curses.A_BOLD | curses.A_UNDERLINE)
    for i, (key, label) in enumerate(sub_tabs):
        if key == active_key:
            cell = f"[ {label} ]"
            attr = active_attr
        else:
            cell = f"  {label}  "
            attr = inactive_attr
        if cur + cell_width(cell) >= w:
            break
        safe_addnstr(stdscr, y, cur, cell, w - cur, attr)
        cur += cell_width(cell) + 1
    if cur < w:
        safe_addnstr(stdscr, y, cur, " " * (w - cur - 1), w - cur - 1, CP_DIM())


def _ensure_subtab_loaded(state: TuiState, sub_key: str) -> None:
    if sub_key in state.ext_cache:
        return
    if sub_key == "plugins":
        state.ext_cache["plugins"] = list_installed_plugins(PATHS.installed_plugins, PATHS.known_marketplaces)
    elif sub_key == "skills":
        items = list_all_skills(project_dir=Path.cwd())
        state.ext_cache["skills"] = items + list_vault_only_items("skills", items)
    elif sub_key == "commands":
        items = list_commands(project_dir=Path.cwd())
        state.ext_cache["commands"] = items + list_vault_only_items("commands", items)
    elif sub_key == "agents":
        items = list_all_agents(project_dir=Path.cwd())
        state.ext_cache["agents"] = items + list_vault_only_items("agents", items)
    elif sub_key == "mcp":
        state.ext_cache["mcp"] = collect_mcp_servers(_active_plugins())
    elif sub_key == "hooks":
        state.ext_cache["hooks"] = list_hooks(
            user_settings_path=PATHS.settings,
            project_dir=Path.cwd(),
            installed_plugins_path=PATHS.installed_plugins,
        )
    elif sub_key == "market":
        state.ext_cache["market"] = list_marketplaces(PATHS.known_marketplaces)


def _plugin_detail_fields(plugin, enabled_g, enabled_p) -> tuple[str, list[tuple[str, str]]]:
    """(title, label/value pairs) for the Plugin detail panel."""
    def _state(v) -> str:
        return "enabled" if v is True else ("disabled" if v is False else "unset")

    fields: list[tuple[str, str]] = [
        ("ID", plugin.id),
        ("Version", plugin.version or "—"),
        ("Marketplace", plugin.marketplace or "—"),
        ("Scope", plugin.scope or "—"),
        ("Global", _state(enabled_g.get(plugin.id))),
        ("Project", _state(enabled_p.get(plugin.id))),
    ]
    if plugin.author:
        fields.append(("Author", plugin.author))
    if plugin.description:
        fields.append(("Description", plugin.description))
    if plugin.homepage:
        fields.append(("Homepage", plugin.homepage))
    if plugin.repository:
        fields.append(("Repository", plugin.repository))
    if plugin.install_path:
        fields.append(("Path", plugin.install_path))
    if plugin.last_updated:
        fields.append(("Updated", plugin.last_updated[:10]))
    return plugin.name, fields


def _mcp_detail_fields(server) -> tuple[str, list[tuple[str, str]]]:
    """(title, label/value pairs) for the MCP detail panel."""
    fields: list[tuple[str, str]] = [
        ("Scope", server.scope),
        ("Transport", server.transport),
        ("Status", "disabled (this project)" if server.disabled else "enabled"),
    ]
    if server.plugin_id:
        fields.append(("Plugin", server.plugin_id))
    if server.version:
        fields.append(("Version", server.version))
    if server.transport == "stdio":
        fields.append(("Command", " ".join([server.command, *server.args_list]).strip() or "—"))
        if server.env_dict:
            # Redacted for the same reason as `mcp info`: the detail panel is
            # what is on screen during a demo or a pairing session.
            fields.append(("Env", ", ".join(
                f"{k}={v}" for k, v in mask_env(server.env_dict).items())))
    elif server.url:
        fields.append(("URL", server.url))
    return server.name, fields


def _hook_detail_fields(hook) -> tuple[str, list[tuple[str, str]]]:
    """(title, label/value pairs) for the Hook detail panel."""
    fields: list[tuple[str, str]] = [
        ("Matcher", hook.matcher or "*"),
        ("Type", hook.type),
        ("Source", hook.source),
        ("Status", "disabled" if hook.disabled else "enabled"),
    ]
    if hook.type == "command":
        fields.append(("Command", hook.command or "—"))
    elif hook.type == "http":
        fields.append(("URL", hook.url or "—"))
    elif hook.type == "mcp_tool":
        fields.append(("Server", hook.server or "—"))
        fields.append(("Tool", hook.tool or "—"))
    elif hook.type in ("prompt", "agent"):
        if hook.model:
            fields.append(("Model", hook.model))
        fields.append(("Prompt", hook.prompt or "—"))
    if hook.timeout is not None:
        fields.append(("Timeout", f"{hook.timeout}ms"))
    if hook.condition:
        fields.append(("If", hook.condition))
    if hook.once:
        fields.append(("Once", "true"))
    if hook.async_:
        fields.append(("Async", "true"))
    if hook.version:
        fields.append(("Version", hook.version))
    if hook.source_path:
        fields.append(("File", hook.source_path))
    return hook.event, fields


def _agent_detail_fields(agent) -> tuple[str, list[tuple[str, str]]]:
    """(title, label/value pairs) for the Agent detail panel."""
    fields: list[tuple[str, str]] = [
        ("Source", agent.source),
        ("Version", agent.version or "—"),
    ]
    if agent.plugin:
        fields.append(("Plugin", agent.plugin))
    if agent.description:
        fields.append(("Description", agent.description))
    if agent.source_path:
        fields.append(("File", agent.source_path))
    return agent.name, fields


def _skill_detail_fields(skill) -> tuple[str, list[tuple[str, str]]]:
    """(title, label/value pairs) for the Skill detail panel."""
    fields: list[tuple[str, str]] = [
        ("Source", skill.source),
        ("Version", skill.version or "—"),
        ("Type", "symlink" if skill.is_symlink else "dir"),
    ]
    if skill.plugin:
        fields.append(("Plugin", skill.plugin))
    fields.append(("Path", skill.path))
    if skill.target:
        fields.append(("Target", skill.target))
    return skill.name, fields


def _command_detail_fields(command) -> tuple[str, list[tuple[str, str]]]:
    """(title, label/value pairs) for the Command detail panel."""
    fields: list[tuple[str, str]] = [
        ("Source", command.source),
        ("Version", command.version or "—"),
    ]
    if command.plugin:
        fields.append(("Plugin", command.plugin))
    if command.description:
        fields.append(("Description", command.description))
    if command.source_path:
        fields.append(("File", command.source_path))
    return f"/{command.name}", fields


def _market_detail_fields(market) -> tuple[str, list[tuple[str, str]]]:
    """(title, label/value pairs) for the Marketplace detail panel."""
    src = market.source
    fields: list[tuple[str, str]] = [
        ("Source", src.kind if src else "—"),
    ]
    if src:
        if src.repo:
            fields.append(("Repo", src.repo))
        if src.url:
            fields.append(("URL", src.url))
        if src.path:
            fields.append(("Path", src.path))
    if market.install_location:
        fields.append(("Location", market.install_location))
    if market.last_updated:
        fields.append(("Updated", market.last_updated[:10]))
    return market.name, fields


# Sub-tabs that render a bottom detail panel (Tab-focusable + scrollable).
# Every non-Vault sub-tab now has one; Vault renders its own bottom panel.
_SUBTABS_WITH_DETAIL: tuple[str, ...] = (
    "plugins", "mcp", "hooks", "agents", "skills", "commands", "market",
)


def _lc(v: Any) -> str:
    """Case-fold a possibly-None string for stable, case-insensitive sorting."""
    return (v or "").lower()


# Per-sub-tab `s`-cycle sort definitions for the non-vault Extensions sub-tabs,
# mirroring the Vault sort cycle. Pressing `s` advances `state.ext_sort[sub]`
# to the next key here. Each spec is:
#   (key, keyfunc, reverse, marked_col, glyph)
# where `marked_col` is the TableColumn.key whose header gets the ▲/▼ `glyph`
# (the visible "sorted by this column" cue), or None for no column mark.
# ─── Per-column sort (shared by every Extensions sub-tab) ────────────────────

# `_SORT_COLUMNS` is the single source of truth for the `s` / `S` sort cycle,
# the ▲/▼ header mark, and the status-bar label. Each entry is
#
#   (key, marked_col, desc_first, keybuilder)
#
#   key         stable id for the column — equal to the TableColumn.key when
#               the column is rendered ("added"/"updated" on Vault sort real
#               data that has no column of its own),
#   marked_col  TableColumn.key whose header carries the ▲/▼ glyph, or None,
#   desc_first  the column's natural first direction: False for text columns
#               (A→Z), True for recency/count columns (newest / most first),
#   keybuilder  (state, sub, data) -> keyfunc(item). Handing the builder the
#               whole list up front lets the state- and filesystem-backed
#               columns (Vault / Proj / Glob / Upd) resolve each row's cell
#               exactly once instead of once per comparison.
#
# Entries follow the rendered column order, so `s` walks the table left to
# right. The `#` column is deliberately absent: it holds the row's position in
# the current order, so sorting by it could never reorder anything. Columns
# that are constant for a whole sub-tab are omitted for the same reason (see
# the Vault-column note on plugins/mcp/hooks below).
_SortCol = tuple[str, Optional[str], bool, Callable[..., Callable[[Any], Any]]]

_DATE_MIN = datetime.min.replace(tzinfo=timezone.utc)

# Rendered glyph → ascending rank, so a status column sorts by what the row
# actually shows and "on" states come first.
_ON_RANK = {"●": 0, "✓": 0, "○": 1, "·": 2, "─": 3}
_UPD_RANK = {"↑": 0, "!": 1, "…": 2, "·": 3, "─": 4}


def _ver_key(v: Optional[str]) -> tuple:
    """Numeric-aware version key so 1.10.0 sorts after 1.9.0 (plain text
    comparison gets that backwards). Non-numeric segments fall back to their
    lowercase text, and a missing version sorts last in ascending order."""
    text = (v or "").strip().lstrip("vV")
    if not text or text in ("—", "─"):
        return (1,)
    parts = [
        (0, int(chunk), "") if chunk.isdigit() else (1, 0, chunk.lower())
        for chunk in re.split(r"[._\-+]", text)
    ]
    return (0, tuple(parts))


def _by(fn: Callable[[Any], Any]):
    """Keybuilder for a column whose value comes straight off the item."""
    return lambda state, sub, data: fn


def _by_state(make: Callable[[TuiState, str], Callable[[Any], Any]]):
    """Keybuilder for a column that needs `state`. `make` runs once per sort,
    so any lookup table it builds is shared by every comparison."""
    return lambda state, sub, data: make(state, sub)


def _by_glyph(cellfn: Callable[[TuiState, str, Any], str], ranks: dict[str, int]):
    """Keybuilder for a status column: rank each row by the glyph the renderer
    would draw for it. `cellfn` runs once per item (some cells stat the
    filesystem or read settings), never inside the comparison."""
    def build(state: TuiState, sub: str, data: list):
        rank = {id(i): ranks.get(cellfn(state, sub, i), 99) for i in data}
        return lambda item: rank.get(id(item), 99)
    return build


def _by_scope_glyph(scope: str):
    """Keybuilder for the Proj / Glob columns. Shares `_scope_cell` with the
    renderer, so the order can never drift from the glyphs on screen."""
    def build(state: TuiState, sub: str, data: list):
        ctx = _scope_ctx(state, sub)
        rank = {id(i): _ON_RANK.get(_scope_cell(sub, i, scope, ctx), 99) for i in data}
        return lambda item: rank.get(id(item), 99)
    return build


# Thin indirections so the spec table below can name cell functions that this
# module defines further down (the table is built at import time; these defer
# the lookup to call time).
def _vault_glyph(state: TuiState, sub: str, item: Any) -> str:
    return _vault_cell(sub, item)


def _upd_glyph(state: TuiState, sub: str, item: Any) -> str:
    return _upd_cell(state, sub, item)


def _vault_used_key(state: TuiState, sub: str):
    """Project count backing the Vault `Used` column (0 when unscanned)."""
    index = state.vault_usage_index

    def keyfn(item: Any) -> int:
        entry = index.get(f"{item.type}:{item.name}") if index else None
        return len(entry.projects) if entry else 0
    return keyfn


_SORT_COLUMNS: dict[str, tuple[_SortCol, ...]] = {
    "vault": (
        ("name",    "name",    False, _by(lambda i: _lc(i.name))),
        ("ver",     "ver",     False, _by(lambda i: _ver_key(i.version))),
        ("type",    "type",    False, _by(lambda i: _lc(i.type))),
        ("project", "project", False, _by(lambda i: not i.is_linked)),
        ("global",  "global",  False, _by(lambda i: not i.is_global_linked)),
        ("used",    "used",    True,  _by_state(_vault_used_key)),
        # No column of their own — the title bar's `sort=` text names them.
        ("added",   None,      True,  _by(lambda i: i.created_at or _DATE_MIN)),
        ("updated", None,      True,  _by(lambda i: i.updated_at or _DATE_MIN)),
    ),
    "skills": (
        ("name",   "name",   False, _by(lambda s: _lc(s.name))),
        ("ver",    "ver",    False, _by(lambda s: _ver_key(s.version))),
        ("vault",  "vault",  False, _by_glyph(_vault_glyph, _ON_RANK)),
        ("proj",   "proj",   False, _by_scope_glyph("proj")),
        ("glob",   "glob",   False, _by_scope_glyph("glob")),
        ("upd",    "upd",    False, _by_glyph(_upd_glyph, _UPD_RANK)),
        ("source", "source", False, _by(lambda s: _lc(s.source))),
        ("type",   "type",   False, _by(lambda s: s.is_symlink)),   # dir before symlink
        ("path",   "path",   False, _by(lambda s: _lc(s.target or s.path))),
    ),
    "commands": (
        ("name",   "name",   False, _by(lambda c: _lc(c.name))),
        ("ver",    "ver",    False, _by(lambda c: _ver_key(c.version))),
        ("vault",  "vault",  False, _by_glyph(_vault_glyph, _ON_RANK)),
        ("proj",   "proj",   False, _by_scope_glyph("proj")),
        ("glob",   "glob",   False, _by_scope_glyph("glob")),
        ("upd",    "upd",    False, _by_glyph(_upd_glyph, _UPD_RANK)),
        ("source", "source", False, _by(lambda c: _lc(c.source))),
        ("desc",   "desc",   False, _by(lambda c: _lc(c.description))),
    ),
    "agents": (
        ("name",   "name",   False, _by(lambda a: _lc(a.name))),
        ("ver",    "ver",    False, _by(lambda a: _ver_key(a.version))),
        ("vault",  "vault",  False, _by_glyph(_vault_glyph, _ON_RANK)),
        ("proj",   "proj",   False, _by_scope_glyph("proj")),
        ("glob",   "glob",   False, _by_scope_glyph("glob")),
        ("upd",    "upd",    False, _by_glyph(_upd_glyph, _UPD_RANK)),
        ("source", "source", False, _by(lambda a: _lc(a.source))),
        ("desc",   "desc",   False, _by(lambda a: _lc(a.description))),
    ),
    "mcp": (
        # The Vault column is `─` for every MCP row (the vault stores only
        # skills/commands/agents), so it is left out of the cycle rather than
        # spending two `s` presses on an order that cannot change.
        ("name",      "name",      False, _by(lambda s: _lc(s.name))),
        ("ver",       "ver",       False, _by(lambda s: _ver_key(getattr(s, "version", "")))),
        ("proj",      "proj",      False, _by_scope_glyph("proj")),
        ("glob",      "glob",      False, _by_scope_glyph("glob")),
        ("upd",       "upd",       False, _by_glyph(_upd_glyph, _UPD_RANK)),
        ("on",        "on",        False, _by(lambda s: bool(s.disabled))),
        ("scope",     "scope",     False, _by(lambda s: _lc(s.scope))),
        ("transport", "transport", False, _by(lambda s: _lc(s.transport))),
        ("detail",    "detail",    False, _by(lambda s: _lc(_mcp_detail_text(s)))),
    ),
    "hooks": (
        # Vault column omitted for the same reason as MCP (always `─`).
        ("event",  "event",  False, _by(lambda h: _lc(h.event))),
        ("ver",    "ver",    False, _by(lambda h: _ver_key(h.version))),
        ("proj",   "proj",   False, _by_scope_glyph("proj")),
        ("glob",   "glob",   False, _by_scope_glyph("glob")),
        ("upd",    "upd",    False, _by_glyph(_upd_glyph, _UPD_RANK)),
        ("type",   "type",   False, _by(lambda h: _lc(h.type))),
        ("source", "source", False, _by(lambda h: _lc(h.source))),
        ("detail", "detail", False, _by(lambda h: _lc(get_hook_detail(h)))),
    ),
    "plugins": (
        # Vault column omitted for the same reason as MCP (always `─`).
        ("name",    "name",    False, _by(lambda p: _lc(p.name))),
        ("version", "version", False, _by(lambda p: _ver_key(p.version))),
        ("proj",    "proj",    False, _by_scope_glyph("proj")),
        ("glob",    "glob",    False, _by_scope_glyph("glob")),
        ("upd",     "upd",     False, _by_glyph(_upd_glyph, _UPD_RANK)),
        ("market",  "market",  False, _by(lambda p: _lc(p.marketplace))),
    ),
    "market": (
        ("name",    "name",    False, _by(lambda m: _lc(m.name))),
        ("upd",     "upd",     False, _by_glyph(_upd_glyph, _UPD_RANK)),
        ("kind",    "kind",    False, _by(lambda m: _lc(m.source.kind))),
        ("loc",     "loc",     False, _by(lambda m: _lc(m.install_location))),
        ("updated", "updated", True,  _by(lambda m: m.last_updated or "")),
    ),
}

# Vault's sort key order, kept as a name of its own because the Vault tab's
# title bar and its tests speak in terms of the key list rather than the specs.
_VAULT_SORTS: tuple[str, ...] = tuple(c[0] for c in _SORT_COLUMNS["vault"])

# Secondary ordering applied before the column sort. Python's sort is stable,
# so rows tying on the chosen column keep this order — every column therefore
# gets a predictable within-group order without repeating a tiebreak in each
# keyfunc.
_SORT_TIEBREAK: dict[str, Callable[[Any], Any]] = {
    "hooks": lambda h: (_lc(h.event), _lc(h.type)),
}


def _sort_tiebreak(sub: str) -> Callable[[Any], Any]:
    return _SORT_TIEBREAK.get(sub, lambda i: _lc(getattr(i, "name", "")))


def _sort_state(state: TuiState, sub: str) -> tuple[str, bool]:
    """Active (column key, descending) for an Extensions sub-tab.

    Vault keeps its own `vault_sort` / `vault_sort_desc` fields (its title bar
    reads them directly); the other sub-tabs share the `ext_sort` /
    `ext_sort_desc` dicts. An unset direction means "this column's natural
    direction", so assigning just the key still yields the sensible order.
    An unknown key falls back to the first column."""
    cols = _SORT_COLUMNS.get(sub)
    if not cols:
        return "", False
    if sub == "vault":
        key, desc = state.vault_sort, state.vault_sort_desc
    else:
        key, desc = state.ext_sort.get(sub, ""), state.ext_sort_desc.get(sub)
    spec = next((c for c in cols if c[0] == key), cols[0])
    return spec[0], spec[2] if desc is None else bool(desc)


def _set_sort_state(state: TuiState, sub: str, key: str, desc: bool) -> None:
    """Write the active sort back and send the selection to the top row (the
    row under the cursor is about to move somewhere else)."""
    if sub == "vault":
        state.vault_sort = key
        state.vault_sort_desc = desc
        state.vault_selected = 0
    else:
        state.ext_sort[sub] = key
        state.ext_sort_desc[sub] = desc
        state.ext_selected[sub] = 0


def _cycle_sort_column(state: TuiState, sub: str) -> None:
    """`s` — move the sort one column to the right, wrapping at the end.

    The new column arrives in its own natural direction (`desc_first`), so
    Updated / Used open newest-and-most-first while text columns open A→Z;
    `S` flips whichever column you land on."""
    cols = _SORT_COLUMNS.get(sub)
    if not cols:
        return
    keys = [c[0] for c in cols]
    cur, _desc = _sort_state(state, sub)
    i = keys.index(cur) if cur in keys else 0
    nxt = cols[(i + 1) % len(cols)]
    _set_sort_state(state, sub, nxt[0], nxt[2])


def _toggle_sort_direction(state: TuiState, sub: str) -> None:
    """`S` — flip the active column between ascending (▲) and descending (▼),
    leaving the column itself alone."""
    cols = _SORT_COLUMNS.get(sub)
    if not cols:
        return
    key, desc = _sort_state(state, sub)
    _set_sort_state(state, sub, key, not desc)


def _sort_column_spec(state: TuiState, sub: str) -> Optional[_SortCol]:
    """The active column's spec, or None if the sub-tab has no sort cycle."""
    cols = _SORT_COLUMNS.get(sub)
    if not cols:
        return None
    key, _desc = _sort_state(state, sub)
    return next((c for c in cols if c[0] == key), cols[0])


def _apply_sort(state: TuiState, sub: str, data: list) -> list:
    """Return `data` ordered by the sub-tab's active column and direction.

    Falls back to the original order if the data lacks an expected attribute
    (defensive — keeps a malformed cache from blanking the list)."""
    cols = _SORT_COLUMNS.get(sub)
    if not cols or not data:
        return data
    key, desc = _sort_state(state, sub)
    spec = next((c for c in cols if c[0] == key), cols[0])
    try:
        keyfn = spec[3](state, sub, data)
        base = sorted(data, key=_sort_tiebreak(sub))
        return sorted(base, key=keyfn, reverse=desc)
    except (TypeError, AttributeError, OSError):
        return data


# Attributes probed (in order) to build a searchable haystack per item. Covers
# every non-vault sub-tab's item shape: plugins (name/id/marketplace), skills
# (name/source), commands/agents (name/source), mcp (name/scope/transport),
# hooks (event/type/source), market (name).
_SEARCH_ATTRS = ("name", "id", "event", "type", "source",
                 "marketplace", "scope", "transport")


def _subtab_search_haystack(item: Any) -> str:
    parts = []
    for attr in _SEARCH_ATTRS:
        v = getattr(item, attr, None)
        if isinstance(v, str) and v:
            parts.append(v)
    return " ".join(parts).lower()


def _subtab_view(state: TuiState, sub: str) -> list:
    """The displayed (sorted, search-filtered) item list for `sub` — the single
    ordering shared by render and the input handlers so selection indices stay
    aligned."""
    data = _apply_sort(state, sub, state.ext_cache.get(sub, []))
    q = state.ext_search.get(sub, "").lower()
    if q:
        data = [item for item in data if q in _subtab_search_haystack(item)]
    return data


def _mark_sorted_column(state: TuiState, sub: str, cols: list) -> list:
    """Annotate the sorted column's header with ▲ (ascending) / ▼ (descending)
    — the on-screen cue for where the `s` / `S` cycle currently sits."""
    spec = _sort_column_spec(state, sub)
    if spec is None or not spec[1]:
        return cols
    marked_col = spec[1]
    glyph = "▼" if _sort_state(state, sub)[1] else "▲"
    return mark_sorted_header(cols, marked_col, glyph)


def subtab_sort_label(state: TuiState, sub: str) -> str:
    """Active sort as `<column> ▲/▼` for the status bar, or "" when the
    sub-tab has no sort cycle."""
    if sub not in _SORT_COLUMNS:
        return ""
    key, desc = _sort_state(state, sub)
    return f"{key} {'▼' if desc else '▲'}"


def sort_cycle_help(sub: str) -> str:
    """`name→ver→…` listing of a sub-tab's sortable columns, so the `?` help
    is generated from _SORT_COLUMNS instead of drifting from it."""
    return "→".join(c[0] for c in _SORT_COLUMNS.get(sub, ()))


def _blur_ext_detail(state: TuiState) -> None:
    """Drop detail-panel focus and reset its scroll (e.g. on sub-tab change)."""
    state.ext_detail_focused = False
    state.ext_detail_scroll = 0


# Sub-tab → detail-panel field builder. `plugins` is special-cased in
# render_extensions_tab because its builder needs the enabled-state closures.
_SUBTAB_DETAIL_FIELD_FNS = {
    "mcp": _mcp_detail_fields,
    "hooks": _hook_detail_fields,
    "agents": _agent_detail_fields,
    "skills": _skill_detail_fields,
    "commands": _command_detail_fields,
    "market": _market_detail_fields,
}


def _render_list_with_detail(stdscr, state, y0, h, w, key, columns, rows, items, field_fn,
                             checked=None):
    """Selectable list with a read-only detail panel pinned to the bottom.

    ``field_fn(item)`` returns ``(title, [(label, value), ...])`` for the
    selected row. ``items`` is the cached object list parallel to ``rows``.
    ``checked`` carries the Space-marked row indices (■/□ prefix, mirrors
    Vault); the row number lives in the explicit `#` column.
    """
    state.ext_selected.setdefault(key, 0)
    state.ext_selected[key] = max(0, min(state.ext_selected[key], max(0, len(rows) - 1)))
    if not rows:
        q = state.ext_search.get(key, "")
        if q:
            # Directly under the `/search:` band — same top/bottom rhythm as
            # Vault/Context (the y0+2 padding below is for band-less empties).
            msg = f'No {key} match "{q}". Press Esc to clear the filter.'
            safe_addnstr(stdscr, y0, 2, fit_cells(msg, w - 4), w - 4, CP_DIM())
            return
        title, hint = _empty_state_hint(key)
        safe_addnstr(stdscr, y0 + 2, 2, fit_cells(title, w - 4), w - 4, CP_DIM())
        if hint:
            safe_addnstr(stdscr, y0 + 4, 2, fit_cells(hint, w - 4), w - 4, CP_DIM())
        return
    # Detail panel claims the bottom ~40% (7–16 rows) but never starves the
    # list below a few visible rows. When it can't show everything, Tab focuses
    # it and j/k scroll (see handle_extensions_input).
    detail_h = max(7, min(16, int(h * 0.4)))
    detail_h = min(detail_h, max(0, h - 4))
    table_h = max(1, h - detail_h)
    render_table(stdscr, y0, 0, table_h, w, columns, rows,
                 selected=state.ext_selected[key], checked=checked,
                 show_header=True, header_rule=False)
    if detail_h >= 3:
        idx = state.ext_selected[key]
        if 0 <= idx < len(items):
            title, fields = field_fn(items[idx])
            state.ext_detail_scroll = render_detail_panel(
                stdscr, y0 + table_h, 0, detail_h, w, title, fields,
                scroll=state.ext_detail_scroll,
                focused=state.ext_detail_focused,
            )


def render_extensions_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    """Extensions parent tab with sub-tab navigation."""
    _render_subtab_bar(
        stdscr, y0, w, EXTENSION_SUB_TABS, state.ext_sub_tab,
        focused=(state.focused_layer == "subTab"),
    )
    safe_addnstr(stdscr, y0 + 1, 0, "─" * (w - 1), w - 1, CP_DIM())

    sub_y = y0 + 2
    sub_h = h - 2

    sub = state.ext_sub_tab
    if sub == "vault":
        render_vault_tab(stdscr, state, sub_y, sub_h, w)
        return

    # Lazily start the async update check backing the `Upd` column. Idempotent
    # per frame: a fresh (< TTL) cached result short-circuits, an in-flight
    # check is left alone, and a completed one re-kicks only after the TTL.
    _kick_update_check(state)

    _ensure_subtab_loaded(state, sub)
    # Sorted view (state.ext_sort) — the same ordering _selected_item uses, so
    # the row the user acts on always matches the highlighted row.
    data = _subtab_view(state, sub)

    # `/search:` band (uniform slot, mirrors Vault): live `_` cursor while
    # typing, cursor-less once applied. Reserves one row above the filter bar.
    q = state.ext_search.get(sub, "")
    if state.ext_searching or q:
        cursor = "_" if state.ext_searching else ""
        safe_addnstr(stdscr, sub_y, 0, fit_cells(f" /search: {q}{cursor}", w - 1),
                     w - 1, CP_INFO() | curses.A_BOLD)
        sub_y += 1
        sub_h -= 1

    # Filter bar (mirrors the Vault title row): label + (filtered/total)
    # counts + sort/search/marked chips. Always visible, like Vault's.
    total = len(state.ext_cache.get(sub, []) or [])
    label = dict(EXTENSION_SUB_TABS).get(sub, sub)
    bar_parts = [f" {label}  ({len(data)}/{total} items)" if q
                 else f" {label}  ({total} items)"]
    sort_label = subtab_sort_label(state, sub)
    if sort_label:
        bar_parts.append(f"sort={sort_label}")
    if q:
        bar_parts.append(f"search={q!r}")
    marks = state.ext_marked.get(sub) or set()
    if marks:
        bar_parts.append(f"marked={len(marks)}")
    safe_addnstr(stdscr, sub_y, 0, fit_cells("  ".join(bar_parts), w - 1),
                 w - 1, CP_TITLE())
    sub_y += 1
    sub_h -= 1

    # Uniform status columns (mirror Vault): the leftmost ■/□ prefix shows
    # the Space marks, `#` carries the row number, and every sub-tab but
    # market shares the `Ver Vault Proj Glob` block right after the name
    # column — Vault: ✓ stored in ~/.axt/vault / ─ not vault-managed;
    # Proj/Glob: ● active ○ inactive · unset (plugins) ─ n/a. Market skips
    # all four: no per-source version, and marketplaces are a global-only
    # registry (no vault/project/global scoping to show).
    if sub == "plugins":
        cols = [
            TableColumn("no", "#", 3),
            TableColumn("name", "Plugin", max(20, w - 77)),
            TableColumn("version", "Ver", 8),
            TableColumn("vault", "Vault", 5),
            TableColumn("proj", "Proj", 4),
            TableColumn("glob", "Glob", 4),
            TableColumn("upd", "Upd", 3),
            TableColumn("market", "Marketplace", 24),
        ]
        ctx = _scope_ctx(state, sub)
        enabled_g, enabled_p = ctx["glob"], ctx["proj"]

        rows = [{
            "no": str(i + 1),
            "name": p.name,
            "version": p.version or "—",
            "vault": _vault_cell(sub, p),
            "proj": _scope_cell(sub, p, "proj", ctx),
            "glob": _scope_cell(sub, p, "glob", ctx),
            "upd": _upd_cell(state, sub, p),
            "market": p.marketplace or "—",
        } for i, p in enumerate(data)]

    elif sub == "skills":
        ctx = _scope_ctx(state, sub)
        cols = [
            TableColumn("no", "#", 3),
            TableColumn("name", "Skill", max(20, w - 96)),
            TableColumn("ver", "Ver", 8),
            TableColumn("vault", "Vault", 5),
            TableColumn("proj", "Proj", 4),
            TableColumn("glob", "Glob", 4),
            TableColumn("upd", "Upd", 3),
            TableColumn("source", "Source", 9),
            TableColumn("type", "Type", 8),
            TableColumn("path", "Path", 30),
        ]
        rows = [{
            "no": str(i + 1),
            "name": s.name,
            "ver": s.version or "─",
            "vault": _vault_cell(sub, s),
            "proj": _scope_cell(sub, s, "proj", ctx),
            "glob": _scope_cell(sub, s, "glob", ctx),
            "upd": _upd_cell(state, sub, s),
            "source": s.source,
            "type": "symlink" if s.is_symlink else "dir",
            "path": (s.target or s.path)[:60],
        } for i, s in enumerate(data)]

    elif sub == "commands":
        ctx = _scope_ctx(state, sub)
        cols = [
            TableColumn("no", "#", 3),
            TableColumn("name", "Command", max(20, w - 97)),
            TableColumn("ver", "Ver", 8),
            TableColumn("vault", "Vault", 5),
            TableColumn("proj", "Proj", 4),
            TableColumn("glob", "Glob", 4),
            TableColumn("upd", "Upd", 3),
            TableColumn("source", "Source", 9),
            TableColumn("desc", "Description", 50),
        ]
        rows = [{
            "no": str(i + 1),
            "name": f"/{c.name}",
            "ver": c.version or "─",
            "vault": _vault_cell(sub, c),
            "proj": _scope_cell(sub, c, "proj", ctx),
            "glob": _scope_cell(sub, c, "glob", ctx),
            "upd": _upd_cell(state, sub, c),
            "source": c.source,
            "desc": (c.description or "")[:80],
        } for i, c in enumerate(data)]

    elif sub == "agents":
        ctx = _scope_ctx(state, sub)
        cols = [
            TableColumn("no", "#", 3),
            TableColumn("name", "Agent", max(20, w - 97)),
            TableColumn("ver", "Ver", 8),
            TableColumn("vault", "Vault", 5),
            TableColumn("proj", "Proj", 4),
            TableColumn("glob", "Glob", 4),
            TableColumn("upd", "Upd", 3),
            TableColumn("source", "Source", 9),
            TableColumn("desc", "Description", 50),
        ]
        rows = [{
            "no": str(i + 1),
            "name": a.name,
            "ver": a.version or "─",
            "vault": _vault_cell(sub, a),
            "proj": _scope_cell(sub, a, "proj", ctx),
            "glob": _scope_cell(sub, a, "glob", ctx),
            "upd": _upd_cell(state, sub, a),
            "source": a.source,
            "desc": (a.description or "")[:80],
        } for i, a in enumerate(data)]

    elif sub == "mcp":
        # MCP splits the two axes the file-backed sub-tabs collapse into one:
        # Proj/Glob mirror the *registration* scope (where the definition
        # lives — read-only; plugin/claude.ai/built-in live outside both), and
        # On carries the *activation* flag, which is always project-scoped
        # (`disabledMcpServers` / built-in opt-in `enabledMcpServers`).
        cols = [
            TableColumn("no", "#", 3),
            TableColumn("name", "Server", max(18, w - 108)),
            TableColumn("ver", "Ver", 8),
            TableColumn("vault", "Vault", 5),
            TableColumn("proj", "Proj", 4),
            TableColumn("glob", "Glob", 4),
            TableColumn("upd", "Upd", 3),
            TableColumn("on", "On", 3),
            TableColumn("scope", "Scope", 13),
            TableColumn("transport", "Transport", 10),
            TableColumn("detail", "Detail", 30),
        ]
        ctx = _scope_ctx(state, sub)
        rows = [{
            "no": str(i + 1),
            "name": s.name,
            "ver": getattr(s, "version", "") or "─",  # plugin-sourced servers only
            "vault": _vault_cell(sub, s),
            "proj": _scope_cell(sub, s, "proj", ctx),
            "glob": _scope_cell(sub, s, "glob", ctx),
            "upd": _upd_cell(state, sub, s),
            "on": "○" if s.disabled else "●",
            "scope": s.scope,
            "transport": s.transport,
            "detail": _mcp_detail_text(s)[:60],
        } for i, s in enumerate(data)]

    elif sub == "hooks":
        cols = [
            TableColumn("no", "#", 3),
            TableColumn("event", "Event", 22),
            TableColumn("ver", "Ver", 8),
            TableColumn("vault", "Vault", 5),
            TableColumn("proj", "Proj", 4),
            TableColumn("glob", "Glob", 4),
            TableColumn("upd", "Upd", 3),
            TableColumn("type", "Type", 10),
            TableColumn("source", "Source", 10),
            TableColumn("detail", "Detail", max(20, w - 107)),
        ]

        ctx = _scope_ctx(state, sub)
        rows = []
        for i, h in enumerate(data):
            proj_cell = _scope_cell(sub, h, "proj", ctx)
            glob_cell = _scope_cell(sub, h, "glob", ctx)
            rows.append({
                "no": str(i + 1),
                "event": h.event,
                "ver": h.version or "─",
                "vault": _vault_cell(sub, h),
                "proj": proj_cell,
                "glob": glob_cell,
                "upd": _upd_cell(state, sub, h),
                "type": h.type,
                "source": h.source,
                "detail": get_hook_detail(h)[:80],
            })

    elif sub == "market":
        cols = [
            TableColumn("no", "#", 3),
            TableColumn("name", "Marketplace", max(20, w - 78)),
            TableColumn("upd", "Upd", 3),
            TableColumn("kind", "Source", 10),
            TableColumn("loc", "Location", 30),
            TableColumn("updated", "Updated", 12),
        ]
        rows = [{
            "no": str(i + 1),
            "name": m.name,
            "upd": _upd_cell(state, sub, m),
            "kind": m.source.kind,
            "loc": m.install_location[:30],  # matches column width — longer values collided with "updated"
            "updated": m.last_updated[:10],
        } for i, m in enumerate(data)]
    else:
        return

    # Annotate the active sort column's header with ▲/▼ (mirrors Vault).
    cols = _mark_sorted_column(state, sub, cols)

    if sub == "plugins":
        field_fn = lambda p: _plugin_detail_fields(p, enabled_g, enabled_p)  # noqa: E731
    else:
        field_fn = _SUBTAB_DETAIL_FIELD_FNS[sub]
    marks = state.ext_marked.get(sub) or set()
    checked = {i for i, item in enumerate(data) if _item_key(sub, item) in marks}
    _render_list_with_detail(stdscr, state, sub_y, sub_h, w, sub, cols, rows, data, field_fn,
                             checked=checked)


def _cycle_sub_tab(state: TuiState, tab_key: str, direction: int) -> None:
    """Cycle the given main tab's sub-tabs. No-op for tabs without a bar."""
    sub_tabs = SUB_TABS_BY_TAB.get(tab_key)
    attr = _SUB_TAB_ATTR.get(tab_key)
    if not sub_tabs or not attr:
        return
    cur = getattr(state, attr)
    i = next((idx for idx, (k, _) in enumerate(sub_tabs) if k == cur), 0)
    setattr(state, attr, sub_tabs[(i + direction) % len(sub_tabs)][0])


def tab_has_sub_tab(tab_key: str) -> bool:
    """True if the tab owns a sub-tab bar (Extensions, Context).
    Drives whether ↓ from mainTab should land on the subTab layer."""
    return tab_key in SUB_TABS_BY_TAB


def tab_has_focusable_content(state: TuiState, tab_key: str) -> bool:
    """True if the tab body has selectable rows / scrollable content.

    Extensions: always focusable (sub-tabs delegate to lists).
    Context: list of context sources.
    Usage: focusable while there is loaded data to scroll. During
    loading or the empty-this-month state the body is one line, so
    descending into `content` would have nothing to do.
    """
    if tab_key == "extensions":
        return True
    if tab_key == "context":
        return True
    if tab_key == "usage":
        if state.usage_loading:
            return False
        return bool(state.usage_entries)
    return False


def sub_tab_has_focusable_content(state: TuiState, tab_key: str, sub_key: str) -> bool:
    """True if the active sub-tab body has selectable rows.

    Mirrors tab_has_focusable_content for the second focus layer: when the
    sub-tab body is empty (e.g. "No plugins installed yet." or zero vault
    items), descending from subTab into `content` would silently swallow
    focus, so the loop keeps focus on subTab instead.
    """
    if tab_key == "context":
        if sub_key == "project":
            _ensure_project_loaded(state)
            return bool(state.project_items)
        # "sources": focusable when the analysis yielded any category rows.
        return bool(_context_rows(state.context_analysis)) if state.context_analysis else False
    # Extensions.
    if sub_key == "vault":
        return len(state.vault_items) > 0
    return bool(state.ext_cache.get(sub_key))


def _at_top_of_content(state: TuiState, tab_key: str) -> bool:
    """True when the active tab's selection is at row 0 — used to decide
    whether ↑ should climb out of the content into the focus row above."""
    if tab_key == "extensions":
        if state.ext_sub_tab == "vault":
            return state.vault_selected == 0
        return state.ext_selected.get(state.ext_sub_tab, 0) == 0
    if tab_key == "context":
        if state.context_sub_tab == "project":
            return state.project_selected == 0
        return state.context_selected == 0
    if tab_key == "usage":
        return state.usage_scroll == 0
    # Other tabs without a selection — treat as top.
    return True


def handle_extensions_input(state: TuiState, key: int) -> Optional[str]:
    """Handles Extensions sub-tab switching AND delegates to active sub-tab.

    Sub-tab cycling keys (content layer):
      [           previous sub-tab
      ]           next sub-tab
    (Tab / Shift+Tab are reserved: Tab toggles detail focus inside Vault;
     the canonical sub-tab navigation lives at the subTab focus layer via
     ←/→ — see _handle_sub_tab_key in axt/tui/loop.py.)
    """
    # Vault `/`-search mode swallows every printable key so the user can
    # type names containing reserved letters (`r`, `[`, `]`, …). Delegate
    # before applying the sub-tab-level shortcuts.
    if state.ext_sub_tab == "vault" and state.vault_searching:
        return handle_vault_input(state, key)

    # Non-vault `/`-search mode swallows every printable key too (mirrors
    # vault), so reserved letters (r, s, j, k, [, ]) go into the query.
    if state.ext_sub_tab != "vault" and state.ext_searching:
        return _handle_ext_search_keys(state, key)

    if key == ord("["):
        _blur_ext_detail(state)
        _cycle_sub_tab(state, "extensions", -1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == ord("]"):
        _blur_ext_detail(state)
        _cycle_sub_tab(state, "extensions", 1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == ord("r"):
        # Refresh the active sub-tab's cache. On non-vault sub-tabs also
        # force a fresh async update check (the Upd column's cache would
        # otherwise persist until UPDATE_STATUS_TTL_S).
        state.ext_cache.pop(state.ext_sub_tab, None)
        if state.ext_sub_tab == "vault":
            state.vault_items = []
            state.refresh_token = 0
            return "Refreshed"
        _kick_update_check(state, force=True)
        return "Refreshed — re-checking updates…"

    sub = state.ext_sub_tab
    if sub == "vault":
        return handle_vault_input(state, key)

    # `/` starts search-input mode (mirrors Vault). The applied query filters
    # _subtab_view; Esc clears it (see below). Blurring the detail panel keeps
    # the filtered list visible while typing.
    if key == ord("/"):
        _blur_ext_detail(state)
        state.ext_searching = True
        state.ext_search[sub] = ""
        state.ext_selected[sub] = 0
        return "/: type to filter, Enter to apply, Esc to cancel"

    # Sort keys (mirror Vault): `s` moves to the next column, `S` flips that
    # column between ▲ and ▼. Handled here, ahead of detail-focus and list
    # nav, so they work regardless of focus. (Market's `S`=sync moved to `y`.)
    if key == ord("s") and sub in _SORT_COLUMNS:
        _cycle_sort_column(state, sub)
        return f"Sort: {subtab_sort_label(state, sub)}"
    if key == ord("S") and sub in _SORT_COLUMNS:
        _toggle_sort_direction(state, sub)
        return f"Sort: {subtab_sort_label(state, sub)}"

    # Space = select: toggle the focused item's bulk mark, then advance focus
    # one row (clamped) so repeated Space marks consecutive items instead of
    # re-toggling the same one (mirrors Vault). Marks accumulate across
    # sort/search changes; the next p/g applies to the whole marked set, and
    # Esc clears the marks.
    if key == ord(" "):
        item = _selected_item(state, sub)
        if item is None:
            return None
        marks = state.ext_marked.setdefault(sub, set())
        item_key = _item_key(sub, item)
        label = _item_label(item)
        if item_key in marks:
            marks.discard(item_key)
            msg = f"Unmarked {label!r} ({len(marks)} marked)"
        else:
            marks.add(item_key)
            msg = f"Marked {label!r} for bulk toggle ({len(marks)} marked)"
        n = len(_subtab_view(state, sub))
        state.ext_selected[sub] = min(n - 1, state.ext_selected.get(sub, 0) + 1)
        return msg

    # Tab toggles focus into the bottom detail panel (sub-tabs that have one).
    if key in (ord("\t"), curses.KEY_BTAB) and sub in _SUBTABS_WITH_DETAIL:
        if not state.ext_cache.get(sub):
            return None
        state.ext_detail_focused = not state.ext_detail_focused
        state.ext_detail_scroll = 0
        return "Detail focused — j/k scroll, Esc/Tab to blur" if state.ext_detail_focused else None

    # While the detail panel is focused, navigation keys scroll it instead of
    # moving the list selection. Esc blurs back to the list (mirrors Vault).
    # Action keys (e/d/p/o/…) still fall through.
    if state.ext_detail_focused and sub in _SUBTABS_WITH_DETAIL:
        if key == KEY_ESC:
            _blur_ext_detail(state)
            return None
        if key in (ord("j"), curses.KEY_DOWN):
            state.ext_detail_scroll += 1
            return None
        if key in (ord("k"), curses.KEY_UP):
            state.ext_detail_scroll = max(0, state.ext_detail_scroll - 1)
            return None
        if key == curses.KEY_NPAGE:
            state.ext_detail_scroll += 10
            return None
        if key == curses.KEY_PPAGE:
            state.ext_detail_scroll = max(0, state.ext_detail_scroll - 10)
            return None
        return _handle_subtab_action(state, sub, key)

    # Esc peels back one UI state at a time (mirrors Vault): marks first,
    # then an applied search filter, and only then does the next Esc climb a
    # focus layer (loop.py routes it here via the climb exception while
    # marks or a query are active).
    if key == KEY_ESC and state.ext_marked.get(sub):
        state.ext_marked[sub].clear()
        return "Cleared marks"
    if key == KEY_ESC and state.ext_search.get(sub):
        state.ext_search.pop(sub, None)
        state.ext_selected[sub] = 0
        return "Search cleared"

    # Simple list navigation for the other sub-tabs. Clamp against the
    # displayed (sorted + search-filtered) view so the selection index stays
    # aligned with the row _selected_item / the renderer resolve.
    data = _subtab_view(state, sub)
    n = len(data)
    sel = state.ext_selected.get(sub, 0)
    if key in (ord("j"), curses.KEY_DOWN):
        state.ext_selected[sub] = min(n - 1, sel + 1) if n else 0
        state.ext_detail_scroll = 0  # new selection → detail back to top
        return None
    elif key in (ord("k"), curses.KEY_UP):
        state.ext_selected[sub] = max(0, sel - 1)
        state.ext_detail_scroll = 0
        return None
    elif key == curses.KEY_NPAGE:
        state.ext_selected[sub] = min(n - 1, sel + 10) if n else 0
        state.ext_detail_scroll = 0
        return None
    elif key == curses.KEY_PPAGE:
        state.ext_selected[sub] = max(0, sel - 10)
        state.ext_detail_scroll = 0
        return None
    return _handle_subtab_action(state, sub, key)


def _selected_item(state: TuiState, sub: str) -> Any:
    """Return the currently selected item in the given Extensions sub-tab.

    Uses the same sorted view as the renderer so the selection index resolves
    to the row actually highlighted on screen."""
    data = _subtab_view(state, sub)
    sel = state.ext_selected.get(sub, 0)
    if 0 <= sel < len(data):
        return data[sel]
    return None


def _item_terminal_dir(sub: str, item: Any) -> Optional[str]:
    """Directory a new terminal should open in for an Extensions sub-tab item.

    Skills resolve symlinks to the real storage path; file-backed items
    (commands/agents/hooks) open at the file's parent directory. MCP servers
    map scope → plugin install dir / ~/.claude / project cwd."""
    if item is None:
        return None
    if sub == "skills":
        try:
            return str(Path(item.path).resolve())
        except OSError:
            return item.path
    if sub in ("commands", "agents", "hooks"):
        sp = getattr(item, "source_path", "") or ""
        if not sp:
            return None
        p = Path(sp)
        return str(p if p.is_dir() else p.parent)
    if sub == "plugins":
        return item.install_path
    if sub == "market":
        return item.install_location
    if sub == "mcp":
        if item.scope == "plugin" and item.plugin_id:
            for p in list_installed_plugins(PATHS.installed_plugins):
                if p.id == item.plugin_id:
                    return p.install_path
            return None
        if item.scope == "user":
            return str(PATHS.claude_dir)
        return str(Path.cwd())  # project / project-file scopes
    return None


def _open_terminal_for_dir(state: TuiState, directory: Optional[str]) -> Optional[str]:
    """Shared `o`-key body: validate `directory`, pick a cmux mode when
    running inside cmux, spawn the terminal, and return the toast message."""
    if not directory:
        return "No directory for this item"
    if not os.path.isdir(directory):
        return f"Path not found: {directory}"
    cb = state.stdscr_callbacks
    stdscr = cb.get("stdscr") if cb else None
    cmux_mode: Optional[str] = None
    if os.environ.get("CMUX_WORKSPACE_ID") and stdscr is not None:
        cmux_mode = cmux_open_mode_modal(stdscr)
        if cmux_mode is None:
            return "Cancelled"
    ok, info = spawn_terminal_at(directory, cmux_mode=cmux_mode)
    return info if ok else f"Terminal open failed: {info}"


# ── Sub-tab action handlers ──────────────────────────────────────────────────
# Uniform signature (state, stdscr, sub, key) → status message. Wired through
# SUBTAB_KEYMAP below; never called directly by the input loop.


def _act_open_terminal(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    item = _selected_item(state, sub)
    if item is None:
        return None
    return _open_terminal_for_dir(state, _item_terminal_dir(sub, item))


# ── Uniform project/global activation layer ─────────────────────────────────
# Every non-vault sub-tab shares the Vault interaction grammar: Proj/Glob
# status columns, `p`/`g` scope toggles, and Space multi-select marks that
# turn the next p/g into a bulk toggle. What "active" means per sub-tab:
#   plugins             settings `enabledPlugins` flag (global + project files)
#   skills/commands/    symlink present in the scope directory
#     agents              (~/.claude/<sub>/ vs <cwd>/.claude/<sub>/)
#   mcp                 activation is project-only (`disabledMcpServers` in
#                         ~/.claude.json) → shown in the On column, toggled by
#                         p; Proj/Glob are read-only registration markers
#   hooks               own settings file (user file = global, project/local
#                         files = project); rule moved hooks ↔ disabledHooks
#   market              global-only registry — no per-scope toggle


def _item_key(sub: str, item: Any) -> str:
    """Stable identity for Space marks, resilient to re-sorting/refreshes."""
    if sub == "plugins":
        return item.id
    if sub == "skills":
        return item.path
    if sub in ("commands", "agents"):
        return item.source_path
    if sub == "mcp":
        return f"{item.scope}:{item.name}"
    if sub == "hooks":
        return "|".join((
            item.source_path, item.event,
            getattr(item, "matcher", "") or "*", item.type,
            getattr(item, "command", "") or "", getattr(item, "url", "") or "",
            getattr(item, "prompt", "") or "",
        ))
    return getattr(item, "name", str(item))


def _item_label(item: Any) -> str:
    return getattr(item, "name", None) or getattr(item, "event", "?")


def _file_scope_dir(sub: str, scope: str) -> Path:
    """Directory holding scope links for a file-backed sub-tab
    (skills/commands/agents): global → ~/.claude/<sub>, project → .claude/<sub>."""
    if sub == "skills":
        return Path(PATHS.skills) if scope == "global" else Path.cwd() / ".claude" / "skills"
    return (Path(PATHS.claude_dir) / sub) if scope == "global" else Path.cwd() / ".claude" / sub


def _item_disk_path(sub: str, item: Any) -> str:
    return item.path if sub == "skills" else item.source_path


def _item_base_name(sub: str, item: Any) -> str:
    """Scope-independent identity: dir name for skills, stem for .md files.
    (Display names of plugin-sourced items carry a `plugin:` prefix, so the
    on-disk name is the cross-scope match key.)"""
    p = Path(_item_disk_path(sub, item))
    return p.name if sub == "skills" else p.stem


def _scope_link_names(state: TuiState, sub: str, scope: str) -> set[str]:
    """Base names present in the given scope for a file-backed sub-tab."""
    src = "user" if scope == "global" else "project"
    return {
        _item_base_name(sub, i)
        for i in state.ext_cache.get(sub, [])
        if i.source == src
    }


def _scope_ctx(state: TuiState, sub: str) -> dict:
    """Precomputed lookups backing a sub-tab's Proj / Glob cells.

    Built once per render (and once per sort) so the settings files behind the
    plugin columns are read a single time instead of once per row."""
    if sub == "plugins":
        return {"proj": read_enabled_plugins(project_settings_path()),
                "glob": read_enabled_plugins(PATHS.settings)}
    if sub in ("skills", "commands", "agents"):
        return {"proj": _scope_link_names(state, sub, "project"),
                "glob": _scope_link_names(state, sub, "global")}
    return {}


def _scope_cell(sub: str, item: Any, scope: str, ctx: dict) -> str:
    """The Proj (`scope="proj"`) or Glob (`scope="glob"`) glyph for one row.

    Shared by the renderer and the column sort so the on-screen glyphs and the
    sort order can never disagree. `ctx` comes from `_scope_ctx`."""
    if sub == "plugins":
        v = ctx.get(scope, {}).get(item.id)
        return "●" if v is True else ("○" if v is False else "·")
    if sub in ("skills", "commands", "agents"):
        return "●" if _item_base_name(sub, item) in ctx.get(scope, set()) else "○"
    if sub == "mcp":
        # Registration scope, not activation — the On column carries that.
        if scope == "proj":
            return "●" if item.scope in ("project", "project-file") else "─"
        return "●" if item.scope == "user" else "─"
    if sub == "hooks":
        # A hook toggles only in the scope its settings file belongs to.
        own = _hook_scope(item)
        on = "○" if item.disabled else "●"
        return on if own == ("project" if scope == "proj" else "global") else "─"
    return "─"


def _mcp_detail_text(server: Any) -> str:
    """The MCP `Detail` cell's full text: the URL for remote transports, the
    resolved command line for stdio ones."""
    return server.url or " ".join([server.command, *server.args_list]).strip()


def _vault_cell(sub: str, item: Any) -> str:
    """`✓` when the row's content lives in vault storage (vault-managed),
    `─` otherwise — including the sub-tabs whose types the vault does not
    store (plugins/mcp/hooks/market).

    Compares against the resolved per-type vault SUBDIR, not the vault root:
    `~/.axt/vault/<sub>` may itself be a symlink to external storage, in
    which case fully-resolved item paths never contain the vault root but do
    land inside the subdir's target."""
    if sub not in ("skills", "commands", "agents"):
        return "─"
    try:
        p = Path(_item_disk_path(sub, item)).resolve()
        vault_sub = (Path(PATHS.vault) / sub).resolve()
    except OSError:
        return "─"
    return "✓" if p.is_relative_to(vault_sub) else "─"


def _upd_cell(state: TuiState, sub: str, item: Any) -> str:
    """`Upd` column marker for a non-vault sub-tab row.

      ↑  update available (tier-1, apply with `u`)
      ·  checked and up to date
      !  the check errored for this item (e.g. fetch failed)
      ─  not updatable here (mcp/hooks, plugin-sourced, manual/non-git, or
         absent from the registry — e.g. a project-scope skill)
      …  first check still running (no cached result yet)
    """
    target = _update_target_for(sub, item)
    if target is None:
        return "─"
    if state.update_statuses is None:
        return "…"
    if state.update_check_failed:
        # The whole sweep died. Reusing the per-item "check failed" glyph is
        # the point: an empty result set otherwise reads as "all up to date".
        return "!"
    st = state.update_statuses.get(target)
    if st is None:
        return "─"
    if st.updatable:
        return "↑"
    if st.error:
        return "!"
    return "─" if st.tier != 1 else "·"


def _toggle_plugin_scope(item: Any, scope: str) -> tuple[bool, str]:
    """Flip the plugin's enabled flag in project/global settings.

    An unset flag counts as enabled (installed plugins run by default), so
    the first toggle of an unset plugin disables it. The project toggle flips
    the *effective* value (project falls back to global), so `p` always
    visibly changes state."""
    path = PATHS.settings if scope == "global" else project_settings_path()
    gv = read_enabled_plugins(PATHS.settings).get(item.id)
    pv = read_enabled_plugins(project_settings_path()).get(item.id)
    if scope == "global":
        current = gv if gv is not None else True
    else:
        current = pv if pv is not None else (gv if gv is not None else True)
    try:
        set_plugin_enabled(path, item.id, not current)
    except OSError as exc:
        return False, f"Toggle failed: {exc}"
    return True, f"{'Disabled' if current else 'Enabled'} {item.id} ({scope})"


def _toggle_mcp_scope(item: Any, scope: str) -> tuple[bool, str]:
    if scope == "global":
        return False, "MCP servers toggle per project only — use p"
    want_disabled = not item.disabled
    try:
        set_mcp_disabled(item.name, disabled=want_disabled)
    except OSError as exc:
        return False, f"Toggle failed: {exc}"
    return True, f"{'Disabled' if want_disabled else 'Enabled'} MCP {item.name} (project)"


def _hook_scope(hook: Any) -> Optional[str]:
    """Which p/g scope owns this hook — its settings file decides."""
    if hook.source == "user":
        return "global"
    if hook.source in ("project", "local"):
        return "project"
    return None  # plugin — read-only


def _toggle_hook_scope(item: Any, scope: str) -> tuple[bool, str]:
    own = _hook_scope(item)
    if own is None:
        return False, "Plugin hooks are read-only (manage them in the plugin)"
    if own != scope:
        other = "g" if own == "global" else "p"
        return False, f"Hook lives in {item.source} settings — use {other}"
    want_disabled = not item.disabled
    try:
        moved = set_hook_disabled(item.source_path, item, disabled=want_disabled)
    except OSError as exc:
        return False, f"Toggle failed: {exc}"
    if not moved:
        return False, "Hook not found in its settings file"
    return True, f"{'Disabled' if want_disabled else 'Enabled'} hook {item.event} ({item.source})"


def _toggle_file_item_scope(state: TuiState, sub: str, item: Any, scope: str) -> tuple[bool, str]:
    """Link/unlink a skill dir or command/agent .md into the scope directory.

    Active in a scope = an entry with the same base name exists there. The
    toggle removes that entry when it is a symlink (real files/dirs are never
    deleted — that's `x`/rm territory) and otherwise symlinks this row's
    resolved path into the scope directory."""
    if not is_symlink_supported():
        return False, "Symlinks unsupported on this platform"
    src = "user" if scope == "global" else "project"
    base = _item_base_name(sub, item)
    existing = next(
        (i for i in state.ext_cache.get(sub, [])
         if i.source == src and _item_base_name(sub, i) == base),
        None,
    )
    if existing is not None:
        p = Path(_item_disk_path(sub, existing))
        if not p.is_symlink():
            return False, f"{base} is not a symlink in {scope} scope (cannot unlink)"
        try:
            p.unlink()
        except OSError as exc:
            return False, f"Unlink failed: {exc}"
        return True, f"Unlinked {base} ({scope})"
    disk = Path(_item_disk_path(sub, item))
    try:
        # Link the resolved target (no symlink chains), but keep the row's
        # on-disk entry name — resolving may change the basename.
        target = disk.resolve()
    except OSError:
        target = disk
    try:
        link_skill(_file_scope_dir(sub, scope), target, name=disk.name)
    except OSError as exc:
        return False, f"Link failed: {exc}"
    return True, f"Linked {base} ({scope})"


def _scope_toggle_one(state: TuiState, sub: str, item: Any, scope: str) -> tuple[bool, str]:
    """Apply one project/global activation toggle. Returns (changed, message)."""
    if sub == "plugins":
        return _toggle_plugin_scope(item, scope)
    if sub == "mcp":
        return _toggle_mcp_scope(item, scope)
    if sub == "hooks":
        return _toggle_hook_scope(item, scope)
    if sub in ("skills", "commands", "agents"):
        return _toggle_file_item_scope(state, sub, item, scope)
    return False, "Marketplaces are global-only — no project/global toggle"


def _act_scope_toggle(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    """p/g: toggle project/global activation — for the whole marked set when
    Space marks exist (bulk, confirmed), else for the selected row."""
    scope = "global" if key == ord("g") else "project"
    marks = state.ext_marked.get(sub) or set()
    if marks:
        items = [i for i in state.ext_cache.get(sub, []) if _item_key(sub, i) in marks]
        if not items:
            return "No marked item found (press r to refresh)"
        if stdscr is not None and not confirm_modal(
            stdscr,
            f"Toggle {scope} activation for {len(items)} marked item(s)?",
            title="Confirm bulk toggle",
        ):
            return "Cancelled"
        changed, skipped = 0, []
        for item in items:
            ok, msg = _scope_toggle_one(state, sub, item, scope)
            if ok:
                changed += 1
            else:
                skipped.append(msg)
        if not changed:
            return f"No marked item toggled — {skipped[0]}"
        marks.clear()
        _refresh_ext(state, sub)
        note = f" — {skipped[0]}" if skipped else ""
        return f"Applied {scope} toggle to {changed}/{len(items)} marked{note}"
    item = _selected_item(state, sub)
    if item is None:
        return None
    changed, msg = _scope_toggle_one(state, sub, item, scope)
    if changed:
        _refresh_ext(state, sub)
    return msg


def _act_market_scope_note(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    return "Marketplaces are global-only — no project/global toggle"


def _act_plugin_uninstall(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    plugin = _selected_item(state, "plugins")
    if plugin is None:
        return None
    if confirm_modal(stdscr, f"Uninstall plugin {plugin.id}?\nThis removes {plugin.install_path}."):
        import shutil
        try:
            shutil.rmtree(plugin.install_path, ignore_errors=True)
            remove_installed_plugin(PATHS.installed_plugins, plugin.id)
            remove_plugin_from_settings(PATHS.settings, plugin.id)
            _refresh_ext(state, "plugins")
            return f"Uninstalled {plugin.id}"
        except OSError as exc:
            return f"Uninstall failed: {exc}"
    return "Cancelled"


def _act_skill_link(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    if not is_symlink_supported():
        return "Symlinks unsupported on this platform"
    target = text_input_modal(stdscr,
                              "Path to skill directory to link",
                              title="Skill link",
                              initial="")
    if not target:
        return None
    try:
        link_skill(PATHS.skills, target.strip())
        _refresh_ext(state, "skills")
        return f"Linked {target}"
    except (OSError, ValueError) as exc:
        return f"Link failed: {exc}"


def _act_skill_unlink(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    skill = _selected_item(state, "skills")
    if skill is None:
        return None
    if not skill.is_symlink:
        return "Selected skill is not a symlink (cannot unlink)"
    if confirm_modal(stdscr, f"Unlink skill {skill.name}?", title="Confirm unlink"):
        try:
            unlink_skill(PATHS.skills, skill.name)
            _refresh_ext(state, "skills")
            return f"Unlinked {skill.name}"
        except (OSError, ValueError) as exc:
            return f"Unlink failed: {exc}"
    return "Cancelled"


# sub-tab key → vault item type, derived from the canonical pairs in core.
_SUB_ITEM_TYPE: dict[str, str] = dict(LINKABLE_TYPES)


def _act_import_to_vault(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    """i: move the selected item into vault storage, leaving a symlink behind."""
    item = _selected_item(state, sub)
    if item is None:
        return None
    if item.source == "plugin":
        return "Plugin-bundled items stay with their plugin (not importable)"
    if _vault_cell(sub, item) == "✓":
        return "Already in vault"
    disk = Path(_item_disk_path(sub, item))
    vitem = VaultItem(name=disk.name, type=_SUB_ITEM_TYPE[sub], path=str(disk), description="")
    try:
        import_to_vault(PATHS.claude_dir, PATHS.vault, vitem)
    except (OSError, ValueError, FileExistsError) as exc:
        return f"Import failed: {exc}"
    if item.source == "project" and (Path.cwd() / ".claude") in disk.parents:
        # import_to_vault left a symlink at the project path; record it in
        # .axt-profile.json so sync_project won't unlink it as an orphan.
        # (Project `.agents/` sources stay outside the profile — sync_project
        # only manages `.claude/<sub>/` links.)
        profile = read_profile(Path.cwd()) or empty_profile()
        profile = profile.with_added(sub, disk.name)
        write_profile(Path.cwd(), profile)
    _refresh_ext(state, sub)
    # The item now lives in the vault, so the Vault sub-tab's cache is stale.
    # Without this the imported item is invisible there until a manual `r`.
    state.vault_items = []
    state.refresh_token = 0
    return f"Imported {disk.name!r} to vault"


def _act_market_add(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    source_str = text_input_modal(
        stdscr,
        "Source (github:user/repo, git:url, dir:/path)",
        title="Marketplace add",
    )
    if not source_str:
        return None
    try:
        source = parse_marketplace_source(source_str.strip())
    except ValueError as exc:
        return f"Parse failed: {exc}"
    if source.kind == "github":
        default_name = source.repo.split("/")[-1] if source.repo else ""
    elif source.kind == "directory":
        default_name = (source.path or "").rstrip("/").split("/")[-1]
    else:
        default_name = "custom"
    name = text_input_modal(stdscr, "Local name for this marketplace",
                            title="Marketplace name",
                            initial=default_name)
    if not name:
        return None
    try:
        add_marketplace(PATHS.known_marketplaces, PATHS.marketplaces, name.strip(), source)
        state.ext_cache.pop("market", None)
        return f"Added {name.strip()}"
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        return f"Add failed: {exc}"


def _act_market_sync(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    m = _selected_item(state, "market")
    if m is None:
        return None
    try:
        result = sync_marketplace(PATHS.known_marketplaces, m.name)
        state.ext_cache.pop("market", None)
        _settle_update_status(state, "marketplace", m.name, result.after)
        return f"Synced {m.name}: {result.before} → {result.after}" if result.updated else f"{m.name} up to date"
    except (RuntimeError, KeyError) as exc:
        return f"Sync failed: {exc}"


def _act_market_remove(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    m = _selected_item(state, "market")
    if m is None:
        return None
    if confirm_modal(stdscr, f"Remove marketplace {m.name}?\nThis deletes {m.install_location}.",
                     title="Confirm remove"):
        try:
            remove_marketplace(PATHS.known_marketplaces, PATHS.marketplaces, m.name)
            state.ext_cache.pop("market", None)
            return f"Removed {m.name}"
        except KeyError as exc:
            return f"Remove failed: {exc}"
    return "Cancelled"


def _act_hook_preview(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    hook = _selected_item(state, "hooks")
    if hook is None:
        return None
    try:
        result = preview_hook(hook)
    except OSError as exc:
        return f"Preview failed: {exc}"
    lines = [
        f"Type:    {result.type}",
        f"Summary: {result.summary}",
        "",
    ]
    if result.exit_code is not None:
        lines.append(f"Exit:    {result.exit_code}")
    if result.output:
        lines += ["", "── stdout ──", result.output]
    if result.error:
        lines += ["", "── stderr ──", result.error]
    preview_modal(stdscr, "\n".join(lines),
                  title=f"Hook preview: {hook.event}", heading_prefix="──")
    return None


def _act_edit_source(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    item = _selected_item(state, sub)
    if item is None or not item.source_path:
        return None
    ok = open_in_editor(stdscr, item.source_path)
    return f"Opened {item.source_path}" if ok else "Editor failed"


_SUB_TO_UPDATE_TYPE = {
    "plugins": "plugin",
    "skills": "skill",
    "commands": "command",
    "agents": "agent",
    "market": "marketplace",
}


def _update_target_for(sub: str, item: Any) -> Optional[tuple[str, str]]:
    """(item_type, name) for the update registry, or None if not updatable here.
    Plugins key on `id` (name@marketplace); skills/commands/agents and
    marketplaces on `name`."""
    itype = _SUB_TO_UPDATE_TYPE.get(sub)
    if itype is None or item is None:
        return None
    name = getattr(item, "id", None) or getattr(item, "name", None)
    return (itype, name) if name else None


def _settle_update_status(state: Optional[TuiState], itype: str, name: str, version: str) -> None:
    """After a successful apply/sync, flip the item's `Upd` marker to
    up-to-date in place and re-persist the cache, so the column stays
    truthful without waiting for the next full background sweep."""
    if state is None or state.update_statuses is None:
        return
    key = (itype, name)
    old = state.update_statuses.get(key)
    tier = old.tier if old else 1
    state.update_statuses[key] = UpdateStatus(itype, name, tier, version, version,
                                              False, note="up to date")
    try:
        save_cached_update_statuses(list(state.update_statuses.values()),
                                    state.update_checked_at or _iso_now())
    except OSError:
        pass  # cache write is best-effort; in-memory state is already correct


def _act_update_marked(state: TuiState, stdscr: Any, sub: str,
                       marks: set[str]) -> Optional[str]:
    """`u` with Space marks: bulk check + apply for every marked item
    (confirmed), mirroring the p/g bulk-toggle path. One item's failure
    doesn't abort the rest; the status line carries the tally."""
    items = [i for i in state.ext_cache.get(sub, []) if _item_key(sub, i) in marks]
    if not items:
        return "No marked item found (press r to refresh)"
    targets: list[tuple[str, str]] = []
    not_updatable = 0
    for item in items:
        t = _update_target_for(sub, item)
        if t is None:
            not_updatable += 1
        else:
            targets.append(t)
    if not targets:
        return "No marked item is updatable here"
    if stdscr is not None and not confirm_modal(
            stdscr, f"Update {len(targets)} marked item(s)? (check + apply)",
            title="Confirm bulk update"):
        return "Cancelled"
    flash_status(state, f"Checking {len(targets)} marked item(s)…")
    types = sorted({t for t, _ in targets})
    try:
        statuses = {(s.item_type, s.name): s
                    for s in check_all_updates(types=types)}
    except Exception as exc:  # noqa: BLE001 — surface as status, never crash the TUI
        return f"Update check failed: {exc}"
    to_apply, uptodate = [], 0
    for t in targets:
        st = statuses.get(t)
        if st is not None and st.tier == 1 and st.updatable:
            to_apply.append(t)
        else:
            uptodate += 1
    updated, failed, first_err = 0, 0, ""
    # One apply_updates call per item (not one batch) so the status bar can
    # name the item currently updating — each git fetch/pull is slow enough
    # that a single "Updating N items…" reads as a freeze.
    for i, target in enumerate(to_apply, start=1):
        flash_status(state, f"Updating {target[1]} ({i}/{len(to_apply)})…")
        res = apply_updates([target])[0]
        if res.error:
            failed += 1
            first_err = first_err or f"{res.name}: {res.error}"
        elif res.updated:
            updated += 1
            _settle_update_status(state, res.item_type, res.name, res.after)
        else:
            uptodate += 1
    marks.clear()
    _refresh_ext(state, sub)
    parts = [f"{updated} updated", f"{uptodate} up to date"]
    if failed:
        parts.append(f"{failed} failed ({first_err})")
    if not_updatable:
        parts.append(f"{not_updatable} not updatable")
    return "Marked update: " + ", ".join(parts)


def _act_update(state: TuiState, stdscr: Any, sub: str, key: int) -> Optional[str]:
    # Space marks present → bulk update the whole marked set.
    marks = (state.ext_marked.get(sub) if state is not None else None) or set()
    if marks:
        return _act_update_marked(state, stdscr, sub, marks)
    item = _selected_item(state, sub)
    target = _update_target_for(sub, item)
    if target is None:
        return None
    itype, name = target
    flash_status(state, f"Checking {name}…")
    try:
        statuses = [s for s in check_all_updates(types=[itype]) if s.name == name]
    except Exception as exc:  # noqa: BLE001 — surface as status, never crash the TUI
        return f"Update check failed: {exc}"
    st = statuses[0] if statuses else None
    if st is None:
        return f"{name}: no update info"
    if st.tier != 1 or not st.updatable:
        return f"{name}: {st.error or st.note or 'up to date'}"
    flash_status(state, f"Updating {name}…")
    res = apply_updates([(itype, name)])[0]
    _refresh_ext(state, sub)
    if res.error:
        return f"Update failed: {res.error}"
    _settle_update_status(state, itype, name, res.after)
    return f"Updated {name}: {res.before} → {res.after}" if res.updated else f"{name} up to date"


# ── Sub-tab keymap: single source of truth for dispatch + hints + help ───────
# Each binding: key codes → handler, plus the status-bar hint fragment and the
# `?`-help line it advertises ("" = hidden). `needs_stdscr` bindings are
# no-ops when no curses screen is available (tests, headless) — this mirrors
# the `and stdscr` guards of the old if-chain exactly.
class SubtabBinding(NamedTuple):
    keys: tuple[int, ...]
    hint: str
    help: str
    needs_stdscr: bool
    handler: Callable[[TuiState, Any, str, int], Optional[str]]


_SUBTAB_COMMON: tuple[SubtabBinding, ...] = (
    SubtabBinding((ord("o"),), "o:term",
                  "o=open a new terminal at the item's directory",
                  False, _act_open_terminal),
)

SUBTAB_KEYMAP: dict[str, tuple[SubtabBinding, ...]] = {
    "plugins": (
        SubtabBinding((ord("p"),), "p:project",
                      "p=toggle enabled in project settings (marked items in bulk)",
                      False, _act_scope_toggle),
        SubtabBinding((ord("g"),), "g:global",
                      "g=toggle enabled in global settings (marked items in bulk)",
                      False, _act_scope_toggle),
        SubtabBinding((ord("x"),), "x:uninstall",
                      "x=uninstall (confirm)",
                      True, _act_plugin_uninstall),
        SubtabBinding((ord("u"),), "u:update", "u=update selected (check + apply; Space marks → bulk)", True, _act_update),
    ),
    "mcp": (
        SubtabBinding((ord("p"),), "p:on",
                      "p=toggle On for this project (disabledMcpServers)",
                      False, _act_scope_toggle),
        SubtabBinding((ord("g"),), "", "", False, _act_scope_toggle),
    ),
    "skills": (
        SubtabBinding((ord("p"),), "p:project",
                      "p=link/unlink into .claude/skills (project)",
                      False, _act_scope_toggle),
        SubtabBinding((ord("g"),), "g:global",
                      "g=link/unlink into ~/.claude/skills (global)",
                      False, _act_scope_toggle),
        SubtabBinding((ord("a"),), "a:link",
                      "a=link new path (input)",
                      True, _act_skill_link),
        SubtabBinding((ord("x"),), "x:unlink",
                      "x=unlink (confirm)",
                      True, _act_skill_unlink),
        SubtabBinding((ord("i"),), "i:import",
                      "i=import into vault (move + leave symlink)",
                      False, _act_import_to_vault),
        SubtabBinding((ord("u"),), "u:update", "u=update selected (check + apply; Space marks → bulk)", True, _act_update),
    ),
    "market": (
        SubtabBinding((ord("p"), ord("g")), "", "", False, _act_market_scope_note),
        SubtabBinding((ord("a"),), "a:add",
                      "a=add (source+name input)",
                      True, _act_market_add),
        SubtabBinding((ord("y"),), "y:sync",
                      "y=sync (selected)",
                      True, _act_market_sync),
        SubtabBinding((ord("x"),), "x:remove",
                      "x=remove (confirm)",
                      True, _act_market_remove),
        SubtabBinding((ord("u"),), "u:update", "u=update selected (check + apply; Space marks → bulk)", True, _act_update),
    ),
    "hooks": (
        SubtabBinding((ord("p"),), "p:project",
                      "p=toggle a project-scope hook (moves it within its settings file)",
                      False, _act_scope_toggle),
        SubtabBinding((ord("g"),), "g:global",
                      "g=toggle a user-scope (global) hook",
                      False, _act_scope_toggle),
        SubtabBinding((ord("v"),), "v:preview",
                      "v=preview hook execution (scrollable modal)",
                      True, _act_hook_preview),
    ),
    "commands": (
        SubtabBinding((ord("p"),), "p:project",
                      "p=link/unlink into .claude/commands (project)",
                      False, _act_scope_toggle),
        SubtabBinding((ord("g"),), "g:global",
                      "g=link/unlink into ~/.claude/commands (global)",
                      False, _act_scope_toggle),
        SubtabBinding((ord("e"),), "e:edit",
                      "e=open source file in $EDITOR",
                      True, _act_edit_source),
        SubtabBinding((ord("i"),), "i:import",
                      "i=import into vault (move + leave symlink)",
                      False, _act_import_to_vault),
        SubtabBinding((ord("u"),), "u:update", "u=update selected (check + apply; Space marks → bulk)", True, _act_update),
    ),
    "agents": (
        SubtabBinding((ord("p"),), "p:project",
                      "p=link/unlink into .claude/agents (project)",
                      False, _act_scope_toggle),
        SubtabBinding((ord("g"),), "g:global",
                      "g=link/unlink into ~/.claude/agents (global)",
                      False, _act_scope_toggle),
        SubtabBinding((ord("e"),), "e:edit",
                      "e=open source file in $EDITOR",
                      True, _act_edit_source),
        SubtabBinding((ord("i"),), "i:import",
                      "i=import into vault (move + leave symlink)",
                      False, _act_import_to_vault),
        SubtabBinding((ord("u"),), "u:update", "u=update selected (check + apply; Space marks → bulk)", True, _act_update),
    ),
}


def subtab_shortcuts(sub: str) -> str:
    """Status-bar action hints for a non-vault Extensions sub-tab, generated
    from SUBTAB_KEYMAP so the bar always matches the live bindings. The
    common `o:term` hint is omitted — the status line's fixed tail shows it."""
    parts = [b.hint for b in SUBTAB_KEYMAP.get(sub, ()) if b.hint]
    if sub in _SUBTABS_WITH_DETAIL:
        parts.append("Tab:detail")
    return "  ".join(parts)


_SUBTAB_HELP_LABELS: tuple[tuple[str, str], ...] = (
    ("plugins", "Plugins"),
    ("skills", "Skills"),
    ("mcp", "MCP"),
    ("market", "Marketplace"),
    ("hooks", "Hooks"),
    ("commands", "Commands"),
    ("agents", "Agents"),
)


def subtab_help_block() -> str:
    """Per-sub-tab key lines of the `?` help, generated from SUBTAB_KEYMAP.
    Continuation lines align under the first help entry (14-cell label)."""
    lines = []
    for sub, label in _SUBTAB_HELP_LABELS:
        helps = [b.help for b in SUBTAB_KEYMAP.get(sub, ()) if b.help]
        if not helps:
            continue
        prefix = f"  {label + ':':<14}"
        lines.append(prefix + helps[0])
        lines.extend(" " * len(prefix) + h for h in helps[1:])
    return "\n".join(lines)


def _handle_subtab_action(state: TuiState, sub: str, key: int) -> Optional[str]:
    """Table-driven sub-tab actions (see SUBTAB_KEYMAP). Returns status message.

    stdscr-bound actions (confirm_modal, text_input_modal, preview_modal,
    open_in_editor) get the curses screen through state.stdscr_callbacks;
    handlers never receive it directly from the loop so they stay testable."""
    cb = state.stdscr_callbacks
    if not cb:
        return None  # No interactive context available (e.g. tests)
    stdscr = cb.get("stdscr")
    for binding in _SUBTAB_COMMON + SUBTAB_KEYMAP.get(sub, ()):
        if key in binding.keys:
            if binding.needs_stdscr and not stdscr:
                return None
            return binding.handler(state, stdscr, sub, key)
    return None


# Dispatch tables: tab key → renderer / handler. Keep in sync with MAIN_TABS.
TAB_RENDERERS: dict[str, Callable[..., None]] = {
    "extensions": render_extensions_tab,
    "context":    render_context_tab,
    "usage":      render_usage_tab,
}

TAB_HANDLERS: dict[str, Callable[..., Optional[str]]] = {
    "extensions": handle_extensions_input,
    "context":    handle_context_input,
    "usage":      handle_usage_input,
}

