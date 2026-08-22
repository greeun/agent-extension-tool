# Integration Test Cases

> Target: axt — 모듈 간 연동(실제 파일시스템 상태 변화 포함)
> Date: 2026-08-22
> Author: full-test-orchestrator (Phase B, Agent 2)
> Scenarios: [integration-scenarios.md](../scenarios/integration-scenarios.md)

## 요약

| 항목 | 값 |
|---|---|
| **총 TC 수** | 42 |
| **시나리오 수** | 12 (SC-INT-001 ~ SC-INT-012) |

### 우선순위 분포

| Priority | 수 |
|---|---|
| Critical | 15 |
| High | 22 |
| Medium | 5 |
| Low | 0 |

### Gap 분포

| Gap | 수 | 의미 |
|---|---|---|
| COVERED | 19 | 기존 테스트가 같은 연동 지점을 이미 단언 — 새로 쓰지 않는다 |
| PARTIAL | 19 | 구성 요소는 검증돼 있으나 **연쇄**나 **상태 스냅샷**이 빠짐 |
| NEW | 4 | 해당 연동을 단언하는 테스트가 없음 |

> Gap 판정은 `grep -rn "<대상함수>" tests/` 로 기존 파일을 먼저 찾은 결과다.
> `COVERED` 는 파일명을, 가능하면 테스트 이름까지 적었다.

---

## SC-INT-001 — vault ↔ `.axt-profile.json` ↔ 프로젝트 심볼릭 링크

### TC-INT-001: vault 항목 링크가 심볼릭 링크와 프로필 항목을 동시에 만든다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-001 |
| **US** | US-PRJ02 AC1, US-VLT05 |
| **Priority** | Critical |
| **Preconditions** | `tmp_path/vault/skills/alpha/SKILL.md` 존재. `monkeypatch.setattr("axt.PATHS", axt.Paths(vault=tmp_path/"vault", claude_dir=tmp_path/"claude"))`, `monkeypatch.chdir(tmp_path/"proj")` |
| **Input** | `VaultItem(name="alpha", type="skill", path=str(tmp_path/"vault/skills/alpha"))` |
| **Gap** | COVERED — `tests/test_vault.py::test_link_to_project_creates_symlink_and_updates_profile`, `tests/test_cli.py::test_project_add_then_remove_roundtrip` |

**Steps**:
1. `axt.link_to_project(proj, item)` 호출
2. `proj/".claude"/"skills"/"alpha"` 의 `is_symlink()` 확인
3. `axt.read_profile(proj).skills` 확인

**Expected Output**: 심볼릭 링크가 `tmp_path/vault/skills/alpha` 를 가리키고 프로필의 `skills` 에 `"alpha"` 가 들어 있다.
**Actual Output**: —
**Status**: —

---

### TC-INT-002: 프로필과 실제 링크가 어긋나면 sync가 양방향으로 정렬한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-001 |
| **US** | US-PRJ03 AC1·AC2·AC3 |
| **Priority** | Critical |
| **Preconditions** | vault에 `skill:alpha`, `skill:beta`. 프로필은 `skills=("alpha",)` 만 선언. 디스크에는 `beta` 심볼릭 링크만 존재(=완전히 반대 상태) |
| **Input** | `sync_project(proj, tmp_path/"vault")` |
| **Gap** | COVERED — `tests/test_vault.py::test_sync_project_links_declared_and_unlinks_orphans` |

**Steps**:
1. 어긋난 상태를 디스크에 만든다
2. `sync_project` 를 호출한다
3. `SyncResult.linked` / `.unlinked` / `.errors` 를 확인한다
4. `.claude/skills/` 의 엔트리 집합을 확인한다

**Expected Output**: `linked == ("skill:alpha",)`, `unlinked == ("skill:beta",)`, `errors == ()`. 디렉터리에는 `alpha` 만 남는다.
**Actual Output**: —
**Status**: —

---

### TC-INT-003: sync는 vault 밖을 가리키는 외부 링크를 건드리지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-001 |
| **US** | US-PRJ03 AC2, US-SYS08 AC3 |
| **Priority** | Critical |
| **Preconditions** | 프로필은 비어 있고, `.claude/skills/foreign` 이 `tmp_path/elsewhere/foreign` (vault 밖)을 가리킨다 |
| **Input** | `sync_project(proj, tmp_path/"vault")` |
| **Gap** | COVERED — `tests/test_vault.py::test_sync_project_leaves_foreign_symlink` |

**Steps**:
1. vault 밖을 가리키는 심볼릭 링크를 만든다
2. sync를 호출한다
3. 링크가 남았는지, `unlinked` 에 포함되지 않았는지 확인한다

**Expected Output**: `unlinked == ()` 이고 `.claude/skills/foreign` 은 그대로 심볼릭 링크로 남는다.
**Actual Output**: —
**Status**: —

---

### TC-INT-004: `project status` 는 파일시스템을 한 바이트도 바꾸지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-001 |
| **US** | US-PRJ04 AC1 |
| **Priority** | High |
| **Preconditions** | 프로필에 `skills=("alpha","beta")`, 디스크에는 `alpha` 링크만. `monkeypatch.chdir(proj)` |
| **Input** | `axt.cli.cli_project_status(argparse.Namespace())` |
| **Gap** | PARTIAL — `tests/test_cli.py::test_project_status_reports_linked_and_missing` 은 출력만 단언한다. 디스크 불변 스냅샷 비교가 없다 |

**Steps**:
1. 실행 전 `sorted(os.walk(proj))` 와 각 파일의 `(st_mtime_ns, st_size)` 를 스냅샷으로 잡는다
2. `cli_project_status` 를 호출한다
3. 같은 스냅샷을 다시 잡아 비교한다

**Expected Output**: 두 스냅샷이 동일하다 — `.claude/skills/beta` 가 생기지도, 프로필이 다시 쓰이지도 않는다.
**Actual Output**: —
**Status**: —

---

## SC-INT-002 — vault ↔ 전역 링크 ↔ `~/.agents/skills` 미러

