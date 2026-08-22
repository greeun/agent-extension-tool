# Load / Stress 테스트 시나리오

## 이 도메인의 "부하"란 무엇인가

axt에는 서버도 동시 접속자도 TPS도 없다. k6·JMeter·Locust 는 적용 대상이 아니다.
이 도구가 실제로 겪는 부하는 다음 네 가지다.

| 부하 축 | 현실의 형태 |
|---|---|
| **데이터 규모** | 1년 쓴 계정의 `~/.claude/projects/**/*.jsonl` — 수만 엔트리 |
| **항목 규모** | 큐레이터의 vault — 수백 개 skill/command/agent |
| **동시성** | TUI가 띄우는 데몬 스레드 3개(vault scan · usage load · update check)가 같은 `TuiState` 를 만진다 |
| **입력 폭주** | 키 리피트로 눌린 `j` 500회, 정렬 `s` 연타 |

성공 기준은 처리량이 아니라 **정확성과 불변식 유지**다. 느려지는 것은 허용하되,
합계가 틀리거나 선택 인덱스가 어긋나거나 파일이 깨지는 것은 허용하지 않는다.

- 스펙 출처: `US-USG01`~`US-USG03`(집계 정확성), `US-VLT02`/`US-VLT08`(대량 항목·마크),
  `US-UPD05` AC4(스레드 실패 내성), `US-TUI03` AC8(행 수 보존), `US-TUI05`(스크롤 경계),
  `US-SYS04`(원자적 쓰기), `FEATURES.md` §2.4 / §2.5 / §3.13
- Layer Owner: `tests/test_load.py` (`TEST_DEDUP_POLICY.md` §2 — 스레드 경합·대량 항목)

## 결정성 규칙

- 스레드 TC는 반드시 `threading.Event` / `Barrier` 로 순서를 통제한다. `time.sleep` 으로 타이밍을 맞추지 않는다
  (느린 CI 에서 무작위로 깨진다)
- 데몬 스레드는 테스트 종료 전에 `join(timeout=…)` 으로 회수하고, 살아남은 스레드가 있으면 실패로 처리한다
- 대량 픽스처는 전부 `tmp_path` 안에서 만든다. 실제 `~/.claude` 를 읽는 TC는 0건이어야 한다
- 시계를 가짜로 만들지 않는다. 필요한 시각은 픽스처의 타임스탬프 문자열로 직접 지정한다

---

## SC-LOAD-001 — 10,000 엔트리 사용량 집계가 정확하다

- **Objective**: `US-USG01` AC1/AC3 + `US-USG03` AC1/AC2 — 세션 파일이 많고 엔트리가 만 단위여도
  요약이 끝나고 **합계가 정확**하다. 부동소수 누적 오차나 캐시 인덱스 오프바이원이 여기서 드러난다.
- **Preconditions**
  - `tmp_path/"projects"` 에 프로젝트 10개 × 세션 파일 20개 = 200파일, 파일당 50줄 = **10,000 엔트리**
  - 토큰 값은 결정적으로 생성한다 (`input = i % 997 + 1` 처럼 난수 금지)
  - 모델 4종을 순환 배정, 타임스탬프는 고정 기준 시각에서 분 단위로 증가
  - 기대 합계는 픽스처를 만들면서 **파이썬에서 함께 누적**해 둔다 (구현 로직 복사 금지 — 단순 합산만)
  - `AXT_CONFIG_DIR` → `tmp_path`
- **Steps**
  1. `load_all_claude_usage(projects_dir)` 로 전체 로드
  2. 모델별·세션별로 집계
  3. `--json` / `--csv` 출력 경로도 한 번씩 태운다
- **Expected Result**
  - 엔트리 수 == 10,000
  - input/output/cacheWrite/cacheRead 4종 합계가 픽스처 누적값과 **정확히 일치**
  - JSON 출력이 `json.loads` 로 파싱되고, CSV 헤더 열 수 == 모든 데이터 행의 열 수
  - 데이터가 0건인 경우도 exit 0 + 0건 요약 (경계 대조)
- **Priority**: Critical

---

## SC-LOAD-002 — 500개 vault 항목 / 500개 스킬에서 목록·렌더·정렬이 무너지지 않는다

- **Objective**: `US-VLT02` AC1 + `US-TUI03` AC8 — 항목이 수백 개여도 목록·렌더·정렬이
  **행 수 불변식**을 유지하고 예외를 내지 않는다.
