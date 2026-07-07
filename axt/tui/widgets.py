"""TUI common helpers + widgets — Sections 11-12 of the original monolith.

Self-contained: depends only on stdlib (curses, unicodedata, subprocess, os).
The ``__version__`` constant is duplicated from :mod:`axt.core` so this
module can be imported before ``core`` finishes initialization (avoiding
the circular import that would happen if widgets.py needed
``axt.core.__version__`` at module level).
"""

from __future__ import annotations

import curses
import os
import shlex
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from typing import Optional

# Duplicated to keep widgets.py independent of axt.core. The single source
# of truth is still axt.core.__version__ / axt.__version__ — the package
# mirror loop in axt/__init__.py re-exports the most-recent definition.
__version__ = "1.7.0"


# ── Section 11: TUI — Common helpers (curses, color, key, width) ────────────
#
# Why curses (vs. an Ink/React equivalent in Python):
#   The original Ink TUI bug ("selected row's ▸/# disappear under WezTerm + cmux")
#   was caused by Ink/Yoga's flex-layout writing rows of *different* trailing-
#   space widths depending on whether they had a background-affecting style.
#   Curses sidesteps the whole class of bugs by writing every cell explicitly
#   via addnstr(y, x, text, width, attr) — the way cst (claude-session-tracker)
#   does and never hits the same issue.



# Theme palettes. pair NUMBERS carry fixed meaning (1 = active/selection chip,
# 2 = header, 3-6 = ok/info/err/mark, 7 = dim, 8 = secondary); only their
# (fg, bg) — and a couple of emphasis attributes — differ per theme. Because
# every CP_* helper resolves a pair by NUMBER, swapping the palette re-themes
# the entire UI without touching call sites.
#
# Both themes fix a background on EVERY pair (terminal-independent) so a theme
# renders identically across Terminal.app / WezTerm / cmux / iTerm2 / ghostty
# regardless of that terminal's own background. The earlier design left dark on
# -1 (inherit the terminal bg), which made the dark theme's saturated accents
# (yellow especially) unreadable when the terminal itself was light.
#
# DARK  = the "looks good on black" scheme (yellow headers, solid cyan chips) on
#         a FIXED black background; stdscr is filled black via bkgd().
# LIGHT = monochrome emphasis (reverse / underline) on a FIXED white background;
#         stdscr is filled white via bkgd(), and cyan (washes out on white) is
#         swapped for blue.
# Pair 7 doubles as the bkgd fill pair in BOTH themes (white-on-black /
# black-on-white), so untouched cells and attr-less text inherit the theme bg.
_DARK_PALETTE = (
    (1, curses.COLOR_BLACK, curses.COLOR_CYAN),        # active / selection chip
    (2, curses.COLOR_YELLOW, curses.COLOR_BLACK),      # header / accent
    (3, curses.COLOR_GREEN, curses.COLOR_BLACK),       # success / active
    (4, curses.COLOR_BLUE, curses.COLOR_BLACK),        # info
    (5, curses.COLOR_RED, curses.COLOR_BLACK),         # danger / error
    (6, curses.COLOR_MAGENTA, curses.COLOR_BLACK),     # mark
    (7, curses.COLOR_WHITE, curses.COLOR_BLACK),       # dim (white fg + A_DIM); also the bkgd fill pair
    (8, curses.COLOR_CYAN, curses.COLOR_BLACK),        # secondary
)
_LIGHT_PALETTE = (
    (1, curses.COLOR_BLACK, curses.COLOR_WHITE),       # active/selection → reverse = white-on-black chip
    (2, curses.COLOR_BLACK, curses.COLOR_WHITE),       # header → +A_UNDERLINE
    (3, curses.COLOR_GREEN, curses.COLOR_WHITE),       # success / active
    (4, curses.COLOR_BLUE, curses.COLOR_WHITE),        # info
    (5, curses.COLOR_RED, curses.COLOR_WHITE),         # danger / error
    (6, curses.COLOR_MAGENTA, curses.COLOR_WHITE),     # mark
    (7, curses.COLOR_BLACK, curses.COLOR_WHITE),       # dim → +A_DIM; also the bkgd fill pair
    (8, curses.COLOR_BLUE, curses.COLOR_WHITE),        # secondary (cyan washes out on white)
)

# Pair 7 doubles as the full-screen background fill (via bkgd) in BOTH themes —
# black-on-white under light, white-on-black under dark — so untouched cells and
# attr-less text inherit the theme's fixed background regardless of the
# terminal's own background.
_BG_PAIR = 7

# Active theme, set by tui_init_colors(). Drives CP_ACTIVE_CHIP()'s reverse
# branch so the curses helpers stay argument-free at their many call sites.
_ACTIVE_THEME = "dark"


def current_theme() -> str:
    """The theme last applied by :func:`tui_init_colors` ("dark"|"light")."""
    return _ACTIVE_THEME


