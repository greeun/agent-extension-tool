# axt — Agent eXtension Tool

A unified CLI & TUI dashboard for managing extensions, plugins, skills, MCP servers, hooks, commands, and agents — and for tracking usage costs — across multiple AI agent platforms (Claude Code, Codex, Gemini CLI, Cursor).

Single-file Python + curses (v1.0.0+). The earlier TypeScript+Ink line is preserved frozen under [`legacy-ts/`](./legacy-ts/).

> **Upgrading from v0.1.x (TypeScript)?** Read [MIGRATION.md](./MIGRATION.md)
> (English) or [MIGRATION.ko.md](./MIGRATION.ko.md) (Korean) first. CLI
> commands and user data (`~/.config/axt/`, `~/.claude/vault/`,
> `.axt-profile.json`) remain compatible across versions.

## Features

- **Multi-platform usage tracking** — token usage and cost for Claude Code, Codex, Gemini CLI, and Cursor IDE in one view, with per-model pricing.
- **Plugin management** — list, enable/disable, inspect, and remove plugins from Claude marketplace registries.
- **Skill / agent / MCP / hook / command discovery** — across user, project, and plugin scopes.
- **Marketplace system** — register GitHub repos, git URLs, or local directories as plugin marketplaces and sync them.
- **Vault** — per-project `.axt-profile.json` + global `~/.claude/vault/`, with link/unlink/sync/migrate/import.
- **Context analysis** — token estimate per context source at session start.
- **Cost projections** — daily / weekly / monthly summaries, 5-hour billing block analysis, plan-aware budgeting.
- **Interactive TUI** — 8 main tabs with keyboard-driven navigation. Renders via curses absolute-cell drawing, so it stays correct under terminal multiplexers (WezTerm + cmux verified).
- **Claude Skill** — `SKILL.md` at the repo root exposes `axt` as a Claude Code skill (EN + KO triggers).

Pure standard library at runtime — no external Python dependencies. Windows users additionally need `windows-curses`.

## Install

Requires Python 3.9+ and Git.

### macOS / Linux

```bash
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
axt --version          # axt 1.0.0
```

For global use without manual `source`:

```bash
# Recommended: pipx isolates the venv and registers ~/.local/bin/axt
pipx install -e ~/<...>/agent-extension-tool
```

### Windows

```powershell
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,windows]"
axt --version
```

> On Windows, `axt skill link` / `unlink` are unavailable (symlinks require elevated privileges). All other features work normally.

### (Optional) Activate the Claude Skill

```bash
ln -s "$(pwd)" ~/.claude/skills/agent-extension-tool
```

Claude Code now picks up `axt` automatically when you mention plugin, skill, MCP, usage, vault, marketplace, or context operations. Trigger phrases (EN + KO) live in the `description:` line at the top of `SKILL.md`.

## Quick start

```bash
# Launch the interactive TUI
axt

# Inspection (read-only — safe to run anytime)
axt plugin list
axt skill list
axt mcp list
axt market list
axt usage today --platform all
axt vault list
axt context analyze

# Mutation (touches ~/.claude/ — confirm before running)
axt market add github:user/repo
axt market sync
axt plugin enable <plugin-id>
axt vault link-global <type> <name>
```

Full CLI inventory: [`FEATURES.md`](./FEATURES.md) (44 subcommands across 10 groups, 4 main TUI tabs + global Platform/Scope filters).

## Updating

```bash
cd agent-extension-tool
git pull
# Editable install picks up code changes automatically.
# Re-run pip only if dependencies or entry points changed:
pip install -e .[dev]
```

## Uninstall

`axt` writes only to its own paths. Removing the install does not touch your AI agent platform directories (`~/.claude/`, `~/.codex/`, …).

```bash
# 1) If installed via pipx
pipx uninstall axt

# 1') If installed via venv + symlink
rm ~/.local/bin/axt           # if you symlinked it
deactivate                    # if inside the venv
rm -rf agent-extension-tool   # the cloned repo

# 2) (Optional) wipe axt's own data
rm -rf ~/.config/axt          # user config
rm -rf ~/.claude/vault        # vault store (irreversible)
# per-project profiles: run in each project
rm -f .axt-profile.json
```

> **Do not delete** `~/.claude/`, `~/.codex/`, `~/.gemini/`, or `~/.cursor/` themselves — those belong to the respective CLIs, not to axt.

## Test

```bash
pytest                            # full suite
pytest tests/test_vault.py        # single file
pytest -k "marketplace"           # match by name
```

## Repository layout

```
axt.py            single source file (~7,400 lines, 15 numbered sections)
pricing.json      model pricing table (edit to add new models — no code change)
pyproject.toml    package metadata, entry point: axt:main
tests/            pytest suite, one test_*.py per domain
DESIGN.md         cst-style single-file rewrite rationale
FEATURES.md       1:1 feature inventory
SKILL.md         Claude Code skill manifest
MIGRATION.md     v0.1.x → v1.0.0 upgrade guide (EN; KO in MIGRATION.ko.md)
legacy-ts/        frozen TypeScript+Ink implementation (v0.1.x line)
```

## License

MIT — see [LICENSE](./LICENSE).
