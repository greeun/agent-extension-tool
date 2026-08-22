# Security 테스트 케이스

Layer Owner: `tests/test_security.py`
시나리오 출처: [security-scenarios.md](../scenarios/security-scenarios.md)
스펙 출처: `tests/doc/user-stories.md`, `FEATURES.md`

## 요약

| 항목 | 값 |
|---|---|
| **총 TC 수** | **29** (그중 5건은 기존 테스트가 이미 소유 → 신규 작성 대상 24건) |
| 우선순위 | Critical 19 / High 10 / Medium 0 / Low 0 |
| Gap | COVERED 5 / PARTIAL 3 / NEW 21 |
| 실패 예상 TC | 10 (TC-SEC-004 · 005 · 006 · 007 · 009 · 022 · 024 · 026 · 027 · 028) — 스펙-구현 갭. 테스트가 아니라 구현을 고쳐야 통과한다 |

## TC 인덱스

| TC ID | 시나리오 | 제목 | US | 우선순위 | OWASP | Gap |
|---|---|---|---|---|---|---|
| TC-SEC-001 | SC-SEC-001 | `skill link -n "../../pwn"` 이 skills 밖에 링크를 만들지 않는다 | US-SYS08 AC1 | Critical | A01 | NEW |
| TC-SEC-002 | SC-SEC-001 | 절대경로 링크 이름이 대상 디렉터리를 벗어나지 않는다 | US-SYS08 AC2 | Critical | A01 | NEW |
| TC-SEC-003 | SC-SEC-001 | `link_to_project` 가 `..` 이름으로 프로젝트 밖에 링크를 만들지 않는다 | US-SYS08 AC1 | Critical | A01 | NEW |
| TC-SEC-004 | SC-SEC-002 | `vault unlink-global` 이 `..` 이름으로 HOME의 dotfile 링크를 지우지 않는다 | US-SYS08 AC1 | Critical | A01 | NEW |
| TC-SEC-005 | SC-SEC-002 | vault에 없는 이름의 `unlink-global` 은 exit 1 | US-VLT05 AC3 | Critical | A01 | NEW |
| TC-SEC-006 | SC-SEC-002 | `project remove` 가 `.claude/<type>s` 밖의 링크를 지우지 않는다 | US-SYS08 AC1 | Critical | A01 | NEW |
| TC-SEC-007 | SC-SEC-002 | `skill unlink "../../x"` 는 exit 1 이고 외부 링크를 보존한다 | US-SYS08 AC1 | Critical | A01 | NEW |
| TC-SEC-008 | SC-SEC-003 | `dir:` 외부 경로는 remove 후에도 남는다 | US-MKT04 AC1 | Critical | A01 | COVERED |
| TC-SEC-009 | SC-SEC-003 | 형제 디렉터리(`marketplaces-backup`)가 소유 오판으로 삭제되지 않는다 | US-SYS08 AC4 | Critical | A01 | NEW |
| TC-SEC-010 | SC-SEC-003 | axt 소유 설치 디렉터리는 remove 시 삭제된다 | US-MKT04 AC1 | High | A01 | COVERED |
| TC-SEC-011 | SC-SEC-004 | unlink 후 링크 대상 실체가 보존된다 | US-LNK03 AC1 | Critical | A01 | COVERED |
| TC-SEC-012 | SC-SEC-004 | 실제 디렉터리 unlink 요청은 거부된다 | US-LNK03 AC2 | Critical | A01 | COVERED |
| TC-SEC-013 | SC-SEC-004 | `~/.claude/agents` 가 심볼릭 링크여도 삭제가 대상 트리로 재귀하지 않는다 | US-SYS08 AC3 | Critical | A01 | NEW |
| TC-SEC-014 | SC-SEC-005 | 셸 메타문자가 든 마켓명이 명령으로 실행되지 않는다 | US-SYS06 AC1 | Critical | A03 | NEW |
| TC-SEC-015 | SC-SEC-005 | `$(…)` 가 든 경로가 git 인자로 그대로 전달된다 | US-SYS06 AC1 | Critical | A03 | NEW |
| TC-SEC-016 | SC-SEC-006 | 훅 목록·렌더는 셸을 호출하지 않는다 | US-HK04 AC1 | Critical | A03(부분) | NEW |
| TC-SEC-017 | SC-SEC-006 | `v` preview 만 `sh -c` 를 정확히 1회 호출한다 | US-HK04 AC1 | High | A03(부분) | NEW |
| TC-SEC-018 | SC-SEC-006 | preview 타임아웃이 예외로 새지 않는다 | US-HK04 AC2 | High | 해당 없음 | COVERED |
| TC-SEC-019 | SC-SEC-007 | `../` 멤버 tar 추출이 거부된다 | US-MKT01 | Critical | A08 | PARTIAL |
| TC-SEC-020 | SC-SEC-007 | 절대경로 멤버 tar 추출이 거부된다 | US-MKT01 | Critical | A08 | NEW |
| TC-SEC-021 | SC-SEC-007 | 바깥을 가리키는 심볼릭 링크 멤버가 거부된다 | US-MKT01 | Critical | A08 | NEW |
| TC-SEC-022 | SC-SEC-008 | 20,000단계 중첩 JSON이 fallback으로 처리된다 | US-SYS05 AC1 | High | A08(부분) | NEW |
| TC-SEC-023 | SC-SEC-008 | 타입이 어긋난 settings 값이 빈 맵으로 fallback 된다 | US-SYS05 AC1 | High | A08(부분) | PARTIAL |
| TC-SEC-024 | SC-SEC-008 | 5MB 비-JSON 파일이 크래시 없이 빈 목록이 된다 | US-SYS05 AC1 | High | A08(부분) | NEW |
| TC-SEC-025 | SC-SEC-009 | `mcp list` 출력에 env 값이 없다 | US-MCP05 AC1 | High | A02 | NEW |
| TC-SEC-026 | SC-SEC-009 | `mcp info` 가 env 값을 마스킹한다 | US-MCP05 AC2 | High | A02 | NEW |
| TC-SEC-027 | SC-SEC-009 | TUI MCP detail 패널이 env 값을 마스킹한다 | US-MCP05 AC3 | High | A02 | NEW |
| TC-SEC-028 | SC-SEC-010 | `write_json_atomic` 이 0600 파일의 퍼미션을 유지한다 | US-SYS04 AC1 | Critical | A05 | NEW |
| TC-SEC-029 | SC-SEC-010 | 두 스레드 동시 쓰기 후에도 파일이 항상 유효한 JSON이다 | US-SYS04 AC3 | High | 해당 없음 | PARTIAL |

