# API(CLI) 테스트 시나리오 — axt

axt 는 HTTP 서버가 아니라 CLI 다. 이 계층의 "API" 는 **CLI 계약**을 뜻한다 —
인자 검증 / exit code / stdout·stderr 형태 / `--json`·`--csv` 스키마 / 상호배타 옵션 / 미존재 이름 처리.

- **Layer Owner**: CLI 인자 검증·exit code·stdout 형태·`--json` 스키마 (`TEST_DEDUP_POLICY.md` §2)
- **금지**: 도메인 파싱 규칙 재검증. 예 — `parse_marketplace_source` 의 파싱 규칙은 unit 소유이므로
  여기서는 "잘못된 소스 → exit 1 + stderr `✗`" 라는 **계약만** 본다
- **반복 패턴 금지**: 같은 검증을 41개 서브명령에 반복하지 않는다. 공통 계층 1회 + 대표 2개로 끝내고,
  나머지는 **그 명령만의 고유 계약**만 쓴다
- **ID**: `SC-API-NNN` / 대응 TC는 `tests/doc/testcases/api-testcases.md`

## 41개 리프 서브명령 커버리지 맵

| 그룹 | 리프 | 담당 시나리오 |
|---|---|---|
| (top) | `tui` | SC-API-004, SC-API-022 |
| `context` | 1개 | SC-API-019 |
| `market` | list / add / sync / remove | SC-API-005 |
| `mcp` | list / info / enable / disable | SC-API-006 |
| `hook` | list / enable / disable | SC-API-007 |
| `plan` | overview / set | SC-API-008 |
| `plugin` | list / enable / disable / info / remove / search | SC-API-009 |
| `project` | init / add / remove / sync / status | SC-API-010 |
| `skill` | list / link / unlink | SC-API-011 |
| `usage` | today / week / month / blocks / session | SC-API-012 ~ SC-API-016 |
| `vault` | list / migrate / add / install / link-global / unlink-global | SC-API-017 ~ SC-API-018 |
| `update` | 1개 (+`[type] [name]`) | SC-API-020, SC-API-021 |

공통 계약(SC-API-001 ~ SC-API-003)은 위 전부에 적용되며 대표 2개 명령으로만 검증한다.

---

## 1. 공통 계층 (41개 명령 전체에 1회)

### SC-API-001 — argparse 계층의 실패는 exit 2 다
- **Objective**: 알 수 없는 서브명령·누락된 필수 인자·`choices` 위반이 argparse 단계에서 exit 2 로 끝나는지 검증. 이 계약을 여기서 1회 확정하고 개별 명령에서 반복하지 않는다 (US-SYS01 AC3, US-UPD04 AC2)
- **Preconditions**: `main(argv)` 를 직접 호출하고 `SystemExit` 을 잡는다. `tmp_path` + `monkeypatch.chdir` 로 cwd 격리
- **Steps**: 1) 없는 최상위 명령 2) 필수 인자 누락 3) `choices` 위반 4) `--json` 같은 알 수 없는 플래그
- **Expected Result**: 모두 `SystemExit` 이고 코드는 2. 사용법(usage) 문자열이 stderr 로 나간다
- **Priority**: Critical

### SC-API-002 — 도메인 예외는 exit 1 + stderr `✗` 로 변환된다
- **Objective**: `main()` 의 최상위 핸들러가 `FileNotFoundError` / `FileExistsError` / `KeyError` / `ValueError` / `OSError` / `RuntimeError` 를 잡아 `✗ <메시지>` 를 **stderr** 로 내고 exit 1 을 돌려주는지, 그 밖의 예외는 그대로 전파되는지 검증 (US-SYS05, US-MKT01 AC2, US-MKT02 AC3)
- **Preconditions**: 대표 명령 2개(`market add` 잘못된 소스 → `ValueError`, `market sync` 없는 이름 → `KeyError`)로만 검증
- **Steps**: 1) 잘못된 소스로 `market add` 2) 없는 이름으로 `market sync` 3) stdout 에는 `✗` 가 없는지 확인
- **Expected Result**: exit 1, stderr 에 `✗` 시작 메시지, stdout 오염 없음
- **Priority**: Critical

