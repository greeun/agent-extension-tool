# Performance 테스트 케이스

Layer Owner: `tests/test_perf.py`
시나리오 출처: [performance-scenarios.md](../scenarios/performance-scenarios.md)

> **측정 원칙**: 벽시계가 아니라 **호출 횟수·복잡도 상한**을 단언한다.
> 벽시계를 쓰는 TC(TC-PERF-010 · 018)는 머신 가정과 넉넉한 천장을 명시한다.
> **결정성**: 모든 TC 는 `tmp_path` + `monkeypatch` 로 HOME·cwd·`axt.PATHS`·`AXT_CONFIG_DIR` 를 격리한다.
> 시계를 가짜로 만들면서 파일 mtime 은 진짜로 두는 조합을 **금지**한다(이 저장소의 실제 플레이키 사고 원인).

## 요약

| 항목 | 값 |
|---|---|
| **총 TC 수** | **18** (그중 1건은 기존 테스트가 소유 → 신규 작성 대상 17건) |
| 우선순위 | Critical 5 / High 9 / Medium 4 / Low 0 |
| Gap | COVERED 1 / PARTIAL 3 / NEW 14 |
| 벽시계 단언을 쓰는 TC | 2 (TC-PERF-010 · TC-PERF-018) — 나머지 16건은 호출 횟수/복잡도만 본다 |

## TC 인덱스

| TC ID | 시나리오 | 제목 | US | 우선순위 | Gap |
|---|---|---|---|---|---|
| TC-PERF-001 | SC-PERF-001 | 200파일 중 1개만 바뀌면 파싱도 1회만 일어난다 | US-USG08 AC1 | Critical | PARTIAL |
| TC-PERF-002 | SC-PERF-001 | 캐시 경유 전후의 토큰 합계가 정확히 같다 | US-USG08 AC1 | High | PARTIAL |
| TC-PERF-003 | SC-PERF-002 | 신선한 캐시에서는 디렉터리 글로브가 0회다 | US-USG08 AC2 | High | NEW |
| TC-PERF-004 | SC-PERF-002 | 캐시 복원 결과가 콜드 로드와 완전히 동일하다 | US-USG08 AC2 | High | NEW |
| TC-PERF-005 | SC-PERF-003 | `Vault` 정렬이 행당 `_vault_cell` 1회만 호출한다 | US-TUI03 AC6 | Critical | NEW |
| TC-PERF-006 | SC-PERF-003 | `Upd` 정렬이 행당 `_upd_cell` 1회만 호출한다 | US-TUI03 AC6 | Critical | NEW |
| TC-PERF-007 | SC-PERF-003 | `Proj` 정렬이 settings 파일을 2회만 읽는다 | US-TUI03 AC6 | Critical | NEW |
| TC-PERF-008 | SC-PERF-003 | 정렬 전후 행 수가 보존된다(500행) | US-TUI03 AC8 | High | NEW |
| TC-PERF-009 | SC-PERF-004 | 컨텍스트 분석이 같은 파일을 두 번 읽지 않는다 | US-CTX01 AC1 | High | NEW |
| TC-PERF-010 | SC-PERF-004 | 636개 소스 분석이 5초 상한 안에 끝난다 | US-CTX01 AC1 | Medium | NEW |
| TC-PERF-011 | SC-PERF-005 | 행이 10배여도 그리기 호출 수가 늘지 않는다 | US-TUI10 | Critical | NEW |
| TC-PERF-012 | SC-PERF-005 | 그리기 호출이 화면 셀 수를 넘지 않는다 | US-TUI10 AC2 | High | NEW |
| TC-PERF-013 | SC-PERF-006 | 프로젝트 수 2배에 스캔 작업량이 2.2배 이하다 | US-VLT07 AC1 | Medium | NEW |
| TC-PERF-014 | SC-PERF-006 | 빈 projects 디렉터리에서 0건으로 끝난다 | US-VLT07 AC4 | Medium | NEW |
| TC-PERF-015 | SC-PERF-007 | 신선한 캐시에서는 백그라운드 스윕을 시작하지 않는다 | US-UPD05 AC2 | High | COVERED |
| TC-PERF-016 | SC-PERF-007 | `force=True` 만 TTL을 무시하고 재확인한다 | US-UPD05 AC3 | High | NEW |
| TC-PERF-017 | SC-PERF-007 | 디스크 캐시 복원이 마커 값을 잃지 않는다 | US-UPD05 AC2 | Medium | PARTIAL |
| TC-PERF-018 | SC-PERF-008 | 2,000행 검색이 단일 패스로 111행을 남긴다 | US-TUI04 AC2 | High | NEW |

