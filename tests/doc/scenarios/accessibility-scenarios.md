# Accessibility 테스트 시나리오

## 스코프 재정의 — 이 문서를 읽기 전에 반드시 확인

axt는 **브라우저가 없는 curses TUI**다. DOM도 ARIA도 포커스 링도 이미지 alt도 존재하지 않는다.
따라서 **WCAG 2.1 AA를 문자 그대로 적용할 수 없다.** axe-core·pa11y·Lighthouse 도 사용 불가다.

사용자 승인 아래 스코프를 **터미널 접근성(terminal accessibility)** 으로 재정의한다. 검증 대상은 다음 6가지다.

| # | 터미널 접근성 항목 | 대응하는 WCAG 원칙(정신적 대응이며 준수 주장 아님) |
|---|---|---|
| 1 | 의미를 색이 단독으로 전달하지 않는다 — 괄호·마커·글리프가 병행 | 1.4.1 Use of Color |
| 2 | light/dark 두 테마 모두 깨지지 않고 렌더된다 | 1.4.3 Contrast (직접 측정은 불가) |
| 3 | 색 미지원 터미널에서도 렌더와 의미가 살아남는다 | 1.4.1 |
| 4 | 최소 터미널 크기 미만에서 명확한 안내를 낸다 | 1.4.10 Reflow |
| 5 | CJK 문자 폭 계산으로 컬럼 정렬이 깨지지 않는다 | 1.4.12 Text Spacing |
| 6 | 오류·경고가 색이 아닌 텍스트 마커로도 식별된다 | 1.4.1 / 3.3.1 |

**측정하지 않는 것**: 명암비 수치(터미널 팔레트는 사용자 소유라 axt가 결정할 수 없다),
스크린리더 발화 순서(curses 셀 버퍼는 스크린리더 대상이 아니다), 터치 타깃 크기.
키보드 접근성은 **모든 조작이 키보드 전용**이라 자명하며, 키맵 자체는 e2e(`tests/test_tui.py`) 소유다.

- 스펙 출처: `US-TUI09`(테마), `US-TUI10`(좁은 터미널·CJK), `US-TUI01`~`US-TUI02`(활성 탭·포커스 식별),
  `US-VLT01`(broken 경고), `FEATURES.md` §2.4 / §2.10 / §2.11 / §7.7
- Layer Owner: `tests/test_a11y.py` (`TEST_DEDUP_POLICY.md` §2 — 색맹 안전·테마 대비·CJK 폭·최소 터미널)
- 렌더 검증 방식: `tests/test_tui.py::_make_stdscr` 과 동일한 fake stdscr 로 `addnstr(y, x, text, max_w, attr)`
  호출을 캡처해 **그려진 텍스트와 속성**을 직접 검사한다

---

## SC-A11Y-001 — 활성 상태를 색 없이도 구분할 수 있다

- **Objective**: `US-TUI01` AC3 + `US-TUI02` AC2 — 활성 메인탭/서브탭과 포커스된 레이어가
  **색상 속성을 제거해도** 텍스트만으로 구별된다. 구현 주석도 "brackets retained for color-blind safety"라고
  명시하므로 이는 우연이 아니라 계약이다.
- **Preconditions**
  - fake stdscr `(rows=30, cols=140)`
  - `tui_init_colors("dark")` 로 팔레트 초기화(전역 `_ACTIVE_THEME` 을 테스트 끝에 dark로 되돌린다)
- **Steps**
  1. `_render_subtab_bar(scr, 0, 140, EXTENSION_SUB_TABS, active_key="skills", focused=True)` 렌더
  2. 그려진 셀 문자열만 이어붙이고 속성 정보는 버린다
  3. 활성/비활성 셀 표기를 비교
  4. 포커스 유/무로 두 번 렌더해 마커 차이를 비교
- **Expected Result**
  - 활성 서브탭은 `[ Skills ]`, 비활성은 `  Plugins  ` — 대괄호 유무로 구별된다
  - 포커스된 바는 선행 `▶ `, 비포커스는 공백 2칸 — 마커 유무로 구별된다
  - 색 속성을 모두 0으로 만들어도 위 두 구별이 유지된다
- **Priority**: High

---

## SC-A11Y-002 — 상태 글리프가 색이 아니라 문자로 의미를 전달한다

