# Load / Stress 테스트 케이스

Layer Owner: `tests/test_load.py`
시나리오 출처: [load-stress-scenarios.md](../scenarios/load-stress-scenarios.md)

> **결정성**: 스레드 TC는 `Event`/`Barrier` 로 순서를 통제하고 `time.sleep` 으로 타이밍을 맞추지 않는다.
> 모든 스레드는 `join(timeout=5)` 으로 회수하며 살아남으면 실패 처리한다.
> 대량 픽스처는 전부 `tmp_path` 안이며 실제 `~/.claude` 를 읽는 TC는 0건이다.
> 시계를 가짜로 만들지 않는다 — 필요한 시각은 픽스처의 타임스탬프 문자열로 직접 지정한다.

## 요약

| 항목 | 값 |
|---|---|
| **총 TC 수** | **16** (전부 신규 작성 대상) |
| 우선순위 | Critical 4 / High 9 / Medium 3 / Low 0 |
| Gap | COVERED 0 / PARTIAL 3 / NEW 13 |
| 실행 시간 예산 | 도메인 전체 60초 이내 (10,000 엔트리 픽스처 생성이 가장 큰 비중) |

## TC 인덱스

| TC ID | 시나리오 | 제목 | US | 우선순위 | Gap |
|---|---|---|---|---|---|
| TC-LOAD-001 | SC-LOAD-001 | 10,000 엔트리의 4종 토큰 합계가 정확하다 | US-USG01 AC1 | Critical | NEW |
| TC-LOAD-002 | SC-LOAD-001 | 10,000 엔트리의 `--json` / `--csv` 출력 형태가 일관된다 | US-USG03 AC1/AC2 | High | PARTIAL |
| TC-LOAD-003 | SC-LOAD-001 | 엔트리 0건에서도 exit 0 + 0건 요약이다 | US-USG01 AC3 | High | PARTIAL |
| TC-LOAD-004 | SC-LOAD-002 | vault 500항목이 타입별로 정확히 열거된다 | US-VLT02 AC1 | High | NEW |
| TC-LOAD-005 | SC-LOAD-002 | 8개 정렬 컬럼을 순회해도 500행이 유지된다 | US-TUI03 AC8 | High | NEW |
| TC-LOAD-006 | SC-LOAD-002 | 검색 후 정렬을 바꿔도 매칭 행 수가 보존된다 | US-TUI04 AC2 | Medium | NEW |
| TC-LOAD-007 | SC-LOAD-003 | 세 데몬 스레드 종료 후 로딩 플래그가 모두 False다 | US-UPD05 AC4 | Critical | NEW |
| TC-LOAD-008 | SC-LOAD-003 | 세 워커의 결과가 서로를 덮어쓰지 않는다 | US-UPD05 AC4 | Critical | NEW |
| TC-LOAD-009 | SC-LOAD-003 | 공유 `status` 필드 경합이 상태바를 영구 오염시키지 않는다 | US-UPD05 AC4 | High | NEW |
| TC-LOAD-010 | SC-LOAD-004 | `j`/`k` 500회에도 선택 인덱스가 경계를 넘지 않는다 | US-TUI03 AC2 | High | NEW |
| TC-LOAD-011 | SC-LOAD-004 | `s` 500회 후 정렬 컬럼과 기본 방향이 정합한다 | US-TUI03 AC4 | High | PARTIAL |
| TC-LOAD-012 | SC-LOAD-004 | detail 스크롤이 내용 끝을 넘지 않는다 | US-TUI05 AC4 | Medium | NEW |
| TC-LOAD-013 | SC-LOAD-004 | 200행 전체 마크가 정렬·검색 변경 후에도 유지된다 | US-VLT08 AC3 | High | NEW |
| TC-LOAD-014 | SC-LOAD-005 | 4 writer × 30회 동시 쓰기 후 파일이 항상 유효하다 | US-SYS04 AC3 | Critical | NEW |
| TC-LOAD-015 | SC-LOAD-005 | 동시 쓰기 후 tmp 잔여물이 없고 `.bak` 도 유효하다 | US-SYS04 AC2 | High | NEW |
| TC-LOAD-016 | SC-LOAD-006 | 2,000자 필드가 두 화면 크기에서 레이아웃을 깨지 않는다 | US-TUI10 AC2 | Medium | NEW |

