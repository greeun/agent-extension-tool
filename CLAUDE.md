# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Communication

- 항상 한글로 답변할 것. 코드와 CLI 출력은 영어 그대로 유지.

## What is this project?

**axt** (Agent eXtension Tool) is a CLI + TUI dashboard that manages extensions, plugins, skills, MCP servers, and usage-cost tracking across multiple AI agent platforms (Claude Code, Codex, Gemini CLI, Cursor). It reads data from each platform's local files (`~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.cursor/`) and presents a unified view.

## Commands

```bash
bun install          # Install dependencies
bun run dev          # Run CLI in dev mode (same as: bun run bin/axt.ts)
bun test             # Run all tests (uses bun:test)
bun test tests/core/plugin.test.ts   # Run a single test file
bun run typecheck    # TypeScript type checking (tsc --noEmit)
```

The entry point is `bin/axt.ts` which delegates to Commander (CLI) or Ink (TUI).

## Architecture

```
bin/axt.ts              → Entry point (shebang: #!/usr/bin/env bun)
src/cli/                → Commander command registrations (one file per command group)
  context.ts            → context analyze/list commands
  market.ts             → marketplace add/remove/list/sync
  mcp.ts                → MCP server list
  plan.ts               → subscription plan info
  plugin.ts             → plugin install/remove/list
  project.ts            → project context/usage commands
  skill.ts              → skill link/unlink/list
  usage.ts              → usage summary/detail per platform
  vault.ts              → vault list/link/unlink/sync/migrate/import
src/core/               → Business logic, platform-agnostic
  agents.ts             → List agents across platforms
  cache.ts              → Usage data caching with mtime-based invalidation
  commands.ts           → Discover slash commands from settings
  context-analysis.ts   → Token estimation, context source collection, impact analysis
  hooks.ts              → List/preview hooks from settings files
  json-io.ts            → readJson / writeJsonAtomic helpers
  marketplace.ts        → Marketplace registry CRUD
  mcp.ts                → MCP server discovery
  paths.ts              → Platform path constants (env overrides, Windows support)
  plugin.ts             → Plugin install/remove/list
  project-context.ts    → Project-level CLAUDE.md, .mdc, settings aggregation
  project-usage.ts      → Scan which projects use each extension
  rate-limits.ts        → Read rate-limit headers from usage data
  settings.ts           → Multi-scope settings reader (global/project)
  skill.ts              → Skill discovery and symlink management
  types.ts              → Shared TypeScript types
  usage.ts              → Claude usage loader
  usage-codex.ts        → Codex usage loader
  usage-cursor.ts       → Cursor usage loader
  usage-gemini.ts       → Gemini usage loader
  usage-unified.ts      → Unified usage adapter (UnifiedUsageEntry)
  vault.ts              → Vault profile, link/unlink, sync, migrate, import
src/tui/                → Ink (React-for-CLI) components
  App.tsx               → Root component, tab routing, keyboard handling
src/tui/tabs/           → One component per TUI tab
  ExtensionsTab.tsx     → Plugins/Skills/MCP/Hooks/Commands/Agents sub-tabs
  ContextTab.tsx        → Context source analysis with token/size breakdown
  ProjectTab.tsx        → Project-level context items
  OverviewTab.tsx       → Dashboard overview
  UsageTab.tsx          → Per-platform usage (claude/codex/gemini)
  CursorTab.tsx         → Cursor-specific usage view
  VaultTab.tsx          → Vault items with search, sort, detail, import
  PluginsTab.tsx        → Plugin list sub-tab (within Extensions)
  SkillsTab.tsx         → Skill list sub-tab (within Extensions)
  McpTab.tsx            → MCP server sub-tab (within Extensions)
  HooksTab.tsx          → Hooks sub-tab (within Extensions)
  CommandsTab.tsx       → Commands sub-tab (within Extensions)
  AgentsTab.tsx         → Agents sub-tab (within Extensions)
  ManageTab.tsx         → Marketplace management sub-tab
  MarketTab.tsx         → Marketplace browse sub-tab
src/tui/components/     → Shared TUI primitives
  Table.tsx             → Sortable, selectable table with column definitions
  TabBar.tsx            → Top-level tab bar (8 tabs: Extensions/Context/Project/Dashboard/Claude/Codex/Gemini/Cursor)
  DetailPanel.tsx       → Right-side detail panel for selected row
  DetailView.tsx        → Full-width detail overlay
  PreviewPanel.tsx      → Preview panel for vault/context items
  HelpPopup.tsx         → ? key help overlay
  SearchInput.tsx       → / key inline search
  BarChart.tsx          → ASCII bar chart for usage data
  SourceSummary.tsx     → Context source summary display
  Confirm.tsx           → y/n confirmation prompt
src/tui/wizards/        → Multi-step interactive flows (Install/Remove)
src/config/             → User config loading (~/.config/axt/config.json)
src/pricing/            → Token pricing tables and cost calculation
src/plans/              → Subscription plan definitions
tests/                  → Mirrors src/ structure; uses bun:test with fixtures
```

