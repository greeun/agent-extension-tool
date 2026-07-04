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
    list_all_skills, list_commands, list_all_agents,
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
    """Copy `src` tree into `dest` crash-safely. Stage into a temp dir on the
    SAME filesystem as `dest` (so the final swap is an atomic rename, never a
    cross-device partial copy), then swap. When `dest` already exists it is
    renamed aside first and restored if the swap fails, so a failed
    materialize never leaves `dest` missing or half-populated."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".axt-plugin-", dir=dest.parent))
    backup = None
    try:
        staged = tmp / "staged"
        shutil.copytree(src, staged)          # dest untouched during the copy
        if dest.exists():
            backup = dest.with_name(dest.name + ".axt-bak")
            if backup.exists():
                shutil.rmtree(backup)
            dest.rename(backup)               # atomic (same filesystem)
        try:
            staged.rename(dest)               # atomic swap (same filesystem)
        except Exception:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            if backup is not None:
                backup.rename(dest)           # restore prior content
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
            backup = None
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


# ── standalone skill/command/agent updaters — git-backed dir, else manual ──

def _resolve_real_dir(path_str: str) -> Path:
    p = Path(path_str)
    try:
        rp = p.resolve()
    except OSError:
        rp = p
    return rp if rp.is_dir() else rp.parent


def _find_git_root(d: Path) -> Optional[Path]:
    for cand in [d, *d.parents]:
        if (cand / ".git").exists():
            return cand
    return None


def _git_dir_status(item_type: str, name: str, real_dir: Path) -> UpdateStatus:
    root = _find_git_root(real_dir)
    if root is None:
        return UpdateStatus(item_type, name, 2, "local", "local", False, note="manual (non-git)")
    code, out, err = _git(["git", "-C", str(root), "rev-parse", "--short", "HEAD"])
    if code != 0:
        return UpdateStatus(item_type, name, 1, "?", "?", False, error=err.strip())
    current = out.strip()
    code, _, err = _git(["git", "-C", str(root), "fetch", "--quiet"])
    if code != 0:
        return UpdateStatus(item_type, name, 1, current, "?", False, error=err.strip() or "fetch failed")
    code, out, err = _git(["git", "-C", str(root), "rev-parse", "--short", "@{u}"])
    if code != 0:
        return UpdateStatus(item_type, name, 1, current, "?", False, note="no upstream")
    remote = out.strip()
    return UpdateStatus(item_type, name, 1, current, remote, current != remote,
                        note=("up to date" if current == remote else ""))


def _git_dir_apply(item_type: str, name: str, real_dir: Path) -> UpdateResult:
    root = _find_git_root(real_dir)
    if root is None:
        return UpdateResult(item_type, name, "local", "local", False, "skipped", error="non-git")
    code, out, _ = _git(["git", "-C", str(root), "rev-parse", "--short", "HEAD"])
    before = out.strip() if code == 0 else "?"
    code, _, err = _git(["git", "-C", str(root), "pull", "--ff-only"])
    if code != 0:
        return UpdateResult(item_type, name, before, before, False, "error", error=err.strip())
    code, out, _ = _git(["git", "-C", str(root), "rev-parse", "--short", "HEAD"])
    after = out.strip() if code == 0 else "?"
    return UpdateResult(item_type, name, before, after, before != after, "git pull")


def _standalone(items, get_path):
    return [(it.name, get_path(it)) for it in items if not it.plugin and it.source == "user"]


def _skill_check_all() -> list[UpdateStatus]:
    return [_git_dir_status("skill", n, _resolve_real_dir(p))
            for n, p in _standalone(list_all_skills(), lambda s: s.path)]


def _skill_apply(name: str, no_sync: bool = False) -> UpdateResult:
    for n, p in _standalone(list_all_skills(), lambda s: s.path):
        if n == name:
            return _git_dir_apply("skill", name, _resolve_real_dir(p))
    return UpdateResult("skill", name, "?", "?", False, "skipped", error="not found")


def _command_check_all() -> list[UpdateStatus]:
    return [_git_dir_status("command", n, _resolve_real_dir(p))
            for n, p in _standalone(list_commands(), lambda c: c.source_path)]


def _command_apply(name: str, no_sync: bool = False) -> UpdateResult:
    for n, p in _standalone(list_commands(), lambda c: c.source_path):
        if n == name:
            return _git_dir_apply("command", name, _resolve_real_dir(p))
    return UpdateResult("command", name, "?", "?", False, "skipped", error="not found")


def _agent_check_all() -> list[UpdateStatus]:
    return [_git_dir_status("agent", n, _resolve_real_dir(p))
            for n, p in _standalone(list_all_agents(), lambda a: a.source_path)]


def _agent_apply(name: str, no_sync: bool = False) -> UpdateResult:
    for n, p in _standalone(list_all_agents(), lambda a: a.source_path):
        if n == name:
            return _git_dir_apply("agent", name, _resolve_real_dir(p))
    return UpdateResult("agent", name, "?", "?", False, "skipped", error="not found")


skill_updater = Updater("skill", 1, _skill_check_all, _skill_apply)
command_updater = Updater("command", 1, _command_check_all, _command_apply)
agent_updater = Updater("agent", 1, _agent_check_all, _agent_apply)


# ── registry + orchestration ────────────────────────────────────────────────

UPDATERS: list[Updater] = [
    marketplace_updater, plugin_updater,
    skill_updater, command_updater, agent_updater,
]


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
