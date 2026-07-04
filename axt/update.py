#!/usr/bin/env python3
"""axt — Agent eXtension Tool — update orchestration (Section 4.5).

A per-type Updater registry over the extension inventory. Two entry points:
``check_all_updates`` (dry-run report) and ``apply_updates`` (perform).
Capability tiers: 1 auto-apply, 2 report-only, 3 delegate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from axt.core import (
    PATHS,
    list_marketplaces,
    get_marketplace_version,
    sync_marketplace,
    pooled_map,
)


# ── Section 4.5: Update orchestration ───────────────────────────────────────

@dataclass(frozen=True)
class UpdateStatus:
    item_type: str
    name: str
    tier: int
    current: str
    available: str
    updatable: bool
    note: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class UpdateResult:
    item_type: str
    name: str
    before: str
    after: str
    updated: bool
    action: str
    error: Optional[str] = None


@dataclass(frozen=True)
class Updater:
    item_type: str
    tier: int
    check_all: Callable[[], list[UpdateStatus]]
    apply_one: Optional[Callable[..., UpdateResult]]


# ── marketplace updater (tier 1) — thin wrap of existing core funcs ─────────

def _marketplace_check_all() -> list[UpdateStatus]:
    mkts = list_marketplaces(PATHS.known_marketplaces)
    if not mkts:
        return []
    pooled = pooled_map(mkts, lambda m: get_marketplace_version(PATHS.known_marketplaces, m.name))
    out: list[UpdateStatus] = []
    for m in mkts:
        vi = pooled.results.get(m)
        if vi is None:
            out.append(UpdateStatus("marketplace", m.name, 1, "?", "?", False, error="check failed"))
            continue
        auto = ""  # known_marketplaces.json may carry an optional autoUpdate flag
        out.append(UpdateStatus(
            "marketplace", m.name, 1, vi.current, vi.remote, vi.updatable,
            note=("up to date" if not vi.updatable and not vi.error else auto),
            error=vi.error,
        ))
    return out


def _marketplace_apply(name: str, no_sync: bool = False) -> UpdateResult:
    r = sync_marketplace(PATHS.known_marketplaces, name)
    return UpdateResult("marketplace", name, r.before, r.after, r.updated,
                        "git pull" if r.updated else "up to date")


marketplace_updater = Updater("marketplace", 1, _marketplace_check_all, _marketplace_apply)


# ── registry + orchestration ────────────────────────────────────────────────

UPDATERS: list[Updater] = [marketplace_updater]


def _updater_by_type() -> dict[str, Updater]:
    return {u.item_type: u for u in UPDATERS}


def check_all_updates(types: Optional[list[str]] = None) -> list[UpdateStatus]:
    out: list[UpdateStatus] = []
    for u in UPDATERS:
        if types and u.item_type not in types:
            continue
        try:
            out.extend(u.check_all())
        except Exception as e:  # noqa: BLE001 — isolate a broken updater
            out.append(UpdateStatus(u.item_type, "*", u.tier, "?", "?", False, error=str(e)))
    return out


def apply_updates(targets: list[tuple[str, str]], *, no_sync: bool = False) -> list[UpdateResult]:
    by_type = _updater_by_type()
    results: list[UpdateResult] = []
    for item_type, name in targets:
        u = by_type.get(item_type)
        if u is None or u.apply_one is None:
            results.append(UpdateResult(item_type, name, "?", "?", False, "skipped", error="not applicable"))
            continue
        try:
            results.append(u.apply_one(name, no_sync=no_sync))
        except Exception as e:  # noqa: BLE001
            results.append(UpdateResult(item_type, name, "?", "?", False, "error", error=str(e)))
    return results
