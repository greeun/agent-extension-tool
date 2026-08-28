"""TUI main loop — Section 14 of the original monolith.

The user-facing entry is :func:`launch_tui`. The frame renderer dispatches
via ``TAB_RENDERERS`` (defined in :mod:`axt.tui.tabs`); per-tab key
handlers come from ``TAB_HANDLERS``. Everything here is bookkeeping
around the dispatch.

This module imports from both :mod:`axt.tui.widgets` (curses primitives)
and :mod:`axt.tui.tabs` (tab renderers/handlers + :class:`TuiState`).
After C5, :mod:`axt.core` no longer carries any TUI code — domain only.
"""

from __future__ import annotations

import curses
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

# Curses primitives, color pairs, key helpers, status bar, tab/sub-tab
# bars, modal dialog. Wildcard mirrors the legacy single-namespace shape.
from axt.tui.widgets import *  # noqa: F401,F403

# Tab renderers + handlers, TuiState, MAIN_TABS.
# Wildcard so bare names (``TAB_RENDERERS``, ``TuiState``, …) resolve
# in this module's globals.
from axt.tui.tabs import *  # noqa: F401,F403
from axt.tui.tabs import (  # noqa: F401 — `_`-prefixed names that wildcard skips
    _active_sub_tab,
    _at_top_of_content,
    _cycle_sub_tab,
    _prime_vault_scan,
    sub_tab_has_focusable_content,
    project_sort_cycle_help,
    sort_cycle_help,
    sources_sort_cycle_help,
    subtab_sort_label,
    tab_has_focusable_content,
    tab_has_sub_tab,
)

# Domain helpers (colors for error messages on TUI startup failure).
from axt.core import *  # noqa: F401,F403
from axt.core import (  # noqa: F401 — `_`-prefixed names that wildcard skips
    _dim,
    _red,
)
# Called directly below (first-run welcome toast) — named explicitly for
# clarity even though the wildcard import above already covers them.
from axt.core import (  # noqa: F401
    is_first_run,
    mark_onboarded,
)


# ── Section 14: TUI — Main loop ──────────────────────────────────────────────


