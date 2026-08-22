# Unit 테스트 시나리오 — axt

순수/준순수 함수의 입력→출력과 경계값을 소유하는 계층이다. 기대값은 `tests/doc/user-stories.md` 와
`FEATURES.md` 에서만 나온다 — 구현을 실행해서 얻은 값이 아니다.

- **Layer Owner**: 순수 함수 입출력·경계값 (`TEST_DEDUP_POLICY.md` §2)
- **금지**: CLI exit code / stdout 형태(api 소유), 키 입력→렌더(e2e 소유), 경로 탈출·자격증명 노출(security 소유)
- **결정성**: `datetime.now()` / 파일 mtime / cwd / `$HOME` 에 닿는 시나리오는 Preconditions 에 고정 방법을 명시한다
- **ID**: `SC-UNIT-NNN` / 대응 TC는 `tests/doc/testcases/unit-testcases.md`

---

## 1. paths (Section 1)

### SC-UNIT-001 — Claude 경로가 `CLAUDE_CONFIG_DIR` 를 따른다
- **Objective**: `CLAUDE_CONFIG_DIR` 유무에 따라 `CLAUDE_DIR` / `CLAUDE_CONFIG_FILE` / `PATHS.*` 파생 경로가 일관되게 재계산되는지 검증 (US-SYS03 AC1)
- **Preconditions**: `clean_env` 픽스처로 `CLAUDE_CONFIG_DIR`·`XDG_CONFIG_HOME`·`APPDATA` 제거. `Path.home` 을 `/tmp/fake-home` 으로 monkeypatch. 모듈 상수는 import 시점에 확정되므로 `importlib.reload(axt)` 로 재평가한다
- **Steps**: 1) env 설정 2) `importlib.reload(axt)` 3) `axt.CLAUDE_DIR` / `axt.PATHS.settings` / `axt.PATHS.installed_plugins` / `axt.CLAUDE_CONFIG_FILE` 확인
- **Expected Result**: 미설정 시 `~/.claude` 기준, 설정 시 그 디렉터리 기준으로 모든 하위 경로가 파생된다. 빈 문자열은 **미설정과 동일**하게 취급한다
- **Priority**: High

### SC-UNIT-002 — axt 자체 설정 디렉터리가 플랫폼 규약을 따른다
- **Objective**: `_axt_config_dir()` 이 POSIX 에서 `XDG_CONFIG_HOME/axt`(미설정 시 `~/.config/axt`), Windows 에서 `%APPDATA%/axt` 로 해석되는지 검증 (US-SYS03 AC2, AC3)
- **Preconditions**: `clean_env`. `sys.platform` 을 `"linux"` / `"win32"` 로 monkeypatch 후 `importlib.reload(axt)`. `Path.home` 고정
- **Steps**: 1) 플랫폼·env 조합 설정 2) reload 3) `AXT_CONFIG_DIR` / `AXT_CONFIG_PATH` 확인
- **Expected Result**: 3가지 조합 각각에서 규약 경로가 나오고 `AXT_CONFIG_PATH == AXT_CONFIG_DIR / "config.json"` 이다
- **Priority**: Medium

### SC-UNIT-003 — 프로젝트 설정 경로와 `Paths` 불변성
- **Objective**: `project_settings_path(cwd)` 가 `<cwd>/.claude/settings.json` 을 돌려주고 `PATHS` 가 frozen dataclass 여서 실수로 전역 오염이 나지 않는지 검증 (US-SYS03)
- **Preconditions**: `tmp_path` + `monkeypatch.chdir(tmp_path)`
- **Steps**: 1) 인자 없이 호출 2) 명시 cwd 로 호출 3) `PATHS.claude_dir` 대입 시도
- **Expected Result**: 1)·2) 모두 `<base>/.claude/settings.json`. 3) 은 예외(`FrozenInstanceError`)
- **Priority**: Medium

---

## 2. json_io (Section 2)

### SC-UNIT-004 — 손상·부재 JSON 에서 fallback 으로 살아남는다
- **Objective**: `read_json(path, fallback=...)` 이 파일 부재·파싱 실패 시 fallback 을 돌려주고, fallback 미지정 시에만 예외를 올리는지 검증 (US-SYS05 AC1)
- **Preconditions**: `tmp_path` 안에서만 파일 생성
- **Steps**: 1) 정상 JSON 읽기 2) 없는 경로 + fallback 3) 없는 경로 + fallback 미지정 4) 깨진 JSON 텍스트 + fallback
- **Expected Result**: 1) 파싱값, 2)·4) fallback 그대로, 3) 예외
- **Priority**: Critical

### SC-UNIT-005 — 모든 쓰기가 원자적이고 기존 파일을 백업한다
- **Objective**: `write_json_atomic` 이 tmpfile+`os.replace` 로 쓰고, 기존 파일이 있으면 `.bak` 을 남기고, 임시 파일을 흘리지 않는지 검증 (US-SYS04 AC1~AC3)
- **Preconditions**: `tmp_path` 격리. 부모 디렉터리 없는 경로도 포함
- **Steps**: 1) 부모 없는 경로에 쓰기 2) 같은 경로에 다시 쓰기 3) 디렉터리 엔트리 목록 확인 4) 비ASCII 값 왕복
- **Expected Result**: 1) 부모 자동 생성, 2) 이전 내용이 `.bak` 에 보존, 3) `.tmp*` 잔재 0개, 4) 유니코드 원문 보존 + 끝에 개행 1개
- **Priority**: Critical

---

## 3. settings (Section 3)

### SC-UNIT-006 — 설정 플래그 맵을 방어적으로 읽는다
- **Objective**: `read_enabled_plugins` / `read_favorite_plugins` / `read_marked_for_update` / `read_extra_marketplaces` 가 파일 부재·비객체·비dict 버킷에서 빈 결과를 돌려주고 값을 bool 로 강제하는지 검증 (US-PLG01 AC1, US-SYS05 AC1)
- **Preconditions**: `tmp_settings` / `seeded_settings` 픽스처 (`tmp_path` 하위)
- **Steps**: 1) 파일 없음 2) 깨진 JSON 3) 버킷이 dict 아님 4) 값이 `"yes"`/`1` 같은 비bool
- **Expected Result**: 1)~3) `{}`, 4) 모든 값이 `bool` 로 강제된 맵
- **Priority**: High

### SC-UNIT-007 — 플래그 쓰기가 형제 키를 보존한다
- **Objective**: `set_plugin_enabled` / `set_plugin_favorite` / `set_marked_for_update` / `remove_plugin_from_settings` 가 대상 키만 바꾸고 나머지 설정을 그대로 두는지 검증 (US-PLG02 AC3)
- **Preconditions**: `seeded_settings` (`otherKey: "preserved"` 포함)
- **Steps**: 1) 플래그 on→off 토글 2) `False` 로 즐겨찾기 설정 3) 존재하지 않는 키 제거 4) 버킷이 dict 가 아닌 상태에서 쓰기
- **Expected Result**: 1) 값만 갱신, 2) 키 자체 삭제, 3) no-op 이며 예외 없음, 4) 버킷이 dict 로 교체되고 다른 최상위 키는 유지
- **Priority**: High

---

## 4. vault — frontmatter 파싱 (Section 5)

### SC-UNIT-008 — `parse_yaml_description` 이 YAML 스칼라 5형태를 처리한다
- **Objective**: PyYAML 없이 자체 파서가 plain / double-quoted(멀티라인·이스케이프·줄 연결) / single-quoted(`''` 리터럴) / 블록 스칼라(`|`, `>`, chomping·indent 지시자) / CRLF 를 모두 해석하는지 검증 (US-LNK01 AC1, US-SYS07 AC2)
- **Preconditions**: 순수 문자열 입력 — 파일시스템·시계 의존 없음
- **Steps**: 각 형태의 frontmatter 문자열을 넣고 반환값 확인
- **Expected Result**: 값이 한 줄로 정규화(연속 공백 1개)되어 나오고, 블록 스칼라는 공통 들여쓰기만큼 dedent 된다. `description:` 키가 없거나 값이 비면 `""`
- **Priority**: High

### SC-UNIT-009 — `parse_yaml_version` 이 따옴표를 벗기고 부재 시 빈 문자열을 준다
- **Objective**: 버전 컬럼(`Ver`)의 원천 값이 plain/quoted 스칼라에서 동일하게 나오는지 검증 (US-LNK01, US-TUI03 AC7 의 입력원)
- **Preconditions**: 순수 문자열 입력
- **Steps**: `version: 1.2.3` / `version: "1.2.3"` / `version: '1.2.3'` / 키 부재 / 값 공백
- **Expected Result**: 앞 3개는 `1.2.3`, 뒤 2개는 `""`
- **Priority**: Medium

