# Chaos 테스트 케이스

Layer Owner: `tests/test_chaos.py`
시나리오 출처: [chaos-scenarios.md](../scenarios/chaos-scenarios.md)

> **공통 성공 기준**: 한 항목의 결함이 나머지 전체를 못 쓰게 만들지 않는다 (`US-SYS05` AC4).
> **결정성**: 모든 픽스처는 `tmp_path` 안이며 실제 `~/.claude` 를 손상시키는 TC는 0건이다.
> 권한 TC는 `os.getuid() == 0` 이면 조용히 skip 하지 않고 **환경 오류로 실패**시킨다(허위 통과 방지).
> 스레드 TC는 `threading.excepthook` 을 가로채 스레드 밖으로 샌 예외를 기록한다 —
> 기본 훅은 stderr 에만 찍고 테스트를 통과시켜 버린다.

## 요약

| 항목 | 값 |
|---|---|
| **총 TC 수** | **26** (COVERED 2 제외 → 신규·보강 대상 24건. 종전 BLOCKED 1건은 SD-001 로 해소) |
| 우선순위 | Critical 12 / High 12 / Medium 2 / Low 0 |
| Gap | COVERED 2 / PARTIAL 6 / NEW 18 |
| 실패 예상 TC | 8 (TC-CHAOS-002 · 003 · 004 · 005 · 010 · 011 · 012 · 024) — 구현 갭 |
| BLOCKED | 0 — TC-CHAOS-018 은 SD-001 결정으로 해제됨 (`tests/doc/SPEC_DECISIONS.md`) |

## TC 인덱스

| TC ID | 시나리오 | 제목 | US | 우선순위 | Gap |
|---|---|---|---|---|---|
| TC-CHAOS-001 | SC-CHAOS-001 | 최상위가 문자열인 settings 가 빈 맵이 된다 | US-SYS05 AC1 | High | COVERED |
| TC-CHAOS-002 | SC-CHAOS-001 | 잘린 settings JSON 이 빈 맵으로 fallback 된다 | US-SYS05 AC1 | Critical | NEW |
| TC-CHAOS-003 | SC-CHAOS-001 | 손상된 `installed_plugins.json` 이 빈 목록이 된다 | US-SYS05 AC1 | Critical | NEW |
| TC-CHAOS-004 | SC-CHAOS-001 | 손상된 `known_marketplaces.json` 이 빈 목록이 된다 | US-SYS05 AC1 | Critical | NEW |
| TC-CHAOS-005 | SC-CHAOS-001 | 손상된 `.axt-profile.json` 이 빈 프로필이 된다 | US-SYS05 AC1 | High | NEW |
| TC-CHAOS-006 | SC-CHAOS-001 | 손상된 usage 캐시가 재빌드로 복구된다 | US-USG08 AC3 | High | PARTIAL |
| TC-CHAOS-007 | SC-CHAOS-002 | broken 심볼릭 링크가 migrate에서 이동되지 않고 리포트된다 | US-VLT01 AC2 | Critical | COVERED |
| TC-CHAOS-008 | SC-CHAOS-002 | broken 이 있어도 정상 항목은 계속 이동된다 | US-VLT01 AC3 | High | NEW |
| TC-CHAOS-009 | SC-CHAOS-003 | `~/.claude` 부재 상태에서 10개 읽기 명령이 모두 exit 0 이다 | US-SYS05 AC3 | Critical | PARTIAL |
| TC-CHAOS-010 | SC-CHAOS-003 | 읽기 명령이 디렉터리를 만들지 않는다 | US-SYS05 AC3 | Medium | NEW |
| TC-CHAOS-011 | SC-CHAOS-004 | 권한 없는 vault 항목만 빠지고 나머지는 열거된다 | US-SYS05 AC4 | Critical | NEW |
| TC-CHAOS-012 | SC-CHAOS-004 | 권한 없는 파일이 컨텍스트 분석을 중단시키지 않는다 | US-SYS05 AC4 | Critical | NEW |
| TC-CHAOS-013 | SC-CHAOS-004 | 권한 없는 프로젝트 디렉터리가 스캔을 중단시키지 않는다 | US-SYS05 AC4 | High | NEW |
| TC-CHAOS-014 | SC-CHAOS-005 | ENOSPC 쓰기 실패 후 원본이 보존된다 | US-SYS04 AC3 | Critical | NEW |
| TC-CHAOS-015 | SC-CHAOS-005 | `os.replace` 실패 후 tmp 잔여물이 없다 | US-SYS04 AC3 | High | NEW |
| TC-CHAOS-016 | SC-CHAOS-005 | 직렬화 불가 값이 원본을 지우지 않는다 | US-SYS04 AC3 | High | NEW |
| TC-CHAOS-017 | SC-CHAOS-006 | git 부재 시 `market list` 가 exit 0 으로 목록을 낸다 | US-MKT03 AC2 | High | PARTIAL |
| TC-CHAOS-018 | SC-CHAOS-007 | dirty 트리에서도 upstream 정렬에 성공하고 실패 시 레지스트리가 무손상이다 | US-MKT05 AC1·AC3 | Critical | NEW |
| TC-CHAOS-019 | SC-CHAOS-006 | git 부재 시 `market sync` 가 traceback 없이 exit 1 이다 | US-SYS06 AC2 | High | NEW |
| TC-CHAOS-020 | SC-CHAOS-007 | fetch 네트워크 실패가 작업트리와 레지스트리를 건드리지 않는다 | US-MKT02 AC4 | Critical | PARTIAL |
| TC-CHAOS-021 | SC-CHAOS-008 | `claude` 부재 시 dry-run 리포트가 완성된다 | US-UPD02 AC2 | High | PARTIAL |
| TC-CHAOS-022 | SC-CHAOS-008 | `claude` 부재 시 `--apply` 가 안내로 끝나고 `--json` 이 유효하다 | US-UPD03 AC2 | High | NEW |
| TC-CHAOS-023 | SC-CHAOS-009 | 세 워커의 예외가 로딩 플래그를 영구 True 로 남기지 않는다 | US-UPD05 AC4 | Critical | PARTIAL |
| TC-CHAOS-024 | SC-CHAOS-009 | 워커 실패가 사용자에게 드러난다 | US-UPD05 AC4 | Critical | NEW |
| TC-CHAOS-025 | SC-CHAOS-010 | 4단계 리사이즈 시퀀스에서 예외가 없다 | US-TUI10 AC2 | High | NEW |
| TC-CHAOS-026 | SC-CHAOS-010 | 검색 입력 중 리사이즈가 버퍼를 보존한다 | US-TUI10 AC2 | Medium | NEW |

