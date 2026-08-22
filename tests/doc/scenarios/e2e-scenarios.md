# E2E Test Scenarios

> Target: axt — 사용자 여정(TUI 실제 키 시퀀스 또는 다단계 CLI 워크플로)
> Date: 2026-08-22
> Author: full-test-orchestrator (Phase B, Agent 2)

## E2E의 정의 (이 저장소 한정)

브라우저도 pty 하네스도 없다. 따라서 이 저장소에서 **E2E 케이스 = 정해진 디스크
상태에서 시작해 실제 키 코드를 연속으로 흘려 보내고, 최종 렌더 화면과 최종 디스크
상태를 함께 단언하는 것**이다.

- **구동 방식**: `tests/test_tui.py` 의 기존 하네스를 그대로 쓴다.
  - `_make_stdscr(rows, cols)` — `addnstr` 인자를 `scr.calls` 에 기록하는 MagicMock
  - `_loop_stdscr(keys, rows, cols)` — `getch()` 가 `keys` 를 순서대로 돌려주는 stdscr.
    마지막 키는 반드시 루프를 종료시켜야 한다(`ord("q")` 등)
  - `_quiet_curses(monkeypatch)` — `curses.curs_set` / `set_escdelay` /
    `tui_init_colors` / `_prime_vault_scan` / `is_first_run` 을 무력화
  - `_setup_isolated_paths(tmp_path, monkeypatch)` — `axt.HOME` · `axt.PATHS` ·
    `axt.AXT_CONFIG_PATH` 를 `tmp_path` 하위로 고정하고 `chdir`
  - 최종 상태 관찰은 `axt.tui.loop._render_frame` 을 감싸 `state` 를 캡처하는 spy로
    한다(기존 `test_tui_loop_number_key_switches_tab_then_quit` 와 동일 방식)
  - 화면 문자열은 `"".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))`
- **경계**: E2E는 API 테스트의 변장이 아니다. 모든 시나리오는 `_tui_loop` 또는
  `handle_*_input` 을 통과하는 **키 시퀀스**를 갖거나, 여러 CLI 명령을 순서대로 엮은
  워크플로여야 한다. 단일 함수 호출 + 단언은 unit / integration 소유다.
- **스레드**: `_kick_update_check` · vault scan · usage load는 데몬 스레드다.
  conftest의 `_no_async_update_sweep` 이 update 스윕을 이미 차단하고,
  `_quiet_curses` 가 `_prime_vault_scan` 을 차단한다. 그 외 워커를 태우는 시나리오는
  각 TC가 stub 또는 join 방식을 명시한다.
- **서브탭 커버리지**: Extensions 8개(vault / skills / commands / agents / mcp /
  hooks / plugins / market)와 Context 2개(project / sources)를 시나리오 집합 전체에서
  모두 통과한다.

---

## SC-E2E-001: 신규 사용자 첫 실행 — 환영 안내 → 3탭 순회 → 종료

- **Objective**: 빈 `~/.claude` 상태로 처음 실행한 사용자가 안내를 받고, 세 메인 탭을
  오가며 빈 목록에서도 다음 행동을 알 수 있는지 확인한다.
  (US-SYS02, US-TUI01, US-TUI06, US-SYS05)
- **Priority**: Critical
- **Preconditions**: `tmp_path` 에 아무 Claude 데이터도 없음. `AXT_CONFIG_DIR` 을
  `tmp_path/config` 로 고정하고 `onboarded` 마커를 만들지 않는다.
- **Steps**:
  1. TUI를 기동한다
  2. `2` → `3` → `1` 로 메인 탭을 순회한다
  3. Extensions에서 `]` 로 Market 서브탭까지 이동한다
  4. `q` 로 종료한다
- **Expected Result**: 첫 프레임 상태 메시지에 환영 안내가 뜨고 `onboarded` 마커가
  생기며, 빈 서브탭에는 제목과 **실재하는 키바인딩**을 가리키는 힌트가 함께 그려진다.
  두 번째 실행에서는 안내가 다시 뜨지 않는다.