### SC-UNIT-010 — 항목 타입에 따라 description/version 원본 파일을 고른다
- **Objective**: `_read_description_for_item` / `_read_version_for_item` 이 skill 은 `index.md` → `SKILL.md` 순으로 탐색하고, command/agent 는 파일 자체를 읽는지 검증 (US-LNK01 AC1)
- **Preconditions**: `tmp_path` 에 skill 디렉터리와 `.md` 파일 생성
- **Steps**: 1) `index.md` 만 있는 skill 2) `SKILL.md` 만 있는 skill 3) 둘 다 없는 skill 4) command `.md`
- **Expected Result**: 1)·2) 각 파일의 값, 3) `""`, 4) 파일 자체의 frontmatter 값. frontmatter 블록 자체가 없으면 `""`
- **Priority**: Medium

---

## 5. vault — 프로필·항목 (Section 5)

### SC-UNIT-011 — `AxtProfile` 이 불변 갱신을 보장한다
- **Objective**: `with_added` / `with_removed` 가 원본을 변형하지 않고 새 객체를 돌려주며, 이미 있는/없는 이름에 대해 자기 자신을 돌려주는지 검증 (US-PRJ01 AC1, US-PRJ02 AC1)
- **Preconditions**: 순수 dataclass 연산 — I/O 없음
- **Steps**: 1) 없는 이름 추가 2) 있는 이름 다시 추가 3) 있는 이름 제거 4) 없는 이름 제거 5) `from_json` 에 비dict 전달
- **Expected Result**: 1)·3) 새 객체, 2)·4) 동일 객체(idempotent), 5) 빈 프로필
- **Priority**: Medium

### SC-UNIT-012 — `list_vault_items` 가 3타입을 스캔하고 잡음을 거른다
- **Objective**: `~/.axt/vault/{skills,commands,agents}` 를 훑어 타입별 항목을 만들고, 점파일·비`.md`·매니페스트 없는 디렉터리를 제외하는지 검증 (US-VLT02 AC1)
- **Preconditions**: `tmp_path` 로 만든 가짜 vault 트리. 디렉터리 부재 케이스 포함
- **Steps**: 1) 3타입 각 1개 배치 2) `.hidden` / `readme.txt` / 매니페스트 없는 디렉터리 추가 3) vault 디렉터리 자체 삭제
- **Expected Result**: 1) 3건 반환, 2) 잡음 항목 미포함, 3) 빈 리스트(예외 아님)
- **Priority**: High

### SC-UNIT-013 — 프로젝트 스코프 링크는 symlink 만 만들고 지운다
- **Objective**: `link_to_project` / `unlink_from_project` 가 `<proj>/.claude/<type>s/<name>` symlink 를 생성·제거하고 프로필을 함께 갱신하며, 실체 파일/디렉터리를 절대 지우지 않는지 검증 (US-LNK04 AC1·AC3, US-PRJ02 AC3, US-LNK03 AC1·AC2)
- **Preconditions**: `tmp_path` 하위의 프로젝트 디렉터리와 vault. Windows 는 `sys.platform == "win32"` 로 skip
- **Steps**: 1) 링크 생성 2) 같은 자리에 실제 파일이 있을 때 링크 시도 3) 오래된 symlink 위에 재링크 4) 해제
- **Expected Result**: 1) symlink 생성 + 프로필 등록, 2) 거부(실체 보존), 3) 낡은 링크 교체, 4) symlink 만 제거되고 vault 실체·프로필 항목 정리
- **Priority**: Critical

### SC-UNIT-014 — 전역 스코프 링크 해제가 vault 실체를 남긴다
- **Objective**: `link_to_global` / `unlink_from_global` 이 `~/.claude/<type>s/<name>` symlink 만 다루고, 해제 후에도 vault 원본이 그대로 남는지 검증 (US-VLT05 AC1, AC2)
- **Preconditions**: `tmp_path` 로 만든 가짜 `~/.claude` 와 vault. Windows skip
- **Steps**: 1) 링크 2) 링크 대상 확인 3) 해제 4) vault 경로 존재 확인 5) `plugin` 타입 링크 시도
- **Expected Result**: 1)~3) symlink 생성·제거, 4) vault 실체 잔존, 5) 거부
- **Priority**: Critical

### SC-UNIT-015 — `.agents` 미러가 vault 원본을 직접 가리키고 잠금을 존중한다
- **Objective**: `link_to_agents` 가 `~/.claude/skills/` 가 아니라 **vault 경로**를 가리키는 symlink 를 만들고, `.skill-lock.json` 이 있는 트리는 기본 거부하되 `force=True` 로 우회되는지, skill 이외 타입은 거부하는지 검증 (US-VLT06 AC1~AC3, AC5)
- **Preconditions**: `tmp_path` 하위 `.agents` 디렉터리. Windows skip
- **Steps**: 1) skill 미러 2) 링크 대상 경로 확인 3) `.skill-lock.json` 배치 후 재시도 4) `force=True` 재시도 5) command 타입 시도 6) 같은 이름의 실제 디렉터리와 충돌
- **Expected Result**: 2) vault 경로, 3) `(False, 메시지)`, 4) 성공, 5) 거부, 6) 거부(실체 보존)
- **Priority**: High

### SC-UNIT-016 — `.agents` 미러 해제는 이 vault 항목을 가리킬 때만 동작한다
- **Objective**: `unlink_from_agents` 가 남의 심볼릭 링크를 지우지 않는지 검증 (US-VLT06 AC4)
- **Preconditions**: `tmp_path` 하위 `.agents`. 같은 이름이지만 다른 대상을 가리키는 symlink 를 별도로 준비. Windows skip
- **Steps**: 1) 이 vault 항목을 가리키는 링크 해제 2) 외부 대상을 가리키는 동명 링크 해제 시도
- **Expected Result**: 1) 제거, 2) 보존 + `(False, 메시지)`
- **Priority**: High

### SC-UNIT-017 — `sync_project` 가 선언과 실제를 맞추고 3집계를 낸다
- **Objective**: 프로필에 있는데 없는 링크는 만들고, 프로필에 없는데 있는 링크는 지우고, 결과를 linked / unlinked / errors 로 보고하는지 검증 (US-PRJ03 AC1~AC3)
- **Preconditions**: `tmp_path` 프로젝트 + vault. Windows skip
- **Steps**: 1) 프로필에만 있는 항목 2) 링크만 있는 고아 항목 3) vault 에 없는 이름이 프로필에 있는 경우 4) 외부 대상을 가리키는 남의 symlink
- **Expected Result**: 1) `linked` 에 계상, 2) `unlinked` 에 계상 + 링크 제거, 3) `errors` 에 계상, 4) 손대지 않음
- **Priority**: Critical

### SC-UNIT-018 — `migrate_to_vault` 가 이동/스킵/브로큰/오류를 분리 집계한다
- **Objective**: 실체는 vault 로 **이동**하고 원위치에 symlink 를 남기며, 대상이 사라진 broken symlink 는 **이동하지도 삭제하지도 않고** `broken` 으로만 보고하는지 검증 (US-VLT01 AC1~AC4)
- **Preconditions**: `tmp_path` 로 만든 가짜 `~/.claude/{skills,commands,agents}`. Windows skip
- **Steps**: 1) 일반 실체 디렉터리 2) 이미 vault 를 가리키는 symlink 3) 대상이 삭제된 broken symlink 4) 점파일·타입 불일치 파일
- **Expected Result**: 1) `moved` + 원위치 symlink, 2) `skipped`, 3) `broken` 이며 원본 링크 **잔존**, 4) 무시. 총계는 moved/skipped/broken/errors 로 나뉜다
- **Priority**: Critical

### SC-UNIT-019 — `import_to_vault` 와 `find_broken_links`
- **Objective**: 임의 위치의 확장을 vault 로 옮기고 원위치에 symlink 를 남기되 이름 충돌 시 실패하는지, `find_broken_links` 가 깨진 링크를 **보고만** 하는지 검증 (US-LNK05 AC3, US-SYS05 AC2)
- **Preconditions**: `tmp_path` 프로젝트/글로벌 소스 + vault. Windows skip
- **Steps**: 1) 글로벌 소스 import 2) 프로젝트 소스 import 3) 같은 이름이 이미 vault 에 있을 때 4) `~/.claude` 하위 broken symlink 목록화 5) 디렉터리 자체가 없을 때
- **Expected Result**: 1)·2) 이동 + 원위치 symlink, 3) 실패(덮어쓰기 금지), 4) 이름 목록 반환 + 링크 잔존, 5) 빈 리스트
- **Priority**: High

### SC-UNIT-020 — vault 항목에 project/global 링크 상태를 채운다
- **Objective**: `list_vault_items_with_project_state` 가 항목별 `is_linked` / `is_global_linked` / `is_agents_linked` 를 정확히 채우는지 검증 (US-VLT02 AC3)
- **Preconditions**: `tmp_path` 프로젝트·글로벌 디렉터리에 링크 배치. Windows skip
- **Steps**: 1) 프로젝트에만 링크 2) 전역에만 링크 3) 프로젝트 local 전용 항목 4) 외부 대상을 가리키는 동명 symlink
- **Expected Result**: 1)·2) 해당 플래그만 `True`, 3) 목록에서 제외, 4) 플래그 `False`(남의 링크를 자기 것으로 오인하지 않음)
- **Priority**: High

---

## 6. marketplace (Section 5)

