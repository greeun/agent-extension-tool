# Integration Test Scenarios

> Target: axt — 모듈 간 연동(실제 파일시스템 상태 변화 포함)
> Date: 2026-08-22
> Author: full-test-orchestrator (Phase B, Agent 2)

## 범위와 경계

- **소유 계층**: 두 개 이상의 모듈이 실제 디스크 상태를 사이에 두고 맞물리는 흐름.
  `tests/test_<domain>.py` 의 integration 섹션이 코드의 소재지다.
- **이 문서가 검증하지 않는 것**
  - 순수 함수 입출력·경계값 → **unit** 소유 (`parse_yaml_description`, `_ver_key`,
    `parse_marketplace_source` 의 파싱 규칙 등은 여기서 다시 확인하지 않는다)
  - CLI 인자 검증 · exit code · stdout 형태 · `--json` 스키마 → **api** 소유
    (`tests/test_cli.py`). 본 문서의 시나리오가 CLI 진입점을 쓰더라도 단언 대상은
    **디스크에 남은 상태**이지 종료 코드나 출력 문자열이 아니다.
  - 키 입력 → 렌더 결과 → 다음 화면 → **e2e** 소유 (`e2e-scenarios.md`).
    단, SC-INT-011 처럼 "키 핸들러가 core를 호출해 파일을 바꾼다"는 **연동 지점**은
    integration 소유이고, 그 뒤의 화면 여정은 e2e가 이어받는다.
- **결정성**: 모든 시나리오는 `tmp_path` + `monkeypatch.setattr("axt.PATHS", ...)`
  로 격리한다. 시계·mtime·cwd·스레드를 건드리는 시나리오는 각 TC의 Preconditions
  에 격리 방법을 명시한다.

---

## SC-INT-001: vault ↔ `.axt-profile.json` ↔ 프로젝트 심볼릭 링크 3자 정합

- **Objective**: `project init/add/sync/remove/status` 가 vault 실체 · 프로필 선언 ·
  `.claude/<sub>/` 심볼릭 링크 세 가지를 항상 같은 상태로 유지하는지 검증한다.
  (US-PRJ01, US-PRJ02, US-PRJ03, US-PRJ04, US-VLT05)
- **Priority**: Critical
- **Preconditions**:
  - `tmp_path/vault/{skills,commands,agents}` 에 실체가 있는 vault
  - `monkeypatch.chdir(tmp_path/proj)` 로 프로젝트 cwd 고정
  - `monkeypatch.setattr("axt.PATHS", axt.Paths(vault=..., claude_dir=...))`
- **Steps**:
  1. 빈 프로젝트에서 프로필을 만들고 vault 항목을 추가한다
  2. 프로필과 심볼릭 링크가 함께 생겼는지 확인한다
  3. 프로필을 손으로 어긋나게 만든 뒤 `sync_project` 로 재정렬한다
  4. `status` 경로가 파일시스템을 바꾸지 않는지 확인한다
- **Expected Result**: 프로필의 선언 집합과 `.claude/<sub>/` 의 vault-향 심볼릭 링크
  집합이 항상 일치하며, vault 실체는 어떤 경로에서도 삭제되지 않는다.
- **Notes**: `sync_project` 는 **vault 하위를 가리키는** 심볼릭 링크만 정리 대상으로
  삼는다 — 외부를 가리키는 링크는 프로필에 없어도 남긴다(`axt/core.py:2258`).

---

## SC-INT-002: vault ↔ 전역 심볼릭 링크 ↔ `~/.agents/skills` 미러

- **Objective**: `link-global` / `unlink-global` 이 `~/.claude/<type>s/` 링크와
  `~/.agents/skills/` 미러를 각각 독립적으로 관리하고, `.skill-lock.json` 가드가
  서드파티 설치기 트리를 보호하는지 검증한다. (US-VLT05, US-VLT06)