---

## SC-LOAD-001 — 대용량 사용량 집계

### TC-LOAD-001 — 10,000 엔트리의 4종 토큰 합계가 정확하다

- **US**: US-USG01 AC1 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `monkeypatch.setattr("axt.PATHS", …)` 로 `projects = tmp_path/"projects"`, `AXT_CONFIG_DIR` → `tmp_path`
  - 픽스처: 프로젝트 10개 × 세션 파일 20개 × 50줄 = **10,000 엔트리**
  - 값 생성 규칙(난수 금지):
    - `input_tokens = (i % 997) + 1`
    - `output_tokens = (i % 389) + 1`
    - `cache_creation_input_tokens = i % 53`
    - `cache_read_input_tokens = i % 211`
    - `model = MODELS[i % 4]` (`claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5`, `claude-fable-5`)
    - `timestamp = 기준시각 + i분` (기준시각은 고정 문자열 `"2026-01-05T00:00:00.000Z"`)
  - 기대 합계는 픽스처를 쓰는 루프에서 **동시에 누적**한다. 구현 함수를 호출해 기대값을 만들지 않는다
    (구현 복사 금지 — 정책 §3)
- **Steps**
  1. `axt.load_all_claude_usage(projects_dir)` 호출
  2. 4종 토큰을 각각 합산
  3. 모델별 합계도 산출
- **Expected Output**
  - `len(entries) == 10_000`
  - 4종 합계가 픽스처 누적값과 **정확히 일치**(부동소수 아님, 정수 비교)
  - 모델 4종 각각 2,500 엔트리
  - 세션 수 == 200 (파일 수)
- **왜 필요한가**: v2 캐시는 모델/세션을 intern 인덱스로 저장한다. 인덱스 테이블이 200개 파일에 걸쳐
  누적되면서 오프바이원이 나면 **비용이 다른 모델로 집계**된다. 소규모 테스트로는 절대 안 잡힌다.

### TC-LOAD-002 — 10,000 엔트리의 `--json` / `--csv` 출력 형태가 일관된다

- **US**: US-USG03 AC1/AC2 / **Priority**: High / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_cli.py` 가 `--json`/`--csv` 계약을 소규모로 덮는다.
  규모에서 확인할 것은 **모든 행의 열 수 일관성** — 값에 콤마·따옴표·줄바꿈이 섞였을 때만 깨진다.
- **Preconditions**
  - TC-LOAD-001 픽스처 + 프로젝트 이름 중 하나를 `proj,with"quote` 로 만든다 (CSV 이스케이프 경로 강제)
  - `capsys` 로 stdout 캡처
- **Steps**
  1. `axt.main(["usage", "month", "--json"])` → `json.loads`
  2. `axt.main(["usage", "month", "--csv"])` → `csv.reader` 로 파싱
- **Expected Output**
  - JSON 파싱 성공, 최상위가 dict 또는 list
  - CSV: 헤더 열 수 == 모든 데이터 행의 열 수 (`len(set(len(r) for r in rows)) == 1`)
  - `--json` 출력에 ANSI 색 코드(`\x1b[`)가 섞이지 않는다 (US-UPD03 AC2 와 같은 계약)

### TC-LOAD-003 — 엔트리 0건에서도 exit 0 + 0건 요약이다