### SC-UNIT-021 — `parse_marketplace_source` 가 4형태를 구분한다
- **Objective**: `github:` / `git:` / `dir:` 접두사와 bare `owner/repo` 를 올바른 `MarketplaceSource` 로 파싱하고, 그 밖은 예외를 던지는지 검증 (US-MKT01 AC1, AC2)
- **Preconditions**: 순수 문자열 입력
- **Steps**: 4형태 + 잘못된 형태 + `to_json`/`from_json` 왕복
- **Expected Result**: `kind` 와 `repo`/`url`/`path` 중 정확히 하나만 채워진다. 잘못된 형태는 `ValueError` 이며 메시지에 지원 형태 3종이 들어간다
- **Priority**: High

### SC-UNIT-022 — 레지스트리 파싱이 손상 엔트리를 건너뛴다
- **Objective**: `list_marketplaces` 가 값이 dict 가 아니거나 `source` 가 dict 가 아닌 엔트리를 조용히 건너뛰고 나머지를 반환하는지 검증 (US-MKT03 AC2, US-SYS05 AC1)
- **Preconditions**: `tmp_path` 에 `known_marketplaces.json` 직접 작성
- **Steps**: 1) 빈 파일 2) 정상 2건 3) 정상 1건 + 문자열 엔트리 1건 4) `source` 가 문자열인 엔트리
- **Expected Result**: 손상 엔트리만 빠지고 나머지는 정상 반환. 예외 없음
- **Priority**: Medium

### SC-UNIT-023 — 로컬 버전이 3가지 경로로 구해진다
- **Objective**: `get_local_version` 이 `dir:` → `"local"`, `.gcs-sha` 파일 → SHA 앞 7자, git repo → short hash 순으로 해석하고, 어느 것도 없으면 `unknown` 을 주는지 검증 (US-MKT03 AC1, AC2)
- **Preconditions**: `tmp_path` 에 각 상태의 설치 디렉터리 준비. `_git` 은 monkeypatch 로 고정(네트워크·실제 git 의존 제거)
- **Steps**: 1) directory 소스 2) `.gcs-sha` 존재 3) `.git` 존재 + rev-parse 성공 4) rev-parse 실패 5) 레지스트리에 없는 이름
- **Expected Result**: 순서대로 `local` / SHA 7자 / short hash / `unknown` / `unknown`. 어떤 경우에도 예외로 목록 출력을 막지 않는다
- **Priority**: Medium

### SC-UNIT-024 — 원격 대비 갱신 가능 여부를 판정한다
- **Objective**: `get_marketplace_version` 이 git/github/기타 소스별로 `current` / `remote` / `updatable` / `error` 를 채우는지 검증 (US-UPD01 AC2)
- **Preconditions**: `_git`, `_fetch_github_head_sha` 를 monkeypatch 로 고정. 네트워크 호출 금지
- **Steps**: 1) git 원격이 앞섬 2) git 최신 3) fetch 실패 4) upstream 없음 5) github 네트워크 오류 6) git 도 github 도 아님
- **Expected Result**: 1) `updatable=True`, 2) `False`, 3)~5) `error` 채워짐 + 크래시 없음, 6) 판정 불가로 표기
- **Priority**: High

### SC-UNIT-025 — `sync_marketplace` 가 소스 종류별로 동작한다
- **Objective**: directory 는 no-op, git 은 fetch 후 동기화, github 은 tarball 재다운로드로 처리하고, 없는 이름은 `KeyError` 를 올리며 `lastUpdated` 를 원자적으로 기록하는지 검증 (US-MKT02 AC1~AC4)
- **Preconditions**: `_git` / `download_and_extract_tarball` monkeypatch. `tmp_path` 레지스트리
- **Steps**: 1) 없는 이름 2) directory 소스 3) git 소스 성공 4) git fetch 실패 5) github tarball 6) 동기화 불가 소스
- **Expected Result**: 1) `KeyError`, 2) `updated=False` + `before==after=="local"`, 3) `before != after` 시 `updated=True`, 4) `RuntimeError` 에 stderr 사유 포함, 5) SHA 앞 7자 비교, 6) `RuntimeError`
- **Priority**: High
- **Note**: git 소스 sync 는 `git fetch` + `git reset --hard @{u}` 다(관리 캐시이므로 로컬 수정 미보존). 낡은 `FEATURES.md` 기술과의 충돌은 `tests/doc/SPEC_DECISIONS.md` SD-001 에서 해소됨

---

## 7. plugin (Section 4)

### SC-UNIT-026 — 설치 레지스트리에서 id·마켓·매니페스트를 해석한다
- **Objective**: `list_installed_plugins` 가 `name@marketplace` id 를 분해하고, 매니페스트를 `.claude-plugin/plugin.json` → `plugin.json` 순으로 찾으며, 손상 레지스트리에서 크래시하지 않는지 검증 (US-PLG01 AC1, US-PLG03 AC2)
- **Preconditions**: `tmp_path` 에 `installed_plugins.json` 과 설치 디렉터리 배치
- **Steps**: 1) 빈 레지스트리 2) `name@market` 형태 3) 마켓 접미사 없음 4) modern 매니페스트가 root 보다 우선 5) 최상위가 dict 아님 / 엔트리 리스트가 빔
- **Expected Result**: 2) name·marketplace 분리, 3) marketplace 빈 값, 4) `.claude-plugin/plugin.json` 값 채택, 5) 빈 리스트
- **Priority**: High

### SC-UNIT-027 — raw SHA 버전을 릴리스 태그로 되돌린다
- **Objective**: `_resolve_release_tag` 가 설치 기록의 raw SHA(전체·단축)를 마켓 저장소의 태그명으로 치환하고, 실패 시 원문을 유지하는지 검증 (US-PLG03 AC1)
- **Preconditions**: `_git` monkeypatch 로 태그 조회 결과 고정
- **Steps**: 1) 전체 SHA 매칭 2) 단축 SHA prefix 매칭 3) 마켓 경로 미지정 4) 매칭 태그 없음
- **Expected Result**: 1)·2) 태그명, 3)·4) raw SHA 그대로
- **Priority**: Medium

### SC-UNIT-028 — 마켓 트리에서 플러그인 소스 디렉터리를 찾는다
- **Objective**: `find_plugin_source_dir` 이 마켓 매니페스트의 `source` 를 우선 해석하고, 없으면 루트/직계 자식 규약으로 폴백하며, 외부 소스는 `None` 을 주는지 검증 (US-VLT04 AC2)
- **Preconditions**: `tmp_path` 에 마켓 디렉터리 구성
- **Steps**: 1) 매니페스트가 상대 경로를 지정 2) 마켓 루트 자체가 플러그인 3) 직계 자식 디렉터리 4) 빈 마켓 5) 외부(원격) 소스
- **Expected Result**: 1)~3) 실제 경로, 4)·5) `None`
- **Priority**: Medium

### SC-UNIT-029 — 설치 레지스트리 갱신이 메타데이터를 보존한다
- **Objective**: `add_installed_plugin` / `update_installed_plugin` / `remove_installed_plugin` 이 `installedAt` 을 보존하고 `lastUpdated`·`version`·`gitCommitSha` 만 갱신하며, 손상 레지스트리를 초기화하는지 검증 (US-PLG04 AC1, US-UPD02)
- **Preconditions**: `tmp_path` 레지스트리 파일. 시각 비교가 필요한 항목은 기록된 문자열의 **변경 여부**만 본다(실제 시계 값 단언 금지)
- **Steps**: 1) 신규 추가 2) 같은 id 갱신 3) 없는 id 갱신 4) 제거 5) 최상위가 dict 아닌 상태에서 추가/제거
- **Expected Result**: 2) `installedAt` 불변 + `lastUpdated` 변경, 3) 엔트리 생성, 4) 키 제거, 5) 레지스트리를 정상 구조로 재설정
- **Priority**: High

---

## 8. mcp (Section 4)

### SC-UNIT-030 — 6개 출처의 MCP 서버를 병합하고 scope 를 붙인다
- **Objective**: `collect_mcp_servers` 가 plugin manifest / user `~/.claude.json` / project entry / `<proj>/.mcp.json` / claude.ai 커넥터 / built-in 을 모두 병합하고 각 서버에 scope 를 부여하는지 검증 (US-MCP01 AC1)
- **Preconditions**: `tmp_path` 에 각 출처 파일 구성. `PATHS` 를 `monkeypatch.setattr("axt.PATHS", ...)` 로 교체, `monkeypatch.chdir` 로 프로젝트 고정
- **Steps**: 1) 전부 비었을 때 2) 출처별 단독 3) plugin + config 동시 4) 설정 파일 손상
- **Expected Result**: 1) 빈 리스트, 2) scope 가 각각 `plugin`/`user`/`project`/`.mcp.json`/`claude.ai`/`built-in`, 3) 중복 없이 병합, 4) 나머지 출처만으로 정상 반환
- **Priority**: Critical

