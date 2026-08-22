# Accessibility 테스트 케이스

Layer Owner: `tests/test_a11y.py`
시나리오 출처: [accessibility-scenarios.md](../scenarios/accessibility-scenarios.md)

> **스코프 주의**: 브라우저가 없으므로 WCAG 2.1 AA를 문자 그대로 적용하지 않는다.
> 스코프는 **터미널 접근성**으로 재정의되어 있다. 근거와 제외 항목은 시나리오 문서 상단을 참조.

## 요약

| 항목 | 값 |
|---|---|
| **총 TC 수** | **16** (그중 2건은 기존 테스트가 소유 → 신규 작성 대상 14건) |
| 우선순위 | Critical 3 / High 10 / Medium 3 / Low 0 |
| Gap | COVERED 2 / PARTIAL 5 / NEW 9 |
| 실패 예상 TC | 0 — 구현이 이미 의도를 갖고 만들어진 영역이라 회귀 방어가 주 목적이다 |

## TC 인덱스

| TC ID | 시나리오 | 제목 | US | 우선순위 | Gap |
|---|---|---|---|---|---|
| TC-A11Y-001 | SC-A11Y-001 | 활성 서브탭의 대괄호가 색 없이도 활성을 표시한다 | US-TUI01 AC3 | High | PARTIAL |
| TC-A11Y-002 | SC-A11Y-001 | 포커스 마커 `▶` 유무로 포커스 레이어를 구별한다 | US-TUI02 AC2 | High | COVERED |
| TC-A11Y-003 | SC-A11Y-001 | 메인 탭 바의 활성 탭이 속성을 지워도 텍스트로 구별된다 | US-TUI01 AC3 | High | NEW |
| TC-A11Y-004 | SC-A11Y-002 | 상태가 다른 4행이 글리프 조합만으로 서로 구별된다 | US-LNK04 AC2 | High | NEW |
| TC-A11Y-005 | SC-A11Y-002 | 상태 글리프가 문서화된 알파벳을 벗어나지 않는다 | US-UPD05 AC1 | Medium | PARTIAL |
| TC-A11Y-006 | SC-A11Y-003 | light 테마에서 3개 메인 탭이 예외 없이 렌더된다 | US-TUI09 AC1 | High | NEW |
| TC-A11Y-007 | SC-A11Y-003 | 테마를 바꿔도 화면의 셀 문자열이 동일하다 | US-TUI09 AC1 | High | NEW |
| TC-A11Y-008 | SC-A11Y-003 | 두 테마 모두 8개 color pair를 초기화한다 | US-TUI09 AC1 | Medium | PARTIAL |
| TC-A11Y-009 | SC-A11Y-004 | `color_pair` 가 실패하는 터미널에서도 프레임이 렌더된다 | US-SYS05 | Critical | NEW |
| TC-A11Y-010 | SC-A11Y-004 | 색이 없어도 선택 행이 `A_REVERSE` 로 식별된다 | US-TUI05 AC1 | High | PARTIAL |
| TC-A11Y-011 | SC-A11Y-005 | 최소 크기 미만에서 안내 문구를 낸다 | US-TUI10 AC1 | Critical | COVERED |
| TC-A11Y-012 | SC-A11Y-005 | 정확히 임계 크기에서는 정상 렌더한다 | US-TUI10 AC1 | Critical | NEW |
| TC-A11Y-013 | SC-A11Y-005 | 좁은 폭에서 `max_w <= 0` 인 그리기 호출이 없다 | US-TUI10 AC2 | High | NEW |
| TC-A11Y-014 | SC-A11Y-006 | CJK 이름 행과 ASCII 행의 다음 컬럼 x좌표가 같다 | US-TUI10 AC3 | High | NEW |
| TC-A11Y-015 | SC-A11Y-006 | 긴 CJK 이름이 배정 컬럼 폭을 넘지 않는다 | US-TUI10 AC3 | High | NEW |
| TC-A11Y-016 | SC-A11Y-006 | wide 문자가 반 칸으로 잘리지 않는다 | US-TUI10 AC3 | Medium | PARTIAL |

---

## SC-A11Y-001 — 색 없이도 활성/포커스 구별

### TC-A11Y-001 — 활성 서브탭의 대괄호가 색 없이도 활성을 표시한다