---

## SC-CHAOS-001 — 손상된 JSON

### TC-CHAOS-001 — 최상위가 문자열인 settings 가 빈 맵이 된다

- **US**: US-SYS05 AC1 / **Priority**: High / **Gap**: **COVERED**
  (`tests/test_settings.py::test_read_enabled_plugins_corrupt_file`) — 참조만 한다.

### TC-CHAOS-002 — 잘린 settings JSON 이 빈 맵으로 fallback 된다

- **US**: US-SYS05 AC1 / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**: `settings.json` 내용 `'{"enabledPlugins": {"alpha": tr'` (다른 프로세스가 쓰다 죽은 형태)
- **Input**: `axt.read_enabled_plugins(settings_path)`
- **Expected Output**
  - 반환값 `{}`
  - 예외 0건
  - 이어서 `set_plugin_enabled(path, "beta", True)` 가 성공하고 결과가 `{"enabledPlugins": {"beta": True}}`
    (손상 파일이 이후 쓰기를 막지 않는다)
- **현재 구현 예상 결과**: `read_json` 이 `json.JSONDecodeError` 를 잡지 않아 예외가 전파된다. **실패 예상.**
- **실패 시 조치**: `read_json` 에 `except (json.JSONDecodeError, UnicodeDecodeError)` → `fallback` 반환을 추가.
  `fallback` 이 주어지지 않은 호출에서만 재전파한다.
- **왜 중요한가**: `read_json_dict` 는 axt 전역의 JSON 진입점이다. 여기 한 곳을 고치면
  TC-CHAOS-003·004·005 가 함께 통과한다 — 즉 이 TC 하나가 결함군 전체의 근본 원인을 가리킨다.

### TC-CHAOS-003 — 손상된 `installed_plugins.json` 이 빈 목록이 된다

- **US**: US-SYS05 AC1 / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**: 3가지 손상 형태를 각각 주입 — (a) `'{"version": 2, "plugins":'`, (b) 빈 파일, (c) `'not json at all'`
- **Input**: `axt.list_installed_plugins(ip_path, km_path)`
- **Expected Output**
  - 세 경우 모두 `[]`
  - 예외 0건
  - TUI Plugins 서브탭이 이 상태에서 렌더되고 빈 상태 안내를 표시한다 (US-TUI06 AC1)
- **비고**: 빈 파일은 `json.load` 가 `JSONDecodeError("Expecting value")` 를 던지므로 (a)·(c) 와 같은 경로다.
  세 형태를 모두 두는 이유는 실제 손상이 어느 형태로든 오기 때문이다.

### TC-CHAOS-004 — 손상된 `known_marketplaces.json` 이 빈 목록이 된다

- **US**: US-SYS05 AC1 / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**: `known_marketplaces.json` 내용 `'{"mine": {"source":'`
- **Steps**
  1. `axt.list_marketplaces(km_path)`
  2. `axt.main(["market", "list"])`
  3. TUI Market 서브탭 렌더 (`_ensure_subtab_loaded`)
