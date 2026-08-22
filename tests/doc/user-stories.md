# axt 유저스토리

axt(Agent eXtension Tool)가 제공해야 할 가치를 사용자 관점에서 기술한다.
**테스트의 기대값은 이 문서와 `FEATURES.md`에서 나온다. 현재 구현의 반환값에서 나오지 않는다.**

- 스펙 출처 우선순위: `FEATURES.md` > `CLAUDE.md` > argparse 정의 > dataclass 계약 > 기존 통과 테스트
- 각 스토리는 `US-<에픽약어><번호>` 로 식별하며 `TRACEABILITY.md` 에서 시나리오·TC와 연결된다

---

## 페르소나

| ID | 페르소나 | 관심사 |
|---|---|---|
| **P1** | 멀티프로젝트 개발자 | 프로젝트를 오가며 어떤 확장이 켜져 있는지 즉시 파악·전환 |
| **P2** | 확장 큐레이터 | 흩어진 skill/command/agent를 한곳에 모아 여러 프로젝트에 배포 |
| **P3** | 비용 관리자 | 토큰 사용량·비용·플랜 한도 추적, 예산 초과 예측 |
| **P4** | 컨텍스트 최적화자 | 세션 시작 컨텍스트를 줄여 실사용 윈도우 확보 |
| **P5** | 자동화/CI | `--json` 으로 스크립트에서 상태 조회 및 무인 적용 |

## 에픽

| ID | 에픽 | 스토리 수 |
|---|---|---|
| E-VLT | Vault — 확장 보관·배포 | 9 |
| E-LNK | Skill / Command / Agent 링크 관리 | 6 |
| E-PLG | Plugin | 6 |
| E-MKT | Marketplace | 5 |
| E-MCP | MCP 서버 | 5 |
| E-HK | Hook | 4 |
| E-UPD | Update | 6 |
| E-USG | Usage / Cost / Plan | 8 |
| E-CTX | Context 분석 | 6 |
| E-PRJ | Project 프로필 | 5 |
| E-TUI | TUI 탐색·조작 | 10 |
| E-SYS | 설치·기동·설정·데이터 안전성 | 8 |
| | **합계** | **78** |

---

## E-VLT — Vault (확장 보관·배포)

### US-VLT01 — 흩어진 확장을 vault 한곳으로 모은다
- **As a** P2 확장 큐레이터
- **I want** `~/.claude/{skills,commands,agents}` 에 흩어진 실체를 `~/.axt/vault/` 로 옮기고 원위치에 심볼릭 링크를 남기고
- **So that** Claude Code 동작을 깨지 않으면서 확장을 한곳에서 버전 관리할 수 있다
- **인수 조건**
  - AC1 `axt vault migrate` 는 실체를 vault로 **이동**하고 원위치에 vault를 가리키는 symlink를 만든다
  - AC2 대상이 사라진 broken symlink는 **이동하지 않고** `broken` 으로만 리포트하며 **삭제하지 않는다**
  - AC3 결과는 moved / skipped / broken / errors 건수로 보고된다
  - AC4 이미 vault에 있는 항목은 skipped로 분류되며 중복 이동하지 않는다
- **출처** FEATURES.md §1.10, §3.4

### US-VLT02 — vault에 무엇이 있고 어디에 연결됐는지 본다
- **As a** P2
- **I want** vault의 모든 확장과 각 항목의 project/global 링크 상태를 한 표로 보고
- **So that** 어떤 확장이 어디서 활성인지 추적할 수 있다
- **인수 조건**
  - AC1 `axt vault list` 는 name / type / 링크 상태를 출력한다
  - AC2 vault가 비어 있으면 오류가 아니라 빈 목록과 안내를 출력하고 exit 0
  - AC3 `list_vault_items_with_project_state` 는 project/global 링크 여부를 항목별로 채운다
- **출처** FEATURES.md §1.10, §3.4

### US-VLT03 — 임의 경로의 확장을 vault에 담는다
- **As a** P2
- **I want** 로컬 경로의 skill/command/agent를 `-t` 로 타입을 지정해 vault에 추가하고
- **So that** 직접 만든 확장도 동일한 배포 경로를 탄다
- **인수 조건**
  - AC1 `axt vault add <path> -t skill` 은 경로를 vault의 해당 타입 하위로 복사한다
  - AC2 `-t` 미지정 시 경로 형태(디렉터리+SKILL.md / `.md` 파일)로 타입을 추론한다
  - AC3 존재하지 않는 경로는 exit 1 + stderr 오류 메시지
  - AC4 같은 이름이 이미 vault에 있으면 덮어쓰지 않고 명확히 실패한다
- **출처** FEATURES.md §1.10

### US-VLT04 — 마켓플레이스에서 vault로 바로 설치한다
- **As a** P2
- **I want** `axt vault install <marketplace> <name>` 로 마켓의 확장을 vault에 바로 넣고
- **So that** 수동 다운로드·복사 단계를 건너뛴다
- **인수 조건**
  - AC1 등록되지 않은 마켓플레이스명은 exit 1 + 사용 가능한 마켓 안내
  - AC2 마켓에 없는 확장명은 exit 1
  - AC3 성공 시 vault에 항목이 생기고 `vault list` 에 나타난다
- **출처** FEATURES.md §1.10

### US-VLT05 — vault 확장을 전역에 켜고 끈다
- **As a** P1
- **I want** vault 항목을 `~/.claude/{type}s/` 에 심볼릭 링크로 걸고 해제하고
- **So that** 모든 프로젝트에서 쓸 확장을 한 번에 켤 수 있다
- **인수 조건**
  - AC1 `vault link-global <type> <name>` 은 `~/.claude/<type>s/<name>` symlink를 만든다
  - AC2 `vault unlink-global` 은 symlink만 제거하고 **vault 실체는 남긴다**
  - AC3 vault에 없는 이름은 exit 1
  - AC4 Windows에서는 symlink 미지원 안내로 graceful degrade (크래시 금지)
- **출처** FEATURES.md §1.10, §3.4, §7.1

### US-VLT06 — 스킬을 다른 에이전트 도구와 공유한다
- **As a** P2
- **I want** `--mirror-agents` 로 skill을 `~/.agents/skills/` 에도 미러링하고
- **So that** Claude Code 외 도구에서도 같은 스킬 원본을 쓴다
- **인수 조건**
  - AC1 미러 symlink는 `~/.claude/skills/` 가 아니라 **vault 원본을 직접** 가리킨다
  - AC2 `.skill-lock.json` 이 있는 트리(서드파티 설치기 소유)는 **기본 거부**한다
  - AC3 `--force-agents` 를 주면 잠금을 무시하고 진행한다
  - AC4 `unlink-global --mirror-agents` 는 **이 vault 항목을 가리킬 때만** 미러를 제거한다
  - AC5 미러는 skill 타입에만 적용된다
