# Chaos 테스트 시나리오

## 이 도구에서 "결함 주입"이란

axt에는 마이크로서비스도 회로 차단기도 데이터베이스 페일오버도 없다.
Chaos Monkey·Litmus·Gremlin 은 적용 대상이 아니다. axt가 실제로 마주치는 결함은
**남이 만든 파일과 남이 만든 프로세스**다.

| 결함 원천 | 구체적 형태 |
|---|---|
| 손상된 데이터 | 다른 도구가 반쯤 쓰고 죽인 JSON, 잘린 캐시, 깨진 심볼릭 링크 |
| 없는 것 | `~/.claude` 자체 부재, `git`/`claude` 바이너리 부재, 사라진 링크 대상 |
| 거부된 것 | 권한 없는 파일, 읽기 전용 파일시스템, 디스크 가득 참 |
| 실패하는 외부 | 네트워크 없음, non-fast-forward, 원격 삭제됨 |
| 죽는 내부 | 백그라운드 데몬 스레드에서 튀는 예외, 렌더 중 SIGWINCH |

**공통 성공 기준**: 한 항목의 결함이 **나머지 전체를 못 쓰게 만들지 않는다.**
이것이 `US-SYS05` AC4("권한 거부는 해당 항목만 실패로 처리하고 나머지를 계속 처리한다")의 정신이며,
이 도메인의 모든 시나리오는 결국 이 한 문장을 여러 각도에서 검증한다.

- 스펙 출처: `US-SYS05`(손상 데이터 내성), `US-SYS06`(외부 명령 실패), `US-SYS04`(원자적 쓰기),
  `US-VLT01` AC2(broken symlink 미삭제), `US-MKT02` AC4 / `US-MKT05`(git 실패), `US-UPD05` AC4(스레드 실패),
  `US-UPD02` AC2(claude 위임), `US-TUI10`(리사이즈), `FEATURES.md` §3.2 / §7.1 / §7.2
- Layer Owner: `tests/test_chaos.py` (`TEST_DEDUP_POLICY.md` §2 — 결함 주입 후 복원력)

## 결정성 규칙

- 권한 결함은 `os.chmod` 로 주입하되, **root 로 실행되면 chmod 가 무의미**하므로
  `os.getuid() == 0` 일 때 명시적으로 실패 처리한다(`skip` 이 아니라 환경 오류로 드러낸다)
- 디스크 가득 참은 실제로 재현할 수 없으므로 `json.dump` 가 `OSError(errno.ENOSPC)` 를 던지도록 주입한다
- 외부 명령 부재는 `subprocess.run` 이 `FileNotFoundError` 를 던지게 주입한다. PATH 를 건드리지 않는다
- 스레드 결함 주입 후에는 `join(timeout=5)` 으로 회수하고 살아 있으면 실패로 처리한다
- 모든 픽스처는 `tmp_path` 안. 실제 `~/.claude` 를 손상시키는 TC는 0건이어야 한다

---

## SC-CHAOS-001 — 손상된 JSON 5종이 각각 fallback으로 처리된다

- **Objective**: `US-SYS05` AC1 — `read_json(path, fallback=…)` 은 파싱 실패 시 fallback을 돌려준다.
  axt가 읽는 주요 JSON 5종 각각에 대해 이 계약이 성립해야 한다.
- **대상 파일과 기대 fallback**

  | 파일 | 읽는 함수 | 기대 fallback |
  |---|---|---|
  | `settings.json` | `read_enabled_plugins` | `{}` |
  | `installed_plugins.json` | `list_installed_plugins` | `[]` |
  | `known_marketplaces.json` | `list_marketplaces` | `[]` |
  | `.axt-profile.json` | `read_profile` | 빈 프로필 |
  | `cache/claude-usage.json` | `load_cached_usage` → `load_all_claude_usage` | 재빌드 |

- **Preconditions**
  - 손상 형태를 3가지로 나눠 각각 주입: (a) 잘린 JSON `{"a":`, (b) 빈 파일, (c) JSON이 아닌 텍스트
  - 전부 `tmp_path`. `axt.PATHS` 와 `AXT_CONFIG_DIR` 교체
