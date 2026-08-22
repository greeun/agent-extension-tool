"""Terminal-accessibility tests — Layer Owner for the a11y domain.

Scope is deliberately NOT WCAG-for-browsers (there is no DOM, no ARIA, no
contrast ratio we can measure — the palette is the user's terminal). Per
`tests/doc/scenarios/accessibility-scenarios.md` the scope is redefined to
**terminal accessibility**:

  1. meaning never travels by color alone (brackets / markers / glyphs)
  2. both themes render without crashing and carry the same information
  3. a color-less terminal still renders and still shows selection
  4. below the minimum terminal size the user gets a clear instruction
  5. CJK cell widths keep table columns aligned
  6. status glyphs stay inside the documented alphabet

Render checks reuse the fake-stdscr pattern from `tests/test_tui.py`:
`addnstr(y, x, text, max_w, attr)` calls are captured so both the drawn text
and the attributes can be inspected without a TTY.
"""
from __future__ import annotations

import curses
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import axt


# ─── Harness ─────────────────────────────────────────────────────────────────


def _make_stdscr(rows: int = 30, cols: int = 140):
    """Fake stdscr recording every addnstr call (mirrors tests/test_tui.py)."""
    scr = MagicMock()
    scr.getmaxyx.return_value = (rows, cols)
    scr.calls = []

    def addnstr(*args):
        scr.calls.append(args)

    scr.addnstr.side_effect = addnstr
    return scr


def _flat(scr) -> str:
    return "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))


def _texts(scr) -> list[str]:
    return [c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str)]


def _attrs(scr) -> list:
    return [c[4] for c in scr.calls if len(c) >= 5]


def _cells_by_row(scr) -> dict[int, list[tuple[int, str]]]:
    """Group drawn cells by screen row, preserving call order within a row."""
    by_y: dict[int, list[tuple[int, str]]] = {}
    for c in scr.calls:
        if len(c) >= 3 and isinstance(c[2], str):
            by_y.setdefault(c[0], []).append((c[1], c[2]))
    return by_y


def _table_rows_with_y(scr, names, name_col: int = 2) -> dict[str, tuple[int, list[tuple[int, str]]]]:
    """Data rows of a rendered table, keyed by the expected name they carry.

    A data row is identified structurally: the `#` cell (index 1) holds a row
    number and the name cell (index `name_col`) carries one of `names` — or a
    truncated prefix of it, since a long name is clipped to its column. That
    keeps the header row and the detail panel out of the result.
    """
    out: dict[str, tuple[int, list[tuple[int, str]]]] = {}
    for y, cells in _cells_by_row(scr).items():
        if len(cells) <= name_col:
            continue
        if not cells[1][1].strip().isdigit():
            continue
        drawn = cells[name_col][1].strip()
        if not drawn:
            continue
        hits = [n for n in names if n == drawn or n.startswith(drawn)]
        if len(hits) == 1:
            out[hits[0]] = (y, cells)
    return out


