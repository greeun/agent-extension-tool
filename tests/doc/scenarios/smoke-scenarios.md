# Smoke 테스트 시나리오 — axt

설치 직후 크리티컬 경로만 본다. **빠르고(전체 2분 이내), 이진 판정(pass/fail)이며, 배포마다 돌린다.**

- **Layer Owner**: 설치 직후 크리티컬 경로 (`TEST_DEDUP_POLICY.md` §2 → `tests/test_smoke.py`)
- **금지**: 도메인 로직·CLI 세부 계약·TUI 상호작용 재검증. 여기서는 "**깔고 나면 켜지는가**" 만 본다
- **결정성**: 사용자의 실제 `~/.claude` / `~/.axt` / `~/.config/axt` 를 **절대 읽거나 쓰지 않는다.**
  모든 시나리오가 `PATHS` / `AXT_CONFIG_PATH` / `HOME` 을 `tmp_path` 로 교체한다
- **ID**: `SC-SMOKE-NNN` / 대응 TC는 `tests/doc/testcases/smoke-testcases.md`

---

### SC-SMOKE-001 — 엔트리포인트가 해석되고 실행된다
- **Objective**: `pip install` 후 등록되는 `axt = "axt:main"` 콘솔 스크립트와 `python3 -m axt` 가 모두 같은 `main()` 으로 들어가고, 인자 없이 호출하면 TUI 를 여는지 검증 (US-SYS01 AC1, AC2)
- **Preconditions**: `launch_tui` 를 monkeypatch 로 스텁 — 헤드리스 환경에서 curses 를 띄우지 않는다. `runpy.run_module("axt", run_name="__main__")` 로 `-m` 경로를 재현한다
- **Steps**: 1) `pyproject.toml` 의 `[project.scripts]` 에 `axt = "axt:main"` 선언 확인 2) `axt.main` 이 호출 가능한지 확인 3) `python -m axt` 재현 4) 인자 0개 호출
- **Expected Result**: 1) 선언 존재, 2) `main` 이 패키지 최상위에서 해석됨, 3) `SystemExit(0)`, 4) `launch_tui` 1회 호출 + exit 0
- **Priority**: Critical

### SC-SMOKE-002 — `--version` 이 패키지 버전과 일치한다
- **Objective**: 버전 리터럴이 4곳(`pyproject.toml`, `axt/__init__.py`, `axt/core.py`, `axt/tui/widgets.py`)에 중복 선언되어 있고 어긋난 채로 릴리스되면 CLI 가 옛 버전을 출력한다. **실제로 그 사고가 있었다.** 4곳이 서로 같고 `--version` 출력과도 같은지 검증 (US-SYS01 AC4)
- **Preconditions**: 저장소 루트를 `Path(axt.__file__).resolve().parent.parent` 로 찾는다. 파일 내용은 정규식으로 읽는다
- **Steps**: 1) 4곳의 리터럴 추출 2) 서로 같은지 비교 3) `axt.__version__` 과 비교 4) `main(["--version"])` 출력과 비교
- **Expected Result**: 4개 리터럴이 모두 동일하고, `axt.__version__` 및 `--version` stdout 과 일치한다. 어느 하나라도 빠지면 명시적 실패 메시지(어느 파일이 어긋났는지)를 낸다
- **Priority**: Critical
- **Note**: `TEST_DEDUP_POLICY.md` §3 이 "상수 검증"을 금지하지만, **서로 다른 곳에 중복 선언된 값의 동기화 검증**은 같은 절에서 명시적으로 허용한 예외다

### SC-SMOKE-003 — `--help` 가 exit 0 이고 모든 명령 그룹을 노출한다
- **Objective**: 파서 트리가 정상적으로 구성되어 12개 명령 그룹이 도움말에 모두 나오는지 검증 — 서브파서 등록 누락은 그 명령 전체가 사라지는 회귀다 (US-SYS01 AC3)
- **Preconditions**: `NO_COLOR=1`. `SystemExit` 을 잡는다
- **Steps**: 1) `main(["--help"])` 2) stdout 에서 명령 그룹 이름 확인 3) `build_parser()` 의 서브파서 리프 개수 세기
- **Expected Result**: exit 0, `tui`·`context`·`market`·`mcp`·`hook`·`plan`·`plugin`·`project`·`skill`·`usage`·`vault`·`update` 12개가 모두 등장. 리프 서브명령 총합이 41개(`FEATURES.md` 집계와 일치)
- **Priority**: Critical

### SC-SMOKE-004 — `~/.claude` 가 없어도 읽기 전용 명령이 살아남는다
- **Objective**: 새 머신·새 계정처럼 Claude 설정이 전혀 없는 상태에서 조회 명령들이 크래시하지 않고 exit 0 + 안내를 내는지 검증 (US-SYS05 AC3)
- **Preconditions**: `PATHS` 를 **존재하지 않는** `tmp_path` 하위 경로로 전부 교체, `AXT_CONFIG_PATH` 도 `tmp_path`, `monkeypatch.chdir(tmp_path)`. `usage` 계열은 `--timezone UTC` 를 명시해 호스트 타임존 의존 제거
- **Steps**: 조회 전용 명령을 순차 실행 — `market list`, `plugin list`, `skill list`, `mcp list`, `hook list`, `vault list`, `usage today`, `plan overview`, `context`
- **Expected Result**: 모두 exit 0, stderr 에 트레이스백 없음, 각각 "없음" 안내 문구 출력. 실행 후 `tmp_path` 밖에는 아무 파일도 생기지 않는다
- **Priority**: Critical