- **Expected Output**
  - 1: `[]`, 예외 없음
  - 2: exit 0 + 빈 목록 안내 (US-MKT03 AC2 — "버전을 못 구해도 목록 출력은 실패하지 않는다"의 확장)
  - 3: **TUI가 죽지 않는다** — 이것이 이 TC의 핵심이다.
    현재 `_ensure_subtab_loaded` 는 `list_marketplaces` 를 감싸지 않아 예외가 메인 루프까지 올라간다
- **실패 시 조치**: `read_json` 수정(TC-CHAOS-002)으로 근본 해결하거나,
  `_ensure_subtab_loaded` 를 항목별 try 로 감싸 실패한 서브탭만 빈 목록 + 오류 상태로 표시한다

### TC-CHAOS-005 — 손상된 `.axt-profile.json` 이 빈 프로필이 된다

- **US**: US-SYS05 AC1 / **Priority**: High / **Gap**: NEW / **실패 예상**
- **Preconditions**: 프로젝트 루트에 손상된 `.axt-profile.json` (`'{"skills": ['`)
- **Steps**
  1. `axt.read_profile(project_dir)`
  2. `axt.main(["project", "status"])`
  3. `axt.main(["project", "sync"])`
- **Expected Output**
  - 1: 빈 프로필(또는 `None`) 반환, 예외 없음
  - 2: exit 0. `status` 는 파일시스템을 변경하지 않는다 (US-PRJ04 AC1)
  - 3: 손상 프로필을 "빈 프로필"로 해석해 실제 링크를 정리하기보다는,
    **파괴적 동작을 하지 않고 사용자에게 알린다** — 손상된 프로필을 빈 것으로 오해해
    모든 링크를 제거하면 데이터 손실이다
- **비고**: 3단계의 기대값은 스토리에 명시가 없다(US-PRJ03 AC2 는 "프로필에 없는데 있는 링크는 제거한다").
  손상과 "비어 있음"을 구별해야 한다는 것이 이 TC의 주장이다. `## 스펙 갭` 참조.

### TC-CHAOS-006 — 손상된 usage 캐시가 재빌드로 복구된다

