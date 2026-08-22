# Performance 테스트 시나리오

## 측정 원칙 — 벽시계 대신 작업량

axt는 공유 CI·개발자 노트북·터미널 안에서 돈다. 벽시계 임계값(`< 200ms`)을 단언하면
머신 부하에 따라 무작위로 깨지는 **플레이키 테스트**가 된다. `quality-criteria.md` 의 LCP/FID/TTFB 표는
브라우저 지표라 이 프로젝트에 해당 사항이 없다.

따라서 이 도메인의 기본 단언은 **호출 횟수·복잡도 상한**이다.

| 방식 | 사용 조건 |
|---|---|
| **호출 횟수 상한** (기본) | 캐시 적중, 정렬 키 빌더, 파일 I/O 반복 — 스파이로 카운트 |
| **복잡도 관계** | 입력을 2배로 늘렸을 때 작업량이 2배 이하인지 (n log n 이 아니라 n 임을 확인) |
| **벽시계 상한** (예외) | 위 둘로 표현할 수 없을 때만. 이때 **넉넉한 천장**과 **머신 가정**을 명시 |

**벽시계 TC의 머신 가정**: 2020년 이후 개발자 노트북/CI 러너(2 vCPU 이상, SSD).
임계값은 관측 중앙값의 **10배** 이상으로 잡아 정상 머신에서는 절대 걸리지 않게 한다.
임계값을 넘겼다면 그것은 "조금 느려짐"이 아니라 **알고리즘이 바뀐 것**이다.

- 스펙 출처: `US-USG08`(대용량 JSONL), `US-UPD05`(비동기 Upd + TTL 캐시), `US-TUI03`(정렬),
  `US-TUI04`(검색), `US-CTX01`(컨텍스트 분석), `US-VLT07`(프로젝트 스캔), `FEATURES.md` §3.13 / §7.3
- Layer Owner: `tests/test_perf.py` (`TEST_DEDUP_POLICY.md` §2 — 대용량 입력의 시간·호출횟수 상한)

## 결정성 주의 — 이 저장소의 실제 사고 이력

1. **`datetime.now()` 를 가짜로 바꾸면서 파일 mtime 은 진짜로 두면 안 된다.**
   방금 만든 파일이 가짜 `now()` 기준으로 131일 된 것처럼 보인 사고가 있었다.
   캐시 신선도(`is_cache_valid`, `_update_status_fresh`)를 다루는 TC는 **mtime 과 now() 를 함께** 고정하거나,
   둘 다 실제 시계로 두고 상대 시간만 쓴다.
2. `plan overview` 계열 테스트가 월중 날짜에만 통과한 사고가 있었다. 시계 의존 경로는 주입 지점을 고정한다.
3. 모든 TC는 `tmp_path` + `monkeypatch` 로 HOME·cwd·`axt.PATHS`·`axt.AXT_CONFIG_PATH` 를 격리한다.

---

## SC-PERF-001 — 변경되지 않은 JSONL은 다시 파싱되지 않는다

- **Objective**: `US-USG08` AC1 — 파일 mtime 기반 캐시를 쓰며 변경 없으면 재파싱하지 않는다.
  작업량이 **총 파일 수가 아니라 변경 파일 수에 비례**해야 한다.
- **Preconditions**
  - `axt.PATHS.projects` 를 `tmp_path/"projects"` 로 교체
  - 캐시 경로(`AXT_CONFIG_DIR`)도 `tmp_path` 로 교체 — 사용자 실제 캐시를 절대 읽지 않는다
  - 200개 세션 파일(프로젝트 4개 × 파일 50개), 각 파일 20줄
  - `parse_claude_jsonl` 을 **원본을 호출하는 카운팅 래퍼**로 교체(동작은 유지, 호출만 센다)
- **Steps**
  1. 1회차 `load_all_claude_usage(projects)` — 콜드 캐시
  2. 카운터 리셋
  3. 파일 1개만 내용을 바꾸고 `os.utime` 으로 mtime 을 명시적으로 +2초 (파일시스템 mtime 해상도 회피)
  4. 2회차 `load_all_claude_usage(projects, force_refresh=True)` — 전체 캐시 게이트는 건너뛰되 per-file 캐시는 살린다