def _table_rows(scr, names, name_col: int = 2) -> dict[str, list[tuple[int, str]]]:
    return {n: cells for n, (_y, cells) in
            _table_rows_with_y(scr, names, name_col).items()}


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every axt path at tmp_path and chdir into a clean project dir.

    `axt.Paths` carries a dozen fields that default to the *real* $HOME; the
    shorter helper in tests/test_tui.py only overrides five of them, which is
    fine there but would let an a11y render read the developer's own
    ~/.claude while walking all eight sub-tabs.
    """
    home = tmp_path / "home"
    claude = tmp_path / "claude"
    vault = tmp_path / "vault"
    axt_cfg = tmp_path / "axt-config"
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=claude,
        claude_config=tmp_path / "claude.json",
        settings=claude / "settings.json",
        known_marketplaces=claude / "plugins" / "known_marketplaces.json",
        installed_plugins=claude / "plugins" / "installed_plugins.json",
        blocklist=claude / "plugins" / "blocklist.json",
        plugin_cache=claude / "plugins" / "cache",
        marketplaces=claude / "plugins" / "marketplaces",
        skills=claude / "skills",
        projects=claude / "projects",
        stats_cache=claude / "stats-cache.json",
        usage_snapshot=claude / "usage-snapshot.json",
        axt_dir=home / ".axt",
        vault=vault,
        vault_skills=vault / "skills",
        vault_commands=vault / "commands",
        vault_agents=vault / "agents",
    ))
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", axt_cfg)
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", axt_cfg / "config.json")
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    monkeypatch.chdir(proj)
    return proj


@pytest.fixture(autouse=True)
def _restore_dark_theme():
    """`tui_init_colors` writes a module global; leaking `light` into other
    test files would silently change their attribute expectations."""
    yield
    axt.tui_init_colors("dark")


def _skill(name: str, path: Path, *, source: str, version: str = "1.0.0"):
    return axt.SkillInfo(name=name, path=str(path), is_symlink=False,
                         source=source, version=version)


def _status(name: str, *, updatable: bool, error: str = "", tier: int = 1):
    return axt.UpdateStatus("skill", name, tier, "1.0.0",
                            "2.0.0" if updatable else "1.0.0",
                            updatable, error=error)


def _seed_four_status_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Four Skills rows whose Vault/Proj/Glob/Upd states are all different.

    `state.update_statuses` is injected directly: the real column is filled by
    a daemon thread that git-fetches, so a render test must never wait on it.
    """
    _isolate(tmp_path, monkeypatch)
    vault_skills = Path(axt.PATHS.vault) / "skills"
    vault_skills.mkdir(parents=True)
    (vault_skills / "a").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    for n in ("b", "c", "d"):
        (outside / n).mkdir()

    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.focused_layer = "content"
    state.ext_cache["skills"] = [
        # vault-stored + linked into the project + update available
        _skill("a", vault_skills / "a", source="project"),
        # not vault-managed, not linked anywhere, up to date
        _skill("b", outside / "b", source="vault"),
        # plugin-bundled: no update-registry entry at all
        _skill("c", outside / "c", source="plugin"),
        # global link whose update check errored
        _skill("d", outside / "d", source="user"),
    ]
    state.update_statuses = {
        ("skill", "a"): _status("a", updatable=True),
        ("skill", "b"): _status("b", updatable=False),
        ("skill", "d"): _status("d", updatable=False, error="fetch failed"),
    }
    return state


# ─── SC-A11Y-001 — active / focused state survives without color ─────────────


def test_active_sub_tab_is_marked_by_brackets_not_color(tmp_path, monkeypatch):
    """Prevents: a refactor that signals the active sub-tab with a color chip
    only. Stripping every attribute must still leave exactly one bracketed
    cell, and inactive cells must carry no brackets at all."""
    # TC-A11Y-001
    _isolate(tmp_path, monkeypatch)
    axt.tui_init_colors("dark")
    scr = _make_stdscr(rows=30, cols=140)

    axt._render_subtab_bar(scr, 0, 140, axt.EXTENSION_SUB_TABS,
                           "skills", focused=True)

    # Attributes are deliberately discarded — this is the color-blind view.
    flat = _flat(scr)
    assert "[ Skills ]" in flat
    assert "[ Plugins ]" not in flat
    assert "  Plugins  " in flat
    assert flat.count("[") == 1, "exactly one cell may read as active"
    assert flat.count("]") == 1


def test_main_tab_bar_distinguishes_active_tab_without_attributes(tmp_path, monkeypatch):
    """Prevents: the main tab bar becoming unreadable for color-blind users /
    monochrome terminals. Two different active tabs must produce two different
    cell strings, while every tab label stays visible."""
    # TC-A11Y-003
    _isolate(tmp_path, monkeypatch)
    axt.tui_init_colors("dark")

    scr1 = _make_stdscr(rows=30, cols=160)
    axt.render_tab_bar(scr1, 0, 0, 160, active_idx=1, focused=True)
    flat1 = _flat(scr1)

    scr2 = _make_stdscr(rows=30, cols=160)
    axt.render_tab_bar(scr2, 0, 0, 160, active_idx=2, focused=True)
    flat2 = _flat(scr2)

    for flat in (flat1, flat2):
        assert flat.count("▶ ") == 1, "focused bar carries exactly one marker"
        for _key, short, long in axt.MAIN_TABS:
            assert (long in flat) or (short in flat), \
                "highlighting one tab must not hide the others"
    assert flat1 != flat2, (
        "the active main tab must be distinguishable from the drawn text "
        "alone (the sub-tab bar already uses brackets for this)"
    )


# ─── SC-A11Y-002 — status glyphs carry the meaning, not the color ────────────


