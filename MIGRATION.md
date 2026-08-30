# axt Migration Guide

A Korean translation is available at [MIGRATION.ko.md](./MIGRATION.ko.md).

## v0.2.x → v1.0.0 — Claude-only

axt v1.0.0 drops support for Codex, Gemini CLI, and Cursor. The tool now manages
Claude Code exclusively. Removed surfaces:

- CLI: `axt usage --platform`, all `axt codex|gemini|cursor` subcommands.
- CLI: `axt plan set <platform> <plan-name>` → `axt plan set <plan-name>` (claude always assumed).
- TUI: Platform filter (`p` key), Usage sub-tabs (All / Codex / Gemini / Cursor), Cursor commit-history tab.
- Pricing: `gpt-*`, `gemini-*` models removed from `pricing.json`.
- Paths: `CODEX_HOME`, `GEMINI_CLI_HOME` env vars no longer honored.
- Config: `AxtConfig.plans` only stores Claude plan now.

If you still need the multi-platform behavior, check out the `v0.2.0` git tag.

---

## v0.1.x → v0.2.0 — TypeScript+Ink to Python+curses

This guide walks existing users of the TypeScript+Ink axt (`v0.1.x`, installed via `bun link`) through removing the old build and installing the new Python+curses axt (`v0.2.0`, installed via `pip install -e .`).

## At a glance

| Item | Old (v0.1.x) | New (v0.2.0) |
|---|---|---|
| Language / runtime | TypeScript + Bun + Ink | Python 3.9+ + curses |
| Dependencies | npm packages (chalk / commander / ink / react …) | Standard library only |
| Global registration | `bun link` → `~/.bun/bin/axt` | `pip install -e .` → venv `bin/axt` |
| Build artifacts | `node_modules/`, `dist/` | `.venv/`, `*.egg-info/` |
| Command surface | Same (`axt …`) | **Same** — no user-facing change |

> **CLI commands and output formats are unchanged.** Anything you ran before — `axt market list`, `axt usage today`, `axt vault list`, etc. — keeps working exactly the same.

## Your data is preserved

Both versions read from and write to the **same paths**. You don't need to back up or migrate any of these manually.

| Path | What it stores |
|---|---|
| `~/.config/axt/config.json` (macOS/Linux) / `%APPDATA%\axt\config.json` (Windows) | axt user config (plan selection, etc.) |
| `~/.claude/vault/` | vault store |
| `<project>/.axt-profile.json` | per-project vault profile |
| `~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.cursor/` | each platform CLI's own directories (axt only **reads** these) |

The on-disk format is identical too. Configs, vault contents, and project profiles created by v0.1.x are read as-is by v0.2.0.

---

## 1. Uninstall the old version (v0.1.x)

### macOS / Linux

```bash
# 1) Detach the global shim — must be run from inside the cloned repo
cd <path to old agent-extension-tool>
bun unlink

# 2) Delete the clone
cd ..
rm -rf agent-extension-tool

# 3) Confirm the command is gone (no output expected)
command -v axt
```

### Windows (PowerShell)

```powershell
cd <path to old agent-extension-tool>
bun unlink

cd ..
Remove-Item -Recurse -Force agent-extension-tool

Get-Command axt -ErrorAction SilentlyContinue   # should return nothing
```

### Leftover bun shim

If you deleted the cloned directory **without** running `bun unlink` first, `~/.bun/bin/axt` will remain as a broken symlink.

```bash
# Force-remove the dangling shim
rm -f ~/.bun/bin/axt
command -v axt   # should produce no output
```

On Windows the equivalent path is `%USERPROFILE%\.bun\bin\axt.*`.

---

## 2. Install the new version (v0.2.0)

### macOS / Linux

```bash
# 1) Verify Python 3.9+
python3 --version

# 2) Clone
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool

# 3) Create venv and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# 4) Verify
axt --version          # axt 0.2.0
which axt              # .../agent-extension-tool/.venv/bin/axt
```