### TC-INT-005: 미러 링크는 `~/.claude/skills` 를 경유하지 않고 vault를 직접 가리킨다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-002 |
| **US** | US-VLT06 AC1 |
| **Priority** | Critical |
| **Preconditions** | `tmp_path/vault/skills/alpha/SKILL.md`. `monkeypatch.setattr("axt.HOME", tmp_path/"home")`. `pytest.mark.skipif(sys.platform == "win32")` |
| **Input** | `link_to_global(claude_dir, item)` → `link_to_agents(home/".agents", item)` |
| **Gap** | COVERED — `tests/test_vault.py::test_link_to_agents_mirrors_skill_pointing_at_vault` |

**Steps**:
1. 전역 링크를 만든다
2. 미러를 만든다
3. `os.readlink(home/".agents"/"skills"/"alpha")` 를 확인한다

**Expected Output**: 미러의 링크 대상이 `tmp_path/vault/skills/alpha` 이고 `tmp_path/claude/skills/alpha` 가 아니다.
**Actual Output**: —
**Status**: —

---

### TC-INT-006: `.skill-lock.json` 트리는 기본 거부, `force=True` 로만 통과

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-002 |
| **US** | US-VLT06 AC2·AC3 |
| **Priority** | Critical |
| **Preconditions** | `home/".agents"/".skill-lock.json"` 존재. vault에 `skill:alpha` |
| **Input** | `link_to_agents(agents_dir, item)` / `link_to_agents(agents_dir, item, force=True)` |
| **Gap** | COVERED — `tests/test_vault.py::test_link_to_agents_guarded_by_skill_lock` (force 우회 포함, `tests/test_vault.py:313`) |

**Steps**:
1. 잠금 파일이 있는 상태에서 미러를 시도한다
2. 반환값과 `skills/` 디렉터리 생성 여부를 확인한다
3. `force=True` 로 재시도한다

**Expected Output**: 첫 호출은 `(False, ".skill-lock.json present — …")` 이고 링크가 생기지 않는다. `force=True` 는 `(True, …)` 로 링크를 만든다.
**Actual Output**: —
**Status**: —

---

### TC-INT-007: `unlink-global` 은 링크만 지우고 vault 실체와 남의 링크를 보존한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-002 |
| **US** | US-VLT05 AC2, US-VLT06 AC4 |
| **Priority** | Critical |
| **Preconditions** | 전역 링크 + 미러가 걸린 상태, 그리고 `home/".agents"/"skills"/"other"` 가 vault 밖을 가리키는 남의 심볼릭 링크 |
| **Input** | `unlink_from_global(claude_dir, item)` → `unlink_from_agents(agents_dir, item)` |
| **Gap** | COVERED — `tests/test_vault.py::test_link_unlink_global`, `::test_unlink_from_agents_only_removes_matching_link`, `::test_unlink_from_agents_leaves_foreign_symlink` |

**Steps**:
1. 전역 해제 후 vault 실체가 남았는지 확인한다
2. 미러 해제 후 `other` 링크가 남았는지 확인한다

**Expected Output**: `tmp_path/vault/skills/alpha/SKILL.md` 는 존재하고, `other` 는 삭제되지 않는다.
**Actual Output**: —
**Status**: —

---

### TC-INT-008: CLI `--mirror-agents` 결과가 `list_vault_items_with_project_state` 의 `is_agents_linked` 로 되돌아온다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-002 |
| **US** | US-VLT06 AC1, US-VLT02 AC3 |
| **Priority** | High |
| **Preconditions** | `PATHS` 를 `tmp_path` 하위로 고정, `axt.HOME` 격리. 잠금 파일 없음 |
| **Input** | `axt vault link-global skill alpha --mirror-agents` → `list_vault_items_with_project_state(vault, proj, global_dir=..., agents_dir=home/".agents")` |
| **Gap** | PARTIAL — `tests/test_cli.py::test_vault_link_global_then_unlink` 는 `--mirror-agents` 를 태우지 않고, `tests/test_vault.py::test_list_vault_items_enriches_is_agents_linked` 는 CLI를 거치지 않는다. 두 구간을 잇는 테스트가 없다 |

**Steps**:
1. CLI로 미러 포함 전역 링크를 만든다
2. 같은 경로들로 enrich 목록을 조회한다
3. `alpha` 항목의 `is_global_linked` / `is_agents_linked` 를 확인한다

**Expected Output**: 두 플래그 모두 `True`. 이어서 CLI로 `unlink-global --mirror-agents` 하면 둘 다 `False` 로 돌아온다.
**Actual Output**: —
**Status**: —

---

## SC-INT-003 — `migrate_to_vault`

### TC-INT-009: 전역 실체가 vault로 이동하고 원위치에 vault를 가리키는 링크가 남는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-003 |
| **US** | US-VLT01 AC1·AC3 |
| **Priority** | Critical |
| **Preconditions** | `tmp_path/claude/skills/alpha/SKILL.md`(실체), `tmp_path/claude/commands/c1.md`(실체). vault 비어 있음 |
| **Input** | `migrate_to_vault(tmp_path/"claude", tmp_path/"vault")` |
| **Gap** | COVERED — `tests/test_vault.py::test_migrate_to_vault_moves_global_items`, `::test_migrate_skips_existing` |

**Steps**:
1. 마이그레이션한다
2. vault 하위에 실체가 있는지 확인한다
3. `MigrateResult.moved` 를 확인한다

**Expected Output**: `moved == ("skill:alpha", "command:c1")`, vault에 실체가 있고 원위치에는 심볼릭 링크가 남는다.
**Actual Output**: —
**Status**: —

---

### TC-INT-010: broken 심볼릭 링크는 이동하지 않고 리포트만 되며 삭제되지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-003 |
| **US** | US-VLT01 AC2, US-SYS05 AC2 |
| **Priority** | Critical |
| **Preconditions** | `tmp_path/claude/skills/dead` → `tmp_path/gone`(존재하지 않음) 심볼릭 링크 |
| **Input** | `migrate_to_vault(...)` |
| **Gap** | COVERED — `tests/test_vault.py::test_migrate_reports_broken_symlink_not_skipped` |

**Steps**:
1. 대상이 없는 링크를 만든다
2. 마이그레이션한다
3. `result.broken` 과 `Path(...).is_symlink()` 를 확인한다

**Expected Output**: `broken == ("skill:dead",)`, `moved == ()`, 링크는 디스크에 그대로 남는다.
**Actual Output**: —
**Status**: —

---

