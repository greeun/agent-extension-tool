# E2E Test Cases

> Target: axt — 사용자 여정(TUI 실제 키 시퀀스 / 다단계 워크플로)
> Date: 2026-08-22
> Author: full-test-orchestrator (Phase B, Agent 2)
> Scenarios: [e2e-scenarios.md](../scenarios/e2e-scenarios.md)

## 요약

| 항목 | 값 |
|---|---|
| **총 TC 수** | 44 |
| **시나리오 수** | 15 (SC-E2E-001 ~ SC-E2E-015) |
| **Extensions 서브탭 커버리지** | vault / skills / commands / agents / mcp / hooks / plugins / market — 8/8 |
| **Context 서브탭 커버리지** | project / sources — 2/2 |

### 우선순위 분포

| Priority | 수 |
|---|---|
| Critical | 9 |
| High | 26 |
| Medium | 8 |
| Low | 1 |

### Gap 분포

| Gap | 수 | 의미 |
|---|---|---|
| COVERED | 15 | 기존 `tests/test_tui.py` 가 같은 단언을 이미 수행 |
| PARTIAL | 23 | 개별 키 동작은 검증돼 있으나 **여정 연쇄** 또는 **최종 디스크/화면 동시 단언**이 빠짐 |
| NEW | 6 | 해당 여정을 태우는 테스트가 없음 |

### 공통 하네스 (모든 TC 전제)

- `_setup_isolated_paths(tmp_path, monkeypatch)` — `axt.HOME` · `axt.PATHS` ·
  `axt.AXT_CONFIG_PATH` 고정 + `chdir`
- `_quiet_curses(monkeypatch)` — 색 초기화 · `_prime_vault_scan` · `is_first_run` 무력화
- conftest `_no_async_update_sweep` — `_kick_update_check` 및 update 캐시 I/O 차단
- 루프 구동은 `_loop_stdscr([...keys..., ord("q")])` + `axt._tui_loop(scr)`,
  최종 상태는 `axt.tui.loop._render_frame` spy로 캡처
- 화면 문자열 = `"".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))`

---

## SC-E2E-001 — 신규 사용자 첫 실행

### TC-E2E-001: 최초 실행에만 환영 안내가 뜨고 마커가 남는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-001 |
| **US** | US-SYS02 AC1·AC2·AC3 |
| **Priority** | Critical |
| **Preconditions** | `monkeypatch.setattr("axt.core.AXT_CONFIG_DIR", tmp_path/"config")`, `onboarded` 마커 없음. `is_first_run` 은 **stub하지 않는다**(실제 배선 검증) |
| **Input** | `_loop_stdscr([ord("q")])` 로 두 번 연속 기동 |
| **Gap** | COVERED — `tests/test_tui.py::test_tui_loop_shows_welcome_toast_on_first_run`, `::test_tui_loop_skips_welcome_toast_when_already_onboarded` |

**Steps**:
1. 마커 없는 상태로 기동해 첫 상태 메시지를 캡처한다
2. `tmp_path/config/onboarded` 존재를 확인한다
3. 같은 설정으로 다시 기동한다