def test_four_different_states_stay_distinguishable_by_glyphs(tmp_path, monkeypatch):
    """Prevents: a column-width or glyph-merge regression collapsing two
    different extension states into the same on-screen row. Colour is not
    available in a log capture — the glyph tuple has to stay unique."""
    # TC-A11Y-004
    state = _seed_four_status_rows(tmp_path, monkeypatch)
    scr = _make_stdscr(rows=30, cols=160)

    axt.render_extensions_tab(scr, state, y0=2, h=26, w=160)

    rows = _table_rows(scr, {"a", "b", "c", "d"})
    assert set(rows) == {"a", "b", "c", "d"}, "every seeded row must be drawn"
    # cells: [prefix, #, Skill, Ver, Vault, Proj, Glob, Upd, ...]
    tuples = {
        name: tuple(cells[i][1].strip() for i in (4, 5, 6, 7))
        for name, cells in rows.items()
    }
    assert len(set(tuples.values())) == 4, f"states collapsed: {tuples}"
    assert tuples["a"][3] == "↑"       # update available
    assert tuples["d"][3] == "!"       # check errored
    assert tuples["c"][3] == "─"       # not updatable here
    assert tuples["a"][0] == "✓"       # vault-stored


def test_rendered_status_glyphs_stay_in_the_documented_alphabet(tmp_path, monkeypatch):
    """Prevents: a new state being added with an ad-hoc character (or an empty
    cell). FEATURES.md §2.4 fixes the alphabet; an unknown glyph is
    unreadable and an empty cell hides the state entirely."""
    # TC-A11Y-005
    state = _seed_four_status_rows(tmp_path, monkeypatch)
    scr = _make_stdscr(rows=30, cols=160)

    axt.render_extensions_tab(scr, state, y0=2, h=26, w=160)

    rows = _table_rows(scr, {"a", "b", "c", "d"})
    assert rows
    for name, cells in rows.items():
        vault, proj, glob, upd = (cells[i][1].strip() for i in (4, 5, 6, 7))
        assert vault in {"✓", "─"}, f"{name}: Vault={vault!r}"
        assert proj in {"●", "○", "·", "─"}, f"{name}: Proj={proj!r}"
        assert glob in {"●", "○", "·", "─"}, f"{name}: Glob={glob!r}"
        assert upd in {"↑", "·", "!", "─", "…"}, f"{name}: Upd={upd!r}"
        assert all(g for g in (vault, proj, glob, upd)), \
            f"{name}: an unknown state must render as ─, never as blank"


# ─── SC-A11Y-003 — theme switching keeps every render path valid ─────────────


def _stub_context(monkeypatch):
    """Fixed ContextAnalysis so Context renders identically on both themes."""
    src = axt.ContextSource(
        name="CLAUDE.md", category="memory", estimated_tokens=100,
        percentage=1.0, path="/p/CLAUDE.md", hint="", chars=400,
        actionable=True, content="x\n", scope="project")
    analysis = axt.ContextAnalysis(
        total_tokens=100, context_window_size=200_000, used_percent=0.1,
        model="claude-sonnet", sources=[src],
        cost_impact=axt.CostImpact(
            model="claude-sonnet", cache_write_cost=0.1,
            cache_read_cost_per_turn=0.01, avg_turns_per_session=30,
            avg_sessions_per_day=5, per_session_cost=0.5, monthly_cost=9.0),
    )
    monkeypatch.setattr("axt.tui.tabs.analyze_context", lambda *a, **k: analysis)
    return analysis


def test_light_theme_renders_every_main_tab_without_error(tmp_path, monkeypatch):
    """Prevents: a light-only palette branch referencing an uninitialized pair
    (or a non-int attribute) and blowing up mid-frame for light-theme users —
    the dark-theme test suite would never notice."""
    # TC-A11Y-006
    _isolate(tmp_path, monkeypatch)
    _stub_context(monkeypatch)
    scr = _make_stdscr(rows=40, cols=160)
    axt.tui_init_colors("light", scr)

    state = axt.TuiState()
    state.usage_entries = []          # loaded-and-empty: no loader thread
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)

    for tab_idx in range(len(axt.MAIN_TABS)):
        state.tab_idx = tab_idx
        before = len(scr.calls)
        axt._render_frame(scr, state)
        assert len(scr.calls) > before, \
            f"{axt.MAIN_TABS[tab_idx][0]} drew nothing on the light theme"

    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")
    for sub_key, _label in axt.EXTENSION_SUB_TABS:
        state.ext_sub_tab = sub_key
        before = len(scr.calls)
        axt._render_frame(scr, state)
        assert len(scr.calls) > before, f"{sub_key} drew nothing on the light theme"

    assert all(isinstance(a, int) for a in _attrs(scr)), \
        "every addnstr attribute must be an int curses can interpret"