- **US**: US-TUI01 AC3 / **Priority**: High / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_tui.py::test_subtab_bar_shows_brackets_around_active`(:2000)가
  `"[ Skills ]" in flat` 를 확인한다. 그러나 **비활성 셀이 대괄호를 갖지 않는다**는 반대 방향과,
  **색 속성을 제거해도 구별이 남는다**는 색맹 안전 조건은 검증되지 않는다.
- **Preconditions**
  - fake stdscr `(rows=30, cols=140)`
  - `tui_init_colors("dark")`; 테스트 종료 시 `tui_init_colors("dark")` 로 복원
- **Input**: `_render_subtab_bar(scr, 0, 140, EXTENSION_SUB_TABS, active_key="skills", focused=True)`
- **Steps**
  1. `scr.calls` 에서 문자열 인자만 뽑아 `flat` 구성 (attr 은 의도적으로 버린다)
  2. 활성 셀 표기와 비활성 셀 표기를 각각 검사
- **Expected Output**
  - `"[ Skills ]" in flat`
  - `"[ Plugins ]" not in flat` 이고 `"  Plugins  " in flat` — 비활성 셀에는 대괄호가 없다
  - `flat` 안에서 `[` 의 등장 횟수가 정확히 1 — 활성은 언제나 유일하다
- **왜 필요한가**: 활성 표시를 대괄호 없이 색 chip 만으로 바꾸는 리팩터가 색맹 사용자에게 화면을
  판독 불가로 만든다. 이 단언이 없으면 그 변경이 조용히 통과한다.

### TC-A11Y-002 — 포커스 마커 `▶` 유무로 포커스 레이어를 구별한다

- **US**: US-TUI02 AC2 / **Priority**: High / **Gap**: **COVERED**
  (`tests/test_tui.py::test_render_subtab_bar_shows_focus_marker_only_when_focused`)
- **조치**: 재작성하지 않는다. 문서에서 참조만 한다.

### TC-A11Y-003 — 메인 탭 바의 활성 탭이 속성을 지워도 텍스트로 구별된다

- **US**: US-TUI01 AC3 / **Priority**: High / **Gap**: NEW
- **Preconditions**: fake stdscr `(rows=30, cols=160)`, `tui_init_colors("dark")`
- **Input**: `render_tab_bar(scr, 0, 0, 160, active_idx=1, focused=True)` 와 `active_idx=2` 두 번
- **Steps**
  1. 두 렌더의 `flat` 문자열을 각각 만든다
  2. 두 문자열을 비교한다
- **Expected Output**
  - 두 `flat` 이 **서로 다르다** — 활성 탭이 바뀌면 그려지는 텍스트도 바뀌어야 한다
  - 두 경우 모두 세 탭 라벨(`Extensions`/`Context`/`Usage` 또는 좁을 때 `Ext`/`Ctx`/`Use`)이 모두 등장한다
    (활성 강조가 다른 탭을 숨기지 않는다)
  - 선행 마커 `▶ ` 가 정확히 1회
- **비고**: 현재 구현은 활성 탭 구별을 **속성(chip)** 에 의존한다. 텍스트 차이가 없다면 이 TC가 실패하고,
  그때는 활성 탭 라벨에도 대괄호 같은 텍스트 신호를 넣어야 한다 —
  서브탭 바가 이미 그렇게 하고 있으므로 일관성 관점에서도 타당한 요구다.

---

## SC-A11Y-002 — 상태 글리프의 정보 보존

### TC-A11Y-004 — 상태가 다른 4행이 글리프 조합만으로 서로 구별된다

- **US**: US-LNK04 AC2 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - `monkeypatch.chdir(proj)`; `axt.PATHS` 를 tmp 기반으로 교체
  - Skills 서브탭 데이터 4행을 직접 `state.ext_cache["skills"]` 에 주입:
    - `a`: vault 소속, project 링크 O, global 링크 X, `UpdateStatus(updatable=True, tier=1)`
    - `b`: vault 아님, 링크 없음, `UpdateStatus(updatable=False, tier=1)`
    - `c`: plugin 소속 (`_update_target_for` 가 None 을 돌려주는 행)
    - `d`: `UpdateStatus(updatable=False, tier=1, error="fetch failed")`
  - `state.update_statuses` 를 **직접 주입** — 백그라운드 스레드·네트워크·시계 배제(결정성)
- **Steps**
  1. Skills 서브탭 렌더
  2. 각 행에서 `Vault`/`Proj`/`Glob`/`Upd` 4개 셀 문자를 순서대로 뽑아 튜플로 만든다
- **Expected Output**
  - 4개 튜플이 모두 서로 다르다: `len({t_a, t_b, t_c, t_d}) == 4`
  - `t_a` 의 `Upd` 는 `↑`, `t_d` 의 `Upd` 는 `!`, `t_c` 의 `Upd` 는 `─`
- **왜 단순 위임이 아닌가**: `_upd_cell` 단위 매핑은 `tests/test_tui.py`(:1004~) 가 소유한다.
  여기서 검증하는 것은 **렌더된 표 전체에서 상태 구별이 붕괴하지 않는다**는 불변식이다.
  컬럼 폭이 줄어 글리프가 잘리거나, 두 상태가 같은 글리프로 통합되면 이 단언만 깨진다.

### TC-A11Y-005 — 상태 글리프가 문서화된 알파벳을 벗어나지 않는다

- **US**: US-UPD05 AC1 / **Priority**: Medium / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `_upd_cell` 의 개별 반환값은 검증되어 있으나, **렌더 결과의 글리프 컬럼 전체**가
  허용 집합 안에 있는지는 미검증. 새 상태를 추가하면서 임의 문자를 쓰는 회귀를 막는다.
- **Preconditions**: TC-A11Y-004 와 동일 데이터
- **Expected Output**
  - `Vault` 셀 ∈ `{"✓", "─"}`
  - `Proj`/`Glob` 셀 ∈ `{"●", "○", "·", "─"}`
  - `Upd` 셀 ∈ `{"↑", "·", "!", "─", "…"}`
  - 공백만 있는 셀 0개 — 상태 미상은 `─` 로 명시되어야 하고 빈칸으로 흐려지면 안 된다

---

## SC-A11Y-003 — 테마 전환 안정성

### TC-A11Y-006 — light 테마에서 3개 메인 탭이 예외 없이 렌더된다

- **US**: US-TUI09 AC1 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - `axt.AXT_CONFIG_PATH` → `tmp_path/"config.json"` (실제 사용자 config 오염 금지)
  - `monkeypatch.chdir(tmp_path)`; `axt.PATHS` tmp 기반
  - Usage 탭은 `state.usage_report` 를 고정 문자열 리포트로 주입 — 실제 JSONL 로드·시계 배제
  - Context 탭은 `analyze_context` 를 고정 `ContextAnalysis` 반환 스텁으로 교체
  - **teardown 에서 `tui_init_colors("dark")`** — 전역 `_ACTIVE_THEME` 이 다른 테스트로 새지 않게 한다
- **Steps**
  1. `tui_init_colors("light", scr)`
  2. `tab_idx` 를 0,1,2 로 바꾸며 `_render_frame(scr, state)` 3회 호출
  3. Extensions 는 8개 서브탭을 순회하며 추가 렌더
- **Expected Output**
  - 예외 0건
  - 모든 `addnstr` 호출의 attr 인자가 `int`
  - 각 렌더가 최소 1회 이상 `addnstr` 을 호출한다(빈 화면 = 렌더 실패)

### TC-A11Y-007 — 테마를 바꿔도 화면의 셀 문자열이 동일하다

- **US**: US-TUI09 AC1 / **Priority**: High / **Gap**: NEW
- **Preconditions**: TC-A11Y-006 과 동일한 고정 데이터(두 렌더가 같은 입력을 보게 해야 한다)
- **Steps**
  1. dark 로 Extensions/Vault 렌더 → `flat_dark`
  2. light 로 동일 렌더 → `flat_light`
- **Expected Output**
  - `flat_dark == flat_light` — 테마는 **색만** 바꾸고 정보량을 바꾸지 않는다
  - 두 렌더의 attr 목록은 다르다(테마가 실제로 적용됐다는 대조군)
- **왜 필요한가**: light 테마 전용 분기(`CP_TITLE` 이 밑줄을 빼는 등)가 늘어나면서
  한쪽 테마에서만 문자열을 덧붙이는 회귀가 생길 수 있다. 그러면 한 테마 사용자만 정보를 잃는다.

### TC-A11Y-008 — 두 테마 모두 8개 color pair를 초기화한다

- **US**: US-TUI09 AC1 / **Priority**: Medium / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_tui.py::test_tui_init_colors_initializes_eight_pairs` 는 기본(dark) 만 확인한다.
  light 팔레트가 한 쌍을 빠뜨리면 그 pair를 쓰는 위젯이 **속성 없이** 그려지고 조용히 대비를 잃는다.
- **Preconditions**: `curses.init_pair` 를 스파이로 감싸 `(n, fg, bg)` 기록
- **Steps**: `tui_init_colors("light")` → 기록 확인 → `tui_init_colors("dark")` → 기록 확인
- **Expected Output**
  - 두 경우 모두 pair 번호 집합이 동일하다 — light 와 dark 가 **같은 번호 공간**을 채운다
  - 어느 번호도 두 테마 중 한쪽에서만 정의되지 않는다
  - `init_pair` 가 예외를 던져도(색 미지원) 함수는 정상 반환한다

---

## SC-A11Y-004 — 모노크롬 폴백

### TC-A11Y-009 — `color_pair` 가 실패하는 터미널에서도 프레임이 렌더된다

- **US**: US-SYS05 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `monkeypatch.setattr(curses, "color_pair", lambda n: (_ for _ in ()).throw(curses.error("no color")))`
    — `_safe_pair` 의 예외 경로를 강제
  - `curses.A_BOLD` / `A_REVERSE` / `A_DIM` 은 그대로 둔다(색과 무관한 속성)
  - Extensions/Vault 에 3행 데이터 주입, 선택 인덱스 1
- **Steps**: `_render_frame(scr, state)` 호출
- **Expected Output**
  - 예외 0건
  - 그려진 텍스트가 색 있는 렌더와 **동일** (정보 손실 없음)
  - 모든 attr 이 정수이고 음수가 아니다
- **왜 필요한가**: CI 로그·`TERM=dumb`·SSH 세션·스크립트 캡처에서 색이 없다.
  색이 없을 때 죽는 대시보드는 장애 대응 중에 정확히 못 쓰게 된다.

### TC-A11Y-010 — 색이 없어도 선택 행이 `A_REVERSE` 로 식별된다

- **US**: US-TUI05 AC1 / **Priority**: High / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_tui.py` 가 `CP_SEL()` 값(:4357)과 테이블 선택 행(:308~320)을 각각 덮지만,
  **색 실패 상태에서의 프레임 렌더**는 미검증.
- **Preconditions**: TC-A11Y-009 와 동일한 색 실패 monkeypatch
- **Steps**
  1. 3행 중 2번째를 선택 상태로 렌더
  2. 각 행을 그린 `addnstr` 호출의 attr 를 수집
- **Expected Output**
  - 선택 행의 attr 에 `curses.A_REVERSE` 비트가 있다
  - 비선택 행의 attr 에는 `A_REVERSE` 가 없다 — 반전이 전 행에 걸리면 선택 표시가 무의미해진다

---

## SC-A11Y-005 — 최소 터미널 크기

### TC-A11Y-011 — 최소 크기 미만에서 안내 문구를 낸다

- **US**: US-TUI10 AC1 / **Priority**: Critical / **Gap**: **COVERED**
  (`tests/test_tui.py::test_render_frame_too_small_shows_resize_message`, `(rows=3, cols=20)`)
- **조치**: 참조만. 아래 TC-A11Y-012 가 반대편 경계를 채운다.

### TC-A11Y-012 — 정확히 임계 크기에서는 정상 렌더한다

- **US**: US-TUI10 AC1 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `monkeypatch.chdir(tmp_path)` — cwd 라인 길이가 결과에 영향을 주지 않게 한다
  - `axt.PATHS` tmp 기반, Extensions/Vault 빈 상태
- **Input**: 다음 4개 크기로 각각 `_render_frame` 호출
  | rows | cols | 기대 |
  |---|---|---|
  | 4 | 120 | 안내 |
  | 30 | 29 | 안내 |
  | 5 | 30 | **정상 렌더** |
  | 5 | 29 | 안내 |
- **Expected Output**
  - `(5, 30)` 에서 `"Terminal too small"` 이 **나타나지 않고**, 탭 바 라벨이 최소 1개 그려진다
  - 나머지 3개에서는 안내 문구가 정확히 `"Terminal too small. Resize and try again."`
  - 안내가 뜬 경우 탭 바·테이블 그리기 호출이 없다(부분 렌더로 화면이 깨지지 않는다)
- **금지**: `assert axt.MIN_ROWS == 5` 같은 상수 검증을 하지 않는다. 경계 **동작**만 단언한다.

### TC-A11Y-013 — 좁은 폭에서 `max_w <= 0` 인 그리기 호출이 없다

- **US**: US-TUI10 AC2 / **Priority**: High / **Gap**: NEW
- **Preconditions**: `(rows=6, cols=31)` — 임계를 겨우 넘는 폭. Skills 서브탭에 3행 주입
- **Steps**: 렌더 후 모든 `addnstr` 호출의 4번째 인자(`max_w`)를 수집
- **Expected Output**
  - `max_w <= 0` 인 호출 0건
  - `x + max_w <= cols` 를 모든 호출이 만족한다 — 화면 밖으로 나가는 그리기가 없다
- **왜 필요한가**: `safe_addnstr` 이 `curses.error` 를 삼키므로 폭 계산 버그가 **조용히** 컬럼을 통째로
  사라지게 만든다. 예외가 안 나므로 기존 렌더 테스트로는 절대 안 잡힌다.

---

## SC-A11Y-006 — CJK 폭과 컬럼 정렬

### TC-A11Y-014 — CJK 이름 행과 ASCII 행의 다음 컬럼 x좌표가 같다

- **US**: US-TUI10 AC3 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - Skills 서브탭 데이터 3행, 이름만 다르게: `"ascii-skill"`, `"한글스킬"`, `"日本語スキル"`
  - 나머지 필드(source/type/path/version)는 동일하게 고정 — 이름 폭만 변수로 남긴다
  - fake stdscr `(rows=30, cols=140)`
- **Steps**
  1. 렌더
  2. 각 행의 `addnstr` 호출을 y좌표로 묶고, 이름 셀 **다음** 셀의 x 인자를 뽑는다
- **Expected Output**
  - 세 x 값이 모두 동일
  - 각 행의 셀 x 값 수열이 세 행에서 완전히 일치한다(모든 컬럼 경계가 정렬)
- **왜 필요한가**: 한글 이름이 있는 스킬 하나가 표 전체를 어긋나게 만드는 것이 이 도구의 대표적 시각 결함이다.
  `cell_width` 단위 테스트는 함수만 보증하고, 렌더러가 그것을 **실제로 쓰는지**는 보증하지 않는다.

### TC-A11Y-015 — 긴 CJK 이름이 배정 컬럼 폭을 넘지 않는다

- **US**: US-TUI10 AC3 / **Priority**: High / **Gap**: NEW
- **Preconditions**: 이름 `"한글스킬이름이아주아주깁니다"` (14자 = 28셀) — Skills `Name` 컬럼 폭보다 확실히 길게
- **Steps**: 렌더 후 해당 행의 이름 셀 텍스트를 뽑아 `cell_width` 로 측정
- **Expected Output**
  - `cell_width(name_cell) <= 배정 컬럼 폭`
  - 다음 컬럼의 x 가 ASCII 행과 동일 (넘침이 뒤 컬럼을 밀지 않았다)
  - 잘린 이름이 빈 문자열이 아니다 — 최소 몇 글자는 보여 식별 가능해야 한다

### TC-A11Y-016 — wide 문자가 반 칸으로 잘리지 않는다

- **US**: US-TUI10 AC3 / **Priority**: Medium / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_tui.py::test_fit_cells_truncates_to_avoid_split` 이 순수 함수를 덮는다.
  렌더 경로에서 그 함수를 우회해 `text[:n]` 슬라이스를 쓰는 코드가 생기면 잡히지 않는다.
- **Preconditions**: 홀수 폭 컬럼에 wide 문자만으로 된 이름(`"한글한글한글"`)이 오도록 `cols` 를 조정
- **Steps**: 렌더 후 이름 셀 텍스트의 각 문자에 대해 `east_asian_width` 를 확인
- **Expected Output**
  - 셀 텍스트에 포함된 wide 문자 수 × 2 + narrow 문자 수 == `cell_width(cell)` (반 칸 잔여 없음)
  - 폭이 남으면 공백으로 패딩되어 있고, wide 문자가 부분적으로 포함되지 않는다
