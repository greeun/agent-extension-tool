# API(CLI) 테스트 케이스 — axt

대응 시나리오: `tests/doc/scenarios/api-scenarios.md`

## 요약

| 항목 | 값 |
|---|---|
| 총 TC 수 | **110** |
| 시나리오 수 | 22 (SC-API-001 ~ SC-API-022) |
| 커버 리프 서브명령 | 41 / 41 |

**우선순위 분포**

| Critical | High | Medium | Low |
|---|---|---|---|
| 24 | 73 | 13 | 0 |

**Gap 분포**

| COVERED | PARTIAL | NEW |
|---|---|---|
| 64 | 11 | 35 |

- 모든 TC 는 `axt.main(argv)` 를 호출하고 `(exit_code, stdout, stderr)` 를 캡처한다
  (기존 `tests/test_cli.py::_run` 헬퍼와 동일 형태).
- **공통 Preconditions**: `conftest.py` 의 `_isolate_cwd` 로 cwd 가 `tmp_path` 로 고정된다.
  `~/.claude` 를 읽는 TC 는 반드시 `monkeypatch.setattr("axt.PATHS", axt.Paths(...))` 로 교체하고,
  axt 설정을 읽는 TC 는 `monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path/"config.json")` 를 건다.
- `--json` / `--csv` / stderr 문자열을 단언하는 TC 는 `monkeypatch.setenv("NO_COLOR", "1")` 로 ANSI 를 제거한다.

---

## 1. 공통 계층

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-001 | SC-API-001 | 없는 최상위 명령은 exit 2 | 공통 | `main(["totally-not-a-command"])` | `SystemExit.code == 2`, stderr 에 usage | Critical | US-SYS01 | PARTIAL — `test_cli.py::test_unknown_command_returns_error` 는 `SystemExit` 만 잡고 **코드 2 를 단언하지 않는다** |
| TC-API-002 | SC-API-001 | 필수 인자 누락은 exit 2 | 공통 | `main(["market", "add"])` / `main(["plugin", "info"])` | `SystemExit.code == 2` | Critical | US-SYS01 | NEW |
| TC-API-003 | SC-API-001 | `choices` 위반은 exit 2 | 공통 | `main(["update", "bogus-type"])` / `main(["vault", "add", "p", "-t", "bogus"])` | `SystemExit.code == 2` | Critical | US-UPD04 AC2 | NEW |
| TC-API-004 | SC-API-001 | 서브명령 없는 그룹은 exit 2 | 공통 | `main(["market"])` / `main(["vault"])` (`required=True` 그룹) | `SystemExit.code == 2` | High | US-SYS01 | NEW |
| TC-API-005 | SC-API-002 | `ValueError` → exit 1 + stderr `✗` | `PATHS` 교체, `NO_COLOR` | `main(["market", "add", "nonsense"])` | exit 1, stderr 에 `✗`, stdout 에 `✗` 없음 | Critical | US-MKT01 AC2 | PARTIAL — stderr `✗` 는 `test_market_sync_unknown_name_errors_via_main` 이 덮지만 `market add` 경로·stdout 청결은 미검증 |
| TC-API-006 | SC-API-002 | `KeyError` → exit 1 + stderr `✗` | 동상 | `main(["market", "sync", "ghost"])` | exit 1, stderr `✗` | Critical | US-MKT02 AC3 | COVERED `test_cli.py::test_market_sync_unknown_name_errors_via_main` |
| TC-API-007 | SC-API-003 | `--version` 은 exit 0 + 패키지 버전 | 공통 | `main(["--version"])` | `SystemExit.code == 0`, stdout 에 `axt.__version__` | Critical | US-SYS01 AC4 | COVERED `test_cli.py::test_version_flag` |
| TC-API-008 | SC-API-003 | `--help` 는 exit 0 + 12개 그룹 노출 | 공통 | `main(["--help"])` | `SystemExit.code == 0`, stdout 에 `tui`·`context`·`market`·`mcp`·`hook`·`plan`·`plugin`·`project`·`skill`·`usage`·`vault`·`update` 전부 | Critical | US-SYS01 AC3 | PARTIAL — 기존 테스트는 9개만 확인 (`hook`·`update`·`tui` 누락) |
| TC-API-009 | SC-API-003 | `--theme light` 만으로 TUI 기동 | `launch_tui` 스텁 | `main(["--theme", "light"])` | exit 0, `launch_tui("light")` 호출 | High | US-TUI09 AC2 | COVERED `test_cli.py::test_cli_theme_flag_overrides` |
| TC-API-010 | SC-API-003 | `--theme bogus` 는 exit 2 | 공통 | `main(["--theme", "bogus"])` | `SystemExit.code == 2` | Medium | US-TUI09 AC2 | NEW |
| TC-API-011 | SC-API-004 | 인자 0개 → TUI 1회 기동 | `launch_tui` 스텁 | `main([])` | exit 0, 호출 1회 | Critical | US-SYS01 AC2 | COVERED `test_cli.py::test_no_args_invokes_tui` |
| TC-API-012 | SC-API-004 | `tui` 서브명령도 같은 경로 | 동상 | `main(["tui"])` | exit 0, 호출 1회 | Critical | US-SYS01 AC2 | COVERED `test_cli.py::test_tui_explicit` |