- **US**: US-USG08 AC3 / **Priority**: High / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_update.py::test_update_status_cache_missing_or_corrupt` 가
  **update-status 캐시**를 덮는다. **usage 캐시**(`cache/claude-usage.json`)의 손상 복구는 미검증이며,
  이쪽은 v1↔v2 스키마 전환 로직까지 얽혀 있어 경로가 다르다.
- **Preconditions**
  - 정상 세션 파일 5개 (`tmp_path/"projects"`)
  - 손상 캐시 3형태를 각각 주입: (a) 잘린 JSON, (b) `{"version": 1, …}` (구 스키마), (c) `projectsDir` 가 다른 경로
- **Steps**: 각 상태에서 `load_all_claude_usage(projects_dir)` 호출
- **Expected Output**
  - 세 경우 모두 정상 엔트리를 돌려준다(재빌드 성공)
  - 예외 0건
  - 호출 후 캐시 파일이 `version: 2` 이고 `projectsDir` 가 현재 경로로 갱신된다
  - (b) 의 v1 데이터가 **결과에 섞이지 않는다** — 폐기 후 재빌드 (US-USG08 AC2)

---

## SC-CHAOS-002 — 깨진 심볼릭 링크

### TC-CHAOS-007 — broken 심볼릭 링크가 migrate에서 이동되지 않고 리포트된다

- **US**: US-VLT01 AC2 / **Priority**: Critical / **Gap**: **COVERED**
  (`tests/test_vault.py::test_migrate_reports_broken_symlink_not_skipped`,
  `tests/test_vault.py::test_find_broken_links`,
  `tests/test_tui.py::test_render_vault_tab_broken_symlink_warning_uses_err_bold`) — 참조만 한다.

### TC-CHAOS-008 — broken 이 있어도 정상 항목은 계속 이동된다

- **US**: US-VLT01 AC3 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - `~/.claude/skills` 에 정상 디렉터리 2개 + broken 심볼릭 링크 1개
  - `~/.claude/commands` 에 정상 `.md` 2개 + broken 심볼릭 링크 1개
  - 이미 vault 에 있는 항목 1개(skipped 대조군)
- **Input**: `axt.migrate_to_vault(claude_dir, vault_dir)`
- **Expected Output**
  - `moved` 4건, `broken` 2건, `skipped` 1건, `errors` 0건
  - broken 심볼릭 링크 2개가 **디스크에 그대로 존재**한다
  - 이동된 4건이 vault 에 실체로 있고, 원위치에 vault 를 가리키는 심볼릭 링크가 남아 있다 (US-VLT01 AC1)
- **왜 필요한가**: 기존 테스트는 broken 1건만 있는 상황을 본다. "결함이 나머지를 막지 않는다"는
  이 도메인의 핵심 계약은 **정상 항목과 결함 항목이 섞였을 때**만 검증된다.

---

## SC-CHAOS-003 — `~/.claude` 부재

### TC-CHAOS-009 — `~/.claude` 부재 상태에서 10개 읽기 명령이 모두 exit 0 이다

- **US**: US-SYS05 AC3 / **Priority**: Critical / **Gap**: **PARTIAL**
- **PARTIAL 사유**: 개별 함수 수준의 missing-dir 테스트는 존재한다
  (`test_list_skills_missing_dir`, `test_scan_project_usage_missing_dir`,
  `test_load_all_claude_usage_missing_dir`). **CLI 전면 스윕**은 미검증이며,
  신규 사용자의 첫 실행 경로가 바로 이 상황이다.
- **Preconditions**
  - `HOME` 을 완전히 빈 `tmp_path` 로 지정. `~/.claude`, `~/.axt`, `~/.config/axt` 모두 없음
  - `monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)`
  - `monkeypatch.chdir(tmp_path/"emptyproj")` (git 저장소도 아님)
  - `subprocess.run` 은 그대로 두되 `git status` 는 저장소가 아니므로 실패한다 — 그 경로도 함께 태운다
- **Input**: 다음 10개 명령을 순서대로 실행
  `plugin list` / `skill list` / `mcp list` / `hook list` / `market list` /
  `vault list` / `usage today` / `context` / `project status` / `update`
- **Expected Output**
  - 10개 모두 반환값 `0`
  - stderr 에 `Traceback` 문자열이 0회
  - 각 stdout 에 빈 상태임을 알리는 텍스트가 있다
- **금지**: 10개 명령을 각각 별도 TC 로 쪼개지 않는다(정책 §3 "반복 패턴" — 공통 계층 1회 + 대표로 충분).
  하나의 파라미터화 TC 로 작성하고, 실패 시 어느 명령인지 메시지에 담는다.

### TC-CHAOS-010 — 읽기 명령이 디렉터리를 만들지 않는다

- **US**: US-SYS05 AC3 / **Priority**: Medium / **Gap**: NEW / **실패 예상**
- **Preconditions**: TC-CHAOS-009 와 동일한 빈 HOME
- **Steps**
  1. 실행 전 `set(tmp_path.rglob("*"))` 스냅샷
  2. 10개 읽기 명령 실행
  3. 실행 후 스냅샷
- **Expected Output**
  - 차집합이 공집합 — 조회가 파일시스템에 부작용을 남기지 않는다
  - 예외: TUI 실행 시의 `~/.config/axt/onboarded` 마커는 대상이 아니다(읽기 CLI 가 아님)
- **현재 구현 예상 결과**: `update` 가 상태 캐시를 쓰거나, `usage` 가 캐시 디렉터리를 만들 가능성이 있다.
  실패하면 **어느 명령이 무엇을 만들었는지**가 곧 결정 사항이다 —
  캐시 생성이 의도된 것이라면 스토리에 AC 로 명시하고 이 TC 의 허용 목록에 넣는다.

---

## SC-CHAOS-004 — 권한 거부

### TC-CHAOS-011 — 권한 없는 vault 항목만 빠지고 나머지는 열거된다

- **US**: US-SYS05 AC4 / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**
  - `if os.getuid() == 0: pytest.fail("root 로 실행하면 chmod 결함 주입이 무력하다 — 비-root 로 실행할 것")`
    (skip 이 아니라 **실패**로 드러낸다 — 조용한 skip 은 허위 통과다)
  - vault skill 5개 생성 후 그중 1개 디렉터리를 `os.chmod(d, 0o000)`
  - `try/finally` 로 teardown 에서 `0o755` 복구 (복구 안 하면 `tmp_path` 정리가 실패한다)
- **Input**: `axt.list_vault_items(vault_dir)`
- **Expected Output**
  - 예외 0건
  - 반환 항목 수 == 4 (접근 가능한 것만) 또는 5(이름은 보이되 설명이 비는 형태)
    — **둘 중 무엇이든 0건이 아니어야 한다**
  - `axt.main(["vault", "list"])` 가 exit 0
- **왜 이 단언 형태인가**: 스토리는 "해당 항목만 실패로 처리하고 나머지를 계속 처리한다"까지만 정한다.
  누락할지 부분 표시할지는 구현 자유이므로, 단언은 **나머지가 살아남는다**에 건다.
  "정확히 4건" 으로 못 박으면 스펙에 없는 것을 강제하게 된다.

### TC-CHAOS-012 — 권한 없는 파일이 컨텍스트 분석을 중단시키지 않는다

- **US**: US-SYS05 AC4 / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**
  - root 가드는 TC-CHAOS-011 과 동일
  - `.claude/skills` 10개 중 1개의 `SKILL.md` 를 `0o000`
  - `.claude/commands` 5개 중 1개의 `.md` 를 `0o000`
  - `git status` 는 고정 스텁으로 교체
- **Input**: `collect_context_sources(home_dir=home, project_dir=proj, installed_plugins_path=ip)`
- **Expected Output**
  - 예외 0건
  - skills 카테고리 소스 수 ≥ 9, commands ≥ 4 — 접근 가능한 항목이 모두 집계된다
  - 접근 불가 항목이 포함된다면 토큰 추정이 0이고, 제외된다면 아예 없다. 어느 쪽이든 **전체가 0건이 아니다**
  - `axt.main(["context"])` 가 exit 0

### TC-CHAOS-013 — 권한 없는 프로젝트 디렉터리가 스캔을 중단시키지 않는다

- **US**: US-SYS05 AC4 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - root 가드 동일
  - `projects_dir` 에 프로젝트 10개, 그중 1개를 `0o000`
  - vault 항목 5개
- **Input**: `scan_project_usage(projects_dir, vault_dir, mode="default")` 및 `mode="full"`
- **Expected Output**
  - 두 모드 모두 예외 0건
  - 접근 가능한 9개 프로젝트의 사용 정보가 인덱스에 반영된다
  - 인덱스 항목 수 == 5 (vault 항목 수는 프로젝트 접근성과 무관)

---

## SC-CHAOS-005 — 쓰기 실패

### TC-CHAOS-014 — ENOSPC 쓰기 실패 후 원본이 보존된다

- **US**: US-SYS04 AC3 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `target = tmp_path/"settings.json"` 에 `{"keep": "original"}` 기록
  - `json.dump` 이 `OSError(errno.ENOSPC, "No space left on device")` 를 던지게 monkeypatch
    (`monkeypatch.setattr("axt.core.json.dump", boom)` — 모듈 경로를 명시해 전역 오염 방지)
- **Input**: `axt.write_json_atomic(target, {"new": "data"})`
- **Expected Output**
  - `OSError` 가 호출자에게 전달된다 — **삼키지 않는다**
    (쓰기 실패를 성공으로 보고하면 사용자가 설정이 저장된 줄 안다)
  - `json.loads(target.read_text()) == {"keep": "original"}`
  - `list(tmp_path.glob(".tmp-*.json")) == []` (`finally` 정리 동작)
  - `.bak` 이 있다면 내용이 `{"keep": "original"}`

### TC-CHAOS-015 — `os.replace` 실패 후 tmp 잔여물이 없다

- **US**: US-SYS04 AC3 / **Priority**: High / **Gap**: NEW
- **Preconditions**: `os.replace` 가 `OSError(errno.EROFS, "Read-only file system")` 을 던지게 monkeypatch
- **Expected Output**
  - `OSError` 전달
  - 원본 내용 보존
  - `.tmp-*.json` 잔여물 0개 — tmp 파일이 쌓이면 홈 디렉터리가 서서히 오염된다
  - 재시도(정상 상태로 복구 후 같은 호출)가 성공한다

### TC-CHAOS-016 — 직렬화 불가 값이 원본을 지우지 않는다

- **US**: US-SYS04 AC3 / **Priority**: High / **Gap**: NEW
- **Input**: `axt.write_json_atomic(target, {"x": object()})`
- **Expected Output**
  - `TypeError` 전달
  - 원본 내용 `{"keep": "original"}` 보존
  - `.tmp-*.json` 잔여물 0개
- **왜 필요한가**: 앞의 두 TC는 I/O 실패를, 이 TC는 **직렬화 도중 실패**를 본다.
  tmp 파일이 이미 열려 부분 기록된 뒤 예외가 나는 경로라서 정리 로직이 다르게 동작한다.

---

## SC-CHAOS-006 · 007 — 외부 git

### TC-CHAOS-017 — git 부재 시 `market list` 가 exit 0 으로 목록을 낸다

- **US**: US-MKT03 AC2 / **Priority**: High / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_marketplace.py::test_git_binary_missing_returns_127` 이
  `_git` 헬퍼 수준을 덮는다. 그 127 이 **CLI 계약(exit 0 + 목록 출력)** 으로 이어지는지는 미검증.