- **US**: US-USG01 AC3 / **Priority**: High / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_usage_claude.py::test_load_all_claude_usage_empty_dir_no_jsonl` 이
  로더 수준을 덮는다. CLI 계약(exit code + 요약 출력)까지의 연결은 대량 케이스의 **대조군**으로 필요하다.
- **Preconditions**: 비어 있는 `projects_dir`
- **Expected Output**
  - `axt.main(["usage", "today"])` 반환값 `0`
  - stdout 에 오류 표기(`✗`)가 없고, 0건임을 알리는 텍스트가 있다
  - 예외 0건
- **허위 양성 방지**: 이 TC 없이 TC-LOAD-001 만 두면, 픽스처 생성이 실패해 0건이 되어도
  "합계 0 == 기대 0" 으로 통과할 수 있다. 두 TC가 서로의 대조군이다.

---

## SC-LOAD-002 — 대량 항목

### TC-LOAD-004 — vault 500항목이 타입별로 정확히 열거된다

- **US**: US-VLT02 AC1 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - `vault/skills` 300개(각 디렉터리 + `SKILL.md`), `vault/commands` 100개(`.md`), `vault/agents` 100개(`.md`)
  - 이름 다양성: ASCII 짧은 이름 / 80자 이름 / 한글 이름 / 공백 포함 이름 / 숫자 시작 이름을 각각 최소 5개씩
  - `axt.PATHS.vault` 를 tmp 로 교체, `monkeypatch.chdir(proj)`
- **Steps**
  1. `list_vault_items(vault)`
  2. `list_vault_items_with_project_state(vault, proj, claude_dir)` — 일부 항목만 미리 링크해 둔다
- **Expected Output**
  - 총 500건, 타입별 300/100/100
  - 미리 링크한 항목만 `is_linked` / `is_global_linked` 가 True 이고 나머지는 False
  - 이름이 파일시스템 원문 그대로 유지된다(한글 정규화·공백 트리밍이 일어나지 않는다)

### TC-LOAD-005 — 8개 정렬 컬럼을 순회해도 500행이 유지된다

- **US**: US-TUI03 AC8 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - TC-LOAD-004 픽스처를 Vault 서브탭 데이터로 사용
  - 값 결측을 의도적으로 심는다: `version=None` 30건, `description=""` 40건, `updated_at=None` 20건
- **Steps**: `ord("s")` 를 컬럼 수만큼 입력하며 매번 `_apply_sort` 결과 행 수와 예외 유무를 확인
- **Expected Output**
  - 모든 컬럼에서 행 수 == 500
  - 예외 0건
  - 한 바퀴 후 활성 컬럼이 처음 컬럼(`name`)으로 복귀
  - `version=None` 행이 `Ver` 오름차순에서 **마지막**에 온다 (US-TUI03 AC7)

### TC-LOAD-006 — 검색 후 정렬을 바꿔도 매칭 행 수가 보존된다

- **US**: US-TUI04 AC2 / **Priority**: Medium / **Gap**: NEW
- **Preconditions**: 500행 중 이름에 `"alpha"` 를 포함하는 행이 정확히 47개가 되도록 픽스처를 구성
  (기대값 47은 픽스처 루프에서 세어서 계산한다)
- **Steps**
  1. 검색어 `"alpha"` 적용 → 행 수 확인
  2. 정렬 컬럼을 3회 이동하며 매번 행 수 확인
  3. 검색 해제 → 행 수 확인
- **Expected Output**
  - 1·2 단계 모두 행 수 == 47
  - 3 단계 행 수 == 500
  - 필터는 서브탭별로 독립 유지 — 다른 서브탭의 검색어가 영향받지 않는다

---

## SC-LOAD-003 — 데몬 스레드 동시성

### TC-LOAD-007 — 세 데몬 스레드 종료 후 로딩 플래그가 모두 False다

- **US**: US-UPD05 AC4 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - **실제 `threading.Thread` 를 사용**한다(스텁 스레드로는 경합이 재현되지 않는다)
  - 세 작업 함수를 `Barrier(3)` 에서 동시에 출발하는 스텁으로 교체:
    - `axt.tui.tabs.scan_project_usage` → 고정 `UsageIndex` 반환
    - `axt.tui.tabs.load_unified_usage` → 고정 엔트리 3건 반환
    - `axt.tui.tabs.check_all_updates` → 고정 `UpdateStatus` 2건 반환
  - `analyze_context` 도 고정값 스텁으로 교체 (usage 워커가 부수적으로 호출)
  - `_save_scan_cache` / `save_cached_update_statuses` 는 `tmp_path` 로 향하게 한다
- **Steps**
  1. `_kick_vault_scan(state)` / `_kick_usage_reload(state)` / `_kick_update_check(state, force=True)` 호출
  2. `state.vault_scan_thread`, `state.usage_load_thread`, `state.update_check_thread` 를 각각 `join(timeout=5)`
  3. `is_alive()` 확인
- **Expected Output**
  - 세 스레드 모두 `is_alive() is False`
  - `state.vault_scan_loading is False`, `state.usage_loading is False`, `state.update_check_loading is False`
- **실패 시 조치**: 어느 워커의 `finally` 가 빠졌는지 확인한다.
  플래그가 True 로 남으면 `_has_background_work` 가 영원히 참이 되어 TUI가 100ms마다 재렌더하며 CPU를 태운다.

### TC-LOAD-008 — 세 워커의 결과가 서로를 덮어쓰지 않는다

- **US**: US-UPD05 AC4 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**: TC-LOAD-007 과 동일 + 각 스텁이 **서로 구별되는 마커 값**을 반환하게 한다
- **Steps**: 세 스레드 join 후 상태 필드 검사
- **Expected Output**
  - `state.vault_usage_index` 가 vault 스텁의 마커를 갖는다
  - `state.usage_entries` 가 usage 스텁의 3건 그대로
  - `state.update_statuses` 가 update 스텁의 2건 그대로
  - 세 결과가 동시에 존재한다 — 마지막 워커가 앞선 결과를 지우지 않았다
  - 이 상태로 `_render_frame` 이 예외 없이 성공하고, 세 결과가 모두 화면에 반영된다

### TC-LOAD-009 — 공유 `status` 필드 경합이 상태바를 영구 오염시키지 않는다

- **US**: US-UPD05 AC4 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - `_kick_usage_reload` 은 시작 시 `set_status(state, "Loading Claude usage…")` 를 쓰고,
    끝날 때 **그 문자열이 그대로일 때만** 지운다. 그 사이에 메인 루프가 다른 상태를 쓰면 로딩 문구가 남는다
  - `Event` 로 순서를 통제: 워커가 시작 상태를 쓴 직후 메인 스레드가 `set_status(state, "Theme: light")` 를 쓰고,
    그다음 워커를 진행시킨다
- **Steps**
  1. 워커 시작 → 시작 상태 기록 확인
  2. 메인 스레드가 다른 상태로 덮어쓴다
  3. 워커 완료 → 최종 `state.status` 확인
- **Expected Output**
  - 최종 상태가 `"Theme: light"` 로 유지된다 — 워커가 나중 상태를 지우지 않는다
  - 반대로 메인이 아무것도 쓰지 않은 경우에는 워커가 로딩 문구를 지운다
  - `state.status_set_at` 이 최종 상태와 정합한다(자동 타임아웃이 잘못된 시각을 쓰지 않는다)
- **왜 필요한가**: `state.status` 는 세 워커와 메인 루프가 **모두 쓰는 유일한 공유 필드**다.
  구현이 "내가 쓴 값일 때만 지운다"는 조건으로 이미 방어하고 있으므로, 그 조건을 잃는 리팩터를 잡는다.

---

## SC-LOAD-004 — 입력 폭주

### TC-LOAD-010 — `j`/`k` 500회에도 선택 인덱스가 경계를 넘지 않는다

- **US**: US-TUI03 AC2 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - Skills 서브탭 200행, 선택 인덱스 0, `state.focused_layer = "content"`
  - 입력은 `handle_extensions_input(state, key)` 직접 호출 — 실제 `getch` 루프와 타이밍 없음
- **Steps**: `ord("j")` 500회 → 확인 → `ord("k")` 500회 → 확인 → `PgDn` 100회 → 확인
- **Expected Output**
  - `j` 500회 후 인덱스 == 199
  - `k` 500회 후 인덱스 == 0
  - `PgDn` 100회 후 인덱스 == 199 (초과 없음)
  - 인덱스가 음수이거나 `len(rows)` 이상이 되는 순간이 한 번도 없다(매 입력마다 검사)

### TC-LOAD-011 — `s` 500회 후 정렬 컬럼과 기본 방향이 정합한다

- **US**: US-TUI03 AC4 / **Priority**: High / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_tui.py`(:8438 부근)가 `_SORT_COLUMNS` 의 `marked_col` 정합성을 덮는다.
  **연타 후 상태 정합**(방향이 기본값으로 초기화되는지)은 미검증.