## 2. `market` (4 리프)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-013 | SC-API-005 | 빈 레지스트리 `list` | `PATHS(known_marketplaces=tmp/km.json)` | `market list` | exit 0 + 빈 목록 안내 | High | US-MKT03 | COVERED `test_cli.py::test_market_list_empty` |
| TC-API-014 | SC-API-005 | 등록 후 `list` 가 4컬럼을 낸다 | `PATHS` 교체, `dir:` 등록 | `market list` | exit 0, 마켓명·Source 종류·Location·Updated 출력 | High | US-MKT03 AC1 | COVERED `test_cli.py::test_market_list_with_registered_marketplace` |
| TC-API-015 | SC-API-005 | 버전 조회 실패해도 목록은 나온다 | `_git` 실패 주입 | `market list` | exit 0, 오류 표기와 함께 행 출력 | Medium | US-MKT03 AC2 | COVERED `test_cli.py::test_market_list_reports_version_errors` |
| TC-API-016 | SC-API-005 | `add` 3형태 + 이름 파생 | `PATHS` 교체, git monkeypatch | `market add dir:<tmp>` / `github:org/repo` / `git:https://x/y.git` | exit 0 + `✓ ... registered`, 이름이 각각 디렉터리명 / repo 이름 / `custom-marketplace` | High | US-MKT01 AC3 | COVERED `test_cli.py` (3개) |
| TC-API-017 | SC-API-005 | `sync <name>` 의 두 결과 메시지 | `sync_marketplace` monkeypatch | 갱신됨 / 최신 | 각각 `before → after` / `(up to date)`, 둘 다 exit 0 | High | US-MKT02 AC2 | COVERED `test_cli.py` (2개) |
| TC-API-018 | SC-API-005 | 이름 생략 `sync` 는 전체 동기화 | 빈 레지스트리 | `market sync` | exit 0 (0건이어도 오류 아님) | High | US-MKT02 AC1 | COVERED `test_cli.py::test_market_sync_all_empty_registry` |
| TC-API-019 | SC-API-005 | 없는 이름 `remove` 는 exit 1 | `PATHS` 교체 | `market remove ghost` | exit 1 + stderr `✗` | High | US-MKT04 AC2 | COVERED `test_cli.py::test_market_remove_missing` |

## 3. `mcp` (4 리프)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-020 | SC-API-006 | 서버 0개 `list` | `PATHS` 교체 + `chdir` | `mcp list` | exit 0 + `No MCP servers found.` | High | US-MCP01 | COVERED `test_cli.py::test_mcp_list_no_plugins` |
| TC-API-021 | SC-API-006 | `list` 컬럼 + `[disabled]` 표기 | 서버 2개(1개 비활성) | `mcp list` | Server/Scope/Transport/Detail + 비활성 행에 `[disabled]` | High | US-MCP02 AC1 | COVERED `test_cli.py::test_mcp_list_with_servers` — `[disabled]` 표기는 PARTIAL |
| TC-API-022 | SC-API-006 | 없는 이름 `info` 는 exit 1 | 동상 | `mcp info ghost` | exit 1 + `not found` | High | US-MCP04 AC1 | COVERED `test_cli.py::test_mcp_info_missing` |
| TC-API-023 | SC-API-006 | stdio 서버 `info` 는 명령줄을 낸다 | stdio 서버 주입 | `mcp info srv1` | exit 0, `Command: node server.js` 형태 | High | US-MCP04 AC2 | COVERED `test_cli.py::test_mcp_info_with_env` |
| TC-API-024 | SC-API-006 | 원격(url) 서버 `info` 는 URL 을 낸다 | url 서버 주입 | `mcp info remote1` | exit 0, `URL: https://...` 출력, `Command:` 없음 | High | US-MCP04 AC2 | NEW |
| TC-API-025 | SC-API-006 | `disable` → `enable` 왕복 + 재시작 안내 | `PATHS(claude_config=tmp/.claude.json)` + `chdir` | `mcp disable srv` → `mcp enable srv` | 둘 다 exit 0, 출력에 `Restart Claude Code` 포함 | High | US-MCP03 AC3 | COVERED `test_cli.py` (2개) — 재시작 안내 단언은 PARTIAL |

