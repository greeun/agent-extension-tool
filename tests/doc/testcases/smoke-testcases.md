# Smoke 테스트 케이스 — axt

대응 시나리오: `tests/doc/scenarios/smoke-scenarios.md`

## 요약

| 항목 | 값 |
|---|---|
| 총 TC 수 | **24** |
| 시나리오 수 | 8 (SC-SMOKE-001 ~ SC-SMOKE-008) |
| 목표 실행 시간 | 전체 2분 이내 |

**우선순위 분포**

| Critical | High | Medium | Low |
|---|---|---|---|
| 19 | 5 | 0 | 0 |

**Gap 분포**

| COVERED | PARTIAL | NEW |
|---|---|---|
| 11 | 5 | 8 |

**모든 TC 공통 Preconditions**
- `conftest.py` 의 `_isolate_cwd` 로 cwd 가 `tmp_path` 에 고정된다.
- 사용자의 실제 `~/.claude` / `~/.axt` / `~/.config/axt` 를 읽거나 쓰지 않는다 —
  `monkeypatch.setattr("axt.PATHS", axt.Paths(...))`, `monkeypatch.setattr("axt.AXT_CONFIG_PATH", ...)`,
  `_onboarded_marker_path` monkeypatch 로 전부 `tmp_path` 하위로 유도한다.
- `launch_tui` 는 명시적으로 검증하는 TC 를 제외하고 항상 스텁한다.
- 문자열을 단언하는 TC 는 `monkeypatch.setenv("NO_COLOR", "1")`.

---

## 1. 엔트리포인트

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-SMOKE-001 | SC-SMOKE-001 | 콘솔 스크립트 선언이 존재한다 | 저장소 루트를 `Path(axt.__file__).parent.parent` 로 해석 | `pyproject.toml` 파싱 | `[project.scripts]` 에 `axt = "axt:main"` 존재 | Critical | US-SYS01 AC1 | NEW |
| TC-SMOKE-002 | SC-SMOKE-001 | `axt:main` 이 패키지 최상위에서 해석된다 | 공통 | `getattr(axt, "main")` | 호출 가능한 함수 | Critical | US-SYS01 AC1 | PARTIAL — `test_cli.py` 가 `axt.main` 을 광범위하게 쓰지만 진입점 해석 자체를 단언하는 TC 는 없음 |
| TC-SMOKE-003 | SC-SMOKE-001 | `python -m axt` 가 같은 `main()` 으로 들어간다 | `launch_tui` 스텁, `sys.argv = ["axt"]` | `runpy.run_module("axt", run_name="__main__")` | `SystemExit.code == 0` | Critical | US-SYS01 AC1 | COVERED `test_cli.py::test_smoke_dunder_main_entry` |
| TC-SMOKE-004 | SC-SMOKE-001 | 인자 0개 호출이 TUI 를 1회 연다 | `launch_tui` 스텁(호출 카운트) | `main([])` | exit 0, 호출 횟수 1 | Critical | US-SYS01 AC2 | COVERED `test_cli.py::test_no_args_invokes_tui` |

## 2. 버전 동기화

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-SMOKE-005 | SC-SMOKE-002 | 4곳의 버전 리터럴이 서로 같다 | 저장소 루트 해석 | `pyproject.toml`(`^version = "..."`), `axt/__init__.py`, `axt/core.py`, `axt/tui/widgets.py`(각 `^__version__ = "..."`) | 4개 값이 모두 동일. 다르면 어느 파일이 어긋났는지 dict 로 보고 | Critical | US-SYS01 AC4 | COVERED `test_cli.py::test_version_string_is_declared_once_per_place_and_they_agree` |
| TC-SMOKE-006 | SC-SMOKE-002 | 리터럴이 `axt.__version__` 과 같다 | 동상 | `axt.__version__` | `axt/__init__.py` 의 리터럴과 일치 | Critical | US-SYS01 AC4 | COVERED (동일 테스트) |
| TC-SMOKE-007 | SC-SMOKE-002 | `--version` stdout 이 그 값을 낸다 | `NO_COLOR` | `main(["--version"])` | `SystemExit.code == 0`, stdout 에 `axt {__version__}` | Critical | US-SYS01 AC4 | COVERED `test_cli.py::test_version_flag` |
| TC-SMOKE-008 | SC-SMOKE-002 | 리터럴이 하나라도 없으면 명시적 실패 | 동상 | 정규식 매칭 결과 | 매칭 실패 시 `"{파일}: no version literal found"` 로 즉시 실패 | High | US-SYS01 AC4 | COVERED (동일 테스트) |