### TC-INT-011: `migrate_to_vault(...).broken` 과 `find_broken_links` 가 같은 집합을 보고한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-003 |
| **US** | US-VLT01 AC2, US-SYS05 AC2 |
| **Priority** | High |
| **Preconditions** | skills·commands·agents 세 디렉터리에 각각 broken 링크 1건씩(총 3건), 정상 실체 1건 |
| **Input** | `find_broken_links(claude_dir)` 와 `migrate_to_vault(claude_dir, vault).broken` |
| **Gap** | PARTIAL — 두 함수는 각각 `tests/test_vault.py::test_find_broken_links`, `::test_migrate_reports_broken_symlink_not_skipped` 로 검증돼 있으나 **두 결과의 정합**을 대조하는 테스트가 없다 |

**Steps**:
1. 세 타입에 broken 링크를 배치한다
2. `find_broken_links` 결과를 받는다
3. 마이그레이션 후 `result.broken` 을 받는다
4. 두 집합을 정렬해 비교한다

**Expected Output**: `sorted(result.broken) == find_broken_links(claude_dir)` 이며 세 항목 모두 `"{type}:{name}"` 형식이다. 마이그레이션 후에도 세 링크가 디스크에 남아 두 번째 `find_broken_links` 결과가 동일하다.
**Actual Output**: —
**Status**: —

---

## SC-INT-004 — 마켓플레이스 레지스트리 ↔ vault install

### TC-INT-012: `dir:` 로 등록한 외부 마켓에서 vault install이 성공한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-004 |
| **US** | US-VLT04 AC3, US-MKT01 AC1·AC3 |
| **Priority** | High |
| **Preconditions** | `tmp_path/external-mkt/.claude-plugin/marketplace.json` 에 `{"plugins":[{"name":"pkg","source":"./plugins/pkg"}]}`, `tmp_path/external-mkt/plugins/pkg/.claude-plugin/plugin.json` 존재. `PATHS.marketplaces = tmp_path/"mks"`(비어 있음), `PATHS.known_marketplaces = tmp_path/"km.json"`, `PATHS.vault = tmp_path/"vault"`. **`find_plugin_source_dir` 을 stub하지 않는다** |
| **Input** | `axt market add dir:{tmp_path}/external-mkt` → `axt vault install external-mkt pkg -t skill` |
| **Gap** | NEW — `tests/test_cli.py::test_vault_install_success` 는 `find_plugin_source_dir` 을 stub해 레지스트리 → 설치 경로 연결을 우회한다. 스펙 갭 §G-2 대상 |

**Steps**:
1. 외부 디렉터리를 `dir:` 마켓으로 등록한다
2. `known_marketplaces.json` 의 `installLocation` 이 외부 경로인지 확인한다
3. vault install을 수행한다
4. `list_vault_items(PATHS.vault)` 에 `pkg` 가 있는지 확인한다

**Expected Output**: 등록된 `installLocation` 아래에서 소스가 해석되어 `tmp_path/vault/skills/pkg/` 가 생기고 `list_vault_items` 가 `name="pkg", type="skill"` 을 돌려준다.
**Actual Output**: —
**Status**: —

---

### TC-INT-013: `market remove` 는 axt가 설치한 디렉터리만 지운다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-004 |
| **US** | US-MKT04 AC1, US-SYS08 AC4 |
| **Priority** | High |
| **Preconditions** | 마켓 2건 — `dir:` 로 등록한 외부 경로 1건, `PATHS.marketplaces` 하위에 설치된 1건 |
| **Input** | `remove_marketplace(km, PATHS.marketplaces, name)` 를 두 마켓에 각각 |
| **Gap** | COVERED — `tests/test_marketplace.py::test_remove_marketplace_directory_keeps_external_dir`, `::test_remove_marketplace_owned_dir_deleted` |

**Steps**:
1. 외부 경로 마켓을 제거하고 디렉터리 존재를 확인한다
2. 소유 디렉터리 마켓을 제거하고 디렉터리 존재를 확인한다

**Expected Output**: 외부 디렉터리는 남고, `PATHS.marketplaces` 하위 디렉터리만 삭제된다. 두 경우 모두 레지스트리에서는 사라진다.
**Actual Output**: —
**Status**: —

---

### TC-INT-014: vault install 실패가 vault 상태를 오염시키지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-004 |
| **US** | US-VLT04 AC1·AC2, US-VLT02 AC2 |
| **Priority** | Medium |
| **Preconditions** | 등록된 마켓 없음. `PATHS.vault` 는 존재하지만 비어 있음 |
| **Input** | `axt vault install no-such-mkt pkg` 이후 `list_vault_items(PATHS.vault)` |
| **Gap** | PARTIAL — `tests/test_cli.py::test_vault_install_missing_in_marketplace` 는 exit code와 메시지(api 소유)만 본다. 실패 후 vault 상태 불변은 확인하지 않는다 |

**Steps**:
1. 실행 전 vault 하위 엔트리 목록을 스냅샷으로 잡는다
2. 없는 마켓명으로 install을 시도한다
3. vault 하위 엔트리 목록을 다시 잡는다

**Expected Output**: 두 목록이 같고 부분 복사된 디렉터리가 남지 않는다. `list_vault_items` 는 `[]` 를 돌려준다.
**Actual Output**: —
**Status**: —

---

## SC-INT-005 — 플러그인 활성 상태의 5개 목록 파급

### TC-INT-015: 활성 플러그인이 skills·commands·agents 목록에 `plugin` 출처로 나타난다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-005 |
| **US** | US-PLG06 AC3, US-LNK01 AC3 |
| **Priority** | High |
| **Preconditions** | `installed_plugins.json` 에 `pg@mk`, 설치 디렉터리에 `skills/s1/SKILL.md`, `commands/c1.md`, `agents/a1.md`. `PATHS.settings` 의 `enabledPlugins = {"pg@mk": True}` |
| **Input** | `list_all_skills(project_dir=cwd)`, `list_commands(project_dir=cwd)`, `list_all_agents(project_dir=cwd)` |
| **Gap** | COVERED — `tests/test_commands_agents.py::test_list_commands_includes_enabled_plugin`, `::test_list_all_agents_includes_enabled_plugin`; 스킬은 `tests/test_skill.py` |

**Steps**:
1. 활성 상태로 세 목록을 조회한다
2. 각 목록에서 `source == "plugin"` 항목을 찾는다

**Expected Output**: 세 목록 모두에 해당 항목이 있고 `plugin` 필드가 `"pg@mk"` 다.
**Actual Output**: —
**Status**: —

