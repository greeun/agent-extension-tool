# Unit 테스트 케이스 — axt

대응 시나리오: `tests/doc/scenarios/unit-scenarios.md`

## 요약

| 항목 | 값 |
|---|---|
| 총 TC 수 | **251** |
| 시나리오 수 | 75 (SC-UNIT-001 ~ SC-UNIT-075) |

**우선순위 분포**

| Critical | High | Medium | Low |
|---|---|---|---|
| 47 | 125 | 74 | 5 |

**Gap 분포**

| COVERED | PARTIAL | NEW |
|---|---|---|
| 225 | 16 | 10 |

`Gap` 판정은 `tests/` 를 grep 해 확인했다. `COVERED` 는 기존 테스트 파일/함수명을 함께 적는다.
`COVERED (N개)` 표기는 기존 테스트 N개가 그 TC 의 단언을 나눠 갖고 있다는 뜻이다.
Gap 코드 단계의 실제 작성 대상은 **`NEW` 10건 + `PARTIAL` 16건 = 26건**이다.

---

## 1. paths

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-001 | SC-UNIT-001 | 기본 Claude 경로는 `~/.claude` | `clean_env`, `Path.home`→`/tmp/fake-home`, `importlib.reload(axt)` | env 없음 | `CLAUDE_DIR == /tmp/fake-home/.claude`, `PATHS.settings == .../.claude/settings.json`, `PATHS.installed_plugins == .../plugins/installed_plugins.json` | High | US-SYS03 | COVERED `test_paths.py::test_default_claude_dir_is_home_dotclaude` |
| TC-UNIT-002 | SC-UNIT-001 | `CLAUDE_CONFIG_DIR` 가 모든 하위 경로를 옮긴다 | 동상 | `CLAUDE_CONFIG_DIR=/custom/claude` | `CLAUDE_DIR == /custom/claude`, `PATHS.settings == /custom/claude/settings.json` | High | US-SYS03 | COVERED `test_paths.py::test_claude_config_dir_env_overrides` |
| TC-UNIT-003 | SC-UNIT-001 | 빈 문자열 env 는 미설정과 같다 | 동상, `Path.home`→`/h` | `CLAUDE_CONFIG_DIR=""` | `CLAUDE_DIR == /h/.claude` | Medium | US-SYS03 | COVERED `test_paths.py::test_empty_env_var_falls_back_to_default` |
| TC-UNIT-004 | SC-UNIT-001 | `CLAUDE_CONFIG_DIR` 가 `.claude.json` 위치도 옮긴다 | 동상 | `CLAUDE_CONFIG_DIR=/custom/claude` | `CLAUDE_CONFIG_FILE == /custom/claude/.claude.json` (미설정 시 `~/.claude.json`) | Medium | US-SYS03 | NEW |
| TC-UNIT-005 | SC-UNIT-002 | POSIX 기본은 `~/.config/axt` | `clean_env`, `sys.platform="linux"`, `Path.home`→`/h`, reload | env 없음 | `AXT_CONFIG_DIR == /h/.config/axt`, `AXT_CONFIG_PATH == /h/.config/axt/config.json` | Medium | US-SYS03 | COVERED `test_paths.py::test_axt_config_dir_unix` |
| TC-UNIT-006 | SC-UNIT-002 | `XDG_CONFIG_HOME` 존중 | 동상 | `XDG_CONFIG_HOME=/xdg` | `AXT_CONFIG_DIR == /xdg/axt` | Medium | US-SYS03 | COVERED `test_paths.py::test_axt_config_dir_xdg` |
| TC-UNIT-007 | SC-UNIT-002 | Windows 는 `%APPDATA%/axt` | `clean_env`, `sys.platform="win32"`, `APPDATA=C:\\Users\\u\\AppData\\Roaming`, reload | — | `AXT_CONFIG_DIR == <APPDATA>/axt`; `APPDATA` 미설정 시 `~/AppData/Roaming/axt` | Medium | US-SYS03 | NEW |
| TC-UNIT-008 | SC-UNIT-003 | `project_settings_path` 기본·명시 cwd | `tmp_path`, `monkeypatch.chdir(tmp_path)` | 인자 없음 / `tmp_path` | 둘 다 `<base>/.claude/settings.json` | Medium | US-SYS03 | COVERED `test_paths.py` (2개) |
| TC-UNIT-009 | SC-UNIT-003 | `PATHS` 는 frozen | reload | `PATHS.claude_dir = Path("/nope")` | 예외 발생 (`FrozenInstanceError`) | Low | US-SYS03 | COVERED `test_paths.py::test_paths_object_is_frozen` |

## 2. json_io

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-010 | SC-UNIT-004 | 정상 JSON 을 파싱해 돌려준다 | `tmp_path` | `{"a": 1}` 파일 | `{"a": 1}` | Critical | US-SYS05 AC1 | COVERED `test_json_io.py` |
| TC-UNIT-011 | SC-UNIT-004 | 부재 파일 + fallback → fallback | `tmp_path` | 없는 경로, `fallback={}` | `{}` (예외 없음) | Critical | US-SYS05 AC1 | COVERED `test_json_io.py` |
| TC-UNIT-012 | SC-UNIT-004 | 부재 파일 + fallback 미지정 → 예외 | `tmp_path` | 없는 경로 | 예외 발생 | High | US-SYS05 AC1 | COVERED `test_json_io.py` |
| TC-UNIT-013 | SC-UNIT-004 | 깨진 JSON + fallback → fallback | `tmp_path` | `"{not json"` 파일, `fallback=[]` | `[]` | Critical | US-SYS05 AC1 | PARTIAL — 부재는 검증되나 **파싱 실패** 경로 단독 TC 부재 |
| TC-UNIT-014 | SC-UNIT-005 | 부모 디렉터리를 자동 생성한다 | `tmp_path` | `tmp_path/a/b/c.json`, `{"x":1}` | 파일 생성 + 내용 일치 | Critical | US-SYS04 AC1 | COVERED `test_json_io.py::test_write_json_atomic_creates_parents` |
| TC-UNIT-015 | SC-UNIT-005 | 기존 파일은 `.bak` 으로 보존 | `tmp_path`, 기존 파일 존재 | 두 번째 쓰기 | `c.json.bak` 에 이전 내용, `c.json` 에 새 내용 | Critical | US-SYS04 AC2 | COVERED `test_json_io.py::test_write_json_atomic_backs_up_existing` |
| TC-UNIT-016 | SC-UNIT-005 | 임시 파일 잔재가 없다 | `tmp_path` | 쓰기 1회 | 디렉터리에 `.tmp*` 엔트리 0개 | High | US-SYS04 AC1 | COVERED `test_json_io.py::test_write_json_atomic_no_tmp_litter` |
| TC-UNIT-017 | SC-UNIT-005 | 유니코드·개행·들여쓰기 보존 | `tmp_path` | `{"k": "한글 값"}` | `ensure_ascii=False` 로 원문 보존, 2칸 들여쓰기, 끝에 개행 1개 | Medium | US-SYS04 | COVERED `test_json_io.py` (3개) |
| TC-UNIT-018 | SC-UNIT-005 | 쓰기 실패 시 원본이 손상되지 않는다 | `tmp_path`, 기존 파일 존재, `os.replace` 를 monkeypatch 해 `OSError` 주입 | 두 번째 쓰기 | 예외 전파되더라도 기존 `c.json` 내용이 그대로 | High | US-SYS04 AC3 | NEW |

## 3. settings

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-019 | SC-UNIT-006 | 파일 부재 시 빈 맵 | `tmp_settings` (파일 없음) | `read_enabled_plugins` / `read_favorite_plugins` / `read_marked_for_update` / `read_extra_marketplaces` | 모두 `{}` | High | US-PLG01 AC1 | COVERED `test_settings.py` (4개) |
| TC-UNIT-020 | SC-UNIT-006 | 깨진 JSON 도 빈 맵 | `tmp_path` 에 `"{broken"` | `read_enabled_plugins` | `{}` | High | US-SYS05 AC1 | COVERED `test_settings.py::test_read_enabled_plugins_corrupt_file` |
| TC-UNIT-021 | SC-UNIT-006 | 비dict 버킷·비bool 값 정규화 | `tmp_path` 에 `{"enabledPlugins": "x"}` / `{"enabledPlugins": {"a": 1}}` | 읽기 | 전자 `{}`, 후자 `{"a": True}` | High | US-PLG01 AC1 | COVERED `test_settings.py` (2개) |
| TC-UNIT-022 | SC-UNIT-007 | 플래그 토글이 형제 키를 보존 | `seeded_settings` (`otherKey: "preserved"`) | `set_plugin_enabled("alpha", False)` | `alpha == False`, `beta`·`otherKey` 불변 | High | US-PLG02 AC3 | COVERED `test_settings.py` (2개) |
| TC-UNIT-023 | SC-UNIT-007 | `False` 즐겨찾기는 키를 삭제 | `seeded_settings` | `set_plugin_favorite("alpha", False)` | `favoritePlugins` 에서 `alpha` 키 제거 | Medium | US-PLG02 AC3 | COVERED `test_settings.py::test_set_plugin_favorite_false_deletes` |
| TC-UNIT-024 | SC-UNIT-007 | 없는 키 제거는 no-op | `seeded_settings` | `remove_plugin_from_settings("nope")` | 예외 없음, 파일 내용 불변 | Medium | US-PLG04 AC1 | COVERED `test_settings.py` / `test_plugin.py` |
| TC-UNIT-025 | SC-UNIT-007 | 비dict 버킷 위에 쓰면 dict 로 교체 | `tmp_path` 에 `{"enabledPlugins": "x", "otherKey": 1}` | `set_plugin_enabled("a", True)` | `enabledPlugins == {"a": True}`, `otherKey` 유지 | Medium | US-PLG02 AC3 | COVERED `test_settings.py::test_set_settings_flag_overwrites_non_dict_bucket` |