### SC-API-003 — 전역 플래그 계약
- **Objective**: `--version/-V`, `--help/-h`, `--theme {auto,dark,light}` 가 문서화된 대로 동작하는지 검증 (US-SYS01 AC3·AC4, US-TUI09 AC2)
- **Preconditions**: `launch_tui` 를 monkeypatch 로 스텁 — 실제 curses 진입 금지
- **Steps**: 1) `--version` 2) `--help` 3) `--theme light` (서브명령 없음) 4) `--theme bogus`
- **Expected Result**: 1) exit 0 + 패키지 버전 문자열, 2) exit 0 + 12개 명령 그룹이 모두 목록에, 3) exit 0 + TUI 를 `light` 로 기동, 4) exit 2
- **Priority**: Critical

### SC-API-004 — 인자 없는 호출은 TUI 를 연다
- **Objective**: `axt` (인자 0개) 와 `axt tui` 가 같은 경로로 TUI 를 여는지 검증 (US-SYS01 AC2)
- **Preconditions**: `launch_tui` 스텁
- **Steps**: 1) `main([])` 2) `main(["tui"])`
- **Expected Result**: 둘 다 exit 0 이며 `launch_tui` 가 정확히 1회 호출된다
- **Priority**: Critical

---

## 2. 그룹별 고유 계약

### SC-API-005 — `market` 4개 서브명령 계약
- **Objective**: 각 서브명령의 exit code 와 출력 요소만 검증한다. 소스 파싱 규칙은 unit(SC-UNIT-021) 소유이므로 여기서는 검증하지 않는다 (US-MKT01~US-MKT04)
- **Preconditions**: `monkeypatch.setattr("axt.PATHS", Paths(known_marketplaces=tmp_path/..., marketplaces=tmp_path/...))`, `monkeypatch.chdir(tmp_path)`. git·네트워크 호출은 monkeypatch 로 차단
- **Steps**: 1) 빈 레지스트리에서 `list` 2) `dir:` 소스로 `add` 3) 등록 후 `list` 4) `sync` (이름 지정 / 전체) 5) 없는 이름으로 `remove`
- **Expected Result**: 1) exit 0 + 빈 목록 안내, 2) exit 0 + `✓ ... registered`, 3) 마켓명·종류·위치·최종 갱신 컬럼, 4) 갱신/최신 두 메시지 형태 + 전체 동기화는 빈 레지스트리에서도 exit 0, 5) exit 1 + stderr `✗`
- **Priority**: High

### SC-API-006 — `mcp` 4개 서브명령 계약
- **Objective**: `list` / `info` / `enable` / `disable` 의 exit code·출력 요소·재시작 안내를 검증 (US-MCP03 AC3, US-MCP04 AC1·AC2)
- **Preconditions**: `PATHS` 교체 + `chdir`. `collect_mcp_servers` 의 출처 병합 규칙은 unit(SC-UNIT-030) 소유
- **Steps**: 1) 서버 0개에서 `list` 2) 서버 있는 상태에서 `list` 3) 없는 이름으로 `info` 4) stdio 서버 `info` 5) 원격(url) 서버 `info` 6) `disable` → `enable`
- **Expected Result**: 1) exit 0 + `No MCP servers found.`, 2) Server/Scope/Transport/Detail 컬럼 + 비활성 서버에 `[disabled]`, 3) exit 1, 4) 명령줄, 5) URL, 6) exit 0 + `Restart Claude Code` 안내
- **Priority**: High

### SC-API-007 — `hook` 인덱스 기반 토글 계약
- **Objective**: `hook list` 가 출력한 인덱스를 `enable`/`disable` 인자로 그대로 쓸 수 있고, 범위 밖 인덱스와 plugin 훅이 exit 1 로 거절되는지 검증 (US-HK01 AC2, US-HK03 AC1)
- **Preconditions**: `PATHS` 교체 + `chdir`. 훅 이동 규칙 자체는 unit(SC-UNIT-037) 소유
- **Steps**: 1) 훅 0개에서 `list` 2) `disable 0` → `list` → `enable 0` 왕복 3) `disable 5`(범위 밖) 4) plugin 훅 인덱스로 `disable` 5) 이미 그 상태인 훅을 다시 토글
- **Expected Result**: 1) exit 0 + `No hooks found.`, 2) `[off]` 표기가 붙었다 사라짐, 3) exit 1 + 범위 안내, 4) exit 1 + `read-only` 문구, 5) exit 0 + `already` 안내(no-op)
- **Priority**: High