---

### TC-INT-016: `enabledPlugins` 를 `false` 로 바꾸면 5개 목록에서 동시에 사라진다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-005 |
| **US** | US-PLG06 AC1·AC2·AC3, US-MCP01 AC1, US-HK01 AC1 |
| **Priority** | Critical |
| **Preconditions** | TC-INT-015 의 픽스처에 더해 `plugin.json` 의 `mcpServers` 1건, `hooks/hooks.json` 의 `SessionStart` 훅 1건 |
| **Input** | `set_plugin_enabled(PATHS.settings, "pg@mk", False)` 이후 5개 수집기 재호출 |
| **Gap** | PARTIAL — 개별 목록의 disabled 분기는 `tests/test_commands_agents.py::test_list_commands_skips_disabled_plugin`, `tests/test_context.py::test_collect_context_skips_disabled_plugin` 에 있으나, **한 번의 설정 변경이 5개 목록 전부에 전파되는지**를 한 테스트로 확인하지 않는다 |

**Steps**:
1. 활성 상태의 5개 목록에서 plugin 항목 수를 센다
2. 설정만 `False` 로 바꾼다(디스크의 플러그인 트리는 그대로)
3. 5개 목록을 다시 조회한다

**Expected Output**: 활성일 때 5개 모두 1건 이상, 비활성 후 5개 모두 0건. 플러그인 설치 디렉터리는 삭제되지 않는다.
**Actual Output**: —
**Status**: —

---

### TC-INT-017: 플러그인 훅은 목록에 포함되되 토글이 거부된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-005 |
| **US** | US-PLG06 AC2, US-HK03 AC1·AC2 |
| **Priority** | High |
| **Preconditions** | 활성 플러그인의 `hooks/hooks.json` 에 훅 1건, user settings에 훅 1건 |
| **Input** | `list_hooks(user_settings_path=..., project_dir=..., installed_plugins_path=...)` → plugin 출처 훅에 `_toggle_hook_scope(hook, "global")` |
| **Gap** | PARTIAL — `tests/test_hooks.py::test_list_hooks_includes_plugin_hooks` 가 목록 포함을 보고, `tests/test_tui.py` 가 토글 거부 메시지를 보지만, **거부 후 설정 파일이 변하지 않았음**을 파일 내용으로 확인하지 않는다 |

**Steps**:
1. 훅 목록에서 plugin 출처 항목을 찾는다
2. 토글을 시도한다
3. user settings 파일의 바이트를 조작 전후로 비교한다

**Expected Output**: 반환값이 `(False, "Plugin hooks are read-only (manage them in the plugin)")` 이고 어느 설정 파일도 바뀌지 않는다.
**Actual Output**: —
**Status**: —

---

### TC-INT-018: 활성 플러그인의 MCP 서버가 병합 목록에 scope와 함께 들어온다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-005 |
| **US** | US-PLG06 AC1, US-MCP01 AC1 |
| **Priority** | High |
| **Preconditions** | 활성 플러그인 `plugin.json` 의 `mcpServers.ctx7`, user `~/.claude.json` 의 서버 1건, project `.mcp.json` 의 서버 1건 |
| **Input** | `collect_mcp_servers(_active_plugins())` |
| **Gap** | COVERED — `tests/test_mcp.py::test_collect_combines_plugin_and_config_sources`, `::test_list_mcp_servers_default_scope_is_plugin` |

**Steps**:
1. 세 출처를 배치한다
2. 병합 목록을 조회한다
3. 각 항목의 `scope` 를 확인한다

**Expected Output**: 세 서버가 모두 나오고 scope가 각각 `plugin` / `user` / `project-file` 로 구분된다.
**Actual Output**: —
**Status**: —

---

## SC-INT-006 — settings 스코프 병합

### TC-INT-019: `settings.local.json` 이 project settings보다 우선한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-006 |
| **US** | US-PLG01 AC2 (FEATURES.md §3.3) |
| **Priority** | High |
| **Preconditions** | global `enabledPlugins={"pg@mk": True}`, project `{"pg@mk": False}`, project local `{"pg@mk": True}`. `monkeypatch.chdir(proj)`, `PATHS.settings` = global 경로 |
| **Input** | 세 스코프를 병합해 `pg@mk` 의 활성 상태를 해석 |
| **Gap** | NEW — `settings.local.json` 을 읽는 `enabledPlugins` 경로가 구현에 없다. 스펙 갭 §G-1 대상 |

**Steps**:
1. 세 파일을 각각 작성한다
2. 활성 상태를 해석한다
3. project local을 지우고 다시 해석한다

**Expected Output**: local이 있을 때 `True`, 지우면 project의 `False`. FEATURES.md §3.3 의 `project local > project > global` 순서를 따른다.
**Actual Output**: —
**Status**: —

---

### TC-INT-020: project의 명시적 `false` 가 global의 `true` 를 덮는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-006 |
| **US** | US-PLG01 AC2 |
| **Priority** | High |
| **Preconditions** | global `{"pg@mk": True}`, project `{"pg@mk": False}`, project local 없음. `monkeypatch.chdir(proj)` |
| **Input** | `read_enabled_plugins(PATHS.settings)` + `read_enabled_plugins(project_settings_path())` 병합 해석 |
| **Gap** | NEW — `axt/cli.py:453` 은 `gv is True or pv is True` 로 논리합을 쓴다. 우선순위 해석을 단언하는 테스트가 없다. 스펙 갭 §G-4 대상 |

**Steps**:
1. 두 스코프에 서로 반대 값을 쓴다
2. 활성 상태를 해석한다

**Expected Output**: `False`(project 우선). 논리합 구현에서는 `True` 가 나와 이 TC가 실패한다 — 실패 시 구현 수정 대상이다.
**Actual Output**: —
**Status**: —

---

### TC-INT-021: 어느 스코프에도 없으면 `unset` 으로 남고 `False` 와 구분된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-006 |
| **US** | US-PLG01 AC3 |
| **Priority** | Medium |
| **Preconditions** | global · project settings 모두 `enabledPlugins` 키에 `pg@mk` 없음 |
| **Input** | 두 스코프 조회 결과의 `.get("pg@mk")` |
| **Gap** | PARTIAL — `tests/test_settings.py::test_read_settings_flag_map_missing_key` 가 단일 스코프의 미설정을 보지만, 두 스코프 병합 후 `unset` 이 `False` 와 다르게 남는지는 확인하지 않는다 |