## 4. vault — frontmatter

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-026 | SC-UNIT-008 | plain / double-quoted 단일행 | 없음 | `description: hello` / `description: "hello"` | 둘 다 `"hello"` | High | US-LNK01 AC1 | COVERED `test_vault.py` (2개) |
| TC-UNIT-027 | SC-UNIT-008 | double-quoted 멀티라인 + 줄 연결 | 없음 | 다음 줄로 이어지는 `"..."` / 끝에 `\` 를 둔 줄 연결 | 줄바꿈은 공백 1개로, `\` 연결은 공백 없이 이어붙음 | High | US-LNK01 AC1 | COVERED `test_vault.py` (2개) |
| TC-UNIT-028 | SC-UNIT-008 | single-quoted (`''` 리터럴, 멀티라인) | 없음 | `description: 'it''s ok'` + 멀티라인 | `it's ok` / 줄바꿈 → 공백 | High | US-LNK01 AC1 | COVERED `test_vault.py` (2개) |
| TC-UNIT-029 | SC-UNIT-008 | 블록 스칼라 `\|` / `>` + dedent + 후속 키 중단 | 없음 | `description: \|` / `>` 블록, 공통 들여쓰기 4칸, 뒤에 다른 키 | 리터럴은 줄바꿈→공백 정규화, 폴디드는 공백 결합, 공통 들여쓰기 제거, 후속 키 이전에서 종료 | High | US-LNK01 AC1 | COVERED `test_vault.py` (4개) |
| TC-UNIT-030 | SC-UNIT-008 | CRLF / 값 없음 / 키 부재 | 없음 | `description: v\r\n` / `description:` / 키 없음 | 순서대로 `"v"` / `""` / `""` | Medium | US-LNK01 AC1 | COVERED `test_vault.py` (3개) |
| TC-UNIT-031 | SC-UNIT-009 | `version` 스칼라 3형태 | 없음 | `1.2.3` / `"1.2.3"` / `'1.2.3'` | 모두 `"1.2.3"` | Medium | US-LNK01 | COVERED `test_vault.py` (2개) |
| TC-UNIT-032 | SC-UNIT-009 | `version` 부재·빈 값 | 없음 | 키 없음 / `version:` | 둘 다 `""` | Medium | US-LNK01 | COVERED `test_vault.py` (2개) |
| TC-UNIT-033 | SC-UNIT-010 | skill 은 `index.md` → `SKILL.md` 순 | `tmp_path` 에 각각 배치 | skill 디렉터리 | `index.md` 값 우선, 없으면 `SKILL.md` 값, 둘 다 없으면 `""` | Medium | US-LNK01 AC1 | COVERED `test_vault.py` (3개) |
| TC-UNIT-034 | SC-UNIT-010 | command/agent 는 파일 자체 | `tmp_path` 에 `.md` | command `.md` (frontmatter 있음/없음) | 있으면 값, frontmatter 블록 없으면 `""` | Medium | US-LNK01 AC1 | COVERED `test_vault.py` (2개) |

## 5. vault — 프로필·항목·링크

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-035 | SC-UNIT-011 | `empty_profile` + 쓰기/읽기 왕복 | `tmp_path` 프로젝트 | 빈 프로필 write → read | 같은 값 복원, 파일 부재 시 `None` | Medium | US-PRJ01 AC1 | COVERED `test_vault.py` (3개) |
| TC-UNIT-036 | SC-UNIT-011 | `with_added` / `with_removed` 가 idempotent | 없음 | 이미 있는 이름 추가 / 없는 이름 제거 | 동일 객체 반환 (새 객체 생성 없음) | Medium | US-PRJ02 AC1 | COVERED `test_vault.py` (4개) |
| TC-UNIT-037 | SC-UNIT-011 | `from_json` 비dict 방어 | 없음 | `"x"` / `{"extensions": "x"}` | 빈 프로필 | Low | US-SYS05 AC1 | COVERED `test_vault.py` (2개) |
| TC-UNIT-038 | SC-UNIT-012 | 3타입 항목을 모두 스캔 | `tmp_path` vault, skill 1 / command 1 / agent 1 | `list_vault_items(vault)` | 3건, 각 `type` 정확 | High | US-VLT02 AC1 | COVERED `test_vault.py::test_list_vault_items_returns_all_three_types` |
| TC-UNIT-039 | SC-UNIT-012 | 점파일·비`.md`·매니페스트 없는 dir 제외 | 동상 + `.hidden`, `readme.txt`, 빈 디렉터리 | 동상 | 잡음 항목 미포함 | High | US-VLT02 AC1 | COVERED `test_vault.py` (3개) |
| TC-UNIT-040 | SC-UNIT-012 | vault 디렉터리 부재 시 빈 목록 | 디렉터리 미생성 | 동상 | `[]` (예외 아님) | High | US-VLT02 AC2 | COVERED `test_vault.py::test_list_vault_items_missing_dir` |
| TC-UNIT-041 | SC-UNIT-013 | 프로젝트 링크 생성 + 프로필 등록 | `tmp_path` 프로젝트/vault, Windows skip | `link_to_project(proj, item)` | `<proj>/.claude/skills/<name>` symlink + `.axt-profile.json` 에 이름 등록 | Critical | US-LNK04 AC1 | COVERED `test_vault.py::test_link_to_project_creates_symlink_and_updates_profile` |
| TC-UNIT-042 | SC-UNIT-013 | 실제 파일/디렉터리 충돌 시 거부 | 링크 자리에 실제 파일 존재 | 동상 | 예외 + 실체 보존 | Critical | US-LNK03 AC2 | COVERED `test_vault.py` (2개) |
| TC-UNIT-043 | SC-UNIT-013 | 낡은 symlink 위에 재링크 | 링크 자리에 깨진 symlink | 동상 | 링크가 새 대상으로 교체 | High | US-LNK04 AC1 | COVERED `test_vault.py::test_link_to_project_replaces_stale_symlink` |
| TC-UNIT-044 | SC-UNIT-013 | 해제는 symlink 와 프로필만 정리 | 링크 상태 | `unlink_from_project` | symlink 제거, vault 실체 잔존, 프로필 항목 제거 | Critical | US-LNK03 AC1 | COVERED `test_vault.py::test_unlink_from_project_removes_symlink_and_profile_entry` |
| TC-UNIT-045 | SC-UNIT-013 | plugin / 알 수 없는 타입 거부 | vault item type=`plugin` / `bogus` | `link_to_project` | 예외 | High | US-LNK05 AC1 | COVERED `test_vault.py` (2개) |
| TC-UNIT-046 | SC-UNIT-014 | 전역 링크 생성·해제 | `tmp_path` `~/.claude`, Windows skip | `link_to_global` → `unlink_from_global` | `~/.claude/skills/<name>` symlink 생성 후 제거 | Critical | US-VLT05 AC1 | COVERED `test_vault.py::test_link_unlink_global` |
| TC-UNIT-047 | SC-UNIT-014 | 해제 후 vault 실체가 남는다 | 동상 | `unlink_from_global` 직후 vault 경로 확인 | vault 실체 디렉터리/파일 존재 | Critical | US-VLT05 AC2 | PARTIAL — 링크 해제는 검증되나 vault 실체 잔존 단언 없음 |
| TC-UNIT-048 | SC-UNIT-014 | `plugin` 타입 전역 링크 거부 | 동상 | `link_to_global(item(type="plugin"))` | 예외 | High | US-VLT05 AC3 | COVERED `test_vault.py::test_link_to_global_rejects_plugin` |
| TC-UNIT-049 | SC-UNIT-015 | `.agents` 미러가 vault 원본을 가리킨다 | `tmp_path/.agents`, Windows skip | `link_to_agents(dot_agents, skill_item)` | `~/.agents/skills/<name>` → **vault 경로** (`~/.claude/skills` 아님) | High | US-VLT06 AC1 | COVERED `test_vault.py::test_link_to_agents_mirrors_skill_pointing_at_vault` |
| TC-UNIT-050 | SC-UNIT-015 | `.skill-lock.json` 이 있으면 기본 거부 | 대상 트리에 `.skill-lock.json` | `link_to_agents(..., force=False)` | `(False, 메시지)` + 링크 미생성 | High | US-VLT06 AC2 | COVERED `test_vault.py::test_link_to_agents_guarded_by_skill_lock` |
| TC-UNIT-051 | SC-UNIT-015 | `force=True` 는 잠금을 무시 | 동상 | `link_to_agents(..., force=True)` | `(True, ...)` + 링크 생성 | High | US-VLT06 AC3 | PARTIAL — 잠금 거부만 검증, `force=True` 우회 경로 미검증 |
| TC-UNIT-052 | SC-UNIT-015 | skill 이외 타입 / 실제 디렉터리 충돌 거부 | command item / 같은 이름 실제 디렉터리 | `link_to_agents` | 둘 다 `(False, 메시지)` | High | US-VLT06 AC5 | COVERED `test_vault.py` (2개) |
| TC-UNIT-053 | SC-UNIT-016 | 이 vault 항목을 가리키는 미러만 제거 | `.agents` 에 vault 를 가리키는 링크 | `unlink_from_agents` | 링크 제거 | High | US-VLT06 AC4 | COVERED `test_vault.py::test_unlink_from_agents_only_removes_matching_link` |
| TC-UNIT-054 | SC-UNIT-016 | 외부 대상을 가리키는 동명 링크는 보존 | `.agents` 에 다른 대상 링크 | 동상 | 링크 잔존 + `(False, 메시지)` | High | US-VLT06 AC4 | COVERED `test_vault.py::test_unlink_from_agents_leaves_foreign_symlink` |
| TC-UNIT-055 | SC-UNIT-017 | 프로필에만 있는 항목을 링크 | `tmp_path` 프로젝트/vault, Windows skip | `sync_project` | `linked` 에 1건, symlink 생성 | Critical | US-PRJ03 AC1 | COVERED `test_vault.py::test_sync_project_links_declared_and_unlinks_orphans` |
| TC-UNIT-056 | SC-UNIT-017 | 프로필에 없는 고아 링크 제거 | 링크만 존재 | 동상 | `unlinked` 에 1건, symlink 제거 | Critical | US-PRJ03 AC2 | COVERED `test_vault.py` (2개) |
| TC-UNIT-057 | SC-UNIT-017 | vault 에 없는 프로필 항목은 errors | 프로필에 미존재 이름 | 동상 | `errors` 에 1건, 예외 아님 | High | US-PRJ03 AC3 | COVERED `test_vault.py` (2개) |
| TC-UNIT-058 | SC-UNIT-017 | 외부 대상을 가리키는 남의 symlink 는 보존 | `.claude/skills/x` → 외부 경로 | 동상 | 링크 잔존 | High | US-PRJ03 AC2 | COVERED `test_vault.py::test_sync_project_leaves_foreign_symlink` |
| TC-UNIT-059 | SC-UNIT-018 | 실체를 vault 로 이동하고 원위치에 symlink | `tmp_path` `~/.claude/skills/<name>` 실체, Windows skip | `migrate_to_vault` | `moved` 1건, vault 에 실체, 원위치는 vault 를 가리키는 symlink | Critical | US-VLT01 AC1 | COVERED `test_vault.py::test_migrate_to_vault_moves_global_items` |
| TC-UNIT-060 | SC-UNIT-018 | 이미 vault 인 항목은 skipped | 원위치가 vault 를 가리키는 symlink | 동상 | `skipped` 1건, 중복 이동 없음 | High | US-VLT01 AC4 | COVERED `test_vault.py` (2개) |
| TC-UNIT-061 | SC-UNIT-018 | broken symlink 는 broken 으로만 보고 (삭제 금지) | 대상이 삭제된 symlink | 동상 | `broken` 1건, `moved`/`skipped` 0, **원본 링크 잔존** | Critical | US-VLT01 AC2 | COVERED `test_vault.py::test_migrate_reports_broken_symlink_not_skipped` |
| TC-UNIT-062 | SC-UNIT-018 | 점파일·타입 불일치 항목 무시 | `.hidden`, `notes.txt` | 동상 | 어느 집계에도 계상되지 않음 | Medium | US-VLT01 AC3 | COVERED `test_vault.py::test_migrate_to_vault_skips_hidden_and_wrong_type` |
| TC-UNIT-063 | SC-UNIT-019 | 글로벌/프로젝트 소스 import + 원위치 symlink | `tmp_path`, Windows skip | `import_to_vault` | vault 로 이동 + 원위치 symlink | High | US-LNK05 AC3 | COVERED `test_vault.py` (2개) |
| TC-UNIT-064 | SC-UNIT-019 | 같은 이름이 vault 에 있으면 실패 | vault 에 동명 항목 | 동상 | 예외 + 원본 미변경 | High | US-LNK05 AC2 | COVERED `test_vault.py::test_import_to_vault_fails_if_exists` |
| TC-UNIT-065 | SC-UNIT-019 | `find_broken_links` 가 목록만 준다 | `~/.claude` 에 broken symlink 2개 | `find_broken_links(claude_dir)` | 이름 2건 반환 + 링크 잔존 | High | US-SYS05 AC2 | COVERED `test_vault.py::test_find_broken_links` |
| TC-UNIT-066 | SC-UNIT-019 | 대상 디렉터리 부재 시 빈 목록 | `~/.claude` 하위 디렉터리 미생성 | 동상 | `[]` | Medium | US-SYS05 AC3 | COVERED `test_vault.py::test_find_broken_links_missing_dirs` |
| TC-UNIT-067 | SC-UNIT-020 | project/global 링크 플래그를 채운다 | `tmp_path` 프로젝트/글로벌, Windows skip | `list_vault_items_with_project_state` | 프로젝트만 링크 → `is_linked=True`/`is_global_linked=False`, 전역만 링크 → 반대 | High | US-VLT02 AC3 | COVERED `test_vault.py` (2개) |
| TC-UNIT-068 | SC-UNIT-020 | 남의 symlink 를 자기 것으로 오인하지 않는다 | 동명이지만 다른 대상을 가리키는 링크 | 동상 | 해당 플래그 `False`; 프로젝트 local 전용 항목은 목록에서 제외 | High | US-VLT02 AC3 | COVERED `test_vault.py` (3개) |

