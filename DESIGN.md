# axt-new — Python + curses 재작성 설계

## 배경 (Why)

axt는 현재 TypeScript + Ink(React-for-CLI)로 작성되어 있다. Ink의 flexbox 레이아웃 모델은 character-width 측정에 의존하며, WezTerm + cmux 같은 환경에서 selected 행의 inverse 렌더링이 시각적으로 사라지는 버그가 재현된다. 동일 도메인 도구인 cst(claude-session-tracker)는 Python + curses로 작성되어 동일 환경에서 정상 동작한다.

여러 Ink 우회 시도(구조 통일, AMBIGUOUS_SAFETY, color 기반 selected)가 모두 실패. 근본 해결을 위해 cst와 동일한 렌더 모델(curses 절대 좌표 cell-by-cell)로 전체 재작성한다.

## 범위 및 결정 사항

| 결정 | 선택 |
|---|---|
| 진행 순서 | 한 번에 전체 재작성 |
| 기존 코드 | `axt/`는 그대로 두고 신규 `axt-new/` 디렉터리에 작성 |
| 프로젝트 구조 | cst 스타일 단일 파일 (`axt-new/axt.py`) |
| 언어 | Python 3.9+ (set_escdelay 등 사용) |
| TUI | 표준 라이브러리 `curses` |
| CLI | 표준 라이브러리 `argparse` |
| HTTP | 표준 라이브러리 `urllib` (marketplace sync) |
| JSON | 표준 라이브러리 `json` |
| 테스트 | `pytest` (`axt-new/tests/`) |

## 디렉터리 구조

```
axt-new/
├── axt.py              # 메인 단일 파일 (~5,000~8,000줄 예상)
├── pricing.json        # 모델별 토큰 가격 테이블 (코드 분리)
├── README.md           # 사용법
├── pyproject.toml      # bin entry: `axt = axt:main`
├── .gitignore          # __pycache__/, *.pyc
└── tests/
    ├── conftest.py     # 공통 fixture (tmp_home 등)
    ├── test_paths.py
    ├── test_json_io.py
    ├── test_settings.py
    ├── test_vault.py
    ├── test_marketplace.py
    ├── test_plugin.py
    ├── test_skill.py
    ├── test_mcp.py
    ├── test_hooks.py
    ├── test_commands.py
    ├── test_agents.py
    ├── test_usage_claude.py
    ├── test_usage_codex.py
    ├── test_usage_gemini.py
    ├── test_usage_cursor.py
    ├── test_pricing.py
    ├── test_context.py
    ├── test_project_usage.py
    └── test_cli_smoke.py
```

## 단일 파일 내부 섹션 구조

`axt.py`는 cst의 `tracker.py` 처럼 단일 파일이지만, 다음 섹션 헤더 주석으로 명확히 구분:

```
# ── Section 1: Constants & Paths ───────────────────────────
# ── Section 2: JSON I/O ────────────────────────────────────
# ── Section 3: Settings Reader (multi-scope merge) ─────────
# ── Section 4: Plugin/Marketplace/Skill/MCP/Hook/Cmd/Agent ─
# ── Section 5: Vault ───────────────────────────────────────
# ── Section 6: Usage Parsers (claude/codex/gemini/cursor) ─
# ── Section 7: Pricing & Cost ──────────────────────────────
# ── Section 8: Context Analysis ────────────────────────────
# ── Section 9: Project Usage Index ─────────────────────────
# ── Section 10: CLI Commands ───────────────────────────────
# ── Section 11: TUI — Common Helpers (color, key) ──────────
# ── Section 12: TUI — Common Widgets (Table, DetailPanel, …)
# ── Section 13: TUI — Tabs (Extensions/Context/.../Cursor) ─
# ── Section 14: TUI — Main Loop ────────────────────────────
# ── Section 15: Entry Point ────────────────────────────────
```

## 기능 인벤토리 (모두 이식 대상)

### CLI 명령 (현행 axt와 1:1)
- `axt` (no args) → TUI
- `axt tui` → TUI 명시
- `axt context analyze` / `axt context list`
- `axt market {list|add|sync|remove}`
- `axt mcp {list|info}`
- `axt plan`
- `axt plugin {list|enable|disable|info|remove|search}`
- `axt project {init|add|remove|sync|status}`
- `axt skill {list|link|unlink}`
- `axt usage {summary|blocks|session} [--platform]`
- `axt vault {list|migrate|add|install|link-global|unlink-global}`

### TUI 탭 (8개 + Extensions 서브탭 8개)
- Top-level: Extensions / Context / Project / Dashboard / Claude / Codex / Gemini / Cursor
- Extensions 서브탭: Plugins / Skills / MCP / Hooks / Commands / Agents / Manage(marketplace) / Market(browse) / Vault

### 핵심 데이터 흐름
- 경로 상수: `CLAUDE_CONFIG_DIR`/`CODEX_HOME`/`GEMINI_CLI_HOME` 환경변수 + Windows %APPDATA% 지원
- JSON I/O: atomic write (`tempfile` + `os.replace`)
- Usage: per-platform JSONL/JSON loader → UnifiedUsageEntry → pricing 적용
- Vault: `.axt-profile.json` per project, `~/.claude/vault/` 글로벌, link/unlink/sync/migrate/import
- Pricing: pricing.json 정적 테이블

## 컴포넌트 책임 분리 (단일 파일 내)