**Steps**:
1. 두 파일 모두 해당 키 없이 만든다
2. 병합 해석 결과를 확인한다
3. 한 쪽만 `False` 로 채워 다시 확인한다

**Expected Output**: 미설정은 `None`(→ 렌더 시 `·`), 명시적 `False` 는 `False`(→ `○`). 둘이 서로 다른 값이다.
**Actual Output**: —
**Status**: —

---

## SC-INT-007 — usage JSONL → 어댑터 → pricing → 캐시

### TC-INT-022: JSONL 4종 토큰이 모델 단가를 거쳐 비용이 된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-007 |
| **US** | US-USG06 AC1 |
| **Priority** | Critical |
| **Preconditions** | `tmp_path/claude_projects/projA/s1.jsonl` 에 `model="claude-sonnet-5"`, `input=1_000_000`, `output=1_000_000`, `cache_creation=1_000_000`, `cache_read=1_000_000` 인 엔트리 1건. 캐시 경로를 `tmp_path` 하위로 고정 |
| **Input** | `load_all_claude_usage(tmp_path/"claude_projects")` → `claude_to_unified` → `calculate_cost` |
| **Gap** | PARTIAL — `tests/test_usage_claude.py::test_compute_blocks_cost_uses_model_pricing_not_hardcoded_opus` 가 블록 단위 비용을 보고 `tests/test_pricing.py` 가 단가를 보지만, **디스크의 JSONL 한 건이 비용으로 이어지는 전체 경로**를 잇는 테스트가 없다 |

**Steps**:
1. JSONL을 쓴다
2. 로드해 `UnifiedUsageEntry` 로 변환한다
3. 비용을 계산한다

**Expected Output**: `3.00 + 15.00 + 3.75 + 0.30 == 22.05` (USD, `pricing.json` 의 claude-sonnet-5 단가 × 각 1M 토큰).
**Actual Output**: —
**Status**: —

---

### TC-INT-023: 변경되지 않은 파일은 재파싱되지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-007 |
| **US** | US-USG08 AC1 |
| **Priority** | High |
| **Preconditions** | 캐시 파일 경로 고정. 파일 mtime은 `os.utime(path, (1_700_000_000, 1_700_000_000))` 으로 명시 지정하고 시계와 섞지 않는다 |
| **Input** | `load_all_claude_usage` 2회 호출, 사이에 `axt.parse_claude_jsonl` 호출 횟수를 카운터로 감싼다 |
| **Gap** | COVERED — `tests/test_usage_claude.py::test_load_all_claude_usage_per_file_cache_hit_skips_reparse` |

**Steps**:
1. 첫 호출로 캐시를 만든다
2. 파서 호출 카운터를 초기화한다
3. 두 번째 호출을 한다

**Expected Output**: 두 번째 호출에서 파서 호출 횟수가 0이고 결과 엔트리는 첫 호출과 동일하다.
**Actual Output**: —
**Status**: —

---

### TC-INT-024: v1 캐시는 마이그레이션 없이 폐기 후 v2로 재빌드된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-007 |
| **US** | US-USG08 AC2·AC3 |
| **Priority** | Critical |
| **Preconditions** | 캐시 파일에 `{"version": 1, "lastUpdated": "<고정 ISO>", "projectsDir": "<같은 경로>", "files": {...옛 스키마...}}` 를 직접 써 둔다. JSONL 1건 존재 |
| **Input** | `load_all_claude_usage(projects_dir)` |
| **Gap** | NEW — v1 캐시를 심어 두고 폐기·재빌드를 확인하는 테스트가 없다 (`grep -rn "version.*1" tests/test_usage_claude.py` 무소득) |

**Steps**:
1. v1 캐시를 심는다
2. 로드한다
3. 캐시 파일을 다시 읽어 스키마를 확인한다
4. 손상된 캐시(잘린 JSON)로 같은 절차를 반복한다

**Expected Output**: 반환 엔트리는 JSONL에서 새로 파싱된 값이고, 캐시 파일은 `version == 2` 에 `models` / `sessions` intern 테이블을 갖는다. 손상 캐시도 예외 없이 재빌드된다.
**Actual Output**: —
**Status**: —

---

### TC-INT-025: 가격표에 없는 모델은 비용 0으로 집계되고 경고 대상으로 드러난다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-007 |
| **US** | US-USG06 AC2·AC3 |
| **Priority** | High |
| **Preconditions** | JSONL에 `model="claude-unknown-9"` 엔트리 1건 + `claude-haiku-4-5` 엔트리 1건 |
| **Input** | `load_all_claude_usage` → `find_unpriced_models(entries)` 와 비용 합계 |
| **Gap** | PARTIAL — `tests/test_pricing.py` 가 `find_unpriced_models` 를 단위로 검증한다. 디스크 JSONL에서 시작해 미등록 모델이 합계에서 빠지는지 잇는 테스트가 없다 |

**Steps**:
1. 두 모델이 섞인 JSONL을 쓴다
2. 로드해 비용을 합산한다
3. `find_unpriced_models` 결과를 확인한다

**Expected Output**: 합계는 haiku 엔트리 비용만 반영하고, `find_unpriced_models` 가 `{"claude-unknown-9": 1}` 을 돌려준다.
**Actual Output**: —
**Status**: —

---

## SC-INT-008 — 컨텍스트 12개 카테고리 수집

### TC-INT-026: 하나의 디스크 상태에서 12개 카테고리가 모두 채워진다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-008 |
| **US** | US-CTX01 AC1 |
| **Priority** | High |
| **Preconditions** | CLAUDE.md · settings 4곳 · memory 1건 · skill 1건 · MCP 1건 · 활성 plugin 1건 · SessionStart 훅 1건 · command 1건 · agent 1건 + `git init` 된 cwd. `monkeypatch.setattr("axt.get_claude_version", lambda: "0.0.0")`, `monkeypatch.setattr("axt.get_git_status", lambda _: " M a.py\n")` |
| **Input** | `collect_context_sources(...)` |
| **Gap** | PARTIAL — `tests/test_context.py` 는 카테고리를 나눠서 검증한다(`test_collect_context_with_plugin_skills_mcp_commands_agents`, `test_collect_context_memory_and_settings`). 12개 전부가 한 상태에서 동시에 나오는지는 확인하지 않는다 |

