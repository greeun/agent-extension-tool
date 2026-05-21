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
    _at_top_of_content,
    _cycle_sub_tab,
    sub_tab_has_focusable_content,
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


HELP_TEXT = """\
axt TUI — keyboard reference

Main tabs (resource axis)
  1  Extensions    vault / plugins / skills / commands / agents / mcp / hooks / market
  2  Context       Session context window analysis + Project files
  3  Usage         Claude usage & cost (plan, budget, today/week/month, insights)

Navigation
  1–3           Jump to main tab (active tab has cyan background)
  ← / →         Previous / next within the focused layer
  ↑ / ↓         Move focus between layers (mainTab ↔ subTab ↔ content)
  Esc           Climb one focus layer up (content → subTab → mainTab → quit)
  Enter         Drop focus one layer down OR confirm an action
  [ / ]         Extensions: previous / next sub-tab
  Shift+Tab     Extensions: previous sub-tab (alt)
  Tab           Extensions (non-Vault): next sub-tab (alt)
  j / ↓         Move selection down (within a list)
  k / ↑         Move selection up
  PgUp / PgDn   Page up / page down

Vault
  Space         Toggle PROJECT link for selected item (pending)
  g             Toggle GLOBAL link for selected item (pending)
  Enter         Apply pending toggles (confirm y/N) OR focus detail panel
  Esc           Discard pending OR blur detail panel
  /             Search input (type → Enter to apply, Esc to clear)
  Tab           Cycle filter (all/skill/command/agent/plugin)
  s             Cycle sort key (incl. `used`, most-used first)
  i             Import a global-only item into the vault (selected row)
  f             Toggle scan mode AND scan ALL projects (cached to disk)
  m             Migrate ~/.claude/skills,commands,agents → vault
  S             Sync .claude/<sub>/ symlinks with .axt-profile.json
  r             Refresh (cheap, no cross-project walk)

Extensions sub-tab actions
  Plugins:      e=enable (global)  d=disable (global)
                E=enable (project) D=disable (project)
                x=uninstall (confirm)
                Status column shows G/P: ● enabled  ○ disabled  · unset
  Skills:       l=link new path (input)  u=unlink (confirm)
  Marketplace:  a=add (source+name input)  s=sync (selected)  r=remove (confirm)
  Commands/Agents: e=open source file in $EDITOR
  Hooks:        p=preview hook execution (scrollable modal)

Context
  Enter         Context: category source list preview
  e             Context: open first source file in $EDITOR
  P             Toggle the per-project files pane on/off (this tab only)

linked vs enabled (activation mechanism)
  skill / command / agent → "linked"   = SYMLINK at .claude/<type>s/<name>
  plugin                  → "enabled"  = settings.json's enabledPlugins[<id>]
  The TUI shows ● / ○ for both, with the DetailPanel labeling the kind.

Vault column meanings
  Vault   ✓        Item lives in ~/.axt/vault/
          glob*    Item only exists in ~/.claude/{type}s/ (use `i` to import)
  Proj    ● / ○    linked/enabled in this project (* = pending toggle)
  Glob    ● / ○    linked/enabled globally
  Used    N proj   Count from last scan (`f` populates this column)

Globals
  ?             Show this help
  q / Q         Quit
  Esc           Quit only at the main-tab layer; otherwise climbs one layer up
"""


