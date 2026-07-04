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
    list_marketplaces, get_marketplace_version, sync_marketplace, pooled_map,
    read_json, list_installed_plugins, find_plugin_source_dir,
    _read_plugin_manifest, _parse_plugin_id, is_git_repo, read_sha_file, _git,
    update_installed_plugin,
)
import shutil
import tempfile
from pathlib import Path


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


# ── plugin updater (tier 1) — re-materialize from marketplace source ───────

def _full_head_sha(install_loc: str) -> str:
    """Full 40-char commit sha for a marketplace install: git HEAD, else .gcs-sha."""
    if is_git_repo(install_loc):
        code, out, _ = _git(["git", "-C", install_loc, "rev-parse", "HEAD"])
        if code == 0 and out.strip():
            return out.strip()
    return read_sha_file(install_loc) or ""


def _materialize_dir(src: Path, dest: Path) -> None:
    """Copy `src` tree into `dest` via a temp dir + swap (no partial state)."""
    tmp = Path(tempfile.mkdtemp(prefix="axt-plugin-"))
    try:
        staged = tmp / "staged"
        shutil.copytree(src, staged)
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(dest))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _plugin_source_version(plugin_id: str, mk_install_loc: str) -> tuple[str, Optional[str]]:
    """Return (source_version, error). Reads the plugin.json in the marketplace."""
    name, _mk = _parse_plugin_id(plugin_id)
    src = find_plugin_source_dir(mk_install_loc, name)
    if src is None:
        return "?", "plugin source not found in marketplace"
    manifest = _read_plugin_manifest(src)
    return (manifest.get("version") or "unknown"), None


def _plugin_check_all() -> list[UpdateStatus]:
    installed = list_installed_plugins(PATHS.installed_plugins)
    if not installed:
        return []
    km = read_json(PATHS.known_marketplaces, fallback={})
    mkts = sorted({p.marketplace for p in installed if p.marketplace and p.marketplace != "unknown"})
    pooled = pooled_map(mkts, lambda m: get_marketplace_version(PATHS.known_marketplaces, m)) if mkts else None
    mk_ver = pooled.results if pooled else {}
    out: list[UpdateStatus] = []
    for p in installed:
        entry = km.get(p.marketplace) if isinstance(km, dict) else None
        loc = entry.get("installLocation", "") if isinstance(entry, dict) else ""
        src_ver, src_err = _plugin_source_version(p.id, loc) if loc else ("?", "marketplace not registered")
        vi = mk_ver.get(p.marketplace)
        mk_updatable = bool(vi and vi.updatable)
        ver_changed = src_ver not in ("?", "unknown", p.version)
        updatable = mk_updatable or ver_changed
        out.append(UpdateStatus(
            "plugin", p.id, 1, p.version,
            src_ver if src_ver not in ("?", "unknown") else (vi.remote if vi else "?"),
            updatable,
            note=("up to date" if not updatable and not src_err else ""),
            error=src_err or (vi.error if vi else None),
        ))
    return out


def _plugin_apply(name: str, no_sync: bool = False) -> UpdateResult:
    plugin_id = name
    pname, mk = _parse_plugin_id(plugin_id)
    km = read_json(PATHS.known_marketplaces, fallback={})
    entry = km.get(mk) if isinstance(km, dict) else None
    if not isinstance(entry, dict):
        return UpdateResult("plugin", plugin_id, "?", "?", False, "skipped", error=f"marketplace {mk} not found")
    loc = entry.get("installLocation", "")
    if not no_sync:
        try:
            sync_marketplace(PATHS.known_marketplaces, mk)
        except Exception as e:  # noqa: BLE001
            return UpdateResult("plugin", plugin_id, "?", "?", False, "error", error=f"sync failed: {e}")
    src = find_plugin_source_dir(loc, pname)
    if src is None:
        return UpdateResult("plugin", plugin_id, "?", "?", False, "error", error="plugin source not found")
    manifest = _read_plugin_manifest(src)
    new_ver = manifest.get("version") or "unknown"
    new_sha = _full_head_sha(loc)
    ip = read_json(PATHS.installed_plugins, fallback={"version": 2, "plugins": {}})
    cur_list = (ip.get("plugins", {}) if isinstance(ip, dict) else {}).get(plugin_id) or [{}]
    cur = cur_list[0] if cur_list else {}
    before = cur.get("version", "?")
    new_path = str(Path(PATHS.plugin_cache) / mk / pname / new_ver)
    _materialize_dir(Path(src), Path(new_path))
    update_installed_plugin(PATHS.installed_plugins, plugin_id,
                            version=new_ver, git_commit_sha=new_sha, install_path=new_path)
    updated = (before != new_ver) or (cur.get("gitCommitSha") != new_sha)
    return UpdateResult("plugin", plugin_id, before, new_ver, updated, "reinstall")


plugin_updater = Updater("plugin", 1, _plugin_check_all, _plugin_apply)


# ── registry + orchestration ────────────────────────────────────────────────

UPDATERS: list[Updater] = [marketplace_updater, plugin_updater]


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