### SC-UNIT-031 — 활성 해석이 opt-out / opt-in 으로 갈린다
- **Objective**: 일반 출처는 `disabledMcpServers`(opt-out), built-in 은 `enabledMcpServers`(opt-in) 로 활성 여부가 결정되는지 검증 (US-MCP01 AC2)
- **Preconditions**: `tmp_path` `~/.claude.json` + `monkeypatch.chdir` 로 프로젝트 키 고정
- **Steps**: 1) 일반 서버 기본 상태 2) `disabledMcpServers` 에 넣기 3) built-in 기본 상태 4) `enabledMcpServers` 에 넣기
- **Expected Result**: 1) `disabled=False`, 2) `True`, 3) `disabled=True`(기본 꺼짐), 4) `False`
- **Priority**: Critical

### SC-UNIT-032 — 토글이 현재 프로젝트에만 기록된다
- **Objective**: `set_mcp_disabled` 가 `~/.claude.json` 의 `projects[<cwd>]` 하위에만 쓰고 다른 프로젝트 항목을 건드리지 않으며, 리스트가 비면 키를 정리하는지 검증 (US-MCP03 AC1, AC2)
- **Preconditions**: `tmp_path` `~/.claude.json` 에 두 개 프로젝트 엔트리 사전 배치. `monkeypatch.chdir` 로 하나를 현재 프로젝트로 고정
- **Steps**: 1) disable 2) 같은 이름 재 disable 3) enable 4) 다른 프로젝트 엔트리 확인 5) 설정 파일 손상 상태에서 토글
- **Expected Result**: 1) 이름 추가, 2) idempotent, 3) 제거 + 빈 키 pruning, 4) 불변, 5) 예외 없이 복구 후 기록
- **Priority**: Critical

---

## 9. skill / commands / agents (Section 4)

### SC-UNIT-033 — 스킬 목록이 4출처를 병합하고 중복을 만들지 않는다
- **Objective**: `list_all_skills` 가 user / project / plugin / `~/.agents` 를 병합하고, symlink 항목의 실제 대상을 기록하며, 프로젝트 디렉터리가 HOME 과 같을 때 중복을 만들지 않고, 비활성 플러그인을 제외하는지 검증 (US-LNK01 AC1~AC3)
- **Preconditions**: `tmp_path` 에 각 위치 구성. Windows skip(symlink)
- **Steps**: 1) `~/.agents/skills` 중첩 레이아웃 2) `.agents` flat 레이아웃 폴백 3) project == HOME 4) 비활성 플러그인 5) symlink 항목
- **Expected Result**: 3) 중복 0건, 4) 미포함, 5) `is_symlink=True` 와 `target` 채워짐
- **Priority**: High

### SC-UNIT-034 — `.md` description 추출이 frontmatter와 첫 줄 폴백을 모두 처리한다
- **Objective**: `_extract_md_description` 이 frontmatter 의 `description`(folded/literal 블록·chomp 지시자 포함)을 우선하고, frontmatter 가 없거나 키가 없으면 첫 줄로 폴백하며 과도한 길이를 자르는지 검증 (US-LNK01, US-LNK06)
- **Preconditions**: 순수 문자열 입력
- **Steps**: 1) 단순 frontmatter 2) `>` 폴디드 3) `|` 리터럴 + chomp 4) frontmatter 없음 5) frontmatter 있으나 키 없음 6) 매우 긴 첫 줄 7) 빈 문서
- **Expected Result**: 1)~3) frontmatter 값, 4)·5) 첫 줄, 6) 잘림, 7) `""`
- **Priority**: Medium

### SC-UNIT-035 — 스킬 링크 함수가 플랫폼과 실체를 가드한다
- **Objective**: `is_symlink_supported()` 가 플랫폼과 일치하고, Windows 에서 `link_skill`/`unlink_skill` 이 크래시 대신 거부하며, symlink 가 아닌 실제 디렉터리 삭제를 거부하는지 검증 (US-LNK02 AC2, US-LNK03 AC2, US-VLT05 AC4)
- **Preconditions**: `tmp_path` skills 디렉터리. Windows 분기는 `sys.platform` monkeypatch 로 강제
- **Steps**: 1) `is_symlink_supported()` 2) 링크 생성 + `-n` 커스텀 이름 3) 해제 4) 실제 디렉터리 해제 시도 5) Windows 강제 후 링크/해제
- **Expected Result**: 1) `sys.platform != "win32"` 와 동치, 2)·3) 정상, 4) 거부(디렉터리 잔존), 5) 예외가 아닌 안내성 실패
- **Priority**: High

---

## 10. hooks (Section 4)

### SC-UNIT-036 — 훅 목록이 4출처와 `disabledHooks` 미러를 병합한다
- **Objective**: `list_hooks` 가 user/project/local/plugin 을 병합하고, 같은 파일의 `disabledHooks` 를 파싱해 `disabled=True` 로 표시하며, matcher/type 기본값을 채우고 알 수 없는 이벤트·손상 엔트리를 건너뛰는지 검증 (US-HK01 AC1, US-PLG06 AC2)
- **Preconditions**: `tmp_path` 에 settings 3종 + plugin `hooks/hooks.json` 배치
- **Steps**: 1) 3스코프 병합 2) user 파일 부재 3) plugin 훅 포함 4) `disabledHooks` 미러 5) matcher 생략 / type 생략 6) 알 수 없는 이벤트 7) 손상 엔트리 8) http·mcp 타입
- **Expected Result**: 4) `disabled=True`, 5) matcher `*` / type `command`, 6)·7) 건너뜀, 3) plugin 출처가 표시되고 읽기 전용으로 취급된다
- **Priority**: High

### SC-UNIT-037 — 훅 비활성화가 같은 파일 안에서 무손실로 일어난다
- **Objective**: `set_hook_disabled` 가 `hooks` ↔ `disabledHooks` 사이를 같은 설정 파일 안에서 이동시키고, 같은 matcher rule 의 다른 훅을 건드리지 않으며, 정의 내용을 손실 없이 보존하는지 검증 (US-HK02 AC1~AC3)
- **Preconditions**: `tmp_path` settings 파일. 한 rule 안에 훅 2개를 배치
- **Steps**: 1) disable → enable 왕복 2) 같은 rule 의 다른 훅 확인 3) 없는 훅 지정 4) 기존 `disabledHooks` matcher rule 에 병합
- **Expected Result**: 1) 원문 dict 가 그대로 왕복, 2) 형제 훅 불변, 3) `False` 반환, 4) 새 rule 을 만들지 않고 기존 rule 에 합쳐짐
- **Priority**: Critical

### SC-UNIT-038 — `preview_hook` 이 dry-run 결과를 구조화해 돌려준다
- **Objective**: command 훅은 `sh -c` 로 실행해 stdout/stderr/exit code 를 모두 담고, http/mcp 는 실행 없이 요약을 만들며, 타임아웃·실행 불가에서 예외를 밖으로 내보내지 않는지 검증 (US-HK04 AC1, AC2)
- **Preconditions**: 실행 명령은 `echo` 같은 무해한 것만 사용. 타임아웃/`OSError` 는 `subprocess.run` monkeypatch 로 주입
- **Steps**: 1) 정상 command 2) command 미지정 3) 비0 종료 + stderr 4) 타임아웃 5) `OSError` 6) http 7) mcp 8) PreToolUse 페이로드에 tool_name 포함 9) `*` matcher 기본값
- **Expected Result**: 모든 분기가 `HookPreviewResult` 로 반환되고 예외가 전파되지 않는다. 3) exit code 와 stderr 가 결과에 남는다
- **Priority**: High

---

## 11. project usage index (Section 9)

### SC-UNIT-039 — 인코딩된 프로젝트 폴더명을 역해석한다
- **Objective**: `/` 와 `.` 이 모두 `-` 로 바뀐 손실 인코딩을 파일시스템 브루트포스 매칭(최장 일치 우선)으로 되돌리는지 검증 (US-VLT07 AC3, FEATURES §7.8)
- **Preconditions**: `tmp_path` 를 `fs_root` 로 넘겨 실제 홈 디렉터리를 건드리지 않는다. `tlog.net` 같은 점 포함 디렉터리를 실제로 만든다
- **Steps**: 1) 점 포함 경로 디코드 2) `-` 로 시작하지 않는 입력 3) 읽을 수 없는 루트 4) 매칭 없음 5) 매칭 대상이 디렉터리가 아님
- **Expected Result**: 1) 실제 경로 문자열, 2)~5) `None`
- **Priority**: High

### SC-UNIT-040 — `scan_project_usage` 가 모드별로 다른 소스를 훑는다
- **Objective**: `default` 는 프로필 + symlink, `full` 은 플러그인 설정까지 인덱싱하고, 스캔 대상이 없어도 0건으로 끝나는지 검증 (US-VLT07 AC1, AC2, AC4)
- **Preconditions**: `tmp_path` 에 가짜 `projects/` 트리. Windows skip(symlink)
- **Steps**: 1) 프로필만 있는 프로젝트 2) symlink 만 있는 프로젝트 3) `full` 모드 + `enabledPlugins` 4) `projects` 디렉터리 부재 5) 알 수 없는 타입
- **Expected Result**: 1)·2) `default` 로 잡힘, 3) `full` 에서만 플러그인 계상, 4) 빈 인덱스, 5) 집계에서 안전하게 무시
- **Priority**: High