- **Expected Result**
  - 1회차 파싱 호출 수 == 200
  - 2회차 파싱 호출 수 == **1** (변경된 파일만)
  - 두 회차의 엔트리 총수가 동일하고 합계 토큰이 정확히 일치한다
- **Priority**: Critical

---

## SC-PERF-002 — 신선한 v2 캐시는 파일시스템을 다시 훑지 않는다

- **Objective**: `US-USG08` AC1/AC2 — 캐시가 신선하면(`is_cache_valid`) 디렉터리 글로브와 mtime stat 조차
  건너뛰고 캐시에서 바로 복원한다. 읽기 비용이 **엔트리 수에만** 비례한다.
- **Preconditions**
  - SC-PERF-001 과 같은 200파일 구성으로 캐시를 미리 채운다
  - `Path.glob` 을 카운팅 래퍼로 감싼다
  - **시계 주의**: `is_cache_valid` 는 캐시의 `lastUpdated` 와 현재 시각을 비교한다.
    `now()` 를 가짜로 만들지 말고, 캐시를 방금 쓴 뒤 곧바로 읽어 실제 시계 안에서 신선하게 유지한다
- **Steps**
  1. 캐시를 채운다
  2. 카운터 리셋
  3. `force_refresh=False` 로 재호출
- **Expected Result**
  - `parse_claude_jsonl` 호출 0회
  - `*/*.jsonl` 글로브 호출 0회
  - 반환 엔트리가 1회차와 **완전히 동일**(개수·모델·세션·토큰)
- **Priority**: High

---

## SC-PERF-003 — 컬럼 정렬이 행마다 파일시스템/설정을 다시 읽지 않는다

- **Objective**: `US-TUI03` AC6/AC8 — 글리프 컬럼(`Vault`/`Proj`/`Glob`/`Upd`/`On`)은
  화면 글리프 기준으로 정렬된다. 이때 셀 값 계산이 **비교 함수 안**에서 일어나면
  `O(n log n)` 번 `Path.resolve()` 나 settings 파싱이 돌아 500행에서 체감 정지가 난다.
  구현은 키빌더(`_by_glyph`/`_by_scope_glyph`/`_by_state`)로 **행당 1회**만 계산하도록 설계되어 있다.
- **Preconditions**
  - Skills 서브탭 500행 주입 (`state.ext_cache["skills"]`)
  - `_vault_cell`·`_upd_cell`·`_scope_ctx`·`read_enabled_plugins` 를 카운팅 래퍼로 감싼다
  - `state.update_statuses` 직접 주입 — 네트워크·스레드 배제
- **Steps**
  1. `Vault` 컬럼으로 정렬 → `_vault_cell` 호출 수 확인
  2. `Upd` 컬럼으로 정렬 → `_upd_cell` 호출 수 확인
  3. Plugins 서브탭 500행에서 `Proj` 정렬 → `read_enabled_plugins` 호출 수 확인
- **Expected Result**
  - `_vault_cell` 호출 수 ≤ 500 (행당 1회). `500 * log2(500) ≈ 4482` 근처면 실패
  - `_upd_cell` 호출 수 ≤ 500
  - `read_enabled_plugins` 호출 수 ≤ 2 (project 1 + global 1) — 정렬 전체에서 settings 파일을 2번만 읽는다
  - 정렬 결과 행 수는 500 그대로 (US-TUI03 AC8)
- **Priority**: Critical

---

## SC-PERF-004 — 컨텍스트 분석이 큰 프로젝트에서 상한 안에 끝난다