- **Steps**: 각 파일 × 각 손상 형태에 대해 읽기 함수를 호출한다
- **Expected Result**
  - 예외 0건, 각각 표에 적힌 fallback 반환
  - 캐시는 폐기 후 재빌드되어 정상 엔트리를 돌려준다 (US-USG08 AC3)
  - 이후 같은 파일에 정상 쓰기가 가능하다(손상 파일이 쓰기를 막지 않는다)
- **Priority**: Critical

---

## SC-CHAOS-002 — 깨진 심볼릭 링크가 리포트되되 삭제되지 않는다

- **Objective**: `US-VLT01` AC2 + `US-SYS05` AC2 — 대상이 사라진 심볼릭 링크는 이동하지 않고
  `broken` 으로만 리포트하며 **삭제하지 않는다**. TUI는 `Warning: N broken symlink(s) not migrated` 를 표시한다.
- **Preconditions**
  - `~/.claude/skills/gone` → 존재하지 않는 경로를 가리키는 심볼릭 링크
  - `~/.claude/commands/gone.md` 도 동일하게 구성
  - 정상 항목 2개를 함께 두어 "나머지는 계속 처리된다"를 확인할 수 있게 한다
- **Steps**
  1. `migrate_to_vault(...)` 실행
  2. `find_broken_links(claude_dir)` 확인
  3. TUI Vault 빈 상태 렌더 확인
- **Expected Result**
  - 결과의 `broken` 에 2건, `moved` 에 정상 2건
  - 깨진 심볼릭 링크 파일이 **디스크에 그대로 존재**한다 (`Path.is_symlink()` 여전히 True)
  - 상태 메시지가 성공(초록)이 아니라 경고로 분류되고 `Warning:` 텍스트를 포함한다
  - Vault가 비고 broken 이 남아 있으면 빈 화면에 굵은 빨간 경고 줄이 추가된다
- **Priority**: High

---

## SC-CHAOS-003 — `~/.claude` 자체가 없어도 전 기능이 빈 상태로 동작한다

- **Objective**: `US-SYS05` AC3 — `~/.claude` 가 없어도 빈 상태로 동작한다.
  신규 설치 직후·다른 계정으로 실행·컨테이너 환경에서 실제로 발생한다.
- **Preconditions**
  - `HOME` 을 완전히 빈 `tmp_path` 로 지정. `~/.claude`, `~/.axt`, `~/.config/axt` 모두 없음
  - `CLAUDE_CONFIG_DIR` 미설정
- **Steps**
  - 읽기 계열 CLI를 전부 실행: `plugin list`, `skill list`, `mcp list`, `hook list`, `market list`,
    `vault list`, `usage today`, `context`, `project status`, `update`
- **Expected Result**
  - 모두 exit 0
  - stderr 에 traceback 이 없다
  - 각 출력에 "비어 있음 + 다음 행동 힌트" 가 있다 (US-TUI06 AC1 의 CLI 대응)
  - 읽기 명령이 **디렉터리를 만들지 않는다** — 조회가 부작용을 남기면 안 된다
    (`~/.config/axt/onboarded` 마커는 TUI 실행 시에만 생성되므로 예외)
- **Priority**: Critical

---

## SC-CHAOS-004 — 권한 거부가 해당 항목만 실패시킨다

- **Objective**: `US-SYS05` AC4 — 권한 거부는 해당 항목만 실패로 처리하고 나머지를 계속 처리한다.
- **Preconditions**
  - `os.getuid() == 0` 이면 chmod 가 무력하므로 **환경 오류로 실패 처리**한다(조용한 skip 금지)
  - 케이스 3종:
    - (a) vault 항목 디렉터리 하나를 `0o000` 으로 만든 상태에서 `list_vault_items`
    - (b) `.claude/skills` 중 한 파일을 `0o000` 으로 만든 상태에서 `collect_context_sources`
    - (c) 프로젝트 디렉터리 하나를 `0o000` 으로 만든 상태에서 `scan_project_usage`
  - teardown 에서 반드시 퍼미션을 복구해 `tmp_path` 정리가 실패하지 않게 한다