HELP_TEXT = f"""\
axt TUI — keyboard reference

Main tabs (resource axis)
  1  Extensions    vault / plugins / skills / commands / agents / mcp / hooks / market
  2  Context       Session context window analysis + Project files
  3  Usage         Claude usage & cost (plan, budget, today/week/month, insights)

Navigation
  1–3           Jump to main tab (active tab is highlighted)
  ← / →         Previous / next within the focused layer
  ↑ / ↓         Move focus between layers (mainTab ↔ subTab ↔ content)
  Esc           Climb one focus layer up (content → subTab → mainTab → quit)
  Enter         Drop focus one layer down OR confirm an action
  [ / ]         Extensions: previous / next sub-tab
  j / ↓         Move selection down (within a list)
  k / ↑         Move selection up
  PgUp / PgDn   Page up / page down

Vault
  Space         Select/deselect focused item for bulk actions (left checkbox ■/□),
                then move focus to the next row
  p             Toggle PROJECT link (pending) — marked items in bulk, else focused
  g             Toggle GLOBAL link (pending) — marked items in bulk, else focused
  G             Skill only: toggle GLOBAL + .agents/skills mirror together
                (immediate, confirm). Both linked → unlink both; else link the
                missing side. .agents skipped when a .skill-lock.json guards it.
  U             Unlink from ALL projects: selected items if any, else focused (confirm)
  u             Update focused item's stored content (git pull)
  Enter         Apply pending toggles (confirm y/N) OR focus detail panel
  Esc           Discard pending / clear marks → clear search → blur detail panel
  Tab           Toggle list ↔ detail panel focus
  /             Search input (type → Enter to apply, Esc to clear)
  c             Cycle filter (all/skill/command/agent)
  s             Sort by the next column (wraps). Every column is sortable;
                each arrives in its natural direction — text A→Z, Used and
                Updated most/newest-first.
                  Cycle: {sort_cycle_help("vault")}
  S             Flip the active column between ascending ▲ and descending ▼.
                The sorted column's header carries the arrow, and the title
                bar's sort= text names the active one (Added and Updated sort
                real data but have no column of their own). The sort you leave
                each list on is saved on quit and restored on the next launch.
  f             Re-scan ALL projects to refresh `Used` (auto-runs on launch in
                the background; cached to disk; title shows scan age / scanning…)
  F             Toggle scan mode (default ↔ full) and re-scan (f's full variant)
  m             Migrate ~/.claude/skills,commands,agents → vault
  y             Sync .claude/<sub>/ symlinks with .axt-profile.json
  r             Refresh (cheap, no cross-project walk)
  o             Open a new terminal at the item's storage path

Extensions sub-tab actions
  All sub-tabs: shared status columns Ver / Vault / Proj / Glob / Upd —
                Vault:     ✓ stored in ~/.axt/vault  ─ not vault-managed
                Proj/Glob: ● active  ○ inactive  · unset (plugins)
                           ─ not applicable (Market project)
                Upd:       ↑ update available (`u` applies)  · up to date
                           ! check error  ─ not updatable  … first check
                           running (async; cached 1h — `r` re-checks now)
                MCP only:  Proj/Glob mark the REGISTRATION scope (read-only:
                           user config → Glob, project/.mcp.json → Proj,
                           plugin/claude.ai/built-in → neither); the On
                           column holds this project's activation state
  All sub-tabs: p=toggle PROJECT activation  g=toggle GLOBAL activation
                (per-sub-tab semantics below)
  All sub-tabs: Space=mark/unmark the focused item (left checkbox ■/□)
                and move focus to the next row; with marks set, p/g toggle
                and u updates every marked item at once (confirm) and Esc
                clears the marks
  All sub-tabs: o=open a new terminal at the item's directory
                (matches your terminal via TERM_PROGRAM; inside cmux a
                 workspace/window chooser appears first)
  All sub-tabs: s=sort by the next column (wraps), S=flip that column
                between ascending ▲ and descending ▼. Every column is
                sortable. A column arrives in its natural direction — text
                A→Z, Updated / Used newest-and-most-first. The sorted
                column's header is marked ▲/▼ and the status bar shows
                s:col/S:dir sort(<column> ▲/▼).
                  Plugins  {sort_cycle_help("plugins")}
                  Skills   {sort_cycle_help("skills")}
                  Commands {sort_cycle_help("commands")}
                  Agents   {sort_cycle_help("agents")}
                  MCP      {sort_cycle_help("mcp")}
                  Hooks    {sort_cycle_help("hooks")}
                  Market   {sort_cycle_help("market")}
                (`#` is the row number in the current order, so it has no
                 sort; columns that never vary on a sub-tab are skipped too)
                Each sub-tab's sort is saved on quit and restored on the
                next launch (~/.config/axt/config.json, "sort").
{subtab_help_block()}
  Notes:        Hooks toggle only in their own scope: a hook in the user
                settings file is global (g), one in project/local settings
                is project (p); plugin-sourced hooks are read-only
  All sub-tabs: a detail panel sits below the list. Tab focuses it,
                j/k (or PgUp/PgDn) scroll it, Esc or Tab blurs back to the list.

Context
  Rate limits   A persistent strip at the top (shown above both sub-tabs)
  Sub-tabs      Sources (live context-window breakdown) · Project (per-
                project context files). ←/→ on the sub-tab bar or [ / ] in
                the body switch between them
  [ / ]         Cycle sub-tabs from the body (Sources ↔ Project)
  j / k         Move selection within the active sub-tab
  PgUp / PgDn   Page the list (±10 rows)
  /             Search filter per sub-tab (type → Enter to apply, Esc to
                clear) — matches name/category/scope/path
  Enter         Focus the bottom detail panel — j/k (or PgUp/PgDn) scroll
                it, Esc blurs back to the table
  s             Sort by the next column of the active sub-tab, wrapping
                  Sources cycle: {sources_sort_cycle_help()}
                  Project cycle: {project_sort_cycle_help()}
                Saved on quit and restored on the next launch
  v             Sources: preview the category's sources with actual content
                Project: preview the focused file's content
  e             Sources: open first source file in $EDITOR
                Project: open the focused file in $EDITOR
  d             Project: delete the focused Memory: * file (confirm) — also
                drops its line from the sibling MEMORY.md index

Usage
  j / k         Scroll the report (PgUp/PgDn page ±10)
  /             Search the report (type → Enter jumps to the first match;
                matches highlighted, Esc clears)
  n / N         Next / previous match
  r             Reload usage data

linked vs enabled (activation mechanism)
  skill / command / agent → "linked"   = SYMLINK at .claude/<type>s/<name>
  plugin                  → "enabled"  = settings.json's enabledPlugins[<id>]
  mcp                     → "enabled"  = not in this project's
                            disabledMcpServers (built-in servers are opt-in
                            via enabledMcpServers) — always project-scoped
  The TUI shows ● / ○ for both, with the DetailPanel labeling the kind.

Vault tab columns
  (every row lives in ~/.axt/vault/ — the tab lists vault storage only;
   items found elsewhere appear on the Skills/Commands/Agents sub-tabs,
   where `i` imports them; plugins live on the Plugins sub-tab)
  Proj    ● / ○    linked in this project (* = pending toggle)
  Glob    ● / ○    linked globally
  Used    N proj   Project count; auto-scanned on launch, `f` to refresh

Globals
  ?             Show this help (in the modal: / to search, n/N next/prev match)
  t             Toggle light / dark theme (saved to config)
  q / Q         Quit
  Esc           Quit only at the main-tab layer; otherwise climbs one layer up
"""