**Steps**:
1. 12개 카테고리를 모두 생산하는 픽스처를 만든다
2. 소스를 수집한다
3. `{s.category for s in sources}` 를 `set(CATEGORY_LABELS)` 와 비교한다

**Expected Output**: 두 집합이 같다(12개). system-prompt와 user-context는 고정 토큰(4,200 / 280) 항목으로 각각 1건이다.
**Actual Output**: —
**Status**: —

---

### TC-INT-027: `.agents/skills` 와 `.agents/agents` 는 집계에서 제외된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-008 |
| **US** | US-CTX03 AC1·AC2 |
| **Priority** | High |
| **Preconditions** | `<proj>/.claude/skills/keep/SKILL.md` 와 `<home>/.agents/skills/trap/SKILL.md`, `<proj>/.claude/agents/keep.md` 와 `<proj>/.agents/agents/trap.md` |
| **Input** | `collect_context_sources(...)` |
| **Gap** | PARTIAL — `tests/test_context.py::test_collect_context_dedups_symlinked_skill` 이 인접 사례를 다루지만 `.agents` 제외 규칙을 직접 단언하지 않는다 |

**Steps**:
1. 함정 항목과 정상 항목을 함께 배치한다
2. 소스를 수집한다
3. 이름 집합을 확인한다

**Expected Output**: `keep` 은 들어오고 `trap` 은 어느 카테고리에도 없다.
**Actual Output**: —
**Status**: —

---

### TC-INT-028: 비활성 MCP 서버는 mcp-tools 카테고리에서 빠진다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-008 |
| **US** | US-CTX03 AC4, US-MCP03 AC1 |
| **Priority** | Medium |
| **Preconditions** | `~/.claude.json` 에 서버 `a`, `b` 등록 + `projects[<cwd>].disabledMcpServers = ["b"]`. `monkeypatch.chdir(proj)` (프로젝트별 설정이므로 cwd 고정 필수) |
| **Input** | `set_mcp_disabled("b", disabled=True)` 이후 `collect_context_sources(...)` |
| **Gap** | PARTIAL — `tests/test_mcp.py::test_set_mcp_disabled_then_reflected_in_collect` 는 MCP 목록까지만 본다. 컨텍스트 분석까지 전파되는지는 확인하지 않는다 |

**Steps**:
1. 서버 2건을 등록한다
2. 한 건을 비활성으로 만든다
3. 컨텍스트 소스를 수집해 `mcp-tools` 카테고리를 확인한다

**Expected Output**: `mcp-tools` 에 `a` 만 남고 총 토큰이 그만큼 줄어든다.
**Actual Output**: —
**Status**: —

---

## SC-INT-009 — update 오케스트레이션

### TC-INT-029: Tier-1만 적용되고 Tier-2 대상 디스크는 변하지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-009 |
| **US** | US-UPD02 AC1 |
| **Priority** | Critical |
| **Preconditions** | git-backed skill 1건(`git init` + 커밋), non-git command 1건, MCP 서버 1건. 네트워크가 필요한 `git fetch` 만 stub |
| **Input** | `check_all_updates()` → Tier-1 타깃만 `apply_updates(targets)` |
| **Gap** | PARTIAL — `tests/test_update.py::test_cli_update_bulk_apply_excludes_tier3` 가 Tier-3 제외를 보고 `::test_mcp_updater_is_report_only` 가 MCP를 본다. **적용 후 non-git 항목 디스크가 불변인지**를 파일로 확인하지 않는다 |

**Steps**:
1. non-git command 파일의 `(st_mtime_ns, 내용)` 스냅샷을 잡는다
2. 전체 확인 후 Tier-1만 적용한다
3. 스냅샷을 다시 비교한다

**Expected Output**: git-backed 항목만 갱신되고 non-git 파일과 MCP 설정은 바이트 단위로 동일하다.
**Actual Output**: —
**Status**: —

---

### TC-INT-030: `no_sync=True` 는 플러그인 적용 전 마켓 동기화를 건너뛴다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-009 |
| **US** | US-UPD02, FEATURES.md §1.8b |
| **Priority** | High |
| **Preconditions** | 마켓 1건 + 그 마켓 소속 플러그인 1건. `axt.update.sync_marketplace` 를 호출 카운터로 감싼다 |
| **Input** | `apply_updates([("plugin", "foo@mk")], no_sync=True)` 와 `no_sync=False` 두 번 |
| **Gap** | COVERED — `tests/test_update.py:127`, `:269`, `:286` 이 `no_sync=True` 경로를 태운다 |

**Steps**:
1. `no_sync=True` 로 적용하고 sync 호출 수를 센다
2. `no_sync=False` 로 적용하고 다시 센다

**Expected Output**: 첫 호출에서 sync 호출 수 0, 두 번째에서 1 이상.
**Actual Output**: —
**Status**: —

---

### TC-INT-031: git-backed 항목 적용이 실제 커밋을 앞당긴다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-009 |
| **US** | US-UPD02 AC1, US-UPD04 AC1 |
| **Priority** | High |
| **Preconditions** | `tmp_path/origin` 에 커밋 2개, `tmp_path/work` 는 첫 커밋에 머문 클론. skill로 링크 |
| **Input** | `apply_path_update("skill", "s1", str(work))` |
| **Gap** | COVERED — `tests/test_update.py::test_git_updater_apply_pulls_new_commit`, `::test_check_and_apply_path_update_roundtrip` |

**Steps**:
1. 두 저장소를 만든다
2. 확인 후 적용한다
3. `git rev-parse HEAD` 로 워킹 카피의 커밋을 확인한다

**Expected Output**: 적용 후 워킹 카피의 HEAD가 origin의 두 번째 커밋과 같다.
**Actual Output**: —
**Status**: —

---

### TC-INT-032: 한 updater의 예외가 다른 타입의 확인을 중단시키지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-009 |
| **US** | US-UPD01 AC2, US-SYS06 |
| **Priority** | High |
| **Preconditions** | `UPDATERS` 중 하나의 `check_all` 을 예외를 던지도록 monkeypatch |
| **Input** | `check_all_updates()` |
| **Gap** | COVERED — `tests/test_update.py::test_check_all_updates_isolates_a_raising_updater` |