- **Priority**: Critical
- **Preconditions**:
  - vault에 `skill:alpha` 실체(`tmp_path/vault/skills/alpha/SKILL.md`)
  - `monkeypatch.setattr("axt.HOME", tmp_path/"home")` 로 `~/.agents` 격리
  - `sys.platform != "win32"` (심볼릭 링크 필요; Windows는 US-VLT05 AC4가 별도 소유)
- **Steps**:
  1. 전역 링크 + 미러를 함께 생성한다
  2. 미러가 `~/.claude/skills` 를 경유하지 않고 vault 실체를 직접 가리키는지 확인한다
  3. `.skill-lock.json` 을 심어 두고 다시 시도한다
  4. 해제 시 미러가 "이 vault 항목을 가리킬 때만" 지워지는지 확인한다
- **Expected Result**: 미러 링크의 `os.path.realpath` 가 vault 실체와 같고, 잠긴
  트리에서는 `(False, ".skill-lock.json present …")` 로 거부되며, 해제는 vault 실체를
  남긴다.
- **Notes**: 미러는 `skill` 타입에만 적용된다(US-VLT06 AC5).

---

## SC-INT-003: `migrate_to_vault` — 실체 이동 + 원위치 심볼릭 링크 + broken 리포트

- **Objective**: 전역에 흩어진 확장을 vault로 **이동**하면서 Claude Code가 계속
  찾을 수 있도록 원위치에 링크를 남기고, 대상이 사라진 심볼릭 링크는 **삭제하지 않고**
  리포트만 하는지 검증한다. (US-VLT01, US-SYS05)
- **Priority**: Critical
- **Preconditions**:
  - `tmp_path/claude/{skills,commands,agents}` 에 실체 · 이미 vault를 가리키는 링크 ·
    대상이 없는 broken 링크를 각각 배치
  - `PATHS.claude_dir`, `PATHS.vault` 를 `tmp_path` 하위로 고정
- **Steps**:
  1. 세 종류가 섞인 전역 디렉터리에서 마이그레이션한다
  2. `MigrateResult` 의 moved / skipped / broken / errors 분류를 확인한다
  3. broken 링크가 디스크에 그대로 남았는지 확인한다
- **Expected Result**: 실체는 vault로 이동하고 원위치에는 vault를 가리키는 심볼릭
  링크가 남으며, broken 링크는 `broken` 으로만 집계되고 파일시스템에서 사라지지 않는다.
- **Notes**: `find_broken_links` 와 `migrate_to_vault(...).broken` 은 같은 사실을 두
  경로로 보고한다 — 두 값의 **정합**이 이 시나리오의 연동 지점이다.

---

## SC-INT-004: 마켓플레이스 레지스트리 ↔ vault install 파이프라인

- **Objective**: `market add` 로 등록한 마켓플레이스의 **installLocation** 이
  `vault install` 의 소스 해석에 실제로 쓰이는지, 그 결과가 `vault list` 에 나타나는지
  검증한다. (US-MKT01, US-VLT04, US-VLT02)
- **Priority**: High
- **Preconditions**:
  - `dir:` 소스용 외부 디렉터리 `tmp_path/external-mkt/` 에
    `.claude-plugin/marketplace.json` + 플러그인 트리 배치
  - `PATHS.known_marketplaces`, `PATHS.marketplaces`, `PATHS.vault` 를 각각
    `tmp_path` 하위 서로 다른 경로로 고정 (레지스트리 경로 ≠ 설치 경로)
  - `find_plugin_source_dir` 을 **stub하지 않는다** — 해석 경로 자체가 검증 대상
- **Steps**:
  1. 외부 디렉터리를 `dir:` 마켓플레이스로 등록한다
  2. 등록 정보(`known_marketplaces.json`)의 `installLocation` 을 확인한다
  3. 그 마켓플레이스명으로 vault install을 수행한다
  4. vault 목록에 항목이 나타나는지 확인한다