- **Objective**: `US-CTX01` AC1 — 12개 카테고리를 모두 집계하면서도 세션 시작 분석이 실용 시간 안에 끝난다.
- **Preconditions**
  - 가짜 프로젝트: `.claude/skills` 200개(각 `SKILL.md` 프론트매터 포함), `.claude/commands` 200개,
    `.claude/agents` 100개, `memory/*.md` 100개, `CLAUDE.md` 3곳
  - `git status` 서브프로세스는 스텁으로 교체(외부 명령·저장소 상태 의존 제거)
  - MCP 서버 30개를 `~/.claude.json` 에 등록
- **Steps**
  1. `collect_context_sources(...)` 를 1회 호출하며 `time.perf_counter()` 로 측정
  2. 각 파일이 **정확히 1번씩만** 열렸는지 `Path.read_text` 카운팅 래퍼로 확인
- **Expected Result**
  - 소스 수가 예상 개수와 일치 (200+200+100+100+3+30+고정 3 = 636 ± 카테고리별 고정행)
  - 같은 파일을 두 번 읽지 않는다 — 파일별 `read_text` 호출 ≤ 1
  - 벽시계 상한 **5초** (머신 가정: 2 vCPU 이상, SSD). 이를 넘으면 파일당 반복 스캔이 들어간 것이다
- **Priority**: High

---

## SC-PERF-005 — TUI 프레임 렌더가 보이는 행 수에만 비례한다

- **Objective**: `US-TUI10` + `FEATURES.md` §2.10 — 500행 목록이어도 화면에 그리는 셀은
  **보이는 행 수**만큼이어야 한다. 전체 행을 그린 뒤 잘라내는 구현이면 목록이 커질수록 프레임이 느려진다.
- **Preconditions**
  - fake stdscr `(rows=30, cols=140)` — 본문에 들어가는 행은 대략 15~20행
  - Skills 서브탭에 500행 주입, 선택 인덱스 0
- **Steps**
  1. 500행으로 렌더 → `addnstr` 호출 수 `N500`
  2. 같은 화면 크기, 50행으로 렌더 → 호출 수 `N50`
- **Expected Result**
  - `N500 == N50` (± 헤더/상태바 상수 차이 몇 건) — 데이터가 10배여도 그리기 호출이 늘지 않는다
  - `N500` 이 화면 셀 수(30 × 140)를 넘지 않는다
  - 선택 행이 화면 안에 있다
- **Priority**: High

---

## SC-PERF-006 — 프로젝트 사용량 스캔이 프로젝트 수에 선형이다

- **Objective**: `US-VLT07` AC1/AC4 — `scan_project_usage` 는 `~/.claude/projects/*` 를 훑어
  항목별 사용 프로젝트 목록을 만든다. 프로젝트가 늘어도 **프로젝트당 상수 회의 디렉터리 접근**이어야 한다.
- **Preconditions**
  - `projects_dir` 에 200개 프로젝트 디렉터리(각각 `.axt-profile.json` + `.claude/skills` 심볼릭 링크 2개)
  - vault 에 항목 20개
  - `default` 모드와 `full` 모드를 각각 측정
  - `decode_project_dir_name` 의 brute-force 매칭이 실제 파일시스템을 훑으므로 **tmp_path 안에서만** 수행
- **Steps**
  1. 100개 프로젝트로 스캔 → 디렉터리 순회 횟수 `D100`
  2. 200개 프로젝트로 스캔 → `D200`
- **Expected Result**
  - `D200 <= D100 * 2.2` — 선형(약간의 오버헤드 허용). 제곱이면 4배가 되어 실패
  - 두 모드 모두에서 결과 인덱스의 항목 수가 20으로 동일
  - 스캔 결과가 없어도(빈 projects_dir) 0건으로 정상 종료 (AC4)
- **Priority**: Medium

---

## SC-PERF-007 — 업데이트 확인이 TTL 안에서는 다시 조회하지 않는다

- **Objective**: `US-UPD05` AC2 — 결과는 `<AXT_CONFIG_DIR>/cache/update-status.json` 에 TTL 1시간으로 캐시된다.
  TTL 안에서는 네트워크 스윕(`check_all_updates`)을 아예 시작하지 않는다.