- **출처** FEATURES.md §1.10, §3.4

### US-VLT07 — 쓰는 확장과 안 쓰는 확장을 구분한다
- **As a** P2
- **I want** 각 vault 항목이 몇 개 프로젝트에서 실제로 쓰이는지 보고
- **So that** 안 쓰는 확장을 정리할 근거를 얻는다
- **인수 조건**
  - AC1 `scan_project_usage` 는 `~/.claude/projects/*` 를 훑어 항목별 사용 프로젝트 목록을 만든다
  - AC2 `default` 모드는 프로필+심볼릭 링크, `full` 모드는 플러그인 설정까지 포함한다
  - AC3 프로젝트 폴더명 인코딩(`/`·`.` → `-`)을 역으로 해석해 실제 경로를 찾는다
  - AC4 스캔 결과가 없어도 오류 없이 0건으로 처리된다
- **출처** FEATURES.md §3.12

### US-VLT08 — 여러 확장을 한 번에 정리한다
- **As a** P2
- **I want** TUI에서 여러 항목을 마크해 일괄 토글/해제하고
- **So that** 항목마다 반복 조작하지 않는다
- **인수 조건**
  - AC1 `Space` 로 마크한 항목이 있으면 `p`/`g` 가 마크 전체에 적용된다
  - AC2 `U` 는 마크된 항목을 모든 프로젝트에서 unlink 한다 (확인 모달 필수)
  - AC3 마크는 정렬·검색이 바뀌어도 유지된다
  - AC4 `Esc` 는 마크 해제 → 검색 해제 → 포커스 상승 순으로 한 단계씩 되돌린다
- **출처** FEATURES.md §2.5

### US-VLT09 — 되돌릴 수 없는 조작 전에 확인받는다
- **As a** P1
- **I want** 링크 토글이 pending으로 쌓였다가 `Enter` 확인 후에만 적용되고
- **So that** 실수로 확장을 끄는 사고를 막는다
- **인수 조건**
  - AC1 `p`/`g` 는 즉시 반영하지 않고 pending 상태로 표시한다(`*` 마커)
  - AC2 `Enter` 는 확인(y/N) 후 pending을 일괄 적용한다
  - AC3 `Esc` 는 pending을 폐기한다
  - AC4 파괴적 명령(`U`, `x`, `remove`)은 확인 모달 없이 실행되지 않는다
- **출처** FEATURES.md §2.5

---

## E-LNK — Skill / Command / Agent 링크 관리

### US-LNK01 — 모든 위치의 스킬을 한 표에서 본다
- **As a** P1
- **I want** user / project / plugin / vault 어디에 있든 스킬을 한 목록으로 보고
- **So that** 이름 충돌과 출처를 즉시 파악한다
- **인수 조건**
  - AC1 `axt skill list` 는 4개 출처를 병합해 Source 컬럼으로 구분한다
  - AC2 symlink 항목은 실제 대상 경로를 보여준다
  - AC3 활성 플러그인의 스킬만 포함한다(비활성 플러그인 제외)
- **출처** FEATURES.md §1.8, §3.7

### US-LNK02 — 임의 디렉터리를 스킬로 연결한다
- **As a** P1
- **I want** `axt skill link <path>` 로 개발 중인 디렉터리를 연결하고
- **So that** 복사 없이 즉시 테스트한다
- **인수 조건**
  - AC1 `-n/--name` 으로 링크 이름을 지정할 수 있고 미지정 시 디렉터리명을 쓴다
  - AC2 Windows에서는 명령 자체가 등록되지 않는다(`is_symlink_supported` false)
  - AC3 존재하지 않는 경로는 exit 1
- **출처** FEATURES.md §1.8, §3.7

### US-LNK03 — 연결만 끊고 원본은 지키다
- **As a** P1
- **I want** `axt skill unlink <name>` 이 symlink만 제거하고
- **So that** 원본 디렉터리를 잃지 않는다
- **인수 조건**
  - AC1 symlink만 삭제하고 대상 실체는 건드리지 않는다
  - AC2 symlink가 아닌 실제 디렉터리는 삭제를 거부한다
  - AC3 없는 이름은 exit 1
- **출처** FEATURES.md §1.8

### US-LNK04 — 프로젝트 단위로 확장을 켠다
- **As a** P1
- **I want** TUI에서 `p` 로 `.claude/<type>/` 에, `g` 로 `~/.claude/<type>/` 에 링크를 걸고
- **So that** 프로젝트별로 필요한 확장만 활성화한다
- **인수 조건**
  - AC1 Skills/Commands/Agents 서브탭의 `p`/`g` 는 symlink 생성·해제로 동작한다
  - AC2 Proj/Glob 컬럼이 `●`(링크됨)/`○`(아님)로 즉시 반영된다
  - AC3 해제는 symlink만 제거하며 실체를 지우지 않는다
- **출처** FEATURES.md §2.6

### US-LNK05 — 외부 확장을 vault로 흡수한다
- **As a** P2
- **I want** `i` 로 기존 확장을 vault로 옮기고 원위치에 symlink를 남기고
- **So that** 관리 대상을 vault로 일원화한다
- **인수 조건**
  - AC1 plugin 소속 항목은 import를 거부한다(읽기 전용)
  - AC2 이미 vault인 항목은 거부한다
  - AC3 성공 시 원위치에 symlink가 남아 Claude Code 동작이 유지된다
- **출처** FEATURES.md §2.6, §3.4

### US-LNK06 — 명령/에이전트를 바로 편집한다
- **As a** P1
- **I want** `e` 로 선택 항목의 소스 파일을 `$EDITOR` 로 열고
- **So that** 경로를 찾아 헤매지 않는다
- **인수 조건**
  - AC1 Commands/Agents 서브탭에서 `e` 는 `source_path` 를 `$EDITOR` 로 연다
  - AC2 `$EDITOR` 미설정 시 안내 메시지를 내고 크래시하지 않는다
- **출처** FEATURES.md §2.6

---

## E-PLG — Plugin

### US-PLG01 — 설치된 플러그인과 활성 상태를 본다
- **As a** P1
- **I want** 설치 플러그인 목록과 project/global 활성 여부를 보고
- **So that** 이 프로젝트에서 무엇이 실제로 동작하는지 안다
- **인수 조건**
  - AC1 `axt plugin list` 는 id / name / version / marketplace / 활성 상태를 낸다
  - AC2 활성 상태는 project settings > global settings 순으로 해석된다
  - AC3 어느 쪽에도 설정이 없으면 `unset`(`·`)으로 구분되며 `off` 와 다르게 표시된다
