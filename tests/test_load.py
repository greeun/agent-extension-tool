"""Load / stress layer — large fixtures, thread contention, input floods.

Layer Owner (tests/doc/TEST_DEDUP_POLICY.md §2): "스레드 경합·대량 항목".

Determinism rules honoured here (tests/doc/testcases/load-stress-testcases.md):
threads are sequenced with `Event`/`Barrier` and always reclaimed with
`join(timeout=...)` — never `sleep`-and-hope; every fixture lives under
`tmp_path`; no test reads the real `~/.claude`; the clock is never faked (the
few date-sensitive fixtures are generated from the real clock so file mtimes
and timestamps stay consistent).
"""
from __future__ import annotations

import csv
import io
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import axt
import axt.tui.tabs as tabs

from axt.tui.tabs import _kick_update_check as REAL_KICK_UPDATE_CHECK  # noqa: E402


MODELS = ("claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5", "claude-fable-5")


# ─── helpers ─────────────────────────────────────────────────────────────────


def _make_stdscr(rows: int = 30, cols: int = 140):
    scr = MagicMock()
    scr.getmaxyx.return_value = (rows, cols)
    scr.calls = []
    scr.addnstr.side_effect = lambda *a: scr.calls.append(a)
    return scr


def _flat(scr) -> str:
    return "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))


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
        projects=tmp_path / "projects",
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


def _write_10k_entries(projects: Path, *, project_names=None, t0=None,
                       step=timedelta(minutes=1)):
    """10 projects x 20 session files x 50 lines = 10,000 usage entries.

    Values are index-derived (no RNG) and the expected totals are accumulated
    in this loop — never by calling the loader we are about to test.
    """
    if t0 is None:
        t0 = datetime(2026, 1, 5, tzinfo=timezone.utc)
    names = project_names or [f"proj-{p:02d}" for p in range(10)]
    exp = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0,
           "count": 0, "by_model": {}, "sessions": set()}
    i = 0
    for name in names:
        pdir = projects / name
        pdir.mkdir(parents=True, exist_ok=True)
        for f in range(20):
            sid = f"{name}-{f:03d}"
            lines = []
            for _ in range(50):
                model = MODELS[i % 4]
                inp = (i % 997) + 1
                out = (i % 389) + 1
                cc = i % 53
                cr = i % 211
                ts = (t0 + step * i).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                lines.append(json.dumps({
                    "type": "assistant", "sessionId": sid, "timestamp": ts,
                    "message": {"model": model, "usage": {
                        "input_tokens": inp, "output_tokens": out,
                        "cache_creation_input_tokens": cc,
                        "cache_read_input_tokens": cr,
                    }},
                }))
                exp["input"] += inp
                exp["output"] += out
                exp["cache_create"] += cc
                exp["cache_read"] += cr
                exp["by_model"][model] = exp["by_model"].get(model, 0) + 1
                exp["count"] += 1
                i += 1
            exp["sessions"].add(sid)
            (pdir / f"{f:03d}.jsonl").write_text("\n".join(lines) + "\n")
    return exp


def _skill(name: str, path: Path, *, version="1.0.0", source="user"):
    return axt.SkillInfo(name=name, path=str(path), is_symlink=False,
                         source=source, version=version)


# ─── SC-LOAD-001 — large usage aggregation ───────────────────────────────────


def test_ten_thousand_entries_aggregate_to_the_exact_fixture_totals(tmp_path, monkeypatch):
    """All four token kinds sum exactly across 10,000 entries and 4 models.

    Prevents: an off-by-one in the v2 cache's intern tables billing one model's
    tokens to another. The tables accumulate across 200 files, so only a
    multi-file, multi-model fixture can expose a shifted index (US-USG01 AC1).
    """
    # TC-LOAD-001
    _isolate(tmp_path, monkeypatch)
    projects = tmp_path / "projects"
    exp = _write_10k_entries(projects)

    entries = axt.load_all_claude_usage(projects)

    assert len(entries) == 10_000
    assert sum(e.input_tokens for e in entries) == exp["input"]
    assert sum(e.output_tokens for e in entries) == exp["output"]
    assert sum(e.cache_creation_tokens for e in entries) == exp["cache_create"]
    assert sum(e.cache_read_tokens for e in entries) == exp["cache_read"]

    by_model: dict[str, int] = {}
    for e in entries:
        by_model[e.model] = by_model.get(e.model, 0) + 1
    assert by_model == exp["by_model"]
    assert all(v == 2500 for v in by_model.values())
    assert {e.session_id for e in entries} == exp["sessions"]
    assert len(exp["sessions"]) == 200


