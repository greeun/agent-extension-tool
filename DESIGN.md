# axt — Python + curses 설계

## 배경 (Why)

axt는 본래 TypeScript + Ink(React-for-CLI)로 작성되었다. Ink의 flexbox 레이아웃 모델은 character-width 측정에 의존하며, WezTerm + cmux 같은 환경에서 selected 행의 inverse 렌더링이 시각적으로 사라지는 버그가 재현된다. 반면 Python + curses 로 셀 단위 렌더링하는 구현은 동일 환경에서 정상 동작한다.

여러 Ink 우회 시도(구조 통일, AMBIGUOUS_SAFETY, color 기반 selected)가 모두 실패. 근본 해결을 위해 curses 절대 좌표 cell-by-cell 렌더 모델로 v1.0.0에서 전체 재작성했다.

> **v1.0.0 — Claude 전용 정리**: Codex / Gemini / Cursor 지원을 제거하고 Claude 한정으로 집중. `UnifiedUsageEntry` 어댑터 구조는 유지하되 `PLATFORMS = ("claude",)`로 좁힌다. 멀티 플랫폼 추상화를 다시 도입할 계획은 없다.

> **Phase C (v1.0.0-rc.C) 변경**: 단일 파일 `axt.py`(~7,400줄)를 섹션별 모듈 패키지 `axt/`로 분리했다. 섹션 헤더(`# ── Section N:`)는 각 모듈 내부에서 그대로 보존되어 네비게이션 앵커 역할을 한다. 패키지의 `__init__.py`는 서브모듈 globals를 `axt` 네임스페이스에 미러링하여 `axt.X`/`monkeypatch.setattr("axt.X", ...)` 같은 기존 호출 규약을 그대로 유지한다.

## 범위 및 결정 사항

| 결정 | 선택 |
|---|---|
| 진행 순서 | 한 번에 전체 재작성 (v0.2) → v1.0.0에서 claude-only 정리 → v1.0.0-rc.C에서 섹션 모듈 분리 |
| 프로젝트 구조 | 섹션별 모듈 패키지 (`axt/core.py`, `axt/cli.py`, `axt/tui/*.py`); 섹션 헤더는 모듈 내 앵커로 보존 |
| 언어 | Python 3.9+ (set_escdelay 등 사용) |
| TUI | 표준 라이브러리 `curses` |
| CLI | 표준 라이브러리 `argparse` |
| HTTP | 표준 라이브러리 `urllib` (marketplace sync) |
| JSON | 표준 라이브러리 `json` |
| 테스트 | `pytest` (`tests/`) |

## 디렉터리 구조

```
.
├── axt/                       # Python 패키지 (Phase C에서 단일 파일에서 분리)
│   ├── __init__.py            # public API + submodule mirror (axt.X 네임스페이스 유지)
│   ├── __main__.py            # `python3 -m axt`
│   ├── core.py                # Section 1-9 (도메인)
│   ├── cli.py                 # Section 10 + 15 (argparse + main)
│   ├── pricing.json           # 모델별 토큰 가격 테이블 (코드 분리; 패키지 데이터로 포함)
│   └── tui/
│       ├── __init__.py
│       ├── widgets.py         # Section 11-12 (curses helpers + 공용 widgets)
│       ├── tabs.py            # Section 13 (TuiState, render_*_tab, handle_*_input)
│       └── loop.py            # Section 14 (HELP_TEXT, _render_frame, _tui_loop, launch_tui)
├── README.md                  # 사용법
├── pyproject.toml             # bin entry: `axt = axt:main`
├── .gitignore
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
    ├── test_commands_agents.py
    ├── test_usage_claude.py
    ├── test_pricing.py
    ├── test_context.py
    ├── test_project_usage.py
    ├── test_tui.py
    └── test_cli.py
```

## 패키지 내부 섹션 매핑