**Steps**:
1. 한 updater를 실패시킨다
2. 전체 확인을 돌린다
3. 나머지 타입의 결과가 들어왔는지 확인한다

**Expected Output**: 나머지 타입의 `UpdateStatus` 가 정상 반환되고 전체 호출이 예외를 올리지 않는다.
**Actual Output**: —
**Status**: —

---

## SC-INT-010 — `scan_project_usage` ↔ vault `Used`

### TC-INT-033: default 모드는 프로필과 심볼릭 링크만 센다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-010 |
| **US** | US-VLT07 AC1·AC2 |
| **Priority** | High |
| **Preconditions** | 실제 프로젝트 A(프로필로 `alpha` 선언), B(`alpha` 심볼릭 링크), C(`enabledPlugins` 만). `PATHS.projects` 에 세 프로젝트의 인코딩 폴더. 폴더명 디코딩이 파일시스템을 훑으므로 `fs_root=str(tmp_path)` 로 제한 |
| **Input** | `scan_project_usage(PATHS.projects, PATHS.vault, mode="default")` |
| **Gap** | COVERED — `tests/test_project_usage.py::test_scan_project_usage_from_profile_only`, `::test_scan_project_usage_indexes_symlinks` |

**Steps**:
1. 세 프로젝트를 배치한다
2. default 모드로 스캔한다
3. `get_project_count(index, "skill", "alpha")` 를 확인한다

**Expected Output**: 2 (A, B). C는 포함되지 않는다.
**Actual Output**: —
**Status**: —

---

### TC-INT-034: full 모드가 플러그인 설정까지 포함해 default보다 넓다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-010 |
| **US** | US-VLT07 AC2 |
| **Priority** | High |
| **Preconditions** | TC-INT-033과 동일 픽스처 |
| **Input** | 같은 픽스처에 `mode="default"` 와 `mode="full"` 을 각각 |
| **Gap** | PARTIAL — `tests/test_project_usage.py::test_scan_project_usage_full_mode_indexes_enabled_plugins` 가 full 모드를 보지만, **같은 상태에서 두 모드 결과를 대조**하지 않는다 |

**Steps**:
1. default 모드로 스캔해 인덱스 키 집합을 받는다
2. full 모드로 스캔해 키 집합을 받는다
3. 두 집합의 포함 관계를 확인한다

**Expected Output**: default 키 집합 ⊂ full 키 집합이고, 차집합이 정확히 플러그인 항목이다.
**Actual Output**: —
**Status**: —

---

### TC-INT-035: 프로젝트 링크 토글이 인메모리 사용 인덱스에 즉시 반영된다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-010 |
| **US** | US-VLT07 AC1, US-VLT09 AC2 |
| **Priority** | High |
| **Preconditions** | vault에 `skill:alpha`, `state.vault_usage_index` 를 스캔 결과로 채워 둔다. `state.stdscr_callbacks = None`(헤드리스). `monkeypatch.chdir(proj)` |
| **Input** | `_vault_apply_pending(state)` — 링크 방향 1회, 해제 방향 1회 |
| **Gap** | COVERED — `tests/test_tui.py::test_apply_pending_project_link_updates_used_index`, `::test_apply_pending_project_unlink_removes_from_used_index` |

**Steps**:
1. pending에 `alpha` 를 넣고 적용한다
2. 인덱스의 `skill:alpha` 프로젝트 목록을 확인한다
3. 다시 적용해 해제한다

**Expected Output**: 링크 시 cwd가 프로젝트 목록에 추가되고, 해제 시 제거되며 마지막 프로젝트가 사라지면 키 자체가 삭제된다.
**Actual Output**: —
**Status**: —

---

## SC-INT-011 — TUI 키 핸들러 → core → 디스크 → 재조회

### TC-INT-036: `p` + `Enter` 가 심볼릭 링크와 프로필을 함께 만든다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-011 |
| **US** | US-VLT09 AC1·AC2, US-LNK04 AC1 |
| **Priority** | Critical |
| **Preconditions** | vault 1건, `state.vault_items = list_vault_items_with_project_state(...)`, `state.stdscr_callbacks = None`, `monkeypatch.chdir(proj)` |
| **Input** | `handle_vault_input(state, ord("p"))` → `handle_vault_input(state, 10)` |
| **Gap** | COVERED — `tests/test_tui.py::test_vault_p_enqueues_pending_toggle`, `::test_handle_vault_input_enter_pending_without_stdscr_applies` |

**Steps**:
1. `p` 를 보낸 뒤 `state.vault_pending_project` 를 확인한다
2. Enter(`10`)를 보낸다
3. 디스크의 심볼릭 링크와 `.axt-profile.json` 을 확인한다

**Expected Output**: pending 단계에서는 디스크가 변하지 않고, Enter 이후 링크와 프로필 항목이 동시에 생긴다. 상태 메시지는 `"Applied 1"`.
**Actual Output**: —
**Status**: —

---

### TC-INT-037: `Esc` 로 폐기한 pending은 디스크에 닿지 않는다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-011 |
| **US** | US-VLT09 AC3 |
| **Priority** | Critical |
| **Preconditions** | TC-INT-036과 동일. 조작 전 `sorted(p.name for p in (proj/".claude").rglob("*"))` 스냅샷 |
| **Input** | `handle_vault_input(state, ord("p"))` → `handle_vault_input(state, 27)` |
| **Gap** | PARTIAL — `tests/test_tui.py::test_vault_esc_discards_pending` 은 상태 집합만 본다. **디스크 불변**을 파일 스냅샷으로 확인하지 않는다 |

**Steps**:
1. 스냅샷을 잡는다
2. `p` → `Esc` 를 보낸다
3. 스냅샷을 다시 잡아 비교한다

**Expected Output**: 두 스냅샷이 동일하고 `.axt-profile.json` 이 생기지 않는다. pending 집합이 비고 상태 메시지는 `"Discarded pending changes"`.
**Actual Output**: —
**Status**: —

---

### TC-INT-038: 파일 항목 서브탭 `g` 토글이 실체를 지우지 않고 링크만 만든다/지운다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-011 |
| **US** | US-LNK04 AC1·AC3, US-LNK03 AC1 |
| **Priority** | Critical |
| **Preconditions** | `<proj>/.claude/agents/a1.md` 실체 1건, `PATHS.claude_dir/agents/` 비어 있음. `state.ext_sub_tab = "agents"`, `_ensure_subtab_loaded` 로 캐시 채움 |
| **Input** | `_act_scope_toggle(state, None, "agents", ord("g"))` 두 번(링크 → 해제) |
| **Gap** | PARTIAL — `tests/test_tui.py` 가 토글 반환 메시지와 캐시 갱신을 보지만, **해제 후 원본 `.md` 실체가 남아 있는지**를 확인하지 않는다 |