## 6. marketplace

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-069 | SC-UNIT-021 | 3개 접두사 파싱 | 없음 | `github:org/r` / `git:https://x/y.git` / `dir:/a/b` | `kind` 가 `github`/`git`/`directory`, `repo`/`url`/`path` 중 하나만 채워짐 | High | US-MKT01 AC1 | COVERED `test_marketplace.py` (3개) |
| TC-UNIT-070 | SC-UNIT-021 | bare `owner/repo` 는 github 기본 | 없음 | `org/repo` | `kind == "github"`, `repo == "org/repo"` | High | US-MKT01 AC1 | COVERED `test_marketplace.py::test_parse_bare_owner_repo_defaults_to_github` |
| TC-UNIT-071 | SC-UNIT-021 | 알 수 없는 형태는 `ValueError` | 없음 | `"nonsense"` | `ValueError`, 메시지에 `github:user/repo`·`git:url`·`dir:/path` 포함 | High | US-MKT01 AC2 | COVERED `test_marketplace.py::test_parse_invalid_raises` |
| TC-UNIT-072 | SC-UNIT-021 | `to_json`/`from_json` 왕복 | 없음 | 3형태 각각 | 동일 값 복원 | Medium | US-MKT01 AC3 | COVERED `test_marketplace.py::test_source_roundtrip` |
| TC-UNIT-073 | SC-UNIT-022 | 빈 레지스트리 / 정상 2건 | `tmp_path` | `known_marketplaces.json` | `[]` / `MarketplaceInfo` 2건 | Medium | US-MKT03 | COVERED `test_marketplace.py` (2개) |
| TC-UNIT-074 | SC-UNIT-022 | 손상 엔트리 건너뛰기 | `tmp_path` | 문자열 엔트리 / `source` 가 문자열 | 손상만 제외하고 정상 반환, 예외 없음 | Medium | US-SYS05 AC1 | COVERED `test_marketplace.py` (2개) |
| TC-UNIT-075 | SC-UNIT-023 | directory → `local`, `.gcs-sha` → 7자 | `tmp_path` 설치 디렉터리 | `get_local_version` | `"local"` / SHA 앞 7자 | Medium | US-MKT03 AC1 | COVERED `test_marketplace.py` (2개) |
| TC-UNIT-076 | SC-UNIT-023 | git repo → short hash, 실패 → unknown | `.git` 생성, `_git` monkeypatch | 동상 | short hash / `unknown` | Medium | US-MKT03 AC2 | COVERED `test_marketplace.py` (2개) |
| TC-UNIT-077 | SC-UNIT-023 | 미등록 이름 / 비dict 엔트리 → unknown | `tmp_path` | 동상 | `"unknown"` (예외 아님) | Medium | US-MKT03 AC2 | COVERED `test_marketplace.py` (2개) |
| TC-UNIT-078 | SC-UNIT-024 | git 원격이 앞서면 updatable | `_git` monkeypatch (local≠remote) | `get_marketplace_version` | `updatable=True`, `current`/`remote` 채워짐 | High | US-UPD01 AC2 | COVERED `test_marketplace.py::test_get_marketplace_version_git_updatable` |
| TC-UNIT-079 | SC-UNIT-024 | git 최신이면 updatable False | `_git` monkeypatch (동일) | 동상 | `updatable=False` | High | US-UPD01 AC2 | COVERED `test_marketplace.py::test_get_marketplace_version_git_up_to_date` |
| TC-UNIT-080 | SC-UNIT-024 | fetch 실패 / upstream 없음 / 네트워크 오류 | `_git`·`_fetch_github_head_sha` monkeypatch 로 실패 주입 | 동상 | `error` 채워짐, 예외 미전파 | High | US-MKT02 AC4 | COVERED `test_marketplace.py` (4개) |
| TC-UNIT-081 | SC-UNIT-025 | 없는 이름은 `KeyError` | `tmp_path` 빈 레지스트리 | `sync_marketplace(km, "nope")` | `KeyError` | High | US-MKT02 AC3 | COVERED `test_marketplace.py::test_sync_marketplace_missing` |
| TC-UNIT-082 | SC-UNIT-025 | directory 소스는 no-op | `dir:` 등록 | `sync_marketplace` | `before == after == "local"`, `updated=False` | Medium | US-MKT02 AC2 | COVERED `test_marketplace.py::test_sync_marketplace_directory_noop` |
| TC-UNIT-083 | SC-UNIT-025 | git 소스: fetch 실패는 `RuntimeError` + stderr 전달 | `_git` monkeypatch 로 exit≠0 | 동상 | `RuntimeError` 메시지에 stderr 원문 포함 | High | US-MKT02 AC4 / US-SYS06 AC1 | COVERED `test_marketplace.py::test_sync_marketplace_git_fetch_failure` |
| TC-UNIT-084 | SC-UNIT-025 | git 소스: `fetch` 성공 후 `reset --hard @{u}` 로 upstream 에 정렬한다 | `_git` monkeypatch 로 호출 인자 기록 | 동상 | 호출 순서가 `fetch` → `reset --hard @{u}` 이고, `reset` 실패 시 `RuntimeError` + 레지스트리 미기록 | High | US-MKT05 AC1·AC3 | NEW — `tests/doc/SPEC_DECISIONS.md` SD-001 로 방향 확정 |
| TC-UNIT-085 | SC-UNIT-025 | github tarball / 동기화 불가 소스 | `download_and_extract_tarball` monkeypatch | 동상 | SHA 앞 7자 비교 후 `updated` 판정 / `RuntimeError` | Medium | US-MKT02 AC1 | COVERED `test_marketplace.py` (2개) |

## 7. plugin

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-086 | SC-UNIT-026 | `name@marketplace` id 분해 | `tmp_path` 레지스트리 | `list_installed_plugins` | `name` 과 `marketplace` 분리; 접미사 없으면 marketplace 빈 값 | High | US-PLG01 AC1 | COVERED `test_plugin.py` (2개) |
| TC-UNIT-087 | SC-UNIT-026 | 매니페스트 우선순위 (`.claude-plugin/` > root) | 두 파일 모두 배치 | 동상 | modern 매니페스트 값 채택; modern 이 비면 root 폴백 | High | US-PLG03 AC2 | COVERED `test_plugin.py` (3개) |
| TC-UNIT-088 | SC-UNIT-026 | 손상 레지스트리 방어 | 최상위가 dict 아님 / 엔트리 리스트 빔 | 동상 | `[]` (예외 아님) | High | US-SYS05 AC1 | COVERED `test_plugin.py` (2개) |
| TC-UNIT-089 | SC-UNIT-026 | 매니페스트 필드 정규화 | author 가 객체 / repository 가 객체 / description 이 비문자열 | 동상 | 문자열 추출 또는 `None` | Medium | US-PLG03 | COVERED `test_plugin.py` (3개) |
| TC-UNIT-090 | SC-UNIT-027 | 전체·단축 SHA 를 태그로 치환 | `_git` monkeypatch | `list_installed_plugins` | 태그명으로 표시 | Medium | US-PLG03 AC1 | COVERED `test_plugin.py` (2개) |
| TC-UNIT-091 | SC-UNIT-027 | 마켓 경로 미지정 / 매칭 태그 없음 | 동상 | 동상 | raw SHA 유지 | Medium | US-PLG03 AC1 | COVERED `test_plugin.py` (2개) |
| TC-UNIT-092 | SC-UNIT-028 | 매니페스트 상대 경로 해석 | `tmp_path` 마켓 트리 | `find_plugin_source_dir` | 실제 경로 반환 | Medium | US-VLT04 AC2 | COVERED `test_plugin.py::test_find_plugin_source_dir_resolves_relative_source` |
| TC-UNIT-093 | SC-UNIT-028 | 루트/직계 자식 폴백 | 동상 | 동상 | 각 규약대로 경로 반환 | Medium | US-VLT04 AC2 | COVERED `test_plugin.py` (3개) |
| TC-UNIT-094 | SC-UNIT-028 | 빈 마켓 / 외부 소스 → `None` | 동상 | 동상 | `None` | Medium | US-VLT04 AC2 | COVERED `test_plugin.py` (2개) |
| TC-UNIT-095 | SC-UNIT-029 | 갱신이 `installedAt` 을 보존 | `tmp_path` 레지스트리 | `update_installed_plugin` | `installedAt` 불변, `lastUpdated`·`version` 갱신 | High | US-UPD02 | COVERED `test_update.py::test_update_installed_plugin_preserves_installed_at_and_bumps_updated` |
| TC-UNIT-096 | SC-UNIT-029 | 없는 id 갱신은 엔트리를 만든다 | 동상 | 동상 | 신규 엔트리 생성 | Medium | US-UPD02 | COVERED `test_update.py::test_update_installed_plugin_creates_entry_when_absent` |
| TC-UNIT-097 | SC-UNIT-029 | 손상 레지스트리에서 추가/제거 | 최상위가 dict 아님 | `add_installed_plugin` / `remove_installed_plugin` | 정상 구조로 재설정 후 반영 | Medium | US-SYS05 AC1 | COVERED `test_plugin.py` (2개) |

