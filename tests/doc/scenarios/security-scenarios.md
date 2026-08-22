# Security 테스트 시나리오

axt의 보안 표면은 **웹이 아니라 로컬 파일시스템·프로세스**다. HTTP 서버도 브라우저도 세션도 없으므로
인증/인가·XSS·CSRF·SQLi는 존재하지 않는다. 실제 위험은 다음 네 가지다.

1. axt가 **심볼릭 링크를 만들고 지우고 디렉터리를 삭제**한다 → 경로 탈출·범위 이탈
2. axt가 **12곳에서 `subprocess`를 띄우고 그중 하나(`preview_hook`)는 의도적으로 `sh -c`를 쓴다** → 명령 주입
3. axt가 **원격 tarball과 git 저장소를 신뢰 없이 받아 푼다** → 아카이브 경로 탈출(CVE-2007-4559 계열)
4. axt가 **토큰이 담긴 설정 파일(`~/.claude.json`, MCP `env`)을 읽고 다시 쓴다** → 민감정보 노출·권한 확대

OWASP 매핑은 **실제로 성립하는 곳에만** 붙인다. 억지로 끼워 맞추지 않고, 성립하지 않으면 `해당 없음`으로 적는다.

- 스펙 출처: `tests/doc/user-stories.md`(US-xxx), `FEATURES.md` §1.3 / §3.2 / §3.4 / §3.5 / §3.10 / §7.2 / §7.6
- Layer Owner: `tests/test_security.py` (`TEST_DEDUP_POLICY.md` §2 — 심볼릭 링크 탈출·명령 주입·민감정보 노출)

---

## SC-SEC-001 — 링크 생성 이름이 대상 디렉터리를 벗어나지 못한다

- **Objective**: `US-SYS08` AC1/AC2 — `..`이 섞였거나 절대경로인 링크 이름이 `~/.claude/<type>s` ·
  `<proj>/.claude/<type>s` 바깥에 심볼릭 링크를 만들지 못함을 검증한다.
- **OWASP**: A01:2021 Broken Access Control (CWE-22 Path Traversal)
- **Preconditions**
  - `tmp_path` 아래에 가짜 HOME/프로젝트를 만들고 `axt.PATHS`·`AXT_CONFIG_PATH`를 monkeypatch로 교체
  - `monkeypatch.chdir(project_dir)` — cwd 의존 코드(`link_to_project`)를 격리
  - POSIX 전용. `IS_WINDOWS`가 True면 `link_skill`/`link_to_global`이 `OSError`를 던지므로 이 시나리오는 skip이 아니라 **Windows 분기 TC로 대체**(US-VLT05 AC4)
- **Steps**
  1. vault에 정상 skill `demo`를 만든다
  2. 링크 이름에 `../../pwn`, `/tmp/axt-abs-pwn`, `..%2f..%2fpwn`(리터럴) 을 넣어 링크 명령을 실행
  3. 대상 디렉터리 바깥에 새 파일/링크가 생겼는지 확인
- **Expected Result**
  - 링크가 만들어지지 않고 명령이 실패한다(exit 1 + stderr `✗`)
  - 대상 디렉터리 밖의 파일시스템은 **호출 전후 스냅샷이 동일**하다
- **Priority**: Critical

---

## SC-SEC-002 — 링크 해제 이름이 대상 디렉터리를 벗어나지 못한다

- **Objective**: `US-SYS08` AC1/AC2 + `US-VLT05` AC3 — 해제(삭제) 경로가 생성 경로보다 위험하다.
  `unlink_from_global` / `unlink_from_project` / `unlink_skill`은 `Path(base) / name` 으로 경로를 만들고
  "심볼릭 링크면 지운다"만 확인하므로, `name`에 `..`이 섞이면 **관리 트리 밖의 심볼릭 링크를 지울 수 있다**.
  dotfile 관리자를 쓰는 사용자의 `~/.zshrc`·`~/.gitconfig`는 대부분 심볼릭 링크라 실제 피해가 난다.