**Steps**:
1. `g` 로 전역에 링크한다
2. `PATHS.claude_dir/agents/a1.md` 가 심볼릭 링크인지 확인한다
3. `g` 를 다시 눌러 해제한다
4. 원본 `<proj>/.claude/agents/a1.md` 가 실제 파일로 남아 있는지 확인한다

**Expected Output**: 링크 생성·해제가 모두 성공하고 원본 파일은 두 단계 모두에서 `is_file() and not is_symlink()` 다.
**Actual Output**: —
**Status**: —

---

### TC-INT-039: `i` import가 실체를 vault로 옮기고 원위치 링크와 프로필을 남긴다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-011 |
| **US** | US-LNK05 AC1·AC2·AC3 |
| **Priority** | High |
| **Preconditions** | `<proj>/.claude/commands/c1.md` 실체(project 출처), plugin 출처 항목 1건, 이미 vault인 항목 1건. `monkeypatch.chdir(proj)` |
| **Input** | `_act_import_to_vault(state, None, "commands", ord("i"))` 를 세 항목에 각각 |
| **Gap** | PARTIAL — `tests/test_tui.py` 에 `import_to_vault` 관련 케이스가 12건 있으나, **project 출처 import 후 `.axt-profile.json` 에 항목이 기록되는지**(`axt/tui/tabs.py:4160`)를 확인하는 케이스가 없다 |

**Steps**:
1. project 출처 항목을 import한다
2. vault 실체 · 원위치 심볼릭 링크 · 프로필 항목 세 가지를 확인한다
3. plugin 출처와 이미 vault인 항목에 각각 import를 시도한다

**Expected Output**: 첫 항목은 세 조건을 모두 만족한다. 나머지 둘은 각각 `"Plugin-bundled items stay with their plugin (not importable)"`, `"Already in vault"` 로 거부되고 디스크가 변하지 않는다.
**Actual Output**: —
**Status**: —

---

## SC-INT-012 — `_invalidate_context`

### TC-INT-040: 링크가 실제로 바뀐 sync만 컨텍스트 캐시를 떨어뜨린다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-012 |
| **US** | US-PRJ05 AC1·AC2 |
| **Priority** | High |
| **Preconditions** | `state.context_analysis` 에 센티넬 `ContextAnalysis` 객체를 넣어 둔다. **`_invalidate_context` 를 monkeypatch하지 않는다** |
| **Input** | `handle_vault_input(state, ord("y"))` — 1) 어긋난 상태에서 2) 이미 정합인 상태에서 |
| **Gap** | PARTIAL — `tests/test_tui.py:7037` 는 `_invalidate_context` **호출 여부**를 monkeypatch로 감시한다(순수 위임 검증). 캐시 상태 자체의 변화와 no-op 분기를 함께 보는 케이스가 없다 |

**Steps**:
1. 어긋난 상태에서 `y` 를 보낸다 → `state.context_analysis` 확인
2. 센티넬을 다시 심는다
3. 이미 정합인 상태에서 `y` 를 보낸다 → `state.context_analysis` 확인

**Expected Output**: 1단계 후 `None`, 3단계 후 센티넬 객체가 그대로 남는다.
**Actual Output**: —
**Status**: —

---

### TC-INT-041: 이동 대상이 없는 migrate는 캐시를 유지한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-012 |
| **US** | US-PRJ05 AC2, US-VLT01 AC4 |
| **Priority** | Medium |
| **Preconditions** | `~/.claude/{skills,commands,agents}` 가 비어 있거나 전부 이미 vault에 있음. 센티넬 분석 객체 주입 |
| **Input** | `handle_vault_input(state, ord("m"))` |
| **Gap** | PARTIAL — `tests/test_tui.py:6966` 은 moved가 있는 경로만 본다. moved가 0건일 때 캐시가 유지되는지는 확인하지 않는다 |

**Steps**:
1. 이동 대상이 없는 상태를 만든다
2. `m` 을 보낸다
3. `state.context_analysis` 와 상태 메시지를 확인한다

**Expected Output**: 센티넬이 그대로 남고 메시지는 `"Migrated: +0 skipped N broken 0 err 0"` 형태다.
**Actual Output**: —
**Status**: —

---

### TC-INT-042: 무효화는 detail 포커스와 스크롤도 함께 초기화한다

| Field | Value |
|-------|-------|
| **Scenario** | SC-INT-012 |
| **US** | US-PRJ05 AC1, US-TUI05 AC3 |
| **Priority** | Medium |
| **Preconditions** | `state.context_detail_focused = True`, `state.context_detail_scroll = 7`, 센티넬 분석 객체 주입 |
| **Input** | 실제로 링크를 바꾸는 조작(`y` sync) |
| **Gap** | COVERED — `tests/test_tui.py::test_invalidate_context_resets_detail_focus` |

**Steps**:
1. detail 포커스와 스크롤을 세팅한다
2. 링크가 바뀌는 조작을 수행한다
3. 세 필드를 확인한다

**Expected Output**: `context_analysis is None`, `context_detail_focused is False`, `context_detail_scroll == 0`.
**Actual Output**: —
**Status**: —

---

## 스펙 갭

시나리오 문서의 [스펙 갭](../scenarios/integration-scenarios.md#스펙-갭) 절과 동일한
항목을 TC 단위로 연결한다.

| ID | 요약 | 관련 TC |
|---|---|---|
| G-1 | `settings.local.json` 우선순위가 플러그인 활성 판정에 반영되지 않음 | TC-INT-019 |
| G-2 | `vault install` 이 마켓 레지스트리의 `installLocation` 을 쓰지 않음 | TC-INT-012 |
| G-3 | `plugin search` 에 마켓플레이스 검색 구현이 없음(US-PLG05 AC2 미충족) | TC 없음 — 구현 전까지 작성 불가 |
| G-4 | 플러그인 활성 판정이 우선순위가 아니라 논리합(OR) | TC-INT-020 |