## 4. `hook` (3 리프)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-026 | SC-API-007 | 훅 0개 `list` | `PATHS` 교체 + `chdir` | `hook list` | exit 0 + `No hooks found.` | High | US-HK01 | COVERED `test_cli.py::test_hook_list_empty` |
| TC-API-027 | SC-API-007 | `list` 인덱스를 그대로 토글에 쓴다 | 훅 1개 배치 | `hook disable 0` → `hook list` → `hook enable 0` | 각각 exit 0, 중간 `list` 에 `[off]` 표기, 마지막에 사라짐 | High | US-HK01 AC2 | COVERED `test_cli.py::test_hook_disable_then_enable_by_index` |
| TC-API-028 | SC-API-007 | 범위 밖 인덱스는 exit 1 | 훅 1개 | `hook disable 5` | exit 1 + `out of range (0..0)` 안내 | High | US-HK01 AC2 | COVERED `test_cli.py::test_hook_disable_out_of_range` |
| TC-API-029 | SC-API-007 | plugin 훅 토글은 exit 1 + read-only | plugin 훅만 배치 | `hook disable 0` | exit 1 + `read-only` 문구, 설정 파일 불변 | High | US-HK03 AC1, AC2 | COVERED `test_cli.py::test_hook_disable_refuses_plugin_hook` |
| TC-API-030 | SC-API-007 | 이미 그 상태면 no-op + exit 0 | 이미 disabled 인 훅 | `hook disable 0` | exit 0 + `already disabled` 안내, 파일 불변 | Medium | US-HK02 | NEW |

## 5. `plan` (2 리프)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-031 | SC-API-008 | 서브명령 없는 `plan` → overview | 빈 환경, `AXT_CONFIG_PATH` 교체 | `plan` | exit 0 | High | US-USG07 | COVERED `test_cli.py::test_smoke_usage_and_plan_default_actions` |
| TC-API-032 | SC-API-008 | `set <name>` 이 자동 감지를 끈다 | `AXT_CONFIG_PATH` 교체 | `plan set max-20x` → `plan overview` | exit 0, `auto-detect off` 안내 + overview 에 플랜 라벨·월정액 반영 | High | US-USG07 AC2 | COVERED `test_cli.py::test_plan_set_then_overview_roundtrip` |
| TC-API-033 | SC-API-008 | `set auto` 가 자동 감지를 켠다 | 동상 | `plan set auto` | exit 0, `Auto-detect enabled` 안내 | High | US-USG07 AC2 | NEW |
| TC-API-034 | SC-API-008 | 예측 초과 시 경고 / 미초과 시 무경고 | `get_days_in_billing_period` 를 `(10, 30)` 로 monkeypatch, 사용량 주입 | `plan overview` | 초과: `⚠ 초과 예상` 존재 / 미초과: 부재 | High | US-USG07 AC4 | COVERED `test_cli.py` (2개) |

## 6. `plugin` (6 리프)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-035 | SC-API-009 | 빈 상태 `list` | `PATHS` 교체 | `plugin list` | exit 0 + `No plugins installed.` | High | US-PLG01 | COVERED `test_cli.py::test_plugin_list_empty` |
| TC-API-036 | SC-API-009 | `list` 가 project/global/unset 을 구분 표기 | 3가지 상태 배치 | `plugin list` | `unset` 이 `off` 와 다른 글리프(`·`)로 표시 | High | US-PLG01 AC3 | COVERED `test_cli.py::test_plugin_list_shows_split_status` |
| TC-API-037 | SC-API-009 | `enable` 기본 스코프는 global | `PATHS(settings=tmp/s.json)` + `chdir(proj)` | `plugin enable p@m` | exit 0, `~/.claude/settings.json` 에만 기록, 재시작 안내 | High | US-PLG02 AC1, AC4 | COVERED `test_cli.py` (2개) |
| TC-API-038 | SC-API-009 | `--scope project` 는 cwd 에 쓴다 | 동상 | `plugin enable p@m --scope project` / `disable` | `<proj>/.claude/settings.json` 에 기록, global 불변 | High | US-PLG02 AC2 | COVERED `test_cli.py` (2개) |
| TC-API-039 | SC-API-009 | `--scope bogus` 는 exit 2 | 공통 | `plugin enable p@m --scope bogus` | `SystemExit.code == 2` | Medium | US-PLG02 AC1 | NEW |
| TC-API-040 | SC-API-009 | 없는 id 로 `info` / `remove` | `PATHS` 교체 | `plugin info ghost` / `plugin remove ghost` | 둘 다 exit 1 + 명확한 메시지 | High | US-PLG03 AC1, US-PLG04 | COVERED `test_cli.py` (2개) |
| TC-API-041 | SC-API-009 | `info` 가 version/marketplace/path/dates 를 낸다 | 플러그인 1개 설치 | `plugin info p@m` | exit 0, 4개 필드 + enabled/disabled 상태 | High | US-PLG03 | COVERED `test_cli.py` (2개) |
| TC-API-042 | SC-API-009 | `remove` 가 dir·레지스트리·설정을 모두 정리 | 설치 상태 + settings 항목 | `plugin remove p@m` | exit 0, 설치 dir 삭제 + `installed_plugins.json` 및 settings 항목 제거 | High | US-PLG04 AC1 | COVERED `test_cli.py::test_plugin_remove_deletes_dir_and_registry` |
| TC-API-043 | SC-API-009 | `search` 0건도 exit 0 | 빈 마켓 | `plugin search zzz` | exit 0 + 안내 문구 | High | US-PLG05 AC1 | COVERED `test_cli.py::test_plugin_search_prints_hint` |