- **OWASP**: A01:2021 Broken Access Control (CWE-22)
- **Preconditions**
  - 가짜 HOME 아래에 `~/.zshrc` → `dotfiles/zshrc` 심볼릭 링크를 만들어 둔다(피해자 역할)
  - vault는 비어 있다 — `cli_vault_unlink_global`이 조회 실패 후 합성 `VaultItem`으로 진행하는 경로를 태운다
- **Steps**
  1. `axt vault unlink-global skill "../../.zshrc"` 실행
  2. `axt project remove skill "../../../.claude/skills/other"` 실행
  3. `axt skill unlink "../../.zshrc"` 실행
- **Expected Result**
  - 세 명령 모두 exit 1 + stderr 오류, `~/.zshrc` 심볼릭 링크는 **그대로 남는다**
  - vault에 없는 이름은 `US-VLT05` AC3에 따라 exit 1이며, exit 0 + 성공 메시지(`✓ Unlinked …`)는 금지
- **Priority**: Critical

---

## SC-SEC-003 — 파괴적 삭제가 axt 소유 디렉터리만 지운다

- **Objective**: `US-MKT04` AC1 + `US-SYS08` AC4 — `market remove`는 axt가 설치한 디렉터리만 삭제하고
  `dir:`로 등록된 외부 경로는 절대 지우지 않는다. 소유 판정이 **경로 경계**가 아니라 **문자열 접두사**면
  형제 디렉터리(`…/marketplaces-backup`)가 오판으로 삭제된다.
- **OWASP**: A01:2021 Broken Access Control
- **Preconditions**
  - `marketplaces_dir = tmp_path/"plugins"/"marketplaces"`
  - 형제 디렉터리 `tmp_path/"plugins"/"marketplaces-backup"` 에 사용자 파일 `keepme.txt` 를 둔다
  - `known_marketplaces.json` 에 `installLocation`이 형제 디렉터리를 가리키는 항목을 등록
- **Steps**
  1. `dir:` 소스로 등록한 외부 마켓을 remove → 외부 디렉터리 보존 확인
  2. `installLocation`이 `…/marketplaces-backup` 인 항목을 remove → 형제 디렉터리 보존 확인
  3. 정상 소유 항목(`…/marketplaces/mine`)을 remove → 삭제 확인
- **Expected Result**
  - 1·2는 레지스트리 항목만 사라지고 디스크는 보존
  - 3만 실제 삭제
- **Priority**: Critical

---

## SC-SEC-004 — 삭제가 심볼릭 링크를 따라 관리 트리 밖으로 나가지 않는다

- **Objective**: `US-SYS08` AC3 + `US-LNK03` AC1/AC2 — 해제는 링크 자체만 지우고 **대상 실체를 지우지 않는다**.
  또한 `~/.claude/skills` 자체가 외부 저장소를 가리키는 심볼릭 링크여도 삭제가 그 안으로 재귀하지 않는다.
- **OWASP**: A01:2021 Broken Access Control (CWE-59 Link Following)
- **Preconditions**
  - `real_skill/` 실체 디렉터리 + 그것을 가리키는 `~/.claude/skills/demo` 심볼릭 링크
  - `~/.claude/agents` 를 `external_agents/` 를 가리키는 심볼릭 링크로 구성
- **Steps**
  1. `axt skill unlink demo` → 링크만 제거, `real_skill/SKILL.md` 존속 확인
  2. `~/.claude/skills/realdir` 를 **실제 디렉터리**로 만들고 `axt skill unlink realdir` → 거부
  3. `vault unlink-global agent x` 실행 후 `external_agents/` 내용 보존 확인
- **Expected Result**
  - 실체 파일 수·내용이 조작 전후 동일
  - 실제 디렉터리 삭제 요청은 exit 1 + `is not a symlink` 취지의 메시지
- **Priority**: Critical

---

## SC-SEC-005 — 외부 명령 인자로 셸 메타문자가 실행되지 않는다

- **Objective**: `US-SYS06` AC1 + `US-MKT01`/`US-MKT02` — git/tar/claude 호출은 인자 리스트로 전달되어야 한다.
  마켓플레이스명·스킬명·경로에 `; touch /tmp/pwned` 나 `$(…)` 가 들어가도 셸이 해석하지 않는다.