def test_theme_changes_colors_but_never_the_information(tmp_path, monkeypatch):
    """Prevents: a theme-specific branch appending or dropping text, which
    would give one theme's users less information than the other's."""
    # TC-A11Y-007
    _isolate(tmp_path, monkeypatch)
    vault_skills = Path(axt.PATHS.vault) / "skills"
    (vault_skills / "alpha").mkdir(parents=True)
    (vault_skills / "alpha" / "SKILL.md").write_text("---\ndescription: a\n---\n")

    state = axt.TuiState()
    state.ext_sub_tab = "vault"
    state.focused_layer = "content"

    axt.tui_init_colors("dark")
    scr_dark = _make_stdscr(rows=30, cols=140)
    axt.render_extensions_tab(scr_dark, state, y0=2, h=26, w=140)

    axt.tui_init_colors("light")
    scr_light = _make_stdscr(rows=30, cols=140)
    axt.render_extensions_tab(scr_light, state, y0=2, h=26, w=140)

    assert _texts(scr_dark) == _texts(scr_light), \
        "the theme may only change colors, never the drawn text"
    assert _attrs(scr_dark) != _attrs(scr_light), \
        "control: the theme must actually reach the attributes"


def test_both_themes_fill_the_same_color_pair_numbers(tmp_path, monkeypatch):
    """Prevents: the light palette omitting a pair the dark one defines. The
    widget using it would then draw with no attribute at all and silently lose
    its contrast on one theme only."""
    # TC-A11Y-008
    _isolate(tmp_path, monkeypatch)
    seen: list[tuple[int, int, int]] = []
    monkeypatch.setattr("curses.init_pair",
                        lambda n, fg, bg: seen.append((n, fg, bg)))

    axt.tui_init_colors("light")
    light = {n for n, _fg, _bg in seen}
    seen.clear()
    axt.tui_init_colors("dark")
    dark = {n for n, _fg, _bg in seen}

    assert light and dark
    assert light == dark, f"pair numbers diverge: light-only={light - dark}, dark-only={dark - light}"

    # A terminal without color support raises here; the helper must absorb it.
    monkeypatch.setattr("curses.init_pair",
                        lambda *a: (_ for _ in ()).throw(curses.error("no pair")))
    axt.tui_init_colors("light")
    axt.tui_init_colors("dark")


# ─── SC-A11Y-004 — monochrome fallback ───────────────────────────────────────


def _seed_vault_three(tmp_path: Path):
    vault_skills = Path(axt.PATHS.vault) / "skills"
    vault_skills.mkdir(parents=True)
    for name in ("alpha", "beta", "gamma"):
        (vault_skills / name).mkdir()
        (vault_skills / name / "SKILL.md").write_text(
            f"---\ndescription: {name}\nversion: 1.0.0\n---\n")


def test_frame_renders_identically_when_color_pair_fails(tmp_path, monkeypatch):
    """Prevents: a dashboard that dies (or loses text) on TERM=dumb, in CI log
    captures and over plain SSH — exactly where it is needed during an
    incident. `_safe_pair` swallows the error; the text must be unchanged."""
    # TC-A11Y-009
    _isolate(tmp_path, monkeypatch)
    _seed_vault_three(tmp_path)
    axt.tui_init_colors("dark")

    def _build_state():
        s = axt.TuiState()
        s.ext_sub_tab = "vault"
        s.focused_layer = "content"
        s.vault_selected = 1
        return s

    # Control: a terminal that *does* answer color_pair.
    monkeypatch.setattr("curses.color_pair", lambda n: n << 8)
    colored = _make_stdscr(rows=30, cols=140)
    axt._render_frame(colored, _build_state())

    # Subject: color_pair raises for every lookup.
    monkeypatch.setattr("curses.color_pair",
                        lambda n: (_ for _ in ()).throw(curses.error("no color")))
    mono = _make_stdscr(rows=30, cols=140)
    axt._render_frame(mono, _build_state())

    assert _texts(mono) == _texts(colored), "no information may be lost without color"
    attrs = _attrs(mono)
    assert attrs
    assert all(isinstance(a, int) and a >= 0 for a in attrs)