def _extensions_shortcuts(state: TuiState) -> str:
    """Status-bar line for non-vault Extensions sub-tabs. While the `/`
    prompt is open it shows the live query; with a query applied it shows a
    `search:'q'` chip so the filtered view is never mistaken for full data."""
    sub = state.ext_sub_tab
    if state.ext_searching:
        return f"/{state.ext_search.get(sub, '')}█  Enter:apply  Esc:cancel"
    parts = ["1-3:tab", "[/]:sub", "j/k:nav"]
    # A dead background worker otherwise renders exactly like a clean empty
    # result. This chip persists (unlike a status message, which auto-clears)
    # and names the key that retries.
    for failed, label, retry in ((state.update_check_failed, "update check", "r"),
                                 (state.vault_scan_failed, "vault scan", "f"),
                                 (state.usage_load_failed, "usage load", "r")):
        if failed:
            parts.append(f"✗ {label} failed({retry}:retry)")
    q = state.ext_search.get(sub, "")
    if q:
        parts.append(f"search:{q!r}(Esc:clear)")
    marks = state.ext_marked.get(sub) or set()
    if marks:
        parts.append(f"{len(marks)} marked(p/g:bulk Esc:clear)")
    sort_label = subtab_sort_label(state, sub)
    if sort_label:
        # `s` picks the column, `S` flips its direction — named in one chip
        # so the already-crowded status line does not grow another entry.
        parts.append(f"s:col/S:dir sort({sort_label})")
    parts.append("/:search")
    parts.append("Space:mark")
    actions = subtab_shortcuts(sub)
    if actions:
        parts.append(actions)
    parts += ["o:term", "r:refresh", "?:help", "q:quit"]
    return "  ".join(parts)


def _context_shortcuts(state: TuiState) -> str:
    """Status-bar line for the Context tab (mirrors _extensions_shortcuts):
    live query while the `/` prompt is open, a `search:'q'` chip while a
    filter is applied."""
    sub = state.context_sub_tab
    if state.context_searching:
        return f"/{state.context_search.get(sub, '')}█  Enter:apply  Esc:cancel"
    parts = ["1-3:tab", "[/]:sub", "j/k:nav"]
    q = state.context_search.get(sub, "")
    if q:
        parts.append(f"search:{q!r}(Esc:clear)")
    # Both sub-tabs cycle their own sort column with `s` (no `S` direction
    # toggle here — each column's direction is fixed), so the chip names only
    # the column the active sub-tab is on.
    parts.append(f"s:sort({state.sources_sort if sub == 'sources' else state.project_sort})")
    parts += ["/:search", "Enter:detail", "v:preview", "e:edit",
              "d:delete(memory)", "r:refresh", "?:help", "q:quit"]
    return "  ".join(parts)


def _usage_shortcuts(state: TuiState) -> str:
    """Status-bar line for the Usage tab. The `/` search is a match-jump
    (n/N), not a filter, so the chip advertises the n/N keys."""
    if state.usage_searching:
        return f"/{state.usage_search}█  Enter:jump  Esc:cancel"
    parts = ["1-3:tab", "j/k:nav"]
    if state.usage_search:
        parts.append(f"search:{state.usage_search!r} n/N:match (Esc:clear)")
    parts += ["/:search", "r:refresh", "?:help", "q:quit"]
    return "  ".join(parts)


