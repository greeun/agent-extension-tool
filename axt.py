#!/usr/bin/env python3
"""
axt — Agent eXtension Tool (Python edition)

Single-file rewrite of the TypeScript+Ink axt. CLI + curses TUI for
Claude/Codex/Gemini/Cursor extension/plugin/skill/MCP/usage management.

See DESIGN.md (architecture) and FEATURES.md (1:1 feature inventory)
for the canonical specification.

Sections (search by header):
  Section 1: Constants & Paths
  Section 2: JSON I/O
  Section 3: Settings (single-scope read/write)
  Section 4: Plugin / Marketplace / Skill / MCP / Hooks / Commands / Agents
  Section 5: Vault
  Section 6: Usage Parsers (claude/codex/gemini/cursor)
  Section 7: Pricing & Cost
  Section 8: Context Analysis
  Section 9: Project Usage Index
  Section 10: CLI Commands (argparse)
  Section 11: TUI — Common helpers (color, key, width)
  Section 12: TUI — Common widgets (Table, DetailPanel, …)
  Section 13: TUI — Tabs
  Section 14: TUI — Main loop
  Section 15: Entry point

Pure stdlib runtime — `pip install -e .` and `axt` should just work on
Python 3.9+ (macOS/Linux). Windows needs `windows-curses`.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TypeVar

__version__ = "1.0.0"

T = TypeVar("T")


# ── Section 1: Constants & Paths ─────────────────────────────────────────────
#
# Mirrors src/core/paths.ts. Honors the same env vars (`CLAUDE_CONFIG_DIR`,
# `CODEX_HOME`, `GEMINI_CLI_HOME`) and the same Windows %APPDATA% fallback
# for the axt user-config dir.

IS_WINDOWS = sys.platform == "win32"

HOME = Path.home()


def _env_dir(env_var: str, default: Path) -> Path:
    """Read a path env var; fall back to `default` when unset or empty."""
    value = os.environ.get(env_var)
    return Path(value) if value else default


CLAUDE_DIR: Path = _env_dir("CLAUDE_CONFIG_DIR", HOME / ".claude")
CODEX_DIR: Path = _env_dir("CODEX_HOME", HOME / ".codex")
# Mirror the TS quirk: $GEMINI_CLI_HOME points one level above ".gemini".
_GEMINI_BASE = os.environ.get("GEMINI_CLI_HOME")
GEMINI_DIR: Path = (Path(_GEMINI_BASE) / ".gemini") if _GEMINI_BASE else (HOME / ".gemini")


@dataclass(frozen=True)
class Paths:
    """All filesystem locations axt reads or writes."""

    # Claude
    claude_dir: Path = CLAUDE_DIR
    settings: Path = CLAUDE_DIR / "settings.json"
    known_marketplaces: Path = CLAUDE_DIR / "plugins" / "known_marketplaces.json"
    installed_plugins: Path = CLAUDE_DIR / "plugins" / "installed_plugins.json"
    blocklist: Path = CLAUDE_DIR / "plugins" / "blocklist.json"
    plugin_cache: Path = CLAUDE_DIR / "plugins" / "cache"
    marketplaces: Path = CLAUDE_DIR / "plugins" / "marketplaces"
    skills: Path = CLAUDE_DIR / "skills"
    projects: Path = CLAUDE_DIR / "projects"
    stats_cache: Path = CLAUDE_DIR / "stats-cache.json"
    usage_snapshot: Path = CLAUDE_DIR / "usage-snapshot.json"

    # Codex
    codex_dir: Path = CODEX_DIR
    codex_sessions: Path = CODEX_DIR / "sessions"

    # Gemini
    gemini_dir: Path = GEMINI_DIR
    gemini_tmp: Path = GEMINI_DIR / "tmp"
    gemini_projects: Path = GEMINI_DIR / "projects.json"

    # Cursor
    cursor_dir: Path = HOME / ".cursor"
    cursor_tracking_db: Path = HOME / ".cursor" / "ai-tracking" / "ai-code-tracking.db"

    # axt vault
    axt_dir: Path = HOME / ".axt"
    vault: Path = HOME / ".axt" / "vault"
    vault_skills: Path = HOME / ".axt" / "vault" / "skills"
    vault_commands: Path = HOME / ".axt" / "vault" / "commands"
    vault_agents: Path = HOME / ".axt" / "vault" / "agents"


# Module-level singleton; tests can monkeypatch individual attrs via
# `monkeypatch.setattr("axt.PATHS", custom_paths_obj)` if needed.
PATHS = Paths()


def _axt_config_dir() -> Path:
    """User-config dir for axt itself (~/.config/axt or %APPDATA%/axt)."""
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or str(HOME / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(HOME / ".config")
    return Path(base) / "axt"


AXT_CONFIG_DIR: Path = _axt_config_dir()
AXT_CONFIG_PATH: Path = AXT_CONFIG_DIR / "config.json"


def project_settings_path(cwd: os.PathLike[str] | str | None = None) -> Path:
    """Return `<cwd>/.claude/settings.json` for project-scoped Claude settings."""
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".claude" / "settings.json"


# ── Section 2: JSON I/O ──────────────────────────────────────────────────────
#
# Mirror of src/core/json-io.ts:
#   - read_json(path, fallback=...) — returns parsed JSON, or `fallback` if
#     the file is missing. Raises `FileNotFoundError` only when no fallback
#     was provided.
#   - write_json_atomic(path, data) — writes via temp-file + rename, backs
#     up any existing file to `<path>.bak`, auto-creates parent dirs.
#
# Atomic write semantics matter: usage and settings files are concurrently
# read by Claude Code, Codex, etc.; a partial write must never be observable.


_MISSING = object()


def read_json(path: os.PathLike[str] | str, *, fallback: Any = _MISSING) -> Any:
    """Read a JSON file. Return `fallback` if missing (when provided)."""
    p = Path(path)
    if not p.exists():
        if fallback is _MISSING:
            raise FileNotFoundError(f"File not found: {p}")
        return fallback
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: os.PathLike[str] | str, data: Any) -> None:
    """Atomically write `data` as pretty-printed JSON to `path`.

    Steps:
      1. mkdir -p parent
      2. cp existing file to `path.bak` (best-effort)
      3. write to `<dir>/.tmp-<uuid>.json`
      4. os.replace tmp → path (atomic on POSIX and Windows)
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if p.exists():
        try:
            backup = p.with_suffix(p.suffix + ".bak")
            backup.write_bytes(p.read_bytes())
        except OSError:
            # Backup is best-effort; don't fail the write if it can't happen
            # (e.g. permission glitch on a network mount).
            pass

    tmp_name = f".tmp-{uuid.uuid4().hex}.json"
    tmp_path = p.parent / tmp_name
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, p)
    finally:
        # Cleanup the tmp file if rename didn't consume it (e.g. on error).
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


# ── Section 3: Settings (single-scope read/write) ────────────────────────────
#
# Mirror of src/core/settings.ts. Each helper operates on ONE settings file;
# multi-scope merge (global vs project vs local) is the caller's job — same
# as the TypeScript version. This matches Claude Code's own behavior where
# precedence is applied at read sites, not in a shared loader.
#
# Settings shape (only keys axt manipulates; other keys are preserved):
#   {
#     "enabledPlugins":         { "<plugin_id>": true|false, ... },
#     "favoritePlugins":        { "<plugin_id>": true, ... },   # missing == not favorite
#     "markedForUpdate":        { "<plugin_id>": true, ... },   # missing == not marked
#     "extraKnownMarketplaces": { "<name>": { "source": {...} }, ... },
#     ...
#   }


def _read_settings(settings_path: os.PathLike[str] | str) -> dict[str, Any]:
    """Read a settings.json file, returning {} when missing or malformed-empty."""
    data = read_json(settings_path, fallback={})
    if not isinstance(data, dict):
        # Defensive: a non-object JSON value here is corruption. Treat as
        # empty rather than crash; callers will overwrite on next write.
        return {}
    return data


def read_enabled_plugins(settings_path: os.PathLike[str] | str) -> dict[str, bool]:
    settings = _read_settings(settings_path)
    enabled = settings.get("enabledPlugins") or {}
    return {k: bool(v) for k, v in enabled.items()}


def set_plugin_enabled(
    settings_path: os.PathLike[str] | str,
    plugin_id: str,
    enabled: bool,
) -> None:
    settings = _read_settings(settings_path)
    settings.setdefault("enabledPlugins", {})[plugin_id] = bool(enabled)
    write_json_atomic(settings_path, settings)


def remove_plugin_from_settings(
    settings_path: os.PathLike[str] | str,
    plugin_id: str,
) -> None:
    settings = _read_settings(settings_path)
    enabled = settings.get("enabledPlugins")
    if isinstance(enabled, dict):
        enabled.pop(plugin_id, None)
    write_json_atomic(settings_path, settings)


def read_favorite_plugins(settings_path: os.PathLike[str] | str) -> dict[str, bool]:
    settings = _read_settings(settings_path)
    favorites = settings.get("favoritePlugins") or {}
    return {k: bool(v) for k, v in favorites.items()}


def set_plugin_favorite(
    settings_path: os.PathLike[str] | str,
    plugin_id: str,
    favorite: bool,
) -> None:
    settings = _read_settings(settings_path)
    favorites = settings.setdefault("favoritePlugins", {})
    if favorite:
        favorites[plugin_id] = True
    else:
        favorites.pop(plugin_id, None)
    write_json_atomic(settings_path, settings)


def read_marked_for_update(settings_path: os.PathLike[str] | str) -> dict[str, bool]:
    settings = _read_settings(settings_path)
    marked = settings.get("markedForUpdate") or {}
    return {k: bool(v) for k, v in marked.items()}


def set_marked_for_update(
    settings_path: os.PathLike[str] | str,
    plugin_id: str,
    marked: bool,
) -> None:
    settings = _read_settings(settings_path)
    bucket = settings.setdefault("markedForUpdate", {})
    if marked:
        bucket[plugin_id] = True
    else:
        bucket.pop(plugin_id, None)
    write_json_atomic(settings_path, settings)


def read_extra_marketplaces(
    settings_path: os.PathLike[str] | str,
) -> dict[str, dict[str, Any]]:
    settings = _read_settings(settings_path)
    extra = settings.get("extraKnownMarketplaces") or {}
    if not isinstance(extra, dict):
        return {}
    # Shape: { name: { "source": { "source": "github"|"git"|"directory", "repo"?, "url"? } } }
    return {k: v for k, v in extra.items() if isinstance(v, dict)}


# ── Section 4: Plugin / MCP / Skill / Commands / Agents ─────────────────────
#
# Marketplace + Hooks live in their own sub-sections below; this block holds
# the read-only "what does the user currently have?" inventory functions.
#
# Conventions mirrored from src/core/{plugin,mcp,skill,commands,agents}.ts:
#   - Names of plugin-sourced items are prefixed `<plugin>:<entry>`.
#   - Missing directories return [] (not an error).
#   - Manifests prefer `.claude-plugin/plugin.json`; fall back to `plugin.json`.

import re
from dataclasses import asdict


# ─── Plugin ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PluginInfo:
    id: str
    name: str
    marketplace: str
    version: str
    install_path: str
    scope: str
    installed_at: str
    last_updated: str
    author: Optional[str] = None
    description: Optional[str] = None
    homepage: Optional[str] = None
    repository: Optional[str] = None


def _parse_plugin_id(plugin_id: str) -> tuple[str, str]:
    """Split `name@marketplace`; default marketplace `unknown`."""
    at = plugin_id.find("@")
    if at < 0:
        return plugin_id, "unknown"
    return plugin_id[:at], plugin_id[at + 1:]


def _normalize_manifest_string(val: Any) -> Optional[str]:
    """Manifests sometimes wrap author/homepage/repository in an object."""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        if isinstance(val.get("name"), str):
            return val["name"]
        if isinstance(val.get("url"), str):
            return val["url"]
    return None


def _read_plugin_manifest(install_path: os.PathLike[str] | str) -> dict[str, Any]:
    """Read `.claude-plugin/plugin.json`, fall back to `plugin.json`."""
    install_dir = Path(install_path)
    primary = install_dir / ".claude-plugin" / "plugin.json"
    manifest = read_json(primary, fallback={})
    if isinstance(manifest, dict) and (manifest.get("name") or manifest.get("description")):
        return manifest
    secondary = read_json(install_dir / "plugin.json", fallback={})
    return secondary if isinstance(secondary, dict) else {}


def list_installed_plugins(ip_path: os.PathLike[str] | str) -> list[PluginInfo]:
    """Read installed_plugins.json and merge each entry's manifest metadata."""
    data = read_json(ip_path, fallback={"version": 2, "plugins": {}})
    plugins_map = data.get("plugins") or {} if isinstance(data, dict) else {}
    results: list[PluginInfo] = []
    for plugin_id, entries in plugins_map.items():
        if not entries:
            continue
        entry = entries[0]
        name, marketplace = _parse_plugin_id(plugin_id)
        manifest = _read_plugin_manifest(entry.get("installPath", ""))
        results.append(
            PluginInfo(
                id=plugin_id,
                name=name,
                marketplace=marketplace,
                version=entry.get("version", ""),
                install_path=entry.get("installPath", ""),
                scope=entry.get("scope", ""),
                installed_at=entry.get("installedAt", ""),
                last_updated=entry.get("lastUpdated", ""),
                author=_normalize_manifest_string(manifest.get("author")),
                description=manifest.get("description") if isinstance(manifest.get("description"), str) else None,
                homepage=_normalize_manifest_string(manifest.get("homepage")),
                repository=_normalize_manifest_string(manifest.get("repository")),
            )
        )
    return results


def get_plugin_info(ip_path: os.PathLike[str] | str, plugin_id: str) -> Optional[PluginInfo]:
    for p in list_installed_plugins(ip_path):
        if p.id == plugin_id:
            return p
    return None


def add_installed_plugin(
    ip_path: os.PathLike[str] | str,
    *,
    plugin_id: str,
    version: str,
    install_path: str,
    scope: str,
) -> None:
    """Write a new entry under `plugins[<id>][0]`, replacing any prior list."""
    from datetime import datetime, timezone
    data = read_json(ip_path, fallback={"version": 2, "plugins": {}})
    if not isinstance(data, dict):
        data = {"version": 2, "plugins": {}}
    data.setdefault("plugins", {})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    data["plugins"][plugin_id] = [
        {
            "scope": scope,
            "installPath": install_path,
            "version": version,
            "installedAt": now,
            "lastUpdated": now,
        }
    ]
    write_json_atomic(ip_path, data)


def remove_installed_plugin(ip_path: os.PathLike[str] | str, plugin_id: str) -> None:
    data = read_json(ip_path, fallback={"version": 2, "plugins": {}})
    if not isinstance(data, dict):
        data = {"version": 2, "plugins": {}}
    data.setdefault("plugins", {}).pop(plugin_id, None)
    write_json_atomic(ip_path, data)


def find_plugin_source_dir(marketplace_dir: os.PathLike[str] | str, plugin_name: str) -> Optional[Path]:
    """Locate a plugin within a cloned marketplace tree."""
    mk = Path(marketplace_dir)
    candidates = [mk / "plugins" / plugin_name, mk / plugin_name, mk]
    for d in candidates:
        if (d / ".claude-plugin" / "plugin.json").exists():
            return d
        if (d / "plugin.json").exists():
            return d
    return None


# ─── MCP ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class McpServerInfo:
    name: str
    plugin_id: str
    command: str
    args: tuple[str, ...]
    env: tuple[tuple[str, str], ...]  # frozen, sorted

    @property
    def args_list(self) -> list[str]:
        return list(self.args)

    @property
    def env_dict(self) -> dict[str, str]:
        return dict(self.env)


def list_mcp_servers(installed_plugins: list[dict[str, str]] | list[PluginInfo]) -> list[McpServerInfo]:
    """Collect `mcpServers` blocks from every installed plugin's manifest."""
    servers: list[McpServerInfo] = []
    for plugin in installed_plugins:
        if isinstance(plugin, PluginInfo):
            pid, install_path = plugin.id, plugin.install_path
        else:
            pid, install_path = plugin.get("id", ""), plugin.get("installPath", plugin.get("install_path", ""))
        if not install_path:
            continue
        manifest_path = Path(install_path) / ".claude-plugin" / "plugin.json"
        manifest = read_json(manifest_path, fallback={})
        mcp_map = manifest.get("mcpServers") if isinstance(manifest, dict) else None
        if not isinstance(mcp_map, dict):
            continue
        for name, definition in mcp_map.items():
            if not isinstance(definition, dict):
                continue
            args = definition.get("args") or []
            env = definition.get("env") or {}
            servers.append(
                McpServerInfo(
                    name=name,
                    plugin_id=pid,
                    command=definition.get("command", ""),
                    args=tuple(str(a) for a in args) if isinstance(args, list) else (),
                    env=tuple(sorted((str(k), str(v)) for k, v in env.items())) if isinstance(env, dict) else (),
                )
            )
    return servers


# ─── Skill ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkillInfo:
    name: str
    path: str
    is_symlink: bool
    source: str  # "user" | "project" | "plugin"
    target: Optional[str] = None
    plugin: Optional[str] = None