- **Steps**: 각 케이스를 실행하고 결과 건수와 예외 유무를 확인
- **Expected Result**
  - 예외 0건
  - 접근 불가 항목만 결과에서 빠지거나 오류로 표시되고, 나머지 항목은 정상 집계된다
  - 결과 건수가 "전체 - 1" 이다(0건으로 무너지지 않는다)
- **Priority**: Critical

---

## SC-CHAOS-005 — 쓰기 실패 시 원본이 손상되지 않는다

- **Objective**: `US-SYS04` AC3 — 쓰기 실패 시 원본이 손상되지 않는다.
  디스크 가득 참·읽기 전용 마운트·직렬화 불가 객체 모두 같은 계약을 따른다.
- **Preconditions**
  - 기존 파일에 알아볼 수 있는 내용(`{"keep": "original"}`)을 넣어 둔다
  - 실패 주입 3종:
    - (a) `json.dump` 가 `OSError(errno.ENOSPC, "No space left on device")` 를 던지게 monkeypatch
    - (b) `os.replace` 가 `OSError(errno.EROFS)` 를 던지게 monkeypatch
    - (c) 직렬화 불가 객체(`{"x": object()}`) 를 넘겨 `TypeError` 유발
- **Steps**: 각 실패 주입 상태에서 `write_json_atomic` 호출
- **Expected Result**
  - 예외가 호출자에게 전달된다(조용히 삼키지 않는다 — 쓰기 실패를 성공으로 보고하면 더 나쁘다)
  - **원본 파일 내용이 `{"keep": "original"}` 그대로**다
  - `.tmp-*.json` 잔여물이 없다 (`finally` 정리가 동작)
  - `.bak` 이 있다면 그 내용도 원본과 같다
- **Priority**: Critical

---

## SC-CHAOS-006 — `git` 바이너리가 없어도 안내로 끝난다

- **Objective**: `US-SYS06` AC2 — 명령 자체가 없어도(FileNotFoundError) 크래시하지 않는다.
  git 없는 컨테이너·최소 이미지에서 실제로 발생한다.
- **Preconditions**
  - `subprocess.run` 이 `FileNotFoundError("No such file or directory: 'git'")` 를 던지게 monkeypatch
  - 등록된 마켓 3개(github 2 + directory 1)
- **Steps**
  1. `market list` (버전 조회에 `git rev-parse` 필요)
  2. `market sync <name>`
  3. `update marketplace` (dry-run)
- **Expected Result**
  - 1: exit 0, 버전 컬럼이 `?` 등으로 표시되고 목록 출력 자체는 성공한다 (US-MKT03 AC2)
  - 2: exit 1 + stderr 에 사람이 읽을 수 있는 안내. traceback 없음
  - 3: 해당 항목만 확인 실패(`!`)로 표시되고 나머지 리포트는 완성된다
  - `directory` 소스 마켓은 git 이 필요 없으므로 **정상 처리**된다
- **Priority**: High

---

## SC-CHAOS-007 — git 실패(네트워크·non-fast-forward)가 작업트리를 건드리지 않는다

- **Objective**: `US-MKT02` AC4 + `US-MKT05` AC1/AC2 — git 실패는 크래시가 아니라 실패 보고로 처리하고,
  로컬 수정이 있는 저장소를 강제로 덮어쓰지 않는다.
- **Preconditions**
  - 실제 로컬 git 저장소 2개(origin ↔ clone)를 `tmp_path` 에 만든다. 네트워크 없음
  - clone 쪽에 커밋되지 않은 로컬 수정 파일 `local-work.txt` 를 둔다
  - 실패 주입 2종: (a) fetch 가 exit 128 + `Could not resolve host` stderr 를 내게 함,
    (b) origin 이 앞서 있어 non-fast-forward 상황을 만든 뒤 sync 시도
- **Steps**: 각 상황에서 `sync_marketplace(km, name)` 실행
- **Expected Result**
  - (a): 실패로 보고되고 stderr 내용이 사용자에게 전달된다. 작업트리 무변화
  - (b): 실패로 보고되고 **`local-work.txt` 내용이 그대로**다
  - 두 경우 모두 레지스트리(`known_marketplaces.json`)가 손상되지 않는다
