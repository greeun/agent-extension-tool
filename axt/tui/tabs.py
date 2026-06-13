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
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# Widget primitives — bring in everything from the TUI widgets layer.
from axt.tui.widgets import *  # noqa: F401,F403
from axt.tui.widgets import (  # noqa: F401 — wildcard skips `_`-prefixed names
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
    _iso_now,
    _project_name_from_path,
    _safe_listdir,
    _safe_read_text,
    _today_in_tz,
    _ts_ms,
    _type_to_dir,
    _unified_to_claude,
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
    # Monotonic timestamp when `status` was last set. The main loop clears
    # `status` after STATUS_TIMEOUT_S so the shortcut hints come back.
    status_set_at: Optional[float] = None
    show_help: bool = False

    # Vault-specific state.
    vault_items: list[VaultItem] = field(default_factory=list)
    vault_selected: int = 0
    vault_filter: str = "all"        # "all" | "skill" | "command" | "agent" | "plugin"
    vault_sort: str = "name"         # "name" | "type" | "added" | "updated" | "project" | "global"
    vault_search: str = ""
    vault_searching: bool = False    # True while user is typing in the `/` prompt
    vault_pending_project: set[str] = field(default_factory=set)   # item names toggled but not applied
    vault_pending_global: set[str] = field(default_factory=set)
    vault_scan_mode: str = "default"  # "default" (profile + symlinks) | "full" (+ plugin settings)
    vault_usage_index: dict[str, Any] = field(default_factory=dict)  # type:name → ExtensionUsage
    vault_detail_focused: bool = False  # Enter → focus detail panel, Esc → blur back
    vault_detail_scroll: int = 0

    # Extensions sub-tab state.
    ext_sub_tab: str = "vault"                     # one of EXTENSION_SUB_TABS keys
    ext_cache: dict[str, Any] = field(default_factory=dict)
    ext_selected: dict[str, int] = field(default_factory=dict)
    # Active sort key per non-vault sub-tab (mirrors `vault_sort`). Empty →
    # the first entry of that sub-tab's `_SUBTAB_SORT_SPECS` is the default.
    ext_sort: dict[str, str] = field(default_factory=dict)
    ext_detail_focused: bool = False  # Tab → focus the bottom detail panel (plugins/mcp/hooks)
    ext_detail_scroll: int = 0

    # Usage data caches (None = not loaded yet).
    usage_entries: Optional[list] = None
    usage_config: Optional[Any] = None
    # Async-load state for the Usage tab. A background thread fills
    # `usage_entries` / `usage_config`; the main loop polls while
    # `usage_loading` is True so the next frame picks up the result.
    usage_loading: bool = False
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

    # Context tab.
    context_analysis: Optional[Any] = None
    context_selected: int = 0
    # Active Context sub-tab: "sources" (live context-window breakdown) or
    # "project" (per-project context files). Rate limits render above both
    # sub-tabs as a persistent strip. ←/→ at the subTab focus layer or [/] in
    # the body cycle between them — mirrors the Extensions sub-tab model.
    context_sub_tab: str = "sources"
    # Scroll offset for the shared bottom detail panel (mirrors the active
    # sub-tab's selected row). PgUp/PgDn scroll it; reset on selection move.
    context_detail_scroll: int = 0

    # Project tab.
    project_items: Optional[list] = None
    project_selected: int = 0
    project_scroll: int = 0

    # Bridge between handler functions and curses-bound widgets. The handlers
    # don't receive stdscr (so they remain unit-testable), so we stash a dict
    # the main loop populates. Tests leave it None → modal/editor actions
    # become no-ops, which is the desired test behavior.
    stdscr_callbacks: Optional[dict] = None


_VAULT_FILTERS = ("all", "skill", "command", "agent", "plugin")
# Cycle order follows the table column layout (Name → Type → Proj → Glob →
# Used), then the two column-less timestamp sorts last.
_VAULT_SORTS = ("name", "type", "project", "global", "used", "added", "updated")

# Active sort key → (table column it annotates, direction glyph ▲ asc / ▼ desc).
# Lets the Vault table header show which column the list is sorted by. The two
# timestamp sorts ("added"/"updated") have no dedicated column, so they mark
# nothing here — the title bar's `sort=` text still names them.
_VAULT_SORT_MARK = {
    "name": ("name", "▲"),
    "type": ("type", "▲"),
    "project": ("project", "▲"),
    "global": ("global", "▲"),
    "used": ("used", "▼"),
}

# Seconds after which `state.status` auto-clears so shortcut hints reappear.
STATUS_TIMEOUT_S: float = 5.0


def set_status(state: TuiState, msg: str) -> None:
    """Set the bottom-bar status message and start its auto-clear timer.

    Pass ``""`` to clear immediately. The main loop polls and clears the
    status after :data:`STATUS_TIMEOUT_S` seconds so the shortcut hints
    become visible again on narrow terminals.
    """
    state.status = msg
    state.status_set_at = time.monotonic() if msg else None


def _invalidate_context(state: TuiState) -> None:
    """Mark Context analysis stale so the next Context/Usage paint re-runs
    ``analyze_context()``. Call from any branch that mutates filesystem
    state observed by the analyzer: plugin enable/disable/uninstall, skill
    link/unlink, vault link/unlink/import/migrate/sync, marketplace
    add/remove. Pure cache invalidation — the re-analysis itself happens
    lazily inside ``_ensure_context_loaded`` / ``_kick_usage_reload``.
    """
    state.context_analysis = None


def _vault_load(state: TuiState) -> None:
    """Refresh vault items from disk into state. Cheap — just reads metadata."""
    plugins = list_installed_plugins(PATHS.installed_plugins)
    plugin_refs = [
        PluginRef(
            id=p.id, name=p.name, description=p.description or "",
            install_path=p.install_path, version=p.version or "",
        )
        for p in plugins
    ]
    state.vault_items = list_vault_items_with_project_state(
        PATHS.vault,
        Path.cwd(),
        installed_plugins=plugin_refs,
        global_dir=PATHS.claude_dir,
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
#   - Cache is best-effort. There is NO automatic TTL — the file is read on
#     vault-tab entry and trusted as-is.
#   - The user explicitly refreshes by pressing `f` in the Vault tab, which
#     also toggles the scan mode (default <-> full) before re-scanning.
#   - Staleness is not surfaced as a relative timestamp; the title bar only
#     shows the current scan mode and the populated-row count
#     (e.g. ``scan=default(12/40)``).
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
def _load_scan_cache() -> tuple[dict[str, ExtensionUsage], str]:
    """Return (index, mode). Empty index + 'default' mode when no cache yet."""
    data = read_json(_scan_cache_path(), fallback={})
    if not isinstance(data, dict):
        return {}, "default"
    entries = data.get("entries", {})
    if not isinstance(entries, dict):
        return {}, "default"
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
    return index, str(data.get("mode", "default"))


def _vault_scan(state: TuiState) -> None:
    """Cross-project scan: walk ~/.claude/projects/* to count usage per item.
    Slower than refresh — only call on explicit user request (`f` key).
    Writes the result to disk so it survives axt restarts.
    """
    state.vault_usage_index = scan_project_usage(
        PATHS.projects, PATHS.vault, mode=state.vault_scan_mode,
    )
    _save_scan_cache(state.vault_usage_index, state.vault_scan_mode)


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
        if not item or item.type == "plugin":
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
        if not item or item.type == "plugin":
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


def _vault_unlink_from_all(state: TuiState, item: VaultItem) -> str:
    """Unlink `item` from EVERY project that references it in the scan index.

    The heavier sibling of the Space toggle, which only touches the current
    project. Project list comes from `state.vault_usage_index` (populated by
    `f`). When a stdscr is available a confirm modal lists the affected
    projects; headless callers (tests) skip straight to applying. Each project
    has its symlink removed and its `.axt-profile.json` entry dropped, and the
    in-memory + on-disk scan index is kept in sync so the `Used` column reverts.
    """
    if item.type == "plugin":
        return "Plugins use enabledPlugins, not symlinks — nothing to unlink."
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


def _vault_filtered(state: TuiState) -> list[VaultItem]:
    items = state.vault_items
    if state.vault_filter != "all":
        items = [i for i in items if i.type == state.vault_filter]
    if state.vault_search:
        q = state.vault_search.lower()
        items = [i for i in items if q in i.name.lower()]
    # Sort.
    if state.vault_sort == "name":
        items = sorted(items, key=lambda i: i.name)
    elif state.vault_sort == "type":
        items = sorted(items, key=lambda i: (i.type, i.name))
    elif state.vault_sort == "added":
        items = sorted(items, key=lambda i: i.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    elif state.vault_sort == "updated":
        items = sorted(items, key=lambda i: i.updated_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    elif state.vault_sort == "project":
        items = sorted(items, key=lambda i: (not i.is_linked, i.name))
    elif state.vault_sort == "global":
        items = sorted(items, key=lambda i: (not i.is_global_linked, i.name))
    elif state.vault_sort == "used":
        # Most-used first (descending). Items with no scan data tie at 0.
        def _used_count(it: VaultItem) -> int:
            entry = state.vault_usage_index.get(f"{it.type}:{it.name}")
            return len(entry.projects) if entry else 0
        items = sorted(items, key=lambda i: (-_used_count(i), i.name))
    return items


def _fmt_date(d: Optional[datetime]) -> str:
    if not d:
        return "─"
    return d.strftime("%y-%m-%d %H:%M")


def _vault_pending_indicator(state: TuiState, item: VaultItem) -> tuple[str, str]:
    """Return the (project, global) cell text reflecting pending toggles.

    Naming differs by item type:
      • skill / command / agent → symlinks (`linked` / `—`)
      • plugin                  → `enabledPlugins` settings flag (`enabled` / `off`)
    The single-glyph cells (●/○) work for either, but the DetailPanel and the
    cell suffix make the distinction explicit so users don't confuse the two
    activation mechanisms.
    """
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
            cached_index, cached_mode = _load_scan_cache()
            if cached_index:
                state.vault_usage_index = cached_index
                state.vault_scan_mode = cached_mode
        state.refresh_token = 1

    # Title row with all the live mode bits.
    pending = len(state.vault_pending_project) + len(state.vault_pending_global)
    scan_label = (
        f"scan={state.vault_scan_mode}({format_scan_summary(state.vault_usage_index, style='title')})"
        if state.vault_usage_index else f"scan={state.vault_scan_mode}(empty)"
    )
    title_parts = [
        f" Vault  ({len(state.vault_items)} items)",
        f"filter={state.vault_filter}",
        f"sort={state.vault_sort}",
        scan_label,
    ]
    if state.vault_search:
        title_parts.append(f"search={state.vault_search!r}")
    if pending:
        title_parts.append(f"pending={pending}")
    # Draw the full-width title/status row (+ the /search prompt when a filter
    # is active) and take the body rect below it. render_title_bar uses
    # CP_TITLE (the accent tier), so no full-width rule appears under the row on
    # light. The trailing cursor (`_`) shows only while capturing input.
    search = None
    if state.vault_searching or state.vault_search:
        cursor = "_" if state.vault_searching else ""
        search = f" /search: {state.vault_search}{cursor}"
    table_y_top, table_h_full = render_title_bar(
        stdscr, y0, h, w, "  ".join(title_parts), search=search)

    filtered = _vault_filtered(state)
    if not filtered:
        safe_addnstr(stdscr, y0 + 2, 2, "Vault is empty or no items match the current filter.", w - 4, CP_DIM())
        safe_addnstr(stdscr, y0 + 4, 2, "Press `m` to migrate global extensions, or `F` to change filter.", w - 4, CP_DIM())
        return

    state.vault_selected = max(0, min(state.vault_selected, len(filtered) - 1))

    # ── Layout: detail panel pinned to the bottom of the list, at every width.
    # Unified with the other Extensions sub-tabs (see _render_list_with_detail)
    # so every sub-tab reads the same way. Earlier builds switched to a
    # right-side panel on wide terminals (w >= 100); that split was dropped.
    # The split uses the body rect (table_y_top / table_h_full) returned by
    # render_title_bar above — no per-renderer reserved-row arithmetic, so the
    # region always fills down to the last body row.
    detail_h = max(8, min(16, int(h * 0.35)))
    # Never let the panel eat the entire list; reserve at least 3 list rows.
    detail_h = min(detail_h, max(1, table_h_full - 3))
    table_w = w
    table_h = max(0, table_h_full - detail_h)
    detail_x = 0
    detail_w = w
    detail_y = table_y_top + table_h

    # Columns: # / Name / Ver / Type / Vault / Project / Global / Used in.
    # "Vault" semantics:  ✓ = item is in ~/.axt/vault/  ;  global = only in ~/.claude/{type}s/
    # "Project" / "Global" show the *intended* state after applying pending toggles.
    no_w = max(3, len(str(len(filtered))) + 1)
    used_w = 6  # "Used" header + " N proj" data ≤ 6
    proj_w = 5  # "Proj" header (4) + "● *" data (3) ≤ 5
    glob_w = 5  # "Glob"
    type_w = 6  # "Type"
    vault_w = 6  # "Vault" header (5) + "glob*"/"proj*" data (5) ≤ 6
    ver_w = 8   # "Ver" header + "1.2.3" data ≤ 8
    # _draw_cell renders each column at `col.width + 2` cells (per-column
    # gap). With 8 columns + 4-cell prefix the gap cost is 4 + 2*8 = 20. We
    # subtract a few more cells of safety so wrap can't eat the last column.
    cols_fixed = no_w + ver_w + type_w + vault_w + proj_w + glob_w + used_w
    name_w = max(10, table_w - cols_fixed - (4 + 2 * 8) - 4)
    # Append a direction arrow to the header of the column the list is sorted by
    # (each fixed column has +2 cells of slack, so the glyph never shifts data).
    mark_col, mark_glyph = _VAULT_SORT_MARK.get(state.vault_sort, (None, ""))

    def _lbl(key: str, text: str) -> str:
        return f"{text} {mark_glyph}" if key == mark_col else text

    columns = [
        TableColumn("no", "#", no_w),
        TableColumn("name", _lbl("name", "Name"), name_w),
        TableColumn("ver", "Ver", ver_w),
        TableColumn("type", _lbl("type", "Type"), type_w),
        TableColumn("vault", "Vault", vault_w),
        TableColumn("project", _lbl("project", "Proj"), proj_w),
        TableColumn("global", _lbl("global", "Glob"), glob_w),
        TableColumn("used", _lbl("used", "Used"), used_w),
    ]
    rows: list[dict[str, str]] = []
    checked: set[int] = set()
    for i, item in enumerate(filtered):
        if item.is_linked or item.name in state.vault_pending_project:
            checked.add(i)
        proj_cell, glob_cell = _vault_pending_indicator(state, item)
        used_count = (
            len(state.vault_usage_index.get(f"{item.type}:{item.name}").projects)
            if state.vault_usage_index and f"{item.type}:{item.name}" in state.vault_usage_index
            else 0
        )
        if item.in_vault:
            vault_cell = "✓"
        elif item.is_global_linked:
            vault_cell = "glob*"
        else:
            vault_cell = "proj*"
        rows.append({
            "no": str(i + 1),
            "name": item.name,
            "ver": item.version or "─",
            "type": item.type,
            "vault": vault_cell,
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

    # Detail panel.
    current = filtered[state.vault_selected]
    if current.in_vault:
        vault_status = "in vault"
    elif current.is_global_linked:
        vault_status = "global only (press `i` to import)"
    else:
        vault_status = "project only (press `i` to import)"
    # Naming differs by activation mechanism (see _activation_term docstring).
    activation_kind = "enabledPlugins" if current.type == "plugin" else "symlink"
    detail_fields: list[tuple[str, str]] = [
        ("Name", current.name),
        ("Type", current.type),
        ("Version", current.version or "—"),
        ("Path", current.path),
        ("Description", current.description or "—"),
        ("Added", _fmt_date(current.created_at)),
        ("Updated", _fmt_date(current.updated_at)),
        ("Vault", vault_status),
        ("Activation", activation_kind),
        ("Project", _activation_term(current.type, current.is_linked)),
        ("Global", _activation_term(current.type, current.is_global_linked)),
    ]
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

    # ── Search-input mode: capture characters, respond only to Enter/Esc/Bksp.
    if state.vault_searching:
        if key in (KEY_ESC, ):
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
    elif key == ord("F"):
        i = _VAULT_FILTERS.index(state.vault_filter)
        state.vault_filter = _VAULT_FILTERS[(i + 1) % len(_VAULT_FILTERS)]
        state.vault_selected = 0
    elif key == ord("s"):
        i = _VAULT_SORTS.index(state.vault_sort)
        state.vault_sort = _VAULT_SORTS[(i + 1) % len(_VAULT_SORTS)]
        state.vault_selected = 0
    elif key == ord("/"):
        # Enter search-input mode.
        state.vault_searching = True
        state.vault_search = ""
        return "/: type to filter, Enter to apply, Esc to cancel"
    elif key == ord("o") and current:
        # Open a new terminal at the item's storage path (file → parent dir).
        p = Path(current.path)
        return _open_terminal_for_dir(state, str(p if p.is_dir() else p.parent))
    elif key == ord(" ") and current and current.type != "plugin":
        # Toggle pending project link for the selected item.
        if current.name in state.vault_pending_project:
            state.vault_pending_project.discard(current.name)
        else:
            state.vault_pending_project.add(current.name)
        return None
    elif key == ord("g") and current and current.type != "plugin":
        if current.name in state.vault_pending_global:
            state.vault_pending_global.discard(current.name)
        else:
            state.vault_pending_global.add(current.name)
        return None
    elif key == ord("U") and current and current.type != "plugin":
        # Unlink the selected item from every project that uses it (per the
        # last scan). Confirms via modal; updates symlinks, profiles, index.
        return _vault_unlink_from_all(state, current)
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
    elif key == KEY_ESC and (state.vault_pending_project or state.vault_pending_global):
        state.vault_pending_project.clear()
        state.vault_pending_global.clear()
        return "Discarded pending changes"
    elif key == KEY_ESC and state.vault_search:
        # First Esc on the filtered list clears the search filter. A second
        # Esc (with no filter left) climbs up to the sub-tab — handled by
        # the layer dispatcher in axt/tui/loop.py.
        state.vault_search = ""
        state.vault_selected = 0
        return "Search cleared"
    elif key == ord("i") and current and not current.in_vault:
        was_project_local = (not current.is_global_linked) and current.is_linked
        try:
            import_to_vault(PATHS.claude_dir, PATHS.vault, current)
            if was_project_local:
                # The symlink at `<project>/.claude/<sub>/<name>` is already
                # in place (left behind by import_to_vault). Record the link
                # in `.axt-profile.json` so `sync_project` won't later treat
                # it as an orphan and unlink it.
                sub = _type_to_dir(current.type)
                profile = read_profile(Path.cwd()) or empty_profile()
                profile = profile.with_added(sub, current.name)
                write_profile(Path.cwd(), profile)
            _vault_load(state)
            _invalidate_context(state)
            origin = "project-local" if was_project_local else "global"
            return f"Imported {current.name!r} ({origin}) to vault"
        except (OSError, ValueError, FileExistsError) as e:
            return f"Import failed: {e}"
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
    elif key == ord("M"):
        # Explicit mode toggle (default↔full) + re-scan + persist.
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
            return f"Migrated: +{len(result.moved)} skipped {len(result.skipped)} err {len(result.errors)}"
        except OSError as e:
            return f"Migrate failed: {e}"
    elif key == ord("S"):
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
    state.usage_loading = True
    set_status(state, "Loading Claude usage…")

    def _worker() -> None:
        try:
            config = load_config(AXT_CONFIG_PATH)
            now = datetime.now(timezone.utc)
            month_start = f"{now.year}-{now.month:02d}-01"
            entries = load_unified_usage(
                claude_projects_dir=PATHS.projects,
                since=month_start,
            )
            # Prime the context cache too — `_render_usage_gauges` reads
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
            if state.status == "Loading Claude usage…":
                set_status(state, "")
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
    without drawing. Mirror of `_render_usage_gauges`.

    Returns ``[(x, text, max_w, attr), ...]``. Empty list if there's
    nothing to show.
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


def _render_usage_gauges(stdscr, state: TuiState, y: int, w: int) -> int:
    """Three gauge bars on the usage tab: context window, 5h, 7d.

    Returns the number of rows drawn so the caller can advance ``row``.
    """
    _ensure_context_loaded(state)
    analysis = state.context_analysis
    rl = read_rate_limits(PATHS.usage_snapshot)

    bar_w = min(30, max(10, w - 40))
    label_w = 10
    rows_used = 0

    if analysis is not None and analysis.context_window_size > 0:
        pct = analysis.used_percent
        filled = round(min(pct, 100) / 100 * bar_w)
        bar = render_bar(filled, bar_w)
        used_tok = format_tokens(analysis.total_tokens)
        win_tok = format_tokens(analysis.context_window_size)
        safe_addnstr(stdscr, y + rows_used, 2, fit_cells(
            f"{'Context:':<{label_w}}{bar} {pct:5.1f}%  {used_tok}/{win_tok} tokens",
            w - 4), w - 4, _gauge_attr(pct))
        rows_used += 1

    if rl is None:
        safe_addnstr(stdscr, y + rows_used, 2,
                     "Rate limits: snapshot missing or stale",
                     w - 4, CP_DIM())
        rows_used += 1
        return rows_used

    if rl.five_hour is not None:
        pct = float(rl.five_hour)
        filled = round(pct / 100 * bar_w)
        bar = render_bar(filled, bar_w)
        safe_addnstr(stdscr, y + rows_used, 2, fit_cells(
            f"{'5h:':<{label_w}}{bar} {rl.five_hour:3d}%    reset in {_fmt_quota_eta(rl.five_hour_reset_at)}",
            w - 4), w - 4, _gauge_attr(pct))
        rows_used += 1
    if rl.seven_day is not None:
        pct = float(rl.seven_day)
        filled = round(pct / 100 * bar_w)
        bar = render_bar(filled, bar_w)
        safe_addnstr(stdscr, y + rows_used, 2, fit_cells(
            f"{'7d:':<{label_w}}{bar} {rl.seven_day:3d}%    reset in {_fmt_quota_eta(rl.seven_day_reset_at)}",
            w - 4), w - 4, _gauge_attr(pct))
        rows_used += 1

    return rows_used


def _usage_period_card(entries: list[UnifiedUsageEntry], label: str) -> list[str]:
    """3-line summary card for a period (Today/Week/Month)."""
    sessions = {e.session_id for e in entries}
    cost = sum(_entry_cost(e) for e in entries)
    in_t = sum(e.input_tokens for e in entries)
    out_t = sum(e.output_tokens for e in entries)
    cw_t = sum(e.cache_write_tokens for e in entries)
    cr_t = sum(e.cache_read_tokens for e in entries)
    return [
        f"  {label:7s}  sessions={len(sessions):>3d}  msgs={len(entries):>4d}",
        f"           in={format_tokens(in_t):>7s}  out={format_tokens(out_t):>7s}  "
        f"cw={format_tokens(cw_t):>7s}  cr={format_tokens(cr_t):>7s}",
        f"           cost=${cost:.2f}",
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
    plan = config.plans.get("claude")
    plan_label = f"{plan.plan} (${plan.monthly_cost}/mo)" if plan else "—"
    lines.append((2, fit_cells(f"Plan: {plan_label}", w - 4), w - 4, CP_TITLE()))

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
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
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
    if entries is None and not state.usage_loading:
        _kick_usage_reload(state)
    config = state.usage_config or load_config(AXT_CONFIG_PATH)

    # Build (or reuse) the line buffer. Scroll keys hit this path every
    # tick, so skipping the rebuild is what keeps scrolling responsive
    # on large transcripts.
    sig = (id(entries), id(config), w)
    if state.usage_lines is None or state.usage_lines_sig != sig:
        lines: list[tuple[int, str, int, int]] = []
        lines.append((0, fit_cells(" Claude usage — this month", w - 1), w - 1, CP_TITLE()))
        lines.append((0, "", w, 0))  # gap

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

    body_h = h
    max_scroll = max(0, len(lines) - body_h)
    if state.usage_scroll > max_scroll:
        state.usage_scroll = max_scroll
    if state.usage_scroll < 0:
        state.usage_scroll = 0

    visible = lines[state.usage_scroll : state.usage_scroll + body_h]
    for i, (x, text, max_w, attr) in enumerate(visible):
        if text:
            safe_addnstr(stdscr, y0 + i, x, text, max_w, attr)


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


def handle_usage_input(state: TuiState, key: int) -> Optional[str]:
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
    label: str
    items: int
    tokens: int
    pct: float


def _context_rows(analysis: ContextAnalysis) -> list[_ContextCategoryRow]:
    by_cat: dict[str, list[ContextSource]] = {}
    for s in analysis.sources:
        by_cat.setdefault(s.category, []).append(s)
    rows = []
    for cat, src_list in by_cat.items():
        tokens = sum(s.estimated_tokens for s in src_list)
        pct = sum(s.percentage for s in src_list)
        rows.append(_ContextCategoryRow(
            category=cat,
            label=CATEGORY_LABELS.get(cat, cat),
            items=len(src_list),
            tokens=tokens,
            pct=pct,
        ))
    rows.sort(key=lambda r: r.tokens, reverse=True)
    return rows


def _render_rate_limit_bars(stdscr, y: int, w: int) -> int:
    """5h/7d rate-limit bars from ~/.claude/usage-snapshot.json. Returns rows used."""
    rl = read_rate_limits(PATHS.usage_snapshot)
    if rl is None:
        safe_addnstr(stdscr, y, 2, "Rate limits: snapshot missing or stale", w - 4, CP_DIM())
        return 1
    bar_w = min(30, w - 40)

    def fmt_eta(reset_at: Optional[datetime]) -> str:
        if not reset_at:
            return "—"
        delta = reset_at - datetime.now(timezone.utc)
        secs = int(delta.total_seconds())
        if secs <= 0:
            return "now"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h {(secs % 3600) // 60}m"
        return f"{secs // 86400}d"

    rows_used = 0
    if rl.five_hour is not None:
        filled = round((rl.five_hour / 100) * bar_w)
        attr = CP_ERR() if rl.five_hour >= 90 else CP_OK() if rl.five_hour < 60 else CP_INFO()
        bar = render_bar(filled, bar_w)
        safe_addnstr(stdscr, y, 2, fit_cells(
            f"5h quota:  {bar} {rl.five_hour:3d}%  reset in {fmt_eta(rl.five_hour_reset_at)}",
            w - 4), w - 4, attr)
        rows_used += 1
    if rl.seven_day is not None:
        filled = round((rl.seven_day / 100) * bar_w)
        attr = CP_ERR() if rl.seven_day >= 90 else CP_OK() if rl.seven_day < 60 else CP_INFO()
        bar = render_bar(filled, bar_w)
        safe_addnstr(stdscr, y + rows_used, 2, fit_cells(
            f"7d quota:  {bar} {rl.seven_day:3d}%  reset in {fmt_eta(rl.seven_day_reset_at)}",
            w - 4), w - 4, attr)
        rows_used += 1
    return rows_used


def _render_context_sources_table(stdscr, state: TuiState, y0: int, h: int, w: int,
                                   rows: list, focused: bool = True) -> None:
    """Render the context-sources breakdown as a full-width table.

    Detail for the selected row lives in the shared bottom panel (see
    ``_context_detail_for``), not a per-section side panel — the table claims
    the whole width. ``focused`` controls the selected-row highlight.
    """
    if h <= 0:
        return
    state.context_selected = max(0, min(state.context_selected, len(rows) - 1))
    columns = [
        TableColumn("label", "Category", max(15, w - 35)),
        TableColumn("items", "#", 4),
        TableColumn("tokens", "Tokens", 10),
        TableColumn("pct", "%", 8),
    ]
    table_rows = [{
        "label": r.label,
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
        TableColumn("name", "Name", max(20, w - 24)),
        TableColumn("source", "Source", 8),
        TableColumn("lines", "Lines", 6),
    ]
    rows_data = [{"name": i.name, "source": i.source, "lines": str(i.lines)}
                 for i in items]
    render_table(stdscr, body_y, 0, body_h, w, columns, rows_data,
                 selected=(state.project_selected if focused else -1),
                 show_header=True)


def _context_detail_for(state: TuiState, analysis: ContextAnalysis,
                        rows: list) -> tuple[str, list[tuple[str, str]]]:
    """(title, fields) for the shared bottom detail panel — reflects the active
    Context sub-tab's selected row (Sources category or Project file)."""
    if state.context_sub_tab == "project":
        items = state.project_items or []
        if items and 0 <= state.project_selected < len(items):
            cur = items[state.project_selected]
            return cur.name, _project_item_detail_fields(cur)
        return "Project files", [("(empty)", "—")]
    if rows and 0 <= state.context_selected < len(rows):
        current = rows[state.context_selected]
        fields: list[tuple[str, str]] = []
        srcs = [s for s in analysis.sources if s.category == current.category]
        srcs.sort(key=lambda s: s.estimated_tokens, reverse=True)
        for s in srcs[:20]:
            hint = f" ({s.hint})" if s.hint else ""
            fields.append((s.name, f"{format_tokens(s.estimated_tokens)} tok{hint}"))
        return current.label, (fields or [("(empty)", "—")])
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

    if state.context_sub_tab == "project":
        _render_project_files_table(stdscr, state, y0, table_h, w, focused=True)
    elif rows:
        _render_context_sources_table(stdscr, state, y0, table_h, w, rows, focused=True)
    else:
        safe_addnstr(stdscr, y0 + 1, 2, "No context sources detected.", w - 4, CP_DIM())

    if detail_h >= 3:
        title, fields = _context_detail_for(state, analysis, rows)
        state.context_detail_scroll = render_detail_panel(
            stdscr, y0 + table_h, 0, detail_h, w, title, fields,
            scroll=state.context_detail_scroll, focused=True)


def render_context_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    _ensure_context_loaded(state)
    analysis = state.context_analysis
    if analysis is None:
        safe_addnstr(stdscr, y0 + 2, 2, "Loading context…", w - 4, CP_DIM())
        return

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
    content_bottom = y0 + h - 2  # cost line sits at h-2
    rows = _context_rows(analysis)
    _render_context_page(stdscr, state, content_y, max(1, content_bottom - content_y),
                         w, analysis, rows)

    # Cost impact line at the bottom.
    ci = analysis.cost_impact
    safe_addnstr(stdscr, y0 + h - 2, 0, fit_cells(
        f"  cost: cache_write=${ci.cache_write_cost:.3f}  "
        f"read/turn=${ci.cache_read_cost_per_turn:.3f}  "
        f"per_session(${ci.per_session_cost:.2f})  monthly(${ci.monthly_cost:.2f})",
        w - 1), w - 1, CP_DIM())


def handle_context_input(state: TuiState, key: int) -> Optional[str]:
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

    # PgUp/PgDn scroll the shared bottom detail panel (both sub-tabs).
    if key == curses.KEY_NPAGE:
        state.context_detail_scroll += 10
        return None
    if key == curses.KEY_PPAGE:
        state.context_detail_scroll = max(0, state.context_detail_scroll - 10)
        return None

    # Project sub-tab: route navigation/actions to the project handler
    # (j/k select, Enter previews, e edits, r reloads).
    if state.context_sub_tab == "project":
        if key in (ord("j"), curses.KEY_DOWN, ord("k"), curses.KEY_UP):
            state.context_detail_scroll = 0
        return handle_project_input(state, key)

    rows = _context_rows(state.context_analysis) if state.context_analysis else []
    n = len(rows)
    if key in (ord("j"), curses.KEY_DOWN):
        state.context_selected = min(n - 1, state.context_selected + 1) if n else 0
        state.context_detail_scroll = 0
    elif key in (ord("k"), curses.KEY_UP):
        state.context_selected = max(0, state.context_selected - 1)
        state.context_detail_scroll = 0
    elif key == ord("r"):
        state.context_analysis = None
        return "Refreshed"
    elif key == ord("e") and state.context_analysis and state.stdscr_callbacks and 0 <= state.context_selected < n:
        cat = rows[state.context_selected].category
        first = next((s for s in state.context_analysis.sources if s.category == cat and s.path), None)
        if first is None:
            return "No file to edit in this category"
        ok = open_in_editor(state.stdscr_callbacks["stdscr"], first.path)
        return f"Opened {first.path}" if ok else "Editor failed"
    elif is_enter(key) and state.context_analysis and state.stdscr_callbacks and 0 <= state.context_selected < n:
        cat = rows[state.context_selected].category
        srcs = [s for s in state.context_analysis.sources if s.category == cat]
        lines = [f"{rows[state.context_selected].label} — {rows[state.context_selected].items} item(s)", ""]
        for s in srcs[:50]:
            hint = f"  ({s.hint})" if s.hint else ""
            lines.append(f"• {s.name}{hint}")
            if s.path:
                lines.append(f"    {s.path}")
            lines.append(f"    {format_tokens(s.estimated_tokens)} tok  {s.percentage:.1f}%")
            lines.append("")
        preview_modal(state.stdscr_callbacks["stdscr"], "\n".join(lines), title=rows[state.context_selected].label)
    return None


# ─── Project tab ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectContextItem:
    name: str
    source: str
    path: str
    content: str
    lines: int


def load_project_context(cwd: os.PathLike[str] | str) -> list[ProjectContextItem]:
    """Mirror src/core/project-context.ts. Returns CLAUDE.md / settings.json /
    memory files relevant to the given project directory."""
    cwd_str = str(cwd)
    home = HOME
    claude_dir = home / ".claude"
    project_settings_dir_name = cwd_str.replace("/", "-")
    # Re-add leading dash per TS quirk: `.replace(/^-/, "-")` is a no-op,
    # so we don't need to strip; just pass through.
    project_settings_dir = claude_dir / "projects" / project_settings_dir_name

    candidates = [
        ("CLAUDE.md (global)", "global", home / "CLAUDE.md"),
        ("CLAUDE.md (user)", "user", claude_dir / "CLAUDE.md"),
        ("CLAUDE.md (project)", "project", Path(cwd) / "CLAUDE.md"),
        ("CLAUDE.md (project/.claude)", "project", Path(cwd) / ".claude" / "CLAUDE.md"),
        ("settings.json (global)", "global", claude_dir / "settings.json"),
        ("settings.local.json (global)", "global", claude_dir / "settings.local.json"),
        ("settings.json (project)", "project", project_settings_dir / "settings.json"),
        ("settings.local.json (project)", "project", project_settings_dir / "settings.local.json"),
    ]
    items: list[ProjectContextItem] = []
    for name, source, path in candidates:
        content = _safe_read_text(path)
        if content is None:
            continue
        items.append(ProjectContextItem(
            name=name, source=source, path=str(path), content=content,
            lines=content.count("\n") + 1,
        ))

    memory_dir = project_settings_dir / "memory"
    for f in _safe_listdir(memory_dir):
        if not f.endswith(".md"):
            continue
        fp = memory_dir / f
        content = _safe_read_text(fp)
        if content is None:
            continue
        stem = Path(f).stem
        items.append(ProjectContextItem(
            name=f"Memory: {stem}", source="memory", path=str(fp),
            content=content, lines=content.count("\n") + 1,
        ))
    return items


def _ensure_project_loaded(state: TuiState) -> None:
    if state.project_items is not None:
        return
    state.project_items = load_project_context(Path.cwd())


def handle_project_input(state: TuiState, key: int) -> Optional[str]:
    items = state.project_items or []
    n = len(items)
    if key in (ord("j"), curses.KEY_DOWN):
        state.project_selected = min(n - 1, state.project_selected + 1) if n else 0
        state.project_scroll = 0
    elif key in (ord("k"), curses.KEY_UP):
        state.project_selected = max(0, state.project_selected - 1)
        state.project_scroll = 0
    elif key == curses.KEY_NPAGE:
        state.project_scroll += 10
    elif key == curses.KEY_PPAGE:
        state.project_scroll = max(0, state.project_scroll - 10)
    elif key == ord("r"):
        state.project_items = None
        return "Refreshed"
    elif is_enter(key) and state.stdscr_callbacks and items and state.project_selected < n:
        item = items[state.project_selected]
        preview_modal(state.stdscr_callbacks["stdscr"], item.content, title=item.name)
    elif key == ord("e") and state.stdscr_callbacks and items and state.project_selected < n:
        item = items[state.project_selected]
        ok = open_in_editor(state.stdscr_callbacks["stdscr"], item.path)
        return f"Opened {item.path}" if ok else "Editor failed"
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
    ("sources", "Sources"),
    ("project", "Project"),
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
        state.ext_cache["plugins"] = list_installed_plugins(PATHS.installed_plugins)
    elif sub_key == "skills":
        state.ext_cache["skills"] = list_all_skills(project_dir=Path.cwd())
    elif sub_key == "commands":
        state.ext_cache["commands"] = list_commands(project_dir=Path.cwd())
    elif sub_key == "agents":
        state.ext_cache["agents"] = list_all_agents(project_dir=Path.cwd())
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
            fields.append(("Env", ", ".join(f"{k}={v}" for k, v in server.env_dict.items())))
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
_SortSpec = tuple[str, Callable[[Any], Any], bool, Optional[str], str]
_SUBTAB_SORT_SPECS: dict[str, tuple[_SortSpec, ...]] = {
    "plugins": (
        ("name",    lambda p: _lc(p.name),                    False, "name",    "▲"),
        ("version", lambda p: (_lc(p.version), _lc(p.name)),  False, "version", "▲"),
        ("market",  lambda p: (_lc(p.marketplace), _lc(p.name)), False, "market", "▲"),
    ),
    "skills": (
        ("name",   lambda s: _lc(s.name),                     False, "name",   "▲"),
        ("source", lambda s: (_lc(s.source), _lc(s.name)),    False, "source", "▲"),
        ("type",   lambda s: (s.is_symlink, _lc(s.name)),     False, "type",   "▲"),
    ),
    "commands": (
        ("name",   lambda c: _lc(c.name),                     False, "name",   "▲"),
        ("source", lambda c: (_lc(c.source), _lc(c.name)),    False, "source", "▲"),
    ),
    "agents": (
        ("name",   lambda a: _lc(a.name),                     False, "name",   "▲"),
        ("source", lambda a: (_lc(a.source), _lc(a.name)),    False, "source", "▲"),
    ),
    "mcp": (
        ("name",      lambda s: _lc(s.name),                       False, "name",      "▲"),
        ("scope",     lambda s: (_lc(s.scope), _lc(s.name)),       False, "scope",     "▲"),
        ("transport", lambda s: (_lc(s.transport), _lc(s.name)),   False, "transport", "▲"),
    ),
    "hooks": (
        ("event",  lambda h: (_lc(h.event), _lc(h.type)),     False, "event",  "▲"),
        ("type",   lambda h: (_lc(h.type), _lc(h.event)),     False, "type",   "▲"),
        ("source", lambda h: (_lc(h.source), _lc(h.event)),   False, "source", "▲"),
    ),
    "market": (
        ("name",    lambda m: _lc(m.name),                        False, "name",    "▲"),
        ("kind",    lambda m: (_lc(m.source.kind), _lc(m.name)),  False, "kind",    "▲"),
        ("updated", lambda m: m.last_updated or "",               True,  "updated", "▼"),
    ),
}


def _subtab_sort_spec(state: TuiState, sub: str) -> Optional[_SortSpec]:
    """Active sort spec for `sub`, or None if the sub-tab has no sort cycle."""
    specs = _SUBTAB_SORT_SPECS.get(sub)
    if not specs:
        return None
    cur = state.ext_sort.get(sub, specs[0][0])
    return next((s for s in specs if s[0] == cur), specs[0])


def _subtab_sorted(state: TuiState, sub: str, data: list) -> list:
    """Return `data` sorted by the sub-tab's active sort key (stable).

    Falls back to the original order if the data lacks an expected attribute
    (defensive — keeps a malformed cache from blanking the list)."""
    spec = _subtab_sort_spec(state, sub)
    if spec is None or not data:
        return data
    _, keyfunc, reverse, _, _ = spec
    try:
        return sorted(data, key=keyfunc, reverse=reverse)
    except (TypeError, AttributeError):
        return data


def _subtab_view(state: TuiState, sub: str) -> list:
    """The displayed (sorted) item list for `sub` — the single ordering shared
    by render and the input handlers so selection indices stay aligned."""
    return _subtab_sorted(state, sub, state.ext_cache.get(sub, []))


def _mark_sorted_column(state: TuiState, sub: str, cols: list) -> list:
    """Append the ▲/▼ glyph to the header of the column the list is sorted by."""
    spec = _subtab_sort_spec(state, sub)
    if spec is None:
        return cols
    _, _, _, marked_col, glyph = spec
    if not marked_col or not glyph:
        return cols
    return [
        TableColumn(c.key, f"{c.label} {glyph}", c.width) if c.key == marked_col else c
        for c in cols
    ]


def _cycle_subtab_sort(state: TuiState, sub: str) -> None:
    """Advance the active sort key for `sub` to the next entry in its cycle."""
    specs = _SUBTAB_SORT_SPECS.get(sub)
    if not specs:
        return
    keys = [s[0] for s in specs]
    cur = state.ext_sort.get(sub, keys[0])
    i = keys.index(cur) if cur in keys else 0
    state.ext_sort[sub] = keys[(i + 1) % len(keys)]
    state.ext_selected[sub] = 0


def subtab_sort_label(state: TuiState, sub: str) -> str:
    """Active sort key name for `sub` (for status hints), or "" if no cycle."""
    spec = _subtab_sort_spec(state, sub)
    return spec[0] if spec else ""


def _blur_ext_detail(state: TuiState) -> None:
    """Drop detail-panel focus and reset its scroll (e.g. on sub-tab change)."""
    state.ext_detail_focused = False
    state.ext_detail_scroll = 0


def _render_list_with_detail(stdscr, state, y0, h, w, key, columns, rows, items, field_fn):
    """Selectable list with a read-only detail panel pinned to the bottom.

    ``field_fn(item)`` returns ``(title, [(label, value), ...])`` for the
    selected row. ``items`` is the cached object list parallel to ``rows``.
    Used by the MCP and Hooks sub-tabs.
    """
    state.ext_selected.setdefault(key, 0)
    state.ext_selected[key] = max(0, min(state.ext_selected[key], max(0, len(rows) - 1)))
    if not rows:
        safe_addnstr(stdscr, y0 + 2, 2, f"No {key} found.", w - 4, CP_DIM())
        return
    # Detail panel claims the bottom ~40% (7–16 rows) but never starves the
    # list below a few visible rows. When it can't show everything, Tab focuses
    # it and j/k scroll (see handle_extensions_input).
    detail_h = max(7, min(16, int(h * 0.4)))
    detail_h = min(detail_h, max(0, h - 4))
    table_h = max(1, h - detail_h)
    render_table(stdscr, y0, 0, table_h, w, columns, rows,
                 selected=state.ext_selected[key], show_header=True,
                 header_rule=False)
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

    _ensure_subtab_loaded(state, sub)
    # Sorted view (state.ext_sort) — the same ordering _selected_item uses, so
    # the row the user acts on always matches the highlighted row.
    data = _subtab_view(state, sub)

    # Non-Vault sub-tabs use the default render_table prefix (` N`/`▸N`) for
    # row numbering — no separate `#` data column needed (it would duplicate).
    if sub == "plugins":
        cols = [
            TableColumn("name", "Plugin", max(20, w - 60)),
            TableColumn("version", "Version", 10),
            TableColumn("status", "G/P", 10),
            TableColumn("market", "Marketplace", 24),
        ]
        enabled_g = read_enabled_plugins(PATHS.settings)
        enabled_p = read_enabled_plugins(project_settings_path())

        def _glyph(v):
            if v is True:
                return "●"
            if v is False:
                return "○"
            return "·"

        rows = [{
            "name": p.name,
            "version": p.version or "—",
            "status": f"{_glyph(enabled_g.get(p.id))} / {_glyph(enabled_p.get(p.id))}",
            "market": p.marketplace or "—",
        } for p in data]

    elif sub == "skills":
        cols = [
            TableColumn("name", "Skill", max(25, w - 58)),
            TableColumn("ver", "Ver", 8),
            TableColumn("source", "Source", 9),
            TableColumn("type", "Type", 8),
            TableColumn("path", "Path", 30),
        ]
        rows = [{
            "name": s.name,
            "ver": s.version or "─",
            "source": s.source,
            "type": "symlink" if s.is_symlink else "dir",
            "path": (s.target or s.path)[:60],
        } for s in data]

    elif sub == "commands":
        cols = [
            TableColumn("name", "Command", max(20, w - 68)),
            TableColumn("ver", "Ver", 8),
            TableColumn("source", "Source", 9),
            TableColumn("desc", "Description", 50),
        ]
        rows = [{
            "name": f"/{c.name}",
            "ver": c.version or "─",
            "source": c.source,
            "desc": (c.description or "")[:80],
        } for c in data]

    elif sub == "agents":
        cols = [
            TableColumn("name", "Agent", max(20, w - 68)),
            TableColumn("ver", "Ver", 8),
            TableColumn("source", "Source", 9),
            TableColumn("desc", "Description", 50),
        ]
        rows = [{
            "name": a.name,
            "ver": a.version or "─",
            "source": a.source,
            "desc": (a.description or "")[:80],
        } for a in data]

    elif sub == "mcp":
        cols = [
            TableColumn("name", "Server", max(18, w - 64)),
            TableColumn("scope", "Scope", 13),
            TableColumn("transport", "Transport", 10),
            TableColumn("detail", "Detail", 30),
        ]
        rows = [{
            "name": s.name + (" [off]" if s.disabled else ""),
            "scope": s.scope,
            "transport": s.transport,
            "detail": (s.url or " ".join([s.command, *s.args_list]).strip())[:60],
        } for s in data]

    elif sub == "hooks":
        cols = [
            TableColumn("event", "Event", 22),
            TableColumn("ver", "Ver", 8),
            TableColumn("type", "Type", 10),
            TableColumn("source", "Source", 10),
            TableColumn("detail", "Detail", max(20, w - 78)),
        ]
        rows = [{
            "event": h.event + (" [off]" if h.disabled else ""),
            "ver": h.version or "─",
            "type": h.type,
            "source": h.source,
            "detail": get_hook_detail(h)[:80],
        } for h in data]

    elif sub == "market":
        cols = [
            TableColumn("name", "Marketplace", max(20, w - 78)),
            TableColumn("ver", "Ver", 8),
            TableColumn("kind", "Source", 10),
            TableColumn("loc", "Location", 30),
            TableColumn("updated", "Updated", 12),
        ]
        rows = [{
            "name": m.name,
            "ver": "─",  # marketplace has no per-source version concept
            "kind": m.source.kind,
            "loc": m.install_location[:50],
            "updated": m.last_updated[:10],
        } for m in data]
    else:
        return

    # Annotate the active sort column's header with ▲/▼ (mirrors Vault).
    cols = _mark_sorted_column(state, sub, cols)

    if sub == "plugins":
        _render_list_with_detail(
            stdscr, state, sub_y, sub_h, w, sub, cols, rows, data,
            lambda p: _plugin_detail_fields(p, enabled_g, enabled_p),
        )
    elif sub == "mcp":
        _render_list_with_detail(stdscr, state, sub_y, sub_h, w, sub, cols, rows, data, _mcp_detail_fields)
    elif sub == "hooks":
        _render_list_with_detail(stdscr, state, sub_y, sub_h, w, sub, cols, rows, data, _hook_detail_fields)
    elif sub == "agents":
        _render_list_with_detail(stdscr, state, sub_y, sub_h, w, sub, cols, rows, data, _agent_detail_fields)
    elif sub == "skills":
        _render_list_with_detail(stdscr, state, sub_y, sub_h, w, sub, cols, rows, data, _skill_detail_fields)
    elif sub == "commands":
        _render_list_with_detail(stdscr, state, sub_y, sub_h, w, sub, cols, rows, data, _command_detail_fields)
    elif sub == "market":
        _render_list_with_detail(stdscr, state, sub_y, sub_h, w, sub, cols, rows, data, _market_detail_fields)


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
    sub-tab body is empty (e.g. "No plugins found." or zero vault items),
    descending from subTab into `content` would silently swallow focus, so
    the loop keeps focus on subTab instead.
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

    if key == ord("["):
        _blur_ext_detail(state)
        _cycle_sub_tab(state, "extensions", -1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == ord("]"):
        _blur_ext_detail(state)
        _cycle_sub_tab(state, "extensions", 1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == ord("r"):
        # Refresh the active sub-tab's cache.
        state.ext_cache.pop(state.ext_sub_tab, None)
        if state.ext_sub_tab == "vault":
            state.vault_items = []
            state.refresh_token = 0
        return "Refreshed"

    sub = state.ext_sub_tab
    if sub == "vault":
        return handle_vault_input(state, key)

    # `s` cycles the active sub-tab's sort (mirrors Vault). Handled here, ahead
    # of detail-focus and list nav, so it works regardless of focus. Sub-tabs
    # without a sort cycle ignore it. (Market's old `s`=sync moved to `S`.)
    if key == ord("s") and sub in _SUBTAB_SORT_SPECS:
        _cycle_subtab_sort(state, sub)
        return f"Sort: {state.ext_sort.get(sub)}"

    # Tab toggles focus into the bottom detail panel (sub-tabs that have one).
    if key in (ord("\t"), curses.KEY_BTAB) and sub in _SUBTABS_WITH_DETAIL:
        if not state.ext_cache.get(sub):
            return None
        state.ext_detail_focused = not state.ext_detail_focused
        state.ext_detail_scroll = 0
        return "Detail focused — j/k scroll, Tab to blur" if state.ext_detail_focused else None

    # While the detail panel is focused, navigation keys scroll it instead of
    # moving the list selection. Action keys (e/d/p/o/…) still fall through.
    if state.ext_detail_focused and sub in _SUBTABS_WITH_DETAIL:
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

    # Simple list navigation for the other sub-tabs.
    data = state.ext_cache.get(sub, [])
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


def _handle_subtab_action(state: TuiState, sub: str, key: int) -> Optional[str]:
    """Sub-tab-specific actions (l/u/a/s/r/p/e/x/o). Returns status message."""
    # Note: stdscr-bound actions (confirm_modal, text_input_modal,
    # preview_modal, open_in_editor) are wired through _tab_stdscr_actions
    # because handler functions don't have stdscr. We use a callback.
    cb = state.stdscr_callbacks
    if not cb:
        return None  # No interactive context available (e.g. tests)
    stdscr = cb.get("stdscr")

    # ── All sub-tabs: o=open a new terminal at the item's directory ───────
    if key == ord("o"):
        item = _selected_item(state, sub)
        if item is None:
            return None
        return _open_terminal_for_dir(state, _item_terminal_dir(sub, item))

    # ── Plugins: e/d=global, E/D=project, x=uninstall i=info ───────────────
    if sub == "plugins":
        plugin = _selected_item(state, "plugins")
        if plugin is None:
            return None
        if key == ord("e"):
            try:
                set_plugin_enabled(PATHS.settings, plugin.id, True)
                state.ext_cache.pop("plugins", None)
                _invalidate_context(state)
                return f"Enabled {plugin.id} (global)"
            except OSError as exc:
                return f"Enable failed: {exc}"
        if key == ord("d"):
            try:
                set_plugin_enabled(PATHS.settings, plugin.id, False)
                state.ext_cache.pop("plugins", None)
                _invalidate_context(state)
                return f"Disabled {plugin.id} (global)"
            except OSError as exc:
                return f"Disable failed: {exc}"
        if key == ord("E"):
            try:
                set_plugin_enabled(project_settings_path(), plugin.id, True)
                state.ext_cache.pop("plugins", None)
                _invalidate_context(state)
                return f"Enabled {plugin.id} (project)"
            except OSError as exc:
                return f"Enable failed: {exc}"
        if key == ord("D"):
            try:
                set_plugin_enabled(project_settings_path(), plugin.id, False)
                state.ext_cache.pop("plugins", None)
                _invalidate_context(state)
                return f"Disabled {plugin.id} (project)"
            except OSError as exc:
                return f"Disable failed: {exc}"
        if key == ord("x") and stdscr:
            if confirm_modal(stdscr, f"Uninstall plugin {plugin.id}?\nThis removes {plugin.install_path}."):
                import shutil
                try:
                    shutil.rmtree(plugin.install_path, ignore_errors=True)
                    remove_installed_plugin(PATHS.installed_plugins, plugin.id)
                    remove_plugin_from_settings(PATHS.settings, plugin.id)
                    state.ext_cache.pop("plugins", None)
                    _invalidate_context(state)
                    return f"Uninstalled {plugin.id}"
                except OSError as exc:
                    return f"Uninstall failed: {exc}"
            return "Cancelled"

    # ── MCP: e=enable d=disable in this project's disabledMcpServers ───────
    if sub == "mcp":
        server = _selected_item(state, "mcp")
        if server is None:
            return None
        if key in (ord("e"), ord("d")):
            want_disabled = key == ord("d")
            if server.disabled == want_disabled:
                return f"MCP {server.name} already {'disabled' if want_disabled else 'enabled'}"
            try:
                set_mcp_disabled(server.name, disabled=want_disabled)
            except OSError as exc:
                return f"{'Disable' if want_disabled else 'Enable'} failed: {exc}"
            state.ext_cache.pop("mcp", None)
            _invalidate_context(state)
            return f"{'Disabled' if want_disabled else 'Enabled'} MCP {server.name} (project)"

    # ── Skills: l=link new path, u=unlink selected (confirmed) ─────────────
    if sub == "skills" and stdscr:
        if key == ord("l"):
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
                state.ext_cache.pop("skills", None)
                _invalidate_context(state)
                return f"Linked {target}"
            except (OSError, ValueError) as exc:
                return f"Link failed: {exc}"
        if key == ord("u"):
            skill = _selected_item(state, "skills")
            if skill is None:
                return None
            if not skill.is_symlink:
                return "Selected skill is not a symlink (cannot unlink)"
            if confirm_modal(stdscr, f"Unlink skill {skill.name}?", title="Confirm unlink"):
                try:
                    unlink_skill(PATHS.skills, skill.name)
                    state.ext_cache.pop("skills", None)
                    _invalidate_context(state)
                    return f"Unlinked {skill.name}"
                except (OSError, ValueError) as exc:
                    return f"Unlink failed: {exc}"
            return "Cancelled"

    # ── Marketplace: a=add (2-step), s=sync (selected), x=remove (confirmed)
    if sub == "market" and stdscr:
        if key == ord("a"):
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
        m = _selected_item(state, "market")
        if m is None:
            return None
        if key == ord("S"):  # `s` is the sort cycle; sync moved to `S`
            try:
                result = sync_marketplace(PATHS.known_marketplaces, m.name)
                state.ext_cache.pop("market", None)
                return f"Synced {m.name}: {result.before} → {result.after}" if result.updated else f"{m.name} up to date"
            except (RuntimeError, KeyError) as exc:
                return f"Sync failed: {exc}"
        if key == ord("x"):
            if confirm_modal(stdscr, f"Remove marketplace {m.name}?\nThis deletes {m.install_location}.",
                             title="Confirm remove"):
                try:
                    remove_marketplace(PATHS.known_marketplaces, PATHS.marketplaces, m.name)
                    state.ext_cache.pop("market", None)
                    return f"Removed {m.name}"
                except KeyError as exc:
                    return f"Remove failed: {exc}"
            return "Cancelled"

    # ── Hooks: e=enable d=disable (move rule within its settings file),
    #          p=preview hook execution in a scrollable modal ───────────────
    if sub == "hooks":
        hook = _selected_item(state, "hooks")
        if hook is None:
            return None
        if key in (ord("e"), ord("d")):
            want_disabled = key == ord("d")
            if hook.disabled == want_disabled:
                return f"Hook already {'disabled' if want_disabled else 'enabled'}"
            if hook.source == "plugin":
                return "Plugin hooks are read-only (manage them in the plugin)"
            try:
                moved = set_hook_disabled(hook.source_path, hook, disabled=want_disabled)
            except OSError as exc:
                return f"{'Disable' if want_disabled else 'Enable'} failed: {exc}"
            if not moved:
                return "Hook not found in its settings file"
            state.ext_cache.pop("hooks", None)
            _invalidate_context(state)
            return f"{'Disabled' if want_disabled else 'Enabled'} hook {hook.event} ({hook.source})"
        if key == ord("p") and stdscr:
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
            preview_modal(stdscr, "\n".join(lines), title=f"Hook preview: {hook.event}")
            return None

    # ── Commands / Agents: e=open source file in $EDITOR ──────────────────
    if sub in ("commands", "agents") and stdscr and key == ord("e"):
        item = _selected_item(state, sub)
        if item is None or not item.source_path:
            return None
        ok = open_in_editor(stdscr, item.source_path)
        return f"Opened {item.source_path}" if ok else "Editor failed"

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