def tui_init_colors(theme: str = "dark", stdscr=None) -> None:
    """Initialize the color palette for ``theme`` ("dark" | "light").

    Safe to call multiple times — used both at startup and on a live theme
    toggle. Unknown values fall back to dark. When ``stdscr`` is provided, the
    light theme also fills the whole screen with a white background (so the
    look is fixed regardless of the terminal's own background); dark resets the
    fill to the terminal default.
    """
    global _ACTIVE_THEME
    _ACTIVE_THEME = "light" if theme == "light" else "dark"
    # curses raises curses.error when color isn't started, and ValueError
    # ("Color pair is greater than COLOR_PAIRS-1") when curses isn't
    # initialized at all (COLOR_PAIRS == -1). Swallow both so the helper is
    # safe to call from unit tests and color-less terminals alike.
    try:
        curses.use_default_colors()
    except (curses.error, ValueError):
        pass
    palette = _LIGHT_PALETTE if _ACTIVE_THEME == "light" else _DARK_PALETTE
    for n, fg, bg in palette:
        try:
            curses.init_pair(n, fg, bg)
        except (curses.error, ValueError):
            pass
    # Fix the screen background to match the theme via the shared fill pair (7):
    # light = solid white, dark = solid black. Both override the terminal's own
    # background so untouched cells and attr-less text stay on the theme bg and
    # the theme looks identical across terminals.
    if stdscr is not None:
        try:
            stdscr.bkgd(" ", curses.color_pair(_BG_PAIR))
        except (curses.error, ValueError):
            pass


# Color pair shortcuts. Wrapped so the widgets remain testable (and degrade
# gracefully) when start_color() hasn't been called yet — e.g. unit tests, or
# terminals that don't support color. Selection also gets A_REVERSE so it's
# visible even without colors.
def _safe_pair(n: int, extra: int = 0) -> int:
    try:
        return curses.color_pair(n) | extra
    except curses.error:
        return extra


def CP_SEL() -> int:   # selection — REVERSE makes it visible even without color
    return _safe_pair(1, curses.A_BOLD | curses.A_REVERSE)


def CP_ACTIVE_CHIP() -> int:
    """Strongest highlight: the active main-tab chip / active sub-tab cell.

    Dark = a solid cyan chip (black-on-cyan, BOLD). Light = a monochrome
    reverse chip (default fg/bg swapped) so there is no fluorescent fill to
    strain the eye on a white background. Selected list rows already use
    CP_SEL() (which carries A_REVERSE), so they adapt automatically.
    """
    extra = curses.A_BOLD
    if _ACTIVE_THEME == "light":
        extra |= curses.A_REVERSE
    return _safe_pair(1, extra)


def CP_TITLE() -> int:
    """Section / status TITLE — the accent tier, just below selection in the
    emphasis hierarchy. Dark: yellow + bold (the strongest content accent).
    Light: the default fg with NO underline/reverse, so a full-width title row
    never renders as a rule or a solid bar on white. Distinct from CP_HDR(),
    which is the subordinate table-column-header tier.
    """
    if _ACTIVE_THEME == "light":
        return _safe_pair(2)
    return _safe_pair(2, curses.A_BOLD)


def CP_HDR() -> int:
    # TABLE COLUMN-HEADER tier — subordinate to CP_TITLE() so column labels
    # recede beneath the section title (which owns the accent).
    # Dark: dim grey (pair 7 + A_DIM) — quieter than the yellow title.
    # Light: default fg + A_UNDERLINE. A_BOLD washes out on white (bold→bright
    # on iTerm2 etc.), and the underline is per-cell here (not a full-width
    # title row), so it reads as a header underline, not a rule.
    if _ACTIVE_THEME == "light":
        return _safe_pair(2, curses.A_UNDERLINE)
    return _safe_pair(7, curses.A_DIM)


def CP_OK() -> int:
    return _safe_pair(3)


def CP_INFO() -> int:
    return _safe_pair(4)


def CP_ERR() -> int:
    return _safe_pair(5)


def CP_MARK() -> int:
    return _safe_pair(6)


def CP_DIM() -> int:
    return _safe_pair(7, curses.A_DIM)


def CP_CYAN() -> int:
    return _safe_pair(8)


def cell_width(text: str) -> int:
    """East-Asian-width-aware character count for terminal cell layout.

    Matches curses' own measurement: wide/full-width = 2 cells, ambiguous = 1
    (matches WezTerm default), everything else = 1.
    """
    width = 0
    for ch in text:
        w = unicodedata.east_asian_width(ch)
        width += 2 if w in ("F", "W") else 1
    return width


def fit_cells(text: str, width: int) -> str:
    """Truncate `text` to fit in `width` cells, padding with spaces."""
    if width <= 0:
        return ""
    out_chars: list[str] = []
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if used + w > width:
            break
        out_chars.append(ch)
        used += w
    return "".join(out_chars) + " " * max(0, width - used)


def safe_addnstr(stdscr, y: int, x: int, text: str, max_w: int, attr: int = 0) -> None:
    """addnstr that swallows boundary errors (cell at (h-1, w-1) raises in curses)."""
    if y < 0 or x < 0 or max_w <= 0:
        return
    try:
        stdscr.addnstr(y, x, text, max_w, attr)
    except curses.error:
        pass


# Key constants for clarity.
KEY_ESC = 27
KEY_TAB = 9
KEY_ENTER = 10
KEY_RETURN = 13
KEY_BACKSPACE = 127


def is_enter(k: int) -> bool:
    return k in (KEY_ENTER, KEY_RETURN, curses.KEY_ENTER)


def is_quit(k: int) -> bool:
    return k in (ord("q"), ord("Q"), KEY_ESC)


# ── Section 12: TUI — Common widgets ─────────────────────────────────────────


# Main tabs in display order. Index is also their 1-based keyboard shortcut.
MAIN_TABS: tuple[tuple[str, str, str], ...] = (
    # (key, short label, long label)
    ("extensions", "Ext",  "Extensions"),
    ("context",    "Ctx",  "Context"),
    ("usage",      "Use",  "Usage"),
)