- **Preconditions**
  - `subprocess.run` 이 `FileNotFoundError("git")` 를 던지게 monkeypatch
  - 등록 마켓 3개: github 2개(git 필요) + directory 1개(git 불필요)
- **Input**: `axt.main(["market", "list"])`
- **Expected Output**
  - 반환값 `0`
  - 3개 마켓이 모두 출력된다
  - github 마켓의 버전이 `?` 등으로 표시되고 traceback 이 없다
  - directory 마켓의 버전은 `local` 로 **정상 표시**된다 — git 부재가 무관한 항목까지 망치지 않는다

### TC-CHAOS-018 — dirty 트리에서도 upstream 정렬에 성공하고 실패 시 레지스트리가 무손상이다

- **US**: US-MKT05 AC1·AC2·AC3 / **Priority**: Critical / **Gap**: NEW
- **결정 근거**: `tests/doc/SPEC_DECISIONS.md` SD-001. 설치 디렉터리는 사용자 작업 공간이
  아니라 관리 대상 캐시이며, 커밋되지 않은 로컬 수정은 업데이터 산출물로 간주해 폐기된다.
  (원래 스토리는 낡은 `FEATURES.md` 기술에서 파생돼 반대로 적혀 있었다.)
- **Preconditions**
  - `tmp_path` 에 로컬 origin 저장소와 그 clone(install) 구성, 둘 다 `user.email`/`user.name` 설정
  - `PATHS.known_marketplaces = tmp_path/"km.json"` 에 해당 마켓이 git 소스로 등록
  - `sys.platform != "win32"` 불필요 (git만 있으면 됨)