- **출처** FEATURES.md §1.6, §2.4, §3.3

### US-PLG02 — 스코프를 골라 플러그인을 켜고 끈다
- **As a** P1
- **I want** `--scope global|project` 로 대상 settings 파일을 지정하고
- **So that** 팀 공유 설정과 개인 설정을 분리한다
- **인수 조건**
  - AC1 `axt plugin enable <id>` 기본 스코프는 global
  - AC2 `--scope project` 는 `<proj>/.claude/settings.json` 에 쓴다
  - AC3 쓰기는 원자적이며 기존 키를 보존한다
  - AC4 재시작 필요 안내를 출력한다
- **출처** FEATURES.md §1.6

### US-PLG03 — 플러그인 상세를 확인한다
- **As a** P1
- **I want** `axt plugin info <id>` 로 version·marketplace·경로·설치일을 보고
- **So that** 문제 발생 시 출처를 추적한다
- **인수 조건**
  - AC1 없는 id는 exit 1 + 명확한 메시지
  - AC2 manifest는 `.claude-plugin/plugin.json` 또는 `plugin.json` 순으로 찾는다
- **출처** FEATURES.md §1.6, §3.6

### US-PLG04 — 플러그인을 완전히 제거한다
- **As a** P1
- **I want** 설치 디렉터리와 설정 항목이 함께 지워지고
- **So that** 잔여 설정이 남지 않는다
- **인수 조건**
  - AC1 `axt plugin remove <id>` 는 install dir 삭제 + `installed_plugins.json` + settings 항목을 모두 정리한다
  - AC2 TUI `x` 는 확인 모달 후에만 실행한다
- **출처** FEATURES.md §1.6, §5

### US-PLG05 — 마켓플레이스 전체에서 플러그인을 찾는다
- **As a** P1
- **I want** `axt plugin search <query>` 로 등록된 모든 마켓을 검색하고
- **So that** 어느 마켓에 있는지 몰라도 찾는다
- **인수 조건**
  - AC1 결과 0건도 오류가 아니며 exit 0 + 안내
  - AC2 결과에 소속 마켓플레이스가 표시된다
- **출처** FEATURES.md §1.6

### US-PLG06 — 플러그인이 무엇을 끌고 오는지 안다
- **As a** P4
- **I want** 플러그인이 제공하는 MCP 서버·훅·스킬·명령·에이전트를 알고
- **So that** 컨텍스트 비용과 부작용을 예측한다
- **인수 조건**
  - AC1 활성 플러그인의 MCP 서버가 `mcp list` 에 포함된다
  - AC2 플러그인 훅은 `hook list` 에 포함되며 **읽기 전용**으로 표시된다
  - AC3 플러그인 스킬/명령/에이전트는 각 목록에 `plugin` 출처로 나타난다
- **출처** FEATURES.md §3.6, §3.8, §3.10

---

## E-MKT — Marketplace

### US-MKT01 — 확장 공급원을 등록한다
- **As a** P1
- **I want** `github:user/repo` · `git:<url>` · `dir:<path>` 세 형태로 마켓을 등록하고
- **So that** 공개 저장소든 사내 저장소든 로컬 디렉터리든 같은 방식으로 쓴다
- **인수 조건**
  - AC1 세 접두사를 각각 올바른 `MarketplaceSource` 로 파싱한다
  - AC2 알 수 없는 형태는 exit 1 + 지원 형태 안내
  - AC3 등록 정보는 `known_marketplaces.json` 에 원자적으로 기록된다
- **출처** FEATURES.md §1.3, §3.5

### US-MKT02 — 마켓을 최신으로 맞춘다
- **As a** P1
- **I want** `axt market sync [name]` 로 단일 또는 전체 마켓을 동기화하고
- **So that** 새 플러그인·새 버전을 받는다
- **인수 조건**
  - AC1 이름 생략 시 전체 동기화
  - AC2 이미 최신이면 `up to date` 로 보고하고 exit 0
  - AC3 없는 이름은 exit 1 + stderr `✗`
  - AC4 git 실패(네트워크 등)는 크래시가 아니라 실패 보고로 처리한다
- **출처** FEATURES.md §1.3, §3.5

### US-MKT03 — 등록된 마켓과 버전을 본다
- **As a** P1
- **I want** `axt market list` 로 마켓명·소스 종류·설치 위치·최종 갱신을 보고
- **So that** 오래된 마켓을 식별한다
- **인수 조건**
  - AC1 로컬 버전은 `.gcs-sha` 또는 git rev-parse 로 구한다
  - AC2 버전을 못 구해도 목록 출력은 실패하지 않는다
- **출처** FEATURES.md §1.3, §3.5

### US-MKT04 — 마켓을 정리한다
- **As a** P1
- **I want** `axt market remove <name>` 이 등록 해제와 함께 소유한 설치 디렉터리도 지우고
- **So that** 디스크에 쓰레기가 남지 않는다
- **인수 조건**
  - AC1 axt가 설치한 디렉터리만 삭제한다(`dir:` 로 등록한 외부 경로는 삭제 금지)
  - AC2 없는 이름은 exit 1
- **출처** FEATURES.md §1.3

### US-MKT05 — 업데이터가 더럽힌 트리에서도 sync가 성공한다
- **As a** P1
- **I want** 마켓 설치 디렉터리가 dirty해도 sync가 upstream 최신으로 맞춰지고
- **So that** Claude Code 자체 업데이터가 파일을 덮어쓴 뒤에도 마켓 갱신이 계속 동작한다
- **인수 조건**
  - AC1 설치 디렉터리는 **사용자 작업 공간이 아니라 관리 대상 캐시**다. sync는
    `git fetch` + `git reset --hard @{u}` 로 upstream head에 강제 정렬한다
  - AC2 커밋되지 않은 로컬 수정은 업데이터 산출물로 간주해 **폐기된다** (보존 대상 아님)
  - AC3 `fetch` 또는 `reset` 실패 시 명확한 사유와 함께 실패로 보고하며,
    `known_marketplaces.json` 레지스트리는 변경되지 않는다
  - AC4 `directory` 소스 마켓은 git을 쓰지 않으므로 git 부재 상태에서도 성공한다
- **출처** FEATURES.md §3.5 (v1.11.0에서 `pull --ff-only` → hard-sync로 변경),
  `axt/core.py` `sync_marketplace` 주석, `test_sync_marketplace_git_dirty_tree_hard_syncs`
- **주의** 이 스토리는 원래 "로컬 수정을 잃지 않는다"로 작성됐다가, 낡은 `FEATURES.md`
  기술에서 파생된 것임이 확인되어 실제 계약에 맞게 뒤집혔다. 상세 경위는
  `tests/doc/SPEC_DECISIONS.md` 참조

