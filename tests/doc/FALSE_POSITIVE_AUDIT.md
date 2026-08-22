# 허위 양성 감사 (Phase A-4)

대상: 기존 테스트 **1304개 / 19개 파일**
목적: **통과하지만 아무것도 검증하지 않는 테스트**를 찾는다. 통과하는 허위 양성은 테스트가 없는 것보다
위험하다 — 거짓 안전감을 준다.

## 총평

이 저장소의 기존 스위트는 전반적으로 건강하다. 흔한 허위 양성 패턴 대부분이 **0건**이다.

| 탐지 패턴 | 결과 |
|---|---|
| `except ...: pass` 로 실패 삼킴 | **0건** |
| `assert True` / 자리채우기 | **0건** |
| 무조건 `skip` / `xfail` | **0건** (`skipif`는 전부 정당한 Windows 플랫폼 가드 20건) |
| 상수 검증만 하는 테스트 | 0건 |
| 존재 확인(`callable`/`hasattr`)만 하는 테스트 | 0건 |
| `assert x is not None` 로 끝나는 단언 | 27건 — **전부 타입 내로잉 가드**이며 뒤에 실제 값 검증이 따름 (허위 양성 아님) |
| 단언이 하나도 없는 테스트 | **8건** → 아래 분류 |
| 광범위 `pytest.raises(Exception)` | 2건 → 아래 분류 |

발견된 실질 조치 대상: **CRITICAL 0 / HIGH 1 / MEDIUM 3 / LOW 1**

---

## HIGH-1 — 이름이 주장하는 동작이 전혀 검증되지 않음

**`tests/test_tui.py:4811 test_preview_modal_search_esc_clears_then_closes`**

```python
keys = [ord("/")] + _ord_seq("needle") + [10, 27, 27]   # 총 10개
win, _calls = _make_modal_win(keys)
monkeypatch.setattr("curses.newwin", lambda *a, **kw: win)
axt.preview_modal(scr, content, title="Search")  # must not raise
```

- **주장**: "첫 Esc는 검색만 해제하고 모달은 유지, 두 번째 Esc가 모달을 닫는다" (2단계 전이)
- **실제 검증**: 없음. 단언이 0개다.
- **왜 허위 양성인가**: `_make_modal_win` 의 `win.getch.side_effect = lambda: next(seq)` 는
  **키를 다 쓴 뒤에만** `StopIteration` 을 낸다. 즉 이 테스트의 유일한 실패 조건은
  "키를 10개보다 **더** 소비하는 것"이다.
  구현이 퇴행해 **첫 Esc에서 모달을 닫아버리면 키를 9개만 소비하고 그대로 통과한다.**
  이 테스트가 막으려던 바로 그 버그를 못 잡는다.
- **실측 근거**: 동일 하네스로 직접 측정한 결과

  | 제공 키 | 결과 | getch 호출 |
  |---|---|---|
  | 10개 (기존 테스트와 동일) | 예외 없이 반환 | **10회** |
  | 9개 (첫 Esc에서 닫히는 퇴행 흉내) | `StopIteration` | 10회 시도 |

  현재 구현은 실제로 키 10개를 전부 소비한다(2단계 Esc 정상 동작). 그러나 조기 종료 퇴행이 생기면
  키를 9개만 소비하고 반환하므로 `StopIteration` 이 나지 않고, 단언이 없어 **그대로 통과한다**.
  즉 `win.getch.call_count == 10` 이라는 **관측 가능하고 의미 있는 단언이 이미 존재하는데
  쓰이지 않고 있다**.
- **위험도 HIGH**: 2단계 Esc 전이는 이 TUI 전반의 상호작용 규약(`Esc` 는 한 번에 한 단계만 되돌린다)이며
  Vault·Extensions·Context 에서 반복되는 핵심 UX다.