## 8. mcp

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-098 | SC-UNIT-030 | 전부 비었을 때 빈 목록 | `tmp_path` PATHS + `monkeypatch.chdir` | `collect_mcp_servers([])` | `[]` | Critical | US-MCP01 AC1 | COVERED `test_mcp.py::test_collect_mcp_servers_empty_everything` |
| TC-UNIT-099 | SC-UNIT-030 | 6개 출처가 각각 scope 를 갖는다 | 각 출처 파일 배치 | 동상 | scope 가 `plugin`/`user`/`project`/`.mcp.json`/`claude.ai`/`built-in` | Critical | US-MCP01 AC1 | COVERED `test_mcp.py` (6개) |
| TC-UNIT-100 | SC-UNIT-030 | transport 추론 (stdio / http / sse / url) | `type` 명시 / `url` 만 있음 | 동상 | `stdio` / `http` / `sse` / url 만 있으면 `http` | High | US-MCP04 AC2 | COVERED `test_mcp.py` (4개) |
| TC-UNIT-101 | SC-UNIT-030 | 설정 파일 손상·부재 방어 | 깨진 `~/.claude.json` | 동상 | plugin 출처만으로 정상 반환 | High | US-SYS05 AC1 | COVERED `test_mcp.py` (2개) |
| TC-UNIT-102 | SC-UNIT-031 | opt-out: `disabledMcpServers` 반영 | `tmp_path` `~/.claude.json`, `chdir` 고정 | 일반 서버 | 기본 `disabled=False`, 목록에 넣으면 `True` | Critical | US-MCP01 AC2 | COVERED `test_mcp.py` (2개) |
| TC-UNIT-103 | SC-UNIT-031 | opt-in: built-in 은 기본 꺼짐 | 동상 | built-in 서버 | 기본 `disabled=True`, `enabledMcpServers` 에 넣으면 `False` | Critical | US-MCP01 AC2 | COVERED `test_mcp.py` (3개) |
| TC-UNIT-104 | SC-UNIT-031 | claude.ai 커넥터의 비활성 반영 | `claudeAiMcpEverConnected` 배치 | 동상 | 프로젝트에서 비활성화 시 `disabled=True`; 값이 리스트가 아니면 무시 | High | US-MCP01 AC1 | COVERED `test_mcp.py` (3개) |
| TC-UNIT-105 | SC-UNIT-032 | disable 가 현재 프로젝트에만 기록 | `~/.claude.json` 에 2개 프로젝트, `chdir` 로 하나 고정 | `set_mcp_disabled(name, disabled=True)` | 현재 프로젝트 목록에만 추가, 다른 프로젝트 엔트리 불변 | Critical | US-MCP03 AC1, AC2 | COVERED `test_mcp.py` (2개) |
| TC-UNIT-106 | SC-UNIT-032 | 재 disable 은 idempotent, enable 은 키 pruning | 동상 | disable ×2 → enable | 중복 없음, 리스트가 비면 키 자체 제거 | High | US-MCP03 AC1 | COVERED `test_mcp.py` (3개) |
| TC-UNIT-107 | SC-UNIT-032 | built-in 토글은 `enabledMcpServers` 를 쓴다 | 동상 | built-in enable/disable | `enabledMcpServers` 에 추가/제거 (disabled 목록 아님) | Critical | US-MCP01 AC2 | COVERED `test_mcp.py` (3개) |
| TC-UNIT-108 | SC-UNIT-032 | 손상 설정에서도 토글이 성립 | 깨진 `~/.claude.json` | 동상 | 예외 없이 정상 구조로 기록 | High | US-SYS05 AC1 | COVERED `test_mcp.py::test_set_mcp_disabled_tolerates_malformed_config` |

## 9. skill / commands / agents

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-109 | SC-UNIT-033 | `.agents` 중첩·flat 레이아웃 모두 인식 | `tmp_path` home, Windows skip | `list_all_skills` | `~/.agents/skills` 우선, 없으면 flat `~/.agents` 폴백 | High | US-LNK01 AC1 | COVERED `test_skill.py` (2개) |
| TC-UNIT-110 | SC-UNIT-033 | project == HOME 일 때 중복 0건 | `project_dir == home` | 동상 | 같은 스킬이 1건만 | High | US-LNK01 AC1 | COVERED `test_skill.py::test_list_all_skills_no_duplicates_when_project_is_home` |
| TC-UNIT-111 | SC-UNIT-033 | symlink 항목의 실제 대상 기록 | 링크 배치 | `list_skills` | `is_symlink=True`, `target` 이 실제 경로 | High | US-LNK01 AC2 | COVERED `test_skill.py::test_list_skills_records_symlink_target` |
| TC-UNIT-112 | SC-UNIT-033 | 비활성 플러그인의 스킬/명령/에이전트 제외 | `enabledPlugins` 에서 off | `list_all_skills` / `list_commands` / `list_all_agents` | 해당 항목 미포함 | High | US-LNK01 AC3 | COVERED `test_commands_agents.py::test_list_commands_skips_disabled_plugin` 외 |
| TC-UNIT-113 | SC-UNIT-033 | 디렉터리 부재 / 경로가 파일 / 읽을 수 없는 `.md` | 각 상태 구성 | `list_skills` / `list_commands` | 빈 목록 또는 해당 항목만 제외, 예외 없음 | High | US-SYS05 AC4 | COVERED `test_skill.py`, `test_commands_agents.py` (4개) |
| TC-UNIT-114 | SC-UNIT-034 | frontmatter description 우선 | 없음 | 단순 frontmatter / `>` 폴디드 / `\|` 리터럴+chomp | 각 값 정확 추출 | Medium | US-LNK01 | COVERED `test_commands_agents.py` (4개) |
| TC-UNIT-115 | SC-UNIT-034 | frontmatter 없음·키 없음 → 첫 줄 폴백 | 없음 | 본문만 있는 `.md` / description 키 없는 frontmatter | 첫 줄 텍스트 | Medium | US-LNK01 | COVERED `test_commands_agents.py` (2개) |
| TC-UNIT-116 | SC-UNIT-034 | 긴 첫 줄 절단 / 빈 문서 | 없음 | 200자 첫 줄 / `""` | 잘린 문자열 / `""` | Medium | US-LNK01 | COVERED `test_commands_agents.py` (2개) |
| TC-UNIT-117 | SC-UNIT-035 | `is_symlink_supported` 가 플랫폼과 일치 | 없음 | 호출 | `sys.platform != "win32"` 와 동치 | High | US-LNK02 AC2 | COVERED `test_skill.py::test_is_symlink_supported_matches_platform` |
| TC-UNIT-118 | SC-UNIT-035 | 링크 생성 (`-n` 커스텀 이름 포함) 후 해제 | `tmp_path` skills, Windows skip | `link_skill(dir, name="alias")` → `unlink_skill("alias")` | `alias` symlink 생성 후 제거, 대상 실체 잔존 | High | US-LNK02 AC1 / US-LNK03 AC1 | COVERED `test_skill.py` (3개) |
| TC-UNIT-119 | SC-UNIT-035 | 실제 디렉터리 해제 거부 | skills 에 실제 디렉터리 | `unlink_skill` | 예외 + 디렉터리 잔존 | High | US-LNK03 AC2 | COVERED `test_skill.py` (2개) |
| TC-UNIT-120 | SC-UNIT-035 | Windows 에서 크래시 대신 거부 | `sys.platform="win32"` monkeypatch | `link_skill` / `unlink_skill` | 안내성 실패 (예외로 프로세스 중단 없음) | High | US-VLT05 AC4 | COVERED `test_skill.py` (2개) |