def _scan_skills_dir(skills_dir: os.PathLike[str] | str, source: str, plugin: Optional[str] = None) -> list[SkillInfo]:
    d = Path(skills_dir)
    if not d.exists() or not d.is_dir():
        return []
    out: list[SkillInfo] = []
    try:
        entries = sorted(d.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            lstat = entry.lstat()
        except OSError:
            continue
        is_symlink = entry.is_symlink()
        # Require directory OR symlink (potentially to a directory).
        if not is_symlink and not entry.is_dir():
            continue
        target: Optional[str] = None
        if is_symlink:
            try:
                target = os.readlink(entry)
            except OSError:
                target = None
        display_name = f"{plugin}:{entry.name}" if plugin else entry.name
        out.append(
            SkillInfo(
                name=display_name,
                path=str(entry),
                is_symlink=is_symlink,
                source=source,
                target=target,
                plugin=plugin,
            )
        )
    return out


def list_skills(skills_dir: os.PathLike[str] | str) -> list[SkillInfo]:
    """Scan a single directory (TS `listSkills`)."""
    return _scan_skills_dir(skills_dir, "user")


def list_all_skills(*, project_dir: Optional[os.PathLike[str] | str] = None) -> list[SkillInfo]:
    """User (~/.claude/skills + ~/.agents) + project + enabled-plugin skills."""
    out: list[SkillInfo] = []
    out += _scan_skills_dir(PATHS.skills, "user")
    out += _scan_skills_dir(HOME / ".agents", "user")
    if project_dir:
        out += _scan_skills_dir(Path(project_dir) / ".claude" / "skills", "project")
    # `.agents` next to the project, defaulting to cwd when project_dir missing.
    out += _scan_skills_dir(Path(project_dir or os.getcwd()) / ".agents", "project")

    plugins = list_installed_plugins(PATHS.installed_plugins)
    enabled = read_enabled_plugins(PATHS.settings)
    for p in plugins:
        if not enabled.get(p.id):
            continue
        out += _scan_skills_dir(Path(p.install_path) / "skills", "plugin", p.name)
    return out


def is_symlink_supported() -> bool:
    return not IS_WINDOWS


def link_skill(skills_dir: os.PathLike[str] | str, target_path: os.PathLike[str] | str, name: Optional[str] = None) -> None:
    """Create `<skills_dir>/<name>` as a symlink to `target_path` (POSIX only)."""
    if IS_WINDOWS:
        raise OSError("Skill linking via symlink is not supported on Windows.")
    target = Path(target_path)
    skill_name = name or target.name
    link_path = Path(skills_dir) / skill_name
    Path(skills_dir).mkdir(parents=True, exist_ok=True)
    os.symlink(str(target), str(link_path))


def unlink_skill(skills_dir: os.PathLike[str] | str, name: str) -> None:
    if IS_WINDOWS:
        raise OSError("Skill unlinking is not supported on Windows.")
    full_path = Path(skills_dir) / name
    if not full_path.is_symlink():
        raise ValueError(f'"{name}" is not a symlink. Use rm to remove directories.')
    full_path.unlink()


# ─── Commands ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CommandInfo:
    name: str
    source: str  # "user" | "project" | "plugin"
    source_path: str
    description: str
    content: str
    plugin: Optional[str] = None


# Regex twins of the TS `description:` extraction.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_DESC_LINE_RE = re.compile(r'description:\s*"?([^"\n]+)"?')


def _extract_md_description(raw: str) -> str:
    """Extract description from frontmatter; fall back to first non-empty content line."""
    fm = _FRONTMATTER_RE.match(raw)
    if fm:
        m = _DESC_LINE_RE.search(fm.group(1))
        if m:
            return m.group(1).strip().strip('"')
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
            return stripped[:80]
    return ""


def _scan_md_dir(
    dir_path: os.PathLike[str] | str,
    source: str,
    plugin: Optional[str] = None,
    *,
    factory,
):
    """Generic `.md` scanner shared by commands/agents."""
    d = Path(dir_path)
    if not d.exists() or not d.is_dir():
        return []
    out = []
    try:
        entries = sorted(d.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    for entry in entries:
        if not entry.is_file() or entry.suffix != ".md":
            continue
        try:
            raw = entry.read_text(encoding="utf-8")
        except OSError:
            continue
        name = entry.stem
        display_name = f"{plugin}:{name}" if plugin else name
        description = _extract_md_description(raw)
        out.append(factory(display_name, source, str(entry), plugin, description, raw))
    return out


def _make_command(name, source, path, plugin, description, raw):
    return CommandInfo(name=name, source=source, source_path=path, plugin=plugin, description=description, content=raw)


def list_commands(*, project_dir: Optional[os.PathLike[str] | str] = None) -> list[CommandInfo]:
    out: list[CommandInfo] = []
    out += _scan_md_dir(PATHS.claude_dir / "commands", "user", factory=_make_command)
    if project_dir:
        out += _scan_md_dir(Path(project_dir) / ".claude" / "commands", "project", factory=_make_command)
    plugins = list_installed_plugins(PATHS.installed_plugins)
    enabled = read_enabled_plugins(PATHS.settings)
    for p in plugins:
        if not enabled.get(p.id):
            continue
        out += _scan_md_dir(Path(p.install_path) / "commands", "plugin", p.name, factory=_make_command)
    return out


# ─── Agents ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentInfo:
    name: str
    source: str
    source_path: str
    description: str
    plugin: Optional[str] = None


def _make_agent(name, source, path, plugin, description, _raw):
    return AgentInfo(name=name, source=source, source_path=path, plugin=plugin, description=description)


def list_all_agents(*, project_dir: Optional[os.PathLike[str] | str] = None) -> list[AgentInfo]:
    out: list[AgentInfo] = []
    out += _scan_md_dir(PATHS.claude_dir / "agents", "user", factory=_make_agent)
    out += _scan_md_dir(HOME / ".agents", "user", factory=_make_agent)
    if project_dir:
        out += _scan_md_dir(Path(project_dir) / ".claude" / "agents", "project", factory=_make_agent)
    out += _scan_md_dir(Path(project_dir or os.getcwd()) / ".agents", "project", factory=_make_agent)
    plugins = list_installed_plugins(PATHS.installed_plugins)
    enabled = read_enabled_plugins(PATHS.settings)
    for p in plugins:
        if not enabled.get(p.id):
            continue
        out += _scan_md_dir(Path(p.install_path) / "agents", "plugin", p.name, factory=_make_agent)
    return out


# ─── Hooks ───────────────────────────────────────────────────────────────────
#
# 28 known hook events. We treat the event names as a closed set, mirroring
# src/core/hooks.ts; new event types in upstream Claude Code require a code
# change here too (acceptable tradeoff vs. silent acceptance of unknown
# events leaking through).


HOOK_EVENTS: tuple[str, ...] = (
    "SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion",
    "PreToolUse", "PermissionRequest", "PermissionDenied",
    "PostToolUse", "PostToolUseFailure", "PostToolBatch",
    "Stop", "StopFailure",
    "SubagentStart", "SubagentStop",
    "TaskCreated", "TaskCompleted", "TeammateIdle",
    "InstructionsLoaded", "ConfigChange", "CwdChanged", "FileChanged",
    "WorktreeCreate", "WorktreeRemove",
    "PreCompact", "PostCompact",
    "Elicitation", "ElicitationResult",
    "SessionEnd", "Notification",
)

HOOK_TYPES = frozenset({"command", "http", "mcp_tool", "prompt", "agent"})


@dataclass(frozen=True)
class HookInfo:
    event: str
    matcher: str
    source: str  # "user" | "project" | "local" | "plugin"
    source_path: str
    type: str  # one of HOOK_TYPES; defaults to "command"
    command: Optional[str] = None
    url: Optional[str] = None
    server: Optional[str] = None
    tool: Optional[str] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    timeout: Optional[int] = None
    status_message: Optional[str] = None
    async_: Optional[bool] = None
    async_rewake: Optional[bool] = None
    condition: Optional[str] = None
    once: Optional[bool] = None


def _extract_hooks(settings: dict[str, Any], source: str, source_path: str) -> list[HookInfo]:
    """Pull hook definitions out of one settings/hooks.json blob."""
    raw_map = settings.get("hooks")
    if not isinstance(raw_map, dict):
        return []
    out: list[HookInfo] = []
    for event in HOOK_EVENTS:
        rules = raw_map.get(event)
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            matcher = rule.get("matcher") or "*"
            hooks_list = rule.get("hooks")
            if not isinstance(hooks_list, list):
                continue
            for hook in hooks_list:
                if not isinstance(hook, dict):
                    continue
                hook_type = hook.get("type") if hook.get("type") in HOOK_TYPES else "command"
                out.append(
                    HookInfo(
                        event=event,
                        matcher=matcher,
                        source=source,
                        source_path=source_path,
                        type=hook_type,
                        command=hook.get("command"),
                        url=hook.get("url"),
                        server=hook.get("server"),
                        tool=hook.get("tool"),
                        prompt=hook.get("prompt"),
                        model=hook.get("model"),
                        timeout=hook.get("timeout"),
                        status_message=hook.get("statusMessage"),
                        async_=hook.get("async") or None,
                        async_rewake=hook.get("asyncRewake") or None,
                        condition=hook.get("if"),
                        once=hook.get("once") or None,
                    )
                )
    return out


def list_hooks(
    *,
    user_settings_path: os.PathLike[str] | str,
    project_dir: Optional[os.PathLike[str] | str] = None,
    installed_plugins_path: Optional[os.PathLike[str] | str] = None,
) -> list[HookInfo]:
    out: list[HookInfo] = []
    user = read_json(user_settings_path, fallback={})
    if isinstance(user, dict):
        out += _extract_hooks(user, "user", str(user_settings_path))

    if project_dir:
        proj_path = Path(project_dir) / ".claude" / "settings.json"
        if proj_path.exists():
            data = read_json(proj_path, fallback={})
            if isinstance(data, dict):
                out += _extract_hooks(data, "project", str(proj_path))
        local_path = Path(project_dir) / ".claude" / "settings.local.json"
        if local_path.exists():
            data = read_json(local_path, fallback={})
            if isinstance(data, dict):
                out += _extract_hooks(data, "local", str(local_path))

    if installed_plugins_path and Path(installed_plugins_path).exists():
        for plugin in list_installed_plugins(installed_plugins_path):
            hooks_path = Path(plugin.install_path) / "hooks" / "hooks.json"
            if not hooks_path.exists():
                continue
            data = read_json(hooks_path, fallback={})
            if isinstance(data, dict):
                out += _extract_hooks(data, "plugin", str(hooks_path))

    return out


@dataclass(frozen=True)
class HookPreviewResult:
    type: str
    summary: str
    output: Optional[str] = None
    error: Optional[str] = None
    exit_code: Optional[int] = None


def _sample_payload(hook: HookInfo) -> dict[str, Any]:
    payload: dict[str, Any] = {"session_id": "axt-preview", "hook_event": hook.event}
    if hook.event in ("PreToolUse", "PostToolUse"):
        payload["tool_name"] = hook.matcher if hook.matcher != "*" else "Bash"
        payload["tool_input"] = {}
    if hook.event == "UserPromptSubmit":
        payload["user_prompt"] = "(preview)"
    return payload


def preview_hook(hook: HookInfo, *, timeout_ms: int = 5000) -> HookPreviewResult:
    """Dry-run a hook. Command hooks actually execute via `sh -c`; HTTP/MCP/
    prompt/agent hooks just return a formatted preview string."""
    import subprocess

    if hook.type == "command":
        if not hook.command:
            return HookPreviewResult(type="command", summary="(no command)")
        payload = json.dumps(_sample_payload(hook))
        try:
            proc = subprocess.run(
                ["sh", "-c", hook.command],
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1000,
                env={**os.environ, "HOOK_EVENT": hook.event},
                check=False,
            )
            return HookPreviewResult(
                type="command",
                summary=hook.command,
                output=proc.stdout.strip() or None,
                error=proc.stderr.strip() or None,
                exit_code=proc.returncode,
            )
        except subprocess.TimeoutExpired as e:
            return HookPreviewResult(type="command", summary=hook.command, error=f"timeout after {timeout_ms}ms")
        except OSError as e:
            return HookPreviewResult(type="command", summary=hook.command, error=str(e))

    if hook.type == "http":
        body = json.dumps(_sample_payload(hook), indent=2)
        url = hook.url or "(no url)"
        return HookPreviewResult(
            type="http",
            summary=url,
            output=f"POST {url}\nContent-Type: application/json\nBody: {body}",
        )

    if hook.type == "mcp_tool":
        return HookPreviewResult(
            type="mcp_tool",
            summary=f"{hook.server}:{hook.tool}",
            output=f"Server: {hook.server}\nTool: {hook.tool}",
        )

    return HookPreviewResult(type=hook.type, summary=hook.type, output=hook.prompt or "(no prompt)")


def get_hook_detail(hook: HookInfo) -> str:
    """Single-line summary used in the TUI Hooks tab."""
    if hook.type == "command":
        return hook.command or ""
    if hook.type == "http":
        return hook.url or ""
    if hook.type == "mcp_tool":
        return f"{hook.server}:{hook.tool}"
    if hook.type in ("prompt", "agent"):
        return (hook.prompt or "")[:60]
    return ""


# ── Section 5: Vault ─────────────────────────────────────────────────────────
#
# Largest single source module. Three responsibilities:
#   (a) YAML-frontmatter description extraction — explicit hand-rolled parser
#       (no PyYAML), handling block scalars (`|`/`>`), single/double-quoted
#       multi-line strings with line continuation, and CRLF endings.
#   (b) Per-project profile (`.axt-profile.json`) read/write + sync.
#   (c) Symlink management to both project (`.claude/<type>s/<name>`) and
#       global (`~/.claude/<type>s/<name>`) directories.
#
# Mirrors src/core/vault.ts. Symlink ops raise OSError on Windows (TS parity).

from datetime import datetime, timezone

VAULT_PROFILE_NAME = ".axt-profile.json"
VAULT_TYPES: tuple[str, ...] = ("skill", "command", "agent", "plugin")


@dataclass
class VaultItem:
    """Mutable — `isLinked`/`isGlobalLinked` are enriched after construction."""
    name: str
    type: str
    path: str
    description: str
    is_linked: bool = False
    is_global_linked: bool = False
    in_vault: Optional[bool] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass(frozen=True)
class AxtProfile:
    skills: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    plugins: tuple[str, ...] = ()

    def as_json(self) -> dict[str, Any]:
        return {
            "extensions": {
                "skills": list(self.skills),
                "commands": list(self.commands),
                "agents": list(self.agents),
                "plugins": list(self.plugins),
            }
        }

    @classmethod
    def empty(cls) -> "AxtProfile":
        return cls()

    @classmethod
    def from_json(cls, data: Any) -> "AxtProfile":
        if not isinstance(data, dict):
            return cls.empty()
        ext = data.get("extensions") or {}
        if not isinstance(ext, dict):
            return cls.empty()
        def _list(key: str) -> tuple[str, ...]:
            v = ext.get(key)
            return tuple(str(x) for x in v) if isinstance(v, list) else ()
        return cls(skills=_list("skills"), commands=_list("commands"), agents=_list("agents"), plugins=_list("plugins"))

    def with_added(self, key: str, name: str) -> "AxtProfile":
        current = getattr(self, key)
        if name in current:
            return self
        return self._replace(**{key: current + (name,)})

    def with_removed(self, key: str, name: str) -> "AxtProfile":
        current = getattr(self, key)
        if name not in current:
            return self
        return self._replace(**{key: tuple(x for x in current if x != name)})

    def _replace(self, **kw) -> "AxtProfile":
        # dataclass(frozen=True) without `eq` we can't use dataclasses.replace
        # on a tuple field cleanly, but we can construct fresh.
        merged = {"skills": self.skills, "commands": self.commands, "agents": self.agents, "plugins": self.plugins}
        merged.update(kw)
        return AxtProfile(**merged)


@dataclass(frozen=True)
class SyncResult:
    linked: tuple[str, ...] = ()
    unlinked: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class MigrateResult:
    moved: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginRef:
    id: str
    name: str
    description: str = ""
    install_path: str = ""


# ─── YAML-frontmatter description parser ─────────────────────────────────────


def _normalize_description(s: str) -> str:
    """Collapse all whitespace to single spaces (multi-line YAML → 1-line TUI)."""
    return " ".join(s.split())


def _read_double_quoted(lines: list[str], i: int, start: str) -> str:
    """Multi-line `"..."` scalar. Honors `\\n`, `\\t`, `\\\\`, line continuation
    via trailing backslash (joins without space), folded line breaks → space."""
    buf: list[str] = []
    line = start
    idx = i
    while True:
        k = 0
        continued = False
        closed = False
        while k < len(line):
            ch = line[k]
            if ch == "\\":
                if k + 1 >= len(line):
                    continued = True
                    k += 1
                    break
                nx = line[k + 1]
                buf.append("\n" if nx == "n" else "\t" if nx == "t" else nx)
                k += 2
                continue
            if ch == '"':
                closed = True
                break
            buf.append(ch)
            k += 1
        if closed or idx + 1 >= len(lines):
            break
        if not continued:
            buf.append(" ")
        idx += 1
        line = lines[idx].lstrip()
    return "".join(buf)


def _read_single_quoted(lines: list[str], i: int, start: str) -> str:
    """Multi-line `'...'` scalar. `''` is a literal quote; line breaks → space."""
    buf: list[str] = []
    line = start
    idx = i
    while True:
        k = 0
        closed = False
        while k < len(line):
            if line[k] == "'":
                if k + 1 < len(line) and line[k + 1] == "'":
                    buf.append("'")
                    k += 2
                    continue
                closed = True
                break
            buf.append(line[k])
            k += 1
        if closed or idx + 1 >= len(lines):
            break
        buf.append(" ")
        idx += 1
        line = lines[idx].lstrip()
    return "".join(buf)


_DESC_RE = re.compile(r"^(\s*)description:(.*)$")
_BLOCK_INDICATOR_RE = re.compile(r"^[|>][0-9+-]*$")


def parse_yaml_description(frontmatter: str) -> str:
    """Extract `description: ...` value. Handles plain, single/double-quoted
    (multi-line, with escapes / continuation), block scalars (`|` / `>` with
    chomping & indent indicators), and CRLF line endings."""
    lines = frontmatter.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, line in enumerate(lines):
        m = _DESC_RE.match(line)
        if not m:
            continue
        key_indent = len(m.group(1))
        rest = m.group(2).strip()

        # Block scalar: `|` or `>` followed by optional chomping/indent.
        if _BLOCK_INDICATOR_RE.match(rest):
            folded = rest[0] == ">"
            block: list[str] = []
            for j in range(i + 1, len(lines)):
                ln = lines[j]
                if ln.strip() == "":
                    block.append("")
                    continue
                indent = len(ln) - len(ln.lstrip())
                if indent <= key_indent:
                    break
                block.append(ln)
            while block and block[-1] == "":
                block.pop()
            non_empty = [x for x in block if x.strip() != ""]
            if not non_empty:
                return ""
            common = min(len(x) - len(x.lstrip()) for x in non_empty)
            dedented = [x[common:] for x in block]
            joined = (" " if folded else "\n").join(dedented)
            return _normalize_description(joined)

        if rest == "":
            return ""
        if rest[0] == '"':
            return _normalize_description(_read_double_quoted(lines, i, rest[1:]))
        if rest[0] == "'":
            return _normalize_description(_read_single_quoted(lines, i, rest[1:]))
        return _normalize_description(rest)
    return ""


_FRONTMATTER_BLOCK_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _read_description(file_path: os.PathLike[str] | str) -> str:
    """Open `file_path`, extract YAML frontmatter, return parsed description."""
    p = Path(file_path)
    try:
        content = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    m = _FRONTMATTER_BLOCK_RE.match(content)
    if not m:
        return ""
    return parse_yaml_description(m.group(1))


def _read_description_for_item(full_path: Path, item_type: str) -> str:
    """Skill items look for `index.md` then `SKILL.md`; everything else is
    the file itself."""
    if item_type == "skill":
        for candidate in ("index.md", "SKILL.md"):
            desc = _read_description(full_path / candidate)
            if desc:
                return desc
        return ""
    return _read_description(full_path)


# ─── Profile read/write ──────────────────────────────────────────────────────


def empty_profile() -> AxtProfile:
    return AxtProfile.empty()


def read_profile(project_dir: os.PathLike[str] | str) -> Optional[AxtProfile]:
    p = Path(project_dir) / VAULT_PROFILE_NAME
    if not p.exists():
        return None
    data = read_json(p, fallback={})
    return AxtProfile.from_json(data)


def write_profile(project_dir: os.PathLike[str] | str, profile: AxtProfile) -> None:
    write_json_atomic(Path(project_dir) / VAULT_PROFILE_NAME, profile.as_json())


# ─── Vault item listing ──────────────────────────────────────────────────────


def _stat_times(p: Path) -> tuple[Optional[datetime], Optional[datetime]]:
    """Return (created_at, updated_at). Falls back to ctime on Linux."""
    try:
        s = p.stat()
    except OSError:
        return None, None
    # birthtime is available on macOS / Windows / BSD; not on Linux.
    born = getattr(s, "st_birthtime", None)
    if born is None:
        born = s.st_ctime
    return (
        datetime.fromtimestamp(born, tz=timezone.utc),
        datetime.fromtimestamp(s.st_mtime, tz=timezone.utc),
    )


_TYPE_TO_DIR = {"skill": "skills", "command": "commands", "agent": "agents"}


def _type_to_dir(item_type: str) -> str:
    """Map vault item type → its subdir. `plugin` is not linkable."""
    if item_type not in _TYPE_TO_DIR:
        raise ValueError(f'Cannot link type "{item_type}" — plugins use enabledPlugins')
    return _TYPE_TO_DIR[item_type]


def _scan_vault_dir(vault_dir: Path, sub: str, item_type: str) -> list[VaultItem]:
    d = vault_dir / sub
    if not d.exists() or not d.is_dir():
        return []
    out: list[VaultItem] = []
    try:
        entries = sorted(d.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            s = entry.stat()
        except OSError:
            continue
        is_dir = entry.is_dir()
        is_file = entry.is_file()
        if item_type == "skill":
            if not is_dir:
                continue
        else:
            if not (is_file and entry.suffix == ".md"):
                continue
        created, updated = _stat_times(entry)
        out.append(
            VaultItem(
                name=entry.name,
                type=item_type,
                path=str(entry),
                description=_read_description_for_item(entry, item_type),
                in_vault=True,
                created_at=created,
                updated_at=updated,
            )
        )
    return out


def list_vault_items(vault_dir: os.PathLike[str] | str) -> list[VaultItem]:
    vd = Path(vault_dir)
    items: list[VaultItem] = []
    items += _scan_vault_dir(vd, "skills", "skill")
    items += _scan_vault_dir(vd, "commands", "command")
    items += _scan_vault_dir(vd, "agents", "agent")
    return items


# ─── Symlink ops ─────────────────────────────────────────────────────────────


def _ensure_no_real_file(link_path: Path, where: Path) -> None:
    """If link_path exists but is a real file/dir, raise. Otherwise unlink."""
    try:
        s = link_path.lstat()
    except FileNotFoundError:
        return
    if not link_path.is_symlink():
        raise FileExistsError(f'"{link_path.name}" already exists as a real file in {where}')
    link_path.unlink()


def link_to_project(project_dir: os.PathLike[str] | str, item: VaultItem) -> None:
    if IS_WINDOWS:
        raise OSError("Vault linking is not supported on Windows.")
    if item.type == "plugin":
        raise ValueError("Plugins use enabledPlugins, not symlinks.")
    sub = _type_to_dir(item.type)
    target_dir = Path(project_dir) / ".claude" / sub
    target_dir.mkdir(parents=True, exist_ok=True)
    link_path = target_dir / item.name
    _ensure_no_real_file(link_path, target_dir)
    os.symlink(item.path, link_path)

    profile = read_profile(project_dir) or empty_profile()
    profile = profile.with_added(sub, item.name)
    write_profile(project_dir, profile)


def unlink_from_project(project_dir: os.PathLike[str] | str, item: VaultItem) -> None:
    if IS_WINDOWS:
        raise OSError("Vault linking is not supported on Windows.")
    if item.type == "plugin":
        raise ValueError("Plugins use enabledPlugins, not symlinks.")
    sub = _type_to_dir(item.type)
    link_path = Path(project_dir) / ".claude" / sub / item.name
    try:
        if link_path.is_symlink():
            link_path.unlink()
    except FileNotFoundError:
        pass
    profile = read_profile(project_dir) or empty_profile()
    profile = profile.with_removed(sub, item.name)
    write_profile(project_dir, profile)


def link_to_global(global_dir: os.PathLike[str] | str, item: VaultItem) -> None:
    if IS_WINDOWS:
        raise OSError("Vault linking is not supported on Windows.")
    if item.type == "plugin":
        raise ValueError("Plugins use enabledPlugins, not symlinks.")
    sub = _type_to_dir(item.type)
    target_dir = Path(global_dir) / sub
    target_dir.mkdir(parents=True, exist_ok=True)
    link_path = target_dir / item.name
    _ensure_no_real_file(link_path, target_dir)
    os.symlink(item.path, link_path)


def unlink_from_global(global_dir: os.PathLike[str] | str, item: VaultItem) -> None:
    if IS_WINDOWS:
        raise OSError("Vault linking is not supported on Windows.")
    if item.type == "plugin":
        raise ValueError("Plugins use enabledPlugins, not symlinks.")
    sub = _type_to_dir(item.type)
    link_path = Path(global_dir) / sub / item.name
    try:
        if link_path.is_symlink():
            link_path.unlink()
    except FileNotFoundError:
        pass


# ─── Sync / Migrate / Import ─────────────────────────────────────────────────


def sync_project(project_dir: os.PathLike[str] | str, vault_dir: os.PathLike[str] | str) -> SyncResult:
    if IS_WINDOWS:
        raise OSError("Vault linking is not supported on Windows.")
    profile = read_profile(project_dir) or empty_profile()
    linked: list[str] = []
    unlinked: list[str] = []
    errors: list[str] = []

    for item_type, sub in (("skill", "skills"), ("command", "commands"), ("agent", "agents")):
        vault_sub = Path(vault_dir) / sub
        project_sub = Path(project_dir) / ".claude" / sub
        project_sub.mkdir(parents=True, exist_ok=True)
        declared = set(getattr(profile, sub))

        # Ensure declared items are linked.
        for name in declared:
            vp = vault_sub / name
            lp = project_sub / name
            if not vp.exists():
                errors.append(f"{item_type}:{name} not found in vault")
                continue
            if lp.is_symlink():
                continue
            try:
                os.symlink(vp, lp)
                linked.append(f"{item_type}:{name}")
            except OSError as e:
                errors.append(f"{item_type}:{name}: {e}")

        # Remove orphaned symlinks pointing into the vault subdir.
        if not project_sub.exists():
            continue
        try:
            entries = list(project_sub.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_symlink():
                continue
            try:
                target = os.readlink(entry)
            except OSError:
                continue
            if not target.startswith(str(vault_sub)):
                continue
            if entry.name not in declared:
                try:
                    entry.unlink()
                    unlinked.append(f"{item_type}:{entry.name}")
                except OSError:
                    pass

    return SyncResult(tuple(linked), tuple(unlinked), tuple(errors))


def _list_global_non_vault_items(global_dir: Path, vault_dir: Path) -> list[VaultItem]:
    """Items present in `~/.claude/<sub>/` but NOT in the vault yet."""
    vault_items = list_vault_items(vault_dir)
    vault_names_by_type: dict[str, set[str]] = {}
    for v in vault_items:
        vault_names_by_type.setdefault(v.type, set()).add(v.name)

    out: list[VaultItem] = []
    for sub, item_type in (("skills", "skill"), ("commands", "command"), ("agents", "agent")):
        d = global_dir / sub
        if not d.exists() or not d.is_dir():
            continue
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        skip_names = vault_names_by_type.get(item_type, set())
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.name in skip_names:
                continue
            try:
                s = entry.stat()
            except OSError:
                continue
            if item_type == "skill":
                if not entry.is_dir():
                    continue
            else:
                if not (entry.is_file() and entry.suffix == ".md"):
                    continue
            created, updated = _stat_times(entry)
            out.append(
                VaultItem(
                    name=entry.name,
                    type=item_type,
                    path=str(entry),
                    description=_read_description_for_item(entry, item_type),
                    is_global_linked=True,
                    in_vault=False,
                    created_at=created,
                    updated_at=updated,
                )
            )
    return out


def import_to_vault(
    global_dir: os.PathLike[str] | str,
    vault_dir: os.PathLike[str] | str,
    item: VaultItem,
) -> None:
    """Move a global item into the vault and leave a symlink behind."""
    if item.type == "plugin":
        raise ValueError("Plugins cannot be imported to vault.")
    sub = _type_to_dir(item.type)
    src_path = Path(global_dir) / sub / item.name
    dest_path = Path(vault_dir) / sub / item.name
    (Path(vault_dir) / sub).mkdir(parents=True, exist_ok=True)

    if dest_path.exists():
        raise FileExistsError(f'"{item.name}" already exists in vault')

    if src_path.is_symlink():
        resolved = src_path.resolve()
        os.symlink(resolved, dest_path)
        return

    # Atomic-ish move; fall back to copy + remove (e.g. cross-device).
    try:
        os.rename(src_path, dest_path)
    except OSError:
        import shutil
        if item.type == "skill":
            shutil.copytree(src_path, dest_path)
            shutil.rmtree(src_path)
        else:
            shutil.copy2(src_path, dest_path)
            src_path.unlink()
    # Leave a symlink behind so Claude Code keeps finding it.
    os.symlink(dest_path, src_path)


def migrate_to_vault(
    global_dir: os.PathLike[str] | str,
    vault_dir: os.PathLike[str] | str,
) -> MigrateResult:
    """Bulk move every global skill/command/agent into the vault."""
    moved: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    gd = Path(global_dir)
    vd = Path(vault_dir)
    for sub in ("skills", "commands", "agents"):
        (vd / sub).mkdir(parents=True, exist_ok=True)

    for item_type, sub, is_dir in (
        ("skill", "skills", True),
        ("command", "commands", False),
        ("agent", "agents", False),
    ):
        src_dir = gd / sub
        if not src_dir.exists() or not src_dir.is_dir():
            continue
        try:
            entries = sorted(src_dir.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                s = entry.stat()
            except OSError:
                continue
            if is_dir and not entry.is_dir():
                continue
            if not is_dir:
                if not entry.is_file() or entry.suffix != ".md":
                    continue
            dest = vd / sub / entry.name
            if dest.exists():
                skipped.append(f"{item_type}:{entry.name}")
                continue
            try:
                if entry.is_symlink():
                    resolved = entry.resolve()
                    os.symlink(resolved, dest)
                    moved.append(f"{item_type}:{entry.name}")
                else:
                    try:
                        os.rename(entry, dest)
                        moved.append(f"{item_type}:{entry.name}")
                    except OSError:
                        import shutil
                        if is_dir:
                            shutil.copytree(entry, dest)
                            shutil.rmtree(entry)
                        else:
                            shutil.copy2(entry, dest)
                            entry.unlink()
                        moved.append(f"{item_type}:{entry.name}")
            except OSError as e:
                errors.append(f"{item_type}:{entry.name}: {e}")

    return MigrateResult(tuple(moved), tuple(skipped), tuple(errors))


# ─── Enriched listing for the TUI ────────────────────────────────────────────


def list_vault_items_with_project_state(
    vault_dir: os.PathLike[str] | str,
    project_dir: os.PathLike[str] | str,
    installed_plugins: Optional[list[PluginRef]] = None,
    global_dir: Optional[os.PathLike[str] | str] = None,
) -> list[VaultItem]:
    """`listVaultItems` enriched with project/global symlink state plus
    plugin-enabled state for the Extensions/Vault TUI tab."""
    items = list_vault_items(vault_dir)
    pd = Path(project_dir)
    gd = Path(global_dir) if global_dir else None
    claude_dir = pd / ".claude"

    for item in items:
        sub = _type_to_dir(item.type)
        link_path = claude_dir / sub / item.name
        item.is_linked = link_path.is_symlink() if link_path.exists() or link_path.is_symlink() else False
        if gd:
            g_link = gd / sub / item.name
            item.is_global_linked = g_link.is_symlink() if g_link.exists() or g_link.is_symlink() else False

    if installed_plugins:
        proj_settings = read_json(claude_dir / "settings.json", fallback={})
        enabled = proj_settings.get("enabledPlugins") if isinstance(proj_settings, dict) else {}
        if not isinstance(enabled, dict):
            enabled = {}
        global_enabled: dict[str, Any] = {}
        if gd:
            gs = read_json(gd / "settings.json", fallback={})
            ge = gs.get("enabledPlugins") if isinstance(gs, dict) else {}
            if isinstance(ge, dict):
                global_enabled = ge
        for p in installed_plugins:
            created: Optional[datetime] = None
            updated: Optional[datetime] = None
            if p.install_path:
                created, updated = _stat_times(Path(p.install_path))
            items.append(
                VaultItem(
                    name=p.name,
                    type="plugin",
                    path=p.install_path,
                    description=p.description,
                    is_linked=bool(enabled.get(p.id) is True),
                    is_global_linked=bool(global_enabled.get(p.id) is True),
                    created_at=created,
                    updated_at=updated,
                )
            )

    if gd:
        global_items = _list_global_non_vault_items(gd, Path(vault_dir))
        for g in global_items:
            sub = _type_to_dir(g.type)
            lp = claude_dir / sub / g.name
            g.is_linked = lp.is_symlink() if lp.exists() or lp.is_symlink() else False
        items += global_items

    return items


# ─── Marketplace ─────────────────────────────────────────────────────────────
#
# Sources are one of:
#   github:<owner>/<repo>     — clone via HTTPS or download tarball via API
#   git:<url>                 — clone an arbitrary git URL
#   dir:<absolute_path>       — point at an already-extracted directory
#
# Sync uses `git pull --ff-only` when the install dir is a git repo, or the
# GitHub tarball API otherwise. The plain GitHub repo+folder cases write a
# `.gcs-sha` file recording which commit was extracted.

import subprocess
import tempfile
import urllib.error
import urllib.request


GCS_SHA_FILE = ".gcs-sha"
DEFAULT_POOL_CONCURRENCY = 4


@dataclass(frozen=True)
class MarketplaceSource:
    """Tagged union. Exactly one of `repo`/`url`/`path` is set per `kind`."""
    kind: str  # "github" | "git" | "directory"
    repo: Optional[str] = None
    url: Optional[str] = None
    path: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"source": self.kind}
        if self.repo is not None:
            out["repo"] = self.repo
        if self.url is not None:
            out["url"] = self.url
        if self.path is not None:
            out["path"] = self.path
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "MarketplaceSource":
        return cls(
            kind=str(data.get("source", "")),
            repo=data.get("repo"),
            url=data.get("url"),
            path=data.get("path"),
        )


@dataclass(frozen=True)
class MarketplaceInfo:
    name: str
    source: MarketplaceSource
    install_location: str
    last_updated: str


@dataclass(frozen=True)
class SyncMarketplaceResult:
    before: str
    after: str
    updated: bool


@dataclass(frozen=True)
class VersionInfo:
    current: str
    remote: str
    updatable: bool
    error: Optional[str] = None


def parse_marketplace_source(input_str: str) -> MarketplaceSource:
    """Mirror the TS parser. Bare `owner/repo` defaults to github."""
    if input_str.startswith("github:"):
        return MarketplaceSource(kind="github", repo=input_str[len("github:"):])
    if input_str.startswith("git:"):
        return MarketplaceSource(kind="git", url=input_str[len("git:"):])
    if input_str.startswith("dir:"):
        return MarketplaceSource(kind="directory", path=input_str[len("dir:"):])
    if "/" in input_str and ":" not in input_str:
        return MarketplaceSource(kind="github", repo=input_str)
    raise ValueError(f"Invalid source format: {input_str}. Use github:user/repo, git:url, or dir:/path")


def _iso_now() -> str:
    """RFC3339-ish UTC timestamp with millisecond precision."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _read_known(km_path: os.PathLike[str] | str) -> dict[str, Any]:
    data = read_json(km_path, fallback={})
    return data if isinstance(data, dict) else {}


def list_marketplaces(km_path: os.PathLike[str] | str) -> list[MarketplaceInfo]:
    data = _read_known(km_path)
    out: list[MarketplaceInfo] = []
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        src = entry.get("source")
        if not isinstance(src, dict):
            continue
        out.append(
            MarketplaceInfo(
                name=name,
                source=MarketplaceSource.from_json(src),
                install_location=str(entry.get("installLocation", "")),
                last_updated=str(entry.get("lastUpdated", "")),
            )
        )
    return out


def is_git_repo(directory: os.PathLike[str] | str) -> bool:
    return (Path(directory) / ".git").exists()


def read_sha_file(directory: os.PathLike[str] | str) -> Optional[str]:
    p = Path(directory) / GCS_SHA_FILE
    try:
        sha = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return sha or None


def _git(args: list[str], cwd: Optional[Path] = None) -> tuple[int, str, str]:
    """Run `git ...`, capture stdout/stderr. Returns (exit_code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        return 127, "", f"git not found on PATH: {e}"
    return proc.returncode, proc.stdout, proc.stderr


def _git_short_hash(directory: os.PathLike[str] | str) -> str:
    code, out, err = _git(["git", "-C", str(directory), "rev-parse", "--short", "HEAD"])
    if code != 0:
        raise RuntimeError(f"git rev-parse failed in {directory} (exit {code}): {err.strip()}")
    h = out.strip()
    if not h:
        raise RuntimeError(f"git rev-parse returned empty in {directory}")
    return h


def _fetch_github_head_sha(repo: str) -> str:
    """GET https://api.github.com/repos/<owner/repo>/commits/HEAD with the
    sha media type to receive just the commit hash."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/commits/HEAD",
        headers={"Accept": "application/vnd.github.sha"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API error: {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"GitHub API error: {e.reason}") from e
    return body.strip()


def download_and_extract_tarball(repo: str, dest: os.PathLike[str] | str) -> str:
    """Download `<repo>` HEAD tarball, extract to `dest`, write `.gcs-sha`.
    Returns the full commit SHA."""
    import shutil
    import tarfile

    sha = _fetch_github_head_sha(repo)
    url = f"https://api.github.com/repos/{repo}/tarball/{sha}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})

    tmp_dir = Path(tempfile.mkdtemp(prefix="axt-tarball-"))
    try:
        archive = tmp_dir / "archive.tar.gz"
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                with archive.open("wb") as f:
                    shutil.copyfileobj(resp, f)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Tarball download failed: {e.code} {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Tarball download failed: {e.reason}") from e

        extract = tmp_dir / "extract"
        extract.mkdir()
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(extract)  # noqa: S202 — trusted source

        entries = [p for p in extract.iterdir() if p.is_dir()]
        if not entries:
            raise RuntimeError("Tarball extracted empty")
        src_dir = entries[0]

        dest_path = Path(dest)
        if dest_path.exists():
            shutil.rmtree(dest_path)
        dest_path.mkdir(parents=True)
        for item in src_dir.iterdir():
            target = dest_path / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        (dest_path / GCS_SHA_FILE).write_text(sha, encoding="utf-8")
        return sha
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def get_local_version(km_path: os.PathLike[str] | str, name: str) -> str:
    data = _read_known(km_path)
    entry = data.get(name)
    if not isinstance(entry, dict):
        return "?"
    src = MarketplaceSource.from_json(entry.get("source", {}))
    if src.kind == "directory":
        return "local"
    install = entry.get("installLocation", "")
    if is_git_repo(install):
        try:
            return _git_short_hash(install)
        except RuntimeError:
            return "error"
    sha = read_sha_file(install)
    return sha[:7] if sha else "unknown"


def get_marketplace_version(km_path: os.PathLike[str] | str, name: str) -> VersionInfo:
    data = _read_known(km_path)
    entry = data.get(name)
    if not isinstance(entry, dict):
        return VersionInfo(current="?", remote="?", updatable=False, error=f'"{name}" not found')
    src = MarketplaceSource.from_json(entry.get("source", {}))
    if src.kind == "directory":
        return VersionInfo(current="local", remote="local", updatable=False)
    install = entry.get("installLocation", "")

    if is_git_repo(install):
        try:
            current = _git_short_hash(install)
            code, _, err = _git(["git", "-C", install, "fetch", "--quiet"])
            if code != 0:
                return VersionInfo(current="?", remote="?", updatable=False, error=err.strip())
            code, out, err = _git(["git", "-C", install, "rev-parse", "--short", "@{u}"])
            if code != 0:
                return VersionInfo(current=current, remote="?", updatable=False, error=err.strip() or "no upstream")
            remote = out.strip()
            return VersionInfo(current=current, remote=remote, updatable=current != remote)
        except RuntimeError as e:
            return VersionInfo(current="?", remote="?", updatable=False, error=str(e))

    if src.kind == "github" and src.repo:
        try:
            local_sha = read_sha_file(install)
            current = local_sha[:7] if local_sha else "unknown"
            remote_sha = _fetch_github_head_sha(src.repo)
            remote = remote_sha[:7]
            return VersionInfo(current=current, remote=remote, updatable=current != remote)
        except RuntimeError as e:
            return VersionInfo(current="?", remote="?", updatable=False, error=str(e))

    return VersionInfo(current="?", remote="?", updatable=False, error="Non-git source without .git directory")


def add_marketplace(
    km_path: os.PathLike[str] | str,
    marketplaces_dir: os.PathLike[str] | str,
    name: str,
    source: MarketplaceSource,
) -> None:
    data = _read_known(km_path)
    if name in data:
        raise ValueError(f'Marketplace "{name}" already exists')

    if source.kind == "directory":
        if not source.path or not Path(source.path).exists():
            raise FileNotFoundError(f"Directory not found: {source.path}")
        install_location = source.path
    else:
        install_location = str(Path(marketplaces_dir) / name)
        if source.kind == "github":
            url = f"https://github.com/{source.repo}.git"
        elif source.kind == "git":
            url = source.url or ""
        else:
            raise ValueError(f"Unknown source kind: {source.kind}")
        code, _, err = _git(["git", "clone", "--depth", "1", url, install_location])
        if code != 0:
            raise RuntimeError(f"git clone failed (exit {code}): {err.strip()}")

    data[name] = {
        "source": source.to_json(),
        "installLocation": install_location,
        "lastUpdated": _iso_now(),
    }
    write_json_atomic(km_path, data)


def remove_marketplace(
    km_path: os.PathLike[str] | str,
    marketplaces_dir: os.PathLike[str] | str,
    name: str,
) -> None:
    import shutil
    data = _read_known(km_path)
    if name not in data:
        raise KeyError(f'Marketplace "{name}" not found')
    install_location = str(data[name].get("installLocation", ""))
    del data[name]
    write_json_atomic(km_path, data)
    if install_location.startswith(str(marketplaces_dir)):
        shutil.rmtree(install_location, ignore_errors=True)


def sync_marketplace(km_path: os.PathLike[str] | str, name: str) -> SyncMarketplaceResult:
    data = _read_known(km_path)
    entry = data.get(name)
    if not isinstance(entry, dict):
        raise KeyError(f'Marketplace "{name}" not found')
    src = MarketplaceSource.from_json(entry.get("source", {}))
    install = entry.get("installLocation", "")

    if src.kind == "directory":
        before = after = "local"
    elif is_git_repo(install):
        before = _git_short_hash(install)
        code, _, err = _git(["git", "-C", install, "pull", "--ff-only"])
        if code != 0:
            raise RuntimeError(f'git pull failed for "{name}" (exit {code}): {err.strip()}')
        after = _git_short_hash(install)
    elif src.kind == "github" and src.repo:
        local_sha = read_sha_file(install)
        before = local_sha[:7] if local_sha else "unknown"
        new_sha = download_and_extract_tarball(src.repo, install)
        after = new_sha[:7]
    else:
        raise RuntimeError(f'Cannot sync "{name}": not a git repo and not a github source')

    entry["lastUpdated"] = _iso_now()
    write_json_atomic(km_path, data)
    return SyncMarketplaceResult(before=before, after=after, updated=before != after)


@dataclass(frozen=True)
class PooledError:
    item: Any
    error: Exception


@dataclass(frozen=True)
class PooledResult:
    results: dict[Any, Any]
    errors: tuple[PooledError, ...]


def pooled_map(
    items: list[Any],
    fn,
    *,
    concurrency: int = DEFAULT_POOL_CONCURRENCY,
    on_result=None,
    on_error=None,
) -> PooledResult:
    """Concurrent fan-out using ThreadPoolExecutor.

    The TS version is async-await with a shared queue; for Python's blocking
    git/urllib calls, threads are the natural primitive. Result order inside
    `results` is unspecified — recover via the input list when ordering
    matters.
    """
    from concurrent.futures import ThreadPoolExecutor

    results: dict[Any, Any] = {}
    errors: list[PooledError] = []
    workers = max(1, min(concurrency, len(items))) if items else 1
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fn, item): item for item in items}
        for fut in futures:
            item = futures[fut]
            try:
                value = fut.result()
            except Exception as e:  # noqa: BLE001 — funnel into PooledError
                err = e if isinstance(e, Exception) else Exception(str(e))
                errors.append(PooledError(item=item, error=err))
                if on_error:
                    on_error(item, err)
            else:
                results[item] = value
                if on_result:
                    on_result(item, value)
    return PooledResult(results=results, errors=tuple(errors))


# ── Section 6: Usage Parsers ─────────────────────────────────────────────────
#
# Four data sources normalized into `UnifiedUsageEntry`:
#   Claude  — JSONL per session under ~/.claude/projects/<proj>/<session>.jsonl
#             with mtime-based per-file cache at ~/.config/axt/cache/claude-usage.json
#   Codex   — JSONL with `session_meta` + `event_msg(token_count)` records
#   Gemini  — JSON or JSONL session files at <gemini_tmp>/<proj>/chats/session-*.{json,jsonl}
#   Cursor  — SQLite (stdlib `sqlite3`) at ~/.cursor/ai-tracking/ai-code-tracking.db
#
# Filter semantics differ between platforms (matches TS):
#   Claude: ms-precision since/until via Date.getTime()
#   Codex/Gemini: YYYY-MM-DD string prefix comparison
#
# Cache:
#   Claude per-file mtime cache (5-min validity). Codex/Gemini intentionally
#   uncached — small datasets that benefit more from freshness than from
#   serialization.

import sqlite3
from glob import iglob


# ─── Unified usage entry & rate limit ────────────────────────────────────────


PLATFORMS: tuple[str, ...] = ("claude", "codex", "gemini")


@dataclass(frozen=True)
class UnifiedUsageEntry:
    platform: str  # one of PLATFORMS
    model: str
    timestamp: str
    session_id: str
    project_path: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    reasoning_tokens: int = 0
    tool_tokens: int = 0


@dataclass(frozen=True)
class RateLimitInfo:
    platform: str
    used_percent: float
    window_minutes: int
    resets_at: Optional[str]  # ISO string or None


@dataclass(frozen=True)
class RateLimitData:
    """Decoded `usage-snapshot.json` (Claude). Both five_hour/seven_day are
    optional. `None` percentages mean the snapshot is stale or absent."""
    five_hour: Optional[int]
    seven_day: Optional[int]
    five_hour_reset_at: Optional[datetime]
    seven_day_reset_at: Optional[datetime]


# ─── Claude usage parser + cache ─────────────────────────────────────────────


@dataclass(frozen=True)
class ClaudeUsageEntry:
    """Native Claude shape before normalization. Kept distinct so the cache
    on disk can roundtrip without ambiguity."""
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    session_id: str
    project_path: str
    timestamp: str


def _ts_ms(iso: str) -> Optional[int]:
    """Parse an ISO timestamp into ms since epoch, or None if unparseable."""
    if not iso:
        return None
    try:
        # Python 3.11+ accepts trailing 'Z' in fromisoformat; older versions
        # need it replaced.
        s = iso.replace("Z", "+00:00") if iso.endswith("Z") else iso
        dt = datetime.fromisoformat(s)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def parse_claude_jsonl(file_path: os.PathLike[str] | str) -> list[ClaudeUsageEntry]:
    """Iterate each line, yield `assistant` records' usage block."""
    p = Path(file_path)
    project_path = p.parent.name
    out: list[ClaudeUsageEntry] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict) or rec.get("type") != "assistant":
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                out.append(
                    ClaudeUsageEntry(
                        model=str(msg.get("model") or "unknown"),
                        input_tokens=int(usage.get("input_tokens") or 0),
                        output_tokens=int(usage.get("output_tokens") or 0),
                        cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                        cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                        session_id=str(rec.get("sessionId") or ""),
                        project_path=project_path,
                        timestamp=str(rec.get("timestamp") or ""),
                    )
                )
    except OSError:
        pass
    return out


def filter_by_timestamp_ms(
    entries: list,
    since_ms: Optional[int],
    until_ms: Optional[int],
    *,
    key=lambda e: e.timestamp,
) -> list:
    """Claude semantics: millisecond compare via parsed timestamp."""
    if since_ms is None and until_ms is None:
        return entries
    out = []
    for e in entries:
        ts = _ts_ms(key(e))
        if ts is None:
            continue
        if since_ms is not None and ts < since_ms:
            continue
        if until_ms is not None and ts > until_ms:
            continue
        out.append(e)
    return out


def filter_by_date_string(
    entries: list,
    since: Optional[str],
    until: Optional[str],
    *,
    key=lambda e: e.timestamp,
) -> list:
    """Codex/Gemini semantics: 10-char YYYY-MM-DD prefix compare."""
    if not since and not until:
        return entries
    out = []
    for e in entries:
        date = key(e)[:10]
        if since and date < since:
            continue
        if until and date > until:
            continue
        out.append(e)
    return out


# ─── Cache helpers ───────────────────────────────────────────────────────────


CACHE_DIR_FOR_USAGE: Path = AXT_CONFIG_DIR / "cache"


def _cache_path(platform: str) -> Path:
    return CACHE_DIR_FOR_USAGE / f"{platform}-usage.json"


def _file_mtime_ms(path: os.PathLike[str] | str) -> float:
    try:
        return Path(path).stat().st_mtime * 1000
    except OSError:
        return 0.0


def load_cached_usage(platform: str) -> dict[str, Any]:
    return read_json(
        _cache_path(platform),
        fallback={"version": 1, "lastUpdated": "", "files": {}},
    )


def save_cached_usage(platform: str, cache: dict[str, Any]) -> None:
    cache["lastUpdated"] = _iso_now()
    write_json_atomic(_cache_path(platform), cache)


def is_cache_valid(cache: dict[str, Any], max_age_ms: int = 5 * 60 * 1000) -> bool:
    last_updated = cache.get("lastUpdated")
    if not last_updated:
        return False
    ts = _ts_ms(last_updated)
    if ts is None:
        return False
    age = int(datetime.now(timezone.utc).timestamp() * 1000) - ts
    return age < max_age_ms


def _claude_entry_to_dict(e: ClaudeUsageEntry) -> dict[str, Any]:
    return {
        "model": e.model,
        "inputTokens": e.input_tokens,
        "outputTokens": e.output_tokens,
        "cacheCreationTokens": e.cache_creation_tokens,
        "cacheReadTokens": e.cache_read_tokens,
        "sessionId": e.session_id,
        "projectPath": e.project_path,
        "timestamp": e.timestamp,
    }


def _claude_entry_from_dict(d: dict[str, Any]) -> ClaudeUsageEntry:
    return ClaudeUsageEntry(
        model=str(d.get("model") or "unknown"),
        input_tokens=int(d.get("inputTokens") or 0),
        output_tokens=int(d.get("outputTokens") or 0),
        cache_creation_tokens=int(d.get("cacheCreationTokens") or 0),
        cache_read_tokens=int(d.get("cacheReadTokens") or 0),
        session_id=str(d.get("sessionId") or ""),
        project_path=str(d.get("projectPath") or ""),
        timestamp=str(d.get("timestamp") or ""),
    )


def load_all_claude_usage(
    projects_dir: os.PathLike[str] | str,
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
    project: Optional[str] = None,
    force_refresh: bool = False,
) -> list[ClaudeUsageEntry]:
    """Cached per-file Claude loader.

    Cache shape (matches TS):
      { version: 1, lastUpdated, projectsDir, files: { <abs>: { mtime, entries } } }
    """
    projects_dir = str(projects_dir)
    since_ms = _ts_ms(since) if since else None
    until_ms = _ts_ms(until) if until else None

    cache = load_cached_usage("claude")

    if (
        not force_refresh
        and is_cache_valid(cache)
        and cache.get("projectsDir") == projects_dir
    ):
        all_cached: list[ClaudeUsageEntry] = []
        for entry in (cache.get("files") or {}).values():
            for e in entry.get("entries") or []:
                all_cached.append(_claude_entry_from_dict(e))
        return _claude_filter(all_cached, since_ms, until_ms, project)

    if cache.get("projectsDir") != projects_dir:
        cache = {"version": 1, "lastUpdated": "", "projectsDir": projects_dir, "files": {}}
    cache["projectsDir"] = projects_dir

    pd = Path(projects_dir)
    if not pd.exists() or not pd.is_dir():
        return []

    # Glob `*/*.jsonl` (one level deep, like the TS `*/*.jsonl` pattern).
    files = sorted(str(f) for f in pd.glob("*/*.jsonl"))
    if not files:
        return []

    changed = False
    file_cache: dict[str, dict[str, Any]] = cache.setdefault("files", {})

    for file_path in files:
        proj_name = Path(file_path).parent.name
        if project and proj_name != project:
            continue
        mtime = _file_mtime_ms(file_path)
        cached_file = file_cache.get(file_path)
        if cached_file and float(cached_file.get("mtime", 0)) >= mtime:
            continue
        entries = parse_claude_jsonl(file_path)
        file_cache[file_path] = {
            "mtime": mtime,
            "entries": [_claude_entry_to_dict(e) for e in entries],
        }
        changed = True

    if changed:
        save_cached_usage("claude", cache)

    all_entries: list[ClaudeUsageEntry] = []
    for entry in file_cache.values():
        for e in entry.get("entries") or []:
            all_entries.append(_claude_entry_from_dict(e))
    return _claude_filter(all_entries, since_ms, until_ms, project)


def _claude_filter(
    entries: list[ClaudeUsageEntry],
    since_ms: Optional[int],
    until_ms: Optional[int],
    project: Optional[str],
) -> list[ClaudeUsageEntry]:
    if project:
        entries = [e for e in entries if e.project_path == project]
    return filter_by_timestamp_ms(entries, since_ms, until_ms)


# ─── Codex usage parser ──────────────────────────────────────────────────────


def parse_codex_file(file_path: os.PathLike[str] | str) -> list[UnifiedUsageEntry]:
    """Codex JSONL: session_meta announces model+session, event_msg/token_count records token usage."""
    p = Path(file_path)
    session_id = p.stem
    project_path = p.parent.name
    current_model = "unknown"
    out: list[UnifiedUsageEntry] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("type") == "session_meta":
                    payload = rec.get("payload") or {}
                    if isinstance(payload, dict):
                        if payload.get("model"):
                            current_model = str(payload["model"])
                        if payload.get("session_id"):
                            session_id = str(payload["session_id"])
                    continue
                if rec.get("type") == "event_msg":
                    payload = rec.get("payload") or {}
                    if not isinstance(payload, dict) or payload.get("type") != "token_count":
                        continue
                    info = payload.get("info") or {}
                    usage = info.get("last_token_usage") if isinstance(info, dict) else None
                    if not isinstance(usage, dict):
                        continue
                    out.append(
                        UnifiedUsageEntry(
                            platform="codex",
                            model=current_model,
                            timestamp=str(rec.get("timestamp") or ""),
                            session_id=session_id,
                            project_path=project_path,
                            input_tokens=int(usage.get("input_tokens") or 0),
                            output_tokens=int(usage.get("output_tokens") or 0),
                            cache_write_tokens=0,
                            cache_read_tokens=int(usage.get("cached_input_tokens") or 0),
                            reasoning_tokens=int(usage.get("reasoning_output_tokens") or 0),
                            tool_tokens=0,
                        )
                    )
    except OSError:
        pass
    return out


def extract_codex_rate_limit(file_path: os.PathLike[str] | str) -> Optional[RateLimitInfo]:
    """Find the most recent `event_msg(token_count)` with rate_limits.primary."""
    p = Path(file_path)
    try:
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "event_msg":
            continue
        payload = rec.get("payload") or {}
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        rl = payload.get("rate_limits") or {}
        primary = rl.get("primary") if isinstance(rl, dict) else None
        if not isinstance(primary, dict):
            continue
        return RateLimitInfo(
            platform="codex",
            used_percent=float(primary.get("used_percent") or 0),
            window_minutes=int(primary.get("window_minutes") or 300),
            resets_at=primary.get("resets_at"),
        )
    return None


def load_codex_usage(
    sessions_dir: os.PathLike[str] | str,
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> list[UnifiedUsageEntry]:
    sd = Path(sessions_dir)
    if not sd.exists() or not sd.is_dir():
        return []
    out: list[UnifiedUsageEntry] = []
    # Recursive `**/*.jsonl`.
    for f in sorted(str(x) for x in sd.rglob("*.jsonl")):
        out.extend(parse_codex_file(f))
    return filter_by_date_string(out, since, until)


# ─── Gemini usage parser ─────────────────────────────────────────────────────


def parse_gemini_file(file_path: os.PathLike[str] | str) -> list[UnifiedUsageEntry]:
    p = Path(file_path)
    try:
        if p.suffix == ".jsonl":
            # First record contains the session shape (TS reads only [0]).
            with p.open("r", encoding="utf-8") as f:
                first_line = next((l for l in f if l.strip()), None)
            if not first_line:
                return []
            session = json.loads(first_line)
        else:
            session = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, StopIteration):
        return []

    if not isinstance(session, dict):
        return []

    session_id = str(session.get("sessionId") or p.stem)
    chats_dir = p.parent
    project_slug = chats_dir.parent.name

    out: list[UnifiedUsageEntry] = []
    for msg in session.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "gemini":
            continue
        tokens = msg.get("tokens")
        if not isinstance(tokens, dict):
            continue
        out.append(
            UnifiedUsageEntry(
                platform="gemini",
                model=str(msg.get("model") or "unknown"),
                timestamp=str(msg.get("timestamp") or ""),
                session_id=session_id,
                project_path=project_slug,
                input_tokens=int(tokens.get("input") or 0),
                output_tokens=int(tokens.get("output") or 0),
                cache_write_tokens=0,
                cache_read_tokens=int(tokens.get("cached") or 0),
                reasoning_tokens=int(tokens.get("thoughts") or 0),
                tool_tokens=int(tokens.get("tool") or 0),
            )
        )
    return out


def load_gemini_usage(
    gemini_tmp_dir: os.PathLike[str] | str,
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> list[UnifiedUsageEntry]:
    base = Path(gemini_tmp_dir)
    if not base.exists() or not base.is_dir():
        return []
    out: list[UnifiedUsageEntry] = []
    # Glob `<proj>/chats/session-*.{json,jsonl}`.
    for ext in ("json", "jsonl"):
        for f in sorted(str(x) for x in base.glob(f"*/chats/session-*.{ext}")):
            out.extend(parse_gemini_file(f))
    return filter_by_date_string(out, since, until)


# ─── Cursor metrics (SQLite) ─────────────────────────────────────────────────


@dataclass(frozen=True)
class CursorCommitMetrics:
    commit_hash: str
    branch_name: str
    scored_at: int  # unix ms
    lines_added: int
    lines_deleted: int
    human_lines_added: int
    human_lines_deleted: int
    composer_lines_added: int
    composer_lines_deleted: int
    ai_percentage: float
    commit_message: str
    commit_date: str  # YYYY-MM-DD


@dataclass(frozen=True)
class CursorSummary:
    total_commits: int
    total_lines_added: int
    total_lines_deleted: int
    human_lines_added: int
    human_lines_deleted: int
    ai_lines_added: int
    ai_lines_deleted: int
    avg_ai_percentage: float


def load_cursor_metrics(
    db_path: os.PathLike[str] | str,
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> list[CursorCommitMetrics]:
    p = Path(db_path)
    if not p.exists():
        return []

    # Open read-only via URI mode so concurrent access from Cursor itself
    # doesn't trip the lock.
    uri = f"file:{p}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error:
        return []

    try:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM scored_commits"
        clauses: list[str] = []
        params: list[Any] = []
        if since:
            clauses.append("commitDate >= ?")
            params.append(since)
        if until:
            clauses.append("commitDate <= ?")
            params.append(until)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY scoredAt DESC"

        out: list[CursorCommitMetrics] = []
        for row in conn.execute(sql, params):
            ai_pct_raw = row["v2AiPercentage"] if "v2AiPercentage" in row.keys() else None
            if ai_pct_raw is None:
                ai_pct_raw = row["v1AiPercentage"] if "v1AiPercentage" in row.keys() else None
            try:
                ai_pct = float(ai_pct_raw) if ai_pct_raw is not None else 0.0
            except (TypeError, ValueError):
                ai_pct = 0.0
            out.append(
                CursorCommitMetrics(
                    commit_hash=str(row["commitHash"] or ""),
                    branch_name=str(row["branchName"] or ""),
                    scored_at=int(row["scoredAt"] or 0),
                    lines_added=int(row["linesAdded"] or 0),
                    lines_deleted=int(row["linesDeleted"] or 0),
                    human_lines_added=int(row["humanLinesAdded"] or 0),
                    human_lines_deleted=int(row["humanLinesDeleted"] or 0),
                    composer_lines_added=int(row["composerLinesAdded"] or 0),
                    composer_lines_deleted=int(row["composerLinesDeleted"] or 0),
                    ai_percentage=ai_pct,
                    commit_message=str(row["commitMessage"] or ""),
                    commit_date=str(row["commitDate"] or ""),
                )
            )
        return out
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def summarize_cursor_metrics(metrics: list[CursorCommitMetrics]) -> CursorSummary:
    if not metrics:
        return CursorSummary(0, 0, 0, 0, 0, 0, 0, 0.0)
    total_added = sum(m.lines_added for m in metrics)
    total_deleted = sum(m.lines_deleted for m in metrics)
    human_added = sum(m.human_lines_added for m in metrics)
    human_deleted = sum(m.human_lines_deleted for m in metrics)
    return CursorSummary(
        total_commits=len(metrics),
        total_lines_added=total_added,
        total_lines_deleted=total_deleted,
        human_lines_added=human_added,
        human_lines_deleted=human_deleted,
        ai_lines_added=total_added - human_added,
        ai_lines_deleted=total_deleted - human_deleted,
        avg_ai_percentage=sum(m.ai_percentage for m in metrics) / len(metrics),
    )


# ─── Rate-limit snapshot ─────────────────────────────────────────────────────


def _parse_percent(value: Any) -> Optional[int]:
    if not isinstance(value, (int, float)):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not (v == v):  # NaN check
        return None
    return round(max(0.0, min(100.0, v)))


def _parse_date(value: Any) -> Optional[datetime]:
    if isinstance(value, (int, float)) and value > 0:
        ms = value if value > 1e12 else value * 1000
        try:
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            s = value.replace("Z", "+00:00") if value.endswith("Z") else value
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


def read_rate_limits(
    snapshot_path: os.PathLike[str] | str,
    *,
    freshness_ms: int = 5 * 60 * 1000,
) -> Optional[RateLimitData]:
    """Read `usage-snapshot.json`. Returns `None` if missing, malformed, or
    stale (older than `freshness_ms`)."""
    p = Path(snapshot_path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        snap = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(snap, dict):
        return None

    updated_at = _parse_date(snap.get("updated_at"))
    if not updated_at:
        return None
    age_ms = int((datetime.now(timezone.utc) - updated_at).total_seconds() * 1000)
    if age_ms > freshness_ms:
        return None

    five = snap.get("five_hour") or {}
    seven = snap.get("seven_day") or {}
    five_pct = _parse_percent(five.get("used_percentage") if isinstance(five, dict) else None)
    seven_pct = _parse_percent(seven.get("used_percentage") if isinstance(seven, dict) else None)
    if five_pct is None and seven_pct is None:
        return None
    return RateLimitData(
        five_hour=five_pct,
        seven_day=seven_pct,
        five_hour_reset_at=_parse_date(five.get("resets_at") if isinstance(five, dict) else None),
        seven_day_reset_at=_parse_date(seven.get("resets_at") if isinstance(seven, dict) else None),
    )


# ─── Unified loader + claude→unified adapter ─────────────────────────────────


def claude_to_unified(e: ClaudeUsageEntry) -> UnifiedUsageEntry:
    return UnifiedUsageEntry(
        platform="claude",
        model=e.model,
        timestamp=e.timestamp,
        session_id=e.session_id,
        project_path=e.project_path,
        input_tokens=e.input_tokens,
        output_tokens=e.output_tokens,
        cache_write_tokens=e.cache_creation_tokens,
        cache_read_tokens=e.cache_read_tokens,
        reasoning_tokens=0,
        tool_tokens=0,
    )


def load_unified_usage(
    *,
    claude_projects_dir: os.PathLike[str] | str,
    codex_sessions_dir: os.PathLike[str] | str,
    gemini_tmp_dir: os.PathLike[str] | str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    platform: str = "all",
    project: Optional[str] = None,
    force_refresh: bool = False,
) -> list[UnifiedUsageEntry]:
    """Run all (or one) platform loaders in series, normalize, sort by ts."""
    entries: list[UnifiedUsageEntry] = []
    if platform in ("all", "claude"):
        try:
            claude_entries = load_all_claude_usage(
                claude_projects_dir,
                since=since,
                until=until,
                project=project,
                force_refresh=force_refresh,
            )
            entries += [claude_to_unified(e) for e in claude_entries]
        except OSError:
            pass
    if platform in ("all", "codex"):
        try:
            entries += load_codex_usage(codex_sessions_dir, since=since, until=until)
        except OSError:
            pass
    if platform in ("all", "gemini"):
        try:
            entries += load_gemini_usage(gemini_tmp_dir, since=since, until=until)
        except OSError:
            pass
    return sorted(entries, key=lambda e: e.timestamp)


# ─── Aggregation: daily / session / 5-hour blocks ────────────────────────────


@dataclass(frozen=True)
class DailyUsage:
    date: str  # YYYY-MM-DD (in caller's timezone)
    sessions: int
    models: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int


@dataclass(frozen=True)
class SessionUsage:
    session_id: str
    project_path: str
    models: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    first_timestamp: str
    last_timestamp: str
    message_count: int


@dataclass(frozen=True)
class BlockUsage:
    start_time: str  # ISO
    end_time: str  # ISO
    duration_hours: int  # always 5
    total_tokens: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    is_active: bool
    burn_rate_per_min: Optional[float]


def _date_in_tz(iso: str, tz: str) -> str:
    """Convert ISO timestamp to YYYY-MM-DD in `tz`. Falls back to UTC slice."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # Python 3.8 lacks zoneinfo, fall back to UTC.
        return iso[:10]
    try:
        s = iso.replace("Z", "+00:00") if iso.endswith("Z") else iso
        dt = datetime.fromisoformat(s)
        return dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")
    except (ValueError, KeyError, Exception):  # noqa: BLE001
        return iso[:10]


def aggregate_daily(entries: list[ClaudeUsageEntry], timezone_name: str) -> list[DailyUsage]:
    buckets: dict[str, dict[str, Any]] = {}
    for e in entries:
        date = _date_in_tz(e.timestamp, timezone_name)
        b = buckets.setdefault(
            date,
            {
                "input": 0,
                "output": 0,
                "cw": 0,
                "cr": 0,
                "sessions": set(),
                "models": set(),
            },
        )
        b["input"] += e.input_tokens
        b["output"] += e.output_tokens
        b["cw"] += e.cache_creation_tokens
        b["cr"] += e.cache_read_tokens
        b["sessions"].add(e.session_id)
        b["models"].add(e.model)
    return [
        DailyUsage(
            date=date,
            sessions=len(b["sessions"]),
            models=tuple(sorted(b["models"])),
            input_tokens=b["input"],
            output_tokens=b["output"],
            cache_creation_tokens=b["cw"],
            cache_read_tokens=b["cr"],
        )
        for date, b in sorted(buckets.items())
    ]


def aggregate_by_session(entries: list[ClaudeUsageEntry]) -> list[SessionUsage]:
    buckets: dict[str, dict[str, Any]] = {}
    for e in entries:
        b = buckets.setdefault(
            e.session_id,
            {
                "project": e.project_path,
                "models": set(),
                "input": 0,
                "output": 0,
                "cw": 0,
                "cr": 0,
                "count": 0,
                "timestamps": [],
            },
        )
        b["input"] += e.input_tokens
        b["output"] += e.output_tokens
        b["cw"] += e.cache_creation_tokens
        b["cr"] += e.cache_read_tokens
        b["count"] += 1
        b["models"].add(e.model)
        b["timestamps"].append(e.timestamp)
    out: list[SessionUsage] = []
    for sid, b in buckets.items():
        ts_sorted = sorted(b["timestamps"])
        out.append(
            SessionUsage(
                session_id=sid,
                project_path=b["project"],
                models=tuple(sorted(b["models"])),
                input_tokens=b["input"],
                output_tokens=b["output"],
                cache_creation_tokens=b["cw"],
                cache_read_tokens=b["cr"],
                first_timestamp=ts_sorted[0] if ts_sorted else "",
                last_timestamp=ts_sorted[-1] if ts_sorted else "",
                message_count=b["count"],
            )
        )
    return out


BLOCK_HOURS = 5
BLOCK_MS = BLOCK_HOURS * 60 * 60 * 1000


def compute_blocks(entries: list[ClaudeUsageEntry], timezone_name: str) -> list[BlockUsage]:
    """5-hour UTC-aligned billing blocks. `timezone_name` is accepted for
    API parity but not used (windows are always UTC-aligned)."""
    del timezone_name  # noqa: F841 — TS signature parity only

    if not entries:
        return []

    window_map: dict[int, list[ClaudeUsageEntry]] = {}
    for e in entries:
        ts_ms = _ts_ms(e.timestamp)
        if ts_ms is None:
            continue
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start_ms = int(day_start.timestamp() * 1000)
        ms_since_midnight = ts_ms - day_start_ms
        window_index = ms_since_midnight // BLOCK_MS
        window_start = day_start_ms + window_index * BLOCK_MS
        window_map.setdefault(window_start, []).append(e)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    blocks: list[BlockUsage] = []
    for window_start, window_entries in window_map.items():
        window_end = window_start + BLOCK_MS
        start_iso = datetime.fromtimestamp(window_start / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        end_iso = datetime.fromtimestamp(window_end / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")

        total_input = sum(e.input_tokens for e in window_entries)
        total_output = sum(e.output_tokens for e in window_entries)
        total_cw = sum(e.cache_creation_tokens for e in window_entries)
        total_cr = sum(e.cache_read_tokens for e in window_entries)
        total = total_input + total_output + total_cw + total_cr

        is_active = window_start <= now_ms < window_end
        burn: Optional[float] = None
        if is_active:
            elapsed_min = (now_ms - window_start) / 60_000
            burn = total / elapsed_min if elapsed_min > 0 else None

        blocks.append(
            BlockUsage(
                start_time=start_iso,
                end_time=end_iso,
                duration_hours=BLOCK_HOURS,
                total_tokens=total,
                input_tokens=total_input,
                output_tokens=total_output,
                cache_creation_tokens=total_cw,
                cache_read_tokens=total_cr,
                is_active=is_active,
                burn_rate_per_min=burn,
            )
        )
    blocks.sort(key=lambda b: b.start_time)
    return blocks


# ── Section 7: Pricing, Plans & Config ───────────────────────────────────────
#
# Pricing lives in `pricing.json` (sibling of axt.py) so updates don't
# require source edits. Looked up by exact model id with a `startswith`
# fallback for versioned model strings ("gpt-5-2026-01-01" → "gpt-5").


@dataclass(frozen=True)
class ModelPricing:
    """Per-million-token rates in USD."""
    input: float
    output: float
    cache_write: float
    cache_read: float
    context_window: Optional[int] = None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


_PRICING_CACHE: Optional[dict[str, ModelPricing]] = None


def _pricing_table() -> dict[str, ModelPricing]:
    """Lazy-load pricing.json (looked for next to axt.py)."""
    global _PRICING_CACHE
    if _PRICING_CACHE is not None:
        return _PRICING_CACHE
    pricing_path = Path(__file__).resolve().parent / "pricing.json"
    data = read_json(pricing_path, fallback={"models": {}})
    table: dict[str, ModelPricing] = {}
    for model_id, fields in (data.get("models") or {}).items():
        if not isinstance(fields, dict):
            continue
        table[model_id] = ModelPricing(
            input=float(fields.get("input", 0)),
            output=float(fields.get("output", 0)),
            cache_write=float(fields.get("cacheWrite", 0)),
            cache_read=float(fields.get("cacheRead", 0)),
            context_window=int(fields["contextWindow"]) if "contextWindow" in fields else None,
        )
    _PRICING_CACHE = table
    return table


def reload_pricing_table() -> None:
    """For tests / hot reloads."""
    global _PRICING_CACHE
    _PRICING_CACHE = None


def get_model_pricing(model_id: str) -> Optional[ModelPricing]:
    table = _pricing_table()
    direct = table.get(model_id)
    if direct is not None:
        return direct
    # Prefix match: longest-key-first so `claude-opus-4-7-r1` prefers
    # `claude-opus-4-7` over `claude-opus-4`.
    for key in sorted(table.keys(), key=len, reverse=True):
        if model_id.startswith(key):
            return table[key]
    return None


def get_context_window_size(model_id: str) -> Optional[int]:
    p = get_model_pricing(model_id)
    return p.context_window if p else None


def calculate_cost(usage: TokenUsage, model_id: str) -> float:
    p = get_model_pricing(model_id)
    if p is None:
        return 0.0
    per_m = 1_000_000
    return (
        (usage.input_tokens / per_m) * p.input
        + (usage.output_tokens / per_m) * p.output
        + (usage.cache_creation_tokens / per_m) * p.cache_write
        + (usage.cache_read_tokens / per_m) * p.cache_read
    )


def convert_currency(amount: float, from_ccy: str, to_ccy: str, exchange_rate: float) -> float:
    """Convert between USD and KRW; passthrough otherwise."""
    if from_ccy == to_ccy:
        return amount
    if from_ccy == "usd" and to_ccy == "krw":
        return amount * exchange_rate
    if from_ccy == "krw" and to_ccy == "usd":
        return amount / exchange_rate if exchange_rate else amount
    return amount


# ─── Plans ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlanConfig:
    plan: str
    monthly_cost: float
    billing_cycle_start: int = 1
    daily_request_limit: Optional[int] = None


@dataclass(frozen=True)
class PlanUsage:
    plan: str
    monthly_cost: float
    current_period_cost: float
    projected_monthly_cost: float
    days_elapsed: int
    days_remaining: int
    daily_avg_cost: float


def project_monthly_cost(current_cost: float, days_elapsed: int, total_days: int) -> float:
    if days_elapsed <= 0:
        return 0.0
    daily_avg = current_cost / days_elapsed
    return daily_avg * total_days


def compute_plan_usage(
    config: PlanConfig,
    current_cost: float,
    days_elapsed: int,
    total_days: int,
) -> PlanUsage:
    daily_avg = current_cost / days_elapsed if days_elapsed > 0 else 0.0
    days_remaining = max(0, total_days - days_elapsed)
    projected = project_monthly_cost(current_cost, days_elapsed, total_days)
    return PlanUsage(
        plan=config.plan,
        monthly_cost=config.monthly_cost,
        current_period_cost=current_cost,
        projected_monthly_cost=projected,
        days_elapsed=days_elapsed,
        days_remaining=days_remaining,
        daily_avg_cost=daily_avg,
    )


def get_days_in_billing_period(billing_start: int, now: Optional[datetime] = None) -> tuple[int, int]:
    """Return (elapsed_days, total_days) for the current billing cycle.

    `billing_start` is a day-of-month [1..28]. The cycle that contains `now`
    starts on the most recent occurrence of that day. Total days = exact
    length of that cycle (UTC).
    """
    n = now or datetime.now(timezone.utc)
    n_utc = n.astimezone(timezone.utc)
    year, month = n_utc.year, n_utc.month
    period_start = datetime(year, month, min(billing_start, 28), tzinfo=timezone.utc)
    if period_start > n_utc:
        # Roll back one month.
        if month == 1:
            period_start = datetime(year - 1, 12, min(billing_start, 28), tzinfo=timezone.utc)
        else:
            period_start = datetime(year, month - 1, min(billing_start, 28), tzinfo=timezone.utc)
    # End of cycle = period_start + 1 month.
    if period_start.month == 12:
        period_end = datetime(period_start.year + 1, 1, period_start.day, tzinfo=timezone.utc)
    else:
        period_end = datetime(period_start.year, period_start.month + 1, period_start.day, tzinfo=timezone.utc)
    total = round((period_end - period_start).total_seconds() / 86400)
    elapsed = max(0, int((n_utc - period_start).total_seconds() // 86400))
    return elapsed, total


# ─── User config ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AxtConfig:
    currency: tuple[str, ...] = ("usd", "krw")
    exchange_rate: float = 1400.0
    monthly_budget: float = 100.0
    timezone: str = "Asia/Seoul"
    locale: str = "ko-KR"
    start_of_week: str = "monday"  # "monday" | "sunday"
    budget_warning_threshold: float = 0.8
    plans: dict[str, PlanConfig] = field(default_factory=lambda: {
        "claude": PlanConfig(plan="max-5x", monthly_cost=100, billing_cycle_start=1),
        "codex": PlanConfig(plan="pro", monthly_cost=200, billing_cycle_start=1),
        "gemini": PlanConfig(plan="free", monthly_cost=0, billing_cycle_start=1, daily_request_limit=1000),
    })


def _plan_from_json(data: Any) -> Optional[PlanConfig]:
    if not isinstance(data, dict):
        return None
    return PlanConfig(
        plan=str(data.get("plan", "")),
        monthly_cost=float(data.get("monthlyCost", 0)),
        billing_cycle_start=int(data.get("billingCycleStart", 1)),
        daily_request_limit=data.get("dailyRequestLimit"),
    )


def _plan_to_json(p: PlanConfig) -> dict[str, Any]:
    out: dict[str, Any] = {
        "plan": p.plan,
        "monthlyCost": p.monthly_cost,
        "billingCycleStart": p.billing_cycle_start,
    }
    if p.daily_request_limit is not None:
        out["dailyRequestLimit"] = p.daily_request_limit
    return out


def load_config(config_path: os.PathLike[str] | str) -> AxtConfig:
    """Merge the user's config.json over `AxtConfig` defaults."""
    saved = read_json(config_path, fallback={})
    if not isinstance(saved, dict):
        saved = {}
    default = AxtConfig()
    plans = dict(default.plans)
    saved_plans = saved.get("plans")
    if isinstance(saved_plans, dict):
        for platform_name in ("claude", "codex", "gemini"):
            p = _plan_from_json(saved_plans.get(platform_name))
            if p is not None:
                plans[platform_name] = p
    return AxtConfig(
        currency=tuple(saved.get("currency", default.currency)),
        exchange_rate=float(saved.get("exchangeRate", default.exchange_rate)),
        monthly_budget=float(saved.get("monthlyBudget", default.monthly_budget)),
        timezone=str(saved.get("timezone", default.timezone)),
        locale=str(saved.get("locale", default.locale)),
        start_of_week=str(saved.get("startOfWeek", default.start_of_week)),
        budget_warning_threshold=float(saved.get("budgetWarningThreshold", default.budget_warning_threshold)),
        plans=plans,
    )


def save_config(config_path: os.PathLike[str] | str, config: AxtConfig) -> None:
    payload: dict[str, Any] = {
        "currency": list(config.currency),
        "exchangeRate": config.exchange_rate,
        "monthlyBudget": config.monthly_budget,
        "timezone": config.timezone,
        "locale": config.locale,
        "startOfWeek": config.start_of_week,
        "budgetWarningThreshold": config.budget_warning_threshold,
        "plans": {k: _plan_to_json(v) for k, v in config.plans.items()},
    }
    write_json_atomic(config_path, payload)


# ── Section 8: Context Analysis ──────────────────────────────────────────────
#
# Token estimation + 12-category source collection + cost impact.
# Source order, fixed-token constants, and hint logic mirror src/core/context/.

import unicodedata


FIXED_SYSTEM_PROMPT_TOKENS = 4200
FIXED_USER_CONTEXT_TOKENS = 280
FIXED_HOOK_OUTPUT_TOKENS = 200


def _is_korean(cp: int) -> bool:
    return (
        0xAC00 <= cp <= 0xD7A3
        or 0x3130 <= cp <= 0x318F
        or 0x1100 <= cp <= 0x11FF
    )


def _is_cjk(cp: int) -> bool:
    return _is_korean(cp) or 0x4E00 <= cp <= 0x9FFF or 0x3040 <= cp <= 0x30FF


def estimate_tokens(text: str) -> int:
    """Naive token estimate matching @utils/tokens.ts:
    CJK chars contribute 1/1.5 each; everything else 1/3.5. Total ceil()."""
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        if _is_cjk(ord(ch)):
            cjk += 1
        else:
            other += 1
    import math
    return math.ceil(cjk / 1.5 + other / 3.5)


def _safe_read_text(path: os.PathLike[str] | str) -> Optional[str]:
    """Return text content or None on any I/O error / non-file."""
    p = Path(path)
    try:
        if not p.is_file():
            return None
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _safe_listdir(path: os.PathLike[str] | str) -> list[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


MEMORY_LINE_LIMIT = 200
MEMORY_BYTE_LIMIT = 25 * 1024


def _truncate_memory(content: str) -> str:
    lines = content.split("\n")[:MEMORY_LINE_LIMIT]
    joined = "\n".join(lines)
    if len(joined.encode("utf-8")) <= MEMORY_BYTE_LIMIT:
        return joined
    while len(joined.encode("utf-8")) > MEMORY_BYTE_LIMIT:
        joined = joined[:-100]
    return joined


@dataclass
class ContextSource:
    name: str
    category: str
    path: str
    chars: int
    estimated_tokens: int
    percentage: float
    actionable: bool
    hint: Optional[str] = None
    content: Optional[str] = None


@dataclass(frozen=True)
class CostImpact:
    model: str
    cache_write_cost: float
    cache_read_cost_per_turn: float
    avg_turns_per_session: int
    avg_sessions_per_day: int
    per_session_cost: float
    monthly_cost: float


@dataclass(frozen=True)
class ContextAnalysis:
    total_tokens: int
    context_window_size: int
    used_percent: float
    model: str
    sources: list[ContextSource]
    cost_impact: CostImpact


CATEGORY_LABELS: dict[str, str] = {
    "system-prompt": "System prompt",
    "claude-md": "CLAUDE.md",
    "settings": "Settings",
    "memory": "Memory",
    "skills": "Skills metadata",
    "mcp-tools": "MCP tools",
    "plugins": "Plugins",
    "hooks": "Hooks output",
    "commands": "Commands",
    "agents": "Agents",
    "git-status": "Git status",
    "user-context": "User context",
}


def _make_src(name: str, category: str, path: str, content: str, actionable: bool, hint: Optional[str] = None) -> ContextSource:
    return ContextSource(
        name=name,
        category=category,
        path=path,
        chars=len(content),
        estimated_tokens=estimate_tokens(content),
        percentage=0.0,
        actionable=actionable,
        hint=hint,
        content=content,
    )


def _make_fixed(name: str, category: str, tokens: int, content: Optional[str] = None) -> ContextSource:
    return ContextSource(
        name=name,
        category=category,
        path="",
        chars=len(content) if content else 0,
        estimated_tokens=tokens,
        percentage=0.0,
        actionable=False,
        hint=None,
        content=content,
    )


def get_claude_version() -> str:
    try:
        proc = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=3)
        return (proc.stdout or "").strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def get_git_status(project_dir: os.PathLike[str] | str) -> str:
    try:
        proc = subprocess.run(["git", "status"], cwd=str(project_dir), capture_output=True, text=True, timeout=5)
        return (proc.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def build_system_prompt_preview(version: str) -> str:
    return "\n".join([
        f"# Claude Code System Prompt (v{version})",
        "",
        "The base system prompt is embedded in the Claude Code binary and sent",
        "at the start of every API call. It cannot be read directly from disk.",
        "",
        "## Known Sections",
        "",
        "1. Identity — \"You are Claude Code, Anthropic's official CLI for Claude.\"",
        "2. Tool definitions — Bash, Read, Edit, Write, Agent, WebSearch, etc.",
        "3. Safety & permissions — OWASP guidelines, destructive-action guards",
        "4. Git workflow — commit, PR, branch conventions",
        "5. Tone & style — concise, no emojis, file:line references",
        "6. Context management — compression, session guidance",
        "7. Environment — platform, shell, model, working directory",
        "",
        f"Estimated tokens: {FIXED_SYSTEM_PROMPT_TOKENS}",
        "",
        "Note: Use `claude --append-system-prompt <text>` to add custom instructions.",
        "Use `claude --system-prompt <text>` to replace the entire system prompt.",
    ])


def build_user_context_preview(home_dir: os.PathLike[str] | str, project_dir: os.PathLike[str] | str) -> str:
    email = os.environ.get("USER_EMAIL") or os.environ.get("EMAIL") or "—"
    today = datetime.now().strftime("%Y-%m-%d")
    return "\n".join([
        "# User Context",
        "",
        "Dynamic per-session values injected by Claude Code:",
        "",
        f"- userEmail: {email}",
        f"- currentDate: {today}",
        f"- homeDir: {home_dir}",
        f"- projectDir: {project_dir}",
        f"- platform: {sys.platform}",
        f"- shell: {os.environ.get('SHELL', '—')}",
        "",
        f"Estimated tokens: {FIXED_USER_CONTEXT_TOKENS}",
    ])


def build_hook_preview(hook: HookInfo) -> str:
    lines = [f"# Hook: {hook.event}", "", f"Type: {hook.type}"]
    if hook.matcher:
        lines.append(f"Matcher: {hook.matcher}")
    if hook.command:
        lines.append(f"Command: {hook.command}")
    if hook.url:
        lines.append(f"URL: {hook.url}")
    if hook.server:
        lines.append(f"MCP Server: {hook.server}")
    if hook.tool:
        lines.append(f"Tool: {hook.tool}")
    if hook.timeout:
        lines.append(f"Timeout: {hook.timeout}ms")
    lines.append("")
    lines.append(f"Estimated output tokens: {FIXED_HOOK_OUTPUT_TOKENS}")
    return "\n".join(lines)


_FM_NAME_RE = re.compile(r'name:\s*"?([^"\n]+)"?')


def collect_context_sources(
    *,
    home_dir: os.PathLike[str] | str,
    project_dir: os.PathLike[str] | str,
    installed_plugins_path: os.PathLike[str] | str,
) -> list[ContextSource]:
    """Twelve-category collector matching src/core/context/collect.ts."""
    home = Path(home_dir)
    proj = Path(project_dir)
    sources: list[ContextSource] = []

    # 1. system-prompt (fixed)
    sources.append(_make_fixed(
        "System Prompt",
        "system-prompt",
        FIXED_SYSTEM_PROMPT_TOKENS,
        build_system_prompt_preview(get_claude_version()),
    ))

    # 2. claude-md
    candidates_claude_md = [
        ("CLAUDE.md (global)", home / "CLAUDE.md"),
        ("CLAUDE.md (user)", home / ".claude" / "CLAUDE.md"),
        ("CLAUDE.md (project)", proj / "CLAUDE.md"),
        ("CLAUDE.md (project/.claude)", proj / ".claude" / "CLAUDE.md"),
        ("CLAUDE.local.md (local)", proj / "CLAUDE.local.md"),
    ]
    for name, p in candidates_claude_md:
        content = _safe_read_text(p)
        if content is not None:
            sources.append(_make_src(name, "claude-md", str(p), content, actionable=True))

    # 3. settings (global + per-project encoded path)
    project_settings_key = str(proj).replace("/", "-").lstrip("-")
    project_settings_dir = home / ".claude" / "projects" / project_settings_key
    candidates_settings = [
        ("settings.json (global)", home / ".claude" / "settings.json"),
        ("settings.local.json (global)", home / ".claude" / "settings.local.json"),
        ("settings.json (project)", project_settings_dir / "settings.json"),
        ("settings.local.json (project)", project_settings_dir / "settings.local.json"),
    ]
    for name, p in candidates_settings:
        content = _safe_read_text(p)
        if content is not None:
            sources.append(_make_src(name, "settings", str(p), content, actionable=True))

    # 4. memory
    memory_dir = project_settings_dir / "memory"
    main = memory_dir / "MEMORY.md"
    main_content = _safe_read_text(main)
    if main_content is not None:
        sources.append(_make_src("MEMORY.md", "memory", str(main), _truncate_memory(main_content), actionable=True))
    for f in _safe_listdir(memory_dir):
        if not f.endswith(".md") or f == "MEMORY.md":
            continue
        p = memory_dir / f
        c = _safe_read_text(p)
        if c is not None:
            stem = Path(f).stem
            sources.append(_make_src(f"Memory: {stem}", "memory", str(p), c, actionable=True))

    # 5. skills
    try:
        for skill in list_all_skills(project_dir=proj):
            skill_md = _safe_read_text(Path(skill.path) / "SKILL.md")
            name = skill.name
            description = ""
            if skill_md:
                fm = _FRONTMATTER_BLOCK_RE.match(skill_md.replace("\r\n", "\n"))
                if fm:
                    body = fm.group(1)
                    nm = _FM_NAME_RE.search(body)
                    if nm:
                        name = nm.group(1).strip().strip('"')
                    description = parse_yaml_description(body)
            text = f"- {name}: {description}"
            sources.append(_make_src(skill.name, "skills", skill.path, text, actionable=True))
    except OSError:
        pass

    # 6. mcp-tools
    try:
        plugins = list_installed_plugins(installed_plugins_path)
        for server in list_mcp_servers(plugins):
            text = f"- {server.name} ({server.plugin_id})"
            sources.append(_make_src(server.name, "mcp-tools", "", text, actionable=False))
    except OSError:
        pass

    # 7. plugins
    try:
        plugins = list_installed_plugins(installed_plugins_path)
        enabled = read_enabled_plugins(home / ".claude" / "settings.json")
        for p in plugins:
            if not enabled.get(p.id):
                continue
            text = f"Plugin: {p.name} v{p.version} — {p.description or ''}"
            sources.append(_make_src(p.name, "plugins", p.install_path, text, actionable=False))
    except OSError:
        pass

    # 8. hooks (only SessionStart / UserPromptSubmit; estimated output tokens)
    try:
        hooks = list_hooks(
            user_settings_path=home / ".claude" / "settings.json",
            project_dir=proj,
            installed_plugins_path=installed_plugins_path,
        )
        for h in hooks:
            if h.event not in ("SessionStart", "UserPromptSubmit"):
                continue
            name = f"Hook: {h.event} ({h.type})"
            sources.append(_make_fixed(name, "hooks", FIXED_HOOK_OUTPUT_TOKENS, build_hook_preview(h)))
    except OSError:
        pass

    # 9. commands
    try:
        for cmd in list_commands(project_dir=proj):
            text = f"- {cmd.name}: {cmd.description}"
            sources.append(_make_src(cmd.name, "commands", cmd.source_path, text, actionable=True))
    except OSError:
        pass

    # 10. agents
    try:
        for agent in list_all_agents(project_dir=proj):
            text = f"- {agent.name}: {agent.description}"
            sources.append(_make_src(agent.name, "agents", agent.source_path, text, actionable=True))
    except OSError:
        pass

    # 11. git-status (fixed 150 tokens)
    git = get_git_status(proj)
    sources.append(_make_fixed("Git Status", "git-status", 150, git or "No git repository or git not available."))

    # 12. user-context (fixed)
    sources.append(_make_fixed(
        "User Context",
        "user-context",
        FIXED_USER_CONTEXT_TOKENS,
        build_user_context_preview(home, proj),
    ))

    # Percentage of total.
    total = sum(s.estimated_tokens for s in sources)
    if total > 0:
        for s in sources:
            s.percentage = (s.estimated_tokens / total) * 100
    return sources


def add_context_hints(sources: list[ContextSource]) -> None:
    """Annotate sources with optimization hints (mutates in place)."""
    sorted_by_tokens = sorted(sources, key=lambda s: s.estimated_tokens, reverse=True)
    top_names = {s.name for s in sorted_by_tokens[:3]}

    for s in sources:
        cat = s.category
        if cat == "system-prompt":
            s.hint = f"{s.estimated_tokens} tok (fixed, cannot reduce)"
        elif cat in ("user-context", "git-status"):
            s.hint = f"{s.estimated_tokens} tok (fixed)"
        elif cat == "claude-md":
            if s.estimated_tokens > 500:
                s.hint = f"{s.estimated_tokens} tok — review for unnecessary sections"
        elif cat == "memory":
            if s.path:
                try:
                    mtime = Path(s.path).stat().st_mtime
                    days_old = int((datetime.now(timezone.utc).timestamp() - mtime) / 86400)
                    if days_old > 90:
                        s.hint = f"{s.estimated_tokens} tok — not modified in {days_old} days (>90 days)"
                except OSError:
                    pass
            if not s.hint and s.estimated_tokens > 100:
                s.hint = f"{s.estimated_tokens} tok"
        elif cat == "skills":
            if s.name in top_names:
                s.hint = f"{s.estimated_tokens} tok — top context consumer"
        elif cat == "hooks":
            s.hint = f"~{s.estimated_tokens} tok estimated output"
        elif cat == "mcp-tools":
            s.hint = "deferred — minimal context impact"
        else:
            if s.estimated_tokens > 100:
                s.hint = f"{s.estimated_tokens} tok"


def analyze_context(
    *,
    home_dir: os.PathLike[str] | str,
    project_dir: os.PathLike[str] | str,
    installed_plugins_path: os.PathLike[str] | str,
    model: str = "claude-opus-4-6",
    avg_turns_per_session: int = 30,
    avg_sessions_per_day: int = 5,
) -> ContextAnalysis:
    sources = collect_context_sources(
        home_dir=home_dir,
        project_dir=project_dir,
        installed_plugins_path=installed_plugins_path,
    )
    total = sum(s.estimated_tokens for s in sources)
    window = get_context_window_size(model) or 1_000_000
    used_pct = (total / window) * 100 if window else 0

    pricing = get_model_pricing(model)
    cache_write = (total / 1_000_000) * pricing.cache_write if pricing else 0.0
    cache_read = (total / 1_000_000) * pricing.cache_read if pricing else 0.0
    per_session = cache_write + (avg_turns_per_session - 1) * cache_read
    monthly = per_session * avg_sessions_per_day * 30

    add_context_hints(sources)

    return ContextAnalysis(
        total_tokens=total,
        context_window_size=window,
        used_percent=used_pct,
        model=model,
        sources=sources,
        cost_impact=CostImpact(
            model=model,
            cache_write_cost=cache_write,
            cache_read_cost_per_turn=cache_read,
            avg_turns_per_session=avg_turns_per_session,
            avg_sessions_per_day=avg_sessions_per_day,
            per_session_cost=per_session,
            monthly_cost=monthly,
        ),
    )


# ── Section 9: Project Usage Index ───────────────────────────────────────────
#
# Walks ~/.claude/projects/* and merges each project's `.axt-profile.json`
# extensions + symlinks under `.claude/<sub>/` pointing into the vault into
# a single `{type:name → projects[]}` map.


@dataclass(frozen=True)
class ProjectRef:
    path: str
    name: str


@dataclass
class ExtensionUsage:
    type: str  # "skill" | "command" | "agent" | "plugin"
    name: str
    projects: list[ProjectRef]


def _decode_project_dir_name(encoded: str, *, fs_root: str = "/") -> Optional[str]:
    """Reverse `/` and `.` → `-` encoding by walking the filesystem.

    Claude Code's encoding is lossy: `tlog.net` and `tlog/net` produce the
    same `tlog-net`. We resolve by trying child names of the current dir,
    preferring the longest match.
    """
    if not encoded.startswith("-"):
        return None
    segments = encoded[1:].split("-")
    current = fs_root
    i = 0
    while i < len(segments):
        try:
            entries = os.listdir(current)
        except OSError:
            return None
        best: Optional[tuple[str, int]] = None
        for name in entries:
            parts = name.replace(".", "-").split("-")
            if len(parts) > len(segments) - i:
                continue
            match = True
            for j, part in enumerate(parts):
                if part != segments[i + j]:
                    match = False
                    break
            if not match:
                continue
            if best is None or len(parts) > best[1]:
                best = (name, len(parts))
        if not best:
            return None
        nxt = os.path.join(current, best[0])
        if not os.path.isdir(nxt):
            return None
        current = nxt
        i += best[1]
    return current


def _usage_key(type_: str, name: str) -> str:
    return f"{type_}:{name}"


def _project_name_from_path(p: str) -> str:
    parts = [x for x in p.split("/") if x]
    return parts[-1] if parts else p


UsageIndex = dict[str, ExtensionUsage]


def _add_to_index(index: UsageIndex, type_: str, name: str, ref: ProjectRef) -> None:
    key = _usage_key(type_, name)
    entry = index.get(key)
    if entry is None:
        entry = ExtensionUsage(type=type_, name=name, projects=[])
        index[key] = entry
    if not any(p.path == ref.path for p in entry.projects):
        entry.projects.append(ref)


def _scan_profile_at(project_path: str, index: UsageIndex, ref: ProjectRef) -> None:
    profile_path = Path(project_path) / VAULT_PROFILE_NAME
    try:
        data = read_json(profile_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    profile = AxtProfile.from_json(data)
    for name in profile.skills:
        _add_to_index(index, "skill", name, ref)
    for name in profile.commands:
        _add_to_index(index, "command", name, ref)
    for name in profile.agents:
        _add_to_index(index, "agent", name, ref)
    for name in profile.plugins:
        _add_to_index(index, "plugin", name, ref)


def _scan_symlinks_at(project_path: str, vault_dir: str, index: UsageIndex, ref: ProjectRef) -> None:
    for sub, type_ in (("skills", "skill"), ("commands", "command"), ("agents", "agent")):
        dir_path = Path(project_path) / ".claude" / sub
        if not dir_path.exists():
            continue
        try:
            entries = list(dir_path.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if not entry.is_symlink():
                    continue
                target = os.readlink(entry)
            except OSError:
                continue
            if target.startswith(vault_dir):
                _add_to_index(index, type_, entry.name, ref)


def _scan_plugin_settings_at(project_path: str, index: UsageIndex, ref: ProjectRef) -> None:
    settings_path = Path(project_path) / ".claude" / "settings.json"
    if not settings_path.exists():
        return
    enabled = read_enabled_plugins(settings_path)
    for plugin_id, val in enabled.items():
        if val:
            _add_to_index(index, "plugin", plugin_id, ref)


def scan_project_usage(
    projects_dir: os.PathLike[str] | str,
    vault_dir: os.PathLike[str] | str,
    *,
    mode: str = "default",  # "default" | "full"
) -> UsageIndex:
    """Walk all Claude projects and build the type:name → projects[] index."""
    index: UsageIndex = {}
    try:
        dir_names = os.listdir(projects_dir)
    except OSError:
        return index

    vault_dir_str = str(vault_dir)
    for dir_name in dir_names:
        if not dir_name.startswith("-"):
            continue
        decoded = _decode_project_dir_name(dir_name)
        if not decoded:
            continue
        ref = ProjectRef(path=decoded, name=_project_name_from_path(decoded))
        _scan_profile_at(decoded, index, ref)
        _scan_symlinks_at(decoded, vault_dir_str, index, ref)
        if mode == "full":
            _scan_plugin_settings_at(decoded, index, ref)
    return index


def get_project_count(index: UsageIndex, type_: str, name: str) -> int:
    entry = index.get(_usage_key(type_, name))
    return len(entry.projects) if entry else 0


def get_projects(index: UsageIndex, type_: str, name: str) -> list[ProjectRef]:
    entry = index.get(_usage_key(type_, name))
    return list(entry.projects) if entry else []


_SCAN_SUMMARY_TYPES: tuple[str, ...] = ("skill", "command", "agent", "plugin")
_SCAN_TITLE_ABBREV: dict[str, str] = {"command": "cmd"}


def scan_counts_by_type(index: UsageIndex) -> dict[str, int]:
    """Tally an index by ExtensionUsage type in display order (skill/command/agent/plugin)."""
    counts: dict[str, int] = {t: 0 for t in _SCAN_SUMMARY_TYPES}
    for entry in index.values():
        if entry.type in counts:
            counts[entry.type] += 1
        else:
            counts[entry.type] = 1
    return counts


def format_scan_summary(index: UsageIndex, *, style: str) -> str:
    """style='title' → 'skill:64 cmd:0 agent:4 plugin:5'
    style='toast' → '64 skill · 0 command · 4 agent · 5 plugin'."""
    counts = scan_counts_by_type(index)
    if style == "title":
        return " ".join(
            f"{_SCAN_TITLE_ABBREV.get(t, t)}:{counts[t]}" for t in counts
        )
    return " · ".join(f"{counts[t]} {t}" for t in counts)


# ── Section 10: CLI Commands (argparse) ──────────────────────────────────────
#
# Mirrors src/cli/* commander structure as argparse subparsers. ANSI color
# uses raw escape codes (no chalk dependency); set NO_COLOR env var or pipe
# stdout to a non-tty to disable.

import argparse


# ─── Color helpers ───────────────────────────────────────────────────────────


def _color_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _c(code: str) -> str:
    return code if _color_enabled() else ""


C_RESET = "\x1b[0m"
C_BOLD = "\x1b[1m"
C_DIM = "\x1b[2m"
C_RED = "\x1b[31m"
C_GREEN = "\x1b[32m"
C_YELLOW = "\x1b[33m"
C_CYAN = "\x1b[36m"
C_GRAY = "\x1b[90m"


def _bold(s: str) -> str:
    return f"{_c(C_BOLD)}{s}{_c(C_RESET)}"


def _dim(s: str) -> str:
    return f"{_c(C_DIM)}{s}{_c(C_RESET)}"


def _green(s: str) -> str:
    return f"{_c(C_GREEN)}{s}{_c(C_RESET)}"


def _yellow(s: str) -> str:
    return f"{_c(C_YELLOW)}{s}{_c(C_RESET)}"


def _red(s: str) -> str:
    return f"{_c(C_RED)}{s}{_c(C_RESET)}"


def _cyan(s: str) -> str:
    return f"{_c(C_CYAN)}{s}{_c(C_RESET)}"


# ─── Formatting helpers (matches @utils/format.ts) ───────────────────────────


def format_tokens(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def format_cost(usd: float, exchange_rate: float) -> str:
    krw = convert_currency(usd, "usd", "krw", exchange_rate)
    return f"${usd:.2f} / ₩{round(krw):,}"


def render_bar(filled: int, width: int, fill_char: str = "█", empty_char: str = "░") -> str:
    filled = max(0, min(filled, width))
    return fill_char * filled + empty_char * (width - filled)


def budget_bar(used: float, budget: float, width: int = 25) -> str:
    if budget <= 0:
        return ""
    pct = min(used / budget, 1.5)
    bar = render_bar(round(min(pct, 1) * width), width)
    label = f"${used:.2f}/${budget} ({pct * 100:.0f}%)"
    if pct >= 1:
        return f"{_red(bar)} {_red(label)} ⛔"
    if pct >= 0.8:
        return f"{_yellow(bar)} {_yellow(label)} ⚠"
    return f"{_green(bar)} {_green(label)}"


# ─── Subcommand implementations ──────────────────────────────────────────────


def _print_no_color(*args, **kwargs) -> None:
    print(*args, **kwargs)


# context

def cli_context(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    result = analyze_context(
        home_dir=HOME,
        project_dir=Path.cwd(),
        installed_plugins_path=PATHS.installed_plugins,
        model=args.model,
        avg_turns_per_session=30,
        avg_sessions_per_day=5,
    )
    if args.json:
        # Serialize via dataclass walks.
        payload = {
            "totalTokens": result.total_tokens,
            "contextWindowSize": result.context_window_size,
            "usedPercent": result.used_percent,
            "model": result.model,
            "sources": [
                {
                    "name": s.name, "category": s.category, "path": s.path,
                    "chars": s.chars, "estimatedTokens": s.estimated_tokens,
                    "percentage": s.percentage, "actionable": s.actionable, "hint": s.hint,
                }
                for s in result.sources
            ],
            "costImpact": {
                "model": result.cost_impact.model,
                "cacheWriteCost": result.cost_impact.cache_write_cost,
                "cacheReadCostPerTurn": result.cost_impact.cache_read_cost_per_turn,
                "avgTurnsPerSession": result.cost_impact.avg_turns_per_session,
                "avgSessionsPerDay": result.cost_impact.avg_sessions_per_day,
                "perSessionCost": result.cost_impact.per_session_cost,
                "monthlyCost": result.cost_impact.monthly_cost,
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(_bold(
        f"Context Usage: {result.used_percent:.1f}% of "
        f"{format_tokens(result.context_window_size)} "
        f"({format_tokens(result.total_tokens)} tokens)  Model: {result.model}"
    ))
    print()

    groups: dict[str, list[ContextSource]] = {}
    for s in result.sources:
        if args.category and s.category != args.category:
            continue
        groups.setdefault(s.category, []).append(s)

    sorted_groups = sorted(
        groups.items(),
        key=lambda kv: -sum(x.estimated_tokens for x in kv[1]),
    )

    print(f"{_bold('Category'.ljust(22))} {_bold('Items'.ljust(7))} {_bold('Tokens'.ljust(12))} {_bold('%'.ljust(8))}")
    print("─" * 52)
    for cat, cat_sources in sorted_groups:
        tokens = sum(s.estimated_tokens for s in cat_sources)
        pct = sum(s.percentage for s in cat_sources)
        label = CATEGORY_LABELS.get(cat, cat)
        print(f"{label.ljust(22)} {str(len(cat_sources)).ljust(7)} {format_tokens(tokens).ljust(12)} {(f'{pct:.1f}%').ljust(8)}")
        if args.detail:
            for s in cat_sources:
                hint = _dim(f" — {s.hint}") if s.hint else ""
                path = s.path[:30].ljust(32) if s.path else "".ljust(32)
                print(_dim(f"  {s.name.ljust(30)} {path} {format_tokens(s.estimated_tokens)} tok") + hint)

    print()
    ci = result.cost_impact
    print(_bold(f"Cost Impact ({ci.model})"))
    print(f"  Cache write (1st call):     ${ci.cache_write_cost:.3f}")
    print(f"  Cache read  (per turn):     ${ci.cache_read_cost_per_turn:.3f}")
    print(f"  Per session (avg {ci.avg_turns_per_session}t):     ${ci.per_session_cost:.2f}")
    print(f"  Monthly (avg {ci.avg_sessions_per_day}/day):       {format_cost(ci.monthly_cost, config.exchange_rate)}")
    return 0


# market

def cli_market_list(args) -> int:
    items = list_marketplaces(PATHS.known_marketplaces)
    if not items:
        print("No marketplaces registered.")
        return 0
    print(_bold(f"{'Name'.ljust(28)} {'Current'.ljust(10)} {'Latest'.ljust(10)} {'Source'.ljust(28)} Updated"))
    print("─" * 90)
    pooled = pooled_map(items, lambda m: get_marketplace_version(PATHS.known_marketplaces, m.name))
    versions = pooled.results
    for m in items:
        src_str = (
            f"github:{m.source.repo}" if m.source.kind == "github"
            else f"git:{m.source.url}" if m.source.kind == "git"
            else f"dir:{m.source.path}"
        )
        v = versions.get(m) or VersionInfo(current="?", remote="?", updatable=False, error="failed")
        current_col = _red(v.current.ljust(10)) if v.error else _cyan(v.current.ljust(10))
        latest_col = (
            _red(v.remote.ljust(10)) if v.error
            else _yellow(v.remote.ljust(10)) if v.updatable
            else _green(v.remote.ljust(10))
        )
        print(f"{m.name.ljust(28)} {current_col} {latest_col} {src_str.ljust(28)} {m.last_updated[:10]}")
    if pooled.errors:
        print(_red(f"\n {len(pooled.errors)} error(s):"))
        for err in pooled.errors:
            print(_red(f"  ✗ {err.item.name}: {err.error}"))
    print(f"\n {len(items)} marketplace(s)")
    return 0


def cli_market_add(args) -> int:
    source = parse_marketplace_source(args.source)
    if source.kind == "github":
        name = source.repo.split("/")[-1]
    elif source.kind == "directory":
        name = source.path.rstrip("/").split("/")[-1]
    else:
        name = "custom-marketplace"
    add_marketplace(PATHS.known_marketplaces, PATHS.marketplaces, name, source)
    print(_green(f'✓ Marketplace "{name}" registered.'))
    return 0


def cli_market_sync(args) -> int:
    def print_result(n: str, result: SyncMarketplaceResult) -> None:
        if result.updated:
            print(_green(f"✓ {n}") + _dim(f" {result.before} → ") + _cyan(result.after))
        else:
            print(_green(f"✓ {n}") + _dim(f" {result.after} (up to date)"))
    if args.name:
        result = sync_marketplace(PATHS.known_marketplaces, args.name)
        print_result(args.name, result)
        return 0
    items = list_marketplaces(PATHS.known_marketplaces)
    pooled = pooled_map(
        items,
        lambda m: sync_marketplace(PATHS.known_marketplaces, m.name),
        on_result=lambda m, r: print_result(m.name, r),
        on_error=lambda m, e: print(_red(f"✗ {m.name}: {e}")),
    )
    if pooled.errors:
        print(_red(f"\n{len(pooled.errors)} sync error(s)"))
    return 0


def cli_market_remove(args) -> int:
    remove_marketplace(PATHS.known_marketplaces, PATHS.marketplaces, args.name)
    print(_green(f'✓ Marketplace "{args.name}" removed.'))
    return 0


# mcp

def _active_plugins() -> list[PluginInfo]:
    plugins = list_installed_plugins(PATHS.installed_plugins)
    enabled = read_enabled_plugins(PATHS.settings)
    return [p for p in plugins if enabled.get(p.id) is True]


def cli_mcp_list(args) -> int:
    servers = list_mcp_servers(_active_plugins())
    if not servers:
        print("No MCP servers found in active plugins.")
        return 0
    print(_bold(f" {'Server'.ljust(25)} {'Command'.ljust(20)} Plugin"))
    print("─" * 70)
    for s in servers:
        cmd = " ".join([s.command, *s.args_list])
        print(f" {s.name.ljust(25)} {cmd.ljust(20)} {s.plugin_id}")
    print(f"\n {len(servers)} MCP server(s)")
    return 0


def cli_mcp_info(args) -> int:
    servers = list_mcp_servers(_active_plugins())
    server = next((s for s in servers if s.name == args.name), None)
    if not server:
        print(_red(f'MCP server "{args.name}" not found.'))
        return 1
    print(_bold(server.name))
    print(f"Plugin: {server.plugin_id}")
    print(f"Command: {server.command} {' '.join(server.args_list)}")
    if server.env_dict:
        print(f"Env: {json.dumps(server.env_dict)}")
    return 0


# plan

def _platform_cost(entries: list[UnifiedUsageEntry], platform: str) -> float:
    cost = 0.0
    for e in entries:
        if e.platform != platform:
            continue
        cost += calculate_cost(
            TokenUsage(
                input_tokens=e.input_tokens,
                output_tokens=e.output_tokens,
                cache_creation_tokens=e.cache_write_tokens,
                cache_read_tokens=e.cache_read_tokens,
            ),
            e.model,
        )
    return cost


def cli_plan_overview(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    now = datetime.now()
    month_start = f"{now.year}-{now.month:02d}-01"
    entries = load_unified_usage(
        claude_projects_dir=PATHS.projects,
        codex_sessions_dir=PATHS.codex_sessions,
        gemini_tmp_dir=PATHS.gemini_tmp,
        since=month_start,
    )
    total = 0.0
    for p in ("claude", "codex", "gemini"):
        plan_cfg = config.plans.get(p)
        if not plan_cfg:
            continue
        cost = _platform_cost(entries, p)
        elapsed, total_days = get_days_in_billing_period(plan_cfg.billing_cycle_start, now.replace(tzinfo=timezone.utc))
        usage = compute_plan_usage(plan_cfg, cost, elapsed, total_days)
        total += cost
        label = f"{p.capitalize()} ({plan_cfg.plan} — ${plan_cfg.monthly_cost}/mo)"
        print(_bold(label))
        print(f"  사용량:    {format_cost(cost, config.exchange_rate)}  ({elapsed}일 경과)")
        print(f"  일평균:    ${usage.daily_avg_cost:.2f}")
        if usage.projected_monthly_cost > plan_cfg.monthly_cost and plan_cfg.monthly_cost > 0:
            est = _red(f"${usage.projected_monthly_cost:.0f} ⚠ 초과 예상")
        else:
            est = f"${usage.projected_monthly_cost:.0f}"
        print(f"  월말 예측: {est}")
        if plan_cfg.monthly_cost > 0:
            print(f"  {budget_bar(cost, plan_cfg.monthly_cost)}")
        print()
    print(_bold(f"Total: {format_cost(total, config.exchange_rate)}"))
    return 0


def cli_plan_set(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    plans = dict(config.plans)
    existing = plans.get(args.platform)
    if existing:
        plans[args.platform] = PlanConfig(
            plan=args.plan_name,
            monthly_cost=existing.monthly_cost,
            billing_cycle_start=existing.billing_cycle_start,
            daily_request_limit=existing.daily_request_limit,
        )
    else:
        plans[args.platform] = PlanConfig(plan=args.plan_name, monthly_cost=0, billing_cycle_start=1)
    save_config(
        AXT_CONFIG_PATH,
        AxtConfig(
            currency=config.currency,
            exchange_rate=config.exchange_rate,
            monthly_budget=config.monthly_budget,
            timezone=config.timezone,
            locale=config.locale,
            start_of_week=config.start_of_week,
            budget_warning_threshold=config.budget_warning_threshold,
            plans=plans,
        ),
    )
    print(_green(f'✓ {args.platform} plan set to "{args.plan_name}".'))
    return 0


# plugin

def cli_plugin_list(args) -> int:
    plugins = list_installed_plugins(PATHS.installed_plugins)
    enabled_g = read_enabled_plugins(PATHS.settings)
    enabled_p = read_enabled_plugins(project_settings_path())
    if not plugins:
        print("No plugins installed.")
        return 0
    print(_bold(f" {'Plugin'.ljust(30)} {'Version'.ljust(10)} {'G/P'.ljust(7)} Marketplace"))
    print("─" * 75)
    active = 0
    for p in plugins:
        gv = enabled_g.get(p.id)
        pv = enabled_p.get(p.id)
        is_active = gv is True or pv is True
        if is_active:
            active += 1
        g_mark = _green("●") if gv is True else (_dim("○") if gv is False else _dim("·"))
        p_mark = _green("●") if pv is True else (_dim("○") if pv is False else _dim("·"))
        status = f"{g_mark} / {p_mark}"
        print(f" {p.name.ljust(30)} {p.version.ljust(10)} {status.ljust(16)} {p.marketplace}")
    print(f"\n {len(plugins)} installed ({active} active, {len(plugins) - active} disabled)")
    print(_dim(" Legend: G/P = global / project   ● enabled  ○ disabled  · unset"))
    return 0


def _plugin_settings_path_for_scope(scope: str) -> Path:
    """Resolve the settings.json target for `--scope global|project`."""
    if scope == "project":
        return project_settings_path()
    return Path(PATHS.settings)


def cli_plugin_enable(args) -> int:
    scope = getattr(args, "scope", "global")
    target = _plugin_settings_path_for_scope(scope)
    set_plugin_enabled(target, args.plugin_id, True)
    print(_green(f'✓ "{args.plugin_id}" enabled ({scope}). Restart Claude Code to apply.'))
    return 0


def cli_plugin_disable(args) -> int:
    scope = getattr(args, "scope", "global")
    target = _plugin_settings_path_for_scope(scope)
    set_plugin_enabled(target, args.plugin_id, False)
    print(_yellow(f'○ "{args.plugin_id}" disabled ({scope}). Restart Claude Code to apply.'))
    return 0


def cli_plugin_info(args) -> int:
    info = get_plugin_info(PATHS.installed_plugins, args.plugin_id)
    if not info:
        print(_red(f'Plugin "{args.plugin_id}" not found.'))
        return 1
    gv = read_enabled_plugins(PATHS.settings).get(info.id)
    pv = read_enabled_plugins(project_settings_path()).get(info.id)

    def _fmt(v: Optional[bool]) -> str:
        if v is True:
            return _green("enabled")
        if v is False:
            return _dim("disabled")
        return _dim("unset")

    print(_bold(info.name) + f" {info.version}")
    print(f"Marketplace: {info.marketplace}")
    print(f"Status: global={_fmt(gv)}  project={_fmt(pv)}")
    print(f"Path: {info.install_path}")
    print(f"Installed: {info.installed_at[:10]}")
    print(f"Updated: {info.last_updated[:10]}")
    return 0


def cli_plugin_remove(args) -> int:
    import shutil
    info = get_plugin_info(PATHS.installed_plugins, args.plugin_id)
    if not info:
        print(_red(f'Plugin "{args.plugin_id}" not found.'))
        return 1
    shutil.rmtree(info.install_path, ignore_errors=True)
    remove_installed_plugin(PATHS.installed_plugins, args.plugin_id)
    remove_plugin_from_settings(PATHS.settings, args.plugin_id)
    print(_green(f'✓ "{args.plugin_id}" removed.'))
    return 0


def cli_plugin_search(args) -> int:
    print(_dim(f'Searching for "{args.query}"...'))
    print(_yellow("Search requires marketplace sync. Run: axt market sync"))
    return 0


# project

def cli_project_init(args) -> int:
    cwd = Path.cwd()
    if read_profile(cwd) is not None:
        print(_yellow(".axt-profile.json already exists."))
        return 0
    write_profile(cwd, empty_profile())
    print(_green("✓ Created .axt-profile.json"))
    return 0


def cli_project_add(args) -> int:
    cwd = Path.cwd()
    items = list_vault_items(PATHS.vault)
    for name in args.names:
        item = next((i for i in items if i.name == name and i.type == args.type), None)
        if not item:
            print(_red(f'✗ {args.type} "{name}" not found in vault'))
            continue
        link_to_project(cwd, item)
        print(_green(f'✓ Linked {args.type} "{name}" → .claude/{args.type}s/{name}'))
    return 0


def cli_project_remove(args) -> int:
    cwd = Path.cwd()
    item = VaultItem(name=args.name, type=args.type, path="", description="")
    unlink_from_project(cwd, item)
    print(_green(f'✓ Unlinked {args.type} "{args.name}"'))
    return 0


def cli_project_sync(args) -> int:
    result = sync_project(Path.cwd(), PATHS.vault)
    for entry in result.linked:
        print(_green(f"  + {entry}"))
    for entry in result.unlinked:
        print(_yellow(f"  - {entry}"))
    for entry in result.errors:
        print(_red(f"  ✗ {entry}"))
    if not result.linked and not result.unlinked and not result.errors:
        print("Already in sync.")
    return 0


def cli_project_status(args) -> int:
    cwd = Path.cwd()
    profile = read_profile(cwd)
    if profile is None:
        print("No .axt-profile.json found. Run `axt project init` first.")
        return 1
    print(_bold("Extension profile status:"))
    for key, type_ in (("skills", "skill"), ("commands", "command"), ("agents", "agent"), ("plugins", "plugin")):
        for name in getattr(profile, key):
            if type_ == "plugin":
                print(f"  {_cyan(type_.ljust(8))} {name} {_green('(in profile)')}")
                continue
            link_path = cwd / ".claude" / key / name
            linked = link_path.is_symlink()
            status = _green("✓ linked") if linked else _red("✗ missing")
            print(f"  {_cyan(type_.ljust(8))} {name.ljust(25)} {status}")
    return 0


# skill

def cli_skill_list(args) -> int:
    skills = list_skills(PATHS.skills)
    if not skills:
        print("No standalone skills found.")
        return 0
    print(_bold(f" {'Name'.ljust(30)} {'Type'.ljust(10)} Path"))
    print("─" * 70)
    for s in skills:
        type_str = _cyan("symlink") if s.is_symlink else _dim("dir")
        path_str = f"→ {s.target}" if s.is_symlink else s.path
        print(f" {s.name.ljust(30)} {type_str.ljust(19)} {path_str}")
    print(f"\n {len(skills)} skill(s)")
    return 0


def cli_skill_link(args) -> int:
    if not is_symlink_supported():
        print(_red("Skill linking is not supported on this platform."))
        return 1
    link_skill(PATHS.skills, args.path, args.name)
    print(_green("✓ Skill linked."))
    return 0


def cli_skill_unlink(args) -> int:
    if not is_symlink_supported():
        print(_red("Skill unlinking is not supported on this platform."))
        return 1
    unlink_skill(PATHS.skills, args.name)
    print(_green(f'✓ Skill "{args.name}" unlinked.'))
    return 0


# usage

def _unified_to_claude(e: UnifiedUsageEntry) -> ClaudeUsageEntry:
    """Adapt for aggregateDaily/aggregateBySession/computeBlocks (Claude shape)."""
    return ClaudeUsageEntry(
        model=e.model,
        input_tokens=e.input_tokens,
        output_tokens=e.output_tokens,
        cache_creation_tokens=e.cache_write_tokens,
        cache_read_tokens=e.cache_read_tokens,
        session_id=e.session_id,
        project_path=e.project_path,
        timestamp=e.timestamp,
    )


def _today_in_tz(tz: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _shared_usage_load(args, *, since: Optional[str] = None, until: Optional[str] = None) -> list[UnifiedUsageEntry]:
    """Apply usage-group filter flags (model/project/platform/timezone)."""
    config = load_config(AXT_CONFIG_PATH)
    tz = args.timezone or config.timezone
    entries = load_unified_usage(
        claude_projects_dir=PATHS.projects,
        codex_sessions_dir=PATHS.codex_sessions,
        gemini_tmp_dir=PATHS.gemini_tmp,
        since=since,
        until=until,
        platform=args.platform or "all",
        project=args.project,
    )
    if args.model:
        entries = [e for e in entries if args.model in e.model]
    return entries


def cli_usage_today(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    tz = args.timezone or config.timezone
    today = _today_in_tz(tz)
    unified = _shared_usage_load(args, since=today, until=today)
    entries = [_unified_to_claude(e) for e in unified]
    if not entries:
        print("No usage data for today.")
        return 0
    daily = aggregate_daily(entries, tz)
    d = daily[0]
    cost = sum(
        calculate_cost(
            TokenUsage(e.input_tokens, e.output_tokens, e.cache_creation_tokens, e.cache_read_tokens),
            e.model,
        )
        for e in entries
    )
    if args.json:
        print(json.dumps({
            "date": d.date,
            "sessions": d.sessions,
            "models": list(d.models),
            "inputTokens": d.input_tokens,
            "outputTokens": d.output_tokens,
            "cacheCreationTokens": d.cache_creation_tokens,
            "cacheReadTokens": d.cache_read_tokens,
            "cost": {"usd": cost, "krw": round(cost * config.exchange_rate)},
        }, indent=2))
        return 0
    print(_bold(f"Today ({today})"))
    print(f"  Sessions:    {d.sessions}")
    print(f"  Models:      {', '.join(d.models)}")
    print(f"  In:          {format_tokens(d.input_tokens)}")
    print(f"  Out:         {format_tokens(d.output_tokens)}")
    print(f"  Cache Write: {format_tokens(d.cache_creation_tokens)}")
    print(f"  Cache Read:  {format_tokens(d.cache_read_tokens)}")
    print(f"  Cost:        {format_cost(cost, config.exchange_rate)}")
    return 0


def cli_usage_week(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    tz = args.timezone or config.timezone
    now = datetime.now(timezone.utc)
    until = _today_in_tz(tz)
    week_ago = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
    since = week_ago.strftime("%Y-%m-%d")
    unified = _shared_usage_load(args, since=since, until=until)
    entries = [_unified_to_claude(e) for e in unified]
    daily = aggregate_daily(entries, tz)
    if args.json:
        print(json.dumps([
            {"date": d.date, "sessions": d.sessions, "models": list(d.models),
             "inputTokens": d.input_tokens, "outputTokens": d.output_tokens,
             "cacheCreationTokens": d.cache_creation_tokens, "cacheReadTokens": d.cache_read_tokens}
            for d in daily
        ], indent=2))
        return 0
    if args.csv:
        print("date,sessions,input_tokens,output_tokens,cache_write_tokens,cache_read_tokens,cost_usd,cost_krw")
        for d in daily:
            cost = _day_cost(entries, d.date, tz)
            print(f"{d.date},{d.sessions},{d.input_tokens},{d.output_tokens},{d.cache_creation_tokens},{d.cache_read_tokens},{cost:.2f},{round(cost * config.exchange_rate)}")
        return 0
    print(_bold(f"Week: {since} ~ {until}\n"))
    print(f" {'Date'.ljust(12)} {'Sess'.ljust(6)} {'In'.ljust(10)} {'Out'.ljust(10)} {'Cache W'.ljust(10)} {'Cache R'.ljust(10)} Cost")
    print("─" * 78)
    total_cost = 0.0
    for d in daily:
        cost = _day_cost(entries, d.date, tz)
        total_cost += cost
        print(
            f" {d.date.ljust(12)} {str(d.sessions).ljust(6)} "
            f"{format_tokens(d.input_tokens).ljust(10)} {format_tokens(d.output_tokens).ljust(10)} "
            f"{format_tokens(d.cache_creation_tokens).ljust(10)} {format_tokens(d.cache_read_tokens).ljust(10)} "
            f"{format_cost(cost, config.exchange_rate)}"
        )
    print("─" * 78)
    print(f" {'Total'.ljust(58)} {format_cost(total_cost, config.exchange_rate)}")
    return 0


def _day_cost(entries: list[ClaudeUsageEntry], date: str, tz: str) -> float:
    return sum(
        calculate_cost(
            TokenUsage(e.input_tokens, e.output_tokens, e.cache_creation_tokens, e.cache_read_tokens),
            e.model,
        )
        for e in entries
        if _date_in_tz(e.timestamp, tz) == date
    )


def cli_usage_month(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    tz = args.timezone or config.timezone
    now = datetime.now()
    since = f"{now.year}-{now.month:02d}-01"
    until = _today_in_tz(tz)
    unified = _shared_usage_load(args, since=since, until=until)
    entries = [_unified_to_claude(e) for e in unified]
    total_cost = sum(
        calculate_cost(
            TokenUsage(e.input_tokens, e.output_tokens, e.cache_creation_tokens, e.cache_read_tokens),
            e.model,
        )
        for e in entries
    )
    sessions = {e.session_id for e in entries}
    print(_bold(f"Month: {since} ~ {until}"))
    print(f"  Sessions:    {len(sessions)}")
    print(f"  Messages:    {len(entries)}")
    print(f"  Cost:        {format_cost(total_cost, config.exchange_rate)}")
    print()
    print(budget_bar(total_cost, config.monthly_budget))
    return 0


def cli_usage_blocks(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    tz = args.timezone or config.timezone
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    since = three_days_ago.strftime("%Y-%m-%d")
    unified = _shared_usage_load(args, since=since)
    entries = [_unified_to_claude(e) for e in unified]
    blocks = compute_blocks(entries, tz)
    if args.active:
        blocks = [b for b in blocks if b.is_active]
    print(_bold(f" {'Block'.ljust(30)} {'Status'.ljust(10)} {'Tokens'.ljust(12)} {'Burn Rate'.ljust(12)} Cost"))
    print("─" * 80)
    for b in reversed(blocks):
        start = b.start_time[5:16].replace("T", " ")
        end = b.end_time[11:16]
        status = _green("● active") if b.is_active else _dim("○ done")
        burn = f"{format_tokens(b.burn_rate_per_min)}/min" if b.burn_rate_per_min else "—"
        cost = (
            (b.input_tokens / 1e6) * 15
            + (b.output_tokens / 1e6) * 75
            + (b.cache_creation_tokens / 1e6) * 18.75
            + (b.cache_read_tokens / 1e6) * 1.5
        )
        print(f" {f'{start}~{end}'.ljust(30)} {status.ljust(19)} {format_tokens(b.total_tokens).ljust(12)} {burn.ljust(12)} ${cost:.2f}")
    return 0


def cli_usage_session(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    unified = _shared_usage_load(args)
    entries = [_unified_to_claude(e) for e in unified if e.session_id.startswith(args.session_id)]
    if not entries:
        print(_red(f'Session "{args.session_id}" not found.'))
        return 1
    sessions = aggregate_by_session(entries)
    s = sessions[0]
    cost = sum(
        calculate_cost(
            TokenUsage(e.input_tokens, e.output_tokens, e.cache_creation_tokens, e.cache_read_tokens),
            e.model,
        )
        for e in entries
    )
    print(_bold(f"Session: {s.session_id}"))
    print(f"  Project:     {s.project_path}")
    print(f"  Models:      {', '.join(s.models)}")
    print(f"  Messages:    {s.message_count}")
    print(f"  In:          {format_tokens(s.input_tokens)}")
    print(f"  Out:         {format_tokens(s.output_tokens)}")
    print(f"  Cache Write: {format_tokens(s.cache_creation_tokens)}")
    print(f"  Cache Read:  {format_tokens(s.cache_read_tokens)}")
    print(f"  Cost:        {format_cost(cost, config.exchange_rate)}")
    print(f"  Period:      {s.first_timestamp[:19]} ~ {s.last_timestamp[:19]}")
    return 0


# vault

def cli_vault_list(args) -> int:
    items = list_vault_items(PATHS.vault)
    if not items:
        print("Vault is empty. Run `axt vault migrate` to move global extensions to vault.")
        return 0
    print(_bold(f"{'Name'.ljust(30)} {'Type'.ljust(10)}"))
    print("─" * 42)
    for item in items:
        print(f"{item.name.ljust(30)} {_cyan(item.type.ljust(10))}")
    print(f"\n {len(items)} extension(s) in vault")
    return 0


def cli_vault_migrate(args) -> int:
    print("Migrating global extensions to vault...")
    result = migrate_to_vault(PATHS.claude_dir, PATHS.vault)
    for m in result.moved:
        print(_green(f"  ✓ {m}"))
    for s in result.skipped:
        print(_yellow(f"  ⊘ {s} (already in vault)"))
    for e in result.errors:
        print(_red(f"  ✗ {e}"))
    total = len(result.moved) + len(result.skipped) + len(result.errors)
    if total == 0:
        print("No extensions found in global paths.")
    else:
        print(f"\nMoved {len(result.moved)}, skipped {len(result.skipped)}, errors {len(result.errors)}")
    return 0


def cli_vault_add(args) -> int:
    import shutil
    src = Path(args.path)
    if not src.exists():
        print(_red(f"✗ Source not found: {src}"))
        return 1
    type_ = args.type or ("skill" if src.is_dir() else "command")
    name = src.name
    dest_dir = (
        PATHS.vault_skills if type_ == "skill"
        else PATHS.vault_commands if type_ == "command"
        else PATHS.vault_agents
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if src.is_dir():
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    print(_green(f'✓ Added {type_} "{name}" to vault'))
    return 0


def cli_vault_install(args) -> int:
    import shutil
    source = find_plugin_source_dir(PATHS.marketplaces / args.marketplace, args.name)
    if not source:
        print(_red(f'✗ "{args.name}" not found in marketplace "{args.marketplace}"'))
        return 1
    dest_dir = (
        PATHS.vault_skills if args.type == "skill"
        else PATHS.vault_commands if args.type == "command"
        else PATHS.vault_agents
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / args.name
    shutil.copytree(source, dest)
    print(_green(f'✓ Installed {args.type} "{args.name}" from "{args.marketplace}" to vault'))
    return 0


def cli_vault_link_global(args) -> int:
    items = list_vault_items(PATHS.vault)
    item = next((i for i in items if i.name == args.name and i.type == args.type), None)
    if not item:
        print(_red(f'✗ {args.type} "{args.name}" not found in vault'))
        return 1
    link_to_global(PATHS.claude_dir, item)
    print(_green(f'✓ Linked {args.type} "{args.name}" to global (~/.claude/{args.type}s/{args.name})'))
    return 0


def cli_vault_unlink_global(args) -> int:
    item = VaultItem(name=args.name, type=args.type, path="", description="")
    unlink_from_global(PATHS.claude_dir, item)
    print(_green(f'✓ Unlinked {args.type} "{args.name}" from global'))
    return 0


# tui — launches the curses dashboard implemented in Sections 11-14.

def cli_tui(args) -> int:
    return launch_tui()


# ─── Argparse wiring ─────────────────────────────────────────────────────────


def _add_usage_filter_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--since", help="Start date (YYYY-MM-DD or YYYYMMDD)")
    p.add_argument("--until", help="End date (YYYY-MM-DD or YYYYMMDD)")
    p.add_argument("--model", help="Filter by model")
    p.add_argument("--project", help="Filter by project")
    p.add_argument("--breakdown", action="store_true", help="Show per-model breakdown")
    p.add_argument("--timezone", help="Timezone for grouping")
    p.add_argument("--locale", help="Date locale")
    p.add_argument("--platform", help="Filter by platform (claude/codex/gemini/all)", default="all")
    p.add_argument("--json", action="store_true", help="Output JSON")
    p.add_argument("--csv", action="store_true", help="Output CSV")
    p.add_argument("--export", help="Export to file")


def build_parser() -> argparse.ArgumentParser:
    """Construct the full argparse tree mirroring src/cli/* commander structure."""
    parser = argparse.ArgumentParser(prog="axt", description="Agent eXtension Tool")
    parser.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # tui (also the no-arg default)
    sp_tui = sub.add_parser("tui", help="Open TUI dashboard")
    sp_tui.set_defaults(func=cli_tui)

    # context
    sp_ctx = sub.add_parser("context", help="Analyze session-start context usage")
    sp_ctx.add_argument("--detail", action="store_true", help="Show individual items within categories")
    sp_ctx.add_argument("--json", action="store_true", help="Output as JSON")
    sp_ctx.add_argument("--category", help="Filter by category")
    sp_ctx.add_argument("--model", default="claude-opus-4-6", help="Model override")
    sp_ctx.set_defaults(func=cli_context)

    # market
    sp_mkt = sub.add_parser("market", help="Manage marketplaces").add_subparsers(dest="action", required=True)
    p = sp_mkt.add_parser("list", help="List registered marketplaces"); p.set_defaults(func=cli_market_list)
    p = sp_mkt.add_parser("add", help="Register a marketplace"); p.add_argument("source"); p.set_defaults(func=cli_market_add)
    p = sp_mkt.add_parser("sync", help="Sync marketplace(s) with remote"); p.add_argument("name", nargs="?"); p.set_defaults(func=cli_market_sync)
    p = sp_mkt.add_parser("remove", help="Unregister a marketplace"); p.add_argument("name"); p.set_defaults(func=cli_market_remove)

    # mcp
    sp_mcp = sub.add_parser("mcp", help="View MCP servers").add_subparsers(dest="action", required=True)
    p = sp_mcp.add_parser("list", help="List MCP servers from active plugins"); p.set_defaults(func=cli_mcp_list)
    p = sp_mcp.add_parser("info", help="Show MCP server details"); p.add_argument("name"); p.set_defaults(func=cli_mcp_info)

    # plan
    sp_plan = sub.add_parser("plan", help="View plan usage and cost projections")
    plan_sub = sp_plan.add_subparsers(dest="action")
    p = plan_sub.add_parser("overview", help="All platforms plan summary"); p.set_defaults(func=cli_plan_overview)
    p = plan_sub.add_parser("set", help="Set plan for a platform"); p.add_argument("platform"); p.add_argument("plan_name"); p.set_defaults(func=cli_plan_set)
    sp_plan.set_defaults(func=cli_plan_overview)  # default action

    # plugin
    sp_plg = sub.add_parser("plugin", help="Manage plugins").add_subparsers(dest="action", required=True)
    p = sp_plg.add_parser("list", help="List installed plugins with status"); p.set_defaults(func=cli_plugin_list)
    p = sp_plg.add_parser("enable", help="Enable a plugin"); p.add_argument("plugin_id"); p.add_argument("--scope", choices=("global", "project"), default="global", help="Write target settings.json (default: global)"); p.set_defaults(func=cli_plugin_enable)
    p = sp_plg.add_parser("disable", help="Disable a plugin"); p.add_argument("plugin_id"); p.add_argument("--scope", choices=("global", "project"), default="global", help="Write target settings.json (default: global)"); p.set_defaults(func=cli_plugin_disable)
    p = sp_plg.add_parser("info", help="Show plugin details"); p.add_argument("plugin_id"); p.set_defaults(func=cli_plugin_info)
    p = sp_plg.add_parser("remove", help="Remove a plugin"); p.add_argument("plugin_id"); p.set_defaults(func=cli_plugin_remove)
    p = sp_plg.add_parser("search", help="Search plugins across all marketplaces"); p.add_argument("query"); p.set_defaults(func=cli_plugin_search)

    # project
    sp_prj = sub.add_parser("project", help="Manage project extension profile").add_subparsers(dest="action", required=True)
    p = sp_prj.add_parser("init", help="Create .axt-profile.json (empty profile)"); p.set_defaults(func=cli_project_init)
    p = sp_prj.add_parser("add", help="Add vault extensions to project"); p.add_argument("type"); p.add_argument("names", nargs="+"); p.set_defaults(func=cli_project_add)
    p = sp_prj.add_parser("remove", help="Remove extension from project"); p.add_argument("type"); p.add_argument("name"); p.set_defaults(func=cli_project_remove)
    p = sp_prj.add_parser("sync", help="Reconcile symlinks with .axt-profile.json"); p.set_defaults(func=cli_project_sync)
    p = sp_prj.add_parser("status", help="Show profile vs actual symlink state"); p.set_defaults(func=cli_project_status)

    # skill
    sp_skl = sub.add_parser("skill", help="Manage standalone skills").add_subparsers(dest="action", required=True)
    p = sp_skl.add_parser("list", help="List standalone skills"); p.set_defaults(func=cli_skill_list)
    if is_symlink_supported():
        p = sp_skl.add_parser("link", help="Link a skill directory"); p.add_argument("path"); p.add_argument("-n", "--name"); p.set_defaults(func=cli_skill_link)
        p = sp_skl.add_parser("unlink", help="Unlink a skill"); p.add_argument("name"); p.set_defaults(func=cli_skill_unlink)

    # usage
    sp_usg = sub.add_parser("usage", help="Track token usage and costs")
    usg_sub = sp_usg.add_subparsers(dest="action")
    for action, help_text, fn in (
        ("today", "Today's usage summary", cli_usage_today),
        ("week", "Weekly usage summary", cli_usage_week),
        ("month", "Monthly usage summary", cli_usage_month),
    ):
        p = usg_sub.add_parser(action, help=help_text); _add_usage_filter_args(p); p.set_defaults(func=fn)
    p = usg_sub.add_parser("blocks", help="5-hour billing block report"); _add_usage_filter_args(p); p.add_argument("--active", action="store_true"); p.set_defaults(func=cli_usage_blocks)
    p = usg_sub.add_parser("session", help="Show specific session usage"); _add_usage_filter_args(p); p.add_argument("session_id"); p.set_defaults(func=cli_usage_session)
    # default = today
    _add_usage_filter_args(sp_usg)
    sp_usg.set_defaults(func=cli_usage_today, active=False, session_id=None)

    # vault
    sp_vlt = sub.add_parser("vault", help="Manage extension vault").add_subparsers(dest="action", required=True)
    p = sp_vlt.add_parser("list", help="List all vault extensions"); p.set_defaults(func=cli_vault_list)
    p = sp_vlt.add_parser("migrate", help="Move global extensions to vault"); p.set_defaults(func=cli_vault_migrate)
    p = sp_vlt.add_parser("add", help="Add extension to vault"); p.add_argument("path"); p.add_argument("-t", "--type", choices=["skill", "command", "agent"]); p.set_defaults(func=cli_vault_add)
    p = sp_vlt.add_parser("install", help="Install extension from marketplace directly to vault"); p.add_argument("marketplace"); p.add_argument("name"); p.add_argument("-t", "--type", choices=["skill", "command", "agent"], default="skill"); p.set_defaults(func=cli_vault_install)
    p = sp_vlt.add_parser("link-global", help="Symlink vault extension to global ~/.claude/"); p.add_argument("type"); p.add_argument("name"); p.set_defaults(func=cli_vault_link_global)
    p = sp_vlt.add_parser("unlink-global", help="Remove symlink from global ~/.claude/"); p.add_argument("type"); p.add_argument("name"); p.set_defaults(func=cli_vault_unlink_global)

    return parser


# Need a `timedelta` import for usage CLI.
from datetime import timedelta


# ── Section 11: TUI — Common helpers (curses, color, key, width) ────────────
#
# Why curses (vs. an Ink/React equivalent in Python):
#   The original Ink TUI bug ("selected row's ▸/# disappear under WezTerm + cmux")
#   was caused by Ink/Yoga's flex-layout writing rows of *different* trailing-
#   space widths depending on whether they had a background-affecting style.
#   Curses sidesteps the whole class of bugs by writing every cell explicitly
#   via addnstr(y, x, text, width, attr) — the way cst (claude-session-tracker)
#   does and never hits the same issue.

import curses


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


# Usage sub-tabs — platform axis, paralleling EXTENSION_SUB_TABS.
USAGE_SUB_TABS: tuple[tuple[str, str], ...] = (
    ("all",    "All"),
    ("claude", "Claude"),
    ("codex",  "Codex"),
    ("gemini", "Gemini"),
    ("cursor", "Cursor"),
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


# ── Section 13: TUI — Tabs (initial: Vault + stubs for the rest) ─────────────
#
# This release focuses on the Vault tab — the one whose Ink rendering caused
# the original "selected row disappears" bug. Other tabs are stubbed so the
# tab bar still works; their full implementations land in follow-up commits.


@dataclass
class TuiState:
    """Mutable per-session UI state. Each tab reads/writes its own bucket."""
    tab_idx: int = 0
    focused_layer: str = "content"  # "mainTab" | "content"
    refresh_token: int = 0          # bump to force data reload
    status: str = ""
    show_help: bool = False

    # Vault-specific state.
    vault_items: list[VaultItem] = field(default_factory=list)
    vault_selected: int = 0
    vault_filter: str = "all"        # "all" | "skill" | "command" | "agent" | "plugin"
    vault_sort: str = "name"         # "name" | "type" | "added" | "updated" | "project" | "global"
    vault_search: str = ""
    vault_searching: bool = False    # True while user is typing in the `/` prompt
    vault_pending_project: set[str] = field(default_factory=set)   # item names toggled but not applied
    vault_pending_global: set[str] = field(default_factory=set)
    vault_scan_mode: str = "default"  # "default" (profile + symlinks) | "full" (+ plugin settings)
    vault_usage_index: dict[str, Any] = field(default_factory=dict)  # type:name → ExtensionUsage
    vault_detail_focused: bool = False  # Enter → focus detail panel, Esc → blur back
    vault_detail_scroll: int = 0

    # Extensions sub-tab state.
    ext_sub_tab: str = "vault"                     # one of EXTENSION_SUB_TABS keys
    ext_cache: dict[str, Any] = field(default_factory=dict)
    ext_selected: dict[str, int] = field(default_factory=dict)

    # Dashboard / usage data caches (None = not loaded yet).
    dashboard_entries: Optional[list] = None
    dashboard_config: Optional[Any] = None
    usage_data: dict[str, list] = field(default_factory=dict)
    usage_config: Optional[Any] = None

    # Cursor tab.
    cursor_metrics: Optional[list] = None
    cursor_selected: int = 0

    # Context tab.
    context_analysis: Optional[Any] = None
    context_selected: int = 0

    # Project tab.
    project_items: Optional[list] = None
    project_selected: int = 0
    project_scroll: int = 0

    # Bridge between handler functions and curses-bound widgets. The handlers
    # don't receive stdscr (so they remain unit-testable), so we stash a dict
    # the main loop populates. Tests leave it None → modal/editor actions
    # become no-ops, which is the desired test behavior.
    stdscr_callbacks: Optional[dict] = None


_VAULT_FILTERS = ("all", "skill", "command", "agent", "plugin")
_VAULT_SORTS = ("name", "type", "added", "updated", "project", "global", "used")


def _vault_load(state: TuiState) -> None:
    """Refresh vault items from disk into state. Cheap — just reads metadata."""
    plugins = list_installed_plugins(PATHS.installed_plugins)
    plugin_refs = [
        PluginRef(id=p.id, name=p.name, description=p.description or "", install_path=p.install_path)
        for p in plugins
    ]
    state.vault_items = list_vault_items_with_project_state(
        PATHS.vault,
        Path.cwd(),
        installed_plugins=plugin_refs,
        global_dir=PATHS.claude_dir,
    )


_SCAN_CACHE_NAME = "vault-scan-index.json"


def _scan_cache_path() -> Path:
    return AXT_CONFIG_DIR / "cache" / _SCAN_CACHE_NAME


def _save_scan_cache(index: dict[str, ExtensionUsage], mode: str) -> None:
    """Persist the cross-project scan so it survives axt restarts.

    Stored as `{ mode, scannedAt, entries: { "type:name": {projects: [...]} } }`
    next to the usage caches (`~/.config/axt/cache/`).
    """
    payload = {
        "mode": mode,
        "scannedAt": _iso_now(),
        "entries": {
            key: {
                "type": usage.type,
                "name": usage.name,
                "projects": [{"path": p.path, "name": p.name} for p in usage.projects],
            }
            for key, usage in index.items()
        },
    }
    try:
        write_json_atomic(_scan_cache_path(), payload)
    except OSError:
        pass  # best-effort cache; never fail the scan


def _load_scan_cache() -> tuple[dict[str, ExtensionUsage], str]:
    """Return (index, mode). Empty index + 'default' mode when no cache yet."""
    data = read_json(_scan_cache_path(), fallback={})
    if not isinstance(data, dict):
        return {}, "default"
    entries = data.get("entries", {})
    if not isinstance(entries, dict):
        return {}, "default"
    index: dict[str, ExtensionUsage] = {}
    for key, value in entries.items():
        if not isinstance(value, dict):
            continue
        projects_raw = value.get("projects") or []
        projects = [
            ProjectRef(path=str(p.get("path", "")), name=str(p.get("name", "")))
            for p in projects_raw
            if isinstance(p, dict)
        ]
        index[key] = ExtensionUsage(
            type=str(value.get("type", "")),
            name=str(value.get("name", "")),
            projects=projects,
        )
    return index, str(data.get("mode", "default"))


def _vault_scan(state: TuiState) -> None:
    """Cross-project scan: walk ~/.claude/projects/* to count usage per item.
    Slower than refresh — only call on explicit user request (`f` key).
    Writes the result to disk so it survives axt restarts.
    """
    state.vault_usage_index = scan_project_usage(
        PATHS.projects, PATHS.vault, mode=state.vault_scan_mode,
    )
    _save_scan_cache(state.vault_usage_index, state.vault_scan_mode)


def _vault_apply_pending(state: TuiState) -> str:
    """Commit the toggle pending state to disk (project and global symlinks)."""
    items_by_name = {i.name: i for i in state.vault_items}
    applied = 0
    errors = 0
    for name in list(state.vault_pending_project):
        item = items_by_name.get(name)
        if not item or item.type == "plugin":
            state.vault_pending_project.discard(name)
            continue
        try:
            if item.is_linked:
                unlink_from_project(Path.cwd(), item)
            else:
                link_to_project(Path.cwd(), item)
            applied += 1
        except (OSError, ValueError, FileExistsError):
            errors += 1
        state.vault_pending_project.discard(name)
    for name in list(state.vault_pending_global):
        item = items_by_name.get(name)
        if not item or item.type == "plugin":
            state.vault_pending_global.discard(name)
            continue
        try:
            if item.is_global_linked:
                unlink_from_global(PATHS.claude_dir, item)
            else:
                link_to_global(PATHS.claude_dir, item)
            applied += 1
        except (OSError, ValueError, FileExistsError):
            errors += 1
        state.vault_pending_global.discard(name)
    _vault_load(state)
    return f"Applied {applied}" + (f", {errors} errors" if errors else "")


def _vault_filtered(state: TuiState) -> list[VaultItem]:
    items = state.vault_items
    if state.vault_filter != "all":
        items = [i for i in items if i.type == state.vault_filter]
    if state.vault_search:
        q = state.vault_search.lower()
        items = [i for i in items if q in i.name.lower()]
    # Sort.
    if state.vault_sort == "name":
        items = sorted(items, key=lambda i: i.name)
    elif state.vault_sort == "type":
        items = sorted(items, key=lambda i: (i.type, i.name))
    elif state.vault_sort == "added":
        items = sorted(items, key=lambda i: i.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    elif state.vault_sort == "updated":
        items = sorted(items, key=lambda i: i.updated_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    elif state.vault_sort == "project":
        items = sorted(items, key=lambda i: (not i.is_linked, i.name))
    elif state.vault_sort == "global":
        items = sorted(items, key=lambda i: (not i.is_global_linked, i.name))
    elif state.vault_sort == "used":
        # Most-used first (descending). Items with no scan data tie at 0.
        def _used_count(it: VaultItem) -> int:
            entry = state.vault_usage_index.get(f"{it.type}:{it.name}")
            return len(entry.projects) if entry else 0
        items = sorted(items, key=lambda i: (-_used_count(i), i.name))
    return items


def _fmt_date(d: Optional[datetime]) -> str:
    if not d:
        return "─"
    return d.strftime("%y-%m-%d %H:%M")


def _vault_pending_indicator(state: TuiState, item: VaultItem) -> tuple[str, str]:
    """Return the (project, global) cell text reflecting pending toggles.

    Naming differs by item type:
      • skill / command / agent → symlinks (`linked` / `—`)
      • plugin                  → `enabledPlugins` settings flag (`enabled` / `off`)
    The single-glyph cells (●/○) work for either, but the DetailPanel and the
    cell suffix make the distinction explicit so users don't confuse the two
    activation mechanisms.
    """
    proj_pending = item.name in state.vault_pending_project
    glob_pending = item.name in state.vault_pending_global
    project_now = (not item.is_linked) if proj_pending else item.is_linked
    global_now = (not item.is_global_linked) if glob_pending else item.is_global_linked
    proj_cell = ("●" if project_now else "○") + (" *" if proj_pending else "")
    glob_cell = ("●" if global_now else "○") + (" *" if glob_pending else "")
    return proj_cell, glob_cell


def _activation_term(item_type: str, on: bool) -> str:
    """Human-readable activation status, distinguishing symlink vs enabledPlugins."""
    if item_type == "plugin":
        return "enabled" if on else "off"
    return "linked" if on else "not linked"


def render_vault_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    """Render the Vault tab — selected row uses curses.A_REVERSE so the
    ▸/# region never disappears."""
    if state.vault_items == [] and state.refresh_token == 0:
        _vault_load(state)
        # Try to restore the previous scan from disk so the "Used in" column
        # is populated immediately on restart (no manual `f` needed).
        if not state.vault_usage_index:
            cached_index, cached_mode = _load_scan_cache()
            if cached_index:
                state.vault_usage_index = cached_index
                state.vault_scan_mode = cached_mode
        state.refresh_token = 1

    # Title row with all the live mode bits.
    pending = len(state.vault_pending_project) + len(state.vault_pending_global)
    scan_label = (
        f"scan={state.vault_scan_mode}({format_scan_summary(state.vault_usage_index, style='title')})"
        if state.vault_usage_index else f"scan={state.vault_scan_mode}(empty)"
    )
    title_parts = [
        f" Vault  ({len(state.vault_items)} items)",
        f"filter={state.vault_filter}",
        f"sort={state.vault_sort}",
        scan_label,
    ]
    if state.vault_search:
        title_parts.append(f"search={state.vault_search!r}")
    if pending:
        title_parts.append(f"pending={pending}")
    safe_addnstr(stdscr, y0, 0, fit_cells("  ".join(title_parts), w - 1), w - 1, CP_HDR())

    # Search-mode prompt (overrides the second row).
    if state.vault_searching:
        prompt = f" /search: {state.vault_search}_"
        safe_addnstr(stdscr, y0 + 1, 0, fit_cells(prompt, w - 1), w - 1, CP_INFO() | curses.A_BOLD)

    filtered = _vault_filtered(state)
    if not filtered:
        safe_addnstr(stdscr, y0 + 2, 2, "Vault is empty or no items match the current filter.", w - 4, CP_DIM())
        safe_addnstr(stdscr, y0 + 4, 2, "Press `m` to migrate global extensions, or `Tab` to change filter.", w - 4, CP_DIM())
        return

    state.vault_selected = max(0, min(state.vault_selected, len(filtered) - 1))

    table_w = int(w * 0.62)
    detail_x = table_w
    detail_w = w - table_w

    # Columns: # / Name / Type / Vault / Project / Global / Used in.
    # "Vault" semantics:  ✓ = item is in ~/.axt/vault/  ;  global = only in ~/.claude/{type}s/
    # "Project" / "Global" show the *intended* state after applying pending toggles.
    no_w = max(3, len(str(len(filtered))) + 1)
    used_w = 6  # "Used" header + " N proj" data ≤ 6
    proj_w = 6  # "Proj" header + "● *" data ≤ 6
    glob_w = 6  # "Glob"
    type_w = 6  # "Type"
    vault_w = 7  # "Vault"
    # _draw_cell renders each column at `col.width + 2` cells (per-column
    # gap). With 7 columns + 4-cell prefix the gap cost is 4 + 2*7 = 18. We
    # subtract a few more cells of safety so wrap can't eat the last column.
    cols_fixed = no_w + type_w + vault_w + proj_w + glob_w + used_w
    name_w = max(10, table_w - cols_fixed - (4 + 2 * 7) - 4)
    columns = [
        TableColumn("no", "#", no_w),
        TableColumn("name", "Name", name_w),
        TableColumn("type", "Type", type_w),
        TableColumn("vault", "Vault", vault_w),
        TableColumn("project", "Proj", proj_w),
        TableColumn("global", "Glob", glob_w),
        TableColumn("used", "Used", used_w),
    ]
    rows: list[dict[str, str]] = []
    checked: set[int] = set()
    for i, item in enumerate(filtered):
        if item.is_linked or item.name in state.vault_pending_project:
            checked.add(i)
        proj_cell, glob_cell = _vault_pending_indicator(state, item)
        used_count = (
            len(state.vault_usage_index.get(f"{item.type}:{item.name}").projects)
            if state.vault_usage_index and f"{item.type}:{item.name}" in state.vault_usage_index
            else 0
        )
        rows.append({
            "no": str(i + 1),
            "name": item.name,
            "type": item.type,
            "vault": "✓" if item.in_vault else "global*",
            "project": proj_cell,
            "global": glob_cell,
            "used": f"{used_count} proj" if used_count else "─",
        })

    # Adjust table viewport for the search prompt row.
    table_y = y0 + (2 if state.vault_searching else 1)
    table_h = h - (4 if state.vault_searching else 3)
    render_table(
        stdscr,
        table_y, 0, table_h, table_w,
        columns, rows,
        selected=state.vault_selected,
        checked=checked,
    )

    # Detail panel.
    current = filtered[state.vault_selected]
    vault_status = "in vault" if current.in_vault else "global only (press `i` to import)"
    # Naming differs by activation mechanism (see _activation_term docstring).
    activation_kind = "enabledPlugins" if current.type == "plugin" else "symlink"
    detail_fields: list[tuple[str, str]] = [
        ("Name", current.name),
        ("Type", current.type),
        ("Path", current.path),
        ("Description", current.description or "—"),
        ("Added", _fmt_date(current.created_at)),
        ("Updated", _fmt_date(current.updated_at)),
        ("Vault", vault_status),
        ("Activation", activation_kind),
        ("Project", _activation_term(current.type, current.is_linked)),
        ("Global", _activation_term(current.type, current.is_global_linked)),
    ]
    if state.vault_usage_index:
        usage = state.vault_usage_index.get(f"{current.type}:{current.name}")
        if usage and usage.projects:
            detail_fields.append(("Used in", ", ".join(p.name for p in usage.projects[:8])))
    render_detail_panel(
        stdscr,
        table_y, detail_x, table_h, detail_w,
        title=f"{current.name} ({current.type})",
        fields=detail_fields,
        scroll=state.vault_detail_scroll,
        focused=state.vault_detail_focused,
    )


def handle_vault_input(state: TuiState, key: int) -> Optional[str]:
    """Vault tab key handler. Returns a status message or None."""
    # ── Detail-panel focus mode: j/k scroll the panel; Esc blurs back to list.
    if state.vault_detail_focused:
        if key == KEY_ESC:
            state.vault_detail_focused = False
            state.vault_detail_scroll = 0
            return None
        if key in (ord("j"), curses.KEY_DOWN):
            state.vault_detail_scroll += 1
        elif key in (ord("k"), curses.KEY_UP):
            state.vault_detail_scroll = max(0, state.vault_detail_scroll - 1)
        elif key == curses.KEY_NPAGE:
            state.vault_detail_scroll += 10
        elif key == curses.KEY_PPAGE:
            state.vault_detail_scroll = max(0, state.vault_detail_scroll - 10)
        return None

    # ── Search-input mode: capture characters, respond only to Enter/Esc/Bksp.
    if state.vault_searching:
        if key in (KEY_ESC, ):
            state.vault_searching = False
            state.vault_search = ""
            state.vault_selected = 0
            return "Search cleared"
        if is_enter(key):
            state.vault_searching = False
            state.vault_selected = 0
            return f"Searching {state.vault_search!r}" if state.vault_search else None
        if key in (curses.KEY_BACKSPACE, KEY_BACKSPACE, 8):
            state.vault_search = state.vault_search[:-1]
            state.vault_selected = 0
            return None
        if 32 <= key < 127:  # printable ASCII
            state.vault_search += chr(key)
            state.vault_selected = 0
            return None
        return None

    filtered = _vault_filtered(state)
    n = len(filtered)
    current = filtered[state.vault_selected] if (n and state.vault_selected < n) else None

    if key in (ord("j"), curses.KEY_DOWN):
        state.vault_selected = min(n - 1, state.vault_selected + 1) if n else 0
    elif key in (ord("k"), curses.KEY_UP):
        state.vault_selected = max(0, state.vault_selected - 1)
    elif key == curses.KEY_NPAGE:
        state.vault_selected = min(n - 1, state.vault_selected + 10) if n else 0
    elif key == curses.KEY_PPAGE:
        state.vault_selected = max(0, state.vault_selected - 10)
    elif key == KEY_TAB:
        i = _VAULT_FILTERS.index(state.vault_filter)
        state.vault_filter = _VAULT_FILTERS[(i + 1) % len(_VAULT_FILTERS)]
        state.vault_selected = 0
    elif key == ord("s"):
        i = _VAULT_SORTS.index(state.vault_sort)
        state.vault_sort = _VAULT_SORTS[(i + 1) % len(_VAULT_SORTS)]
        state.vault_selected = 0
    elif key == ord("/"):
        # Enter search-input mode.
        state.vault_searching = True
        state.vault_search = ""
        return "/: type to filter, Enter to apply, Esc to cancel"
    elif key == ord(" ") and current and current.type != "plugin":
        # Toggle pending project link for the selected item.
        if current.name in state.vault_pending_project:
            state.vault_pending_project.discard(current.name)
        else:
            state.vault_pending_project.add(current.name)
        return None
    elif key == ord("g") and current and current.type != "plugin":
        if current.name in state.vault_pending_global:
            state.vault_pending_global.discard(current.name)
        else:
            state.vault_pending_global.add(current.name)
        return None
    elif is_enter(key) and (state.vault_pending_project or state.vault_pending_global):
        return _vault_apply_pending(state)
    elif is_enter(key) and current:
        # No pending changes → drop focus into the detail panel for scrolling.
        state.vault_detail_focused = True
        state.vault_detail_scroll = 0
        return "Detail focused — j/k to scroll, Esc to blur"
    elif key == KEY_ESC and (state.vault_pending_project or state.vault_pending_global):
        state.vault_pending_project.clear()
        state.vault_pending_global.clear()
        return "Discarded pending changes"
    elif key == ord("i") and current and not current.in_vault:
        try:
            import_to_vault(PATHS.claude_dir, PATHS.vault, current)
            _vault_load(state)
            return f"Imported {current.name!r} to vault"
        except (OSError, ValueError, FileExistsError) as e:
            return f"Import failed: {e}"
    elif key == ord("f"):
        # Toggle scan mode AND immediately re-scan (the slow op).
        state.vault_scan_mode = "full" if state.vault_scan_mode == "default" else "default"
        try:
            _vault_scan(state)
            return (
                f"Scan ({state.vault_scan_mode}): "
                f"{format_scan_summary(state.vault_usage_index, style='toast')}  "
                f"(total {len(state.vault_usage_index)})"
            )
        except OSError as e:
            return f"Scan failed: {e}"
    elif key == ord("m"):
        try:
            result = migrate_to_vault(PATHS.claude_dir, PATHS.vault)
            _vault_load(state)
            return f"Migrated: +{len(result.moved)} skipped {len(result.skipped)} err {len(result.errors)}"
        except OSError as e:
            return f"Migrate failed: {e}"
    elif key == ord("S"):
        try:
            result = sync_project(Path.cwd(), PATHS.vault)
            _vault_load(state)
            return f"Sync: +{len(result.linked)} -{len(result.unlinked)} err {len(result.errors)}"
        except OSError as e:
            return f"Sync failed: {e}"
    elif key == ord("r"):
        _vault_load(state)
        return "Refreshed"
    return None


def render_stub_tab(stdscr, state: TuiState, y0: int, h: int, w: int, name: str, hint: str) -> None:
    title = f" {name}"
    safe_addnstr(stdscr, y0, 0, fit_cells(title, w - 1), w - 1, CP_HDR())
    safe_addnstr(stdscr, y0 + 2, 2, f"{name} tab — not yet implemented in the curses TUI.", w - 4, 0)
    safe_addnstr(stdscr, y0 + 3, 2, hint, w - 4, CP_DIM())
    safe_addnstr(stdscr, y0 + 5, 2, "Use the CLI for now:", w - 4, CP_INFO())
    safe_addnstr(stdscr, y0 + 6, 4, f"$ axt {name.lower()} --help", w - 6, CP_DIM())


def handle_stub_input(state: TuiState, key: int) -> Optional[str]:
    return None


# ─── BarChart widget ─────────────────────────────────────────────────────────


def render_bar_chart(
    stdscr,
    y: int,
    x: int,
    w: int,
    data: list[tuple[str, float]],
    *,
    label_w: int = 10,
    value_fmt=lambda v: f"${v:.2f}",
) -> int:
    """Render a horizontal ASCII bar chart. Returns rows used.

    `data` is a list of (label, value). Bars are scaled to the max value.
    """
    if not data:
        return 0
    max_value = max((v for _, v in data), default=1.0) or 1.0
    value_w = max(len(value_fmt(v)) for _, v in data)
    bar_w = max(4, w - label_w - value_w - 4)
    for i, (label, value) in enumerate(data):
        filled = round((value / max_value) * bar_w) if max_value > 0 else 0
        bar = render_bar(filled, bar_w)
        line = f"{fit_cells(label, label_w)} {bar} {value_fmt(value)}"
        safe_addnstr(stdscr, y + i, x, fit_cells(line, w), w, CP_INFO())
    return len(data)


def _date_iter(now: datetime, days: int) -> list[datetime]:
    """Last `days` days, oldest first, including today."""
    out = []
    for i in range(days - 1, -1, -1):
        out.append(now - timedelta(days=i))
    return out


# ─── Cost helpers ────────────────────────────────────────────────────────────


def _entry_cost(e: UnifiedUsageEntry) -> float:
    return calculate_cost(
        TokenUsage(
            input_tokens=e.input_tokens,
            output_tokens=e.output_tokens,
            cache_creation_tokens=e.cache_write_tokens,
            cache_read_tokens=e.cache_read_tokens,
        ),
        e.model,
    )


def _daily_costs(entries: list[UnifiedUsageEntry], days: int, tz: str) -> list[tuple[str, float]]:
    """Per-day cost for the last `days` days. Ordered oldest → newest."""
    today = datetime.now(timezone.utc)
    dates: list[tuple[str, float]] = []
    by_day: dict[str, float] = {}
    for e in entries:
        d = _date_in_tz(e.timestamp, tz)
        by_day[d] = by_day.get(d, 0.0) + _entry_cost(e)
    for dt in _date_iter(today, days):
        key = dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
        try:
            from zoneinfo import ZoneInfo
            key = dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")
        except Exception:
            pass
        label = key[5:]  # MM-DD
        dates.append((label, by_day.get(key, 0.0)))
    return dates


# ─── Dashboard tab ───────────────────────────────────────────────────────────


def _ensure_dashboard_loaded(state: TuiState) -> None:
    if state.dashboard_entries is not None:
        return
    config = load_config(AXT_CONFIG_PATH)
    state.dashboard_config = config
    now = datetime.now()
    month_start = f"{now.year}-{now.month:02d}-01"
    state.dashboard_entries = load_unified_usage(
        claude_projects_dir=PATHS.projects,
        codex_sessions_dir=PATHS.codex_sessions,
        gemini_tmp_dir=PATHS.gemini_tmp,
        since=month_start,
    )


def render_dashboard_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    _ensure_dashboard_loaded(state)
    config = state.dashboard_config or load_config(AXT_CONFIG_PATH)
    entries = state.dashboard_entries or []

    safe_addnstr(stdscr, y0, 0, fit_cells(" Dashboard — this month so far", w - 1), w - 1, CP_HDR())
    if not entries:
        safe_addnstr(stdscr, y0 + 2, 2, "No usage data this month yet.", w - 4, CP_DIM())
        return

    # Per-platform card line.
    row = y0 + 2
    total_cost = 0.0
    for platform in ("claude", "codex", "gemini"):
        plat_entries = [e for e in entries if e.platform == platform]
        if not plat_entries:
            continue
        cost = sum(_entry_cost(e) for e in plat_entries)
        total_cost += cost
        plan = config.plans.get(platform)
        plan_label = f"{plan.plan} (${plan.monthly_cost}/mo)" if plan else "—"
        in_t = sum(e.input_tokens for e in plat_entries)
        out_t = sum(e.output_tokens for e in plat_entries)
        cr_t = sum(e.cache_read_tokens for e in plat_entries)
        line = (
            f"{platform.capitalize():9s}  {plan_label:24s}  "
            f"cost={format_cost(cost, config.exchange_rate):26s}  "
            f"in={format_tokens(in_t):>7s}  out={format_tokens(out_t):>7s}  cache_r={format_tokens(cr_t):>7s}"
        )
        safe_addnstr(stdscr, row, 2, fit_cells(line, w - 4), w - 4, 0)
        row += 1

    # Total + monthly budget bar.
    row += 1
    safe_addnstr(stdscr, row, 2, fit_cells(f"Total: {format_cost(total_cost, config.exchange_rate)}", w - 4), w - 4, CP_HDR())
    row += 1
    if config.monthly_budget > 0:
        bar_w = min(40, w - 30)
        pct = min(total_cost / config.monthly_budget, 1.5)
        filled = round(min(pct, 1) * bar_w)
        bar = render_bar(filled, bar_w)
        label = f"${total_cost:.2f}/${config.monthly_budget} ({pct * 100:.0f}%)"
        if pct >= 1:
            text, attr = f"{bar} {label} ⛔", CP_ERR()
        elif pct >= 0.8:
            text, attr = f"{bar} {label} ⚠", CP_HDR()
        else:
            text, attr = f"{bar} {label}", CP_OK()
        safe_addnstr(stdscr, row, 2, fit_cells(text, w - 4), w - 4, attr)
        row += 1

    # 14-day BarChart.
    row += 2
    safe_addnstr(stdscr, row, 2, "Last 14 days (daily cost):", w - 4, CP_HDR())
    row += 1
    chart_data = _daily_costs(entries, 14, config.timezone)
    chart_rows = render_bar_chart(stdscr, row, 4, w - 8, chart_data)
    row += chart_rows


def handle_dashboard_input(state: TuiState, key: int) -> Optional[str]:
    if key == ord("r"):
        state.dashboard_entries = None
        return "Refreshed"
    return None


# ─── Usage tabs (Claude / Codex / Gemini share a renderer) ───────────────────


def _ensure_usage_loaded(state: TuiState, platform: str) -> None:
    bucket = state.usage_data.get(platform)
    if bucket is not None:
        return
    config = load_config(AXT_CONFIG_PATH)
    state.usage_config = config
    now = datetime.now(timezone.utc)
    month_start = f"{now.year}-{now.month:02d}-01"
    state.usage_data[platform] = load_unified_usage(
        claude_projects_dir=PATHS.projects,
        codex_sessions_dir=PATHS.codex_sessions,
        gemini_tmp_dir=PATHS.gemini_tmp,
        since=month_start,
        platform=platform,
    )


def _platform_period_card(entries: list[UnifiedUsageEntry], label: str, w: int) -> list[str]:
    """3-line summary card."""
    sessions = {e.session_id for e in entries}
    cost = sum(_entry_cost(e) for e in entries)
    in_t = sum(e.input_tokens for e in entries)
    out_t = sum(e.output_tokens for e in entries)
    cw_t = sum(e.cache_write_tokens for e in entries)
    cr_t = sum(e.cache_read_tokens for e in entries)
    return [
        f"  {label:7s}  sessions={len(sessions):>3d}  msgs={len(entries):>4d}",
        f"           in={format_tokens(in_t):>7s}  out={format_tokens(out_t):>7s}  "
        f"cw={format_tokens(cw_t):>7s}  cr={format_tokens(cr_t):>7s}",
        f"           cost=${cost:.2f}",
    ]


def render_usage_tab(stdscr, state: TuiState, y0: int, h: int, w: int, platform: str) -> None:
    _ensure_usage_loaded(state, platform)
    config = state.usage_config or load_config(AXT_CONFIG_PATH)
    entries = state.usage_data.get(platform) or []

    safe_addnstr(stdscr, y0, 0, fit_cells(f" {platform.capitalize()} usage — this month", w - 1), w - 1, CP_HDR())

    if not entries:
        safe_addnstr(stdscr, y0 + 2, 2, f"No {platform} usage data this month yet.", w - 4, CP_DIM())
        return

    tz = config.timezone
    today = _today_in_tz(tz)
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    today_entries = [e for e in entries if _date_in_tz(e.timestamp, tz) == today]
    week_entries = [e for e in entries if _date_in_tz(e.timestamp, tz) >= week_ago]
    month_entries = entries

    row = y0 + 2
    for label, eps in (("Today", today_entries), ("Week", week_entries), ("Month", month_entries)):
        for line in _platform_period_card(eps, label, w - 4):
            safe_addnstr(stdscr, row, 2, fit_cells(line, w - 4), w - 4, 0)
            row += 1
        row += 1

    # 14-day BarChart of daily cost.
    safe_addnstr(stdscr, row, 2, "Last 14 days (daily cost):", w - 4, CP_HDR())
    row += 1
    chart_data = _daily_costs(entries, 14, tz)
    rows_used = render_bar_chart(stdscr, row, 4, w - 8, chart_data)
    row += rows_used + 1

    # Claude: show current active block + simple insights summary.
    if platform == "claude":
        claude_entries = [_unified_to_claude(e) for e in entries]
        blocks = compute_blocks(claude_entries, tz)
        active = next((b for b in blocks if b.is_active), None)
        if active:
            burn = format_tokens(active.burn_rate_per_min) if active.burn_rate_per_min else "—"
            safe_addnstr(stdscr, row, 2, fit_cells(
                f"Active block: {active.start_time[11:16]}–{active.end_time[11:16]}  "
                f"tokens={format_tokens(active.total_tokens)}  burn={burn}/min",
                w - 4), w - 4, CP_OK())
            row += 2

        insights = _compute_simple_insights(claude_entries)
        safe_addnstr(stdscr, row, 2, "Insights (this month):", w - 4, CP_HDR())
        row += 1
        safe_addnstr(stdscr, row, 2, fit_cells(
            f"  large-context sessions (>150k input tokens):  {insights['large_pct']:.1f}%",
            w - 4), w - 4, 0)
        row += 1
        safe_addnstr(stdscr, row, 2, fit_cells(
            f"  parallel sessions (3+ overlapping at once):   {insights['parallel_pct']:.1f}%",
            w - 4), w - 4, 0)
        row += 1
        safe_addnstr(stdscr, row, 2, fit_cells(
            f"  top model by tokens:                          "
            f"{insights['top_model'] or '—'}",
            w - 4), w - 4, 0)
        row += 1
        # Plan-limit row (5h / 7d) if we have the snapshot.
        rl = read_rate_limits(PATHS.usage_snapshot)
        if rl is not None:
            five = f"{rl.five_hour}%" if rl.five_hour is not None else "—"
            seven = f"{rl.seven_day}%" if rl.seven_day is not None else "—"
            safe_addnstr(stdscr, row, 2, fit_cells(
                f"  plan limits:  5h={five}  7d={seven}",
                w - 4), w - 4, CP_INFO())


def _compute_simple_insights(entries: list[ClaudeUsageEntry]) -> dict[str, Any]:
    """Lightweight stand-in for usage-insights.ts.

    Produces three signals the original Ink Insights view shows:
      • large_pct      — % of SESSIONS with >150k input tokens
      • parallel_pct   — % of MESSAGES whose timestamp falls inside a window
                         where 3+ sessions were active simultaneously
      • top_model      — model with the highest token count
    Heavy aggregates (skill/agent/plugin token-share breakdowns) require
    re-reading transcript bodies — deferred to a follow-up.
    """
    if not entries:
        return {"large_pct": 0.0, "parallel_pct": 0.0, "top_model": None}

    # large-context sessions.
    by_session: dict[str, int] = {}
    for e in entries:
        by_session[e.session_id] = by_session.get(e.session_id, 0) + e.input_tokens
    large_sessions = sum(1 for v in by_session.values() if v > 150_000)
    large_pct = (large_sessions / len(by_session)) * 100 if by_session else 0.0

    # parallel sessions: bucket entries into 5-minute windows; flag windows
    # that contain 3+ distinct session_ids.
    bucket: dict[int, set[str]] = {}
    for e in entries:
        ts = _ts_ms(e.timestamp)
        if ts is None:
            continue
        slot = ts // (5 * 60_000)
        bucket.setdefault(slot, set()).add(e.session_id)
    parallel_msgs = 0
    total_msgs = 0
    for e in entries:
        ts = _ts_ms(e.timestamp)
        if ts is None:
            continue
        total_msgs += 1
        slot = ts // (5 * 60_000)
        if len(bucket.get(slot, set())) >= 3:
            parallel_msgs += 1
    parallel_pct = (parallel_msgs / total_msgs) * 100 if total_msgs else 0.0

    # top model by token count.
    by_model: dict[str, int] = {}
    for e in entries:
        by_model[e.model] = by_model.get(e.model, 0) + e.input_tokens + e.output_tokens
    top_model = max(by_model.items(), key=lambda kv: kv[1])[0] if by_model else None

    return {"large_pct": large_pct, "parallel_pct": parallel_pct, "top_model": top_model}


def handle_usage_input(state: TuiState, key: int, platform: str) -> Optional[str]:
    if key == ord("r"):
        state.usage_data.pop(platform, None)
        return "Refreshed"
    return None


# ─── Cursor tab ──────────────────────────────────────────────────────────────


def _ensure_cursor_loaded(state: TuiState) -> None:
    if state.cursor_metrics is not None:
        return
    state.cursor_metrics = load_cursor_metrics(PATHS.cursor_tracking_db)


def render_cursor_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    _ensure_cursor_loaded(state)
    metrics = state.cursor_metrics or []
    summary = summarize_cursor_metrics(metrics)

    safe_addnstr(stdscr, y0, 0, fit_cells(" Cursor — AI vs human code", w - 1), w - 1, CP_HDR())

    if not metrics:
        safe_addnstr(stdscr, y0 + 2, 2, "No Cursor commit metrics found.", w - 4, CP_DIM())
        safe_addnstr(stdscr, y0 + 3, 2, f"Expected DB at: {PATHS.cursor_tracking_db}", w - 4, CP_DIM())
        return

    # Three summary lines.
    row = y0 + 2
    safe_addnstr(stdscr, row, 2, fit_cells(
        f"Commits: {summary.total_commits:>5d}    "
        f"+{summary.total_lines_added:>5d} / -{summary.total_lines_deleted:>5d} lines",
        w - 4), w - 4, 0)
    row += 1
    safe_addnstr(stdscr, row, 2, fit_cells(
        f"AI:      +{summary.ai_lines_added:>5d} / -{summary.ai_lines_deleted:>5d}    "
        f"Human: +{summary.human_lines_added:>5d} / -{summary.human_lines_deleted:>5d}",
        w - 4), w - 4, 0)
    row += 1
    pct = summary.avg_ai_percentage
    bar_w = min(40, w - 30)
    filled = round((pct / 100) * bar_w)
    safe_addnstr(stdscr, row, 2, fit_cells(
        f"Avg AI %: {render_bar(filled, bar_w)} {pct:5.1f}%",
        w - 4), w - 4, CP_INFO())
    row += 2

    # Commits table.
    columns = [
        TableColumn("hash", "Hash", 9),
        TableColumn("date", "Date", 12),
        TableColumn("ai", "AI %", 7),
        TableColumn("lines", "Lines", 14),
        TableColumn("message", "Message", max(20, w - 60)),
    ]
    rows = []
    for m in metrics[:50]:
        rows.append({
            "hash": m.commit_hash[:8],
            "date": m.commit_date[:10] if m.commit_date else "—",
            "ai": f"{m.ai_percentage:.1f}%",
            "lines": f"+{m.lines_added}/-{m.lines_deleted}",
            "message": (m.commit_message or "")[:80],
        })
    state.cursor_selected = max(0, min(state.cursor_selected, max(0, len(rows) - 1)))
    render_table(stdscr, row, 0, h - (row - y0) - 1, w, columns, rows,
                 selected=state.cursor_selected, show_header=True)


def handle_cursor_input(state: TuiState, key: int) -> Optional[str]:
    metrics = state.cursor_metrics or []
    n = min(50, len(metrics))
    if key in (ord("j"), curses.KEY_DOWN):
        state.cursor_selected = min(n - 1, state.cursor_selected + 1) if n else 0
    elif key in (ord("k"), curses.KEY_UP):
        state.cursor_selected = max(0, state.cursor_selected - 1)
    elif key == curses.KEY_NPAGE:
        state.cursor_selected = min(n - 1, state.cursor_selected + 10) if n else 0
    elif key == curses.KEY_PPAGE:
        state.cursor_selected = max(0, state.cursor_selected - 10)
    elif key == ord("r"):
        state.cursor_metrics = None
        return "Refreshed"
    elif is_enter(key) and state.stdscr_callbacks and metrics and state.cursor_selected < len(metrics):
        m = metrics[state.cursor_selected]
        lines = [
            f"Commit:   {m.commit_hash}",
            f"Branch:   {m.branch_name}",
            f"Date:     {m.commit_date}",
            f"AI %:     {m.ai_percentage:.1f}",
            f"Lines:    +{m.lines_added} / -{m.lines_deleted}",
            f"  human:  +{m.human_lines_added} / -{m.human_lines_deleted}",
            f"  AI:     +{m.composer_lines_added} / -{m.composer_lines_deleted}",
            "",
            "── Message ──",
            m.commit_message or "(empty)",
        ]
        preview_modal(state.stdscr_callbacks["stdscr"], "\n".join(lines), title=f"Cursor {m.commit_hash[:8]}")
    return None


# ─── Context tab ─────────────────────────────────────────────────────────────


def _ensure_context_loaded(state: TuiState) -> None:
    if state.context_analysis is not None:
        return
    state.context_analysis = analyze_context(
        home_dir=HOME,
        project_dir=Path.cwd(),
        installed_plugins_path=PATHS.installed_plugins,
        model="claude-opus-4-6",
    )


@dataclass
class _ContextCategoryRow:
    category: str
    label: str
    items: int
    tokens: int
    pct: float


def _context_rows(analysis: ContextAnalysis) -> list[_ContextCategoryRow]:
    by_cat: dict[str, list[ContextSource]] = {}
    for s in analysis.sources:
        by_cat.setdefault(s.category, []).append(s)
    rows = []
    for cat, src_list in by_cat.items():
        tokens = sum(s.estimated_tokens for s in src_list)
        pct = sum(s.percentage for s in src_list)
        rows.append(_ContextCategoryRow(
            category=cat,
            label=CATEGORY_LABELS.get(cat, cat),
            items=len(src_list),
            tokens=tokens,
            pct=pct,
        ))
    rows.sort(key=lambda r: r.tokens, reverse=True)
    return rows


def _render_rate_limit_bars(stdscr, y: int, w: int) -> int:
    """5h/7d rate-limit bars from ~/.claude/usage-snapshot.json. Returns rows used."""
    rl = read_rate_limits(PATHS.usage_snapshot)
    if rl is None:
        safe_addnstr(stdscr, y, 2, "Rate limits: snapshot missing or stale", w - 4, CP_DIM())
        return 1
    bar_w = min(30, w - 40)

    def fmt_eta(reset_at: Optional[datetime]) -> str:
        if not reset_at:
            return "—"
        delta = reset_at - datetime.now(timezone.utc)
        secs = int(delta.total_seconds())
        if secs <= 0:
            return "now"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h {(secs % 3600) // 60}m"
        return f"{secs // 86400}d"

    rows_used = 0
    if rl.five_hour is not None:
        filled = round((rl.five_hour / 100) * bar_w)
        attr = CP_ERR() if rl.five_hour >= 90 else CP_OK() if rl.five_hour < 60 else CP_INFO()
        bar = render_bar(filled, bar_w)
        safe_addnstr(stdscr, y, 2, fit_cells(
            f"5h quota:  {bar} {rl.five_hour:3d}%  reset in {fmt_eta(rl.five_hour_reset_at)}",
            w - 4), w - 4, attr)
        rows_used += 1
    if rl.seven_day is not None:
        filled = round((rl.seven_day / 100) * bar_w)
        attr = CP_ERR() if rl.seven_day >= 90 else CP_OK() if rl.seven_day < 60 else CP_INFO()
        bar = render_bar(filled, bar_w)
        safe_addnstr(stdscr, y + rows_used, 2, fit_cells(
            f"7d quota:  {bar} {rl.seven_day:3d}%  reset in {fmt_eta(rl.seven_day_reset_at)}",
            w - 4), w - 4, attr)
        rows_used += 1
    return rows_used


def render_context_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    _ensure_context_loaded(state)
    analysis = state.context_analysis
    if analysis is None:
        safe_addnstr(stdscr, y0 + 2, 2, "Loading context…", w - 4, CP_DIM())
        return

    safe_addnstr(stdscr, y0, 0, fit_cells(
        f" Context — {format_tokens(analysis.total_tokens)} / {format_tokens(analysis.context_window_size)} "
        f"({analysis.used_percent:.1f}%)  model={analysis.model}",
        w - 1), w - 1, CP_HDR())

    # Rate-limit bars (5h / 7d quota) at the top so the user sees them first.
    rl_rows = _render_rate_limit_bars(stdscr, y0 + 1, w)
    y0_table = y0 + 1 + rl_rows + 1

    rows = _context_rows(analysis)
    if not rows:
        safe_addnstr(stdscr, y0 + 2, 2, "No context sources detected.", w - 4, CP_DIM())
        return

    # Layout: table on left (60%), detail on right (40%).
    table_w = int(w * 0.55)
    detail_x = table_w
    detail_w = w - table_w

    state.context_selected = max(0, min(state.context_selected, len(rows) - 1))

    columns = [
        TableColumn("label", "Category", max(15, table_w - 35)),
        TableColumn("items", "#", 4),
        TableColumn("tokens", "Tokens", 10),
        TableColumn("pct", "%", 8),
    ]
    table_rows = []
    for r in rows:
        table_rows.append({
            "label": r.label,
            "items": str(r.items),
            "tokens": format_tokens(r.tokens),
            "pct": f"{r.pct:.1f}%",
        })

    table_h = h - (y0_table - y0) - 2
    render_table(stdscr, y0_table, 0, table_h, table_w, columns, table_rows,
                 selected=state.context_selected, show_header=True)

    # Detail panel: list sources in the selected category.
    current = rows[state.context_selected]
    detail_fields = []
    sources_in_cat = [s for s in analysis.sources if s.category == current.category]
    sources_in_cat.sort(key=lambda s: s.estimated_tokens, reverse=True)
    for s in sources_in_cat[:20]:
        hint = f" ({s.hint})" if s.hint else ""
        detail_fields.append((s.name, f"{format_tokens(s.estimated_tokens)} tok{hint}"))
    if not detail_fields:
        detail_fields = [("(empty)", "—")]
    render_detail_panel(stdscr, y0_table, detail_x, table_h, detail_w,
                        title=current.label, fields=detail_fields)

    # Cost impact line at the bottom.
    ci = analysis.cost_impact
    safe_addnstr(stdscr, y0 + h - 2, 0, fit_cells(
        f"  cost: cache_write=${ci.cache_write_cost:.3f}  "
        f"read/turn=${ci.cache_read_cost_per_turn:.3f}  "
        f"per_session(${ci.per_session_cost:.2f})  monthly(${ci.monthly_cost:.2f})",
        w - 1), w - 1, CP_DIM())


def handle_context_input(state: TuiState, key: int) -> Optional[str]:
    rows = _context_rows(state.context_analysis) if state.context_analysis else []
    n = len(rows)
    if key in (ord("j"), curses.KEY_DOWN):
        state.context_selected = min(n - 1, state.context_selected + 1) if n else 0
    elif key in (ord("k"), curses.KEY_UP):
        state.context_selected = max(0, state.context_selected - 1)
    elif key == ord("r"):
        state.context_analysis = None
        return "Refreshed"
    elif key == ord("e") and state.context_analysis and state.stdscr_callbacks and 0 <= state.context_selected < n:
        cat = rows[state.context_selected].category
        first = next((s for s in state.context_analysis.sources if s.category == cat and s.path), None)
        if first is None:
            return "No file to edit in this category"
        ok = open_in_editor(state.stdscr_callbacks["stdscr"], first.path)
        return f"Opened {first.path}" if ok else "Editor failed"
    elif is_enter(key) and state.context_analysis and state.stdscr_callbacks and 0 <= state.context_selected < n:
        cat = rows[state.context_selected].category
        srcs = [s for s in state.context_analysis.sources if s.category == cat]
        lines = [f"{rows[state.context_selected].label} — {rows[state.context_selected].items} item(s)", ""]
        for s in srcs[:50]:
            hint = f"  ({s.hint})" if s.hint else ""
            lines.append(f"• {s.name}{hint}")
            if s.path:
                lines.append(f"    {s.path}")
            lines.append(f"    {format_tokens(s.estimated_tokens)} tok  {s.percentage:.1f}%")
            lines.append("")
        preview_modal(state.stdscr_callbacks["stdscr"], "\n".join(lines), title=rows[state.context_selected].label)
    return None


# ─── Project tab ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectContextItem:
    name: str
    source: str
    path: str
    content: str
    lines: int


def load_project_context(cwd: os.PathLike[str] | str) -> list[ProjectContextItem]:
    """Mirror src/core/project-context.ts. Returns CLAUDE.md / settings.json /
    memory files relevant to the given project directory."""
    cwd_str = str(cwd)
    home = HOME
    claude_dir = home / ".claude"
    project_settings_dir_name = cwd_str.replace("/", "-")
    # Re-add leading dash per TS quirk: `.replace(/^-/, "-")` is a no-op,
    # so we don't need to strip; just pass through.
    project_settings_dir = claude_dir / "projects" / project_settings_dir_name

    candidates = [
        ("CLAUDE.md (global)", "global", home / "CLAUDE.md"),
        ("CLAUDE.md (user)", "user", claude_dir / "CLAUDE.md"),
        ("CLAUDE.md (project)", "project", Path(cwd) / "CLAUDE.md"),
        ("CLAUDE.md (project/.claude)", "project", Path(cwd) / ".claude" / "CLAUDE.md"),
        ("settings.json (global)", "global", claude_dir / "settings.json"),
        ("settings.local.json (global)", "global", claude_dir / "settings.local.json"),
        ("settings.json (project)", "project", project_settings_dir / "settings.json"),
        ("settings.local.json (project)", "project", project_settings_dir / "settings.local.json"),
    ]
    items: list[ProjectContextItem] = []
    for name, source, path in candidates:
        content = _safe_read_text(path)
        if content is None:
            continue
        items.append(ProjectContextItem(
            name=name, source=source, path=str(path), content=content,
            lines=content.count("\n") + 1,
        ))

    memory_dir = project_settings_dir / "memory"
    for f in _safe_listdir(memory_dir):
        if not f.endswith(".md"):
            continue
        fp = memory_dir / f
        content = _safe_read_text(fp)
        if content is None:
            continue
        stem = Path(f).stem
        items.append(ProjectContextItem(
            name=f"Memory: {stem}", source="memory", path=str(fp),
            content=content, lines=content.count("\n") + 1,
        ))
    return items


def _ensure_project_loaded(state: TuiState) -> None:
    if state.project_items is not None:
        return
    state.project_items = load_project_context(Path.cwd())


def render_project_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    _ensure_project_loaded(state)
    items = state.project_items or []

    safe_addnstr(stdscr, y0, 0, fit_cells(
        f" Project context — {Path.cwd().name}  ({len(items)} files)",
        w - 1), w - 1, CP_HDR())

    if not items:
        safe_addnstr(stdscr, y0 + 2, 2, "No project context files found.", w - 4, CP_DIM())
        return

    # Layout: table on left (50%), preview on right (50%).
    table_w = int(w * 0.45)
    preview_x = table_w
    preview_w = w - table_w

    state.project_selected = max(0, min(state.project_selected, len(items) - 1))

    columns = [
        TableColumn("name", "Name", max(20, table_w - 22)),
        TableColumn("source", "Source", 8),
        TableColumn("lines", "Lines", 6),
    ]
    rows = [{"name": i.name, "source": i.source, "lines": str(i.lines)} for i in items]
    render_table(stdscr, y0 + 1, 0, h - 2, table_w, columns, rows,
                 selected=state.project_selected, show_header=True)

    # Preview: render the file content in the detail panel.
    current = items[state.project_selected]
    # Show first ~40 lines of content as detail rows (label/value pairs aren't ideal,
    # but the panel is also OK with lines-mode).
    fields: list[tuple[str, str]] = [
        ("Source", current.source),
        ("Path", current.path),
        ("Lines", str(current.lines)),
        ("─" * 10, ""),
    ]
    preview_lines = current.content.split("\n")[:40]
    for i, ln in enumerate(preview_lines):
        fields.append((f"{i + 1:3d}", ln))
    render_detail_panel(stdscr, y0 + 1, preview_x, h - 2, preview_w,
                        title=current.name, fields=fields, scroll=state.project_scroll)


def handle_project_input(state: TuiState, key: int) -> Optional[str]:
    items = state.project_items or []
    n = len(items)
    if key in (ord("j"), curses.KEY_DOWN):
        state.project_selected = min(n - 1, state.project_selected + 1) if n else 0
        state.project_scroll = 0
    elif key in (ord("k"), curses.KEY_UP):
        state.project_selected = max(0, state.project_selected - 1)
        state.project_scroll = 0
    elif key == curses.KEY_NPAGE:
        state.project_scroll += 10
    elif key == curses.KEY_PPAGE:
        state.project_scroll = max(0, state.project_scroll - 10)
    elif key == ord("r"):
        state.project_items = None
        return "Refreshed"
    elif is_enter(key) and state.stdscr_callbacks and items and state.project_selected < n:
        item = items[state.project_selected]
        preview_modal(state.stdscr_callbacks["stdscr"], item.content, title=item.name)
    elif key == ord("e") and state.stdscr_callbacks and items and state.project_selected < n:
        item = items[state.project_selected]
        ok = open_in_editor(state.stdscr_callbacks["stdscr"], item.path)
        return f"Opened {item.path}" if ok else "Editor failed"
    return None


# ─── Extensions sub-tabs ─────────────────────────────────────────────────────


EXTENSION_SUB_TABS: tuple[tuple[str, str], ...] = (
    ("vault", "Vault"),
    ("plugins", "Plugins"),
    ("skills", "Skills"),
    ("commands", "Commands"),
    ("agents", "Agents"),
    ("mcp", "MCP"),
    ("hooks", "Hooks"),
    ("market", "Market"),
)


def _render_subtab_bar(stdscr, y: int, w: int, active_key: str, *, focused: bool = False) -> None:
    """Render the Extensions sub-tab bar with a clear focus indicator.

    Layered focus (matches `render_tab_bar` so focus is unambiguous when
    switching between main-tab and sub-tab layers):
      - Bar focused:    `▶ Sub:` marker + active sub-tab is solid cyan chip
                        (pair 1 + BOLD), brackets retained for color-blind safety
      - Bar unfocused:  `  Sub:` (no marker) + active sub-tab is bold cyan text
                        with underline (no fill), brackets retained
    """
    label_attr = CP_HDR() if focused else CP_DIM()
    marker = "▶ " if focused else "  "
    marker_attr = _safe_pair(8, curses.A_BOLD) if focused else CP_DIM()
    safe_addnstr(stdscr, y, 0, marker, w, marker_attr)
    safe_addnstr(stdscr, y, cell_width(marker), "Sub: ", w - cell_width(marker), label_attr)
    cur = cell_width(marker) + 5  # "Sub: " is 5 cells
    inactive_attr = _safe_pair(8, curses.A_BOLD) if focused else CP_DIM()
    active_attr = _safe_pair(1, curses.A_BOLD) if focused else _safe_pair(8, curses.A_BOLD | curses.A_UNDERLINE)
    for i, (key, label) in enumerate(EXTENSION_SUB_TABS):
        if key == active_key:
            cell = f"[ {label} ]"
            attr = active_attr
        else:
            cell = f"  {label}  "
            attr = inactive_attr
        if cur + cell_width(cell) >= w:
            break
        safe_addnstr(stdscr, y, cur, cell, w - cur, attr)
        cur += cell_width(cell) + 1
    if cur < w:
        safe_addnstr(stdscr, y, cur, " " * (w - cur - 1), w - cur - 1, CP_DIM())


def _ensure_subtab_loaded(state: TuiState, sub_key: str) -> None:
    if sub_key in state.ext_cache:
        return
    if sub_key == "plugins":
        state.ext_cache["plugins"] = list_installed_plugins(PATHS.installed_plugins)
    elif sub_key == "skills":
        state.ext_cache["skills"] = list_all_skills(project_dir=Path.cwd())
    elif sub_key == "commands":
        state.ext_cache["commands"] = list_commands(project_dir=Path.cwd())
    elif sub_key == "agents":
        state.ext_cache["agents"] = list_all_agents(project_dir=Path.cwd())
    elif sub_key == "mcp":
        state.ext_cache["mcp"] = list_mcp_servers(_active_plugins())
    elif sub_key == "hooks":
        state.ext_cache["hooks"] = list_hooks(
            user_settings_path=PATHS.settings,
            project_dir=Path.cwd(),
            installed_plugins_path=PATHS.installed_plugins,
        )
    elif sub_key == "market":
        state.ext_cache["market"] = list_marketplaces(PATHS.known_marketplaces)


def _render_simple_list(stdscr, state, y0, h, w, key, columns, rows):
    """Render a simple selectable list for a sub-tab."""
    state.ext_selected.setdefault(key, 0)
    state.ext_selected[key] = max(0, min(state.ext_selected[key], max(0, len(rows) - 1)))
    if not rows:
        safe_addnstr(stdscr, y0 + 2, 2, f"No {key} found.", w - 4, CP_DIM())
        return
    render_table(stdscr, y0, 0, h, w, columns, rows,
                 selected=state.ext_selected[key], show_header=True)


def render_extensions_tab(stdscr, state: TuiState, y0: int, h: int, w: int) -> None:
    """Extensions parent tab with sub-tab navigation."""
    _render_subtab_bar(
        stdscr, y0, w, state.ext_sub_tab,
        focused=(state.focused_layer == "subTab"),
    )
    safe_addnstr(stdscr, y0 + 1, 0, "─" * (w - 1), w - 1, CP_DIM())

    sub_y = y0 + 2
    sub_h = h - 2

    sub = state.ext_sub_tab
    if sub == "vault":
        render_vault_tab(stdscr, state, sub_y, sub_h, w)
        return

    _ensure_subtab_loaded(state, sub)
    data = state.ext_cache.get(sub, [])

    # Non-Vault sub-tabs use the default render_table prefix (` N`/`▸N`) for
    # row numbering — no separate `#` data column needed (it would duplicate).
    if sub == "plugins":
        cols = [
            TableColumn("name", "Plugin", max(20, w - 60)),
            TableColumn("version", "Version", 10),
            TableColumn("status", "G/P", 10),
            TableColumn("market", "Marketplace", 24),
        ]
        enabled_g = read_enabled_plugins(PATHS.settings)
        enabled_p = read_enabled_plugins(project_settings_path())

        def _glyph(v):
            if v is True:
                return "●"
            if v is False:
                return "○"
            return "·"

        rows = [{
            "name": p.name,
            "version": p.version or "—",
            "status": f"{_glyph(enabled_g.get(p.id))} / {_glyph(enabled_p.get(p.id))}",
            "market": p.marketplace or "—",
        } for p in data]

    elif sub == "skills":
        cols = [
            TableColumn("name", "Skill", max(25, w - 50)),
            TableColumn("source", "Source", 9),
            TableColumn("type", "Type", 8),
            TableColumn("path", "Path", 30),
        ]
        rows = [{
            "name": s.name,
            "source": s.source,
            "type": "symlink" if s.is_symlink else "dir",
            "path": (s.target or s.path)[:60],
        } for s in data]

    elif sub == "commands":
        cols = [
            TableColumn("name", "Command", max(20, w - 60)),
            TableColumn("source", "Source", 9),
            TableColumn("desc", "Description", 50),
        ]
        rows = [{
            "name": f"/{c.name}",
            "source": c.source,
            "desc": (c.description or "")[:80],
        } for c in data]

    elif sub == "agents":
        cols = [
            TableColumn("name", "Agent", max(20, w - 60)),
            TableColumn("source", "Source", 9),
            TableColumn("desc", "Description", 50),
        ]
        rows = [{
            "name": a.name,
            "source": a.source,
            "desc": (a.description or "")[:80],
        } for a in data]

    elif sub == "mcp":
        cols = [
            TableColumn("name", "Server", max(20, w - 60)),
            TableColumn("plugin", "Plugin", 25),
            TableColumn("cmd", "Command", 30),
        ]
        rows = [{
            "name": s.name,
            "plugin": s.plugin_id,
            "cmd": " ".join([s.command, *s.args_list])[:60],
        } for s in data]

    elif sub == "hooks":
        cols = [
            TableColumn("event", "Event", 22),
            TableColumn("type", "Type", 10),
            TableColumn("source", "Source", 10),
            TableColumn("detail", "Detail", max(20, w - 70)),
        ]
        rows = [{
            "event": h.event,
            "type": h.type,
            "source": h.source,
            "detail": get_hook_detail(h)[:80],
        } for h in data]

    elif sub == "market":
        cols = [
            TableColumn("name", "Marketplace", max(20, w - 70)),
            TableColumn("kind", "Source", 10),
            TableColumn("loc", "Location", 30),
            TableColumn("updated", "Updated", 12),
        ]
        rows = [{
            "name": m.name,
            "kind": m.source.kind,
            "loc": m.install_location[:50],
            "updated": m.last_updated[:10],
        } for m in data]
    else:
        return

    _render_simple_list(stdscr, state, sub_y, sub_h, w, sub, cols, rows)


def _cycle_sub_tab(state: TuiState, direction: int) -> None:
    i = next((idx for idx, (k, _) in enumerate(EXTENSION_SUB_TABS) if k == state.ext_sub_tab), 0)
    state.ext_sub_tab = EXTENSION_SUB_TABS[(i + direction) % len(EXTENSION_SUB_TABS)][0]


def _at_top_of_content(state: TuiState, tab_key: str) -> bool:
    """True when the active tab's selection is at row 0 — used to decide
    whether ↑ should climb out of the content into the focus row above."""
    if tab_key == "extensions":
        if state.ext_sub_tab == "vault":
            return state.vault_selected == 0
        return state.ext_selected.get(state.ext_sub_tab, 0) == 0
    if tab_key == "cursor":
        return state.cursor_selected == 0
    if tab_key == "context":
        return state.context_selected == 0
    if tab_key == "project":
        return state.project_selected == 0
    # Tabs without a selection (dashboard, usage) always count as "top".
    return True


def handle_extensions_input(state: TuiState, key: int) -> Optional[str]:
    """Handles Extensions sub-tab switching AND delegates to active sub-tab.

    Sub-tab cycling keys:
      [           previous sub-tab
      ]           next sub-tab
      Shift+Tab   previous (KEY_BTAB)
      Tab         next — ONLY on non-Vault sub-tabs (Vault's Tab is filter)
    """
    if key == ord("["):
        _cycle_sub_tab(state, -1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == ord("]"):
        _cycle_sub_tab(state, 1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == curses.KEY_BTAB:  # Shift+Tab
        _cycle_sub_tab(state, -1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == KEY_TAB and state.ext_sub_tab != "vault":
        # Vault's Tab is the filter cycler; only intercept Tab elsewhere.
        _cycle_sub_tab(state, 1)
        return f"Sub-tab: {state.ext_sub_tab}"
    if key == ord("r"):
        # Refresh the active sub-tab's cache.
        state.ext_cache.pop(state.ext_sub_tab, None)
        if state.ext_sub_tab == "vault":
            state.vault_items = []
            state.refresh_token = 0
        return "Refreshed"

    sub = state.ext_sub_tab
    if sub == "vault":
        return handle_vault_input(state, key)

    # Simple list navigation for the other sub-tabs.
    data = state.ext_cache.get(sub, [])
    n = len(data)
    sel = state.ext_selected.get(sub, 0)
    if key in (ord("j"), curses.KEY_DOWN):
        state.ext_selected[sub] = min(n - 1, sel + 1) if n else 0
        return None
    elif key in (ord("k"), curses.KEY_UP):
        state.ext_selected[sub] = max(0, sel - 1)
        return None
    elif key == curses.KEY_NPAGE:
        state.ext_selected[sub] = min(n - 1, sel + 10) if n else 0
        return None
    elif key == curses.KEY_PPAGE:
        state.ext_selected[sub] = max(0, sel - 10)
        return None
    return _handle_subtab_action(state, sub, key)


def _selected_item(state: TuiState, sub: str) -> Any:
    """Return the currently selected item in the given Extensions sub-tab."""
    data = state.ext_cache.get(sub, [])
    sel = state.ext_selected.get(sub, 0)
    if 0 <= sel < len(data):
        return data[sel]
    return None


def _handle_subtab_action(state: TuiState, sub: str, key: int) -> Optional[str]:
    """Sub-tab-specific actions (l/u/a/s/r/p/e/x). Returns status message."""
    # Note: stdscr-bound actions (confirm_modal, text_input_modal,
    # preview_modal, open_in_editor) are wired through _tab_stdscr_actions
    # because handler functions don't have stdscr. We use a callback.
    cb = state.stdscr_callbacks
    if not cb:
        return None  # No interactive context available (e.g. tests)
    stdscr = cb.get("stdscr")

    # ── Plugins: e/d=global, E/D=project, x=uninstall i=info ───────────────
    if sub == "plugins":
        plugin = _selected_item(state, "plugins")
        if plugin is None:
            return None
        if key == ord("e"):
            try:
                set_plugin_enabled(PATHS.settings, plugin.id, True)
                state.ext_cache.pop("plugins", None)
                return f"Enabled {plugin.id} (global)"
            except OSError as exc:
                return f"Enable failed: {exc}"
        if key == ord("d"):
            try:
                set_plugin_enabled(PATHS.settings, plugin.id, False)
                state.ext_cache.pop("plugins", None)
                return f"Disabled {plugin.id} (global)"
            except OSError as exc:
                return f"Disable failed: {exc}"
        if key == ord("E"):
            try:
                set_plugin_enabled(project_settings_path(), plugin.id, True)
                state.ext_cache.pop("plugins", None)
                return f"Enabled {plugin.id} (project)"
            except OSError as exc:
                return f"Enable failed: {exc}"
        if key == ord("D"):
            try:
                set_plugin_enabled(project_settings_path(), plugin.id, False)
                state.ext_cache.pop("plugins", None)
                return f"Disabled {plugin.id} (project)"
            except OSError as exc:
                return f"Disable failed: {exc}"
        if key == ord("x") and stdscr:
            if confirm_modal(stdscr, f"Uninstall plugin {plugin.id}?\nThis removes {plugin.install_path}."):
                import shutil
                try:
                    shutil.rmtree(plugin.install_path, ignore_errors=True)
                    remove_installed_plugin(PATHS.installed_plugins, plugin.id)
                    remove_plugin_from_settings(PATHS.settings, plugin.id)
                    state.ext_cache.pop("plugins", None)
                    return f"Uninstalled {plugin.id}"
                except OSError as exc:
                    return f"Uninstall failed: {exc}"
            return "Cancelled"

    # ── Skills: l=link new path, u=unlink selected (confirmed) ─────────────
    if sub == "skills" and stdscr:
        if key == ord("l"):
            if not is_symlink_supported():
                return "Symlinks unsupported on this platform"
            target = text_input_modal(stdscr,
                                       "Path to skill directory to link",
                                       title="Skill link",
                                       initial="")
            if not target:
                return None
            try:
                link_skill(PATHS.skills, target.strip())
                state.ext_cache.pop("skills", None)
                return f"Linked {target}"
            except (OSError, ValueError) as exc:
                return f"Link failed: {exc}"
        if key == ord("u"):
            skill = _selected_item(state, "skills")
            if skill is None:
                return None
            if not skill.is_symlink:
                return "Selected skill is not a symlink (cannot unlink)"
            if confirm_modal(stdscr, f"Unlink skill {skill.name}?", title="Confirm unlink"):
                try:
                    unlink_skill(PATHS.skills, skill.name)
                    state.ext_cache.pop("skills", None)
                    return f"Unlinked {skill.name}"
                except (OSError, ValueError) as exc:
                    return f"Unlink failed: {exc}"
            return "Cancelled"

    # ── Marketplace: a=add (2-step), s=sync (selected), r=remove (confirmed)
    if sub == "market" and stdscr:
        if key == ord("a"):
            source_str = text_input_modal(
                stdscr,
                "Source (github:user/repo, git:url, dir:/path)",
                title="Marketplace add",
            )
            if not source_str:
                return None
            try:
                source = parse_marketplace_source(source_str.strip())
            except ValueError as exc:
                return f"Parse failed: {exc}"
            if source.kind == "github":
                default_name = source.repo.split("/")[-1] if source.repo else ""
            elif source.kind == "directory":
                default_name = (source.path or "").rstrip("/").split("/")[-1]
            else:
                default_name = "custom"
            name = text_input_modal(stdscr, "Local name for this marketplace",
                                     title="Marketplace name",
                                     initial=default_name)
            if not name:
                return None
            try:
                add_marketplace(PATHS.known_marketplaces, PATHS.marketplaces, name.strip(), source)
                state.ext_cache.pop("market", None)
                return f"Added {name.strip()}"
            except (RuntimeError, FileNotFoundError, ValueError) as exc:
                return f"Add failed: {exc}"
        m = _selected_item(state, "market")
        if m is None:
            return None
        if key == ord("s"):
            try:
                result = sync_marketplace(PATHS.known_marketplaces, m.name)
                state.ext_cache.pop("market", None)
                return f"Synced {m.name}: {result.before} → {result.after}" if result.updated else f"{m.name} up to date"
            except (RuntimeError, KeyError) as exc:
                return f"Sync failed: {exc}"
        if key == ord("r"):
            if confirm_modal(stdscr, f"Remove marketplace {m.name}?\nThis deletes {m.install_location}.",
                             title="Confirm remove"):
                try:
                    remove_marketplace(PATHS.known_marketplaces, PATHS.marketplaces, m.name)
                    state.ext_cache.pop("market", None)
                    return f"Removed {m.name}"
                except KeyError as exc:
                    return f"Remove failed: {exc}"
            return "Cancelled"

    # ── Hooks: p=preview hook execution in a scrollable modal ──────────────
    if sub == "hooks" and stdscr:
        if key == ord("p"):
            hook = _selected_item(state, "hooks")
            if hook is None:
                return None
            try:
                result = preview_hook(hook)
            except OSError as exc:
                return f"Preview failed: {exc}"
            lines = [
                f"Type:    {result.type}",
                f"Summary: {result.summary}",
                "",
            ]
            if result.exit_code is not None:
                lines.append(f"Exit:    {result.exit_code}")
            if result.output:
                lines += ["", "── stdout ──", result.output]
            if result.error:
                lines += ["", "── stderr ──", result.error]
            preview_modal(stdscr, "\n".join(lines), title=f"Hook preview: {hook.event}")
            return None

    # ── Commands / Agents: e=open source file in $EDITOR ──────────────────
    if sub in ("commands", "agents") and stdscr and key == ord("e"):
        item = _selected_item(state, sub)
        if item is None or not item.source_path:
            return None
        ok = open_in_editor(stdscr, item.source_path)
        return f"Opened {item.source_path}" if ok else "Editor failed"

    return None


# ── Section 14: TUI — Main loop ──────────────────────────────────────────────


HELP_TEXT = """\
axt TUI — keyboard reference

Navigation
  1–8           Jump to main tab (active tab has cyan background)
  ← / →         Previous / next within the focused layer
  ↑ / ↓         Move focus between layers (mainTab ↔ subTab ↔ content)
  Enter         Drop focus one layer down OR confirm an action
  [ / ]         Extensions: previous / next sub-tab
  Shift+Tab     Extensions: previous sub-tab (alt)
  Tab           Extensions (non-Vault): next sub-tab (alt)
  j / ↓         Move selection down (within a list)
  k / ↑         Move selection up
  PgUp / PgDn   Page up / page down

Vault
  Space         Toggle PROJECT link for selected item (pending)
  g             Toggle GLOBAL link for selected item (pending)
  Enter         Apply pending toggles  OR  focus detail panel if no pending
  Esc           Discard pending OR blur detail panel
  /             Search input (type → Enter to apply, Esc to clear)
  Tab           Cycle filter (all/skill/command/agent/plugin)
  s             Cycle sort key (incl. `used`, most-used first)
  i             Import a global-only item into the vault (selected row)
  f             Toggle scan mode AND scan ALL projects (cached to disk)
  m             Migrate ~/.claude/skills,commands,agents → vault
  S             Sync .claude/<sub>/ symlinks with .axt-profile.json
  r             Refresh (cheap, no cross-project walk)

Extensions sub-tab actions
  Plugins:      e=enable (global)  d=disable (global)
                E=enable (project) D=disable (project)
                x=uninstall (confirm)
                Status column shows G/P: ● enabled  ○ disabled  · unset
  Skills:       l=link new path (input)  u=unlink (confirm)
  Marketplace:  a=add (source+name input)  s=sync (selected)  r=remove (confirm)
  Commands/Agents: e=open source file in $EDITOR
  Hooks:        p=preview hook execution (scrollable modal)

Cursor / Context / Project
  Enter         Cursor: full commit preview. Project: file content preview.
                Context: category source list preview.
  e             Context: open first source file in $EDITOR.
                Project: open selected file in $EDITOR.

linked vs enabled (activation mechanism)
  skill / command / agent → "linked"   = SYMLINK at .claude/<type>s/<name>
  plugin                  → "enabled"  = settings.json's enabledPlugins[<id>]
  The TUI shows ● / ○ for both, with the DetailPanel labeling the kind.

Vault column meanings
  Vault   ✓        Item lives in ~/.axt/vault/
          global*  Item only exists in ~/.claude/{type}s/ (use `i` to import)
  Proj    ● / ○    linked/enabled in this project (* = pending toggle)
  Glob    ● / ○    linked/enabled globally
  Used    N proj   Count from last scan (`f` populates this column)

Globals
  ?             Show this help
  q / Esc       Quit (Esc only quits when no pending state)
"""


def _render_frame(stdscr, state: TuiState) -> None:
    h, w = stdscr.getmaxyx()
    if h < 5 or w < 30:
        stdscr.erase()
        safe_addnstr(stdscr, 0, 0, "Terminal too small. Resize and try again.", w - 1, CP_ERR())
        return
    stdscr.erase()

    # Header (tab bar + project path + divider).
    render_tab_bar(stdscr, 0, 0, w, state.tab_idx, focused=(state.focused_layer == "mainTab"))
    project_line = f" cwd: {Path.cwd()}"
    safe_addnstr(stdscr, 1, 0, fit_cells(project_line, w - 1), w - 1, CP_DIM())
    safe_addnstr(stdscr, 2, 0, "─" * (w - 1), w - 1, CP_DIM())

    # Tab content.
    body_y = 3
    body_h = h - body_y - 1  # leave one line for status

    tab_key = MAIN_TABS[state.tab_idx][0]
    if tab_key == "extensions":
        render_extensions_tab(stdscr, state, body_y, body_h, w)
    elif tab_key == "context":
        render_context_tab(stdscr, state, body_y, body_h, w)
    elif tab_key == "project":
        render_project_tab(stdscr, state, body_y, body_h, w)
    elif tab_key == "dashboard":
        render_dashboard_tab(stdscr, state, body_y, body_h, w)
    elif tab_key in ("claude", "codex", "gemini"):
        render_usage_tab(stdscr, state, body_y, body_h, w, tab_key)
    elif tab_key == "cursor":
        render_cursor_tab(stdscr, state, body_y, body_h, w)
    else:
        render_stub_tab(stdscr, state, body_y, body_h, w,
                        name=MAIN_TABS[state.tab_idx][2], hint="")

    # Status / shortcuts line — adjust per active tab + sub-tab.
    if tab_key == "extensions" and state.ext_sub_tab == "vault":
        if state.vault_searching:
            shortcuts = "/: typing search…  Enter:apply  Esc:cancel"
        elif state.vault_pending_project or state.vault_pending_global:
            shortcuts = "Enter:apply pending  Esc:discard  Space:project  g:global  j/k:nav"
        else:
            shortcuts = (
                "1-8:tab  [/]:sub  j/k:nav  Space:project  g:global  Enter:apply  "
                "Tab:filter  s:sort  /:search  i:import  f:scan  m:migrate  S:sync  r:refresh  ?:help  q:quit"
            )
    elif tab_key == "extensions":
        shortcuts = "1-8:tab  [/]:sub  j/k:nav  r:refresh  ?:help  q:quit"
    else:
        shortcuts = "1-8:tab  j/k:nav  r:refresh  ?:help  q:quit"
    render_status_bar(stdscr, h - 1, w, shortcuts, state.status)

    stdscr.refresh()


def _tui_loop(stdscr) -> None:
    curses.curs_set(0)
    try:
        curses.set_escdelay(25)  # 3.9+
    except (AttributeError, curses.error):
        pass
    stdscr.keypad(True)
    stdscr.timeout(-1)  # blocking getch
    tui_init_colors()

    state = TuiState()
    state.stdscr_callbacks = {"stdscr": stdscr}
    _render_frame(stdscr, state)

    while True:
        if state.show_help:
            show_modal(stdscr, HELP_TEXT, title="axt help")
            state.show_help = False
            _render_frame(stdscr, state)
            continue

        try:
            key = stdscr.getch()
        except KeyboardInterrupt:
            return

        if key == -1:
            continue

        # Modal states that intercept input — pass key straight to the active
        # tab handler so it can process search/pending logic without losing
        # keystrokes to the global tab-switcher.
        tab_key = MAIN_TABS[state.tab_idx][0]
        modal = (
            tab_key == "extensions"
            and state.ext_sub_tab == "vault"
            and (state.vault_searching
                 or state.vault_pending_project
                 or state.vault_pending_global
                 or state.vault_detail_focused)
        )

        # Global keys (skipped while in a modal sub-state).
        if not modal:
            if key == ord("?"):
                state.show_help = True
                continue
            if is_quit(key):
                return
            if key == curses.KEY_RESIZE:
                _render_frame(stdscr, state)
                continue
            if ord("1") <= key <= ord("8"):
                state.tab_idx = key - ord("1")
                state.status = ""
                state.focused_layer = "content"
                _render_frame(stdscr, state)
                continue

            # ── Focus-layer aware arrow navigation ──
            # ←/→ : cycle within the focused layer (mainTab cycles tabs;
            #       subTab cycles sub-tabs; content also cycles main tabs).
            # ↑   : move focus up (content → subTab/mainTab → mainTab)
            # ↓   : move focus down (mainTab → subTab/content → content)
            # Enter from mainTab/subTab: drop into the next layer down.

            if state.focused_layer == "mainTab":
                if key in (curses.KEY_LEFT, ord("h")):
                    state.tab_idx = (state.tab_idx - 1) % len(MAIN_TABS)
                    _render_frame(stdscr, state)
                    continue
                if key in (curses.KEY_RIGHT, ord("l")):
                    state.tab_idx = (state.tab_idx + 1) % len(MAIN_TABS)
                    _render_frame(stdscr, state)
                    continue
                if key == curses.KEY_DOWN or is_enter(key):
                    state.focused_layer = "subTab" if tab_key == "extensions" else "content"
                    _render_frame(stdscr, state)
                    continue
                if key == curses.KEY_UP:
                    # Already at the top — no-op for clarity.
                    continue

            elif state.focused_layer == "subTab":
                if key == curses.KEY_LEFT:
                    _cycle_sub_tab(state, -1)
                    _render_frame(stdscr, state)
                    continue
                if key == curses.KEY_RIGHT:
                    _cycle_sub_tab(state, 1)
                    _render_frame(stdscr, state)
                    continue
                if key == curses.KEY_UP:
                    state.focused_layer = "mainTab"
                    _render_frame(stdscr, state)
                    continue
                if key == curses.KEY_DOWN or is_enter(key):
                    state.focused_layer = "content"
                    _render_frame(stdscr, state)
                    continue

            else:  # focused_layer == "content"
                # Allow ↑ from the TOP of a list to climb back out.
                if key == curses.KEY_UP and _at_top_of_content(state, tab_key):
                    state.focused_layer = "subTab" if tab_key == "extensions" else "mainTab"
                    _render_frame(stdscr, state)
                    continue
                # ← / → still cycle main tabs (legacy) so users without focus
                # awareness keep working as before.
                if key == curses.KEY_LEFT:
                    state.tab_idx = (state.tab_idx - 1) % len(MAIN_TABS)
                    _render_frame(stdscr, state)
                    continue
                if key == curses.KEY_RIGHT:
                    state.tab_idx = (state.tab_idx + 1) % len(MAIN_TABS)
                    _render_frame(stdscr, state)
                    continue
        else:
            # In modal: still allow resize.
            if key == curses.KEY_RESIZE:
                _render_frame(stdscr, state)
                continue

        # When focus is mainTab/subTab, the tab body handlers should NOT
        # consume keys (we already handled all the relevant ones above).
        # Drop the key here.
        if not modal and state.focused_layer != "content":
            continue

        # Tab-specific input.
        tab_key = MAIN_TABS[state.tab_idx][0]
        status: Optional[str] = None
        if tab_key == "extensions":
            status = handle_extensions_input(state, key)
        elif tab_key == "context":
            status = handle_context_input(state, key)
        elif tab_key == "project":
            status = handle_project_input(state, key)
        elif tab_key == "dashboard":
            status = handle_dashboard_input(state, key)
        elif tab_key in ("claude", "codex", "gemini"):
            status = handle_usage_input(state, key, tab_key)
        elif tab_key == "cursor":
            status = handle_cursor_input(state, key)
        else:
            handle_stub_input(state, key)

        if status is not None:
            state.status = status

        _render_frame(stdscr, state)


def launch_tui() -> int:
    """Public entry point — invoked from `cli_tui` and `main` with no args."""
    try:
        curses.wrapper(_tui_loop)
    except curses.error as e:
        print(_red(f"TUI failed to start: {e}"), file=sys.stderr)
        print(_dim("This usually means the terminal is too small or doesn't support curses."), file=sys.stderr)
        return 1
    return 0


# ── Section 15: Entry Point ──────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point used by `axt = axt:main` in pyproject.toml."""
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()

    # No-arg invocation → launch TUI (matches `axt` with no args).
    if not argv:
        return cli_tui(argparse.Namespace())

    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    try:
        return func(args) or 0
    except (FileNotFoundError, FileExistsError, KeyError, ValueError, OSError, RuntimeError) as e:
        print(_red(f"✗ {e}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