The `axt` command is only on `PATH` while the venv is active. To use it from any shell, pick one of:

```bash
# Option A: auto-activate the venv in every shell
echo 'source ~/<...>/agent-extension-tool/.venv/bin/activate' >> ~/.zshrc

# Option B: symlink the venv's axt into ~/.local/bin (no activation needed)
ln -s ~/<...>/agent-extension-tool/.venv/bin/axt ~/.local/bin/axt

# Option C: install with pipx (isolated venv, auto shim — recommended)
pipx install -e ~/<...>/agent-extension-tool
```

> **Recommended: Option C (pipx).** pipx creates its own isolated venv and registers a `~/.local/bin/axt` shim automatically, with no `source` calls required.

### Windows

```powershell
# 1) Verify Python 3.9+
python --version

# 2) Clone
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool

# 3) Create venv and install (includes windows-curses)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,windows]"

# 4) Verify
axt --version
Get-Command axt
```

> On Windows, `axt skill link` / `unlink` remain unavailable (symlinks require elevated privileges). Every other feature works normally.

---

## 3. Updating

```bash
cd agent-extension-tool
git pull
# Code-only changes need no reinstall (editable install picks them up).
# Re-run pip only if dependencies or entry points changed:
pip install -e .[dev]
```

---

## 4. (Optional) Enable the Claude Skill

Starting with v0.2.0, `axt` can also be exposed as a Claude Code skill. The `SKILL.md` at the repo root is the manifest.

```bash
# Point ~/.claude/skills/agent-extension-tool at this repo
ln -s "$(pwd)" ~/.claude/skills/agent-extension-tool
```

Once linked, Claude Code can invoke `axt` automatically when you mention phrases like "list plugins", "claude usage", "marketplace", "vault", or their Korean equivalents. The full trigger phrase list lives in the `description:` line at the top of `SKILL.md`.

---

## 5. Troubleshooting

### `axt: command not found`

The venv isn't active. Either `source .venv/bin/activate`, or use Option B/C above to register a global shim.

### `Permission denied` (Linux/macOS)

`~/.local/bin` may not be on `PATH`. Add this line to `~/.zshrc` or `~/.bashrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Both versions on PATH

Check with `which -a axt` (macOS/Linux) or `Get-Command axt -All` (Windows). If you see both `~/.bun/bin/axt` (old) and `~/.local/bin/axt` or `.venv/bin/axt` (new), remove the old one first as described in §1.

### `windows-curses` fails to install (Windows)

Some `windows-curses` builds break on newer Python (e.g. 3.13). Upgrade pip first, then retry:

```powershell
pip install --upgrade pip
pip install -e ".[dev,windows]"
```

### Garbled output (CJK width / colors)

The new version computes display width via `unicodedata.east_asian_width`, but terminals vary in how they treat East Asian Ambiguous characters. The WezTerm + cmux combination is explicitly tested, and the v0.1.x bug where the selected row's ▸/index would vanish has been resolved.

---

## 6. (Reference) Running the legacy TypeScript build

The v0.1.x line is no longer in the working tree. It stays reachable through git history — check out a tag that still carries it (`v0.2.0` through `v1.19.0`) and build from the `legacy-ts/` directory that tag contains:

```bash
git checkout v0.2.0
cd legacy-ts
bun install
bun run dev          # or: bun run bin/axt.ts <subcommand>
```

That line will not receive further updates. Bug reports and feature requests target v1.0.0 (Claude-only). The v0.2.x multi-platform line is unmaintained.

---

## 7. Wiping data completely

To remove only the files `axt` itself wrote, follow the steps below. **Do not delete** the platform CLI directories (`~/.claude/`, `~/.codex/`, …) — they belong to those tools, not axt.

```bash
# axt-only config
rm -rf ~/.config/axt           # macOS/Linux
# Remove-Item -Recurse -Force "$env:APPDATA\axt"   # Windows

# vault data (irreversible)
rm -rf ~/.claude/vault

# per-project profile (run inside each project)
rm -f .axt-profile.json
```