def render_tab_bar(stdscr, y: int, x: int, w: int, active_idx: int, focused: bool) -> None:
    """Top tab bar: `▶ 1·Ext  2·Ctx  3·Prj  …` on the left, ` axt v0.2.0 ` on
    the right.

    Highlight tiers:
      - Bar focused:    leading `▶ ` marker + active tab is a solid cyan chip
                        (black-on-cyan, BOLD)
      - Bar unfocused:  leading `  ` (no marker) + active tab is bold cyan text
                        with underline (no fill) — clearly secondary
      - Inactive cells: dim
    """
    version_label = f" axt v{__version__} "
    version_w = cell_width(version_label)
    right_x = x + w - version_w
    if w > version_w + 4:
        safe_addnstr(stdscr, y, right_x, version_label, version_w, CP_CYAN() | curses.A_BOLD)

    cur = x
    marker = "▶ " if focused else "  "
    marker_attr = _safe_pair(8, curses.A_BOLD) if focused else CP_DIM()
    safe_addnstr(stdscr, y, cur, marker, w - (cur - x), marker_attr)
    cur += cell_width(marker)
    tab_limit = right_x if w > version_w + 4 else x + w
    # Active+focused = solid cyan chip (pair 1 = black-on-cyan + BOLD) — the
    # strongest cell on screen. Active+unfocused = bold cyan text with
    # underline (no fill) so it's clearly weaker than the focused chip but
    # still visibly different from inactive (dim) cells.
    active_focused = CP_ACTIVE_CHIP()
    active_unfocused = _safe_pair(8, curses.A_BOLD | curses.A_UNDERLINE)
    # Compute total cell width with full names; if it doesn't fit, fall back
    # to the short labels so a narrow terminal still shows every tab.
    full_widths = [cell_width(f" {i + 1}·{long} ") for i, (_, _short, long) in enumerate(MAIN_TABS)]
    use_full = (cur + sum(full_widths)) <= tab_limit
    for i, (_, short, long) in enumerate(MAIN_TABS):
        label = f"{i + 1}·{long if use_full else short}"
        cell = f" {label} "
        if i == active_idx:
            attr = active_focused if focused else active_unfocused
        else:
            attr = CP_DIM()
        if cur + cell_width(cell) > tab_limit:
            break
        safe_addnstr(stdscr, y, cur, cell, tab_limit - cur, attr)
        cur += cell_width(cell)
    if cur < tab_limit:
        safe_addnstr(stdscr, y, cur, " " * (tab_limit - cur), tab_limit - cur, CP_DIM())


@dataclass
class TableColumn:
    key: str
    label: str
    width: int


def render_title_bar(stdscr, y: int, h: int, w: int, title: str, *,
                     search: Optional[str] = None) -> tuple[int, int]:
    """Draw a full-width section / status TITLE at row ``y`` using ``CP_TITLE()``
    (the accent tier — never the dim ``CP_HDR()`` column-header tier), with an
    optional search-prompt row just below it, and return the body rectangle
    ``(body_y, body_h)`` left beneath the title band.

    This centralizes the "title row (+ optional search row) then content"
    geometry each tab used to hand-roll, so the reserved-row arithmetic lives
    in one place instead of drifting per renderer (the source of the earlier
    Vault blank-band / off-by-rows bugs).
    """
    safe_addnstr(stdscr, y, 0, fit_cells(title, w - 1), w - 1, CP_TITLE())
    used = 1
    if search is not None:
        safe_addnstr(stdscr, y + 1, 0, fit_cells(search, w - 1), w - 1,
                     CP_INFO() | curses.A_BOLD)
        used = 2
    return y + used, max(0, h - used)


def render_section_header(stdscr, y: int, w: int, label: str) -> None:
    """Draw a stacked-section header as a distinct band: a left block marker
    ``▌``, the label, then a ``─`` rule filling to the right edge.

    A bare ``CP_TITLE()`` text row is just bright text; when several stack
    above tables (the Context tab: Rate limits / Context sources / Project
    files) they blur into one block with no visible boundary. The marker plus
    the trailing rule make each section's start unmistakable in BOTH themes —
    without a reverse bar, which ``CP_TITLE()`` deliberately avoids on light
    backgrounds (a full-width solid fill reads as a glaring band on white).
    """
    prefix = f"▌ {label} "
    rule = "─" * max(0, (w - 1) - cell_width(prefix))
    safe_addnstr(stdscr, y, 0, fit_cells(prefix + rule, w - 1), w - 1, CP_TITLE())