def test_export_flags_stay_well_formed_at_ten_thousand_entries(tmp_path, monkeypatch, capsys):
    """`usage week --json` parses and `--csv` keeps one column count everywhere.

    Prevents: a value with a comma or a quote (a project name, a formatted cost)
    breaking downstream spreadsheet imports at a scale nobody hand-checks
    (US-USG03 AC1/AC2).

    Command note: the TC doc names `usage month`, but `--json` / `--csv` are
    implemented on `today` / `week` only (see the argparse help text), so
    asserting on `month` would pass without exercising either exporter — a
    false positive under policy §4. `week` is used instead.
    """
    # TC-LOAD-002
    _isolate(tmp_path, monkeypatch)
    projects = tmp_path / "projects"
    # Anchor on the real clock: `usage week` derives its window from
    # datetime.now(), so a hard-coded base date would filter everything out.
    # 5.5 days ago + 10,000 * 30s (~3.5 days) stays inside [7 days ago, today)
    # even if the configured timezone shifts either boundary by a day.
    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    t0 = midnight - timedelta(days=5, hours=12)
    names = [f"proj-{p:02d}" for p in range(9)] + ['proj,with"quote']
    _write_10k_entries(projects, project_names=names, t0=t0, step=timedelta(seconds=30))

    rc_json = axt.main(["usage", "week", "--json"])
    json_out = capsys.readouterr().out
    parsed = json.loads(json_out)

    rc_csv = axt.main(["usage", "week", "--csv"])
    csv_out = capsys.readouterr().out
    rows = list(csv.reader(io.StringIO(csv_out)))
    rows = [r for r in rows if r]

    assert rc_json == 0 and rc_csv == 0
    assert isinstance(parsed, (dict, list)) and parsed, "empty export — the fixture never landed"
    assert "\x1b[" not in json_out, "ANSI colour leaked into machine-readable output"
    assert len(rows) > 1, "CSV has no data rows"
    assert len({len(r) for r in rows}) == 1, (
        f"ragged CSV: column counts {sorted({len(r) for r in rows})}")


def test_empty_projects_dir_reports_zero_usage_and_exits_zero(tmp_path, monkeypatch, capsys):
    """No usage data is a normal state, not an error.

    Prevents: a fresh install treating "nothing recorded yet" as a failure.
    Also the control group for TC-LOAD-001: without it, a fixture that silently
    failed to write would still "pass" a totals-are-zero assertion
    (US-USG01 AC3).
    """
    # TC-LOAD-003
    _isolate(tmp_path, monkeypatch)
    (tmp_path / "projects").mkdir()

    rc = axt.main(["usage", "today"])
    cap = capsys.readouterr()

    assert rc == 0
    assert "✗" not in cap.out
    assert "No usage data" in cap.out
    assert cap.err == ""


# ─── SC-LOAD-002 — bulk items ────────────────────────────────────────────────


def _diverse_names(prefix: str, n: int, suffix: str = "") -> list[str]:
    """n names covering ASCII / 80-char / Hangul / spaces / digit-leading."""
    names = []
    for i in range(n):
        bucket = i % 5
        if bucket == 0:
            core = f"{prefix}-{i:03d}"
        elif bucket == 1:
            core = (f"{prefix}-long-{i:03d}-" + "x" * 80)[:80]
        elif bucket == 2:
            core = f"한글{prefix}-{i:03d}"
        elif bucket == 3:
            core = f"{prefix} with space {i:03d}"
        else:
            core = f"{i:03d}-{prefix}-starts-with-digit"
        names.append(core + suffix)
    return names


def _build_vault(tmp_path: Path) -> tuple[Path, dict[str, list[str]]]:
    vault = tmp_path / "vault"
    made: dict[str, list[str]] = {}
    skills = _diverse_names("skill", 300)
    for name in skills:
        d = vault / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: s\ndescription: d\nversion: 1.0.0\n---\n")
    made["skill"] = skills
    for sub, type_, count in (("commands", "command", 100), ("agents", "agent", 100)):
        names = _diverse_names(type_, count, suffix=".md")
        (vault / sub).mkdir(parents=True, exist_ok=True)
        for name in names:
            (vault / sub / name).write_text("---\ndescription: d\nversion: 1.0.0\n---\n")
        made[type_] = names
    return vault, made


