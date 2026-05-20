---
name: agent-extension-tool
description: Use `axt` (Agent eXtension Tool) — a Python+curses CLI/TUI — to inspect and manage extensions, plugins, skills, MCP servers, hooks, commands, agents, marketplaces, and usage/cost across Claude Code, Codex, Gemini CLI, and Cursor. Trigger phrases — EN ("axt", "list plugins", "install plugin", "list skills", "list MCP", "show hooks", "list agents", "claude/codex/gemini/cursor usage", "claude plan", "billing cycle", "marketplace add/sync", "vault list", "link skill", "context analyze", "token usage at session start"). KO ("axt", "플러그인 목록", "플러그인 설치", "스킬 목록", "MCP 서버", "훅 보기", "에이전트 목록", "클로드 사용량", "코덱스 사용량", "제미니 사용량", "커서 사용량", "마켓플레이스", "볼트", "스킬 링크", "컨텍스트 분석", "에이전트 확장 도구").
---

# axt — Agent eXtension Tool

`axt` is a single-file Python CLI + curses TUI (v1.0.0) that gives a unified view of:

- **Plugins** installed via Claude marketplaces (`~/.claude/plugins/`)
- **Skills** (`~/.claude/skills/`, `~/.agents/`, `<project>/.agents/`, plugin-bundled)
- **MCP servers** declared by plugins or settings
- **Hooks**, **commands**, **agents** discovered across scopes
- **Usage & cost** for Claude / Codex / Gemini / Cursor with per-model pricing
- **Vault** profiles per project (`.axt-profile.json`) and global `~/.claude/vault/`
- **Marketplace** registry (github / git / dir sources) with version tracking

## When to invoke this skill

Use `axt` when the user asks any of:

- "List / install / remove a plugin", "what plugins do I have?"
- "Show me skills / MCP / hooks / commands / agents"
- "How much have I spent on Claude / Codex / Gemini / Cursor this month?"
- "What's in the marketplace? Sync it."
- "Link this skill to my project", "vault status"
- "What's my context size at session start?"
- "Switch my plan", "billing cycle status"

## CLI reference

```bash
axt                           # launch TUI (default)
axt tui

axt market   {list, add <source>, sync [name], remove <name>}
axt plugin   {list, enable <id>, disable <id>, info <id>, remove <id>, search <q>}
axt skill    {list, link <path>, unlink <name>}
axt mcp      {list, info <name>}
axt usage    [today | week | month | blocks | session <id>]
             [--platform claude|codex|gemini|cursor|all]
             [--since YYYYMMDD] [--until YYYYMMDD]
             [--model <id>] [--project <name>] [--breakdown]
             [--json | --csv | --export <path>]
axt plan     [overview | set <platform> <plan-name>]
axt project  {init, add <type> <name>..., remove <type> <name>, sync, status}
axt context  {analyze, list} [--detail] [--json] [--category <name>] [--model <id>]
axt vault    {list, migrate, add <type> <name>, install, link-global, unlink-global}
```

Marketplace source formats: `github:user/repo`, `git:<url>`, `dir:/path`.

Full inventory: see `FEATURES.md` in this repo (44 subcommands, 8 main TUI tabs, 9 Extensions sub-tabs).

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

`axt` reads from each platform's own directories (`~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.cursor/`) and does **not** modify them. Treat those as belonging to the platform CLIs.

## Architecture pointer

Single file `axt.py` (~7,400 lines) organized into 15 numbered sections (Constants → JSON I/O → Settings → domain → Vault → Usage parsers → Pricing → Context analysis → Project usage index → CLI → TUI helpers/widgets/tabs/main loop → Entry point). See `DESIGN.md` for the cst-style single-file rationale.

Pure stdlib runtime — no external Python deps. Windows users additionally need `windows-curses`.

## How to verify availability

```bash
axt --version    # expect: axt 1.0.0 or later
```

If missing, install per `README.md` (clone + `pip install -e .[dev]`).
