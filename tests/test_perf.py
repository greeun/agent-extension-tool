"""Performance layer — work-per-item ceilings, not wall-clock stopwatches.

Layer Owner (tests/doc/TEST_DEDUP_POLICY.md §2): "대용량 입력의 시간·호출횟수 상한".

Measurement policy (tests/doc/testcases/performance-testcases.md): assert call
counts and complexity ceilings, because a shared CI box makes timing flaky.
Exactly one test here uses a stopwatch (TC-PERF-018) and states its machine
assumption inline.

Determinism: every test isolates HOME / cwd / `axt.PATHS` / `AXT_CONFIG_DIR`
under `tmp_path`. Where a code path reads the real clock (usage-cache TTL,
update-status TTL) the fixture is written with the real clock too — faking
`datetime.now()` while leaving file mtimes real is the exact combination that
made this repo's `plan overview` tests flaky.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import axt
import axt.tui.tabs as tabs

# Captured before conftest's autouse fixture swaps the module attribute for a
# no-op (same trick as tests/test_tui.py).
from axt.tui.tabs import _kick_update_check as REAL_KICK_UPDATE_CHECK  # noqa: E402


MODELS = ("claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5", "claude-fable-5")


# ─── helpers ─────────────────────────────────────────────────────────────────


def _make_stdscr(rows: int = 30, cols: int = 140):
    scr = MagicMock()
    scr.getmaxyx.return_value = (rows, cols)
    scr.calls = []
    scr.addnstr.side_effect = lambda *a: scr.calls.append(a)
    return scr


class _Counter:
    """Call-counting wrapper that still runs the real function."""

    def __init__(self, fn):
        self._fn = fn
        self.n = 0
        self.args: list = []

    def __call__(self, *a, **kw):
        self.n += 1
        self.args.append((a, kw))
        return self._fn(*a, **kw)

    def reset(self) -> None:
        self.n = 0
        self.args.clear()


def _count_method(monkeypatch, cls, name: str) -> _Counter:
    """Count calls to an unbound method while still running it.

    A plain callable object assigned onto a class is not a descriptor, so it
    would be invoked without `self`. This wraps a real function instead.
    """
    original = getattr(cls, name)
    counter = _Counter(original)

    def wrapper(self, *a, **kw):
        counter.n += 1
        counter.args.append(((self, *a), kw))
        return original(self, *a, **kw)

    monkeypatch.setattr(cls, name, wrapper)
    return counter


class _StubThread:
    """Records construction/start instead of running anything."""

    started: list = []

    def __init__(self, target=None, args=(), name=None, daemon=None):
        self.name = name

    def start(self):
        _StubThread.started.append(self.name)


def _isolate(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=home / ".claude",
        claude_config=home / ".claude.json",
        settings=home / ".claude" / "settings.json",
        known_marketplaces=home / ".claude" / "km.json",
        installed_plugins=home / ".claude" / "ip.json",
        skills=home / ".claude" / "skills",
        projects=home / ".claude" / "projects",
        vault=tmp_path / "vault",
        vault_skills=tmp_path / "vault" / "skills",
        vault_commands=tmp_path / "vault" / "commands",
        vault_agents=tmp_path / "vault" / "agents",
    ))
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", tmp_path / "axtcfg")
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "axtcfg" / "config.json")
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "axtcfg" / "cache")
    monkeypatch.chdir(tmp_path)
    return home


def _write_sessions(projects: Path, *, n_projects: int, n_files: int, n_lines: int,
                    models=("claude-sonnet-5",), base="2026-01-05T00:00:00.000Z"):
    """Write `n_projects * n_files` JSONL session files and return the totals
    accumulated *while writing* — expectations must never come from the loader.
    """
    from datetime import datetime, timedelta, timezone
    t0 = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    totals = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0,
              "count": 0, "by_model": {}, "sessions": set()}
    i = 0
    for p in range(n_projects):
        pdir = projects / f"proj-{p:02d}"
        pdir.mkdir(parents=True, exist_ok=True)
        for f in range(n_files):
            sid = f"s-{p:02d}-{f:03d}"
            lines = []
            for _ in range(n_lines):
                model = models[i % len(models)]
                usage = {
                    "input_tokens": (i % 997) + 1,
                    "output_tokens": (i % 389) + 1,
                    "cache_creation_input_tokens": i % 53,
                    "cache_read_input_tokens": i % 211,
                }
                ts = (t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                lines.append(json.dumps({
                    "type": "assistant", "sessionId": sid, "timestamp": ts,
                    "message": {"model": model, "usage": usage},
                }))
                totals["input"] += usage["input_tokens"]
                totals["output"] += usage["output_tokens"]
                totals["cache_create"] += usage["cache_creation_input_tokens"]
                totals["cache_read"] += usage["cache_read_input_tokens"]
                totals["by_model"][model] = totals["by_model"].get(model, 0) + 1
                totals["count"] += 1
                i += 1
            totals["sessions"].add(sid)
            (pdir / f"{sid}.jsonl").write_text("\n".join(lines) + "\n")
    return totals


def _skill(name: str, path: Path, *, version: str = "1.0.0", source: str = "user"):
    return axt.SkillInfo(name=name, path=str(path), is_symlink=False,
                         source=source, version=version)


# ─── SC-PERF-001 — JSONL re-parse avoidance ──────────────────────────────────


def test_only_the_changed_file_is_reparsed_across_200_files(tmp_path, monkeypatch):
    """One touched file out of 200 must cause exactly one re-parse.

    Prevents: a refactor that moves the mtime check outside the per-file loop.
    The existing single-file test still passes in that state; only scale shows
    that work now tracks total files instead of changed files (US-USG08 AC1).
    """
    # TC-PERF-001
    _isolate(tmp_path, monkeypatch)
    projects = tmp_path / "projects"
    _write_sessions(projects, n_projects=4, n_files=50, n_lines=20)

    counter = _Counter(axt.core.parse_claude_jsonl)
    monkeypatch.setattr("axt.core.parse_claude_jsonl", counter)

    cold = axt.load_all_claude_usage(projects)
    assert counter.n == 200, f"cold load parsed {counter.n} files, expected 200"

    counter.reset()
    victim = projects / "proj-01" / "s-01-007.jsonl"
    with victim.open("a") as f:
        f.write(json.dumps({
            "type": "assistant", "sessionId": "s-01-007",
            "timestamp": "2026-01-06T00:00:00.000Z",
            "message": {"model": "claude-sonnet-5", "usage": {"input_tokens": 7}},
        }) + "\n")
    # Advance mtime explicitly: on a 1s-resolution filesystem a same-second
    # edit would be mistaken for a cache hit.
    st = victim.stat()
    os.utime(victim, (st.st_mtime + 2, st.st_mtime + 2))

    warm = axt.load_all_claude_usage(projects, force_refresh=True)

    assert counter.n == 1, f"re-parsed {counter.n} files for one change"
    assert len(warm) == len(cold) + 1


def test_token_totals_survive_the_v2_intern_cache_at_scale(tmp_path, monkeypatch):
    """Per-(model, session) totals are identical cold and cache-restored.

    Prevents: an off-by-one in the v2 intern tables (models / sessions are
    stored as indices). At 200 files across 4 models a shifted index silently
    bills one model's tokens to another; a 2-entry round-trip cannot see it
    (US-USG08 AC1/AC2).
    """
    # TC-PERF-002
    _isolate(tmp_path, monkeypatch)
    projects = tmp_path / "projects"
    _write_sessions(projects, n_projects=4, n_files=50, n_lines=20, models=MODELS)

    def totals(entries):
        acc: dict = {}
        for e in entries:
            key = (e.model, e.session_id)
            cur = acc.setdefault(key, [0, 0, 0, 0])
            cur[0] += e.input_tokens
            cur[1] += e.output_tokens
            cur[2] += e.cache_creation_tokens
            cur[3] += e.cache_read_tokens
        return acc

    cold = totals(axt.load_all_claude_usage(projects))
    warm = totals(axt.load_all_claude_usage(projects))

    assert warm == cold
    assert {m for m, _ in cold} == set(MODELS), "model ids did not survive as raw strings"


# ─── SC-PERF-002 — fresh-cache short circuit ─────────────────────────────────


def test_fresh_cache_skips_globbing_and_statting_session_files(tmp_path, monkeypatch):
    """A cache written seconds ago must not glob or stat the session tree again.

    Prevents: the TTL short-circuit being bypassed, which turns every usage
    view into 200 stat calls plus a directory walk (US-USG08 AC2).
    """
    # TC-PERF-003
    _isolate(tmp_path, monkeypatch)
    projects = tmp_path / "projects"
    _write_sessions(projects, n_projects=4, n_files=50, n_lines=20)
    axt.load_all_claude_usage(projects)          # fills the cache (real clock)

    parse = _Counter(axt.core.parse_claude_jsonl)
    monkeypatch.setattr("axt.core.parse_claude_jsonl", parse)
    globs = _count_method(monkeypatch, Path, "glob")
    stats = _count_method(monkeypatch, Path, "stat")

    entries = axt.load_all_claude_usage(projects)

    assert entries, "cache restore returned nothing — the counters prove nothing"
    assert parse.n == 0
    jsonl_globs = [a for a, _ in globs.args if any("jsonl" in str(x) for x in a[1:])]
    assert jsonl_globs == [], f"session tree was globbed: {jsonl_globs}"
    jsonl_stats = [a[0] for a, _ in stats.args if str(a[0]).endswith(".jsonl")]
    assert jsonl_stats == [], f"{len(jsonl_stats)} session files were stat'ed"


def test_cache_restore_reproduces_the_cold_load_exactly(tmp_path, monkeypatch):
    """The fast path must return byte-identical usage rows, not just fast ones.

    Prevents: the worst kind of perf regression — a short-circuit that drops or
    mangles rows (projectPath is derived from the cache key, not stored) so cost
    reports quietly go wrong while looking snappier (US-USG08 AC2).
    """
    # TC-PERF-004
    _isolate(tmp_path, monkeypatch)
    projects = tmp_path / "projects"
    _write_sessions(projects, n_projects=4, n_files=50, n_lines=20, models=MODELS)

    def shape(entries):
        return sorted((e.model, e.session_id, e.project_path, e.input_tokens,
                       e.output_tokens, e.cache_creation_tokens,
                       e.cache_read_tokens, e.timestamp) for e in entries)

    cold = shape(axt.load_all_claude_usage(projects))
    warm = shape(axt.load_all_claude_usage(projects))
    assert warm == cold

    cold_p = shape(axt.load_all_claude_usage(projects, project="proj-02", force_refresh=True))
    warm_p = shape(axt.load_all_claude_usage(projects, project="proj-02"))
    assert warm_p == cold_p
    assert cold_p and len(cold_p) < len(cold)


# ─── SC-PERF-003 — sort keybuilders run once per row ─────────────────────────


def _skill_rows(tmp_path: Path, n: int = 500):
    """n SkillInfo rows, half of them stored under the (patched) vault."""
    vault_skills = tmp_path / "vault" / "skills"
    vault_skills.mkdir(parents=True, exist_ok=True)
    other = tmp_path / "elsewhere"
    other.mkdir(exist_ok=True)
    rows = []
    for i in range(n):
        base = vault_skills if i % 2 == 0 else other
        d = base / f"skill-{i:04d}"
        d.mkdir(exist_ok=True)
        rows.append(_skill(f"skill-{i:04d}", d))
    return rows


def test_vault_column_sort_calls_vault_cell_once_per_row(tmp_path, monkeypatch):
    """Sorting by Vault must cost O(n) glyph computations, not O(n log n).

    Prevents: the glyph column being wired to `_by(...)` (recomputed inside
    every comparison). `_vault_cell` resolves paths on disk, so 500 rows would
    mean ~4,500 filesystem round-trips per keypress (US-TUI03 AC6).
    """
    # TC-PERF-005
    _isolate(tmp_path, monkeypatch)
    rows = _skill_rows(tmp_path, 500)
    counter = _Counter(tabs._vault_cell)
    monkeypatch.setattr("axt.tui.tabs._vault_cell", counter)

    state = axt.TuiState()
    state.ext_cache["skills"] = rows
    state.update_statuses = {}
    tabs._set_sort_state(state, "skills", "vault", False)

    out = tabs._apply_sort(state, "skills", rows)

    assert counter.n <= 500, (
        f"{counter.n} glyph computations for 500 rows — comparison-based sorting "
        "would land near 500*log2(500) ≈ 4482")
    glyphs = [tabs._vault_cell("skills", i) for i in out]
    ranks = [tabs._ON_RANK.get(g, 99) for g in glyphs]
    assert ranks == sorted(ranks), "vault-stored rows did not sort ahead of the rest"
    assert glyphs[0] == "✓" and glyphs[-1] == "─"


def test_upd_column_sort_calls_upd_cell_once_per_row(tmp_path, monkeypatch):
    """Sorting by Upd must cost O(n) marker lookups and honour _UPD_RANK order.

    Prevents: the same `_by(...)` mistake on the Upd column, and a rank table
    drift that scatters unknown rows through the list instead of grouping them
    last (US-TUI03 AC6).
    """
    # TC-PERF-006
    _isolate(tmp_path, monkeypatch)
    rows = _skill_rows(tmp_path, 500)
    US = axt.update.UpdateStatus
    statuses = {}
    for i, r in enumerate(rows[:200]):
        if i < 60:
            statuses[("skill", r.name)] = US("skill", r.name, 1, "a", "b", True)
        elif i < 130:
            statuses[("skill", r.name)] = US("skill", r.name, 1, "a", "?", False,
                                             error="fetch failed")
        else:
            statuses[("skill", r.name)] = US("skill", r.name, 1, "a", "a", False)

    counter = _Counter(tabs._upd_cell)
    monkeypatch.setattr("axt.tui.tabs._upd_cell", counter)

    state = axt.TuiState()
    state.ext_cache["skills"] = rows
    state.update_statuses = statuses
    tabs._set_sort_state(state, "skills", "upd", False)

    out = tabs._apply_sort(state, "skills", rows)

    assert counter.n <= 500, f"{counter.n} marker lookups for 500 rows"
    glyphs = [tabs._upd_cell(state, "skills", i) for i in out]
    ranks = [tabs._UPD_RANK.get(g, 99) for g in glyphs]
    assert ranks == sorted(ranks), f"Upd order violates _UPD_RANK: {glyphs[:12]}"
    assert glyphs.count("↑") == 60 and glyphs.count("!") == 70
    assert glyphs.count("─") == 300, "rows without a status must all land in the last group"


def test_proj_column_sort_reads_settings_files_twice_at_most(tmp_path, monkeypatch):
    """Sorting plugins by Proj must read the two settings files once each.

    Prevents: `_scope_ctx` being rebuilt per row, which turns one keypress into
    1,000 JSON parses at 500 plugins, and flattens the three-state
    enabled/disabled/unset ordering (US-TUI03 AC6, US-PLG01 AC3).
    """
    # TC-PERF-007
    home = _isolate(tmp_path, monkeypatch)
    proj_settings = tmp_path / ".claude" / "settings.json"
    proj_settings.parent.mkdir(parents=True, exist_ok=True)
    plugins = [
        axt.PluginInfo(id=f"p{i:03d}@mk", name=f"p{i:03d}", marketplace="mk",
                       version="1.0.0", install_path=str(tmp_path / "pi" / f"p{i}"),
                       scope="user", installed_at="", last_updated="")
        for i in range(500)
    ]
    enabled = {p.id: True for p in plugins[:150]}
    enabled.update({p.id: False for p in plugins[150:320]})
    proj_settings.write_text(json.dumps({"enabledPlugins": enabled}))
    (home / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {}}))

    counter = _Counter(tabs.read_enabled_plugins)
    monkeypatch.setattr("axt.tui.tabs.read_enabled_plugins", counter)

    state = axt.TuiState()
    state.ext_cache["plugins"] = plugins
    state.update_statuses = {}
    tabs._set_sort_state(state, "plugins", "proj", False)

    out = tabs._apply_sort(state, "plugins", plugins)

    assert counter.n <= 2, (
        f"read settings {counter.n} times — one per row means _scope_ctx moved inside the sort")
    ctx = tabs._scope_ctx(state, "plugins")
    glyphs = [tabs._scope_cell("plugins", i, "proj", ctx) for i in out]
    assert glyphs == sorted(glyphs, key=lambda g: tabs._ON_RANK.get(g, 99))
    assert glyphs.count("●") == 150 and glyphs.count("○") == 170 and glyphs.count("·") == 180


def test_every_sort_column_preserves_the_row_count(tmp_path, monkeypatch):
    """All nine Skills columns keep 500 rows, missing fields included.

    Prevents: the `{id(item): rank}` keybuilder cache — introduced for speed —
    dropping rows, which it does silently when the same object appears twice, or
    the defensive `except` fallback swallowing rows instead of the order
    (US-TUI03 AC8).
    """
    # TC-PERF-008
    _isolate(tmp_path, monkeypatch)
    rows = []
    for i in range(500):
        name = f"스킬-{i:04d}" if i % 25 == 0 else f"skill-{i:04d}"
        version = None if i % 17 == 0 else f"1.{i % 10}.0"
        rows.append(axt.SkillInfo(name=name, path=str(tmp_path / "s" / name),
                                  is_symlink=(i % 3 == 0), source="user",
                                  target=None if i % 5 else str(tmp_path / "t"),
                                  version=version))

    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = rows
    state.update_statuses = {}
    cols = [c[0] for c in tabs._SORT_COLUMNS["skills"]]
    seen = []
    for _ in cols:
        key, _desc = tabs._sort_state(state, "skills")
        seen.append(key)
        out = tabs._apply_sort(state, "skills", rows)
        assert len(out) == 500, f"column {key!r} lost rows: {len(out)}"
        assert {id(x) for x in out} == {id(x) for x in rows}, f"column {key!r} duplicated rows"
        axt.handle_extensions_input(state, ord("s"))

    assert seen == cols, "the `s` cycle did not visit every column exactly once"


# ─── SC-PERF-004 — context analysis scale ────────────────────────────────────


def _context_fixture(tmp_path: Path, monkeypatch):
    home = _isolate(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    monkeypatch.chdir(proj)

    for i in range(200):
        d = proj / ".claude" / "skills" / f"sk-{i:03d}"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: sk-{i:03d}\ndescription: d{i}\n---\nbody\n")
    for i in range(200):
        p = proj / ".claude" / "commands" / f"cmd-{i:03d}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\ndescription: c{i}\n---\ncontent\n")
    for i in range(100):
        p = proj / ".claude" / "agents" / f"ag-{i:03d}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\ndescription: a{i}\n---\ncontent\n")

    mem = home / ".claude" / "projects" / axt.core._encode_project_dir_name(proj) / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("# index\n")
    for i in range(99):
        (mem / f"m-{i:03d}.md").write_text(f"memory {i}\n")

    (home / "CLAUDE.md").write_text("global\n")
    (home / ".claude" / "CLAUDE.md").write_text("user\n")
    (proj / "CLAUDE.md").write_text("project\n")

    (home / ".claude.json").write_text(json.dumps({
        "mcpServers": {f"srv-{i:02d}": {"command": "node", "args": [f"{i}.js"]}
                       for i in range(30)},
    }))

    # Cross-agent mirrors that Claude Code never reads (US-CTX03 AC1/AC2).
    (proj / ".agents" / "skills" / "ghost").mkdir(parents=True)
    (proj / ".agents" / "skills" / "ghost" / "SKILL.md").write_text("---\nname: ghost\n---\n")
    (proj / ".agents" / "agents").mkdir(parents=True)
    (proj / ".agents" / "agents" / "ghost.md").write_text("---\ndescription: g\n---\n")

    # No shelling out for `claude --version` / `git status`.
    import subprocess as _sp
    monkeypatch.setattr(
        "axt.core.subprocess.run",
        lambda *a, **kw: _sp.CompletedProcess(a[0] if a else [], 0, "", ""))
    return home, proj


def test_context_collection_reads_each_file_at_most_once(tmp_path, monkeypatch):
    """No file on disk is read twice while collecting 600+ context sources.

    Prevents: the collector duplicating work the directory scanners already did
    — at 200 skills a second read of every SKILL.md doubles the I/O of the
    Context tab's first paint. Also pins the category counts so a scan-order
    change cannot quietly add or lose sources (US-CTX01 AC1, US-CTX03 AC1/AC2).
    """
    # TC-PERF-009
    home, proj = _context_fixture(tmp_path, monkeypatch)

    reads: dict[str, int] = {}
    original = Path.read_text

    def counting(self, *a, **kw):
        reads[str(self)] = reads.get(str(self), 0) + 1
        return original(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", counting)

    sources = axt.collect_context_sources(
        home_dir=home, project_dir=proj,
        installed_plugins_path=home / ".claude" / "ip.json")

    by_cat: dict[str, int] = {}
    for s in sources:
        by_cat[s.category] = by_cat.get(s.category, 0) + 1
    assert by_cat.get("skills") == 200
    assert by_cat.get("commands") == 200
    assert by_cat.get("agents") == 100
    assert by_cat.get("memory") == 100
    assert by_cat.get("claude-md") == 3
    assert by_cat.get("mcp-tools") == 30

    repeated = {p: n for p, n in reads.items() if n > 1}
    assert repeated == {}, (
        f"{len(repeated)} file(s) read more than once, e.g. "
        f"{sorted(repeated.items(), key=lambda kv: -kv[1])[:3]}")


# ─── SC-PERF-005 — frame render ceiling ──────────────────────────────────────


def _seed_skills_tab(state, tmp_path: Path, n: int):
    rows = [_skill(f"skill-{i:04d}", tmp_path / "s" / f"skill-{i:04d}") for i in range(n)]
    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = rows
    state.update_statuses = {}
    return rows


def test_draw_call_count_is_flat_in_row_count(tmp_path, monkeypatch):
    """Ten times the rows must not mean more drawing.

    Prevents: a renderer that formats the whole list and then slices. Only the
    viewport may be drawn, otherwise scrolling a 5,000-row Skills tab stutters
    (US-TUI10).
    """
    # TC-PERF-011
    _isolate(tmp_path, monkeypatch)

    scr50 = _make_stdscr(30, 140)
    s50 = axt.TuiState()
    _seed_skills_tab(s50, tmp_path, 50)
    axt._render_frame(scr50, s50)
    n50 = len(scr50.calls)

    scr500 = _make_stdscr(30, 140)
    s500 = axt.TuiState()
    _seed_skills_tab(s500, tmp_path, 500)
    axt._render_frame(scr500, s500)
    n500 = len(scr500.calls)

    assert n50 > 0
    assert n500 < n50 * 2, f"10x the rows produced {n500} draws vs {n50}"
    assert abs(n500 - n50) <= 5, f"draw count moved with row count: {n50} → {n500}"


def test_draw_calls_are_bounded_by_columns_not_by_screen_cells(tmp_path, monkeypatch):
    """Drawing is per column-cell, never per character cell, and stays on screen.

    Prevents: a per-character draw loop (30x140 = 4,200 addnstr calls a frame)
    and any write past the terminal bounds, which curses turns into a hard error
    on the last cell (US-TUI10 AC2).
    """
    # TC-PERF-012
    _isolate(tmp_path, monkeypatch)
    rows, cols = 30, 140
    scr = _make_stdscr(rows, cols)
    state = axt.TuiState()
    _seed_skills_tab(state, tmp_path, 500)
    axt._render_frame(scr, state)

    n_cols = len(tabs._SORT_COLUMNS["skills"])
    # Structural ceiling: at most one call per visible line per column, plus the
    # row prefix, the trailing background fill, and slack for the header /
    # filter bar / detail panel / status bar. Observed on this renderer:
    # 199 calls, well under the bound; the cell-count alternative would be
    # rows*cols = 4,200.
    ceiling = rows * (n_cols + 4)
    assert len(scr.calls) <= ceiling, f"{len(scr.calls)} draws exceeds {ceiling}"
    assert len(scr.calls) < rows * cols / 4, "draw count is at cell scale, not column scale"
    for call in scr.calls:
        y, x, _text, max_w = call[0], call[1], call[2], call[3]
        assert 0 <= y < rows, f"drew at y={y}"
        assert 0 <= x < cols, f"drew at x={x}"
        assert x + max_w <= cols, f"draw runs past the right edge: x={x} w={max_w}"


# ─── SC-PERF-006 — project scan linearity ────────────────────────────────────


def _make_projects(root: Path, projects_dir: Path, vault: Path, start: int, end: int,
                   vault_names: list[str]):
    for i in range(start, end):
        p = root / f"pj{i:03d}"
        (p / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
        axt.write_profile(p, axt.AxtProfile(skills=tuple(vault_names)))
        for name in vault_names[:2]:
            link = p / ".claude" / "skills" / name
            if not os.path.lexists(link):
                os.symlink(vault / "skills" / name, link)
        (projects_dir / str(p).replace("/", "-")).mkdir(exist_ok=True)


def test_project_scan_work_grows_linearly_with_project_count(tmp_path, monkeypatch):
    """Doubling the project count must not more than 2.2x the directory walks.

    Prevents: a per-project step that re-walks the whole vault or the whole
    projects dir — quadratic behaviour that only shows up on a machine with
    hundreds of Claude projects (US-VLT07 AC1/AC2).
    """
    # TC-PERF-013
    _isolate(tmp_path, monkeypatch)
    root = tmp_path / "code"
    root.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    vault = tmp_path / "vault"
    (vault / "skills").mkdir(parents=True)
    names = []
    for i in range(20):
        d = vault / "skills" / f"vs{i:02d}"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: v\n---\n")
        names.append(d.name)

    def measure(mode: str) -> int:
        with pytest.MonkeyPatch.context() as mp:
            counter = _count_method(mp, Path, "iterdir")
            index = axt.scan_project_usage(projects_dir, vault, mode=mode)
        assert len(index) == 20, f"index has {len(index)} entries, expected 20"
        return counter.n

    _make_projects(root, projects_dir, vault, 0, 100, names)
    d100 = measure("default")
    f100 = measure("full")
    _make_projects(root, projects_dir, vault, 100, 200, names)
    d200 = measure("default")
    f200 = measure("full")

    assert d100 > 0
    assert d200 <= d100 * 2.2, f"default mode: {d100} → {d200}"
    assert f200 <= f100 * 2.2, f"full mode: {f100} → {f200}"


def test_empty_projects_dir_scans_once_and_returns_nothing(tmp_path, monkeypatch):
    """An empty projects dir costs one listing and yields an empty index.

    Prevents: a retry/rescan loop over a directory that is legitimately empty —
    the state every new Claude user starts in (US-VLT07 AC4).
    """
    # TC-PERF-014
    # The TC doc names `iterdir`; the implementation lists the projects root
    # with `os.listdir` and only uses `Path.iterdir` per project, so both are
    # counted: exactly one root listing, zero per-project walks.
    _isolate(tmp_path, monkeypatch)
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    vault = tmp_path / "vault"
    (vault / "skills").mkdir(parents=True)
    for i in range(20):
        d = vault / "skills" / f"vs{i:02d}"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: v\n---\n")

    listdir = _Counter(os.listdir)
    monkeypatch.setattr("axt.core.os.listdir", listdir)
    iterdir = _count_method(monkeypatch, Path, "iterdir")

    index = axt.scan_project_usage(projects_dir, vault, mode="default")

    assert index == {}
    assert all(u.projects == [] for u in index.values())
    assert listdir.n == 1, f"listed the projects dir {listdir.n} times"
    assert iterdir.n == 0


# ─── SC-PERF-007 — update-check TTL ──────────────────────────────────────────


def test_only_force_bypasses_the_update_status_ttl(tmp_path, monkeypatch):
    """A fresh cached result short-circuits; only `force=True` re-sweeps.

    Prevents: the Upd column firing a network sweep on every frame (or `r`
    silently not forcing one), which is the difference between an instant list
    and a git fetch per marketplace per repaint (US-UPD05 AC2/AC3).
    """
    # TC-PERF-016
    _isolate(tmp_path, monkeypatch)
    st = axt.update.UpdateStatus("skill", "sk", 1, "a", "a", False)
    # Real clock on both sides: _update_status_fresh compares this stamp
    # against datetime.now(), so no fake clock is introduced.
    monkeypatch.setattr("axt.tui.tabs.load_cached_update_statuses",
                        lambda: ([st], axt.core._iso_now()))
    sweeps = _Counter(lambda types=None: [st])
    monkeypatch.setattr("axt.tui.tabs.check_all_updates", sweeps)
    monkeypatch.setattr("axt.tui.tabs.threading.Thread", _StubThread)
    _StubThread.started = []

    state = axt.TuiState()
    REAL_KICK_UPDATE_CHECK(state)
    assert _StubThread.started == [], "a fresh cache still started a sweep"

    REAL_KICK_UPDATE_CHECK(state, force=True)
    assert _StubThread.started == ["axt-update-check"]
    assert state.update_check_loading is True

    tabs._update_check_worker(state)

    assert state.update_check_loading is False
    assert state.update_checked_at is not None
    assert sweeps.n == 1, f"check_all_updates ran {sweeps.n} times"


def test_disk_cached_update_statuses_still_render_their_original_glyphs(tmp_path, monkeypatch):
    """Restoring the cache must reproduce ↑ / · / ! exactly, not flatten to ─.

    Prevents: a cache field dropping out of the schema so an available update
    comes back looking up to date after a restart — the user never sees the
    update exists (US-UPD05 AC2).
    """
    # TC-PERF-017
    _isolate(tmp_path, monkeypatch)
    US = axt.update.UpdateStatus
    statuses = [
        US("skill", "up", 1, "1.0.0", "1.1.0", True, note="git"),
        US("skill", "ok", 1, "1.0.0", "1.0.0", False, note="up to date"),
        US("skill", "err", 1, "1.0.0", "?", False, note="", error="fetch failed"),
    ]
    axt.update.save_cached_update_statuses(statuses, axt.core._iso_now())
    monkeypatch.setattr("axt.tui.tabs.load_cached_update_statuses",
                        axt.update.load_cached_update_statuses)
    monkeypatch.setattr("axt.tui.tabs.threading.Thread", _StubThread)
    _StubThread.started = []

    state = axt.TuiState()
    REAL_KICK_UPDATE_CHECK(state)

    items = [_skill(n, tmp_path / n) for n in ("up", "ok", "err")]
    assert [tabs._upd_cell(state, "skills", i) for i in items] == ["↑", "·", "!"]

    restored = {(s.item_type, s.name): s for s in statuses}
    for key, original in restored.items():
        got = state.update_statuses[key]
        assert (got.tier, got.current, got.available, got.note, got.error) == (
            original.tier, original.current, original.available,
            original.note, original.error)


# ─── SC-PERF-008 — single-pass search ────────────────────────────────────────


def test_search_over_2000_rows_is_a_single_filtered_pass(tmp_path, monkeypatch):
    """Filtering 2,000 rows builds each haystack once and sorts once.

    Prevents: a second haystack build or a re-sort after filtering — this path
    runs on every keystroke of `/`, so double work is felt as typing lag from a
    few hundred rows up (US-TUI04 AC2).

    Machine assumption: any 2020-or-later dev laptop / 2-vCPU CI runner with an
    SSD. The 1s ceiling is >10x the observed median, so only an algorithmic
    regression trips it.
    """
    # TC-PERF-018
    _isolate(tmp_path, monkeypatch)
    rows = [_skill(f"skill-{i:04d}", tmp_path / "s" / f"skill-{i:04d}") for i in range(2000)]
    expected = sum(1 for r in rows if "77" in r.name)
    assert expected > 0, "fixture produced no matches"

    hay = _Counter(tabs._subtab_search_haystack)
    monkeypatch.setattr("axt.tui.tabs._subtab_search_haystack", hay)
    srt = _Counter(tabs._apply_sort)
    monkeypatch.setattr("axt.tui.tabs._apply_sort", srt)

    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = rows
    state.update_statuses = {}
    state.ext_search["skills"] = "77"

    t0 = time.perf_counter()
    out = tabs._subtab_view(state, "skills")
    elapsed = time.perf_counter() - t0

    assert len(out) == expected
    assert hay.n <= 2000, f"built {hay.n} haystacks for 2000 rows"
    assert srt.n == 1, f"sorted {srt.n} times — filtering must not trigger a re-sort"
    names = [s.name for s in out]
    assert names == sorted(names), "the filtered view lost the active sort order"
    assert elapsed < 1.0, f"took {elapsed:.3f}s"
