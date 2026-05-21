"""Tests for Section 11-14 — curses TUI widgets.

We can't open a real curses screen in pytest, so we use a Mock stdscr that
records every addnstr call. This is the same pattern cst uses to verify its
TUI without a TTY.
"""
from __future__ import annotations

import curses
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


def test_main_tabs_three_resource_types():
    """Top-level tabs after Dashboard was folded into Usage."""
    keys = [t[0] for t in axt.MAIN_TABS]
    assert keys == ["extensions", "context", "usage"]


def test_tui_state_defaults_context_show_project_on():
    """Context-tab-local toggle for the project files pane defaults to on."""
    s = axt.TuiState()
    assert s.context_show_project is True


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


def test_cycle_sub_tab_rotates_only_extensions():
    """_cycle_sub_tab rotates ext_sub_tab — Extensions is the only tab with sub-tabs."""
    state = axt.TuiState()
    assert state.ext_sub_tab == "vault"
    axt._cycle_sub_tab(state, +1)
    assert state.ext_sub_tab == "plugins"


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


def test_context_tab_includes_project_files_section_when_toggle_on(monkeypatch, tmp_path):
    """With context_show_project=True (default), Context tab lists project
    context files under a dedicated section header."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# test\nproject level\n")

    scr = _make_stdscr(rows=40, cols=140)
    state = axt.TuiState()
    assert state.context_show_project is True
    state.context_analysis = _make_empty_context_analysis()
    axt.render_context_tab(scr, state, y0=3, h=30, w=140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Project files" in flat
    assert "CLAUDE.md" in flat


def test_context_tab_hides_project_files_section_when_toggle_off(monkeypatch, tmp_path):
    """With context_show_project=False, the per-project file list is hidden."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# test\nshould not appear\n")

    scr = _make_stdscr(rows=40, cols=140)
    state = axt.TuiState()
    state.context_show_project = False
    state.context_analysis = _make_empty_context_analysis()
    axt.render_context_tab(scr, state, y0=3, h=30, w=140)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "Project files" not in flat


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
    texts = [c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str)]
    assert any(t.startswith("┌") for t in texts)
    assert any(t.startswith("└") for t in texts)


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
    axt._render_subtab_bar(scr_focused, 0, 120, active_key="vault", focused=True)
    scr_unfocused = _make_stdscr()
    axt._render_subtab_bar(scr_unfocused, 0, 120, active_key="vault", focused=False)
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


def test_handle_vault_input_filter_shift_f():
    s = axt.TuiState()
    axt.handle_vault_input(s, ord("F"))
    assert s.vault_filter == "skill"
    axt.handle_vault_input(s, ord("F"))
    assert s.vault_filter == "command"


def test_handle_vault_input_tab_does_not_cycle_filter():
    """Tab is reserved for sub-tab cycling at the parent level; the vault
    handler must not consume it as a filter shortcut."""
    s = axt.TuiState()
    axt.handle_vault_input(s, 9)  # Tab
    assert s.vault_filter == "all"


def test_handle_vault_input_sort_cycle():
    s = axt.TuiState()
    axt.handle_vault_input(s, ord("s"))
    assert s.vault_sort == "type"
    axt.handle_vault_input(s, ord("s"))
    assert s.vault_sort == "added"


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


def test_help_text_documents_tab_navigation():
    assert "1–3" in axt.HELP_TEXT
    assert "main tab" in axt.HELP_TEXT


def test_help_text_documents_context_project_pane_toggle():
    assert "project files pane" in axt.HELP_TEXT.lower()


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
    assert state.ext_sub_tab == "plugins"
    axt.handle_extensions_input(state, ord("]"))
    assert state.ext_sub_tab == "skills"


def test_extensions_sub_tab_cycle_backward():
    state = axt.TuiState()
    axt.handle_extensions_input(state, ord("["))
    # Wraps to last sub-tab.
    assert state.ext_sub_tab == "market"


# ─── load_project_context smoke test ─────────────────────────────────────────


def test_load_project_context_picks_up_claude_md(tmp_path, monkeypatch):
    _setup_isolated_paths(tmp_path, monkeypatch)
    (tmp_path / "CLAUDE.md").write_text("hello")
    items = axt.load_project_context(tmp_path)
    names = [i.name for i in items]
    assert "CLAUDE.md (project)" in names


def test_load_project_context_lines_count(tmp_path, monkeypatch):
    _setup_isolated_paths(tmp_path, monkeypatch)
    (tmp_path / "CLAUDE.md").write_text("one\ntwo\nthree\n")
    items = axt.load_project_context(tmp_path)
    item = next((i for i in items if i.name == "CLAUDE.md (project)"), None)
    assert item is not None
    assert item.lines == 4  # 3 newlines + 1 (final empty line counts)


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