def render_table(
    stdscr,
    y: int,
    x: int,
    h: int,
    w: int,
    columns: list[TableColumn],
    rows: list[dict[str, str]],
    *,
    selected: int,
    checked: Optional[set[int]] = None,
    show_header: bool = True,
    header_rule: bool = True,
    top_offset: int = 0,
) -> int:
    """Draw a table at (y, x, h, w). Returns the number of data rows drawn.

    Selection rendering — the whole reason this module exists — uses
    `curses.A_REVERSE` applied via addnstr to every cell on the selected row.
    Trailing whitespace is also written explicitly via fit_cells(), so a
    selected row's background is identical-width to a non-selected row's. No
    Yoga, no flex, no asymmetric trailing-pad: the WezTerm/cmux dropout
    cannot happen.
    """
    if h <= 0 or w <= 0:
        return 0

    # Header.
    header_h = 0
    if show_header:
        cursor = x
        if checked is not None:
            cursor += _draw_cell(stdscr, y, cursor, "■  ", 4, w - (cursor - x), CP_HDR())
        else:
            cursor += _draw_cell(stdscr, y, cursor, "#   ", 4, w - (cursor - x), CP_HDR())
        for col in columns:
            cursor += _draw_cell(stdscr, y, cursor, col.label, col.width + 2, w - (cursor - x), CP_HDR())
            if cursor - x >= w:
                break
        header_h = 1
        # Separator line under the header — suppressed when header_rule=False
        # so the header can attach directly to the first data row.
        if header_rule:
            safe_addnstr(stdscr, y + 1, x, "─" * max(0, w - 1), w - 1, CP_DIM())
            header_h = 2

    avail = h - header_h
    if avail <= 0:
        return 0

    # Virtual scrolling: keep selection in window.
    visible_start = top_offset
    visible_end = visible_start + avail
    if selected >= visible_end:
        visible_start = selected - avail + 1
        visible_end = visible_start + avail
    if selected < visible_start:
        visible_start = selected
        visible_end = visible_start + avail
    visible_start = max(0, min(visible_start, max(0, len(rows) - avail)))
    visible_end = min(visible_start + avail, len(rows))

    drawn = 0
    for vi, ri in enumerate(range(visible_start, visible_end)):
        row = rows[ri]
        sel = ri == selected
        row_y = y + header_h + vi
        row_attr = CP_SEL() if sel else 0
        # Prefix: 4 cells. Either checkbox or 1-based number with optional pointer.
        if checked is not None:
            on = ri in checked
            if sel:
                prefix = "▸■ " if on else "▸□ "
            else:
                prefix = " ■ " if on else " □ "
        else:
            num = str(ri + 1).rjust(2)
            prefix = f"▸{num} " if sel else f" {num} "
        cursor = x
        cursor += _draw_cell(stdscr, row_y, cursor, prefix, 4, w - (cursor - x), row_attr)
        for col in columns:
            value = row.get(col.key, "")
            cursor += _draw_cell(stdscr, row_y, cursor, value, col.width + 2, w - (cursor - x), row_attr)
            if cursor - x >= w:
                break
        # CRITICAL: fill the rest of the line with the row's background attr so
        # trailing-space symmetry matches between selected and non-selected.
        if cursor < x + w:
            safe_addnstr(stdscr, row_y, cursor, " " * (x + w - cursor), x + w - cursor, row_attr)
        drawn += 1
    return drawn


def _draw_cell(stdscr, y: int, x: int, text: str, width: int, max_w: int, attr: int) -> int:
    """Internal: draw a single column cell with fit_cells padding."""
    if max_w <= 0:
        return 0
    actual_w = min(width, max_w)
    safe_addnstr(stdscr, y, x, fit_cells(text, actual_w), actual_w, attr)
    return actual_w


def render_detail_panel(
    stdscr,
    y: int,
    x: int,
    h: int,
    w: int,
    title: Optional[str],
    fields: list[tuple[str, str]],
    *,
    scroll: int = 0,
    focused: bool = False,
) -> int:
    """Right-side detail panel. Boxed via plain ASCII `+ - |` borders, scrollable.

    Returns the scroll offset actually used after clamping to the content
    height — callers that track scroll in state should write this back so a
    held scroll key can't run past the last line into blank space."""
    if h <= 0 or w <= 0:
        return 0
    # Unfocused border uses the default fg *without* A_DIM. A_DIM (SGR 2 / faint)
    # is unreliable across terminals — some (e.g. plain TERM=xterm consoles)
    # render it near-invisible — so the structural box outline must not depend
    # on it. Focus is still signalled by cyan vs. the default fg.
    border_attr = CP_CYAN() if focused else _safe_pair(7)
    # Borders use plain ASCII (+, -, |) instead of Unicode box-drawing
    # (┌ ─ │ …). Box-drawing glyphs render inconsistently across terminals /
    # fonts (some consoles show them faint or blank), so a universal ASCII frame
    # guarantees the panel outline is visible everywhere.
    # Top border.
    safe_addnstr(stdscr, y, x, "+" + "-" * (w - 2) + "+", w, border_attr)
    if h >= 2:
        safe_addnstr(stdscr, y + h - 1, x, "+" + "-" * (w - 2) + "+", w, border_attr)
    # Side borders + content.
    inner_w = w - 4  # 2 for borders + 2 padding
    if inner_w <= 0:
        return 0

    # Build all content lines (title + blank + label:value pairs + wrapping).
    lines: list[tuple[str, int]] = []  # (text, attr)
    if title:
        lines.append((fit_cells(title, inner_w), CP_TITLE()))
        lines.append(("", 0))
    for label, value in fields:
        label_part = f"{label}: "
        label_w = cell_width(label_part)
        wrap_width = max(1, inner_w - label_w)
        value_lines = _wrap_to_cells(value or "—", wrap_width)
        first = label_part + (value_lines[0] if value_lines else "")
        lines.append((fit_cells(first, inner_w), 0))
        indent = " " * label_w
        for cont in value_lines[1:]:
            lines.append((fit_cells(indent + cont, inner_w), 0))

    # Render side borders + visible slice. Clamp scroll so the last line pins
    # to the bottom row — never scroll past the content into blank space.
    content_h = h - 2  # minus borders
    max_scroll = max(0, len(lines) - content_h)
    scroll = max(0, min(scroll, max_scroll))
    visible_lines = lines[scroll:scroll + content_h]
    for row_i in range(content_h):
        safe_addnstr(stdscr, y + 1 + row_i, x, "|", 1, border_attr)
        safe_addnstr(stdscr, y + 1 + row_i, x + w - 1, "|", 1, border_attr)
        if row_i < len(visible_lines):
            text, attr = visible_lines[row_i]
            safe_addnstr(stdscr, y + 1 + row_i, x + 2, text, inner_w, attr)
        else:
            safe_addnstr(stdscr, y + 1 + row_i, x + 2, " " * inner_w, inner_w, 0)
    return scroll