---

## SC-PERF-001 — JSONL 재파싱 회피

### TC-PERF-001 — 200파일 중 1개만 바뀌면 파싱도 1회만 일어난다

- **US**: US-USG08 AC1 / **Priority**: Critical / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_usage_claude.py::test_load_all_claude_usage_per_file_cache_hit_skips_reparse` 가
  **파일 1개** 상황을 덮는다. 규모에서의 불변식 — 작업량이 **총 파일 수가 아니라 변경 파일 수에 비례** — 은 미검증.
  파일 수 루프 안에 캐시 조회를 넣지 않은 리팩터가 1파일 테스트는 통과시키고 200파일에서만 터진다.
- **Preconditions**
  - `monkeypatch.setattr("axt.PATHS", …)` 로 `projects = tmp_path/"projects"`
  - `AXT_CONFIG_DIR` → `tmp_path/"axtcfg"` (사용자 캐시 접근 차단)
  - 4개 프로젝트 × 50개 세션 파일 = 200파일. 각 파일 20줄, 모델은 `claude-sonnet-5` 고정
  - `parse_claude_jsonl` 을 **원본 호출 + 카운트** 래퍼로 교체 (`monkeypatch.setattr("axt.core.parse_claude_jsonl", counting)`)
- **Input / Steps**
  1. `axt.load_all_claude_usage(projects_dir)` — 콜드
  2. `counter.reset()`
  3. 파일 1개에 줄 1개 추가 후 `os.utime(path, (t+2, t+2))` — **mtime 을 명시적으로 진행**시킨다
     (파일시스템 mtime 해상도가 1초인 환경에서 같은 초 안의 수정이 캐시 적중으로 잘못 판정되는 것을 막는다)
  4. `axt.load_all_claude_usage(projects_dir, force_refresh=True)`
- **Expected Output**
  - 1단계 파싱 호출 수 == 200
  - 4단계 파싱 호출 수 == **1**
  - 4단계 반환 엔트리 수 == 1단계 + 1
- **실패 시 조치**: mtime 비교(`float(cached_file.get("m", 0)) >= mtime`)가 루프 안에 남아 있는지 확인.
  캐시 키가 절대경로에서 다른 것으로 바뀌었으면 전량 재파싱이 된다.

### TC-PERF-002 — 캐시 경유 전후의 토큰 합계가 정확히 같다

- **US**: US-USG08 AC1 / **Priority**: High / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `test_load_all_claude_usage_cache_roundtrip` 이 소규모 왕복을 덮으나,
  v2 intern 테이블(모델/세션 인덱스)이 **200파일 · 다중 모델** 규모에서 인덱스 충돌 없이 복원되는지는 미검증.
- **Preconditions**: TC-PERF-001 구성 + 모델 4종(`claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5`, `claude-fable-5`) 섞기
- **Steps**
  1. 콜드 로드 결과의 `(model, sessionId)` 별 토큰 합계 딕셔너리 `A` 를 만든다
  2. 캐시 경유 로드 결과로 `B` 를 만든다
- **Expected Output**
  - `A == B` (키 집합·값 모두 정확히 일치)
  - 모델 이름이 인덱스로 저장되었다가 **원문 문자열로** 복원된다 (intern 테이블 오프바이원 방지)

---

## SC-PERF-002 — 신선한 캐시 단축 경로

### TC-PERF-003 — 신선한 캐시에서는 디렉터리 글로브가 0회다

- **US**: US-USG08 AC2 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - TC-PERF-001 구성으로 캐시를 먼저 채운다
  - `Path.glob` 을 카운팅 래퍼로 감싼다 (`monkeypatch.setattr(Path, "glob", counting_glob)`)
  - **시계 처리**: `datetime.now()` 를 monkeypatch 하지 **않는다**. 캐시를 방금 쓴 직후 읽어
    실제 시계 기준으로 TTL(5분) 안에 들어가게 한다 — 가짜 시계와 실제 mtime 을 섞지 않는다
- **Input**: `axt.load_all_claude_usage(projects_dir)` — `force_refresh` 없음
- **Expected Output**
  - `parse_claude_jsonl` 호출 0회
  - `*/*.jsonl` 패턴 글로브 호출 0회
  - `Path.stat` 호출이 세션 파일에 대해 0회 (200회 stat 이 나면 단축 경로가 안 탄 것)

### TC-PERF-004 — 캐시 복원 결과가 콜드 로드와 완전히 동일하다

- **US**: US-USG08 AC2 / **Priority**: High / **Gap**: NEW
- **Preconditions**: TC-PERF-003 과 동일
- **Steps**: 콜드 결과 리스트와 캐시 결과 리스트를 각각 `(model, session_id, input, output, cache_create, cache_read, ts)` 튜플의 정렬된 리스트로 변환해 비교
- **Expected Output**
  - 두 리스트가 완전히 같다
  - `projectPath` 가 캐시에 저장되지 않고 **파일 키에서 파생**되므로(FEATURES.md §3.13),
    `--project` 필터 결과도 두 경로에서 동일하다
- **왜 필요한가**: 성능 단축 경로가 조용히 데이터를 잃으면 비용 보고가 틀린다.
  "빨라졌다"만 보고 정확성을 안 보면 최악의 회귀가 통과한다.

---

## SC-PERF-003 — 정렬 키빌더의 행당 1회 계약

### TC-PERF-005 — `Vault` 정렬이 행당 `_vault_cell` 1회만 호출한다

- **US**: US-TUI03 AC6 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `state.ext_cache["skills"]` 에 500개 `SkillInfo` 주입 (경로는 vault/비-vault 섞기)
  - `axt.tui.tabs._vault_cell` 을 원본 호출 + 카운트 래퍼로 교체
  - `state.update_statuses` 를 빈 dict 로 주입 — 백그라운드 스레드 배제
  - `monkeypatch.chdir(tmp_path)`, `axt.PATHS` tmp 기반
- **Input**: `state.ext_sort["skills"] = ("vault", False)` 후 `_apply_sort(state, "skills", data)`
- **Expected Output**
  - `_vault_cell` 호출 수 ≤ **500**
  - 비교 기반 구현이면 `500 * log2(500) ≈ 4,482` 근처가 나온다 — 그 경우 실패
  - 정렬 결과가 `✓` 행 먼저, `─` 행 나중 (`_ON_RANK` 순서)
- **실패 시 조치**: `_SORT_COLUMNS` 의 해당 항목이 `_by(...)` (행별 즉시 계산)로 바뀌지 않았는지 확인.
  글리프 컬럼은 반드시 `_by_glyph` / `_by_scope_glyph` 키빌더를 써야 한다.

### TC-PERF-006 — `Upd` 정렬이 행당 `_upd_cell` 1회만 호출한다

- **US**: US-TUI03 AC6 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**: TC-PERF-005 와 동일 + `state.update_statuses` 에 500행 중 200행 분의 상태 주입
- **Expected Output**
  - `_upd_cell` 호출 수 ≤ 500
  - 정렬 결과가 `↑ → ! → … → · → ─` 순 (`_UPD_RANK`)
  - 상태가 없는 행도 예외 없이 마지막 그룹으로 간다

### TC-PERF-007 — `Proj` 정렬이 settings 파일을 2회만 읽는다

- **US**: US-TUI03 AC6 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - Plugins 서브탭에 500개 `PluginInfo` 주입
  - `axt.tui.tabs.read_enabled_plugins` 를 카운팅 래퍼로 교체
  - project/global settings 파일을 각각 `tmp_path` 에 실제로 만들어 둔다(읽기 실패로 조기 반환하지 않게)
- **Input**: `Proj` 컬럼으로 정렬
- **Expected Output**
  - `read_enabled_plugins` 호출 수 ≤ **2** (project 1 + global 1)
  - 500회에 가까우면 `_scope_ctx` 가 행마다 다시 만들어지고 있는 것 — 실패
  - `●`(enabled) → `○`(disabled) → `·`(unset) 순으로 정렬된다 (US-PLG01 AC3 의 3상태가 뭉개지지 않는다)

### TC-PERF-008 — 정렬 전후 행 수가 보존된다(500행)

- **US**: US-TUI03 AC8 / **Priority**: High / **Gap**: NEW
- **Preconditions**: 500행, 그중 30행은 `version=None`, 20행은 이름에 CJK 포함, 10행은 필드 일부 누락
- **Steps**: Skills 서브탭의 9개 정렬 컬럼을 `s` 로 한 바퀴 순회하며 매번 행 수 확인
- **Expected Output**
  - 모든 컬럼에서 결과 행 수 == 500
  - `_apply_sort` 의 방어적 `except (TypeError, AttributeError, OSError)` 폴백이 발동해도 행이 사라지지 않는다
  - 예외 0건
- **왜 성능 파일에 두는가**: 이 단언은 정렬 **정확성**이 아니라, 성능을 위해 도입한 키빌더 캐시
  (`{id(i): rank}` 딕셔너리)가 행을 누락시키지 않는다는 **성능 최적화의 안전성** 검증이다.
  `id()` 기반 매핑은 동일 객체가 리스트에 두 번 들어가면 조용히 어긋난다.

---

## SC-PERF-004 — 컨텍스트 분석 규모

### TC-PERF-009 — 컨텍스트 분석이 같은 파일을 두 번 읽지 않는다

- **US**: US-CTX01 AC1 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - `proj = tmp_path/"proj"`; `.claude/skills` 200개(각 `SKILL.md`), `.claude/commands` 200개(`.md`),
    `.claude/agents` 100개(`.md`), `home/.claude/projects/<key>/memory` 100개(`.md`), `CLAUDE.md` 3곳
  - `~/.claude.json` 에 MCP 서버 30개
  - `git status` 서브프로세스를 고정 문자열 반환 스텁으로 교체
  - `pathlib.Path.read_text` 를 경로별 호출 횟수를 세는 래퍼로 교체
- **Input**: `collect_context_sources(home_dir=home, project_dir=proj, installed_plugins_path=ip)`
- **Expected Output**
  - 어떤 경로도 `read_text` 호출 수 > 1 이 아니다
  - 카테고리별 소스 수: skills 200 / commands 200 / agents 100 / memory 100 / claude-md 3 / mcp-tools 30
  - `.agents/skills` · `.agents/agents` 를 심어 두어도 결과에 포함되지 않는다 (US-CTX03 AC1/AC2 —
    잘못 포함하면 작업량과 수치가 동시에 틀린다)

### TC-PERF-010 — 636개 소스 분석이 5초 상한 안에 끝난다

- **US**: US-CTX01 AC1 / **Priority**: Medium / **Gap**: NEW
- **머신 가정**: 2020년 이후 개발자 노트북 또는 CI 러너, 2 vCPU 이상, SSD.
  상한 5초는 관측 중앙값의 10배 이상으로 잡은 값이라 정상 머신에서는 걸리지 않는다.
  **걸렸다면 파일당 반복 스캔이나 O(n²) 경로가 들어간 것**이다.
- **Preconditions**: TC-PERF-009 와 동일 픽스처 (`read_text` 래핑은 제거 — 오버헤드 배제)
- **Steps**: `time.perf_counter()` 로 `collect_context_sources` 1회 실행 시간 측정
- **Expected Output**
  - 경과 시간 < 5.0초
  - 반환 소스 수 > 600 (픽스처가 실제로 만들어졌다는 대조 — 0건을 빠르게 반환하는 허위 통과 방지)
- **허위 양성 방지**: 시간 단언만 두면 픽스처 생성이 실패해도 "빠르게" 통과한다.
  반드시 소스 수 단언을 함께 둔다.

---

## SC-PERF-005 — 프레임 렌더 상한

### TC-PERF-011 — 행이 10배여도 그리기 호출 수가 늘지 않는다

- **US**: US-TUI10 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - fake stdscr `(rows=30, cols=140)`
  - Skills 서브탭 데이터를 50행 / 500행 두 벌 준비 (필드는 동일 패턴)
  - `state.update_statuses = {}`, `monkeypatch.chdir(tmp_path)`
- **Steps**
  1. 50행으로 `_render_frame` → `len(scr.calls)` = `N50`
  2. 새 fake stdscr 로 500행 렌더 → `N500`
- **Expected Output**
  - `abs(N500 - N50) <= 5` — 헤더/상태바 상수 차이만 허용
  - `N500 < N50 * 2` 를 반드시 만족 (10배 데이터에 2배 미만)
- **실패 시 조치**: 렌더러가 전체 행을 만든 뒤 슬라이스하는 구조인지 확인.
  뷰포트 계산을 먼저 하고 그 범위만 그려야 한다.

### TC-PERF-012 — 그리기 호출이 화면 셀 수를 넘지 않는다

- **US**: US-TUI10 AC2 / **Priority**: High / **Gap**: NEW
- **Preconditions**: `(rows=30, cols=140)`, 500행
- **Expected Output**
  - `len(scr.calls) <= 30 * 4` — 행당 그리기 호출은 컬럼 수 수준이지 셀 수 수준이 아니다
    (구체 상한은 첫 실행에서 관측한 값의 2배로 고정하고, 그 값을 테스트 주석에 근거와 함께 남긴다)
  - 모든 호출의 `y` 가 `0 <= y < 30`, `x` 가 `0 <= x < 140`

---

## SC-PERF-006 — 프로젝트 스캔 선형성

### TC-PERF-013 — 프로젝트 수 2배에 스캔 작업량이 2.2배 이하다

- **US**: US-VLT07 AC1 / **Priority**: Medium / **Gap**: NEW
- **Preconditions**
  - `tmp_path/"projects"` 에 100개 / 200개 디렉터리 두 벌
  - 각 프로젝트에 `.axt-profile.json` + `.claude/skills` 심볼릭 링크 2개
  - vault 항목 20개
  - `Path.iterdir` 을 카운팅 래퍼로 감싼다
  - `decode_project_dir_name` 의 brute-force 매칭이 실제 파일시스템을 훑으므로 **`tmp_path` 밖으로 나가지 않게**
    `axt.HOME` 을 tmp 기반으로 교체한다
- **Steps**: `scan_project_usage(projects_dir, vault_dir, mode="default")` 를 두 규모에서 각각 실행
- **Expected Output**
  - `D200 <= D100 * 2.2`
  - 두 규모 모두 인덱스 항목 수 == 20
  - `mode="full"` 로도 같은 관계가 성립한다 (플러그인 설정 추가 읽기가 프로젝트당 상수여야 함)

### TC-PERF-014 — 빈 projects 디렉터리에서 0건으로 끝난다

- **US**: US-VLT07 AC4 / **Priority**: Medium / **Gap**: NEW
- **Preconditions**: 존재하지만 비어 있는 `projects_dir`, vault 항목 20개
- **Expected Output**
  - 반환 인덱스의 모든 항목의 프로젝트 목록이 빈 리스트
  - 예외 0건, `iterdir` 호출 1회 (빈 디렉터리를 반복 재순회하지 않는다)

---

## SC-PERF-007 — 업데이트 확인 TTL

### TC-PERF-015 — 신선한 캐시에서는 백그라운드 스윕을 시작하지 않는다

- **US**: US-UPD05 AC2 / **Priority**: High / **Gap**: **COVERED**
  (`tests/test_tui.py::test_kick_update_check_short_circuits_on_fresh_cache`) — 참조만 한다.

### TC-PERF-016 — `force=True` 만 TTL을 무시하고 재확인한다

- **US**: US-UPD05 AC3 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - `threading.Thread` 를 `_StubThread` 방식(생성만 기록)으로 교체
  - `load_cached_update_statuses` 가 **방금 시각**(`_iso_now()`)의 신선한 캐시를 돌려주게 한다
  - `check_all_updates` 는 카운팅 스텁 — **네트워크 금지**
  - **시계 처리**: `_update_status_fresh` 는 실제 `datetime.now()` 를 읽는다.
    `_iso_now()` 로 만든 값을 그대로 쓰므로 가짜 시계를 도입할 필요가 없다
- **Steps**
  1. `_kick_update_check(state)` → 스레드 시작 0건 확인
  2. `_kick_update_check(state, force=True)` → 스레드 시작 1건 확인
  3. 워커 본문 `_update_check_worker(state)` 를 동기 호출
- **Expected Output**
  - 1단계 시작 목록 `[]`, 2단계 `["axt-update-check"]`
  - 3단계 후 `state.update_check_loading is False`, `state.update_checked_at` 갱신
  - `check_all_updates` 총 호출 수 == 1

### TC-PERF-017 — 디스크 캐시 복원이 마커 값을 잃지 않는다

- **US**: US-UPD05 AC2 / **Priority**: Medium / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_update.py::test_update_status_cache_roundtrip` 이 저장/복원을 덮으나,
  복원된 상태가 **TUI 마커로 그려질 때** 원래 글리프를 유지하는지는 미검증.
  캐시 스키마 필드 하나가 빠지면 `↑` 가 조용히 `─` 로 바뀐다.
- **Preconditions**: `AXT_CONFIG_DIR` → `tmp_path`. 상태 3종(updatable / up-to-date / error)을 저장
- **Steps**
  1. `save_cached_update_statuses(statuses, _iso_now())`
  2. 새 `TuiState` 에 `_kick_update_check` 로 복원
  3. 각 항목의 `_upd_cell` 결과를 확인
- **Expected Output**
  - 세 항목의 글리프가 각각 `↑`, `·`, `!`
  - 저장 전후 `UpdateStatus` 필드가 모두 보존 (`tier`, `current`, `available`, `note`, `error`)

---

## SC-PERF-008 — 검색 단일 패스

### TC-PERF-018 — 2,000행 검색이 단일 패스로 111행을 남긴다

- **US**: US-TUI04 AC2 / **Priority**: High / **Gap**: NEW
- **머신 가정**: TC-PERF-010 과 동일. 벽시계 상한 1초는 관측 중앙값의 10배 이상이다.
- **Preconditions**
  - Skills 서브탭에 2,000행 (`skill-0000` ~ `skill-1999`)
  - 이름에 `"77"` 이 포함되는 행은 정확히 111개 (`0077`, `0770`~`0779`, `1770`~`1779`, `x77y` 조합을
    테스트 안에서 **세어서 기대값을 계산**한다 — 하드코딩한 111과 실제가 어긋나면 픽스처 오류)
  - `_subtab_search_haystack` 과 `_apply_sort` 를 각각 카운팅 래퍼로 감싼다
- **Input**: `state.ext_search["skills"] = "77"` → `_subtab_view(state, "skills")`
- **Expected Output**
  - `_subtab_search_haystack` 호출 수 ≤ 2,000
  - `_apply_sort` 호출 수 == 1 — 필터 후 재정렬이 없다
  - 반환 행 수 == 계산한 기대값
  - 반환 순서가 정렬 기준(기본 `name` 오름차순)을 유지한다
  - 경과 시간 < 1.0초
- **왜 필요한가**: 검색은 **키를 누를 때마다** 이 경로를 탄다.
  행당 haystack 을 두 번 만들거나 필터 후 재정렬하면 500행부터 타이핑이 눈에 띄게 끊긴다.