cst의 `tracker.py`처럼 섹션 헤더 주석으로 코드를 구분한다는 컨벤션은 유지하되, 섹션을 모듈로 분리했다:

| 섹션 | 모듈 | 설명 |
|---|---|---|
| 1 — Constants & Paths | `axt/core.py` | `Paths` dataclass, `CLAUDE_CONFIG_DIR` env, Windows 처리 |
| 2 — JSON I/O | `axt/core.py` | `read_json`, `write_json_atomic` |
| 3 — Settings | `axt/core.py` | single-scope read/write, plugin enable/disable |
| 4 — Plugin/Marketplace/Skill/MCP/Hook/Cmd/Agent | `axt/core.py` | 도메인 목록·메타·info |
| 5 — Vault | `axt/core.py` | `.axt-profile.json` + `~/.claude/vault/` |
| 6 — Usage Parsers (Claude) | `axt/core.py` | JSONL → `UnifiedUsageEntry`, mtime 캐시 |
| 7 — Pricing & Cost | `axt/core.py` | `pricing.json` 로더 |
| 8 — Context Analysis | `axt/core.py` | CLAUDE.md / .mdc / settings / MCP 토큰 추정 |
| 9 — Project Usage Index | `axt/core.py` | 프로젝트 사용량 집계 |
| 10 — CLI Commands | `axt/cli.py` | argparse 트리 + `cli_*` 핸들러 |
| 11 — TUI Common Helpers | `axt/tui/widgets.py` | color/key/width 헬퍼 |
| 12 — TUI Common Widgets | `axt/tui/widgets.py` | `Table`, `DetailPanel`, … |
| 13 — TUI Tabs | `axt/tui/tabs.py` | `TuiState`, `render_*_tab`, `handle_*_input` |
| 14 — TUI Main Loop | `axt/tui/loop.py` | `HELP_TEXT`, `_render_frame`, `_tui_loop`, `launch_tui` |
| 15 — Entry Point | `axt/cli.py` | `main()` (console_script 진입점) |

각 모듈 안에는 원래 섹션 헤더 주석(`# ── Section N: …`)이 그대로 남아있다. 도메인 코드를 찾을 때는 `axt/core.py`에서 `# ── Section 6:` 같은 앵커로 점프하면 된다.

## 기능 인벤토리 (요약)

### CLI 명령
- `axt` (no args) → TUI
- `axt tui` → TUI 명시
- `axt context analyze` / `axt context list`
- `axt market {list|add|sync|remove}`
- `axt mcp {list|info}`
- `axt plan {overview|set}`
- `axt plugin {list|enable|disable|info|remove|search}`
- `axt project {init|add|remove|sync|status}`
- `axt skill {list|link|unlink}`
- `axt usage {today|week|month|blocks|session}`
- `axt vault {list|migrate|add|install|link-global|unlink-global}`

### TUI 탭 (3 메인 + Extensions 서브탭 8개)
- Top-level: Extensions / Context / Usage
- Extensions 서브탭: Vault / Plugins / Skills / Commands / Agents / MCP / Hooks / Market

### 핵심 데이터 흐름
- 경로 상수: `CLAUDE_CONFIG_DIR` 환경변수 + Windows `%APPDATA%` 지원
- JSON I/O: atomic write (`tempfile` + `os.replace`)
- Usage: Claude JSONL loader → `UnifiedUsageEntry` → pricing 적용
- Vault: `.axt-profile.json` per project, `~/.claude/vault/` 글로벌, link/unlink/sync/migrate/import
- Pricing: `pricing.json` 정적 테이블

## 컴포넌트 책임 분리

각 섹션 모듈은 다음 인터페이스를 갖는다.

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
# v1.0.0: Claude 전용. 멀티 플랫폼 로더는 v0.2.x 한정으로 제거됨.
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
  - subprocess (editor 실행, git, hook preview)
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
- **smoke 테스트**: CLI 명령 각각 `subprocess.run([sys.executable, "-m", "axt", ...])` 실행 후 exit code 검증