> COVERED 5건(TC-SEC-008 · 010 · 011 · 012 · 018)은 기존 테스트가 소유한다.
> Layer Ownership 위반을 피해 `tests/test_security.py` 에서 재작성하지 않고 문서에서 참조만 한다.
> **신규 작성 대상은 24건**(NEW 21 + PARTIAL 3).

---

## SC-SEC-001 — 링크 생성 경로 탈출

### TC-SEC-001 — `skill link -n "../../pwn"` 이 skills 밖에 링크를 만들지 않는다

- **US**: US-SYS08 AC1 / **OWASP**: A01:2021 Broken Access Control (CWE-22) / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `home = tmp_path/"home"`, `monkeypatch.setattr("axt.PATHS", …)` 로 `claude_dir = home/".claude"` 지정
  - `monkeypatch.setattr("axt.HOME", home)`, `monkeypatch.setenv("HOME", str(home))`
  - `monkeypatch.chdir(tmp_path/"proj")` — cwd 의존 제거
  - POSIX 전용 (`pytest.mark.skipif(sys.platform == "win32")`)
- **Input**
  - 실제 스킬 디렉터리: `tmp_path/"src-skill"` (안에 `SKILL.md`)
  - 명령: `axt skill link <tmp_path>/src-skill -n "../../pwn"`
- **Steps**
  1. `home/".claude"/"skills"` 를 만들어 둔다
  2. 실행 전 `tmp_path` 전체 파일 목록을 `set(p for p in tmp_path.rglob("*"))` 로 스냅샷
  3. `axt.main(["skill", "link", str(src), "-n", "../../pwn"])` 호출
  4. 실행 후 스냅샷 재수집
- **Expected Output**
  - 반환값 `1`
  - stderr 에 `✗` 로 시작하는 오류 1줄
  - `(home/".claude").parent/"pwn"` 및 `home/"pwn"` 이 **존재하지 않는다**
  - 실행 전후 스냅샷 차집합이 공집합
- **실패 시 조치**: `link_skill` 에 이름 경계 검증을 추가한다 — `(skills_dir/name).resolve()` 가
  `skills_dir.resolve()` 의 자손인지 확인하고 아니면 `ValueError`

### TC-SEC-002 — 절대경로 링크 이름이 대상 디렉터리를 벗어나지 않는다

- **US**: US-SYS08 AC2 / **OWASP**: A01 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**: TC-SEC-001 과 동일한 격리
- **Input**: `-n "/tmp/axt-abs-pwn"` (리터럴 절대경로)
- **Steps**
  1. `axt.main(["skill", "link", str(src), "-n", "/tmp/axt-abs-pwn"])`
  2. `Path("/tmp/axt-abs-pwn").exists()` 확인 후 즉시 정리 (테스트가 실패하더라도 잔여물이 남지 않게 `finally` 로 unlink)