## 3. 파서 트리

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-SMOKE-009 | SC-SMOKE-003 | `--help` 는 exit 0 | `NO_COLOR` | `main(["--help"])` | `SystemExit.code == 0` | Critical | US-SYS01 AC3 | COVERED `test_cli.py::test_help_flag_lists_subcommands` |
| TC-SMOKE-010 | SC-SMOKE-003 | 12개 명령 그룹이 모두 노출 | 동상 | 동상 | stdout 에 `tui`·`context`·`market`·`mcp`·`hook`·`plan`·`plugin`·`project`·`skill`·`usage`·`vault`·`update` 전부 | Critical | US-SYS01 AC3 | PARTIAL — 기존 테스트는 9개만 확인(`hook`·`update`·`tui` 누락) |
| TC-SMOKE-011 | SC-SMOKE-003 | 리프 서브명령 총합이 41개 | 공통 | `build_parser()` 의 서브파서 트리 순회 | 리프 개수 41 (`FEATURES.md` 집계와 일치). POSIX 기준 — Windows 는 `skill link`/`unlink` 2개가 빠진 39 | Critical | US-SYS01 AC3 | NEW |

## 4. 빈 환경 생존 (읽기 전용)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-SMOKE-012 | SC-SMOKE-004 | 확장 조회 6종이 exit 0 | `PATHS` 를 존재하지 않는 `tmp_path` 하위로 전부 교체, `chdir(tmp_path)` | `market list` / `plugin list` / `skill list` / `mcp list` / `hook list` / `vault list` | 6개 모두 exit 0, 각각 "없음" 안내 출력 | Critical | US-SYS05 AC3 | PARTIAL — `test_cli.py` 에 개별 empty 테스트가 6개 있으나 **`~/.claude` 자체 부재**를 전제로 묶어 도는 smoke TC 는 없음 |
| TC-SMOKE-013 | SC-SMOKE-004 | 사용량·플랜 조회가 exit 0 | 동상 + `AXT_CONFIG_PATH` 교체 | `usage today --timezone UTC` / `plan overview` | 둘 다 exit 0 | Critical | US-USG01 AC3 | COVERED `test_cli.py::test_smoke_usage_and_plan_default_actions` |
| TC-SMOKE-014 | SC-SMOKE-004 | 컨텍스트 분석이 exit 0 | 동상 + `get_claude_version`/`get_git_status` monkeypatch | `context` | exit 0, 고정 소스(system-prompt / user-context)만으로도 표 출력 | Critical | US-SYS05 AC3 | NEW |
| TC-SMOKE-015 | SC-SMOKE-004 | stderr 에 트레이스백이 없다 | 동상 | 위 9개 명령 전부 | stderr 에 `Traceback (most recent call last)` 부재 | Critical | US-SYS05 AC3 | NEW |
| TC-SMOKE-016 | SC-SMOKE-004 | `tmp_path` 밖에 파일을 만들지 않는다 | 동상, 실행 전후 `tmp_path` 외부 경로 스냅샷 | 위 9개 명령 전부 | 실제 `~/.claude`·`~/.axt`·`~/.config/axt` 에 변화 없음 | Critical | US-SYS04 | NEW |

## 5. 빈 환경 생존 (쓰기 계열)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-SMOKE-017 | SC-SMOKE-005 | `project init` 이 프로필을 만든다 | `chdir(tmp_path)` | `project init` → `project status` | exit 0 + `<tmp_path>/.axt-profile.json` 생성, `status` 도 exit 0 | High | US-PRJ01 AC1 | PARTIAL — `test_cli.py::test_project_init_creates_profile` 이 덮지만 `status` 연쇄는 미검증 |
| TC-SMOKE-018 | SC-SMOKE-005 | 글로벌 항목 없는 `vault migrate` | `PATHS(claude_dir=tmp/claude, vault=tmp/vault)`, Windows skip | `vault migrate` | exit 0 + `No extensions found in global paths.` | High | US-VLT01 AC3 | COVERED `test_cli.py::test_vault_migrate_no_globals` |