## 7. `project` (5 리프)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-044 | SC-API-010 | `init` 이 프로필을 만든다 | `chdir(proj)` | `project init` | exit 0 + `.axt-profile.json` 생성 | High | US-PRJ01 AC1 | COVERED `test_cli.py::test_project_init_creates_profile` |
| TC-API-045 | SC-API-010 | 재 `init` 은 덮어쓰지 않는다 | 프로필 존재 | `project init` | exit 0 + `already exists` 안내, 내용 불변 | High | US-PRJ01 AC2 | COVERED `test_cli.py::test_project_init_idempotent` |
| TC-API-046 | SC-API-010 | 프로필 없는 `status` 는 exit 1 | 프로필 없음 | `project status` | exit 1 + `Run \`axt project init\` first.` | High | US-PRJ04 | COVERED `test_cli.py::test_project_status_no_profile` |
| TC-API-047 | SC-API-010 | `status` 가 linked / missing 을 구분 | 프로필 + 일부만 링크, Windows skip | `project status` | `✓ linked` / `✗ missing` 각각 출력, plugin 항목은 `(in profile)` | High | US-PRJ04 AC2 | COVERED `test_cli.py::test_project_status_reports_linked_and_missing` |
| TC-API-048 | SC-API-010 | `status` 는 파일시스템을 바꾸지 않는다 | 동상, 실행 전 디렉터리 스냅샷 | `project status` | 실행 전후 디렉터리 트리 동일 | High | US-PRJ04 AC1 | NEW |
| TC-API-049 | SC-API-010 | vault 에 없는 이름 `add` | vault 비어 있음 | `project add skill ghost` | 해당 항목에 `✗ ... not found in vault` | High | US-PRJ02 AC2 | COVERED `test_cli.py::test_project_add_item_not_in_vault` |
| TC-API-050 | SC-API-010 | `add` 는 이름을 여러 개 받는다 | vault 에 2개, Windows skip | `project add skill a b` | 둘 다 링크 + 각각 `✓` 라인 | Medium | US-PRJ02 AC1 | PARTIAL — 단일 이름 왕복만 검증 |
| TC-API-051 | SC-API-010 | `add` → `remove` 왕복 | 동상 | `project add skill a` → `project remove skill a` | symlink 생성 후 제거, 실체 잔존 | High | US-PRJ02 AC3 | COVERED `test_cli.py::test_project_add_then_remove_roundtrip` |
| TC-API-052 | SC-API-010 | `sync` 의 두 출력 형태 | 동기화 상태 / 프로필에 미링크 항목 | `project sync` | `Already in sync.` / `+ <entry>` 라인 | High | US-PRJ03 AC3 | COVERED `test_cli.py` (2개) |

## 8. `skill` (3 리프)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-053 | SC-API-011 | 스킬 0개 `list` | `PATHS(skills=tmp/skills)` | `skill list` | exit 0 + `No skills found.` | High | US-LNK01 | COVERED `test_cli.py::test_skill_list_empty` |
| TC-API-054 | SC-API-011 | `list` 가 symlink 대상을 표시 | 실체 + symlink, Windows skip | `skill list` | exit 0, symlink 행에 `→ <대상>` | High | US-LNK01 AC2 | COVERED `test_cli.py::test_skill_list_with_items` |
| TC-API-055 | SC-API-011 | `list` 가 vault 전용 항목도 포함 | vault 에만 있는 스킬 | `skill list` | Source `vault` 행 존재 | High | US-LNK01 AC1 | COVERED `test_cli.py::test_skill_list_includes_vault_only` |
| TC-API-056 | SC-API-011 | `link` → `unlink` 왕복 | Windows skip | `skill link <dir> -n alias` → `skill unlink alias` | 둘 다 exit 0, symlink 생성·제거 | High | US-LNK02 AC1 | COVERED `test_cli.py::test_skill_link_then_unlink` |
| TC-API-057 | SC-API-011 | 미지원 플랫폼에서는 파서에 등록되지 않는다 | `is_symlink_supported` 를 `False` 로 monkeypatch 후 `build_parser()` | 파서 조사 | `skill` 그룹에 `link`/`unlink` 서브파서 부재 | High | US-LNK02 AC2 | NEW — 기존 테스트는 **핸들러 거부**만 검증(`test_skill_link_handler_rejects_unsupported_platform`) |
| TC-API-058 | SC-API-011 | 없는 경로로 `link` 는 exit 1 | Windows skip | `skill link <없는 경로>` | exit 1 + stderr `✗` | High | US-LNK02 AC3 | NEW |