def _wrap_to_cells(text: str, max_cells: int) -> list[str]:
    """Wrap a string to lines of at most `max_cells` terminal cells."""
    if max_cells <= 0:
        return [text]
    out: list[str] = []
    current: list[str] = []
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if ch == "\n":
            out.append("".join(current))
            current = []
            used = 0
            continue
        if used + w > max_cells and current:
            out.append("".join(current))
            current = []
            used = 0
        current.append(ch)
        used += w
    if current:
        out.append("".join(current))
    return out if out else [""]


def render_status_bar(stdscr, y: int, w: int, shortcuts: str, status: str = "",
                      status_attr: Optional[int] = None) -> None:
    """Bottom shortcuts line.

    ``status_attr`` colors the status-message segment only (green for a
    completed action, red for a failure); the shortcut hints stay dim.
    """
    if not status:
        safe_addnstr(stdscr, y, 0, fit_cells(shortcuts, w - 1), w - 1, CP_DIM())
        return
    attr = CP_DIM() if status_attr is None else status_attr
    if len(status) + 3 + len(shortcuts) < w:
        # Status segment unpadded (fit_cells pads to full width, which would
        # leave no room for the shortcut tail drawn right after it).
        safe_addnstr(stdscr, y, 0, status, w - 1, attr)
        x = cell_width(status)
        tail_w = w - 1 - x
        if tail_w > 0:
            safe_addnstr(stdscr, y, x, fit_cells(f"  │  {shortcuts}", tail_w), tail_w, CP_DIM())
    else:
        safe_addnstr(stdscr, y, 0, fit_cells(status, w - 1), w - 1, attr)