- **Expected Output**
  - 반환값 `1`, `/tmp/axt-abs-pwn` 미생성
  - `home/".claude"/"skills"` 안에 새 항목 0개
- **비고**: `Path(a) / "/abs"` 는 파이썬에서 `/abs` 로 평가되므로 앵커 리셋이 실제 위험이다.
  경계 검증은 `..` 뿐 아니라 절대경로도 함께 막아야 한다.

### TC-SEC-003 — `link_to_project` 가 `..` 이름으로 프로젝트 밖에 링크를 만들지 않는다

- **US**: US-SYS08 AC1 / **OWASP**: A01 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `proj = tmp_path/"proj"` 생성 후 `monkeypatch.chdir(proj)`
  - `sibling = tmp_path/"sibling"` 을 만들어 침범 대상으로 둔다
- **Input**: `VaultItem(name="../../sibling/pwn", type="skill", path=str(vault_skill), description="")`
- **Steps**
  1. `axt.link_to_project(proj, item)` 호출
  2. `(tmp_path/"sibling"/"pwn").exists()` 확인
  3. `.axt-profile.json` 내용 확인
- **Expected Output**
  - `ValueError` 발생 (이름 경계 위반)
  - `tmp_path/"sibling"` 아래에 아무것도 생기지 않는다
  - 프로필 파일이 **쓰이지 않는다** — 실패한 링크가 프로필에 기록되면 이후 `project sync` 가 매번 같은 탈출을 재시도한다

---

## SC-SEC-002 — 링크 해제 경로 탈출

### TC-SEC-004 — `vault unlink-global` 이 `..` 이름으로 HOME의 dotfile 링크를 지우지 않는다

- **US**: US-SYS08 AC1 / **OWASP**: A01 (CWE-22) / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**
  - `home = tmp_path/"home"`; `dotfiles = tmp_path/"dotfiles"` 에 실제 `zshrc` 파일 생성
  - `home/".zshrc"` → `dotfiles/"zshrc"` 심볼릭 링크 (dotfile 관리자 사용자 재현)
  - `axt.PATHS.claude_dir = home/".claude"`, `axt.PATHS.vault = home/".axt"/"vault"` (vault는 **비어 있음**)
  - `monkeypatch.setattr("axt.HOME", home)`
- **Input**: `axt.main(["vault", "unlink-global", "skill", "../../.zshrc"])`
- **Steps**
  1. 실행 전 `home/".zshrc"` 가 심볼릭 링크임을 확인
  2. 명령 실행
  3. `home/".zshrc"` 존속 여부 재확인
- **Expected Output**
  - 반환값 `1`
  - `home/".zshrc"` 가 **여전히 심볼릭 링크로 존재**하고 `dotfiles/"zshrc"` 를 가리킨다
  - stdout 에 `✓ Unlinked` 성공 메시지가 **없다**
- **현재 구현 예상 결과**: `cli_vault_unlink_global` 이 vault 조회 실패 시 합성 `VaultItem` 으로 진행하고
  `unlink_from_global` 이 `claude_dir/"skills"/"../../.zshrc"` → `home/".zshrc"` 를 심볼릭 링크로 판정해 삭제.
  exit 0. **이 TC는 현재 실패해야 정상이다.**

### TC-SEC-005 — vault에 없는 이름의 `unlink-global` 은 exit 1

- **US**: US-VLT05 AC3 / **OWASP**: A01 / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**: vault 비어 있음, `home/".claude"/"skills"` 존재
- **Input**: `axt.main(["vault", "unlink-global", "skill", "never-existed"])`
- **Steps**: 명령 실행 → 반환값과 stdout/stderr 캡처
- **Expected Output**
  - 반환값 `1`
  - stderr 에 `not found in vault` 취지의 메시지
  - stdout 에 `✓` 성공 표기 없음
- **비고**: `cli_vault_link_global` 은 같은 조회 실패에 대해 이미 exit 1 이다. 두 명령의 계약이 어긋나 있다.

### TC-SEC-006 — `project remove` 가 `.claude/<type>s` 밖의 링크를 지우지 않는다

- **US**: US-SYS08 AC1 / **OWASP**: A01 / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**
  - `proj = tmp_path/"proj"`, `monkeypatch.chdir(proj)`
  - `proj/".claude"/"skills"` 생성
  - 침범 대상: `tmp_path/"victim"` → `tmp_path/"real"` 심볼릭 링크
