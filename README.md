# axt — Agent eXtension Tool

A unified CLI & TUI dashboard for managing extensions, plugins, skills, MCP servers, hooks, commands, and agents — and for tracking usage costs — for **Claude Code**.

> 🌐 한국어: [README.ko.md](./README.ko.md)

> **v1.0.0: Claude-only.** The earlier multi-platform line (Codex / Gemini CLI / Cursor) is retained as v0.2.x; v1 drops that surface to focus on Claude depth. See [MIGRATION.md](./MIGRATION.md) (English) or [MIGRATION.ko.md](./MIGRATION.ko.md) (Korean) for upgrade notes.

Python + curses package, pure stdlib runtime. The older TypeScript+Ink line (v0.1.x) lives in git history only — see the `v0.2.0` tag.

## Features

- **Vault** — per-project `.axt-profile.json` + global `~/.claude/vault/`, with link/unlink/sync/migrate/import.
- **Plugin management** — list, enable/disable, inspect, search, and remove plugins from Claude marketplace registries.
- **Skills** — list standalone skills, link/unlink directories into `~/.claude/skills/`.
- **MCP servers** — view servers declared by active plugins or settings; enable/disable per project (`disabledMcpServers`).
- **Hooks** — discover across user, project, local, and plugin scopes; enable/disable user/project/local hooks (parked under `disabledHooks`, plugin hooks read-only).
- **Commands / Agents** — discover across user, project, and plugin scopes.
- **Marketplace system** — register GitHub repos, git URLs, or local directories as plugin marketplaces and sync them.
- **Usage tracking** — Claude token usage and cost with per-model pricing; today / week / month / 5-hour billing blocks / session views.
- **Plan budget** — plan overview with daily / weekly / monthly projections and budget bars.
- **Context analysis** — token estimate per context source at session start (CLAUDE.md, skills, MCP tools, hooks, etc.).
- **Interactive TUI** — 3 main tabs (Extensions / Context / Usage) with keyboard-driven navigation. Renders via curses absolute-cell drawing, so it stays correct under terminal multiplexers (WezTerm + cmux verified).
- **Claude Skill** — `SKILL.md` at the repo root exposes `axt` as a Claude Code skill (EN + KO triggers).

Pure standard library at runtime — no external Python dependencies. Windows users additionally need `windows-curses`.

## Install

Pure stdlib at runtime — no dependencies to resolve. Just need Python 3.9+.

### Quick install (easiest — one line, no clone)

`axt` installs straight from git. [pipx](https://pipx.pypa.io) is recommended (isolated venv + `axt` on your PATH):

```bash
pipx install "git+https://github.com/greeun/agent-extension-tool.git"
axt --version          # axt 1.5.0
```

> **No pipx?** `python3 -m pip install --user pipx && python3 -m pipx ensurepath`, reopen the shell, then run the command above.
> **Prefer plain pip?** `pip install --user "git+https://github.com/greeun/agent-extension-tool.git"` works the same (just doesn't isolate the venv).

Update later with `pipx upgrade axt`; remove with `pipx uninstall axt`.

### From source (for development)

Clone and install editable so code edits take effect immediately. `[dev]` adds pytest (only needed to run the test suite):

```bash
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
axt --version          # axt 1.5.0
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
axt --theme light                  # force a theme for this run (auto / dark / light)

# Inspection (read-only — safe to run anytime)
axt plugin list
axt skill list
axt mcp list
axt hook list
axt market list
axt usage today
axt vault list
axt context

# Mutation (touches ~/.claude/ — confirm before running)
axt market add github:user/repo
axt market sync
axt plugin enable <plugin-id>
axt mcp disable <server-name>      # project-scoped (disabledMcpServers)
axt hook disable <index>          # index from `axt hook list`
axt vault link-global <type> <name>
```

Full CLI inventory: [`FEATURES.md`](./FEATURES.md).

### Updating extensions

```bash
axt update                 # dry-run: what is updatable across all types
axt update --json          # machine-readable
axt update --apply --yes   # apply all updatable (Tier-1) items
axt update plugin foo@mk --apply   # update one plugin
axt update claude-code --apply     # delegate to `claude update`
```

Capability tiers: plugins, marketplaces, and git-backed standalone skills/commands/agents auto-apply (Tier 1 — bulk `axt update --apply` covers these); MCP servers are report-only since their version is pinned in the launch args (Tier 2 — reports `pinned @x.y.z` / `floating (@latest)` / `unpinned`); the Claude Code binary is delegated to `claude update` and only updates when explicitly targeted via `axt update claude-code --apply` (Tier 3).

## Updating

```bash
cd agent-extension-tool
git pull
# Editable install picks up code changes automatically.
# Re-run pip only if dependencies or entry points changed:
pip install -e .[dev]
```

## Uninstall

`axt` writes only to its own paths. Removing the install does not touch your `~/.claude/` directory.

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

> **Do not delete** `~/.claude/` itself — that belongs to Claude Code, not to axt.

## Test

```bash
pytest                            # full suite
pytest tests/test_vault.py        # single file
pytest -k "marketplace"           # match by name
```

## Repository layout

```
axt/                Python package (sections preserved as # ── Section N: anchors)
├── __init__.py     public API + submodule mirror
├── __main__.py     `python3 -m axt` entry
├── core.py         Sections 1-9: domain (paths, JSON I/O, settings, plugin,
│                   skill, MCP, hooks, commands, agents, vault, marketplace,
│                   usage, pricing, context, project usage)
├── cli.py          Section 10 + 15: argparse + `main` entry
├── pricing.json    model pricing table (edit to add new models — no code change)
└── tui/
    ├── widgets.py  Sections 11-12: curses helpers + common widgets
    ├── tabs.py     Section 13: tab rendering + input dispatch
    └── loop.py     Section 14: TUI main loop + launch_tui

pyproject.toml      package metadata, entry point: axt:main
tests/              pytest suite, one test_*.py per domain
DESIGN.md           rewrite rationale + Phase-C package split
FEATURES.md         feature inventory
SKILL.md            Claude Code skill manifest
MIGRATION.md        Upgrade notes: v0.1.x→v0.2.0 and v0.2.x→v1.0.0 (EN; KO in MIGRATION.ko.md)
```

## License

MIT — see [LICENSE](./LICENSE).