### SC-UNIT-041 — 사용 인덱스 조회 헬퍼가 미등록 키에 안전하다
- **Objective**: `get_project_count` / `get_projects` / `scan_counts_by_type` / `format_scan_summary` 가 없는 키에 대해 0·빈 리스트를 주고 요약 문자열을 만드는지 검증 (US-VLT07 AC4)
- **Preconditions**: 인메모리 인덱스 dict — I/O 없음
- **Steps**: 1) 없는 키 조회 2) 타입별 집계 3) 요약 문자열 생성
- **Expected Result**: 1) `0` / `[]`, 2) 타입별 건수, 3) 스타일별 요약 문자열
- **Priority**: Low

---

## 12. usage 파싱·캐시 (Section 6)

### SC-UNIT-042 — JSONL 파서가 4종 토큰 필드를 뽑고 잡음을 건너뛴다
- **Objective**: `parse_claude_jsonl` 이 assistant 레코드의 `usage.{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}` 를 뽑고, 빈 줄·깨진 JSON·비dict message 를 건너뛰며, 파일 부재에서 빈 리스트를 주는지 검증 (US-USG01, US-SYS05)
- **Preconditions**: `tmp_path` 에 JSONL 파일 직접 작성
- **Steps**: 1) 정상 레코드 2) 깨진 줄 섞기 3) 빈 줄·비dict message 4) 파일 없음
- **Expected Result**: 유효 레코드만 파싱되고 나머지는 조용히 스킵. 4개 토큰 필드가 각각 정확히 매핑된다
- **Priority**: Critical

### SC-UNIT-043 — 캐시 스키마 v2 의 intern 테이블이 왕복한다
- **Objective**: `_encode_claude_file` / `_decode_claude_file` 이 model·sessionId 를 top-level intern 테이블 인덱스로 저장하고, projectPath 는 저장하지 않고 파일 키에서 복원하며, v1 캐시는 폐기 후 재빌드되는지 검증 (US-USG08 AC2, AC3)
- **Preconditions**: `tmp_path` 캐시 파일. `_cache_path` monkeypatch 로 실제 `~/.config/axt/cache` 접근 차단
- **Steps**: 1) 인코딩 → 디코딩 왕복 2) 같은 model 을 여러 엔트리에서 사용 3) 손상된 위치 배열(길이 불일치) 4) `version: 1` 캐시 로드
- **Expected Result**: 1) 모든 필드 동일 복원 + projectPath 는 부모 디렉터리명, 2) intern 테이블에 1회만 등록, 3) 해당 행만 스킵, 4) v1 은 사용되지 않고 재파싱된다
- **Priority**: Critical

### SC-UNIT-044 — mtime 기반 캐시가 변경 없는 파일을 재파싱하지 않는다
- **Objective**: `load_all_claude_usage` 가 파일 mtime 이 같으면 캐시 행을 그대로 쓰고, `is_cache_valid` 가 TTL 을 판정하는지 검증 (US-USG08 AC1)
- **Preconditions**: `tmp_path` projects 디렉터리 + `_cache_path` monkeypatch. **mtime 과 `datetime.now()` 를 혼용하지 않는다** — TTL 판정은 `lastUpdated` 문자열을 직접 주입해 검증한다
- **Steps**: 1) 최초 로드 2) 파싱 함수 호출 횟수를 세며 재로드 3) `lastUpdated` 없음/파싱 불가 4) 신선한 `lastUpdated` 5) `force_refresh=True`
- **Expected Result**: 2) 재파싱 0회, 3) `is_cache_valid` 가 `False`, 4) `True`, 5) 캐시를 무시하고 재파싱
- **Priority**: High

### SC-UNIT-045 — 일별·세션별 집계가 결정적이다
- **Objective**: `aggregate_daily` / `aggregate_by_session` 이 타임존 기준으로 날짜를 묶고, 세션별 메시지 수·모델 집합·최초/최종 시각을 채우는지 검증 (US-USG01 AC2, US-USG05 AC1)
- **Preconditions**: 엔트리의 `timestamp` 를 명시 ISO 문자열로 고정 — `datetime.now()` 미사용. 타임존은 `"UTC"` 로 명시
- **Steps**: 1) 같은 날의 여러 엔트리 2) 타임존 경계를 넘는 엔트리 3) 여러 세션 4) 잘못된 타임존 이름
- **Expected Result**: 1) 1개 `DailyUsage`, 2) 지정 타임존의 날짜로 분리, 3) 세션별 분리 + 모델 집합 채움, 4) UTC 폴백(예외 아님)
- **Priority**: High

### SC-UNIT-046 — 5시간 블록이 첫 엔트리 시각을 시간 단위로 내림해 열린다
- **Objective**: 블록 시작이 **벽시계 00/05/10 정렬이 아니라** 첫 엔트리 시각의 floor-to-hour(UTC) 인지, 블록 종료(시작+5h) 이후 첫 엔트리가 자기 시각 기준으로 새 블록을 여는지, `isActive` 와 burn rate 규칙이 맞는지 검증 (US-USG04 AC1~AC5)
- **Preconditions**: 엔트리 timestamp 를 명시 ISO 로 고정. `isActive`/burn rate 검증 TC 는 `datetime.now` 를 monkeypatch 로 고정한다(과거 날짜 의존 플레이크 이력)
- **Steps**: 1) 첫 엔트리 `10:37Z` 2) 5h 를 넘긴 두 번째 엔트리 3) 옛 UTC 경계를 가로지르지만 5h 안인 활동 4) 빈 입력 5) 파싱 불가 timestamp 6) 활성/비활성 블록의 burn rate
- **Expected Result**: 1) `blockStart == 10:00Z`, 2) 새 블록이 자기 시각의 정시에 앵커, 3) 한 블록 유지, 4) `[]`, 5) 해당 엔트리만 제외, 6) 활성 블록만 burn rate 를 갖고 비활성은 `None`
- **Priority**: Critical

### SC-UNIT-047 — 기간 필터와 타임존 헬퍼가 폴백을 갖는다
- **Objective**: `filter_by_timestamp_ms` / `filter_by_date_string` / `_date_in_tz` / `_today_in_tz` / `_days_ago_in_tz` 가 경계 포함 규칙과 잘못된 타임존 폴백을 지키는지 검증 (US-USG01 AC2, US-USG02 AC3)
- **Preconditions**: 명시 ISO 문자열 입력. `_today_in_tz` / `_days_ago_in_tz` 검증은 두 함수를 같은 타임존으로 호출해 **상대 관계**만 단언한다(절대 날짜 단언 금지)
- **Steps**: 1) 경계값 포함 여부 2) 상·하한 모두 미지정 3) 파싱 불가 timestamp 4) 잘못된 타임존 이름 5) 잘못된 형식의 timestamp
- **Expected Result**: 1) 경계 포함, 2) 전량 반환, 3) 해당 항목 제외, 4)·5) UTC 슬라이스 폴백(예외 아님)
- **Priority**: High

---

## 13. pricing / plan / config (Section 7)

### SC-UNIT-048 — 모델 단가 조회가 정확/접두 매칭 순으로 동작한다
- **Objective**: `get_model_pricing` 이 정확 일치를 우선하고, 없으면 **가장 긴 키 우선** 접두 매칭을 하며, 미등록 모델에 `None` 을 주는지, `get_context_window_size` 가 이를 따라가는지 검증 (US-USG06 AC2)
- **Preconditions**: `axt/pricing.json` 이 원천. `reload_pricing_table()` 로 캐시 초기화 후 실행
- **Steps**: 1) `claude-opus-4-7` 정확 일치 2) `claude-opus-4-7-r1` 접두 매칭 3) `claude-fable-5` / `claude-sonnet-5` / `claude-haiku-4-5` 4) 미등록 모델 5) 컨텍스트 윈도우 조회
- **Expected Result**: 1) input 5.00 / output 25.00 / cacheWrite 6.25 / cacheRead 0.50, 2) 같은 값, 3) 표대로, 4) `None`, 5) opus·sonnet·fable 은 1,000,000 / haiku 는 200,000 / 미등록은 `None`
- **Priority**: Critical

### SC-UNIT-049 — 비용이 4종 토큰의 합으로 계산된다
- **Objective**: `calculate_cost` = `(input/1M)*Pin + (output/1M)*Pout + (cacheCreation/1M)*Pcw + (cacheRead/1M)*Pcr` 이며, 각 토큰 종류가 독립적으로 기여하고, 미등록 모델은 0 인지 검증 (US-USG06 AC1, AC2)
- **Preconditions**: `reload_pricing_table()`. 부동소수 비교는 `pytest.approx`
- **Steps**: 1) output 만 5,000,000 토큰 2) 4종을 각각 1,000,000 씩 3) 전부 0 4) 미등록 모델
- **Expected Result**: 1) `claude-opus-4-7` → $125.00, 2) 5.00+25.00+6.25+0.50 = $36.75, 3) $0.00, 4) $0.00
- **Priority**: Critical