- **Expected Result**: 등록된 `installLocation` 아래에서 플러그인 소스가 해석되고,
  vault의 해당 타입 하위에 복사되어 `list_vault_items` 에 나타난다.
- **Notes**: 현재 구현은 레지스트리를 보지 않고 `PATHS.marketplaces / <name>` 을
  고정 조합한다(`axt/cli.py:906`). `dir:` 로 등록한 외부 경로 마켓에서는 이 조합이
  존재하지 않으므로 실패한다 — 스펙 갭 §G-2 참조.

---

## SC-INT-005: 플러그인 활성 상태가 5개 목록에 파급되는가

- **Objective**: 활성 플러그인이 MCP 서버 · 훅 · 스킬 · 명령 · 에이전트 각 목록에
  기여하고, 비활성 플러그인은 어느 목록에도 나타나지 않는지 검증한다.
  (US-PLG06, US-LNK01, US-MCP01, US-HK01)
- **Priority**: High
- **Preconditions**:
  - `installed_plugins.json` 에 플러그인 1개 등록 + 설치 디렉터리에
    `plugin.json`(mcpServers) · `hooks/hooks.json` · `skills/` · `commands/` · `agents/`
  - `PATHS.settings` 의 `enabledPlugins` 로 활성/비활성을 전환
- **Steps**:
  1. 플러그인을 활성으로 두고 5개 수집 함수를 각각 호출한다
  2. 같은 디스크 상태에서 `enabledPlugins` 만 `false` 로 바꾼다
  3. 5개 목록을 다시 수집한다
- **Expected Result**: 활성일 때 5개 목록 모두에 `source="plugin"` 항목이 들어오고,
  비활성으로 바꾸면 같은 항목이 5개 목록 전부에서 사라진다. 플러그인 훅은 읽기 전용
  으로 표시된다.
- **Notes**: 개별 수집기의 파싱 규칙은 unit 소유. 여기서는 **`enabledPlugins` 한 곳의
  변경이 5개 목록에 동시에 전파되는지**만 본다.

---

## SC-INT-006: settings 스코프 병합 — project local > project > global

- **Objective**: 같은 키가 세 스코프에 있을 때 우선순위가 결정적으로 해석되는지
  검증한다. (US-PLG01, US-HK01)
- **Priority**: High
- **Preconditions**:
  - `~/.claude/settings.json`(global), `<proj>/.claude/settings.json`(project),
    `<proj>/.claude/settings.local.json`(local) 세 파일을 모두 생성
  - `PATHS.settings` = global 경로, `monkeypatch.chdir(<proj>)`
- **Steps**:
  1. 세 스코프에 서로 다른 값을 넣고 해석 결과를 확인한다
  2. 상위 스코프만 남기고 하위를 지웠을 때 결과가 바뀌는지 확인한다
  3. 어느 스코프에도 없을 때 `unset` 으로 구분되는지 확인한다
- **Expected Result**: FEATURES.md §3.3 의 우선순위대로 project local이 project를,
  project가 global을 덮는다. 미설정은 `False` 가 아니라 `unset` 으로 남는다.
- **Notes**: 훅은 `local` 소스를 별도 항목으로 병합하지만(`axt/core.py:1433`),
  `enabledPlugins` 계열에는 `settings.local.json` 을 읽는 경로가 없다 —
  스펙 갭 §G-1 참조.

---

## SC-INT-007: usage JSONL → `UnifiedUsageEntry` → pricing → 비용, mtime 캐시 경유

- **Objective**: 디스크의 JSONL이 파서 → 어댑터 → 가격표를 거쳐 비용이 되고, 그 결과가
  mtime 기반 v2 캐시를 통해 재사용되며, v1 캐시는 폐기 후 재빌드되는지 검증한다.
  (US-USG06, US-USG08)