### SC-API-008 — `plan` 계약과 기본 액션
- **Objective**: `plan` 이 서브명령 없이 `overview` 로 폴백하고, `set <name>` / `set auto` 가 자동 감지 플래그를 뒤집는지, 초과 예상 시 경고가 나오는지 검증 (US-USG07 AC2, AC4)
- **Preconditions**: `AXT_CONFIG_PATH` 를 `tmp_path` 로 monkeypatch. **`get_days_in_billing_period` 를 고정값으로 monkeypatch** — 월중 날짜 의존 플레이크 이력이 있다
- **Steps**: 1) 서브명령 없이 `plan` 2) `plan set max-20x` → `plan overview` 3) `plan set auto` 4) 예측이 월정액을 넘도록 사용량 주입 5) 넘지 않는 경우
- **Expected Result**: 1) exit 0(빈 환경에서도), 2) 플랜 라벨·월정액 반영 + `auto-detect off` 안내, 3) `auto-detect enabled` 안내, 4) 초과 경고 문구 존재, 5) 경고 부재
- **Priority**: High

### SC-API-009 — `plugin` 6개 서브명령 + `--scope` 계약
- **Objective**: `--scope global|project` 가 서로 다른 settings 파일에 쓰고, `info`/`remove` 의 미존재 id 가 exit 1 이며, `search` 는 0건도 exit 0 인지 검증 (US-PLG02 AC1·AC2, US-PLG03 AC1, US-PLG05 AC1)
- **Preconditions**: `PATHS` 교체 + `chdir(proj)`
- **Steps**: 1) 빈 상태 `list` 2) `enable <id>` (스코프 미지정) 3) `--scope project` 로 enable/disable 4) 없는 id 로 `info` / `remove` 5) 결과 0건 `search` 6) `--scope bogus`
- **Expected Result**: 1) exit 0 + `No plugins installed.`, 2) 글로벌 settings 에 기록 + 재시작 안내, 3) `<proj>/.claude/settings.json` 에 기록, 4) exit 1 + 명확한 메시지, 5) exit 0 + 안내, 6) exit 2
- **Priority**: High

### SC-API-010 — `project` 5개 서브명령 계약
- **Objective**: `init` 이 멱등하고, `status` 가 프로필 부재 시 exit 1 이며 파일시스템을 바꾸지 않고, `add` 가 vault 에 없는 이름을 거절하는지 검증 (US-PRJ01 AC2, US-PRJ02 AC2, US-PRJ04 AC1·AC2)
- **Preconditions**: `PATHS` 교체 + `chdir(proj)`. symlink 가 필요한 TC 는 Windows skip
- **Steps**: 1) `init` → 재 `init` 2) 프로필 없는 상태에서 `status` 3) vault 미존재 이름으로 `add` 4) `add` → `remove` 왕복 5) 이미 동기화된 상태에서 `sync` 6) `status` 실행 전후 파일시스템 비교
- **Expected Result**: 1) 첫 회 생성 + 두 번째는 덮어쓰지 않음(exit 0 + 안내), 2) exit 1 + `Run \`axt project init\` first.`, 3) 해당 항목에 `✗` 안내, 4) symlink 생성·제거, 5) `Already in sync.`, 6) 변경 없음
- **Priority**: High

### SC-API-011 — `skill` 3개 서브명령 + 플랫폼 게이팅
- **Objective**: `link`/`unlink` 가 `is_symlink_supported()` 가 False 인 플랫폼에서 **파서에 등록조차 되지 않고**, 등록된 플랫폼에서는 미존재 경로가 exit 1 인지 검증 (US-LNK02 AC2·AC3)
- **Preconditions**: 파서 등록 여부는 `build_parser()` 를 직접 조사한다. 핸들러 거부 경로는 `is_symlink_supported` 를 monkeypatch 해 확인
- **Steps**: 1) 스킬 0개 `list` 2) 링크된 항목 포함 `list` 3) `link` → `unlink` 왕복 4) `is_symlink_supported=False` 로 핸들러 직접 호출 5) 없는 경로로 `link`
- **Expected Result**: 1) exit 0 + `No skills found.`, 2) 이름/출처/타입/경로 컬럼 + symlink 는 `→ 대상`, 3) exit 0, 4) exit 1 + 미지원 안내(크래시 아님), 5) exit 1
- **Priority**: High

