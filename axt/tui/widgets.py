"""TUI common helpers + widgets — Sections 11-12 of the original monolith.

Self-contained: depends only on stdlib (curses, unicodedata, subprocess, os).
The ``__version__`` constant is duplicated from :mod:`axt._core` so this
module can be imported before ``_core`` finishes initialization (avoiding
the circular import that would happen if widgets.py needed
``axt._core.__version__`` at module level).
"""

from __future__ import annotations

import curses
import os
import subprocess
import unicodedata
from dataclasses import dataclass
from typing import Optional

# Duplicated to keep widgets.py independent of axt._core. The single source
# of truth is still axt._core.__version__ / axt.__version__ — the package
# mirror loop in axt/__init__.py re-exports the most-recent definition.
__version__ = "2.0.0"


# ── Section 11: TUI — Common helpers (curses, color, key, width) ────────────
#
# Why curses (vs. an Ink/React equivalent in Python):
#   The original Ink TUI bug ("selected row's ▸/# disappear under WezTerm + cmux")
#   was caused by Ink/Yoga's flex-layout writing rows of *different* trailing-
#   space widths depending on whether they had a background-affecting style.
#   Curses sidesteps the whole class of bugs by writing every cell explicitly
#   via addnstr(y, x, text, width, attr) — the way cst (claude-session-tracker)
#   does and never hits the same issue.



def tui_init_colors() -> None:
    """Initialize the standard 9-color palette. Safe to call multiple times."""
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    pairs = [
        (1, curses.COLOR_BLACK, curses.COLOR_CYAN),    # selection
        (2, curses.COLOR_YELLOW, -1),                  # header / accent
        (3, curses.COLOR_GREEN, -1),                   # success / active
        (4, curses.COLOR_BLUE, -1),                    # info
        (5, curses.COLOR_RED, -1),                     # danger / error
        (6, curses.COLOR_MAGENTA, -1),                 # mark
        (7, curses.COLOR_WHITE, -1),                   # dim
        (8, curses.COLOR_CYAN, -1),                    # secondary
    ]
    for n, fg, bg in pairs:
        try:
            curses.init_pair(n, fg, bg)
        except curses.error:
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


def CP_HDR() -> int:
    return _safe_pair(2, curses.A_BOLD)


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
    ("dashboard",  "Dash", "Dashboard"),
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
    active_focused = _safe_pair(1, curses.A_BOLD)
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


_SCOPE_CHIP_LABEL: dict[str, str] = {"project": "Project", "all": "All"}


def render_filter_chips(stdscr, y: int, x: int, w: int, scope: str) -> None:
    """Render the Scope filter chip on the header line.

    Layout:  `Scope: [Project]`  (left-aligned, single row)

    A chip whose value is the default (`project`) renders dim — it carries
    no information. A non-default chip renders BOLD cyan so the user can
    see at a glance that the view is filtered.
    """
    scope_label = _SCOPE_CHIP_LABEL.get(scope, scope.title())
    scope_attr = CP_CYAN() | curses.A_BOLD if scope != "project" else CP_DIM()

    cur = x
    label = "Scope: "
    safe_addnstr(stdscr, y, cur, label, w - (cur - x), CP_DIM())
    cur += cell_width(label)
    chip = f"[{scope_label}]"
    safe_addnstr(stdscr, y, cur, chip, w - (cur - x), scope_attr)


@dataclass
class TableColumn:
    key: str
    label: str
    width: int


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
        # Separator line.
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
) -> None:
    """Right-side detail panel. Boxed via simple `│` borders, scrollable."""
    if h <= 0 or w <= 0:
        return
    border_attr = CP_CYAN() if focused else CP_DIM()
    # Top border.
    safe_addnstr(stdscr, y, x, "┌" + "─" * (w - 2) + "┐", w, border_attr)
    if h >= 2:
        safe_addnstr(stdscr, y + h - 1, x, "└" + "─" * (w - 2) + "┘", w, border_attr)
    # Side borders + content.
    inner_w = w - 4  # 2 for borders + 2 padding
    if inner_w <= 0:
        return

    # Build all content lines (title + blank + label:value pairs + wrapping).
    lines: list[tuple[str, int]] = []  # (text, attr)
    if title:
        lines.append((fit_cells(title, inner_w), CP_HDR()))
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

    # Render side borders + visible slice.
    content_h = h - 2  # minus borders
    visible_lines = lines[scroll:scroll + content_h]
    for row_i in range(content_h):
        safe_addnstr(stdscr, y + 1 + row_i, x, "│", 1, border_attr)
        safe_addnstr(stdscr, y + 1 + row_i, x + w - 1, "│", 1, border_attr)
        if row_i < len(visible_lines):
            text, attr = visible_lines[row_i]
            safe_addnstr(stdscr, y + 1 + row_i, x + 2, text, inner_w, attr)
        else:
            safe_addnstr(stdscr, y + 1 + row_i, x + 2, " " * inner_w, inner_w, 0)


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


