# axt — Agent eXtension Tool

여러 AI 에이전트 플랫폼(Claude Code, Codex, Gemini CLI, Cursor)의 확장, 플러그인, 스킬, MCP 서버를 관리하고 사용량과 비용을 추적하는 통합 CLI & TUI 대시보드입니다.

## 주요 기능

- **멀티 플랫폼 사용량 추적** — Claude Code, OpenAI Codex, Google Gemini CLI, Cursor IDE의 토큰 사용량과 비용을 한곳에서 모니터링
- **플러그인 관리** — 마켓플레이스에서 플러그인 설치, 활성화/비활성화, 업데이트, 제거
- **스킬 관리** — 사용자, 프로젝트, 플러그인 소스의 스킬을 탐색하고 관리
- **에이전트 탐색** — 사용자, 프로젝트, 플러그인 디렉토리의 에이전트 브라우징
- **마켓플레이스 시스템** — GitHub 리포, git URL, 로컬 디렉토리를 플러그인 마켓플레이스로 등록
- **인터랙티브 TUI** — 키보드 중심의 터미널 대시보드
- **비용 예측** — 일별 트렌드, 빌링 블록 분석, 통화 변환(USD/KRW) 지원 예산 추적

## 설치

[Bun](https://bun.sh) 런타임과 [Git](https://git-scm.com)이 필요합니다.

### macOS / Linux

```bash
# 1. Bun 설치 (이미 설치되어 있으면 건너뜀)
curl -fsSL https://bun.sh/install | bash

# 2. 클론 및 의존성 설치
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool
bun install

# 3. `axt` 명령을 전역에 등록
bun link

# 4. 확인
axt --version
which axt
```

`bun link`는 이 디렉토리를 `package.json`의 `bin.axt` 소스로 등록합니다. 전역 심볼릭 링크는 Bun의 bin 디렉토리(보통 `~/.bun/bin/axt`)에 만들어지므로 해당 경로가 `PATH`에 포함되어 있어야 합니다.

### Windows

[Windows Terminal](https://aka.ms/terminal) (권장) 과 Bun for Windows가 필요합니다.

```powershell
# 1. Bun 설치
powershell -c "irm bun.sh/install.ps1 | iex"

# 2. 클론 및 의존성 설치
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool
bun install

# 3. 전역 링크
bun link

# 4. 확인
axt --version
```

> **참고:** Windows에서는 `axt skill link` / `unlink` 명령을 사용할 수 없습니다 (symlink에 관리자 권한 필요). 그 외 모든 기능은 정상 동작합니다.

### 업데이트

```bash
cd agent-extension-tool
git pull
bun install
# 전역 링크는 이 디렉토리를 가리키고 있으므로 `bun link`를 다시 실행할 필요가 없습니다.
```

## 제거

`axt`는 `bun link`로 만든 전역 shim과 클론된 소스 디렉토리로만 구성됩니다. 따라서 제거는 두 단계면 끝납니다. 사용자가 만든 데이터(설정·vault)는 별도 경로에 저장되며, 명시적으로 지우지 않는 한 그대로 유지됩니다.

### macOS / Linux

```bash
# 1. 전역 `axt` shim 제거
#    어떤 패키지를 unlink할지 Bun이 알 수 있도록 클론한 디렉토리 안에서 실행합니다.
cd agent-extension-tool
bun unlink

# 2. 클론한 소스 삭제
cd ..
rm -rf agent-extension-tool

# 3. 명령이 사라졌는지 확인
command -v axt   # 아무것도 출력되지 않아야 정상
```

### Windows (PowerShell)

```powershell
cd agent-extension-tool
bun unlink

cd ..
Remove-Item -Recurse -Force agent-extension-tool

Get-Command axt -ErrorAction SilentlyContinue   # 결과가 없어야 정상
```

### 사용자 데이터 제거 (선택)

`axt`는 각 에이전트 플랫폼의 디렉토리(`~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.cursor/`)를 **읽기만** 합니다. 해당 디렉토리는 각 CLI가 직접 관리하는 데이터이므로 **절대 삭제하지 마세요**.

`axt`가 직접 생성/기록하는 경로는 다음뿐입니다.

| 경로 | 용도 | 삭제해도 되는가 |
|------|------|----------------|
| `~/.config/axt/config.json` (macOS/Linux) | axt 사용자 설정 | 가능 |
| `%APPDATA%\axt\config.json` (Windows) | axt 사용자 설정 | 가능 |
| `~/.claude/vault/` | axt vault 저장소 (`axt vault`로 생성됨) | vault 기능을 쓰지 않을 때만 |
| `<project>/.axt-profile.json` | 프로젝트별 vault 프로필 | vault 기능을 쓰지 않을 때만 |

```bash
# axt 자체 설정만 정리 (macOS/Linux)
rm -rf ~/.config/axt

# vault 데이터 삭제 — 복구 불가
rm -rf ~/.claude/vault
```

## 빠른 시작

```bash
# 인터랙티브 TUI 대시보드 실행
axt tui

# 또는 CLI 명령어 직접 사용
axt usage today
axt plugin list
axt skill list
axt market list
```

## CLI 명령어

### 사용량 추적

```bash
axt usage today                     # 오늘의 사용량 요약
axt usage week                      # 주간 분석
axt usage month                     # 월간 비용 및 예산 비교
axt usage blocks                    # 5시간 빌링 블록 리포트
axt usage session <id>              # 특정 세션 상세

# 옵션
--platform claude|codex|gemini|all  # 플랫폼 필터
--since 2025-01-01                  # 시작 날짜
--json / --csv                      # 내보내기 형식
```

### 플러그인 관리

```bash
axt plugin list                     # 설치된 플러그인 목록
axt plugin enable <id>              # 플러그인 활성화
axt plugin disable <id>             # 플러그인 비활성화
axt plugin info <id>                # 플러그인 메타데이터
axt plugin remove <id>              # 플러그인 제거
axt plugin search <query>           # 마켓플레이스 검색
```

### 스킬 관리

```bash
axt skill list                      # 전체 스킬 목록
axt skill link <path>               # 스킬 디렉토리 링크 (macOS/Linux 전용)
axt skill unlink <name>             # 스킬 링크 해제 (macOS/Linux 전용)
```

### 마켓플레이스

```bash
axt market list                     # 등록된 마켓플레이스
axt market add github:user/repo     # GitHub 마켓플레이스 추가
axt market add git:<url>            # git 기반 마켓플레이스 추가
axt market add dir:/local/path      # 로컬 디렉토리 추가
axt market sync [name]              # 마켓플레이스 동기화
axt market remove <name>            # 마켓플레이스 제거
```

### MCP 서버

```bash
axt mcp list                        # 활성 플러그인의 MCP 서버 목록
axt mcp info <name>                 # 서버 설정 정보
```

### 플랜 관리

```bash
axt plan                            # 전체 플랫폼 개요
axt plan set claude max-5x          # 플랫폼별 플랜 설정
```

## TUI 대시보드

`axt tui` 또는 `axt`로 실행합니다.

### 메인 탭 (1-7)

| # | 탭 | 설명 |
|---|-----|------|
| 1 | **Extensions** | 스킬, 훅, 커맨드, 에이전트, 플러그인, 마켓플레이스 |
| 2 | **Project** | CLAUDE.md, 설정 파일, 메모리 파일 |
| 3 | **Dashboard** | 크로스 플랫폼 비용 개요 및 예측 |
| 4 | **Claude** | Claude Code 토큰 사용량 및 비용 |
| 5 | **Codex** | OpenAI Codex CLI 사용량 |
| 6 | **Gemini** | Google Gemini CLI 사용량 |
| 7 | **Cursor** | Cursor IDE AI 코드 기여도 분석 |

### 키보드 단축키

| 키 | 동작 |
|----|------|
| `←` `→` | 메인 탭 전환 |
| `1`-`7` | 탭 바로 이동 |
| `Tab` | Extensions 서브탭 전환 |
| `j` / `k` | 목록 위/아래 스크롤 |
| `r` | 데이터 새로고침 |
| `?` | 도움말 팝업 |
| `q` / `Esc` | 종료 |

### Extensions 서브탭 단축키

| 서브탭 | 단축키 |
|--------|--------|
| Skills | `u` 링크 해제, `l` 링크 (macOS/Linux 전용) |
| Plugins | `e` 활성화/비활성화, `r` 제거, `u` 업데이트, `i` 설치, `/` 검색 |
| Marketplace | `s` 동기화, `r` 제거, `a` 추가 |

### 반응형 레이아웃

- 터미널 폭에 따라 탭 라벨 자동 축약 (100칸 미만 시 컴팩트 모드)
- 실시간 리사이즈 대응
- 긴 목록 스크롤 윈도우 (Cursor 커밋 목록)
- CJK/전각 문자 테이블 컬럼 정렬 지원

## 지원 플랫폼 및 모델

### Claude Code
- Claude Opus 4.7 / 4.6
- Claude Sonnet 4.6
- Claude Haiku 4.5

### OpenAI Codex
- GPT-5, GPT-5.2, GPT-5.3, GPT-5.4-codex

### Google Gemini
- Gemini 2.5 Pro / Flash / Flash-Lite
- Gemini 3.1 Pro Preview

### Cursor IDE
- SQLite 기반 AI 코드 기여도 추적

## 설정

설정 파일:
- macOS / Linux: `~/.config/axt/config.json`
- Windows: `%APPDATA%\axt\config.json`

```json
{
  "currency": ["usd", "krw"],
  "exchangeRate": 1400,
  "monthlyBudget": 100,
  "timezone": "Asia/Seoul",
  "locale": "ko-KR",
  "plans": {
    "claude": { "plan": "max-5x", "monthlyCost": 100 },
    "codex": { "plan": "pro", "monthlyCost": 200 },
    "gemini": { "plan": "free", "monthlyCost": 0 }
  }
}
```

## 데이터 소스

| 플랫폼 | 소스 경로 |
|--------|----------|
| Claude | `~/.claude/projects/{name}/.usage.jsonl` |
| Codex | `~/.codex/sessions/**/*.jsonl` |
| Gemini | `~/.gemini/tmp/*/chats/session-*.json` |
| Cursor | `~/.cursor/ai-tracking/ai-code-tracking.db` |
| Plugins | `~/.claude/plugins/installed_plugins.json` |
| Skills | `~/.claude/skills/` |
| Agents | `~/.claude/agents/` |

## 기술 스택

- **런타임**: [Bun](https://bun.sh)
- **CLI**: [Commander.js](https://github.com/tj/commander.js)
- **TUI**: [Ink](https://github.com/vadimdemedes/ink) (React for CLI)
- **언어**: TypeScript

## 라이선스

MIT