@pytest.mark.skipif(os.name == "nt", reason="symlink state needs POSIX symlinks")
def test_five_hundred_vault_items_enumerate_by_type_with_names_intact(tmp_path, monkeypatch):
    """500 vault items list as 300/100/100 with link state only where linked.

    Prevents: a scanner that trims whitespace, normalizes Unicode or drops
    unusual names — the item would vanish from `vault list` while its symlink
    stayed on disk, so the user could never unlink it (US-VLT02 AC1).
    """
    # TC-LOAD-004
    _isolate(tmp_path, monkeypatch)
    vault, made = _build_vault(tmp_path)
    proj = tmp_path / "proj"
    (proj / ".claude" / "skills").mkdir(parents=True)
    claude_dir = tmp_path / "home" / ".claude"
    (claude_dir / "skills").mkdir(parents=True, exist_ok=True)

    linked_project = made["skill"][:3]
    linked_global = made["skill"][3:6]
    for name in linked_project:
        os.symlink(vault / "skills" / name, proj / ".claude" / "skills" / name)
    for name in linked_global:
        os.symlink(vault / "skills" / name, claude_dir / "skills" / name)

    items = axt.list_vault_items(vault)
    by_type: dict[str, list] = {}
    for it in items:
        by_type.setdefault(it.type, []).append(it)

    assert len(items) == 500
    assert len(by_type["skill"]) == 300
    assert len(by_type["command"]) == 100
    assert len(by_type["agent"]) == 100
    # Names must come back byte-for-byte as they sit on disk.
    assert {i.name for i in by_type["skill"]} == set(os.listdir(vault / "skills"))
    assert {i.name for i in by_type["command"]} == set(os.listdir(vault / "commands"))
    for probe in (made["skill"][2], made["skill"][3]):
        assert any(i.name == probe for i in by_type["skill"]), f"lost name {probe!r}"

    enriched = axt.list_vault_items_with_project_state(vault, proj, claude_dir)
    assert len(enriched) == 500
    got_project = {i.name for i in enriched if i.is_linked}
    got_global = {i.name for i in enriched if i.is_global_linked}
    assert got_project == set(linked_project)
    assert got_global == set(linked_global)


def test_vault_sort_cycle_keeps_all_500_rows(tmp_path, monkeypatch):
    """Every Vault sort column returns 500 rows and the cycle returns home.

    Prevents: a keybuilder raising on a missing field and silently emptying the
    list, and `Ver ▲` floating version-less rows to the top where they hide the
    real oldest entries (US-TUI03 AC7/AC8).
    """
    # TC-LOAD-005
    _isolate(tmp_path, monkeypatch)
    vault, _made = _build_vault(tmp_path)
    items = axt.list_vault_items(vault)
    assert len(items) == 500
    for i, it in enumerate(items):
        if i % 17 == 0:
            it.version = None
        if i % 13 == 0:
            it.description = ""
        if i % 25 == 0:
            it.updated_at = None

    state = axt.TuiState()
    state.ext_sub_tab = "vault"
    state.vault_items = items
    keys = [c[0] for c in tabs._SORT_COLUMNS["vault"]]
    seen = []
    for _ in keys:
        key, _desc = tabs._sort_state(state, "vault")
        seen.append(key)
        out = tabs._apply_sort(state, "vault", items)
        assert len(out) == 500, f"column {key!r} returned {len(out)} rows"
        axt.handle_extensions_input(state, ord("s"))

    assert seen == keys
    assert tabs._sort_state(state, "vault")[0] == keys[0], "the cycle did not wrap to `name`"

    tabs._set_sort_state(state, "vault", "ver", False)
    ordered = tabs._apply_sort(state, "vault", items)
    missing = [i for i, it in enumerate(ordered) if not it.version]
    assert missing and min(missing) >= 500 - len(missing), (
        "version-less rows must sort last in ascending Ver order")