### SC-API-012 — `usage` 기본 액션과 데이터 0건
- **Objective**: 인자 없는 `axt usage` 가 `today` 와 동일하고, 데이터가 없어도 오류가 아니라 0건 요약 + exit 0 인지 검증 (US-USG01 AC1, AC3)
- **Preconditions**: `PATHS.projects` 를 빈 `tmp_path` 로, `AXT_CONFIG_PATH` 를 `tmp_path` 로 monkeypatch. `--timezone UTC` 를 명시해 호스트 타임존 의존 제거
- **Steps**: 1) `usage` 2) `usage today` 3) `usage week` / `month` / `blocks` 를 빈 데이터로
- **Expected Result**: 1)·2) 동일 출력, 3) 모두 exit 0 (예외·비0 종료 없음)
- **Priority**: Critical

### SC-API-013 — `usage` 필터 인자 계약
- **Objective**: `--since` / `--until` / `--model` / `--project` / `--timezone` 이 선언대로 동작하고, 잘못된 날짜 형식과 `--since > --until` 이 exit 1 로 거절되는지 검증 (US-USG02 AC1~AC3)
- **Preconditions**: 데이터가 있는 `tmp_path` projects. timestamp 는 명시 ISO 로 고정
- **Steps**: 1) `--model` 로 필터 2) `--project` 로 필터 3) `--since 2026-01-01 --until 2026-01-31` 4) `--since notadate` 5) `--since 2026-03-10 --until 2026-03-01` 6) 필터 2개 동시 지정
- **Expected Result**: 1)·2) 해당 항목만, 3) 지정 구간만, 4) exit 1 + 형식 안내, 5) exit 1, 6) AND 결합
- **Priority**: High
- **Note**: 3)~5) 는 현재 구현에 없다 — `unit-scenarios.md` `## 스펙 갭` G-1 참조

### SC-API-014 — `usage --json` / `--csv` 스키마 계약
- **Objective**: `--json` 이 파싱 가능한 JSON 이고 장식 문자가 섞이지 않는지, `--csv` 의 헤더와 열 수가 모든 행에서 일치하는지 검증 (US-USG03 AC1, AC2)
- **Preconditions**: `NO_COLOR` 를 설정해 ANSI 이스케이프 제거. 데이터 유·무 두 경우 모두
- **Steps**: 1) `usage today --json` (데이터 있음/없음) 2) `usage week --json` 3) `usage week --csv` 헤더 4) `usage week --csv` 데이터 행의 열 수 5) `--json` 과 `--csv` 동시 지정
- **Expected Result**: 1)·2) `json.loads` 성공, 필수 키(`date`/`sessions`/`inputTokens`/`outputTokens`/`cacheCreationTokens`/`cacheReadTokens`/`cost`) 존재, 3) 9개 컬럼 헤더, 4) 모든 행의 콤마 개수가 헤더와 동일, 5) 결정적으로 하나가 우선(모호한 혼합 출력 금지)
- **Priority**: Critical

### SC-API-015 — `usage --export` 계약
- **Objective**: `--export <path>` 가 지정 경로에 파일을 쓰고, 쓰기 실패 시 exit 1 인지 검증 (US-USG03 AC3)
- **Preconditions**: `tmp_path` 대상 경로. 쓰기 실패는 존재하지 않는 부모 디렉터리나 읽기 전용 경로로 유도
- **Steps**: 1) `usage week --export <tmp>/out.csv` 2) 쓸 수 없는 경로로 `--export`
- **Expected Result**: 1) exit 0 + 파일 생성 + 내용이 비어 있지 않음, 2) exit 1 + stderr 오류
- **Priority**: Medium
- **Note**: `--export`·`--breakdown` 은 현재 argparse 에 없다 — `## 스펙 갭` G-3 참조