- **Priority**: Critical
- **Preconditions**:
  - `tmp_path/claude_projects/<proj>/<session>.jsonl` 에 알려진 토큰 수의 엔트리
  - `axt._cache_path` 가 가리키는 캐시 파일을 `tmp_path` 하위로 고정
  - **mtime과 `datetime.now()` 를 섞지 않는다** — 캐시 유효성은 `is_cache_valid` 의
    `lastUpdated` 를 직접 심어 고정하고, 파일 mtime은 `os.utime` 으로 명시 지정
- **Steps**:
  1. 최초 로드 후 캐시 파일의 스키마(`version: 2`, intern 테이블)를 확인한다
  2. 파일을 건드리지 않고 재로드해 재파싱이 일어나지 않는지 확인한다
  3. `version: 1` 캐시를 심어 두고 로드한다
  4. 가격표에 없는 모델을 섞어 비용 집계와 경고 노출을 확인한다
- **Expected Result**: 비용은 input·output·cacheWrite·cacheRead 4종 합이고, 변경 없는
  파일은 재파싱되지 않으며, v1 캐시는 마이그레이션 없이 폐기 후 v2로 재빌드된다.
  미등록 모델은 비용 0으로 집계되고 `find_unpriced_models` 에 드러난다.
- **Notes**: 5시간 블록 anchoring(UTC)과 기간 컷오프(사용자 timezone)의 규칙 자체는
  unit 소유. 여기서는 **파일 → 캐시 → 비용** 연결만 본다.

---

## SC-INT-008: 컨텍스트 분석이 디스크의 12개 카테고리를 실제로 수집하는가

- **Objective**: 하나의 실제 디스크 상태에서 `collect_context_sources` 가 12개
  카테고리를 모두 채우고, Claude Code가 읽지 않는 경로는 제외하는지 검증한다.
  (US-CTX01, US-CTX03)
- **Priority**: High
- **Preconditions**:
  - `tmp_path` 아래에 12개 카테고리를 모두 생산하는 픽스처를 한 번에 배치
    (CLAUDE.md · settings 4곳 · memory · skills · MCP · plugins · hooks · commands ·
    agents · git repo)
  - `axt.get_claude_version` / `axt.get_git_status` 를 고정값으로 monkeypatch
    (외부 명령 · 실행 환경 비의존)
  - `~/.agents/skills` 와 `<proj>/.agents/agents` 에 함정 항목을 배치
- **Steps**:
  1. 준비된 디스크 상태에서 소스를 수집한다
  2. 카테고리 집합을 `CATEGORY_LABELS` 의 12개 키와 대조한다
  3. `.agents` 하위 함정 항목이 결과에 없는지 확인한다
  4. 비활성 MCP 서버가 제외되는지 확인한다
- **Expected Result**: 12개 카테고리가 모두 1건 이상으로 나타나고, `.agents/skills` ·
  `.agents/agents` 항목과 disabled MCP 서버는 집계에서 빠진다.
- **Notes**: 토큰 추정 함수(`estimate_tokens`)의 CJK 가중치는 unit 소유.

---

## SC-INT-009: update 오케스트레이션 ↔ git-backed 항목 ↔ 마켓 pre-sync

- **Objective**: `check_all_updates` 가 타입별 updater를 모아 티어를 붙이고,
  `apply_updates` 가 Tier-1만 적용하며, `--no-sync` 가 플러그인 적용 전 마켓
  동기화를 실제로 건너뛰는지 검증한다. (US-UPD01, US-UPD02, US-UPD04)
- **Priority**: High
- **Preconditions**:
  - 실제 git 저장소 2개(`git init` + 커밋)를 `tmp_path` 에 만들어 skill/command로 연결
  - `axt.core._git` 호출 중 네트워크가 필요한 `fetch` 만 stub하고, 로컬 `rev-parse` ·
    `pull` 은 실제 실행 (외부 네트워크 비의존 · 결정적)
  - `_kick_update_check` 는 conftest의 autouse 픽스처가 이미 무력화한다
