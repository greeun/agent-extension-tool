#!/usr/bin/env python3
"""
axt — Agent eXtension Tool (Python edition)

Single-file CLI + curses TUI for Claude Code extension / plugin / skill /
MCP / hook / command / agent / usage management. v2.0.0 onwards is
Claude-only (Codex / Gemini / Cursor support was dropped after v1.x).

See DESIGN.md (architecture) and FEATURES.md (feature inventory)
for the canonical specification.

Sections (search by header):
  Section 1: Constants & Paths
  Section 2: JSON I/O
  Section 3: Settings (single-scope read/write)
  Section 4: Plugin / Marketplace / Skill / MCP / Hooks / Commands / Agents
  Section 5: Vault
  Section 6: Usage Parsers (Claude)
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
from typing import Any, Callable, Optional, TypeVar

__version__ = "2.0.0"

T = TypeVar("T")


# ── Section 1: Constants & Paths ─────────────────────────────────────────────
#
# Mirrors src/core/paths.ts. Honors `CLAUDE_CONFIG_DIR` and the Windows
# %APPDATA% fallback for the axt user-config dir.

IS_WINDOWS = sys.platform == "win32"

HOME = Path.home()


def _env_dir(env_var: str, default: Path) -> Path:
    """Read a path env var; fall back to `default` when unset or empty."""
    value = os.environ.get(env_var)
    return Path(value) if value else default


CLAUDE_DIR: Path = _env_dir("CLAUDE_CONFIG_DIR", HOME / ".claude")


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
# read by Claude Code; a partial write must never be observable.


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


def _active_plugins() -> list[PluginInfo]:
    """Plugins that are both installed AND enabled in user settings.

    Reads from the module-level ``PATHS`` so it stays in sync with
    ``monkeypatch.setattr("axt.PATHS", ...)`` in tests. Used by both the
    CLI (``cli_mcp_list`` / ``cli_mcp_info``) and the TUI (Extensions tab's
    mcp sub-tab loader).
    """
    plugins = list_installed_plugins(PATHS.installed_plugins)
    enabled = read_enabled_plugins(PATHS.settings)
    return [p for p in plugins if enabled.get(p.id) is True]


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

from datetime import datetime, timedelta, timezone

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
# Claude usage normalized into `UnifiedUsageEntry`:
#   Claude — JSONL per session under ~/.claude/projects/<proj>/<session>.jsonl
#            with mtime-based per-file cache at ~/.config/axt/cache/claude-usage.json
#
# Cache:
#   Claude per-file mtime cache (5-min validity).


# ─── Unified usage entry & rate limit ────────────────────────────────────────


PLATFORMS: tuple[str, ...] = ("claude",)


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
    """YYYY-MM-DD prefix compare (10-char string slice)."""
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


def _unified_to_claude(e: UnifiedUsageEntry) -> ClaudeUsageEntry:
    """Inverse of :func:`claude_to_unified` — adapter for aggregators
    (``aggregate_daily``, ``aggregate_by_session``, ``compute_blocks``)
    that operate on the Claude shape. Used by the CLI usage subcommands
    and the TUI Usage tab.
    """
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


def load_unified_usage(
    *,
    claude_projects_dir: os.PathLike[str] | str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    project: Optional[str] = None,
    force_refresh: bool = False,
) -> list[UnifiedUsageEntry]:
    """Load Claude usage, normalize to UnifiedUsageEntry, and sort by ts."""
    entries: list[UnifiedUsageEntry] = []
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


def _today_in_tz(tz: str) -> str:
    """Today's date (YYYY-MM-DD) in `tz`. Falls back to UTC on errors."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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
# Pricing lives in `pricing.json` (shipped as package data next to this
# module) so updates don't require source edits. Looked up by exact model
# id with a `startswith` fallback for versioned model strings
# ("gpt-5-2026-01-01" → "gpt-5").


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


_PRICING_FILE = Path(__file__).resolve().parent / "pricing.json"
_PRICING_CACHE: Optional[dict[str, ModelPricing]] = None


def _pricing_table() -> dict[str, ModelPricing]:
    """Lazy-load pricing.json (shipped as package data next to this module)."""
    global _PRICING_CACHE
    if _PRICING_CACHE is not None:
        return _PRICING_CACHE
    data = read_json(_PRICING_FILE, fallback={"models": {}})
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
        p = _plan_from_json(saved_plans.get("claude"))
        if p is not None:
            plans["claude"] = p
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


# ── Section 10: CLI Commands (argparse) — moved to axt/cli.py ───────────────
#
# The argparse tree, `cli_*` handlers, and `main` live in axt/cli.py. The
# shared color/format helpers below are referenced by both the CLI module
# (via ``from axt._core import *``) and by the TUI sections that follow,
# so they stay here in _core.


# ─── Color helpers (shared by CLI + TUI) ─────────────────────────────────────


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


# ─── Formatting helpers (shared by CLI + TUI) ────────────────────────────────


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


# ── Sections 11-14: TUI helpers, widgets, tabs, main loop ──────────────────
#
# Sections 11-12 → axt/tui/widgets.py
# Section 13    → axt/tui/tabs.py
# Section 14    → axt/tui/loop.py
#
# After C5 those modules no longer need anything mirrored back into _core,
# so the transitional re-import shims that used to live here are gone.
# Anything tests reach via ``axt.<name>`` is provided by the package-level
# mirror in :mod:`axt/__init__.py`, which walks the submodules in order.


# ── Section 15: Entry Point — moved to axt/cli.py (main()) ─────────────────