## 9. `usage` (5 리프)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-059 | SC-API-012 | 인자 없는 `usage` == `usage today` | 빈 `PATHS.projects`, `AXT_CONFIG_PATH` 교체 | `usage` / `usage today` | 두 출력이 동일, 둘 다 exit 0 | Critical | US-USG01 AC1 | COVERED `test_cli.py::test_smoke_usage_and_plan_default_actions` — 출력 동일성은 PARTIAL |
| TC-API-060 | SC-API-012 | 데이터 0건에서 5개 리프 모두 exit 0 | 동상, `--timezone UTC` 명시 | `usage today` / `week` / `month` / `blocks` / `session x` | `session` 만 exit 1(`not found`), 나머지 exit 0 | Critical | US-USG01 AC3 | COVERED `test_cli.py` (4개) |
| TC-API-061 | SC-API-012 | 데이터 있는 `today` 요약 필드 | 엔트리 주입, `--timezone UTC` | `usage today --timezone UTC` | Sessions/Models/In/Out/Cache Write/Cache Read/Cost/Cache Saved 8줄 | High | US-USG01 | COVERED `test_cli.py::test_usage_today_with_data_renders_full_summary` |
| TC-API-062 | SC-API-012 | `week` / `month` / `blocks` 표 렌더 | 동상 | 각 명령 | 헤더 + 데이터 행 출력, exit 0 | High | US-USG01 | COVERED `test_cli.py` (3개) |
| TC-API-063 | SC-API-013 | `--model` 필터 | 엔트리 주입 | `usage today --timezone UTC --model no-such-model` | 매칭 0건 → `No usage data for today.` | High | US-USG02 AC3 | COVERED `test_cli.py::test_usage_today_model_filter` |
| TC-API-064 | SC-API-013 | `--project` 필터 | 서로 다른 project 의 엔트리 2건 | `usage today --project projA` | projA 엔트리만 집계 | High | US-USG02 AC3 | NEW |
| TC-API-065 | SC-API-013 | `--since` / `--until` 이 실제로 구간을 좁힌다 | 서로 다른 날짜의 엔트리 3건 | `usage today --since 2026-03-01 --until 2026-03-01` | 지정 구간 엔트리만 집계 | High | US-USG02 | NEW — 스펙 갭 G-1 (현재 두 인자는 무시됨) |
| TC-API-066 | SC-API-013 | 잘못된 날짜 형식은 exit 1 | 동상 | `usage today --since notadate` | exit 1 + 형식 안내 | High | US-USG02 AC1 | NEW — 스펙 갭 G-1 |
| TC-API-067 | SC-API-013 | `--since > --until` 은 오류 | 동상 | `usage today --since 2026-03-10 --until 2026-03-01` | exit 1 | High | US-USG02 AC2 | NEW — 스펙 갭 G-1 |
| TC-API-068 | SC-API-013 | 필터 조합은 AND | 동상 | `--model claude-opus-4-7 --project projA` | 두 조건을 모두 만족하는 엔트리만 | Medium | US-USG02 AC3 | NEW |
| TC-API-069 | SC-API-014 | `today --json` 이 유효 JSON + 필수 키 | `NO_COLOR`, 엔트리 주입 | `usage today --timezone UTC --json` | `json.loads` 성공, `date`/`sessions`/`models`/`inputTokens`/`outputTokens`/`cacheCreationTokens`/`cacheReadTokens`/`cost`/`cacheSavings` 키 존재 | Critical | US-USG03 AC1 | COVERED `test_cli.py::test_usage_today_json_with_data` |
| TC-API-070 | SC-API-014 | `week --json` 은 빈 데이터에서도 유효 JSON | `NO_COLOR`, 빈 데이터 | `usage week --json` | `json.loads` 성공 (`[]`) | Critical | US-USG03 AC1 | COVERED `test_cli.py::test_usage_week_json_empty_is_valid_json` |
| TC-API-071 | SC-API-014 | `week --csv` 헤더가 9컬럼 | `NO_COLOR` | `usage week --csv` | 첫 줄 == `date,sessions,input_tokens,output_tokens,cache_write_tokens,cache_read_tokens,cost_usd,cost_krw,cache_savings_usd` | Critical | US-USG03 AC2 | COVERED `test_cli.py::test_usage_week_csv_emits_header` |
| TC-API-072 | SC-API-014 | 모든 CSV 행의 열 수가 헤더와 같다 | `NO_COLOR`, 여러 날짜 엔트리 주입 | `usage week --timezone UTC --csv` | 각 데이터 행의 콤마 개수 == 헤더의 콤마 개수 | Critical | US-USG03 AC2 | PARTIAL — 행 1건 존재만 검증(`test_usage_week_csv_with_data_has_row`), **열 수 일치 미검증** |
| TC-API-073 | SC-API-014 | `--json` 과 `--csv` 동시 지정의 결정성 | `NO_COLOR` | `usage week --json --csv` | 하나의 형식만 출력(혼합 출력 금지) — 현 구현은 `--json` 우선 | Medium | US-USG03 | NEW |
| TC-API-074 | SC-API-015 | `--export` 가 파일을 쓴다 | `tmp_path` 경로 | `usage week --export <tmp>/out.csv` | exit 0 + 파일 생성 + 비어 있지 않음 | Medium | US-USG03 AC3 | NEW — 스펙 갭 G-3 (현재 argparse 에 없음 → exit 2) |
| TC-API-075 | SC-API-015 | 쓸 수 없는 경로 `--export` 는 exit 1 | 없는 부모 디렉터리 | `usage week --export /nonexistent/dir/out.csv` | exit 1 + stderr 오류 | Medium | US-USG03 AC3 | NEW — 스펙 갭 G-3 |
| TC-API-076 | SC-API-016 | `blocks --active` 가 활성 블록만 남긴다 | `datetime.now` 고정 + 엔트리 주입 | `usage blocks --timezone UTC --active` | 활성 블록 행만 출력 | High | US-USG04 AC4 | COVERED `test_cli.py::test_usage_blocks_active_filter` |
| TC-API-077 | SC-API-016 | `session <prefix>` 유일 매칭 상세 | 세션 1개 엔트리 주입 | `usage session abc` | exit 0, Project/Models/Messages/토큰/Cost/Period 출력 | High | US-USG05 AC1 | COVERED `test_cli.py::test_usage_session_with_data_reports_totals` |
| TC-API-078 | SC-API-016 | 매칭 0건은 exit 1 | 빈 데이터 | `usage session zzz` | exit 1 + `not found` | High | US-USG05 AC2 | COVERED `test_cli.py::test_usage_session_not_found` |
| TC-API-079 | SC-API-016 | 다중 매칭은 후보를 제시한다 | 같은 prefix 를 갖는 세션 2개 주입 | `usage session ab` | 후보 목록 출력(임의로 첫 세션만 보여주지 않음) | High | US-USG05 AC3 | NEW — 스펙 갭 G-6 |