## 10. hooks

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-121 | SC-UNIT-036 | user/project/local 3스코프 병합 | `tmp_path` settings 3종 | `list_hooks` | 3출처 훅이 모두 등장, 각 `source` 정확 | High | US-HK01 AC1 | COVERED `test_hooks.py::test_list_hooks_merges_three_scopes` |
| TC-UNIT-122 | SC-UNIT-036 | plugin 훅 포함 + `hooks.json` 부재 방어 | plugin 설치 디렉터리 | 동상 | plugin 출처 훅 등장; `hooks.json` 없으면 조용히 건너뜀 | High | US-PLG06 AC2 | COVERED `test_hooks.py` (2개) |
| TC-UNIT-123 | SC-UNIT-036 | `disabledHooks` 미러 → `disabled=True` | settings 에 `disabledHooks` | 동상 | 해당 훅 `disabled=True` | High | US-HK01 AC1 | COVERED `test_hooks.py` (2개) |
| TC-UNIT-124 | SC-UNIT-036 | matcher/type 기본값 + 잡음 스킵 | matcher 생략 / type 생략 / 알 수 없는 이벤트 / 손상 엔트리 | `_extract_hooks` | matcher `*`, type `command`, 알 수 없는 이벤트·손상 엔트리는 스킵 | High | US-HK01 AC1 | COVERED `test_hooks.py` (4개) |
| TC-UNIT-125 | SC-UNIT-036 | http / mcp 타입 파싱 | 해당 엔트리 | 동상 | 타입별 필드가 채워짐 | Medium | US-HK01 | COVERED `test_hooks.py::test_extract_hooks_handles_http_and_mcp` |
| TC-UNIT-126 | SC-UNIT-037 | disable → enable 왕복이 무손실 | `tmp_path` settings, 한 rule 에 훅 2개 | `set_hook_disabled(path, hook, True)` → `False` | 훅 정의 dict 가 원문 그대로 복원 | Critical | US-HK02 AC1, AC3 | COVERED `test_hooks.py::test_set_hook_disabled_round_trip` |
| TC-UNIT-127 | SC-UNIT-037 | 같은 rule 의 형제 훅은 불변 | 동상 | 하나만 disable | 다른 훅은 `hooks` 에 그대로 | Critical | US-HK02 AC3 | COVERED `test_hooks.py::test_set_hook_disabled_only_targets_matching_inner_hook` |
| TC-UNIT-128 | SC-UNIT-037 | 없는 훅 지정 → `False`, 기존 rule 에 병합 | 동상 | 미존재 훅 / 기존 `disabledHooks` matcher 존재 | `False` 반환 / 새 rule 을 만들지 않고 병합 | High | US-HK02 AC1 | COVERED `test_hooks.py` (2개) |
| TC-UNIT-129 | SC-UNIT-038 | command 훅 dry-run 이 stdout/exit 를 담는다 | 무해한 `echo` 명령 | `preview_hook` | stdout·exit code 가 결과에 채워짐 | High | US-HK04 AC1 | COVERED `test_hooks.py::test_preview_hook_command_runs` |
| TC-UNIT-130 | SC-UNIT-038 | 비0 종료 / 타임아웃 / `OSError` 를 결과로 반환 | `subprocess.run` monkeypatch | 동상 | 예외 전파 없이 `HookPreviewResult` 반환, stderr·사유 포함 | Critical | US-HK04 AC2 / US-SYS06 AC2, AC3 | COVERED `test_hooks.py` (4개) |
| TC-UNIT-131 | SC-UNIT-038 | http / mcp / 프롬프트 훅 요약 | 각 타입 훅 | 동상 | 실행 없이 요약 문자열; PreToolUse 페이로드에 tool_name 포함, `*` matcher 는 기본값 사용 | Medium | US-HK04 AC1 | COVERED `test_hooks.py` (5개) |
| TC-UNIT-132 | SC-UNIT-038 | `get_hook_detail` 이 타입별 한 줄 요약 | 각 타입 | `get_hook_detail` | command/mcp 각 형식, 알 수 없는 타입은 `""` | Low | US-HK01 AC2 | COVERED `test_hooks.py` (3개) |

## 11. project usage index

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-133 | SC-UNIT-039 | 점 포함 경로를 브루트포스로 디코드 | `tmp_path` 를 `fs_root` 로 주입, `tlog.net` 디렉터리 실제 생성 | `-tmp-...-tlog-net` | 실제 경로 문자열 (최장 일치 우선) | High | US-VLT07 AC3 | COVERED `test_project_usage.py::test_decode_project_dir_name_walks_filesystem` |
| TC-UNIT-134 | SC-UNIT-039 | `-` 로 시작하지 않으면 `None` | 동상 | `"tmp-x"` | `None` | Medium | US-VLT07 AC3 | COVERED `test_project_usage.py` |
| TC-UNIT-135 | SC-UNIT-039 | 읽기 불가 / 매칭 없음 / 디렉터리 아님 → `None` | 동상 | 각 상황 | `None` (예외 아님) | Medium | US-VLT07 AC3 | COVERED `test_project_usage.py` (3개) |
| TC-UNIT-136 | SC-UNIT-040 | `default` 모드가 프로필과 symlink 를 인덱싱 | `tmp_path` projects 트리, Windows skip | `scan_project_usage(mode="default")` | 프로필 기반·symlink 기반 사용 프로젝트 목록 생성 | High | US-VLT07 AC1, AC2 | COVERED `test_project_usage.py` (2개) |
| TC-UNIT-137 | SC-UNIT-040 | `full` 모드가 `enabledPlugins` 까지 포함 | 동상 | `mode="full"` | 플러그인 항목이 `default` 에는 없고 `full` 에만 있음 | High | US-VLT07 AC2 | COVERED `test_project_usage.py::test_scan_project_usage_full_mode_indexes_enabled_plugins` |
| TC-UNIT-138 | SC-UNIT-040 | `projects` 디렉터리 부재 → 0건 | 디렉터리 미생성 | 동상 | 빈 인덱스 (예외 아님) | High | US-VLT07 AC4 | COVERED `test_project_usage.py::test_scan_project_usage_missing_dir` |
| TC-UNIT-139 | SC-UNIT-041 | 미등록 키 조회 안전 | 인메모리 인덱스 | `get_project_count` / `get_projects` | `0` / `[]` | Low | US-VLT07 AC4 | COVERED `test_project_usage.py` (2개) |
| TC-UNIT-140 | SC-UNIT-041 | 타입별 집계 + 요약 문자열 | 동상 | `scan_counts_by_type` / `format_scan_summary` | 타입별 건수 / 스타일별 요약; 알 수 없는 타입도 예외 없음 | Low | US-VLT07 AC4 | COVERED `test_project_usage.py` (2개) |

## 12. usage 파싱·집계·캐시

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-141 | SC-UNIT-042 | assistant 레코드에서 4종 토큰 추출 | `tmp_path` JSONL | `usage.{input_tokens=100, output_tokens=200, cache_creation_input_tokens=300, cache_read_input_tokens=400}` | `ClaudeUsageEntry(input=100, output=200, cache_creation=300, cache_read=400)` | Critical | US-USG01 | COVERED `test_usage_claude.py::test_parse_claude_jsonl_extracts_assistant_records` |
| TC-UNIT-142 | SC-UNIT-042 | 깨진 줄·빈 줄·비dict message 스킵 | 동상 | 유효 2줄 + 잡음 3줄 | 유효 2건만 반환 | Critical | US-SYS05 | COVERED `test_usage_claude.py` (2개) |
| TC-UNIT-143 | SC-UNIT-042 | 파일 부재 → 빈 리스트 | 없는 경로 | `parse_claude_jsonl` | `[]` | High | US-SYS05 AC3 | COVERED `test_usage_claude.py::test_parse_claude_jsonl_missing_file` |
| TC-UNIT-144 | SC-UNIT-043 | v2 인코딩→디코딩 왕복 | 인메모리 intern 테이블 | 엔트리 3건 | 모든 필드 복원, `project_path` 는 파일 키의 부모 디렉터리명 | Critical | US-USG08 AC2 | PARTIAL — 캐시 왕복은 검증되나 `_encode/_decode` 단독 왕복 TC 부재 |
| TC-UNIT-145 | SC-UNIT-043 | 같은 model/session 은 intern 테이블에 1회만 | 동상 | 같은 model 을 쓰는 엔트리 5건 | `models` 테이블 길이 1, 각 행이 같은 인덱스 참조 | Critical | US-USG08 AC2 | NEW |
| TC-UNIT-146 | SC-UNIT-043 | 손상된 위치 배열 행은 스킵 | 동상 | 길이 5짜리 행 1개 + 정상 행 2개 | 정상 2건만 복원, 예외 없음 | High | US-USG08 AC3 | NEW |
| TC-UNIT-147 | SC-UNIT-043 | v1 캐시는 폐기 후 재빌드 | `tmp_path` 캐시에 `version: 1` payload, `_cache_path` monkeypatch | `load_all_claude_usage` | v1 행이 결과에 쓰이지 않고 JSONL 재파싱, 저장 시 `version: 2` | Critical | US-USG08 AC2 | NEW |
| TC-UNIT-148 | SC-UNIT-044 | mtime 동일 시 재파싱 없음 | `tmp_path` projects + `_cache_path` monkeypatch, 파서 호출 카운터 | 2회 연속 로드 | 두 번째 로드에서 파싱 호출 0회 | High | US-USG08 AC1 | COVERED `test_usage_claude.py::test_load_all_claude_usage_per_file_cache_hit_skips_reparse` |
| TC-UNIT-149 | SC-UNIT-044 | `is_cache_valid` TTL 판정 | `lastUpdated` 문자열 직접 주입 | 없음 / 파싱 불가 / 신선 | `False` / `False` / `True` | High | US-USG08 AC1 | COVERED `test_usage_claude.py` (3개) |
| TC-UNIT-150 | SC-UNIT-044 | 손상 캐시에서 재빌드로 복구 | 깨진 캐시 JSON | `load_all_claude_usage` | 예외 없이 JSONL 재파싱 결과 반환 | Critical | US-USG08 AC3 | PARTIAL — 빈 디렉터리·부재는 있으나 **손상 캐시 복구** 단독 TC 부재 |
| TC-UNIT-151 | SC-UNIT-045 | 같은 날 엔트리를 하나로 묶는다 | timestamp 를 명시 ISO 로 고정, tz=`UTC` | 같은 날 3건 | `DailyUsage` 1건, 토큰 합계 정확 | High | US-USG01 AC2 | COVERED `test_usage_claude.py::test_aggregate_daily_groups_by_date` |
| TC-UNIT-152 | SC-UNIT-045 | 타임존 경계에서 날짜가 갈린다 | 동상, tz=`Asia/Seoul` | `2026-03-01T20:00:00Z` | 로컬 기준 `2026-03-02` 로 분류 | High | US-USG01 AC2 | COVERED `test_usage_claude.py::test_date_in_tz_converts_to_local_day` |
| TC-UNIT-153 | SC-UNIT-045 | 세션별 집계가 메시지 수·모델 집합을 채운다 | 동상 | 2세션 5엔트리 | 세션별 분리, `message_count`·`models`·first/last timestamp 정확 | High | US-USG05 AC1 | COVERED `test_usage_claude.py::test_aggregate_by_session` |
| TC-UNIT-154 | SC-UNIT-046 | 블록 시작 = 첫 엔트리 시각의 floor-to-hour(UTC) | timestamp 명시 고정 | 첫 엔트리 `2026-03-01T10:37:00Z` | `blockStart == 2026-03-01T10:00:00Z` (벽시계 `10:00` 정렬 우연 일치 아님을 `13:37` 케이스로도 확인) | Critical | US-USG04 AC1 | COVERED `test_usage_claude.py::test_compute_blocks_anchored_to_first_entry_hour` |
| TC-UNIT-155 | SC-UNIT-046 | 5h 경과 후 첫 엔트리가 새 블록을 연다 | 동상 | `10:37Z` + `16:20Z` | 블록 2개, 두 번째 `blockStart == 16:00Z` | Critical | US-USG04 AC2 | COVERED `test_usage_claude.py` (2개) |
| TC-UNIT-156 | SC-UNIT-046 | 옛 UTC 경계(00/05/10)를 가로질러도 5h 안이면 한 블록 | 동상 | `09:30Z` + `11:00Z` | 블록 1개 | Critical | US-USG04 AC1 | COVERED `test_usage_claude.py::test_compute_blocks_activity_spanning_old_utc_boundary_stays_in_one_block` |
| TC-UNIT-157 | SC-UNIT-046 | `isActive` 와 burn rate | `datetime.now` monkeypatch 로 현재 시각 고정 | 활성 블록 / 종료된 블록 | 활성만 `is_active=True` + `burn_rate = tokens / 경과분`, 비활성은 `None` | Critical | US-USG04 AC3, AC5 | COVERED `test_usage_claude.py` (2개) |
| TC-UNIT-158 | SC-UNIT-046 | 빈 입력 / 파싱 불가 timestamp | 동상 | `[]` / 잘못된 timestamp 1건 | `[]` / 해당 엔트리만 제외 | High | US-USG04 | COVERED `test_usage_claude.py` (2개) |
| TC-UNIT-159 | SC-UNIT-046 | 블록 비용은 엔트리별 모델 단가 합 | 여러 모델 혼재 | `compute_blocks` | opus 하드코딩이 아니라 모델별 단가로 합산 | Critical | US-USG06 AC1 | COVERED `test_usage_claude.py` (2개) |
| TC-UNIT-160 | SC-UNIT-047 | 기간 필터가 경계를 포함한다 | 명시 ISO 입력 | `since == 엔트리 날짜`, `until == 엔트리 날짜` | 해당 엔트리 포함 | High | US-USG02 AC3 | COVERED `test_usage_claude.py` (2개) |
| TC-UNIT-161 | SC-UNIT-047 | 상·하한 미지정 / 파싱 불가 항목 | 동상 | 없음 / 잘못된 timestamp | 전량 반환 / 해당 항목만 제외 | Medium | US-USG02 AC3 | COVERED `test_usage_claude.py` (2개) |
| TC-UNIT-162 | SC-UNIT-047 | 잘못된 타임존·timestamp 는 UTC 슬라이스로 폴백 | 동상 | tz=`"Not/AZone"` | 예외 없이 UTC 기준 날짜 | Medium | US-USG01 AC2 | COVERED `test_usage_claude.py` (4개) |