- **Input**: `axt.main(["project", "remove", "skill", "../../../victim"])`
- **Expected Output**
  - 반환값 `1`, `tmp_path/"victim"` 심볼릭 링크 존속
  - `.axt-profile.json` 이 새로 쓰이지 않는다

### TC-SEC-007 — `skill unlink "../../x"` 는 exit 1 이고 외부 링크를 보존한다

- **US**: US-SYS08 AC1 / **OWASP**: A01 / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**: `home/".claude"/"skills"` 존재, `home/"outside-link"` → `tmp_path/"real"` 심볼릭 링크
- **Input**: `axt.main(["skill", "unlink", "../outside-link"])`
- **Expected Output**
  - 반환값 `1`, `home/"outside-link"` 존속
  - 메시지는 "심볼릭 링크가 아님"이 아니라 **경로 경계 위반**을 알려야 한다(원인 진단 가능성)

---

## SC-SEC-003 — 파괴적 삭제 범위

### TC-SEC-008 — `dir:` 외부 경로는 remove 후에도 남는다

- **US**: US-MKT04 AC1 / **OWASP**: A01 / **Priority**: Critical / **Gap**: **COVERED**
- **소유 테스트**: `tests/test_marketplace.py::test_remove_marketplace_directory_keeps_external_dir`
- **조치**: 재작성하지 않는다. security 파일에서는 참조만 한다(Layer Ownership 중복 금지).

### TC-SEC-009 — 형제 디렉터리가 소유 오판으로 삭제되지 않는다

- **US**: US-SYS08 AC4 / **OWASP**: A01 / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**
  - `mks = tmp_path/"plugins"/"marketplaces"` (생성)
  - 형제 `sib = tmp_path/"plugins"/"marketplaces-backup"` 에 `keepme.txt` (내용 `"user data"`)
  - `known_marketplaces.json` 에 항목 `"bad"` 를 직접 기록:
    `{"bad": {"source": {"source": "github", "repo": "x/y"}, "installLocation": "<sib>", "lastUpdated": ""}}`
- **Input**: `axt.remove_marketplace(km, mks, "bad")`
- **Steps**
  1. 호출
  2. `sib.exists()` 및 `(sib/"keepme.txt").read_text()` 확인
  3. `km` 내용 확인
- **Expected Output**
  - `sib/"keepme.txt"` 가 그대로 `"user data"`
  - 레지스트리에서 `"bad"` 항목만 제거
- **현재 구현 예상 결과**: `str(sib).startswith(str(mks))` 가 True 이므로 `shutil.rmtree(sib)` 실행 → **삭제된다.**
- **실패 시 조치**: 소유 판정을 `_is_within_dir(Path(install_location), Path(marketplaces_dir))` 로 교체

### TC-SEC-010 — axt 소유 설치 디렉터리는 remove 시 삭제된다

- **US**: US-MKT04 AC1 / **Priority**: High / **Gap**: **COVERED**
  (`tests/test_marketplace.py::test_remove_marketplace_owned_dir_deleted`)
- **조치**: 참조만. TC-SEC-009 와 짝을 이루는 양성 대조군으로 문서에만 남긴다.

---

## SC-SEC-004 — 심볼릭 링크 추종 삭제

### TC-SEC-011 — unlink 후 링크 대상 실체가 보존된다

- **US**: US-LNK03 AC1 / **Priority**: Critical / **Gap**: **COVERED**
  (`tests/test_skill.py::test_unlink_skill_removes_symlink` — `assert target.exists()` 포함)

### TC-SEC-012 — 실제 디렉터리 unlink 요청은 거부된다

- **US**: US-LNK03 AC2 / **Priority**: Critical / **Gap**: **COVERED**
  (`tests/test_skill.py::test_unlink_skill_refuses_real_directory`, `…_rejects_non_symlink`)

### TC-SEC-013 — `~/.claude/agents` 가 심볼릭 링크여도 삭제가 대상 트리로 재귀하지 않는다

- **US**: US-SYS08 AC3 / **OWASP**: A01 (CWE-59) / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `external = tmp_path/"external-agents"` 에 실제 파일 `keep.md`(내용 `"keep"`)와 `x.md`
  - `home/".claude"/"agents"` → `external` 심볼릭 링크
  - vault에 `agent` 타입 `x` 를 등록
- **Input**: `axt.unlink_from_global(home/".claude", VaultItem(name="x.md", type="agent", path=str(vault_x), description=""))`
- **Steps**
  1. 호출
  2. `external/"keep.md"` 내용 확인
  3. `external/"x.md"` 가 **실제 파일**이므로 삭제되지 않았는지 확인
  4. `home/".claude"/"agents"` 가 여전히 심볼릭 링크인지 확인