- **Priority**: Critical
- **⚠ 결정 필요 — TC 작성 전에 사람이 판단해야 한다**
  현재 구현은 `git fetch` + `git reset --hard @{u}` 를 쓰고,
  `tests/test_marketplace.py::test_sync_marketplace_git_dirty_tree_hard_syncs` 가
  **그 파괴적 동작을 의도된 회귀 방지 사양으로 명시하고 있다**
  (근거: "Claude Code 자신의 업데이터가 커밋 없이 파일을 덮어써서 트리가 항상 dirty 이므로
  `pull --ff-only` 가 병합을 거부했다 — 그래서 v1.11.0 이 hard-sync 로 바꿨다, `tests/doc/SPEC_DECISIONS.md` SD-001).
  즉 스토리(US-MKT05 AC1)와 기존 테스트가 **정면으로 충돌**한다.
  이 충돌은 조사 후 `tests/doc/SPEC_DECISIONS.md` SD-001 로 해소됐다 (구현이 옳고 문서가 낡음). (b) 케이스는
  스토리를 고칠지 구현을 고칠지 결정된 뒤에 TC를 확정한다. 자세한 내용은 `## 스펙 갭` G-CHAOS-4 참조.

---

## SC-CHAOS-008 — `claude` 바이너리가 없을 때 위임이 우아하게 실패한다

- **Objective**: `US-UPD02` AC2 + `US-SYS06` AC2 — Claude Code 바이너리는 명시 타깃팅했을 때만
  `claude update` 에 위임한다. 바이너리가 없으면 안내로 끝난다.
- **Preconditions**
  - `subprocess.run(["claude", …])` 만 `FileNotFoundError` 를 던지게 주입(다른 명령은 정상)
  - `--json` 경로도 함께 확인 (US-UPD03 AC1 — 프롬프트 없이 non-interactive)
- **Steps**
  1. `axt update` (전체 dry-run)
  2. `axt update claude-code --apply -y`
  3. `axt update --json`
- **Expected Result**
  - 1: `claude-code` 항목이 `error="claude not found on PATH"` 취지로 리포트되고, 다른 티어 리포트는 완성된다
  - 2: exit 1 + 설치 안내. traceback 없음
  - 3: 출력이 유효한 JSON이며 `claude-code` 항목의 상태가 기계 판독 가능하다
  - 어떤 경우에도 Tier-1 항목의 처리가 중단되지 않는다 (US-UPD06 AC2)
- **Priority**: High

---

## SC-CHAOS-009 — 백그라운드 스레드가 예외를 던져도 TUI가 살아남는다

- **Objective**: `US-UPD05` AC4 — 스레드 실패가 TUI를 죽이지 않는다.
  세 워커(vault scan · usage load · update check) 각각에 대해 성립해야 한다.
- **Preconditions**
  - 각 워커의 작업 함수가 `RuntimeError("injected")` 를 던지게 monkeypatch
  - 실제 `threading.Thread` 사용. `join(timeout=5)` 으로 회수
  - `threading.excepthook` 을 임시로 가로채 스레드에서 새어나온 예외를 기록한다
    (기본 훅은 stderr 에만 찍고 테스트를 통과시켜 버린다 — 허위 양성 방지)
- **Steps**: 세 워커를 각각 kick 하고 join 후 상태를 확인, 이어서 `_render_frame` 을 호출
- **Expected Result**
  - 세 경우 모두 로딩 플래그가 False 로 복구된다(무한 폴링 방지)
  - `_render_frame` 이 예외 없이 성공한다
  - update check 실패는 `Upd` 컬럼에 `!` 또는 `…`→해소된 형태로 **사용자에게 드러난다** — 조용히 사라지지 않는다
  - vault scan / usage load 실패도 상태바나 컬럼으로 드러난다
- **Priority**: Critical
- **비고**: `_update_check_worker` 만 `except Exception` 을 갖고, `_kick_vault_scan` / `_kick_usage_reload` 의
  워커는 `try/finally` 만 갖는다. 후자는 예외가 스레드 밖으로 새어 `threading.excepthook` 으로 간다.
  프로세스는 살지만 **실패가 사용자에게 보이지 않는다**. 이 시나리오는 그 차이를 드러낸다.