- **권장 수정**: 모달이 첫 Esc 후에도 살아 있었음을 관측 가능한 증거로 단언한다.
  - 첫 Esc 직후 재렌더된 프레임에 검색 하이라이트가 사라지고 본문이 남아 있을 것
    (`_calls` 에서 `NEEDLE` 라인이 여전히 그려지고 `match` 칩은 사라짐)
  - 또는 `win.getch.call_count == 10` 으로 **모든 키가 소비됐음**을 단언
    (조기 종료 시 9로 떨어져 실패) — 위 실측대로 현재 구현에서 정확히 10이다

---

## MEDIUM — 선언한 의도가 부분적으로만 검증됨

이 3건은 크래시는 잡지만, **함수가 아무것도 그리지 않아도 통과**한다.

| # | 테스트 | 선언한 의도 | 미검증 부분 | 권장 수정 |
|---|---|---|---|---|
| M-1 | `test_tui.py:543 test_render_table_empty_rows` | 주석에 "No crash **+ no data rows drawn**" | 뒷부분(데이터 행 미출력)이 단언되지 않음 | 헤더만 그려지고 데이터 행 y좌표에 출력이 없음을 단언 |
| M-2 | `test_tui.py:3470 test_render_usage_tab_with_data_does_not_raise` | `NameError` 회귀 방지 | 렌더 결과가 비어도 통과 | 합성 엔트리의 모델·토큰이 화면 문자열에 나타남을 단언 |
| M-3 | `test_tui.py:3494 test_render_extensions_tab_mcp_sub_tab_does_not_raise` | `_active_plugins` `NameError` 회귀 방지 | 동일 | MCP 서브탭 헤더(`Server`/`Scope` 등)가 그려짐을 단언 |

> 이 3건은 **"does not raise"가 곧 검증 대상인 테스트**(아래 OK 목록)와 구분된다.
> 차이는 *이름과 주석이 렌더 결과까지 주장하는가* 이다.

---

## LOW — 개선 여지

| # | 테스트 | 문제 | 권장 |
|---|---|---|---|
| L-1 | `test_paths.py:73 test_paths_object_is_frozen` | `pytest.raises(Exception)` 로 너무 넓음 — 무관한 예외도 통과 | `pytest.raises((dataclasses.FrozenInstanceError, AttributeError))` 로 좁힘 |

---

## 허위 양성이 **아닌** 것 (오탐 방지용 기록)

아래는 단언이 없거나 넓은 예외를 쓰지만 **정당하다**. 재감사 시 다시 지적하지 않는다.

| 테스트 | 왜 정당한가 |
|---|---|
| `test_tui.py:4244 test_tui_init_colors_swallows_errors` | "예외를 삼킨다"가 **검증 대상 그 자체**. 관측할 다른 상태가 없음 |
| `test_tui.py:4720 test_preview_modal_newwin_failure_is_silent` | 동일 — `newwin` 실패 시 조용히 반환하는 것이 계약 |
| `test_tui.py:6751 test_save_scan_cache_swallows_oserror` | 동일 — best-effort 쓰기의 계약 |
| `test_tui.py:1120 test_settle_update_status_none_state_is_noop` | `state=None` 이라 관측 가능한 상태가 존재하지 않음. 크래시 가드로 유효 |
| `test_update.py:160 test_materialize_dir_...` | 넓은 `raises` 는 부수적이고, **진짜 단언은 그 뒤의 불변식**(`dest` 무손상) |
| `test_pricing.py` 의 `is not None` 27건 | 타입 내로잉 가드이며 뒤에 실제 단가 검증이 따름 |

---

## Phase F 조치 계획

| ID | 조치 | 분류 |
|---|---|---|
| HIGH-1 | 단언 추가 (테스트 수정) | TEST_ERROR — 테스트가 자기 이름을 검증하지 않음 |
| M-1 ~ M-3 | 단언 추가 (테스트 수정) | TEST_ERROR — 선언한 의도의 미검증 부분 보강 |
| L-1 | 예외 타입 좁힘 | TEST_ERROR — 과도하게 느슨한 단언 |

모두 **테스트 측 수정**이며 구현 변경은 없다. 수정 시 `TEST_DEDUP_POLICY.md` §5에 따라
사유 주석을 남긴다.