- **Expected Output**
  - `external/"keep.md"` == `"keep"` (무손상)
  - `external/"x.md"` 존속 — 실체 파일은 심볼릭 링크가 아니므로 `unlink_from_global` 이 건드리지 않아야 한다
  - `home/".claude"/"agents"` 자체는 절대 삭제되지 않는다
- **판단 근거**: 현재 구현은 `link_path.is_symlink()` 로 가드하므로 통과할 가능성이 높다.
  그래도 **회귀 방어 가치**가 있다 — 가드를 `exists()` 로 바꾸는 리팩터가 조용히 데이터를 지운다.

---

## SC-SEC-005 — 외부 명령 인자 주입

### TC-SEC-014 — 셸 메타문자가 든 마켓명이 명령으로 실행되지 않는다

- **US**: US-SYS06 AC1 / **OWASP**: A03:2021 Injection (CWE-78) / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `sentinel = tmp_path/"pwned"` — 절대 만들어지면 안 되는 파일
  - `subprocess.run` 을 스파이로 교체: 호출 인자를 `calls` 에 기록하고
    `CompletedProcess(args, 0, "", "")` 를 돌려주되 **실제 실행은 하지 않는다**
  - `monkeypatch.setattr("axt.core.subprocess.run", spy)` — 모듈 경로를 명시해 다른 테스트에 새지 않게 한다
- **Input**
  - 마켓명: `evil; touch <sentinel>`
  - `github:owner/repo` 소스로 add 후 `sync_marketplace(km, "evil; touch <sentinel>")`
- **Steps**
  1. add → sync 실행
  2. `sentinel.exists()` 확인
  3. `calls` 의 각 항목에 대해 `args[0]` 이 `list` 이고 `kwargs.get("shell")` 이 `True` 가 아님을 확인
  4. 위험 문자열이 argv 원소 중 하나에 **통째로** 들어 있는지 확인
- **Expected Output**
  - `sentinel.exists() is False`
  - 모든 호출이 argv 리스트 형태, `shell=True` 0건
  - `"evil; touch …"` 가 분리되지 않고 단일 원소로 유지
- **금지**: `grep "shell=True" axt/` 같은 소스 스캔으로 대체하지 않는다(정적 구조 검증 — 정책 §3 위반).
  실제 호출 인자를 관찰해야 리팩터로 도입된 f-string 셸 호출을 잡는다.

### TC-SEC-015 — `$(…)` 가 든 경로가 git 인자로 그대로 전달된다

- **US**: US-SYS06 AC1 / **OWASP**: A03 / **Priority**: Critical / **Gap**: NEW
- **Preconditions**: TC-SEC-014 와 동일한 스파이
- **Input**: `installLocation` 이 `<tmp_path>/$(touch <sentinel>)` 인 레지스트리 항목 → `get_local_version(km, name)`
- **Expected Output**
  - `sentinel` 미생성
  - `git -C <경로> rev-parse --short HEAD` 의 `<경로>` 원소가 `$(touch …)` 문자열을 **이스케이프 없이 그대로** 포함
    (인자 리스트라면 이스케이프가 필요 없다는 사실 자체가 증거)

---

## SC-SEC-006 — `sh -c` 훅 프리뷰 격리

### TC-SEC-016 — 훅 목록·렌더는 셸을 호출하지 않는다

- **US**: US-HK04 AC1 / **OWASP**: A03 (부분 — 설계상 셸 실행이 허용된 경로의 자동 실행 금지) / **Priority**: Critical / **Gap**: NEW
- **Preconditions**
  - `~/.claude/settings.json` 에 `SessionStart` 명령 훅 `touch <sentinel>` 등록
  - `subprocess.run` 스파이로 교체(실행하지 않음)
  - fake stdscr: `tests/test_tui.py::_make_stdscr(rows=30, cols=140)` 와 동일한 형태
- **Steps**
  1. `axt.main(["hook", "list"])`
  2. TUI Hooks 서브탭 렌더 (`_ensure_subtab_loaded` + 렌더러 호출)
  3. detail 패널 포커스 이동(`Tab`)까지 수행
- **Expected Output**
  - 스파이 호출 횟수 **0**
  - `sentinel` 미생성
  - 훅 커맨드 문자열은 화면에 **텍스트로만** 나타난다
- **왜 필요한가**: 훅 명령은 사용자 설정이지만 프로젝트 `.claude/settings.json` 은 **저장소에서 클론된 남의 파일**일 수 있다.
  목록을 보는 것만으로 남의 훅이 실행되면 그것이 곧 원격 코드 실행이다.

### TC-SEC-017 — `v` preview 만 `sh -c` 를 정확히 1회 호출한다