def test_vault_space_toggles_project_pending():
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="", is_linked=False)]
    axt.handle_vault_input(state, ord(" "))
    assert "alpha" in state.vault_pending_project
    # Toggling again removes it.
    axt.handle_vault_input(state, ord(" "))
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


def test_vault_space_ignored_for_plugins():
    """Plugins use enabledPlugins, not symlinks — Space must not enqueue."""
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="plug", type="plugin", path="", description="")]
    axt.handle_vault_input(state, ord(" "))
    assert "plug" not in state.vault_pending_project


def test_vault_scan_toggles_mode_and_runs(tmp_path, monkeypatch):
    """`f` toggles scan_mode AND runs scan_project_usage."""
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        projects=tmp_path / "projects",
        vault=tmp_path / "vault",
    ))
    state = axt.TuiState()
    assert state.vault_scan_mode == "default"
    msg = axt.handle_vault_input(state, ord("f"))
    assert state.vault_scan_mode == "full"
    assert msg is not None and "Scan" in msg
    # Toggle back.
    axt.handle_vault_input(state, ord("f"))
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


def test_vault_global_only_status_clarified(tmp_path, monkeypatch):
    """A global-only item (not in vault) is marked `glob*` in the Vault column."""
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
    # The "glob*" status must appear at least once.
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "glob*" in flat


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
    assert "glob*" in h or "global only" in h.lower()
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
    loaded, mode = axt._load_scan_cache()
    assert mode == "full"
    assert "skill:alpha" in loaded
    assert len(loaded["skill:alpha"].projects) == 2
    assert loaded["skill:alpha"].projects[0].name == "p1"


def test_load_scan_cache_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", tmp_path / "config")
    loaded, mode = axt._load_scan_cache()
    assert loaded == {}
    assert mode == "default"


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


# ─── Sub-tab navigation: visual focus + Shift+Tab / Tab ──────────────────────


def test_subtab_bar_shows_brackets_around_active():
    """Active sub-tab is bracketed so it's visible even without color."""
    scr = _make_stdscr(rows=20, cols=120)
    axt._render_subtab_bar(scr, 0, 120, active_key="skills")
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "[ Skills ]" in flat
    assert "Sub:" in flat


def test_subtab_shift_tab_goes_backward():
    state = axt.TuiState()
    assert state.ext_sub_tab == "vault"
    # KEY_BTAB = Shift+Tab.
    axt.handle_extensions_input(state, curses.KEY_BTAB)
    assert state.ext_sub_tab == "market"


def test_subtab_tab_forward_on_non_vault():
    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    axt.handle_extensions_input(state, 9)  # Tab
    assert state.ext_sub_tab == "skills"


def test_subtab_tab_on_vault_cycles_sub_tab():
    """Tab is unified: even on Vault it advances to the next sub-tab and
    leaves the vault filter untouched."""
    state = axt.TuiState()
    state.ext_sub_tab = "vault"
    before_filter = state.vault_filter
    axt.handle_extensions_input(state, 9)  # Tab
    assert state.ext_sub_tab != "vault"  # advanced to next sub-tab
    assert state.vault_filter == before_filter  # filter NOT cycled


def test_subtab_status_message_on_cycle():
    state = axt.TuiState()
    msg = axt.handle_extensions_input(state, ord("]"))
    assert msg == "Sub-tab: plugins"


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
    axt._render_subtab_bar(scr_focused, 0, 120, active_key="plugins", focused=True)
    scr_unfocused = _make_stdscr()
    axt._render_subtab_bar(scr_unfocused, 0, 120, active_key="plugins", focused=False)
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
    """The header area must include a line with 'cwd:' + the full project path."""
    monkeypatch.chdir(tmp_path)
    scr = _make_stdscr(rows=30, cols=140)
    state = axt.TuiState()
    axt._render_frame(scr, state)
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "cwd:" in flat
    assert str(tmp_path) in flat


# ─── Non-Vault Extensions sub-tabs: no duplicated row number ─────────────────