- **Preconditions**
  - vault 에 skill 300 / command 100 / agent 100 = 500 항목을 실제 파일로 생성
  - 이름은 길이·문자셋을 섞는다: ASCII 짧은 이름, 80자 긴 이름, 한글 이름, 공백 포함 이름
  - fake stdscr `(rows=30, cols=140)`
- **Steps**
  1. `list_vault_items(vault)` → 500건 확인
  2. `list_vault_items_with_project_state(...)` → project/global 상태가 항목별로 채워졌는지 확인
  3. Vault 서브탭 렌더
  4. 8개 정렬 컬럼을 `s` 로 한 바퀴 순회
  5. 검색 `/` 로 필터링 후 다시 정렬
- **Expected Result**
  - 매 단계 행 수가 500 (검색 단계는 매칭 수)로 일관
  - 예외 0건, 렌더 호출이 화면 크기에 비례해 유지 (SC-PERF-005 와 다른 축: 여기서는 **정확성**)
  - 정렬 순환이 한 바퀴 돌아 처음 컬럼으로 복귀한다
- **Priority**: High

---

## SC-LOAD-003 — 데몬 스레드 3개가 동시에 돌아도 `TuiState` 가 깨지지 않는다

- **Objective**: `US-UPD05` AC4 — 스레드 실패가 TUI를 죽이지 않는다. 나아가 **정상 동작 시에도**
  세 워커가 같은 `TuiState` 필드를 동시에 리바인딩하며 서로의 결과를 지우거나 로딩 플래그를 영구 True 로
  남기지 않아야 한다.
- **Preconditions**
  - 세 워커의 실제 작업 함수(`scan_project_usage`, 사용량 로더, `check_all_updates`)를
    `Barrier(3)` 에서 동시에 출발하는 스텁으로 교체 — 실제 파일 I/O·네트워크 없음
  - 각 스텁은 고정된 결과를 돌려주고 반환 전에 짧게 양보(`threading.Event.wait(0)`)해 인터리빙을 유도
  - 실제 `threading.Thread` 를 쓴다(스텁 스레드로는 경합을 재현할 수 없다).
    단 모든 스레드는 `join(timeout=5)` 으로 회수하고, 살아 있으면 실패
- **Steps**
  1. `_kick_vault_scan(state)`, `_kick_usage_reload(state)`, `_kick_update_check(state, force=True)` 를 연달아 호출
  2. 세 스레드 join
  3. 상태 필드를 검사
- **Expected Result**
  - `vault_scan_loading` / `usage_loading` / `update_check_loading` 이 **모두 False**
    (하나라도 True 로 남으면 TUI가 영원히 폴링하며 CPU를 먹는다)
  - 세 결과 필드가 모두 각자의 스텁 결과로 채워져 있다 — 서로를 덮어쓰지 않았다
  - 렌더가 예외 없이 성공하고, 세 결과가 모두 화면에 반영된다
- **Priority**: Critical

---

## SC-LOAD-004 — 키 입력 폭주에도 선택 인덱스와 스크롤이 경계를 벗어나지 않는다

- **Objective**: `US-TUI03` AC2 + `US-TUI05` AC4 — 키 리피트로 같은 키가 수백 번 들어와도
  선택 인덱스가 목록 범위를 벗어나지 않고, detail 스크롤이 내용 끝을 넘지 않으며,
  정렬 순환이 상태를 잃지 않는다.
- **Preconditions**
  - Skills 서브탭 200행, detail 패널 내용 40줄
  - 입력은 핸들러 직접 호출로 재현한다(실제 `getch` 루프·타이밍 없음 → 완전 결정적)
- **Steps**
  1. `ord("j")` 500회 → 인덱스 확인
  2. `ord("k")` 500회 → 인덱스 확인
  3. `ord("s")` 500회 → 활성 정렬 컬럼 확인
  4. `Tab` 으로 detail 포커스 후 `ord("j")` 500회 → 스크롤 오프셋 확인
  5. `ord("Space")` 로 200행 전부 마크 후 검색·정렬 변경 → 마크 수 확인