- **US**: US-HK04 AC1 / **Priority**: High / **Gap**: NEW
- **Preconditions**: TC-SEC-016 과 동일 + 스파이가 `CompletedProcess(args, 0, "out", "err")` 반환
- **Steps**
  1. Hooks 서브탭에서 `ord("v")` 를 입력 핸들러에 전달
  2. 스파이 호출 기록 확인
- **Expected Output**
  - 호출 1회, `args[0] == ["sh", "-c", "<hook command>"]`
  - `capture_output=True`, `text=True`, `timeout` 이 지정됨 (무한 대기 금지 — US-SYS06 AC3)
  - `env` 에 `HOOK_EVENT` 가 포함되고 기존 `os.environ` 을 파괴하지 않음
  - 결과 모달 텍스트에 stdout/stderr/exit code 세 요소가 모두 나타난다
- **결정성**: 실제 셸을 띄우지 않으므로 OS·PATH 의존이 없다.

### TC-SEC-018 — preview 타임아웃이 예외로 새지 않는다

- **US**: US-HK04 AC2 / **Priority**: High / **Gap**: **COVERED**
  (`tests/test_hooks.py::test_preview_hook_command_timeout`) — 참조만 한다.

---

## SC-SEC-007 — 비신뢰 아카이브 추출

### TC-SEC-019 — `../` 멤버 tar 추출이 거부된다

- **US**: US-MKT01 / **OWASP**: A08:2021 (CWE-22, CVE-2007-4559 계열) / **Priority**: Critical / **Gap**: **PARTIAL**
- **기존**: `tests/test_marketplace.py::test_download_and_extract_tarball_rejects_path_traversal` 이
  `download_and_extract_tarball` 경로 1건을 덮는다.
- **PARTIAL 사유**: 파이썬 3.12+ 는 `tarfile.data_filter` 분기를, 3.9–3.11 은 자체 검증 루프를 탄다.
  기존 테스트는 실행 인터프리터의 분기 **한쪽만** 태운다. 보안 파일에서는 `_safe_tar_extractall` 을 직접 불러
  `monkeypatch.setattr(tarfile, "data_filter", None)` 로 **레거시 분기도 강제**한다.
- **Input**: 멤버 `../escape.txt`(내용 `"x"`) 하나만 든 `.tar.gz`
- **Expected Output**
  - `RuntimeError` 발생, 메시지에 `Unsafe path` 포함(3.9–3.11) 또는 `Unsafe tarball member`(3.12+)
  - `dest.parent/"escape.txt"` 미생성
  - 두 분기 모두에서 동일한 결론

### TC-SEC-020 — 절대경로 멤버 tar 추출이 거부된다

- **US**: US-MKT01 / **OWASP**: A08 / **Priority**: Critical / **Gap**: NEW
- **Input**: 멤버명 `/tmp/axt-tar-abs.txt`
- **Steps**: `_safe_tar_extractall(tf, dest)` 를 두 분기(`data_filter` 유/무)에서 각각 호출
- **Expected Output**
  - 두 분기 모두 `RuntimeError`
  - `/tmp/axt-tar-abs.txt` 미생성 (테스트는 `finally` 에서 존재 시 정리 후 실패 처리)

### TC-SEC-021 — 바깥을 가리키는 심볼릭 링크 멤버가 거부된다

- **US**: US-MKT01 / **OWASP**: A08 / **Priority**: Critical / **Gap**: NEW
- **Input**: `link.txt` 심볼릭 링크 멤버, `linkname="../../outside"`
- **Expected Output**
  - 레거시 분기: `RuntimeError`, 메시지에 `Unsafe link` 포함
  - 3.12+ 분기: `tarfile.FilterError` 를 감싼 `RuntimeError`
  - `dest` 밖에 심볼릭 링크가 생기지 않는다
- **왜 필요한가**: 경로 검증만 하고 `linkname` 을 놓치면 추출 자체는 안전해 보이지만
  이후 그 링크를 따라 쓰는 코드가 임의 파일을 덮어쓴다. 2단계 공격이라 경로 TC로는 못 잡는다.

---

## SC-SEC-008 — 적대적 JSON

### TC-SEC-022 — 20,000단계 중첩 JSON이 fallback으로 처리된다

- **US**: US-SYS05 AC1 / **OWASP**: A08 (부분) / **Priority**: High / **Gap**: NEW / **실패 예상**
- **Preconditions**
  - `sys.setrecursionlimit` 을 **변경하지 않는다**(전역 상태 오염 금지)
  - 파일 생성: `"[" * 20000 + "]" * 20000` 을 `settings.json` 에 기록