- **Input / Steps**
  1. origin 을 `v2` 로 진행시킨다
  2. install 트리를 커밋 없이 더럽힌다: `f.txt` ← `"overwritten-in-place"`
  3. `axt.sync_marketplace(km_path, name)` 호출
- **Expected Output**
  - 반환 `SyncMarketplaceResult.updated is True`, `before != after`
  - `install/f.txt` 내용 == `"v2\n"` (업데이터 산출물이 폐기되고 upstream 에 정렬됨)
  - `known_marketplaces.json` 의 해당 항목에 `lastUpdated` 가 갱신됨
- **대조군 (같은 TC 안에서 함께 확인)**
  - `git fetch` 를 실패(exit≠0)하도록 주입하면 `RuntimeError` 가 오르고,
    `install/f.txt` 는 더럽혀진 상태 그대로이며 `known_marketplaces.json` 은 **변경되지 않는다**
    (실패한 sync 가 레지스트리를 건드리지 않는다 — US-MKT05 AC3)
- **비고**: 성공 경로는 `test_sync_marketplace_git_dirty_tree_hard_syncs` 가 이미 덮는다.
  이 TC 의 신규 가치는 **실패 경로의 레지스트리 무손상** 이므로 그쪽에 무게를 둔다.

### TC-CHAOS-019 — git 부재 시 `market sync` 가 traceback 없이 exit 1 이다

- **US**: US-SYS06 AC2 / **Priority**: High / **Gap**: NEW
- **Preconditions**: TC-CHAOS-017 과 동일한 `FileNotFoundError` 주입
- **Input**: `axt.main(["market", "sync", "gh-market"])`
- **Expected Output**
  - 반환값 `1`
  - stderr 에 `✗` 로 시작하는 한 줄이 있고 `git` 이 없다는 취지가 담긴다
  - stderr 에 `Traceback` 문자열이 없다
  - `known_marketplaces.json` 이 변경되지 않는다(실패한 sync 가 레지스트리를 건드리지 않는다)
- **비고**: `directory` 소스 마켓에 대한 sync 는 git 이 필요 없으므로 같은 주입 상태에서 **exit 0** 이어야 한다.
  같은 TC 안에서 대조군으로 함께 확인한다.

### TC-CHAOS-020 — fetch 네트워크 실패가 작업트리와 레지스트리를 건드리지 않는다

- **US**: US-MKT02 AC4 / **Priority**: Critical / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_marketplace.py::test_sync_marketplace_git_fetch_failure` 와
  `tests/test_update.py::test_git_updater_absorbs_fetch_failure` 가 실패 보고를 덮는다.
  **작업트리·레지스트리 무손상**은 미검증 — 실패 경로가 중간까지 진행했다가 멈추면 그때 손상이 난다.
- **Preconditions**
  - 실제 로컬 git 저장소 origin↔clone 을 `tmp_path` 에 구성 (네트워크 없음)
  - `_git` 을 감싸서 `fetch` 호출만 `(128, "", "fatal: Could not resolve host: github.com")` 을 돌려주게 한다.
    나머지 git 명령은 실제로 실행되게 둔다(부분 실패 재현)
  - 실행 전 clone 의 파일 목록·내용과 `known_marketplaces.json` 내용을 스냅샷
- **Input**: `axt.sync_marketplace(km_path, "x")`
- **Expected Output**
  - `RuntimeError` 발생, 메시지에 `git fetch failed` 와 원본 stderr 내용이 포함된다 (US-SYS06 AC1)
  - clone 디렉터리의 파일 목록·내용이 스냅샷과 동일
  - `known_marketplaces.json` 이 스냅샷과 바이트 단위로 동일
  - `HEAD` 커밋이 변하지 않는다

---

## SC-CHAOS-008 — `claude` 바이너리 부재

### TC-CHAOS-021 — `claude` 부재 시 dry-run 리포트가 완성된다

- **US**: US-UPD02 AC2 / **Priority**: High / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_update.py::test_claude_code_check_and_apply` 는 **정상 경로**만 덮는다.
  `_claude_version()` 이 `None` 을 돌려주는 부재 경로가 CLI 리포트 전체에 미치는 영향은 미검증.