- **Preconditions**: Skills 서브탭(정렬 컬럼 9개), 초기 정렬 `("name", False)`
- **Steps**
  1. `ord("S")` 로 방향을 뒤집는다
  2. `ord("s")` 500회 입력
  3. 활성 컬럼과 방향 확인
- **Expected Output**
  - 활성 컬럼 == `_SORT_COLUMNS["skills"][500 % 9][0]`
  - 방향이 그 컬럼의 **기본 방향**이다 — `S` 로 뒤집은 방향이 `s` 이동 시 초기화된다(US-TUI03 AC4)
  - 헤더의 ▲/▼ 표기가 실제 방향과 일치
  - 예외 0건, 행 수 불변

### TC-LOAD-012 — detail 스크롤이 내용 끝을 넘지 않는다

- **US**: US-TUI05 AC4 / **Priority**: Medium / **Gap**: NEW
- **Preconditions**: detail 내용 40줄, 패널 표시 가능 줄 수는 화면 크기에서 산출
- **Steps**
  1. `Tab` 으로 detail 포커스
  2. `ord("j")` 500회, `PgDn` 100회
  3. `ord("k")` 500회
  4. 선택 행을 바꾼 뒤 스크롤 오프셋 확인
- **Expected Output**
  - 최대 오프셋이 `max(0, 40 - 표시가능줄수)` 를 넘지 않는다
  - `k` 연타 후 오프셋 == 0
  - 선택이 바뀌면 오프셋이 0으로 복귀 (US-TUI05 AC3)

