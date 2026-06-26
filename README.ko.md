# axt — Agent eXtension Tool

**Claude Code**의 익스텐션·플러그인·스킬·MCP 서버·훅·커맨드·에이전트를 통합 관리하고, 사용량·비용을 추적하는 CLI & TUI 대시보드.

> 🌐 English: [README.md](./README.md)

> **v1.0.0부터 Claude 전용.** 이전 멀티플랫폼 라인(Codex / Gemini CLI / Cursor)은 v0.2.x로 유지되며, v1은 Claude 깊이에 집중하기 위해 해당 영역을 제거했습니다. 업그레이드 안내는 [MIGRATION.ko.md](./MIGRATION.ko.md)(한글) 또는 [MIGRATION.md](./MIGRATION.md)(영어) 참고.

Python + curses 패키지, 순수 stdlib 런타임. 구버전 TypeScript+Ink 라인(v0.1.x)은 [`legacy-ts/`](./legacy-ts/)에 동결 보존되어 있습니다.

## 기능

- **Vault** — 프로젝트별 `.axt-profile.json` + 전역 `~/.claude/vault/`. link/unlink/sync/migrate/import 지원.
- **플러그인 관리** — Claude 마켓플레이스 레지스트리의 플러그인 목록·활성/비활성·조회·검색·삭제.
- **스킬** — 독립 스킬 목록 조회, `~/.claude/skills/`로 디렉터리 link/unlink.
- **MCP 서버** — 활성 플러그인이나 설정이 선언한 서버 조회, 프로젝트 단위 활성/비활성(`disabledMcpServers`).
- **훅** — user / project / local / plugin 스코프 전역 탐색. user/project/local 훅 활성/비활성(`disabledHooks`에 보관, plugin 훅은 읽기 전용).
- **커맨드 / 에이전트** — user / project / plugin 스코프 전역 탐색.
- **마켓플레이스** — GitHub 저장소·git URL·로컬 디렉터리를 플러그인 마켓플레이스로 등록·동기화.
- **사용량 추적** — Claude 토큰 사용량·비용을 모델별 단가로 계산. today / week / month / 5시간 빌링 블록 / session 뷰.
- **플랜 예산** — 일/주/월 예상치와 예산 바를 포함한 플랜 개요.
- **컨텍스트 분석** — 세션 시작 시 컨텍스트 소스별 토큰 추정(CLAUDE.md, 스킬, MCP 도구, 훅 등).
- **인터랙티브 TUI** — 메인 탭 3개(Extensions / Context / Usage), 키보드 중심 내비게이션. curses 절대좌표 셀 드로잉이라 터미널 멀티플렉서에서도 정확히 렌더(WezTerm + cmux 검증).
- **Claude Skill** — 루트의 `SKILL.md`가 `axt`를 Claude Code 스킬로 노출(영문 + 한글 트리거).

런타임은 순수 표준 라이브러리 — 외부 Python 의존성 없음. Windows는 추가로 `windows-curses` 필요.

## 설치

런타임은 순수 stdlib — 풀어야 할 의존성 없음. Python 3.9+ 만 있으면 됨.

### 빠른 설치 (가장 쉬움 — 한 줄, clone 불필요)