def test_selected_row_stays_reverse_video_without_color(tmp_path, monkeypatch):
    """Prevents: selection becoming invisible on a color-less terminal, and
    the opposite failure — A_REVERSE leaking onto every row, which makes the
    highlight meaningless."""
    # TC-A11Y-010
    _isolate(tmp_path, monkeypatch)
    _seed_vault_three(tmp_path)
    axt.tui_init_colors("dark")
    monkeypatch.setattr("curses.color_pair",
                        lambda n: (_ for _ in ()).throw(curses.error("no color")))

    state = axt.TuiState()
    state.ext_sub_tab = "vault"
    state.focused_layer = "content"
    state.vault_selected = 1          # "beta" — the middle row

    scr = _make_stdscr(rows=30, cols=140)
    axt._render_frame(scr, state)

    named_rows = _table_rows_with_y(scr, {"alpha", "beta", "gamma"})
    assert set(named_rows) == {"alpha", "beta", "gamma"}

    attrs_for = {
        name: [c[4] for c in scr.calls
               if len(c) >= 5 and c[0] == y and isinstance(c[2], str)]
        for name, (y, _cells) in named_rows.items()
    }

    assert all(a & curses.A_REVERSE for a in attrs_for["beta"]), \
        "the selected row must stay identifiable through A_REVERSE alone"
    for other in ("alpha", "gamma"):
        assert not any(a & curses.A_REVERSE for a in attrs_for[other]), \
            f"{other} is not selected — reversing it destroys the selection cue"


# ─── SC-A11Y-005 — minimum terminal size ─────────────────────────────────────


_TOO_SMALL = "Terminal too small. Resize and try again."


def test_minimum_size_boundary_renders_or_instructs(tmp_path, monkeypatch):
    """Prevents: an off-by-one in the size gate — either a half-drawn frame
    below the threshold (unreadable garbage) or a refusal to render at a size
    that actually fits. Only the boundary *behaviour* is asserted, never the
    constant."""
    # TC-A11Y-012
    _isolate(tmp_path, monkeypatch)

    for rows, cols in ((4, 120), (30, 29), (5, 29)):
        scr = _make_stdscr(rows=rows, cols=cols)
        axt._render_frame(scr, axt.TuiState())
        drawn = _texts(scr)
        assert drawn == [_TOO_SMALL], (
            f"({rows}x{cols}) must show only the resize instruction, got {drawn!r}")

    scr = _make_stdscr(rows=5, cols=30)
    axt._render_frame(scr, axt.TuiState())
    flat = _flat(scr)
    assert _TOO_SMALL not in flat, "(5x30) is large enough — it must render"
    assert any(short in flat or long in flat for _k, short, long in axt.MAIN_TABS), \
        "the tab bar must be drawn at the threshold size"


