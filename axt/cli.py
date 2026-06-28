"""axt CLI — argparse subcommands.

Section 10 of the original monolith (plus the Section 15 ``main`` entry
point). All CLI subcommand handlers, the argparse tree builder, ANSI
color helpers, and console-output formatters live here.

The module relies on a wildcard import from :mod:`axt.core` so handlers
keep using bare symbol names (``PATHS``, ``load_config``, ``ContextSource``,
…) the way they did when this code shared one big namespace. The
``axt/__init__.py`` mirror loop ensures the same symbols are reachable
as ``axt.<name>`` so tests can still ``monkeypatch.setattr("axt.PATHS", …)``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Wildcard import: this module is a logical continuation of core.py
# (sharing its module-level constants and domain helpers). Explicit
# imports here would require listing ~80 names and would re-break every
# time core grows a new public symbol. Wildcard mirrors the legacy
# single-namespace behavior; the package-level mirror in
# axt/__init__.py keeps `axt.<name>` lookups working.
from axt.core import *  # noqa: F401,F403

# Underscore-prefixed names are skipped by `import *`; pull them in
# explicitly so handlers can use them.
from axt.core import (  # noqa: F401
    _active_plugins,
    _date_in_tz,
    _today_in_tz,
    _unified_to_claude,
    HOME,
    PATHS,
    AXT_CONFIG_PATH,
    CATEGORY_LABELS,
    __version__,
)


# Color / formatting helpers (``_red``, ``format_tokens``, ``render_bar``,
# ``budget_bar``, …) are defined in :mod:`axt.core` because the curses
# TUI uses them too. They land in this module via the wildcard import
# above and the explicit re-exports below for legibility / IDE support.
from axt.core import (  # noqa: F401
    _bold, _c, _color_enabled, _cyan, _dim, _green, _red, _yellow,
    C_BOLD, C_CYAN, C_DIM, C_GRAY, C_GREEN, C_RED, C_RESET, C_YELLOW,
    budget_bar, format_cost, format_tokens, render_bar,
)

# TUI entry — used by ``cli_tui`` and as the default action when ``main``
# runs with no args. Lives in :mod:`axt.tui.loop` after C5.
from axt.tui.loop import launch_tui, HELP_TEXT  # noqa: F401


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
        model=args.model or detect_current_model(project_dir=Path.cwd()),
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

def _print_list_header(header: str, width: int) -> None:
    """Bold column header followed by a horizontal rule — the opening of every
    `axt … list` table."""
    print(_bold(header))
    print("─" * width)


def _print_count_footer(n: int, noun: str, suffix: str = "") -> None:
    """Blank line then a `<n> <noun>(s)<suffix>` count — the closing of every
    `axt … list` table."""
    print(f"\n {n} {noun}(s){suffix}")


def cli_market_list(args) -> int:
    items = list_marketplaces(PATHS.known_marketplaces)
    if not items:
        print("No marketplaces registered.")
        return 0
    _print_list_header(f"{'Name'.ljust(28)} {'Current'.ljust(10)} {'Latest'.ljust(10)} {'Source'.ljust(28)} Updated", 90)
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
    _print_count_footer(len(items), "marketplace")
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
# (_active_plugins moved to axt/core.py near plugin code so the curses
# TUI in axt/tui/tabs.py can reach it too. It is re-exported here via the
# wildcard `from axt.core import *` at the top of this module.)


def _mcp_detail(server) -> str:
    """One-line transport detail: URL for remote, command line for stdio."""
    if server.url:
        return server.url
    return " ".join([server.command, *server.args_list]).strip()


def cli_mcp_list(args) -> int:
    servers = collect_mcp_servers(_active_plugins())
    if not servers:
        print("No MCP servers found.")
        return 0
    _print_list_header(f" {'Server'.ljust(24)} {'Scope'.ljust(13)} {'Transport'.ljust(10)} Detail", 78)
    for s in servers:
        flag = _red(" [disabled]") if s.disabled else ""
        print(f" {s.name.ljust(24)} {s.scope.ljust(13)} {s.transport.ljust(10)} {_mcp_detail(s)}{flag}")
    _print_count_footer(len(servers), "MCP server")
    return 0


def cli_mcp_info(args) -> int:
    servers = collect_mcp_servers(_active_plugins())
    server = next((s for s in servers if s.name == args.name), None)
    if not server:
        print(_red(f'MCP server "{args.name}" not found.'))
        return 1
    print(_bold(server.name))
    print(f"Scope: {server.scope}")
    print(f"Transport: {server.transport}")
    if server.plugin_id:
        print(f"Plugin: {server.plugin_id}")
    if server.transport == "stdio":
        print(f"Command: {server.command} {' '.join(server.args_list)}".rstrip())
        if server.env_dict:
            print(f"Env: {json.dumps(server.env_dict)}")
    elif server.url:
        print(f"URL: {server.url}")
    if server.disabled:
        print(_red("Disabled in current project"))
    return 0


def cli_mcp_enable(args) -> int:
    set_mcp_disabled(args.name, disabled=False)
    print(_green(f'✓ MCP "{args.name}" enabled (project). Restart Claude Code to apply.'))
    return 0


def cli_mcp_disable(args) -> int:
    set_mcp_disabled(args.name, disabled=True)
    print(_yellow(f'○ MCP "{args.name}" disabled (project). Restart Claude Code to apply.'))
    return 0


# hook


def _cli_hooks() -> list:
    return list_hooks(
        user_settings_path=PATHS.settings,
        project_dir=Path.cwd(),
        installed_plugins_path=PATHS.installed_plugins,
    )


def cli_hook_list(args) -> int:
    hooks = _cli_hooks()
    if not hooks:
        print("No hooks found.")
        return 0
    _print_list_header(f" {'#'.ljust(3)} {'Event'.ljust(20)} {'Matcher'.ljust(12)} {'Type'.ljust(9)} {'Source'.ljust(8)} Detail", 78)
    for i, h in enumerate(hooks):
        flag = _red(" [off]") if h.disabled else ""
        print(f" {str(i).ljust(3)} {h.event.ljust(20)} {(h.matcher or '*').ljust(12)} {h.type.ljust(9)} {h.source.ljust(8)} {get_hook_detail(h)[:40]}{flag}")
    _print_count_footer(len(hooks), "hook")
    print(_dim(" Toggle by index from this list: axt hook disable <#> / axt hook enable <#>"))
    return 0


def _resolve_hook(index: int):
    hooks = _cli_hooks()
    if index < 0 or index >= len(hooks):
        return None, hooks
    return hooks[index], hooks


def _cli_hook_toggle(args, *, disabled: bool) -> int:
    hook, hooks = _resolve_hook(args.index)
    if hook is None:
        upper = len(hooks) - 1
        print(_red(f"Hook index {args.index} out of range (0..{upper})." if hooks else "No hooks found."))
        return 1
    verb = "disabled" if disabled else "enabled"
    if hook.disabled == disabled:
        print(_dim(f"Hook {args.index} ({hook.event}) already {verb}."))
        return 0
    if hook.source == "plugin":
        print(_red("Plugin hooks are read-only; manage them in the plugin itself."))
        return 1
    if set_hook_disabled(hook.source_path, hook, disabled=disabled):
        glyph = _yellow("○") if disabled else _green("✓")
        print(f"{glyph} Hook {args.index} ({hook.event}) {verb}. Restart Claude Code to apply.")
        return 0
    print(_red("Hook not found in its settings file (it may have changed)."))
    return 1


def cli_hook_enable(args) -> int:
    return _cli_hook_toggle(args, disabled=False)


def cli_hook_disable(args) -> int:
    return _cli_hook_toggle(args, disabled=True)


# plan

def cli_plan_overview(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    now = datetime.now()
    month_start = f"{now.year}-{now.month:02d}-01"
    entries = load_unified_usage(
        claude_projects_dir=PATHS.projects,
        since=month_start,
    )
    plan_cfg = resolve_claude_plan(config)
    if not plan_cfg:
        print("No plan configured for Claude.")
        return 0
    detected = config.auto_detect_plan and detect_claude_plan() is not None
    cost = 0.0
    for e in entries:
        cost += calculate_cost(
            TokenUsage(
                input_tokens=e.input_tokens,
                output_tokens=e.output_tokens,
                cache_creation_tokens=e.cache_write_tokens,
                cache_read_tokens=e.cache_read_tokens,
            ),
            e.model,
        )
    elapsed, total_days = get_days_in_billing_period(plan_cfg.billing_cycle_start, now.replace(tzinfo=timezone.utc))
    usage = compute_plan_usage(plan_cfg, cost, elapsed, total_days)
    suffix = " · auto-detected" if detected else ""
    label = f"Claude ({plan_cfg.plan} — ${plan_cfg.monthly_cost}/mo{suffix})"
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
    print(_bold(f"Total: {format_cost(cost, config.exchange_rate)}"))
    return 0


def cli_plan_set(args) -> int:
    config = load_config(AXT_CONFIG_PATH)

    # `axt plan set auto` re-enables auto-detection from ~/.claude.json.
    if args.plan_name.lower() == "auto":
        save_config(AXT_CONFIG_PATH, replace(config, auto_detect_plan=True))
        found = detect_claude_plan()
        if found:
            print(_green(f'✓ Auto-detect enabled — Claude plan is "{found[0]}" (${found[1]}/mo).'))
        else:
            print(_green("✓ Auto-detect enabled (no plan detected in ~/.claude.json yet)."))
        return 0

    plans = dict(config.plans)
    existing = plans.get("claude")
    # Use the standard tier price for a recognized plan; else keep the prior
    # cost (or 0 for a brand-new entry).
    parsed = parse_rate_limit_tier(args.plan_name)
    cost = parsed[1] if parsed else (existing.monthly_cost if existing else 0.0)
    plans["claude"] = PlanConfig(
        plan=args.plan_name,
        monthly_cost=cost,
        billing_cycle_start=existing.billing_cycle_start if existing else 1,
        daily_request_limit=existing.daily_request_limit if existing else None,
    )
    # Manual set pins the plan: turn off auto-detect so it is not overridden.
    save_config(AXT_CONFIG_PATH, replace(config, plans=plans, auto_detect_plan=False))
    print(_green(f'✓ Claude plan set to "{args.plan_name}" (auto-detect off — use `axt plan set auto` to re-enable).'))
    return 0


# plugin

def cli_plugin_list(args) -> int:
    plugins = list_installed_plugins(PATHS.installed_plugins)
    enabled_g = read_enabled_plugins(PATHS.settings)
    enabled_p = read_enabled_plugins(project_settings_path())
    if not plugins:
        print("No plugins installed.")
        return 0
    _print_list_header(f" {'Plugin'.ljust(30)} {'Version'.ljust(10)} {'G/P'.ljust(7)} Marketplace", 75)
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
    _print_list_header(f" {'Name'.ljust(30)} {'Type'.ljust(10)} Path", 70)
    for s in skills:
        type_str = _cyan("symlink") if s.is_symlink else _dim("dir")
        path_str = f"→ {s.target}" if s.is_symlink else s.path
        print(f" {s.name.ljust(30)} {type_str.ljust(19)} {path_str}")
    _print_count_footer(len(skills), "skill")
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
# (_unified_to_claude and _today_in_tz moved to axt/core.py so the curses
# TUI in axt/tui/tabs.py can reach them too. Both are re-exported here via
# the wildcard `from axt.core import *` at the top of this module.)


def _shared_usage_load(args, *, since: Optional[str] = None, until: Optional[str] = None) -> list[UnifiedUsageEntry]:
    """Apply usage-group filter flags (model/project/timezone)."""
    entries = load_unified_usage(
        claude_projects_dir=PATHS.projects,
        since=since,
        until=until,
        project=args.project,
    )
    if args.model:
        entries = [e for e in entries if args.model in e.model]
    return entries


def _load_usage_entries(
    args, *, since: Optional[str] = None, until: Optional[str] = None
) -> list[ClaudeUsageEntry]:
    """Filter-load usage then adapt unified→claude — the shared opening of every
    `axt usage` subcommand."""
    return [_unified_to_claude(e) for e in _shared_usage_load(args, since=since, until=until)]


def _entries_cost(entries: list[ClaudeUsageEntry]) -> float:
    """Total USD cost across `entries` via the pricing table."""
    return sum(
        calculate_cost(
            TokenUsage(e.input_tokens, e.output_tokens, e.cache_creation_tokens, e.cache_read_tokens),
            e.model,
        )
        for e in entries
    )


def cli_usage_today(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    tz = args.timezone or config.timezone
    today = _today_in_tz(tz)
    entries = _load_usage_entries(args, since=today, until=today)
    if not entries:
        print("No usage data for today.")
        return 0
    daily = aggregate_daily(entries, tz)
    d = daily[0]
    cost = _entries_cost(entries)
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
    entries = _load_usage_entries(args, since=since, until=until)
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
    return _entries_cost([e for e in entries if _date_in_tz(e.timestamp, tz) == date])


def cli_usage_month(args) -> int:
    config = load_config(AXT_CONFIG_PATH)
    tz = args.timezone or config.timezone
    now = datetime.now()
    since = f"{now.year}-{now.month:02d}-01"
    until = _today_in_tz(tz)
    entries = _load_usage_entries(args, since=since, until=until)
    total_cost = _entries_cost(entries)
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
    entries = _load_usage_entries(args, since=since)
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
    entries = [e for e in _load_usage_entries(args) if e.session_id.startswith(args.session_id)]
    if not entries:
        print(_red(f'Session "{args.session_id}" not found.'))
        return 1
    sessions = aggregate_by_session(entries)
    s = sessions[0]
    cost = _entries_cost(entries)
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
    _print_list_header(f"{'Name'.ljust(30)} {'Type'.ljust(10)}", 42)
    for item in items:
        print(f"{item.name.ljust(30)} {_cyan(item.type.ljust(10))}")
    _print_count_footer(len(items), "extension", suffix=" in vault")
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
    cfg = load_config(AXT_CONFIG_PATH)
    theme = resolve_theme(cfg.theme, getattr(args, "theme", None))
    return launch_tui(theme)


# ─── Argparse wiring ─────────────────────────────────────────────────────────


def _add_usage_filter_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--since", help="Start date (YYYY-MM-DD or YYYYMMDD)")
    p.add_argument("--until", help="End date (YYYY-MM-DD or YYYYMMDD)")
    p.add_argument("--model", help="Filter by model")
    p.add_argument("--project", help="Filter by project")
    p.add_argument("--breakdown", action="store_true", help="Show per-model breakdown")
    p.add_argument("--timezone", help="Timezone for grouping")
    p.add_argument("--locale", help="Date locale")
    p.add_argument("--json", action="store_true", help="Output JSON")
    p.add_argument("--csv", action="store_true", help="Output CSV")
    p.add_argument("--export", help="Export to file")


def build_parser() -> argparse.ArgumentParser:
    """Construct the full argparse tree mirroring src/cli/* commander structure."""
    parser = argparse.ArgumentParser(prog="axt", description="Agent eXtension Tool")
    parser.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--theme", choices=("auto", "dark", "light"), default=None,
        help="TUI color theme for this run (default: saved config / auto-detect)",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # tui (also the no-arg default)
    sp_tui = sub.add_parser("tui", help="Open TUI dashboard")
    sp_tui.set_defaults(func=cli_tui)

    # context
    sp_ctx = sub.add_parser("context", help="Analyze session-start context usage")
    sp_ctx.add_argument("--detail", action="store_true", help="Show individual items within categories")
    sp_ctx.add_argument("--json", action="store_true", help="Output as JSON")
    sp_ctx.add_argument("--category", help="Filter by category")
    sp_ctx.add_argument("--model", default=None, help="Model override (default: auto-detect current model)")
    sp_ctx.set_defaults(func=cli_context)

    # market
    sp_mkt = sub.add_parser("market", help="Manage marketplaces").add_subparsers(dest="action", required=True)
    p = sp_mkt.add_parser("list", help="List registered marketplaces"); p.set_defaults(func=cli_market_list)
    p = sp_mkt.add_parser("add", help="Register a marketplace"); p.add_argument("source"); p.set_defaults(func=cli_market_add)
    p = sp_mkt.add_parser("sync", help="Sync marketplace(s) with remote"); p.add_argument("name", nargs="?"); p.set_defaults(func=cli_market_sync)
    p = sp_mkt.add_parser("remove", help="Unregister a marketplace"); p.add_argument("name"); p.set_defaults(func=cli_market_remove)

    # mcp
    sp_mcp = sub.add_parser("mcp", help="View and toggle MCP servers").add_subparsers(dest="action", required=True)
    p = sp_mcp.add_parser("list", help="List MCP servers from active plugins"); p.set_defaults(func=cli_mcp_list)
    p = sp_mcp.add_parser("info", help="Show MCP server details"); p.add_argument("name"); p.set_defaults(func=cli_mcp_info)
    p = sp_mcp.add_parser("enable", help="Enable an MCP server in this project"); p.add_argument("name"); p.set_defaults(func=cli_mcp_enable)
    p = sp_mcp.add_parser("disable", help="Disable an MCP server in this project"); p.add_argument("name"); p.set_defaults(func=cli_mcp_disable)

    # hook
    sp_hook = sub.add_parser("hook", help="View and toggle hooks").add_subparsers(dest="action", required=True)
    p = sp_hook.add_parser("list", help="List hooks with toggle index"); p.set_defaults(func=cli_hook_list)
    p = sp_hook.add_parser("enable", help="Enable a hook by index (from `hook list`)"); p.add_argument("index", type=int); p.set_defaults(func=cli_hook_enable)
    p = sp_hook.add_parser("disable", help="Disable a hook by index (from `hook list`)"); p.add_argument("index", type=int); p.set_defaults(func=cli_hook_disable)

    # plan
    sp_plan = sub.add_parser("plan", help="View plan usage and cost projections")
    plan_sub = sp_plan.add_subparsers(dest="action")
    p = plan_sub.add_parser("overview", help="Claude plan summary"); p.set_defaults(func=cli_plan_overview)
    p = plan_sub.add_parser("set", help="Set Claude plan"); p.add_argument("plan_name"); p.set_defaults(func=cli_plan_set)
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


# ─── Entry point (Section 15 of the original monolith) ───────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point used by `axt = axt:main` in pyproject.toml."""
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()

    # No-arg invocation → launch TUI (matches `axt` with no args).
    if not argv:
        return cli_tui(argparse.Namespace(theme=None))

    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        # Top-level-only invocation (e.g. `axt --theme light`) → launch TUI.
        if getattr(args, "theme", None) is not None:
            return cli_tui(args)
        parser.print_help()
        return 1
    try:
        return func(args) or 0
    except (FileNotFoundError, FileExistsError, KeyError, ValueError, OSError, RuntimeError) as e:
        print(_red(f"✗ {e}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
