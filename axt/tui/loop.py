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
  Space         Toggle PROJECT link for selected item (pending)
  g             Toggle GLOBAL link for selected item (pending)
  U             Unlink selected item from ALL projects that use it (confirm)
  Enter         Apply pending toggles (confirm y/N) OR focus detail panel
  Esc           Discard pending → clear search → blur detail panel (in that order)
  Tab           Toggle list ↔ detail panel focus
  /             Search input (type → Enter to apply, Esc to clear)
  c             Cycle filter (all/skill/command/agent/plugin)
  s             Cycle sort (Name→Type→Proj→Glob→Used→Added→Updated); active column header marked ▲/▼
  i             Import a global-only item into the vault (selected row)
  f             Re-scan ALL projects to refresh `Used` (auto-runs on launch in
                the background; cached to disk; title shows scan age / scanning…)
  F             Toggle scan mode (default ↔ full) and re-scan (f's full variant)
  m             Migrate ~/.claude/skills,commands,agents → vault
  S             Sync .claude/<sub>/ symlinks with .axt-profile.json
  r             Refresh (cheap, no cross-project walk)
  o             Open a new terminal at the item's storage path

Extensions sub-tab actions
  All sub-tabs: o=open a new terminal at the item's directory
                (matches your terminal via TERM_PROGRAM; inside cmux a
                 workspace/window chooser appears first)
  All sub-tabs: s=cycle sort (the sorted column's header is marked ▲/▼;
                active key shown as s:sort(<key>) in the status bar)
                  Plugins  Name→Version→Marketplace
                  Skills   Name→Source→Type
                  Commands Name→Source     Agents  Name→Source
                  MCP      Name→Scope→Transport
                  Hooks    Event→Type→Source
                  Market   Name→Source→Updated
{subtab_help_block()}
  Notes:        Plugins status column G/P: ● enabled  ○ disabled  · unset
                Hooks [off] = parked; plugin-sourced hooks are read-only
  All sub-tabs: a detail panel sits below the list. Tab focuses it,
                j/k (or PgUp/PgDn) scroll it, Esc or Tab blurs back to the list.

Context
  Rate limits   A persistent strip at the top (shown above both sub-tabs)
  Sub-tabs      Sources (live context-window breakdown) · Project (per-
                project context files). ←/→ on the sub-tab bar or [ / ] in
                the body switch between them
  [ / ]         Cycle sub-tabs from the body (Sources ↔ Project)
  j / k         Move selection within the active sub-tab
  PgUp / PgDn   Scroll the shared bottom detail panel
  Enter         Sources: category source list preview
                Project: preview the focused file's content
  e             Sources: open first source file in $EDITOR
                Project: open the focused file in $EDITOR

linked vs enabled (activation mechanism)
  skill / command / agent → "linked"   = SYMLINK at .claude/<type>s/<name>
  plugin                  → "enabled"  = settings.json's enabledPlugins[<id>]
  The TUI shows ● / ○ for both, with the DetailPanel labeling the kind.

Vault column meanings
  Vault   ✓        Item lives in ~/.axt/vault/
          glob*    Item only exists in ~/.claude/{{type}}s/ (use `i` to import)
  Proj    ● / ○    linked/enabled in this project (* = pending toggle)
  Glob    ● / ○    linked/enabled globally
  Used    N proj   Project count; auto-scanned on launch, `f` to refresh

Globals
  ?             Show this help (in the modal: / to search, n/N next/prev match)
  t             Toggle light / dark theme (saved to config)
  q / Q         Quit
  Esc           Quit only at the main-tab layer; otherwise climbs one layer up
"""


def _render_frame(stdscr, state: TuiState) -> None:
    # Auto-clear the status message after STATUS_TIMEOUT_S so the shortcut
    # hint line becomes visible again. The polling tick in `_tui_loop`
    # guarantees we re-enter this function while a status is shown.
    if state.status and state.status_set_at is not None:
        if time.monotonic() - state.status_set_at >= STATUS_TIMEOUT_S:
            state.status = ""
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
            shortcuts = "Enter:apply pending (confirm)  Esc:discard  Space:project  g:global  j/k:nav"
        else:
            shortcuts = (
                "1-3:tab  [/]:sub  j/k:nav  Space:project  g:global  U:unlink-all  "
                "Enter:apply  c:filter  s:sort  /:search  i:import  f:scan  F:scan+mode  m:migrate  S:sync  o:term  r:refresh  ?:help  q:quit"
            )
    elif tab_key == "extensions":
        sub = state.ext_sub_tab
        actions = subtab_shortcuts(sub)
        parts = ["1-3:tab", "[/]:sub", "j/k:nav"]
        sort_label = subtab_sort_label(state, sub)
        if sort_label:
            parts.append(f"s:sort({sort_label})")
        if actions:
            parts.append(actions)
        parts += ["o:term", "r:refresh", "?:help", "q:quit"]
        shortcuts = "  ".join(parts)
    elif tab_key == "context":
        shortcuts = "1-3:tab  [/]:sub  j/k:nav  PgUp/PgDn:scroll  e:edit  Enter:preview  r:refresh  ?:help  q:quit"
    else:
        shortcuts = "1-3:tab  j/k:nav  r:refresh  ?:help  q:quit"
    render_status_bar(stdscr, h - 1, w, shortcuts, state.status)

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
    # Search exception (vault and non-vault sub-tabs alike): when a search
    # filter is active, the first Esc clears the filter (handled by the tab
    # handler) before climbing out. The second Esc then proceeds with the
    # normal climb because the query is empty by then.
    if (
        key == KEY_ESC
        and tab_key == "extensions"
        and not state.vault_detail_focused
        and (
            (state.ext_sub_tab == "vault" and state.vault_search)
            or (state.ext_sub_tab != "vault" and state.ext_search.get(state.ext_sub_tab))
        )
    ):
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
      - A status message is shown and waiting to auto-clear so the
        bottom-bar shortcut hints can come back.
    """
    if state.usage_loading:
        return True
    if state.vault_scan_loading:
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


def _tui_loop(stdscr, theme: str = "dark") -> None:
    curses.curs_set(0)
    try:
        curses.set_escdelay(25)  # 3.9+
    except (AttributeError, curses.error):
        pass
    stdscr.keypad(True)
    tui_init_colors(theme, stdscr)

    state = TuiState()
    state.stdscr_callbacks = {"stdscr": stdscr}
    # Show the last cross-project scan instantly, then refresh it in the
    # background so the Vault `Used` column is current on launch — no manual
    # `f` needed. The poll loop redraws when the worker finishes.
    _prime_vault_scan(state)
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
        modal = tab_key == "extensions" and (
            state.ext_searching
            or (
                state.ext_sub_tab == "vault"
                and (state.vault_searching
                     or state.vault_pending_project
                     or state.vault_pending_global
                     or state.vault_detail_focused)
            )
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