def render_status_bar(stdscr, y: int, w: int, shortcuts: str, status: str = "") -> None:
    """Bottom shortcuts line."""
    text = shortcuts
    if status:
        text = f"{status}  │  {shortcuts}" if len(status) + 3 + len(shortcuts) < w else status
    safe_addnstr(stdscr, y, 0, fit_cells(text, w - 1), w - 1, CP_DIM())


def show_modal(stdscr, message: str, title: str = "axt") -> None:
    """Centered modal with the given message. Press any key to dismiss."""
    h, w = stdscr.getmaxyx()
    lines = message.split("\n")
    box_w = min(w - 4, max(40, max(cell_width(l) for l in lines) + 4))
    box_h = min(h - 4, len(lines) + 4)
    y0 = max(0, (h - box_h) // 2)
    x0 = max(0, (w - box_w) // 2)
    try:
        win = curses.newwin(box_h, box_w, y0, x0)
    except curses.error:
        return
    win.keypad(True)
    win.box()
    safe_addnstr(win, 0, max(2, (box_w - cell_width(title) - 2) // 2), f" {title} ", box_w - 4, CP_HDR())
    for i, line in enumerate(lines):
        safe_addnstr(win, 2 + i, 2, fit_cells(line, box_w - 4), box_w - 4, 0)
    safe_addnstr(win, box_h - 2, 2, fit_cells(" Press any key… ", box_w - 4), box_w - 4, CP_DIM())
    win.refresh()
    win.getch()


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
                         f" {title} ", box_w - 4, CP_HDR())
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


def preview_modal(stdscr, content: str, *, title: str = "Preview") -> None:
    """Scrollable full-screen overlay for long content (file body, hook output).

    j/k or arrows scroll; PgUp/PgDn page; g/G jump top/bottom; q/Esc/Enter exit.
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
    # Pre-wrap.
    raw_lines: list[str] = []
    for src_line in content.splitlines():
        wrapped = _wrap_to_cells(src_line, inner_w - 5)  # leave room for line numbers
        raw_lines.extend(wrapped or [""])
    scroll = 0
    max_scroll = max(0, len(raw_lines) - inner_h)
    try:
        while True:
            win.erase()
            win.box()
            safe_addnstr(win, 0, max(2, (box_w - cell_width(title) - 2) // 2),
                         f" {title} ", box_w - 4, CP_HDR())
            visible = raw_lines[scroll:scroll + inner_h]
            for i, ln in enumerate(visible):
                lineno = scroll + i + 1
                safe_addnstr(win, 2 + i, 2, fit_cells(f"{lineno:4d}", 4), 4, CP_DIM())
                safe_addnstr(win, 2 + i, 7, fit_cells(ln, inner_w - 5), inner_w - 5, 0)
            indicator = f"[{scroll + 1}-{scroll + len(visible)}/{len(raw_lines)}]"
            footer = " j/k ↑↓  PgUp/PgDn  g/G  q/Enter:close "
            safe_addnstr(win, box_h - 2, 2, fit_cells(footer, box_w - 4), box_w - 4, CP_DIM())
            safe_addnstr(win, box_h - 2, max(2, box_w - cell_width(indicator) - 3), indicator, len(indicator), CP_DIM())
            win.refresh()
            k = win.getch()
            if k in (ord("q"), ord("Q"), KEY_ESC) or is_enter(k):
                return
            if k in (ord("j"), curses.KEY_DOWN):
                scroll = min(max_scroll, scroll + 1)
            elif k in (ord("k"), curses.KEY_UP):
                scroll = max(0, scroll - 1)
            elif k == curses.KEY_NPAGE:
                scroll = min(max_scroll, scroll + inner_h)
            elif k == curses.KEY_PPAGE:
                scroll = max(0, scroll - inner_h)
            elif k == ord("g"):
                scroll = 0
            elif k == ord("G"):
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