- **Input**: `axt.read_enabled_plugins(settings_path)`
- **Expected Output**
  - 반환값 `{}`
  - `RecursionError` 를 포함해 어떤 예외도 전파되지 않는다
- **현재 구현 예상 결과**: `read_json` 은 `json.load` 를 감싸지 않으므로 `RecursionError` 가 그대로 올라온다.
  `read_json_dict` → `read_enabled_plugins` 경로에도 방어가 없다. **실패 예상.**
- **실패 시 조치**: `read_json` 에 `except (json.JSONDecodeError, RecursionError, UnicodeDecodeError, OSError)` →
  `fallback` 반환을 추가한다. `fallback` 미지정 시에만 재전파.

### TC-SEC-023 — 타입이 어긋난 settings 값이 빈 맵으로 fallback 된다

- **US**: US-SYS05 AC1 / **Priority**: High / **Gap**: **PARTIAL**
- **기존**: `tests/test_settings.py::test_read_enabled_plugins_corrupt_file` 이 최상위가 문자열인 경우를 덮는다
- **PARTIAL 사유**: 최상위는 객체인데 `enabledPlugins` 가 **리스트**인 경우(부분 손상)는 미검증.
  실제 손상은 대개 최상위가 아니라 하위 키에서 난다.
- **Input**: `{"enabledPlugins": ["alpha", "beta"], "otherKey": 1}`
- **Expected Output**
  - `read_enabled_plugins` → `{}` (리스트는 `{id: bool}` 계약을 만족하지 않음)
  - 이후 `set_plugin_enabled(path, "alpha", True)` 호출 시 `otherKey` 가 보존된다
    (손상 키를 덮어쓰되 무관한 사용자 설정을 날리지 않는다)

### TC-SEC-024 — 5MB 비-JSON 파일이 크래시 없이 빈 목록이 된다

- **US**: US-SYS05 AC1 / **Priority**: High / **Gap**: NEW / **실패 예상**
- **Preconditions**: `known_marketplaces.json` 에 `"lorem ipsum " * 450_000` (약 5.4MB) 기록
- **Input**: `axt.list_marketplaces(km_path)`
- **Expected Output**
  - 반환값 `[]`
  - 예외 없음, 호출이 5초 이내에 끝난다(단순 파싱 실패라 즉시 반환되어야 한다)
- **현재 구현 예상 결과**: `json.JSONDecodeError` 전파. CLI 레벨에서는 `ValueError` 로 잡혀 exit 1 이 되지만
  **TUI `_ensure_subtab_loaded` 는 감싸지 않아 대시보드가 죽는다.** 실패 예상.

---

## SC-SEC-009 — MCP 자격증명 노출

### TC-SEC-025 — `mcp list` 출력에 env 값이 없다

- **US**: US-MCP05 AC1 / **OWASP**: A02:2021 (2017 A3) / **Priority**: High / **Gap**: NEW
- **Preconditions**
  - 가짜 `~/.claude.json`:
    `{"mcpServers": {"gh": {"command": "node", "args": ["s.js"], "env": {"GITHUB_TOKEN": "ghp_LIVEKEY0000000000000000000000000000", "DEBUG": "1"}}}}`
  - `capsys` 로 stdout 캡처
- **Input**: `axt.main(["mcp", "list"])`
- **Expected Output**
  - 반환값 `0`
  - stdout 에 `"ghp_LIVEKEY0000000000000000000000000000"` 부분 문자열이 **없다**
  - 서버 이름 `gh` 는 나타난다(기능 회귀 방지 대조)

### TC-SEC-026 — `mcp info` 가 env 값을 마스킹한다

- **US**: US-MCP05 AC2 / **OWASP**: A02 / **Priority**: High / **Gap**: NEW / **실패 예상**
- **Input**: `axt.main(["mcp", "info", "gh"])`
- **Expected Output**
  - 반환값 `0`
  - stdout 에 원문 토큰이 없다
  - 키 이름 `GITHUB_TOKEN` 은 있다 (무엇이 설정됐는지 진단 가능해야 함)
  - `DEBUG` 처럼 비밀이 아닌 값도 동일 규칙으로 마스킹해도 무방하다 —
    단언은 "원문 토큰 부재"이지 "특정 마스킹 형식"이 아니다
- **현재 구현 예상 결과**: `print(f"Env: {json.dumps(server.env_dict)}")` 로 평문 출력. **실패 예상.**
- **실패 시 조치**: `env` 값을 마스킹하는 헬퍼를 core에 두고 CLI·TUI 양쪽이 공유하게 한다.

### TC-SEC-027 — TUI MCP detail 패널이 env 값을 마스킹한다