def _render_frame(stdscr, state: TuiState) -> None:
    # Auto-clear the status message after STATUS_TIMEOUT_S so the shortcut
    # hint line becomes visible again. The polling tick in `_tui_loop`
    # guarantees we re-enter this function while a status is shown.
    if state.status and state.status_set_at is not None:
        if time.monotonic() - state.status_set_at >= STATUS_TIMEOUT_S:
            state.status = ""
            state.status_kind = "info"
            state.status_set_at = None

    h, w = stdscr.getmaxyx()
    if h < 5 or w < 30:
        stdscr.erase()
        safe_addnstr(stdscr, 0, 0, "Terminal too small. Resize and try again.", w - 1, CP_ERR())
        return
    stdscr.erase()

    # Header: tab bar + divider. The cwd line now sits at the bottom, just
    # above the status/shortcuts bar (see below), so the top stays compact.
    render_tab_bar(stdscr, 0, 0, w, state.tab_idx, focused=(state.focused_layer == "mainTab"))
    safe_addnstr(stdscr, 1, 0, "─" * (w - 1), w - 1, CP_DIM())

    # Tab content.
    body_y = 2
    body_h = h - body_y - 2  # leave two lines at the bottom: cwd + status bar

    tab_key = MAIN_TABS[state.tab_idx][0]
    renderer = TAB_RENDERERS.get(tab_key)
    if renderer is None:
        render_stub_tab(stdscr, state, body_y, body_h, w,
                        name=MAIN_TABS[state.tab_idx][2], hint="")
    else:
        renderer(stdscr, state, body_y, body_h, w)

    # cwd line — left-aligned at column 0 (flush with the divider/status bar),
    # on the row just above the status/shortcuts bar.
    cwd_text = fit_cells(f"cwd: {Path.cwd()}", w - 1)
    safe_addnstr(stdscr, h - 2, 0, cwd_text, w - 1, CP_DIM())

    # Status / shortcuts line — adjust per active tab + sub-tab.
    if tab_key == "extensions" and state.ext_sub_tab == "vault":
        if state.vault_searching:
            shortcuts = "/: typing search…  Enter:apply  Esc:cancel"
        elif state.vault_pending_project or state.vault_pending_global:
            shortcuts = "Enter:apply pending (confirm)  Esc:discard  p:project  g:global  j/k:nav"
        elif state.vault_marked:
            shortcuts = (
                f"{len(state.vault_marked)} marked  U:unlink-all marked (confirm)  "
                "p/g:toggle marked (pending)  Space:mark/unmark  Esc:clear marks  j/k:nav"
            )
        else:
            shortcuts = (
                "1-3:tab  [/]:sub  j/k:nav  Space:mark  p:project  g:global  G:global+agents  u:update  U:unlink-all  "
                f"Enter:apply  c:filter  s:col/S:dir sort({subtab_sort_label(state, 'vault')})  /:search  f:scan  F:scan+mode  "
                "m:migrate  y:sync  o:term  r:refresh  ?:help  q:quit"
            )
    elif tab_key == "extensions":
        shortcuts = _extensions_shortcuts(state)
    elif tab_key == "context":
        shortcuts = _context_shortcuts(state)
    else:
        shortcuts = _usage_shortcuts(state)
    # Color the status message by its kind so action results stand out:
    # green = state change applied, red = failure, dim = hints/progress.
    status_attr = {
        "ok": CP_OK() | curses.A_BOLD,
        "error": CP_ERR() | curses.A_BOLD,
    }.get(state.status_kind)
    render_status_bar(stdscr, h - 1, w, shortcuts, state.status, status_attr=status_attr)

    stdscr.refresh()


def _handle_main_tab_key(stdscr, state: TuiState, key: int, tab_key: str) -> bool:
    """Handle ←/→/↑/↓/Enter when focus is on the main tab bar.

    Returns True if the key was consumed.
    """
    if key in (curses.KEY_LEFT, ord("h")):
        state.tab_idx = (state.tab_idx - 1) % len(MAIN_TABS)
        _render_frame(stdscr, state)
        return True
    if key in (curses.KEY_RIGHT, ord("l")):
        state.tab_idx = (state.tab_idx + 1) % len(MAIN_TABS)
        _render_frame(stdscr, state)
        return True
    if key == curses.KEY_DOWN or is_enter(key):
        # Capability-driven descent. Usage has no focusable
        # body, so ↓ stays put — no silent focus loss.
        if tab_has_sub_tab(tab_key):
            state.focused_layer = "subTab"
            _render_frame(stdscr, state)
        elif tab_has_focusable_content(state, tab_key):
            state.focused_layer = "content"
            _render_frame(stdscr, state)
        # else: no-op — keep focus on mainTab.
        return True
    if key == curses.KEY_UP:
        # Already at the top layer — explicit no-op.
        return True
    return False