- **Expected Result**
  - 1: 인덱스 == 199 (마지막 행에서 멈춤, 음수/초과 없음)
  - 2: 인덱스 == 0
  - 3: 500 % (컬럼 수) 위치의 컬럼이 활성이고, 각 컬럼은 자기 **기본 방향**으로 진입해 있다 (US-TUI03 AC4)
  - 4: 스크롤 오프셋이 `max(0, 40 - 표시가능줄수)` 를 넘지 않는다
  - 5: 마크 수가 200으로 유지 (US-VLT08 AC3 — 정렬·검색이 바뀌어도 마크 유지)
- **Priority**: High

---

## SC-LOAD-005 — 같은 JSON 파일에 동시 쓰기가 몰려도 파일이 유효하다

- **Objective**: `US-SYS04` AC1/AC3 — TUI는 백그라운드에서 vault scan 캐시, usage 캐시,
  update-status 캐시를 각각 `write_json_atomic` 으로 쓴다. 같은 경로에 두 writer 가 몰릴 수 있는 구조다.
- **Preconditions**
  - 4개 writer 스레드, `Barrier(4)`, 각 30회 반복 = 120회 쓰기
  - 페이로드 크기를 크게 다르게 해서 부분 쓰기가 있으면 파싱이 깨지도록 만든다
  - 전부 `tmp_path`. 실제 캐시 경로 금지
- **Steps**
  1. 4개 스레드가 동시에 같은 경로에 쓴다
  2. 매 회 메인 스레드가 파일을 읽어 파싱을 시도한다(읽기 경합도 함께 재현)
  3. 종료 후 잔여물 확인
- **Expected Result**
  - 파싱 실패 0건
  - 매 회 내용이 4개 writer 중 **정확히 하나의 완전한** 페이로드
  - `.tmp-*.json` 잔여물 0개
  - `.bak` 파일이 존재하고 그 자체도 유효한 JSON
- **Priority**: High

---

## SC-LOAD-006 — 극단적으로 긴 필드 값이 레이아웃을 깨뜨리지 않는다

- **Objective**: `US-TUI10` AC2 — 컬럼이 잘려도 크래시하지 않는다.
  description·path 는 사용자가 만든 파일에서 오므로 길이 상한이 없다.
- **Preconditions**
  - Commands 서브탭에 3행: description 2,000자, path 2,000자, 이름 500자
  - 개행·탭·널이 아닌 제어문자(`\x01`)를 포함한 값도 1행 추가
  - fake stdscr `(rows=30, cols=140)` 과 `(rows=6, cols=31)` 두 크기에서 각각 렌더
- **Steps**
  1. 두 크기에서 렌더
  2. detail 패널에 긴 값을 표시하고 스크롤
  3. 검색으로 긴 값을 매칭
- **Expected Result**
  - 예외 0건, 두 크기 모두에서 컬럼 x 좌표가 다른 행과 정렬된다
  - 어떤 `addnstr` 도 `x + max_w > cols` 가 아니다
  - 개행이 포함된 값이 **한 행 안에서** 처리된다(다음 행을 침범하지 않는다)
  - detail 스크롤이 내용 끝을 넘지 않는다
- **Priority**: Medium

---

## 스펙 갭

| # | 관측 | 관련 US | 판단 |
|---|---|---|---|
| G-LOAD-1 | `TuiState` 필드에 락이 없다. 세 워커가 서로 다른 필드를 쓰므로 현재는 충돌하지 않지만, 이는 **우연이 아니라 암묵적 규약**이다 | US-UPD05 AC4 | **문서 갭**. "각 워커는 자기 필드만 리바인딩한다"는 규약을 코드 주석 이상으로 남길 필요가 있다. SC-LOAD-003 이 회귀 방어를 맡는다 |
| G-LOAD-2 | 목록 크기 상한이 스펙에 없다 | US-VLT02 | **문서 갭**. 상한이 없다면 "임의 크기에서 불변식 유지"가 계약이다. 시나리오는 그렇게 해석했다 |
| G-LOAD-3 | 필드 값 길이 상한이 없다(description/path) | US-TUI10 AC2 | **문서 갭**. 잘림은 명시돼 있으나 어디서 자르는지·말줄임 표기 여부가 스토리에 없다. TC 는 "크래시 없음 + 정렬 유지"만 단언한다 |
| G-LOAD-4 | `_kick_usage_reload` / `_kick_vault_scan` 워커의 예외 처리 수준이 워커마다 다르다(`_update_check_worker` 만 `except Exception` 을 갖는다) | US-UPD05 AC4 | **구현 갭**. chaos 도메인 SC-CHAOS-009 에서 별도로 다룬다 |