## 성공 기준

1. WezTerm + cmux에서 vault 목록 j/k 이동 시 selected 행의 ▸/번호가 항상 표시된다
2. axt의 모든 Claude 관련 CLI 명령이 안정적으로 동작
3. 모든 3개 메인 탭(Extensions / Context / Usage)이 cst 수준의 응답성으로 동작
4. pytest 단위 테스트 통과율 ≥ 95%

## 위험 및 완화

| 위험 | 완화 |
|---|---|
| 모듈 분리로 인한 namespace 회귀 | `axt/__init__.py`의 submodule mirror + write-proxy가 `axt.X` / `monkeypatch.setattr("axt.X", ...)`를 보장. 340 테스트로 회귀 감시 |
| Python의 JSONL 파싱 성능 | usage 데이터 mtime 기반 캐시 (cst가 이미 검증) |
| curses의 색상 표현 한계 | `curses.init_pair`로 8색 + bold/dim/reverse 조합 |
| Windows curses | `windows-curses` 패키지 필요. 별도 install 안내. macOS/Linux 우선 |

## Vault Scan Cache Policy

Vault 탭의 "Used" 컬럼은 모든 프로젝트의 `.claude/skills`, `commands`, `agents`
심볼릭 링크와 `.axt-profile.json`을 순회하는 cross-project scan 결과를 반영한다.
이 스캔은 비싸므로(프로젝트 수에 선형), TUI 응답성을 유지하기 위해 결과를 디스크에
캐싱한다.

**캐시 위치**: `<AXT_CONFIG_DIR>/cache/vault-scan-index.json`
  - POSIX: `~/.config/axt/cache/vault-scan-index.json`
    (`$XDG_CONFIG_HOME`가 설정되어 있으면 `$XDG_CONFIG_HOME/axt/cache/...`)
  - Windows: `%APPDATA%/axt/cache/vault-scan-index.json`

**갱신 트리거**: Vault 탭에서 `f` 키를 눌렀을 때만 캐시가 채워지거나 갱신된다.
같은 키가 스캔 모드를 `"default"` ↔ `"full"`로 토글한다. 타이머·시작 시 자동
스캔·자동 무효화는 없다.

**스테일니스**: 스캔 진행 중에는 상태 바에 `scan=<mode>(<count>/<total>)`이 표시된다.
스캔이 완료된 뒤에는 캐시 파일의 mtime만이 staleness의 유일한 단서이며, 갱신 시점은
사용자가 결정한다.

**쓰기**: `write_json_atomic`을 통과한다 — partial 파일은 절대 외부에 노출되지 않으며,
원자적 rename 직전의 `.bak` sibling이 한 사이클 동안 보존된다.

**동시성**: 단일 사용자 도구로 가정. 파일 락이 없다. 동시에 두 스캔이 일어나면 atomic
rename의 last-writer-wins 시맨틱에 의존하며, 이는 허용 가능한 동작이다.

**스키마 진화**: payload에 `"mode": "default" | "full"` 태그가 박혀 있다. 현재는
`"version"` 필드가 없으며, 향후 스키마 변경 시 `"version": N`을 추가하고 없는 경우를
version 0으로 취급해야 한다.

(상기 정책의 canonical reference는 `axt/tui/tabs.py`의 `_scan_cache_path` 위 인라인
주석 블록이다. 본 섹션은 이를 아키텍처 레벨에서 미러링한다.)

## 비고

- 본 문서는 단일 spec. 변경 사항이 생기면 본 문서를 업데이트하고 git commit.
- 작업 도중 발견된 axt 도메인 로직의 버그·모호함은 본 문서 또는 FEATURES.md에 추가 후 진행.
- v1.0.0에서 Codex / Gemini / Cursor 지원은 의도적으로 제거되었다 (이전 multi-platform 구현은 v0.2.x에서 참고). 재도입할 계획 없음.