def _handle_sub_tab_key(stdscr, state: TuiState, key: int, tab_key: str) -> bool:
    """Handle ←/→/↑/↓/Enter/Esc when focus is on a sub-tab bar (Extensions or
    Context — both drive the same subTab focus layer)."""
    if key == curses.KEY_LEFT:
        _cycle_sub_tab(state, tab_key, -1)
        _render_frame(stdscr, state)
        return True
    if key == curses.KEY_RIGHT:
        _cycle_sub_tab(state, tab_key, 1)
        _render_frame(stdscr, state)
        return True
    if key in (curses.KEY_UP, KEY_ESC):
        state.focused_layer = "mainTab"
        _render_frame(stdscr, state)
        return True
    if key == curses.KEY_DOWN or is_enter(key):
        # Capability-driven descent (mirrors _handle_main_tab_key). If the
        # active sub-tab is empty (e.g. "No plugins found."), keep focus on
        # the sub-tab bar so the user doesn't lose their cursor to an
        # invisible content layer.
        if sub_tab_has_focusable_content(state, tab_key, _active_sub_tab(state, tab_key)):
            state.focused_layer = "content"
            _render_frame(stdscr, state)
        return True
    # An empty sub-tab keeps focus here (above), but its empty state still
    # advertises actions — the Vault screen says to press `m` to migrate and
    # `F` to change scan mode. Those keys used to reach nothing at all, so the
    # screen instructed an action it then refused. Forward exactly the keys the
    # empty state names; everything else still falls through.
    if (tab_key == "extensions" and _active_sub_tab(state, tab_key) == "vault"
            and not state.vault_items and key in (ord("m"), ord("F"), ord("f"), ord("r"))):
        set_status(state, handle_extensions_input(state, key) or "")
        _render_frame(stdscr, state)
        return True
    return False


def _handle_content_layer_key(stdscr, state: TuiState, key: int, tab_key: str) -> bool:
    """Handle layer-level keys when focus is on the tab body.

    Esc and ↑-at-top climb out of the content into subTab (or mainTab if
    the tab has no sub-tab bar). Esc is a one-shot escape that does not
    require scrolling to row 0 first — handy on long lists where ↑ would
    take many keystrokes. All other keys (j/k/←/→/Enter/letters) are
    left to the tab-specific handler in TAB_HANDLERS.
    """
    climb = key == KEY_ESC or (
        key == curses.KEY_UP and _at_top_of_content(state, tab_key)
    )
    # Extensions detail-panel exception: while the bottom detail panel is
    # focused, Esc blurs it back to the list and ↑ scrolls it (both handled
    # by handle_extensions_input) instead of climbing out. The next Esc,
    # with the panel blurred, then climbs as usual.
    if tab_key == "extensions" and state.ext_detail_focused:
        climb = False
    # Context detail-panel exception: same deal — while the bottom panel is
    # focused, Esc blurs it and ↑ scrolls it (handled by
    # handle_context_input) instead of climbing out.
    if tab_key == "context" and state.context_detail_focused:
        climb = False
    # Marks/search exception (vault and non-vault sub-tabs alike): while
    # Space marks or an applied search filter are active, Esc peels those
    # back first (handled by the tab handler — marks, then the filter). The
    # next Esc, with nothing left to clear, proceeds with the normal climb.
    if (
        key == KEY_ESC
        and tab_key == "extensions"
        and not state.vault_detail_focused
        and (
            (state.ext_sub_tab == "vault"
             and (state.vault_search or state.vault_marked))
            or (state.ext_sub_tab != "vault"
                and (state.ext_search.get(state.ext_sub_tab)
                     or state.ext_marked.get(state.ext_sub_tab)))
        )
    ):
        climb = False
    # Context / Usage applied-search exception: Esc peels the filter (or the
    # match query) back first — handled by the tab handler — before climbing.
    if (
        key == KEY_ESC
        and tab_key == "context"
        and not state.context_detail_focused
        and state.context_search.get(state.context_sub_tab)
    ):
        climb = False
    if key == KEY_ESC and tab_key == "usage" and state.usage_search:
        climb = False
    if climb:
        state.focused_layer = "subTab" if tab_has_sub_tab(tab_key) else "mainTab"
        _render_frame(stdscr, state)
        return True
    return False


