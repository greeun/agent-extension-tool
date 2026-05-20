# axt — Agent eXtension Tool

A unified CLI & TUI dashboard for managing extensions, plugins, skills, MCP servers, and tracking usage costs across multiple AI agent platforms (Claude Code, Codex, Gemini CLI, Cursor).

## Features

- **Multi-Platform Usage Tracking** — Monitor token usage and costs for Claude Code, OpenAI Codex, Google Gemini CLI, and Cursor IDE in one place
- **Plugin Management** — Install, enable/disable, update, and remove plugins from marketplace registries
- **Skill Management** — Discover and manage skills from user, project, and plugin sources
- **Agent Discovery** — Browse agents across user, project, and plugin directories
- **Marketplace System** — Register GitHub repos, git URLs, or local directories as plugin marketplaces
- **Interactive TUI** — Full-featured terminal dashboard with keyboard-driven navigation
- **Cost Projections** — Budget tracking with daily trends, billing block analysis, and currency conversion (USD/KRW)

## Installation

Requires [Bun](https://bun.sh) runtime and [Git](https://git-scm.com).

### macOS / Linux

```bash
# 1. Install Bun (skip if already installed)
curl -fsSL https://bun.sh/install | bash

# 2. Clone and install
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool
bun install

# 3. Register the `axt` command globally
bun link

# 4. Verify
axt --version
which axt
```

`bun link` registers this directory as the source for the `axt` bin defined in `package.json`. The global shim lives under Bun's bin directory (typically `~/.bun/bin/axt`) — make sure that directory is on your `PATH`.

### Windows

Requires [Windows Terminal](https://aka.ms/terminal) (recommended) and Bun for Windows.

```powershell
# 1. Install Bun
powershell -c "irm bun.sh/install.ps1 | iex"

# 2. Clone and install
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool
bun install

# 3. Link globally
bun link

# 4. Verify
axt --version
```

> **Note:** On Windows, `axt skill link` / `unlink` commands are not available (symlinks require elevated privileges). All other features work normally.

### Updating

```bash
cd agent-extension-tool
git pull
bun install
# `bun link` does not need to be re-run — the global shim points at this directory.
```

## Uninstall

`axt` itself is just a `bun link` shim plus a cloned repo, so removing it is two steps. User data created by `axt` (config, vault) lives in separate paths and is preserved unless you delete it explicitly.

### macOS / Linux

```bash
# 1. Remove the global `axt` shim
#    Run from inside the cloned repo so bun knows which package to unlink:
cd agent-extension-tool
bun unlink

# 2. Delete the cloned source
cd ..
rm -rf agent-extension-tool

# 3. Verify the command is gone
command -v axt   # should print nothing
```

### Windows (PowerShell)

```powershell
cd agent-extension-tool
bun unlink

cd ..
Remove-Item -Recurse -Force agent-extension-tool

Get-Command axt -ErrorAction SilentlyContinue   # should return nothing
```

### Removing user data (optional)

`axt` reads from each agent platform's own directories (`~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.cursor/`) — **do not delete those**, they belong to those CLIs.

The only paths `axt` writes to are its own:

| Path | What it is | Safe to delete? |
|------|-----------|-----------------|
| `~/.config/axt/config.json` (macOS/Linux) | axt user config | Yes |
| `%APPDATA%\axt\config.json` (Windows) | axt user config | Yes |
| `~/.claude/vault/` | axt vault store (created by `axt vault`) | Only if you don't use vault |
| `<project>/.axt-profile.json` | per-project vault profile | Only if you don't use vault |

```bash
# Wipe axt-only config (macOS/Linux)
rm -rf ~/.config/axt

# Wipe vault data — irreversible
rm -rf ~/.claude/vault
```

## Quick Start

```bash
# Launch interactive TUI dashboard
axt tui

# Or use CLI commands directly
axt usage today
axt plugin list
axt skill list
axt market list
```

## CLI Commands

### Usage Tracking

```bash
axt usage today                     # Today's usage summary
axt usage week                      # Weekly breakdown
axt usage month                     # Monthly cost with budget comparison
axt usage blocks                    # 5-hour billing block report
axt usage session <id>              # Specific session details

# Options
--platform claude|codex|gemini|all  # Filter by platform
--since 2025-01-01                  # Start date
--json / --csv                      # Export format
```

### Plugin Management

```bash
axt plugin list                     # List installed plugins
axt plugin enable <id>              # Enable a plugin
axt plugin disable <id>             # Disable a plugin
axt plugin info <id>                # Show plugin metadata
axt plugin remove <id>              # Uninstall a plugin
axt plugin search <query>           # Search across marketplaces
```

### Skill Management

```bash
axt skill list                      # List all skills
axt skill link <path>               # Link a skill directory (macOS/Linux only)
axt skill unlink <name>             # Unlink a skill (macOS/Linux only)
```

### Marketplace

```bash
axt market list                     # Show registered marketplaces
axt market add github:user/repo     # Add GitHub marketplace
axt market add git:<url>            # Add git-based marketplace
axt market add dir:/local/path      # Add local directory
axt market sync [name]              # Sync marketplace(s)
axt market remove <name>            # Remove a marketplace
```

### MCP Servers

```bash
axt mcp list                        # List MCP servers from active plugins
axt mcp info <name>                 # Show server configuration
```

### Plan Management

```bash
axt plan                            # Overview across all platforms
axt plan set claude max-5x          # Set plan for a platform
```

## TUI Dashboard

Launch with `axt tui` or just `axt`.

### Main Tabs (1-7)

| # | Tab | Description |
|---|-----|-------------|
| 1 | **Extensions** | Skills, Hooks, Commands, Agents, Plugins, Marketplace |
| 2 | **Project** | CLAUDE.md, settings, and memory files |
| 3 | **Dashboard** | Cross-platform cost overview and projections |
| 4 | **Claude** | Claude Code token usage and costs |
| 5 | **Codex** | OpenAI Codex CLI usage |
| 6 | **Gemini** | Google Gemini CLI usage |
| 7 | **Cursor** | Cursor IDE AI code authorship metrics |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `←` `→` | Switch main tab |
| `1`-`7` | Jump to tab |
| `Tab` | Switch Extensions sub-tab |
| `j` / `k` | Scroll list up/down |
| `r` | Refresh data |
| `?` | Help popup |
| `q` / `Esc` | Quit |

### Extensions Sub-tab Shortcuts

| Sub-tab | Shortcuts |
|---------|-----------|
| Skills | `u` unlink, `l` link (macOS/Linux only) |
| Plugins | `e` enable/disable, `r` remove, `u` update, `i` install, `/` search |
| Marketplace | `s` sync, `r` remove, `a` add |

### Responsive Layout

- Adapts to terminal width: compact tab labels below 100 columns
- Real-time resize handling
- Scroll windowing for long lists (Cursor commits)
- CJK/fullwidth character support in table columns

## Supported Platforms & Models

### Claude Code
- Claude Opus 4.7 / 4.6
- Claude Sonnet 4.6
- Claude Haiku 4.5

### OpenAI Codex
- GPT-5, GPT-5.2, GPT-5.3, GPT-5.4-codex

### Google Gemini
- Gemini 2.5 Pro / Flash / Flash-Lite
- Gemini 3.1 Pro Preview

### Cursor IDE
- AI code authorship tracking via SQLite metrics

## Configuration

Config file:
- macOS / Linux: `~/.config/axt/config.json`
- Windows: `%APPDATA%\axt\config.json`

```json
{
  "currency": ["usd", "krw"],
  "exchangeRate": 1400,
  "monthlyBudget": 100,
  "timezone": "Asia/Seoul",
  "locale": "ko-KR",
  "plans": {
    "claude": { "plan": "max-5x", "monthlyCost": 100 },
    "codex": { "plan": "pro", "monthlyCost": 200 },
    "gemini": { "plan": "free", "monthlyCost": 0 }
  }
}
```

## Data Sources

| Platform | Source Path |
|----------|------------|
| Claude | `~/.claude/projects/{name}/.usage.jsonl` |
| Codex | `~/.codex/sessions/**/*.jsonl` |
| Gemini | `~/.gemini/tmp/*/chats/session-*.json` |
| Cursor | `~/.cursor/ai-tracking/ai-code-tracking.db` |
| Plugins | `~/.claude/plugins/installed_plugins.json` |
| Skills | `~/.claude/skills/` |
| Agents | `~/.claude/agents/` |

## Tech Stack

- **Runtime**: [Bun](https://bun.sh)
- **CLI**: [Commander.js](https://github.com/tj/commander.js)
- **TUI**: [Ink](https://github.com/vadimdemedes/ink) (React for CLI)
- **Language**: TypeScript

## License

MIT