---

## SC-E2E-002: 큐레이터 여정 — migrate → import → 전역 링크 → 프로젝트 링크 → status 일치

- **Objective**: 흩어진 확장을 vault로 모아 여러 스코프에 배포하는 P2의 전체 여정을
  한 세션으로 검증한다. (US-VLT01, US-LNK05, US-VLT05, US-VLT09, US-PRJ04)
- **Priority**: Critical
- **Preconditions**: `~/.claude/{skills,commands,agents}` 에 실체 3건, vault는 비어
  있음. `PATHS.vault` · `PATHS.claude_dir` · cwd 모두 `tmp_path` 하위.
- **Steps**:
  1. Vault 서브탭에서 `m` 으로 마이그레이션한다
  2. Agents 서브탭으로 이동해 vault 밖 항목을 `i` 로 import한다
  3. Vault 서브탭으로 돌아와 `g` → `p` 로 pending을 쌓고 `Enter` 로 적용한다
  4. `y` 로 프로젝트를 동기화한다
  5. `q` 로 종료한 뒤 디스크 상태와 `.axt-profile.json` 을 확인한다
- **Expected Result**: vault에 실체가 모이고, 원위치·전역·프로젝트 세 곳에 vault를
  가리키는 심볼릭 링크가 남으며, 프로필 선언과 실제 링크가 일치한다.

---

## SC-E2E-003: 정렬 여정 — Skills → Commands → Agents 에서 `s` / `S` 순회

- **Objective**: 정렬 컬럼 이동과 방향 토글이 헤더 글리프·상태바·행 순서에 동시에
  반영되고, 서브탭을 옮겨도 각자의 정렬이 독립인지 확인한다. (US-TUI03)
- **Priority**: High
- **Preconditions**: skills 3건 · commands 3건 · agents 3건을 이름/버전/소스가 서로
  다르게 배치. 업데이트 스윕은 conftest가 차단하므로 `Upd` 는 `…` 로 고정.
- **Steps**:
  1. Skills 서브탭에서 `s` 를 눌러 컬럼을 오른쪽으로 옮긴다
  2. `S` 로 방향을 뒤집는다
  3. `s` 로 다음 컬럼에 넘어가 방향이 그 컬럼의 기본값으로 초기화되는지 본다
  4. `]` 로 Commands → Agents 로 옮겨 같은 조작을 반복한다
- **Expected Result**: 활성 컬럼 헤더에 `▲`/`▼` 가 붙고 상태바가 같은 컬럼을 가리키며,
  행 수는 변하지 않는다. `s` 로 도착한 컬럼은 항상 기본 방향으로 진입한다.

---

## SC-E2E-004: 검색 여정 — Market·Skills `/` 입력 → 적용 → `Esc` 단계적 해제

- **Objective**: 검색 입력 중 예약 키가 질의어로 들어가고, 적용된 필터가 서브탭별로
  독립 유지되며, `Esc` 가 한 번에 한 단계씩 되돌리는지 확인한다.
  (US-TUI04, US-VLT08 AC4)
- **Priority**: High
- **Preconditions**: Market 2건, Skills 3건. 이름에 `s` · `r` 이 포함된 항목을 최소
  1건 포함시켜 예약 키 캡처를 실제로 시험한다.
- **Steps**:
  1. Market 서브탭에서 `/` 를 누르고 예약 키가 섞인 질의어를 입력한다
  2. `Enter` 로 적용하고 필터바 칩을 확인한다
  3. `]` 로 Skills 로 옮겨 다른 질의어를 적용한다
  4. `Esc` 를 눌러 Skills 필터만 풀린 뒤 다시 `Esc` 로 포커스가 올라가는지 본다
  5. Market 으로 돌아와 필터가 남아 있는지 확인한다