## 13. pricing / plan / config

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-163 | SC-UNIT-048 | 정확 일치 단가 | `reload_pricing_table()` | `claude-opus-4-7` | `input=5.00, output=25.00, cache_write=6.25, cache_read=0.50` | Critical | US-USG06 AC1 | COVERED `test_pricing.py::test_get_model_pricing_exact_match` |
| TC-UNIT-164 | SC-UNIT-048 | 가장 긴 키 우선 접두 매칭 | 동상 | `claude-opus-4-7-r1` | `claude-opus-4` 가 아니라 `claude-opus-4-7` 의 단가 | Critical | US-USG06 AC1 | COVERED `test_pricing.py::test_get_model_pricing_prefix_match` |
| TC-UNIT-165 | SC-UNIT-048 | Claude 5 계열 단가 | 동상 | `claude-fable-5` / `claude-sonnet-5` / `claude-haiku-4-5` | 10/50/12.5/1.0, 3/15/3.75/0.3, 1/5/1.25/0.1 | Critical | US-USG06 AC1 | COVERED `test_pricing.py::test_get_model_pricing_claude_5_family` |
| TC-UNIT-166 | SC-UNIT-048 | 미등록 모델 → `None` | 동상 | `"gpt-9"` | `None`, `get_context_window_size` 도 `None` | High | US-USG06 AC2 | COVERED `test_pricing.py` (2개) |
| TC-UNIT-167 | SC-UNIT-048 | 컨텍스트 윈도우 크기 | 동상 | opus/sonnet/fable / haiku | 1,000,000 / 200,000 | High | US-CTX01 | COVERED `test_pricing.py::test_get_context_window_claude_models` |
| TC-UNIT-168 | SC-UNIT-049 | output 5,000,000 토큰 = $125.00 | 동상 | `TokenUsage(0, 5_000_000, 0, 0)`, `claude-opus-4-7` | `125.00` (approx) | Critical | US-USG06 AC1 | COVERED `test_pricing.py::test_calculate_cost_claude_opus` |
| TC-UNIT-169 | SC-UNIT-049 | 4종 토큰이 각각 기여 | 동상 | 각 1,000,000, `claude-opus-4-7` | `5.00+25.00+6.25+0.50 = 36.75` | Critical | US-USG06 AC1 | COVERED `test_pricing.py::test_calculate_cost_each_token_type_contributes` |
| TC-UNIT-170 | SC-UNIT-049 | 0 토큰 / 미등록 모델 → $0 | 동상 | 전부 0 / `"gpt-9"` | `0.0` | High | US-USG06 AC2 | COVERED `test_pricing.py` (2개) |
| TC-UNIT-171 | SC-UNIT-050 | 캐시 절감 = cacheRead × (input − cacheRead) | 동상 | cacheRead 2,000,000, `claude-opus-4-7` | `2 × (5.00 − 0.50) = 9.00` | High | US-USG06 AC1 | COVERED `test_pricing.py::test_calculate_cache_savings_uses_input_minus_cache_read_rate` |
| TC-UNIT-172 | SC-UNIT-050 | cacheWrite 는 절감에 포함하지 않음 / 미등록 모델 0 | 동상 | cacheWrite 만 / `"gpt-9"` | `0.0` | High | US-USG06 AC1 | COVERED `test_pricing.py` (2개) |
| TC-UNIT-173 | SC-UNIT-051 | 미등록 모델을 모델별 건수로 반환 | 동상 | 미등록 모델 3건 + 등록 2건 | `{미등록: 3}` | High | US-USG06 AC3 | COVERED `test_pricing.py::test_find_unpriced_models_counts_by_model` |
| TC-UNIT-174 | SC-UNIT-051 | 전부 등록 모델이면 빈 dict | 동상 | 등록 모델만 | `{}` | High | US-USG06 AC3 | COVERED `test_pricing.py::test_find_unpriced_models_empty_when_all_priced` |
| TC-UNIT-175 | SC-UNIT-051 | `unknown` / `<synthetic>` 는 세지 않는다 | 동상 | 해당 모델 표식 2건 | `{}` | High | US-USG06 AC3 | PARTIAL — `_is_real_model` 은 `test_context.py` 에서 간접 검증, `find_unpriced_models` 경유 TC 부재 |
| TC-UNIT-176 | SC-UNIT-052 | usd↔krw 변환 | 없음 | `(10, "usd", "krw", 1400)` / `(14000, "krw", "usd", 1400)` | `14000.0` / `10.0` | Medium | US-USG01 | COVERED `test_pricing.py` (2개) |
| TC-UNIT-177 | SC-UNIT-052 | 동일 통화 / 미지원 조합 / 환율 0 | 없음 | 각 상황 | 원값 반환, `ZeroDivisionError` 없음 | Medium | US-USG01 | PARTIAL — 동일 통화·미지원 조합은 `test_pricing.py` 가 덮지만 환율 0 분기 미검증 |
| TC-UNIT-178 | SC-UNIT-053 | 월중 시각의 경과일·주기길이 | `now=datetime(2026,3,20,tzinfo=utc)` 명시 주입 | `billing_start=15` | `(5, 31)` | Critical | US-USG07 AC3 | COVERED `test_pricing.py::test_get_days_in_billing_period_basic` |
| TC-UNIT-179 | SC-UNIT-053 | 시작일 이전이면 전월로 롤백 | `now` 명시 주입 | `billing_start=25`, `now=2026-03-10` | 주기 시작 `2026-02-25`, elapsed 계산이 그 기준 | Critical | US-USG07 AC3 | COVERED `test_pricing.py::test_get_days_in_billing_period_rolls_back` |
| TC-UNIT-180 | SC-UNIT-053 | 1월→12월 롤백 / 12월 주기가 해를 넘김 | `now` 명시 주입 | `now=2026-01-05`, `billing_start=20` / `now=2026-12-25`, `billing_start=20` | 각각 전년 12월 시작 / 다음 해 1월 종료, `total` 정확 | Critical | US-USG07 AC3 | COVERED `test_pricing.py` (2개) |
| TC-UNIT-181 | SC-UNIT-053 | `billing_start=31` 은 28로 클램프, 첫날은 elapsed 0 | `now` 명시 주입 | `billing_start=31` / `now` == 주기 시작일 | 시작일 day 28 / `elapsed == 0` | High | US-USG07 AC5 | NEW |
| TC-UNIT-182 | SC-UNIT-054 | 월말 예측 = 사용액 ÷ 경과일 × 주기일 | 없음 | `(60.0, 6, 30)` | `300.0` | Critical | US-USG07 AC3 | COVERED `test_pricing.py::test_project_monthly_cost_basic` |
| TC-UNIT-183 | SC-UNIT-054 | 경과일 0/음수에서 0나눗셈 없음 | 없음 | `(60.0, 0, 30)` / `(60.0, -1, 30)` | `0.0`, 예외 없음 | Critical | US-USG07 AC5 | PARTIAL — `test_project_monthly_cost_zero_days` 가 0 은 덮지만 음수 분기 미검증 |
| TC-UNIT-184 | SC-UNIT-054 | `compute_plan_usage` 필드 일관성 | 없음 | `(config, 60.0, 6, 30)` | `daily_avg=10.0`, `days_remaining=24`, `projected=300.0`; elapsed=0 이면 `daily_avg=0.0` | Critical | US-USG07 AC3, AC5 | PARTIAL — 정상 케이스만 있고 elapsed=0 분기 미검증 |
| TC-UNIT-185 | SC-UNIT-055 | tier 문자열 정규화 | 없음 | `default_claude_max_20x` / `..._max_5x` / `..._pro` / `"weird"` | `("max-20x",200.0)` / `("max-5x",100.0)` / `("pro",20.0)` / `None` | High | US-USG07 AC1 | COVERED `test_pricing.py::test_parse_rate_limit_tier` |
| TC-UNIT-186 | SC-UNIT-055 | user tier 가 org tier 보다 우선 | `tmp_path` 가짜 `.claude.json` 경로 주입 | 두 필드 모두 존재 | user tier 결과 | High | US-USG07 AC1 | COVERED `test_pricing.py` (2개) |
| TC-UNIT-187 | SC-UNIT-055 | `oauthAccount` / 파일 부재 → `None` | 동상 | 각 상황 | `None` | High | US-USG07 AC1 | COVERED `test_pricing.py` (2개) |
| TC-UNIT-188 | SC-UNIT-055 | 수동 고정이 자동 감지를 이긴다 | `tmp_path` config | `auto_detect_plan=False` + 저장된 플랜 | 감지값이 저장 플랜을 덮지 않음; `auto_detect_plan=True` 면 오버레이; 감지 실패 시 저장값 폴백 | High | US-USG07 AC2 | COVERED `test_pricing.py` (3개) |
| TC-UNIT-189 | SC-UNIT-056 | 파일 부재·부분 키·비dict payload | `tmp_path` config 경로 주입 | 각 상황 | 기본값 폴백, 예외 없음 | Medium | US-SYS05 AC1 | COVERED `test_pricing.py` (4개) |
| TC-UNIT-190 | SC-UNIT-056 | 저장→로드 왕복 (theme, plans, auto_detect) | 동상 | 값 저장 후 로드 | 동일 값 복원 | Medium | US-TUI09 AC1 | COVERED `test_pricing.py` (3개) |
| TC-UNIT-191 | SC-UNIT-057 | 우선순위: CLI > config > auto | `monkeypatch.setenv`/`delenv` | (`light`, `dark`) / (`None`, `dark`) | `light` / `dark` | Medium | US-TUI09 AC2 | COVERED `test_pricing.py::test_resolve_theme_priority` |
| TC-UNIT-192 | SC-UNIT-057 | `COLORFGBG` 로 밝은 배경 감지 / 미설정 폴백 | 동상 | `COLORFGBG="0;15"` / 미설정 | `light` / 기본 `dark` | Medium | US-TUI09 AC1 | COVERED `test_pricing.py::test_detect_terminal_is_light_via_colorfgbg` |
| TC-UNIT-193 | SC-UNIT-058 | 신선한 스냅샷은 값 반환, 오래되면 `None` | `tmp_path` 스냅샷, `updated_at` 을 현재 기준 상대값으로 작성 | 1분 전 / 30분 전 | 값 / `None` (기본 5분 tolerance) | Medium | US-CTX06 AC2 | COVERED `test_pricing.py` (2개) |
| TC-UNIT-194 | SC-UNIT-058 | 백분율 0~100 클램프 | 동상 | `120` / `-5` | `100` / `0` | Medium | US-CTX06 AC2 | COVERED `test_pricing.py::test_read_rate_limits_clamps_percent` |
| TC-UNIT-195 | SC-UNIT-058 | 부재·손상·필드 결손·형식 불량·unix 초/밀리초 | 동상 | 각 상황 | 부재/손상/`updated_at` 부재/백분율 전무 → `None`; `resets_at` 불량은 나머지 필드 유효; unix 초·밀리초 모두 해석 | Medium | US-SYS05 AC1 | COVERED `test_pricing.py` (9개) |