### SC-UNIT-050 — 캐시 절감액은 cache read 만 계산한다
- **Objective**: `calculate_cache_savings` 가 `(cacheRead/1M) × (input단가 − cacheRead단가)` 이고 cache write 토큰을 무시하며, 미등록 모델에 0 을 주는지 검증 (US-USG06 AC1)
- **Preconditions**: `reload_pricing_table()`
- **Steps**: 1) `claude-opus-4-7` cacheRead 2,000,000 2) cacheWrite 만 있고 cacheRead 0 3) 미등록 모델
- **Expected Result**: 1) 2 × (5.00 − 0.50) = $9.00, 2) $0.00, 3) $0.00
- **Priority**: High

### SC-UNIT-051 — 미등록 모델이 조용히 묻히지 않는다
- **Objective**: `find_unpriced_models` 가 `pricing.json` 에 없는 모델을 모델별 엔트리 수로 돌려주고, `unknown`/`<synthetic>` 같은 비실모델 표식은 세지 않는지 검증 (US-USG06 AC3, AC4)
- **Preconditions**: `reload_pricing_table()`. 인메모리 엔트리 객체 사용
- **Steps**: 1) 미등록 모델 3건 + 등록 모델 2건 2) 전부 등록 모델 3) `unknown` / `<synthetic>` 섞기
- **Expected Result**: 1) `{미등록모델: 3}`, 2) `{}`, 3) 비실모델 미포함
- **Priority**: High

### SC-UNIT-052 — 통화 변환이 양방향 + 패스스루를 갖는다
- **Objective**: `convert_currency` 가 USD↔KRW 를 환율로 변환하고, 같은 통화·미지원 조합은 원값을 돌려주며, 환율 0 에서 0나눗셈을 내지 않는지 검증 (US-USG01)
- **Preconditions**: 순수 산술 — I/O 없음
- **Steps**: 1) usd→krw 2) krw→usd 3) 동일 통화 4) 미지원 조합 5) 환율 0
- **Expected Result**: 1) `amount × rate`, 2) `amount / rate`, 3)·4) 원값, 5) 예외 없이 원값
- **Priority**: Medium

### SC-UNIT-053 — 청구 주기의 경과일·주기길이를 정확히 센다
- **Objective**: `get_days_in_billing_period(billing_start, now)` 가 `now` 를 포함하는 주기의 시작일을 잡고, 주기 길이(월 길이)와 경과일을 UTC 로 계산하며, 연말·연초를 넘어가도 맞는지 검증 (US-USG07 AC3)
- **Preconditions**: **`now` 를 반드시 명시 `datetime`(tz-aware UTC)으로 주입한다.** 과거 이 저장소에서 월중 날짜에만 통과하던 플레이크 사고가 있었다
- **Steps**: 1) `billing_start=15`, `now=2026-03-20` 2) `now` 가 시작일 이전이라 전월로 롤백 3) 1월에서 12월로 롤백 4) 12월 주기가 해를 넘김 5) `billing_start=31` (28로 클램프) 6) 주기 첫날(경과 0일)
- **Expected Result**: 1) `(5, 31)`, 2) 전월 시작 기준으로 계산, 3)·4) 연도 경계에서도 정확, 5) day 28 로 클램프, 6) `elapsed == 0`
- **Priority**: Critical

### SC-UNIT-054 — 경과일 0 에서 0나눗셈이 나지 않는다
- **Objective**: `project_monthly_cost` / `compute_plan_usage` 가 `days_elapsed <= 0` 일 때 0 을 돌려주고, 정상 구간에서 `사용액 ÷ 경과일수 × 주기일수` 로 예측하는지 검증 (US-USG07 AC3, AC5)
- **Preconditions**: 순수 산술. `days_elapsed`·`total_days` 를 직접 주입(시계 미사용)
- **Steps**: 1) cost=60, elapsed=6, total=30 2) elapsed=0 3) elapsed 음수 4) `compute_plan_usage` 의 `days_remaining`
- **Expected Result**: 1) 예측 300.0, 일평균 10.0, 2)·3) 0.0 (`ZeroDivisionError` 금지), 4) `max(0, total - elapsed)`
- **Priority**: Critical

### SC-UNIT-055 — 플랜 자동 감지와 수동 고정이 공존한다
- **Objective**: `parse_rate_limit_tier` 가 `default_claude_max_20x` 류 문자열을 (라벨, 월정액) 으로 정규화하고, `detect_claude_plan` 이 `userRateLimitTier` 를 조직 tier 보다 우선하며, `resolve_claude_plan` 이 수동 고정(`auto_detect_plan=False`)을 존중하는지 검증 (US-USG07 AC1, AC2)
- **Preconditions**: `tmp_path` 에 가짜 `~/.claude.json` 작성 후 경로를 인자로 주입
- **Steps**: 1) `max_20x` / `max_5x` / `pro` / 인식 불가 2) user tier 우선 3) org tier 폴백 4) `oauthAccount` 부재 / 파일 부재 5) 감지값 오버레이 6) 수동 고정 7) 감지 실패 폴백
- **Expected Result**: 1) `("max-20x", 200.0)` / `("max-5x", 100.0)` / `("pro", 20.0)` / `None`, 2)~4) 규칙대로, 6) 감지값이 저장된 플랜을 덮지 않음
- **Priority**: High

### SC-UNIT-056 — 설정 로드/저장이 왕복하고 손상에 견딘다
- **Objective**: `load_config` / `save_config` 가 기본값·부분 오버라이드·비dict payload 를 처리하고 왕복하는지 검증 (US-SYS05 AC1, US-TUI09 AC1)
- **Preconditions**: `tmp_path` config 경로를 인자로 주입 — 실제 `~/.config/axt` 접근 금지
- **Steps**: 1) 파일 없음 2) 일부 키만 있는 파일 3) 최상위가 dict 아님 4) `plans` 섹션이 dict 아님 5) theme 저장 후 재로드
- **Expected Result**: 1)~4) 기본값으로 안전 폴백, 5) 값 왕복
- **Priority**: Medium

### SC-UNIT-057 — 테마 해석 우선순위가 명확하다
- **Objective**: `resolve_theme` 이 CLI 인자 > 저장 config > 자동 감지 순으로 결정하고, `_detect_terminal_is_light` 가 `COLORFGBG` 를 해석하는지 검증 (US-TUI09 AC1, AC2)
- **Preconditions**: 환경변수는 `monkeypatch.setenv`/`delenv` 로 명시 주입 — 호스트 터미널 상태 비의존
- **Steps**: 1) CLI `light` + config `dark` 2) CLI 미지정 + config `dark` 3) 둘 다 `auto` + `COLORFGBG` 밝은 배경 4) `COLORFGBG` 없음
- **Expected Result**: 1) `light`, 2) `dark`, 3) `light`, 4) 기본값(`dark`)으로 폴백
- **Priority**: Medium

### SC-UNIT-058 — rate limit 스냅샷의 신선도와 클램프
- **Objective**: `read_rate_limits` 가 기본 5분 tolerance 를 넘긴 스냅샷을 `None` 으로 처리하고, 백분율을 0~100 으로 클램프하며, 손상·부재 파일과 unix 초/밀리초 타임스탬프를 모두 견디는지 검증 (US-CTX06 AC2)
- **Preconditions**: `tmp_path` 스냅샷 파일. **`updated_at` 을 현재 시각 기준 상대값으로 직접 작성**해 tolerance 를 명시적으로 통제한다
- **Steps**: 1) 신선한 스냅샷 2) 오래된 스냅샷 3) 백분율 120/-5 4) 파일 없음 / 깨진 JSON / 비dict 5) `updated_at` 부재 6) 백분율 필드 전무 7) `resets_at` 형식 불량 8) unix 초 / 밀리초
- **Expected Result**: 1) 값 반환, 2)·4)·5)·6) `None`, 3) 100/0 으로 클램프, 7) 나머지 필드는 유효, 8) 둘 다 해석
- **Priority**: Medium

---

## 14. context 분석 (Section 8)

### SC-UNIT-059 — 토큰 추정이 CJK 와 비CJK 를 다르게 센다
- **Objective**: `estimate_tokens` 가 CJK 문자 1/1.5, 그 외 1/3.5 로 계산하고 총합을 올림하는지, 빈 문자열이 0 인지 검증 (US-CTX01)
- **Preconditions**: 순수 문자열 — I/O 없음
- **Steps**: 1) 빈 문자열 2) ASCII 만 3) 한글만 4) 히라가나 / 한자 5) 혼합
- **Expected Result**: 1) 0, 2)~5) `ceil(cjk/1.5 + other/3.5)` 와 일치
- **Priority**: High