def test_search_survives_sort_changes_and_stays_per_subtab(tmp_path, monkeypatch):
    """A filtered view keeps its 47 matches across sort changes and per sub-tab.

    Prevents: the sort path re-reading the unfiltered cache (row count jumps
    back to 500 mid-session) and one sub-tab's query bleeding into another
    (US-TUI04 AC2).

    Uses the Skills sub-tab rather than Vault because per-sub-tab query
    isolation — the actual acceptance criterion — only exists in `ext_search`;
    Vault owns a single `vault_search` field.
    """
    # TC-LOAD-006
    _isolate(tmp_path, monkeypatch)
    rows = []
    for i in range(500):
        name = f"alpha-{i:03d}" if i < 47 else f"beta-{i:03d}"
        rows.append(_skill(name, tmp_path / "s" / name))
    expected = sum(1 for r in rows if "alpha" in r.name)
    assert expected == 47

    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = rows
    state.ext_cache["commands"] = []
    state.update_statuses = {}

    state.ext_search["skills"] = "alpha"
    assert len(tabs._subtab_view(state, "skills")) == expected

    for _ in range(3):
        axt.handle_extensions_input(state, ord("s"))
        assert len(tabs._subtab_view(state, "skills")) == expected, (
            "changing the sort column changed the match count")

    assert state.ext_search.get("commands") is None, "the query leaked to another sub-tab"

    state.ext_search.pop("skills")
    assert len(tabs._subtab_view(state, "skills")) == 500


# ─── SC-LOAD-003 — daemon thread concurrency ─────────────────────────────────


def _stub_three_workers(monkeypatch, barrier, markers):
    """Replace the three background jobs with barrier-synchronised stubs."""
    def vault_scan(projects, vault, *, mode="default"):
        barrier.wait(timeout=5)
        return markers["vault"]

    def usage_load(**kw):
        barrier.wait(timeout=5)
        return markers["usage"]

    def update_check(types=None):
        barrier.wait(timeout=5)
        return markers["update"]

    monkeypatch.setattr("axt.tui.tabs.scan_project_usage", vault_scan)
    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", usage_load)
    monkeypatch.setattr("axt.tui.tabs.check_all_updates", update_check)
    monkeypatch.setattr("axt.tui.tabs.analyze_context", lambda **kw: None)
    monkeypatch.setattr("axt.tui.tabs.detect_current_model",
                        lambda *a, **kw: "claude-sonnet-5")
    monkeypatch.setattr("axt.tui.tabs._save_scan_cache", lambda index, mode: None)