---

## SC-CHAOS-010 — 렌더 도중 리사이즈가 다음 프레임을 깨뜨리지 않는다

- **Objective**: `US-TUI10` AC1/AC2 — 창이 좁거나 리사이즈돼도 레이아웃이 무너지지 않는다.
  curses 는 `KEY_RESIZE` 로 알리며, 그 시점에 `getmaxyx()` 가 바뀐다.
- **Preconditions**
  - fake stdscr 의 `getmaxyx()` 가 호출마다 다른 값을 돌려주도록 구성(리사이즈 중간 상태 재현)
  - 리사이즈 시퀀스: `(30,140) → (10,40) → (4,20) → (30,140)`
  - Skills 서브탭 200행, 선택 인덱스 150 (뷰포트 밖 재계산 강제)
- **Steps**
  1. 각 크기에서 `_render_frame` 호출
  2. `KEY_RESIZE` 입력이 모달 상태(`/` 검색 입력 중)에서도 처리되는지 확인
  3. 마지막에 원래 크기로 복귀해 렌더
- **Expected Result**
  - 모든 단계에서 예외 0건
  - `(4,20)` 단계는 안내 문구만 표시된다
  - 복귀 단계에서 선택 인덱스가 여전히 150이고 화면 안에 보인다(스크롤 오프셋 재계산)
  - 모달 상태에서도 `KEY_RESIZE` 가 재렌더로 처리되고 **검색 입력 버퍼가 보존**된다
- **Priority**: High

---

## 스펙 갭

| # | 관측 | 관련 US | 판단 |
|---|---|---|---|
| G-CHAOS-1 | `read_json` 이 `json.JSONDecodeError` 를 잡지 않는다. `fallback` 은 **파일 부재**에만 적용된다 | US-SYS05 AC1 | **구현 갭**. AC1 은 "파싱 실패 시 fallback" 이라고 명시한다. CLI 는 `ValueError` 를 잡아 exit 1 로 끝나지만, TUI `_ensure_subtab_loaded` 는 감싸지 않아 **대시보드가 죽는다**. SC-CHAOS-001 이 이를 드러낸다 |
| G-CHAOS-2 | TUI 메인 루프에 렌더 예외를 감싸는 곳이 없다 | US-SYS05 | **구현 갭**. 한 서브탭의 손상 데이터가 전체 TUI를 종료시킨다. "한 파일 문제로 도구 전체를 못 쓰는 일이 없다"는 US-SYS05 의 So-that 과 정면으로 어긋난다 |
| G-CHAOS-3 | `_kick_vault_scan` / `_kick_usage_reload` 워커에 `except` 가 없다 | US-UPD05 AC4 | **구현 갭**. 프로세스는 살지만 실패가 사용자에게 보이지 않는다. `_update_check_worker` 와 처리 수준이 불일치 |
| G-CHAOS-4 | `sync_marketplace` 가 `git reset --hard @{u}` 로 로컬 수정을 파괴한다 | US-MKT05 AC1 | **해소됨 — `tests/doc/SPEC_DECISIONS.md` SD-001.** 구현(hard-sync)이 옳고 낡은 `FEATURES.md` §3.5 가 틀렸다. 설치 디렉터리는 사용자 작업 공간이 아니라 관리 대상 캐시이며, 커밋되지 않은 로컬 수정은 Claude Code 업데이터 산출물로 간주해 폐기된다. 문서·유저스토리를 정정했고 구현은 변경하지 않았다. |
| G-CHAOS-5 | 디스크 가득 참 / 읽기 전용 파일시스템에 대한 스토리 AC 가 없다 | US-SYS04 AC3 | **문서 갭**. AC3("쓰기 실패 시 원본이 손상되지 않는다")로 커버되는 것으로 해석했다 |
| G-CHAOS-6 | 읽기 명령이 디렉터리를 만드는지에 대한 규정이 없다 | US-SYS05 AC3 | **문서 갭**. SC-CHAOS-003 은 "조회는 부작용 없음"을 기대값으로 삼았다. 구현이 다르면 스토리에 AC 를 추가해 확정해야 한다 |