### SC-UNIT-060 — 12개 카테고리를 모두 수집한다
- **Objective**: `collect_context_sources` 가 system-prompt / claude-md / settings / memory / skills / mcp-tools / plugins / hooks / commands / agents / git-status / user-context 를 모두 만들어내는지, 각 소스에 category·scope·path 가 붙는지 검증 (US-CTX01 AC1)
- **Preconditions**: `tmp_path` 를 home·project 로 주입. `get_claude_version` / `get_git_status` 는 monkeypatch 로 고정(외부 명령 호출 금지)
- **Steps**: 1) 최소 환경(고정 소스만) 2) 파일 전 종류 배치 3) plugin 이 skill/mcp/command/agent/hook 를 모두 제공 4) 비활성 플러그인
- **Expected Result**: 1) system-prompt 4,200 tok + user-context 280 tok 고정 소스가 항상 존재, 2)·3) 모든 카테고리 등장, 4) 비활성 플러그인 소스 미포함
- **Priority**: Critical

### SC-UNIT-061 — Claude Code 가 읽지 않는 경로를 세지 않는다
- **Objective**: skills 는 `.claude/skills` 만, agents 는 `.claude/agents` 만 세고 `~/.agents/{skills,agents}` 를 **제외**하며, symlink 로 두 번 보이는 스킬을 한 번만 세는지 검증 (US-CTX03 AC1, AC2)
- **Preconditions**: `tmp_path` 에 `.agents/skills` 실체 + `.claude/skills` symlink 구성. Windows skip
- **Steps**: 1) `.agents/skills` 에만 있는 스킬 2) `.agents` 실체 + `.claude` symlink 3) `.agents/agents` 에만 있는 에이전트
- **Expected Result**: 1)·3) 컨텍스트 소스에 미포함, 2) 정확히 1건
- **Priority**: High

### SC-UNIT-062 — settings 4곳과 disabled MCP 제외
- **Objective**: global `~/.claude/settings*.json` 2개 + project `<proj>/.claude/settings*.json` 2개를 보고, disabled MCP 서버를 mcp-tools 집계에서 제외하는지 검증 (US-CTX03 AC3, AC4)
- **Preconditions**: `tmp_path` home/project 주입. `_encode_project_dir_name` 결과와 무관하게 project settings 는 **프로젝트 트리**에서 읽는다
- **Steps**: 1) 4개 파일 모두 배치 2) 일부만 배치 3) disabled MCP 1개 포함 4) 읽을 수 없는 memory `.md`
- **Expected Result**: 1) settings 소스 4건, 2) 존재하는 것만, 3) 해당 서버 제외, 4) 해당 파일만 제외되고 나머지는 수집
- **Priority**: High

### SC-UNIT-063 — actionable 플래그가 고정비를 구분한다
- **Objective**: system-prompt(4,200 tok)·user-context(280 tok)가 `actionable=False`, skills·commands·agents 등 사용자가 조정 가능한 소스가 `actionable=True` 인지 검증 (US-CTX02 AC1, AC2)
- **Preconditions**: `tmp_path` home/project. 외부 명령 monkeypatch
- **Steps**: 1) 고정 소스 2종 확인 2) skills / commands / agents / claude-md / memory 확인 3) mcp-tools / plugins 확인
- **Expected Result**: 1) `actionable=False`, 2) `actionable=True`, 3) US-CTX02 AC2 기준 `True` — 현재 구현과 어긋난다(`## 스펙 갭` §G-4)
- **Priority**: Medium

### SC-UNIT-064 — 90일 이상 미수정 memory 에 힌트가 붙는다
- **Objective**: `add_context_hints` 가 memory 파일의 mtime 을 보고 90일 초과 시 `not modified in N days (>90 days)` 힌트를 붙이고, 그 외 카테고리는 각자의 규칙을 따르는지 검증 (US-CTX04 AC1)
- **Preconditions**: memory 파일의 mtime 을 `os.utime` 으로 **명시 고정**한다(현재 시각 기준 상대 오프셋). mtime 과 `datetime.now()` 를 섞지 않도록, 힌트 유무만 단언하고 정확한 N 값은 범위로 본다
- **Steps**: 1) mtime 을 200일 전으로 2) mtime 을 1일 전으로 3) 읽을 수 없는 경로의 memory 4) 상위 3위 skill 5) hooks / git-status / mcp-tools / 500 tok 이하 claude-md
- **Expected Result**: 1) `>90 days` 힌트, 2) 토큰 수 힌트만, 3) 예외 없이 토큰 힌트만, 4) `top context consumer`, 5) 각 카테고리 고정 문구 / 힌트 없음
- **Priority**: High

### SC-UNIT-065 — memory 삭제가 `MEMORY.md` 인덱스도 정리한다
- **Objective**: `delete_memory_file` 이 파일을 지우고 `MEMORY.md` 에서 그 파일을 링크하는 줄을 제거하며, `memory/` 밖 경로를 거부하는지 검증 (US-CTX04 AC3)
- **Preconditions**: `tmp_path` 에 `memory/` 디렉터리 + `MEMORY.md`
- **Steps**: 1) 인덱스 줄이 있는 파일 삭제 2) 인덱스 파일 자체가 없을 때 3) `MEMORY.md` 자체 삭제 4) `memory/` 밖 경로
- **Expected Result**: 1) 파일 삭제 + 해당 줄만 제거(다른 줄 보존), 2) no-op, 3) 인덱스 정리 스킵, 4) `ValueError`
- **Priority**: High

### SC-UNIT-066 — `analyze_context` 가 총합·윈도우·비용을 묶는다
- **Objective**: 총 토큰 합계, `get_context_window_size` 기반 윈도우, `used_percent`, cost impact(cache write 1회 + `(turns-1)` × cache read, 월 = 세션당 × 세션/일 × 30) 가 맞는지 검증 (US-CTX01, US-CTX06 AC3)
- **Preconditions**: `tmp_path` home/project. 외부 명령 monkeypatch. 모델을 명시 인자로 고정
- **Steps**: 1) 기본 모델로 분석 2) 컨텍스트 윈도우가 다른 모델(`claude-haiku-4-5`) 3) 미등록 모델
- **Expected Result**: 1) `total == sum(sources)`, `used_percent == total/window*100`, 2) window 200,000 반영, 3) window 1,000,000 폴백 + 비용 0
- **Priority**: High

---

## 15. update 티어링 (update.py)

### SC-UNIT-067 — 업데이트 티어가 자동/리포트/위임으로 갈린다
- **Objective**: `check_all_updates` 가 Tier 1(플러그인·마켓·git-backed 스킬/명령/에이전트), Tier 2(MCP·non-git), Tier 3(Claude Code 바이너리)로 분류하고, 한 updater 의 예외가 나머지를 죽이지 않는지 검증 (US-UPD01 AC2, US-UPD05 AC4)
- **Preconditions**: 각 updater 를 monkeypatch 로 대체 — 실제 git·네트워크·`claude` 바이너리 호출 금지
- **Steps**: 1) 전체 스윕 2) 한 updater 가 예외를 던짐 3) `types=["plugin"]` 로 좁히기 4) MCP updater 5) claude-code updater
- **Expected Result**: 1) 티어별로 분류됨, 2) 나머지 결과는 정상 반환, 3) 해당 타입만, 4) `tier=2` + `updatable=False`(리포트 전용), 5) `tier=3`
- **Priority**: High

### SC-UNIT-068 — git-backed 여부가 자동 적용 대상을 가른다
- **Objective**: `_resolve_real_dir` / `_find_git_root` / `_git_dir_status` / `_git_dir_apply` 가 symlink 를 따라 실제 디렉터리를 찾고, git repo 만 Tier 1 로 올리며, 주변 저장소(예: 설정 리포)를 잘못 잡지 않는지 검증 (US-UPD02 AC1)
- **Preconditions**: `tmp_path` 에 `.git` 디렉터리를 만든 가짜 repo. `_git` monkeypatch
- **Steps**: 1) git repo 스킬 2) non-git 스킬 3) symlink 를 따라간 실제 디렉터리 4) 상위 ambient 저장소만 있는 경우 5) fetch 실패
- **Expected Result**: 1) Tier 1 + updatable 판정, 2) Tier 2 manual, 3) 링크 대상 기준 판정, 4) 업데이트 대상 아님, 5) `error` 채워지고 크래시 없음
- **Priority**: High

### SC-UNIT-069 — 업데이트 상태 캐시가 왕복하고 손상에 견딘다
- **Objective**: `save_cached_update_statuses` / `load_cached_update_statuses` 가 `<AXT_CONFIG_DIR>/cache/update-status.json` 에 원자적으로 쓰고 `checked_at` 과 함께 복원하며, 파일 부재·손상 시 빈 결과를 주는지 검증 (US-UPD05 AC2)
- **Preconditions**: `_update_status_cache_path` monkeypatch 로 `tmp_path` 로 유도 — 실제 사용자 캐시 오염 금지
- **Steps**: 1) 저장 후 로드 2) 파일 없음 3) 깨진 JSON
- **Expected Result**: 1) 상태 목록 + `checked_at` 복원, 2)·3) `([], None)`
- **Priority**: Medium

---

## 16. TUI 순수 헬퍼 (Sections 11-13)