- **Steps**:
  1. git-backed 항목과 non-git 항목을 섞어 전체 확인을 돌린다
  2. 티어별 그룹(Tier1 / Tier2 / Tier3)을 확인한다
  3. Tier-1만 적용하고 Tier-2·3 대상이 건드려지지 않았는지 확인한다
  4. `no_sync=True` 로 플러그인을 적용하고 마켓 동기화 호출 여부를 확인한다
- **Expected Result**: MCP·non-git은 리포트에만 남고 디스크가 변하지 않으며,
  `claude-code` 는 명시 타깃팅 없이는 적용 대상에 들어가지 않는다.
- **Notes**: dry-run 리포트의 **출력 형태**는 api 소유(`tests/test_cli.py`).

---

## SC-INT-010: `scan_project_usage` ↔ vault `Used` 컬럼

- **Objective**: `~/.claude/projects/*` 를 훑어 만든 사용 인덱스가 vault 항목별
  프로젝트 수로 이어지고, default / full 모드의 수집 범위 차이가 결과에 드러나는지
  검증한다. (US-VLT07)
- **Priority**: High
- **Preconditions**:
  - `PATHS.projects` 아래에 인코딩된 프로젝트 폴더 2개(`-tmp-...-projA` 형태)
  - 실제 프로젝트 디렉터리에 `.axt-profile.json` · vault를 가리키는 심볼릭 링크 ·
    `enabledPlugins` 를 각각 다른 프로젝트에 배치
  - **cwd 격리**: `monkeypatch.chdir(tmp_path)`; 폴더명 디코딩이 파일시스템을 훑으므로
    `fs_root` 를 `tmp_path` 로 넘겨 호스트 디렉터리를 스캔하지 않게 한다
- **Steps**:
  1. default 모드로 스캔해 프로필 + 심볼릭 링크만 잡히는지 확인한다
  2. full 모드로 스캔해 플러그인 설정까지 포함되는지 확인한다
  3. 스캔 결과가 없는 항목이 0건으로 처리되는지 확인한다
- **Expected Result**: `get_project_count` 가 모드에 따라 다른 값을 돌려주고, 스캔
  대상이 없어도 예외 없이 빈 인덱스가 된다.
- **Notes**: 인덱스 → 화면 글리프(`Used` 셀) 변환은 e2e 소유.

---

## SC-INT-011: TUI 키 핸들러가 core를 통해 실제 파일을 바꾸고 다음 조회에 반영되는가

- **Objective**: `handle_vault_input` / `_handle_subtab_action` 이 core 함수를 호출해
  디스크를 바꾼 뒤, 같은 상태에서 다시 읽은 목록이 그 변화를 반영하는지 검증한다.
  (US-VLT09, US-LNK04)
- **Priority**: Critical
- **Preconditions**:
  - vault + 프로젝트 + 전역 디렉터리를 `tmp_path` 하위로 고정
  - `state.stdscr_callbacks = None` 로 두어 확인 모달 없이 직접 적용되는 헤드리스
    경로를 탄다(`axt/tui/tabs.py:1204`)
  - conftest의 `_no_async_update_sweep` 이 백그라운드 스윕을 이미 차단한다
- **Steps**:
  1. `p` 로 pending을 쌓고 `Enter` 로 적용한다
  2. 디스크에 심볼릭 링크와 프로필 항목이 함께 생겼는지 확인한다
  3. `_vault_load` 후 항목의 `is_linked` 가 뒤집혔는지 확인한다
  4. 파일 항목 서브탭에서 `g` 토글이 실제 심볼릭 링크를 만들고 지우는지 확인한다
- **Expected Result**: 키 한 번 → core 호출 → 디스크 변경 → 재조회 결과 반영이 한
  사이클로 이어지고, 실체 파일은 어느 경로에서도 삭제되지 않는다.
- **Notes**: 화면에 그려지는 글리프(`●`/`○`)까지의 확인은 e2e 소유.