- **Objective**: `FEATURES.md` §2.4 — `Vault`/`Proj`/`Glob`/`Upd`/`On` 컬럼은 서로 다른 **문자**를 쓴다
  (`✓ ● ○ · ─ ↑ ! …`). 색맹 사용자·모노크롬 터미널·로그 캡처 어디서도 상태가 보존되어야 한다.
- **Preconditions**
  - Skills 서브탭에 상태가 서로 다른 4행을 구성:
    (a) vault 소속 + project 링크됨 + 업데이트 가능,
    (b) vault 아님 + 링크 없음 + 최신,
    (c) plugin 소속(업데이트 대상 아님),
    (d) 확인 실패(`UpdateStatus.error` 설정)
  - `state.update_statuses` 를 직접 주입해 백그라운드 스레드·네트워크를 배제(결정성)
- **Steps**
  1. Skills 서브탭 렌더
  2. 각 행의 `Vault`/`Proj`/`Glob`/`Upd` 셀 문자를 추출
- **Expected Result**
  - 4행이 서로 **다른 글리프 조합**을 갖는다 — 어떤 두 행도 글리프만으로 동일해지지 않는다
  - 사용 글리프가 `FEATURES.md` §2.4 가 정의한 집합 안에 있다
  - 같은 의미에 두 글리프가 섞이지 않는다(예: 링크됨을 어떤 행은 `●`, 다른 행은 `✓` 로 그리지 않는다)
- **Priority**: High

---

## SC-A11Y-003 — light ↔ dark 전환이 크래시 없이 전 화면을 다시 그린다

- **Objective**: `US-TUI09` AC1 — `t` 는 팔레트를 즉시 재초기화하고 config에 저장한다.
  두 테마 모두에서 **모든 렌더 경로가 유효한 속성을 해석**해야 한다(미초기화 pair로 인한 `curses.error` 금지).
- **Preconditions**
  - `axt.AXT_CONFIG_PATH` 를 `tmp_path` 로 교체 — 사용자 실제 config 오염 금지
  - `curses.init_pair` 를 스파이로 감싸 호출 인자를 기록
  - 테스트 종료 시 `tui_init_colors("dark")` 로 전역 테마 복원(다른 테스트에 전이 금지)
- **Steps**
  1. `tui_init_colors("light", stdscr)` → 3개 메인 탭 × 대표 서브탭을 순회 렌더
  2. `tui_init_colors("dark", stdscr)` → 동일 순회
  3. 각 렌더에서 `addnstr` 에 넘어간 attr 값이 정수이고 예외가 없었는지 확인
- **Expected Result**
  - 두 테마 모두 예외 0건
  - 각 테마에서 `init_pair` 가 8쌍을 모두 채운다 — 어떤 렌더도 미정의 pair를 참조하지 않는다
  - 같은 화면의 셀 문자열이 테마와 무관하게 동일하다(테마는 **색만** 바꾼다 — 정보량이 달라지면 안 된다)
- **Priority**: High

---

## SC-A11Y-004 — 색을 지원하지 않는 터미널에서도 렌더와 의미가 살아남는다

- **Objective**: `US-SYS05` 정신 + `FEATURES.md` §2.10 — `TERM=dumb`, `curses.start_color()` 미호출,
  `COLOR_PAIRS == -1` 같은 환경에서 `_safe_pair` 가 예외를 삼키고 **속성 없이** 그린다.
  이때도 선택 행·오류 줄이 식별 가능해야 한다.
- **Preconditions**
  - `curses.color_pair` 를 `curses.error` 를 던지도록 monkeypatch
  - `curses.A_REVERSE`/`A_BOLD` 는 색과 무관한 속성이라 그대로 유효
- **Steps**
  1. Vault 서브탭을 3행으로 렌더하고 2번째 행을 선택 상태로 둔다
  2. 오류 상태 메시지(`set_status(state, "…", kind="error")`)를 띄운 상태로 프레임 렌더
- **Expected Result**
  - 예외 0건
  - 선택 행의 attr 에 `curses.A_REVERSE` 비트가 남아 있다 — 색이 없어도 선택이 보인다
  - 오류 줄에 `✗` 또는 `Warning:` 같은 **텍스트 마커**가 포함된다
- **Priority**: High

---

## SC-A11Y-005 — 최소 터미널 크기 경계가 정확하고 안내가 명확하다

- **Objective**: `US-TUI10` AC1/AC2 — 최소 크기 미만이면
  `Terminal too small. Resize and try again.` 을 표시하고, 임계값에서는 정상 렌더한다.
  임계값은 구현상 `h < 5 or w < 30` 이다.