**Expected Output**: 1회차 메시지에 `"Welcome to axt"` 가 있고 마커가 생기며, 2회차에는 상태 메시지가 뜨지 않는다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-002: `2` → `3` → `1` 로 세 메인 탭을 오간 뒤 종료한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-001 |
| **US** | US-TUI01 AC1·AC3 |
| **Priority** | High |
| **Preconditions** | 빈 `~/.claude`. `get_claude_version` / `get_git_status` 고정값 monkeypatch(외부 명령 비의존) |
| **Input** | `_loop_stdscr([ord("2"), ord("3"), ord("1"), ord("q")])` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_tui_loop_number_key_switches_tab_then_quit` 은 `2` 한 번만 태운다. 3탭 순회와 프레임별 tab_idx 기록이 없다 |

**Steps**:
1. `_render_frame` spy로 프레임마다 `state.tab_idx` 를 리스트에 기록한다
2. 키 시퀀스를 흘려 넣는다
3. 기록된 인덱스 시퀀스를 확인한다

**Expected Output**: 기록이 `[0, 1, 2, 0]` 로 끝나고(초기 프레임 포함), 숫자키 이후 `state.focused_layer == "mainTab"` 이며 예외 없이 종료한다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-003: 빈 Market 서브탭이 실재하는 키바인딩을 가리키는 힌트를 보여준다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-001 |
| **US** | US-TUI06 AC1·AC2 |
| **Priority** | High |
| **Preconditions** | `known_marketplaces.json` 없음. `_loop_stdscr(rows=30, cols=120)` |
| **Input** | `[ord("]")]*7 + [ord("q")]` — Vault에서 Market까지 이동 |
| **Gap** | PARTIAL — `tests/test_tui.py::test_empty_state_hint_known_keys` 는 헬퍼 반환값만, `::test_render_extensions_skills_subtab_empty` 는 한 서브탭 렌더만 본다. 여정으로 7개 서브탭을 지나며 힌트를 확인하지 않는다 |

**Steps**:
1. `]` 를 7번 눌러 Vault → Market까지 순회한다
2. 각 서브탭 프레임의 화면 문자열을 캡처한다
3. Market 프레임에서 제목과 힌트를 확인한다

**Expected Output**: 화면에 `"No marketplaces added yet."` 과 ``"Press `a` to add one (github:user/repo, git:url, dir:/path)."`` 가 함께 있고, 힌트가 가리키는 `a` 가 Market 서브탭의 실제 바인딩이다. Vault를 제외한 7개 서브탭 모두 제목+힌트 2줄을 갖는다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-002 — 큐레이터 여정

### TC-E2E-004: `m` 한 번으로 전역 확장이 vault로 모이고 화면이 갱신된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-002 |
| **US** | US-VLT01 AC1·AC3, US-VLT02 AC1 |
| **Priority** | Critical |
| **Preconditions** | `PATHS.claude_dir/skills/alpha/SKILL.md`, `/commands/c1.md`, `/agents/a1.md` 실체. vault 비어 있음 |
| **Input** | `_loop_stdscr([ord("m"), ord("q")])` |
| **Gap** | PARTIAL — `tests/test_tui.py` 가 `handle_vault_input(state, ord("m"))` 의 반환 메시지를 보지만, 루프를 통과한 뒤 **다음 프레임에 vault 행이 그려지는지**는 확인하지 않는다 |

**Steps**:
1. 세 실체를 배치하고 루프를 기동한다
2. `m` 이후 프레임의 화면 문자열을 캡처한다
3. vault 디렉터리와 원위치 링크를 확인한다

**Expected Output**: 상태 메시지가 `"Migrated: +3 skipped 0 broken 0 err 0"` 이고, 마지막 프레임 화면에 `alpha` · `c1` · `a1` 세 행이 있으며, 원위치 세 경로가 모두 심볼릭 링크다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-005: Agents 서브탭 `i` import 결과가 Vault 서브탭에 나타난다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-002 |
| **US** | US-LNK05 AC3, US-VLT02 AC1 |
| **Priority** | High |
| **Preconditions** | `PATHS.claude_dir/agents/a2.md` 실체(vault 밖). vault에는 이미 `skill:alpha` |
| **Input** | `_loop_stdscr([ord("]")]*3 + [ord("i"), ord("[")]*1 ... )` — Agents로 이동 → `i` → `[`×3 으로 Vault 복귀 → `q` |
| **Gap** | NEW — import 후 **다른 서브탭의 목록에 반영되는지**를 여정으로 확인하는 테스트가 없다 |

**Steps**:
1. Vault → Agents 로 `]` 3번 이동한다
2. `i` 로 import한다
3. `[` 3번으로 Vault 서브탭에 돌아온다
4. 마지막 프레임 화면과 디스크를 확인한다

**Expected Output**: 화면에 `a2` 행이 있고 `PATHS.vault/agents/a2.md` 가 실체, `PATHS.claude_dir/agents/a2.md` 가 심볼릭 링크다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-006: `g` → `p` → `Enter` 로 전역·프로젝트 링크가 한 번에 적용된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-002 |
| **US** | US-VLT09 AC1·AC2, US-VLT05 AC1 |
| **Priority** | Critical |
| **Preconditions** | vault에 `skill:alpha`. `confirm_modal` 을 `lambda *a, **k: True` 로 monkeypatch |
| **Input** | `_loop_stdscr([ord("g"), ord("p"), 10, ord("q")])` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_vault_enter_pending_confirm_yes_applies` 는 핸들러 직접 호출이다. 루프를 통과한 뒤 두 스코프가 **동시에** 적용되는 여정 단언이 없다 |

**Steps**:
1. `g` 와 `p` 로 두 pending을 쌓는다
2. `Enter` 로 확인 모달을 승인한다
3. 두 링크와 프로필을 확인한다

**Expected Output**: 상태 메시지 `"Applied 2"`, `PATHS.claude_dir/skills/alpha` 와 `<cwd>/.claude/skills/alpha` 가 모두 심볼릭 링크이며 프로필의 `skills` 에 `"alpha"` 가 있다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-007: `y` sync 이후 프로필 선언과 실제 링크가 완전히 일치한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-002 |
| **US** | US-PRJ03 AC1·AC2·AC3, US-PRJ04 AC2 |
| **Priority** | Critical |
| **Preconditions** | 프로필은 `skills=("alpha","beta")` 선언, 디스크에는 `alpha` 링크 + 프로필에 없는 `gamma` 링크. vault에 세 항목 모두 존재 |
| **Input** | `_loop_stdscr([ord("y"), ord("q")])` |
| **Gap** | NEW — TUI `y` 로 sync를 태운 뒤 **최종 디스크 집합 == 프로필 집합** 을 단언하는 여정 테스트가 없다 |

**Steps**:
1. 어긋난 상태를 배치한다
2. `y` 를 눌러 동기화한다
3. `.claude/skills/` 의 엔트리 집합과 프로필의 `skills` 를 비교한다

**Expected Output**: 상태 메시지가 `"Sync: +1 -1 err 0"` 이고 두 집합이 `{"alpha", "beta"}` 로 같으며 vault 실체는 그대로다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-003 — 정렬 여정 (Skills → Commands → Agents)

### TC-E2E-008: Skills에서 `s` 순회가 헤더 글리프·상태바·행 순서를 함께 움직인다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-003 |
| **US** | US-TUI03 AC1·AC2·AC5·AC8 |
| **Priority** | High |
| **Preconditions** | skills 3건(`zeta`/`alpha`/`mid`)을 이름·버전·소스가 서로 다르게 배치. `state.ext_sub_tab = "skills"` |
| **Input** | `ord("s")` × 9 (Skills의 정렬 컬럼 수 만큼) |
| **Gap** | PARTIAL — `tests/test_tui.py::test_sort_column_cycle_wraps_and_covers_every_column` 은 키 순환만, `::test_render_marks_active_sort_column` 은 렌더만 본다. 순환 중 **행 수 불변**과 상태바 동기화를 한 여정에서 함께 보지 않는다 |

**Steps**:
1. 매 `s` 마다 화면 문자열과 표시 행 수를 캡처한다
2. 헤더의 `▲`/`▼` 위치를 확인한다
3. 9회 후 첫 컬럼으로 돌아왔는지 확인한다

**Expected Output**: 매 단계 행 수가 3으로 고정되고, 활성 컬럼 헤더에만 글리프가 붙으며 상태바가 같은 컬럼명을 표시한다. 9회 후 `name ▲` 로 순환 복귀한다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-009: `S` 로 뒤집은 방향은 `s` 로 다음 컬럼에 갈 때 기본 방향으로 초기화된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-003 |
| **US** | US-TUI03 AC3·AC4 |
| **Priority** | High |
| **Preconditions** | Skills 3건. 시작 상태는 기본 정렬(`name ▲`) |
| **Input** | `ord("S")` → `ord("s")` |
| **Gap** | COVERED — `tests/test_tui.py::test_sort_direction_reverses_the_order`, `::test_sort_key_alone_uses_the_column_natural_direction` |

**Steps**:
1. `S` 로 방향을 뒤집고 상태바 라벨을 확인한다
2. `s` 로 다음 컬럼에 넘어간다
3. 새 컬럼의 방향을 확인한다

**Expected Output**: `S` 후 `name ▼`, `s` 후 `ver ▲`(텍스트 컬럼의 기본 방향). `Updated`/`Used` 계열은 `▼` 로 진입한다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-010: 서브탭을 옮겨도 각자의 정렬 상태가 독립으로 유지된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-003 |
| **US** | US-TUI03 AC9 |
| **Priority** | Medium |
| **Preconditions** | skills 3건, commands 3건, agents 3건 |
| **Input** | Skills에서 `s`×2 → `]` → Commands에서 `s`×1 → `]` → Agents → `[`×2 로 Skills 복귀 |
| **Gap** | NEW — 정렬 상태의 서브탭별 독립성을 여정으로 확인하는 테스트가 없다(검색 쪽에는 `::test_ext_search_is_per_subtab` 이 있다) |

**Steps**:
1. Skills 정렬을 두 칸 옮긴다
2. Commands로 이동해 한 칸 옮긴다
3. Agents를 지나 Skills로 돌아온다
4. 세 서브탭의 상태바 정렬 라벨을 각각 확인한다

**Expected Output**: Skills는 `vault ▲`, Commands는 `ver ▲`, Agents는 기본 `name ▲` 로 각각 유지된다. 서브탭 전환 시 detail 포커스는 해제된다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-004 — 검색 여정

### TC-E2E-011: 검색 입력 중 예약 키가 질의어로 들어가고 적용 후 필터바에 칩이 뜬다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-004 |
| **US** | US-TUI04 AC1·AC4 |
| **Priority** | High |
| **Preconditions** | Market 2건 — 이름에 `s` 와 `r` 이 포함된 `sort-repo` 와 무관한 `other` |
| **Input** | `ord("/")` → `ord("s")`, `ord("r")` → `10`(Enter) |
| **Gap** | PARTIAL — `tests/test_tui.py::test_ext_slash_search_filters_subtab_view`, `::test_ext_subtab_search_band_renders_like_vault` 가 각각을 본다. **예약 키 캡처 → 필터 적용 → 필터바 칩** 을 한 흐름으로 잇지 않는다 |

**Steps**:
1. `/` 로 입력 모드에 들어간다
2. `s`, `r` 을 차례로 보낸다
3. 정렬이 바뀌지 않았는지 확인한다
4. Enter로 적용하고 필터바를 확인한다

**Expected Output**: 정렬 라벨은 그대로이고 질의어는 `"sr"`, 적용 후 필터바에 `(1/2 items)` 와 `search='sr'` 이 표시된다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-012: 검색 0건과 데이터 0건의 안내 문구가 다르다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-004 |
| **US** | US-TUI04 AC3, US-TUI06 AC3 |
| **Priority** | Medium |
| **Preconditions** | Skills 1건 존재(데이터 있음), 그리고 항목이 전혀 없는 별도 상태 |
| **Input** | 매칭되지 않는 질의어 적용 / 빈 목록 렌더 |
| **Gap** | COVERED — `tests/test_tui.py::test_render_extensions_skills_subtab_search_no_match`, `::test_render_extensions_skills_subtab_empty` |

**Steps**:
1. 매칭 0건이 되는 질의어를 적용하고 화면을 확인한다
2. 항목이 없는 상태에서 화면을 확인한다

**Expected Output**: 전자는 `No skills match "zzz". Press Esc to clear the filter.`, 후자는 `"No skills found yet."` + 힌트 줄이다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-013: 서브탭별 필터가 독립 유지되고 `Esc` 가 한 단계씩 되돌린다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-004 |
| **US** | US-TUI04 AC2, US-VLT08 AC4, US-TUI02 AC4 |
| **Priority** | High |
| **Preconditions** | Market 2건, Skills 3건. `state.focused_layer = "content"` |
| **Input** | Market에서 `/`+질의+Enter → `]` → Skills에서 `/`+질의+Enter → `27`(Esc) → `27` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_ext_search_is_per_subtab`, `::test_ext_search_applied_esc_clears_before_climb` 이 각각을 본다. 두 서브탭을 오가며 **한쪽 해제 후 다른 쪽 필터 잔존**까지 잇지 않는다 |

**Steps**:
1. Market에 필터를 적용한다
2. Skills로 옮겨 다른 필터를 적용한다
3. `Esc` 한 번으로 Skills 필터만 풀린 것을 확인한다
4. `Esc` 를 한 번 더 눌러 포커스가 subTab으로 올라가는지 확인한다
5. Market으로 돌아가 필터가 남았는지 확인한다

**Expected Output**: 3단계 후 `state.ext_search` 에 `"market"` 키만 남고, 4단계 후 `state.focused_layer == "subTab"` 이며, 5단계에서 Market 필터바에 칩이 그대로 있다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-005 — 일괄 조작 여정 (Plugins)

### TC-E2E-014: `Space` 마크가 정렬 변경을 넘어 유지된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-005 |
| **US** | US-VLT08 AC3 |
| **Priority** | High |
| **Preconditions** | 플러그인 3건(`a@mk`, `b@mk`, `c@mk`). `state.ext_sub_tab = "plugins"` |
| **Input** | `ord(" ")` → `ord("j")` → `ord(" ")` → `ord("s")` → `ord("S")` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_space_marks_and_unmarks_item`, `::test_extensions_row_checkbox_reflects_marks` 가 마크 자체를 본다. **정렬 변경 후 마크 집합 보존**은 확인하지 않는다 |

**Steps**:
1. 두 항목을 마크한다
2. 정렬 컬럼과 방향을 바꾼다
3. `state.ext_marked["plugins"]` 와 화면 체크박스를 확인한다

**Expected Output**: 마크 집합이 정렬 전후로 같고, 재정렬된 화면에서도 같은 두 행에 `■` 가 그려진다. 상태바에 `marked=2` 가 표시된다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-015: 마크된 항목만 `g` 로 일괄 토글되어 settings에 기록된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-005 |
| **US** | US-VLT08 AC1, US-PLG02 AC2·AC3 |
| **Priority** | Critical |
| **Preconditions** | 플러그인 3건, `PATHS.settings` 는 빈 JSON. `confirm_modal` → `True` monkeypatch |
| **Input** | `ord(" ")`, `ord("j")`, `ord(" ")`, `ord("g")` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_bulk_p_toggle_applies_to_marked_plugins` 가 project 스코프 일괄을 본다. **global 스코프 + settings 파일 내용 + 마크 해제** 를 함께 단언하지 않는다 |

**Steps**:
1. 두 항목을 마크한다
2. `g` 를 눌러 모달을 승인한다
3. `PATHS.settings` 의 `enabledPlugins` 를 읽는다
4. 마크 집합을 확인한다

**Expected Output**: 마크한 두 id만 키로 들어가고 세 번째는 없다. 기존 키는 보존되며(`write_json_atomic`) 마크는 비워지고 상태 메시지에 `2/2` 가 담긴다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-016: 확인 모달을 거절하면 파일도 마크도 변하지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-005 |
| **US** | US-VLT09 AC4, US-PLG04 AC2 |
| **Priority** | Critical |
| **Preconditions** | TC-E2E-015와 동일. `confirm_modal` → `False` monkeypatch. settings 파일의 바이트 스냅샷 확보 |
| **Input** | `ord(" ")`, `ord("j")`, `ord(" ")`, `ord("g")` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_bulk_toggle_nothing_changed_keeps_marks` 는 토글이 전부 실패한 경로다. **모달 거절 경로에서의 파일 불변**은 확인하지 않는다 |

**Steps**:
1. 두 항목을 마크한다
2. `g` 를 눌러 모달을 거절한다
3. settings 바이트를 비교하고 마크 집합을 확인한다

**Expected Output**: 상태 메시지는 `"Cancelled"`, settings 파일은 바이트 단위로 동일, 마크 2건이 그대로 남는다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-006 — pending 취소 여정 (Vault)

### TC-E2E-017: pending은 화면에만 표시되고 디스크에 닿지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-006 |
| **US** | US-VLT09 AC1 |
| **Priority** | High |
| **Preconditions** | vault 2건, 프로젝트 링크 없음. `<cwd>/.claude` 하위 엔트리 스냅샷 확보 |
| **Input** | `ord("p")` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_vault_p_toggles_project_pending`, `::test_render_frame_vault_pending_shortcuts` 가 상태와 상태바를 본다. **pending 상태에서 디스크 불변**을 파일로 확인하지 않는다 |

**Steps**:
1. 스냅샷을 잡는다
2. `p` 를 보낸다
3. 프레임을 그려 pending 표시를 확인한다
4. 스냅샷을 다시 비교한다

**Expected Output**: 상태바가 `Enter:apply pending (confirm)  Esc:discard …` 로 바뀌고, `.claude` 하위 엔트리와 `.axt-profile.json` 존재 여부는 변하지 않는다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-018: `Esc` 폐기 후 디스크가 조작 전과 동일하다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-006 |
| **US** | US-VLT09 AC3 |
| **Priority** | Critical |
| **Preconditions** | TC-E2E-017과 동일 |
| **Input** | `_loop_stdscr([ord("p"), 27, ord("q")])` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_vault_esc_discards_pending` 은 pending 집합만 본다. 루프를 통과한 뒤 디스크 스냅샷 비교가 없다 |

**Steps**:
1. 스냅샷을 잡는다
2. `p` → `Esc` → `q` 를 흘려 넣는다
3. 스냅샷을 다시 잡아 비교한다

**Expected Output**: 두 스냅샷이 동일하고 최종 상태 메시지는 `"Discarded pending changes"` 이며 `Esc` 가 앱을 종료시키지 않는다(content 레이어에서 climb 예외).
**Actual Output**: —
**Status**: —

---

## SC-E2E-007 — MCP 여정 (등록 ≠ 활성, detail 패널)

### TC-E2E-019: `Tab` 으로 detail 패널을 포커스해 스크롤하고 다시 복귀한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-007 |
| **US** | US-TUI05 AC1·AC2 |
| **Priority** | High |
| **Preconditions** | MCP 서버 2건 등록. `state.ext_sub_tab = "mcp"`, 캐시 로드 완료 |
| **Input** | `9`(Tab) → `ord("j")`×3 → `9` |
| **Gap** | COVERED — `tests/test_tui.py::test_ext_detail_tab_focus_and_scroll`, `::test_mcp_sub_tab_renders_detail_panel` |

**Steps**:
1. `Tab` 으로 포커스한다
2. `j` 로 3칸 스크롤한다
3. `Tab` 으로 블러한다

**Expected Output**: 포커스 시 상태 메시지가 `"Detail focused — j/k scroll, Esc/Tab to blur"`, 스크롤 값이 3, 블러 후 `ext_detail_focused is False` 이고 스크롤이 0으로 돌아간다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-020: 선택을 옮기면 detail 스크롤이 맨 위로 돌아가고 끝을 넘지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-007 |
| **US** | US-TUI05 AC3·AC4 |
| **Priority** | High |
| **Preconditions** | MCP 서버 2건, 그중 하나는 detail이 패널보다 짧다 |
| **Input** | `9` → `curses.KEY_NPAGE`×5 → `9` → `ord("j")` |
| **Gap** | COVERED — `tests/test_tui.py::test_ext_detail_scroll_resets_on_selection_move`, `::test_render_detail_panel_clamps_to_max_scroll` |

**Steps**:
1. detail을 크게 스크롤한다
2. 리스트로 복귀해 `j` 로 선택을 옮긴다
3. 스크롤 값과 렌더 결과를 확인한다

**Expected Output**: 스크롤이 0으로 리셋되고, 내용이 짧은 항목에서는 렌더가 스크롤을 상한으로 되돌린다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-021: `p` 는 On만 바꾸고 Proj/Glob 등록 글리프는 그대로다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-007 |
| **US** | US-MCP02 AC1·AC3, US-MCP03 AC1·AC2 |
| **Priority** | Critical |
| **Preconditions** | `~/.claude.json` 에 user 스코프 서버 `srvA` 등록. `PATHS.claude_config` 를 `tmp_path` 하위로 고정, `monkeypatch.chdir(proj)`(프로젝트별 기록이므로 cwd 격리 필수) |
| **Input** | `ord("p")` |
| **Gap** | NEW — On 토글 후 **`projects[<cwd>].disabledMcpServers` 기록 + Proj/Glob 글리프 불변** 을 함께 단언하는 테스트가 없다 |

**Steps**:
1. 토글 전 프레임에서 해당 행의 Proj/Glob/On 셀을 캡처한다
2. `p` 를 보낸다
3. `~/.claude.json` 을 읽어 `projects[<cwd>]` 를 확인한다
4. 다음 프레임의 같은 셀들을 캡처해 비교한다

**Expected Output**: `disabledMcpServers == ["srvA"]` 로 기록되고 On 셀만 뒤집힌다. Glob은 `●`, Proj는 `─` 로 변하지 않으며 다른 프로젝트 키는 생기지 않는다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-022: MCP의 `g` 는 안내만 내고 어떤 파일도 쓰지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-007 |
| **US** | US-MCP02 AC2 |
| **Priority** | Medium |
| **Preconditions** | TC-E2E-021과 동일. `~/.claude.json` 의 mtime과 바이트 스냅샷 확보 |
| **Input** | `ord("g")` |
| **Gap** | PARTIAL — `tests/test_tui.py` 가 안내 메시지를 보지만 파일 불변은 확인하지 않는다 |

**Steps**:
1. 스냅샷을 잡는다
2. `g` 를 보낸다
3. 스냅샷을 비교한다

**Expected Output**: 안내 메시지가 나오고 `~/.claude.json` 이 바이트 단위로 동일하다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-008 — Usage 리포트 검색 점프

### TC-E2E-023: 타이핑 중 앵커 이후 첫 매칭으로 라이브 점프하고, 매칭이 없어지면 앵커로 돌아온다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-008 |
| **US** | US-TUI07 AC1·AC2 |
| **Priority** | High |
| **Preconditions** | `state.usage_entries` 를 직접 채워 백그라운드 로더를 태우지 않는다. `state.usage_lines` 가 렌더로 채워진 뒤 `state.usage_scroll = 5` 로 앵커 위치를 만든다 |
| **Input** | `ord("/")` → `ord("o")`, `ord("p")` → `ord("z")` |
| **Gap** | COVERED — `tests/test_tui.py::test_usage_search_live_jump_while_typing`, `::test_usage_search_esc_while_typing_restores_anchor` |

**Steps**:
1. `/` 로 앵커를 잡는다
2. 매칭되는 글자를 입력해 점프를 확인한다
3. 매칭이 사라지는 글자를 추가한다

**Expected Output**: 매칭 중에는 `usage_scroll` 이 앵커 이후 첫 매칭 라인, 매칭 소실 시 `usage_scroll == 5`(앵커)이고 `usage_match_idx == -1`.
**Actual Output**: —
**Status**: —

---

### TC-E2E-024: Enter 적용 후 `n`/`N` 이 매칭을 순회하고 상태바에 `match i/N` 이 뜬다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-008 |
| **US** | US-TUI07 AC3·AC4 |
| **Priority** | High |
| **Preconditions** | 같은 문자열이 3줄에 나오도록 usage 엔트리를 구성 |
| **Input** | `ord("/")` → 질의 입력 → `10` → `ord("n")` → `ord("n")` → `ord("N")` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_usage_search_enter_jumps_to_first_match`, `::test_usage_search_n_cycles_matches`, `::test_usage_filter_bar_shows_search_chip` 이 각각을 본다. 적용 → 순회 → 고정 필터바 칩을 **한 여정에서** 잇지 않는다 |

**Steps**:
1. 질의를 적용한다
2. `n` 을 두 번, `N` 을 한 번 보낸다
3. 각 단계의 반환 메시지와 프레임의 타이틀 행을 확인한다

**Expected Output**: 메시지가 `"match 1/3"` → `"match 2/3"` → `"match 3/3"` → `"match 2/3"` 로 변하고, 타이틀 행(고정 필터바)에 `search='q'` 와 `match i/N` 칩이 함께 그려진다. 매칭 라인이 하이라이트된다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-025: 적용 후 첫 `Esc` 는 해제, 두 번째 `Esc` 는 레이어 상승

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-008 |
| **US** | US-TUI07 AC5, US-TUI02 AC4 |
| **Priority** | Medium |
| **Preconditions** | Usage 탭, 검색 적용 상태, `state.focused_layer = "content"` |
| **Input** | `27` → `27` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_usage_search_esc_clears_applied`, `::test_content_layer_esc_defers_to_usage_search_clear` 가 각각을 본다. 연속 두 번의 `Esc` 결과를 잇지 않는다 |

**Steps**:
1. 검색을 적용한다
2. `Esc` 를 보내 `usage_search` 를 확인한다
3. `Esc` 를 한 번 더 보내 `focused_layer` 를 확인한다

**Expected Output**: 첫 `Esc` 후 `usage_search == ""`, `focused_layer == "content"` 유지. 두 번째 `Esc` 후 `focused_layer == "mainTab"`(Usage는 subTab이 없다).
**Actual Output**: —
**Status**: —

---

## SC-E2E-009 — Context Project 여정

### TC-E2E-026: `s` 정렬 순환이 헤더 글리프를 옮기고 `%` 는 순환에서 빠진다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-009 |
| **US** | US-CTX05 AC2·AC3·AC4 |
| **Priority** | High |
| **Preconditions** | 토큰 수가 서로 다른 소스 3건. `state.context_sub_tab = "project"`, `get_claude_version`/`get_git_status` 고정 |
| **Input** | `ord("s")` × 4 |
| **Gap** | PARTIAL — `tests/test_tui.py::test_handle_project_input_s_cycles_sort`, `::test_render_project_files_table_marks_sorted_column_header` 가 각각을 본다. **4단계 순환 전체 + `%` 제외** 를 한 여정으로 보지 않는다 |

**Steps**:
1. 초기 렌더의 헤더와 행 순서를 확인한다
2. `s` 를 네 번 눌러 매 단계 헤더를 캡처한다
3. `%` 헤더에 글리프가 붙는지 확인한다

**Expected Output**: 기본은 `Tokens ▼`(내림차순), 순환은 `Name ▲` → `Category ▲` → `Scope ▲` → 다시 `Tokens ▼`. `%` 헤더에는 어느 단계에서도 글리프가 붙지 않는다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-027: memory 소스를 `d` 로 지우면 파일과 `MEMORY.md` 인덱스 줄이 함께 사라진다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-009 |
| **US** | US-CTX04 AC2·AC3 |
| **Priority** | Critical |
| **Preconditions** | `PATHS.projects/<key>/memory/` 에 `old.md`, `keep.md` 와 두 줄짜리 `MEMORY.md`. `confirm_modal` → `True` monkeypatch. `state.stdscr_callbacks` 설정 |
| **Input** | `ord("j")` 로 `old.md` 선택 → `ord("d")` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_project_d_deletes_memory_file_on_confirm` 은 파일 삭제만, `tests/test_context.py::test_delete_memory_file_removes_file_and_index_line` 은 core만 본다. **TUI 여정에서 인덱스 줄까지** 확인하지 않는다 |

**Steps**:
1. Project 목록에서 `old.md` 행을 선택한다
2. `d` 로 확인 모달을 승인한다
3. 파일 존재와 `MEMORY.md` 내용을 확인한다
4. 다음 렌더에서 목록이 갱신됐는지 확인한다

**Expected Output**: `old.md` 가 사라지고 `MEMORY.md` 에는 `keep.md` 줄만 남으며, `state.project_items` 와 `state.context_analysis` 가 `None` 으로 무효화돼 다음 렌더에서 재수집된다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-028: memory가 아닌 소스의 `d` 는 거부되고, 취소하면 파일이 남는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-009 |
| **US** | US-CTX04 AC2, US-VLT09 AC4 |
| **Priority** | High |
| **Preconditions** | CLAUDE.md 소스와 memory 소스가 각각 1건. `confirm_modal` 은 케이스별로 `True`/`False` |
| **Input** | CLAUDE.md 선택 후 `ord("d")` / memory 선택 후 `ord("d")` + 거절 |
| **Gap** | COVERED — `tests/test_tui.py::test_project_d_rejects_non_memory_source`, `::test_project_d_cancelled_leaves_file` |

**Steps**:
1. CLAUDE.md 소스에서 `d` 를 누른다
2. memory 소스에서 `d` 를 누르고 모달을 거절한다

**Expected Output**: 전자는 `"Only memory files can be deleted here"`, 후자는 `"Cancelled"` 이고 두 경우 모두 파일이 남는다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-010 — Context Sources 여정

### TC-E2E-029: rate limit 스트립과 cost impact 라인이 두 서브탭 공통으로 표시된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-010 |
| **US** | US-CTX06 AC1·AC3 |
| **Priority** | High |
| **Preconditions** | rate limit 스냅샷 파일에 `five_hour.used_percentage = 42`, `seven_day.used_percentage = 17`, `updated_at` 을 **고정 ISO 문자열**로 심는다(시계 비의존) |
| **Input** | Context 탭에서 `ord("]")` → `ord("[")` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_context_tab_shows_project_files_on_project_sub_tab`, `::test_context_tab_hides_project_files_on_sources_sub_tab` 가 본문 전환만 본다. 스트립·cost impact의 **양 서브탭 공통 표시**를 함께 단언하지 않는다 |

**Steps**:
1. Project 서브탭 프레임을 캡처한다
2. `]` 로 Sources 로 전환해 프레임을 캡처한다
3. `[` 로 되돌아온다
4. 두 프레임에서 스트립과 cost impact 라인을 확인한다

**Expected Output**: 두 프레임 모두에 5h/7d 게이지와 `[assumes 30 turns × 5 sessions/day]` 문구가 있고, 본문 테이블만 바뀐다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-030: rate limit 데이터가 없거나 낡으면 그 사실이 화면에 드러난다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-010 |
| **US** | US-CTX06 AC2 |
| **Priority** | Medium |
| **Preconditions** | (a) 스냅샷 파일 없음 (b) `updated_at` 이 tolerance(기본 5분)보다 오래된 **고정 ISO 문자열**. 판정 기준 시각을 주입 지점으로 고정하고 `datetime.now()` 에 의존하지 않는다 |
| **Input** | 두 상태에서 각각 Context 탭 렌더 |
| **Gap** | NEW — 신선도 판정이 화면 문구로 드러나는지 확인하는 테스트가 없다 |

**Steps**:
1. 스냅샷 없는 상태로 렌더한다
2. 낡은 스냅샷으로 렌더한다
3. 두 화면 문자열을 비교한다

**Expected Output**: 두 경우 모두 게이지 자리에 데이터 부재/낡음을 알리는 문구가 나오고, 신선한 경우와 화면이 구별된다. 어느 경우에도 예외가 나지 않는다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-031: Sources에서 `Enter` 로 detail에 내려갔다 `Esc` 로 돌아온다(탭 이탈 없음)

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-010 |
| **US** | US-TUI05 AC2, US-CTX01 AC1 |
| **Priority** | High |
| **Preconditions** | 카테고리 롤업 행이 2건 이상인 분석 결과. `state.context_sub_tab = "sources"`, `focused_layer = "content"` |
| **Input** | `10` → `ord("j")`×2 → `27` → `27` |
| **Gap** | COVERED — `tests/test_tui.py::test_context_sources_enter_focuses_detail_panel`, `::test_context_detail_focus_scrolls_and_esc_blurs`, `::test_content_layer_esc_defers_to_context_search_clear` |

**Steps**:
1. `Enter` 로 detail을 포커스한다
2. `j` 로 스크롤한다
3. `Esc` 로 블러한다
4. `Esc` 를 한 번 더 눌러 레이어 상승을 확인한다

**Expected Output**: 3단계 후 `context_detail_focused is False` 이고 탭은 그대로. 4단계 후 `focused_layer == "subTab"`.
**Actual Output**: —
**Status**: —

---

## SC-E2E-011 — 훅 여정

### TC-E2E-032: `v` 미리보기가 exit code와 stdout을 모달에 담는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-011 |
| **US** | US-HK04 AC1 |
| **Priority** | High |
| **Preconditions** | user settings에 `command = "echo axt-preview-probe"` 훅 1건(부작용 없는 명령만 사용). `preview_modal` 을 본문 캡처 stub으로 교체 |
| **Input** | `ord("v")` |
| **Gap** | COVERED — `tests/test_tui.py::test_subtab_action_hook_preview`, `::test_subtab_action_hook_preview_includes_stderr` |

**Steps**:
1. Hooks 서브탭에서 훅을 선택한다
2. `v` 를 보낸다
3. 캡처된 모달 본문을 확인한다

**Expected Output**: 본문에 `Exit:    0` 과 `axt-preview-probe` 가 있고 제목이 `Hook preview: <event>` 다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-033: 실행이 실패해도 모달로 보고되고 TUI가 죽지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-011 |
| **US** | US-HK04 AC2, US-SYS06 AC2 |
| **Priority** | High |
| **Preconditions** | 존재하지 않는 명령을 가진 훅 1건 |
| **Input** | `ord("v")` → 이어서 `ord("j")` 로 계속 조작 |
| **Gap** | COVERED — `tests/test_tui.py::test_subtab_action_hook_preview_failure` |

**Steps**:
1. 실패하는 훅에서 `v` 를 보낸다
2. 모달 본문에 exit code / stderr가 담겼는지 확인한다
3. 이어서 `j` 를 보내 핸들러가 정상 동작하는지 확인한다

**Expected Output**: 0이 아닌 exit code와 stderr가 본문에 담기고, 이후 키 처리가 예외 없이 이어진다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-034: plugin 훅의 `p`/`g` 는 읽기 전용 안내만 내고 설정 파일이 변하지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-011 |
| **US** | US-HK03 AC1·AC2 |
| **Priority** | High |
| **Preconditions** | 활성 플러그인 훅 1건 + user 훅 1건. 두 설정 파일의 바이트 스냅샷 확보 |
| **Input** | plugin 훅 선택 후 `ord("p")`, `ord("g")` |
| **Gap** | PARTIAL — 안내 메시지는 `tests/test_tui.py` 가 보지만, 거부 후 **설정 파일 바이트 불변**은 확인하지 않는다 |

**Steps**:
1. 스냅샷을 잡는다
2. plugin 훅에서 `p` 와 `g` 를 각각 보낸다
3. 스냅샷을 비교한다
4. user 훅으로 옮겨 `g` 로 무손실 토글이 되는지 확인한다

**Expected Output**: plugin 훅에서는 `"Plugin hooks are read-only …"` 만 나오고 파일이 동일하다. user 훅의 `g` 는 같은 파일 안에서 `hooks` ↔ `disabledHooks` 로 정의를 손실 없이 옮긴다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-012 — 테마 토글 여정

### TC-E2E-035: `t` 가 테마를 전환하고 config에 저장한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-012 |
| **US** | US-TUI09 AC1 |
| **Priority** | Medium |
| **Preconditions** | `axt.tui_init_colors("dark")` 로 활성 테마 시드. `_persist_theme` 캡처 stub 또는 `AXT_CONFIG_PATH` 를 `tmp_path` 로 고정 |
| **Input** | `_loop_stdscr([ord("t"), ord("q")])` |
| **Gap** | COVERED — `tests/test_tui.py::test_tui_loop_t_persists_theme_toggle` |

**Steps**:
1. dark로 시드한 뒤 `t` 를 보낸다
2. 저장된 값을 확인한다

**Expected Output**: `"light"` 가 저장되고 상태 메시지가 `"Theme: light"` 다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-036: 검색 입력 중의 `t` 는 테마를 바꾸지 않고 질의어로 들어간다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-012 |
| **US** | US-TUI09 AC3, US-TUI04 AC1 |
| **Priority** | Medium |
| **Preconditions** | Vault 서브탭, `_persist_theme` 호출 카운터 |
| **Input** | `_loop_stdscr([ord("/"), ord("t"), 27, ord("q")])` |
| **Gap** | NEW — `tests/test_tui.py::test_vault_search_captures_r_via_extensions_dispatcher` 는 `r` 만 태운다. **전역 키 `t` 의 modal 게이트**를 루프에서 확인하는 테스트가 없다 |

**Steps**:
1. `/` 로 검색 입력에 들어간다
2. `t` 를 보낸다
3. `_persist_theme` 호출 수와 `state.vault_search` 를 확인한다
4. `Esc` 로 취소하고 종료한다

**Expected Output**: `_persist_theme` 호출 0회, `state.vault_search == "t"`. `Esc` 이후 검색이 취소되고 테마는 초기값 그대로다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-037: 테마 전환 직후 프레임이 즉시 다시 그려진다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-012 |
| **US** | US-TUI09 AC1 |
| **Priority** | Low |
| **Preconditions** | `_render_frame` 호출 카운터 spy |
| **Input** | `_loop_stdscr([ord("t"), ord("q")])` |
| **Gap** | PARTIAL — 테마 저장은 covered이나 **전환 직후 즉시 재렌더**는 별도로 확인되지 않는다 |

**Steps**:
1. 렌더 호출 수를 기록한다
2. `t` 를 보낸다
3. 호출 수 증가를 확인한다

**Expected Output**: `t` 처리 중 `_render_frame` 이 한 번 더 호출되어 상태 메시지가 즉시 화면에 반영된다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-013 — 좁은 터미널 여정

### TC-E2E-038: 최소 크기 미만에서는 안내 문구만 그린다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-013 |
| **US** | US-TUI10 AC1 |
| **Priority** | High |
| **Preconditions** | `_make_stdscr(rows=4, cols=20)` |
| **Input** | `axt._render_frame(scr, axt.TuiState())` |
| **Gap** | COVERED — `tests/test_tui.py::test_render_frame_too_small_shows_resize_message` |

**Steps**:
1. 작은 화면으로 프레임을 그린다
2. 화면 문자열을 확인한다

**Expected Output**: `"Terminal too small. Resize and try again."` 만 그려지고 탭 바·테이블은 그려지지 않는다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-039: 리사이즈 후 정상 프레임이 복구되고 CJK 정렬이 유지된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-013 |
| **US** | US-TUI10 AC2·AC3 |
| **Priority** | High |
| **Preconditions** | `getmaxyx` 가 `(4, 20)` → `(30, 120)` 순으로 다른 값을 돌려주는 stdscr. 이름이 `한글스킬` 인 항목 1건 |
| **Input** | `_loop_stdscr([curses.KEY_RESIZE, ord("q")])` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_tui_loop_resize_then_quit` 은 예외 없이 종료하는지만 본다. **복구된 프레임 내용과 CJK 폭 처리**를 확인하지 않는다 |

**Steps**:
1. 작은 크기로 첫 프레임을 그린다
2. `KEY_RESIZE` 를 보낸다
3. 두 번째 프레임의 화면 문자열과 각 `addnstr` 의 `max_w` 인자를 확인한다

**Expected Output**: 두 번째 프레임에 탭 바와 테이블이 나타나고 `한글스킬` 셀이 잘리더라도 예외가 나지 않으며, wide 문자에 대해 `east_asian_width` 기반 폭이 `addnstr` 에 넘어간다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-014 — 도움말 여정

### TC-E2E-040: `?` 로 도움말을 열고 닫은 뒤 정상 종료한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-014 |
| **US** | US-TUI08 AC2 |
| **Priority** | Medium |
| **Preconditions** | `preview_modal` 을 제목·본문 캡처 stub으로 교체 |
| **Input** | `_loop_stdscr([ord("?"), ord("q")])` |
| **Gap** | COVERED — `tests/test_tui.py::test_tui_loop_help_then_quit` |

**Steps**:
1. `?` 를 보낸다
2. 캡처된 제목을 확인한다
3. `q` 로 종료한다

**Expected Output**: 제목이 `"axt help"` 이고 모달 처리 후 `state.show_help` 가 `False` 로 돌아오며 루프가 정상 종료한다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-041: 도움말 본문의 정렬 순환이 실제 키맵에서 생성된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-014 |
| **US** | US-TUI08 AC1 |
| **Priority** | High |
| **Preconditions** | 없음(정적 문자열 생성 경로) |
| **Input** | `axt.HELP_TEXT` 와 `sort_cycle_help(sub)` 를 8개 서브탭에 대해 대조 |
| **Gap** | COVERED — `tests/test_tui.py::test_sort_cycle_help_lists_the_columns`, `::test_help_text_includes_every_keymap_help_line` |

**Steps**:
1. 각 서브탭의 `sort_cycle_help` 값을 만든다
2. `HELP_TEXT` 에 그 문자열이 포함됐는지 확인한다

**Expected Output**: 8개 서브탭의 순환 문자열(예: Market의 `name→upd→kind→loc→updated`)이 모두 도움말 본문에 있다.
**Actual Output**: —
**Status**: —

---

## SC-E2E-015 — 업데이트 여정 (Market)

### TC-E2E-042: 확인 전 `…` 가 확인 후 `↑`/`·` 로 바뀐다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-015 |
| **US** | US-UPD05 AC1 |
| **Priority** | High |
| **Preconditions** | 마켓 2건 등록. 1단계는 `state.update_statuses = None`, 2단계는 결과 dict를 직접 심는다(백그라운드 스윕은 conftest가 차단 — 스레드 비의존) |
| **Input** | 두 상태에서 각각 Market 서브탭 렌더 |
| **Gap** | PARTIAL — `tests/test_tui.py::test_upd_cell_markers` 는 셀 헬퍼를 개별 상태로 본다. **한 세션 안에서 `…` → `↑` 전이가 화면에 반영되는지**는 확인하지 않는다 |

**Steps**:
1. `update_statuses = None` 으로 렌더해 Upd 열을 캡처한다
2. 결과를 심고 다시 렌더한다
3. 두 프레임의 같은 행을 비교한다

**Expected Output**: 1단계는 두 행 모두 `…`, 2단계는 업데이트 가능 행이 `↑`, 최신 행이 `·` 다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-043: `u` 적용 성공 후 같은 프레임에서 마커가 `·` 로 갱신된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-015 |
| **US** | US-UPD06 AC1 |
| **Priority** | High |
| **Preconditions** | 업데이트 가능 상태를 심어 둔 마켓 1건. `sync_marketplace` 를 결정적 결과 stub으로 교체(네트워크·git 비의존) |
| **Input** | `ord("u")` 이후 렌더 |
| **Gap** | PARTIAL — `tests/test_tui.py::test_act_update_settles_upd_marker` 는 `state.update_statuses` 만 단언한다(`tests/test_tui.py:1115`). **렌더된 Upd 셀**까지 확인하지 않는다 |

**Steps**:
1. `u` 를 보낸다
2. 상태 메시지를 확인한다
3. 다음 프레임의 해당 행 Upd 셀을 확인한다

**Expected Output**: 메시지에 적용 결과가 담기고, 다시 확인을 돌리지 않아도 해당 행의 Upd 셀이 `·` 로 그려진다.
**Actual Output**: —
**Status**: —

---

### TC-E2E-044: 마크 일괄 `u` 에서 한 항목의 실패가 나머지를 중단시키지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-E2E-015 |
| **US** | US-UPD06 AC2·AC3, US-VLT08 AC1 |
| **Priority** | High |
| **Preconditions** | 마켓 3건 — 성공 1, 최신 1, 실패 1이 되도록 apply 결과를 stub. `confirm_modal` → `True` |
| **Input** | `ord(" ")`, `ord("j")`, `ord(" ")`, `ord("j")`, `ord(" ")`, `ord("u")` |
| **Gap** | COVERED — `tests/test_tui.py::test_act_update_bulk_marked`, `::test_act_update_bulk_reports_failure`, `::test_act_update_bulk_flashes_current_item` |

**Steps**:
1. 세 항목을 마크한다
2. `u` 로 일괄 적용한다
3. 상태바 집계 문구를 확인한다

**Expected Output**: 실패 항목에서 중단하지 않고 세 건을 모두 처리하며, 상태바에 `1 updated, 1 up to date, 1 failed` 형태의 집계가 표시된다.
**Actual Output**: —
**Status**: —

---

## 스펙 갭

시나리오 문서의 [스펙 갭](../scenarios/e2e-scenarios.md#스펙-갭) 절과 대응한다.

| ID | 요약 | 관련 TC |
|---|---|---|
| G-5 | Usage 탭의 focus 레이어 전이표가 FEATURES.md에 명시돼 있지 않음 — TC-E2E-025는 검색 해제와 mainTab 복귀까지만 단언 | TC-E2E-025 |
| G-6 | Commands/Agents의 `e` 편집 여정은 `$EDITOR` 외부 프로세스에 의존해 헤드리스 E2E 대상에서 제외 | TC 없음 |
| G-7 | rate limit 신선도(기본 5분 tolerance) 판정 결과의 **화면 문구**가 FEATURES.md §2.7 / §4.5에 문자열로 규정돼 있지 않음 — TC-E2E-030은 "신선한 경우와 화면이 구별된다"까지만 단언한다 | TC-E2E-030 |
