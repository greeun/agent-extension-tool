# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Communication

- 항상 한글로 답변할 것. 코드와 CLI 출력은 영어 그대로 유지.

## What is this project?

**axt** (Agent eXtension Tool) is a CLI + TUI dashboard that manages extensions, plugins, skills, MCP servers, hooks, commands, agents, and usage-cost tracking for Claude Code. It reads data from `~/.claude/` and presents a unified view. **v1.0.0 is Claude-only.** The earlier multi-platform implementation (Codex / Gemini CLI / Cursor support) was kept as v0.2.0 for reference; that surface area was removed to focus on Claude depth.

**Primary implementation**: Python + curses, packaged as `axt/`. Pure stdlib runtime.

**Frozen legacy**: TypeScript + Ink implementation lives under `legacy-ts/` (v0.1.x line). Read-only — no new development.

## Commands

```bash
# One-time setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# Run
axt                  # launch TUI
axt --help           # CLI help
python3 -m axt       # equivalent entry via `axt = "axt:main"` script

# Test
pytest               # full suite
pytest tests/test_vault.py        # single file
pytest -k "marketplace"           # match name

# Type check (optional, dev tool)
mypy axt/
```

The entry point is `axt:main` (declared in `pyproject.toml` under `[project.scripts]`).

## Architecture

`axt/` is a Python package; section headers (`# ── Section N:`) are preserved as stable navigation anchors inside each module. Phase C (commits up to v1.0.0-rc.C) split the original single-file `axt.py` into per-section modules. The package's `__init__.py` mirrors each submodule's globals onto the `axt` namespace, so `axt.X` still resolves regardless of which submodule owns `X`.

```
axt/                    → Package
├── __init__.py         → Public API, version, submodule mirror system
├── __main__.py         → `python3 -m axt` entry
├── core.py             → Sections 1-9 — domain layer:
│                         paths, JSON I/O, settings,
│                         plugin / MCP / skill / hook / command / agent,
│                         vault, marketplace, usage parsers (Claude),
│                         pricing / plans / config, context analysis,
│                         project usage index
├── cli.py              → Section 10 + Section 15 — argparse subcommands and `main`
├── pricing.json        → Per-million-token pricing table (package data)
└── tui/
    ├── __init__.py
    ├── widgets.py      → Sections 11-12 — curses helpers + common widgets
    ├── tabs.py         → Section 13 — TuiState, render_*_tab, handle_*_input, dispatch
    └── loop.py         → Section 14 — HELP_TEXT, _render_frame, _tui_loop, launch_tui

pyproject.toml          → Package metadata; entry = axt:main
README.md               → User-facing install/usage doc
DESIGN.md               → Rationale for the cst-style rewrite + Phase-C package split
FEATURES.md             → Feature inventory (35 subcommands, 3 main TUI tabs + Scope filter)
SKILL.md                → Claude Skill manifest exposing axt to Claude Code
tests/                  → pytest suite, one test_*.py per domain (paths, json_io,
                          settings, vault, marketplace, plugin, skill, mcp,
                          hooks, commands_agents, usage_claude, pricing,
                          context, project_usage, tui, cli)
legacy-ts/              → Frozen TypeScript+Ink implementation (v0.1.x, no new work)
```

### Key design patterns

- **Path constants** centralized in Section 1 (`Paths` dataclass). Supports `CLAUDE_CONFIG_DIR` env override and Windows `%APPDATA%`.
- **JSON I/O** (Section 2): `read_json(path, fallback=...)` and `write_json_atomic(path, data)`. All file mutations go through atomic writes (`tempfile` + `os.replace`).
- **Usage data flow**: Claude JSONL parser (Section 6) → `UnifiedUsageEntry` adapter → pricing applied. Caching is mtime-based (`load_cached_usage` / `save_cached_usage`). `PLATFORMS = ("claude",)`.
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
| `axt usage` | Claude usage summary (today/week/month/blocks/session) |
| `axt plan` | Claude plan overview / set |
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
- Package layout: `packages = ["axt"]` (via `setuptools.find_packages`) in `pyproject.toml`; `axt/pricing.json` is shipped as package data.

## Claude Skill

`SKILL.md` at the repo root exposes `axt` as a Claude Code skill. Trigger phrases cover plugin/skill/MCP/hook/usage/marketplace/vault/context operations in both English and Korean. Symlink or install this directory under `~/.claude/skills/agent-extension-tool` to activate.

## Working in this repo

- Edit per-section modules inside `axt/` directly:
  - Domain (Sections 1-9) → `axt/core.py`
  - CLI (Section 10) + entry point (Section 15) → `axt/cli.py`
  - TUI helpers/widgets (Sections 11-12) → `axt/tui/widgets.py`
  - TUI tabs (Section 13) → `axt/tui/tabs.py`
  - TUI main loop (Section 14) → `axt/tui/loop.py`
- Section header comments (`# ── Section N:`) are stable navigation anchors — keep them.
- The package mirror in `axt/__init__.py` re-exports submodule globals onto `axt`, so tests can keep using `axt.X` / `monkeypatch.setattr("axt.X", ...)` without caring which submodule owns `X`. When adding a new public name, no manual re-export is needed; mirror happens automatically.
- Tests live in `tests/` and import `axt` as a package. Run `pytest` from the repo root.
- Do not modify `legacy-ts/`. It is frozen as historical reference and a fallback.