각 섹션은 다음 인터페이스를 갖는다:

**Section 2 (JSON I/O)** — 외부 의존: pathlib, json, tempfile, os
```python
def read_json(path: Path, fallback: Any = None) -> Any
def write_json_atomic(path: Path, data: Any) -> None
```

**Section 3 (Settings)** — 외부 의존: Section 2
```python
def read_settings(scopes: list[Path]) -> dict   # global > project merge
def set_plugin_enabled(settings_path: Path, plugin_id: str, enabled: bool) -> None
```

**Section 4~5 (도메인)** — 외부 의존: Section 2, 3, 1(paths)
```python
def list_plugins(installed_path: Path) -> list[Plugin]
def list_marketplaces(known_path: Path) -> list[Marketplace]
def list_vault_items(vault_dir: Path, project_dir: Path, ...) -> list[VaultItem]
# ... 등
```

**Section 6 (Usage)** — 외부 의존: Section 1, 2; 캐싱은 mtime 기반 단순 dict
```python
def load_claude_usage() -> list[UnifiedUsageEntry]
def load_codex_usage() -> list[UnifiedUsageEntry]
def load_gemini_usage() -> list[UnifiedUsageEntry]
def load_cursor_usage() -> list[UnifiedUsageEntry]
```

**Section 11~14 (TUI)** — 외부 의존: curses, Section 1~9
- `_render_table(stdscr, y, x, h, w, columns, rows, selected_idx, checked)` — 절대 좌표
- `_render_detail_panel(stdscr, y, x, h, w, title, fields, scroll, focused)`
- `_render_tab_bar(stdscr, tabs, active, focus_layer)`
- `_run_tui(stdscr)` — cst `_pick_ui` 패턴

## TUI 렌더 모델 (핵심)

cst와 동일하게:
1. `stdscr.clear()` (또는 부분 clear)
2. 각 셀을 `addnstr(y, x, text, max_w, attr)` 로 명시적으로 그림
3. `attr`는 `curses.A_REVERSE`(selected) / `curses.A_DIM`(non-selected prefix) / `curses.color_pair(N)`
4. `stdscr.refresh()` — curses가 diff 계산 후 ANSI 출력

Ink와의 결정적 차이:
- 행의 trailing whitespace는 항상 명시적으로 그려진다 (selected/non-selected 비대칭 없음)
- 너비 측정은 curses에 위임. East Asian Ambiguous 문자는 `unicodedata.east_asian_width`로 사전 계산 가능

## 의존성

```
Python: 3.9+
표준 라이브러리만:
  - curses
  - argparse
  - json
  - pathlib
  - tempfile, os
  - subprocess (editor 실행)
  - urllib (marketplace HTTP)
  - unicodedata (CJK width)
  - datetime
  - re
  - shutil
  - sys
  - time
외부 라이브러리: 없음 (cst와 동일 정책)
테스트:
  - pytest
```

`pyproject.toml`로 `pip install -e .` 또는 `pipx install .` 지원. 엔트리포인트 `axt = axt:main`.

## 테스트 전략

- **단위 테스트**: 각 함수에 대해 tmp 디렉터리 fixture (`pytest tmp_path`) 활용
- **TUI 테스트**: `unittest.mock`으로 curses stdscr 모킹, `addstr` 호출 인자 검증
- **smoke 테스트**: CLI 명령 각각 `subprocess.run([sys.executable, "axt.py", ...])` 실행 후 exit code 검증
- 기존 axt 테스트 59개 케이스를 가능한 한 1:1 이식

## 성공 기준

1. WezTerm + cmux에서 vault 목록 j/k 이동 시 selected 행의 ▸/번호가 항상 표시된다
2. axt의 모든 CLI 명령이 동일하게 동작 (output 포맷은 약간 다를 수 있음)
3. 모든 8개 탭이 cst 수준의 응답성으로 동작
4. pytest 단위 테스트 통과율 ≥ 95%

## 위험 및 완화

| 위험 | 완화 |
|---|---|
| 5,000줄+ 단일 파일 가독성 | 섹션 주석 + 명확한 함수 이름, type hint 활용 |
| Python의 JSONL 파싱 성능 | usage 데이터 mtime 기반 캐시 (cst가 이미 검증) |
| curses의 색상 표현 한계 | `curses.init_pair`로 8색 + bold/dim/reverse 조합. axt 현행 색상 매핑 충실히 |
| 마이그레이션 중 기존 axt 변경 | `axt/`는 freeze, 모든 신규 작업은 `axt-new/`에서. README 안내 |
| Windows curses | windows-curses 패키지 필요. 별도 install 안내. macOS/Linux 우선 |

## 단계 (참고용, 한 번에 진행)

본 작업은 사용자 결정에 따라 한 번에 모두 진행하지만, 내부적으로 다음 순서를 따른다:
1. 스켈레톤 + paths + json_io + settings (가장 기초)
2. domain modules (vault, marketplace, plugin, skill, mcp, hooks, commands, agents)
3. usage parsers + pricing
4. context analysis + project usage index
5. CLI commands (argparse)
6. TUI common widgets
7. TUI tabs
8. main loop + entry point
9. tests

## 비고

- 이 문서는 단일 spec. 변경 사항이 생기면 본 문서를 업데이트하고 git commit.
- 작업 도중 발견된 axt 도메인 로직의 버그·모호함은 본 문서 "수정 사항" 섹션에 추가 후 진행.