- **Expected Result**: 입력 중 `s`/`S`/`r` 은 질의어가 되고, 필터바에
  `(필터/전체 items)` 와 `search='q'` 가 표시되며, 0건이면
  `No <탭> match "<검색어>". Press Esc to clear the filter.` 가 뜬다.

---

## SC-E2E-005: 일괄 조작 여정 — Plugins `Space` 다중 마크 → `g` 일괄 토글 → 확인 → 적용

- **Objective**: 여러 항목을 마크해 한 번에 토글하는 흐름이 확인 모달을 거쳐 settings
  파일에 반영되고, 마크가 정렬·검색 변화를 넘어 유지되는지 확인한다.
  (US-VLT08 AC1·AC3, US-PLG02, US-VLT09 AC4)
- **Priority**: Critical
- **Preconditions**: 설치 플러그인 3건. `confirm_modal` 을 `True`/`False` 로 각각
  monkeypatch해 승인/취소 두 경로를 모두 태운다.
- **Steps**:
  1. `Space` 로 2건을 마크한다
  2. `s` 로 정렬을 바꿔 마크가 살아 있는지 확인한다
  3. `g` 를 눌러 확인 모달에서 승인한다
  4. `q` 로 종료한 뒤 `settings.json` 의 `enabledPlugins` 를 확인한다
- **Expected Result**: 마크된 2건만 토글되고 나머지는 그대로이며, 상태바에 적용 건수가
  뜨고 마크는 성공 후 비워진다. 모달을 거절하면 파일이 변하지 않는다.

---

## SC-E2E-006: pending 취소 여정 — Vault `p` 토글 → `Esc` 폐기 → 디스크 미변경

- **Objective**: 되돌릴 수 없는 조작이 `Enter` 확인 전에는 절대 디스크에 닿지 않는지
  확인한다. (US-VLT09 AC1·AC3)
- **Priority**: Critical
- **Preconditions**: vault 2건, 프로젝트에 링크 없음. 조작 전 `.claude/skills/` 의
  엔트리 목록과 `.axt-profile.json` 존재 여부를 스냅샷으로 잡아 둔다.
- **Steps**:
  1. `p` 로 pending을 만든다
  2. 렌더 화면에 pending 마커가 나타나는지 확인한다
  3. `Esc` 로 폐기한다
  4. `q` 로 종료한 뒤 스냅샷과 비교한다
- **Expected Result**: pending 동안 화면에는 표시가 있지만 디스크는 조작 전과 바이트
  단위로 동일하고, `Esc` 이후 pending 집합이 비며 상태바에 폐기 메시지가 뜬다.

---

## SC-E2E-007: MCP 여정 — 등록 위치 ≠ 활성 상태, detail 패널 포커스와 스크롤

- **Objective**: MCP 서브탭에서 Proj/Glob이 읽기 전용 등록 위치를, On이 프로젝트 활성
  상태를 나타내며, 하단 detail 패널이 `Tab` 으로 포커스되어 스크롤되는지 확인한다.
  (US-MCP02, US-MCP03, US-TUI05, US-MCP05)
- **Priority**: High
- **Preconditions**: user 스코프 서버 1건 + project `.mcp.json` 서버 1건 +
  built-in 1건. `~/.claude.json` 을 `tmp_path` 하위로 고정하고 `chdir` 로 프로젝트
  경로를 고정(설정이 `projects[<cwd>]` 에 기록되므로 cwd 격리가 필수).
- **Steps**:
  1. MCP 서브탭에서 `Tab` 으로 detail 패널에 포커스한다
  2. `j` 를 여러 번 눌러 스크롤한 뒤 `Tab` 으로 리스트에 복귀한다
  3. `j` 로 선택을 옮겨 detail 스크롤이 맨 위로 돌아가는지 확인한다
  4. `p` 로 On을 토글하고 `g` 를 눌러 안내 메시지만 나오는지 확인한다
- **Expected Result**: On 토글은 `~/.claude.json` 의 `projects[<cwd>]` 에만 기록되고
  Proj/Glob 글리프는 변하지 않으며, `g` 는 파일을 건드리지 않고 안내만 낸다.
  detail 스크롤은 내용 끝을 넘지 않고 선택 이동 시 0으로 리셋된다.

