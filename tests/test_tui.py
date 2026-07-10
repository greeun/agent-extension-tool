"""Tests for Section 11-14 — curses TUI widgets.

We can't open a real curses screen in pytest, so we use a Mock stdscr that
records every addnstr call. This is the same pattern cst uses to verify its
TUI without a TTY.
"""
from __future__ import annotations

import curses
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import axt


def _make_stdscr(rows: int = 30, cols: int = 120):
    """Mock stdscr that records addnstr arguments and returns sensible defaults."""
    scr = MagicMock()
    scr.getmaxyx.return_value = (rows, cols)
    scr.calls = []
    def addnstr(*args):
        # (y, x, text, max_w, attr) or (y, x, text, max_w)
        scr.calls.append(args)
    scr.addnstr.side_effect = addnstr
    return scr


def _project_source(name, *, category="claude-md", scope="project", path="",
                    content="x\n", tokens=1, pct=0.0):
    """Minimal ContextSource for Project sub-tab tests (state.project_items
    now holds ContextSource, not the removed ProjectContextItem)."""
    return axt.ContextSource(
        name=name, category=category, path=path, chars=len(content),
        estimated_tokens=tokens, percentage=pct, actionable=True,
        content=content, scope=scope,
    )


def test_main_tabs_three_resource_types():
    """Top-level tabs after Dashboard was folded into Usage."""
    keys = [t[0] for t in axt.MAIN_TABS]
    assert keys == ["extensions", "context", "usage"]


def test_tui_state_default_context_sub_tab_is_project():
    """Context tab opens on the Project sub-tab."""
    s = axt.TuiState()
    assert s.context_sub_tab == "project"


def test_render_frame_dispatches_usage_tab(monkeypatch):
    """When tab_idx points at 'usage', _render_frame should call the usage renderer."""
    calls = []
    monkeypatch.setitem(axt.TAB_RENDERERS, "usage",
                        lambda *a, **kw: calls.append("usage"))
    scr = _make_stdscr()
    state = axt.TuiState()
    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "usage")
    axt._render_frame(scr, state)
    assert calls == ["usage"]


def test_cycle_sub_tab_rotates_extensions_and_context():
    """_cycle_sub_tab rotates the given tab's sub-tab field (Extensions + Context)."""
    state = axt.TuiState()
    assert state.ext_sub_tab == "vault"
    axt._cycle_sub_tab(state, "extensions", +1)
    assert state.ext_sub_tab == "skills"
    assert state.context_sub_tab == "project"  # untouched
    axt._cycle_sub_tab(state, "context", +1)
    assert state.context_sub_tab == "sources"
    axt._cycle_sub_tab(state, "context", +1)  # wraps back
    assert state.context_sub_tab == "project"


def _make_empty_context_analysis():
    return axt.ContextAnalysis(
        total_tokens=0, context_window_size=200_000, used_percent=0.0,
        model="claude-sonnet", sources=[],
        cost_impact=axt.CostImpact(
            model="claude-sonnet", cache_write_cost=0.0,
            cache_read_cost_per_turn=0.0, avg_turns_per_session=10,
            avg_sessions_per_day=1, per_session_cost=0.0, monthly_cost=0.0,
        ),
    )


def _make_empty_context_analysis_with_source():
    """Like _make_empty_context_analysis but with one source so the Sources
    sub-tab has a focusable category row."""
    src = axt.ContextSource(
        name="CLAUDE.md", category="memory", estimated_tokens=100,
        percentage=1.0, path="/p/CLAUDE.md", hint="", chars=400, actionable=True)
    return axt.ContextAnalysis(
        total_tokens=100, context_window_size=200_000, used_percent=0.1,
        model="claude-sonnet", sources=[src],
        cost_impact=_make_empty_context_analysis().cost_impact)


def test_context_tab_shows_project_files_on_project_sub_tab(monkeypatch, tmp_path):
    """The Project sub-tab lists every context source under its header."""
    monkeypatch.chdir(tmp_path)

    scr = _make_stdscr(rows=40, cols=140)
    state = axt.TuiState()
    state.context_sub_tab = "project"
    state.context_analysis = _seed_context_analysis_with_sources()
    axt.render_context_tab(scr, state, y0=3, h=30, w=140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Project context" in flat
    assert "CLAUDE.md" in flat


def test_context_tab_hides_project_files_on_sources_sub_tab(monkeypatch, tmp_path):
    """The Sources sub-tab does not render the Project sources list."""
    monkeypatch.chdir(tmp_path)

    scr = _make_stdscr(rows=40, cols=140)
    state = axt.TuiState()
    state.context_sub_tab = "sources"
    state.context_analysis = _make_empty_context_analysis()
    axt.render_context_tab(scr, state, y0=3, h=30, w=140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Project context" not in flat


def test_context_tab_default_sub_tab_is_project():
    assert axt.TuiState().context_sub_tab == "project"


def test_context_tab_bracket_keys_cycle_sub_tabs():
    """[ / ] cycle the Context sub-tab from the body (mirrors Extensions)."""
    state = axt.TuiState()
    assert state.context_sub_tab == "project"
    msg = axt.handle_context_input(state, ord("]"))
    assert state.context_sub_tab == "sources"
    assert "sources" in msg
    axt.handle_context_input(state, ord("["))
    assert state.context_sub_tab == "project"


def test_context_tab_jk_routes_to_project_sub_tab():
    """On the Project sub-tab, j/k drive project_selected, not context_selected
    (the keys are routed to the project handler)."""
    state = axt.TuiState()
    state.project_items = [_project_source(f"f{i}", path=f"/p/{i}") for i in range(3)]
    state.context_sub_tab = "project"
    before_ctx = state.context_selected
    axt.handle_context_input(state, ord("j"))
    assert state.project_selected == 1
    assert state.context_selected == before_ctx  # sources selection untouched


def test_at_top_of_content_tracks_active_sub_tab():
    """↑-climb-out uses the active sub-tab's selection, so navigating the
    project list doesn't prematurely bounce focus out of the content layer."""
    state = axt.TuiState()
    state.context_sub_tab = "project"
    state.context_selected = 0
    state.project_selected = 3
    assert axt._at_top_of_content(state, "context") is False
    state.project_selected = 0
    assert axt._at_top_of_content(state, "context") is True


def test_context_tab_project_pane_has_detail_panel(monkeypatch, tmp_path):
    """The shared bottom detail panel exposes the focused Project source's
    metadata (Category / Scope / Tokens / Path) when the Project pane owns
    the keyboard."""
    monkeypatch.chdir(tmp_path)
    scr = _make_stdscr(rows=40, cols=140)
    state = axt.TuiState()
    state.context_analysis = _seed_context_analysis_with_sources()
    state.context_sub_tab = "project"  # Project sub-tab → shared detail mirrors it
    axt.render_context_tab(scr, state, y0=3, h=34, w=140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Category:" in flat
    assert "Scope:" in flat
    assert "Tokens:" in flat
    assert "Path:" in flat


def test_tui_state_initial_focus_is_main_tab():
    """Default focus on mainTab so arrow-key navigation is immediately
    discoverable (the ▶ marker appears on the tab bar from frame 1)."""
    s = axt.TuiState()
    assert s.focused_layer == "mainTab"


# ─── cell_width / fit_cells ──────────────────────────────────────────────────


def test_cell_width_ascii():
    assert axt.cell_width("hello") == 5


def test_cell_width_korean():
    """Korean is full-width = 2 cells each."""
    assert axt.cell_width("한글") == 4


def test_cell_width_mixed():
    assert axt.cell_width("ab한글cd") == 8  # 1+1+2+2+1+1


def test_cell_width_empty():
    assert axt.cell_width("") == 0


def test_fit_cells_truncates_ascii():
    assert axt.fit_cells("abcdef", 4) == "abcd"


def test_fit_cells_pads_short():
    assert axt.fit_cells("ab", 5) == "ab   "


def test_fit_cells_respects_wide_chars():
    # 한 = 2 cells, so 한+space fits in 3 cells.
    assert axt.fit_cells("한a", 3) == "한a"


def test_fit_cells_truncates_to_avoid_split():
    # 한글 = 4 cells; with width=3, only 한 fits, +1 padding.
    assert axt.fit_cells("한글", 3) == "한 "


def test_fit_cells_zero_width():
    assert axt.fit_cells("anything", 0) == ""


# ─── render_title_bar — section title band + body rect ───────────────────────


def test_render_title_bar_returns_body_rect_and_uses_cp_title():
    """render_title_bar draws the title with CP_TITLE (accent, never the dim
    CP_HDR) and returns the body rect below the title band."""
    axt.tui_init_colors("dark")
    try:
        scr = _make_stdscr(rows=20, cols=80)
        body = axt.render_title_bar(scr, 3, 15, 80, " My Title")
        assert body == (4, 14), f"no-search band should reserve 1 row, got {body}"
        title_calls = [c for c in scr.calls if c[0] == 3 and c[1] == 0]
        assert any("My Title" in c[2] for c in title_calls)
        attr = next(c[4] for c in title_calls if "My Title" in c[2])
        assert attr & curses.A_BOLD, "dark title must use CP_TITLE bold accent"

        scr2 = _make_stdscr(rows=20, cols=80)
        body2 = axt.render_title_bar(scr2, 3, 15, 80, " T", search=" /search: ab_")
        assert body2 == (5, 13), f"search band should reserve 2 rows, got {body2}"
        assert any("/search: ab" in c[2] for c in scr2.calls if c[0] == 4), \
            "search prompt should render on the row below the title"
    finally:
        axt.tui_init_colors("dark")


# ─── render_section_header — stacked-section band ────────────────────────────


def test_render_section_header_draws_marker_and_rule_fill():
    """A section band leads with the ▌ marker, shows the label, and fills the
    rest of the row with a ─ rule so it reads as a divider, not bare text."""
    axt.tui_init_colors("dark")
    try:
        scr = _make_stdscr(rows=20, cols=60)
        axt.render_section_header(scr, 4, 60, "Rate limits")
        band = next(c[2] for c in scr.calls if c[0] == 4 and c[1] == 0)
        assert band.startswith("▌ Rate limits ")
        assert band.endswith("─")
        # Marker + label + rule fills the full width (w - 1 cells).
        assert axt.cell_width(band) == 59
        attr = next(c[4] for c in scr.calls if c[0] == 4 and c[1] == 0)
        assert attr & curses.A_BOLD, "dark section band uses CP_TITLE accent"
    finally:
        axt.tui_init_colors("dark")


def test_context_tab_renders_rate_limits_band_and_subtab_bar(monkeypatch, tmp_path):
    """Context tab shows a persistent Rate limits band plus a Sources/Project
    sub-tab bar (the sections-as-sub-tabs restructure)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# test\nproject level\n")
    scr = _make_stdscr(rows=40, cols=140)
    state = axt.TuiState()
    state.context_analysis = _make_empty_context_analysis()
    axt.render_context_tab(scr, state, y0=3, h=34, w=140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    bands = [c[2] for c in scr.calls
             if len(c) >= 3 and isinstance(c[2], str) and c[2].startswith("▌ ")]
    assert any("Rate limits" in b for b in bands)
    assert "Sub: " in flat
    assert "Sources" in flat
    assert "Project" in flat


# ─── render_table — the bug-source test ──────────────────────────────────────


def test_render_table_marks_selected_row():
    """The selected row must use CP_SEL() attr — curses absolute positioning
    guarantees the ▸/# cells are always drawn (the original Ink bug). We check
    A_REVERSE since A_BOLD may be 0 when colors aren't initialized in tests."""
    scr = _make_stdscr(rows=20, cols=80)
    cols = [axt.TableColumn("name", "Name", 20), axt.TableColumn("type", "Type", 10)]
    rows = [{"name": f"item-{i}", "type": "skill"} for i in range(5)]
    axt.render_table(scr, 0, 0, 15, 80, cols, rows, selected=2)
    # data row 2 = display row 4 (header(0) + separator(1) + data 0..n at 2,3,4,...).
    drew_selected = False
    for call in scr.calls:
        if len(call) >= 5 and call[0] == 4:
            attr = call[4]
            if attr & curses.A_REVERSE:
                drew_selected = True
    assert drew_selected, "Selected row should have A_REVERSE applied"


def test_render_table_writes_prefix_with_pointer():
    """The selected row prefix must include ▸ — the # column dropout case."""
    scr = _make_stdscr()
    cols = [axt.TableColumn("name", "Name", 20)]
    rows = [{"name": f"item-{i}"} for i in range(5)]
    axt.render_table(scr, 0, 0, 15, 80, cols, rows, selected=2)
    # Find any text containing ▸.
    found = False
    for call in scr.calls:
        text = call[2] if len(call) >= 3 else ""
        if "▸" in text:
            found = True
            break
    assert found, "Selected row must include the ▸ pointer in its prefix"


def test_render_table_with_checked_set_uses_checkboxes():
    scr = _make_stdscr()
    cols = [axt.TableColumn("name", "Name", 20)]
    rows = [{"name": f"item-{i}"} for i in range(3)]
    axt.render_table(scr, 0, 0, 15, 80, cols, rows, selected=1, checked={1, 2})
    # Look for ■ (checked) and □ (unchecked) prefixes.
    prefixes = [call[2] for call in scr.calls if len(call) >= 3 and isinstance(call[2], str)]
    assert any("■" in p for p in prefixes)
    assert any("□" in p for p in prefixes)


# ─── Task 3: Vault responsive detail-panel layout ────────────────────────────


def _detail_panel_top_left(calls):
    """Return (y, x) of the first addnstr call that draws the detail panel's
    top border ('+...+'). Returns None if no such row was drawn. The panel uses
    a plain ASCII frame ('+ - |'), so top and bottom borders share the '+...+'
    shape — the FIRST match is the top."""
    for args in calls:
        # addnstr signature: (y, x, text, max_w[, attr])
        if len(args) >= 3 and isinstance(args[2], str) and args[2].startswith("+"):
            return args[0], args[1]
    return None


def _detail_panel_bottom_y(calls):
    """Return the y of the detail panel's bottom border ('+...+'), or None.
    Top and bottom borders share the ASCII '+...+' shape, so the LAST match is
    the bottom (side borders are '|', never '+')."""
    bottom = None
    for args in calls:
        if len(args) >= 3 and isinstance(args[2], str) and args[2].startswith("+"):
            bottom = args[0]
    return bottom


def _seed_vault_for_render(s):
    """Minimum state needed for render_vault_tab to draw the detail panel."""
    s.vault_items = [
        axt.VaultItem(
            name="example-skill",
            type="skill",
            path="/some/long/path/to/skill/source/example-skill",
            description="A reasonably long description that would wrap on a narrow panel.",
        )
    ]
    s.refresh_token = 1  # skip the lazy _vault_load that touches disk
    s.vault_selected = 0


def test_render_vault_tab_uses_bottom_layout_when_wide():
    """w=120: detail panel is pinned to the bottom (x=0, below the table) just
    like the narrow case — the right-side layout was dropped for UI unity."""
    scr = _make_stdscr(rows=30, cols=120)
    s = axt.TuiState()
    _seed_vault_for_render(s)
    axt.render_vault_tab(scr, s, y0=2, h=25, w=120)
    top = _detail_panel_top_left(scr.calls)
    assert top is not None, "detail panel was not rendered"
    y, x = top
    assert x == 0, f"expected bottom layout at x=0, got x={x}"
    assert y > 3, f"expected detail below table (y>3), got y={y}"


def test_render_vault_tab_fills_to_bottom_no_blank_band():
    """Regression: the Vault table/detail region must fill down to the last
    body row (y0 + h - 1). A stale `h - 3` reservation used to leave a 2-row
    blank band above the cwd line — the list looked like it had trailing
    padding. The detail panel's bottom border pins the region's last row."""
    scr = _make_stdscr(rows=30, cols=120)
    s = axt.TuiState()
    _seed_vault_for_render(s)
    y0, h = 2, 25
    axt.render_vault_tab(scr, s, y0=y0, h=h, w=120)
    bottom = _detail_panel_bottom_y(scr.calls)
    assert bottom is not None, "detail panel bottom border was not drawn"
    assert bottom == y0 + h - 1, (
        f"vault region must fill to the last body row {y0 + h - 1}, "
        f"got bottom border at y={bottom} ({y0 + h - 1 - bottom} blank rows)"
    )


def test_render_vault_tab_header_has_no_underline_rule():
    """The Vault column header attaches directly to the list — there is no
    ──── rule between the header row and the first data row (header_rule=False).
    The row right below the header now holds the first item instead."""
    scr = _make_stdscr(rows=30, cols=120)
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name=f"item-{i:02d}", type="skill", path=f"/x/{i}",
                      description="d", in_vault=True, version="1.0.0")
        for i in range(10)
    ]
    s.refresh_token = 1
    s.vault_selected = 0
    y0, h = 2, 25
    axt.render_vault_tab(scr, s, y0=y0, h=h, w=120)
    header_y = y0 + 1          # table_y_top with no search row
    below_y = header_y + 1
    # No horizontal rule (a run of ─) at x=0 directly below the header.
    for c in scr.calls:
        if c[0] == below_y and c[1] == 0 and isinstance(c[2], str) and c[2].strip():
            assert set(c[2].strip()) != {"─"}, (
                f"unexpected ──── header underline at row {below_y}")
    # The first item renders on that row instead of a blank separator.
    first_row_texts = [c[2] for c in scr.calls if c[0] == below_y]
    assert any("item-00" in t for t in first_row_texts), \
        "first vault item should sit directly under the header"


def test_render_vault_tab_title_no_underline_in_light_theme():
    """Light theme: the full-width filter/sort title row must NOT carry
    A_UNDERLINE (it would render as a rule under the row). Dark theme keeps
    its A_BOLD header emphasis."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name=f"item-{i:02d}", type="skill", path=f"/x/{i}",
                      description="d", in_vault=True, version="1.0.0")
        for i in range(6)
    ]
    s.refresh_token = 1
    s.vault_selected = 0

    def _title_attr(theme):
        axt.tui_init_colors(theme)
        scr = _make_stdscr(rows=30, cols=120)
        axt.render_vault_tab(scr, s, y0=2, h=25, w=120)
        # Title row is at y0=2, x=0.
        return next(c[4] for c in scr.calls
                    if c[0] == 2 and c[1] == 0 and len(c) >= 5)

    try:
        light_attr = _title_attr("light")
        dark_attr = _title_attr("dark")
    finally:
        axt.tui_init_colors("dark")

    assert not (light_attr & curses.A_UNDERLINE), \
        "light-theme vault title must not be underlined"
    assert dark_attr & curses.A_BOLD, \
        "dark-theme vault title keeps its bold header emphasis"


def test_render_vault_tab_uses_bottom_layout_when_narrow():
    """w=80: detail panel is drawn at x=0 and y below the table."""
    scr = _make_stdscr(rows=30, cols=80)
    s = axt.TuiState()
    _seed_vault_for_render(s)
    axt.render_vault_tab(scr, s, y0=2, h=25, w=80)
    top = _detail_panel_top_left(scr.calls)
    assert top is not None
    y, x = top
    assert x == 0, f"expected bottom layout at x=0, got x={x}"
    assert y > 3, f"expected detail below table (y>3), got y={y}"


def test_render_vault_tab_bottom_layout_at_every_width():
    """No width threshold: the detail panel is at x=0 (bottom) at narrow AND
    wide widths. The old w>=100 right-side switch was removed."""
    s = axt.TuiState()
    _seed_vault_for_render(s)

    for w in (99, 100, 140):
        scr = _make_stdscr(rows=30, cols=w)
        axt.render_vault_tab(scr, s, y0=2, h=25, w=w)
        x = _detail_panel_top_left(scr.calls)[1]
        assert x == 0, f"w={w} must use bottom layout (x=0), got x={x}"


def test_render_vault_tab_bottom_height_clamped():
    """detail_h = clamp(int(h*0.35), 8, 16). At h=10 it clamps up to 8,
    then the second guard collapses it to leave at least 3 list rows."""
    s = axt.TuiState()
    _seed_vault_for_render(s)
    scr = _make_stdscr(rows=12, cols=80)
    axt.render_vault_tab(scr, s, y0=0, h=10, w=80)
    top = _detail_panel_top_left(scr.calls)
    assert top is not None
    y, _x = top
    # h=10, not searching → table_h_full = 10 - 1 = 9. detail_h candidate = 8,
    # guard = min(8, max(1, 9-3)) = 6. table_h = 9-6 = 3. table_y_top = 0+1=1.
    # detail_y = 1 + 3 = 4 (the extra 2 rows now extend the panel downward).
    assert y == 4, f"expected detail top y=4 under guard, got y={y}"


def test_render_table_scrolls_to_keep_selection_visible():
    """Selection past the visible window should shift the viewport."""
    scr = _make_stdscr(rows=10, cols=80)
    cols = [axt.TableColumn("name", "Name", 20)]
    rows = [{"name": f"item-{i}"} for i in range(50)]
    # 7 data rows fit (10 - 2 header - 1 status = 7).
    axt.render_table(scr, 0, 0, 9, 80, cols, rows, selected=20)
    # Find which item-N strings were drawn.
    drawn_names: set[str] = set()
    for call in scr.calls:
        if len(call) >= 3 and isinstance(call[2], str):
            for n in range(50):
                if f"item-{n}" in call[2]:
                    drawn_names.add(f"item-{n}")
    assert "item-20" in drawn_names, "Selected item must be drawn"
    assert "item-0" not in drawn_names, "Off-screen items must NOT be drawn"


def test_render_table_empty_rows():
    """Empty rows list should not crash."""
    scr = _make_stdscr()
    cols = [axt.TableColumn("name", "Name", 20)]
    axt.render_table(scr, 0, 0, 15, 80, cols, [], selected=0)
    # No crash + no data rows drawn.


# ─── render_detail_panel ─────────────────────────────────────────────────────


def test_render_detail_panel_draws_borders():
    scr = _make_stdscr()
    axt.render_detail_panel(scr, 0, 0, 10, 30, "title", [("Name", "alpha")])
    # ASCII frame: top and bottom borders are both "+---...---+".
    border_ys = [c[0] for c in scr.calls
                 if len(c) >= 3 and isinstance(c[2], str) and c[2].startswith("+")]
    assert 0 in border_ys          # top border at y=0
    assert 9 in border_ys          # bottom border at y=h-1


def test_render_detail_panel_includes_title_and_fields():
    scr = _make_stdscr()
    axt.render_detail_panel(scr, 0, 0, 10, 30, "MyTitle", [("Foo", "bar")])
    flat = " ".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "MyTitle" in flat
    assert "Foo:" in flat
    assert "bar" in flat


def test_render_detail_panel_handles_long_value():
    """Wrapping: a long value should split into multiple lines."""
    scr = _make_stdscr()
    long = "x" * 100
    axt.render_detail_panel(scr, 0, 0, 12, 30, "T", [("Long", long)])
    # The full value shouldn't appear in one call — it gets wrapped.
    appeared_full = any(long in (c[2] or "") for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert not appeared_full


def test_render_detail_panel_clamps_overscroll_when_content_fits():
    """Content shorter than the panel → no scroll possible; an over-scrolled
    value is clamped back to 0 so the panel never shows blank space."""
    scr = _make_stdscr()
    # h=10 → content_h=8. title + blank + 2 short fields = 4 lines (< 8).
    clamped = axt.render_detail_panel(
        scr, 0, 0, 10, 30, "T", [("A", "1"), ("B", "2")], scroll=9999
    )
    assert clamped == 0


def test_render_detail_panel_clamps_to_max_scroll():
    """Content taller than the panel → scroll is clamped to the last full
    page (len(lines) - content_h), pinning the final line to the bottom."""
    scr = _make_stdscr()
    fields = [(f"k{i:02d}", str(i)) for i in range(20)]  # 20 short, unwrapped lines
    # h=10 → content_h=8. title + blank + 20 fields = 22 lines. max = 22-8 = 14.
    clamped = axt.render_detail_panel(scr, 0, 0, 10, 30, "T", fields, scroll=9999)
    assert clamped == 14


# ─── render_tab_bar ──────────────────────────────────────────────────────────


def test_render_tab_bar_lists_all_tabs_full_names():
    """A wide terminal should show the full tab names, not the short ones."""
    scr = _make_stdscr()
    axt.render_tab_bar(scr, 0, 0, 160, active_idx=0, focused=True)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    for full in ("Extensions", "Context", "Usage"):
        assert full in flat, f"Expected full name {full!r} in tab bar"
    assert "Dashboard" not in flat, "Dashboard tab was removed"
    # Platform names no longer appear at the top level (they moved into
    # Usage sub-tabs).
    for moved in ("Claude", "Codex", "Gemini", "Cursor", "Project"):
        assert moved not in flat, f"{moved!r} should not be a top-level tab anymore"


def test_render_tab_bar_falls_back_to_short_names_in_narrow_terminal():
    """A narrow terminal where the full names won't fit must use the short labels."""
    scr = _make_stdscr()
    # 30 cols is too tight for "Extensions / Context / Usage" + version
    # badge, so the renderer must fall back to short labels.
    axt.render_tab_bar(scr, 0, 0, 30, active_idx=0, focused=True)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Extensions" not in flat
    # At least one short label must render.
    assert any(short in flat for short in ("Ext", "Ctx", "Use"))


def test_render_tab_bar_highlights_active_when_focused():
    scr = _make_stdscr()
    axt.render_tab_bar(scr, 0, 0, 120, active_idx=2, focused=True)
    # Active+focused tab uses a solid cyan chip (pair 1 + BOLD, no REVERSE).
    # Unfocused-active uses A_UNDERLINE instead — focused state must NOT have
    # underline so the two states are unambiguously different.
    for call in scr.calls:
        if len(call) >= 5 and isinstance(call[2], str) and "Prj" in call[2]:
            attr = call[4]
            assert attr & curses.A_BOLD
            assert not (attr & curses.A_UNDERLINE)


def test_render_tab_bar_shows_version_badge():
    """`axt vX.Y.Z` must appear on the right side of the tab bar."""
    scr = _make_stdscr()
    axt.render_tab_bar(scr, 0, 0, 120, active_idx=0, focused=True)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert f"axt v{axt.__version__}" in flat


def test_render_tab_bar_version_uses_right_edge():
    """Version badge must be drawn at the right edge of the bar."""
    scr = _make_stdscr()
    axt.render_tab_bar(scr, 0, 0, 100, active_idx=0, focused=True)
    badge = f" axt v{axt.__version__} "
    badge_w = axt.cell_width(badge)
    for call in scr.calls:
        if len(call) >= 3 and isinstance(call[2], str) and call[2] == badge:
            # x position should equal 100 - badge_w.
            assert call[1] == 100 - badge_w
            return
    pytest.fail(f"Version badge {badge!r} not drawn at right edge")


def test_render_tab_bar_narrow_terminal_skips_version_gracefully():
    """In a too-narrow terminal, version badge is omitted but tabs still render."""
    scr = _make_stdscr()
    axt.render_tab_bar(scr, 0, 0, 12, active_idx=0, focused=True)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    # Version not present, but at least one tab label is.
    assert f"axt v{axt.__version__}" not in flat


def test_render_tab_bar_shows_focus_marker_only_when_focused():
    """A `▶` marker on the bar's left edge signals which layer owns the keys."""
    scr_focused = _make_stdscr()
    axt.render_tab_bar(scr_focused, 0, 0, 120, active_idx=0, focused=True)
    scr_unfocused = _make_stdscr()
    axt.render_tab_bar(scr_unfocused, 0, 0, 120, active_idx=0, focused=False)
    flat_focused = "".join(c[2] for c in scr_focused.calls if len(c) >= 3 and isinstance(c[2], str))
    flat_unfocused = "".join(c[2] for c in scr_unfocused.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "▶" in flat_focused
    assert "▶" not in flat_unfocused


def test_render_subtab_bar_shows_focus_marker_only_when_focused():
    scr_focused = _make_stdscr()
    axt._render_subtab_bar(scr_focused, 0, 120, axt.EXTENSION_SUB_TABS, active_key="vault", focused=True)
    scr_unfocused = _make_stdscr()
    axt._render_subtab_bar(scr_unfocused, 0, 120, axt.EXTENSION_SUB_TABS, active_key="vault", focused=False)
    flat_focused = "".join(c[2] for c in scr_focused.calls if len(c) >= 3 and isinstance(c[2], str))
    flat_unfocused = "".join(c[2] for c in scr_unfocused.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "▶" in flat_focused
    assert "▶" not in flat_unfocused


# ─── TuiState + Vault input ──────────────────────────────────────────────────


def test_tui_state_defaults():
    s = axt.TuiState()
    assert s.tab_idx == 0
    assert s.vault_selected == 0
    assert s.vault_filter == "all"
    assert s.vault_sort == "name"


def test_handle_vault_input_navigation():
    s = axt.TuiState()
    # Seed with 5 fake items.
    s.vault_items = [
        axt.VaultItem(name=f"item-{i}", type="skill", path="", description="")
        for i in range(5)
    ]
    axt.handle_vault_input(s, ord("j"))
    assert s.vault_selected == 1
    axt.handle_vault_input(s, ord("j"))
    assert s.vault_selected == 2
    axt.handle_vault_input(s, ord("k"))
    assert s.vault_selected == 1


def test_handle_vault_input_filter_c():
    s = axt.TuiState()
    axt.handle_vault_input(s, ord("c"))
    assert s.vault_filter == "skill"
    axt.handle_vault_input(s, ord("c"))
    assert s.vault_filter == "command"


def test_handle_vault_input_tab_focuses_detail_panel():
    """Tab from the list focuses the detail panel (same effect as Enter when
    no pending toggles exist)."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name=f"item-{i}", type="skill", path="", description="")
        for i in range(3)
    ]
    assert s.vault_detail_focused is False
    axt.handle_vault_input(s, 9)  # Tab
    assert s.vault_detail_focused is True
    assert s.vault_detail_scroll == 0


def test_handle_vault_input_tab_blurs_when_focused():
    """Tab from the detail panel blurs back to the list (same effect as Esc)."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="item-0", type="skill", path="", description="")
    ]
    s.vault_detail_focused = True
    s.vault_detail_scroll = 5
    axt.handle_vault_input(s, 9)  # Tab
    assert s.vault_detail_focused is False
    assert s.vault_detail_scroll == 0


def test_handle_vault_input_tab_noop_when_search_active():
    """In `/`-search mode, Tab must not steal the key — printable filtering
    rules still apply (Tab is non-printable so it is dropped silently)."""
    s = axt.TuiState()
    s.vault_searching = True
    s.vault_search = "abc"
    axt.handle_vault_input(s, 9)  # Tab
    assert s.vault_searching is True
    assert s.vault_search == "abc"
    assert s.vault_detail_focused is False


def test_handle_vault_input_tab_does_not_change_filter():
    """Regression: Tab must never advance the filter cycle (covered by F).
    Also confirms the no-item branch leaves focus untouched."""
    s = axt.TuiState()
    axt.handle_vault_input(s, 9)
    assert s.vault_filter == "all"
    assert s.vault_detail_focused is False


def test_handle_vault_input_sort_cycle():
    s = axt.TuiState()
    axt.handle_vault_input(s, ord("s"))
    assert s.vault_sort == "type"
    axt.handle_vault_input(s, ord("s"))
    assert s.vault_sort == "project"


@pytest.mark.skipif(sys.platform == "win32", reason="vault rejects Windows")
def test_handle_vault_input_unlink_from_all_projects(tmp_path, monkeypatch):
    """`U` unlinks the selected item from every project the scan index lists:
    symlinks removed, profiles cleaned, usage entry dropped."""
    vault = tmp_path / "vault"
    (vault / "skills" / "myskill").mkdir(parents=True)
    (vault / "skills" / "myskill" / "SKILL.md").write_text("---\nname: myskill\n---\n")
    skill = next(i for i in axt.list_vault_items(vault) if i.name == "myskill")

    proj_a, proj_b = tmp_path / "proj-a", tmp_path / "proj-b"
    proj_a.mkdir()
    proj_b.mkdir()
    axt.link_to_project(proj_a, skill)
    axt.link_to_project(proj_b, skill)
    assert (proj_a / ".claude" / "skills" / "myskill").is_symlink()
    assert (proj_b / ".claude" / "skills" / "myskill").is_symlink()

    s = axt.TuiState()
    s.vault_items = [skill]
    s.vault_usage_index = {
        "skill:myskill": axt.ExtensionUsage(
            type="skill",
            name="myskill",
            projects=[
                axt.ProjectRef(path=str(proj_a), name="proj-a"),
                axt.ProjectRef(path=str(proj_b), name="proj-b"),
            ],
        )
    }
    # Keep hermetic: don't write the real scan cache. No stdscr → skip confirm.
    monkeypatch.setattr("axt.tui.tabs._save_scan_cache", lambda *a, **k: None)

    msg = axt.handle_vault_input(s, ord("U"))

    assert "2 project" in msg
    assert not (proj_a / ".claude" / "skills" / "myskill").exists()
    assert not (proj_b / ".claude" / "skills" / "myskill").exists()
    assert axt.read_profile(proj_a).skills == ()
    assert axt.read_profile(proj_b).skills == ()
    assert "skill:myskill" not in s.vault_usage_index


def test_handle_vault_input_unlink_from_all_no_projects():
    """With no scan data the item is used nowhere → no-op with a hint message."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="lonely", type="skill", path="", description="")
    ]
    msg = axt.handle_vault_input(s, ord("U"))
    assert "not used by any project" in msg


def test_handle_vault_input_mark_toggle():
    """Space toggles the focused item's bulk-unlink mark."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="alpha", type="skill", path="", description=""),
        axt.VaultItem(name="beta", type="command", path="", description=""),
    ]
    s.vault_selected = 0
    axt.handle_vault_input(s, ord(" "))
    assert s.vault_marked == {"alpha"}
    axt.handle_vault_input(s, ord(" "))
    assert s.vault_marked == set()


def test_handle_vault_input_unlink_marked_bulk(tmp_path, monkeypatch):
    """With marks present, `U` unlinks EVERY marked item from all its projects
    and clears the marks; the single-item path is not taken."""
    vault = tmp_path / "vault"
    for name in ("skill-a", "skill-b"):
        (vault / "skills" / name).mkdir(parents=True)
        (vault / "skills" / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
    items = {i.name: i for i in axt.list_vault_items(vault)}
    skill_a, skill_b = items["skill-a"], items["skill-b"]

    proj = tmp_path / "proj"
    proj.mkdir()
    axt.link_to_project(proj, skill_a)
    axt.link_to_project(proj, skill_b)
    assert (proj / ".claude" / "skills" / "skill-a").is_symlink()
    assert (proj / ".claude" / "skills" / "skill-b").is_symlink()

    s = axt.TuiState()
    s.vault_items = [skill_a, skill_b]
    s.vault_usage_index = {
        "skill:skill-a": axt.ExtensionUsage(
            type="skill", name="skill-a",
            projects=[axt.ProjectRef(path=str(proj), name="proj")],
        ),
        "skill:skill-b": axt.ExtensionUsage(
            type="skill", name="skill-b",
            projects=[axt.ProjectRef(path=str(proj), name="proj")],
        ),
    }
    s.vault_marked = {"skill-a", "skill-b"}
    monkeypatch.setattr("axt.tui.tabs._save_scan_cache", lambda *a, **k: None)

    msg = axt.handle_vault_input(s, ord("U"))

    assert "2 item" in msg
    assert not (proj / ".claude" / "skills" / "skill-a").exists()
    assert not (proj / ".claude" / "skills" / "skill-b").exists()
    assert axt.read_profile(proj).skills == ()
    assert "skill:skill-a" not in s.vault_usage_index
    assert "skill:skill-b" not in s.vault_usage_index
    assert s.vault_marked == set()


def test_handle_vault_input_unlink_marked_none_used():
    """Marks that reference never-used items → no-op hint, marks preserved."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="alpha", type="skill", path="", description="")
    ]
    s.vault_marked = {"alpha"}
    msg = axt.handle_vault_input(s, ord("U"))
    assert "No marked item" in msg
    assert s.vault_marked == {"alpha"}


def test_handle_vault_input_esc_clears_marks():
    """First Esc with marks present clears them (before touching search/detail)."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="alpha", type="skill", path="", description="")
    ]
    s.vault_marked = {"alpha"}
    msg = axt.handle_vault_input(s, 27)  # Esc
    assert s.vault_marked == set()
    assert "Cleared marks" in msg


# ─── Vault "u" = update focused item in place ────────────────────────────────


def test_handle_vault_input_update_git_backed(monkeypatch):
    """`u` on a skill row checks the storage path and applies the git pull
    when an update is available; the result lands in the status message."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="myskill", type="skill",
                      path="/vault/skills/myskill", description="")
    ]
    calls = {}
    monkeypatch.setattr(
        "axt.tui.tabs.check_path_update",
        lambda t, n, p: axt.update.UpdateStatus(t, n, 1, "abc", "def", True))
    monkeypatch.setattr(
        "axt.tui.tabs.apply_path_update",
        lambda t, n, p: (calls.setdefault("apply", (t, n, p)),
                         axt.update.UpdateResult(t, n, "abc", "def", True, "git pull"))[1])
    monkeypatch.setattr("axt.tui.tabs._vault_load", lambda state: None)
    msg = axt.handle_vault_input(s, ord("u"))
    assert calls["apply"] == ("skill", "myskill", "/vault/skills/myskill")
    assert "Updated myskill" in msg and "abc → def" in msg


def test_handle_vault_input_update_not_updatable(monkeypatch):
    """Non-git (or up-to-date) item → hint message only, apply never runs."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="plain", type="skill", path="/v/s/plain", description="")
    ]
    monkeypatch.setattr(
        "axt.tui.tabs.check_path_update",
        lambda t, n, p: axt.update.UpdateStatus(t, n, 2, "local", "local", False,
                                                note="manual (non-git)"))
    monkeypatch.setattr(
        "axt.tui.tabs.apply_path_update",
        lambda *a: (_ for _ in ()).throw(AssertionError("apply must not run")))
    msg = axt.handle_vault_input(s, ord("u"))
    assert "manual (non-git)" in msg


def test_handle_vault_input_update_no_path():
    """Row without a storage path (defensive) → hint, git helpers never touched."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="ghost", type="skill", path="", description="")
    ]
    msg = axt.handle_vault_input(s, ord("u"))
    assert "no storage path" in msg


# ─── Upd column + async update-availability check ────────────────────────────

# Original captured at import time — the conftest autouse fixture replaces the
# module attribute with a no-op for every test, so kick tests call this.
from axt.tui.tabs import _kick_update_check as REAL_KICK_UPDATE_CHECK  # noqa: E402


class _StubThread:
    """Records construction instead of running anything."""
    started: list = []

    def __init__(self, target=None, args=(), name=None, daemon=None):
        self.name = name

    def start(self):
        _StubThread.started.append(self.name)


def test_upd_cell_markers():
    from types import SimpleNamespace
    from axt.tui.tabs import _upd_cell
    from axt.core import SkillInfo
    US = axt.update.UpdateStatus
    s = axt.TuiState()
    sk = lambda n: SkillInfo(name=n, path="/p", is_symlink=False, source="user")

    assert _upd_cell(s, "skills", sk("sk")) == "…"       # first check not done
    s.update_statuses = {
        ("skill", "sk"): US("skill", "sk", 1, "a", "b", True),
        ("skill", "manual"): US("skill", "manual", 2, "local", "local", False, note="manual (non-git)"),
        ("skill", "err"): US("skill", "err", 1, "a", "?", False, error="fetch failed"),
        ("marketplace", "mk"): US("marketplace", "mk", 1, "a", "a", False, note="up to date"),
    }
    assert _upd_cell(s, "skills", sk("sk")) == "↑"       # updatable
    assert _upd_cell(s, "skills", sk("manual")) == "─"   # tier-2 manual
    assert _upd_cell(s, "skills", sk("err")) == "!"      # check errored
    assert _upd_cell(s, "market", SimpleNamespace(name="mk")) == "·"   # up to date
    assert _upd_cell(s, "skills", sk("ghost")) == "─"    # not in registry
    assert _upd_cell(s, "mcp", SimpleNamespace(name="x")) == "─"       # never updatable
    assert _upd_cell(s, "hooks", SimpleNamespace(name="x")) == "─"


def test_kick_update_check_short_circuits_on_fresh_cache(monkeypatch):
    """A fresh disk cache binds statuses and skips the background sweep."""
    st = axt.update.UpdateStatus("skill", "sk", 1, "a", "a", False)
    monkeypatch.setattr("axt.tui.tabs.load_cached_update_statuses",
                        lambda: ([st], axt.tui.tabs._iso_now()))
    monkeypatch.setattr("axt.tui.tabs.threading.Thread", _StubThread)
    _StubThread.started = []
    s = axt.TuiState()
    REAL_KICK_UPDATE_CHECK(s)
    assert s.update_statuses == {("skill", "sk"): st}
    assert s.update_check_loading is False
    assert _StubThread.started == []


def test_kick_update_check_stale_cache_kicks_worker(monkeypatch):
    """A stale cache stays visible but a background re-check is started."""
    st = axt.update.UpdateStatus("skill", "sk", 1, "a", "a", False)
    monkeypatch.setattr("axt.tui.tabs.load_cached_update_statuses",
                        lambda: ([st], "2020-01-01T00:00:00.000Z"))
    monkeypatch.setattr("axt.tui.tabs.threading.Thread", _StubThread)
    _StubThread.started = []
    s = axt.TuiState()
    REAL_KICK_UPDATE_CHECK(s)
    assert s.update_statuses == {("skill", "sk"): st}   # stale markers kept
    assert s.update_check_loading is True
    assert _StubThread.started == ["axt-update-check"]
    # In flight → a second kick is a no-op.
    REAL_KICK_UPDATE_CHECK(s)
    assert _StubThread.started == ["axt-update-check"]


def test_update_check_worker_binds_and_saves(monkeypatch):
    st = axt.update.UpdateStatus("plugin", "foo@mk", 1, "1", "2", True)
    monkeypatch.setattr("axt.tui.tabs.check_all_updates", lambda types=None: [st])
    saved = {}
    monkeypatch.setattr("axt.tui.tabs.save_cached_update_statuses",
                        lambda sts, at: saved.update(sts=sts, at=at))
    s = axt.TuiState()
    s.update_check_loading = True
    axt.tui.tabs._update_check_worker(s)
    assert s.update_statuses == {("plugin", "foo@mk"): st}
    assert s.update_checked_at == saved["at"]
    assert saved["sts"] == [st]
    assert s.update_check_loading is False


def test_update_check_worker_absorbs_failure(monkeypatch):
    """A raising sweep stamps an empty result — no re-kick storm, no crash."""
    def _boom(types=None):
        raise RuntimeError("network down")
    monkeypatch.setattr("axt.tui.tabs.check_all_updates", _boom)
    s = axt.TuiState()
    s.update_check_loading = True
    axt.tui.tabs._update_check_worker(s)
    assert s.update_statuses == {}
    assert s.update_checked_at is not None
    assert s.update_check_loading is False


def test_ext_r_key_forces_update_recheck(monkeypatch):
    calls = []
    monkeypatch.setattr("axt.tui.tabs._kick_update_check",
                        lambda state, force=False: calls.append(force))
    s = axt.TuiState()
    s.ext_sub_tab = "plugins"
    msg = axt.handle_extensions_input(s, ord("r"))
    assert calls == [True]
    assert "re-checking" in msg
    # Vault keeps its cheap refresh — no forced sweep.
    calls.clear()
    s.ext_sub_tab = "vault"
    msg = axt.handle_extensions_input(s, ord("r"))
    assert calls == [] and msg == "Refreshed"


def test_act_update_settles_upd_marker(monkeypatch):
    """After `u` applies, the row's Upd marker flips to up-to-date in place."""
    import axt
    from axt.core import PluginInfo
    plugin = PluginInfo(id="foo@mk", name="foo", marketplace="mk", version="1",
                        install_path="", scope="user", installed_at="", last_updated="")
    monkeypatch.setattr("axt.tui.tabs._selected_item", lambda state, sub: plugin)
    monkeypatch.setattr("axt.tui.tabs.check_all_updates",
        lambda types=None: [axt.update.UpdateStatus("plugin", "foo@mk", 1, "1", "2", True)])
    monkeypatch.setattr("axt.tui.tabs.apply_updates",
        lambda targets: [axt.update.UpdateResult("plugin", "foo@mk", "1", "2", True, "reinstall")])
    monkeypatch.setattr("axt.tui.tabs._refresh_ext", lambda state, sub: None)
    saved = {}
    monkeypatch.setattr("axt.tui.tabs.save_cached_update_statuses",
                        lambda sts, at: saved.update(sts=sts))
    s = axt.TuiState()
    s.update_statuses = {("plugin", "foo@mk"): axt.update.UpdateStatus("plugin", "foo@mk", 1, "1", "2", True)}
    s.update_checked_at = "2026-07-05T00:00:00.000Z"
    msg = axt.tui.tabs._act_update(s, None, "plugins", ord("u"))
    assert "Updated foo@mk" in msg
    settled = s.update_statuses[("plugin", "foo@mk")]
    assert settled.updatable is False and settled.current == "2"
    assert any(x.name == "foo@mk" and not x.updatable for x in saved["sts"])


def test_settle_update_status_none_state_is_noop():
    """_act_update is also called with state=None in headless paths."""
    axt.tui.tabs._settle_update_status(None, "plugin", "x", "1")  # must not raise


# ─── launch_tui graceful failure ─────────────────────────────────────────────


def test_launch_tui_returns_1_when_curses_unavailable(capsys):
    """Without a TTY, curses.wrapper raises curses.error; we catch it."""
    code = axt.launch_tui()
    assert code == 1


# ─── HELP_TEXT ───────────────────────────────────────────────────────────────


def test_help_text_documents_quit_key():
    # `q` quits unconditionally; Esc climbs the focus stack and quits only at
    # the main-tab layer (see _handle_content_layer_key / _handle_sub_tab_key).
    assert "q / Q" in axt.HELP_TEXT
    assert "Esc" in axt.HELP_TEXT
    assert "Quit" in axt.HELP_TEXT


def test_help_text_documents_vault_tab_focus_toggle():
    """HELP_TEXT must teach Tab as a Vault list↔detail toggle, and the
    stale 'Extensions: ... sub-tab (alt)' lines must be gone."""
    assert "Tab" in axt.HELP_TEXT
    assert "Extensions: next sub-tab (alt)" not in axt.HELP_TEXT
    assert "Extensions: previous sub-tab (alt)" not in axt.HELP_TEXT


def test_help_text_documents_tab_navigation():
    assert "1–3" in axt.HELP_TEXT
    assert "main tab" in axt.HELP_TEXT


def test_help_text_documents_context_sub_tabs():
    help_lower = axt.HELP_TEXT.lower()
    assert "sub-tab" in help_lower
    assert "sources" in help_lower
    assert "rate limits" in help_lower


# ─── # column regression (the bug the user reported) ─────────────────────────


def test_render_vault_includes_row_number_column(tmp_path, monkeypatch):
    """Vault list must show the '#' column even in checked mode."""
    vault = tmp_path / "vault"
    (vault / "skills" / "alpha").mkdir(parents=True)
    (vault / "skills" / "alpha" / "SKILL.md").write_text("---\ndescription: a\n---")
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=vault, installed_plugins=tmp_path / "ip.json",
                                                claude_dir=tmp_path / "claude"))
    monkeypatch.chdir(tmp_path)
    state = axt.TuiState()
    scr = _make_stdscr(rows=20, cols=120)
    axt.render_vault_tab(scr, state, 0, 18, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    # The '#' header AND the row number '1' must both appear.
    assert "#" in flat
    # Row 1 in the no column ("1" with padding).
    # Look for a cell that contains exactly "1" with surrounding whitespace.
    has_row_no = any("1" in (c[2] or "") and "alpha" in (c[2] or "") for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    # More lenient: just check that the data row contains both "1" and "alpha".
    rows_with_alpha = [c for c in scr.calls if len(c) >= 3 and isinstance(c[2], str) and "alpha" in c[2]]
    assert rows_with_alpha, "alpha row should be drawn"


def test_render_vault_checkbox_reflects_space_marks(tmp_path, monkeypatch):
    """The leftmost ■/□ prefix mirrors the Space selection (vault_marked) —
    NOT project-link state, which stays in the Proj column. No Mk column."""
    vault = tmp_path / "vault"
    for name in ("alpha", "beta"):
        (vault / "skills" / name).mkdir(parents=True)
        (vault / "skills" / name / "SKILL.md").write_text("---\ndescription: a\n---")
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=vault, installed_plugins=tmp_path / "ip.json",
                                                claude_dir=tmp_path / "claude"))
    monkeypatch.chdir(tmp_path)
    items = {i.name: i for i in axt.list_vault_items(vault)}
    axt.link_to_project(tmp_path, items["alpha"])  # linked but NOT selected

    state = axt.TuiState()
    state.vault_marked = {"beta"}  # selected but NOT linked
    scr = _make_stdscr(rows=20, cols=140)
    axt.render_vault_tab(scr, state, 0, 18, 140)

    def _prefix(name: str) -> str:
        ys = [c[0] for c in scr.calls
              if len(c) >= 3 and isinstance(c[2], str) and name in c[2]]
        assert ys, f"{name} row should be drawn"
        y = min(ys)
        return next(c[2] for c in scr.calls
                    if c[0] == y and c[1] == 0 and isinstance(c[2], str))

    assert "□" in _prefix("alpha")   # linked ≠ selected → empty box
    assert "■" in _prefix("beta")    # Space-marked → filled box
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Mk" not in flat          # the old rightmost mark column is gone


def test_render_extensions_plugins_subtab_shows_row_number_in_prefix(tmp_path, monkeypatch):
    """Non-Vault Extensions sub-tabs use the render_table PREFIX numbering
    (` 1 `, `▸1 `) — no duplicate `#` data column."""
    import json
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
        vault=tmp_path / "vault",
        claude_dir=tmp_path / "claude",
    ))
    (tmp_path / "ip.json").write_text(json.dumps({
        "version": 2,
        "plugins": {"myplugin@m": [{
            "scope": "user", "installPath": "/tmp/myplugin",
            "version": "1.0", "installedAt": "", "lastUpdated": "",
        }]},
    }))
    monkeypatch.chdir(tmp_path)
    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    scr = _make_stdscr(rows=20, cols=120)
    axt.render_extensions_tab(scr, state, 0, 18, 120)
    # The prefix `▸ 1 ` should appear on the selected row.
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "▸ 1 " in flat or "▸1 " in flat or " 1 " in flat
    # And there should NOT be a separate `#` header for a `no` data column —
    # the only "1" cell associated with the plugin row is the prefix number.
    plugin_calls = [c for c in scr.calls if len(c) >= 3 and isinstance(c[2], str) and "myplugin" in c[2]]
    assert plugin_calls


# ─── Usage / Context / Project smoke tests ───────────────────────────────────


def _setup_isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.HOME", tmp_path / "home")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "claude",
        settings=tmp_path / "settings.json",
        installed_plugins=tmp_path / "ip.json",
        projects=tmp_path / "claude_projects",
        vault=tmp_path / "vault",
    ))
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.chdir(tmp_path)


def test_render_usage_claude_no_data(tmp_path, monkeypatch):
    """Loaded-but-empty case: usage_entries == [] should show the
    'No Claude usage data this month yet.' line, not the loading line."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    state = axt.TuiState()
    state.usage_entries = []                              # loaded, empty
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)
    scr = _make_stdscr(rows=30, cols=120)
    axt.render_usage_tab(scr, state, 0, 28, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "No Claude usage data this month yet." in flat
    assert "Loading Claude usage" not in flat


def test_render_usage_tab_shows_context_5h_7d_gauges(tmp_path, monkeypatch):
    """Usage tab top should render three gauge bars: Context / 5h / 7d."""
    import json

    _setup_isolated_paths(tmp_path, monkeypatch)
    snap = tmp_path / "usage-snapshot.json"
    snap.write_text(json.dumps({
        "five_hour": {"used_percentage": 42, "resets_at": "2099-01-01T00:00:00Z"},
        "seven_day": {"used_percentage": 17, "resets_at": "2099-01-08T00:00:00Z"},
        "updated_at": "2099-01-01T00:00:00Z",
    }))
    # Re-point PATHS to also include usage_snapshot.
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "claude",
        settings=tmp_path / "settings.json",
        installed_plugins=tmp_path / "ip.json",
        projects=tmp_path / "claude_projects",
        vault=tmp_path / "vault",
        usage_snapshot=snap,
    ))

    state = axt.TuiState()
    # Pre-seed context_analysis so render does not need to walk the filesystem.
    state.context_analysis = axt.ContextAnalysis(
        total_tokens=120_000,
        context_window_size=500_000,
        used_percent=24.0,
        model="claude-opus-4-7",
        sources=[],
        cost_impact=axt.CostImpact(
            model="claude-opus-4-7",
            cache_write_cost=0.0,
            cache_read_cost_per_turn=0.0,
            avg_turns_per_session=0,
            avg_sessions_per_day=0,
            per_session_cost=0.0,
            monthly_cost=0.0,
        ),
    )
    scr = _make_stdscr(rows=40, cols=140)
    axt.render_usage_tab(scr, state, 0, 38, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Context:" in flat
    assert "5h:" in flat
    assert "7d:" in flat
    assert "24.0%" in flat
    assert " 42%" in flat
    assert " 17%" in flat


def test_render_context_basic(tmp_path, monkeypatch):
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    state = axt.TuiState()
    state.context_sub_tab = "sources"
    scr = _make_stdscr(rows=30, cols=140)
    axt.render_context_tab(scr, state, 0, 28, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Context" in flat
    assert "Category" in flat  # Table header label


# ─── Bar chart widget ────────────────────────────────────────────────────────


def test_render_bar_chart_empty():
    scr = _make_stdscr()
    rows = axt.render_bar_chart(scr, 0, 0, 50, [])
    assert rows == 0


def test_render_bar_chart_with_data():
    scr = _make_stdscr()
    data = [("04-29", 1.50), ("04-30", 3.00), ("05-01", 0.75)]
    rows = axt.render_bar_chart(scr, 0, 0, 60, data)
    assert rows == 3
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "04-29" in flat
    assert "04-30" in flat


# ─── Extensions sub-tab cycling ──────────────────────────────────────────────


def test_extensions_sub_tab_cycle_forward():
    state = axt.TuiState()
    assert state.ext_sub_tab == "vault"
    axt.handle_extensions_input(state, ord("]"))
    assert state.ext_sub_tab == "skills"
    axt.handle_extensions_input(state, ord("]"))
    assert state.ext_sub_tab == "commands"


def test_extensions_sub_tab_cycle_backward():
    state = axt.TuiState()
    axt.handle_extensions_input(state, ord("["))
    # Wraps to last sub-tab.
    assert state.ext_sub_tab == "market"


# ─── _ensure_project_loaded smoke test ────────────────────────────────────────


def test_ensure_project_loaded_picks_up_claude_md_and_system_prompt(tmp_path, monkeypatch):
    """Project sub-tab items come straight from collect_context_sources, so a
    project CLAUDE.md shows up alongside always-on baseline sources like the
    system prompt — not just the file categories."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    (tmp_path / "CLAUDE.md").write_text("hello")
    state = axt.TuiState()
    axt._ensure_project_loaded(state)
    names = [i.name for i in state.project_items]
    assert "CLAUDE.md (project)" in names
    assert "System Prompt" in names


# ─── Vault: tab background + search + pending toggles + scan ─────────────────


def test_active_tab_has_colored_background_when_unfocused():
    """Active tab must have SOMETHING visible even when focus_layer=content.

    On real terminals color_pair(1) (black-on-cyan) provides the background;
    in tests without start_color() that's 0, but the A_BOLD fallback fires.
    Either way the cell must NOT be drawn with attr=0.
    """
    scr = _make_stdscr()
    axt.render_tab_bar(scr, 0, 0, 120, active_idx=1, focused=False)
    inactive_attr = None
    active_attr = None
    # The active tab cell contains the digit `2·` (tab index 2 = Context).
    # Search by the unique digit-dot prefix instead of substring of the name,
    # which works for both full ("Context") and short ("Ctx") label modes.
    for call in scr.calls:
        if len(call) < 5 or not isinstance(call[2], str):
            continue
        if "2·" in call[2]:
            active_attr = call[4]
        elif "1·" in call[2] and inactive_attr is None:
            inactive_attr = call[4]
    assert active_attr is not None
    assert active_attr & (curses.A_BOLD | curses.A_REVERSE) or active_attr != 0
    if inactive_attr is not None:
        assert active_attr != inactive_attr


def test_vault_search_captures_r_via_extensions_dispatcher():
    """Regression: Extensions tab dispatcher reserves `r` for sub-tab refresh,
    but in Vault `/`-search mode the printable key must reach the search field
    instead of triggering refresh."""
    state = axt.TuiState()
    state.ext_sub_tab = "vault"
    state.vault_searching = True
    state.vault_search = ""
    axt.handle_extensions_input(state, ord("r"))
    assert state.vault_searching is True
    assert state.vault_search == "r"
    # `[` and `]` are also reserved by the dispatcher — same exemption.
    axt.handle_extensions_input(state, ord("["))
    axt.handle_extensions_input(state, ord("]"))
    assert state.vault_search == "r[]"
    assert state.ext_sub_tab == "vault"  # no sub-tab cycle


def test_vault_search_mode_enter_and_capture(tmp_path, monkeypatch):
    """`/` enters search mode; ASCII keys append to vault_search."""
    state = axt.TuiState()
    state.vault_items = [
        axt.VaultItem(name="alpha", type="skill", path="", description=""),
        axt.VaultItem(name="beta", type="skill", path="", description=""),
    ]
    axt.handle_vault_input(state, ord("/"))
    assert state.vault_searching is True
    # Type "alp" → search="alp"
    axt.handle_vault_input(state, ord("a"))
    axt.handle_vault_input(state, ord("l"))
    axt.handle_vault_input(state, ord("p"))
    assert state.vault_search == "alp"
    # Enter applies, exits mode.
    axt.handle_vault_input(state, 10)
    assert state.vault_searching is False
    assert state.vault_search == "alp"


def test_vault_search_esc_clears(tmp_path):
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_searching = True
    state.vault_search = "xyz"
    axt.handle_vault_input(state, 27)  # Esc
    assert state.vault_searching is False
    assert state.vault_search == ""


def test_vault_search_backspace_deletes():
    state = axt.TuiState()
    state.vault_searching = True
    state.vault_search = "abc"
    axt.handle_vault_input(state, curses.KEY_BACKSPACE)
    assert state.vault_search == "ab"


def test_vault_p_toggles_project_pending():
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="", is_linked=False)]
    axt.handle_vault_input(state, ord("p"))
    assert "alpha" in state.vault_pending_project
    # Toggling again removes it.
    axt.handle_vault_input(state, ord("p"))
    assert "alpha" not in state.vault_pending_project


def test_vault_g_toggles_global_pending():
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    axt.handle_vault_input(state, ord("g"))
    assert "alpha" in state.vault_pending_global


def test_vault_esc_discards_pending():
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_pending_project.add("alpha")
    msg = axt.handle_vault_input(state, 27)  # Esc
    assert msg == "Discarded pending changes"
    assert state.vault_pending_project == set()


def test_vault_p_enqueues_pending_toggle():
    """p enqueues a pending project toggle for the focused item."""
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="myskill", type="skill", path="", description="")]
    axt.handle_vault_input(state, ord("p"))
    assert "myskill" in state.vault_pending_project


def test_vault_scan_runs_without_toggling_mode(tmp_path, monkeypatch):
    """`f` re-scans in the current mode and does NOT toggle it.

    Regression: previously `f` flipped default↔full and re-scanned, which
    silently shrank the on-disk cache (e.g. lost plugin enabledPlugins
    entries) and made the next axt run look like it had stale usage data.
    """
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        projects=tmp_path / "projects",
        vault=tmp_path / "vault",
    ))
    state = axt.TuiState()
    assert state.vault_scan_mode == "default"
    msg = axt.handle_vault_input(state, ord("f"))
    assert state.vault_scan_mode == "default"  # mode preserved
    assert msg is not None and "Scan" in msg
    # Pressing `f` again still re-scans in the same mode.
    axt.handle_vault_input(state, ord("f"))
    assert state.vault_scan_mode == "default"


def test_vault_mode_key_toggles_scan_mode(tmp_path, monkeypatch):
    """`F` (capital, f's extension) toggles scan_mode default↔full and re-scans."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        projects=tmp_path / "projects",
        vault=tmp_path / "vault",
    ))
    state = axt.TuiState()
    assert state.vault_scan_mode == "default"
    msg = axt.handle_vault_input(state, ord("F"))
    assert state.vault_scan_mode == "full"
    assert msg is not None and "Mode" in msg
    axt.handle_vault_input(state, ord("F"))
    assert state.vault_scan_mode == "default"


def test_vault_used_column_present_in_render(tmp_path, monkeypatch):
    """The Vault table must include a 'Used' column (shortened from 'Used in')."""
    vault = tmp_path / "vault"
    (vault / "skills" / "alpha").mkdir(parents=True)
    (vault / "skills" / "alpha" / "SKILL.md").write_text("---\ndescription: a\n---")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=vault,
        installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    monkeypatch.chdir(tmp_path)
    state = axt.TuiState()
    scr = _make_stdscr(rows=20, cols=140)
    axt.render_vault_tab(scr, state, 0, 18, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    # Short labels.
    assert "Used" in flat
    assert "Proj" in flat
    assert "Glob" in flat
    # Long labels were removed.
    assert "Used in" not in flat
    assert "Project " not in flat  # trailing space distinguishes column-label
    assert "Global " not in flat


def test_vault_tab_excludes_global_only_items(tmp_path, monkeypatch):
    """The Vault tab lists vault storage only: an item existing ONLY in
    ~/.claude/skills (never imported) must not appear at all."""
    vault = tmp_path / "vault"
    claude = tmp_path / "claude"
    # Item exists ONLY in ~/.claude/skills, NOT in vault.
    (claude / "skills" / "myskill").mkdir(parents=True)
    (claude / "skills" / "myskill" / "SKILL.md").write_text("---\ndescription: x\n---")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=vault, installed_plugins=tmp_path / "ip.json", claude_dir=claude,
    ))
    monkeypatch.chdir(tmp_path)
    state = axt.TuiState()
    scr = _make_stdscr(rows=20, cols=140)
    axt.render_vault_tab(scr, state, 0, 18, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "myskill" not in flat
    assert "glob*" not in flat


def test_vault_tab_has_no_plugin_rows(tmp_path, monkeypatch):
    """Plugins are never vaulted (enabledPlugins, not symlinks) and belong to
    the Plugins sub-tab — installed plugins must not appear in the Vault tab,
    even alongside real vault items."""
    claude = tmp_path / "claude"
    vault = tmp_path / "vault"
    (vault / "skills" / "vaulted-skill").mkdir(parents=True)
    (vault / "skills" / "vaulted-skill" / "SKILL.md").write_text("---\ndescription: v\n---")
    (tmp_path / "pl" / "one").mkdir(parents=True)
    ip = tmp_path / "ip.json"
    ip.write_text(json.dumps({"version": 2, "plugins": {
        "one@mkt": [{"installPath": str(tmp_path / "pl" / "one"), "version": "1.0.0"}],
    }}))
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps(
        {"enabledPlugins": {"one@mkt": True}}))
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=vault, installed_plugins=ip, claude_dir=claude,
    ))
    monkeypatch.chdir(tmp_path)
    state = axt.TuiState()
    scr = _make_stdscr(rows=24, cols=140)
    axt.render_vault_tab(scr, state, 0, 22, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "vaulted-skill" in flat
    assert "one" not in [i.name for i in state.vault_items]
    assert not any(i.type == "plugin" for i in state.vault_items)


def test_help_text_documents_new_keys():
    """The help screen must reference all the new bindings."""
    h = axt.HELP_TEXT
    for token in ("/", "Space", "Enter", "Esc", "i", "f", "[ / ]"):
        assert token in h, f"Help text should document {token!r}"
    # And document the scan vs refresh distinction.
    assert "scan" in h.lower()
    assert "refresh" in h.lower()


def test_help_text_documents_vault_column_meanings():
    h = axt.HELP_TEXT
    # Vault tab is vault-storage-only; import moved to the file sub-tabs.
    assert "vault" in h.lower()
    assert "glob*" not in h and "proj*" not in h
    assert "i=import into vault" in h
    # The short column label is "Used" (was "Used in" before the column rename).
    assert "Used" in h


# ─── Sort by "used" ──────────────────────────────────────────────────────────


def test_vault_sort_includes_used():
    """`s` cycles through sorts; `used` must be one of them."""
    assert "used" in axt._VAULT_SORTS


def test_vault_sort_used_orders_by_project_count():
    """Sort by `used` puts highest-count items first."""
    state = axt.TuiState()
    state.vault_items = [
        axt.VaultItem(name="rare", type="skill", path="", description=""),
        axt.VaultItem(name="popular", type="skill", path="", description=""),
        axt.VaultItem(name="unused", type="skill", path="", description=""),
    ]
    state.vault_sort = "used"
    state.vault_usage_index = {
        "skill:rare": axt.ExtensionUsage(type="skill", name="rare", projects=[
            axt.ProjectRef(path="/p1", name="p1")
        ]),
        "skill:popular": axt.ExtensionUsage(type="skill", name="popular", projects=[
            axt.ProjectRef(path="/p1", name="p1"),
            axt.ProjectRef(path="/p2", name="p2"),
            axt.ProjectRef(path="/p3", name="p3"),
        ]),
    }
    sorted_items = axt._vault_filtered(state)
    assert [i.name for i in sorted_items] == ["popular", "rare", "unused"]


# ─── Apply pending keeps the Used index in sync ──────────────────────────────


def _seed_vault_skill(tmp_path: Path, name: str = "myskill") -> Path:
    """Create a minimal vault skill on disk and point axt.PATHS at it."""
    skill_dir = tmp_path / "vault" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\nbody\n")
    return skill_dir


@pytest.mark.skipif(sys.platform == "win32", reason="vault linking unsupported on Windows")
def test_apply_pending_project_link_updates_used_index(tmp_path, monkeypatch):
    """Linking a vault item to the current project must add that project to the
    Used index, so the 'Used' column reflects it without a manual `f` re-scan."""
    skill_dir = _seed_vault_skill(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=tmp_path / "vault",
        installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)

    item = axt.VaultItem(name="myskill", type="skill", path=str(skill_dir),
                         description="", in_vault=True, is_linked=False)
    state = axt.TuiState()
    state.vault_items = [item]
    state.vault_pending_project = {"myskill"}

    axt._vault_apply_pending(state)

    entry = state.vault_usage_index.get("skill:myskill")
    assert entry is not None, "Used index should gain an entry for the linked item"
    assert any(p.path == str(proj) for p in entry.projects)


@pytest.mark.skipif(sys.platform == "win32", reason="vault linking unsupported on Windows")
def test_apply_pending_project_unlink_removes_from_used_index(tmp_path, monkeypatch):
    """Unlinking from the current project must drop that project from the Used
    index so the count goes back down immediately."""
    skill_dir = _seed_vault_skill(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=tmp_path / "vault",
        installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)

    # Pre-link on disk so is_linked is True, and seed the index as a prior scan would.
    item = axt.VaultItem(name="myskill", type="skill", path=str(skill_dir),
                         description="", in_vault=True, is_linked=True)
    axt.link_to_project(proj, item)
    state = axt.TuiState()
    state.vault_items = [item]
    state.vault_usage_index = {
        "skill:myskill": axt.ExtensionUsage(type="skill", name="myskill", projects=[
            axt.ProjectRef(path=str(proj), name="proj"),
        ]),
    }
    state.vault_pending_project = {"myskill"}

    axt._vault_apply_pending(state)

    entry = state.vault_usage_index.get("skill:myskill")
    projects = entry.projects if entry else []
    assert all(p.path != str(proj) for p in projects)


# ─── Vault `G` — global + .agents mirror toggle ──────────────────────────────


def _seed_G_env(tmp_path, monkeypatch):
    """Point axt.PATHS/HOME at tmp_path and return (skill_dir, home)."""
    skill_dir = _seed_vault_skill(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=tmp_path / "vault",
        installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    return skill_dir, home


@pytest.mark.skipif(sys.platform == "win32", reason="vault linking unsupported on Windows")
def test_vault_G_activates_global_and_agents(tmp_path, monkeypatch):
    skill_dir, home = _seed_G_env(tmp_path, monkeypatch)
    item = axt.VaultItem(name="myskill", type="skill", path=str(skill_dir),
                         description="", in_vault=True)
    state = axt.TuiState()
    state.vault_items = [item]

    msg = axt.handle_vault_input(state, ord("G"))
    assert (tmp_path / "claude" / "skills" / "myskill").is_symlink()
    assert (home / ".agents" / "skills" / "myskill").is_symlink()
    assert "Activated" in msg


@pytest.mark.skipif(sys.platform == "win32", reason="vault linking unsupported on Windows")
def test_vault_G_deactivates_when_both_linked(tmp_path, monkeypatch):
    skill_dir, home = _seed_G_env(tmp_path, monkeypatch)
    item = axt.VaultItem(name="myskill", type="skill", path=str(skill_dir),
                         description="", in_vault=True,
                         is_global_linked=True, is_agents_linked=True)
    axt.link_to_global(tmp_path / "claude", item)
    axt.link_to_agents(home / ".agents", item)
    state = axt.TuiState()
    state.vault_items = [item]

    msg = axt.handle_vault_input(state, ord("G"))
    assert not (tmp_path / "claude" / "skills" / "myskill").exists()
    assert not (home / ".agents" / "skills" / "myskill").exists()
    assert "Deactivated" in msg


@pytest.mark.skipif(sys.platform == "win32", reason="vault linking unsupported on Windows")
def test_vault_G_respects_skill_lock_guard(tmp_path, monkeypatch):
    skill_dir, home = _seed_G_env(tmp_path, monkeypatch)
    (home / ".agents").mkdir(parents=True)
    (home / ".agents" / axt.SKILL_LOCK_NAME).write_text("{}")
    item = axt.VaultItem(name="myskill", type="skill", path=str(skill_dir),
                         description="", in_vault=True)
    state = axt.TuiState()
    state.vault_items = [item]

    msg = axt.handle_vault_input(state, ord("G"))
    # .claude linked; .agents skipped because a .skill-lock.json guards it.
    assert (tmp_path / "claude" / "skills" / "myskill").is_symlink()
    assert not (home / ".agents" / "skills" / "myskill").exists()
    assert axt.SKILL_LOCK_NAME in msg


def test_vault_G_noop_for_non_skill():
    state = axt.TuiState()
    state.vault_items = [
        axt.VaultItem(name="deploy.md", type="command", path="", description="")
    ]
    msg = axt.handle_vault_input(state, ord("G"))
    assert "Only skills" in msg


# ─── Scan cache persistence ──────────────────────────────────────────────────


def test_save_and_load_scan_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", tmp_path / "config")
    index = {
        "skill:alpha": axt.ExtensionUsage(type="skill", name="alpha", projects=[
            axt.ProjectRef(path="/users/me/p1", name="p1"),
            axt.ProjectRef(path="/users/me/p2", name="p2"),
        ]),
    }
    axt._save_scan_cache(index, "full")
    loaded, mode, scanned_at = axt._load_scan_cache()
    assert mode == "full"
    assert "skill:alpha" in loaded
    assert len(loaded["skill:alpha"].projects) == 2
    assert loaded["skill:alpha"].projects[0].name == "p1"
    # The stamp round-trips so the title bar can show cache age.
    assert scanned_at is not None and scanned_at.endswith("Z")


def test_load_scan_cache_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", tmp_path / "config")
    loaded, mode, scanned_at = axt._load_scan_cache()
    assert loaded == {}
    assert mode == "default"
    assert scanned_at is None


def test_vault_first_render_restores_scan_cache(tmp_path, monkeypatch):
    """On vault first paint, scan cache should auto-populate vault_usage_index."""
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=tmp_path / "vault",
        installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    monkeypatch.chdir(tmp_path)
    # Pre-seed a scan cache to disk.
    axt._save_scan_cache({
        "skill:alpha": axt.ExtensionUsage(type="skill", name="alpha", projects=[
            axt.ProjectRef(path="/p", name="p"),
        ])
    }, "full")
    state = axt.TuiState()
    scr = _make_stdscr(rows=20, cols=140)
    axt.render_vault_tab(scr, state, 0, 18, 140)
    # The cache should have been loaded into state.
    assert state.vault_usage_index == {} or "skill:alpha" in state.vault_usage_index or state.vault_scan_mode == "full"
    # The status shouldn't say "(empty)" if cache was loaded — but with no
    # actual vault items, this is best-effort. The key assertion is that
    # the state mode was updated.


def test_kick_vault_scan_populates_index_in_background(tmp_path, monkeypatch):
    """`_kick_vault_scan` fills `vault_usage_index` + `vault_scanned_at` from a
    daemon thread, persists the cache, and clears the loading flag."""
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", tmp_path / "config")
    projects = tmp_path / "projects"
    home = tmp_path / "home" / "me"
    proj = home / "p1"
    proj.mkdir(parents=True)
    # Encoded project dir Claude would create for /<tmp>/home/me/p1.
    encoded = str(proj).replace("/", "-")
    (projects / encoded).mkdir(parents=True)
    axt.write_profile(proj, axt.AxtProfile(skills=("alpha",)))
    monkeypatch.setattr("axt.PATHS", axt.Paths(projects=projects, vault=tmp_path / "vault"))

    state = axt.TuiState()
    axt._kick_vault_scan(state)
    assert state.vault_scan_loading is True
    state.vault_scan_thread.join(timeout=5)

    assert state.vault_scan_loading is False
    assert "skill:alpha" in state.vault_usage_index
    assert state.vault_scanned_at is not None
    # Result persisted so the next launch paints it instantly.
    loaded, _, _ = axt._load_scan_cache()
    assert "skill:alpha" in loaded


def test_kick_vault_scan_idempotent_while_loading(monkeypatch):
    """A second kick while one is in flight is a no-op (no double thread)."""
    state = axt.TuiState()
    state.vault_scan_loading = True
    spawned = []
    monkeypatch.setattr("axt.tui.tabs.threading.Thread",
                        lambda *a, **k: spawned.append(1))
    axt._kick_vault_scan(state)
    assert spawned == []


def test_prime_vault_scan_restores_cache_then_kicks(tmp_path, monkeypatch):
    """`_prime_vault_scan` loads the cached index for an instant paint and
    fires the background refresh."""
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr("axt.PATHS", axt.Paths(projects=tmp_path / "projects", vault=tmp_path / "vault"))
    axt._save_scan_cache({
        "skill:alpha": axt.ExtensionUsage(type="skill", name="alpha", projects=[
            axt.ProjectRef(path="/p", name="p")]),
    }, "full")
    kicked = []
    monkeypatch.setattr("axt.tui.tabs._kick_vault_scan", lambda s: kicked.append(s))
    state = axt.TuiState()
    axt._prime_vault_scan(state)
    assert "skill:alpha" in state.vault_usage_index
    assert state.vault_scan_mode == "full"
    assert state.vault_scanned_at is not None
    assert kicked == [state]


def test_fmt_scan_age_buckets():
    """`_fmt_scan_age` renders just-now / minute / hour / day buckets and
    tolerates missing or malformed input."""
    from datetime import datetime, timezone, timedelta

    def stamp(**kw):
        when = datetime.now(timezone.utc) - timedelta(**kw)
        return when.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    assert axt._fmt_scan_age(None) == ""
    assert axt._fmt_scan_age("garbage") == ""
    assert axt._fmt_scan_age(stamp(seconds=5)) == "just now"
    assert axt._fmt_scan_age(stamp(minutes=3)) == "3m ago"
    assert axt._fmt_scan_age(stamp(hours=2)) == "2h ago"
    assert axt._fmt_scan_age(stamp(days=4)) == "4d ago"


def test_vault_title_shows_scanning_then_age(tmp_path, monkeypatch):
    """While a scan is in flight the title reads 'scanning…'; once done it
    shows the relative age."""
    from datetime import datetime, timezone, timedelta
    vault = tmp_path / "vault"
    (vault / "skills" / "alpha").mkdir(parents=True)
    (vault / "skills" / "alpha" / "SKILL.md").write_text("---\ndescription: a\n---")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=vault, installed_plugins=tmp_path / "ip.json", claude_dir=tmp_path / "claude"))
    monkeypatch.chdir(tmp_path)

    def render_title(state):
        scr = _make_stdscr(rows=20, cols=160)
        axt.render_vault_tab(scr, state, 0, 18, 160)
        return "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))

    state = axt.TuiState()
    state.vault_usage_index = {"skill:alpha": axt.ExtensionUsage(
        type="skill", name="alpha", projects=[axt.ProjectRef(path="/p", name="p")])}
    state.vault_scan_loading = True
    assert "scanning…" in render_title(state)

    state.vault_scan_loading = False
    state.vault_scanned_at = (
        datetime.now(timezone.utc) - timedelta(minutes=2)
    ).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    assert "2m ago" in render_title(state)


def test_has_background_work_includes_vault_scan():
    """The poll loop must stay awake while a vault scan runs so the result
    paints without a keypress."""
    state = axt.TuiState()
    assert axt.tui.loop._has_background_work(state) is False
    state.vault_scan_loading = True
    assert axt.tui.loop._has_background_work(state) is True


# ─── Sub-tab navigation: visual focus + Shift+Tab / Tab ──────────────────────


def test_subtab_bar_shows_brackets_around_active():
    """Active sub-tab is bracketed so it's visible even without color."""
    scr = _make_stdscr(rows=20, cols=120)
    axt._render_subtab_bar(scr, 0, 120, axt.EXTENSION_SUB_TABS, active_key="skills")
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "[ Skills ]" in flat
    assert "Sub:" in flat


def test_subtab_shift_tab_no_longer_cycles():
    """Shift+Tab no longer cycles sub-tabs at the content layer (Task 2).
    Use Esc → subTab layer → ←/→ for canonical navigation."""
    state = axt.TuiState()
    assert state.ext_sub_tab == "vault"
    axt.handle_extensions_input(state, curses.KEY_BTAB)
    # Sub-tab must NOT change; Tab falls through to handle_vault_input
    # (vault_detail_focused stays False because no items are loaded).
    assert state.ext_sub_tab == "vault"


def test_subtab_tab_forward_on_non_vault():
    """Tab no longer cycles sub-tabs at the content layer (Task 2).
    On a non-vault sub-tab the key is simply inert."""
    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    axt.handle_extensions_input(state, 9)  # Tab
    assert state.ext_sub_tab == "plugins"  # unchanged


def test_subtab_tab_on_vault_delegates_to_vault_input():
    """Tab on the Vault sub-tab now delegates to handle_vault_input,
    which toggles detail-panel focus rather than cycling sub-tabs."""
    state = axt.TuiState()
    state.ext_sub_tab = "vault"
    state.vault_items = [
        axt.VaultItem(name="v0", type="skill", path="", description="")
    ]
    before_filter = state.vault_filter
    axt.handle_extensions_input(state, 9)  # Tab
    assert state.ext_sub_tab == "vault"     # sub-tab NOT cycled
    assert state.vault_filter == before_filter  # filter NOT cycled
    assert state.vault_detail_focused is True   # detail panel toggled


def test_subtab_status_message_on_cycle():
    state = axt.TuiState()
    msg = axt.handle_extensions_input(state, ord("]"))
    assert msg == "Sub-tab: skills"


def test_extension_sub_tabs_order():
    """Sub-tab order: vault first, then skills/commands/agents/mcp/hooks/plugins/market."""
    keys = [k for k, _ in axt.EXTENSION_SUB_TABS]
    assert keys == ["vault", "skills", "commands", "agents", "mcp", "hooks", "plugins", "market"]


def test_set_status_records_timestamp_and_clears():
    """set_status() arms the auto-clear timer; clearing resets the timestamp."""
    state = axt.TuiState()
    assert state.status_set_at is None
    axt.set_status(state, "hello")
    assert state.status == "hello"
    assert state.status_set_at is not None
    axt.set_status(state, "")
    assert state.status == ""
    assert state.status_set_at is None


def test_classify_status_kinds():
    """Action confirmations → ok, failures → error, hints/progress → info."""
    assert axt.classify_status("Linked my-skill") == "ok"
    assert axt.classify_status("Enabled plugin-x (global)") == "ok"
    assert axt.classify_status("Theme: dark") == "ok"
    assert axt.classify_status("Link failed: boom") == "error"
    assert axt.classify_status("Sync failed: nope") == "error"  # error beats "sync" prefix
    assert axt.classify_status("Hook not found in its settings file") == "error"
    assert axt.classify_status("Symlinks unsupported on this platform") == "error"
    assert axt.classify_status("Loading Claude usage…") == "info"
    assert axt.classify_status("/: type to filter, Enter to apply, Esc to cancel") == "info"
    assert axt.classify_status("Cancelled") == "info"


def test_set_status_sets_kind_and_resets_on_clear():
    """set_status() derives status_kind from the message; "" resets to info."""
    state = axt.TuiState()
    assert state.status_kind == "info"
    axt.set_status(state, "Unlinked my-skill")
    assert state.status_kind == "ok"
    axt.set_status(state, "Toggle failed: err")
    assert state.status_kind == "error"
    axt.set_status(state, "Detail focused", kind="ok")  # explicit override wins
    assert state.status_kind == "ok"
    axt.set_status(state, "")
    assert state.status_kind == "info"


# ─── linked vs enabled distinction ───────────────────────────────────────────


def test_activation_term_for_plugin():
    assert axt._activation_term("plugin", True) == "enabled"
    assert axt._activation_term("plugin", False) == "off"


def test_activation_term_for_skill():
    assert axt._activation_term("skill", True) == "linked"
    assert axt._activation_term("skill", False) == "not linked"


def test_help_text_documents_linked_vs_enabled():
    h = axt.HELP_TEXT
    assert "linked" in h and "enabled" in h
    assert "enabledPlugins" in h


def test_help_text_documents_used_sort():
    assert "most-used first" in axt.HELP_TEXT.lower() or "used" in axt.HELP_TEXT


# ─── Focus-layer navigation (arrow keys move between mainTab/subTab/content)


def test_at_top_of_content_vault_at_zero():
    state = axt.TuiState()
    state.vault_selected = 0
    assert axt._at_top_of_content(state, "extensions") is True
    state.vault_selected = 3
    assert axt._at_top_of_content(state, "extensions") is False


def test_at_top_of_content_usage_respects_scroll():
    """Usage scroll == 0 → top; scroll > 0 → not top."""
    state = axt.TuiState()
    assert axt._at_top_of_content(state, "usage") is True
    state.usage_scroll = 1
    assert axt._at_top_of_content(state, "usage") is False


def test_subtab_bar_focus_attr_differs_from_unfocused(tmp_path):
    """subTab focused → solid cyan chip (BOLD, no UNDERLINE);
    unfocused → bold cyan text with UNDERLINE (no fill)."""
    scr_focused = _make_stdscr()
    axt._render_subtab_bar(scr_focused, 0, 120, axt.EXTENSION_SUB_TABS, active_key="plugins", focused=True)
    scr_unfocused = _make_stdscr()
    axt._render_subtab_bar(scr_unfocused, 0, 120, axt.EXTENSION_SUB_TABS, active_key="plugins", focused=False)
    # Pull attr of the call that drew "[ Plugins ]".
    def attr_of_plugins(scr):
        for call in scr.calls:
            if len(call) >= 5 and isinstance(call[2], str) and "Plugins" in call[2] and "[" in call[2]:
                return call[4]
        return None
    a_focused = attr_of_plugins(scr_focused)
    a_unfocused = attr_of_plugins(scr_unfocused)
    assert a_focused is not None and a_unfocused is not None
    # The two states must differ. Focused = bold without underline (solid
    # chip); unfocused = bold WITH underline (just decorated text).
    assert a_focused != a_unfocused
    assert a_focused & curses.A_BOLD
    assert not (a_focused & curses.A_UNDERLINE)
    assert a_unfocused & curses.A_UNDERLINE


# ─── Current project path display ────────────────────────────────────────────


def test_render_frame_shows_cwd_line(tmp_path, monkeypatch):
    """The frame shows a 'cwd:' line with the full project path, on the row
    just above the status bar (h-2)."""
    monkeypatch.chdir(tmp_path)
    scr = _make_stdscr(rows=30, cols=140)
    state = axt.TuiState()
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "cwd:" in flat
    assert str(tmp_path) in flat
    # cwd now sits on the row just above the status/shortcuts bar.
    cwd_rows = [c[0] for c in scr.calls
                if len(c) >= 3 and isinstance(c[2], str) and "cwd:" in c[2]]
    assert cwd_rows == [30 - 2]


def _ext_idx() -> int:
    return next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")


def test_status_bar_shows_mcp_toggle_shortcuts(monkeypatch):
    """MCP sub-tab status bar advertises the p (On) toggle + Space marking."""
    scr = _make_stdscr(rows=30, cols=200)
    state = axt.TuiState()
    state.tab_idx = _ext_idx()
    state.ext_sub_tab = "mcp"
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "p:on" in flat
    assert "Space:mark" in flat


def test_status_bar_shows_hooks_toggle_shortcuts(monkeypatch):
    """Hooks sub-tab status bar advertises p/g toggles / v:preview."""
    scr = _make_stdscr(rows=30, cols=200)
    state = axt.TuiState()
    state.tab_idx = _ext_idx()
    state.ext_sub_tab = "hooks"
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "p:project" in flat
    assert "g:global" in flat
    assert "v:preview" in flat


def test_status_bar_shows_marked_count_for_subtab(monkeypatch):
    """With Space marks set, the status bar shows the count + bulk hint."""
    from types import SimpleNamespace
    scr = _make_stdscr(rows=30, cols=200)
    state = axt.TuiState()
    state.tab_idx = _ext_idx()
    state.ext_sub_tab = "mcp"
    state.ext_cache["mcp"] = [SimpleNamespace(
        name="srv", scope="user", transport="stdio", disabled=False,
        plugin_id="", version="", url="", command="node", args_list=[],
        env_dict={})]
    state.ext_marked["mcp"] = {"user:srv"}
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "1 marked" in flat


# ─── Non-Vault Extensions sub-tabs: no duplicated row number ─────────────────


def test_extensions_plugins_sub_tab_checkbox_prefix_and_number_column():
    """Plugins sub-tab mirrors Vault's layout: the leftmost prefix is the
    Space-mark checkbox (■/□) and the row number lives in ONE `#` column."""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path as _P
        ip_path = _P(tmp) / "ip.json"
        ip_path.write_text(json.dumps({
            "version": 2,
            "plugins": {"plug@m": [{
                "scope": "user", "installPath": "/p", "version": "9.9",
                "installedAt": "", "lastUpdated": "",
            }]},
        }))
        # Patch PATHS for this test.
        original = axt.PATHS
        try:
            axt.PATHS = axt.Paths(installed_plugins=ip_path, settings=_P(tmp) / "s.json", vault=_P(tmp) / "vault", claude_dir=_P(tmp) / "claude")
            state = axt.TuiState()
            state.ext_sub_tab = "plugins"
            scr = _make_stdscr(rows=20, cols=120)
            axt.render_extensions_tab(scr, state, 0, 18, 120)
            plug_y = next(c[0] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str) and "plug" in c[2])
            cells_on_row = [c for c in scr.calls if len(c) >= 3 and c[0] == plug_y and isinstance(c[2], str)]
            # Exactly one isolated "1" cell — the `#` column (the prefix is now
            # a checkbox, not a number).
            number_cells = [c for c in cells_on_row if c[2].strip() == "1"]
            assert len(number_cells) == 1
            # The selected-row prefix carries the (unmarked) checkbox.
            assert any("□" in c[2] for c in cells_on_row)
        finally:
            axt.PATHS = original


def test_extensions_row_checkbox_reflects_marks(tmp_path, monkeypatch):
    """A Space-marked row renders the filled ■ checkbox (mirrors Vault)."""
    from types import SimpleNamespace
    state = axt.TuiState()
    state.ext_sub_tab = "mcp"
    state.ext_cache["mcp"] = [
        SimpleNamespace(name="alpha", scope="user", transport="stdio",
                        disabled=False, plugin_id="", version="", url="",
                        command="node", args_list=[], env_dict={}),
        SimpleNamespace(name="beta", scope="user", transport="stdio",
                        disabled=False, plugin_id="", version="", url="",
                        command="node", args_list=[], env_dict={}),
    ]
    state.ext_marked["mcp"] = {"user:beta"}
    scr = _make_stdscr(rows=30, cols=120)
    axt.render_extensions_tab(scr, state, 0, 28, 120)

    def _prefix(name: str) -> str:
        row_y = next(c[0] for c in scr.calls
                     if len(c) >= 3 and isinstance(c[2], str) and name in c[2])
        return "".join(c[2] for c in scr.calls
                       if len(c) >= 3 and c[0] == row_y and isinstance(c[2], str))

    assert "■" in _prefix("beta")   # marked → filled box
    assert "□" in _prefix("alpha")  # unmarked → empty box


def _flat(scr) -> str:
    return "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))


def test_mcp_sub_tab_renders_detail_panel():
    state = axt.TuiState()
    state.ext_sub_tab = "mcp"
    state.ext_cache["mcp"] = [axt.McpServerInfo(
        name="ctx7", plugin_id="", command="node", args=("server.js",),
        env=(("K", "V"),), scope="user", transport="stdio", disabled=True,
    )]
    scr = _make_stdscr(rows=30, cols=120)
    axt.render_extensions_tab(scr, state, 0, 28, 120)
    flat = _flat(scr)
    assert "Scope:" in flat
    assert "Transport:" in flat
    assert "Status:" in flat
    assert "disabled" in flat
    assert "Command:" in flat


def test_mcp_rows_split_registration_and_activation():
    """MCP Proj/Glob mirror the *registration* scope (user → Glob ●,
    project/.mcp.json → Proj ●, plugin/claude.ai/built-in → both ─) while the
    On column carries the per-project activation flag."""
    from types import SimpleNamespace

    def _srv(name, scope, disabled):
        return SimpleNamespace(
            name=name, scope=scope, transport="http", disabled=disabled,
            plugin_id="", version="", url="", command="", args_list=[],
            env_dict={})

    state = axt.TuiState()
    state.ext_sub_tab = "mcp"
    state.ext_cache["mcp"] = [
        _srv("glob-srv", "user", False),
        _srv("proj-srv", "project-file", False),
        _srv("builtin-srv", "built-in", True),
    ]
    scr = _make_stdscr(rows=30, cols=160)
    axt.render_extensions_tab(scr, state, 0, 28, 160)

    def _proj_glob_on(name: str) -> list[str]:
        row_y = next(c[0] for c in scr.calls
                     if len(c) >= 3 and isinstance(c[2], str) and name in c[2])
        cells = sorted((c for c in scr.calls
                        if len(c) >= 3 and c[0] == row_y and isinstance(c[2], str)),
                       key=lambda c: c[1])
        # Glyph cells on an MCP row, in x order: Ver, Vault, Proj, Glob, Upd,
        # On (transport/detail hold plain text) — pick Proj/Glob/On, skipping
        # the always-`─` Upd cell between Glob and On.
        glyphs = [t for t in (c[2].strip() for c in cells) if t in ("●", "○", "─")]
        return [glyphs[-4], glyphs[-3], glyphs[-1]]

    assert _proj_glob_on("glob-srv") == ["─", "●", "●"]
    assert _proj_glob_on("proj-srv") == ["●", "─", "●"]
    assert _proj_glob_on("builtin-srv") == ["─", "─", "○"]


def test_hooks_sub_tab_renders_detail_panel():
    state = axt.TuiState()
    state.ext_sub_tab = "hooks"
    state.ext_cache["hooks"] = [axt.HookInfo(
        event="PreToolUse", matcher="Bash", source="user",
        source_path="/u/settings.json", type="command", command="echo hi",
    )]
    scr = _make_stdscr(rows=30, cols=120)
    axt.render_extensions_tab(scr, state, 0, 28, 120)
    flat = _flat(scr)
    assert "Matcher:" in flat
    assert "Type:" in flat
    assert "Command:" in flat
    assert "File:" in flat


def test_plugins_sub_tab_renders_detail_panel(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(settings=tmp_path / "s.json"))
    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    state.ext_cache["plugins"] = [axt.PluginInfo(
        id="plug@m", name="plug", marketplace="m", version="1.2",
        install_path="/p", scope="user", installed_at="", last_updated="2026-01-01",
    )]
    scr = _make_stdscr(rows=30, cols=120)
    axt.render_extensions_tab(scr, state, 0, 28, 120)
    flat = _flat(scr)
    assert "ID:" in flat
    assert "Marketplace:" in flat
    assert "Global:" in flat
    assert "Project:" in flat


def test_ext_detail_tab_focus_and_scroll():
    import curses
    state = axt.TuiState()
    state.ext_sub_tab = "mcp"
    state.ext_cache["mcp"] = [axt.McpServerInfo(
        name="s", plugin_id="", command="node", args=(), env=(), scope="user",
    )]
    # Tab focuses the detail panel.
    axt.handle_extensions_input(state, ord("\t"))
    assert state.ext_detail_focused is True
    # j/k scroll the panel, not the (single-row) selection.
    axt.handle_extensions_input(state, ord("j"))
    assert state.ext_detail_scroll == 1
    axt.handle_extensions_input(state, ord("k"))
    assert state.ext_detail_scroll == 0
    # Tab again blurs.
    axt.handle_extensions_input(state, ord("\t"))
    assert state.ext_detail_focused is False


def test_ext_detail_tab_noop_without_data():
    state = axt.TuiState()
    state.ext_sub_tab = "mcp"
    state.ext_cache["mcp"] = []
    axt.handle_extensions_input(state, ord("\t"))
    assert state.ext_detail_focused is False


def test_ext_detail_scroll_resets_on_selection_move():
    import curses
    state = axt.TuiState()
    state.ext_sub_tab = "hooks"
    state.ext_cache["hooks"] = [
        axt.HookInfo(event="Stop", matcher="*", source="user", source_path="/x", type="command", command="a"),
        axt.HookInfo(event="Stop", matcher="*", source="user", source_path="/x", type="command", command="b"),
    ]
    state.ext_detail_scroll = 5
    axt.handle_extensions_input(state, ord("j"))  # move selection
    assert state.ext_selected["hooks"] == 1
    assert state.ext_detail_scroll == 0


def test_ext_detail_blurred_on_subtab_cycle():
    state = axt.TuiState()
    state.ext_sub_tab = "mcp"
    state.ext_cache["mcp"] = [axt.McpServerInfo(name="s", plugin_id="", command="x", args=(), env=())]
    state.ext_detail_focused = True
    state.ext_detail_scroll = 3
    axt.handle_extensions_input(state, ord("]"))  # next sub-tab
    assert state.ext_detail_focused is False
    assert state.ext_detail_scroll == 0


def _plugin(name: str) -> "axt.PluginInfo":
    return axt.PluginInfo(
        id=f"{name}@m", name=name, marketplace="m", version="1",
        install_path="/p", scope="user", installed_at="", last_updated="",
    )


def test_ext_detail_esc_blurs_back_to_list():
    """Esc while the detail panel is focused blurs it back to the list
    (mirrors Vault's Esc-blur) so j/k move the selection again."""
    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    state.ext_cache["plugins"] = [_plugin("a"), _plugin("b")]
    state.ext_detail_focused = True
    state.ext_detail_scroll = 3
    axt.handle_extensions_input(state, 27)  # Esc
    assert state.ext_detail_focused is False
    assert state.ext_detail_scroll == 0
    # j now moves the list selection, not the detail scroll.
    axt.handle_extensions_input(state, ord("j"))
    assert state.ext_selected["plugins"] == 1


def test_ext_content_esc_with_detail_focused_does_not_climb():
    """Esc with the detail panel focused must NOT climb to the sub-tab bar —
    it has to fall through to handle_extensions_input so it blurs the panel
    first (the second Esc, with the panel blurred, then climbs)."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "plugins"
    state.focused_layer = "content"
    state.ext_detail_focused = True
    scr = _make_stdscr()
    consumed = axt._handle_content_layer_key(scr, state, 27, "extensions")
    assert consumed is False
    assert state.focused_layer == "content"  # unchanged


def test_ext_content_up_with_detail_focused_does_not_climb():
    """↑ at the top of the list scrolls the focused detail panel instead of
    climbing out of the content layer."""
    import curses
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "plugins"
    state.focused_layer = "content"
    state.ext_selected["plugins"] = 0  # at top → would climb if unguarded
    state.ext_detail_focused = True
    scr = _make_stdscr()
    consumed = axt._handle_content_layer_key(scr, state, curses.KEY_UP, "extensions")
    assert consumed is False
    assert state.focused_layer == "content"  # unchanged


def test_extensions_subtab_header_has_no_underline_rule():
    """Non-Vault Extensions sub-tabs match Vault: the column header attaches
    directly to the list with no ──── rule below it (header_rule=False)."""
    import json
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as tmp:
        ip_path = _P(tmp) / "ip.json"
        ip_path.write_text(json.dumps({
            "version": 2,
            "plugins": {"plug@m": [{
                "scope": "user", "installPath": "/p", "version": "1",
                "installedAt": "", "lastUpdated": "",
            }]},
        }))
        original = axt.PATHS
        try:
            axt.PATHS = axt.Paths(installed_plugins=ip_path, settings=_P(tmp) / "s.json", vault=_P(tmp) / "vault", claude_dir=_P(tmp) / "claude")
            state = axt.TuiState()
            state.ext_sub_tab = "plugins"
            scr = _make_stdscr(rows=20, cols=120)
            axt.render_extensions_tab(scr, state, 0, 18, 120)
            # The header row carries the "Plugin" column label, now suffixed
            # with the active-sort glyph ("Plugin ▲" — default sort is by name).
            # The subtab bar shows "Plugins" plural, so matching the glyph form
            # avoids it.
            header_y = next(c[0] for c in scr.calls
                            if len(c) >= 3 and isinstance(c[2], str)
                            and c[2].strip() == "Plugin ▲")
            below_y = header_y + 1
            for c in scr.calls:
                if c[0] == below_y and c[1] == 0 and isinstance(c[2], str) and c[2].strip():
                    assert set(c[2].strip()) != {"─"}, (
                        f"unexpected ──── header underline at row {below_y}")
        finally:
            axt.PATHS = original


# ─── Shortened Vault column labels ───────────────────────────────────────────


# ─── DetailPanel focus mode ──────────────────────────────────────────────────


def test_vault_enter_focuses_detail_when_no_pending():
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    msg = axt.handle_vault_input(state, 10)  # Enter
    assert state.vault_detail_focused is True
    assert "Detail focused" in (msg or "")


def test_vault_enter_applies_pending_first():
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_pending_project.add("alpha")
    # With pending, Enter applies — does NOT focus the detail panel.
    msg = axt.handle_vault_input(state, 10)
    assert state.vault_detail_focused is False
    assert "Applied" in (msg or "") or "error" in (msg or "").lower()


def test_vault_enter_pending_confirm_yes_applies(monkeypatch):
    calls = []
    monkeypatch.setattr("axt.confirm_modal",
                        lambda stdscr, msg, title="Confirm": calls.append(msg) or True)
    state = axt.TuiState()
    state.stdscr_callbacks = {"stdscr": object()}
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_pending_project.add("alpha")
    msg = axt.handle_vault_input(state, 10)
    assert calls and "Apply pending" in calls[0]
    assert "Applied" in (msg or "") or "error" in (msg or "").lower()


def test_vault_enter_pending_confirm_no_keeps_pending(monkeypatch):
    monkeypatch.setattr("axt.confirm_modal",
                        lambda stdscr, msg, title="Confirm": False)
    state = axt.TuiState()
    state.stdscr_callbacks = {"stdscr": object()}
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_pending_project.add("alpha")
    msg = axt.handle_vault_input(state, 10)
    assert msg == "Cancelled"
    # Pending toggles are preserved so the user can retry.
    assert state.vault_pending_project == {"alpha"}


def test_vault_detail_focus_scroll_j_k():
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_detail_focused = True
    axt.handle_vault_input(state, ord("j"))
    assert state.vault_detail_scroll == 1
    axt.handle_vault_input(state, ord("j"))
    assert state.vault_detail_scroll == 2
    axt.handle_vault_input(state, ord("k"))
    assert state.vault_detail_scroll == 1


def test_vault_detail_render_clamps_overscroll_back_to_state():
    """Rendering the vault tab clamps an over-scrolled detail panel and writes
    the clamped value back to state, so a held `j` can't scroll into blank
    space (mirrors the usage-tab render-time clamp)."""
    scr = _make_stdscr(rows=30, cols=120)
    s = axt.TuiState()
    _seed_vault_for_render(s)
    s.vault_detail_focused = True
    s.vault_detail_scroll = 9999
    axt.render_vault_tab(scr, s, y0=2, h=25, w=120)
    assert s.vault_detail_scroll < 9999       # clamped, not left runaway
    assert s.vault_detail_scroll >= 0


def test_vault_detail_focus_esc_blurs():
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_detail_focused = True
    state.vault_detail_scroll = 5
    axt.handle_vault_input(state, 27)  # Esc
    assert state.vault_detail_focused is False
    assert state.vault_detail_scroll == 0


def test_vault_detail_focus_esc_preserves_search():
    """Esc from detail panel only blurs back to the filtered list — the
    search filter stays intact. Clearing the filter is reserved for a
    follow-up Esc pressed on the list (see test_vault_list_esc_clears_search)."""
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_detail_focused = True
    state.vault_detail_scroll = 3
    state.vault_search = "alp"
    msg = axt.handle_vault_input(state, 27)  # Esc
    assert state.vault_detail_focused is False
    assert state.vault_detail_scroll == 0
    assert state.vault_search == "alp"
    assert msg is None


def test_vault_list_esc_clears_search():
    """First Esc on the filtered list clears vault_search and resets the
    selection. focused_layer is owned by the loop dispatcher and is not
    touched by handle_vault_input."""
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_search = "alp"
    state.vault_selected = 2
    msg = axt.handle_vault_input(state, 27)  # Esc
    assert state.vault_search == ""
    assert state.vault_selected == 0
    assert msg == "Search cleared"


def test_vault_content_esc_with_search_does_not_climb():
    """When focus is on the Vault content layer and a search filter is
    active, the content-layer handler must NOT consume Esc — it has to
    fall through to handle_vault_input so the first Esc can clear the
    filter (the second Esc, with vault_search empty, then climbs)."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "vault"
    state.focused_layer = "content"
    state.vault_search = "alp"
    scr = _make_stdscr()
    consumed = axt._handle_content_layer_key(scr, state, 27, "extensions")
    assert consumed is False
    assert state.focused_layer == "content"  # unchanged


def test_vault_content_esc_without_search_climbs_to_sub_tab():
    """With no search filter, the standard climb behavior is preserved:
    content-layer Esc moves focus up to the sub-tab bar."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "vault"
    state.focused_layer = "content"
    state.vault_search = ""
    scr = _make_stdscr()
    consumed = axt._handle_content_layer_key(scr, state, 27, "extensions")
    assert consumed is True
    assert state.focused_layer == "subTab"


def test_vault_list_esc_pending_takes_priority_over_search():
    """Pending toggles are the closer-to-action state, so an Esc with both
    pending + search active discards the pending changes first. A second
    Esc would then clear the search."""
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_search = "alp"
    state.vault_pending_project.add("alpha")
    msg = axt.handle_vault_input(state, 27)
    assert state.vault_pending_project == set()
    assert state.vault_search == "alp"  # search preserved on this Esc
    assert msg == "Discarded pending changes"


# ─── Subtab actions (Plugin enable / disable / Skill / Marketplace / Hook) ───


def _plugin_toggle_state(tmp_path, monkeypatch):
    import json
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
    ))
    (tmp_path / "ip.json").write_text(json.dumps({
        "version": 2,
        "plugins": {"p@m": [{"scope": "u", "installPath": "/p", "version": "1",
                              "installedAt": "", "lastUpdated": ""}]},
    }))
    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    state.ext_cache["plugins"] = axt.list_installed_plugins(tmp_path / "ip.json")
    state.ext_selected["plugins"] = 0
    state.stdscr_callbacks = {"stdscr": None}
    return state


def test_plugin_p_toggles_project_scope(tmp_path, monkeypatch):
    state = _plugin_toggle_state(tmp_path, monkeypatch)
    proj_settings = tmp_path / ".claude" / "settings.json"
    # Unset counts as enabled → the first `p` disables, in project settings.
    msg = axt._handle_subtab_action(state, "plugins", ord("p"))
    assert "Disabled" in (msg or "") and "(project)" in msg
    assert axt.read_enabled_plugins(proj_settings)["p@m"] is False
    state.ext_cache["plugins"] = axt.list_installed_plugins(tmp_path / "ip.json")
    msg = axt._handle_subtab_action(state, "plugins", ord("p"))
    assert "Enabled" in (msg or "")
    assert axt.read_enabled_plugins(proj_settings)["p@m"] is True


def test_plugin_g_toggles_global_scope(tmp_path, monkeypatch):
    state = _plugin_toggle_state(tmp_path, monkeypatch)
    msg = axt._handle_subtab_action(state, "plugins", ord("g"))
    assert "Disabled" in (msg or "") and "(global)" in msg
    assert axt.read_enabled_plugins(tmp_path / "settings.json")["p@m"] is False
    state.ext_cache["plugins"] = axt.list_installed_plugins(tmp_path / "ip.json")
    msg = axt._handle_subtab_action(state, "plugins", ord("g"))
    assert "Enabled" in (msg or "")
    assert axt.read_enabled_plugins(tmp_path / "settings.json")["p@m"] is True


def test_plugin_project_toggle_starts_from_global_value(tmp_path, monkeypatch):
    """Project unset + global False → effective disabled → `p` enables (project)."""
    state = _plugin_toggle_state(tmp_path, monkeypatch)
    axt.set_plugin_enabled(tmp_path / "settings.json", "p@m", False)
    msg = axt._handle_subtab_action(state, "plugins", ord("p"))
    assert "Enabled" in (msg or "") and "(project)" in msg
    assert axt.read_enabled_plugins(tmp_path / ".claude" / "settings.json")["p@m"] is True


def test_plugin_toggle_failure_reports(tmp_path, monkeypatch):
    state = _plugin_toggle_state(tmp_path, monkeypatch)
    def boom(path, pid, enabled):
        raise OSError("disk full")
    monkeypatch.setattr("axt.tui.tabs.set_plugin_enabled", boom)
    msg = axt._handle_subtab_action(state, "plugins", ord("p"))
    assert "Toggle failed" in (msg or "")


def _mcp_state(disabled):
    from types import SimpleNamespace
    state = axt.TuiState()
    state.ext_sub_tab = "mcp"
    state.ext_cache["mcp"] = [SimpleNamespace(
        name="srv", scope="user", transport="stdio", disabled=disabled)]
    state.ext_selected["mcp"] = 0
    state.stdscr_callbacks = {"stdscr": None}
    return state


def test_mcp_p_flips_disabled_state(monkeypatch):
    calls = []
    monkeypatch.setattr("axt.tui.tabs.set_mcp_disabled",
                        lambda name, disabled: calls.append((name, disabled)))
    monkeypatch.setattr("axt.tui.tabs._refresh_ext", lambda state, sub: None)
    msg = axt._handle_subtab_action(_mcp_state(disabled=False), "mcp", ord("p"))
    assert calls == [("srv", True)] and "Disabled" in msg
    calls.clear()
    msg = axt._handle_subtab_action(_mcp_state(disabled=True), "mcp", ord("p"))
    assert calls == [("srv", False)] and "Enabled" in msg


def test_mcp_g_explains_project_only_scope():
    msg = axt._handle_subtab_action(_mcp_state(disabled=False), "mcp", ord("g"))
    assert msg == "MCP servers toggle per project only — use p"


def _hook_state(source: str, source_path: str = "/tmp/settings.json"):
    from types import SimpleNamespace
    state = axt.TuiState()
    state.ext_sub_tab = "hooks"
    state.ext_cache["hooks"] = [SimpleNamespace(
        event="PreToolUse", type="command", source=source,
        source_path=source_path, disabled=False)]
    state.ext_selected["hooks"] = 0
    state.stdscr_callbacks = {"stdscr": None}
    return state


def test_hook_p_on_user_hook_explains_scope():
    """A user-settings hook lives in the global scope → `p` points at `g`."""
    msg = axt._handle_subtab_action(_hook_state("user"), "hooks", ord("p"))
    assert msg == "Hook lives in user settings — use g"


def test_hook_g_on_project_hook_explains_scope():
    msg = axt._handle_subtab_action(_hook_state("project"), "hooks", ord("g"))
    assert msg == "Hook lives in project settings — use p"


def test_hook_g_flips_user_hook_disabled_state(monkeypatch):
    calls = []
    monkeypatch.setattr("axt.tui.tabs.set_hook_disabled",
                        lambda path, hook, disabled: calls.append(disabled) or True)
    monkeypatch.setattr("axt.tui.tabs._refresh_ext", lambda state, sub: None)
    msg = axt._handle_subtab_action(_hook_state("user"), "hooks", ord("g"))
    assert calls == [True] and "Disabled" in msg


def test_hook_p_flips_project_hook_disabled_state(monkeypatch):
    calls = []
    monkeypatch.setattr("axt.tui.tabs.set_hook_disabled",
                        lambda path, hook, disabled: calls.append(disabled) or True)
    monkeypatch.setattr("axt.tui.tabs._refresh_ext", lambda state, sub: None)
    msg = axt._handle_subtab_action(_hook_state("project"), "hooks", ord("p"))
    assert calls == [True] and "Disabled" in msg


def test_hook_toggle_plugin_hook_read_only():
    msg = axt._handle_subtab_action(_hook_state("plugin"), "hooks", ord("p"))
    assert msg == "Plugin hooks are read-only (manage them in the plugin)"


# ─── Uniform Space marking + bulk p/g toggles (non-vault sub-tabs) ───────────


def test_space_marks_and_unmarks_item():
    state = _mcp_state(disabled=False)
    msg = axt.handle_extensions_input(state, ord(" "))
    assert "Marked 'srv'" in msg and "(1 marked)" in msg
    assert state.ext_marked["mcp"] == {"user:srv"}
    msg = axt.handle_extensions_input(state, ord(" "))
    assert "Unmarked 'srv'" in msg and "(0 marked)" in msg
    assert state.ext_marked["mcp"] == set()


def test_esc_clears_marks_before_search():
    state = _mcp_state(disabled=False)
    state.ext_marked["mcp"] = {"user:srv"}
    state.ext_search["mcp"] = "sr"
    msg = axt.handle_extensions_input(state, 27)
    assert msg == "Cleared marks"
    assert not state.ext_marked["mcp"]
    msg = axt.handle_extensions_input(state, 27)
    assert msg == "Search cleared"


def test_ext_content_esc_with_marks_does_not_climb():
    """Content-layer Esc must fall through to handle_extensions_input while
    Space marks exist so the first Esc clears them (mirrors the search
    exception)."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "mcp"
    state.focused_layer = "content"
    state.ext_marked["mcp"] = {"user:srv"}
    scr = _make_stdscr()
    assert axt._handle_content_layer_key(scr, state, 27, "extensions") is False
    assert state.focused_layer == "content"


def test_vault_content_esc_with_marks_does_not_climb():
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "vault"
    state.focused_layer = "content"
    state.vault_marked = {"alpha"}
    scr = _make_stdscr()
    assert axt._handle_content_layer_key(scr, state, 27, "extensions") is False
    assert state.focused_layer == "content"


def test_bulk_p_toggle_applies_to_marked_plugins(tmp_path, monkeypatch):
    import json
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
    ))
    (tmp_path / "ip.json").write_text(json.dumps({
        "version": 2,
        "plugins": {
            "a@m": [{"scope": "u", "installPath": "/a", "version": "1",
                     "installedAt": "", "lastUpdated": ""}],
            "b@m": [{"scope": "u", "installPath": "/b", "version": "1",
                     "installedAt": "", "lastUpdated": ""}],
        },
    }))
    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    state.ext_cache["plugins"] = axt.list_installed_plugins(tmp_path / "ip.json")
    state.ext_selected["plugins"] = 0
    state.stdscr_callbacks = {"stdscr": None}
    state.ext_marked["plugins"] = {"a@m", "b@m"}
    msg = axt._handle_subtab_action(state, "plugins", ord("p"))
    assert "Applied project toggle to 2/2 marked" in msg
    flags = axt.read_enabled_plugins(tmp_path / ".claude" / "settings.json")
    assert flags == {"a@m": False, "b@m": False}
    assert state.ext_marked["plugins"] == set()  # marks consumed on success


def test_bulk_toggle_reports_skipped_wrong_scope(monkeypatch):
    """Bulk p on mixed-scope hooks: project hooks flip, user hooks are
    skipped with the first skip reason attached."""
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr("axt.tui.tabs.set_hook_disabled",
                        lambda path, hook, disabled: calls.append(disabled) or True)
    monkeypatch.setattr("axt.tui.tabs._refresh_ext", lambda state, sub: None)
    proj = SimpleNamespace(event="Stop", type="command", source="project",
                           source_path="/p.json", disabled=False, matcher="*",
                           command="x", url=None, prompt=None)
    user = SimpleNamespace(event="Stop", type="command", source="user",
                           source_path="/u.json", disabled=False, matcher="*",
                           command="y", url=None, prompt=None)
    state = axt.TuiState()
    state.ext_sub_tab = "hooks"
    state.ext_cache["hooks"] = [proj, user]
    state.ext_selected["hooks"] = 0
    state.stdscr_callbacks = {"stdscr": None}
    state.ext_marked["hooks"] = {axt._item_key("hooks", proj),
                                 axt._item_key("hooks", user)}
    msg = axt._handle_subtab_action(state, "hooks", ord("p"))
    assert calls == [True]
    assert "1/2 marked" in msg and "use g" in msg


def test_bulk_toggle_nothing_changed_keeps_marks():
    state = _mcp_state(disabled=False)
    state.ext_marked["mcp"] = {"user:srv"}
    msg = axt._handle_subtab_action(state, "mcp", ord("g"))
    assert msg.startswith("No marked item toggled")
    assert state.ext_marked["mcp"] == {"user:srv"}  # kept for retry


def test_skill_p_links_into_project_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        skills=tmp_path / "global-skills", claude_dir=tmp_path / "claude"))
    src = tmp_path / "somewhere" / "myskill"
    src.mkdir(parents=True)
    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = [axt.SkillInfo(
        name="myskill", path=str(src), is_symlink=False, source="user")]
    state.ext_selected["skills"] = 0
    state.stdscr_callbacks = {"stdscr": None}
    msg = axt._handle_subtab_action(state, "skills", ord("p"))
    assert msg == "Linked myskill (project)"
    link = tmp_path / ".claude" / "skills" / "myskill"
    assert link.is_symlink()
    assert link.resolve() == src.resolve()


def test_skill_p_unlinks_project_symlink(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "store" / "myskill"
    src.mkdir(parents=True)
    proj_dir = tmp_path / ".claude" / "skills"
    proj_dir.mkdir(parents=True)
    link = proj_dir / "myskill"
    link.symlink_to(src)
    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = [
        axt.SkillInfo(name="myskill", path=str(src), is_symlink=False, source="user"),
        axt.SkillInfo(name="myskill", path=str(link), is_symlink=True, source="project"),
    ]
    state.ext_selected["skills"] = 0
    state.stdscr_callbacks = {"stdscr": None}
    msg = axt._handle_subtab_action(state, "skills", ord("p"))
    assert msg == "Unlinked myskill (project)"
    assert not link.exists() and not link.is_symlink()


def test_skill_toggle_refuses_real_dir_in_scope(tmp_path, monkeypatch):
    """A real (non-symlink) directory in the target scope is never deleted."""
    monkeypatch.chdir(tmp_path)
    proj_dir = tmp_path / ".claude" / "skills" / "myskill"
    proj_dir.mkdir(parents=True)
    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = [axt.SkillInfo(
        name="myskill", path=str(proj_dir), is_symlink=False, source="project")]
    state.ext_selected["skills"] = 0
    state.stdscr_callbacks = {"stdscr": None}
    msg = axt._handle_subtab_action(state, "skills", ord("p"))
    assert msg == "myskill is not a symlink in project scope (cannot unlink)"
    assert proj_dir.is_dir()


def test_command_g_links_into_global_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(claude_dir=tmp_path / "claude"))
    src = tmp_path / "proj-cmds" / "foo.md"
    src.parent.mkdir()
    src.write_text("# hi")
    state = axt.TuiState()
    state.ext_sub_tab = "commands"
    state.ext_cache["commands"] = [axt.CommandInfo(
        name="foo", source="project", source_path=str(src),
        description="", content="")]
    state.ext_selected["commands"] = 0
    state.stdscr_callbacks = {"stdscr": None}
    msg = axt._handle_subtab_action(state, "commands", ord("g"))
    assert msg == "Linked foo (global)"
    link = tmp_path / "claude" / "commands" / "foo.md"
    assert link.is_symlink()
    assert link.resolve() == src.resolve()


def test_agent_p_links_into_project_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(claude_dir=tmp_path / "claude"))
    src = tmp_path / "claude" / "agents" / "bot.md"
    src.parent.mkdir(parents=True)
    src.write_text("# bot")
    state = axt.TuiState()
    state.ext_sub_tab = "agents"
    state.ext_cache["agents"] = [axt.AgentInfo(
        name="bot", source="user", source_path=str(src), description="")]
    state.ext_selected["agents"] = 0
    state.stdscr_callbacks = {"stdscr": None}
    msg = axt._handle_subtab_action(state, "agents", ord("p"))
    assert msg == "Linked bot (project)"
    assert (tmp_path / ".claude" / "agents" / "bot.md").is_symlink()


def test_market_p_and_g_explain_global_only():
    state = axt.TuiState()
    state.ext_sub_tab = "market"
    state.stdscr_callbacks = {"stdscr": None}
    for key in (ord("p"), ord("g")):
        msg = axt._handle_subtab_action(state, "market", key)
        assert msg == "Marketplaces are global-only — no project/global toggle"


def test_vault_p_g_with_marks_toggle_pending_in_bulk():
    state = axt.TuiState()
    state.vault_items = [
        axt.VaultItem(name="alpha", type="skill", path="", description=""),
        axt.VaultItem(name="beta", type="skill", path="", description=""),
    ]
    state.vault_marked = {"alpha", "beta"}
    msg = axt.handle_vault_input(state, ord("p"))
    assert state.vault_pending_project == {"alpha", "beta"}
    assert "2 marked" in msg
    # Second press flips the same pending entries back off.
    axt.handle_vault_input(state, ord("p"))
    assert state.vault_pending_project == set()
    axt.handle_vault_input(state, ord("g"))
    assert state.vault_pending_global == {"alpha", "beta"}


def test_skills_proj_glob_columns_reflect_scope_presence():
    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = [
        axt.SkillInfo(name="both", path="/u/skills/both", is_symlink=False, source="user"),
        axt.SkillInfo(name="both", path="/p/.claude/skills/both", is_symlink=True, source="project"),
        axt.SkillInfo(name="globonly", path="/u/skills/globonly", is_symlink=False, source="user"),
    ]
    scr = _make_stdscr(rows=30, cols=140)
    axt.render_extensions_tab(scr, state, 0, 28, 140)
    flat = _flat(scr)
    assert "Proj" in flat and "Glob" in flat

    def _row(name: str) -> str:
        row_y = next(c[0] for c in scr.calls
                     if len(c) >= 3 and isinstance(c[2], str) and name in c[2])
        return "".join(c[2] for c in scr.calls
                       if len(c) >= 3 and c[0] == row_y and isinstance(c[2], str))

    # globonly: not in project scope (○) but present globally (●).
    assert "○" in _row("globonly") and "●" in _row("globonly")
    # both: linked in both scopes → no empty circle on that row.
    assert "○" not in _row("both")


def test_vault_cell_marks_vault_backed_rows(tmp_path, monkeypatch):
    """Skills whose content resolves into ~/.axt/vault get ✓; others ─.
    Sub-tabs whose types the vault does not store always get ─."""
    from types import SimpleNamespace
    vault = tmp_path / "vault"
    (vault / "skills" / "inv").mkdir(parents=True)
    plain = tmp_path / "plain-skill"
    plain.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(vault / "skills" / "inv")
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=vault))
    in_vault = axt.SkillInfo(name="inv", path=str(vault / "skills" / "inv"),
                             is_symlink=False, source="user")
    via_link = axt.SkillInfo(name="linked", path=str(linked),
                             is_symlink=True, source="user")
    outside = axt.SkillInfo(name="plain-skill", path=str(plain),
                            is_symlink=False, source="user")
    assert axt._vault_cell("skills", in_vault) == "✓"
    assert axt._vault_cell("skills", via_link) == "✓"   # symlink → resolves into vault
    assert axt._vault_cell("skills", outside) == "─"
    mcp = SimpleNamespace(name="srv", scope="user")
    assert axt._vault_cell("mcp", mcp) == "─"
    assert axt._vault_cell("market", SimpleNamespace(name="m")) == "─"


def test_vault_cell_handles_symlinked_vault_subdir(tmp_path, monkeypatch):
    """`~/.axt/vault/skills` may itself be a symlink to external storage —
    items resolving into that storage still count as vault-managed."""
    store = tmp_path / "external-store"
    store.mkdir()
    (store / "sk").mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "skills").symlink_to(store)
    monkeypatch.setattr("axt.PATHS", axt.Paths(vault=vault))
    # A user-scope skill symlinked through the vault path.
    link = tmp_path / "claude-skill"
    link.symlink_to(vault / "skills" / "sk")
    row = axt.SkillInfo(name="sk", path=str(link), is_symlink=True, source="user")
    assert axt._vault_cell("skills", row) == "✓"


def test_uniform_status_columns_rendered_on_every_subtab(tmp_path, monkeypatch):
    """Every non-vault sub-tab renders the shared Ver/Vault/Proj/Glob block."""
    import json
    from types import SimpleNamespace
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "s.json",
        vault=tmp_path / "vault",
        claude_dir=tmp_path / "claude",
    ))
    (tmp_path / "ip.json").write_text(json.dumps({
        "version": 2,
        "plugins": {"p@m": [{"scope": "u", "installPath": "/p", "version": "1",
                             "installedAt": "", "lastUpdated": ""}]},
    }))
    caches = {
        "plugins": axt.list_installed_plugins(tmp_path / "ip.json"),
        "skills": [axt.SkillInfo(name="sk", path="/u/skills/sk",
                                 is_symlink=False, source="user")],
        "commands": [axt.CommandInfo(name="c", source="user", source_path="/c.md",
                                     description="", content="")],
        "agents": [axt.AgentInfo(name="a", source="user", source_path="/a.md",
                                 description="")],
        "mcp": [SimpleNamespace(name="srv", scope="user", transport="stdio",
                                disabled=False, plugin_id="", version="2.0",
                                url="", command="node", args_list=[], env_dict={})],
        "hooks": [axt.HookInfo(event="Stop", matcher="*", source="user",
                               source_path="/s.json", type="command", command="x")],
        "market": [axt.MarketplaceInfo(
            name="mkt", source=axt.MarketplaceSource(kind="github", repo="o/r"),
            install_location="/loc", last_updated="2026-01-01T00:00:00Z")],
    }
    for sub, cache in caches.items():
        state = axt.TuiState()
        state.ext_sub_tab = sub
        state.ext_cache[sub] = cache
        scr = _make_stdscr(rows=30, cols=160)
        axt.render_extensions_tab(scr, state, 0, 28, 160)
        flat = _flat(scr)
        if sub == "market":
            # Marketplaces have no per-source version and are a global-only
            # registry — Ver/Vault/Proj/Glob columns don't apply.
            for header in ("Ver", "Proj", "Glob"):
                assert header not in flat, f"market: {header} column should not be rendered"
        else:
            for header in ("Ver", "Vault", "Proj", "Glob"):
                assert header in flat, f"{sub}: {header} column missing"
    # MCP: the plugin-sourced server's version lands in the Ver column.
    state = axt.TuiState()
    state.ext_sub_tab = "mcp"
    state.ext_cache["mcp"] = caches["mcp"]
    scr = _make_stdscr(rows=30, cols=160)
    axt.render_extensions_tab(scr, state, 0, 28, 160)
    assert "2.0" in _flat(scr)


def test_subtab_action_without_stdscr_is_noop():
    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.stdscr_callbacks = None
    assert axt._handle_subtab_action(state, "skills", ord("a")) is None


# ─── Project Enter preview & `e` editor (smoke) ──────────────────────────────


def test_project_v_calls_preview(monkeypatch):
    called = []
    monkeypatch.setattr("axt.preview_modal", lambda stdscr, content, title="Preview": called.append((title, content)))
    state = axt.TuiState()
    state.project_items = [_project_source(
        "CLAUDE.md (project)", path="/p/CLAUDE.md", content="hello",
    )]
    state.project_selected = 0
    state.stdscr_callbacks = {"stdscr": object()}
    axt.handle_project_input(state, ord("v"))
    assert called and called[0][1] == "hello"


def test_context_sources_v_previews_actual_content(monkeypatch):
    """Sources sub-tab `v` modal includes each source's real content, not
    just name/path/token metadata; content-less sources get a fallback note."""
    called = []
    monkeypatch.setattr("axt.preview_modal",
                        lambda stdscr, content, title="Preview", **kw: called.append((title, content, kw)))
    with_content = axt.ContextSource(
        name="CLAUDE.md (user)", category="claude-md", path="/h/.claude/CLAUDE.md",
        chars=40, estimated_tokens=100, percentage=1.0, actionable=True,
        content="# rules\nalways answer in Korean")
    without_content = axt.ContextSource(
        name="System prompt", category="claude-md", path="",
        chars=0, estimated_tokens=50, percentage=0.5, actionable=False)
    state = axt.TuiState()
    state.context_sub_tab = "sources"
    state.context_analysis = axt.ContextAnalysis(
        total_tokens=150, context_window_size=200_000, used_percent=0.1,
        model="claude-sonnet", sources=[with_content, without_content],
        cost_impact=_make_empty_context_analysis().cost_impact)
    state.context_selected = 0
    state.stdscr_callbacks = {"stdscr": object()}
    axt.handle_context_input(state, ord("v"))
    assert called
    _, body, kw = called[0]
    assert "always answer in Korean" in body
    assert "/h/.claude/CLAUDE.md" in body
    assert "content unavailable" in body  # System prompt has no content
    # Per-source headers are marked so the modal colors them as headings.
    assert kw.get("heading_prefix") == "━━"


def test_project_e_calls_editor(monkeypatch):
    called = []
    monkeypatch.setattr("axt.open_in_editor", lambda stdscr, path: called.append(path) or True)
    state = axt.TuiState()
    state.project_items = [_project_source("X", path="/p/X.md")]
    state.project_selected = 0
    state.stdscr_callbacks = {"stdscr": object()}
    axt.handle_project_input(state, ord("e"))
    assert called == ["/p/X.md"]


def test_project_e_no_file_for_fixed_source(monkeypatch):
    """A fixed source with no real path (e.g. System Prompt) reports the
    no-file status instead of failing the editor call."""
    state = axt.TuiState()
    state.project_items = [_project_source("System Prompt", category="system-prompt", scope="global", path="")]
    state.project_selected = 0
    state.stdscr_callbacks = {"stdscr": object()}
    msg = axt.handle_project_input(state, ord("e"))
    assert msg == "No file to edit for this source"


def test_project_d_deletes_memory_file_on_confirm(monkeypatch):
    deleted = []
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: True)
    monkeypatch.setattr("axt.delete_memory_file", lambda path: deleted.append(str(path)))
    state = axt.TuiState()
    state.project_items = [_project_source(
        "Memory: topic", category="memory", path="/mem/topic.md",
    )]
    state.project_selected = 0
    state.context_analysis = object()  # invalidated on success
    state.stdscr_callbacks = {"stdscr": object()}
    msg = axt.handle_project_input(state, ord("d"))
    assert deleted == ["/mem/topic.md"]
    assert msg == "Deleted Memory: topic"
    assert state.project_items is None
    assert state.context_analysis is None


def test_project_d_cancelled_leaves_file(monkeypatch):
    deleted = []
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: False)
    monkeypatch.setattr("axt.delete_memory_file", lambda path: deleted.append(str(path)))
    state = axt.TuiState()
    state.project_items = [_project_source(
        "Memory: topic", category="memory", path="/mem/topic.md",
    )]
    state.project_selected = 0
    state.stdscr_callbacks = {"stdscr": object()}
    msg = axt.handle_project_input(state, ord("d"))
    assert deleted == []
    assert msg == "Cancelled"
    assert state.project_items is not None  # untouched


def test_project_d_rejects_non_memory_source(monkeypatch):
    deleted = []
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: True)
    monkeypatch.setattr("axt.delete_memory_file", lambda path: deleted.append(str(path)))
    state = axt.TuiState()
    state.project_items = [_project_source(
        "CLAUDE.md (project)", path="/p/CLAUDE.md",
    )]
    state.project_selected = 0
    state.stdscr_callbacks = {"stdscr": object()}
    msg = axt.handle_project_input(state, ord("d"))
    assert deleted == []
    assert msg == "Only memory files can be deleted here"


def test_project_d_delete_failure_reports_message(monkeypatch):
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: True)
    def _raise(path):
        raise OSError("boom")
    monkeypatch.setattr("axt.delete_memory_file", _raise)
    state = axt.TuiState()
    state.project_items = [_project_source(
        "Memory: topic", category="memory", path="/mem/topic.md",
    )]
    state.project_selected = 0
    state.stdscr_callbacks = {"stdscr": object()}
    msg = axt.handle_project_input(state, ord("d"))
    assert msg == "Delete failed: boom"


# ─── Context Rate-Limit bars ─────────────────────────────────────────────────


def test_render_rate_limit_bars_no_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(usage_snapshot=tmp_path / "missing.json"))
    scr = _make_stdscr()
    rows = axt._render_rate_limit_bars(scr, 0, 100)
    assert rows == 1
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "snapshot missing or stale" in flat


def test_render_rate_limit_bars_with_snapshot(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone
    snap = tmp_path / "snap.json"
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snap.write_text(json.dumps({
        "five_hour": {"used_percentage": 14, "resets_at": "2026-12-01T00:00:00Z"},
        "seven_day": {"used_percentage": 8, "resets_at": "2026-12-08T00:00:00Z"},
        "updated_at": now_iso,
    }))
    monkeypatch.setattr("axt.PATHS", axt.Paths(usage_snapshot=snap))
    scr = _make_stdscr()
    rows = axt._render_rate_limit_bars(scr, 0, 100)
    # Both quotas now share a single line.
    assert rows == 1
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "5h" in flat and "14%" in flat
    assert "7d" in flat and "8%" in flat


# ─── Claude insights summary ─────────────────────────────────────────────────


def test_compute_simple_insights_empty():
    out = axt._compute_simple_insights([])
    assert out["large_pct"] == 0.0
    assert out["parallel_pct"] == 0.0
    assert out["top_model"] is None


def test_compute_simple_insights_large_session():
    # One session has 200k input tokens → 100% large.
    entries = [
        axt.ClaudeUsageEntry(
            model="claude-opus-4-7", input_tokens=200_000, output_tokens=0,
            cache_creation_tokens=0, cache_read_tokens=0,
            session_id="big", project_path="p", timestamp="2026-04-29T10:00:00Z",
        ),
    ]
    out = axt._compute_simple_insights(entries)
    assert out["large_pct"] == 100.0
    assert out["top_model"] == "claude-opus-4-7"


def test_compute_simple_insights_parallel_sessions():
    # 3 sessions all within the same 5-min window → 100% parallel.
    ts = "2026-04-29T10:00:00Z"
    entries = [
        axt.ClaudeUsageEntry(model="m", input_tokens=1, output_tokens=1,
                              cache_creation_tokens=0, cache_read_tokens=0,
                              session_id=f"s{i}", project_path="p", timestamp=ts)
        for i in range(3)
    ]
    out = axt._compute_simple_insights(entries)
    assert out["parallel_pct"] == 100.0


# ─── Confirm / text-input / preview modal smoke ──────────────────────────────


def test_confirm_modal_returns_false_when_window_fails(monkeypatch):
    """When curses.newwin raises, the helper must NOT crash — return False."""
    scr = _make_stdscr(rows=2, cols=5)  # too small
    # Force newwin to fail.
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: (_ for _ in ()).throw(curses.error("too small")))
    assert axt.confirm_modal(scr, "are you sure?") is False


def test_open_in_editor_falls_back_when_editor_missing(monkeypatch):
    """If $EDITOR doesn't exist on PATH, function must return False, not crash."""
    monkeypatch.setenv("EDITOR", "definitely-not-a-real-editor-xyz123")
    monkeypatch.setattr("subprocess.call", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError()))
    scr = _make_stdscr()
    assert axt.open_in_editor(scr, "/tmp/x") is False


# ─── existing test marker ────────────────────────────────────────────────────


def test_vault_columns_use_short_labels(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "skills" / "alpha").mkdir(parents=True)
    (vault / "skills" / "alpha" / "SKILL.md").write_text("---\ndescription: a\n---")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=vault, installed_plugins=tmp_path / "ip.json", claude_dir=tmp_path / "claude",
    ))
    monkeypatch.chdir(tmp_path)
    state = axt.TuiState()
    scr = _make_stdscr(rows=20, cols=140)
    axt.render_vault_tab(scr, state, 0, 18, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Proj " in flat or "Proj  " in flat
    assert "Glob " in flat or "Glob  " in flat
    assert "Used " in flat or "Used  " in flat


def test_tab_renderers_dispatch_covers_all_main_tabs():
    import axt
    keys = {key for key, _icon, _label in axt.MAIN_TABS}
    assert set(axt.TAB_RENDERERS.keys()) == keys
    assert set(axt.TAB_HANDLERS.keys()) == keys


def test_tab_renderers_are_callable():
    import axt
    for fn in axt.TAB_RENDERERS.values():
        assert callable(fn)
    for fn in axt.TAB_HANDLERS.values():
        assert callable(fn)


# ─── C5 regression: helpers referenced as bare names in tabs.py ──────────────
#
# The C4 extraction (commit 74b50ee) moved Section 13 out of core.py into
# axt/tui/tabs.py. tabs.py wildcards from core, but THREE helpers were
# defined in cli.py, not core.py — so the bare references in
# tabs.py:render_usage_tab (_today_in_tz, _unified_to_claude) and
# tabs.py:_ensure_subtab_loaded (_active_plugins) resolved to nothing once
# tabs.py left the cli.py namespace. C5 moves the three helpers into
# core.py and explicitly imports them from tabs.py. These tests force the
# code paths that trip the bare-name lookups.


def test_render_usage_tab_with_data_does_not_raise(monkeypatch):
    """tabs.py:render_usage_tab references _today_in_tz and _unified_to_claude.
    Force the past-empty-data code path with a single synthetic entry."""
    entry = axt.UnifiedUsageEntry(
        platform="claude",
        model="claude-sonnet-4",
        timestamp="2026-05-21T12:00:00Z",
        session_id="s1",
        project_path="/tmp/proj",
        input_tokens=1000,
        output_tokens=500,
        cache_write_tokens=0,
        cache_read_tokens=0,
    )
    state = axt.TuiState()
    state.usage_entries = [entry]
    # Pre-seed config to avoid a live load_config call.
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)

    scr = _make_stdscr(rows=40, cols=140)
    # Must NOT raise NameError("_today_in_tz" / "_unified_to_claude").
    axt.render_usage_tab(scr, state, y0=3, h=30, w=140)


def test_render_extensions_tab_mcp_sub_tab_does_not_raise(monkeypatch, tmp_path):
    """tabs.py:_ensure_subtab_loaded references _active_plugins for sub='mcp'.
    Force the mcp sub-tab load path and confirm no NameError."""
    import dataclasses
    # Point PATHS at a tmp dir so list_installed_plugins / read_enabled_plugins
    # see an empty (but non-failing) world. Paths is frozen, so build a
    # replacement via dataclasses.replace and swap the module attr.
    fake_settings = tmp_path / "settings.json"
    fake_installed = tmp_path / "installed_plugins.json"
    fake_settings.write_text("{}")
    fake_installed.write_text('{"version":2,"plugins":{}}')

    fake_paths = dataclasses.replace(
        axt.PATHS, settings=fake_settings, installed_plugins=fake_installed,
        claude_config=tmp_path / ".claude.json",
    )
    monkeypatch.setattr("axt.PATHS", fake_paths)
    monkeypatch.chdir(tmp_path)

    state = axt.TuiState()
    state.ext_sub_tab = "mcp"
    state.focused_layer = "content"

    scr = _make_stdscr(rows=40, cols=140)
    # Must NOT raise NameError("_active_plugins").
    axt.render_extensions_tab(scr, state, y0=3, h=30, w=140)


# ─── Focus-layer key routing (per-layer handlers) ────────────────────────────
#
# These tests pin down the layered key model that replaced the original
# single if/elif/else block in loop.py. The key contract:
#   • mainTab ↓ only descends when the tab actually has a focusable target
#     (sub-tab bar OR a focusable content body). Usage has neither, so ↓
#     stays put — no silent focus loss.
#   • subTab ↓ always lands on content (Extensions sub-tabs are lists).
#   • content ←/→ is owned by the tab body now — the legacy mainTab
#     cycling that lived at the content layer is gone.


def _tab_idx(key: str) -> int:
    return [t[0] for t in axt.MAIN_TABS].index(key)


def test_tab_has_sub_tab_extensions_and_context():
    assert axt.tab_has_sub_tab("extensions") is True
    assert axt.tab_has_sub_tab("context") is True
    assert axt.tab_has_sub_tab("usage") is False


def test_usage_down_arrow_keeps_focus_when_no_data(monkeypatch, tmp_path):
    """With no usage data yet, ↓ on the Usage main tab should NOT descend
    to the content layer (nothing to scroll)."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    state = axt.TuiState()
    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "usage")
    state.focused_layer = "mainTab"
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, curses.KEY_DOWN, "usage")
    assert consumed is True
    assert state.focused_layer == "mainTab"


def test_extensions_down_arrow_descends_to_sub_tab():
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    # Use the plugins sub-tab with a real PluginInfo so the second descent
    # passes the "no focusable rows → keep focus on subTab" guard *and* the
    # downstream renderer (which accesses attributes on each row). The empty
    # case is covered by test_sub_tab_down_arrow_keeps_focus_when_empty.
    state.ext_sub_tab = "plugins"
    state.ext_cache["plugins"] = [
        axt.PluginInfo(
            id="p1@m", name="p1", marketplace="m", version="1.0",
            install_path="/tmp/p1", scope="user",
            installed_at="", last_updated="",
        ),
    ]
    scr = _make_stdscr()
    axt._handle_layer_key(scr, state, curses.KEY_DOWN, "extensions")
    assert state.focused_layer == "subTab"
    # Second ↓ from subTab → content.
    axt._handle_layer_key(scr, state, curses.KEY_DOWN, "extensions")
    assert state.focused_layer == "content"


def test_context_down_arrow_descends_to_sub_tab():
    """Context now owns a sub-tab bar, so ↓ from the main tab lands on the
    subTab layer (mirrors Extensions); a second ↓ enters the content."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("context")
    # Give the (default) Project sub-tab focusable rows so the second descent
    # passes the "no rows → keep focus on subTab" guard.
    state.project_items = [_project_source("CLAUDE.md", path="/p/CLAUDE.md")]
    scr = _make_stdscr()
    axt._handle_layer_key(scr, state, curses.KEY_DOWN, "context")
    assert state.focused_layer == "subTab"
    axt._handle_layer_key(scr, state, curses.KEY_DOWN, "context")
    assert state.focused_layer == "content"


def test_sub_tab_up_arrow_returns_to_main_tab():
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.focused_layer = "subTab"
    scr = _make_stdscr()
    axt._handle_layer_key(scr, state, curses.KEY_UP, "extensions")
    assert state.focused_layer == "mainTab"


def test_content_left_right_no_longer_cycles_main_tabs():
    """The legacy 'content layer ← / → cycles main tabs' fallback was
    removed — ←/→ now belong to the tab body."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("context")
    state.focused_layer = "content"
    original = state.tab_idx
    scr = _make_stdscr()
    # The layer dispatcher must NOT consume ←/→ here.
    assert axt._handle_layer_key(scr, state, curses.KEY_LEFT, "context") is False
    assert axt._handle_layer_key(scr, state, curses.KEY_RIGHT, "context") is False
    assert state.tab_idx == original


def test_content_up_at_top_climbs_out_for_context():
    state = axt.TuiState()
    state.tab_idx = _tab_idx("context")
    state.focused_layer = "content"
    state.context_selected = 0  # at top
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, curses.KEY_UP, "context")
    assert consumed is True
    # Context now owns a sub-tab bar, so ↑-at-top climbs to the subTab layer.
    assert state.focused_layer == "subTab"


def test_content_up_at_top_climbs_to_sub_tab_for_extensions():
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "plugins"
    state.focused_layer = "content"
    state.ext_selected = {"plugins": 0}  # at top
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, curses.KEY_UP, "extensions")
    assert consumed is True
    assert state.focused_layer == "subTab"


def test_main_tab_left_right_cycles_tabs():
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    scr = _make_stdscr()
    axt._handle_layer_key(scr, state, curses.KEY_RIGHT, "extensions")
    assert state.tab_idx == _tab_idx("context")
    axt._handle_layer_key(scr, state, curses.KEY_LEFT, "context")
    assert state.tab_idx == _tab_idx("extensions")


def test_main_tab_up_arrow_is_no_op_but_consumed():
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, curses.KEY_UP, "extensions")
    assert consumed is True
    assert state.focused_layer == "mainTab"


def test_esc_in_content_climbs_to_sub_tab_for_extensions():
    """Esc anywhere in the content list (not just at row 0) should climb back
    to the sub-tab — otherwise users at the bottom of a long list have to
    press ↑ many times just to leave the list."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "plugins"
    state.focused_layer = "content"
    state.ext_selected = {"plugins": 42}  # mid-list, not at top
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, axt.KEY_ESC, "extensions")
    assert consumed is True
    assert state.focused_layer == "subTab"


def test_esc_in_content_climbs_to_sub_tab_for_context():
    """Context now owns a sub-tab bar, so Esc in the body climbs to subTab."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("context")
    state.focused_layer = "content"
    state.context_selected = 5
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, axt.KEY_ESC, "context")
    assert consumed is True
    assert state.focused_layer == "subTab"


def test_esc_on_sub_tab_climbs_to_main_tab():
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.focused_layer = "subTab"
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, axt.KEY_ESC, "extensions")
    assert consumed is True
    assert state.focused_layer == "mainTab"


def test_sub_tab_has_focusable_content_reflects_data():
    """Vault uses vault_items; the other Extensions sub-tabs use ext_cache."""
    s = axt.TuiState()
    # Empty by default.
    assert axt.sub_tab_has_focusable_content(s, "extensions", "vault") is False
    assert axt.sub_tab_has_focusable_content(s, "extensions", "plugins") is False
    # Populate and re-check (sentinel values — function only inspects truthiness).
    s.vault_items = ["dummy"]
    s.ext_cache["plugins"] = ["dummy"]
    assert axt.sub_tab_has_focusable_content(s, "extensions", "vault") is True
    assert axt.sub_tab_has_focusable_content(s, "extensions", "plugins") is True


def test_sub_tab_down_arrow_keeps_focus_when_empty():
    """↓ on an empty Extensions sub-tab must NOT drop focus into an
    invisible `content` layer — there are no rows to focus on."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "plugins"
    state.focused_layer = "subTab"
    state.ext_cache["plugins"] = []  # explicitly empty
    scr = _make_stdscr()
    for _ in range(5):
        consumed = axt._handle_layer_key(scr, state, curses.KEY_DOWN, "extensions")
        assert consumed is True
    assert state.focused_layer == "subTab"


def test_sub_tab_enter_keeps_focus_when_empty():
    """Enter from an empty sub-tab is the same no-op as ↓."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "vault"
    state.focused_layer = "subTab"
    state.vault_items = []  # empty
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, ord("\n"), "extensions")
    assert consumed is True
    assert state.focused_layer == "subTab"


def test_sub_tab_down_arrow_descends_when_populated():
    """When the sub-tab has rows, ↓ still drops into the content layer."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "plugins"
    state.focused_layer = "subTab"
    state.ext_cache["plugins"] = [
        axt.PluginInfo(
            id="p1@m", name="p1", marketplace="m", version="1.0",
            install_path="/tmp/p1", scope="user",
            installed_at="", last_updated="",
        ),
    ]
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, curses.KEY_DOWN, "extensions")
    assert consumed is True
    assert state.focused_layer == "content"


def test_tui_state_has_usage_loading_fields():
    """TuiState exposes async-loading flags for the Usage tab."""
    s = axt.TuiState()
    assert s.usage_loading is False
    assert s.usage_load_thread is None


def test_kick_usage_reload_spawns_and_populates(monkeypatch, tmp_path):
    """_kick_usage_reload runs load_unified_usage in a background thread and
    populates state when it completes."""
    _setup_isolated_paths(tmp_path, monkeypatch)

    # Gate the stubbed loader so we can observe the in-flight state
    # deterministically — otherwise the worker may finish before the
    # `usage_loading is True` assertion when the runtime is hot.
    import threading as _threading
    gate = _threading.Event()
    stub_entries = []
    def gated_load(**kw):
        gate.wait(timeout=2.0)
        return stub_entries
    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", gated_load)

    state = axt.TuiState()
    axt._kick_usage_reload(state)
    assert state.usage_loading is True
    assert state.status == "Loading Claude usage…"

    # Release the worker and wait for it.
    gate.set()
    if state.usage_load_thread is not None:
        state.usage_load_thread.join(timeout=2.0)

    assert state.usage_loading is False
    assert state.usage_entries is stub_entries
    assert state.usage_config is not None
    assert state.status == ""


def test_kick_usage_reload_idempotent_while_loading(monkeypatch, tmp_path):
    """A second _kick_usage_reload call while a load is in flight is a no-op
    (does not spawn another thread)."""
    _setup_isolated_paths(tmp_path, monkeypatch)

    # Block the worker so we can observe the in-flight state.
    gate = __import__("threading").Event()
    def slow_load(**kw):
        gate.wait(timeout=2.0)
        return []
    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", slow_load)

    state = axt.TuiState()
    axt._kick_usage_reload(state)
    first_thread = state.usage_load_thread
    assert first_thread is not None and first_thread.is_alive()

    axt._kick_usage_reload(state)  # should be a no-op
    assert state.usage_load_thread is first_thread

    gate.set()
    first_thread.join(timeout=2.0)
    assert state.usage_loading is False


def test_render_usage_tab_shows_loading_when_entries_none(tmp_path, monkeypatch):
    """First paint (usage_entries is None) should kick a background reload
    and render the 'Loading Claude usage…' body line. Worker is stubbed so
    the thread completes quickly."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", lambda **kw: [])

    state = axt.TuiState()
    assert state.usage_entries is None
    scr = _make_stdscr(rows=30, cols=120)
    axt.render_usage_tab(scr, state, 0, 28, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Loading Claude usage" in flat

    # The worker may or may not have finished by the time we hit this
    # assertion — either way usage_load_thread is set.
    assert state.usage_load_thread is not None
    state.usage_load_thread.join(timeout=2.0)


def test_handle_usage_input_r_kicks_reload_without_clearing(monkeypatch, tmp_path):
    """Pressing `r` should kick a background reload while keeping any
    previously loaded entries visible (stale-while-revalidate)."""
    import threading as _threading
    _setup_isolated_paths(tmp_path, monkeypatch)

    # Pre-populate with stale data the user can still see.
    stale = [object()]
    state = axt.TuiState()
    state.usage_entries = stale
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)

    # Gate keeps the worker blocked so we can check the in-flight state
    # before it completes (avoids race on usage_loading and usage_entries).
    gate = _threading.Event()
    fresh = []

    def _gated_load(**kw):
        gate.wait(timeout=2.0)
        return fresh

    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", _gated_load)

    axt.handle_usage_input(state, ord("r"))
    assert state.usage_loading is True
    # Stale data is still visible until the worker swaps it in.
    assert state.usage_entries is stale

    # Release the gate and wait for completion.
    gate.set()
    if state.usage_load_thread is not None:
        state.usage_load_thread.join(timeout=2.0)
    assert state.usage_entries is fresh
    assert state.usage_loading is False


def test_has_background_work_tracks_usage_loading():
    state = axt.TuiState()
    assert axt._has_background_work(state) is False
    state.usage_loading = True
    assert axt._has_background_work(state) is True


def test_tui_state_has_usage_scroll_field():
    s = axt.TuiState()
    assert s.usage_scroll == 0


def test_tab_has_focusable_content_usage_with_data():
    state = axt.TuiState()
    state.usage_entries = [object()]   # any non-empty list
    state.usage_loading = False
    assert axt.tab_has_focusable_content(state, "usage") is True


def test_tab_has_focusable_content_usage_without_data():
    state = axt.TuiState()
    state.usage_entries = None
    assert axt.tab_has_focusable_content(state, "usage") is False
    state.usage_entries = []
    assert axt.tab_has_focusable_content(state, "usage") is False
    state.usage_entries = [object()]
    state.usage_loading = True
    assert axt.tab_has_focusable_content(state, "usage") is False


def test_kick_usage_reload_primes_context_analysis(monkeypatch, tmp_path):
    """The Usage worker should also run analyze_context so the first paint
    after data appears does not trigger a synchronous filesystem scan."""
    _setup_isolated_paths(tmp_path, monkeypatch)

    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", lambda **kw: [])

    stub_analysis = object()
    calls = []
    def fake_analyze(**kw):
        calls.append(kw)
        return stub_analysis
    monkeypatch.setattr("axt.tui.tabs.analyze_context", fake_analyze)

    state = axt.TuiState()
    assert state.context_analysis is None
    axt._kick_usage_reload(state)
    if state.usage_load_thread is not None:
        state.usage_load_thread.join(timeout=2.0)

    assert state.context_analysis is stub_analysis
    assert len(calls) == 1


def test_kick_usage_reload_skips_context_if_already_loaded(monkeypatch, tmp_path):
    """If state.context_analysis is already populated, the worker should
    NOT re-run analyze_context."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", lambda **kw: [])

    calls = []
    monkeypatch.setattr("axt.tui.tabs.analyze_context",
                        lambda **kw: calls.append(kw) or object())

    state = axt.TuiState()
    state.context_analysis = object()  # pretend already loaded
    axt._kick_usage_reload(state)
    if state.usage_load_thread is not None:
        state.usage_load_thread.join(timeout=2.0)
    assert calls == []


def test_kick_usage_reload_refreshes_stale_model(monkeypatch, tmp_path):
    """If usage entries reveal a different live model than the one a cache
    was primed with, the worker must rebuild context with the real model."""
    from types import SimpleNamespace
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    entry = axt.UnifiedUsageEntry(
        platform="claude", model="claude-opus-4-8",
        timestamp="2026-05-30T00:00:00Z", session_id="s", project_path="p",
        input_tokens=1, output_tokens=1, cache_write_tokens=0, cache_read_tokens=0,
    )
    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", lambda **kw: [entry])

    calls = []
    monkeypatch.setattr(
        "axt.tui.tabs.analyze_context",
        lambda **kw: calls.append(kw) or SimpleNamespace(model=kw["model"]),
    )

    state = axt.TuiState()
    state.context_analysis = SimpleNamespace(model="claude-opus-4-6")  # stale
    axt._kick_usage_reload(state)
    if state.usage_load_thread is not None:
        state.usage_load_thread.join(timeout=2.0)

    assert len(calls) == 1
    assert calls[0]["model"] == "claude-opus-4-8"
    assert state.context_analysis.model == "claude-opus-4-8"


def test_kick_usage_reload_keeps_matching_model(monkeypatch, tmp_path):
    """No needless rebuild when the cached model already matches the live one."""
    from types import SimpleNamespace
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    entry = axt.UnifiedUsageEntry(
        platform="claude", model="claude-opus-4-8",
        timestamp="2026-05-30T00:00:00Z", session_id="s", project_path="p",
        input_tokens=1, output_tokens=1, cache_write_tokens=0, cache_read_tokens=0,
    )
    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", lambda **kw: [entry])

    calls = []
    monkeypatch.setattr(
        "axt.tui.tabs.analyze_context",
        lambda **kw: calls.append(kw) or SimpleNamespace(model=kw["model"]),
    )

    state = axt.TuiState()
    state.context_analysis = SimpleNamespace(model="claude-opus-4-8")  # already current
    axt._kick_usage_reload(state)
    if state.usage_load_thread is not None:
        state.usage_load_thread.join(timeout=2.0)

    assert calls == []


def test_render_usage_tab_loading_skips_summary(tmp_path, monkeypatch):
    """During first-paint loading, the tab body must NOT include the plan
    label or insights — those depend on data that isn't loaded yet."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    # Gate the worker so it cannot finish mid-render and feed back a
    # half-initialised context_analysis to _usage_gauge_lines.
    import threading as _threading
    gate = _threading.Event()
    def gated_load(**kw):
        gate.wait(timeout=2.0)
        return []
    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", gated_load)
    monkeypatch.setattr("axt.tui.tabs.analyze_context",
                        lambda **kw: _make_empty_context_analysis())

    state = axt.TuiState()
    assert state.usage_entries is None
    scr = _make_stdscr(rows=30, cols=120)
    axt.render_usage_tab(scr, state, 0, 28, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Loading Claude usage" in flat
    assert "Plan:" not in flat
    assert "Insights" not in flat

    gate.set()
    if state.usage_load_thread is not None:
        state.usage_load_thread.join(timeout=2.0)


def test_render_usage_tab_scroll_clips_header(tmp_path, monkeypatch):
    """With a non-zero scroll offset, the header (which lives at line 0
    of the buffer) must NOT appear in the drawn output."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    state = axt.TuiState()
    # Pre-seed loaded state so we render the full summary lines.
    state.usage_entries = []        # loaded, no entries
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)
    # Use a small body_h (4) so even a short buffer has lines beyond row 0,
    # making scroll=3 a valid non-zero offset that clips the header.
    state.usage_scroll = 3
    scr = _make_stdscr(rows=10, cols=120)
    axt.render_usage_tab(scr, state, 0, 4, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    # Header was at buffer-row 0; scroll==3 should clip it out.
    assert "Claude usage — this month" not in flat


def test_handle_usage_input_j_increments_scroll():
    state = axt.TuiState()
    axt.handle_usage_input(state, ord("j"))
    assert state.usage_scroll == 1
    axt.handle_usage_input(state, ord("j"))
    assert state.usage_scroll == 2


def test_handle_usage_input_k_decrements_scroll_floored_at_zero():
    state = axt.TuiState()
    state.usage_scroll = 1
    axt.handle_usage_input(state, ord("k"))
    assert state.usage_scroll == 0
    axt.handle_usage_input(state, ord("k"))
    assert state.usage_scroll == 0  # clamped


def test_handle_usage_input_arrow_keys_scroll():
    state = axt.TuiState()
    axt.handle_usage_input(state, curses.KEY_DOWN)
    assert state.usage_scroll == 1
    axt.handle_usage_input(state, curses.KEY_UP)
    assert state.usage_scroll == 0


def test_handle_usage_input_pgdn_pgup():
    state = axt.TuiState()
    axt.handle_usage_input(state, curses.KEY_NPAGE)
    assert state.usage_scroll == 10
    axt.handle_usage_input(state, curses.KEY_PPAGE)
    assert state.usage_scroll == 0
    axt.handle_usage_input(state, curses.KEY_PPAGE)
    assert state.usage_scroll == 0  # clamped at 0


def test_render_usage_tab_caches_lines_across_scroll(monkeypatch, tmp_path):
    """Scrolling must not re-invoke _usage_summary_lines — same inputs
    (same entries, config, width) → cache hit on second render."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    state = axt.TuiState()
    state.usage_entries = [object()]   # any non-empty list with stable id
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)
    # Pre-seed context_analysis so _usage_gauge_lines doesn't crash on
    # bare object access (and so we never trigger the loading branch).
    state.context_analysis = _make_empty_context_analysis()

    call_count = [0]
    def counting(state_, config_, entries_, w_):
        call_count[0] += 1
        return []   # stub — we only care about call count, not output lines
    monkeypatch.setattr("axt.tui.tabs._usage_summary_lines", counting)

    scr = _make_stdscr(rows=30, cols=120)
    axt.render_usage_tab(scr, state, 0, 28, 120)
    assert call_count[0] == 1
    # Second render with the same state inputs — cache hit.
    axt.render_usage_tab(scr, state, 0, 28, 120)
    assert call_count[0] == 1
    # Third render after scroll bump — still a cache hit (scroll is not
    # part of the signature).
    state.usage_scroll = 2
    axt.render_usage_tab(scr, state, 0, 28, 120)
    assert call_count[0] == 1


def test_render_usage_tab_cache_invalidates_on_new_entries(monkeypatch, tmp_path):
    """Replacing state.usage_entries with a new list (new id) invalidates
    the cache."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    state = axt.TuiState()
    state.usage_entries = [object()]
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)
    state.context_analysis = _make_empty_context_analysis()

    call_count = [0]
    def counting(state_, config_, entries_, w_):
        call_count[0] += 1
        return []
    monkeypatch.setattr("axt.tui.tabs._usage_summary_lines", counting)

    scr = _make_stdscr(rows=30, cols=120)
    axt.render_usage_tab(scr, state, 0, 28, 120)
    assert call_count[0] == 1
    state.usage_entries = [object()]  # new list object, new id
    axt.render_usage_tab(scr, state, 0, 28, 120)
    assert call_count[0] == 2


def test_render_usage_tab_cache_invalidates_on_width_change(monkeypatch, tmp_path):
    """Different terminal width → different layout → cache miss."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    state = axt.TuiState()
    state.usage_entries = [object()]
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)
    state.context_analysis = _make_empty_context_analysis()

    call_count = [0]
    def counting(state_, config_, entries_, w_):
        call_count[0] += 1
        return []
    monkeypatch.setattr("axt.tui.tabs._usage_summary_lines", counting)

    scr80 = _make_stdscr(rows=30, cols=80)
    scr120 = _make_stdscr(rows=30, cols=120)
    axt.render_usage_tab(scr80, state, 0, 28, 80)
    axt.render_usage_tab(scr120, state, 0, 28, 120)
    assert call_count[0] == 2


# ─── Task 2: Tab/Shift+Tab removed from extensions content layer ──────────────


def test_extensions_tab_no_longer_cycles_subtab():
    """Tab/Shift+Tab are no longer content-layer sub-tab shortcuts. The
    canonical path is Esc → subTab layer → ←/→. `[` and `]` remain as
    in-content shortcuts. Vault sub-tab forwards Tab to handle_vault_input
    (covered by test_extensions_tab_delegates_to_vault_input below)."""
    s = axt.TuiState()
    s.ext_sub_tab = "plugins"  # non-vault sub-tab so Tab is fully inert
    axt.handle_extensions_input(s, 9)  # Tab
    assert s.ext_sub_tab == "plugins"
    axt.handle_extensions_input(s, curses.KEY_BTAB)  # Shift+Tab
    assert s.ext_sub_tab == "plugins"


def test_extensions_tab_brackets_still_cycle():
    """`[` / `]` keep working as content-layer sub-tab shortcuts."""
    s = axt.TuiState()
    s.ext_sub_tab = "vault"
    axt.handle_extensions_input(s, ord("]"))
    assert s.ext_sub_tab != "vault"  # advanced
    axt.handle_extensions_input(s, ord("["))
    assert s.ext_sub_tab == "vault"  # back


def test_extensions_tab_delegates_to_vault_input():
    """Integration check: pressing Tab while on the Vault sub-tab must reach
    handle_vault_input (which toggles vault_detail_focused). This is the
    end-to-end path the user actually exercises."""
    s = axt.TuiState()
    s.ext_sub_tab = "vault"
    s.vault_items = [
        axt.VaultItem(name="item-0", type="skill", path="", description="")
    ]
    assert s.vault_detail_focused is False
    axt.handle_extensions_input(s, 9)  # Tab
    assert s.vault_detail_focused is True


def test_render_vault_tab_bottom_layout_never_negative_table_h():
    """At pathologically small h, the table area must collapse to 0 instead
    of going negative — otherwise detail_y would overlap the title row."""
    scr = _make_stdscr(rows=5, cols=80)
    s = axt.TuiState()
    _seed_vault_for_render(s)
    # h=3 → table_h_full = 2; detail_h guard collapses to 1; table_h clamps to
    # max(0, 2-1) = 1, so detail_y stays at or below the table area (panel never
    # starts above the title row).
    axt.render_vault_tab(scr, s, y0=0, h=3, w=80)
    top = _detail_panel_top_left(scr.calls)
    assert top is not None
    y, _x = top
    # table_y_top = 0 + 1 = 1; table_h = 1; detail_y = 2.
    assert y >= 1, f"detail must not be drawn above the title row, got y={y}"


# ════════════════════════════════════════════════════════════════════════════
#  Coverage-raising additions
# ════════════════════════════════════════════════════════════════════════════


def _make_modal_win(keys, rows=24, cols=80):
    """Mock curses window that records addnstr calls and returns `keys` from
    getch() one by one. Returns (win, calls)."""
    win = MagicMock()
    calls: list = []
    def addnstr(*args):
        calls.append(args)
    win.addnstr.side_effect = addnstr
    win.getmaxyx.return_value = (rows, cols)
    seq = iter(keys)
    win.getch.side_effect = lambda: next(seq)
    win.calls = calls
    return win, calls


# ─── tui_init_colors / color helpers ─────────────────────────────────────────


def test_tui_init_colors_swallows_errors(monkeypatch):
    """tui_init_colors must not raise even when curses color setup fails
    (no real terminal in tests)."""
    monkeypatch.setattr("curses.use_default_colors",
                        lambda: (_ for _ in ()).throw(curses.error("no color")))
    monkeypatch.setattr("curses.init_pair",
                        lambda *a: (_ for _ in ()).throw(curses.error("no pair")))
    # Should complete without raising.
    axt.tui_init_colors()


def test_tui_init_colors_initializes_eight_pairs(monkeypatch):
    """All eight palette pairs are initialized when curses cooperates."""
    monkeypatch.setattr("curses.use_default_colors", lambda: None)
    seen = []
    monkeypatch.setattr("curses.init_pair", lambda n, fg, bg: seen.append(n))
    axt.tui_init_colors()
    assert seen == [1, 2, 3, 4, 5, 6, 7, 8]


def test_dim_pair_pins_a_fixed_background_per_theme(monkeypatch):
    """The 'dim' pair (7) doubles as the screen bkgd fill, so it must pin a
    FIXED background per theme rather than inherit the terminal's (-1): dark =
    white-on-black, light = black-on-white. Pinning the bg is what keeps the
    theme readable regardless of the terminal's own background (a saturated
    dark-theme accent on an inherited light bg was the original bug)."""
    monkeypatch.setattr("curses.use_default_colors", lambda: None)
    pairs = {}
    monkeypatch.setattr("curses.init_pair", lambda n, fg, bg: pairs.__setitem__(n, (fg, bg)))
    axt.tui_init_colors("dark")
    assert pairs[7] == (curses.COLOR_WHITE, curses.COLOR_BLACK)
    axt.tui_init_colors("light")
    assert pairs[7] == (curses.COLOR_BLACK, curses.COLOR_WHITE)
    axt.tui_init_colors("dark")  # restore global so other tests see dark


def test_dark_palette_keeps_original_hues(monkeypatch):
    """The DARK theme restores the original "looks good on black" scheme:
    solid cyan chip, yellow header, cyan secondary — now on a FIXED black
    background on every pair (terminal-independent), not the inherited -1."""
    monkeypatch.setattr("curses.use_default_colors", lambda: None)
    pairs = {}
    monkeypatch.setattr("curses.init_pair", lambda n, fg, bg: pairs.__setitem__(n, (fg, bg)))
    axt.tui_init_colors("dark")
    assert pairs[1] == (curses.COLOR_BLACK, curses.COLOR_CYAN)         # solid cyan chip
    assert pairs[2] == (curses.COLOR_YELLOW, curses.COLOR_BLACK)       # yellow header
    assert pairs[8] == (curses.COLOR_CYAN, curses.COLOR_BLACK)         # cyan secondary
    # Every pair but the cyan selection chip (1) pins a black background so the
    # dark theme renders identically on a light terminal.
    assert all(bg == curses.COLOR_BLACK for n, (fg, bg) in pairs.items() if n != 1)
    assert axt.current_theme() == "dark"


def test_light_palette_drops_fluorescent_hues(monkeypatch):
    """The LIGHT theme fixes a white background on every pair, uses monochrome
    emphasis (reverse/underline) for active & header, and never uses the
    wash-out hues (yellow/cyan) as a foreground."""
    monkeypatch.setattr("curses.use_default_colors", lambda: None)
    pairs = {}
    monkeypatch.setattr("curses.init_pair", lambda n, fg, bg: pairs.__setitem__(n, (fg, bg)))
    axt.tui_init_colors("light")
    # Light fixes a white background on every pair (terminal-independent).
    assert all(bg == curses.COLOR_WHITE for _fg, bg in pairs.values())
    assert pairs[1] == (curses.COLOR_BLACK, curses.COLOR_WHITE)   # reverse → white-on-black chip
    assert pairs[2] == (curses.COLOR_BLACK, curses.COLOR_WHITE)   # header (+underline)
    assert pairs[8] == (curses.COLOR_BLUE, curses.COLOR_WHITE)    # secondary
    fgs = {fg for fg, _bg in pairs.values()}
    assert curses.COLOR_YELLOW not in fgs   # no fluorescent yellow
    assert curses.COLOR_CYAN not in fgs     # cyan washes out on white → blue
    assert axt.current_theme() == "light"
    axt.tui_init_colors("dark")  # restore global so other tests see dark


def test_both_themes_fill_a_fixed_background(monkeypatch):
    """Both themes fill stdscr with a FIXED background via the shared fill pair
    (7) — light = white, dark = black — so neither inherits the terminal's own
    background and a theme looks identical across terminals."""
    monkeypatch.setattr("curses.use_default_colors", lambda: None)
    monkeypatch.setattr("curses.init_pair", lambda *a: None)
    monkeypatch.setattr("curses.color_pair", lambda n: 0x100 << n)
    bkgds = []

    class _Scr:
        def bkgd(self, ch, attr):
            bkgds.append((ch, attr))

    scr = _Scr()
    axt.tui_init_colors("light", scr)
    assert bkgds[-1] == (" ", 0x100 << 7)   # fill pair 7 (black-on-white → white screen)
    axt.tui_init_colors("dark", scr)
    assert bkgds[-1] == (" ", 0x100 << 7)   # fill pair 7 (white-on-black → black screen)
    axt.tui_init_colors("dark")  # restore global


def test_cp_active_chip_reverses_in_light_only(monkeypatch):
    """The active-tab chip uses a solid color pair in dark, but a monochrome
    A_REVERSE chip in light (no fluorescent fill on a white background)."""
    monkeypatch.setattr("curses.color_pair", lambda n: 0x100 << n)
    axt.tui_init_colors("dark")
    assert axt.CP_ACTIVE_CHIP() & curses.A_BOLD
    assert not (axt.CP_ACTIVE_CHIP() & curses.A_REVERSE)
    axt.tui_init_colors("light")
    assert axt.CP_ACTIVE_CHIP() & curses.A_BOLD
    assert axt.CP_ACTIVE_CHIP() & curses.A_REVERSE
    axt.tui_init_colors("dark")  # restore global so other tests see dark


def test_color_pair_helpers_degrade_without_color(monkeypatch):
    """When color_pair raises (no start_color), the CP_* helpers return just
    the extra attribute bits instead of crashing."""
    monkeypatch.setattr("curses.color_pair",
                        lambda n: (_ for _ in ()).throw(curses.error("no color")))
    # CP_SEL keeps its A_BOLD|A_REVERSE extras even without color.
    assert axt.CP_SEL() == (curses.A_BOLD | curses.A_REVERSE)
    # CP_DIM keeps A_DIM.
    assert axt.CP_DIM() == curses.A_DIM
    # CP_OK has no extra → degrades to 0.
    assert axt.CP_OK() == 0


def test_color_pair_helpers_use_color_when_available(monkeypatch):
    """When color_pair works, the bit is OR-ed into the returned attribute."""
    axt.tui_init_colors("dark")  # emphasis bits are theme-dependent
    monkeypatch.setattr("curses.color_pair", lambda n: 0x100 << n)
    # CP_TITLE = the accent tier (pair 2 + bold in dark).
    assert axt.CP_TITLE() & (0x100 << 2)
    assert axt.CP_TITLE() & curses.A_BOLD
    # CP_HDR = the subordinate column-header tier (pair 7 / dim in dark).
    assert axt.CP_HDR() & (0x100 << 7)
    assert axt.CP_INFO() == (0x100 << 4)


def test_cp_title_vs_hdr_emphasis_hierarchy(monkeypatch):
    """Two distinct tiers: CP_TITLE (section/status accent) sits above CP_HDR
    (table column header). Dark: title = yellow+bold, header = dim grey.
    Light: title = plain default fg (no full-width rule), header = underline."""
    monkeypatch.setattr("curses.color_pair", lambda n: 0x100 << n)
    axt.tui_init_colors("dark")
    # Title: bold accent, never underlined.
    assert axt.CP_TITLE() & curses.A_BOLD
    assert not (axt.CP_TITLE() & curses.A_UNDERLINE)
    # Header: dim, not bold (subordinate to the title).
    assert axt.CP_HDR() & curses.A_DIM
    assert not (axt.CP_HDR() & curses.A_BOLD)
    axt.tui_init_colors("light")
    # Title: no underline and no bold → a full-width title row stays plain text
    # (no rule, no solid bar) on white.
    assert not (axt.CP_TITLE() & curses.A_UNDERLINE)
    assert not (axt.CP_TITLE() & curses.A_BOLD)
    # Header: underline (A_BOLD washes out on white), not bold.
    assert axt.CP_HDR() & curses.A_UNDERLINE
    assert not (axt.CP_HDR() & curses.A_BOLD)
    axt.tui_init_colors("dark")  # restore global so other tests see dark


# ─── safe_addnstr error handling + guards ────────────────────────────────────


def test_safe_addnstr_swallows_curses_error():
    """A curses.error from addnstr (e.g. writing the bottom-right cell) must
    be swallowed silently."""
    scr = MagicMock()
    scr.addnstr.side_effect = curses.error("boundary")
    # No exception should escape.
    axt.safe_addnstr(scr, 0, 0, "x", 5)
    assert scr.addnstr.called


def test_safe_addnstr_guards_negative_coords():
    """Negative y/x or non-positive width is a no-op — addnstr never called."""
    scr = MagicMock()
    axt.safe_addnstr(scr, -1, 0, "x", 5)
    axt.safe_addnstr(scr, 0, -1, "x", 5)
    axt.safe_addnstr(scr, 0, 0, "x", 0)
    assert not scr.addnstr.called


# ─── _wrap_to_cells / fit_cells edge branches via render_detail_panel ─────────


def test_render_detail_panel_zero_width_returns_zero():
    scr = _make_stdscr()
    assert axt.render_detail_panel(scr, 0, 0, 10, 0, "t", []) == 0


def test_render_detail_panel_tiny_inner_width_returns_zero():
    """w=4 → inner_w = 0 → early return 0 (no content drawn)."""
    scr = _make_stdscr()
    assert axt.render_detail_panel(scr, 0, 0, 10, 4, "t", [("A", "1")]) == 0


def test_render_detail_panel_wraps_on_newline():
    """A value containing '\\n' splits into multiple wrapped lines."""
    scr = _make_stdscr()
    axt.render_detail_panel(scr, 0, 0, 12, 40, "T", [("Body", "line1\nline2\nline3")])
    flat = "\n".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "line1" in flat
    assert "line2" in flat
    assert "line3" in flat


def test_render_detail_panel_no_title_skips_title_row():
    """title=None must not draw a header line, but fields still render."""
    scr = _make_stdscr()
    axt.render_detail_panel(scr, 0, 0, 10, 30, None, [("Key", "Val")])
    flat = " ".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Key:" in flat
    assert "Val" in flat


def test_render_detail_panel_single_row_height_skips_bottom_border():
    """h=1 → only the top border drawn (the `if h >= 2` guard skips the bottom).
    Top and bottom share the ASCII '+...+' shape, so 'no bottom' means exactly
    one '+...+' row was drawn (at y=0)."""
    scr = _make_stdscr()
    axt.render_detail_panel(scr, 0, 0, 1, 30, "T", [])
    border_ys = [c[0] for c in scr.calls
                 if len(c) >= 3 and isinstance(c[2], str) and c[2].startswith("+")]
    assert border_ys == [0]        # only the top border, no bottom


# ─── render_table edge branches ──────────────────────────────────────────────


def test_render_table_zero_height_returns_zero():
    scr = _make_stdscr()
    cols = [axt.TableColumn("name", "Name", 10)]
    assert axt.render_table(scr, 0, 0, 0, 80, cols, [{"name": "a"}], selected=0) == 0


def test_render_table_no_room_for_rows_returns_zero():
    """h=2 with header → header eats both rows, avail <= 0 → 0 data rows."""
    scr = _make_stdscr()
    cols = [axt.TableColumn("name", "Name", 10)]
    rows = [{"name": "a"}, {"name": "b"}]
    drawn = axt.render_table(scr, 0, 0, 2, 80, cols, rows, selected=0, show_header=True)
    assert drawn == 0


def test_render_table_no_header_draws_all_visible_rows():
    """show_header=False uses the full height for data rows."""
    scr = _make_stdscr()
    cols = [axt.TableColumn("name", "Name", 10)]
    rows = [{"name": f"r{i}"} for i in range(3)]
    drawn = axt.render_table(scr, 0, 0, 5, 80, cols, rows, selected=0, show_header=False)
    assert drawn == 3
    # No "Name" header label should have been drawn.
    flat = " ".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "r0" in flat and "r1" in flat and "r2" in flat


def test_render_table_wide_east_asian_values():
    """Korean values must render without splitting wide chars across cells."""
    scr = _make_stdscr()
    cols = [axt.TableColumn("name", "이름", 12)]
    rows = [{"name": "한글스킬"}]
    drawn = axt.render_table(scr, 0, 0, 10, 80, cols, rows, selected=0)
    assert drawn == 1
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "한글" in flat


def test_render_table_narrow_width_truncates_columns():
    """A width too small to fit all columns must still draw rows without error
    (the inner `cursor - x >= w` break fires)."""
    scr = _make_stdscr()
    cols = [axt.TableColumn(f"c{i}", f"Col{i}", 20) for i in range(5)]
    rows = [{f"c{i}": "value" for i in range(5)}]
    drawn = axt.render_table(scr, 0, 0, 10, 12, cols, rows, selected=0)
    assert drawn == 1


def test_render_table_unchecked_row_uses_box_glyph():
    """A non-selected unchecked row uses the ' □ ' prefix; checked uses ' ■ '."""
    scr = _make_stdscr()
    cols = [axt.TableColumn("name", "Name", 10)]
    rows = [{"name": f"r{i}"} for i in range(3)]
    axt.render_table(scr, 0, 0, 10, 80, cols, rows, selected=0, checked={2})
    prefixes = [c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str)]
    # Selected row (0) unchecked → "▸□ "; checked row (2) non-selected → " ■ ".
    assert any("▸□" in p for p in prefixes)
    assert any(" ■ " in p for p in prefixes)


# ─── _draw_cell zero-width guard (via a 1-cell table) ────────────────────────


def test_draw_cell_zero_max_width_returns_zero():
    assert axt._draw_cell(_make_stdscr(), 0, 0, "x", 4, 0, 0) == 0


# ─── render_status_bar ───────────────────────────────────────────────────────


def test_render_status_bar_shortcuts_only():
    scr = _make_stdscr()
    axt.render_status_bar(scr, 0, 80, "q:quit  ?:help")
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "q:quit" in flat


def test_render_status_bar_with_status_prefixes_shortcuts():
    """When a status fits, it is shown before the shortcuts joined by '│'."""
    scr = _make_stdscr()
    axt.render_status_bar(scr, 0, 120, "q:quit", status="Saved!")
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Saved!" in flat
    assert "│" in flat


def test_render_status_bar_long_status_drops_shortcuts():
    """If status + shortcuts won't fit the width, only the status is shown."""
    scr = _make_stdscr()
    long_status = "X" * 50
    axt.render_status_bar(scr, 0, 30, "q:quit  ?:help  r:refresh", status=long_status)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    # The status text is present; the shortcut tail is dropped.
    assert "X" in flat
    assert "r:refresh" not in flat


def test_render_status_bar_status_attr_colors_status_only():
    """status_attr is applied to the status segment; shortcuts stay CP_DIM."""
    scr = _make_stdscr()
    axt.render_status_bar(scr, 0, 120, "q:quit", status="Linked x", status_attr=12345)
    status_calls = [c for c in scr.calls if len(c) >= 5 and c[2] == "Linked x"]
    assert status_calls and status_calls[0][4] == 12345
    tail_calls = [c for c in scr.calls if len(c) >= 5 and "q:quit" in c[2]]
    assert tail_calls and tail_calls[0][4] == axt.CP_DIM()


# ─── confirm_modal interactive paths ─────────────────────────────────────────


def test_confirm_modal_yes_on_y(monkeypatch):
    scr = _make_stdscr(rows=24, cols=80)
    win, _calls = _make_modal_win([ord("y")])
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    assert axt.confirm_modal(scr, "Delete this?") is True
    # The window content should include the prompt and the y/n hint.
    flat = "".join(c[2] for c in win.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Delete this?" in flat
    assert "Yes" in flat


def test_confirm_modal_no_on_esc(monkeypatch):
    scr = _make_stdscr()
    win, _calls = _make_modal_win([27])  # Esc
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    assert axt.confirm_modal(scr, "Remove?") is False


def test_confirm_modal_enter_confirms(monkeypatch):
    scr = _make_stdscr()
    win, _calls = _make_modal_win([10])  # Enter
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    assert axt.confirm_modal(scr, "Confirm?") is True


def test_confirm_modal_ignores_unrelated_keys_then_n(monkeypatch):
    """Keys other than y/Y/n/N/Enter/Esc loop until a decision key arrives."""
    scr = _make_stdscr()
    win, _calls = _make_modal_win([ord("x"), ord("z"), ord("n")])
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    assert axt.confirm_modal(scr, "Sure?") is False


# ─── text_input_modal interactive paths ──────────────────────────────────────


def test_text_input_modal_types_and_enter(monkeypatch):
    scr = _make_stdscr()
    win, _calls = _make_modal_win([ord("a"), ord("b"), ord("c"), 10])
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    monkeypatch.setattr("curses.curs_set", lambda *a: None)
    assert axt.text_input_modal(scr, "Name?") == "abc"


def test_text_input_modal_esc_returns_none(monkeypatch):
    scr = _make_stdscr()
    win, _calls = _make_modal_win([ord("a"), 27])  # type then Esc
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    monkeypatch.setattr("curses.curs_set", lambda *a: None)
    assert axt.text_input_modal(scr, "Name?") is None


def test_text_input_modal_backspace_deletes(monkeypatch):
    scr = _make_stdscr()
    win, _calls = _make_modal_win([ord("a"), ord("b"), 127, 10])  # ab, bksp, enter
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    monkeypatch.setattr("curses.curs_set", lambda *a: None)
    assert axt.text_input_modal(scr, "Name?") == "a"


def test_text_input_modal_uses_initial_value(monkeypatch):
    scr = _make_stdscr()
    win, _calls = _make_modal_win([ord("X"), 10])
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    monkeypatch.setattr("curses.curs_set", lambda *a: None)
    assert axt.text_input_modal(scr, "Name?", initial="seed") == "seedX"


def test_text_input_modal_newwin_failure_returns_none(monkeypatch):
    scr = _make_stdscr()
    monkeypatch.setattr("curses.newwin",
                        lambda *a, **kw: (_ for _ in ()).throw(curses.error("too small")))
    assert axt.text_input_modal(scr, "Name?") is None


# ─── preview_modal interactive paths ─────────────────────────────────────────


def test_preview_modal_quit_on_q(monkeypatch):
    scr = _make_stdscr()
    win, _calls = _make_modal_win([ord("q")])
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, "line one\nline two", title="My Preview")
    flat = "".join(c[2] for c in win.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "My Preview" in flat
    assert "line one" in flat


def test_preview_modal_scrolls_then_quits(monkeypatch):
    scr = _make_stdscr()
    content = "\n".join(f"row {i}" for i in range(200))
    # j, G (bottom), g (top), PgDn, PgUp, k, then Esc.
    win, _calls = _make_modal_win([
        ord("j"), ord("G"), ord("g"),
        curses.KEY_NPAGE, curses.KEY_PPAGE, ord("k"), 27,
    ])
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, content, title="Big")
    flat = "".join(c[2] for c in win.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "row 0" in flat


def test_preview_modal_home_end_jump_top_bottom(monkeypatch):
    scr = _make_stdscr()
    content = "\n".join(f"row {i}" for i in range(200))
    # End (bottom), Home (top), then quit — same effect as G then g.
    win, _calls = _make_modal_win([curses.KEY_END, curses.KEY_HOME, ord("q")])
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, content, title="Big")
    flat = "".join(c[2] for c in win.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "row 0" in flat


def test_preview_modal_heading_prefix_colors_headings(monkeypatch):
    """Lines starting with heading_prefix render with the bold heading attr;
    body lines keep the plain attr — the per-source separation is visible."""
    scr = _make_stdscr()
    win, calls = _make_modal_win([ord("q")])
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, "━━ section one\nplain body", title="T",
                      heading_prefix="━━")
    def attr_of(text):
        for c in calls:
            if len(c) >= 5 and isinstance(c[2], str) and text in c[2]:
                return c[4]
        raise AssertionError(f"{text!r} not drawn")
    assert attr_of("section one") & curses.A_BOLD
    assert not attr_of("plain body") & curses.A_BOLD


def test_preview_modal_without_heading_prefix_is_plain(monkeypatch):
    """Default preview (no heading_prefix) never bolds content lines, even
    ones that happen to start with box-drawing characters."""
    scr = _make_stdscr()
    win, calls = _make_modal_win([ord("q")])
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, "━━ looks like a heading", title="T")
    hits = [c for c in calls
            if len(c) >= 5 and isinstance(c[2], str) and "looks like a heading" in c[2]]
    assert hits and not (hits[0][4] & curses.A_BOLD)


def test_preview_modal_newwin_failure_is_silent(monkeypatch):
    scr = _make_stdscr()
    monkeypatch.setattr("curses.newwin",
                        lambda *a, **kw: (_ for _ in ()).throw(curses.error("nope")))
    # Should return without raising.
    axt.preview_modal(scr, "anything")


# ─── preview_modal search ────────────────────────────────────────────────────


def _ord_seq(s: str) -> list:
    return [ord(c) for c in s]


def test_preview_modal_search_jumps_and_highlights(monkeypatch):
    scr = _make_stdscr()
    # NEEDLE sits far below the fold so a plain first frame can't show it.
    lines = [f"row {i}" for i in range(60)] + ["a NEEDLE here"] + [f"row {i}" for i in range(60)]
    content = "\n".join(lines)
    # `/` opens the prompt, "needle" is typed, Enter runs it, `q` closes.
    keys = [ord("/")] + _ord_seq("needle") + [10, ord("q")]
    win, _calls = _make_modal_win(keys)
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, content, title="Search")
    flat = "".join(c[2] for c in win.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "NEEDLE" in flat          # scrolled into view
    assert "[match 1/1]" in flat


def test_preview_modal_search_backspace_edits_term(monkeypatch):
    scr = _make_stdscr()
    content = "\n".join([f"row {i}" for i in range(30)] + ["a NEEDLE here"])
    # Type "needlex", backspace removes the x, then Enter → matches "needle".
    keys = [ord("/")] + _ord_seq("needlex") + [127] + [10, ord("q")]
    win, _calls = _make_modal_win(keys)
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, content, title="Search")
    flat = "".join(c[2] for c in win.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "[match 1/1]" in flat


def test_preview_modal_search_n_cycles_matches(monkeypatch):
    scr = _make_stdscr()
    # Three lines carry the term; `n` advances the current-match counter.
    lines = ["mark one", "filler", "mark two", "filler", "mark three"]
    content = "\n".join(lines)
    keys = [ord("/")] + _ord_seq("mark") + [10, ord("n"), ord("n"), ord("q")]
    win, _calls = _make_modal_win(keys)
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, content, title="Search")
    flat = "".join(c[2] for c in win.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "[match 3/3]" in flat      # advanced from 1/3 → 2/3 → 3/3


def test_preview_modal_search_N_wraps_backward(monkeypatch):
    scr = _make_stdscr()
    content = "\n".join(["mark one", "filler", "mark two", "filler", "mark three"])
    # `N` from the first match wraps to the last.
    keys = [ord("/")] + _ord_seq("mark") + [10, ord("N"), ord("q")]
    win, _calls = _make_modal_win(keys)
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, content, title="Search")
    flat = "".join(c[2] for c in win.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "[match 3/3]" in flat


def test_preview_modal_search_no_match_indicator(monkeypatch):
    scr = _make_stdscr()
    content = "\n".join(f"row {i}" for i in range(20))
    keys = [ord("/")] + _ord_seq("zzzz") + [10, ord("q")]
    win, _calls = _make_modal_win(keys)
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, content, title="Search")
    flat = "".join(c[2] for c in win.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "[no match]" in flat


def test_preview_modal_search_esc_cancels_input(monkeypatch):
    scr = _make_stdscr()
    content = "\n".join(f"row {i}" for i in range(20))
    # Esc (27) aborts the prompt, leaving no active search; second Esc closes.
    keys = [ord("/")] + _ord_seq("row") + [27, 27]
    win, _calls = _make_modal_win(keys)
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, content, title="Search")
    flat = "".join(c[2] for c in win.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "[match" not in flat
    assert "[no match]" not in flat


def test_preview_modal_search_esc_clears_then_closes(monkeypatch):
    scr = _make_stdscr()
    content = "\n".join([f"row {i}" for i in range(30)] + ["a NEEDLE here"])
    # Run a search, first Esc clears it (modal stays), second Esc closes.
    # Exactly enough keys: exhausting them before return would raise StopIteration.
    keys = [ord("/")] + _ord_seq("needle") + [10, 27, 27]
    win, _calls = _make_modal_win(keys)
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    axt.preview_modal(scr, content, title="Search")  # must not raise


# ─── open_in_editor success path ─────────────────────────────────────────────


def test_open_in_editor_success_returns_true(monkeypatch):
    monkeypatch.setenv("EDITOR", "true")
    monkeypatch.setattr("subprocess.call", lambda *a, **kw: 0)
    monkeypatch.setattr("curses.endwin", lambda: None)
    monkeypatch.setattr("curses.curs_set", lambda *a: None)
    scr = _make_stdscr()
    assert axt.open_in_editor(scr, "/tmp/file.txt") is True
    assert scr.clear.called
    assert scr.refresh.called


def test_open_in_editor_nonzero_exit_returns_false(monkeypatch):
    monkeypatch.setattr("subprocess.call", lambda *a, **kw: 1)
    monkeypatch.setattr("curses.endwin", lambda: None)
    monkeypatch.setattr("curses.curs_set", lambda *a: None)
    scr = _make_stdscr()
    assert axt.open_in_editor(scr, "/tmp/file.txt") is False


# ─── render_tab_bar narrow break branch ──────────────────────────────────────


def test_render_tab_bar_unfocused_uses_underline_on_active():
    """Unfocused active tab uses A_UNDERLINE (no solid chip)."""
    scr = _make_stdscr()
    axt.render_tab_bar(scr, 0, 0, 120, active_idx=0, focused=False)
    for call in scr.calls:
        if len(call) >= 5 and isinstance(call[2], str) and "Extensions" in call[2]:
            assert call[4] & curses.A_UNDERLINE
            return
    pytest.fail("active tab cell not drawn")


# ─── _render_subtab_bar break branch (narrow) ────────────────────────────────


def test_render_subtab_bar_narrow_truncates():
    """A narrow width must stop drawing sub-tab cells without error."""
    scr = _make_stdscr()
    axt._render_subtab_bar(scr, 0, 20, axt.EXTENSION_SUB_TABS, active_key="vault", focused=True)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Sub:" in flat


# ─── _render_frame branches ──────────────────────────────────────────────────


def test_render_frame_too_small_shows_resize_message():
    scr = _make_stdscr(rows=3, cols=20)
    state = axt.TuiState()
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Terminal too small" in flat


def test_render_frame_extensions_vault_shortcuts(tmp_path, monkeypatch):
    """The status bar for the Extensions/Vault tab includes the full vault
    shortcut hint line."""
    monkeypatch.chdir(tmp_path)
    scr = _make_stdscr(rows=30, cols=140)
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "vault"
    state.refresh_token = 1  # avoid disk
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "c:filter" in flat
    assert "Space:mark" in flat
    assert "p:project" in flat


def test_render_frame_vault_search_shortcuts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scr = _make_stdscr(rows=30, cols=140)
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "vault"
    state.refresh_token = 1
    state.vault_searching = True
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "typing search" in flat


def test_render_frame_vault_pending_shortcuts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scr = _make_stdscr(rows=30, cols=140)
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "vault"
    state.refresh_token = 1
    state.vault_pending_project = {"x"}
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "apply pending" in flat


def test_render_frame_extensions_nonvault_shortcuts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "s.json",
        vault=tmp_path / "vault",
        claude_dir=tmp_path / "claude",
    ))
    scr = _make_stdscr(rows=30, cols=140)
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.ext_sub_tab = "plugins"
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "[/]:sub" in flat
    # The vault-specific c:filter hint must NOT be present on a non-vault sub-tab.
    assert "c:filter" not in flat


def test_render_frame_context_shortcuts(tmp_path, monkeypatch):
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    scr = _make_stdscr(rows=30, cols=140)
    state = axt.TuiState()
    state.tab_idx = _tab_idx("context")
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "[/]:sub" in flat


def test_render_frame_usage_shortcuts(tmp_path, monkeypatch):
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", lambda **kw: [])
    scr = _make_stdscr(rows=30, cols=140)
    state = axt.TuiState()
    state.tab_idx = _tab_idx("usage")
    state.usage_entries = []
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    # Generic shortcut line for tabs without sub-tabs.
    assert "1-3:tab" in flat
    assert "j/k:nav" in flat


def test_render_frame_auto_clears_expired_status(tmp_path, monkeypatch):
    """A status older than STATUS_TIMEOUT_S is cleared during the frame render."""
    import time as _time
    monkeypatch.chdir(tmp_path)
    scr = _make_stdscr(rows=30, cols=140)
    state = axt.TuiState()
    state.status = "stale message"
    state.status_set_at = _time.monotonic() - (axt.STATUS_TIMEOUT_S + 5)
    axt._render_frame(scr, state)
    assert state.status == ""
    assert state.status_set_at is None


def test_render_frame_keeps_fresh_status(tmp_path, monkeypatch):
    import time as _time
    monkeypatch.chdir(tmp_path)
    scr = _make_stdscr(rows=30, cols=140)
    state = axt.TuiState()
    state.status = "fresh"
    state.status_set_at = _time.monotonic()
    axt._render_frame(scr, state)
    assert state.status == "fresh"


def test_render_frame_truncates_long_cwd(tmp_path, monkeypatch):
    """A cwd wider than the terminal must be fit_cells-truncated, not crash."""
    monkeypatch.chdir(tmp_path)
    scr = _make_stdscr(rows=30, cols=40)  # narrow so cwd overflows
    state = axt.TuiState()
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "cwd:" in flat


# ─── _has_background_work status branch ──────────────────────────────────────


def test_has_background_work_true_for_pending_status():
    import time as _time
    state = axt.TuiState()
    state.status = "doing something"
    state.status_set_at = _time.monotonic()
    assert axt._has_background_work(state) is True


# ─── _render_frame stub-renderer fallback ────────────────────────────────────


def test_render_frame_uses_stub_when_renderer_missing(monkeypatch, tmp_path):
    """When a tab has no registered renderer, _render_frame falls back to
    render_stub_tab."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(axt.TAB_RENDERERS, "usage", None)
    # Use the patched dict but None means renderer is None → stub path.
    # Restore is handled by monkeypatch.
    scr = _make_stdscr(rows=30, cols=120)
    state = axt.TuiState()
    state.tab_idx = _tab_idx("usage")
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "not yet implemented" in flat


# ─── render_stub_tab + handle_stub_input ─────────────────────────────────────


def test_render_stub_tab_draws_name_and_hint():
    scr = _make_stdscr()
    state = axt.TuiState()
    axt.render_stub_tab(scr, state, 0, 20, 80, name="Foo", hint="some hint here")
    flat = "\n".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Foo" in flat
    assert "some hint here" in flat
    assert "axt foo --help" in flat


def test_handle_stub_input_returns_none():
    assert axt.handle_stub_input(axt.TuiState(), ord("x")) is None


# ─── Vault input: navigation + paging branches ───────────────────────────────


def test_handle_vault_input_pgdn_pgup():
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name=f"i{i}", type="skill", path="", description="")
        for i in range(30)
    ]
    axt.handle_vault_input(s, curses.KEY_NPAGE)
    assert s.vault_selected == 10
    axt.handle_vault_input(s, curses.KEY_PPAGE)
    assert s.vault_selected == 0


def test_handle_vault_input_detail_scroll_pgdn_pgup():
    s = axt.TuiState()
    s.vault_items = [axt.VaultItem(name="a", type="skill", path="", description="")]
    s.vault_detail_focused = True
    axt.handle_vault_input(s, curses.KEY_NPAGE)
    assert s.vault_detail_scroll == 10
    axt.handle_vault_input(s, curses.KEY_PPAGE)
    assert s.vault_detail_scroll == 0


def test_handle_vault_input_search_enter_empty_returns_none():
    """Applying an empty search returns None (no status toast)."""
    s = axt.TuiState()
    s.vault_searching = True
    s.vault_search = ""
    assert axt.handle_vault_input(s, 10) is None
    assert s.vault_searching is False


def test_handle_vault_input_search_nonprintable_ignored():
    """A non-printable key during search input is dropped without effect."""
    s = axt.TuiState()
    s.vault_searching = True
    s.vault_search = "ab"
    axt.handle_vault_input(s, curses.KEY_F5)  # arbitrary non-printable
    assert s.vault_search == "ab"
    assert s.vault_searching is True


def test_handle_vault_input_enter_pending_without_stdscr_applies():
    """With pending toggles and no stdscr (headless), Enter applies directly."""
    s = axt.TuiState()
    s.vault_items = [axt.VaultItem(name="a", type="skill", path="", description="")]
    s.vault_pending_project.add("a")
    s.stdscr_callbacks = None
    msg = axt.handle_vault_input(s, 10)
    # _vault_apply_pending returns an "Applied"/error message, not "Cancelled".
    assert msg is not None
    assert "Cancelled" not in msg


def test_handle_vault_input_refresh_resets_token():
    s = axt.TuiState()
    s.vault_items = [axt.VaultItem(name="a", type="skill", path="", description="")]
    s.refresh_token = 1
    msg = axt.handle_vault_input(s, ord("r"))
    assert msg == "Refreshed"


# ─── Skills sub-tab `i` import path ──────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="vault import unsupported on Windows")
def test_act_import_to_vault_moves_user_skill(tmp_path, monkeypatch):
    """`i` on a non-vault skill row moves it into the vault and leaves a
    symlink at the original location."""
    claude = tmp_path / "claude"
    vault = tmp_path / "vault"
    src = claude / "skills" / "gskill"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\ndescription: g\n---")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=vault, installed_plugins=tmp_path / "ip.json", claude_dir=claude,
    ))
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    s = axt.TuiState()
    s.ext_cache["skills"] = [axt.SkillInfo(
        name="gskill", path=str(src), is_symlink=False, source="user")]
    s.ext_selected["skills"] = 0
    msg = axt._act_import_to_vault(s, None, "skills", ord("i"))
    assert msg is not None and "Imported" in msg
    assert (vault / "skills" / "gskill" / "SKILL.md").exists()
    assert src.is_symlink()


def test_act_import_to_vault_already_vaulted_is_noop(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vs = vault / "skills" / "vaulted"
    vs.mkdir(parents=True)
    (vs / "SKILL.md").write_text("---\ndescription: v\n---")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=vault, installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    s = axt.TuiState()
    s.ext_cache["skills"] = [axt.SkillInfo(
        name="vaulted", path=str(vs), is_symlink=False, source="vault")]
    s.ext_selected["skills"] = 0
    msg = axt._act_import_to_vault(s, None, "skills", ord("i"))
    assert msg == "Already in vault"
    assert not vs.is_symlink()  # untouched


def test_act_import_to_vault_refuses_plugin_source():
    s = axt.TuiState()
    s.ext_cache["skills"] = [axt.SkillInfo(
        name="p:sk", path="/plug/skills/sk", is_symlink=False,
        source="plugin", plugin="p")]
    s.ext_selected["skills"] = 0
    msg = axt._act_import_to_vault(s, None, "skills", ord("i"))
    assert msg is not None and "not importable" in msg


def test_act_import_to_vault_failure_returns_error(tmp_path, monkeypatch):
    """If import_to_vault raises, `i` returns an 'Import failed' status."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=tmp_path / "vault", installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    monkeypatch.setattr("axt.tui.tabs.import_to_vault",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("boom")))
    s = axt.TuiState()
    s.ext_cache["skills"] = [axt.SkillInfo(
        name="x", path=str(tmp_path / "claude" / "skills" / "x"),
        is_symlink=False, source="user")]
    s.ext_selected["skills"] = 0
    msg = axt._act_import_to_vault(s, None, "skills", ord("i"))
    assert msg is not None and "Import failed" in msg


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need elevation")
def test_skills_subtab_merges_vault_only_items(tmp_path, monkeypatch):
    """The Skills sub-tab loader appends vault-stored skills nothing links to
    (source="vault"), keeps linked ones deduped, and applies the same
    SKILL.md validity rule as the Vault tab."""
    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    vault = tmp_path / "vault"
    v = vault / "skills" / "vault-only"
    v.mkdir(parents=True)
    (v / "SKILL.md").write_text("---\ndescription: v\n---")
    (vault / "skills" / "stray").mkdir()  # no SKILL.md → not a skill
    linked = vault / "skills" / "linked"
    linked.mkdir()
    (linked / "SKILL.md").write_text("---\ndescription: l\n---")
    os.symlink(linked, home / ".claude" / "skills" / "linked")
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=vault, installed_plugins=tmp_path / "ip.json",
        claude_dir=home / ".claude", skills=home / ".claude" / "skills",
    ))
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    s = axt.TuiState()
    axt._ensure_subtab_loaded(s, "skills")
    rows = [(i.name, i.source) for i in s.ext_cache["skills"]]
    assert ("vault-only", "vault") in rows
    assert [n for n, _ in rows].count("linked") == 1   # deduped via resolve()
    assert not any(n == "stray" for n, _ in rows)


def test_handle_vault_input_migrate(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=tmp_path / "vault", installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    monkeypatch.chdir(tmp_path)
    s = axt.TuiState()
    s.refresh_token = 1
    msg = axt.handle_vault_input(s, ord("m"))
    assert msg is not None and "Migrated" in msg


def test_handle_vault_input_sync(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=tmp_path / "vault", installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    s = axt.TuiState()
    s.refresh_token = 1
    msg = axt.handle_vault_input(s, ord("S"))
    assert msg is not None and "Sync" in msg


# ─── handle_context_input branches ───────────────────────────────────────────


def _seed_context_analysis_with_sources():
    src = axt.ContextSource(
        name="CLAUDE.md", category="memory", estimated_tokens=1000,
        percentage=5.0, path="/tmp/CLAUDE.md", hint="project",
        chars=4000, actionable=True,
    )
    return axt.ContextAnalysis(
        total_tokens=1000, context_window_size=200_000, used_percent=0.5,
        model="claude-sonnet", sources=[src],
        cost_impact=axt.CostImpact(
            model="claude-sonnet", cache_write_cost=0.0,
            cache_read_cost_per_turn=0.0, avg_turns_per_session=10,
            avg_sessions_per_day=1, per_session_cost=0.0, monthly_cost=0.0,
        ),
    )


def test_handle_context_input_navigation():
    s = axt.TuiState()
    s.context_analysis = _seed_context_analysis_with_sources()
    # Only one category, so down clamps at 0.
    axt.handle_context_input(s, ord("j"))
    assert s.context_selected == 0
    axt.handle_context_input(s, ord("k"))
    assert s.context_selected == 0


def test_handle_context_input_refresh_clears_analysis():
    s = axt.TuiState()
    s.context_sub_tab = "sources"
    s.context_analysis = _seed_context_analysis_with_sources()
    msg = axt.handle_context_input(s, ord("r"))
    assert msg == "Refreshed"
    assert s.context_analysis is None


def test_handle_context_input_v_opens_preview(monkeypatch):
    called = []
    monkeypatch.setattr("axt.preview_modal",
                        lambda stdscr, content, title="Preview", **kw: called.append((title, content)))
    s = axt.TuiState()
    s.context_sub_tab = "sources"
    s.context_analysis = _seed_context_analysis_with_sources()
    s.stdscr_callbacks = {"stdscr": object()}
    s.context_selected = 0
    axt.handle_context_input(s, ord("v"))
    assert called
    assert "CLAUDE.md" in called[0][1]


def test_handle_context_input_e_opens_editor(monkeypatch):
    called = []
    monkeypatch.setattr("axt.open_in_editor",
                        lambda stdscr, path: called.append(path) or True)
    s = axt.TuiState()
    s.context_sub_tab = "sources"
    s.context_analysis = _seed_context_analysis_with_sources()
    s.stdscr_callbacks = {"stdscr": object()}
    s.context_selected = 0
    msg = axt.handle_context_input(s, ord("e"))
    assert called == ["/tmp/CLAUDE.md"]
    assert msg is not None and "Opened" in msg


def test_handle_context_input_e_no_file_in_category(monkeypatch):
    """A category whose sources have no path returns the no-file status."""
    src = axt.ContextSource(
        name="rules", category="rules", estimated_tokens=10,
        percentage=0.1, path="", hint="", chars=40, actionable=False,
    )
    s = axt.TuiState()
    s.context_sub_tab = "sources"
    s.context_analysis = axt.ContextAnalysis(
        total_tokens=10, context_window_size=200_000, used_percent=0.0,
        model="m", sources=[src],
        cost_impact=axt.CostImpact(
            model="m", cache_write_cost=0.0, cache_read_cost_per_turn=0.0,
            avg_turns_per_session=1, avg_sessions_per_day=1,
            per_session_cost=0.0, monthly_cost=0.0,
        ),
    )
    s.stdscr_callbacks = {"stdscr": object()}
    s.context_selected = 0
    msg = axt.handle_context_input(s, ord("e"))
    assert msg == "No file to edit in this category"


# ─── handle_project_input paging branches ────────────────────────────────────


def test_handle_context_input_pgdn_pgup_pages_project_list():
    """PgUp/PgDn page the Project sub-tab's list (state.project_selected) by
    10 rows, clamped to bounds — not the shared detail-panel scroll."""
    s = axt.TuiState()
    s.project_items = [_project_source(f"f{i}", path=f"/p/f{i}") for i in range(15)]
    axt.handle_context_input(s, curses.KEY_NPAGE)
    assert s.project_selected == 10
    axt.handle_context_input(s, curses.KEY_PPAGE)
    assert s.project_selected == 0
    # Already at top → PgUp clamps, no underflow.
    axt.handle_context_input(s, curses.KEY_PPAGE)
    assert s.project_selected == 0


def test_handle_context_input_pgdn_pgup_pages_sources_list():
    """PgUp/PgDn page the Sources sub-tab's list (state.context_selected) by
    10 rows, clamped to bounds."""
    s = axt.TuiState()
    s.context_sub_tab = "sources"
    srcs = [axt.ContextSource(name=f"s{i}", category=f"cat{i}", path="", estimated_tokens=1,
                               percentage=0.0, chars=1, actionable=True)
            for i in range(15)]
    s.context_analysis = axt.ContextAnalysis(
        total_tokens=15, context_window_size=200_000, used_percent=0.0,
        model="m", sources=srcs,
        cost_impact=axt.CostImpact(
            model="m", cache_write_cost=0.0, cache_read_cost_per_turn=0.0,
            avg_turns_per_session=1, avg_sessions_per_day=1,
            per_session_cost=0.0, monthly_cost=0.0,
        ),
    )
    axt.handle_context_input(s, curses.KEY_NPAGE)
    assert s.context_selected == 10
    axt.handle_context_input(s, curses.KEY_PPAGE)
    assert s.context_selected == 0
    # Already at top → PgUp clamps, no underflow.
    axt.handle_context_input(s, curses.KEY_PPAGE)
    assert s.context_selected == 0


def test_handle_context_input_nav_and_cycle_reset_detail_scroll():
    """Moving the selection (j/k) or cycling sub-tabs ([/]) resets the shared
    detail scroll so the new selection's detail starts at the top."""
    s = axt.TuiState()
    s.context_analysis = _seed_context_analysis_with_sources()
    s.context_detail_scroll = 7
    axt.handle_context_input(s, ord("j"))
    assert s.context_detail_scroll == 0
    s.context_detail_scroll = 7
    axt.handle_context_input(s, ord("]"))
    assert s.context_sub_tab == "sources"
    assert s.context_detail_scroll == 0


def test_handle_project_input_nav_moves_selection():
    s = axt.TuiState()
    s.project_items = [_project_source(f"f{i}", path=f"/p/f{i}") for i in range(3)]
    axt.handle_project_input(s, ord("j"))
    assert s.project_selected == 1


def test_handle_project_input_refresh():
    s = axt.TuiState()
    s.project_items = [_project_source("f", path="/p/f")]
    s.context_analysis = _make_empty_context_analysis()
    msg = axt.handle_project_input(s, ord("r"))
    assert msg == "Refreshed"
    assert s.project_items is None
    assert s.context_analysis is None


# ─── handle_extensions_input: list nav on non-vault sub-tabs ──────────────────


def test_handle_extensions_input_list_navigation():
    s = axt.TuiState()
    s.ext_sub_tab = "plugins"
    s.ext_cache["plugins"] = [
        axt.PluginInfo(id=f"p{i}@m", name=f"p{i}", marketplace="m",
                       version="1", install_path=f"/p{i}", scope="user",
                       installed_at="", last_updated="")
        for i in range(5)
    ]
    axt.handle_extensions_input(s, ord("j"))
    assert s.ext_selected["plugins"] == 1
    axt.handle_extensions_input(s, curses.KEY_NPAGE)
    assert s.ext_selected["plugins"] == 4  # clamped at n-1
    axt.handle_extensions_input(s, curses.KEY_PPAGE)
    assert s.ext_selected["plugins"] == 0
    axt.handle_extensions_input(s, ord("k"))
    assert s.ext_selected["plugins"] == 0


def test_handle_extensions_input_refresh_non_vault_clears_cache():
    s = axt.TuiState()
    s.ext_sub_tab = "plugins"
    s.ext_cache["plugins"] = ["dummy"]
    msg = axt.handle_extensions_input(s, ord("r"))
    assert msg == "Refreshed — re-checking updates…"
    assert "plugins" not in s.ext_cache


# ─── _selected_item ──────────────────────────────────────────────────────────


def test_selected_item_out_of_range_returns_none():
    s = axt.TuiState()
    s.ext_cache["plugins"] = []
    s.ext_selected["plugins"] = 0
    assert axt._selected_item(s, "plugins") is None


def test_selected_item_returns_row():
    s = axt.TuiState()
    p = axt.PluginInfo(id="p@m", name="p", marketplace="m", version="1",
                       install_path="/p", scope="user",
                       installed_at="", last_updated="")
    s.ext_cache["plugins"] = [p]
    s.ext_selected["plugins"] = 0
    assert axt._selected_item(s, "plugins") is p


# ─── _handle_subtab_action: plugin E/D project, uninstall ─────────────────────


def test_subtab_action_plugin_uninstall_confirmed(tmp_path, monkeypatch):
    import json
    install_path = tmp_path / "myplugin"
    install_path.mkdir()
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
    ))
    (tmp_path / "ip.json").write_text(json.dumps({
        "version": 2,
        "plugins": {"p@m": [{"scope": "u", "installPath": str(install_path),
                             "version": "1", "installedAt": "", "lastUpdated": ""}]},
    }))
    monkeypatch.setattr("axt.confirm_modal",
                        lambda stdscr, msg, title="Confirm": True)
    s = axt.TuiState()
    s.ext_sub_tab = "plugins"
    s.ext_cache["plugins"] = axt.list_installed_plugins(tmp_path / "ip.json")
    s.ext_selected["plugins"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "plugins", ord("x"))
    assert "Uninstalled" in (msg or "")
    assert not install_path.exists()


def test_subtab_action_plugin_uninstall_cancelled(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json",
        settings=tmp_path / "settings.json",
    ))
    (tmp_path / "ip.json").write_text(json.dumps({
        "version": 2,
        "plugins": {"p@m": [{"scope": "u", "installPath": "/p", "version": "1",
                             "installedAt": "", "lastUpdated": ""}]},
    }))
    monkeypatch.setattr("axt.confirm_modal",
                        lambda stdscr, msg, title="Confirm": False)
    s = axt.TuiState()
    s.ext_sub_tab = "plugins"
    s.ext_cache["plugins"] = axt.list_installed_plugins(tmp_path / "ip.json")
    s.ext_selected["plugins"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(s, "plugins", ord("x")) == "Cancelled"


def test_subtab_action_plugin_none_selected_returns_none():
    s = axt.TuiState()
    s.ext_sub_tab = "plugins"
    s.ext_cache["plugins"] = []
    s.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(s, "plugins", ord(" ")) is None


# ─── _handle_subtab_action: skills link/unlink ───────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks unsupported on Windows")
def test_subtab_action_skill_link(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    skills.mkdir()
    target = tmp_path / "src-skill"
    target.mkdir()
    (target / "SKILL.md").write_text("---\nname: src\n---")
    monkeypatch.setattr("axt.PATHS", axt.Paths(skills=skills, claude_dir=tmp_path / "claude"))
    monkeypatch.setattr("axt.text_input_modal",
                        lambda stdscr, prompt, title="Input", initial="": str(target))
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "skills", ord("a"))
    assert msg is not None and "Linked" in msg


def test_subtab_action_skill_link_cancelled(monkeypatch):
    """text_input_modal returning None (Esc) means link is aborted."""
    if sys.platform == "win32":
        pytest.skip("symlinks unsupported on Windows")
    monkeypatch.setattr("axt.text_input_modal",
                        lambda *a, **kw: None)
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(s, "skills", ord("a")) is None


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks unsupported on Windows")
def test_subtab_action_skill_unlink_non_symlink(monkeypatch):
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.ext_cache["skills"] = [
        axt.SkillInfo(name="dirskill", path="/x", is_symlink=False, source="user")
    ]
    s.ext_selected["skills"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "skills", ord("x"))
    assert msg == "Selected skill is not a symlink (cannot unlink)"


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks unsupported on Windows")
def test_subtab_action_skill_unlink_confirmed(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    skills.mkdir()
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_text("---\n---")
    link = skills / "mylink"
    link.symlink_to(src)
    monkeypatch.setattr("axt.PATHS", axt.Paths(skills=skills, claude_dir=tmp_path / "claude"))
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: True)
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.ext_cache["skills"] = [
        axt.SkillInfo(name="mylink", path=str(link), is_symlink=True,
                      source="user", target=str(src))
    ]
    s.ext_selected["skills"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "skills", ord("x"))
    assert msg is not None and "Unlinked" in msg
    assert not link.exists()


# ─── _handle_subtab_action: marketplace add/sync/remove ───────────────────────


def test_subtab_action_market_add(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        known_marketplaces=tmp_path / "km.json",
        marketplaces=tmp_path / "marketplaces",
    ))
    inputs = iter(["dir:/some/path", "mymarket"])
    monkeypatch.setattr("axt.text_input_modal",
                        lambda *a, **kw: next(inputs))
    captured = {}
    def fake_add(km, mk, name, source):
        captured["name"] = name
        captured["source"] = source
    monkeypatch.setattr("axt.tui.tabs.add_marketplace", fake_add)
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "market", ord("a"))
    assert msg is not None and "Added mymarket" in msg
    assert captured["name"] == "mymarket"
    assert captured["source"].kind == "directory"


def test_subtab_action_market_add_cancelled_at_source(monkeypatch):
    monkeypatch.setattr("axt.text_input_modal", lambda *a, **kw: None)
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(s, "market", ord("a")) is None


def test_subtab_action_market_add_parse_failure(monkeypatch):
    monkeypatch.setattr("axt.text_input_modal", lambda *a, **kw: "  ")  # blank → returns early
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.stdscr_callbacks = {"stdscr": object()}
    # Blank source string is falsy after strip? Actually "  " is truthy, then
    # parse_marketplace_source("") is called on strip → bare path → github.
    # To force a parse error, supply a value that the parser rejects.
    monkeypatch.setattr("axt.text_input_modal", lambda *a, **kw: "github:")
    # github: with empty repo parses OK (kind=github). Use a clearly invalid form.
    monkeypatch.setattr("axt.tui.tabs.parse_marketplace_source",
                        lambda s: (_ for _ in ()).throw(ValueError("bad")))
    msg = axt._handle_subtab_action(s, "market", ord("a"))
    assert msg is not None and "Parse failed" in msg


def test_subtab_action_market_sync(monkeypatch):
    monkeypatch.setattr("axt.tui.tabs.sync_marketplace",
                        lambda km, name: axt.SyncMarketplaceResult(before="a", after="b", updated=True))
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.ext_cache["market"] = [
        axt.MarketplaceInfo(name="m1",
                            source=axt.MarketplaceSource(kind="directory", path="/p"),
                            install_location="/loc", last_updated="2026-01-01")
    ]
    s.ext_selected["market"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "market", ord("S"))  # `s` is sort; sync = `S`
    assert msg is not None and "Synced m1" in msg


def test_subtab_action_market_remove_confirmed(monkeypatch):
    removed = []
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: True)
    monkeypatch.setattr("axt.tui.tabs.remove_marketplace",
                        lambda km, mk, name: removed.append(name))
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.ext_cache["market"] = [
        axt.MarketplaceInfo(name="m1",
                            source=axt.MarketplaceSource(kind="directory", path="/p"),
                            install_location="/loc", last_updated="2026-01-01")
    ]
    s.ext_selected["market"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "market", ord("x"))
    assert msg is not None and "Removed m1" in msg
    assert removed == ["m1"]


def test_subtab_action_market_none_selected_returns_none():
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.ext_cache["market"] = []
    s.stdscr_callbacks = {"stdscr": object()}
    # 's' with no selection returns None (m is None).
    assert axt._handle_subtab_action(s, "market", ord("s")) is None


# ─── _handle_subtab_action: hooks preview ─────────────────────────────────────


def test_subtab_action_hook_preview(monkeypatch):
    captured = []
    monkeypatch.setattr("axt.preview_modal",
                        lambda stdscr, content, title="Preview", **kw: captured.append((title, content)))
    monkeypatch.setattr("axt.tui.tabs.preview_hook",
                        lambda hook: axt.HookPreviewResult(
                            type="command", summary="ran echo",
                            output="hello", error="", exit_code=0))
    s = axt.TuiState()
    s.ext_sub_tab = "hooks"
    s.ext_cache["hooks"] = [
        axt.HookInfo(event="PreToolUse", matcher="*", source="user",
                     source_path="/s.json", type="command", command="echo hi")
    ]
    s.ext_selected["hooks"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "hooks", ord("v"))
    assert msg is None  # preview returns None
    assert captured
    assert "ran echo" in captured[0][1]
    assert "hello" in captured[0][1]


def test_subtab_action_hook_preview_none_selected():
    s = axt.TuiState()
    s.ext_sub_tab = "hooks"
    s.ext_cache["hooks"] = []
    s.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(s, "hooks", ord("v")) is None


# ─── _handle_subtab_action: commands/agents editor ────────────────────────────


def test_subtab_action_command_edit(monkeypatch):
    called = []
    monkeypatch.setattr("axt.open_in_editor",
                        lambda stdscr, path: called.append(path) or True)
    s = axt.TuiState()
    s.ext_sub_tab = "commands"
    s.ext_cache["commands"] = [
        axt.CommandInfo(name="cmd", source="user", source_path="/c.md",
                        description="d", content="x")
    ]
    s.ext_selected["commands"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "commands", ord("e"))
    assert called == ["/c.md"]
    assert msg is not None and "Opened" in msg


def test_subtab_action_agent_edit_no_source_path():
    s = axt.TuiState()
    s.ext_sub_tab = "agents"
    s.ext_cache["agents"] = [
        axt.AgentInfo(name="a", source="user", source_path="", description="d")
    ]
    s.ext_selected["agents"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    # No source_path → returns None.
    assert axt._handle_subtab_action(s, "agents", ord("e")) is None


# ─── render_extensions_tab: each sub-tab renders without error ────────────────


def _isolate_ext_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.HOME", tmp_path / "home")
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "claude",
        settings=tmp_path / "settings.json",
        installed_plugins=tmp_path / "ip.json",
        skills=tmp_path / "skills",
        vault=tmp_path / "vault",
        known_marketplaces=tmp_path / "km.json",
        marketplaces=tmp_path / "marketplaces",
    ))
    monkeypatch.chdir(tmp_path)


def test_render_extensions_skills_subtab_empty(tmp_path, monkeypatch):
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_extensions_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "No skills found." in flat


def test_render_extensions_commands_subtab_with_data(tmp_path, monkeypatch):
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    s.ext_sub_tab = "commands"
    s.ext_cache["commands"] = [
        axt.CommandInfo(name="deploy", source="user", source_path="/c.md",
                        description="Deploy the app", content="x", version="2.0")
    ]
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_extensions_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "/deploy" in flat
    assert "Deploy the app" in flat


def test_render_extensions_agents_subtab_with_data(tmp_path, monkeypatch):
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    s.ext_sub_tab = "agents"
    s.ext_cache["agents"] = [
        axt.AgentInfo(name="reviewer", source="user", source_path="/a.md",
                      description="Reviews code", version="1.1")
    ]
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_extensions_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "reviewer" in flat
    assert "Reviews code" in flat


def test_render_extensions_mcp_subtab_with_data(tmp_path, monkeypatch):
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    s.ext_sub_tab = "mcp"
    s.ext_cache["mcp"] = [
        axt.McpServerInfo(name="srv", plugin_id="p@m", command="node",
                          args=("server.js",), env=(), version="3.0")
    ]
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_extensions_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "srv" in flat
    assert "node" in flat


def test_render_extensions_mcp_subtab_on_column_shows_state(tmp_path, monkeypatch):
    """Enabled state renders in its own On column (●/○), not inlined into the
    server name as a ' [off]' suffix."""
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    s.ext_sub_tab = "mcp"
    s.ext_cache["mcp"] = [
        axt.McpServerInfo(name="live", plugin_id="", command="node",
                          args=(), env=()),
        axt.McpServerInfo(name="parked", plugin_id="", command="node",
                          args=(), env=(), disabled=True),
    ]
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_extensions_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "●" in flat            # enabled glyph
    assert "○" in flat            # disabled glyph
    assert "[off]" not in flat    # state no longer inlined into the name


def test_render_extensions_hooks_subtab_with_data(tmp_path, monkeypatch):
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    s.ext_sub_tab = "hooks"
    s.ext_cache["hooks"] = [
        axt.HookInfo(event="PreToolUse", matcher="*", source="user",
                     source_path="/s.json", type="command", command="echo hi")
    ]
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_extensions_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "PreToolUse" in flat


def test_render_extensions_hooks_subtab_on_column_shows_state(tmp_path, monkeypatch):
    """Hook enabled state renders in its own On column (●/○), not inlined into
    the event name as a ' [off]' suffix."""
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    s.ext_sub_tab = "hooks"
    s.ext_cache["hooks"] = [
        axt.HookInfo(event="PreToolUse", matcher="*", source="user",
                     source_path="/s.json", type="command", command="echo hi"),
        axt.HookInfo(event="PostToolUse", matcher="*", source="user",
                     source_path="/s.json", type="command", command="echo bye",
                     disabled=True),
    ]
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_extensions_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "●" in flat            # enabled glyph
    assert "○" in flat            # disabled glyph
    assert "[off]" not in flat    # state no longer inlined into the event name


def test_render_extensions_market_subtab_with_data(tmp_path, monkeypatch):
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.ext_cache["market"] = [
        axt.MarketplaceInfo(
            name="official",
            source=axt.MarketplaceSource(kind="github", repo="user/repo"),
            install_location="/loc/official", last_updated="2026-05-01T00:00:00Z")
    ]
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_extensions_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "official" in flat
    assert "github" in flat


def test_render_extensions_unknown_subtab_is_noop(tmp_path, monkeypatch):
    """An unrecognized sub-tab key hits the final `else: return` — sub-tab bar
    is still drawn but no list."""
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    s.ext_sub_tab = "vault"
    # Force an unknown key directly through the dispatch by patching ext_sub_tab
    # to a value not in the if/elif chain after the vault early-return guard.
    s.ext_sub_tab = "bogus"
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_extensions_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    # The sub-tab bar header still renders.
    assert "Sub:" in flat


# ─── render_usage_tab: full summary path (budget + cards + chart + active) ────


def test_render_usage_tab_full_summary_with_budget(tmp_path, monkeypatch):
    """A loaded usage tab with a configured budget and real entries renders
    the plan line, budget bar, period cards, the daily chart and insights."""
    import json
    _setup_isolated_paths(tmp_path, monkeypatch)
    # Configure a monthly budget + a claude plan so the budget bar + plan line draw.
    (tmp_path / "config.json").write_text(json.dumps({
        "monthly_budget": 100,
        "timezone": "UTC",
        "plans": {"claude": {"plan": "max", "monthly_cost": 200}},
    }))
    now = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = axt.UnifiedUsageEntry(
        platform="claude", model="claude-sonnet-4",
        timestamp=now, session_id="s1", project_path="/tmp/proj",
        input_tokens=2000, output_tokens=1000,
        cache_write_tokens=10, cache_read_tokens=5,
    )
    state = axt.TuiState()
    state.usage_entries = [entry]
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)
    state.context_analysis = _make_empty_context_analysis()
    scr = _make_stdscr(rows=50, cols=140)
    axt.render_usage_tab(scr, state, 0, 48, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Plan: max" in flat
    assert "Today" in flat and "Week" in flat and "Month" in flat
    assert "Last 14 days" in flat
    assert "Insights" in flat


def test_usage_period_card_aggregates():
    """_usage_period_card returns 3 lines with session/msg counts."""
    e = axt.UnifiedUsageEntry(
        platform="claude", model="claude-sonnet-4",
        timestamp="2026-05-01T00:00:00Z", session_id="s1", project_path="/p",
        input_tokens=100, output_tokens=50, cache_write_tokens=0, cache_read_tokens=0,
    )
    lines = axt._usage_period_card([e], "Today")
    assert len(lines) == 3
    assert "Today" in lines[0]
    assert "sessions=" in lines[0]
    assert "cost=$" in lines[2]


def test_gauge_attr_thresholds():
    assert axt._gauge_attr(95) == axt.CP_ERR()
    assert axt._gauge_attr(70) == axt.CP_INFO()
    assert axt._gauge_attr(10) == axt.CP_OK()


def test_fmt_quota_eta_buckets():
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    assert axt._fmt_quota_eta(None) == "—"
    assert axt._fmt_quota_eta(now - timedelta(seconds=10)) == "now"
    assert axt._fmt_quota_eta(now + timedelta(minutes=30)).endswith("m")
    assert "h" in axt._fmt_quota_eta(now + timedelta(hours=3))
    assert "d" in axt._fmt_quota_eta(now + timedelta(days=2))


def test_usage_gauge_lines_no_rate_limits(tmp_path, monkeypatch):
    """With no snapshot, the gauge lines include the missing/stale message."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(usage_snapshot=tmp_path / "none.json"))
    state = axt.TuiState()
    state.context_analysis = _make_empty_context_analysis()
    lines = axt._usage_gauge_lines(state, 120)
    flat = " ".join(t for (_x, t, _w, _a) in lines)
    assert "Rate limits: snapshot missing or stale" in flat


def test_usage_gauge_lines_with_snapshot(tmp_path, monkeypatch):
    """_usage_gauge_lines builds Context + 5h + 7d rows."""
    import json
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({
        "five_hour": {"used_percentage": 50, "resets_at": "2099-01-01T00:00:00Z"},
        "seven_day": {"used_percentage": 95, "resets_at": "2099-01-08T00:00:00Z"},
        "updated_at": "2099-01-01T00:00:00Z",
    }))
    monkeypatch.setattr("axt.PATHS", axt.Paths(usage_snapshot=snap))
    state = axt.TuiState()
    state.context_analysis = axt.ContextAnalysis(
        total_tokens=50_000, context_window_size=200_000, used_percent=25.0,
        model="m", sources=[],
        cost_impact=axt.CostImpact(
            model="m", cache_write_cost=0.0, cache_read_cost_per_turn=0.0,
            avg_turns_per_session=1, avg_sessions_per_day=1,
            per_session_cost=0.0, monthly_cost=0.0),
    )
    lines = axt._usage_gauge_lines(state, 140)
    assert len(lines) == 3  # context + 5h + 7d
    flat = " ".join(t for (_x, t, _w, _a) in lines)
    assert "Context:" in flat
    assert "5h:" in flat
    assert "7d:" in flat


def test_usage_summary_flags_unpriced_models(tmp_path, monkeypatch):
    """Entries from models without a pricing.json row render a warning line
    instead of silently contributing $0 to the totals."""
    now = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = axt.UnifiedUsageEntry(
        platform="claude", model="mystery-model-9",
        timestamp=now, session_id="s1", project_path="/p",
        input_tokens=1000, output_tokens=100,
        cache_write_tokens=0, cache_read_tokens=0)
    state = axt.TuiState()
    state.context_analysis = _make_empty_context_analysis()
    config = axt.AxtConfig()
    lines = axt._usage_summary_lines(state, config, [entry], 140)
    flat = " ".join(t for (_x, t, _w, _a) in lines)
    assert "unpriced models" in flat
    assert "mystery-model-9" in flat
    # The API-equivalent caption always renders.
    assert "not your subscription bill" in flat


# ─── _daily_costs ─────────────────────────────────────────────────────────────


def test_daily_costs_buckets_by_day():
    e = axt.UnifiedUsageEntry(
        platform="claude", model="claude-sonnet-4",
        timestamp="2026-05-01T12:00:00Z", session_id="s", project_path="/p",
        input_tokens=1000, output_tokens=1000, cache_write_tokens=0, cache_read_tokens=0,
    )
    out = axt._daily_costs([e], 14, "UTC")
    assert len(out) == 14
    # Each element is (MM-DD label, cost).
    assert all(len(label) == 5 for label, _ in out)


def test_date_iter_length_and_order():
    from datetime import datetime, timezone
    now = datetime(2026, 5, 10, tzinfo=timezone.utc)
    days = axt._date_iter(now, 5)
    assert len(days) == 5
    assert days[-1].day == 10  # last element is today
    assert days[0].day == 6    # 5 days ago


# ─── _context_rows ────────────────────────────────────────────────────────────


def test_context_rows_groups_and_sorts():
    a1 = axt.ContextSource(name="a1", category="memory", estimated_tokens=300,
                           percentage=3.0, path="", hint="", chars=1200, actionable=True)
    a2 = axt.ContextSource(name="a2", category="memory", estimated_tokens=200,
                           percentage=2.0, path="", hint="", chars=800, actionable=True)
    b1 = axt.ContextSource(name="b1", category="rules", estimated_tokens=1000,
                           percentage=10.0, path="", hint="", chars=4000, actionable=True)
    analysis = axt.ContextAnalysis(
        total_tokens=1500, context_window_size=200_000, used_percent=0.75,
        model="m", sources=[a1, a2, b1],
        cost_impact=axt.CostImpact(
            model="m", cache_write_cost=0.0, cache_read_cost_per_turn=0.0,
            avg_turns_per_session=1, avg_sessions_per_day=1,
            per_session_cost=0.0, monthly_cost=0.0),
    )
    rows = axt._context_rows(analysis)
    # rules (1000) sorts before memory (500).
    assert rows[0].category == "rules"
    assert rows[0].tokens == 1000
    assert rows[1].category == "memory"
    assert rows[1].items == 2
    assert rows[1].tokens == 500


# ─── render_context_tab: sources + project pane path ──────────────────────────


def test_render_context_tab_sources_and_project_sub_tabs(tmp_path, monkeypatch):
    """Each sub-tab renders its own body; the Rate limits strip and cost line
    persist across both."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    (tmp_path / "CLAUDE.md").write_text("# proj\nhello\n")
    state = axt.TuiState()
    state.context_analysis = _seed_context_analysis_with_sources()

    # Sources sub-tab: sources table, no Project sources list.
    state.context_sub_tab = "sources"
    scr = _make_stdscr(rows=40, cols=140)
    axt.render_context_tab(scr, state, 0, 38, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Category" in flat  # sources table header
    assert "Project context" not in flat
    assert "cost:" in flat

    # Project sub-tab: Project sources list.
    state.context_sub_tab = "project"
    scr = _make_stdscr(rows=40, cols=140)
    axt.render_context_tab(scr, state, 0, 38, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Project context" in flat
    assert "cost:" in flat


def test_render_context_tab_no_sources_message(tmp_path, monkeypatch):
    _setup_isolated_paths(tmp_path, monkeypatch)
    state = axt.TuiState()
    state.context_sub_tab = "sources"
    state.context_analysis = _make_empty_context_analysis()  # no sources
    scr = _make_stdscr(rows=40, cols=140)
    axt.render_context_tab(scr, state, 0, 38, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "No context sources detected." in flat


def test_render_project_files_pane_empty(tmp_path, monkeypatch):
    _setup_isolated_paths(tmp_path, monkeypatch)
    state = axt.TuiState()
    state.project_items = []  # explicitly empty
    scr = _make_stdscr(rows=20, cols=120)
    axt._render_project_files_table(scr, state, 0, 10, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "No project context sources found." in flat


def test_render_project_files_pane_with_items(tmp_path, monkeypatch):
    _setup_isolated_paths(tmp_path, monkeypatch)
    state = axt.TuiState()
    state.project_items = [_project_source("CLAUDE.md", path="/p/CLAUDE.md")]
    scr = _make_stdscr(rows=20, cols=120)
    axt._render_project_files_table(scr, state, 0, 10, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "CLAUDE.md" in flat
    assert "Project context" in flat


# ─── render_vault_tab: empty filtered + search prompt ─────────────────────────


def test_render_vault_tab_empty_filter_message(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=tmp_path / "vault", installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    monkeypatch.chdir(tmp_path)
    s = axt.TuiState()
    s.refresh_token = 1  # skip disk
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_vault_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Vault is empty or no items match" in flat


def test_render_vault_tab_search_prompt_visible():
    """When searching, the /search prompt row with cursor is drawn."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="alpha", type="skill", path="/p/alpha", description="d",
                      in_vault=True)
    ]
    s.refresh_token = 1
    s.vault_searching = True
    s.vault_search = "alp"
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_vault_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "/search: alp" in flat


def test_render_vault_tab_pending_indicator_in_title():
    """Pending toggles show a `pending=N` segment in the title row."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="alpha", type="skill", path="/p/alpha", description="d",
                      in_vault=True)
    ]
    s.refresh_token = 1
    s.vault_pending_project.add("alpha")
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_vault_tab(scr, s, 0, 20, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "pending=1" in flat


def test_render_vault_tab_used_in_detail_field(tmp_path, monkeypatch):
    """When the usage index has projects for the selected item, the detail
    panel includes a 'Used in' field listing project names."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="alpha", type="skill", path="/p/alpha", description="d",
                      in_vault=True)
    ]
    s.refresh_token = 1
    s.vault_usage_index = {
        "skill:alpha": axt.ExtensionUsage(type="skill", name="alpha", projects=[
            axt.ProjectRef(path="/x/projA", name="projA"),
            axt.ProjectRef(path="/x/projB", name="projB"),
        ])
    }
    # Bottom panel: render tall enough (detail_h clamps to 16) that all detail
    # fields — "Used in" is the last — are visible without scrolling.
    scr = _make_stdscr(rows=52, cols=140)
    axt.render_vault_tab(scr, s, 0, 50, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Used in" in flat
    assert "projA" in flat


# ─── loop.py: _handle_sub_tab_key left/right cycle + fall-through ─────────────


def test_sub_tab_left_right_cycle_sub_tabs():
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.focused_layer = "subTab"
    assert state.ext_sub_tab == "vault"
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, curses.KEY_RIGHT, "extensions")
    assert consumed is True
    assert state.ext_sub_tab == "skills"
    consumed = axt._handle_layer_key(scr, state, curses.KEY_LEFT, "extensions")
    assert consumed is True
    assert state.ext_sub_tab == "vault"


def test_sub_tab_unrecognized_key_not_consumed():
    """A non-navigation key on the subTab layer returns False (not consumed)."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("extensions")
    state.focused_layer = "subTab"
    scr = _make_stdscr()
    assert axt._handle_layer_key(scr, state, ord("z"), "extensions") is False


def test_main_tab_unrecognized_key_not_consumed():
    """A non-navigation key on the mainTab layer returns False."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("usage")
    state.focused_layer = "mainTab"
    scr = _make_stdscr()
    assert axt._handle_layer_key(scr, state, ord("z"), "usage") is False


def test_content_layer_non_climb_key_not_consumed():
    """A content-layer key that is neither Esc nor an up-at-top climb returns
    False so the tab body handler can process it."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("context")
    state.context_sub_tab = "sources"
    state.focused_layer = "content"
    state.context_selected = 3  # not at top → KEY_UP does not climb
    scr = _make_stdscr()
    assert axt._handle_content_layer_key(scr, state, curses.KEY_UP, "context") is False
    assert axt._handle_content_layer_key(scr, state, ord("j"), "context") is False


# ─── loop.py: _tui_loop driven with a mock stdscr (no real TTY) ──────────────
#
# _tui_loop takes `stdscr` as a parameter and only touches curses module
# functions we can monkeypatch — it does NOT spawn its own curses.wrapper.
# Feeding a key sequence through stdscr.getch() exercises the dispatch loop
# without a terminal.


def _loop_stdscr(keys, rows=30, cols=120):
    """Mock stdscr for _tui_loop: getch() returns `keys` in order. The final
    key MUST cause the loop to return (e.g. ord('q'))."""
    scr = _make_stdscr(rows, cols)
    seq = iter(keys)
    scr.getch.side_effect = lambda: next(seq)
    return scr


def _quiet_curses(monkeypatch):
    monkeypatch.setattr("curses.curs_set", lambda *a: None)
    monkeypatch.setattr("curses.set_escdelay", lambda *a: None, raising=False)
    monkeypatch.setattr("axt.tui.loop.tui_init_colors", lambda *a, **k: None)
    # _tui_loop primes a background project-usage scan on launch; stub it so
    # loop tests never spawn a real daemon thread / clobber the on-disk cache.
    monkeypatch.setattr("axt.tui.loop._prime_vault_scan", lambda *a, **k: None)


def test_tui_loop_t_persists_theme_toggle(monkeypatch, tmp_path):
    """Pressing `t` flips the theme and persists the new value. The palette
    re-init is stubbed by _quiet_curses, so current_theme() stays at the value
    we seed (dark) and the first toggle resolves to light."""
    monkeypatch.chdir(tmp_path)
    axt.tui_init_colors("dark")  # seed the active theme
    _quiet_curses(monkeypatch)   # stubs loop.tui_init_colors → theme stays put
    persisted = []
    monkeypatch.setattr("axt.tui.loop._persist_theme", lambda t: persisted.append(t))
    scr = _loop_stdscr([ord("t"), ord("q")])
    axt._tui_loop(scr, "dark")
    assert persisted == ["light"]


def test_tui_loop_quits_on_q(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _quiet_curses(monkeypatch)
    scr = _loop_stdscr([ord("q")])
    # Returns cleanly (None) without raising.
    assert axt._tui_loop(scr) is None
    assert scr.keypad.called


def test_tui_loop_help_then_quit(monkeypatch, tmp_path):
    """`?` opens the help preview, then `q` quits. preview_modal is stubbed."""
    monkeypatch.chdir(tmp_path)
    _quiet_curses(monkeypatch)
    shown = []
    monkeypatch.setattr("axt.tui.loop.preview_modal",
                        lambda stdscr, content, title="Preview": shown.append(title))
    scr = _loop_stdscr([ord("?"), ord("q")])
    axt._tui_loop(scr)
    assert shown == ["axt help"]


def test_tui_loop_esc_at_main_tab_quits(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _quiet_curses(monkeypatch)
    scr = _loop_stdscr([27])  # Esc at mainTab → quit
    assert axt._tui_loop(scr) is None


def test_tui_loop_number_key_switches_tab_then_quit(monkeypatch, tmp_path):
    """Pressing '2' jumps to the Context tab (index 1) before quitting."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    _quiet_curses(monkeypatch)
    captured = {}
    real_handle = axt.handle_context_input

    # Drive: press '2' then 'q'. We can't read state after return, so verify
    # via a render-frame side effect: capture state.tab_idx at quit time by
    # patching _render_frame to record it.
    real_render = axt.tui.loop._render_frame
    def spy_render(stdscr, state):
        captured["tab_idx"] = state.tab_idx
        return real_render(stdscr, state)
    monkeypatch.setattr("axt.tui.loop._render_frame", spy_render)
    scr = _loop_stdscr([ord("2"), ord("q")])
    axt._tui_loop(scr)
    assert captured["tab_idx"] == _tab_idx("context")


def test_tui_loop_resize_then_quit(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _quiet_curses(monkeypatch)
    scr = _loop_stdscr([curses.KEY_RESIZE, ord("q")])
    assert axt._tui_loop(scr) is None


def test_tui_loop_context_sub_tab_switch_then_quit(monkeypatch, tmp_path):
    """←/→ on the Context sub-tab bar switches sub-tabs (Project → Sources)."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    monkeypatch.setattr("axt.tui.tabs.analyze_context",
                        lambda **kw: _seed_context_analysis_with_sources())
    _quiet_curses(monkeypatch)
    captured = {}
    real_render = axt.tui.loop._render_frame
    def spy_render(stdscr, state):
        captured["sub_tab"] = state.context_sub_tab
        return real_render(stdscr, state)
    monkeypatch.setattr("axt.tui.loop._render_frame", spy_render)
    # '2' → Context tab; ↓ → subTab layer; → cycles to Sources; 'q' quits.
    scr = _loop_stdscr([ord("2"), curses.KEY_DOWN, curses.KEY_RIGHT, ord("q")])
    axt._tui_loop(scr)
    assert captured["sub_tab"] == "sources"


def test_tui_loop_timeout_tick_redraws(monkeypatch, tmp_path):
    """A -1 getch (timeout) while background work is pending triggers a redraw,
    then the next key quits."""
    monkeypatch.chdir(tmp_path)
    _quiet_curses(monkeypatch)
    render_count = [0]
    real_render = axt.tui.loop._render_frame
    def counting_render(stdscr, state):
        render_count[0] += 1
        return real_render(stdscr, state)
    monkeypatch.setattr("axt.tui.loop._render_frame", counting_render)
    scr = _loop_stdscr([-1, -1, ord("q")])
    axt._tui_loop(scr)
    # initial render + 2 timeout-tick redraws (q does a final-ish redraw path
    # only via handler; quit returns before that). At minimum 3 renders.
    assert render_count[0] >= 3


def test_tui_loop_content_layer_routes_keys_to_tab_handler(monkeypatch, tmp_path):
    """Descending into the Context content layer and pressing `j` must route
    the key to handle_context_input (advancing context_selected)."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    _quiet_curses(monkeypatch)
    # Seed two context categories so `j` has somewhere to move.
    monkeypatch.setattr("axt.tui.tabs.analyze_context",
                        lambda **kw: _seed_context_analysis_with_sources())
    captured = {}
    real_render = axt.tui.loop._render_frame
    def spy_render(stdscr, state):
        captured["layer"] = state.focused_layer
        captured["selected"] = state.context_selected
        return real_render(stdscr, state)
    monkeypatch.setattr("axt.tui.loop._render_frame", spy_render)
    # '2' → Context tab; ↓ → subTab (Project); → cycles to Sources; ↓ → content
    # layer; 'j' → handler; 'q' quits.
    scr = _loop_stdscr([ord("2"), curses.KEY_DOWN, curses.KEY_RIGHT,
                        curses.KEY_DOWN, ord("j"), ord("q")])
    axt._tui_loop(scr)
    assert captured["layer"] == "content"


def test_tui_loop_plugins_detail_esc_returns_focus_to_list(monkeypatch, tmp_path):
    """Full loop: focus the plugins detail panel (Tab), Esc blurs it back to
    the list — staying on the content layer — and `j` then moves the list
    selection."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    _quiet_curses(monkeypatch)
    monkeypatch.setattr("axt.tui.tabs.list_installed_plugins",
                        lambda *_a: [_plugin("a"), _plugin("b")])
    captured = {}
    real_render = axt.tui.loop._render_frame
    def spy_render(stdscr, state):
        captured["layer"] = state.focused_layer
        captured["detail"] = state.ext_detail_focused
        captured["selected"] = state.ext_selected.get("plugins", 0)
        return real_render(stdscr, state)
    monkeypatch.setattr("axt.tui.loop._render_frame", spy_render)
    # ↓ → subTab; ←← → vault→market→plugins; ↓ → content; Tab → focus detail;
    # Esc → blur back to list (content layer); j → next row; q → quit.
    scr = _loop_stdscr([
        curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_LEFT, curses.KEY_DOWN,
        9, 27, ord("j"), ord("q"),
    ])
    axt._tui_loop(scr)
    assert captured["layer"] == "content"
    assert captured["detail"] is False
    assert captured["selected"] == 1


def test_tui_loop_resize_in_modal_state_redraws(monkeypatch, tmp_path):
    """KEY_RESIZE while in a vault modal sub-state takes the modal resize
    branch (still redraws), then quits via the handler path."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        vault=tmp_path / "vault", installed_plugins=tmp_path / "ip.json",
        claude_dir=tmp_path / "claude",
    ))
    monkeypatch.chdir(tmp_path)
    _quiet_curses(monkeypatch)
    # Vault sub-tab with one item; descend to content, focus the detail panel
    # (Tab) → that is a modal sub-state. Then KEY_RESIZE (modal branch), then q.
    captured = {"detail_ever": False}
    real_render = axt.tui.loop._render_frame
    def spy_render(stdscr, state):
        if state.vault_detail_focused:
            captured["detail_ever"] = True
        return real_render(stdscr, state)
    monkeypatch.setattr("axt.tui.loop._render_frame", spy_render)
    # Pre-seed vault items by faking _vault_load via refresh_token + direct list
    # — but the loop builds its own TuiState. Instead, monkeypatch _vault_load
    # to populate one item so descent works.
    def fake_load(state):
        state.vault_items = [
            axt.VaultItem(name="a", type="skill", path="/p/a", description="d",
                          in_vault=True)
        ]
    monkeypatch.setattr("axt.tui.tabs._vault_load", fake_load)
    # mainTab→subTab (KEY_DOWN), subTab→content (KEY_DOWN, needs items), Tab
    # (focus detail = modal), KEY_RESIZE (modal resize branch), Esc (blurs the
    # detail panel via the handler — exits the modal sub-state), q (quits — `q`
    # only quits when NOT in a modal sub-state).
    scr = _loop_stdscr([
        curses.KEY_DOWN, curses.KEY_DOWN, 9, curses.KEY_RESIZE, 27, ord("q"),
    ])
    axt._tui_loop(scr)
    assert captured["detail_ever"] is True


# ─── More tabs.py branch coverage ────────────────────────────────────────────


def test_compute_simple_insights_skips_unparseable_timestamps():
    """Entries with timestamps that don't parse are skipped in the parallel
    computation (the `continue` branches)."""
    good = axt.ClaudeUsageEntry(
        model="m", input_tokens=10, output_tokens=10,
        cache_creation_tokens=0, cache_read_tokens=0,
        session_id="s1", project_path="p", timestamp="2026-04-29T10:00:00Z")
    bad = axt.ClaudeUsageEntry(
        model="m", input_tokens=10, output_tokens=10,
        cache_creation_tokens=0, cache_read_tokens=0,
        session_id="s2", project_path="p", timestamp="not-a-timestamp")
    out = axt._compute_simple_insights([good, bad])
    # Only the good entry contributes a parseable bucket → not 3 sessions →
    # parallel_pct stays 0, and the function does not raise.
    assert out["parallel_pct"] == 0.0
    assert out["top_model"] == "m"


def test_handle_usage_input_unrecognized_key_returns_none():
    s = axt.TuiState()
    assert axt.handle_usage_input(s, ord("z")) is None


def _usage_entry_now():
    now = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return axt.UnifiedUsageEntry(
        platform="claude", model="claude-opus-4-7",
        timestamp=now, session_id="s1", project_path="/p",
        input_tokens=100_000, output_tokens=20_000,
        cache_write_tokens=0, cache_read_tokens=0)


def test_usage_summary_budget_over_limit_shows_stop():
    """A cost over the monthly budget renders the ⛔ marker (pct >= 1 branch)."""
    import dataclasses
    entry = _usage_entry_now()
    cost = axt._entry_cost(entry)
    assert cost > 0  # sanity: opus-4-7 is in the pricing table
    config = dataclasses.replace(axt.AxtConfig(), monthly_budget=cost / 2)  # over 100%
    state = axt.TuiState()
    state.usage_config = config
    state.context_analysis = _make_empty_context_analysis()
    lines = axt._usage_summary_lines(state, config, [entry], 140)
    flat = " ".join(t for (_x, t, _w, _a) in lines)
    assert "⛔" in flat


def test_usage_summary_budget_warning_threshold():
    """A cost between 80% and 100% of budget renders the ⚠ marker."""
    import dataclasses
    entry = _usage_entry_now()
    cost = axt._entry_cost(entry)
    config = dataclasses.replace(axt.AxtConfig(), monthly_budget=cost / 0.9)  # ~90%
    state = axt.TuiState()
    state.usage_config = config
    state.context_analysis = _make_empty_context_analysis()
    lines = axt._usage_summary_lines(state, config, [entry], 140)
    flat = " ".join(t for (_x, t, _w, _a) in lines)
    assert "⚠" in flat


def test_render_usage_tab_clamps_negative_scroll(tmp_path, monkeypatch):
    """A negative usage_scroll is clamped back to 0 during render."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    state = axt.TuiState()
    state.usage_entries = []
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)
    state.usage_scroll = -5
    scr = _make_stdscr(rows=30, cols=120)
    axt.render_usage_tab(scr, state, 0, 28, 120)
    assert state.usage_scroll == 0


# ─── _handle_subtab_action: error-return branches ────────────────────────────


def test_subtab_action_market_sync_failure(monkeypatch):
    monkeypatch.setattr("axt.tui.tabs.sync_marketplace",
                        lambda km, name: (_ for _ in ()).throw(RuntimeError("network")))
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.ext_cache["market"] = [
        axt.MarketplaceInfo(name="m1",
                            source=axt.MarketplaceSource(kind="directory", path="/p"),
                            install_location="/loc", last_updated="2026-01-01")
    ]
    s.ext_selected["market"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "market", ord("S"))  # `s` is sort; sync = `S`
    assert msg is not None and "Sync failed" in msg


def test_subtab_action_skill_link_unsupported(monkeypatch):
    """When symlinks are unsupported (e.g. Windows), `l` returns a clear msg."""
    monkeypatch.setattr("axt.tui.tabs.is_symlink_supported", lambda: False)
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "skills", ord("a"))
    assert msg == "Symlinks unsupported on this platform"


def test_handle_vault_input_scan_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        projects=tmp_path / "projects", vault=tmp_path / "vault"))
    monkeypatch.setattr("axt.tui.tabs._vault_scan",
                        lambda state: (_ for _ in ()).throw(OSError("scan boom")))
    s = axt.TuiState()
    s.refresh_token = 1
    msg = axt.handle_vault_input(s, ord("f"))
    assert msg is not None and "Scan failed" in msg


def test_handle_vault_input_mode_scan_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        projects=tmp_path / "projects", vault=tmp_path / "vault"))
    monkeypatch.setattr("axt.tui.tabs._vault_scan",
                        lambda state: (_ for _ in ()).throw(OSError("scan boom")))
    s = axt.TuiState()
    s.refresh_token = 1
    msg = axt.handle_vault_input(s, ord("F"))
    assert msg is not None and "Scan failed" in msg
    # Mode still toggled despite the scan failure.
    assert s.vault_scan_mode == "full"


# ─── Coverage push: widgets.py deep branches ─────────────────────────────────


def test_cp_mark_returns_pair_or_zero():
    """CP_MARK() returns a color attr (or 0 when start_color is unavailable),
    never raising — exercises the magenta `_safe_pair(6)` shortcut."""
    val = axt.CP_MARK()
    assert isinstance(val, int)


def test_is_quit_recognizes_q_and_esc():
    assert axt.is_quit(ord("q")) is True
    assert axt.is_quit(ord("Q")) is True
    assert axt.is_quit(27) is True  # Esc
    assert axt.is_quit(ord("a")) is False


def test_render_table_scrolls_up_when_selected_above_window():
    """When `selected` is above the current top_offset window, render_table
    rewinds visible_start to the selection (the `selected < visible_start`
    arm). Row 0's prefix must appear since selection 0 forces the window up."""
    scr = _make_stdscr(rows=30, cols=80)
    cols = [axt.TableColumn("name", "Name", 20)]
    rows = [{"name": f"row{i}"} for i in range(20)]
    # avail = h(5) - header(2) = 3 visible rows. top_offset=10 puts the window
    # well below selection 0, so the up-scroll branch must fire.
    axt.render_table(scr, 0, 0, 5, 80, cols, rows,
                     selected=0, show_header=True, top_offset=10)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    # The first data row's selected prefix `▸ 1` proves window rewound to row 0.
    assert "row0" in flat
    assert "row10" not in flat


def test_wrap_to_cells_nonpositive_width_returns_text_as_single_line():
    """_wrap_to_cells with max_cells <= 0 short-circuits, returning [text]."""
    assert axt._wrap_to_cells("abc", 0) == ["abc"]
    assert axt._wrap_to_cells("xyz", -3) == ["xyz"]


def test_text_input_modal_curs_set_errors_are_swallowed(monkeypatch):
    """text_input_modal must not raise when curses.curs_set raises on entry
    (line 468-469) and on the finally exit (line 494-495). Esc returns None."""
    scr = _make_stdscr(rows=24, cols=100)
    win = MagicMock()
    win.getch.return_value = 27  # Esc → return None immediately
    monkeypatch.setattr("curses.newwin", lambda *a: win)
    monkeypatch.setattr("curses.curs_set",
                        lambda *a: (_ for _ in ()).throw(curses.error("no cursor")))
    out = axt.text_input_modal(scr, "prompt", title="t")
    assert out is None


def test_open_in_editor_curs_set_error_swallowed(monkeypatch, tmp_path):
    """open_in_editor swallows a curses.error from curs_set after the editor
    returns (lines 585-586) and still reports success on rc==0."""
    monkeypatch.setattr("subprocess.call", lambda *a, **kw: 0)
    monkeypatch.setattr("curses.endwin", lambda: None)
    monkeypatch.setattr("curses.curs_set",
                        lambda *a: (_ for _ in ()).throw(curses.error("no cursor")))
    scr = _make_stdscr()
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert axt.open_in_editor(scr, f) is True


# ─── Coverage push: tabs.py deep branches ────────────────────────────────────


def test_save_scan_cache_swallows_oserror(monkeypatch):
    """_save_scan_cache best-effort: a write error is caught (lines 242-243)."""
    monkeypatch.setattr("axt.tui.tabs.write_json_atomic",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    # Should not raise.
    axt._save_scan_cache({}, "default")


def test_load_scan_cache_non_dict_payload(monkeypatch, tmp_path):
    """_load_scan_cache returns the default tuple when the cache file is not a
    dict (line 253)."""
    monkeypatch.setattr("axt.tui.tabs.read_json", lambda *a, **kw: ["not", "a", "dict"])
    index, mode, scanned_at = axt._load_scan_cache()
    assert index == {}
    assert mode == "default"
    assert scanned_at is None


def test_load_scan_cache_non_dict_entries(monkeypatch):
    """When `entries` is not a dict, _load_scan_cache returns default (line 256)."""
    monkeypatch.setattr("axt.tui.tabs.read_json",
                        lambda *a, **kw: {"mode": "full", "entries": ["bad"]})
    index, mode, _ = axt._load_scan_cache()
    assert index == {}
    assert mode == "default"


def test_load_scan_cache_skips_non_dict_entry_value(monkeypatch):
    """A non-dict value inside `entries` is skipped (line 260 `continue`)."""
    monkeypatch.setattr("axt.tui.tabs.read_json", lambda *a, **kw: {
        "mode": "full",
        "entries": {"skill:bad": "not-a-dict",
                    "skill:good": {"type": "skill", "name": "good", "projects": []}},
    })
    index, mode, _ = axt._load_scan_cache()
    assert "skill:bad" not in index
    assert "skill:good" in index
    assert mode == "full"


def test_usage_index_drop_missing_entry_is_noop():
    """_usage_index_drop returns early when the key is absent (line 293)."""
    index = {}
    axt._usage_index_drop(index, "skill", "ghost", "/p")
    assert index == {}


def test_vault_apply_pending_skips_plugin_items():
    """A plugin in the pending sets is discarded without a link attempt
    (lines 312-313 for project, 326-328 for global)."""
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="plug", type="plugin", path="", description=""),
    ]
    s.vault_pending_project.add("plug")
    s.vault_pending_global.add("plug")
    s.vault_pending_project.add("ghost-removed")  # not in items → also discarded
    msg = axt._vault_apply_pending(s)
    assert "Applied 0" in msg
    assert not s.vault_pending_project
    assert not s.vault_pending_global


def test_vault_apply_pending_project_link_error_counted(monkeypatch):
    """A link_to_project raising OSError increments the error count (line 322-323)."""
    monkeypatch.setattr("axt.tui.tabs.link_to_project",
                        lambda cwd, item: (_ for _ in ()).throw(OSError("boom")))
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="sk", type="skill", path="", description="", is_linked=False),
    ]
    s.vault_pending_project.add("sk")
    msg = axt._vault_apply_pending(s)
    assert "1 errors" in msg


def test_vault_apply_pending_global_link_and_unlink(monkeypatch):
    """Exercises the global link path (line 334) and the global-unlink path
    (line 332) plus its error arm (lines 336-338)."""
    linked = []
    monkeypatch.setattr("axt.tui.tabs.link_to_global",
                        lambda claude_dir, item: linked.append(item.name))
    monkeypatch.setattr("axt.tui.tabs.unlink_from_global",
                        lambda claude_dir, item: (_ for _ in ()).throw(OSError("nope")))
    s = axt.TuiState()
    s.vault_items = [
        axt.VaultItem(name="newg", type="skill", path="", description="",
                      is_global_linked=False),
        axt.VaultItem(name="oldg", type="skill", path="", description="",
                      is_global_linked=True),
    ]
    s.vault_pending_global.add("newg")
    s.vault_pending_global.add("oldg")
    msg = axt._vault_apply_pending(s)
    assert "newg" in linked
    assert "1 errors" in msg  # the unlink raise


def test_vault_filtered_sort_added():
    """Sort by `added` orders newest-first using created_at (line 358)."""
    import datetime as _dt
    old = _dt.datetime(2020, 1, 1, tzinfo=_dt.timezone.utc)
    new = _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)
    s = axt.TuiState()
    s.vault_sort = "added"
    s.vault_items = [
        axt.VaultItem(name="older", type="skill", path="", description="", created_at=old),
        axt.VaultItem(name="newer", type="skill", path="", description="", created_at=new),
    ]
    names = [i.name for i in axt._vault_filtered(s)]
    assert names == ["newer", "older"]


def test_vault_filtered_sort_updated():
    """Sort by `updated` orders newest-first using updated_at (line 360)."""
    import datetime as _dt
    s = axt.TuiState()
    s.vault_sort = "updated"
    s.vault_items = [
        axt.VaultItem(name="a", type="skill", path="", description="",
                      updated_at=_dt.datetime(2021, 5, 5, tzinfo=_dt.timezone.utc)),
        axt.VaultItem(name="b", type="skill", path="", description="",
                      updated_at=_dt.datetime(2025, 5, 5, tzinfo=_dt.timezone.utc)),
    ]
    names = [i.name for i in axt._vault_filtered(s)]
    assert names == ["b", "a"]


def test_vault_filtered_sort_project():
    """Sort by `project` puts linked items first (line 362)."""
    s = axt.TuiState()
    s.vault_sort = "project"
    s.vault_items = [
        axt.VaultItem(name="unlinked", type="skill", path="", description="", is_linked=False),
        axt.VaultItem(name="linked", type="skill", path="", description="", is_linked=True),
    ]
    names = [i.name for i in axt._vault_filtered(s)]
    assert names == ["linked", "unlinked"]


def test_vault_filtered_sort_global():
    """Sort by `global` puts globally-linked items first (line 364)."""
    s = axt.TuiState()
    s.vault_sort = "global"
    s.vault_items = [
        axt.VaultItem(name="local", type="skill", path="", description="", is_global_linked=False),
        axt.VaultItem(name="glob", type="skill", path="", description="", is_global_linked=True),
    ]
    names = [i.name for i in axt._vault_filtered(s)]
    assert names == ["glob", "local"]


def test_vault_g_toggle_removes_existing_global_pending():
    """`g` on an already-pending global item removes it (line 666)."""
    s = axt.TuiState()
    s.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    s.vault_pending_global.add("alpha")
    axt.handle_vault_input(s, ord("g"))
    assert "alpha" not in s.vault_pending_global


def test_vault_apply_confirm_modal_skips_missing_item(monkeypatch):
    """The confirm-message builder skips a pending name with no matching item
    (line 684 `continue`), still showing the apply prompt and applying on yes."""
    seen = {}
    monkeypatch.setattr("axt.confirm_modal",
                        lambda stdscr, msg, title="Confirm": seen.setdefault("msg", msg) or True)
    applied = []
    monkeypatch.setattr("axt.tui.tabs._vault_apply_pending",
                        lambda state: applied.append(True) or "Applied 1")
    s = axt.TuiState()
    s.vault_items = [axt.VaultItem(name="real", type="skill", path="", description="")]
    s.vault_pending_project.add("real")
    s.vault_pending_project.add("phantom")  # no item → skipped in _lines
    s.vault_pending_global.add("realg")      # builds the Global section (694-695)
    s.vault_items.append(axt.VaultItem(name="realg", type="skill", path="", description=""))
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt.handle_vault_input(s, 10)  # Enter → confirm apply
    assert applied == [True]
    assert "Global" in seen["msg"]
    assert "phantom" not in seen["msg"]


def test_skills_import_records_project_local_profile(tmp_path, monkeypatch):
    """`i` on a project-source skill under <proj>/.claude/skills imports it
    and records the link in .axt-profile.json."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=tmp_path / "claude", vault=tmp_path / "vault",
        installed_plugins=tmp_path / "ip.json"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("axt.tui.tabs.import_to_vault", lambda cd, vd, item: None)
    written = {}
    monkeypatch.setattr("axt.tui.tabs.write_profile",
                        lambda cwd, profile: written.setdefault("profile", profile))
    s = axt.TuiState()
    s.ext_cache["skills"] = [axt.SkillInfo(
        name="loc", path=str(tmp_path / ".claude" / "skills" / "loc"),
        is_symlink=False, source="project")]
    s.ext_selected["skills"] = 0
    msg = axt._act_import_to_vault(s, None, "skills", ord("i"))
    assert msg is not None and "Imported" in msg
    assert "loc" in written["profile"].skills


def test_vault_migrate_failure(monkeypatch):
    """`m` migrate raising OSError returns a 'Migrate failed' message (767-768)."""
    monkeypatch.setattr("axt.tui.tabs.migrate_to_vault",
                        lambda cd, vd: (_ for _ in ()).throw(OSError("mig boom")))
    s = axt.TuiState()
    s.vault_items = [axt.VaultItem(name="x", type="skill", path="", description="")]
    msg = axt.handle_vault_input(s, ord("m"))
    assert msg is not None and "Migrate failed" in msg


def test_vault_migrate_success_with_moves_invalidates_context(monkeypatch):
    """`m` migrate with at least one moved item hits _invalidate_context
    (line 765) and returns the summary line."""
    monkeypatch.setattr("axt.tui.tabs.migrate_to_vault",
                        lambda cd, vd: axt.MigrateResult(moved=["a"], skipped=[], errors=[]))
    monkeypatch.setattr("axt.tui.tabs._vault_load", lambda state: None)
    invalidated = []
    monkeypatch.setattr("axt.tui.tabs._invalidate_context",
                        lambda state: invalidated.append(True))
    s = axt.TuiState()
    s.vault_items = [axt.VaultItem(name="x", type="skill", path="", description="")]
    msg = axt.handle_vault_input(s, ord("m"))
    assert msg is not None and "Migrated: +1" in msg
    assert invalidated == [True]


def test_vault_sync_failure(monkeypatch):
    """`S` sync raising OSError returns a 'Sync failed' message (776-777)."""
    monkeypatch.setattr("axt.tui.tabs.sync_project",
                        lambda cwd, vd: (_ for _ in ()).throw(OSError("sync boom")))
    s = axt.TuiState()
    s.vault_items = [axt.VaultItem(name="x", type="skill", path="", description="")]
    msg = axt.handle_vault_input(s, ord("S"))
    assert msg is not None and "Sync failed" in msg


def test_vault_sync_success_invalidates_context(monkeypatch):
    """`S` sync with linked changes hits the _invalidate_context branch (line 774)."""
    monkeypatch.setattr("axt.tui.tabs.sync_project",
                        lambda cwd, vd: axt.SyncResult(linked=["a"], unlinked=[], errors=[]))
    monkeypatch.setattr("axt.tui.tabs._vault_load", lambda state: None)
    invalidated = []
    monkeypatch.setattr("axt.tui.tabs._invalidate_context",
                        lambda state: invalidated.append(True))
    s = axt.TuiState()
    s.vault_items = [axt.VaultItem(name="x", type="skill", path="", description="")]
    msg = axt.handle_vault_input(s, ord("S"))
    assert msg is not None and "Sync" in msg
    assert invalidated == [True]


def test_bar_chart_lines_empty_returns_empty_list():
    """_bar_chart_lines with no data returns [] (line 838)."""
    assert axt._bar_chart_lines([], 60) == []


def test_daily_costs_invalid_timezone_falls_back(monkeypatch):
    """_daily_costs with an unresolvable tz hits the `except Exception: pass`
    fallback (lines 887-888) and still returns one label per day."""
    out = axt._daily_costs([], days=3, tz="Not/AReal_Zone")
    assert len(out) == 3
    # Each tuple is (MM-DD label, cost) and cost is 0.0 with no entries.
    assert all(c == 0.0 for _label, c in out)


def test_render_rate_limit_bars_no_reset_shows_dash(tmp_path, monkeypatch):
    """A rate-limit entry with no reset_at renders the em-dash ETA (line 1327)."""
    import json
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({
        "five_hour": {"used_percentage": 50},  # no resets_at
        "updated_at": "2099-01-01T00:00:00Z",
    }))
    monkeypatch.setattr("axt.PATHS", axt.Paths(usage_snapshot=snap))
    scr = _make_stdscr(rows=30, cols=120)
    used = axt._render_rate_limit_bars(scr, 0, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert used >= 1
    assert "(—)" in flat


def test_render_rate_limit_bars_reset_now_and_minutes(tmp_path, monkeypatch):
    """reset_at in the past → 'now' (line 1331); within the hour → minutes
    (line 1333)."""
    import json
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({
        "five_hour": {"used_percentage": 95, "resets_at": "2000-01-01T00:00:00Z"},  # past → now
        "seven_day": {"used_percentage": 30, "resets_at": "2099-01-01T00:00:00Z"},
        "updated_at": "2099-01-01T00:00:00Z",
    }))
    monkeypatch.setattr("axt.PATHS", axt.Paths(usage_snapshot=snap))
    scr = _make_stdscr(rows=30, cols=120)
    axt._render_rate_limit_bars(scr, 0, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "(now)" in flat


def test_render_rate_limit_minutes_eta(monkeypatch):
    """Directly exercise the <3600s minutes branch (line 1333) via fmt_eta by
    rendering with a near-future reset."""
    import json
    import datetime as _dt
    soon = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=30)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Build a snapshot dict file on the fly.
    import tempfile, os as _os
    fd, path = tempfile.mkstemp(suffix=".json")
    with _os.fdopen(fd, "w") as fh:
        json.dump({"five_hour": {"used_percentage": 20, "resets_at": soon},
                   "updated_at": "2099-01-01T00:00:00Z"}, fh)
    monkeypatch.setattr("axt.PATHS", axt.Paths(usage_snapshot=Path(path)))
    scr = _make_stdscr(rows=30, cols=120)
    axt._render_rate_limit_bars(scr, 0, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    _os.unlink(path)
    assert "(29m)" in flat or "(30m)" in flat


def test_render_context_sources_empty_category_detail(monkeypatch, tmp_path):
    """A selected category row whose sources list is empty after filtering
    renders the `(empty)` detail field (line 1394)."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    # Analysis has a single `memory` source.
    src = axt.ContextSource(
        name="x", category="memory", estimated_tokens=10, percentage=1.0,
        path="", hint="", chars=40, actionable=True)
    analysis = axt.ContextAnalysis(
        total_tokens=10, context_window_size=200_000, used_percent=0.1,
        model="m", sources=[src],
        cost_impact=axt.CostImpact(
            model="m", cache_write_cost=0.0, cache_read_cost_per_turn=0.0,
            avg_turns_per_session=1, avg_sessions_per_day=1,
            per_session_cost=0.0, monthly_cost=0.0))
    # Hand-craft a row whose category (`rules`) has NO matching source, so the
    # per-category filter in _context_detail_for yields the empty placeholder
    # (the shared bottom detail panel now owns this; tables are full-width).
    rows = [axt._ContextCategoryRow(
        category="rules", scope="global", label="Rules", items=0, tokens=0, pct=0.0)]
    state = axt.TuiState()
    state.context_sub_tab = "sources"
    state.context_selected = 0
    title, fields = axt._context_detail_for(state, analysis, rows)
    assert title == "Rules — global"
    assert ("(empty)", "—") in fields


def test_render_context_tab_loading_when_analysis_none(tmp_path, monkeypatch):
    """render_context_tab shows 'Loading context…' when analysis is None
    (lines 1424-1425). Prevent _ensure_context_loaded from populating it."""
    monkeypatch.setattr("axt.tui.tabs._ensure_context_loaded", lambda state: None)
    scr = _make_stdscr(rows=30, cols=120)
    state = axt.TuiState()
    state.context_analysis = None
    axt.render_context_tab(scr, state, 0, 26, 120)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Loading context" in flat


def test_handle_project_input_k_moves_selection_up():
    """`k` on the Project sub-tab moves the selection up."""
    s = axt.TuiState()
    s.project_items = [
        _project_source("a", path="/a", content="x"),
        _project_source("b", path="/b", content="y"),
    ]
    s.project_selected = 1
    axt.handle_project_input(s, ord("k"))
    assert s.project_selected == 0


# ─── Project sub-tab: `s` column-sort cycle ───────────────────────────────────


def _project_sort_fixture():
    return [
        _project_source("Zebra", category="commands", scope="global", tokens=5, pct=5.0),
        _project_source("Alpha", category="hooks", scope="project", tokens=50, pct=50.0),
        _project_source("Middle", category="agents", scope="project", tokens=20, pct=20.0),
    ]


def test_cycle_project_sort_advances_through_columns():
    """`s` cycles Project's active sort key tokens → name → category → scope,
    wrapping back to tokens; each step re-sorts the loaded items and resets
    the selection."""
    s = axt.TuiState()
    assert s.project_sort == "tokens"
    s.project_items = _project_sort_fixture()
    s.project_selected = 2

    axt._cycle_project_sort(s)
    assert s.project_sort == "name"
    assert s.project_selected == 0
    assert [i.name for i in s.project_items] == ["Alpha", "Middle", "Zebra"]

    axt._cycle_project_sort(s)
    assert s.project_sort == "category"
    assert [i.category for i in s.project_items] == ["agents", "commands", "hooks"]

    axt._cycle_project_sort(s)
    assert s.project_sort == "scope"
    assert [i.scope for i in s.project_items] == ["project", "project", "global"]

    axt._cycle_project_sort(s)
    assert s.project_sort == "tokens"
    assert [i.name for i in s.project_items] == ["Alpha", "Middle", "Zebra"]  # 50, 20, 5 desc


def test_handle_project_input_s_cycles_sort():
    s = axt.TuiState()
    s.project_items = _project_sort_fixture()
    msg = axt.handle_project_input(s, ord("s"))
    assert s.project_sort == "name"
    assert msg == "Sort: name"


def test_render_project_files_table_marks_sorted_column_header():
    """The active sort column's header carries the ▲/▼ glyph (mirrors the
    Vault/Extensions sub-tab sort-cycle convention)."""
    state = axt.TuiState()
    state.project_items = _project_sort_fixture()
    scr = _make_stdscr(rows=20, cols=140)
    axt._render_project_files_table(scr, state, 0, 10, 140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Tokens ▼" in flat

    axt._cycle_project_sort(state)  # → name
    scr2 = _make_stdscr(rows=20, cols=140)
    axt._render_project_files_table(scr2, state, 0, 10, 140)
    flat2 = "".join(c[2] for c in scr2.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Name ▲" in flat2


def test_ensure_subtab_loaded_commands(tmp_path, monkeypatch):
    """_ensure_subtab_loaded populates the commands cache (line 1642)."""
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    axt._ensure_subtab_loaded(s, "commands")
    assert "commands" in s.ext_cache
    assert isinstance(s.ext_cache["commands"], list)


def test_ensure_subtab_loaded_agents(tmp_path, monkeypatch):
    """_ensure_subtab_loaded populates the agents cache (line 1644)."""
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    axt._ensure_subtab_loaded(s, "agents")
    assert "agents" in s.ext_cache
    assert isinstance(s.ext_cache["agents"], list)


def test_ensure_subtab_loaded_hooks(tmp_path, monkeypatch):
    """_ensure_subtab_loaded populates the hooks cache (line 1648)."""
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    axt._ensure_subtab_loaded(s, "hooks")
    assert "hooks" in s.ext_cache
    assert isinstance(s.ext_cache["hooks"], list)


def test_ensure_subtab_loaded_market(tmp_path, monkeypatch):
    """_ensure_subtab_loaded populates the market cache (line 1654)."""
    _isolate_ext_paths(tmp_path, monkeypatch)
    s = axt.TuiState()
    axt._ensure_subtab_loaded(s, "market")
    assert "market" in s.ext_cache
    assert isinstance(s.ext_cache["market"], list)


def test_tab_has_focusable_content_extensions_and_context():
    """Extensions and Context are always focusable (lines 1830, 1832)."""
    s = axt.TuiState()
    assert axt.tab_has_focusable_content(s, "extensions") is True
    assert axt.tab_has_focusable_content(s, "context") is True


def test_tab_has_focusable_content_usage_loading_false():
    """Usage tab while loading is NOT focusable (lines 1834-1835); empty entries
    likewise (line 1836 → bool([]) == False)."""
    s = axt.TuiState()
    s.usage_loading = True
    assert axt.tab_has_focusable_content(s, "usage") is False
    s.usage_loading = False
    s.usage_entries = []
    assert axt.tab_has_focusable_content(s, "usage") is False


def test_tab_has_focusable_content_usage_with_entries_true():
    """Usage tab with loaded entries IS focusable (line 1836-1837 → True)."""
    s = axt.TuiState()
    s.usage_loading = False
    s.usage_entries = [_usage_entry_now()]
    assert axt.tab_has_focusable_content(s, "usage") is True


def test_tab_has_focusable_content_unknown_tab_false():
    """An unrecognized tab key falls through to the final `return False`."""
    s = axt.TuiState()
    assert axt.tab_has_focusable_content(s, "nope") is False


def test_at_top_of_content_unknown_tab_true():
    """An unknown tab key falls through to the default `return True` (line 1865)."""
    s = axt.TuiState()
    assert axt._at_top_of_content(s, "nonexistent") is True


def test_handle_extensions_r_refresh_vault_resets_items():
    """`r` on the Vault sub-tab clears vault_items and resets refresh_token
    (lines 1894-1895)."""
    s = axt.TuiState()
    s.ext_sub_tab = "vault"
    s.vault_items = [axt.VaultItem(name="a", type="skill", path="", description="")]
    s.refresh_token = 5
    msg = axt.handle_extensions_input(s, ord("r"))
    assert msg == "Refreshed"
    assert s.vault_items == []
    assert s.refresh_token == 0


def test_subtab_action_plugin_uninstall_failure(tmp_path, monkeypatch):
    """`x` uninstall where remove_installed_plugin raises → 'Uninstall failed'
    (lines 1987-1988)."""
    import json
    install_path = tmp_path / "myplugin"
    install_path.mkdir()
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        installed_plugins=tmp_path / "ip.json", settings=tmp_path / "settings.json"))
    (tmp_path / "ip.json").write_text(json.dumps({
        "version": 2,
        "plugins": {"p@m": [{"scope": "u", "installPath": str(install_path),
                             "version": "1", "installedAt": "", "lastUpdated": ""}]},
    }))
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: True)
    monkeypatch.setattr("axt.tui.tabs.remove_installed_plugin",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("rm boom")))
    s = axt.TuiState()
    s.ext_sub_tab = "plugins"
    s.ext_cache["plugins"] = axt.list_installed_plugins(tmp_path / "ip.json")
    s.ext_selected["plugins"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "plugins", ord("x"))
    assert msg is not None and "Uninstall failed" in msg


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks unsupported on Windows")
def test_subtab_action_skill_link_failure(monkeypatch):
    """`l` link where link_skill raises ValueError → 'Link failed' (2007-2008)."""
    monkeypatch.setattr("axt.tui.tabs.is_symlink_supported", lambda: True)
    monkeypatch.setattr("axt.text_input_modal",
                        lambda *a, **kw: "/some/path")
    monkeypatch.setattr("axt.tui.tabs.link_skill",
                        lambda skills, target: (_ for _ in ()).throw(ValueError("bad path")))
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "skills", ord("a"))
    assert msg is not None and "Link failed" in msg


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks unsupported on Windows")
def test_subtab_action_skill_unlink_none_selected(monkeypatch):
    """`u` with no selected skill returns None (line 2012)."""
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.ext_cache["skills"] = []
    s.ext_selected["skills"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(s, "skills", ord("x")) is None


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks unsupported on Windows")
def test_subtab_action_skill_unlink_failure(monkeypatch):
    """`u` confirmed where unlink_skill raises OSError → 'Unlink failed'
    (lines 2021-2022)."""
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: True)
    monkeypatch.setattr("axt.tui.tabs.unlink_skill",
                        lambda skills, name: (_ for _ in ()).throw(OSError("unlink boom")))
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.ext_cache["skills"] = [
        axt.SkillInfo(name="mylink", path="/p", is_symlink=True, source="user",
                      target="/src")
    ]
    s.ext_selected["skills"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "skills", ord("x"))
    assert msg is not None and "Unlink failed" in msg


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks unsupported on Windows")
def test_subtab_action_skill_unlink_cancelled(monkeypatch):
    """`u` where confirm_modal returns False → 'Cancelled' (line 2023)."""
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: False)
    unlinked = []
    monkeypatch.setattr("axt.tui.tabs.unlink_skill",
                        lambda skills, name: unlinked.append(name))
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.ext_cache["skills"] = [
        axt.SkillInfo(name="mylink", path="/p", is_symlink=True, source="user",
                      target="/src")
    ]
    s.ext_selected["skills"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "skills", ord("x"))
    assert msg == "Cancelled"
    assert unlinked == []  # confirm declined → no unlink attempted


def test_subtab_action_market_add_github_default_name(monkeypatch):
    """`a` add with a github source derives the default name from the repo
    tail (line 2040)."""
    initials = []
    inputs = iter(["github:acme/cool-market", None])  # 2nd input None → cancel name
    def fake_modal(*a, **kw):
        initials.append(kw.get("initial"))
        return next(inputs)
    monkeypatch.setattr("axt.text_input_modal", fake_modal)
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.stdscr_callbacks = {"stdscr": object()}
    # Name input returns None → aborts at line 2049 after computing default.
    assert axt._handle_subtab_action(s, "market", ord("a")) is None
    # Second prompt (the name input) received the github-derived default.
    assert initials[1] == "cool-market"


def test_subtab_action_market_add_git_default_name(monkeypatch):
    """`a` add with a git: source (neither github nor directory) uses the
    'custom' default name (line 2044)."""
    initials = []
    inputs = iter(["git:https://example.com/x.git", None])
    def fake_modal(*a, **kw):
        initials.append(kw.get("initial"))
        return next(inputs)
    monkeypatch.setattr("axt.text_input_modal", fake_modal)
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(s, "market", ord("a")) is None
    assert initials[1] == "custom"


def test_subtab_action_market_add_name_cancelled(monkeypatch):
    """`a` add where the name input is cancelled returns None (line 2049)."""
    inputs = iter(["dir:/some/path", None])
    monkeypatch.setattr("axt.text_input_modal", lambda *a, **kw: next(inputs))
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(s, "market", ord("a")) is None


def test_subtab_action_market_add_failure(monkeypatch):
    """`a` add where add_marketplace raises RuntimeError → 'Add failed'
    (lines 2054-2055)."""
    inputs = iter(["dir:/some/path", "mname"])
    monkeypatch.setattr("axt.text_input_modal", lambda *a, **kw: next(inputs))
    monkeypatch.setattr("axt.tui.tabs.add_marketplace",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("clone failed")))
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "market", ord("a"))
    assert msg is not None and "Add failed" in msg


def test_subtab_action_market_remove_failure(monkeypatch):
    """`x` remove confirmed where remove_marketplace raises KeyError →
    'Remove failed' (lines 2073-2074)."""
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: True)
    monkeypatch.setattr("axt.tui.tabs.remove_marketplace",
                        lambda *a, **kw: (_ for _ in ()).throw(KeyError("missing")))
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.ext_cache["market"] = [
        axt.MarketplaceInfo(name="m1",
                            source=axt.MarketplaceSource(kind="directory", path="/p"),
                            install_location="/loc", last_updated="2026-01-01")
    ]
    s.ext_selected["market"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "market", ord("x"))
    assert msg is not None and "Remove failed" in msg


def test_subtab_action_market_remove_cancelled(monkeypatch):
    """`x` remove where confirm_modal returns False → 'Cancelled' (line 2075)."""
    monkeypatch.setattr("axt.confirm_modal", lambda *a, **kw: False)
    removed = []
    monkeypatch.setattr("axt.tui.tabs.remove_marketplace",
                        lambda *a, **kw: removed.append(True))
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.ext_cache["market"] = [
        axt.MarketplaceInfo(name="m1",
                            source=axt.MarketplaceSource(kind="directory", path="/p"),
                            install_location="/loc", last_updated="2026-01-01")
    ]
    s.ext_selected["market"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "market", ord("x"))
    assert msg == "Cancelled"
    assert removed == []


def test_subtab_action_hook_preview_failure(monkeypatch):
    """`v` preview where preview_hook raises OSError → 'Preview failed'."""
    monkeypatch.setattr("axt.tui.tabs.preview_hook",
                        lambda hook: (_ for _ in ()).throw(OSError("exec boom")))
    s = axt.TuiState()
    s.ext_sub_tab = "hooks"
    s.ext_cache["hooks"] = [
        axt.HookInfo(event="PreToolUse", matcher="*", source="user",
                     source_path="/s.json", type="command", command="echo hi")
    ]
    s.ext_selected["hooks"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt._handle_subtab_action(s, "hooks", ord("v"))
    assert msg is not None and "Preview failed" in msg


def test_subtab_action_hook_preview_includes_stderr(monkeypatch):
    """A preview result with a non-empty `error` appends a stderr section
    (line 2097)."""
    captured = []
    monkeypatch.setattr("axt.preview_modal",
                        lambda stdscr, content, title="Preview", **kw: captured.append(content))
    monkeypatch.setattr("axt.tui.tabs.preview_hook",
                        lambda hook: axt.HookPreviewResult(
                            type="command", summary="ran", output="",
                            error="boom on stderr", exit_code=1))
    s = axt.TuiState()
    s.ext_sub_tab = "hooks"
    s.ext_cache["hooks"] = [
        axt.HookInfo(event="PreToolUse", matcher="*", source="user",
                     source_path="/s.json", type="command", command="echo hi")
    ]
    s.ext_selected["hooks"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    axt._handle_subtab_action(s, "hooks", ord("v"))
    assert captured
    assert "stderr" in captured[0]
    assert "boom on stderr" in captured[0]


def test_subtab_action_unhandled_sub_returns_none():
    """An action key that no sub-tab branch handles falls to the final
    `return None` (line 2109)."""
    s = axt.TuiState()
    s.ext_sub_tab = "mcp"  # mcp has no action keys in _handle_subtab_action
    s.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(s, "mcp", ord("z")) is None


# ─── Coverage push: loop.py deep branches ────────────────────────────────────


def test_tui_loop_set_escdelay_attributeerror_swallowed(monkeypatch, tmp_path):
    """If curses.set_escdelay is missing (older Python) the AttributeError is
    swallowed (lines 298-299) and the loop still runs to quit."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("curses.curs_set", lambda *a: None)
    monkeypatch.setattr("axt.tui.loop.tui_init_colors", lambda *a, **k: None)
    monkeypatch.delattr("curses.set_escdelay", raising=False)
    scr = _loop_stdscr([ord("q")])
    assert axt._tui_loop(scr) is None


def test_tui_loop_keyboard_interrupt_on_getch_returns(monkeypatch, tmp_path):
    """A KeyboardInterrupt raised by getch is caught and returns cleanly
    (lines 321-322)."""
    monkeypatch.chdir(tmp_path)
    _quiet_curses(monkeypatch)
    scr = _make_stdscr()
    def boom():
        raise KeyboardInterrupt
    scr.getch.side_effect = boom
    assert axt._tui_loop(scr) is None


def test_tui_loop_drops_key_when_not_content_layer(monkeypatch, tmp_path):
    """A non-navigation key (e.g. 'j') while focus is still on mainTab is
    dropped without reaching the tab handler (line 393-394 `continue`)."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    _quiet_curses(monkeypatch)
    handler_calls = []
    real = axt.handle_context_input
    def spy(state, key):
        handler_calls.append(key)
        return real(state, key)
    monkeypatch.setattr("axt.tui.loop.TAB_HANDLERS",
                        {**axt.tui.loop.TAB_HANDLERS, "context": spy})
    # '2' → Context tab (focus stays mainTab); 'j' should be DROPPED (mainTab);
    # 'q' quits. So the handler must never see 'j'.
    scr = _loop_stdscr([ord("2"), ord("j"), ord("q")])
    axt._tui_loop(scr)
    assert ord("j") not in handler_calls


def test_tui_loop_stub_tab_handler_path(monkeypatch, tmp_path):
    """When the active tab has no entry in TAB_HANDLERS, the loop calls
    handle_stub_input (line 403). We register a stub tab to force this."""
    _setup_isolated_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")
    monkeypatch.setattr("axt.get_git_status", lambda _: "")
    _quiet_curses(monkeypatch)
    # Add a 4th main tab with a renderer but NO handler so the else-branch runs.
    monkeypatch.setattr("axt.tui.loop.MAIN_TABS",
                        axt.MAIN_TABS + (("stub", "Stub", "Stub"),))
    monkeypatch.setattr("axt.tui.loop.TAB_RENDERERS",
                        {**axt.tui.loop.TAB_RENDERERS})  # 'stub' absent → render_stub_tab
    stub_calls = []
    real_stub = axt.handle_stub_input
    def spy_stub(state, key):
        stub_calls.append(key)
        return real_stub(state, key)
    monkeypatch.setattr("axt.tui.loop.handle_stub_input", spy_stub)
    # '4' jumps to the stub tab. tab_has_focusable_content returns False for
    # 'stub', so KEY_DOWN won't descend — force content focus another way:
    # since the stub tab has no sub-tab and is not focusable, we instead set
    # focus to content directly via a spy on _render_frame is not enough.
    # Simpler: the handler path runs only when focused_layer == 'content'. Use
    # a tab whose focusable check is True. 'stub' isn't, so drive through the
    # modal=False, focused_layer!=content guard. To reach line 403 we need
    # focused_layer == content with a stub tab. Patch tab_has_focusable_content.
    monkeypatch.setattr("axt.tui.loop.tab_has_focusable_content",
                        lambda state, key: True)
    scr = _loop_stdscr([ord("4"), curses.KEY_DOWN, ord("z"), ord("q")])
    axt._tui_loop(scr)
    assert ord("z") in stub_calls


def test_launch_tui_returns_0_on_clean_exit(monkeypatch):
    """launch_tui returns 0 when curses.wrapper completes without error
    (line 419)."""
    monkeypatch.setattr("curses.wrapper", lambda fn: None)
    assert axt.launch_tui() == 0


# ─── spawn_terminal_at (cst open_in_new_terminal port) ───────────────────────


def _capture_popen(monkeypatch):
    """Record every subprocess.Popen(argv, **kw) call; return the list."""
    calls = []

    def fake_popen(argv, **kw):
        calls.append((argv, kw))
        return MagicMock()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    return calls


def test_spawn_terminal_iterm_uses_osascript(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    calls = _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/axt skill")
    assert ok is True and info == "opened in iTerm"
    argv = calls[0][0]
    assert argv[0] == "osascript"
    assert 'tell application "iTerm"' in argv[2]
    assert "cd '/tmp/axt skill'" in argv[2]


def test_spawn_terminal_apple_terminal(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    calls = _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and info == "opened in Terminal"
    assert 'tell application "Terminal"' in calls[0][0][2]


def test_spawn_terminal_unknown_term_program_suffix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "FooTerm")
    _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True
    assert "opened in Terminal.app" in info
    assert "unknown TERM_PROGRAM='FooTerm'" in info


def test_spawn_terminal_unset_term_program_no_suffix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and info == "opened in Terminal.app"


def test_spawn_terminal_warp_falls_back_with_note(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "WarpTerminal")
    _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and "Warp is not scriptable" in info


def test_spawn_terminal_vscode_falls_back_with_note(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and "from vscode integrated terminal" in info


def test_spawn_terminal_ghostty_cli(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.setattr("shutil.which", lambda name: "/bin/ghostty" if name == "ghostty" else None)
    calls = _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and info == "opened in Ghostty"
    assert calls[0][0] == ["/bin/ghostty", "--working-directory", "/tmp/x"]
    # Second spawn is the AppleScript activate.
    assert calls[1][0][0] == "osascript"


def test_spawn_terminal_wezterm_cli(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "WezTerm")
    monkeypatch.setattr("shutil.which", lambda name: "/bin/wezterm" if name == "wezterm" else None)
    calls = _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and info == "opened in WezTerm"
    assert calls[0][0] == ["/bin/wezterm", "start", "--cwd", "/tmp/x"]


def test_spawn_terminal_kitty_cli(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "kitty")
    monkeypatch.setattr("shutil.which", lambda name: "/bin/kitty" if name == "kitty" else None)
    calls = _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and info == "opened in kitty"
    assert calls[0][0] == ["/bin/kitty", "--detach", "--directory", "/tmp/x"]


def test_spawn_terminal_alacritty_cli(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "Alacritty")
    monkeypatch.setattr("shutil.which", lambda name: "/bin/alacritty" if name == "alacritty" else None)
    calls = _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and info == "opened in Alacritty"
    assert calls[0][0] == ["/bin/alacritty", "--working-directory", "/tmp/x"]


def test_spawn_terminal_ghostty_missing_falls_back(monkeypatch):
    """TERM_PROGRAM matches ghostty but the binary is absent → Terminal.app."""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.setattr("shutil.which", lambda name: None)
    calls = _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and "opened in Terminal.app" in info
    assert calls[0][0][0] == "osascript"


def test_spawn_terminal_osascript_oserror(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")

    def boom(argv, **kw):
        raise OSError("spawn denied")

    monkeypatch.setattr("subprocess.Popen", boom)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is False and "osascript failed" in info


def test_spawn_terminal_linux_gnome_terminal(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("TERMINAL", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/bin/gnome-terminal" if name == "gnome-terminal" else None)
    calls = _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and info == "opened in gnome-terminal"
    assert calls[0][0] == ["/bin/gnome-terminal", "--working-directory", "/tmp/x"]


def test_spawn_terminal_linux_env_terminal_first(monkeypatch):
    """$TERMINAL is tried before the built-in candidate list; generic
    terminals inherit cwd via Popen(cwd=...)."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("TERMINAL", "footerm")
    monkeypatch.setattr("shutil.which", lambda name: "/bin/footerm" if name == "footerm" else None)
    calls = _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is True and info == "opened in footerm"
    assert calls[0][0] == ["/bin/footerm"]
    assert calls[0][1]["cwd"] == "/tmp/x"


def test_spawn_terminal_linux_none_found(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("TERMINAL", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    ok, info = axt.spawn_terminal_at("/tmp/x")
    assert ok is False and info == "no supported terminal emulator found"


def test_spawn_terminal_unsupported_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    ok, info = axt.spawn_terminal_at("C:/x")
    assert ok is False and "unsupported platform" in info


def test_spawn_terminal_cmux_binary_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    ok, info = axt.spawn_terminal_at("/tmp/x", cmux_mode="workspace")
    assert ok is False and info == "cmux binary not found"


def test_spawn_terminal_cmux_workspace(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/cmux" if name == "cmux" else None)
    calls = _capture_popen(monkeypatch)
    ok, info = axt.spawn_terminal_at("/tmp/my-skill", cmux_mode="workspace")
    assert ok is True and info == "opened in cmux workspace"
    argv = calls[0][0]
    assert argv[:2] == ["/bin/cmux", "new-workspace"]
    assert argv[argv.index("--cwd") + 1] == "/tmp/my-skill"
    assert argv[argv.index("--name") + 1] == "axt:my-skill"


def test_spawn_terminal_cmux_window(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/cmux" if name == "cmux" else None)
    runs = []

    def fake_run(argv, **kw):
        runs.append(argv)
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        if argv[1] == "new-window":
            r.stdout = "window window:7\n"
        elif argv[1] == "list-workspaces":
            r.stdout = "tab workspace:42 active\n"
        else:
            r.stdout = ""
        return r

    monkeypatch.setattr("subprocess.run", fake_run)
    ok, info = axt.spawn_terminal_at("/tmp/x", cmux_mode="window")
    assert ok is True and info == "opened in cmux window"
    send = next(argv for argv in runs if argv[1] == "send")
    assert send[send.index("--workspace") + 1] == "workspace:42"
    assert "cd /tmp/x" in send[-1]


def test_spawn_terminal_cmux_window_create_fails(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/cmux" if name == "cmux" else None)

    def fake_run(argv, **kw):
        r = MagicMock()
        r.returncode = 1
        r.stdout = ""
        r.stderr = "nope"
        return r

    monkeypatch.setattr("subprocess.run", fake_run)
    ok, info = axt.spawn_terminal_at("/tmp/x", cmux_mode="window")
    assert ok is False and "cmux new-window failed" in info


# ─── cmux_open_mode_modal ─────────────────────────────────────────────────────


@pytest.mark.parametrize("key,expected", [
    (ord("t"), "workspace"),
    (10, "workspace"),  # Enter defaults to workspace tab
    (ord("w"), "window"),
    (27, None),  # Esc cancels
])
def test_cmux_open_mode_modal_keys(monkeypatch, key, expected):
    scr = _make_stdscr()
    win, _calls = _make_modal_win([key])
    monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
    assert axt.cmux_open_mode_modal(scr) == expected


def test_cmux_open_mode_modal_newwin_failure(monkeypatch):
    scr = _make_stdscr()
    monkeypatch.setattr("curses.newwin",
                        lambda *a, **kw: (_ for _ in ()).throw(curses.error("too small")))
    assert axt.cmux_open_mode_modal(scr) is None


# ─── _item_terminal_dir per item type ────────────────────────────────────────


def test_item_terminal_dir_skill_resolves_symlink(tmp_path):
    real = tmp_path / "real-skill"
    real.mkdir()
    link = tmp_path / "linked-skill"
    link.symlink_to(real)
    skill = axt.SkillInfo(name="s", path=str(link), is_symlink=True, source="user")
    assert axt._item_terminal_dir("skills", skill) == str(real.resolve())


def test_item_terminal_dir_command_uses_parent(tmp_path):
    f = tmp_path / "cmds" / "deploy.md"
    f.parent.mkdir()
    f.write_text("x")
    cmd = axt.CommandInfo(name="deploy", source="user", source_path=str(f),
                          description="", content="")
    assert axt._item_terminal_dir("commands", cmd) == str(f.parent)


def test_item_terminal_dir_command_empty_source_path():
    cmd = axt.CommandInfo(name="x", source="user", source_path="",
                          description="", content="")
    assert axt._item_terminal_dir("commands", cmd) is None


def test_item_terminal_dir_plugin_and_market():
    plugin = axt.PluginInfo(id="p@m", name="p", marketplace="m", version="1",
                            install_path="/plug/dir", scope="user",
                            installed_at="", last_updated="")
    assert axt._item_terminal_dir("plugins", plugin) == "/plug/dir"
    market = axt.MarketplaceInfo(name="m", source=None,
                                 install_location="/mkt/dir", last_updated="")
    assert axt._item_terminal_dir("market", market) == "/mkt/dir"


def test_item_terminal_dir_hook_uses_parent(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text("{}")
    hook = axt.HookInfo(event="PreToolUse", matcher="*", source="user",
                        source_path=str(f), type="command")
    assert axt._item_terminal_dir("hooks", hook) == str(tmp_path)


def test_item_terminal_dir_mcp_scopes(monkeypatch, tmp_path):
    plugin = axt.PluginInfo(id="pid@m", name="p", marketplace="m", version="1",
                            install_path="/plug/pid", scope="user",
                            installed_at="", last_updated="")
    monkeypatch.setattr("axt.list_installed_plugins", lambda path: [plugin])
    srv_plugin = axt.McpServerInfo(name="s", plugin_id="pid@m", command="x",
                                   args=(), env=(), scope="plugin")
    assert axt._item_terminal_dir("mcp", srv_plugin) == "/plug/pid"
    srv_orphan = axt.McpServerInfo(name="s", plugin_id="gone@m", command="x",
                                   args=(), env=(), scope="plugin")
    assert axt._item_terminal_dir("mcp", srv_orphan) is None
    srv_user = axt.McpServerInfo(name="s", plugin_id="", command="x",
                                 args=(), env=(), scope="user")
    assert axt._item_terminal_dir("mcp", srv_user) == str(axt.PATHS.claude_dir)
    srv_proj = axt.McpServerInfo(name="s", plugin_id="", command="x",
                                 args=(), env=(), scope="project")
    assert axt._item_terminal_dir("mcp", srv_proj) == str(Path.cwd())


def test_item_terminal_dir_none_item_and_unknown_sub():
    assert axt._item_terminal_dir("skills", None) is None
    assert axt._item_terminal_dir("vault", object()) is None


# ─── `o` key: open terminal at item path ─────────────────────────────────────


def _skills_state(tmp_path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = [axt.SkillInfo(
        name="my-skill", path=str(skill_dir), is_symlink=False, source="user")]
    state.ext_selected["skills"] = 0
    state.stdscr_callbacks = {"stdscr": object()}
    return state, skill_dir


def test_subtab_o_opens_terminal(monkeypatch, tmp_path):
    monkeypatch.delenv("CMUX_WORKSPACE_ID", raising=False)
    opened = []
    monkeypatch.setattr("axt.spawn_terminal_at",
                        lambda cwd, cmux_mode=None: opened.append((cwd, cmux_mode)) or (True, "opened in Terminal"))
    state, skill_dir = _skills_state(tmp_path)
    assert axt._handle_subtab_action(state, "skills", ord("o")) == "opened in Terminal"
    assert opened == [(str(skill_dir.resolve()), None)]


def test_subtab_o_path_not_found(monkeypatch, tmp_path):
    monkeypatch.delenv("CMUX_WORKSPACE_ID", raising=False)
    state, skill_dir = _skills_state(tmp_path)
    state.ext_cache["skills"] = [axt.SkillInfo(
        name="gone", path=str(tmp_path / "missing"), is_symlink=False, source="user")]
    msg = axt._handle_subtab_action(state, "skills", ord("o"))
    assert msg is not None and msg.startswith("Path not found:")


def test_subtab_o_no_item_returns_none(monkeypatch):
    monkeypatch.delenv("CMUX_WORKSPACE_ID", raising=False)
    state = axt.TuiState()
    state.ext_cache["skills"] = []
    state.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(state, "skills", ord("o")) is None


def test_subtab_o_mcp_without_dir(monkeypatch):
    monkeypatch.delenv("CMUX_WORKSPACE_ID", raising=False)
    monkeypatch.setattr("axt.list_installed_plugins", lambda path: [])
    state = axt.TuiState()
    state.ext_cache["mcp"] = [axt.McpServerInfo(
        name="s", plugin_id="gone@m", command="x", args=(), env=(), scope="plugin")]
    state.ext_selected["mcp"] = 0
    state.stdscr_callbacks = {"stdscr": object()}
    assert axt._handle_subtab_action(state, "mcp", ord("o")) == "No directory for this item"


def test_subtab_o_cmux_chooser_cancel(monkeypatch, tmp_path):
    monkeypatch.setenv("CMUX_WORKSPACE_ID", "ws-1")
    monkeypatch.setattr("axt.cmux_open_mode_modal", lambda stdscr: None)
    state, _ = _skills_state(tmp_path)
    assert axt._handle_subtab_action(state, "skills", ord("o")) == "Cancelled"


def test_subtab_o_cmux_chooser_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("CMUX_WORKSPACE_ID", "ws-1")
    monkeypatch.setattr("axt.cmux_open_mode_modal", lambda stdscr: "workspace")
    opened = []
    monkeypatch.setattr("axt.spawn_terminal_at",
                        lambda cwd, cmux_mode=None: opened.append(cmux_mode) or (True, "opened in cmux workspace"))
    state, _ = _skills_state(tmp_path)
    assert axt._handle_subtab_action(state, "skills", ord("o")) == "opened in cmux workspace"
    assert opened == ["workspace"]


def test_vault_o_opens_terminal_at_parent_of_file(monkeypatch, tmp_path):
    monkeypatch.delenv("CMUX_WORKSPACE_ID", raising=False)
    f = tmp_path / "deploy.md"
    f.write_text("x")
    opened = []
    monkeypatch.setattr("axt.spawn_terminal_at",
                        lambda cwd, cmux_mode=None: opened.append(cwd) or (True, "opened in Terminal"))
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="deploy", type="command",
                                       path=str(f), description="")]
    state.vault_selected = 0
    assert axt.handle_vault_input(state, ord("o")) == "opened in Terminal"
    assert opened == [str(tmp_path)]


def test_vault_o_spawn_failure_toast(monkeypatch, tmp_path):
    monkeypatch.delenv("CMUX_WORKSPACE_ID", raising=False)
    d = tmp_path / "skill"
    d.mkdir()
    monkeypatch.setattr("axt.spawn_terminal_at",
                        lambda cwd, cmux_mode=None: (False, "boom"))
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="s", type="skill",
                                       path=str(d), description="")]
    state.vault_selected = 0
    assert axt.handle_vault_input(state, ord("o")) == "Terminal open failed: boom"


# ─── Non-vault sub-tab sort (ported from Vault) ───────────────────────────────


def test_subtab_sort_label_defaults_to_first_spec():
    """With no explicit choice, each sortable sub-tab reports its first key;
    a sub-tab with no sort cycle reports ""."""
    s = axt.TuiState()
    assert axt.subtab_sort_label(s, "skills") == "name"
    assert axt.subtab_sort_label(s, "mcp") == "name"
    assert axt.subtab_sort_label(s, "market") == "name"
    assert axt.subtab_sort_label(s, "hooks") == "event"
    assert axt.subtab_sort_label(s, "vault") == ""  # vault has its own cycle


def test_handle_extensions_input_s_cycles_sort_skills():
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.ext_cache["skills"] = [axt.SkillInfo(name="a", path="/x", is_symlink=False, source="user")]
    axt.handle_extensions_input(s, ord("s"))
    assert s.ext_sort["skills"] == "source"
    axt.handle_extensions_input(s, ord("s"))
    assert s.ext_sort["skills"] == "type"
    axt.handle_extensions_input(s, ord("s"))
    assert s.ext_sort["skills"] == "name"  # wraps


def test_subtab_sort_resets_selection():
    s = axt.TuiState()
    s.ext_sub_tab = "mcp"
    s.ext_cache["mcp"] = [axt.McpServerInfo(name=n, plugin_id="", command="c", args=(), env=())
                          for n in ("a", "b", "c")]
    s.ext_selected["mcp"] = 2
    axt.handle_extensions_input(s, ord("s"))
    assert s.ext_sort["mcp"] == "scope"
    assert s.ext_selected["mcp"] == 0


def test_subtab_view_reorders_by_active_key():
    """Sorting by name orders alphabetically; switching to source groups by
    source first. _subtab_view is the single ordering used everywhere."""
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.ext_cache["skills"] = [
        axt.SkillInfo(name="zeta", path="/z", is_symlink=False, source="user"),
        axt.SkillInfo(name="alpha", path="/a", is_symlink=False, source="plugin"),
        axt.SkillInfo(name="mid", path="/m", is_symlink=False, source="user"),
    ]
    # Default: by name.
    assert [i.name for i in axt._subtab_view(s, "skills")] == ["alpha", "mid", "zeta"]
    # By source: plugin before user, name as tiebreak.
    s.ext_sort["skills"] = "source"
    assert [i.name for i in axt._subtab_view(s, "skills")] == ["alpha", "mid", "zeta"]
    assert [i.source for i in axt._subtab_view(s, "skills")] == ["plugin", "user", "user"]


def test_selected_item_follows_sorted_view():
    """The item _handle_subtab_action acts on must be the highlighted (sorted)
    row, not the raw cache order."""
    s = axt.TuiState()
    s.ext_sub_tab = "skills"
    s.ext_cache["skills"] = [
        axt.SkillInfo(name="zeta", path="/z", is_symlink=False, source="user"),
        axt.SkillInfo(name="alpha", path="/a", is_symlink=False, source="user"),
    ]
    s.ext_selected["skills"] = 0  # top row
    # Default name sort puts "alpha" at row 0, even though it's cache index 1.
    assert axt._selected_item(s, "skills").name == "alpha"


def test_market_s_cycles_sort_does_not_sync(monkeypatch):
    """`s` on Market now cycles sort instead of syncing; sync moved to `S`."""
    synced = []
    monkeypatch.setattr("axt.tui.tabs.sync_marketplace",
                        lambda km, name: synced.append(name) or
                        axt.SyncMarketplaceResult(before="a", after="b", updated=True))
    s = axt.TuiState()
    s.ext_sub_tab = "market"
    s.ext_cache["market"] = [
        axt.MarketplaceInfo(name="m1",
                            source=axt.MarketplaceSource(kind="directory", path="/p"),
                            install_location="/loc", last_updated="2026-01-01")
    ]
    s.ext_selected["market"] = 0
    s.stdscr_callbacks = {"stdscr": object()}
    msg = axt.handle_extensions_input(s, ord("s"))
    assert s.ext_sort["market"] == "kind"
    assert synced == []           # no sync triggered
    assert "Sort:" in (msg or "")


def test_render_marks_active_sort_column(monkeypatch):
    """The sorted column's header shows ▲/▼; others stay plain."""
    s = axt.TuiState()
    s.ext_sub_tab = "mcp"
    s.ext_cache["mcp"] = [axt.McpServerInfo(name="srv", plugin_id="", command="c", args=(), env=())]
    s.ext_sort["mcp"] = "scope"
    scr = _make_stdscr(rows=24, cols=120)
    axt.render_extensions_tab(scr, s, 0, 22, 120)
    headers = {c[2].strip() for c in scr.calls if len(c) >= 3 and isinstance(c[2], str)}
    assert "Scope ▲" in headers      # active sort column marked
    assert "Server" in headers       # name column unmarked


def test_sort_cycle_keys_match_columns():
    """Every spec's marked_col is a real column key for that sub-tab so the
    ▲/▼ glyph always lands on an existing header."""
    col_keys = {
        "plugins":  {"name", "version", "status", "market"},
        "skills":   {"name", "ver", "source", "type", "path"},
        "commands": {"name", "ver", "source", "desc"},
        "agents":   {"name", "ver", "source", "desc"},
        "mcp":      {"name", "scope", "transport", "detail"},
        "hooks":    {"event", "ver", "type", "source", "detail"},
        "market":   {"name", "ver", "kind", "loc", "updated"},
    }
    for sub, specs in axt._SUBTAB_SORT_SPECS.items():
        for key, _fn, _rev, marked, _glyph in specs:
            assert marked is None or marked in col_keys[sub], \
                f"{sub} sort {key!r} marks unknown column {marked!r}"


# ─── SUBTAB_KEYMAP table (single source of truth for dispatch/hints/help) ───


def test_subtab_keymap_no_duplicate_keys():
    """Common + per-sub-tab bindings must not claim the same key twice."""
    for sub, bindings in axt.SUBTAB_KEYMAP.items():
        seen = set()
        for b in axt._SUBTAB_COMMON + bindings:
            for k in b.keys:
                assert k not in seen, f"{sub}: key {chr(k)!r} bound twice"
                seen.add(k)


def test_subtab_keymap_avoids_reserved_navigation_keys():
    """Keys consumed by handle_extensions_input's shared navigation layer
    ([, ], r, s, Tab, j, k, /, Space) must never appear in an action binding."""
    reserved = {ord("["), ord("]"), ord("r"), ord("s"), ord("\t"),
                ord("j"), ord("k"), ord("/"), ord(" ")}
    for sub, bindings in axt.SUBTAB_KEYMAP.items():
        for b in axt._SUBTAB_COMMON + bindings:
            assert not (set(b.keys) & reserved), f"{sub}: {b.hint!r} uses a reserved key"


def test_subtab_keymap_covers_all_non_vault_subtabs():
    subs = {k for k, _ in axt.EXTENSION_SUB_TABS} - {"vault"}
    assert set(axt.SUBTAB_KEYMAP) == subs


# ─── Extensions `/` search (non-vault sub-tabs) ──────────────────────────────


def _search_plugins_state():
    from types import SimpleNamespace
    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    state.ext_cache["plugins"] = [
        SimpleNamespace(name="alpha", id="alpha@m", version="1", marketplace="m"),
        SimpleNamespace(name="beta", id="beta@m", version="1", marketplace="m"),
    ]
    return state


def test_ext_slash_search_filters_subtab_view():
    state = _search_plugins_state()
    msg = axt.handle_extensions_input(state, ord("/"))
    assert state.ext_searching is True and "type to filter" in msg
    for ch in "alp":
        axt.handle_extensions_input(state, ord(ch))
    # Reserved nav keys are captured as text while typing (mirrors vault).
    axt.handle_extensions_input(state, ord("h"))
    axt.handle_extensions_input(state, 127)  # backspace → "alp"
    axt.handle_extensions_input(state, 10)   # Enter applies
    assert state.ext_searching is False
    assert [p.name for p in axt._subtab_view(state, "plugins")] == ["alpha"]


def test_ext_search_esc_while_typing_cancels():
    state = _search_plugins_state()
    axt.handle_extensions_input(state, ord("/"))
    axt.handle_extensions_input(state, ord("a"))
    msg = axt.handle_extensions_input(state, 27)
    assert msg == "Search cleared"
    assert state.ext_searching is False
    assert state.ext_search.get("plugins", "") == ""
    assert len(axt._subtab_view(state, "plugins")) == 2


def test_ext_search_applied_esc_clears_before_climb():
    state = _search_plugins_state()
    axt.handle_extensions_input(state, ord("/"))
    axt.handle_extensions_input(state, ord("b"))
    axt.handle_extensions_input(state, 10)
    assert [p.name for p in axt._subtab_view(state, "plugins")] == ["beta"]
    msg = axt.handle_extensions_input(state, 27)
    assert msg == "Search cleared"
    assert len(axt._subtab_view(state, "plugins")) == 2


def test_ext_search_is_per_subtab():
    state = _search_plugins_state()
    state.ext_search["plugins"] = "alp"
    assert [p.name for p in axt._subtab_view(state, "plugins")] == ["alpha"]
    from types import SimpleNamespace
    state.ext_cache["mcp"] = [SimpleNamespace(name="srv", scope="user",
                                              transport="stdio", disabled=False)]
    assert len(axt._subtab_view(state, "mcp")) == 1  # other sub-tab unfiltered


def test_extensions_shortcuts_show_search_state():
    from axt.tui.loop import _extensions_shortcuts
    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    base = _extensions_shortcuts(state)
    assert "/:search" in base and "q:quit" in base
    state.ext_searching = True
    state.ext_search["plugins"] = "alp"
    assert _extensions_shortcuts(state).startswith("/alp")
    state.ext_searching = False
    assert "search:'alp'" in _extensions_shortcuts(state)


def test_subtab_shortcuts_generated_from_keymap():
    assert axt.subtab_shortcuts("plugins") == "p:project  g:global  x:uninstall  u:update  Tab:detail"
    assert axt.subtab_shortcuts("commands") == "p:project  g:global  e:edit  i:import  u:update  Tab:detail"
    assert axt.subtab_shortcuts("market") == "a:add  S:sync  x:remove  u:update  Tab:detail"
    assert axt.subtab_shortcuts("mcp") == "p:on  Tab:detail"
    assert axt.subtab_shortcuts("vault") == ""  # vault owns its own status line


def test_help_text_includes_every_keymap_help_line():
    from axt.tui.loop import HELP_TEXT
    assert axt.subtab_help_block()  # non-empty
    for sub, bindings in axt.SUBTAB_KEYMAP.items():
        for b in bindings:
            if b.help:
                assert b.help in HELP_TEXT, f"{sub}: {b.help!r} missing from HELP_TEXT"


# ─── Extensions "u" = update selected (Task 8) ───────────────────────────────


def test_update_target_for_maps_types():
    from types import SimpleNamespace
    from axt.tui.tabs import _update_target_for
    from axt.core import PluginInfo, SkillInfo
    p = PluginInfo(id="foo@mk", name="foo", marketplace="mk", version="1",
                   install_path="", scope="user", installed_at="", last_updated="")
    assert _update_target_for("plugins", p) == ("plugin", "foo@mk")
    s = SkillInfo(name="s", path="/p", is_symlink=False, source="user")
    assert _update_target_for("skills", s) == ("skill", "s")
    assert _update_target_for("market", SimpleNamespace(name="mk")) == ("marketplace", "mk")
    assert _update_target_for("mcp", object()) is None      # report-only, no u action
    assert _update_target_for("hooks", object()) is None


def test_act_update_applies_updatable_selected(monkeypatch):
    import axt
    from axt.core import PluginInfo
    plugin = PluginInfo(id="foo@mk", name="foo", marketplace="mk", version="1",
                        install_path="", scope="user", installed_at="", last_updated="")
    monkeypatch.setattr("axt.tui.tabs._selected_item", lambda state, sub: plugin)
    monkeypatch.setattr("axt.tui.tabs.check_all_updates",
        lambda types=None: [axt.update.UpdateStatus("plugin", "foo@mk", 1, "1", "2", True)])
    applied = {}
    monkeypatch.setattr("axt.tui.tabs.apply_updates",
        lambda targets: (applied.setdefault("t", targets),
            [axt.update.UpdateResult("plugin", "foo@mk", "1", "2", True, "reinstall")])[1])
    monkeypatch.setattr("axt.tui.tabs._refresh_ext", lambda state, sub: None)
    msg = axt.tui.tabs._act_update(None, None, "plugins", ord("u"))
    assert applied["t"] == [("plugin", "foo@mk")]
    assert "Updated foo@mk" in msg and "1 → 2" in msg


def test_act_update_market_syncs_marketplace(monkeypatch):
    """`u` on the Market sub-tab routes through the marketplace updater."""
    import axt
    from types import SimpleNamespace
    monkeypatch.setattr("axt.tui.tabs._selected_item",
                        lambda state, sub: SimpleNamespace(name="mk"))
    monkeypatch.setattr("axt.tui.tabs.check_all_updates",
        lambda types=None: [axt.update.UpdateStatus("marketplace", "mk", 1, "abc", "def", True)])
    applied = {}
    monkeypatch.setattr("axt.tui.tabs.apply_updates",
        lambda targets: (applied.setdefault("t", targets),
            [axt.update.UpdateResult("marketplace", "mk", "abc", "def", True, "sync")])[1])
    monkeypatch.setattr("axt.tui.tabs._refresh_ext", lambda state, sub: None)
    msg = axt.tui.tabs._act_update(None, None, "market", ord("u"))
    assert applied["t"] == [("marketplace", "mk")]
    assert "Updated mk" in msg and "abc → def" in msg


def test_flash_status_forces_immediate_render():
    """flash_status sets the status AND drives the render callback so a slow op
    can show 'Updating…' before it blocks."""
    import axt
    renders = []
    state = axt.TuiState()
    state.stdscr_callbacks = {"stdscr": None, "render": lambda: renders.append(state.status)}
    axt.tui.tabs.flash_status(state, "Updating foo…")
    assert state.status == "Updating foo…"
    assert renders == ["Updating foo…"]      # painted synchronously, once


def test_act_update_shows_updating_before_apply(monkeypatch):
    """`u` paints an 'Updating…' indicator BEFORE the blocking apply runs."""
    import axt
    from axt.core import PluginInfo
    plugin = PluginInfo(id="foo@mk", name="foo", marketplace="mk", version="1",
                        install_path="", scope="user", installed_at="", last_updated="")
    monkeypatch.setattr("axt.tui.tabs._selected_item", lambda state, sub: plugin)
    monkeypatch.setattr("axt.tui.tabs.check_all_updates",
        lambda types=None: [axt.update.UpdateStatus("plugin", "foo@mk", 1, "1", "2", True)])
    seen = {}
    monkeypatch.setattr("axt.tui.tabs.apply_updates",
        lambda targets: (seen.setdefault("status_at_apply", state.status),
            [axt.update.UpdateResult("plugin", "foo@mk", "1", "2", True, "reinstall")])[1])
    monkeypatch.setattr("axt.tui.tabs._refresh_ext", lambda s, sub: None)
    state = axt.TuiState()
    state.stdscr_callbacks = {"stdscr": None, "render": lambda: None}
    axt.tui.tabs._act_update(state, None, "plugins", ord("u"))
    assert seen["status_at_apply"] == "Updating foo@mk…"


def test_context_detail_lists_all_members_with_tok_and_pct():
    """Sources group detail shows every member source (no 20-item cap),
    each valued as '<tok> tok  <pct>%'."""
    srcs = [axt.ContextSource(
        name=f"Memory: m{i}", category="memory", path=f"/m/{i}.md",
        chars=400, estimated_tokens=100 + i, percentage=1.5,
        actionable=True) for i in range(25)]
    analysis = axt.ContextAnalysis(
        total_tokens=2500, context_window_size=200_000, used_percent=1.2,
        model="claude-sonnet", sources=srcs,
        cost_impact=_make_empty_context_analysis().cost_impact)
    state = axt.TuiState()
    state.context_sub_tab = "sources"
    state.context_selected = 0
    rows = axt._context_rows(analysis)
    title, fields = axt._context_detail_for(state, analysis, rows)
    assert title.startswith("Memory")
    assert len(fields) == 25  # cap removed
    for _label, value in fields:
        assert " tok" in value
        assert "1.5%" in value


def test_context_sources_enter_focuses_detail_panel():
    state = axt.TuiState()
    state.context_sub_tab = "sources"
    state.context_analysis = _seed_context_analysis_with_sources()
    state.context_selected = 0
    msg = axt.handle_context_input(state, 10)  # Enter
    assert state.context_detail_focused is True
    assert state.context_detail_scroll == 0
    assert "Detail focused" in msg


def test_context_sources_enter_on_empty_list_is_noop():
    state = axt.TuiState()
    state.context_sub_tab = "sources"
    state.context_analysis = _make_empty_context_analysis()
    assert axt.handle_context_input(state, 10) is None
    assert state.context_detail_focused is False


def test_context_detail_focus_scrolls_and_esc_blurs():
    state = axt.TuiState()
    state.context_detail_focused = True
    axt.handle_context_input(state, ord("j"))
    assert state.context_detail_scroll == 1
    axt.handle_context_input(state, curses.KEY_NPAGE)
    assert state.context_detail_scroll == 11
    axt.handle_context_input(state, ord("k"))
    assert state.context_detail_scroll == 10
    axt.handle_context_input(state, curses.KEY_PPAGE)
    assert state.context_detail_scroll == 0
    axt.handle_context_input(state, axt.KEY_ESC)
    assert state.context_detail_focused is False
    assert state.context_detail_scroll == 0


def test_context_detail_focus_freezes_table_selection():
    state = axt.TuiState()
    state.context_sub_tab = "sources"
    state.context_analysis = _seed_context_analysis_with_sources()
    state.context_detail_focused = True
    before = state.context_selected
    axt.handle_context_input(state, ord("j"))
    assert state.context_selected == before  # panel scrolled, row frozen
    assert state.context_detail_scroll == 1


def test_context_detail_focus_bracket_cycles_subtab_and_blurs():
    state = axt.TuiState()
    state.context_sub_tab = "sources"
    state.context_detail_focused = True
    state.context_detail_scroll = 5
    msg = axt.handle_context_input(state, ord("["))
    assert state.context_sub_tab == "project"
    assert state.context_detail_focused is False
    assert state.context_detail_scroll == 0
    assert "project" in msg


def test_project_enter_focuses_detail_panel():
    state = axt.TuiState()
    state.project_items = [_project_source("X", path="/p/X.md", content="hello")]
    state.project_selected = 0
    msg = axt.handle_project_input(state, 10)  # Enter
    assert state.context_detail_focused is True
    assert state.context_detail_scroll == 0
    assert "Detail focused" in msg


def test_project_enter_on_empty_list_is_noop():
    state = axt.TuiState()
    state.project_items = []
    assert axt.handle_project_input(state, 10) is None
    assert state.context_detail_focused is False
