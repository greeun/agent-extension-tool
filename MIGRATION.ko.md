# axt v0.1.x → v1.0.0 마이그레이션 가이드

기존 TypeScript+Ink axt(`v0.1.x`, `bun link` 기반)에서 새 Python+curses axt(`v1.0.0`, `pip install -e .` 기반)로 갈아타는 절차입니다.

## 한눈에 보기

| 항목 | 이전 (v0.1.x) | 새 버전 (v1.0.0) |
|---|---|---|
| 언어/런타임 | TypeScript + Bun + Ink | Python 3.9+ + curses |
| 의존성 | npm 패키지 (chalk/commander/ink/react …) | 표준 라이브러리만 |
| 글로벌 등록 | `bun link` → `~/.bun/bin/axt` | `pip install -e .` → venv `bin/axt` |
| 빌드 산출물 | `node_modules/`, `dist/` | `.venv/`, `*.egg-info/` |
| 명령 인터페이스 | 동일 (`axt …`) | **동일** — 사용자 입장 변화 없음 |

> **CLI 명령과 출력 형식은 그대로입니다.** `axt market list`, `axt usage today`, `axt vault list` 등 기존에 쓰던 명령은 그대로 동작합니다.

## 사용자 데이터는 그대로 보존됩니다

두 버전이 **같은 경로**에 읽고 씁니다. 마이그레이션 중에 이 파일들은 건드리지 않아도 됩니다.

| 경로 | 내용 |
|---|---|
| `~/.config/axt/config.json` (macOS/Linux) / `%APPDATA%\axt\config.json` (Windows) | axt 사용자 설정 (플랜 등) |
| `~/.claude/vault/` | vault 저장소 |
| `<project>/.axt-profile.json` | 프로젝트별 vault 프로필 |
| `~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.cursor/` | 각 플랫폼 CLI의 자체 디렉토리 (axt가 **읽기만** 함) |

데이터 포맷도 동일합니다. config/vault/profile 모두 v0.1.x에서 만든 것을 v1.0.0이 그대로 읽습니다.

---

## 1. 이전 버전(v0.1.x) 제거

### macOS / Linux

```bash
# 1) 글로벌 shim 해제 — 반드시 cloned 디렉토리 안에서 실행
cd <기존 agent-extension-tool 경로>
bun unlink

# 2) cloned 디렉토리 삭제
cd ..
rm -rf agent-extension-tool

# 3) 명령이 사라졌는지 확인 (출력이 없어야 함)
command -v axt
```

### Windows (PowerShell)

```powershell
cd <기존 agent-extension-tool 경로>
bun unlink

cd ..
Remove-Item -Recurse -Force agent-extension-tool

Get-Command axt -ErrorAction SilentlyContinue   # 출력이 없어야 함
```

### bun shim이 남아 있을 때

`bun unlink`를 안 거치고 디렉토리만 삭제했다면 `~/.bun/bin/axt`가 깨진 symlink로 남을 수 있습니다.

```bash
# 깨진 shim 강제 제거
rm -f ~/.bun/bin/axt
command -v axt   # 출력이 없어야 함
```

Windows는 `%USERPROFILE%\.bun\bin\axt.*`에서 동일한 처리가 필요합니다.

---

## 2. 새 버전(v1.0.0) 설치

### macOS / Linux

```bash
# 1) Python 3.9 이상 확인
python3 --version

# 2) 클론
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool

# 3) 가상환경 + 설치
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# 4) 동작 확인
axt --version          # axt 1.0.0
which axt              # .../agent-extension-tool/.venv/bin/axt
```

`axt` 명령은 venv가 활성화된 상태에서만 PATH에 잡힙니다. 새 터미널에서도 쓰려면 다음 한 줄 중 하나를:

```bash
# 옵션 A: 매 셸 시작 시 자동 활성화
echo 'source ~/<...>/agent-extension-tool/.venv/bin/activate' >> ~/.zshrc

# 옵션 B: venv의 axt를 ~/.local/bin으로 symlink (활성화 없이 사용)
ln -s ~/<...>/agent-extension-tool/.venv/bin/axt ~/.local/bin/axt

# 옵션 C: pipx로 격리 설치 (venv 활성화 불필요)
pipx install -e ~/<...>/agent-extension-tool
```