## 14. context 분석

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-196 | SC-UNIT-059 | 빈 문자열은 0 토큰 | 없음 | `""` | `0` | High | US-CTX01 | COVERED `test_context.py::test_estimate_tokens_empty` |
| TC-UNIT-197 | SC-UNIT-059 | ASCII 는 1/3.5 | 없음 | `"a"*35` | `ceil(35/3.5) == 10` | High | US-CTX01 | COVERED `test_context.py::test_estimate_tokens_ascii_only` |
| TC-UNIT-198 | SC-UNIT-059 | 한글/한자/히라가나는 1/1.5 | 없음 | 한글 15자 | `ceil(15/1.5) == 10` | High | US-CTX01 | COVERED `test_context.py` (3개) |
| TC-UNIT-199 | SC-UNIT-059 | 혼합 문자열은 두 항의 합을 올림 | 없음 | 한글 3 + ASCII 7 | `ceil(3/1.5 + 7/3.5) == 4` | High | US-CTX01 | COVERED `test_context.py::test_estimate_tokens_mixed` |
| TC-UNIT-200 | SC-UNIT-060 | 최소 환경에서도 고정 소스 2종 존재 | `tmp_path` home/project, 외부 명령 monkeypatch | `collect_context_sources` | `system-prompt` 4,200 tok + `user-context` 280 tok | Critical | US-CTX01 AC1 / US-CTX02 AC1 | COVERED `test_context.py::test_collect_context_minimum` |
| TC-UNIT-201 | SC-UNIT-060 | 12개 카테고리가 모두 등장 | 파일 전 종류 + plugin 이 skill/mcp/command/agent/hook 제공 | 동상 | 12 카테고리 모두 존재, 각 소스에 category/scope/path | Critical | US-CTX01 AC1 | COVERED `test_context.py` (4개) |
| TC-UNIT-202 | SC-UNIT-060 | 비활성 플러그인의 소스는 제외 | `enabledPlugins` off | 동상 | 해당 소스 미포함 | High | US-PLG06 AC3 | COVERED `test_context.py::test_collect_context_skips_disabled_plugin` |
| TC-UNIT-203 | SC-UNIT-060 | 헬퍼 `OSError` 를 삼킨다 | 읽기 실패 주입 | 동상 | 해당 소스만 빠지고 나머지 수집 | High | US-SYS05 AC4 | COVERED `test_context.py::test_collect_context_swallows_helper_oserrors` |
| TC-UNIT-204 | SC-UNIT-061 | `.agents/skills` 전용 스킬은 세지 않는다 | `tmp_path` home, Windows skip | `.agents/skills/only-here` | 컨텍스트 소스에 미포함 | High | US-CTX03 AC1 | PARTIAL — dedup TC 는 있으나 **`.agents` 단독 스킬 제외** 단언 부재 |
| TC-UNIT-205 | SC-UNIT-061 | symlink 로 두 번 보이는 스킬은 1건 | `.agents` 실체 + `.claude` symlink | 동상 | 정확히 1건 | High | US-CTX03 AC1 | COVERED `test_context.py::test_collect_context_dedups_symlinked_skill` |
| TC-UNIT-206 | SC-UNIT-061 | `.agents/agents` 전용 에이전트는 세지 않는다 | 동상 | `.agents/agents/only-here.md` | 컨텍스트 소스에 미포함 | High | US-CTX03 AC2 | NEW |
| TC-UNIT-207 | SC-UNIT-062 | settings 4곳을 본다 | 4개 파일 모두 배치 | `collect_context_sources` | `settings` 카테고리 4건 (global 2 + project 2), scope 정확 | High | US-CTX03 AC3 | COVERED `test_context.py` (2개) |
| TC-UNIT-208 | SC-UNIT-062 | project settings 는 프로젝트 트리에서 읽는다 | `<proj>/.claude/settings.json` 만 배치 | 동상 | 해당 파일이 수집됨 (`~/.claude/projects/<key>/` 아님) | High | US-CTX03 AC3 | COVERED `test_context.py::test_collect_context_project_settings_from_project_tree` |
| TC-UNIT-209 | SC-UNIT-062 | disabled MCP 서버는 mcp-tools 에서 제외 | `disabledMcpServers` 에 1건 | 동상 | 해당 서버 미포함, 나머지 포함 | High | US-CTX03 AC4 | COVERED `test_context.py::test_collect_context_mcp_covers_all_registration_sources` |
| TC-UNIT-210 | SC-UNIT-062 | 비`.md`·읽기 불가 memory 파일 스킵 | memory 디렉터리에 `notes.txt` / 권한 없는 `.md` | 동상 | 해당 파일만 제외 | Medium | US-SYS05 AC4 | COVERED `test_context.py` (2개) |
| TC-UNIT-211 | SC-UNIT-063 | 고정비 소스는 `actionable=False` | 동상 | system-prompt / user-context | 둘 다 `actionable=False` | Medium | US-CTX02 AC1 | PARTIAL — 힌트 테스트가 `actionable=False` 를 픽스처로만 쓰고 수집기 산출값을 단언하지 않음 |
| TC-UNIT-212 | SC-UNIT-063 | 조정 가능한 소스는 `actionable=True` | 동상 | skills / commands / agents / claude-md / memory / **mcp-tools** | 모두 `actionable=True` | Medium | US-CTX02 AC2 | NEW — 스펙 갭 G-4 (mcp-tools·plugins 는 현재 `False`) |
| TC-UNIT-213 | SC-UNIT-064 | 90일 초과 memory 에 힌트가 붙는다 | `os.utime` 으로 mtime 을 200일 전으로 고정 | `add_context_hints` | 힌트에 `not modified in`·`(>90 days)` 포함 | High | US-CTX04 AC1 | COVERED `test_context.py::test_add_context_hints_memory_old_and_recent` |
| TC-UNIT-214 | SC-UNIT-064 | 최근 memory 는 토큰 힌트만 | mtime 1일 전 | 동상 | `>90 days` 문구 없음 | High | US-CTX04 AC1 | COVERED `test_context.py` (동일 테스트) |
| TC-UNIT-215 | SC-UNIT-064 | mtime 을 읽을 수 없는 memory | 존재하지 않는 path 를 가진 소스 | 동상 | 예외 없이 토큰 힌트만 | Medium | US-SYS05 AC4 | COVERED `test_context.py::test_add_context_hints_memory_unreadable_mtime_only_token_hint` |
| TC-UNIT-216 | SC-UNIT-064 | 카테고리별 고정 힌트 | 인메모리 소스 목록 | hooks / git-status / mcp-tools / 500 tok 이하 claude-md / top-3 skill | 각각 `~N tok estimated output` / `live estimate` / `deferred` / 힌트 없음 / `top context consumer` | Medium | US-CTX01 | COVERED `test_context.py` (3개) |
| TC-UNIT-217 | SC-UNIT-065 | memory 삭제가 인덱스 줄도 지운다 | `tmp_path` memory + `MEMORY.md` 3줄 | `delete_memory_file(memory/a.md)` | 파일 삭제 + `MEMORY.md` 에서 `a.md` 링크 줄만 제거(나머지 2줄 보존) | High | US-CTX04 AC3 | COVERED `test_context.py::test_delete_memory_file_removes_file_and_index_line` |
| TC-UNIT-218 | SC-UNIT-065 | 인덱스 부재 / `MEMORY.md` 자체 삭제 | 각 상황 | 동상 | no-op / 인덱스 정리 스킵, 예외 없음 | Medium | US-CTX04 AC3 | COVERED `test_context.py` (2개) |
| TC-UNIT-219 | SC-UNIT-065 | `memory/` 밖 경로 거부 | `tmp_path/other/x.md` | 동상 | `ValueError`, 파일 잔존 | High | US-SYS08 | COVERED `test_context.py::test_delete_memory_file_rejects_path_outside_memory_dir` |
| TC-UNIT-220 | SC-UNIT-066 | 총합·윈도우·비율이 일관 | 외부 명령 monkeypatch, 모델 명시 | `analyze_context(model="claude-opus-4-8")` | `total == sum(sources)`, `used_percent == total/1_000_000*100` | High | US-CTX01 | COVERED `test_context.py` (2개) |
| TC-UNIT-221 | SC-UNIT-066 | cost impact 공식 | 동상 | `avg_turns=30`, `avg_sessions=5` | `per_session == cache_write + 29 × cache_read`, `monthly == per_session × 5 × 30` | High | US-CTX06 AC3 | COVERED `test_context.py::test_analyze_context_includes_cost_impact` |
| TC-UNIT-222 | SC-UNIT-066 | 다른 윈도우 모델 / 미등록 모델 | 동상 | `claude-haiku-4-5` / `"gpt-9"` | window 200,000 / 1,000,000 폴백 + 비용 0 | Medium | US-USG06 AC2 | PARTIAL — 기본 모델 경로만 검증 |

