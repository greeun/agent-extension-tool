# axt — Agent eXtension Tool (Python edition)

Single-file Python + curses rewrite of the TypeScript+Ink axt CLI/TUI.
Same surface, but curses' absolute-cell rendering avoids the Ink/Yoga
selected-row dropout issues observed under WezTerm + cmux.

See `DESIGN.md` and `FEATURES.md` for the full inventory.

> **Upgrading from v0.1.x (TypeScript)?** Read [MIGRATION.md](./MIGRATION.md)
> (English) or [MIGRATION.ko.md](./MIGRATION.ko.md) (Korean) first. CLI
> commands and user data (`~/.config/axt/`, `~/.claude/vault/`,
> `.axt-profile.json`) remain compatible across versions.

## Install (development)

```bash
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
```

On Windows you also need `windows-curses`:

```bash
pip install -e .[dev,windows]
```

## Run

```bash
axt              # launch TUI
axt --help       # CLI help
axt vault list   # any subcommand
```

## Test

```bash
pytest
```

## File layout

- `axt.py` — single source file, organized into 15 sections (see `DESIGN.md`)
- `pricing.json` — model pricing table (kept out of code for easy updates)
- `tests/` — pytest suite