## 10. `vault` (6 리프)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-080 | SC-API-017 | 빈 vault `list` 는 오류가 아니다 | `PATHS(vault=tmp/vault)` | `vault list` | exit 0 + `Vault is empty. Run \`axt vault migrate\` ...` | High | US-VLT02 AC2 | COVERED `test_cli.py::test_vault_list_empty` |
| TC-API-081 | SC-API-017 | 항목 있는 `list` 가 name/type 을 낸다 | vault 에 2건 | `vault list` | exit 0, Name·Type 컬럼 + `N extension(s) in vault` | High | US-VLT02 AC1 | COVERED `test_cli.py::test_vault_list_with_items` |
| TC-API-082 | SC-API-017 | 없는 경로 `add` 는 exit 1 | `PATHS` 교체 | `vault add /nope` | exit 1 + `✗ Source not found` | High | US-VLT03 AC3 | COVERED `test_cli.py::test_vault_add_missing_source` |
| TC-API-083 | SC-API-017 | `-t` 미지정 시 타입 추론 | 디렉터리 / `.md` 파일 | `vault add <dir>` / `vault add <file.md>` | 각각 `skill` / `command` 로 저장 | High | US-VLT03 AC2 | COVERED `test_cli.py` (2개) |
| TC-API-084 | SC-API-017 | 같은 이름 `add` 는 덮어쓰지 않고 실패 | vault 에 동명 항목(디렉터리·파일 각각) | `vault add <same>` | exit 1 + stderr `✗`, 기존 vault 내용 불변 | High | US-VLT03 AC4 | NEW — 파일 타입은 스펙 갭 G-5 (현재 조용히 덮어씀) |
| TC-API-085 | SC-API-017 | `install` 미존재 확장 / 성공 | 마켓 디렉터리 구성 | `vault install m ghost` / `vault install m real` | exit 1 + `not found in marketplace` / exit 0 + vault 에 생성 | High | US-VLT04 AC2, AC3 | COVERED `test_cli.py` (2개) |
| TC-API-086 | SC-API-017 | 미등록 마켓플레이스는 사용 가능 마켓을 안내 | 레지스트리 비어 있음 | `vault install ghost-market x` | exit 1 + 등록된 마켓 목록 안내(확장 미존재와 구분) | Medium | US-VLT04 AC1 | NEW — 스펙 갭 G-7 |
| TC-API-087 | SC-API-017 | `migrate` 의 3가지 출력 형태 | 글로벌 항목 없음 / 이동 대상 있음 / broken symlink 있음 | `vault migrate` | 각각 `No extensions found in global paths.` / `✓ moved` + 집계 / `⚠ ... broken symlink` + 집계, 모두 exit 0 | High | US-VLT01 AC3 | COVERED `test_cli.py` (3개) — broken 출력은 PARTIAL |
| TC-API-088 | SC-API-018 | vault 에 없는 이름 `link-global` | 빈 vault | `vault link-global skill ghost` | exit 1 + `not found in vault` | High | US-VLT05 AC3 | COVERED `test_cli.py::test_vault_link_global_not_in_vault` |
| TC-API-089 | SC-API-018 | `link-global` → `unlink-global` 왕복 | vault 에 1건, Windows skip | 두 명령 연속 | 둘 다 exit 0, symlink 생성·제거, vault 실체 잔존 | High | US-VLT05 AC1, AC2 | COVERED `test_cli.py::test_vault_link_global_then_unlink` |
| TC-API-090 | SC-API-018 | `--mirror-agents` 가 `~/.agents/skills` 를 만든다 | `HOME` → `tmp_path`, Windows skip | `vault link-global skill s --mirror-agents` | exit 0, `~/.agents/skills/s` 생성 + `✓` 표기 | High | US-VLT06 AC1 | NEW |
| TC-API-091 | SC-API-018 | `.skill-lock.json` 은 미러를 건너뛰고 `--force-agents` 로 강행 | 동상 + 잠금 파일 | `--mirror-agents` / `--mirror-agents --force-agents` | 전자 exit 0 + `⊘` 표기(미러 미생성), 후자 미러 생성 | High | US-VLT06 AC2, AC3 | NEW |
| TC-API-092 | SC-API-018 | `unlink-global --mirror-agents` 가 미러도 제거 | 동상 | `vault unlink-global skill s --mirror-agents` | exit 0, 글로벌 symlink 와 `.agents` 미러 모두 제거 | High | US-VLT06 AC4 | NEW |