### TC-LOAD-013 — 200행 전체 마크가 정렬·검색 변경 후에도 유지된다

- **US**: US-VLT08 AC3 / **Priority**: High / **Gap**: NEW
- **Preconditions**: Skills 서브탭 200행. 마크는 이름 기준 집합으로 관리된다고 가정하고, 실제 저장 키를 확인한다
- **Steps**
  1. 각 행으로 이동하며 `Space` 200회 → 마크 수 확인
  2. 정렬 컬럼 3회 변경 → 마크 수 확인
  3. 검색 `"alpha"` 적용(47행 매칭) → 마크 수 확인
  4. 검색 해제 → 마크 수 확인
  5. `Esc` 1회 → 마크 해제 확인
- **Expected Output**
  - 1~4 단계 내내 마크 수 == 200 (필터로 화면에서 사라진 항목의 마크도 유지)
  - 상태바에 `marked=200` 표시
  - 5 단계에서 마크가 0이 되고 **검색은 아직 유지**된다 (US-VLT08 AC4 — Esc 순서: 마크 → 검색 → 포커스)
- **왜 필요한가**: 마크가 화면 인덱스 기반이면 정렬 한 번에 **다른 항목이 마크된 것으로 바뀐다**.
  그 상태로 `U`(일괄 unlink)를 누르면 의도하지 않은 확장이 해제된다 — 데이터 손실 사고다.