### Key design patterns

- **Path constants** are centralized in `src/core/paths.ts` (supports `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GEMINI_CLI_HOME` env overrides and Windows `%APPDATA%`).
- **JSON I/O** uses `src/core/json-io.ts` with `readJson(path, { fallback })` and `writeJsonAtomic(path, data)` — all file mutations go through atomic writes.
- **Usage data** flows: platform-specific loaders (`usage.ts`, `usage-codex.ts`, `usage-gemini.ts`, `usage-cursor.ts`) → unified adapter (`usage-unified.ts`) → `UnifiedUsageEntry` type. Cached via `cache.ts` with mtime-based invalidation.
- **Pricing** is a static lookup table in `src/pricing/models.ts` mapping model IDs to per-million-token costs. Cost = tokens × rate. Add new models there.
- **Plugin system** tracks installs in `~/.claude/plugins/installed_plugins.json` and marketplaces in `~/.claude/plugins/known_marketplaces.json`. Marketplace sources: `github:user/repo`, `git:<url>`, `dir:/path`.
- **Vault system** manages extension profiles in `.axt-profile.json` per project. Global vault lives in `~/.claude/vault/`. Supports link/unlink, sync, migrate, and import operations.
- **Context analysis** collects all context sources (CLAUDE.md, .mdc rules, settings, MCP configs) and estimates token usage per source.
- **TUI state** lives in the top-level `App.tsx` component with tab routing; each tab is self-contained and fetches its own data on mount/refresh. The Extensions tab has nested sub-tabs (Plugins/Skills/MCP/Hooks/Commands/Agents/Manage/Market).
- **Settings** are read from multiple scopes (global `~/.claude/settings.json`, project `.claude/settings.json`) and merged via `src/core/settings.ts`.

### CLI command groups

| Command | Description |
|---------|-------------|
| `axt` (no args) | Launch TUI dashboard |
| `axt market` | Marketplace add/remove/list/sync |
| `axt plugin` | Plugin install/remove/list |
| `axt skill` | Skill link/unlink/list |
| `axt mcp` | MCP server list |
| `axt usage` | Usage summary per platform |
| `axt plan` | Subscription plan info |
| `axt context` | Context source analysis |
| `axt vault` | Vault list/link/unlink/sync/migrate/import |
| `axt project` | Project context/usage info |

### Platform differences

- Windows: `skill link`/`unlink` commands are disabled (symlinks need elevated privileges).
- All path resolution uses `process.platform === "win32"` checks in `paths.ts`.

## TypeScript configuration

- Target: ES2022, module: ES2022, JSX: react-jsx
- Path aliases: `@core/*`, `@cli/*`, `@tui/*`, `@pricing/*`, `@config/*`
- Strict mode enabled