def _handle_layer_key(stdscr, state: TuiState, key: int, tab_key: str) -> bool:
    """Dispatch to the active focus layer's key handler."""
    if state.focused_layer == "mainTab":
        return _handle_main_tab_key(stdscr, state, key, tab_key)
    if state.focused_layer == "subTab":
        return _handle_sub_tab_key(stdscr, state, key, tab_key)
    return _handle_content_layer_key(stdscr, state, key, tab_key)


def _has_background_work(state: TuiState) -> bool:
    """Return True iff a background task wants the main loop to poll.

    Cases:
      - Usage tab's background loader is in flight.
      - The cross-project vault scan is in flight.
      - The async update-availability check (Upd column) is in flight.
      - A status message is shown and waiting to auto-clear so the
        bottom-bar shortcut hints can come back.
    """
    if state.usage_loading:
        return True
    if state.vault_scan_loading:
        return True
    if state.update_check_loading:
        return True
    if state.status and state.status_set_at is not None:
        return True
    return False


_POLL_TIMEOUT_MS = 200


def _persist_theme(theme: str) -> None:
    """Save the chosen theme to the user config so it survives restarts.

    Best-effort: a read-only or malformed config must never crash a live
    theme toggle.
    """
    try:
        cfg = load_config(AXT_CONFIG_PATH)
        save_config(AXT_CONFIG_PATH, replace(cfg, theme=theme))
    except (OSError, ValueError):
        pass


def _restore_sort(state) -> None:
    """Put every list back on the sort the last session left it on.

    Best-effort, same as `_persist_theme`: an unreadable or malformed config
    must never keep the TUI from starting — the lists just open on their
    defaults.
    """
    try:
        apply_sort_prefs(state, load_config(AXT_CONFIG_PATH).sort)
    except (OSError, ValueError):
        pass


def _persist_sort(state) -> None:
    """Save the sort every list ended on, once, as the TUI exits.

    The config is re-read here rather than carried over from launch, so a
    mid-session write (`t` saving the theme) survives. Nothing is written
    when the sorts are unchanged, which keeps a look-and-quit session from
    creating a config file it never needed.
    """
    try:
        cfg = load_config(AXT_CONFIG_PATH)
        prefs = collect_sort_prefs(state)
        if prefs == cfg.sort:
            return
        save_config(AXT_CONFIG_PATH, replace(cfg, sort=prefs))
    except (OSError, ValueError):
        pass


def _tui_loop(stdscr, theme: str = "dark") -> None:
    """Run the TUI until the user quits, restoring and then re-saving the
    per-list sort around the session."""
    state = TuiState()
    _restore_sort(state)
    try:
        _run_tui_loop(stdscr, state, theme)
    finally:
        # `finally` rather than a line before each `return`: the loop leaves
        # by `q`, by Esc, and by KeyboardInterrupt, and a fourth exit added
        # later would silently skip the save.
        _persist_sort(state)