### SC-API-016 — `usage blocks --active` 와 `usage session <prefix>`
- **Objective**: `--active` 가 활성 블록만 남기고, `session` 이 prefix 매칭으로 세션을 찾으며, 0건은 exit 1, 다중 매칭은 후보를 제시하는지 검증 (US-USG04 AC4, US-USG05 AC1~AC3)
- **Preconditions**: 활성 블록이 존재하도록 timestamp 를 주입하되, **`datetime.now` 를 monkeypatch 로 고정**한다
- **Steps**: 1) `blocks` (전체) 2) `blocks --active` 3) 유일 prefix 로 `session` 4) 매칭 0건 5) 서로 다른 두 세션이 같은 prefix 를 가질 때
- **Expected Result**: 1) 블록 표 출력 + exit 0, 2) 활성 블록만, 3) 세션 상세(Project/Models/Messages/토큰/비용/기간), 4) exit 1 + `not found`, 5) 후보 목록 제시
- **Priority**: High
- **Note**: 5) 는 현재 구현에 없다 — `## 스펙 갭` G-6 참조

### SC-API-017 — `vault` 조회·이동 계약 (`list` / `migrate` / `add` / `install`)
- **Objective**: 빈 vault 가 오류가 아니고, `add` 의 미존재 경로·중복 이름이 exit 1 이며, `install` 의 미등록 마켓/미존재 확장이 exit 1 인지 검증 (US-VLT02 AC2, US-VLT03 AC1~AC4, US-VLT04 AC1~AC3)
- **Preconditions**: `PATHS` 교체 + `chdir`. symlink 가 필요한 TC 는 Windows skip
- **Steps**: 1) 빈 vault `list` 2) 항목 있는 `list` 3) 없는 경로로 `add` 4) 디렉터리 `add` (타입 추론) 5) `.md` 파일 `add` (타입 추론) 6) 이미 있는 이름으로 `add` 7) 미등록 마켓으로 `install` 8) 성공적인 `install` 9) 글로벌 확장이 없을 때 `migrate` 10) broken symlink 가 있을 때 `migrate`
- **Expected Result**: 1) exit 0 + 안내, 3) exit 1 + `✗ Source not found`, 4) `skill` 로 추론, 5) `command` 로 추론, 6) exit 1 (덮어쓰기 금지 — 파일 타입 포함), 7) exit 1 + 등록된 마켓 안내, 9) `No extensions found in global paths.`, 10) moved/skipped/broken/errors 집계가 출력되고 broken 항목이 별도 표기
- **Priority**: High
- **Note**: 6) 파일 타입 중복은 `## 스펙 갭` G-5, 7) 미등록 마켓 구분은 G-7 참조

### SC-API-018 — `vault link-global` / `unlink-global` + `--mirror-agents`
- **Objective**: vault 에 없는 이름이 exit 1 이고, `--mirror-agents` / `--force-agents` 플래그가 미러 동작을 켜며, 해제가 vault 실체를 남기는지 검증 (US-VLT05 AC1~AC3, US-VLT06 AC1·AC3·AC4)
- **Preconditions**: `PATHS` 교체 + `HOME` 을 `tmp_path` 로 monkeypatch. Windows skip
- **Steps**: 1) vault 에 없는 이름으로 `link-global` 2) `link-global` → `unlink-global` 왕복 3) `--mirror-agents` 로 link 4) `.skill-lock.json` 상태에서 `--mirror-agents` 5) `--force-agents` 추가 6) `--mirror-agents` 로 unlink
- **Expected Result**: 1) exit 1 + `not found in vault`, 2) exit 0 + vault 실체 잔존, 3) `~/.agents/skills/<name>` 생성 + 성공 표기, 4) exit 0 이지만 미러는 `⊘` 로 건너뜀, 5) 미러 생성, 6) 미러도 제거
- **Priority**: High

### SC-API-019 — `context` 옵션 계약
- **Objective**: `--detail` / `--json` / `--category` / `--model` 이 출력 형태를 바꾸고, `--json` 이 유효한 JSON 인지 검증 (US-CTX01 AC2~AC4)
- **Preconditions**: `HOME`·cwd 를 `tmp_path` 로 격리. `get_claude_version` / `get_git_status` monkeypatch (외부 명령 호출 금지). `NO_COLOR` 설정
- **Steps**: 1) 옵션 없이 2) `--detail` 3) `--category skills` 4) 존재하지 않는 카테고리 5) `--json` 6) `--model claude-haiku-4-5`
- **Expected Result**: 1) 카테고리 표 + Cost Impact 블록, 2) 카테고리 아래 개별 항목 행 추가, 3) 해당 카테고리만, 4) exit 0 + 빈 표(오류 아님), 5) `json.loads` 성공 + `totalTokens`/`contextWindowSize`/`usedPercent`/`model`/`sources`/`costImpact` 키, 6) 윈도우 200,000 이 반영된 `usedPercent`
- **Priority**: High