- **US**: US-MCP05 AC3 / **OWASP**: A02 / **Priority**: High / **Gap**: NEW / **실패 예상**
- **Preconditions**: fake stdscr(`_make_stdscr(rows=40, cols=160)`), MCP 서브탭 선택, 위 서버가 첫 행
- **Steps**
  1. MCP 서브탭 렌더 호출
  2. `scr.calls` 의 3번째 인자(문자열)를 모두 이어붙여 `flat` 생성
- **Expected Output**
  - `"ghp_LIVEKEY0000000000000000000000000000" not in flat`
  - `"GITHUB_TOKEN" in flat`
- **왜 별도 TC인가**: CLI와 TUI가 서로 다른 함수(`cli_mcp_info` / `_mcp_detail_fields`)에서 env를 포맷한다.
  한쪽만 고치면 나머지가 계속 샌다 — 화면 공유 중 사고는 대개 TUI 쪽에서 난다.

---

## SC-SEC-010 — 원자적 쓰기 권한·동시성

### TC-SEC-028 — `write_json_atomic` 이 0600 파일의 퍼미션을 유지한다

- **US**: US-SYS04 AC1 / **OWASP**: A05:2021 Security Misconfiguration / **Priority**: Critical / **Gap**: NEW / **실패 예상**
- **Preconditions**
  - POSIX 전용
  - `target = tmp_path/"claude.json"` 생성 후 `os.chmod(target, 0o600)`
  - `os.umask` 은 건드리지 않는다 — 기본 umask 에서도 통과해야 하는 것이 요구사항이다
- **Input**: `axt.write_json_atomic(target, {"oauthAccount": {"accessToken": "secret"}})`
- **Steps**
  1. 호출
  2. `stat.S_IMODE(target.stat().st_mode)` 확인
  3. `.bak` 파일 퍼미션도 확인
- **Expected Output**
  - `0o600` 유지
  - `.bak` 도 `0o600` 이하 (백업이 원본보다 넓으면 백업 자체가 유출 경로)
- **현재 구현 예상 결과**: tmp 파일이 기본 umask(대개 `0o644`)로 만들어지고 `os.replace` 가 그 퍼미션을 그대로
  옮기므로 **0644 로 넓어진다**. `.bak` 도 `write_bytes` 로 0644. **실패 예상.**
- **실패 시 조치**: 쓰기 전 원본의 `st_mode` 를 읽어 두고 `os.replace` 직전에 `os.chmod(tmp, mode)` 를 적용.
  원본이 없을 때만 기본값 사용.

### TC-SEC-029 — 두 스레드 동시 쓰기 후에도 파일이 항상 유효한 JSON이다

- **US**: US-SYS04 AC3 / **OWASP**: 해당 없음 (동시성 무결성은 OWASP 항목이 아님) / **Priority**: High / **Gap**: **PARTIAL**
- **PARTIAL 사유**: `tests/test_json_io.py` 가 단일 writer 의 원자성·`.bak`·tmp 잔여물을 덮지만
  **경합**은 전혀 검증하지 않는다. axt는 TUI에서 3개 데몬 스레드가 동시에 캐시를 쓴다(§Load 참조).
- **Preconditions**
  - `threading.Barrier(2)` 로 시작 시점 정렬, 반복 50회
  - 두 writer 는 크기가 크게 다른 페이로드를 쓴다(부분 쓰기가 있으면 파싱이 깨지도록):
    A = `{"who": "A", "pad": "a"*10}` / B = `{"who": "B", "pad": "b"*20000}`
  - 전부 `tmp_path` 안. 실HOME·실 캐시 경로 금지
- **Steps**
  1. 매 회 두 스레드를 동시에 출발시켜 같은 경로에 쓴다
  2. 두 스레드 join 후 `json.loads(target.read_text())` 시도
  3. `who` 가 `"A"` 또는 `"B"` 이고 `pad` 길이가 그 값과 **정합**한지 확인
- **Expected Output**
  - 50회 모두 파싱 성공 (`json.JSONDecodeError` 0건)
  - `who=="A"` 이면 `len(pad)==10`, `who=="B"` 이면 `len(pad)==20000` — 두 writer 내용이 섞이지 않는다
  - 종료 후 `tmp_path` 에 `.tmp-*.json` 잔여물 0개
- **왜 단순 위임이 아닌가**: `os.replace` 의 원자성 자체는 OS 보장이지만, axt는 replace **전에** `.bak` 복사와
  `mkdir` 을 한다. 그 사이에 다른 writer 가 끼면 `.bak` 이 반쪽 내용이 되거나 tmp가 서로 지워질 수 있다.
  검증 대상은 OS가 아니라 axt의 전후 처리 순서다.