## 6. TUI 기동/종료

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-SMOKE-019 | SC-SMOKE-006 | 비-TTY 에서 exit 1 + 안내 | TTY 없음(테스트 기본) | `launch_tui()` | exit 1, stderr 에 `TUI failed to start` 또는 curses 안내 | Critical | US-SYS01 AC2 | COVERED `test_cli.py::test_tui_launch_outside_terminal_fails_gracefully` |
| TC-SMOKE-020 | SC-SMOKE-006 | 비-TTY 실패에 트레이스백이 없다 | 동상 | 동상 | stderr 에 `Traceback` 부재 | High | US-SYS01 AC2 | NEW |
| TC-SMOKE-021 | SC-SMOKE-006 | `q` 로 루프가 정상 종료한다 | `curses.wrapper` 스텁 + 키 큐에 `ord("q")` 주입, `PATHS` 격리 | `launch_tui("dark")` | exit 0, 예외 없이 반환 | Critical | US-TUI08 | NEW |

## 7. 최초 실행 온보딩

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-SMOKE-022 | SC-SMOKE-007 | 마커 없음 → 있음 → 삭제 후 다시 없음 | `_onboarded_marker_path` → `tmp_path/onboarded` | `is_first_run()` → `mark_onboarded()` → `is_first_run()` → 마커 삭제 → `is_first_run()` | `True` → `False` → `True`, 마커 파일 실제 생성 | High | US-SYS02 AC1~AC3 | COVERED `test_first_run.py` (3개) |

## 8. 패키징

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-SMOKE-023 | SC-SMOKE-008 | 런타임 의존성이 0개 | 저장소 루트 해석 | `pyproject.toml` 의 `[project] dependencies` | `[]` (빈 리스트). `[project.optional-dependencies]` 는 검사 대상 아님 | Critical | US-SYS07 AC1 | NEW |
| TC-SMOKE-024 | SC-SMOKE-008 | `pricing.json` 이 로드되고 표가 살아 있다 | `reload_pricing_table()` | `axt.core._PRICING_FILE` 존재 + `get_model_pricing("claude-opus-4-8")` | 파일 존재, `package-data` 선언 존재, 단가 `input=5.00 / output=25.00 / cache_write=6.25 / cache_read=0.50` | Critical | US-USG06 AC1 | PARTIAL — 단가 자체는 `test_pricing.py` 가 덮지만 **패키지 데이터 동봉 선언**은 미검증 |

---

## 작성 대상 요약

`NEW` 8건 + `PARTIAL` 5건 = **13건**이 gap-code 단계의 입력이다.
전부 구현 변경 없이 작성 가능하다 — smoke 계층에는 스펙 갭이 없다.

작성 시 주의:
1. `tests/test_smoke.py` 를 신설하고, `test_cli.py` 의 smoke 성격 테스트 4개
   (`test_smoke_usage_and_plan_default_actions`, `test_smoke_dunder_main_entry`,
   `test_version_string_is_declared_once_per_place_and_they_agree`,
   `test_tui_launch_outside_terminal_fails_gracefully`)를 이관할지 먼저 결정한다.
   이관한다면 원본을 반드시 삭제해 **중복 실행이 생기지 않게** 한다.
2. TC-SMOKE-011(리프 41개)은 `FEATURES.md` 의 집계와 `build_parser()` 를 대조하는
   **표-대-표 정합성 검사**다 — `TEST_DEDUP_POLICY.md` §3 의 허용 예외에 해당한다.
   플랫폼에 따라 `skill link`/`unlink` 2개가 빠지므로 `is_symlink_supported()` 로 분기한다.
3. TC-SMOKE-016(홈 오염 검사)은 실제 홈 경로를 **읽기만** 하고 절대 쓰지 않는다.