---

## E-MCP — MCP 서버

### US-MCP01 — 모든 출처의 MCP 서버를 한 목록에서 본다
- **As a** P1
- **I want** plugin manifest / user `~/.claude.json` / project entry / `<proj>/.mcp.json` / claude.ai 커넥터 / built-in 을 병합해 보고
- **So that** 어디서 온 서버인지 헷갈리지 않는다
- **인수 조건**
  - AC1 6개 출처가 모두 병합되며 각 서버에 scope가 붙는다
  - AC2 built-in은 **opt-in**(`enabledMcpServers`), 나머지는 **opt-out**(`disabledMcpServers`)로 활성 여부를 해석한다
  - AC3 이름 충돌 시 해석 규칙이 결정적이다
- **출처** FEATURES.md §3.8

### US-MCP02 — 등록 위치와 활성 상태를 구분해서 본다
- **As a** P1
- **I want** Proj/Glob이 **등록 위치**를, On이 **현재 프로젝트 활성 여부**를 나타내고
- **So that** "등록됐지만 꺼져 있음"을 오해하지 않는다
- **인수 조건**
  - AC1 Proj/Glob은 읽기 전용이며 `p`/`g` 로 등록 위치를 옮길 수 없다
  - AC2 MCP의 `g` 는 안내 메시지만 낸다(전역 활성 스코프 없음)
  - AC3 On 토글은 항상 프로젝트 단위로 기록된다
- **출처** FEATURES.md §2.4, §2.6, §3.8

### US-MCP03 — 프로젝트별로 MCP 서버를 끈다
- **As a** P4
- **I want** 안 쓰는 MCP 서버를 이 프로젝트에서만 끄고
- **So that** MCP 툴 정의가 차지하는 컨텍스트를 줄인다
- **인수 조건**
  - AC1 `axt mcp disable <name>` 은 `~/.claude.json` 의 `projects[<cwd>]` 에 기록한다
  - AC2 다른 프로젝트 설정에 영향을 주지 않는다
  - AC3 재시작 필요 안내를 출력한다
- **출처** FEATURES.md §1.4, §3.8

### US-MCP04 — 서버 상세를 확인한다
- **As a** P1
- **I want** `axt mcp info <name>` 로 command/args/env/transport를 보고
- **So that** 실행 실패 원인을 진단한다
- **인수 조건**
  - AC1 없는 이름은 exit 1
  - AC2 원격 서버는 URL을, stdio 서버는 명령줄을 상세로 보여준다
- **출처** FEATURES.md §1.4

### US-MCP05 — MCP 자격증명이 새지 않는다
- **As a** P1 (보안 관심사)
- **I want** env에 담긴 토큰·키가 목록/상세/로그에 평문으로 노출되지 않고
- **So that** 화면 공유·이슈 첨부 시 사고가 나지 않는다
- **인수 조건**
  - AC1 `mcp list` 는 env 값을 출력하지 않는다
  - AC2 `mcp info` 가 env를 보여준다면 값은 마스킹되어야 한다
  - AC3 TUI detail 패널도 같은 규칙을 따른다
- **출처** 보안 요구(스펙 갭 — §F-3 확인 대상)

---

## E-HK — Hook

### US-HK01 — 어떤 훅이 언제 도는지 본다
- **As a** P1
- **I want** user/project/local/plugin 4개 출처의 훅을 이벤트별로 보고
- **So that** 예기치 않은 자동 동작의 출처를 찾는다
- **인수 조건**
  - AC1 4개 출처가 병합되고 `disabledHooks` 미러도 파싱해 `[off]` 로 표시한다
  - AC2 `hook list` 인덱스는 enable/disable 인자로 그대로 쓸 수 있다
- **출처** FEATURES.md §1.4b, §3.10

### US-HK02 — 훅을 무손실로 끈다
- **As a** P1
- **I want** 훅을 지우지 않고 같은 파일의 `disabledHooks` 로 옮기고
- **So that** 나중에 원복할 수 있다
- **인수 조건**
  - AC1 `hooks` ↔ `disabledHooks` 이동은 같은 설정 파일 안에서 일어난다
  - AC2 Claude Code가 `disabledHooks` 를 무시하므로 실질적으로 꺼진다
  - AC3 훅 정의 내용은 손실 없이 보존된다
- **출처** FEATURES.md §3.10

### US-HK03 — 플러그인 훅은 건드리지 않는다
- **As a** P1
- **I want** 플러그인이 제공한 훅의 토글이 거부되고
- **So that** 플러그인 관리 영역을 침범하지 않는다
- **인수 조건**
  - AC1 plugin 출처 훅에 `p`/`g`/`hook disable` 을 시도하면 읽기 전용 안내를 낸다
  - AC2 파일은 변경되지 않는다
- **출처** FEATURES.md §2.6, §3.10

### US-HK04 — 훅이 실제로 무엇을 실행하는지 미리 본다
- **As a** P1
- **I want** `v` 로 훅의 dry-run 결과를 모달로 보고
- **So that** 위험한 명령을 켜기 전에 확인한다
- **인수 조건**
  - AC1 preview는 `sh -c` 로 실행하며 stdout/stderr/exit code를 모두 보여준다
  - AC2 실행 실패도 모달로 보고하며 TUI가 죽지 않는다
  - AC3 긴 출력은 모달 안에서 스크롤된다
- **출처** FEATURES.md §2.6, §3.10

---

## E-UPD — Update

### US-UPD01 — 무엇이 낡았는지 먼저 확인만 한다
- **As a** P1
- **I want** `axt update` 가 기본적으로 **dry-run 리포트**만 내고
- **So that** 의도치 않은 변경 없이 현황을 파악한다
- **인수 조건**
  - AC1 옵션 없는 `axt update` 는 아무것도 변경하지 않는다
  - AC2 Updatable / Up to date / Manual / Delegated 티어별로 그룹핑해 보여준다
  - AC3 마지막에 요약 라인을 낸다
- **출처** FEATURES.md §1.8b

### US-UPD02 — 자동 적용 가능한 것만 골라 적용한다
- **As a** P1
- **I want** `--apply` 가 Tier-1(플러그인·마켓·git-backed 스킬/명령/에이전트)만 적용하고
- **So that** 위임/수동 대상까지 멋대로 건드리지 않는다
- **인수 조건**
  - AC1 Tier-2(MCP·non-git)는 `--apply` 로도 변경되지 않는다
  - AC2 Claude Code 바이너리는 `axt update claude-code --apply` 로 **명시 타깃팅했을 때만** `claude update` 에 위임한다
  - AC3 적용 전 확인 프롬프트가 있고 `-y` 로 생략할 수 있다