`axt`는 git에서 바로 설치된다. [pipx](https://pipx.pypa.io) 권장(venv 격리 + `axt`를 PATH에 등록):

```bash
pipx install "git+https://github.com/greeun/agent-extension-tool.git"
axt --version          # axt 1.5.0
```

> **pipx 없음?** `python3 -m pip install --user pipx && python3 -m pipx ensurepath` 실행 → 셸 재시작 → 위 명령 실행.
> **그냥 pip?** `pip install --user "git+https://github.com/greeun/agent-extension-tool.git"` 도 동일하게 동작(venv 격리만 안 됨).

업데이트는 `pipx upgrade axt`, 제거는 `pipx uninstall axt`.

### 소스에서 설치 (개발용)

clone 후 editable 설치 → 코드 수정이 바로 반영. `[dev]`는 pytest 추가(테스트 실행 시에만 필요):

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

> Windows에서는 `axt skill link` / `unlink`를 쓸 수 없습니다(심볼릭 링크에 관리자 권한 필요). 그 외 기능은 정상 동작.

### (선택) Claude Skill 활성화

```bash
ln -s "$(pwd)" ~/.claude/skills/agent-extension-tool
```

이제 플러그인·스킬·MCP·사용량·vault·마켓플레이스·컨텍스트 작업을 언급하면 Claude Code가 `axt`를 자동으로 인식합니다. 트리거 문구(영문 + 한글)는 `SKILL.md` 상단 `description:` 줄에 정의되어 있습니다.

## 빠른 시작

```bash
# 인터랙티브 TUI 실행
axt
axt --theme light                  # 이번 실행만 테마 강제 (auto / dark / light)

# 조회 (읽기 전용 — 언제든 안전하게 실행)
axt plugin list
axt skill list
axt mcp list
axt hook list
axt market list
axt usage today
axt vault list
axt context

# 변경 (~/.claude/ 를 건드림 — 실행 전 확인)
axt market add github:user/repo
axt market sync
axt plugin enable <plugin-id>
axt mcp disable <server-name>      # 프로젝트 스코프 (disabledMcpServers)
axt hook disable <index>          # index는 `axt hook list`에서 확인
axt vault link-global <type> <name>
```

전체 CLI 목록: [`FEATURES.md`](./FEATURES.md).

## 업데이트

```bash
cd agent-extension-tool
git pull
# editable 설치라 코드 변경은 자동 반영.
# 의존성이나 엔트리포인트가 바뀐 경우에만 pip 재실행:
pip install -e .[dev]
```

## 제거

`axt`는 자기 경로에만 기록합니다. 설치를 지워도 `~/.claude/` 디렉터리는 건드리지 않습니다.

```bash
# 1) pipx로 설치한 경우
pipx uninstall axt

# 1') venv + 심볼릭 링크로 설치한 경우
rm ~/.local/bin/axt           # 심볼릭 링크를 걸었다면
deactivate                    # venv 안이라면
rm -rf agent-extension-tool   # 클론한 저장소

# 2) (선택) axt 자체 데이터 삭제
rm -rf ~/.config/axt          # 사용자 설정
rm -rf ~/.claude/vault        # vault 저장소 (복구 불가)
# 프로젝트별 프로파일: 각 프로젝트에서 실행
rm -f .axt-profile.json
```

> `~/.claude/` **자체를 삭제하지 마세요** — axt가 아니라 Claude Code의 디렉터리입니다.

## 테스트

```bash
pytest                            # 전체 스위트
pytest tests/test_vault.py        # 단일 파일
pytest -k "marketplace"           # 이름 매칭
```

## 저장소 구조

```
axt/                Python 패키지 (# ── Section N: 앵커로 섹션 보존)
├── __init__.py     공개 API + 서브모듈 미러
├── __main__.py     `python3 -m axt` 엔트리
├── core.py         Section 1-9: 도메인 (paths, JSON I/O, settings, plugin,
│                   skill, MCP, hooks, commands, agents, vault, marketplace,
│                   usage, pricing, context, project usage)
├── cli.py          Section 10 + 15: argparse + `main` 엔트리
├── pricing.json    모델 단가 테이블 (모델 추가 시 여기만 수정 — 코드 변경 불필요)
└── tui/
    ├── widgets.py  Section 11-12: curses 헬퍼 + 공통 위젯
    ├── tabs.py     Section 13: 탭 렌더링 + 입력 디스패치
    └── loop.py     Section 14: TUI 메인 루프 + launch_tui

pyproject.toml      패키지 메타데이터, 엔트리포인트: axt:main
tests/              pytest 스위트, 도메인별 test_*.py 하나씩
DESIGN.md           재작성 배경 + Phase-C 패키지 분할
FEATURES.md         기능 목록
SKILL.md            Claude Code 스킬 매니페스트
MIGRATION.md        업그레이드 안내: v0.1.x→v0.2.0, v0.2.x→v1.0.0 (영문; 한글은 MIGRATION.ko.md)
legacy-ts/          동결된 TypeScript+Ink 구현 (v0.1.x 라인)
```

## 라이선스

MIT — [LICENSE](./LICENSE) 참고.