- **Preconditions**
  - `axt.update._claude_version` 이 `None` 을 돌려주게 monkeypatch (내부적으로는 `FileNotFoundError` 경로)
  - Tier-1 항목(플러그인 1개, 마켓 1개)을 정상 상태로 준비하고 각 updater 는 고정 스텁
- **Input**: `axt.main(["update"])`
- **Expected Output**
  - 반환값 `0` (dry-run 은 아무것도 변경하지 않는다 — US-UPD01 AC1)
  - `claude-code` 항목이 `error="claude not found on PATH"` 취지로 리포트된다
  - Tier-1 두 항목의 리포트가 **정상적으로 완성**된다 — 한 티어의 실패가 다른 티어를 막지 않는다
  - 마지막 요약 라인이 출력된다 (US-UPD01 AC3)

### TC-CHAOS-022 — `claude` 부재 시 `--apply` 가 안내로 끝나고 `--json` 이 유효하다

- **US**: US-UPD03 AC2 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - `axt.update._run_claude_update` 가 `(127, "", "No such file or directory: 'claude'")` 를 돌려주게 한다
  - `--json` 경로는 확인 프롬프트를 띄우지 않아야 하므로, 프롬프트 함수가 호출되면 실패하도록 스파이를 건다
- **Steps**
  1. `axt.main(["update", "claude-code", "--apply", "-y"])`
  2. `axt.main(["update", "--json"])`
- **Expected Output**
  - 1: 반환값 `1`, stdout/stderr 에 설치 안내가 있고 traceback 이 없다
  - 2: 반환값 `0`, 출력이 `json.loads` 로 파싱되고 ANSI 이스케이프(`\x1b[`)가 섞이지 않는다
  - 2: 프롬프트 스파이 호출 0회 (US-UPD03 AC1)
  - 2: JSON 안에 `claude-code` 항목의 상태가 기계 판독 가능한 필드로 담긴다 (US-UPD03 AC3)

---

## SC-CHAOS-009 — 백그라운드 스레드 결함

### TC-CHAOS-023 — 세 워커의 예외가 로딩 플래그를 영구 True 로 남기지 않는다