---

## SC-LOAD-005 — 동시 쓰기

### TC-LOAD-014 — 4 writer × 30회 동시 쓰기 후 파일이 항상 유효하다

- **US**: US-SYS04 AC3 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `target = tmp_path/"cache.json"`
  - writer 4개, 각각 크기가 다른 페이로드:
    `{"who": "W1", "pad": "1"*10}` / `"2"*1000` / `"3"*20000` / `"4"*100000`
  - `threading.Barrier(4)` 로 매 회 동시 출발, 30회 반복
  - 메인 스레드는 매 회 사이에 파일을 읽어 파싱을 시도한다(읽기 경합도 재현)
- **Steps**
  1. 30회 라운드 실행
  2. 매 라운드 후 `json.loads(target.read_text())`
- **Expected Output**
  - `json.JSONDecodeError` 0건 (읽기 도중 부분 쓰기가 보이지 않는다)
  - 매 회 결과가 4개 페이로드 중 **정확히 하나**와 완전 일치 — `who` 와 `len(pad)` 가 정합
    (`W1`↔10, `W2`↔1000, `W3`↔20000, `W4`↔100000)
  - 내용이 섞인 경우가 0건
- **왜 단순 위임이 아닌가**: `os.replace` 의 원자성은 OS 보장이다. 검증 대상은 axt가 replace **전에**
  하는 `mkdir` + `.bak` 복사 + tmp 생성 순서다. 이 전처리에서 경합이 나면 OS 보장이 무의미해진다.

### TC-LOAD-015 — 동시 쓰기 후 tmp 잔여물이 없고 `.bak` 도 유효하다

- **US**: US-SYS04 AC2 / **Priority**: High / **Gap**: NEW
- **Preconditions**: TC-LOAD-014 종료 시점의 디렉터리
- **Expected Output**
  - `list(tmp_path.glob(".tmp-*.json")) == []`
  - `target.with_suffix(".json.bak")` 이 존재하고 `json.loads` 로 파싱된다
  - `.bak` 내용도 4개 페이로드 중 하나와 완전 일치(반쪽 백업 금지)
- **비고**: `.bak` 복사는 `except OSError: pass` 로 best-effort 처리되므로,
  경합 상황에서 **조용히 건너뛰어졌는지**를 이 TC가 드러낸다.

---

## SC-LOAD-006 — 극단적 필드 길이

### TC-LOAD-016 — 2,000자 필드가 두 화면 크기에서 레이아웃을 깨지 않는다

- **US**: US-TUI10 AC2 / **Priority**: Medium / **Gap**: NEW
- **Preconditions**
  - Commands 서브탭 4행:
    - r1: `description` 2,000자 (`"x" * 2000`)
    - r2: `source_path` 2,000자 (깊은 중첩 경로)
    - r3: `name` 500자
    - r4: `description` 에 `"line1\nline2\tTAB\x01CTRL"` 포함
  - fake stdscr 두 개: `(rows=30, cols=140)` 과 `(rows=6, cols=31)`
- **Steps**
  1. 두 크기에서 각각 렌더
  2. detail 패널에 r1 을 표시하고 `PgDn` 20회 스크롤
  3. 검색어 `"xxxx"` 로 r1 을 매칭
- **Expected Output**
  - 예외 0건 (두 크기 모두)
  - 모든 `addnstr` 이 `x + max_w <= cols` 를 만족
  - 4행의 컬럼 x 좌표 수열이 서로 동일 (긴 값이 뒤 컬럼을 밀지 않는다)
  - r4 의 개행이 **한 행 안에서** 처리된다 — 다음 행의 y좌표에 그려지는 텍스트가 생기지 않는다
  - detail 스크롤 오프셋이 내용 줄 수를 넘지 않는다
