# TEST_DEDUP_POLICY — axt 테스트 중복 방지 정책

이 저장소에 테스트를 추가하기 전에 반드시 읽는다. 목적은 커버리지 수치를 늘리는 것이 아니라
**프로덕션에 나갈 버그를 잡는 것**이다.

## 1. 작성 전 3문답 (통과 못 하면 작성 금지)

1. 이 테스트가 없으면 어떤 버그가 프로덕션에 나갈 수 있는가?
2. 이 검증 항목의 Layer Owner는 어디인가? (이미 다른 계층이 검증하면 작성 금지)
3. 이 테스트가 실패하면 어떤 행동을 취하는가? (행동이 불분명하면 설계가 잘못된 것)

## 2. Layer Ownership — 검증 항목당 소유 계층은 하나

| 검증 항목 | 소유 계층 | 파일 |
|---|---|---|
| 순수 함수 입출력·경계값 | unit | `tests/test_<domain>.py` |
| CLI 인자 검증·exit code·stdout 형태·`--json` 스키마 | api(cli) | `tests/test_cli.py` |
| 모듈 간 연동(파일시스템 상태 변화 포함) | integration | `tests/test_integration.py` |
| TUI 키 입력 → 상태 전이 → 렌더 결과 | e2e | `tests/test_tui.py` |
| 심볼릭 링크 탈출·명령 주입·민감정보 노출 | security | `tests/test_security.py` |
| 색맹 안전·테마 대비·CJK 폭·최소 터미널 | accessibility | `tests/test_a11y.py` |
| 대용량 입력의 시간·호출횟수 상한 | performance | `tests/test_perf.py` |
| 스레드 경합·대량 항목 | load-stress | `tests/test_load.py` |
| 설치 직후 크리티컬 경로 | smoke | `tests/test_smoke.py` |
| 결함 주입 후 복원력 | chaos | `tests/test_chaos.py` |

**금지**: 같은 항목을 두 계층에서 반복 검증. 예 — `parse_marketplace_source` 의 파싱 규칙은
unit 소유이므로 `test_cli.py` 에서 다시 검증하지 않는다. cli 계층은 "잘못된 소스 → exit 1 + stderr"
라는 **계약**만 검증한다.

## 3. 금지 패턴 (가치 없음 — 절대 작성 금지)

| 패턴 | 예 | 왜 무의미한가 |
|---|---|---|
| 상수 검증 | `assert axt.SYSTEM_PROMPT_TOKENS == 4200` | 상수는 버그를 만들지 않음. 변경 시 코드·테스트를 함께 고쳐야 해 순수 비용 |
| 존재 확인 | `assert callable(axt.list_skills)` | import 가 이미 보장 |
| 구현 복사 | 테스트 안에서 구현 로직을 재작성해 비교 | 동어반복 — 스펙이 아니라 자기 자신과 비교 |
| 자리채우기 | `assert True` | 개수만 부풀림 |
| 순수 위임 | A가 B를 호출했는지만 확인(B에 자체 테스트 있음) | 중복 + Layer Ownership 위반 |
| 정적 자료구조 | `EXTENSION_SUB_TABS` 튜플 내용 나열 | 조건 분기 없음. 변경 시 테스트도 고쳐야 함 |
| 반복 패턴 | 같은 검증 × 41개 서브커맨드 | 공통 계층 1회 + 대표 2개로 충분 |

**예외** — 다음은 상수/자료구조처럼 보이지만 **작성 가치가 있다**:
- 서로 다른 곳에 중복 선언된 값의 **동기화 검증**
  (예: 4곳의 `__version__` 일치 — 실제로 어긋나 CLI가 옛 버전을 출력한 사고 있음)
- 표가 **다른 표를 참조**하는 정합성
  (예: `_SORT_COLUMNS` 의 `marked_col` 이 실제 렌더 컬럼 키에 존재하는지)

## 4. 허위 양성(False Positive) 금지

통과하지만 아무것도 검증하지 않는 테스트는 **테스트가 없는 것보다 위험**하다. 거짓 안전감을 준다.

| 허위 양성 패턴 | 탐지 방법 |
|---|---|
| `try/except: pass` 로 실패를 삼킴 | `grep -n "except.*:\s*pass" tests/` |
| assert 없는 테스트 | 함수 본문에 `assert` 0회 |
| 항상 참인 단언 | `assert x is not None` 뒤에 실제 값 검증 없음 |
| mock 이 실제 코드를 전부 대체 | 검증 대상 함수 자체를 monkeypatch |
| 예외를 기대하지만 메시지 미검증 | `pytest.raises(Exception)` (광범위 타입) |

## 5. 안티 편향 규칙 (실패 대응)

1. 구현에 맞추려고 테스트를 고치지 않는다. 스펙과 일치하면 **구현이 틀린 것**이다.
2. 근본 원인 분석 없이 실패 테스트를 삭제하지 않는다.
3. `skip` / `xfail` 로 우회하지 않는다.
4. 단언을 약화(`== 200` → `is not None`)하지 않는다.
5. 테스트를 고쳤다면 **사유를 주석으로 남긴다** (스펙 변경 / 테스트의 잘못된 가정 / 비결정성 제거).

## 6. 결정성 규칙 (이 저장소의 실제 사고 이력 반영)

- **시계에 의존하지 않는다.** `datetime.now()` 를 읽는 코드 경로를 검증할 때는
  주입 지점(`get_days_in_billing_period(now=...)` 등)을 고정한다.
  과거에 `plan overview` 테스트가 월중 날짜에만 통과해 대부분의 날짜에서 깨진 사고가 있었다.
- **파일 mtime 과 `datetime.now()` 를 섞지 않는다.** 둘 다 실제 시계일 때만 정합하다.
- 무작위·순서 의존을 두지 않는다. `dict` 순회 순서에 기대지 않는다.
- 홈 디렉터리·cwd 를 건드리는 테스트는 반드시 `tmp_path` + `monkeypatch` 로 격리한다
  (`axt.PATHS`, `axt.AXT_CONFIG_PATH`, `monkeypatch.chdir`).

## 7. 파일 배치 규칙

- 1 도메인 = 1 파일. 도메인이 커지면 파일 내 `# ─── 섹션 ───` 으로 나눈다.
- integration 은 정의상 2개 이상 모듈에 걸치므로 `tests/test_<domain>.py` 중 어디에 둘지가
  모호하다. 전용 `tests/test_integration.py` 에 모은다 — 소재지가 결정적이고,
  단위 테스트 파일을 동시에 수정하는 작업과 충돌하지 않는다.
- 임시 검증 파일(`verify_*.py`, `tmp_test_*.py`) 금지.
- 새 도메인 파일을 만들기 전에 `grep -rn "<대상함수>" tests/ -l` 로 기존 파일을 먼저 찾는다.