- **출처** FEATURES.md §1.8b

### US-UPD03 — 자동화에서 무인 실행한다
- **As a** P5 자동화/CI
- **I want** `--json` 이 확인 프롬프트까지 생략하고 기계가 읽을 형태로 내고
- **So that** 파이프라인에서 블로킹 없이 돌린다
- **인수 조건**
  - AC1 `--json` 은 프롬프트를 띄우지 않는다(non-interactive)
  - AC2 출력이 유효한 JSON이며 사람용 장식 문자가 섞이지 않는다
  - AC3 항목별 상태(updatable/current/manual/delegated)가 담긴다
- **출처** FEATURES.md §1.8b

### US-UPD04 — 특정 대상만 업데이트한다
- **As a** P1
- **I want** `axt update <type> [name]` 으로 범위를 좁히고
- **So that** 전체 스윕 없이 한 항목만 처리한다
- **인수 조건**
  - AC1 지원 type: plugin / marketplace / skill / command / agent / mcp / claude-code / all(기본)
  - AC2 알 수 없는 type은 argparse 단계에서 exit 2
  - AC3 없는 name은 exit 1 + 안내
- **출처** FEATURES.md §1.8b

### US-UPD05 — 업데이트 확인이 화면을 막지 않는다
- **As a** P1
- **I want** TUI의 `Upd` 컬럼이 백그라운드로 채워지고
- **So that** 목록이 즉시 뜨고 조작이 막히지 않는다
- **인수 조건**
  - AC1 첫 확인 중에는 `…`, 완료 후 `↑`/`·`/`!`/`─` 로 바뀐다
  - AC2 결과는 `<AXT_CONFIG_DIR>/cache/update-status.json` 에 TTL 1시간으로 캐시된다
  - AC3 `r` 은 목록 새로고침 + 강제 재확인을 함께 한다
  - AC4 스레드 실패가 TUI를 죽이지 않는다
- **출처** FEATURES.md §2.4

### US-UPD06 — 적용 결과가 즉시 화면에 반영된다
- **As a** P1
- **I want** `u` 적용·sync 성공 시 해당 행의 마커가 바로 최신으로 바뀌고
- **So that** 다시 새로고침하지 않아도 상태를 신뢰한다
- **인수 조건**
  - AC1 성공한 항목의 `Upd` 는 즉시 `·` 로 갱신된다
  - AC2 일괄 적용 시 항목별 실패가 나머지를 중단시키지 않는다
  - AC3 상태바에 `N updated, N up to date, N failed` 집계를 표시한다
- **출처** FEATURES.md §2.4, §2.6

---

## E-USG — Usage / Cost / Plan

### US-USG01 — 오늘/주/월 사용량을 본다
- **As a** P3 비용 관리자
- **I want** `axt usage today|week|month` 로 세션·모델·토큰·비용 요약을 보고
- **So that** 소비 추세를 파악한다
- **인수 조건**
  - AC1 인자 없는 `axt usage` 는 `today` 와 동일하다
  - AC2 기간 경계(오늘/주/월 컷오프)는 **사용자 timezone** 기준이다
  - AC3 데이터가 없으면 오류가 아니라 0건 요약을 내고 exit 0
- **출처** FEATURES.md §1.9, §7.5

### US-USG02 — 원하는 조건으로 걸러 본다
- **As a** P3
- **I want** `--since/--until/--model/--project/--timezone` 으로 범위를 좁히고
- **So that** 특정 프로젝트나 모델의 비용만 본다
- **인수 조건**
  - AC1 잘못된 날짜 형식은 exit 1 + 형식 안내
  - AC2 `--since > --until` 은 오류로 처리한다
  - AC3 필터 조합이 논리곱(AND)으로 적용된다
- **출처** FEATURES.md §1.9

### US-USG03 — 다른 도구로 내보낸다
- **As a** P5
- **I want** `--json` / `--csv` / `--export <path>` 로 결과를 내보내고
- **So that** 스프레드시트·대시보드에 넣는다
- **인수 조건**
  - AC1 `--json` 출력이 유효한 JSON이다
  - AC2 `--csv` 출력의 헤더와 열 수가 모든 행에서 일치한다
  - AC3 `--export` 는 지정 경로에 파일을 쓰고 실패 시 exit 1
- **출처** FEATURES.md §1.9

### US-USG04 — 5시간 빌링 블록을 본다
- **As a** P3
- **I want** 활동 기준으로 나뉜 5h 블록과 현재 블록의 소진 속도를 보고
- **So that** 한도에 언제 닿을지 예측한다
- **인수 조건**
  - AC1 블록 시작은 첫 엔트리 시각을 **시간 단위로 내림(UTC)** 한 지점이다 (벽시계 00/05/10 정렬 아님)
  - AC2 블록 종료(시작+5h) 이후 첫 엔트리가 자기 시각 기준으로 새 블록을 연다
  - AC3 `isActive` 는 `blockStart <= now < blockEnd`
  - AC4 `--active` 는 활성 블록만 보여준다
  - AC5 burn rate = 활성 블록 토큰 / 경과 분
- **출처** FEATURES.md §4.2

### US-USG05 — 특정 세션을 파고든다
- **As a** P3
- **I want** `axt usage session <id>` 가 prefix 매칭으로 세션을 찾고
- **So that** 전체 UUID를 외우지 않는다
- **인수 조건**
  - AC1 prefix 매칭이 유일하면 해당 세션 상세를 낸다
  - AC2 매칭 0건은 exit 1
  - AC3 매칭 다수는 후보를 제시한다
- **출처** FEATURES.md §1.9

### US-USG06 — 비용이 어떻게 계산됐는지 신뢰한다
- **As a** P3
- **I want** 모델별 단가가 코드가 아닌 `pricing.json` 에 있고 4종 토큰이 모두 반영되고
- **So that** 가격 변동 시 코드 수정 없이 맞출 수 있다
- **인수 조건**
  - AC1 비용 = input·output·cacheWrite·cacheRead 각각 (토큰/1M)×단가의 합
  - AC2 `pricing.json` 에 없는 모델은 비용 0으로 집계되고 **경고로 드러난다**
  - AC3 `find_unpriced_models` 가 미등록 모델 목록을 반환한다
  - AC4 Usage 탭이 `⚠ N entries from unpriced models` 경고 라인을 표시한다
- **출처** FEATURES.md §4.3