- **OWASP**: A03:2021 Injection (CWE-78 OS Command Injection)
- **Preconditions**
  - `subprocess.run` 을 스파이로 교체해 **호출 인자 그대로** 기록하되 실제 실행은 하지 않는다
  - 센티널 파일 경로는 `tmp_path/"pwned"` (실HOME 오염 금지)
- **Steps**
  1. 이름이 `evil; touch <sentinel>` 인 마켓을 add → sync
  2. `installLocation` 이 `$(touch <sentinel>)` 인 항목으로 `get_local_version` 호출
  3. 기록된 각 호출의 첫 인자가 리스트이고 `shell=True` 가 없음을 확인
- **Expected Result**
  - 센티널 파일이 만들어지지 않는다
  - 위험 문자열은 **하나의 argv 원소**로 그대로 전달된다(분리·해석되지 않음)
- **Priority**: Critical

---

## SC-SEC-006 — `sh -c` 훅 프리뷰가 의도된 범위 안에서만 실행된다

- **Objective**: `US-HK04` AC1/AC2 — 훅 프리뷰는 **사용자가 `v`를 눌러 명시적으로 시작할 때만** 셸을 띄우고,
  결과는 캡처될 뿐 평가되지 않으며, 실패·타임아웃이 TUI를 죽이지 않는다.
  이 경로는 "셸 실행"이 버그가 아니라 **기능**이다. 검증 대상은 실행 여부가 아니라 **격리·촉발 조건**이다.
- **OWASP**: A03:2021 Injection — 부분 해당. 명령은 사용자 자신의 설정 파일에서 오고 실행이 설계 목표이므로
  "주입 차단"이 아니라 **자동 실행 금지 + 출력 무해화 + 타임아웃**이 검증 항목이다.
- **Preconditions**
  - `hooks` 설정에 `echo` 계열 명령 훅 1건, 5초 이상 도는 `sleep` 훅 1건
  - `preview_hook(hook, timeout_ms=…)` 의 timeout 을 테스트에서 200ms로 낮춰 결정적으로 만든다
- **Steps**
  1. 목록 조회(`hook list`) · 렌더(`render` 경로)만 수행 → 셸이 한 번도 호출되지 않았는지 확인
  2. `v` (preview) 를 눌렀을 때만 `sh -c` 가 1회 호출되는지 확인
  3. 출력에 ANSI 이스케이프/제어문자가 섞여 있어도 그대로 화면 셀에 기록되지 않고 잘려 들어가는지 확인
  4. 타임아웃 훅 → `timeout after Nms` 결과 객체 반환, 예외 전파 없음
- **Expected Result**
  - 자동 실행 0회, 명시 실행 1회
  - 실패/타임아웃은 `HookPreviewResult.error` 로 담기고 호출자에게 예외가 새지 않는다
- **Priority**: High

---

## SC-SEC-007 — 비신뢰 아카이브·원격 소스가 추출 루트를 벗어나지 못한다

- **Objective**: `US-MKT01` + `US-SYS07` AC3 — `urllib.request` 로 받은 tarball을 `tarfile` 로 풀 때
  `../` 멤버, 절대경로 멤버, 바깥을 가리키는 심볼릭/하드 링크 멤버가 추출 루트를 탈출하지 못한다.
- **OWASP**: A08:2021 Software and Data Integrity Failures (CWE-22, CVE-2007-4559 계열)
- **Preconditions**
  - 네트워크 없음 — `_fetch_github_head_sha` 와 `urllib.request.urlopen` 을 로컬 tar 바이트를 돌려주는 스텁으로 교체
  - 악성 tar은 테스트 안에서 `tarfile` 로 직접 만든다(고정 바이트, 외부 픽스처 파일 금지)
  - Python 3.12+ 는 `filter="data"`, 3.9–3.11 은 자체 멤버 검증 분기를 타므로 **양쪽 분기 모두** 태운다