- **US**: US-UPD05 AC4 / **Priority**: Critical / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_update.py::test_check_all_updates_isolates_a_raising_updater` 가
  **업데이터 수준**의 격리를 덮는다. TUI 워커 스레드 수준(플래그 복구·프로세스 생존)은 미검증.
- **Preconditions**
  - 세 작업 함수를 각각 `RuntimeError("injected")` 를 던지게 monkeypatch:
    `scan_project_usage` / `load_unified_usage` / `check_all_updates`
  - **실제 `threading.Thread`** 사용, `join(timeout=5)` 으로 회수
  - `threading.excepthook` 을 임시로 교체해 스레드에서 샌 예외를 리스트에 기록
    (기본 훅은 stderr 에만 찍고 테스트를 통과시킨다 — 허위 양성)
  - teardown 에서 원래 훅 복구
- **Steps**: 세 kick 함수를 각각 호출하고 join 후 상태 확인, 이어서 `_render_frame` 호출
- **Expected Output**
  - 세 플래그 모두 `False` (`vault_scan_loading` / `usage_loading` / `update_check_loading`)
  - `_render_frame` 이 예외 없이 성공
  - 프로세스가 살아 있고 후속 입력 처리가 정상
- **현재 구현 예상 결과**: 플래그는 `finally` 로 복구되므로 이 부분은 통과한다.
  다만 `_kick_vault_scan` / `_kick_usage_reload` 는 예외를 잡지 않아 **`excepthook` 에 기록이 남는다.**
  그 자체는 크래시가 아니므로 이 TC 는 통과할 수 있고, 다음 TC 가 진짜 문제를 잡는다.

### TC-CHAOS-024 — 워커 실패가 사용자에게 드러난다

- **US**: US-UPD05 AC4 / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**: TC-CHAOS-023 과 동일한 예외 주입
- **Steps**
  1. 세 워커를 kick 하고 join
  2. `_render_frame` 렌더 후 화면 텍스트 `flat` 을 만든다
  3. `Upd` 컬럼과 상태바를 검사
- **Expected Output**
  - update check 실패: `Upd` 컬럼이 `!` 또는 상태바에 확인 실패 표시
  - vault scan 실패: `Used` 컬럼이 낡았음/실패임을 알리거나 상태바에 메시지가 있다
  - usage load 실패: Usage 탭 또는 상태바에 실패가 표시된다
  - **세 경우 모두 화면 어딘가에 실패가 나타난다** — 조용히 빈 값으로 표시되고 끝나지 않는다
- **현재 구현 예상 결과**: `_update_check_worker` 만 `except Exception` 으로 실패를 흡수하고
  빈 결과를 stamped 상태로 바인딩한다. `_kick_vault_scan` / `_kick_usage_reload` 는 예외가 스레드 밖으로 새며
  **화면에는 아무 표시도 남지 않는다**. 사용자는 "스캔이 안 끝났나" 로 오해한다. **실패 예상.**
- **실패 시 조치**: 두 워커에도 `except Exception` 을 추가하고 실패를 `state.status` 에 기록한다.
  `_update_check_worker` 와 처리 수준을 맞춘다.

---

## SC-CHAOS-010 — 리사이즈

### TC-CHAOS-025 — 4단계 리사이즈 시퀀스에서 예외가 없다

- **US**: US-TUI10 AC2 / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - fake stdscr 의 `getmaxyx()` 가 호출마다 다음 값을 순서대로 돌려주게 구성:
    `(30,140) → (10,40) → (4,20) → (30,140)`
  - Skills 서브탭 200행, 선택 인덱스 150
  - `monkeypatch.chdir(tmp_path)`
- **Steps**: 각 크기에서 `_render_frame(scr, state)` 호출
- **Expected Output**
  - 4단계 모두 예외 0건
  - `(4,20)` 단계에서 `"Terminal too small"` 만 표시되고 테이블 그리기 호출이 없다
  - 마지막 `(30,140)` 복귀 단계에서 선택 인덱스가 여전히 150이고, 그 행이 화면 안에 그려진다
    (스크롤 오프셋이 재계산된다)
  - 모든 단계에서 `x + max_w <= 그 단계의 cols`

### TC-CHAOS-026 — 검색 입력 중 리사이즈가 버퍼를 보존한다

- **US**: US-TUI10 AC2 / **Priority**: Medium / **Gap**: NEW
- **Preconditions**
  - Skills 서브탭에서 `/` 를 눌러 검색 입력 상태(`state.ext_searching = True`)
  - 입력 버퍼에 `"data"` 를 채운다
- **Steps**
  1. 메인 루프의 모달 분기에 `curses.KEY_RESIZE` 를 전달
  2. 재렌더 후 상태 확인
- **Expected Output**
  - 검색 입력 버퍼가 `"data"` 그대로다 — 리사이즈가 입력을 삼키거나 초기화하지 않는다
  - `state.ext_searching` 이 여전히 True (모달 상태 유지)
  - `/search:` 입력 밴드가 새 크기에 맞춰 다시 그려진다
  - 예외 0건
- **왜 필요한가**: 메인 루프는 모달 상태에서 대부분의 전역 키를 차단하고 `KEY_RESIZE` 만 통과시킨다.
  그 예외 처리가 빠지면 리사이즈 이벤트가 **검색어 문자로 들어가** 버퍼가 오염된다.

---

## 스펙 갭

| # | 관측 | 관련 US | 판단 |
|---|---|---|---|
| G-CHAOS-A | `read_json` 이 `JSONDecodeError` 를 잡지 않아 AC1("파싱 실패 시 fallback")이 미충족 | US-SYS05 AC1 | **구현 갭**. TC-CHAOS-002~005 가 모두 이 한 원인을 가리킨다 |
| G-CHAOS-B | 손상된 프로필과 "빈 프로필"을 구별하는 규칙이 없다 | US-PRJ03 AC2 | **스펙 갭**. 손상을 빈 것으로 오해해 `sync` 가 모든 링크를 제거하면 데이터 손실이다. TC-CHAOS-005 3단계의 기대값 확정을 위해 AC 추가가 필요하다 |
| G-CHAOS-C | 조회 명령의 부작용(디렉터리·캐시 생성) 허용 범위가 스펙에 없다 | US-SYS05 AC3 | **문서 갭**. TC-CHAOS-010 이 실패하면 그 결과가 곧 결정 사항 — 캐시 생성을 허용한다면 AC 로 명시하고 허용 목록을 둔다 |
| G-CHAOS-D | 백그라운드 워커 실패의 **가시성** 요구가 AC4("죽지 않는다")에만 걸려 있고, "드러난다"는 명문화되어 있지 않다 | US-UPD05 AC4 | **스펙 갭**. TC-CHAOS-024 는 "실패가 화면에 드러난다"를 요구사항으로 승격해 작성했다. 조용한 실패는 크래시보다 진단이 어렵다 |
| G-CHAOS-E | `sync_marketplace` 의 hard-sync ↔ `--ff-only` 충돌 | US-MKT05 AC1 | **해소됨 — `tests/doc/SPEC_DECISIONS.md` SD-001.** 구현(hard-sync)이 옳고 낡은 `FEATURES.md` §3.5 가 틀렸다. 설치 디렉터리는 사용자 작업 공간이 아니라 관리 대상 캐시이며, 커밋되지 않은 로컬 수정은 Claude Code 업데이터 산출물로 간주해 폐기된다. 문서·유저스토리를 정정했고 구현은 변경하지 않았다. |