### SC-SMOKE-005 — 상태를 바꾸는 명령이 빈 환경에서도 안전하게 끝난다
- **Objective**: 빈 환경에서 `project init` / `vault migrate` 같은 쓰기 계열 진입점이 예외 없이 종료하고, 예상 위치에만 파일을 만드는지 검증 (US-SYS01, US-VLT01 AC3, US-PRJ01 AC1)
- **Preconditions**: SC-SMOKE-004 와 동일한 격리. Windows 는 symlink 관련 TC 를 skip
- **Steps**: 1) `project init` 2) `project status` 3) `vault migrate` (글로벌 항목 없음)
- **Expected Result**: 1) exit 0 + `<cwd>/.axt-profile.json` 생성, 2) exit 0, 3) exit 0 + `No extensions found in global paths.`
- **Priority**: High

### SC-SMOKE-006 — TUI 가 기동하고 깨끗이 종료한다
- **Objective**: curses 를 초기화할 수 없는 환경(CI·파이프)에서 트레이스백 대신 exit 1 + 안내로 끝나고, 초기화 가능한 상황에서는 `q` 로 정상 종료하는지 검증 (US-SYS01 AC2, US-TUI10)
- **Preconditions**: 헤드리스 실행 — 실제 TTY 없음. 정상 종료 경로는 `curses.wrapper` 를 스텁하고 키 큐에 `q` 를 넣어 재현한다
- **Steps**: 1) `launch_tui()` 직접 호출(비-TTY) 2) `wrapper` 스텁 + `q` 입력으로 루프 1회 진입/종료
- **Expected Result**: 1) exit 1 + stderr 안내, 트레이스백 없음, 2) exit 0 + 루프가 예외 없이 반환
- **Priority**: Critical

### SC-SMOKE-007 — 최초 실행 온보딩이 1회만 뜨고 마커를 남긴다
- **Objective**: 신규 사용자가 처음 `axt` 를 켤 때 안내가 1회 표시되고 `<AXT_CONFIG_DIR>/onboarded` 마커가 생겨 두 번째부터는 뜨지 않는지 검증 (US-SYS02 AC1~AC3)
- **Preconditions**: `_onboarded_marker_path` 를 `tmp_path` 로 monkeypatch — 사용자 홈 오염 금지
- **Steps**: 1) 마커 없는 상태에서 `is_first_run()` 2) `mark_onboarded()` 3) 재확인 4) 마커 삭제 후 재확인
- **Expected Result**: `True` → 마커 생성 → `False` → `True`. 마커 쓰기 실패는 예외 없이 삼켜진다
- **Priority**: High

### SC-SMOKE-008 — 런타임 의존성이 0개이고 패키지 데이터가 동봉된다
- **Objective**: 순수 stdlib 원칙이 지켜지는지와, `pricing.json` 이 패키지 데이터로 실제 설치 트리에 들어가 로드되는지 검증 — 패키징 실수는 설치 후에만 드러난다 (US-SYS07 AC1, US-USG06)
- **Preconditions**: `pyproject.toml` 을 파싱해 `[project] dependencies` 를 읽는다. `pricing.json` 은 `axt.core._PRICING_FILE` 경로로 확인
- **Steps**: 1) `dependencies == []` 확인 2) `package-data` 에 `pricing.json` 선언 확인 3) `_PRICING_FILE` 존재 확인 4) `reload_pricing_table()` 후 `get_model_pricing("claude-opus-4-8")` 5) `axt` 및 하위 모듈이 서드파티를 import 하지 않는지 확인
- **Expected Result**: 1) 빈 리스트, 2)·3) 파일 존재, 4) `input=5.00 / output=25.00 / cache_write=6.25 / cache_read=0.50`, 5) `yaml`·`requests` 등 서드파티 import 없음
- **Priority**: Critical

---

## 계층 경계 메모

smoke 는 "켜지는가" 만 본다. 아래는 여기서 **검증하지 않는다**.

| 항목 | 소유 계층 |
|---|---|
| 개별 명령의 exit code·출력 형태 | api |
| 도메인 계산·파싱 규칙 | unit |
| TUI 키 입력 → 상태 전이 → 렌더 | e2e |
| 손상 데이터 주입 후 복원력 | chaos |
| 기동 시간·응답 시간 | performance |

## 파일 배치

`TEST_DEDUP_POLICY.md` §2 는 smoke 를 `tests/test_smoke.py` 에 두라고 규정한다. 현재
`tests/test_cli.py` 안의 `# ─── smoke: CLI entrypoints return cleanly on an empty environment ───`
섹션(2개 테스트)과 `test_version_string_is_declared_once_per_place_and_they_agree`,
`test_tui_launch_outside_terminal_fails_gracefully` 가 이 역할을 겸하고 있다.
gap-code 단계에서 **`tests/test_smoke.py` 를 신설하고 위 4개를 이관**할지, 현 위치를 유지할지 결정이 필요하다.
이관 시에는 중복 실행이 생기지 않도록 원본을 반드시 제거한다.