### SC-UNIT-070 — CJK 폭 계산과 셀 맞춤
- **Objective**: `cell_width` 가 East-Asian Wide/Fullwidth 를 2셀로 세고 ambiguous 를 1셀로 세는지, `fit_cells` 가 폭을 넘지 않게 자르고 남는 자리를 공백으로 채우는지 검증 (US-TUI10 AC3)
- **Preconditions**: 순수 문자열 — curses 미사용
- **Steps**: 1) ASCII 만 2) 한글/한자 3) 혼합 4) `width <= 0` 5) wide 문자가 경계에 걸림 6) 짧은 문자열 패딩
- **Expected Result**: 1) 길이와 동일, 2) 문자수 × 2, 4) `""`, 5) 잘려서 폭 초과 없음, 6) 정확히 `width` 셀
- **Priority**: High

### SC-UNIT-071 — 버전 정렬이 숫자 인식이다
- **Objective**: `_ver_key` 가 `1.10.0 > 1.9.0` 으로 정렬되게 하고, `v` 접두사를 무시하며, 값 없음/`—` 을 오름차순 마지막으로 보내는지 검증 (US-TUI03 AC7)
- **Preconditions**: 순수 함수 — 상태 없음
- **Steps**: 1) `1.9.0` vs `1.10.0` 2) `v1.2.3` vs `1.2.3` 3) `""` / `None` / `"—"` 4) 비숫자 세그먼트(`1.0-beta`)
- **Expected Result**: 1) `1.10.0` 이 뒤, 2) 동일 키, 3) 오름차순 마지막, 4) 예외 없이 텍스트 폴백으로 비교 가능
- **Priority**: High

### SC-UNIT-072 — 정렬 스펙 표가 실제 렌더 컬럼을 가리킨다
- **Objective**: `_SORT_COLUMNS` 의 각 항목이 (a) 8개 서브탭을 모두 덮고, (b) `marked_col` 이 `None` 이거나 자기 key 와 같으며 실제 렌더 컬럼 키에 존재하고, (c) 서브탭 안에서 key 중복이 없고, (d) `#`(행 번호)를 포함하지 않는지 검증 — 표가 다른 표를 참조하는 정합성 검사로 `TEST_DEDUP_POLICY.md` §3 예외에 해당한다 (US-TUI03 AC1, AC5)
- **Preconditions**: 정적 표 대조 — curses 렌더 불필요
- **Steps**: 1) 키 집합 대조 2) `marked_col` 검증 3) 중복 key 4) `no` 키 부재 5) `sort_cycle_help` 문자열이 표에서 생성되는지
- **Expected Result**: 모든 서브탭이 스펙을 만족하고, 힌트 문자열이 표에서 파생된다
- **Priority**: High

### SC-UNIT-073 — 글리프 컬럼은 화면에 그려지는 글리프로 정렬된다
- **Objective**: `_ON_RANK`(`●`/`✓` → `○` → `·` → `─`)와 `_UPD_RANK`(`↑` → `!` → `…` → `·` → `─`)가 렌더러와 같은 cell 함수를 통해 순위를 매기는지 검증 (US-TUI03 AC6)
- **Preconditions**: 인메모리 `TuiState` + 더미 항목. 파일시스템 접근이 필요한 cell 함수는 monkeypatch
- **Steps**: 1) 4가지 상태 글리프를 섞어 정렬 2) 알 수 없는 글리프 3) `S` 로 방향 뒤집기
- **Expected Result**: 1) 랭크 순서대로, 2) 마지막으로 밀림, 3) 정확히 역순
- **Priority**: Medium

---

## 17. 기타 시스템 함수

### SC-UNIT-074 — 최초 실행 마커가 1회성 안내를 통제한다
- **Objective**: `is_first_run()` 이 마커 부재 시 `True` 이고, `mark_onboarded()` 가 마커를 만들며 idempotent 하고, 쓰기 실패를 삼키는지 검증 (US-SYS02 AC1~AC3)
- **Preconditions**: `_onboarded_marker_path` 를 `tmp_path` 로 monkeypatch — 사용자 홈 오염 금지
- **Steps**: 1) 마커 없음 2) `mark_onboarded()` 후 재확인 3) 두 번 호출 4) 부모 디렉터리 생성 실패 주입 5) 마커 삭제 후 재확인
- **Expected Result**: 1) `True`, 2) `False`, 3) 예외 없음, 4) 예외를 삼키고 진행, 5) 다시 `True`
- **Priority**: Medium

### SC-UNIT-075 — 병렬 실행 헬퍼가 실패를 격리한다
- **Objective**: `pooled_map` 이 결과와 오류를 분리 수집하고, 콜백을 항목별로 호출하며, 빈 입력에서 안전한지 검증 (US-SYS06 AC1, US-UPD06 AC2)
- **Preconditions**: 순수 인메모리 함수 — 스레드 경합 검증은 load 계층 소유이므로 여기서는 결과 분리만 본다
- **Steps**: 1) 전부 성공 2) 일부가 예외 3) 빈 입력 4) `on_result` / `on_error` 콜백
- **Expected Result**: 2) 성공 결과는 그대로 수집되고 실패는 `errors` 에 담김, 3) 빈 결과, 4) 항목별로 정확히 1회씩 호출
- **Priority**: Medium

---

## 스펙 갭

문서(`FEATURES.md` / `user-stories.md`)와 현재 구현이 어긋나는 지점. 테스트는 **스펙 기준**으로 작성하므로
아래 항목의 TC 는 현 구현에서 실패할 수 있다. 실패 시 `TEST_DEDUP_POLICY.md` §5 에 따라 테스트가 아니라
구현/스펙 중 무엇이 틀렸는지를 먼저 판정한다.

### G-1 — `axt usage` 의 `--since` / `--until` 이 선언만 되고 무시된다
`_add_usage_filter_args` 는 `--since`/`--until` 을 등록하지만 `cli.py` 어디에서도 `args.since`/`args.until` 을
읽지 않는다. `cli_usage_today` 는 항상 오늘, `cli_usage_week` 는 항상 최근 7일을 자체 계산한다.
US-USG02 AC1(잘못된 날짜 형식 → exit 1)·AC2(`--since > --until` → 오류)는 구현이 없다.
→ 관련 TC 는 `api-testcases.md` 에서 `NEW` 로 표기.

### G-2 — (해소됨) 마켓 sync 는 `reset --hard` 가 맞다
`FEATURES.md` §3.5 가 `git pull --ff-only` 로 낡아 있었고 US-MKT05 가 거기서 파생됐다.
구현의 hard-sync 가 v1.11.0 에서 의도적으로 도입된 회귀 대응임이 확인되어 **문서를 정정**했다.
판정 근거: `tests/doc/SPEC_DECISIONS.md` SD-001

### G-3 — `usage` 공통 옵션 `--breakdown` / `--export` 가 argparse 에 없다
`FEATURES.md` §1.9 는 공통 옵션으로 `--breakdown`·`--export <path>` 를 명시하고 US-USG03 AC3 은
`--export` 가 파일을 쓰고 실패 시 exit 1 이라고 정의하지만, `_add_usage_filter_args` 에는 두 옵션이 없다.
현재는 argparse 단계에서 exit 2 로 거절된다.

### G-4 — mcp-tools / plugins 의 `actionable` 이 스펙과 반대다
US-CTX02 AC2 는 `mcp-tools` 를 actionable=true 로 규정하지만, `collect_context_sources` 는 mcp-tools 와
plugins 를 `actionable=False` 로 만든다. 어느 쪽이 맞는지 확정이 필요하다.

### G-5 — `vault add` 가 파일 타입에서 덮어쓰기를 막지 못한다
US-VLT03 AC4 는 "같은 이름이 이미 vault 에 있으면 덮어쓰지 않고 명확히 실패"를 요구한다. 디렉터리는
`shutil.copytree` 가 `FileExistsError` 를 내지만, 파일은 `shutil.copy2` 라 **조용히 덮어쓴다**.

### G-6 — `usage session` 이 다중 prefix 매칭 후보를 제시하지 않는다
US-USG05 AC3 은 매칭이 여럿이면 후보를 보여주라고 하지만, `cli_usage_session` 은 `aggregate_by_session` 의
첫 번째 세션만 출력한다.

### G-7 — `vault install` 이 미등록 마켓플레이스를 구분하지 못한다
US-VLT04 AC1 은 등록되지 않은 마켓명에 대해 사용 가능한 마켓 목록을 안내하라고 하지만, 구현은
마켓 미등록과 확장 미존재를 같은 메시지로 처리한다.

### 다른 계층이 소유하는 항목 (여기서 검증하지 않음)
- MCP `env` 값 마스킹(US-MCP05) → **security** 계층
- `..` / 절대 경로 / symlink 탈출(US-SYS08), tarball 경로 탈출 → **security** 계층
  (단 `test_download_and_extract_tarball_rejects_path_traversal` 이 이미 `tests/test_marketplace.py` 에 있음 — 이관 검토 대상)
- 색맹 안전·최소 터미널 폭(US-TUI10 AC1) → **accessibility** 계층
- 대용량 JSONL 의 시간·호출횟수 상한(US-USG08) → **performance** 계층