### US-USG07 — 플랜 대비 예산을 관리한다
- **As a** P3
- **I want** 플랜 월정액 대비 현재 사용액·일평균·월말 예측을 보고
- **So that** 초과 전에 조정한다
- **인수 조건**
  - AC1 플랜은 `~/.claude.json` 기반 자동 감지가 기본이다
  - AC2 `axt plan set <name>` 은 수동 고정(자동 감지 끔), `set auto` 는 재활성화
  - AC3 월말 예측 = 사용액 ÷ 경과일수 × 주기일수
  - AC4 예측이 월정액을 넘으면 초과 경고를 표시한다
  - AC5 경과일수 0(주기 첫날)에도 크래시하지 않는다
- **출처** FEATURES.md §1.5, §3.13

### US-USG08 — 큰 파일에서도 빠르게 뜬다
- **As a** P3
- **I want** JSONL 사용량 파일이 커도 목록이 빠르게 뜨고
- **So that** 조회할 때마다 기다리지 않는다
- **인수 조건**
  - AC1 파일 mtime 기반 캐시를 사용하며 변경 없으면 재파싱하지 않는다
  - AC2 캐시 스키마 v2(intern 테이블 + 위치 배열)를 쓰고 v1 캐시는 폐기 후 재빌드한다
  - AC3 캐시가 손상돼도 재빌드로 복구하며 크래시하지 않는다
- **출처** FEATURES.md §3.13, §7.3

---

## E-CTX — Context 분석

### US-CTX01 — 세션 시작 컨텍스트가 무엇으로 차는지 본다
- **As a** P4 컨텍스트 최적화자
- **I want** 12개 카테고리별 토큰 소비를 보고
- **So that** 무엇을 줄일지 판단한다
- **인수 조건**
  - AC1 12개 카테고리(system-prompt, claude-md, settings, memory, skills, mcp-tools, plugins, hooks, commands, agents, git-status, user-context)를 모두 집계한다
  - AC2 `--detail` 은 카테고리 내 개별 항목을 펼친다
  - AC3 `--category <name>` 으로 하나만 본다
  - AC4 `--json` 은 유효한 JSON을 낸다
- **출처** FEATURES.md §1.2, §4.4

### US-CTX02 — 조정 가능한 항목을 구분한다
- **As a** P4
- **I want** `actionable` 플래그로 내가 바꿀 수 있는 소스를 구분해 보고
- **So that** 고정비(system-prompt 등)에 시간을 낭비하지 않는다
- **인수 조건**
  - AC1 system-prompt(4,200 tok) / user-context(280 tok)는 고정이며 actionable=false
  - AC2 skills·commands·agents·mcp-tools 등은 actionable=true
- **출처** FEATURES.md §4.4

### US-CTX03 — Claude Code가 실제로 읽는 것만 센다
- **As a** P4
- **I want** 집계 대상이 Claude Code의 실제 읽기 경로와 일치하고
- **So that** 잘못된 최적화를 하지 않는다
- **인수 조건**
  - AC1 skills는 `.claude/skills` 만 포함하고 `.agents/skills` 는 **제외**한다
  - AC2 agents는 `.claude/agents` 만 포함하고 `.agents/agents` 는 **제외**한다
  - AC3 settings는 global·project의 `settings*.json` 4곳을 본다
  - AC4 disabled MCP 서버는 제외한다
- **출처** FEATURES.md §4.4

### US-CTX04 — 오래된 메모리를 찾아 지운다
- **As a** P4
- **I want** 90일 이상 미수정 memory에 힌트가 붙고 `d` 로 삭제할 수 있고
- **So that** 낡은 컨텍스트를 정리한다
- **인수 조건**
  - AC1 90일 초과 memory 파일에 `not modified in N days (>90 days)` 힌트가 붙는다
  - AC2 `d` 는 memory 소스일 때만 동작하며 확인 모달을 거친다
  - AC3 삭제 시 `MEMORY.md` 인덱스에서 해당 줄도 제거한다
- **출처** FEATURES.md §2.7, §4.4

### US-CTX05 — 프로젝트 단위로 낱개 소스를 본다
- **As a** P4
- **I want** Project 서브탭이 카테고리로 묶지 않고 개별 소스를 낱개로 나열하고
- **So that** 어떤 파일 하나가 얼마를 먹는지 정확히 안다
- **인수 조건**
  - AC1 `collect_context_sources` 의 flat 결과를 그대로 행으로 만든다
  - AC2 Name/Category/Scope/Tokens/% 컬럼을 갖는다
  - AC3 기본 정렬은 Tokens 내림차순이다
  - AC4 `%` 는 Tokens와 순서가 항상 같아 정렬 순환에서 제외된다
- **출처** FEATURES.md §2.7

### US-CTX06 — 남은 한도를 함께 본다
- **As a** P3 / P4
- **I want** Context 탭 상단에 5h/7d rate limit 스트립이 고정 표시되고
- **So that** 컨텍스트 조정과 한도를 같이 판단한다
- **인수 조건**
  - AC1 스트립은 두 서브탭 공통으로 항상 표시된다
  - AC2 rate limit 데이터가 없거나 낡으면(기본 5분 tolerance) 그 사실을 표시한다
  - AC3 하단 cost impact 라인은 가정(`30 turns × 5 sessions/day`)을 명시한다
- **출처** FEATURES.md §2.7, §4.5

---

## E-PRJ — Project 프로필

### US-PRJ01 — 프로젝트가 쓰는 확장을 선언한다
- **As a** P1
- **I want** `.axt-profile.json` 에 이 프로젝트가 쓰는 확장을 적고
- **So that** 팀원이 같은 구성을 재현한다
- **인수 조건**
  - AC1 `axt project init` 은 빈 프로필을 만든다
  - AC2 이미 있으면 덮어쓰지 않는다
  - AC3 프로필은 원자적으로 기록된다
- **출처** FEATURES.md §1.7

### US-PRJ02 — 프로필에 확장을 추가·제거한다
- **As a** P1
- **I want** `project add <type> <names...>` / `remove <type> <name>` 으로 편집하고
- **So that** 손으로 JSON을 고치지 않는다
- **인수 조건**
  - AC1 `add` 는 여러 이름을 한 번에 받는다
  - AC2 vault에 없는 이름은 거부한다
  - AC3 `remove` 는 프로필 항목과 symlink를 함께 정리한다
- **출처** FEATURES.md §1.7

### US-PRJ03 — 선언과 실제를 일치시킨다
- **As a** P1
- **I want** `project sync` 가 프로필과 실제 symlink를 맞추고
- **So that** 새로 클론한 저장소에서 한 번에 구성한다
- **인수 조건**
  - AC1 프로필에 있는데 없는 링크는 만든다
  - AC2 프로필에 없는데 있는 링크는 제거한다
  - AC3 결과를 linked / unlinked / errors 건수로 보고한다