---

## SC-E2E-008: Usage 리포트 검색 점프 여정 — 라이브 점프 → `Enter` → `n`/`N` → `Esc`

- **Objective**: Usage 탭의 `/` 가 목록 필터가 아니라 매칭 점프로 동작하는 전체
  사이클을 확인한다. (US-TUI07)
- **Priority**: High
- **Preconditions**: 알려진 문자열이 여러 줄에 나오도록 usage 엔트리를 배치.
  `state.usage_entries` 를 미리 채워 백그라운드 로더를 태우지 않는다
  (`_kick_usage_reload` 미호출 — 스레드 비의존).
- **Steps**:
  1. `/` 를 눌러 앵커를 잡고 질의어를 한 글자씩 입력한다
  2. 매칭이 사라지는 글자를 하나 더 입력해 앵커 복귀를 확인한다
  3. 지운 뒤 `Enter` 로 적용한다
  4. `n` / `N` 으로 매칭을 순회한다
  5. `Esc` 로 해제한다
- **Expected Result**: 타이핑 중 앵커 이후 첫 매칭으로 뷰포트가 따라가고, 매칭이
  없어지면 앵커로 돌아오며, 적용 후 상태바에 `match i/N` 이 뜬다. 입력 중 `Esc` 는
  취소 + 앵커 복귀, 적용 후 `Esc` 는 해제다.

---

## SC-E2E-009: Context Project 여정 — 정렬 → memory 선택 → `d` 확인 → 삭제 + 인덱스 정리

- **Objective**: 낱개 소스 목록에서 오래된 memory를 찾아 지우고, `MEMORY.md` 인덱스의
  해당 줄까지 정리되는 전체 흐름을 확인한다. (US-CTX05, US-CTX04)
- **Priority**: Critical
- **Preconditions**: `~/.claude/projects/<key>/memory/` 에 `.md` 2건과 그 둘을 가리키는
  `MEMORY.md` 인덱스. 90일 힌트를 쓰는 TC는 `os.utime` 으로 mtime을 명시 지정하고
  `datetime.now()` 와 섞지 않는다. `confirm_modal` 은 monkeypatch로 고정.
- **Steps**:
  1. `2` 로 Context 탭, Project 서브탭에서 시작한다
  2. `s` 를 눌러 정렬 컬럼을 옮기고 헤더 글리프를 확인한다
  3. `j` 로 memory 소스를 선택한다
  4. `d` 를 눌러 확인 모달을 승인한다
  5. `q` 로 종료한 뒤 파일과 `MEMORY.md` 를 확인한다
- **Expected Result**: 기본 정렬은 Tokens 내림차순이고 `s` 로 옮긴 컬럼 헤더에
  `Scope ▲` 같은 글리프가 붙는다. 삭제 후 memory 파일과 `MEMORY.md` 의 해당 줄이 함께
  사라지고, memory가 아닌 소스에서 `d` 는 거부된다.

---

## SC-E2E-010: Context Sources 여정 — 서브탭 전환 → rate limit 스트립 → detail 포커스

- **Objective**: Context 탭의 두 서브탭이 rate limit 스트립과 cost impact 라인을
  공유하고, 카테고리 롤업에서 detail 패널로 내려갔다 돌아오는지 확인한다.
  (US-CTX01, US-CTX06, US-TUI05)
- **Priority**: High
- **Preconditions**: rate limit 스냅샷 파일을 `tmp_path` 에 두고 `updated_at` 을
  고정 문자열로 심는다(신선도 판정이 시계에 의존하므로 **낡음/신선 두 값을 각각 명시**).
  `get_claude_version` · `get_git_status` 는 고정값 monkeypatch.