def _run_tui_loop(stdscr, state, theme: str = "dark") -> None:
    curses.curs_set(0)
    try:
        curses.set_escdelay(25)  # 3.9+
    except (AttributeError, curses.error):
        pass
    stdscr.keypad(True)
    tui_init_colors(theme, stdscr)

    # `render` lets synchronous handlers force an immediate repaint before a
    # blocking op (e.g. flash "Updating…" ahead of a git fetch/pull on `u`).
    state.stdscr_callbacks = {"stdscr": stdscr, "render": lambda: _render_frame(stdscr, state)}
    # Show the last cross-project scan instantly, then refresh it in the
    # background so the Vault `Used` column is current on launch — no manual
    # `f` needed. The poll loop redraws when the worker finishes.
    _prime_vault_scan(state)
    if is_first_run():
        set_status(state,
                   "Welcome to axt! Press ? for full help. Empty tabs show how to fill them.")
        mark_onboarded()
    _render_frame(stdscr, state)

    while True:
        if state.show_help:
            preview_modal(stdscr, HELP_TEXT, title="axt help")
            state.show_help = False
            _render_frame(stdscr, state)
            continue

        # Dynamic timeout: poll while a background task is in flight,
        # otherwise block forever. The wake-up redraws the frame so the
        # worker's result becomes visible without user input.
        stdscr.timeout(_POLL_TIMEOUT_MS if _has_background_work(state) else -1)

        try:
            key = stdscr.getch()
        except KeyboardInterrupt:
            return

        if key == -1:
            # Timeout tick — just redraw and loop again. The worker
            # may have finished between ticks.
            _render_frame(stdscr, state)
            continue

        # Modal states that intercept input — pass key straight to the active
        # tab handler so it can process search/pending logic without losing
        # keystrokes to the global tab-switcher.
        tab_key = MAIN_TABS[state.tab_idx][0]
        modal = (
            tab_key == "extensions" and (
                state.ext_searching
                or (
                    state.ext_sub_tab == "vault"
                    and (state.vault_searching
                         or state.vault_pending_project
                         or state.vault_pending_global
                         or state.vault_detail_focused)
                )
            )
        ) or (
            # Context / Usage `/`-search prompts swallow every printable key
            # too, so `q`, `t`, `?` and digits land in the query.
            tab_key == "context" and state.context_searching
        ) or (
            tab_key == "usage" and state.usage_searching
        )

        # Global keys (skipped while in a modal sub-state).
        if not modal:
            if key == ord("?"):
                state.show_help = True
                continue
            # Live theme toggle (dark ↔ light) — re-inits the palette in place
            # and persists the choice. Skipped while a modal sub-state owns the
            # keyboard so `t` can still be typed into the Vault search field.
            if key == ord("t"):
                new_theme = "light" if current_theme() == "dark" else "dark"
                tui_init_colors(new_theme, stdscr)
                _persist_theme(new_theme)
                set_status(state, f"Theme: {new_theme}")
                _render_frame(stdscr, state)
                continue
            # `q`/`Q` always quits. Esc only quits when focus is on the main
            # tab row — at lower layers it climbs up one level (handled by
            # the layer dispatch below) so users on a long list don't get
            # bounced out of the app.
            if key in (ord("q"), ord("Q")):
                return
            if key == KEY_ESC and state.focused_layer == "mainTab":
                return
            if key == curses.KEY_RESIZE:
                _render_frame(stdscr, state)
                continue
            # Number-key jump: 1..len(MAIN_TABS). Keeps the binding in sync
            # with the actual tab count instead of hard-coding "1..4".
            n_tabs = len(MAIN_TABS)
            if ord("1") <= key <= ord("1") + n_tabs - 1:
                state.tab_idx = key - ord("1")
                set_status(state, "")
                state.focused_layer = "mainTab"
                _render_frame(stdscr, state)
                continue

            # ── Focus-layer aware arrow navigation ──
            # Each focus layer owns its own ←/→/↑/↓/Enter semantics.
            # The per-layer handlers below return True when they consumed
            # the key so the main loop can `continue` without falling
            # through to the tab body.
            if _handle_layer_key(stdscr, state, key, tab_key):
                continue
        else:
            # In modal: still allow resize.
            if key == curses.KEY_RESIZE:
                _render_frame(stdscr, state)
                continue

        # When focus is mainTab/subTab, the tab body handlers should NOT
        # consume keys (we already handled all the relevant ones above).
        # Drop the key here.
        if not modal and state.focused_layer != "content":
            continue

        # Tab-specific input.
        tab_key = MAIN_TABS[state.tab_idx][0]
        status: Optional[str] = None
        handler = TAB_HANDLERS.get(tab_key)
        if handler is not None:
            status = handler(state, key)
        else:
            handle_stub_input(state, key)

        if status is not None:
            set_status(state, status)

        _render_frame(stdscr, state)


def launch_tui(theme: str = "dark") -> int:
    """Public entry point — invoked from `cli_tui` and `main`.

    ``theme`` ("dark" | "light") selects the initial color palette; the user
    can flip it live with `t` (persisted to config). The lambda keeps
    ``curses.wrapper`` a single-argument call so test stubs stay simple.
    """
    try:
        curses.wrapper(lambda scr: _tui_loop(scr, theme))
    except curses.error as e:
        print(_red(f"TUI failed to start: {e}"), file=sys.stderr)
        print(_dim("This usually means the terminal is too small or doesn't support curses."), file=sys.stderr)
        return 1
    return 0