- **Preconditions**
  - `AXT_CONFIG_DIR` → `tmp_path`
  - `check_all_updates` 를 카운팅 스텁으로 교체 — **네트워크 절대 금지**
  - `threading.Thread` 를 동기 실행 스텁으로 교체(`tests/test_tui.py::_StubThread` 방식)해 결정적으로 만든다
  - **시계 주의**: 캐시의 `checkedAt` 을 "지금"으로 쓰고 곧바로 읽는다. `datetime.now()` 를 가짜로 만들면
    파일 mtime 과 어긋나 신선도 판정이 뒤집힌다
- **Steps**
  1. `_kick_update_check(state)` 1회 → 스윕 1회, 캐시 파일 생성 확인
  2. 새 `TuiState` 로 `_kick_update_check(state2)` → 캐시 복원
  3. 같은 상태에서 `_kick_update_check(state2)` 재호출
  4. `_kick_update_check(state2, force=True)` 호출
- **Expected Result**
  - 2·3 단계에서 `check_all_updates` 호출 수 증가분 **0**
  - 4 단계(`force=True`)에서만 +1
  - 복원된 마커가 1단계 결과와 동일 (캐시가 값을 잃지 않는다)
- **Priority**: High

---

## SC-PERF-008 — 검색 필터가 목록을 한 번만 훑는다

- **Objective**: `US-TUI04` AC2/AC3 — 서브탭별 검색은 표시 목록을 만드는 단일 패스여야 한다.
  항목마다 haystack 을 여러 번 만들거나, 필터 후 다시 정렬하면 큰 목록에서 타이핑이 끊긴다.
- **Preconditions**
  - Skills 서브탭 2,000행 주입 (이름은 `skill-0000` ~ `skill-1999`, 그중 111개가 `"77"` 을 포함)
  - `_subtab_search_haystack` 을 카운팅 래퍼로 감싼다
  - `_apply_sort` 도 카운팅 래퍼로 감싼다
- **Steps**
  1. `state.ext_search["skills"] = "77"` 설정
  2. `_subtab_view(state, "skills")` 1회 호출
- **Expected Result**
  - `_subtab_search_haystack` 호출 수 ≤ 2,000 (행당 1회)
  - `_apply_sort` 호출 수 == 1 (필터 전 1회. 필터 후 재정렬 금지)
  - 반환 행 수 == 111, 순서가 정렬 기준을 유지한다
  - 벽시계 상한 **1초** (머신 가정 위와 동일)
- **Priority**: Medium

---

## 스펙 갭

| # | 관측 | 관련 US | 판단 |
|---|---|---|---|
| G-PERF-1 | 어떤 성능 목표치(응답 시간·목록 크기 상한)도 스펙에 수치로 없다 | US-USG08, US-TUI10 | **문서 갭**. 스토리는 "빠르게 뜬다"까지만 말한다. 이 문서는 수치를 단언하는 대신 **작업량 상한**을 계약으로 삼았다. 수치가 필요하면 스토리에 AC를 추가해야 한다 |
| G-PERF-2 | 정렬 키빌더의 "행당 1회" 계약이 코드 주석에만 있다 | US-TUI03 AC6 | **문서 갭**. 성능 계약이므로 스토리 AC로 승격 가치가 있다. 지금은 SC-PERF-003 이 회귀 방어를 맡는다 |
| G-PERF-3 | `_kick_vault_scan` 의 워커에는 `except` 가 없다(`finally` 만 있음) | US-UPD05 AC4 | **구현 갭**(chaos 도메인 SC-CHAOS-009 에서 다룸). 성능 관점에서는 스캔 실패 후 매 프레임 재시도로 이어지는지 확인 필요 |
| G-PERF-4 | 컨텍스트 분석에 캐시가 없다 — `r` 이나 탭 전환마다 전체 재수집 | US-CTX01, US-PRJ05 AC1 | **관측**. `_invalidate_context` 가 존재하는 것으로 보아 캐시 개념은 있으나 분석 자체의 재사용 정책이 스토리에 없다 |