> 권장: 글로벌 사용은 **옵션 C (pipx)** 가 가장 깔끔합니다. pipx가 격리된 venv를 만들고 `~/.local/bin/axt` shim을 자동 등록합니다.

### Windows

```powershell
# 1) Python 3.9 이상 확인
python --version

# 2) 클론
git clone https://github.com/greeun/agent-extension-tool.git
cd agent-extension-tool

# 3) 가상환경 + 설치 (windows-curses 포함)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,windows]"

# 4) 동작 확인
axt --version
Get-Command axt
```

> Windows에서는 `axt skill link` / `unlink`는 여전히 제한됩니다 (symlink 권한 문제). 다른 모든 기능은 정상 동작합니다.

---

## 3. 업데이트

```bash
cd agent-extension-tool
git pull
# 코드 변경만 있으면 pip 재설치 불필요 (editable install)
# 의존성 또는 entry_points가 바뀐 경우만:
pip install -e .[dev]
```

---

## 4. (선택) Claude Skill 활성화

v1.0.0부터 axt를 Claude Code skill로도 노출할 수 있습니다. 저장소 루트의 `SKILL.md`가 manifest입니다.

```bash
# ~/.claude/skills/agent-extension-tool 가 이 저장소를 가리키도록
ln -s "$(pwd)" ~/.claude/skills/agent-extension-tool
```

활성화 후 Claude Code 안에서 "axt", "플러그인 목록", "클로드 사용량", "마켓플레이스" 등의 표현으로 axt가 자동 호출됩니다. 전체 트리거 phrase는 `SKILL.md` 상단의 `description:` 줄에 있습니다.

---

## 5. 트러블슈팅

### `axt: command not found`

가상환경이 활성화 안 됐을 가능성. `source .venv/bin/activate` 후 다시 시도하거나, 위의 옵션 B/C(symlink 또는 pipx)로 글로벌 등록.

### `Permission denied` (Linux/macOS)

`~/.local/bin`이 PATH에 없을 수 있음. 다음 한 줄을 `~/.zshrc` 또는 `~/.bashrc`에 추가:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 두 버전이 동시에 PATH에 있음

`which -a axt` (macOS/Linux) 또는 `Get-Command axt -All` (Windows)로 확인. `~/.bun/bin/axt`(옛것)와 `~/.local/bin/axt` 또는 `.venv/bin/axt`(새것)가 같이 보이면 옛것을 먼저 제거.

### `windows-curses` 설치 실패 (Windows)

Python 3.13에서 일부 버전이 깨질 수 있음. 명시적으로 최신 버전 시도:

```powershell
pip install --upgrade pip
pip install -e ".[dev,windows]"
```

### 출력이 깨짐 (CJK 폭/색상)

새 버전은 `unicodedata.east_asian_width`로 너비를 계산하지만, 터미널이 East Asian Ambiguous를 어떻게 다루는지에 따라 차이가 있을 수 있습니다. WezTerm + cmux 조합은 명시적으로 검증됐고, v0.1.x에서 발생하던 selected 행 ▸/번호 사라짐 버그는 해결됐습니다.

---

## 6. (참고) 정말 옛 TS 버전을 다시 돌려야 한다면

새 저장소의 `legacy-ts/` 디렉토리에 v0.1.x가 freeze된 채로 남아 있습니다. 이전 동작이 필요하면 그 디렉토리에서 그대로 실행 가능합니다 (전역 `axt`는 새 v1.0.0이므로 충돌하지 않도록 직접 호출):

```bash
cd legacy-ts
bun install
bun run dev          # 또는: bun run bin/axt.ts <subcommand>
```

`legacy-ts/`는 더 이상 갱신되지 않습니다. 이슈/기능 요청은 v1.0.0 기준으로 받습니다.

---

## 7. 데이터를 완전히 지우고 싶다면

axt가 만든 파일만 골라 지웁니다. 플랫폼 CLI의 자체 디렉토리(`~/.claude/`, `~/.codex/` 등)는 **삭제하지 마세요** — 그 CLI들의 것입니다.

```bash
# axt 설정만
rm -rf ~/.config/axt           # macOS/Linux
# Remove-Item -Recurse -Force "$env:APPDATA\axt"   # Windows

# vault 데이터 (되돌릴 수 없음)
rm -rf ~/.claude/vault

# 프로젝트별 프로필 (각 프로젝트 디렉토리에서)
rm -f .axt-profile.json
```