- **Steps**:
  1. Context 탭에서 `]` 로 Sources 서브탭으로 전환한다
  2. 상단 rate limit 스트립과 하단 cost impact 라인을 확인한다
  3. `Enter` 로 detail 패널에 포커스하고 `j` 로 스크롤한다
  4. `Esc` 로 복귀하고 `[` 로 Project 서브탭에 돌아간다
- **Expected Result**: 스트립과 cost impact 라인은 두 서브탭 모두에서 그려지고,
  cost impact는 가정(`30 turns × 5 sessions/day`)을 문구로 명시한다. detail 포커스
  중에는 `Esc` 가 탭을 벗어나지 않고 패널만 블러한다.

---

## SC-E2E-011: 훅 여정 — `v` dry-run 미리보기 → plugin 훅 읽기 전용 거부

- **Objective**: 켜기 전에 훅이 실제로 무엇을 실행하는지 확인하고, 플러그인 소유 훅은
  토글이 거부되는지 확인한다. (US-HK04, US-HK03, US-HK02)
- **Priority**: High
- **Preconditions**: user settings에 훅 1건 + 플러그인 제공 훅 1건. preview는
  `sh -c` 로 실제 실행되므로 **부작용 없는 명령**(`echo axt-preview-probe`)만 쓰고,
  실패 경로는 존재하지 않는 명령으로 만든다. `preview_modal` 은 인자 캡처용 stub.
- **Steps**:
  1. Hooks 서브탭에서 user 훅을 선택해 `v` 를 누른다
  2. 모달에 전달된 본문에서 exit code와 stdout을 확인한다
  3. 실패하는 훅으로 옮겨 `v` 를 눌러 TUI가 죽지 않는지 확인한다
  4. plugin 훅으로 옮겨 `p` / `g` 를 눌러 본다
- **Expected Result**: 미리보기 본문에 `Exit:` · stdout · stderr가 담기고, 실패해도
  모달로 보고된다. plugin 훅 토글은 읽기 전용 안내만 내고 설정 파일이 변하지 않는다.

---

## SC-E2E-012: 테마 토글 여정 — `t` 즉시 전환·저장, 검색 입력 중에는 질의어

- **Objective**: 전역 키가 즉시 반영·저장되면서, 모달/입력 상태가 키보드를 소유할 때는
  가로채지 않는지 확인한다. (US-TUI09, US-TUI08 AC2)
- **Priority**: Medium
- **Preconditions**: `AXT_CONFIG_PATH` 를 `tmp_path/config.json` 으로 고정.
  `_persist_theme` 는 실제 호출하되 대상 파일이 `tmp_path` 안이 되도록 한다.
- **Steps**:
  1. `t` 를 눌러 테마를 전환한다
  2. config 파일에 저장된 값을 확인한다
  3. Vault 서브탭에서 `/` 로 검색 입력에 들어간 뒤 `t` 를 누른다
  4. `Esc` 로 취소하고 `q` 로 종료한다
- **Expected Result**: 첫 `t` 는 팔레트를 재초기화하고 config에 새 값을 남기지만,
  검색 입력 중의 `t` 는 테마를 바꾸지 않고 질의어에 들어간다.

---

## SC-E2E-013: 좁은 터미널 여정 — 최소 크기 미만 안내와 리사이즈 복구

- **Objective**: 분할 터미널·리사이즈 상황에서 레이아웃이 무너지거나 크래시하지 않는지
  확인한다. (US-TUI10)
- **Priority**: High
- **Preconditions**: `getmaxyx` 를 시퀀스로 돌려주는 stdscr를 만들어 프레임마다 다른
  크기를 보고하게 한다. CJK 이름을 가진 항목을 최소 1건 포함시킨다.
- **Steps**:
  1. `h=4, w=20` 상태에서 프레임을 그린다
  2. `KEY_RESIZE` 를 흘려 넣고 정상 크기로 복귀시킨다
  3. 좁은 폭에서 CJK 이름 행이 그려지는지 확인한다