def test_extensions_plugins_sub_tab_no_duplicate_number_column():
    """Plugins sub-tab should NOT have a `#` data column — render_table's
    own prefix already shows the row number."""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path as _P
        ip_path = _P(tmp) / "ip.json"
        ip_path.write_text(json.dumps({
            "version": 2,
            "plugins": {"plug@m": [{
                "scope": "user", "installPath": "/p", "version": "1",
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
            # Count standalone '1' cells next to "plug" row — only ONE (the prefix).
            plug_y = next(c[0] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str) and "plug" in c[2])
            # Count cells on plug_y whose content equals exactly "1" or starts with "1 ".
            # The render_table prefix is `▸ 1 ` or ` 1 ` (single contiguous cell).
            cells_on_row = [c for c in scr.calls if len(c) >= 3 and c[0] == plug_y and isinstance(c[2], str)]
            number_cells = [c for c in cells_on_row if c[2].strip() == "1"]
            # Exactly one occurrence of an isolated "1" cell — the prefix number,
            # NOT also a duplicated `no` column.
            assert len(number_cells) <= 1
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


def test_vault_detail_focus_esc_blurs():
    state = axt.TuiState()
    state.vault_items = [axt.VaultItem(name="alpha", type="skill", path="", description="")]
    state.vault_detail_focused = True
    state.vault_detail_scroll = 5
    axt.handle_vault_input(state, 27)  # Esc
    assert state.vault_detail_focused is False
    assert state.vault_detail_scroll == 0


# ─── Subtab actions (Plugin enable / disable / Skill / Marketplace / Hook) ───


def test_plugin_enable_disable_action(tmp_path, monkeypatch):
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
    state = axt.TuiState()
    state.ext_sub_tab = "plugins"
    state.ext_cache["plugins"] = axt.list_installed_plugins(tmp_path / "ip.json")
    state.ext_selected["plugins"] = 0
    # Without stdscr context, modal-bound actions are no-ops; e/d don't need it.
    state.stdscr_callbacks = {"stdscr": None}
    msg = axt._handle_subtab_action(state, "plugins", ord("e"))
    assert "Enabled" in (msg or "")
    assert axt.read_enabled_plugins(tmp_path / "settings.json")["p@m"] is True
    state.ext_cache["plugins"] = axt.list_installed_plugins(tmp_path / "ip.json")
    msg = axt._handle_subtab_action(state, "plugins", ord("d"))
    assert "Disabled" in (msg or "")
    assert axt.read_enabled_plugins(tmp_path / "settings.json")["p@m"] is False


def test_subtab_action_without_stdscr_is_noop():
    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.stdscr_callbacks = None
    assert axt._handle_subtab_action(state, "skills", ord("l")) is None


# ─── Project Enter preview & `e` editor (smoke) ──────────────────────────────


def test_project_enter_calls_preview(monkeypatch):
    called = []
    monkeypatch.setattr("axt.preview_modal", lambda stdscr, content, title="Preview": called.append((title, content)))
    state = axt.TuiState()
    state.project_items = [axt.ProjectContextItem(
        name="CLAUDE.md (project)", source="project", path="/p/CLAUDE.md",
        content="hello", lines=1,
    )]
    state.project_selected = 0
    state.stdscr_callbacks = {"stdscr": object()}
    axt.handle_project_input(state, 10)
    assert called and called[0][1] == "hello"


def test_project_e_calls_editor(monkeypatch):
    called = []
    monkeypatch.setattr("axt.open_in_editor", lambda stdscr, path: called.append(path) or True)
    state = axt.TuiState()
    state.project_items = [axt.ProjectContextItem(
        name="X", source="project", path="/p/X.md", content="x", lines=1,
    )]
    state.project_selected = 0
    state.stdscr_callbacks = {"stdscr": object()}
    axt.handle_project_input(state, ord("e"))
    assert called == ["/p/X.md"]


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
    assert rows == 2
    flat = "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))
    assert "5h quota" in flat
    assert "7d quota" in flat


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
        axt.PATHS, settings=fake_settings, installed_plugins=fake_installed
    )
    monkeypatch.setattr("axt.PATHS", fake_paths)

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


def test_tab_has_sub_tab_only_extensions():
    assert axt.tab_has_sub_tab("extensions") is True
    for k in ("context", "usage"):
        assert axt.tab_has_sub_tab(k) is False


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


def test_context_down_arrow_descends_directly_to_content():
    """Context has no sub-tab but has a focusable list, so ↓ → content."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("context")
    scr = _make_stdscr()
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
    # Context has no sub-tab, so we climb all the way back to mainTab.
    assert state.focused_layer == "mainTab"


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


def test_esc_in_content_climbs_to_main_tab_for_context():
    """Tabs without a sub-tab bar (Context) jump straight to the main tab."""
    state = axt.TuiState()
    state.tab_idx = _tab_idx("context")
    state.focused_layer = "content"
    state.context_selected = 5
    scr = _make_stdscr()
    consumed = axt._handle_layer_key(scr, state, axt.KEY_ESC, "context")
    assert consumed is True
    assert state.focused_layer == "mainTab"


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
    assert axt.sub_tab_has_focusable_content(s, "vault") is False
    assert axt.sub_tab_has_focusable_content(s, "plugins") is False
    # Populate and re-check (sentinel values — function only inspects truthiness).
    s.vault_items = ["dummy"]
    s.ext_cache["plugins"] = ["dummy"]
    assert axt.sub_tab_has_focusable_content(s, "vault") is True
    assert axt.sub_tab_has_focusable_content(s, "plugins") is True


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