- **출처** FEATURES.md §1.7, §3.4

### US-PRJ04 — 어긋난 부분을 먼저 확인한다
- **As a** P1
- **I want** `project status` 가 변경 없이 차이만 보여주고
- **So that** sync 전에 영향 범위를 안다
- **인수 조건**
  - AC1 `status` 는 파일시스템을 변경하지 않는다
  - AC2 프로필에만 있는 항목과 실제에만 있는 항목을 구분해 보여준다
- **출처** FEATURES.md §1.7

### US-PRJ05 — 프로필 동기화가 컨텍스트 분석에 반영된다
- **As a** P4
- **I want** 링크가 바뀌면 컨텍스트 분석 캐시가 무효화되고
- **So that** 낡은 수치를 보고 잘못 판단하지 않는다
- **인수 조건**
  - AC1 sync로 링크가 변하면 컨텍스트 캐시를 무효화한다
  - AC2 변화가 없으면 무효화하지 않는다
- **출처** FEATURES.md §2.7, 구현(`_invalidate_context`)

---

## E-TUI — TUI 탐색·조작

### US-TUI01 — 세 축을 탭으로 오간다
- **As a** P1
- **I want** Extensions / Context / Usage 를 숫자키·화살표로 오가고
- **So that** 확장·컨텍스트·비용을 한 도구에서 본다
- **인수 조건**
  - AC1 `1`~`3` 이 해당 메인 탭으로 점프한다
  - AC2 `← →` 가 포커스된 레이어 안에서 순회한다
  - AC3 활성 탭이 시각적으로 구분된다
- **출처** FEATURES.md §2.1, §2.11

### US-TUI02 — 포커스가 어디 있는지 항상 안다
- **As a** P1
- **I want** mainTab ↔ subTab ↔ content 3단 포커스가 명확히 표시되고
- **So that** 키 입력이 어디에 먹는지 헷갈리지 않는다
- **인수 조건**
  - AC1 `↑ ↓ Return` 으로 레이어를 오르내린다
  - AC2 포커스된 레이어에 `▶` 마커가 붙는다
  - AC3 포커스 가능한 본문이 없는 탭(Usage)은 `↓` 를 받아도 mainTab에 머문다 (capability 기반 분기)
  - AC4 `Esc` 는 한 레이어 위로 오르고 mainTab에서만 종료한다
- **출처** FEATURES.md §2.3, §2.11

### US-TUI03 — 목록을 원하는 컬럼으로 정렬한다
- **As a** P1
- **I want** `s` 로 정렬 컬럼을 옮기고 `S` 로 오름/내림을 뒤집고
- **So that** 찾는 항목을 빨리 만난다
- **인수 조건**
  - AC1 `#`(행 번호)를 제외한 **모든 컬럼**이 정렬 대상이다
  - AC2 `s` 는 다음 컬럼으로 이동하며 끝에서 순환한다
  - AC3 `S` 는 컬럼을 바꾸지 않고 방향만 뒤집는다
  - AC4 `s` 로 도착한 컬럼은 그 컬럼의 기본 방향으로 진입한다(텍스트 A→Z, Used/Updated 최신·최다 순)
  - AC5 활성 컬럼 헤더에 ▲/▼ 가 표시되고 필터바·상태바에 활성 정렬이 나타난다
  - AC6 글리프 컬럼(Vault/Proj/Glob/Upd/On)은 **화면에 그려지는 글리프 기준**으로 정렬된다
  - AC7 `Ver` 는 숫자 인식 비교다(1.10.0 > 1.9.0, 값 없음은 마지막)
  - AC8 정렬을 바꿔도 행 수는 변하지 않는다
  - AC9 정렬 상태는 세션 내에서만 유지된다
- **출처** FEATURES.md §2.6

### US-TUI04 — 목록을 걸러 찾는다
- **As a** P1
- **I want** `/` 로 입력해 Enter로 적용하고 Esc로 해제하고
- **So that** 항목이 많아도 즉시 좁힌다
- **인수 조건**
  - AC1 검색 입력 중에는 `s`·`S`·`r` 등 예약 키도 **질의어로 들어간다**
  - AC2 필터는 서브탭별로 독립 유지된다
  - AC3 0건이면 `No <탭> match "<검색어>". Press Esc to clear the filter.` 를 표시한다
  - AC4 필터바에 `(필터/전체 items)` 와 `search='q'` 칩이 표시된다
- **출처** FEATURES.md §2.4, §2.6

### US-TUI05 — 선택 항목의 상세를 본다
- **As a** P1
- **I want** 목록 하단 detail 패널에서 선택 항목의 상세를 보고 `Tab` 으로 포커스해 스크롤하고
- **So that** 화면 전환 없이 확인한다
- **인수 조건**
  - AC1 8개 서브탭 모두 하단 detail 패널을 갖는다
  - AC2 `Tab` 포커스 → `j/k`·`PgUp/PgDn` 스크롤 → `Tab`/`Esc` 복귀
  - AC3 선택이 바뀌면 detail 스크롤이 맨 위로 돌아간다
  - AC4 스크롤이 내용 끝을 넘어가지 않는다
- **출처** FEATURES.md §2.4, §2.10

### US-TUI06 — 목록이 비어도 다음 행동을 안다
- **As a** P1 (신규 사용자)
- **I want** 빈 목록에 제목 + 다음 행동 힌트가 뜨고
- **So that** 무엇을 해야 할지 막히지 않는다
- **인수 조건**
  - AC1 Vault 제외 7개 서브탭이 빈 상태 안내를 갖는다
  - AC2 힌트가 **실재하는 키바인딩**을 가리킨다 (예: Market → `a`)
  - AC3 검색 0건과 데이터 0건의 안내 문구가 다르다
- **출처** FEATURES.md §2.4

### US-TUI07 — 사용량 리포트에서 원하는 줄로 점프한다
- **As a** P3
- **I want** Usage 탭 `/` 가 필터가 아니라 매칭 점프로 동작하고
- **So that** 긴 리포트에서 원하는 항목을 찾는다
- **인수 조건**
  - AC1 타이핑 중 앵커 이후 첫 매칭 라인으로 라이브 점프한다
  - AC2 매칭이 없어지면 앵커로 복귀한다
  - AC3 Enter 적용 후 `n`/`N` 으로 다음/이전 매칭을 순회한다
  - AC4 상태바에 `match i/N` 을 표시한다
  - AC5 입력 중 Esc는 취소+앵커 복귀, 적용 후 Esc는 해제
- **출처** FEATURES.md §2.8