### SC-API-020 — `update` 타깃팅과 티어 게이팅
- **Objective**: 옵션 없는 `axt update` 가 아무것도 바꾸지 않는 리포트이고, `--apply` 가 Tier-1 만 일괄 적용하며, `claude-code` 는 명시 타깃일 때만 위임되고, 확인 프롬프트가 `-y` 로 생략되는지 검증 (US-UPD01 AC1~AC3, US-UPD02 AC1~AC3, US-UPD04 AC1~AC3)
- **Preconditions**: `check_all_updates` / `apply_updates` 를 monkeypatch — 실제 git·`claude update` 실행 금지. 프롬프트는 `input` monkeypatch
- **Steps**: 1) 옵션 없는 `update` 2) 알 수 없는 `type` 3) 없는 `name` 4) `--apply` 없이 파일시스템 변화 확인 5) `--apply` (bulk) 6) `axt update claude-code --apply` 7) 확인 프롬프트에 `n` 응답 8) `-y` 로 생략 9) 적용 대상 0건
- **Expected Result**: 1) Updatable / Up to date / Manual / Delegated 4그룹 + 요약 라인, 2) exit 2(argparse), 3) 필터 결과 0건 안내, 4) 변화 없음, 5) tier-1 updatable 만 targets 에, 6) tier-3 포함, 7) exit 1 + `Aborted.`, 8) 프롬프트 없이 진행, 9) `Nothing to update.`
- **Priority**: Critical

### SC-API-021 — `update --json` 은 non-interactive 다
- **Objective**: `--json` 이 확인 프롬프트를 띄우지 않고, 사람용 장식 문자가 섞이지 않은 유효 JSON 을 내며, 항목별 상태를 담는지 검증 (US-UPD03 AC1~AC3)
- **Preconditions**: `input` 을 호출 시 예외를 던지도록 monkeypatch — 프롬프트가 뜨면 테스트가 실패한다. `NO_COLOR` 설정
- **Steps**: 1) `update --json` (dry-run) 2) `update --apply --json` (`-y` 없이) 3) 적용 대상 0건 + `--json`
- **Expected Result**: 1) `json.loads` 성공 + 각 원소에 `item_type`/`name`/`tier`/`current`/`available`/`updatable`/`note`/`error`, 2) 프롬프트 없이 결과 JSON(`before`/`after`/`updated`/`action`/`error`), 3) `[]`
- **Priority**: Critical

### SC-API-022 — 비-TTY 환경에서 TUI 가 깨끗이 실패한다
- **Objective**: curses 를 초기화할 수 없는 환경(CI·파이프)에서 `launch_tui` 가 트레이스백 대신 exit 1 + 안내 메시지를 내는지 검증 (US-SYS01 AC2, US-TUI10)
- **Preconditions**: 테스트는 TTY 없이 돈다 — 별도 조작 없이 `curses.wrapper` 가 실패한다
- **Steps**: 1) `launch_tui()` 직접 호출 2) stderr 확인
- **Expected Result**: exit 1, stderr 에 `TUI failed to start` 또는 curses 관련 안내. 트레이스백 미출력
- **Priority**: High

---

## 계층 경계 메모

아래는 이 문서가 **의도적으로 검증하지 않는** 항목이다.

| 항목 | 소유 계층 |
|---|---|
| `mcp info` 의 env 값 마스킹 (US-MCP05) | security |
| `market remove` 가 외부 `dir:` 경로를 지우지 않는지 (US-SYS08 AC4) | security |
| `..`·절대 경로가 대상 디렉터리를 벗어나지 못하는지 (US-SYS08 AC1~AC3) | security |
| stdout 색상 대비·색맹 안전 | accessibility |
| 큰 JSONL 에서 `usage` 응답 시간 | performance |
| TUI 키 입력 → 렌더 (US-TUI01~US-TUI10 대부분) | e2e |
| 도메인 파싱·계산 규칙 전반 | unit |
