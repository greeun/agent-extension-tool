# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Communication

- 항상 한글로 답변할 것. 코드와 CLI 출력은 영어 그대로 유지.

## What is this project?

**axt** (Agent eXtension Tool) is a CLI + TUI dashboard that manages extensions, plugins, skills, MCP servers, hooks, commands, agents, and usage-cost tracking across multiple AI agent platforms (Claude Code, Codex, Gemini CLI, Cursor). It reads data from each platform's local files (`~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.cursor/`) and presents a unified view.

**Primary implementation (v1.0.0+)**: Python + curses, single file `axt.py`. Pure stdlib runtime.

**Frozen legacy**: TypeScript + Ink implementation lives under `legacy-ts/` (v0.1.x line). Read-only — no new development.

## Commands

```bash
# One-time setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# Run
axt                  # launch TUI
axt --help           # CLI help
python3 axt.py       # alternative entry without the script bin

# Test
pytest               # full suite
pytest tests/test_vault.py        # single file
pytest -k "marketplace"           # match name

# Type check (optional, dev tool)
mypy axt.py
```

The entry point is `axt:main` (declared in `pyproject.toml` under `[project.scripts]`).

## Architecture

Single-file Python: `axt.py` (~7,400 lines). Internally organized into 15 numbered sections — search by `# ── Section N:` header to navigate.

```
axt.py                  → All code (CLI + TUI + domain + parsers)
  Section 1             → Constants & Paths
  Section 2             → JSON I/O (atomic write)
  Section 3             → Settings (single-scope read/write)
  Section 4             → Plugin / MCP / Skill / Commands / Agents / Hooks
  Section 5             → Vault + Marketplace
  Section 6             → Usage parsers (claude/codex/gemini/cursor)
  Section 7             → Pricing, Plans & Config
  Section 8             → Context Analysis
  Section 9             → Project Usage Index
  Section 10            → CLI Commands (argparse)
  Section 11            → TUI common helpers (curses, color, key, width)
  Section 12            → TUI common widgets (Table, DetailPanel, …)
  Section 13            → TUI tabs (Vault + others)
  Section 14            → TUI main loop
  Section 15            → Entry point (main)

pricing.json            → Model pricing table (kept out of code for easy updates)
pyproject.toml          → Package metadata; entry = axt:main
README.md               → User-facing install/usage doc
DESIGN.md               → Rationale for the cst-style single-file rewrite
FEATURES.md             → 1:1 feature inventory (44 subcommands, 8 TUI tabs)
SKILL.md                → Claude Skill manifest exposing axt to Claude Code
tests/                  → pytest suite, one test_*.py per domain (paths, json_io,
                          settings, vault, marketplace, plugin, skill, mcp,
                          hooks, commands_agents, usage_claude, usage_codex_gemini,
                          usage_cursor, pricing, context, project_usage, tui, cli)
legacy-ts/              → Frozen TypeScript+Ink implementation (v0.1.x, no new work)
```

### Key design patterns

- **Path constants** centralized in Section 1 (`Paths` dataclass). Supports `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GEMINI_CLI_HOME` env overrides and Windows `%APPDATA%`.
- **JSON I/O** (Section 2): `read_json(path, fallback=...)` and `write_json_atomic(path, data)`. All file mutations go through atomic writes (`tempfile` + `os.replace`).
- **Usage data flow**: per-platform parsers (Section 6) → `UnifiedUsageEntry` adapter → pricing applied. Caching is mtime-based (`load_cached_usage` / `save_cached_usage`).
- **Pricing** (Section 7): static lookup table loaded from `pricing.json`. Cost = tokens × per-million rate. To add a model, edit `pricing.json` — no code change.
- **Plugin system**: tracks installs in `~/.claude/plugins/installed_plugins.json` and marketplaces in `~/.claude/plugins/known_marketplaces.json`. Sources: `github:user/repo`, `git:<url>`, `dir:/path`.
- **Vault system** (Section 5): manages `.axt-profile.json` per project and `~/.claude/vault/` globally. Supports link/unlink/sync/migrate/import.
- **Context analysis** (Section 8): collects all context sources (CLAUDE.md, .mdc rules, settings, MCP configs) and estimates token usage per source.
- **TUI rendering** (Sections 11–14): curses absolute-cell drawing (`addnstr(y, x, text, max_w, attr)`) — no Ink/Yoga layout dependency. Selected row uses `curses.A_REVERSE` directly. East Asian width via `unicodedata.east_asian_width`.
- **Settings** (Section 3): read from multiple scopes (global `~/.claude/settings.json`, project `.claude/settings.json`) and merge.

### CLI command groups

| Command | Description |
|---------|-------------|
| `axt` (no args) / `axt tui` | Launch TUI dashboard |
| `axt market` | Marketplace add / remove / list / sync |
| `axt plugin` | Plugin list / enable / disable / info / remove / search |
| `axt skill` | Skill list / link / unlink |
| `axt mcp` | MCP server list / info |
| `axt usage` | Usage summary per platform (today/week/month/blocks/session) |
| `axt plan` | Subscription plan overview / set |
| `axt project` | Project context init/add/remove/sync/status |
| `axt context` | Context source analysis (analyze / list) |
| `axt vault` | Vault list / migrate / add / install / link-global / unlink-global |

Full subcommand inventory: see `FEATURES.md`.

### Platform differences

- Windows: `skill link` / `unlink` commands are disabled (symlinks need elevated privileges); use the `windows-curses` extra for the TUI (`pip install -e .[dev,windows]`).
- All path resolution checks `sys.platform == "win32"` in Section 1.

## Python configuration

- Python 3.9+ (uses `set_escdelay`, type-hint syntax `dict[str, X]`, etc.).
- Pure stdlib runtime — no external dependencies. Dev: pytest, pytest-cov.
- Package layout: single-file (`py-modules = ["axt"]` in `pyproject.toml`).

## Claude Skill

`SKILL.md` at the repo root exposes `axt` as a Claude Code skill. Trigger phrases cover plugin/skill/MCP/hook/usage/marketplace/vault/context operations in both English and Korean. Symlink or install this directory under `~/.claude/skills/agent-extension-tool` to activate.

## Working in this repo

- Edit `axt.py` directly. Section headers are stable navigation anchors — keep them.
- Tests live in `tests/` and import `axt` as a module (via `pyproject` `py-modules`). Run `pytest` from the repo root.
- Do not modify `legacy-ts/`. It is frozen as historical reference and a fallback.