### US-TUI08 — 도움말을 언제든 연다
- **As a** P1
- **I want** `?` 로 키 레퍼런스를 열고 `?/q/Esc/Return` 으로 닫고
- **So that** 키를 외우지 않아도 된다
- **인수 조건**
  - AC1 도움말 내용이 **실제 키맵에서 생성**되어 코드와 어긋나지 않는다
  - AC2 모달이 열린 동안 전역 키(`t` 테마 등)가 입력을 가로채지 않는다
- **출처** FEATURES.md §2.10, §2.11

### US-TUI09 — 테마를 즉시 바꾼다
- **As a** P1
- **I want** `t` 로 light ↔ dark 를 즉시 전환하고 선택이 저장되고
- **So that** 터미널 배경에 맞춘다
- **인수 조건**
  - AC1 `t` 는 팔레트를 즉시 재초기화하고 config에 저장한다
  - AC2 `axt --theme light` 로 이번 실행만 지정할 수 있다
  - AC3 검색 입력 중에는 `t` 가 질의어로 들어간다(모달/입력이 우선)
- **출처** FEATURES.md §1.11, §2.11

### US-TUI10 — 좁은 터미널에서도 깨지지 않는다
- **As a** P1
- **I want** 창이 좁거나 리사이즈돼도 레이아웃이 무너지지 않고
- **So that** 분할 터미널에서도 쓴다
- **인수 조건**
  - AC1 최소 크기 미만이면 `Terminal too small. Resize and try again.` 안내를 낸다
  - AC2 컬럼이 잘려도 크래시하지 않는다
  - AC3 CJK 문자 폭을 `east_asian_width` 로 계산해 정렬이 깨지지 않는다
- **출처** FEATURES.md §2.10, §7.7

---

## E-SYS — 설치·기동·설정·데이터 안전성

### US-SYS01 — 설치 직후 바로 실행된다
- **As a** P1
- **I want** `pip install` 후 `axt` 명령이 즉시 동작하고
- **So that** 추가 설정 없이 시작한다
- **인수 조건**
  - AC1 `axt` 엔트리포인트가 등록된다
  - AC2 인자 없는 `axt` 는 TUI를 연다
  - AC3 `axt --help` / `--version` 이 exit 0 으로 동작한다
  - AC4 `--version` 이 출력하는 값이 패키지 버전과 **일치**한다
- **출처** FEATURES.md §1.1, §1.11

### US-SYS02 — 처음 쓰는 사람에게 안내한다
- **As a** P1 (신규)
- **I want** 최초 실행 시 환영 안내를 1회 보고
- **So that** 무엇부터 할지 안다
- **인수 조건**
  - AC1 마커(`~/.config/axt/onboarded`) 부재 시 1회 표시하고 마커를 만든다
  - AC2 두 번째 실행부터는 표시하지 않는다
  - AC3 마커를 지우면 다시 표시된다
- **출처** FEATURES.md §1.1

### US-SYS03 — 표준 경로와 환경변수를 따른다
- **As a** P1
- **I want** `CLAUDE_CONFIG_DIR` / `XDG_CONFIG_HOME` / Windows `%APPDATA%` 를 존중하고
- **So that** 비표준 환경에서도 동작한다
- **인수 조건**
  - AC1 `CLAUDE_CONFIG_DIR` 이 설정되면 모든 Claude 경로가 그 아래로 해석된다
  - AC2 axt 설정은 `XDG_CONFIG_HOME/axt` (Windows는 AppData)를 쓴다
  - AC3 경로 해석은 `sys.platform == "win32"` 분기를 갖는다
- **출처** FEATURES.md §3.1

### US-SYS04 — 설정 파일이 깨지지 않는다
- **As a** P1
- **I want** 모든 쓰기가 원자적이고 백업을 남기고
- **So that** 중간에 죽어도 설정을 잃지 않는다
- **인수 조건**
  - AC1 `write_json_atomic` 은 tmpfile + `os.replace` 를 쓴다
  - AC2 기존 파일이 있으면 `.bak` 을 남긴다
  - AC3 쓰기 실패 시 원본이 손상되지 않는다
- **출처** FEATURES.md §3.2

### US-SYS05 — 손상된 데이터에도 살아남는다
- **As a** P1
- **I want** 손상된 JSON·깨진 symlink·없는 디렉터리를 만나도 크래시하지 않고
- **So that** 한 파일 문제로 도구 전체를 못 쓰는 일이 없다
- **인수 조건**
  - AC1 `read_json(path, fallback=...)` 은 파싱 실패 시 fallback을 돌려준다
  - AC2 깨진 symlink는 경고로 드러나되 자동 삭제되지 않는다
  - AC3 `~/.claude` 자체가 없어도 빈 상태로 동작한다
  - AC4 권한 거부는 해당 항목만 실패로 처리하고 나머지를 계속 처리한다
- **출처** FEATURES.md §3.2, §7

### US-SYS06 — 외부 명령 실패가 전파되지 않는다
- **As a** P1
- **I want** git·tar·sh·claude 호출 실패가 안내 메시지로 처리되고
- **So that** 네트워크가 없어도 도구를 쓴다
- **인수 조건**
  - AC1 `subprocess.run` 실패 시 stderr를 캡처해 사용자에게 전달한다
  - AC2 명령 자체가 없어도(FileNotFoundError) 크래시하지 않는다
  - AC3 타임아웃이 무한 대기로 이어지지 않는다
- **출처** FEATURES.md §7.2

### US-SYS07 — 의존성 없이 동작한다
- **As a** P1
- **I want** 순수 stdlib만으로 동작하고
- **So that** 설치 실패·버전 충돌이 없다
- **인수 조건**
  - AC1 런타임 의존성이 0개다 (`pyproject.toml`)
  - AC2 YAML frontmatter는 자체 파서로 처리한다(PyYAML 미사용)
  - AC3 HTTP는 `urllib.request`, 압축 해제는 `tarfile` 을 쓴다
- **출처** FEATURES.md §7.4, §7.6, CLAUDE.md

### US-SYS08 — 파괴적 조작이 의도한 범위를 넘지 않는다
- **As a** P1 (보안 관심사)
- **I want** 링크·삭제 조작이 vault/`.claude` 밖으로 나가지 않고
- **So that** 경로 조작으로 시스템 파일이 손상되지 않는다
- **인수 조건**
  - AC1 `..` 이 섞인 이름/경로가 대상 디렉터리 밖을 가리키지 못한다
  - AC2 절대 경로 이름이 대상 디렉터리를 벗어나지 못한다
  - AC3 symlink를 따라 밖으로 나가는 삭제가 일어나지 않는다
  - AC4 `market remove` 는 axt가 설치한 디렉터리만 지운다
- **출처** 보안 요구 + FEATURES.md §1.3, §3.4