---

## SC-INT-012: `_invalidate_context` — 링크 변화만 캐시를 무효화한다

- **Objective**: 파일시스템을 실제로 바꾼 조작만 컨텍스트 분석 캐시를 떨어뜨리고,
  아무것도 바꾸지 않은 조작은 캐시를 유지하는지 검증한다. (US-PRJ05)
- **Priority**: High
- **Preconditions**:
  - `state.context_analysis` 에 센티넬 분석 객체를 미리 넣어 둔다
  - vault · 프로젝트 경로를 `tmp_path` 하위로 고정
  - `_invalidate_context` **자체를 monkeypatch하지 않는다** — 호출 여부가 아니라
    캐시 상태의 변화를 본다(순수 위임 검증 금지)
- **Steps**:
  1. 실제로 링크가 바뀌는 sync를 수행한다
  2. 이미 정합인 상태에서 sync를 한 번 더 수행한다
  3. 마이그레이션 대상이 없는 상태에서 migrate를 수행한다
- **Expected Result**: 변화가 있을 때만 `state.context_analysis is None` 이 되고,
  변화가 없으면 이전 분석 객체가 그대로 남는다. detail 포커스/스크롤도 함께 초기화된다.
- **Notes**: 무효화 이후의 재분석은 지연 수행(`_ensure_context_loaded`)이므로 이
  시나리오에서 재분석 결과까지 확인하지 않는다.

---

## 스펙 갭

문서(FEATURES.md / user-stories.md)와 구현이 어긋나거나, 스토리가 요구하는 동작의
구현 경로를 찾을 수 없는 항목. **여기에 스토리를 새로 만들지 않는다** — 발견 사실만
기록하고 후속 단계(gap-code / triage)의 판단에 넘긴다.

### G-1. `settings.local.json` 우선순위가 플러그인 활성 판정에 반영되지 않음
- 스펙: FEATURES.md §3.3 "우선순위: project local > project > global"
- 구현: `read_enabled_plugins` 는 단일 스코프 리더이고, 호출자
  (`axt/cli.py:441`, `axt/tui/tabs.py:_scope_ctx`)는 global · project 두 곳만 읽는다.
  `settings.local.json` 을 읽는 경로가 없다.
- 영향: SC-INT-006 / TC-INT-019.

### G-2. `vault install` 이 마켓플레이스 레지스트리의 `installLocation` 을 쓰지 않음
- 스펙: US-VLT04 AC3, US-MKT01 AC1(세 소스 형태를 같은 방식으로 사용)
- 구현: `cli_vault_install` 이 `PATHS.marketplaces / args.marketplace` 를 고정 조합
  한다(`axt/cli.py:906`). `dir:` 로 등록해 `installLocation` 이 외부 경로인 마켓에서는
  이 경로가 존재하지 않는다.
- 영향: SC-INT-004 / TC-INT-012.

### G-3. `plugin search` 에 마켓플레이스 검색 구현이 없음
- 스펙: US-PLG05 AC1·AC2(결과 0건도 exit 0, 결과에 소속 마켓플레이스 표시)
- 구현: `cli_plugin_search` 는 안내 문구만 출력하고 검색을 수행하지 않는다
  (`axt/cli.py:524`). 따라서 "결과에 소속 마켓플레이스가 표시된다"를 만족할 경로가 없다.
- 영향: SC-INT-004에서 search 단계를 제외했다. 검색 구현 전에는 TC를 세울 수 없다.

### G-4. 플러그인 활성 판정이 우선순위가 아니라 논리합(OR)
- 스펙: US-PLG01 AC2 "활성 상태는 project settings > global settings 순으로 해석된다"
- 구현: `is_active = gv is True or pv is True` (`axt/cli.py:453`) — project가 명시적
  `false` 여도 global이 `true` 면 활성으로 집계된다.
- 영향: SC-INT-006 / TC-INT-020.