def confirm_modal(stdscr, message: str, *, title: str = "Confirm") -> bool:
    """Centered y/N modal. Returns True on y/Enter, False on n/Esc.

    Used by destructive actions (skill unlink, plugin uninstall, marketplace
    remove). The default highlighted action is the safe one (No)."""
    h, w = stdscr.getmaxyx()
    lines = message.split("\n")
    box_w = min(w - 4, max(40, max(cell_width(l) for l in lines) + 6))
    box_h = min(h - 4, len(lines) + 5)
    y0 = max(0, (h - box_h) // 2)
    x0 = max(0, (w - box_w) // 2)
    try:
        win = curses.newwin(box_h, box_w, y0, x0)
    except curses.error:
        return False
    win.keypad(True)
    try:
        win.box()
        safe_addnstr(win, 0, max(2, (box_w - cell_width(title) - 2) // 2),
                     f" {title} ", box_w - 4, CP_ERR() | curses.A_BOLD)
        for i, line in enumerate(lines):
            safe_addnstr(win, 2 + i, 2, fit_cells(line, box_w - 4), box_w - 4, 0)
        safe_addnstr(win, box_h - 2, 2, fit_cells(" [y] Yes    [n/Esc] No ", box_w - 4), box_w - 4, curses.A_BOLD)
        win.refresh()
        while True:
            k = win.getch()
            if k in (ord("y"), ord("Y")) or is_enter(k):
                return True
            if k in (ord("n"), ord("N"), KEY_ESC):
                return False
    finally:
        del win
        stdscr.touchwin()
        stdscr.refresh()


def text_input_modal(stdscr, prompt: str, *, title: str = "Input", initial: str = "") -> Optional[str]:
    """Centered text-input modal. Returns the typed string, or None if Esc."""
    h, w = stdscr.getmaxyx()
    box_w = min(w - 4, max(50, cell_width(prompt) + 10))
    box_h = 7
    y0 = max(0, (h - box_h) // 2)
    x0 = max(0, (w - box_w) // 2)
    try:
        win = curses.newwin(box_h, box_w, y0, x0)
    except curses.error:
        return None
    win.keypad(True)
    buffer = initial
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    try:
        while True:
            win.erase()
            win.box()
            safe_addnstr(win, 0, max(2, (box_w - cell_width(title) - 2) // 2),
                         f" {title} ", box_w - 4, CP_TITLE())
            safe_addnstr(win, 2, 2, fit_cells(prompt, box_w - 4), box_w - 4, 0)
            safe_addnstr(win, 3, 2, fit_cells("> " + buffer, box_w - 4), box_w - 4, curses.A_BOLD)
            safe_addnstr(win, box_h - 2, 2, fit_cells(" Enter:ok  Esc:cancel ", box_w - 4), box_w - 4, CP_DIM())
            win.refresh()
            k = win.getch()
            if k == KEY_ESC:
                return None
            if is_enter(k):
                return buffer
            if k in (curses.KEY_BACKSPACE, KEY_BACKSPACE, 8):
                buffer = buffer[:-1]
                continue
            # Accept printable ASCII + tab characters.
            if 32 <= k < 127:
                buffer += chr(k)
    finally:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        del win
        stdscr.touchwin()
        stdscr.refresh()


def _modal_search_prompt(win, y: int, width: int) -> Optional[str]:
    """Read a search term at the modal footer line `y`.

    Shows a live `/term` prompt. Returns the typed string on Enter (may be
    empty → caller clears the search) or None on Esc (cancel, keep prior
    search). Backspace edits; only printable ASCII is accepted.
    """
    buf = ""
    while True:
        safe_addnstr(win, y, 2, " " * width, width, CP_DIM())
        safe_addnstr(win, y, 2, fit_cells("/" + buf, width), width, CP_TITLE())
        win.refresh()
        k = win.getch()
        if is_enter(k):
            return buf
        if k == KEY_ESC:
            return None
        if k in (curses.KEY_BACKSPACE, KEY_BACKSPACE, 8):
            buf = buf[:-1]
        elif 32 <= k < 127:
            buf += chr(k)


def _addstr_search_hl(win, y: int, x: int, text: str, max_w: int,
                      query: str, *, current: bool, base: int = 0) -> None:
    """Draw `text` fitted to `max_w` cells, highlighting case-insensitive
    occurrences of `query`. The current-match line uses a reverse attr; other
    matches use the mark color. Non-match segments use `base` (e.g. a section
    heading attr). Segments are placed by East-Asian cell width."""
    fitted = fit_cells(text, max_w)
    low = fitted.lower()
    hl = CP_SEL() if current else CP_MARK()
    col, i = x, 0
    while i < len(fitted):
        j = low.find(query, i)
        if j == -1:
            safe_addnstr(win, y, col, fitted[i:], max_w, base)
            return
        if j > i:
            seg = fitted[i:j]
            safe_addnstr(win, y, col, seg, max_w, base)
            col += cell_width(seg)
        mseg = fitted[j:j + len(query)]
        safe_addnstr(win, y, col, mseg, max_w, hl)
        col += cell_width(mseg)
        i = j + len(query)


def preview_modal(stdscr, content: str, *, title: str = "Preview",
                  heading_prefix: Optional[str] = None) -> None:
    """Scrollable full-screen overlay for long content (file body, hook output).

    j/k or arrows scroll; PgUp/PgDn page; g/G or Home/End jump top/bottom;
    q/Enter exit. / opens a case-insensitive search; n/N jump to the
    next/previous match; matches are highlighted and the footer shows
    [match i/N]. While a search is active Esc clears it first, then a second
    Esc closes the modal.

    Lines starting with ``heading_prefix`` render bold-cyan as section
    headings — for callers that concatenate several documents into one preview
    (e.g. Context Sources, hook stdout/stderr) so each section stands out.
    """
    h, w = stdscr.getmaxyx()
    box_w = min(w - 4, 120)
    box_h = h - 4
    y0 = max(0, (h - box_h) // 2)
    x0 = max(0, (w - box_w) // 2)
    try:
        win = curses.newwin(box_h, box_w, y0, x0)
    except curses.error:
        return
    win.keypad(True)
    inner_w = box_w - 4
    inner_h = box_h - 4  # title row + bottom hint row + 2 border lines
    # Pre-wrap. Heading flags stay parallel to raw_lines so wrapped
    # continuation segments of a heading keep the heading attr.
    raw_lines: list[str] = []
    raw_heads: list[bool] = []
    for src_line in content.splitlines():
        is_head = bool(heading_prefix) and src_line.startswith(heading_prefix)
        wrapped = _wrap_to_cells(src_line, inner_w - 5)  # leave room for line numbers
        for seg in (wrapped or [""]):
            raw_lines.append(seg)
            raw_heads.append(is_head)
    scroll = 0
    max_scroll = max(0, len(raw_lines) - inner_h)

    query = ""              # active (already-applied) search term, lowercased
    matches: list[int] = []  # indices into raw_lines containing `query`
    midx = -1               # current position within `matches` (-1 = none)

    def apply_search(term: str, anchor: int) -> None:
        """Set `query` to `term` and select the first match at/after `anchor`."""
        nonlocal query, matches, midx
        query = term
        matches = [i for i, ln in enumerate(raw_lines) if term and term in ln.lower()]
        if not matches:
            midx = -1
            return
        midx = next((j for j, i in enumerate(matches) if i >= anchor), 0)

    try:
        while True:
            win.erase()
            win.box()
            safe_addnstr(win, 0, max(2, (box_w - cell_width(title) - 2) // 2),
                         f" {title} ", box_w - 4, CP_TITLE())
            visible = raw_lines[scroll:scroll + inner_h]
            cur_line = matches[midx] if 0 <= midx < len(matches) else -1
            for i, ln in enumerate(visible):
                lineno = scroll + i + 1
                safe_addnstr(win, 2 + i, 2, fit_cells(f"{lineno:4d}", 4), 4, CP_DIM())
                base = (CP_CYAN() | curses.A_BOLD) if raw_heads[scroll + i] else 0
                if query and query in ln.lower():
                    _addstr_search_hl(win, 2 + i, 7, ln, inner_w - 5, query,
                                      current=(scroll + i == cur_line), base=base)
                else:
                    safe_addnstr(win, 2 + i, 7, fit_cells(ln, inner_w - 5), inner_w - 5, base)
            indicator = f"[{scroll + 1}-{scroll + len(visible)}/{len(raw_lines)}]"
            if query:
                tag = f"[match {midx + 1}/{len(matches)}]" if matches else "[no match]"
                indicator = f"{tag}  {indicator}"
            footer = " /:search  n/N:match  j/k ↑↓  PgUp/PgDn  g/G/Home/End  q/Enter:close "
            safe_addnstr(win, box_h - 2, 2, fit_cells(footer, box_w - 4), box_w - 4, CP_DIM())
            safe_addnstr(win, box_h - 2, max(2, box_w - cell_width(indicator) - 3), indicator, len(indicator), CP_DIM())
            win.refresh()
            k = win.getch()
            if k == ord("/"):
                term = _modal_search_prompt(win, box_h - 2, box_w - 4)
                if term is not None:
                    apply_search(term.lower(), scroll)
                    if matches:
                        scroll = min(max_scroll, matches[midx])
                continue
            if k in (ord("n"), ord("N")) and matches:
                midx = (midx + (1 if k == ord("n") else -1)) % len(matches)
                scroll = min(max_scroll, matches[midx])
                continue
            if k in (ord("q"), ord("Q")) or is_enter(k):
                return
            if k == KEY_ESC:
                if query:  # first Esc clears the search, keeping the modal open
                    query, matches, midx = "", [], -1
                    continue
                return
            if k in (ord("j"), curses.KEY_DOWN):
                scroll = min(max_scroll, scroll + 1)
            elif k in (ord("k"), curses.KEY_UP):
                scroll = max(0, scroll - 1)
            elif k == curses.KEY_NPAGE:
                scroll = min(max_scroll, scroll + inner_h)
            elif k == curses.KEY_PPAGE:
                scroll = max(0, scroll - inner_h)
            elif k in (ord("g"), curses.KEY_HOME):
                scroll = 0
            elif k in (ord("G"), curses.KEY_END):
                scroll = max_scroll
    finally:
        del win
        stdscr.touchwin()
        stdscr.refresh()


def open_in_editor(stdscr, path: os.PathLike[str] | str) -> bool:
    """Suspend curses, run $EDITOR (or `vi`) on `path`, then resume.

    Returns True on apparent success, False if no editor available. The
    suspend pattern matches cst's: endwin → spawn → endwin-recover.
    """
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    try:
        curses.endwin()
    except curses.error:
        pass
    try:
        rc = subprocess.call([editor, str(path)])
    except FileNotFoundError:
        # Re-init curses and bail.
        stdscr.clear()
        stdscr.refresh()
        return False
    # Refresh the terminal.
    stdscr.clear()
    stdscr.refresh()
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    return rc == 0


# ── terminal-window spawning (cst `open_in_new_terminal` port) ──────────────


def _applescript_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _popen_detached(argv: list[str], cwd: Optional[str] = None) -> None:
    """Spawn `argv` fully detached from the TUI (no stdio, own session)."""
    subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _activate_macos_app(app_name: str) -> None:
    """Bring a macOS app to the foreground via AppleScript. Fire-and-forget;
    failures are silent."""
    try:
        _popen_detached(["osascript", "-e",
                         f'tell application "{app_name}" to activate'])
    except OSError:
        pass


def cmux_open_mode_modal(stdscr) -> Optional[str]:
    """cmux open-mode chooser: workspace tab vs new window (cst port).

    Returns "workspace", "window", or None (cancel)."""
    h, w = stdscr.getmaxyx()
    box_w = min(56, max(40, w - 6))
    box_h = 7
    y0 = max(0, (h - box_h) // 2)
    x0 = max(0, (w - box_w) // 2)
    try:
        win = curses.newwin(box_h, box_w, y0, x0)
    except curses.error:
        return None
    win.keypad(True)
    try:
        win.box()
        title = " cmux: Open Mode "
        safe_addnstr(win, 0, max(2, (box_w - cell_width(title)) // 2), title,
                     box_w - 4, CP_TITLE())
        safe_addnstr(win, 2, 3, "[t] Workspace tab  (current window)", box_w - 6, 0)
        safe_addnstr(win, 3, 3, "[w] New window", box_w - 6, 0)
        safe_addnstr(win, box_h - 2, 3, " t / w / Esc cancel ", box_w - 6,
                     curses.A_BOLD)
        win.refresh()
        while True:
            k = win.getch()
            if k in (ord("t"), ord("T")) or is_enter(k):
                return "workspace"
            if k in (ord("w"), ord("W")):
                return "window"
            if k == KEY_ESC:
                return None
    finally:
        del win
        stdscr.touchwin()
        stdscr.refresh()


def _spawn_terminal_cmux(cwd: str, cmux_mode: str) -> tuple[bool, str]:
    """Open `cwd` in cmux: a workspace tab or a new window (cst port)."""
    cmux_bin = shutil.which("cmux")
    if not cmux_bin:
        return False, "cmux binary not found"
    try:
        if cmux_mode == "window":
            result = subprocess.run(
                [cmux_bin, "new-window"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return False, f"cmux new-window failed: {result.stderr.strip()}"
            parts = result.stdout.strip().split()
            win_id = parts[1] if len(parts) >= 2 else None
            if not win_id:
                return False, "cmux new-window returned no window id"
            ws_result = subprocess.run(
                [cmux_bin, "list-workspaces", "--window", win_id],
                capture_output=True, text=True, timeout=5,
            )
            ws_ref = None
            for line in ws_result.stdout.strip().splitlines():
                for tok in line.split():
                    if tok.startswith("workspace:"):
                        ws_ref = tok
                        break
                if ws_ref:
                    break
            if ws_ref:
                subprocess.run(
                    [cmux_bin, "send", "--workspace", ws_ref,
                     f"cd {shlex.quote(cwd)}\\n"],
                    capture_output=True, timeout=5,
                )
            return True, "opened in cmux window"
        _popen_detached([cmux_bin, "new-workspace",
                         "--name", f"axt:{os.path.basename(cwd) or cwd}",
                         "--cwd", cwd])
        return True, "opened in cmux workspace"
    except OSError as e:
        return False, f"cmux spawn failed: {e}"
    except subprocess.TimeoutExpired:
        return False, "cmux command timed out"


def spawn_terminal_at(cwd: str, cmux_mode: Optional[str] = None) -> tuple[bool, str]:
    """Open a new terminal window with an interactive shell at `cwd`.

    Port of cst's `open_in_new_terminal` adapter, minus the resume command:
    match the user's current terminal (TERM_PROGRAM) first, fall back to
    Terminal.app on macOS / a candidate list on Linux. Returns (ok, info);
    `info` names the terminal used or carries the error for the status toast.

    When `cmux_mode` is "workspace" or "window", open via cmux instead of a
    native terminal window.
    """
    if cmux_mode:
        return _spawn_terminal_cmux(cwd, cmux_mode)

    shell_cmd = f"cd {shlex.quote(cwd)}"

    if sys.platform == "darwin":
        tp = os.environ.get("TERM_PROGRAM", "")
        tp_l = tp.lower()
        escaped = _applescript_escape(shell_cmd)

        def _run_osascript(script: str, label: str) -> tuple[bool, str]:
            try:
                _popen_detached(["osascript", "-e", script])
                return True, f"opened in {label}"
            except OSError as e:
                return False, f"osascript failed: {e}"

        def _run_cli(argv: list[str], label: str,
                     activate_name: Optional[str] = None) -> tuple[bool, str]:
            try:
                _popen_detached(argv)
                if activate_name:
                    _activate_macos_app(activate_name)
                return True, f"opened in {label}"
            except OSError as e:
                return False, f"{label} spawn failed: {e}"

        terminal_app_script = (
            'tell application "Terminal"\n'
            '  activate\n'
            f'  do script "{escaped}"\n'
            "end tell"
        )
        iterm_script = (
            'tell application "iTerm"\n'
            '  activate\n'
            '  set newWindow to (create window with default profile)\n'
            f'  tell current session of newWindow to write text "{escaped}"\n'
            "end tell"
        )

        # Match the user's current terminal first.
        if "iterm" in tp_l:
            return _run_osascript(iterm_script, "iTerm")
        if "ghostty" in tp_l:
            p = shutil.which("ghostty")
            if p:
                return _run_cli([p, "--working-directory", cwd],
                                "Ghostty", activate_name="Ghostty")
        if "wezterm" in tp_l:
            p = shutil.which("wezterm")
            if p:
                return _run_cli([p, "start", "--cwd", cwd],
                                "WezTerm", activate_name="WezTerm")
        if "kitty" in tp_l:
            p = shutil.which("kitty")
            if p:
                return _run_cli([p, "--detach", "--directory", cwd],
                                "kitty", activate_name="kitty")
        if "alacritty" in tp_l:
            p = shutil.which("alacritty")
            if p:
                return _run_cli([p, "--working-directory", cwd],
                                "Alacritty", activate_name="Alacritty")
        if tp == "Apple_Terminal":
            return _run_osascript(terminal_app_script, "Terminal")
        if "warp" in tp_l:
            # Warp has no public scripting API; fall back to Terminal.app.
            ok, info = _run_osascript(terminal_app_script, "Terminal.app")
            return ok, f"{info}  (Warp is not scriptable)"
        if tp_l in ("vscode", "cursor"):
            ok, info = _run_osascript(terminal_app_script, "Terminal.app")
            return ok, f"{info}  (from {tp} integrated terminal)"

        # Unknown / unset TERM_PROGRAM → default to Terminal.app.
        ok, info = _run_osascript(terminal_app_script, "Terminal.app")
        suffix = f"  (unknown TERM_PROGRAM={tp!r})" if tp else ""
        return ok, info + suffix

    if sys.platform.startswith("linux"):
        candidates: list[str] = []
        env_term = os.environ.get("TERMINAL")
        if env_term:
            candidates.append(env_term)
        candidates.extend([
            "x-terminal-emulator", "gnome-terminal", "konsole",
            "alacritty", "kitty", "wezterm", "xterm",
        ])
        for term in candidates:
            path = shutil.which(term)
            if not path:
                continue
            try:
                if term == "gnome-terminal":
                    _popen_detached([path, "--working-directory", cwd])
                elif term == "konsole":
                    _popen_detached([path, "--workdir", cwd])
                elif term == "wezterm":
                    _popen_detached([path, "start", "--cwd", cwd])
                elif term == "kitty":
                    _popen_detached([path, "--detach", "--directory", cwd])
                elif term == "alacritty":
                    _popen_detached([path, "--working-directory", cwd])
                else:
                    # xterm, x-terminal-emulator, $TERMINAL, … — the spawned
                    # terminal starts its shell in the inherited cwd.
                    _popen_detached([path], cwd=cwd)
                return True, f"opened in {term}"
            except OSError:
                continue
        return False, "no supported terminal emulator found"

    return False, f"unsupported platform: {sys.platform}"