## 11. `context` (1 리프)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-093 | SC-API-019 | 옵션 없는 `context` | `HOME`·cwd 격리, 외부 명령 monkeypatch | `context` | exit 0, `Context Usage: N% of ...` + 카테고리 표 + `Cost Impact` 블록 | High | US-CTX01 AC1 | COVERED `test_cli.py::test_context_command_runs` |
| TC-API-094 | SC-API-019 | `--json` 이 유효 JSON + 필수 키 | `NO_COLOR` | `context --json` | `json.loads` 성공, `totalTokens`/`contextWindowSize`/`usedPercent`/`model`/`sources`/`costImpact` | High | US-CTX01 AC4 | COVERED `test_cli.py::test_context_json_output` |
| TC-API-095 | SC-API-019 | `--detail` 이 개별 항목 행을 추가한다 | 동상 | `context` vs `context --detail` | `--detail` 출력이 카테고리 아래 항목 행을 포함(줄 수 증가) | High | US-CTX01 AC2 | NEW |
| TC-API-096 | SC-API-019 | `--category` 가 하나만 남긴다 / 없는 카테고리 | 동상 | `context --category skills` / `--category nope` | 해당 카테고리 행만 / exit 0 + 빈 표(오류 아님) | High | US-CTX01 AC3 | NEW |
| TC-API-097 | SC-API-019 | `--model` 이 윈도우·비용을 바꾼다 | 동상 | `context --model claude-haiku-4-5 --json` | `contextWindowSize == 200000`, `usedPercent` 가 그 기준 | Medium | US-CTX01 | NEW |