## 15. update 티어링

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-223 | SC-UNIT-067 | 전체 스윕이 티어별로 분류 | 각 updater monkeypatch | `check_all_updates()` | plugin/marketplace/git-skill 은 tier 1, MCP·non-git 은 tier 2, claude-code 는 tier 3 | High | US-UPD01 AC2 | COVERED `test_update.py` (5개) |
| TC-UNIT-224 | SC-UNIT-067 | 한 updater 의 예외가 나머지를 죽이지 않는다 | 하나가 raise 하도록 monkeypatch | 동상 | 나머지 결과 정상 반환 | High | US-UPD05 AC4 | COVERED `test_update.py::test_check_all_updates_isolates_a_raising_updater` |
| TC-UNIT-225 | SC-UNIT-067 | `types` 로 범위 축소 | 동상 | `types=["plugin"]` | plugin 상태만 반환 | Medium | US-UPD04 AC1 | PARTIAL — CLI 경유로만 검증, 함수 레벨 TC 부재 |
| TC-UNIT-226 | SC-UNIT-067 | MCP updater 는 리포트 전용 | 동상 | `_mcp_check_all` | `tier=2`, `updatable=False`, `note` 에 `pinned @x.y.z`/`floating (@latest)`/`unpinned` 표기 | High | US-UPD02 AC1 | COVERED `test_update.py` (3개) |
| TC-UNIT-227 | SC-UNIT-068 | git repo 스킬은 tier 1, non-git 은 tier 2 | `tmp_path` 에 `.git` 유무, `_git` monkeypatch | `_skill_check_all` | 각각 tier 1 / tier 2(manual) | High | US-UPD02 AC1 | COVERED `test_update.py::test_skill_updater_tiers_git_vs_nongit` |
| TC-UNIT-228 | SC-UNIT-068 | symlink 를 따라 실제 디렉터리로 판정 | symlink 스킬, Windows skip | `check_path_update` | 링크 대상 기준 상태 | High | US-UPD02 AC1 | COVERED `test_update.py` (2개) |
| TC-UNIT-229 | SC-UNIT-068 | 상위 ambient 저장소를 잘못 잡지 않는다 | 항목 상위에만 `.git` | 동상 | 업데이트 대상 아님(tier 2) | High | US-UPD02 AC1 | COVERED `test_update.py::test_git_updater_ignores_ambient_config_repo` |
| TC-UNIT-230 | SC-UNIT-068 | fetch/pull 실패는 error 로 흡수 | `_git` 실패 주입 | `_git_dir_apply` | `error` 채워짐, 예외 미전파 | High | US-SYS06 AC1 | COVERED `test_update.py::test_git_updater_absorbs_fetch_failure` |
| TC-UNIT-231 | SC-UNIT-069 | 상태 캐시 저장→로드 왕복 | `_update_status_cache_path` → `tmp_path` | 상태 3건 + `checked_at` | 동일 목록·시각 복원 | Medium | US-UPD05 AC2 | COVERED `test_update.py::test_update_status_cache_roundtrip` |
| TC-UNIT-232 | SC-UNIT-069 | 부재·손상 캐시 → `([], None)` | 동상 | 파일 없음 / 깨진 JSON | `([], None)` | Medium | US-UPD05 AC2 | COVERED `test_update.py::test_update_status_cache_missing_or_corrupt` |

## 16. TUI 순수 헬퍼

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-233 | SC-UNIT-070 | ASCII / CJK / 혼합 셀 폭 | 없음 | `"abc"` / `"한글"` / `"a한b"` | `3` / `4` / `4` | High | US-TUI10 AC3 | COVERED `test_tui.py` (cell_width 계열) |
| TC-UNIT-234 | SC-UNIT-070 | `width <= 0` 은 빈 문자열 | 없음 | `fit_cells("abc", 0)` / `-1` | `""` | High | US-TUI10 AC2 | COVERED `test_tui.py` |
| TC-UNIT-235 | SC-UNIT-070 | wide 문자가 경계에 걸리면 잘린다 | 없음 | `fit_cells("한글", 3)` | `cell_width(결과) <= 3`, 폭 초과 없음 | High | US-TUI10 AC3 | COVERED `test_tui.py` |
| TC-UNIT-236 | SC-UNIT-070 | 짧은 문자열은 공백으로 패딩 | 없음 | `fit_cells("ab", 5)` | `"ab   "` (정확히 5셀) | Medium | US-TUI10 AC3 | COVERED `test_tui.py` |
| TC-UNIT-237 | SC-UNIT-071 | `1.10.0` 이 `1.9.0` 보다 뒤 | 없음 | 두 버전 정렬 | `1.9.0` → `1.10.0` 순 | High | US-TUI03 AC7 | COVERED `test_tui.py::test_sort_by_version_is_numeric_aware` |
| TC-UNIT-238 | SC-UNIT-071 | `v` 접두사 무시 | 없음 | `_ver_key("v1.2.3") == _ver_key("1.2.3")` | 동일 키 | Medium | US-TUI03 AC7 | PARTIAL — 정렬 결과로만 간접 확인 |
| TC-UNIT-239 | SC-UNIT-071 | 값 없음·`—` 은 오름차순 마지막 | 없음 | `""` / `None` / `"—"` | 다른 모든 버전보다 뒤 | High | US-TUI03 AC7 | COVERED `test_tui.py::test_sort_by_version_is_numeric_aware` |
| TC-UNIT-240 | SC-UNIT-072 | 8개 서브탭을 모두 덮는다 | 없음 | `_SORT_COLUMNS` 키 집합 | `EXTENSION_SUB_TABS` 키 집합과 동일 | High | US-TUI03 AC1 | COVERED `test_tui.py::test_every_sub_tab_has_a_sort_cycle` |
| TC-UNIT-241 | SC-UNIT-072 | `marked_col` 이 실제 렌더 컬럼에 존재 | 없음 | 각 스펙 항목 | `marked_col` 은 `None` 이거나 자기 key 와 같고, 그 서브탭의 렌더 컬럼 키 집합에 포함 | High | US-TUI03 AC5 | COVERED `test_tui.py::test_sort_columns_match_rendered_columns` |
| TC-UNIT-242 | SC-UNIT-072 | key 중복 없음 / `#` 은 정렬 대상 아님 | 없음 | 동상 | 서브탭 내 key 유일, `"no"` 키 부재 | High | US-TUI03 AC1 | COVERED `test_tui.py` (2개) |
| TC-UNIT-243 | SC-UNIT-072 | 힌트 문자열이 표에서 파생 | 없음 | `sort_cycle_help("market")` | `"name→upd→kind→loc→updated"`, 없는 서브탭은 `""` | Medium | US-TUI08 AC1 | COVERED `test_tui.py::test_sort_cycle_help_lists_the_columns` |
| TC-UNIT-244 | SC-UNIT-073 | 글리프 랭크 순서대로 정렬 | 인메모리 `TuiState` + 더미 항목 | `●`/`○`/`·`/`─` 혼재 | `● → ○ → · → ─` 순 (오름차순) | Medium | US-TUI03 AC6 | PARTIAL — 렌더 결과 기준 정렬은 검증되나 랭크 표 자체 대조 TC 부재 |
| TC-UNIT-245 | SC-UNIT-073 | `Upd` 랭크와 알 수 없는 글리프 | 동상 | `↑`/`!`/`…`/`·`/`─` + 미지정 | `↑ → ! → … → · → ─`, 미지정은 마지막 | Medium | US-TUI03 AC6 | PARTIAL |
| TC-UNIT-246 | SC-UNIT-073 | 방향 토글이 정확한 역순 | 동상 | `S` 로 방향 뒤집기 | 항목 순서가 정확히 뒤집힘, 행 수 불변 | Medium | US-TUI03 AC3, AC8 | COVERED `test_tui.py::test_sort_direction_reverses_the_order` |

## 17. 기타 시스템 함수

| ID | SC | Title | Preconditions | Input | Expected Output | Pri | US | Gap |
|---|---|---|---|---|---|---|---|---|
| TC-UNIT-247 | SC-UNIT-074 | 마커 부재 시 최초 실행 | `_onboarded_marker_path` → `tmp_path` | `is_first_run()` | `True` | Medium | US-SYS02 AC1 | COVERED `test_first_run.py::test_is_first_run_true_when_marker_absent` |
| TC-UNIT-248 | SC-UNIT-074 | 마커 생성 후 두 번째부터 `False`, 삭제 시 복귀 | 동상 | `mark_onboarded()` → `is_first_run()` → 마커 삭제 → `is_first_run()` | `False` → `True` | Medium | US-SYS02 AC2, AC3 | COVERED `test_first_run.py` (2개) |
| TC-UNIT-249 | SC-UNIT-074 | 마커 쓰기 실패를 삼킨다 | `Path.touch` / `mkdir` 에 `OSError` 주입 | `mark_onboarded()` | 예외 없이 반환 | Medium | US-SYS02 AC1 | COVERED `test_first_run.py::test_mark_onboarded_swallows_errors` |
| TC-UNIT-250 | SC-UNIT-075 | 성공/실패를 분리 수집 | 없음 | 3항목 중 1개가 예외 | `results` 2건 + `errors` 1건 | Medium | US-UPD06 AC2 | COVERED `test_marketplace.py::test_pooled_map_collects_errors` |
| TC-UNIT-251 | SC-UNIT-075 | 빈 입력 / 콜백 호출 횟수 | 없음 | `[]` / `on_result`·`on_error` 지정 | 빈 결과 / 항목별 정확히 1회 | Medium | US-SYS06 | COVERED `test_marketplace.py` (2개) |

---

**작성 대상 요약** — `NEW` / `PARTIAL` 로 표기된 26건이 gap-code 단계의 입력이다. 그중
TC-UNIT-212(`actionable`) 는 구현이 아니라 **스펙 확정이 먼저** 필요하다. TC-UNIT-084 는 `tests/doc/SPEC_DECISIONS.md` SD-001 로 해소됨 (구현이 옳고 낡은 문서를 정정)
(`unit-scenarios.md` 의 `## 스펙 갭` G-2 / G-4 참조).
