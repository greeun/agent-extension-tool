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
    _date_in_tz,
    _iso_now,
    _safe_listdir,
    _safe_read_text,
    _today_in_tz,
    _ts_ms,
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

    # Global filter — applies to every tab uniformly.
    # Scope axis: "project" (current cwd only) | "all" (project + global)
    scope_filter: str = "project"

    # Dashboard / usage data caches (None = not loaded yet).
    dashboard_entries: Optional[list] = None
    dashboard_config: Optional[Any] = None
    usage_entries: Optional[list] = None
    usage_config: Optional[Any] = None

    # Context tab.
    context_analysis: Optional[Any] = None
    context_selected: int = 0

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
_VAULT_SORTS = ("name", "type", "added", "updated", "project", "global", "used")


def _vault_load(state: TuiState) -> None:
    """Refresh vault items from disk into state. Cheap — just reads metadata."""
    plugins = list_installed_plugins(PATHS.installed_plugins)
    plugin_refs = [
        PluginRef(id=p.id, name=p.name, description=p.description or "", install_path=p.install_path)
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


def _vault_apply_pending(state: TuiState) -> str:
    """Commit the toggle pending state to disk (project and global symlinks)."""
    items_by_name = {i.name: i for i in state.vault_items}
    applied = 0
    errors = 0
    for name in list(state.vault_pending_project):
        item = items_by_name.get(name)
        if not item or item.type == "plugin":
            state.vault_pending_project.discard(name)
            continue
        try:
            if item.is_linked:
                unlink_from_project(Path.cwd(), item)
            else:
                link_to_project(Path.cwd(), item)
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
    return f"Applied {applied}" + (f", {errors} errors" if errors else "")


def filter_vault_items_by_scope(items: list[VaultItem], scope: str) -> list[VaultItem]:
    """Apply the global Scope filter to a list of vault items.

    scope='project': keep items that are active for the current cwd — either
                      linked at project level or globally enabled (and thus
                      visible from any project).
    scope='all'    : pass everything through unchanged.
    """
    if scope == "project":
        return [i for i in items if i.is_linked or i.is_global_linked]
    return list(items)


def _vault_filtered(state: TuiState) -> list[VaultItem]:
    # NOTE: the global Scope filter (state.scope_filter) is *not* applied here.
    # Vault is the machine-level inventory; hiding unlinked items would break
    # the import/link workflow. Use `filter_vault_items_by_scope()` from other
    # extension sub-tabs (plugins/skills/commands/agents) where the
    # activation-vs-installed distinction matters.
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
    safe_addnstr(stdscr, y0, 0, fit_cells("  ".join(title_parts), w - 1), w - 1, CP_HDR())

    # Search-mode prompt (overrides the second row).
    if state.vault_searching:
        prompt = f" /search: {state.vault_search}_"
        safe_addnstr(stdscr, y0 + 1, 0, fit_cells(prompt, w - 1), w - 1, CP_INFO() | curses.A_BOLD)

    filtered = _vault_filtered(state)
    if not filtered:
        safe_addnstr(stdscr, y0 + 2, 2, "Vault is empty or no items match the current filter.", w - 4, CP_DIM())
        safe_addnstr(stdscr, y0 + 4, 2, "Press `m` to migrate global extensions, or `Tab` to change filter.", w - 4, CP_DIM())
        return

    state.vault_selected = max(0, min(state.vault_selected, len(filtered) - 1))

    table_w = int(w * 0.62)
    detail_x = table_w
    detail_w = w - table_w

    # Columns: # / Name / Type / Vault / Project / Global / Used in.
    # "Vault" semantics:  ✓ = item is in ~/.axt/vault/  ;  global = only in ~/.claude/{type}s/
    # "Project" / "Global" show the *intended* state after applying pending toggles.
    no_w = max(3, len(str(len(filtered))) + 1)
    used_w = 6  # "Used" header + " N proj" data ≤ 6
    proj_w = 6  # "Proj" header + "● *" data ≤ 6
    glob_w = 6  # "Glob"
    type_w = 6  # "Type"
    vault_w = 7  # "Vault"
    # _draw_cell renders each column at `col.width + 2` cells (per-column
    # gap). With 7 columns + 4-cell prefix the gap cost is 4 + 2*7 = 18. We
    # subtract a few more cells of safety so wrap can't eat the last column.
    cols_fixed = no_w + type_w + vault_w + proj_w + glob_w + used_w
    name_w = max(10, table_w - cols_fixed - (4 + 2 * 7) - 4)
    columns = [
        TableColumn("no", "#", no_w),
        TableColumn("name", "Name", name_w),
        TableColumn("type", "Type", type_w),
        TableColumn("vault", "Vault", vault_w),
        TableColumn("project", "Proj", proj_w),
        TableColumn("global", "Glob", glob_w),
        TableColumn("used", "Used", used_w),
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
        rows.append({
            "no": str(i + 1),
            "name": item.name,
            "type": item.type,
            "vault": "✓" if item.in_vault else "global*",
            "project": proj_cell,
            "global": glob_cell,
            "used": f"{used_count} proj" if used_count else "─",
        })

    # Adjust table viewport for the search prompt row.
    table_y = y0 + (2 if state.vault_searching else 1)
    table_h = h - (4 if state.vault_searching else 3)
    render_table(
        stdscr,
        table_y, 0, table_h, table_w,
        columns, rows,
        selected=state.vault_selected,
        checked=checked,
    )

    # Detail panel.
    current = filtered[state.vault_selected]
    vault_status = "in vault" if current.in_vault else "global only (press `i` to import)"
    # Naming differs by activation mechanism (see _activation_term docstring).
    activation_kind = "enabledPlugins" if current.type == "plugin" else "symlink"
    detail_fields: list[tuple[str, str]] = [
        ("Name", current.name),
        ("Type", current.type),
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
    render_detail_panel(
        stdscr,
        table_y, detail_x, table_h, detail_w,
        title=f"{current.name} ({current.type})",
        fields=detail_fields,
        scroll=state.vault_detail_scroll,
        focused=state.vault_detail_focused,
    )


def handle_vault_input(state: TuiState, key: int) -> Optional[str]:
    """Vault tab key handler. Returns a status message or None."""
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
    elif key == KEY_TAB:
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
    elif is_enter(key) and (state.vault_pending_project or state.vault_pending_global):
        return _vault_apply_pending(state)
    elif is_enter(key) and current:
        # No pending changes → drop focus into the detail panel for scrolling.
        state.vault_detail_focused = True
        state.vault_detail_scroll = 0
        return "Detail focused — j/k to scroll, Esc to blur"
    elif key == KEY_ESC and (state.vault_pending_project or state.vault_pending_global):
        state.vault_pending_project.clear()
        state.vault_pending_global.clear()
        return "Discarded pending changes"
    elif key == ord("i") and current and not current.in_vault:
        try:
            import_to_vault(PATHS.claude_dir, PATHS.vault, current)
            _vault_load(state)
            return f"Imported {current.name!r} to vault"
        except (OSError, ValueError, FileExistsError) as e:
            return f"Import failed: {e}"
    elif key == ord("f"):
        # Toggle scan mode AND immediately re-scan (the slow op).
        state.vault_scan_mode = "full" if state.vault_scan_mode == "default" else "default"
        try:
            _vault_scan(state)
            return (
                f"Scan ({state.vault_scan_mode}): "
                f"{format_scan_summary(state.vault_usage_index, style='toast')}  "
                f"(total {len(state.vault_usage_index)})"
            )
        except OSError as e:
            return f"Scan failed: {e}"
    elif key == ord("m"):
        try:
            result = migrate_to_vault(PATHS.claude_dir, PATHS.vault)
            _vault_load(state)
            return f"Migrated: +{len(result.moved)} skipped {len(result.skipped)} err {len(result.errors)}"
        except OSError as e:
            return f"Migrate failed: {e}"
    elif key == ord("S"):
        try:
            result = sync_project(Path.cwd(), PATHS.vault)
            _vault_load(state)
            return f"Sync: +{len(result.linked)} -{len(result.unlinked)} err {len(result.errors)}"
        except OSError as e:
            return f"Sync failed: {e}"
    elif key == ord("r"):
        _vault_load(state)
        return "Refreshed"
    return None


def render_stub_tab(stdscr, state: TuiState, y0: int, h: int, w: int, name: str, hint: str) -> None:
    title = f" {name}"
    safe_addnstr(stdscr, y0, 0, fit_cells(title, w - 1), w - 1, CP_HDR())
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


# ─── Dashboard tab ───────────────────────────────────────────────────────────


def _ensure_dashboard_loaded(state: TuiState) -> None:
    if state.dashboard_entries is not None:
        return
    config = load_config(AXT_CONFIG_PATH)
    state.dashboard_config = config
    now = datetime.now()
    month_start = f"{now.year}-{now.month:02d}-01"
    state.dashboard_entries = load_unified_usage(
        claude_projects_dir=PATHS.projects,
        since=month_start,
    )


def render_dashboard_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    _ensure_dashboard_loaded(state)
    config = state.dashboard_config or load_config(AXT_CONFIG_PATH)
    entries = state.dashboard_entries or []

    header = " Dashboard — this month so far"
    safe_addnstr(stdscr, y0, 0, fit_cells(header, w - 1), w - 1, CP_HDR())
    if not entries:
        safe_addnstr(stdscr, y0 + 2, 2, "No usage data this month yet.", w - 4, CP_DIM())
        return

    # Claude summary line.
    row = y0 + 2
    total_cost = sum(_entry_cost(e) for e in entries)
    plan = config.plans.get("claude")
    plan_label = f"{plan.plan} (${plan.monthly_cost}/mo)" if plan else "—"
    in_t = sum(e.input_tokens for e in entries)
    out_t = sum(e.output_tokens for e in entries)
    cr_t = sum(e.cache_read_tokens for e in entries)
    line = (
        f"{'Claude':9s}  {plan_label:24s}  "
        f"cost={format_cost(total_cost, config.exchange_rate):26s}  "
        f"in={format_tokens(in_t):>7s}  out={format_tokens(out_t):>7s}  cache_r={format_tokens(cr_t):>7s}"
    )
    safe_addnstr(stdscr, row, 2, fit_cells(line, w - 4), w - 4, 0)
    row += 1

    # Total + monthly budget bar.
    row += 1
    safe_addnstr(stdscr, row, 2, fit_cells(f"Total: {format_cost(total_cost, config.exchange_rate)}", w - 4), w - 4, CP_HDR())
    row += 1
    if config.monthly_budget > 0:
        bar_w = min(40, w - 30)
        pct = min(total_cost / config.monthly_budget, 1.5)
        filled = round(min(pct, 1) * bar_w)
        bar = render_bar(filled, bar_w)
        label = f"${total_cost:.2f}/${config.monthly_budget} ({pct * 100:.0f}%)"
        if pct >= 1:
            text, attr = f"{bar} {label} ⛔", CP_ERR()
        elif pct >= 0.8:
            text, attr = f"{bar} {label} ⚠", CP_HDR()
        else:
            text, attr = f"{bar} {label}", CP_OK()
        safe_addnstr(stdscr, row, 2, fit_cells(text, w - 4), w - 4, attr)
        row += 1

    # 14-day BarChart.
    row += 2
    safe_addnstr(stdscr, row, 2, "Last 14 days (daily cost):", w - 4, CP_HDR())
    row += 1
    chart_data = _daily_costs(entries, 14, config.timezone)
    chart_rows = render_bar_chart(stdscr, row, 4, w - 8, chart_data)
    row += chart_rows


def handle_dashboard_input(state: TuiState, key: int) -> Optional[str]:
    if key == ord("r"):
        state.dashboard_entries = None
        return "Refreshed"
    return None


# ─── Usage tab (Claude-only) ─────────────────────────────────────────────────


def _ensure_usage_loaded(state: TuiState) -> None:
    if state.usage_entries is not None:
        return
    config = load_config(AXT_CONFIG_PATH)
    state.usage_config = config
    now = datetime.now(timezone.utc)
    month_start = f"{now.year}-{now.month:02d}-01"
    state.usage_entries = load_unified_usage(
        claude_projects_dir=PATHS.projects,
        since=month_start,
    )


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


def render_usage_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    _ensure_usage_loaded(state)
    config = state.usage_config or load_config(AXT_CONFIG_PATH)
    entries = state.usage_entries or []

    safe_addnstr(stdscr, y0, 0, fit_cells(" Claude usage — this month", w - 1), w - 1, CP_HDR())

    if not entries:
        safe_addnstr(stdscr, y0 + 2, 2, "No Claude usage data this month yet.", w - 4, CP_DIM())
        return

    tz = config.timezone
    today = _today_in_tz(tz)
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    today_entries = [e for e in entries if _date_in_tz(e.timestamp, tz) == today]
    week_entries = [e for e in entries if _date_in_tz(e.timestamp, tz) >= week_ago]
    month_entries = entries

    row = y0 + 2
    for label, eps in (("Today", today_entries), ("Week", week_entries), ("Month", month_entries)):
        for line in _usage_period_card(eps, label):
            safe_addnstr(stdscr, row, 2, fit_cells(line, w - 4), w - 4, 0)
            row += 1
        row += 1

    # 14-day BarChart of daily cost.
    safe_addnstr(stdscr, row, 2, "Last 14 days (daily cost):", w - 4, CP_HDR())
    row += 1
    chart_data = _daily_costs(entries, 14, tz)
    rows_used = render_bar_chart(stdscr, row, 4, w - 8, chart_data)
    row += rows_used + 1

    # Active block + simple insights summary.
    claude_entries = [_unified_to_claude(e) for e in entries]
    blocks = compute_blocks(claude_entries, tz)
    active = next((b for b in blocks if b.is_active), None)
    if active:
        burn = format_tokens(active.burn_rate_per_min) if active.burn_rate_per_min else "—"
        safe_addnstr(stdscr, row, 2, fit_cells(
            f"Active block: {active.start_time[11:16]}–{active.end_time[11:16]}  "
            f"tokens={format_tokens(active.total_tokens)}  burn={burn}/min",
            w - 4), w - 4, CP_OK())
        row += 2

    insights = _compute_simple_insights(claude_entries)
    safe_addnstr(stdscr, row, 2, "Insights (this month):", w - 4, CP_HDR())
    row += 1
    safe_addnstr(stdscr, row, 2, fit_cells(
        f"  large-context sessions (>150k input tokens):  {insights['large_pct']:.1f}%",
        w - 4), w - 4, 0)
    row += 1
    safe_addnstr(stdscr, row, 2, fit_cells(
        f"  parallel sessions (3+ overlapping at once):   {insights['parallel_pct']:.1f}%",
        w - 4), w - 4, 0)
    row += 1
    safe_addnstr(stdscr, row, 2, fit_cells(
        f"  top model by tokens:                          "
        f"{insights['top_model'] or '—'}",
        w - 4), w - 4, 0)
    row += 1
    # Plan-limit row (5h / 7d) if we have the snapshot.
    rl = read_rate_limits(PATHS.usage_snapshot)
    if rl is not None:
        five = f"{rl.five_hour}%" if rl.five_hour is not None else "—"
        seven = f"{rl.seven_day}%" if rl.seven_day is not None else "—"
        safe_addnstr(stdscr, row, 2, fit_cells(
            f"  plan limits:  5h={five}  7d={seven}",
            w - 4), w - 4, CP_INFO())


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
        state.usage_entries = None
        return "Refreshed"
    return None


# ─── Context tab ─────────────────────────────────────────────────────────────


def _ensure_context_loaded(state: TuiState) -> None:
    if state.context_analysis is not None:
        return
    state.context_analysis = analyze_context(
        home_dir=HOME,
        project_dir=Path.cwd(),
        installed_plugins_path=PATHS.installed_plugins,
        model="claude-opus-4-6",
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


def _render_context_sources(stdscr, state: TuiState, y0: int, h: int, w: int,
                            analysis: ContextAnalysis, rows: list) -> None:
    """Render the context-sources table + detail panel within (y0, h)."""
    # Layout: table on left (~55%), detail on right.
    table_w = int(w * 0.55)
    detail_x = table_w
    detail_w = w - table_w

    state.context_selected = max(0, min(state.context_selected, len(rows) - 1))

    columns = [
        TableColumn("label", "Category", max(15, table_w - 35)),
        TableColumn("items", "#", 4),
        TableColumn("tokens", "Tokens", 10),
        TableColumn("pct", "%", 8),
    ]
    table_rows = []
    for r in rows:
        table_rows.append({
            "label": r.label,
            "items": str(r.items),
            "tokens": format_tokens(r.tokens),
            "pct": f"{r.pct:.1f}%",
        })

    render_table(stdscr, y0, 0, h, table_w, columns, table_rows,
                 selected=state.context_selected, show_header=True)

    current = rows[state.context_selected]
    detail_fields: list[tuple[str, str]] = []
    sources_in_cat = [s for s in analysis.sources if s.category == current.category]
    sources_in_cat.sort(key=lambda s: s.estimated_tokens, reverse=True)
    for s in sources_in_cat[:20]:
        hint = f" ({s.hint})" if s.hint else ""
        detail_fields.append((s.name, f"{format_tokens(s.estimated_tokens)} tok{hint}"))
    if not detail_fields:
        detail_fields = [("(empty)", "—")]
    render_detail_panel(stdscr, y0, detail_x, h, detail_w,
                        title=current.label, fields=detail_fields)


def _render_project_files_pane(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    """Render the per-project context file list (CLAUDE.md, settings, memory…)."""
    _ensure_project_loaded(state)
    items = state.project_items or []
    safe_addnstr(stdscr, y0, 0, fit_cells(
        f" Project files — {Path.cwd().name}  ({len(items)} files)",
        w - 1), w - 1, CP_HDR())
    if not items:
        safe_addnstr(stdscr, y0 + 1, 2, "No project context files found.", w - 4, CP_DIM())
        return
    columns = [
        TableColumn("name", "Name", max(20, w - 22)),
        TableColumn("source", "Source", 8),
        TableColumn("lines", "Lines", 6),
    ]
    rows_data = [{"name": i.name, "source": i.source, "lines": str(i.lines)}
                 for i in items]
    render_table(stdscr, y0 + 1, 0, max(1, h - 1), w, columns, rows_data,
                 selected=state.project_selected, show_header=True)


def render_context_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    _ensure_context_loaded(state)
    analysis = state.context_analysis
    if analysis is None:
        safe_addnstr(stdscr, y0 + 2, 2, "Loading context…", w - 4, CP_DIM())
        return

    safe_addnstr(stdscr, y0, 0, fit_cells(
        f" Context — {format_tokens(analysis.total_tokens)} / {format_tokens(analysis.context_window_size)} "
        f"({analysis.used_percent:.1f}%)  model={analysis.model}",
        w - 1), w - 1, CP_HDR())

    # Rate-limit bars (5h / 7d quota) at the top so the user sees them first.
    rl_rows = _render_rate_limit_bars(stdscr, y0 + 1, w)
    y_body = y0 + 1 + rl_rows + 1

    # Reserve 2 rows at the bottom: cost line + spacing.
    body_h = max(1, h - (y_body - y0) - 2)

    # When scope=project, split the body between sources (top) and project
    # files (bottom). When scope=all, sources fill the whole body.
    show_project = (state.scope_filter == "project")
    project_h = max(6, body_h // 3) if show_project else 0
    sources_h = max(1, body_h - project_h)

    rows = _context_rows(analysis)
    if rows:
        _render_context_sources(stdscr, state, y_body, sources_h, w, analysis, rows)
    else:
        safe_addnstr(stdscr, y_body + 1, 2, "No context sources detected.", w - 4, CP_DIM())

    if show_project:
        _render_project_files_pane(stdscr, state, y_body + sources_h, project_h, w)

    # Cost impact line at the bottom.
    ci = analysis.cost_impact
    safe_addnstr(stdscr, y0 + h - 2, 0, fit_cells(
        f"  cost: cache_write=${ci.cache_write_cost:.3f}  "
        f"read/turn=${ci.cache_read_cost_per_turn:.3f}  "
        f"per_session(${ci.per_session_cost:.2f})  monthly(${ci.monthly_cost:.2f})",
        w - 1), w - 1, CP_DIM())


def handle_context_input(state: TuiState, key: int) -> Optional[str]:
    rows = _context_rows(state.context_analysis) if state.context_analysis else []
    n = len(rows)
    if key in (ord("j"), curses.KEY_DOWN):
        state.context_selected = min(n - 1, state.context_selected + 1) if n else 0
    elif key in (ord("k"), curses.KEY_UP):
        state.context_selected = max(0, state.context_selected - 1)
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
    ("plugins", "Plugins"),
    ("skills", "Skills"),
    ("commands", "Commands"),
    ("agents", "Agents"),
    ("mcp", "MCP"),
    ("hooks", "Hooks"),
    ("market", "Market"),
)


def _render_subtab_bar(stdscr, y: int, w: int, active_key: str, *, focused: bool = False) -> None:
    """Render the Extensions sub-tab bar with a clear focus indicator.

    Layered focus (matches `render_tab_bar` so focus is unambiguous when
    switching between main-tab and sub-tab layers):
      - Bar focused:    `▶ Sub:` marker + active sub-tab is solid cyan chip
                        (pair 1 + BOLD), brackets retained for color-blind safety
      - Bar unfocused:  `  Sub:` (no marker) + active sub-tab is bold cyan text
                        with underline (no fill), brackets retained
    """
    label_attr = CP_HDR() if focused else CP_DIM()
    marker = "▶ " if focused else "  "
    marker_attr = _safe_pair(8, curses.A_BOLD) if focused else CP_DIM()
    safe_addnstr(stdscr, y, 0, marker, w, marker_attr)
    safe_addnstr(stdscr, y, cell_width(marker), "Sub: ", w - cell_width(marker), label_attr)
    cur = cell_width(marker) + 5  # "Sub: " is 5 cells
    inactive_attr = _safe_pair(8, curses.A_BOLD) if focused else CP_DIM()
    active_attr = _safe_pair(1, curses.A_BOLD) if focused else _safe_pair(8, curses.A_BOLD | curses.A_UNDERLINE)
    for i, (key, label) in enumerate(EXTENSION_SUB_TABS):
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
        state.ext_cache["mcp"] = list_mcp_servers(_active_plugins())
    elif sub_key == "hooks":
        state.ext_cache["hooks"] = list_hooks(
            user_settings_path=PATHS.settings,
            project_dir=Path.cwd(),
            installed_plugins_path=PATHS.installed_plugins,
        )
    elif sub_key == "market":
        state.ext_cache["market"] = list_marketplaces(PATHS.known_marketplaces)


def _render_simple_list(stdscr, state, y0, h, w, key, columns, rows):
    """Render a simple selectable list for a sub-tab."""
    state.ext_selected.setdefault(key, 0)
    state.ext_selected[key] = max(0, min(state.ext_selected[key], max(0, len(rows) - 1)))
    if not rows:
        safe_addnstr(stdscr, y0 + 2, 2, f"No {key} found.", w - 4, CP_DIM())
        return
    render_table(stdscr, y0, 0, h, w, columns, rows,
                 selected=state.ext_selected[key], show_header=True)


def render_extensions_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    """Extensions parent tab with sub-tab navigation."""
    _render_subtab_bar(
        stdscr, y0, w, state.ext_sub_tab,
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
    data = state.ext_cache.get(sub, [])

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
            TableColumn("name", "Skill", max(25, w - 50)),
            TableColumn("source", "Source", 9),
            TableColumn("type", "Type", 8),
            TableColumn("path", "Path", 30),
        ]
        rows = [{
            "name": s.name,
            "source": s.source,
            "type": "symlink" if s.is_symlink else "dir",
            "path": (s.target or s.path)[:60],
        } for s in data]

    elif sub == "commands":
        cols = [
            TableColumn("name", "Command", max(20, w - 60)),
            TableColumn("source", "Source", 9),
            TableColumn("desc", "Description", 50),
        ]
        rows = [{
            "name": f"/{c.name}",
            "source": c.source,
            "desc": (c.description or "")[:80],
        } for c in data]

    elif sub == "agents":
        cols = [
            TableColumn("name", "Agent", max(20, w - 60)),
            TableColumn("source", "Source", 9),
            TableColumn("desc", "Description", 50),
        ]
        rows = [{
            "name": a.name,
            "source": a.source,
            "desc": (a.description or "")[:80],
        } for a in data]

    elif sub == "mcp":
        cols = [
            TableColumn("name", "Server", max(20, w - 60)),
            TableColumn("plugin", "Plugin", 25),
            TableColumn("cmd", "Command", 30),
        ]
        rows = [{
            "name": s.name,
            "plugin": s.plugin_id,
            "cmd": " ".join([s.command, *s.args_list])[:60],
        } for s in data]

    elif sub == "hooks":
        cols = [
            TableColumn("event", "Event", 22),
            TableColumn("type", "Type", 10),
            TableColumn("source", "Source", 10),
            TableColumn("detail", "Detail", max(20, w - 70)),
        ]
        rows = [{
            "event": h.event,
            "type": h.type,
            "source": h.source,
            "detail": get_hook_detail(h)[:80],
        } for h in data]

    elif sub == "market":
        cols = [
            TableColumn("name", "Marketplace", max(20, w - 70)),
            TableColumn("kind", "Source", 10),
            TableColumn("loc", "Location", 30),
            TableColumn("updated", "Updated", 12),
        ]
        rows = [{
            "name": m.name,
            "kind": m.source.kind,
            "loc": m.install_location[:50],
            "updated": m.last_updated[:10],
        } for m in data]
    else:
        return

    _render_simple_list(stdscr, state, sub_y, sub_h, w, sub, cols, rows)


def _cycle_sub_tab(state: TuiState, direction: int) -> None:
    """Cycle Extensions sub-tabs. Other main tabs have no sub-tabs."""
    i = next((idx for idx, (k, _) in enumerate(EXTENSION_SUB_TABS) if k == state.ext_sub_tab), 0)
    state.ext_sub_tab = EXTENSION_SUB_TABS[(i + direction) % len(EXTENSION_SUB_TABS)][0]


_SCOPE_FILTER_ORDER: tuple[str, ...] = ("project", "all")


def cycle_scope_filter(state: TuiState, direction: int) -> None:
    """Toggle `state.scope_filter` between project and all."""
    try:
        i = _SCOPE_FILTER_ORDER.index(state.scope_filter)
    except ValueError:
        i = 0
    state.scope_filter = _SCOPE_FILTER_ORDER[(i + direction) % len(_SCOPE_FILTER_ORDER)]


def _at_top_of_content(state: TuiState, tab_key: str) -> bool:
    """True when the active tab's selection is at row 0 — used to decide
    whether ↑ should climb out of the content into the focus row above."""
    if tab_key == "extensions":
        if state.ext_sub_tab == "vault":
            return state.vault_selected == 0
        return state.ext_selected.get(state.ext_sub_tab, 0) == 0
    if tab_key == "context":
        return state.context_selected == 0
    # Tabs without a selection (dashboard, usage) always count as "top".
    return True


def handle_extensions_input(state: TuiState, key: int) -> Optional[str]:
    """Handles Extensions sub-tab switching AND delegates to active sub-tab.

    Sub-tab cycling keys:
      [           previous sub-tab
      ]           next sub-tab
      Shift+Tab   previous (KEY_BTAB)
      Tab         next — ONLY on non-Vault sub-tabs (Vault's Tab is filter)
    """
    if key == ord("["):
        _cycle_sub_tab(state, -1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == ord("]"):
        _cycle_sub_tab(state, 1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == curses.KEY_BTAB:  # Shift+Tab
        _cycle_sub_tab(state, -1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == KEY_TAB and state.ext_sub_tab != "vault":
        # Vault's Tab is the filter cycler; only intercept Tab elsewhere.
        _cycle_sub_tab(state, 1)
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

    # Simple list navigation for the other sub-tabs.
    data = state.ext_cache.get(sub, [])
    n = len(data)
    sel = state.ext_selected.get(sub, 0)
    if key in (ord("j"), curses.KEY_DOWN):
        state.ext_selected[sub] = min(n - 1, sel + 1) if n else 0
        return None
    elif key in (ord("k"), curses.KEY_UP):
        state.ext_selected[sub] = max(0, sel - 1)
        return None
    elif key == curses.KEY_NPAGE:
        state.ext_selected[sub] = min(n - 1, sel + 10) if n else 0
        return None
    elif key == curses.KEY_PPAGE:
        state.ext_selected[sub] = max(0, sel - 10)
        return None
    return _handle_subtab_action(state, sub, key)


def _selected_item(state: TuiState, sub: str) -> Any:
    """Return the currently selected item in the given Extensions sub-tab."""
    data = state.ext_cache.get(sub, [])
    sel = state.ext_selected.get(sub, 0)
    if 0 <= sel < len(data):
        return data[sel]
    return None


def _handle_subtab_action(state: TuiState, sub: str, key: int) -> Optional[str]:
    """Sub-tab-specific actions (l/u/a/s/r/p/e/x). Returns status message."""
    # Note: stdscr-bound actions (confirm_modal, text_input_modal,
    # preview_modal, open_in_editor) are wired through _tab_stdscr_actions
    # because handler functions don't have stdscr. We use a callback.
    cb = state.stdscr_callbacks
    if not cb:
        return None  # No interactive context available (e.g. tests)
    stdscr = cb.get("stdscr")

    # ── Plugins: e/d=global, E/D=project, x=uninstall i=info ───────────────
    if sub == "plugins":
        plugin = _selected_item(state, "plugins")
        if plugin is None:
            return None
        if key == ord("e"):
            try:
                set_plugin_enabled(PATHS.settings, plugin.id, True)
                state.ext_cache.pop("plugins", None)
                return f"Enabled {plugin.id} (global)"
            except OSError as exc:
                return f"Enable failed: {exc}"
        if key == ord("d"):
            try:
                set_plugin_enabled(PATHS.settings, plugin.id, False)
                state.ext_cache.pop("plugins", None)
                return f"Disabled {plugin.id} (global)"
            except OSError as exc:
                return f"Disable failed: {exc}"
        if key == ord("E"):
            try:
                set_plugin_enabled(project_settings_path(), plugin.id, True)
                state.ext_cache.pop("plugins", None)
                return f"Enabled {plugin.id} (project)"
            except OSError as exc:
                return f"Enable failed: {exc}"
        if key == ord("D"):
            try:
                set_plugin_enabled(project_settings_path(), plugin.id, False)
                state.ext_cache.pop("plugins", None)
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
                    return f"Uninstalled {plugin.id}"
                except OSError as exc:
                    return f"Uninstall failed: {exc}"
            return "Cancelled"

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
                    return f"Unlinked {skill.name}"
                except (OSError, ValueError) as exc:
                    return f"Unlink failed: {exc}"
            return "Cancelled"

    # ── Marketplace: a=add (2-step), s=sync (selected), r=remove (confirmed)
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
        if key == ord("s"):
            try:
                result = sync_marketplace(PATHS.known_marketplaces, m.name)
                state.ext_cache.pop("market", None)
                return f"Synced {m.name}: {result.before} → {result.after}" if result.updated else f"{m.name} up to date"
            except (RuntimeError, KeyError) as exc:
                return f"Sync failed: {exc}"
        if key == ord("r"):
            if confirm_modal(stdscr, f"Remove marketplace {m.name}?\nThis deletes {m.install_location}.",
                             title="Confirm remove"):
                try:
                    remove_marketplace(PATHS.known_marketplaces, PATHS.marketplaces, m.name)
                    state.ext_cache.pop("market", None)
                    return f"Removed {m.name}"
                except KeyError as exc:
                    return f"Remove failed: {exc}"
            return "Cancelled"

    # ── Hooks: p=preview hook execution in a scrollable modal ──────────────
    if sub == "hooks" and stdscr:
        if key == ord("p"):
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
    "dashboard":  render_dashboard_tab,
    "extensions": render_extensions_tab,
    "context":    render_context_tab,
    "usage":      render_usage_tab,
}

TAB_HANDLERS: dict[str, Callable[..., Optional[str]]] = {
    "dashboard":  handle_dashboard_input,
    "extensions": handle_extensions_input,
    "context":    handle_context_input,
    "usage":      handle_usage_input,
}