- **Steps**
  1. 멤버명이 `../escape.txt` 인 tar → 추출
  2. 멤버명이 `/etc/escape.txt` 인 tar → 추출
  3. `link.txt -> ../../outside` 심볼릭 링크 멤버 tar → 추출
- **Expected Result**
  - 세 경우 모두 `RuntimeError`(unsafe path/link 취지) 로 거부
  - 추출 루트 **바깥에 어떤 파일도 생기지 않는다**
  - 임시 디렉터리는 실패 경로에서도 정리된다
- **Priority**: Critical

---

## SC-SEC-008 — 적대적 JSON이 크래시나 무한 대기를 만들지 않는다

- **Objective**: `US-SYS05` AC1 — `read_json(path, fallback=…)` 은 파싱 실패 시 fallback을 돌려준다.
  깊게 중첩된 배열, 타입이 어긋난 값, 매우 큰 파일에서도 예외가 호출자까지 전파되지 않는다.
- **OWASP**: A08:2021 Software and Data Integrity Failures — **부분 해당**.
  JSON은 코드 실행 벡터가 없으므로 고전적 "insecure deserialization"은 아니고, 가용성(DoS)·무결성 관점만 성립한다.
- **Preconditions**
  - `sys.setrecursionlimit` 는 건드리지 않는다(전역 오염). 중첩 깊이는 CPython 기본 한계를 넘도록 20,000단계로 만든다
  - 큰 파일은 5MB 상당의 반복 문자열로 생성하고 `tmp_path` 안에서만 다룬다
- **Steps**
  1. `[[[[…]]]]` 20,000단계 중첩 JSON을 `settings.json` 으로 두고 `read_enabled_plugins` 호출
  2. `enabledPlugins` 가 리스트(객체 아님)인 settings 로 동일 호출
  3. 5MB 무의미 텍스트를 `known_marketplaces.json` 으로 두고 `list_marketplaces` 호출
- **Expected Result**
  - 셋 다 빈 결과(`{}` / `[]`) 로 fallback 하고 예외를 던지지 않는다
  - `RecursionError` 를 포함해 어떤 예외도 호출자에게 새지 않는다
- **Priority**: High

---

## SC-SEC-009 — MCP 자격증명이 목록·상세·TUI에 평문으로 나오지 않는다

- **Objective**: `US-MCP05` AC1/AC2/AC3 — MCP 서버의 `env` 에는 API 키·토큰이 들어간다.
  `mcp list` 는 env를 출력하지 않고, `mcp info` 와 TUI detail 패널은 **값을 마스킹**해야 한다.
- **OWASP**: A02:2021 Cryptographic Failures (2017 A3 Sensitive Data Exposure)
- **Preconditions**
  - `~/.claude.json` 에 `env: {"GITHUB_TOKEN": "ghp_LIVEKEY0000000000000000000000000000", "DEBUG": "1"}` 인 서버 등록
  - 마스킹 정책은 스펙에 문장으로만 있으므로 **"원문 값이 출력에 나타나지 않는다"** 를 단언 기준으로 삼는다
    (마스킹 형식 `ghp_…****` 등은 구현 자유)
- **Steps**
  1. `axt mcp list` stdout 캡처
  2. `axt mcp info <name>` stdout 캡처
  3. TUI MCP 서브탭 detail 패널을 fake stdscr 로 렌더하고 그려진 텍스트를 이어붙여 검사
- **Expected Result**
  - 세 출력 어디에도 `ghp_LIVEKEY0000000000000000000000000000` 원문이 없다
  - 키 **이름**(`GITHUB_TOKEN`)은 진단에 필요하므로 노출을 허용한다
- **Priority**: High
- **비고**: 현재 구현은 `cli_mcp_info` 가 `json.dumps(server.env_dict)` 를, TUI `_mcp_detail_fields` 가
  `k=v` 를 그대로 출력한다. 이 시나리오의 TC는 **스펙 기준으로 작성**하며 지금은 실패할 것으로 예상한다
  (`## 스펙 갭` 참조).

---

## SC-SEC-010 — 원자적 쓰기가 권한을 넓히거나 동시 쓰기로 파일을 깨뜨리지 않는다