- **Expected Result**: 최소 크기 미만에서는
  `Terminal too small. Resize and try again.` 만 그려지고, 리사이즈 후에는 정상
  프레임이 복구된다. 컬럼이 잘려도 예외가 나지 않고 CJK 폭 계산으로 정렬이 유지된다.

---

## SC-E2E-014: 도움말 여정 — `?` 로 열고 닫기, 내용이 실제 키맵에서 생성됨

- **Objective**: 도움말이 코드의 키맵에서 생성되어 어긋나지 않고, 모달이 열린 동안
  전역 키가 입력을 가로채지 않는지 확인한다. (US-TUI08)
- **Priority**: Medium
- **Preconditions**: `preview_modal` 을 제목·본문 캡처 stub으로 교체.
- **Steps**:
  1. `?` 를 눌러 도움말을 연다
  2. 캡처된 본문에서 각 서브탭의 정렬 순환 문구를 확인한다
  3. 도움말을 닫고 `q` 로 종료한다
- **Expected Result**: 모달 제목은 `axt help` 이고, 본문의 정렬 순환 목록이
  `_SORT_COLUMNS` 에서 생성된 값과 일치한다. 모달 처리 중에는 다른 키가 탭을 바꾸지
  않는다.

---

## SC-E2E-015: 업데이트 여정 — Market 서브탭 `u` 적용 → `Upd` 마커 즉시 갱신

- **Objective**: 백그라운드 확인 결과가 컬럼에 반영되고, 적용 성공 시 해당 행의 마커가
  다시 조회하지 않아도 최신으로 바뀌는지 확인한다. (US-UPD05, US-UPD06, US-MKT02)
- **Priority**: High
- **Preconditions**: 마켓 2건 등록. `state.update_statuses` 를 직접 심어
  "확인 완료 + 업데이트 가능" 상태를 만든다(백그라운드 스윕은 conftest가 차단).
  `sync_marketplace` 는 결정적 결과를 돌려주는 stub으로 교체 — 네트워크·git 비의존.
- **Steps**:
  1. Market 서브탭에서 업데이트 가능한 행을 선택한다
  2. `u` 를 눌러 적용한다
  3. 같은 프레임에서 해당 행의 `Upd` 셀을 확인한다
  4. 실패하는 항목을 섞어 `Space` 마크 후 일괄 `u` 를 수행한다
- **Expected Result**: 확인 전에는 `…`, 확인 후에는 `↑`/`·`/`!`/`─` 로 바뀌고, 적용
  성공한 행은 즉시 `·` 가 된다. 일괄 적용에서 한 항목의 실패가 나머지를 중단시키지
  않고 상태바에 `N updated, N up to date, N failed` 집계가 뜬다.

---

## 스펙 갭

### G-5. Usage 탭은 포커스 가능한 본문이 없어 `Esc` 단계 축소가 한 단계다
- 스펙: US-TUI02 AC3 "포커스 가능한 본문이 없는 탭(Usage)은 `↓` 를 받아도 mainTab에
  머문다", US-TUI07 AC5 "적용 후 Esc는 해제"
- 관찰: Usage는 subTab이 없어 content 레이어에 들어가는 경로가 `_handle_layer_key`
  기준으로 mainTab에서 직접 내려가는 형태다. 검색 적용 상태에서의 `Esc` 우선순위는
  `axt/tui/loop.py:428` 의 예외 분기가 담당한다. 두 스토리를 함께 만족시키는 상태
  전이표가 FEATURES.md에 명시돼 있지 않아 SC-E2E-008에서는 검색 해제까지만 단언한다.

### G-6. Commands / Agents 서브탭의 `e` 편집 여정은 외부 프로세스에 의존한다
- 스펙: US-LNK06 AC1·AC2
- 관찰: `open_in_editor` 가 `$EDITOR` 프로세스를 띄운다. 헤드리스 E2E에서 실제 실행은
  검증 대상으로 부적합해 시나리오 집합에서 제외했다. `$EDITOR` 미설정 시 안내 문구
  경로는 unit/integration이 stub 없이 검증할 수 있다.