def _render_frame(stdscr, state: TuiState) -> None:
    h, w = stdscr.getmaxyx()
    if h < 5 or w < 30:
        stdscr.erase()
        safe_addnstr(stdscr, 0, 0, "Terminal too small. Resize and try again.", w - 1, CP_ERR())
        return
    stdscr.erase()

    # Header (tab bar on top, cwd on right of second row, divider).
    render_tab_bar(stdscr, 0, 0, w, state.tab_idx, focused=(state.focused_layer == "mainTab"))
    cwd_text = f" cwd: {Path.cwd()}"
    cwd_w = cell_width(cwd_text)
    if cwd_w >= w - 2:
        cwd_text = fit_cells(cwd_text, w - 2)
        cwd_w = cell_width(cwd_text)
    cwd_x = max(0, w - 1 - cwd_w)
    if cwd_w > 0:
        safe_addnstr(stdscr, 1, cwd_x, cwd_text, cwd_w, CP_DIM())
    safe_addnstr(stdscr, 2, 0, "─" * (w - 1), w - 1, CP_DIM())

    # Tab content.
    body_y = 3
    body_h = h - body_y - 1  # leave one line for status

    tab_key = MAIN_TABS[state.tab_idx][0]
    renderer = TAB_RENDERERS.get(tab_key)
    if renderer is None:
        render_stub_tab(stdscr, state, body_y, body_h, w,
                        name=MAIN_TABS[state.tab_idx][2], hint="")
    else:
        renderer(stdscr, state, body_y, body_h, w)

    # Status / shortcuts line — adjust per active tab + sub-tab.
    if tab_key == "extensions" and state.ext_sub_tab == "vault":
        if state.vault_searching:
            shortcuts = "/: typing search…  Enter:apply  Esc:cancel"
        elif state.vault_pending_project or state.vault_pending_global:
            shortcuts = "Enter:apply pending (confirm)  Esc:discard  Space:project  g:global  j/k:nav"
        else:
            shortcuts = (
                "1-3:tab  [/]:sub  j/k:nav  Space:project  g:global  "
                "Enter:apply  Tab:filter  s:sort  /:search  i:import  f:scan  m:migrate  S:sync  r:refresh  ?:help  q:quit"
            )
    elif tab_key == "extensions":
        shortcuts = "1-3:tab  [/]:sub  j/k:nav  r:refresh  ?:help  q:quit"
    elif tab_key == "context":
        shortcuts = "1-3:tab  j/k:nav  P:project pane  e:edit  r:refresh  ?:help  q:quit"
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
    """Handle ←/→/↑/↓/Enter/Esc when focus is on the Extensions sub-tab bar."""
    del tab_key  # subTab layer is Extensions-only by construction
    if key == curses.KEY_LEFT:
        _cycle_sub_tab(state, -1)
        _render_frame(stdscr, state)
        return True
    if key == curses.KEY_RIGHT:
        _cycle_sub_tab(state, 1)
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
        if sub_tab_has_focusable_content(state, state.ext_sub_tab):
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

    Today: only the Usage tab's loader. Centralizing here lets future
    background work plug in without touching `_tui_loop`'s structure.
    """
    return bool(state.usage_loading)


_POLL_TIMEOUT_MS = 200


def _tui_loop(stdscr) -> None:
    curses.curs_set(0)
    try:
        curses.set_escdelay(25)  # 3.9+
    except (AttributeError, curses.error):
        pass
    stdscr.keypad(True)
    tui_init_colors()

    state = TuiState()
    state.stdscr_callbacks = {"stdscr": stdscr}
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
            tab_key == "extensions"
            and state.ext_sub_tab == "vault"
            and (state.vault_searching
                 or state.vault_pending_project
                 or state.vault_pending_global
                 or state.vault_detail_focused)
        )

        # Global keys (skipped while in a modal sub-state).
        if not modal:
            if key == ord("?"):
                state.show_help = True
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
            if key == ord("P") and tab_key == "context":
                state.context_show_project = not state.context_show_project
                state.status = (
                    "Project files pane: on" if state.context_show_project
                    else "Project files pane: off"
                )
                _render_frame(stdscr, state)
                continue
            # Number-key jump: 1..len(MAIN_TABS). Keeps the binding in sync
            # with the actual tab count instead of hard-coding "1..4".
            n_tabs = len(MAIN_TABS)
            if ord("1") <= key <= ord("1") + n_tabs - 1:
                state.tab_idx = key - ord("1")
                state.status = ""
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
            state.status = status

        _render_frame(stdscr, state)


def launch_tui() -> int:
    """Public entry point — invoked from `cli_tui` and `main` with no args."""
    try:
        curses.wrapper(_tui_loop)
    except curses.error as e:
        print(_red(f"TUI failed to start: {e}"), file=sys.stderr)
        print(_dim("This usually means the terminal is too small or doesn't support curses."), file=sys.stderr)
        return 1
    return 0
