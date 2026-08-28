---
name: agent-extension-tool
description: Use `axt` (Agent eXtension Tool) — a Python+curses CLI/TUI — to inspect and manage extensions, plugins, skills, MCP servers, hooks, commands, agents, marketplaces, and usage/cost for Claude Code. Trigger phrases — EN ("axt", "list plugins", "install plugin", "list skills", "list MCP", "enable/disable MCP", "show hooks", "enable/disable hook", "list agents", "claude usage", "claude plan", "billing cycle", "marketplace add/sync", "vault list", "link skill", "context analyze", "token usage at session start", "check for updates", "update plugins", "axt update"). KO ("axt", "플러그인 목록", "플러그인 설치", "스킬 목록", "MCP 서버", "MCP 켜기/끄기", "훅 보기", "훅 켜기/끄기", "에이전트 목록", "클로드 사용량", "마켓플레이스", "볼트", "스킬 링크", "컨텍스트 분석", "에이전트 확장 도구", "업데이트 확인", "플러그인 업데이트", "확장 업데이트").
version: 1.15.0
---

# axt — Agent eXtension Tool

`axt` is a Python + curses CLI + TUI package (Claude-only, pure stdlib runtime) that gives a unified view of:

- **Plugins** installed via Claude marketplaces (`~/.claude/plugins/`)
- **Skills** (`~/.claude/skills/`, `~/.agents/`, `<project>/.agents/`, plugin-bundled)
- **MCP servers** declared by plugins or settings
- **Hooks**, **commands**, **agents** discovered across scopes
- **Usage & cost** for Claude with per-model pricing
- **Vault** profiles per project (`.axt-profile.json`) and global `~/.claude/vault/`
- **Marketplace** registry (github / git / dir sources) with version tracking

## When to invoke this skill

Use `axt` when the user asks any of:

- "List / install / remove a plugin", "what plugins do I have?"
- "Show me skills / MCP / hooks / commands / agents"
- "How much have I spent on Claude this month?"
- "What's in the marketplace? Sync it."
- "Link this skill to my project", "vault status"
- "What's my context size at session start?"
- "Switch my plan", "billing cycle status"

## CLI reference

```bash
axt                           # launch TUI (default)
axt tui
axt --theme {auto,dark,light} # TUI color theme for this run (top-level flag)

axt market   {list, add <source>, sync [name], remove <name>}
axt plugin   {list, enable <id> [--scope global|project], disable <id> [--scope ...], info <id>, remove <id>, search <q>}
axt skill    {list, link <path> [-n <name>], unlink <name>}    # link/unlink hidden on Windows
axt mcp      {list, info <name>, enable <name>, disable <name>}
axt hook     {list, enable <index>, disable <index>}
axt usage    [today | week | month | blocks [--active] | session <id>]
             [--since YYYY-MM-DD] [--until YYYY-MM-DD]
             [--model <id>] [--project <name>]
             [--json]   # today, week only
             [--csv]    # week only
axt plan     [overview | set <plan-name|auto>]
axt project  {init, add <type> <name>..., remove <type> <name>, sync, status}
axt context  [--detail] [--json] [--category <name>] [--model <id>]
axt vault    {list, migrate, add <path> [-t <type>], install <market> <name> [-t <type>],
              link-global <type> <name>, unlink-global <type> <name>}
```

Marketplace source formats: `github:user/repo`, `git:<url>`, `dir:/path`.

Full inventory: see `FEATURES.md` in this repo.

## Operating principles

1. **Inspection is safe.** `list`, `info`, `status`, `analyze` only read — run them freely.
2. **Mutation needs confirmation.** `add`, `remove`, `enable`, `disable`, `install`, `link`, `unlink`, `sync`, `migrate`, `set` touch `~/.claude/`, marketplace clones, and project files. Confirm with the user before running.
3. **TUI for exploration.** Suggest `axt` (no args) when the user wants to browse.
4. **JSON for piping.** Many commands accept `--json` for scripting; prefer this when feeding output into another tool.

## Data boundaries

`axt` writes only to:

| Path | Purpose |
|------|---------|
| `~/.config/axt/config.json` (macOS/Linux) / `%APPDATA%\axt\config.json` (Windows) | axt user config (plan selection, etc.) |
| `~/.claude/vault/` | vault store, only when the user runs `axt vault` commands |
| `<project>/.axt-profile.json` | per-project vault link tracking |

`axt` reads from `~/.claude/` and does **not** modify it outside of explicit user-invoked mutations (plugin enable/disable, marketplace add, vault link, etc.). Treat `~/.claude/` as belonging to Claude Code.

## Architecture pointer

Python package `axt/` (Phase C split the original single-file `axt.py` into per-section modules; `# ── Section N:` headers survive as in-module anchors):

- `core.py` — Sections 1-9, domain layer (paths, JSON I/O, settings, plugin / skill / MCP / hook / command / agent, vault, marketplace, usage parsers, pricing, context, project usage)
- `cli.py` — Section 10 + 15, argparse subcommands + `main` entry
- `pricing.json` — per-million-token model pricing (package data; edit to add a model, no code change)
- `tui/widgets.py` (11-12), `tui/tabs.py` (13), `tui/loop.py` (14) — curses helpers, tab renderers/handlers, main loop

`axt/__init__.py` mirrors each submodule's globals onto the `axt` namespace, so `axt.X` resolves regardless of which module owns `X`. See `DESIGN.md` for the cst-style rewrite + Phase-C package-split rationale.

Pure stdlib runtime — no external Python deps. Windows users additionally need `windows-curses`.

## How to verify availability

```bash
axt --version    # expect: axt 1.5.0 or later
```

If missing, install per `README.md` (clone + `pip install -e .[dev]`).