def _markers():
    return {
        "vault": {"skill:vaultmarker": axt.ExtensionUsage(
            type="skill", name="vaultmarker",
            projects=[axt.ProjectRef(path="/p1", name="p1")])},
        "usage": [
            axt.claude_to_unified(axt.ClaudeUsageEntry(
                model="claude-sonnet-5", input_tokens=11, output_tokens=22,
                cache_creation_tokens=0, cache_read_tokens=0,
                session_id=f"sess-{i}", project_path="p",
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")))
            for i in range(3)
        ],
        "update": [
            axt.update.UpdateStatus("skill", "upmarker", 1, "1.0.0", "2.0.0", True),
            axt.update.UpdateStatus("skill", "okmarker", 1, "1.0.0", "1.0.0", False),
        ],
    }


def _join_all(state):
    for attr in ("vault_scan_thread", "usage_load_thread", "update_check_thread"):
        t = getattr(state, attr)
        assert t is not None, f"{attr} was never started"
        t.join(timeout=5)
        assert not t.is_alive(), f"{attr} did not finish"


def test_three_daemon_workers_all_clear_their_loading_flags(tmp_path, monkeypatch):
    """Three simultaneous background workers each reset their loading flag.

    Prevents: a missing `finally` leaving a flag True forever, which makes
    `_has_background_work` permanently true and pins the TUI to a 100ms repaint
    loop that burns CPU with nothing left to show (US-UPD05 AC4).
    """
    # TC-LOAD-007
    _isolate(tmp_path, monkeypatch)
    barrier = threading.Barrier(3)
    _stub_three_workers(monkeypatch, barrier, _markers())

    state = axt.TuiState()
    tabs._kick_vault_scan(state)
    tabs._kick_usage_reload(state)
    REAL_KICK_UPDATE_CHECK(state, force=True)

    _join_all(state)

    assert state.vault_scan_loading is False
    assert state.usage_loading is False
    assert state.update_check_loading is False


def test_three_daemon_workers_do_not_overwrite_each_others_results(tmp_path, monkeypatch):
    """Each worker's distinct marker survives the other two finishing.

    Prevents: a shared-state write pattern where the last worker to land clears
    or replaces a sibling's result — the user sees the Used column reset the
    moment the update sweep lands (US-UPD05 AC4).
    """
    # TC-LOAD-008
    _isolate(tmp_path, monkeypatch)
    barrier = threading.Barrier(3)
    markers = _markers()
    _stub_three_workers(monkeypatch, barrier, markers)

    state = axt.TuiState()
    tabs._kick_vault_scan(state)
    tabs._kick_usage_reload(state)
    REAL_KICK_UPDATE_CHECK(state, force=True)
    _join_all(state)

    assert "skill:vaultmarker" in state.vault_usage_index
    assert state.usage_entries == markers["usage"]
    assert set(state.update_statuses) == {("skill", "upmarker"), ("skill", "okmarker")}

    # All three results must still be reachable from one live render pass.
    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")
    state.ext_sub_tab = "vault"
    state.vault_items = [axt.VaultItem(name="vaultmarker", type="skill",
                                       path=str(tmp_path / "v"), description="")]
    scr = _make_stdscr(40, 160)
    axt._render_frame(scr, state)
    assert "vaultmarker" in _flat(scr)

    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = [_skill("upmarker", tmp_path / "upmarker")]
    scr2 = _make_stdscr(40, 160)
    axt._render_frame(scr2, state)
    assert "↑" in _flat(scr2), "the update sweep's marker never reached the Upd column"

    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "usage")
    state.usage_config = axt.load_config(axt.AXT_CONFIG_PATH)
    scr3 = _make_stdscr(40, 160)
    axt._render_frame(scr3, state)
    assert "Loading Claude usage" not in _flat(scr3)


def test_worker_only_clears_the_status_line_it_wrote(tmp_path, monkeypatch):
    """A worker must not wipe a status message the main loop wrote after it.

    Prevents: losing the "Theme: light" style feedback the moment a background
    load finishes — and the mirror bug, a loading message that never clears
    (US-UPD05 AC4).
    """
    # TC-LOAD-009
    _isolate(tmp_path, monkeypatch)
    gate = threading.Event()
    started = threading.Event()

    def gated_load(**kw):
        started.set()
        gate.wait(timeout=5)
        return []

    monkeypatch.setattr("axt.tui.tabs.load_unified_usage", gated_load)
    monkeypatch.setattr("axt.tui.tabs.analyze_context", lambda **kw: None)
    monkeypatch.setattr("axt.tui.tabs.detect_current_model", lambda *a, **kw: "claude-sonnet-5")

    # Case 1: the main loop overwrites the status while the worker is in flight.
    state = axt.TuiState()
    tabs._kick_usage_reload(state)
    assert started.wait(timeout=5)
    assert state.status == "Loading Claude usage…"
    tabs.set_status(state, "Theme: light")
    stamp = state.status_set_at
    gate.set()
    state.usage_load_thread.join(timeout=5)
    assert not state.usage_load_thread.is_alive()

    assert state.status == "Theme: light", "the worker clobbered a newer status"
    assert state.status_set_at == stamp, "status timestamp drifted from the status text"

    # Case 2: nobody else wrote — the worker clears its own loading message.
    gate.clear()
    started.clear()
    state2 = axt.TuiState()
    tabs._kick_usage_reload(state2)
    assert started.wait(timeout=5)
    gate.set()
    state2.usage_load_thread.join(timeout=5)
    assert state2.status == ""
    assert state2.status_set_at is None


# ─── SC-LOAD-004 — input floods ──────────────────────────────────────────────


def test_navigation_key_flood_never_leaves_the_selection_out_of_range(tmp_path, monkeypatch):
    """500 j / k / PgDn presses keep the selection inside [0, len-1] every step.

    Prevents: an unclamped index that resolves to the wrong row (or IndexErrors)
    when a user leans on a nav key — the row acted on would not be the row
    highlighted (US-TUI03 AC2).
    """
    # TC-LOAD-010
    _isolate(tmp_path, monkeypatch)
    rows = [_skill(f"skill-{i:03d}", tmp_path / "s" / f"skill-{i:03d}") for i in range(200)]
    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.focused_layer = "content"
    state.ext_cache["skills"] = rows
    state.ext_selected["skills"] = 0
    state.update_statuses = {}

    import curses

    def press(key, times):
        for _ in range(times):
            axt.handle_extensions_input(state, key)
            sel = state.ext_selected["skills"]
            assert 0 <= sel < len(rows), f"selection escaped to {sel}"

    press(ord("j"), 500)
    assert state.ext_selected["skills"] == 199
    press(ord("k"), 500)
    assert state.ext_selected["skills"] == 0
    press(curses.KEY_NPAGE, 100)
    assert state.ext_selected["skills"] == 199


def test_sort_key_flood_lands_on_the_expected_column_in_its_default_direction(tmp_path, monkeypatch):
    """500 `s` presses land on column 500 % 9 with that column's default order.

    Prevents: `s` inheriting the direction a previous `S` flipped, so arriving
    at Updated shows oldest-first — and the header arrow disagreeing with the
    real order (US-TUI03 AC4/AC5).
    """
    # TC-LOAD-011
    _isolate(tmp_path, monkeypatch)
    rows = [_skill(f"skill-{i:03d}", tmp_path / "s" / f"skill-{i:03d}") for i in range(200)]
    state = axt.TuiState()
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = rows
    state.update_statuses = {}

    cols = tabs._SORT_COLUMNS["skills"]
    assert tabs._sort_state(state, "skills") == (cols[0][0], cols[0][2])

    axt.handle_extensions_input(state, ord("S"))
    assert tabs._sort_state(state, "skills")[1] is not cols[0][2]

    for _ in range(500):
        axt.handle_extensions_input(state, ord("s"))

    expected_col = cols[500 % len(cols)]
    key, desc = tabs._sort_state(state, "skills")
    assert key == expected_col[0]
    assert desc == expected_col[2], "the flipped direction leaked into the new column"
    assert len(tabs._subtab_view(state, "skills")) == 200

    label = tabs.subtab_sort_label(state, "skills")
    assert label == f"{key} {'▼' if desc else '▲'}"
    if expected_col[1]:
        marked = tabs._mark_sorted_column(
            state, "skills",
            [tabs.TableColumn(expected_col[1], expected_col[1].title(), 8)])
        assert ("▼" if desc else "▲") in marked[0].label


def test_detail_scroll_flood_clamps_to_the_content_and_resets_on_selection(tmp_path, monkeypatch):
    """Detail scroll pins at the content end and returns to 0 on k / reselect.

    Prevents: a held j scrolling the detail panel into blank space (and never
    coming back), and a stale offset carrying over when the user moves to a
    different row (US-TUI05 AC3/AC4).
    """
    # TC-LOAD-012
    _isolate(tmp_path, monkeypatch)
    import curses

    long_desc = "\n".join(f"detail line {i:02d}" for i in range(40))
    rows = [
        axt.CommandInfo(name="big", source="user",
                        source_path=str(tmp_path / "c" / "big.md"),
                        description=long_desc, content=""),
        axt.CommandInfo(name="small", source="user",
                        source_path=str(tmp_path / "c" / "small.md"),
                        description="short", content=""),
    ]
    state = axt.TuiState()
    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")
    state.ext_sub_tab = "commands"
    state.ext_cache["commands"] = rows
    state.ext_selected["commands"] = 0
    state.update_statuses = {}

    axt.handle_extensions_input(state, ord("\t"))
    assert state.ext_detail_focused is True

    def flood(key, times):
        for _ in range(times):
            axt.handle_extensions_input(state, key)
        axt._render_frame(_make_stdscr(40, 160), state)   # render clamps + writes back

    flood(ord("j"), 500)
    pinned = state.ext_detail_scroll
    # 40 description lines + at most a handful of other detail fields; the
    # exact viewport height is the renderer's business, so only the
    # content-bounded ceiling is asserted (never the 500 keypresses).
    assert 0 < pinned <= 50, f"scroll offset {pinned} is not content-bounded"

    flood(curses.KEY_NPAGE, 100)
    assert state.ext_detail_scroll == pinned, "PgDn scrolled past the end of the content"

    flood(ord("k"), 500)
    assert state.ext_detail_scroll == 0

    flood(ord("j"), 500)
    assert state.ext_detail_scroll == pinned
    axt.handle_extensions_input(state, ord("\t"))   # blur back to the list
    axt.handle_extensions_input(state, ord("j"))    # move the selection
    assert state.ext_selected["commands"] == 1
    assert state.ext_detail_scroll == 0, "detail scroll survived a selection change"


def test_marks_survive_sort_and_search_and_esc_peels_them_off_first(tmp_path, monkeypatch):
    """200 marks survive re-sorting and filtering; Esc drops marks before search.

    Prevents: marks keyed by screen position — one re-sort and `U` (bulk unlink)
    would act on entirely different extensions, which is data loss, not a
    cosmetic bug (US-VLT08 AC3/AC4).
    """
    # TC-LOAD-013
    _isolate(tmp_path, monkeypatch)
    from axt.tui.widgets import KEY_ESC

    rows = []
    for i in range(200):
        name = f"alpha-{i:03d}" if i < 47 else f"beta-{i:03d}"
        rows.append(_skill(name, tmp_path / "s" / name))
    state = axt.TuiState()
    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")
    state.ext_sub_tab = "skills"
    state.ext_cache["skills"] = rows
    state.ext_selected["skills"] = 0
    state.update_statuses = {}

    for _ in range(200):
        axt.handle_extensions_input(state, ord(" "))
        axt.handle_extensions_input(state, ord("j"))
    assert len(state.ext_marked["skills"]) == 200

    for _ in range(3):
        axt.handle_extensions_input(state, ord("s"))
        assert len(state.ext_marked["skills"]) == 200, "a re-sort dropped marks"

    axt.handle_extensions_input(state, ord("/"))
    for ch in "alpha":
        axt.handle_extensions_input(state, ord(ch))
    axt.handle_extensions_input(state, 10)   # Enter applies
    assert state.ext_search["skills"] == "alpha"
    assert len(tabs._subtab_view(state, "skills")) == 47
    assert len(state.ext_marked["skills"]) == 200, "filtering dropped off-screen marks"

    scr = _make_stdscr(40, 160)
    axt._render_frame(scr, state)
    assert "marked=200" in _flat(scr)

    # Esc order (US-VLT08 AC4): marks first, then the search filter.
    axt.handle_extensions_input(state, KEY_ESC)
    assert state.ext_marked["skills"] == set()
    assert state.ext_search.get("skills") == "alpha", "Esc cleared the search before the marks"
    assert len(tabs._subtab_view(state, "skills")) == 47

    axt.handle_extensions_input(state, KEY_ESC)
    assert state.ext_search.get("skills") in (None, "")
    assert len(tabs._subtab_view(state, "skills")) == 200


# ─── SC-LOAD-005 — concurrent writes ─────────────────────────────────────────


PAYLOADS = {
    "W1": {"who": "W1", "pad": "1" * 10},
    "W2": {"who": "W2", "pad": "2" * 1_000},
    "W3": {"who": "W3", "pad": "3" * 20_000},
    "W4": {"who": "W4", "pad": "4" * 100_000},
}


def _run_write_rounds(target: Path, rounds: int = 30) -> list[dict]:
    """Four writers race on `target` for `rounds` rounds; return what each
    round left behind (raises if a reader ever saw a partial write)."""
    barrier = threading.Barrier(len(PAYLOADS))
    errors: list[BaseException] = []
    observed: list[dict] = []

    def writer(which: str) -> None:
        try:
            barrier.wait(timeout=5)
            axt.write_json_atomic(target, PAYLOADS[which])
        except BaseException as exc:  # noqa: BLE001 — reported by the caller
            errors.append(exc)

    for _ in range(rounds):
        barrier.reset()
        threads = [threading.Thread(target=writer, args=(w,)) for w in PAYLOADS]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            assert not t.is_alive(), "a writer thread hung"
        observed.append(json.loads(target.read_text()))

    assert errors == [], f"writer raised: {errors[0]!r}"
    return observed


def test_four_concurrent_writers_never_produce_a_blended_file(tmp_path):
    """Every round leaves exactly one of the four payloads, whole.

    Prevents: axt's pre-`os.replace` work (mkdir, `.bak` copy, temp creation)
    racing between the TUI's background writers. `os.replace` atomicity is the
    OS's promise; the ordering around it is axt's (US-SYS04 AC3).
    """
    # TC-LOAD-014
    target = tmp_path / "cache.json"
    for data in _run_write_rounds(target):
        assert data["who"] in PAYLOADS
        assert len(data["pad"]) == len(PAYLOADS[data["who"]]["pad"]), (
            f"content blended: who={data['who']} pad={len(data['pad'])}")


def test_concurrent_writes_leave_no_temp_files_and_a_valid_backup(tmp_path):
    """After the race there are no `.tmp-*` leftovers and `.bak` still parses.

    Prevents: temp files accumulating in the user's config dir, and the
    best-effort `.bak` copy (wrapped in `except OSError: pass`) silently
    capturing half a file — a backup that cannot be restored from
    (US-SYS04 AC2).
    """
    # TC-LOAD-015
    target = tmp_path / "cache.json"
    _run_write_rounds(target)

    assert list(tmp_path.glob(".tmp-*.json")) == []
    bak = target.with_suffix(".json.bak")
    assert bak.exists(), "no backup was produced across 30 contended rounds"
    data = json.loads(bak.read_text())
    assert data["who"] in PAYLOADS
    assert len(data["pad"]) == len(PAYLOADS[data["who"]]["pad"]), "the backup is half-written"


# ─── SC-LOAD-006 — extreme field lengths ─────────────────────────────────────


def test_two_thousand_character_fields_do_not_break_the_layout(tmp_path, monkeypatch):
    """Oversized names/paths/descriptions render inside bounds at two sizes.

    Prevents: a long value pushing later columns off their x positions (the
    table stops being readable), a draw running past the right edge, and an
    embedded newline in a cell moving the cursor onto the next row and
    corrupting it (US-TUI10 AC2).
    """
    # TC-LOAD-016
    _isolate(tmp_path, monkeypatch)
    import curses

    deep = "/" + "/".join(f"seg{i:03d}" for i in range(250))
    rows = [
        axt.CommandInfo(name="r1", source="user", source_path=str(tmp_path / "r1.md"),
                        description="x" * 2000, content=""),
        axt.CommandInfo(name="r2", source="user", source_path=deep[:2000],
                        description="d2", content=""),
        axt.CommandInfo(name="r3" + "n" * 498, source="user",
                        source_path=str(tmp_path / "r3.md"), description="d3", content=""),
        axt.CommandInfo(name="r4", source="user", source_path=str(tmp_path / "r4.md"),
                        description="line1\nline2\tTAB\x01CTRL", content=""),
    ]
    state = axt.TuiState()
    state.tab_idx = next(i for i, t in enumerate(axt.MAIN_TABS) if t[0] == "extensions")
    state.ext_sub_tab = "commands"
    state.ext_cache["commands"] = rows
    state.ext_selected["commands"] = 0
    state.update_statuses = {}

    for h, w in ((30, 140), (6, 31)):
        scr = _make_stdscr(h, w)
        axt._render_frame(scr, state)
        assert scr.calls, f"nothing drawn at {h}x{w}"
        for y, x, text, max_w, *_rest in scr.calls:
            assert 0 <= y < h and 0 <= x < w, f"{h}x{w}: drew outside at ({y},{x})"
            assert x + max_w <= w, f"{h}x{w}: draw runs past the edge x={x} w={max_w}"
            assert "\n" not in text and "\r" not in text, (
                f"{h}x{w}: a row-breaking control character reached addnstr: {text!r}")

    # Column x positions must not depend on the row's content length.
    scr = _make_stdscr(30, 140)
    axt._render_frame(scr, state)
    by_y: dict[int, list[int]] = {}
    for y, x, *_ in scr.calls:
        by_y.setdefault(y, []).append(x)
    row_shapes = [tuple(v) for v in by_y.values() if len(v) > 5]
    assert len(set(row_shapes)) == 1, (
        f"long values shifted later columns: {sorted(set(row_shapes))[:2]}")

    # Detail panel + search stay well behaved on the oversized row.
    axt.handle_extensions_input(state, ord("\t"))
    for _ in range(20):
        axt.handle_extensions_input(state, curses.KEY_NPAGE)
    axt._render_frame(_make_stdscr(30, 140), state)
    assert state.ext_detail_scroll <= 2100

    state.ext_search["commands"] = "xxxx"
    assert [c.name for c in tabs._subtab_view(state, "commands")] == []