## 12. `update` (1 리프 + 타깃팅)

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-API-098 | SC-API-020 | 옵션 없는 `update` 는 4그룹 리포트 | `check_all_updates` monkeypatch (tier 1/2/3 혼합) | `update` | exit 0, `Updatable:` / `Up to date:` / `Manual (report only):` / `Delegated:` + `N updatable, N up to date, N manual, N delegated` 요약 | Critical | US-UPD01 AC2, AC3 | NEW |
| TC-API-099 | SC-API-020 | 옵션 없는 `update` 는 아무것도 바꾸지 않는다 | `apply_updates` 를 호출 시 실패하도록 monkeypatch | `update` | `apply_updates` 미호출, 파일시스템 변화 없음 | Critical | US-UPD01 AC1 | NEW |
| TC-API-100 | SC-API-020 | 알 수 없는 `type` 은 exit 2 | 공통 | `update bogus` | `SystemExit.code == 2` | Critical | US-UPD04 AC2 | NEW |
| TC-API-101 | SC-API-020 | 없는 `name` 은 0건 안내 | `check_all_updates` monkeypatch | `update plugin ghost` | exit 0 + 필터 결과 0건 안내(스펙 US-UPD04 AC3 기준은 exit 1 + 안내) | High | US-UPD04 AC3 | NEW |
| TC-API-102 | SC-API-020 | bulk `--apply` 는 tier-1 updatable 만 | `check_all_updates`·`apply_updates` monkeypatch | `update --apply --yes` | targets == tier-1 updatable 목록만, tier-3 제외 | Critical | US-UPD02 AC1 | COVERED `test_update.py::test_cli_update_bulk_apply_excludes_tier3` |
| TC-API-103 | SC-API-020 | `claude-code` 명시 타깃일 때만 위임 | 동상 | `update claude-code --apply --yes` | targets 에 `("claude-code","claude-code")` 포함 | Critical | US-UPD02 AC2 | COVERED `test_update.py::test_cli_update_claude_code_explicit_apply` |
| TC-API-104 | SC-API-020 | 확인 프롬프트 거절은 exit 1 + 미적용 | `input` → `"n"` | `update --apply` | exit 1 + `Aborted.`, `apply_updates` 미호출 | Critical | US-UPD02 AC3 | COVERED `test_update.py::test_cli_update_apply_decline_aborts` |
| TC-API-105 | SC-API-020 | `-y` 는 프롬프트를 생략 | `input` 호출 시 예외를 던지도록 monkeypatch | `update --apply --yes` | 예외 없이 exit 0 | Critical | US-UPD02 AC3 | COVERED `test_update.py::test_cli_update_apply_gated_by_yes` — `input` 미호출 단언은 PARTIAL |
| TC-API-106 | SC-API-020 | 적용 대상 0건 | `check_all_updates` → 빈 목록 | `update --apply --yes` | exit 0 + `Nothing to update.` | Medium | US-UPD01 | NEW |
| TC-API-107 | SC-API-021 | `--json` dry-run 스키마 | `NO_COLOR` + monkeypatch | `update --json` | `json.loads` 성공, 각 원소에 `item_type`/`name`/`tier`/`current`/`available`/`updatable`/`note`/`error` | Critical | US-UPD03 AC2, AC3 | COVERED `test_update.py::test_cli_update_dry_run_json` — 전체 키 집합 단언은 PARTIAL |
| TC-API-108 | SC-API-021 | `--apply --json` 은 프롬프트를 띄우지 않는다 | `input` 호출 시 예외를 던지도록 monkeypatch | `update --apply --json` (`-y` 없음) | 예외 없이 exit 0 + 결과 JSON(`before`/`after`/`updated`/`action`/`error`) | Critical | US-UPD03 AC1 | NEW |
| TC-API-109 | SC-API-021 | `--json` + 대상 0건은 `[]` | 동상 | `update --apply --json` | stdout == `[]` | Medium | US-UPD03 AC2 | NEW |
| TC-API-110 | SC-API-022 | 비-TTY 에서 TUI 는 exit 1 + 안내 | TTY 없음(테스트 기본) | `launch_tui()` | exit 1, stderr 에 `TUI failed to start` 또는 curses 안내, 트레이스백 없음 | High | US-SYS01 AC2 | COVERED `test_cli.py::test_tui_launch_outside_terminal_fails_gracefully` |

---

**작성 대상 요약** — `NEW` 35건 + `PARTIAL` 11건 = **46건**이 gap-code 단계의 입력이다.
그중 `usage --since/--until`(TC-API-065~067), `--export`(TC-API-074~075),
`session` 다중 매칭(TC-API-079), `vault add` 파일 중복(TC-API-084),
`vault install` 미등록 마켓(TC-API-086), `update <type> <name>` 미존재 이름(TC-API-101)
6개 묶음은 **구현이 없거나 스펙과 어긋나므로 스펙 확정이 먼저** 필요하다
(`unit-scenarios.md` 의 `## 스펙 갭` G-1 / G-3 / G-5 / G-6 / G-7 참조).