- **Objective**: `US-SYS04` AC1/AC3 — `write_json_atomic` 은 tmpfile + `os.replace` 를 쓴다.
  이때 (a) 기존 파일의 퍼미션이 유지되어야 하고(0600 파일이 0644로 넓어지면 안 됨),
  (b) 두 writer 가 같은 파일을 동시에 써도 최종 파일이 항상 **유효한 JSON**이어야 한다.
- **OWASP**: (a) A05:2021 Security Misconfiguration / (b) 해당 없음 — 동시성 무결성은 OWASP 카테고리가 아니다
- **Preconditions**
  - POSIX 전용(퍼미션 비트). Windows 는 대상 외
  - 동시성 TC는 `threading` 2개 + `Barrier` 로 시작 시점을 맞추고, 반복 50회로 경합을 강제한다
  - 실HOME 금지 — 전부 `tmp_path`
- **Steps**
  1. `0o600` 인 기존 `claude.json` 에 `write_json_atomic` → `stat().st_mode & 0o777` 확인
  2. 같은 경로에 두 스레드가 서로 다른 내용을 50회 교차 기록
  3. 매 회 결과 파일을 `json.load` 로 파싱
- **Expected Result**
  - 1: 퍼미션이 `0o600` 으로 유지된다
  - 2·3: 파싱 실패가 0회, 최종 내용은 두 writer 중 하나의 **완전한** 내용(부분 병합 금지)
  - `.tmp-*.json` 잔여물이 남지 않는다
- **Priority**: High

---

## 스펙 갭

| # | 관측 | 관련 US | 판단 |
|---|---|---|---|
| G-SEC-1 | `cli_mcp_info` / `_mcp_detail_fields` 가 MCP `env` 값을 평문 출력 | US-MCP05 AC2/AC3 | **구현 갭**. 스토리 자체가 "스펙 갭 — §F-3 확인 대상"으로 표기됨. TC는 스펙 기준(마스킹)으로 작성했고 현재는 실패 예상 |
| G-SEC-2 | `write_json_atomic` 이 tmpfile 기본 umask(0644)로 만들고 `os.replace` 하므로 0600 원본의 퍼미션이 넓어짐 | US-SYS04 | **구현 갭**. 스토리에 퍼미션 조항은 없으나 `~/.claude.json`(OAuth 토큰 보관)에 쓰는 경로이므로 보안 요구로 승격 |
| G-SEC-3 | `cli_vault_unlink_global` / `cli_project_remove` 가 vault 조회 실패 시 합성 `VaultItem` 으로 진행하고 exit 0 | US-VLT05 AC3 | **구현 갭**. AC3는 "vault에 없는 이름은 exit 1" 이므로 스펙 위반이자 SC-SEC-002의 탈출 경로 |
| G-SEC-4 | `remove_marketplace` 의 소유 판정이 `install_location.startswith(str(marketplaces_dir))` 문자열 접두사 | US-MKT04 AC1 | **구현 갭**. 형제 디렉터리 오판 삭제 가능. 경로 경계(`_is_within_dir`)로 판정해야 함 |
| G-SEC-5 | `sync_marketplace` 가 `git fetch` + `git reset --hard @{u}` 를 사용 | US-MKT05 AC1 (`git pull --ff-only`), FEATURES.md §3.5 | **해소됨 — `tests/doc/SPEC_DECISIONS.md` SD-001.** 구현(hard-sync)이 옳고 낡은 `FEATURES.md` §3.5 가 틀렸다. 설치 디렉터리는 사용자 작업 공간이 아니라 관리 대상 캐시이며, 커밋되지 않은 로컬 수정은 Claude Code 업데이터 산출물로 간주해 폐기된다. 문서·유저스토리를 정정했고 구현은 변경하지 않았다. |
| G-SEC-6 | 링크 이름에 대한 정규화·경계 검증 함수가 없음(`_is_within_dir` 는 tar 추출에만 사용) | US-SYS08 AC1/AC2 | **구현 갭**. 링크 생성/해제 경로에도 동일 가드가 필요 |