- **Preconditions**
  - fake stdscr 의 `getmaxyx()` 를 크기별로 바꿔 가며 `_render_frame` 호출
  - `monkeypatch.chdir(tmp_path)` — cwd 라인이 실제 경로 길이에 좌우되지 않게 한다
- **Steps**
  1. `(4, 120)`, `(30, 29)`, `(4, 29)` → 안내 표시 확인
  2. `(5, 30)` (정확히 임계값) → 정상 렌더 확인
  3. `(5, 30)` 에서 어떤 `addnstr` 도 `max_w <= 0` 으로 호출되지 않는지 확인
- **Expected Result**
  - 1: 세 경우 모두 안내 문구가 정확히 등장하고, 탭 바·테이블은 그려지지 않는다
  - 2: 안내 문구가 **없고** 탭 바가 그려진다
  - 3: 음수/0 폭 호출 0건 (`safe_addnstr` 이 삼키더라도 호출 자체가 나오면 레이아웃 계산이 틀린 것)
- **Priority**: High

---

## SC-A11Y-006 — CJK 이름이 있어도 테이블 컬럼 정렬이 유지된다

- **Objective**: `US-TUI10` AC3 + `FEATURES.md` §7.7 — `east_asian_width` 기반 셀 계산으로
  한글·일본어 이름이 자기 컬럼을 넘지 않고, 뒤 컬럼의 시작 x좌표가 밀리지 않는다.
- **Preconditions**
  - Skills 서브탭에 이름이 다른 3행: `"ascii-skill"`, `"한글스킬이름입니다"`, `"日本語スキル"`
  - 한글 이름은 **컬럼 폭보다 길게** 만들어 잘림 경로를 태운다
  - fake stdscr `(rows=30, cols=140)`
- **Steps**
  1. 렌더 후 각 행에서 이름 다음 컬럼(`Ver`)의 `addnstr` x 인자를 수집
  2. 각 이름 셀의 `cell_width(text)` 를 컬럼 폭과 비교
- **Expected Result**
  - 세 행의 `Ver` 컬럼 x 좌표가 **모두 동일**하다
  - 각 이름 셀의 `cell_width` 가 배정된 컬럼 폭을 넘지 않는다
  - 잘린 wide 문자가 반 칸으로 남지 않는다 — `fit_cells` 가 wide 문자를 쪼개는 대신 공백으로 패딩한다
- **Priority**: High
- **비고**: 순수 함수 `cell_width` / `fit_cells` 의 입출력은 `tests/test_tui.py` 가 이미 소유한다.
  이 시나리오는 **렌더된 표의 정렬 불변식**을 검증하므로 계층이 다르다(중복 아님).

---

## 스펙 갭

| # | 관측 | 관련 US | 판단 |
|---|---|---|---|
| G-A11Y-1 | 최소 터미널 임계값(`h<5 or w<30`)이 `FEATURES.md`·유저스토리 어디에도 수치로 적혀 있지 않다 | US-TUI10 AC1 | **문서 갭**. TC는 구현 임계값을 경계로 삼되, 값 자체를 단언하지 않고 "임계 미만 → 안내 / 임계 → 렌더" 라는 **동작**을 단언한다(상수 검증 금지 정책 준수) |
| G-A11Y-2 | 색 미지원 터미널에서의 동작이 스토리에 없다 | — | **스펙 갭**. `_safe_pair` 의 예외 삼킴은 구현 의도가 명확하므로 요구사항으로 승격해 TC를 작성. 실패 시 스토리에 AC 추가 필요 |
| G-A11Y-3 | 오류 상태의 "텍스트 마커 병행" 규칙이 명문화되어 있지 않다(구현은 `✗` / `Warning:` 을 쓴다) | US-VLT01 AC2 | **문서 갭**. 브로큰 심링크 경고에는 `Warning:` 이 명시돼 있으나 일반 오류에는 규칙이 없다 |
| G-A11Y-4 | WCAG 명암비 4.5:1 은 검증 불가 — 팔레트는 curses 색 번호이고 실제 RGB는 사용자 터미널이 정한다 | — | **적용 불가**. 이 도메인에서 명암비 수치 TC를 작성하지 않는다. 대신 "테마별로 배경 pair를 고정한다"(구현이 이미 하는 것)를 SC-A11Y-003 이 간접 검증 |