def test_narrow_terminal_never_draws_outside_the_screen(tmp_path, monkeypatch):
    """Prevents: a width-arithmetic bug silently erasing a column. `safe_addnstr`
    swallows curses.error, so an out-of-bounds write leaves no exception for a
    normal render test to catch — only the call arguments reveal it."""
    # TC-A11Y-013
    _isolate(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    for n in ("one", "two", "three"):
        (outside / n).mkdir()

    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.focused_layer = "content"
    state.ext_cache["skills"] = [
        _skill(n, outside / n, source="user") for n in ("one", "two", "three")
    ]

    cols = 31
    scr = _make_stdscr(rows=6, cols=cols)
    axt._render_frame(scr, state)

    assert scr.calls, "a 6x31 terminal is above the threshold and must render"
    for call in scr.calls:
        y, x, text, max_w = call[0], call[1], call[2], call[3]
        assert max_w > 0, f"zero/negative width draw at ({y},{x}): {text!r}"
        assert x + max_w <= cols, \
            f"draw at ({y},{x}) width {max_w} runs past the {cols}-cell screen"


# ─── SC-A11Y-006 — CJK width and column alignment ────────────────────────────


def _seed_named_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, names: list[str]):
    """Skills rows differing only in their name, so name width is the one
    variable in the layout."""
    _isolate(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.focused_layer = "content"
    items = []
    for name in names:
        d = outside / name
        d.mkdir()
        items.append(_skill(name, d, source="user", version="1.0.0"))
    state.ext_cache["skills"] = items
    # Fixed order regardless of locale collation: keep the seeded order.
    state.ext_sort["skills"] = "source"
    return state


def test_cjk_names_do_not_shift_the_following_columns(tmp_path, monkeypatch):
    """Prevents: the signature visual defect of this tool — one Hangul-named
    skill knocking every column of the table out of alignment. `cell_width`
    has unit tests, but nothing proves the *renderer* uses it."""
    # TC-A11Y-014
    names = ["ascii-skill", "한글스킬", "日本語スキル"]
    state = _seed_named_skills(tmp_path, monkeypatch, names)
    scr = _make_stdscr(rows=30, cols=140)

    axt.render_extensions_tab(scr, state, y0=2, h=26, w=140)

    rows = _table_rows(scr, set(names))
    assert set(rows) == set(names)
    xs = {name: [x for x, _t in cells] for name, cells in rows.items()}
    ref = xs[names[0]]
    for name in names[1:]:
        assert xs[name] == ref, (
            f"{name!r} shifted the column boundaries: {xs[name]} != {ref}")
    # The column right after the name is the one a mis-measured name breaks first.
    ver_x = {name: cells[3][0] for name, cells in rows.items()}
    assert len(set(ver_x.values())) == 1, f"Ver column x diverged: {ver_x}"


def test_long_cjk_name_is_truncated_inside_its_own_column(tmp_path, monkeypatch):
    """Prevents: an over-long CJK name overflowing its column and pushing the
    rest of the row sideways — or being truncated to nothing, which would make
    the row unidentifiable."""
    # TC-A11Y-015
    long_name = "한글스킬이름이아주아주깁니다"      # 14 chars = 28 cells
    names = ["ascii", long_name]
    state = _seed_named_skills(tmp_path, monkeypatch, names)
    # 116 cols puts the Skill column at its 20-cell floor, well under 28 cells.
    scr = _make_stdscr(rows=30, cols=116)

    axt.render_extensions_tab(scr, state, y0=2, h=26, w=116)

    rows = _table_rows(scr, set(names))
    assert set(rows) == set(names)
    cjk_cell = rows[long_name][2][1]
    ascii_cell = rows["ascii"][2][1]
    column_w = rows["ascii"][3][0] - rows["ascii"][2][0]   # x(Ver) - x(Skill)

    assert axt.cell_width(cjk_cell) == column_w, \
        f"name cell is {axt.cell_width(cjk_cell)} cells in a {column_w}-cell column"
    assert axt.cell_width(cjk_cell) == axt.cell_width(ascii_cell)
    assert rows[long_name][3][0] == rows["ascii"][3][0], \
        "overflow must not push the next column"
    assert cjk_cell.strip(), "a truncated name must still show something identifiable"
    assert cjk_cell.strip() != long_name, "this case is supposed to exercise truncation"
    assert long_name.startswith(cjk_cell.strip()), \
        "truncation must keep the leading characters, not an arbitrary slice"


def test_wide_characters_are_never_cut_in_half(tmp_path, monkeypatch):
    """Prevents: a renderer bypassing `fit_cells` for a plain `text[:n]` slice.
    At an odd column width that leaves half a wide glyph, which curses paints
    as a stray blank and drags the rest of the row one cell left."""
    # TC-A11Y-016
    wide_name = "한" * 30                        # 60 cells — far past the column
    names = ["ascii", wide_name]
    state = _seed_named_skills(tmp_path, monkeypatch, names)
    # 139 cols makes the drawn name column an ODD number of cells, so a wide
    # glyph cannot exactly fill it — the padding path has to kick in.
    scr = _make_stdscr(rows=30, cols=139)

    axt.render_extensions_tab(scr, state, y0=2, h=26, w=139)

    rows = _table_rows(scr, set(names))
    assert set(rows) == set(names)
    cell = rows[wide_name][2][1]
    column_w = rows["ascii"][3][0] - rows["ascii"][2][0]
    assert column_w % 2 == 1, "this test needs an odd column width to be meaningful"

    assert axt.cell_width(cell) == column_w
    content = cell.rstrip(" ")
    assert content, "the name must not be truncated away entirely"
    assert all(axt.cell_width(ch) == 2 for ch in content), \
        "content is all wide characters; nothing else may sneak in"
    assert axt.cell_width(content) <= column_w - 1, \
        "a wide glyph was allowed to straddle the column boundary"
    assert cell == content + " " * (column_w - axt.cell_width(content)), \
        "leftover width must be padded with spaces, not half a wide glyph"
