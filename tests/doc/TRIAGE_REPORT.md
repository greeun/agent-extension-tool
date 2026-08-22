# Phase E 트리아지 보고서

Phase D 전체 실행 결과: **1531개 중 1486 통과 / 45 실패**, 소요 16.2초.
`git stash` 로 원본 대비 확인 결과 **기존 1304개는 전부 통과 — 회귀 0건**.
45건은 전부 신규 테스트이며, 아래는 각 실패의 근본 원인 분류다.

분류 기준(스킬 Phase E): 테스트 기대값이 스펙과 일치하면 **구현이 틀린 것**(IMPL_BUG)이 기본 가정이다.

| 분류 | 건수 | 조치 |
|---|---:|---|
| IMPL_BUG — 보안 | 12 | **Phase F 수정** |
| IMPL_BUG — 명백한 결함 | 10 | **Phase F 수정** |
| DESIGN_DECISION — 설계 판단 필요 | 18 | 보고만. 사용자 결정 후 별건 |
| NOT_IMPLEMENTED — 미구현 기능 | 3 | 보고 + 문서 정정. 기능 추가는 별건 |
| TEST_ERROR — 테스트가 과함 | 2 | 테스트 수정 |

---

## A. IMPL_BUG — 보안 (12건, 수정 대상)

모두 **직접 재현 확인**했다. 원격 공격 벡터는 아니다 — 사용자가 해당 인자로 직접 실행해야 한다.
그러나 `-n`/`<name>` 은 설계상 **이름**이지 경로가 아니며, US-SYS08(파괴적 조작이 의도 범위를 넘지 않는다)의 직접 위반이다.

### A-1. 경로 탈출 — 쓰기
```
skill link <경로> -n "../../pwn"   → exit 0 "✓ Skill linked."  $HOME/pwn 에 심링크 생성
skill link <경로> -n "<절대경로>"   → exit 0                    임의 절대경로에 생성
```
`TC-SEC-001`, `TC-SEC-002`, `TC-SEC-005`

### A-2. 경로 탈출 — 삭제 (더 심각)
```
skill unlink "../../.my-config"    → exit 0 "✓ Skill ... unlinked."
                                      $HOME/.my-config 심링크가 실제로 삭제됨
market remove <installLocation 이 ../ 로 벗어난 항목>
                                   → exit 0  marketplaces/ 의 형제 디렉터리가 통째로 삭제됨
```
심링크만 지우고 대상 원본은 남으므로 파일 소실은 아니지만, 사용자의 다른 설정 링크가 조용히 사라진다.
`market remove` 는 디렉터리를 통째로 지운다.
`TC-SEC-006`, `TC-SEC-009`, `TC-SEC-011`, `TC-SEC-013`

### A-3. 민감정보 노출
`cli_mcp_info` 가 `print(f"Env: {json.dumps(server.env_dict)}")` 로 **토큰을 평문 출력**한다.
TUI detail 패널도 같다. MCP 서버 env 는 API 키를 담는 것이 일반적이며, 화면 공유·이슈 첨부에서 그대로 샌다.
`TC-SEC-026`, `TC-SEC-027`
> 주의: `FEATURES.md` §1.4 는 `mcp info` 가 "env 상세"를 보여준다고만 적고 마스킹을 요구하지 않는다.
> 즉 문서화된 스펙 위반이 아니라 **보안 개선**이다. 값만 가리고 키 이름은 남긴다(진단 가능성 유지).

### A-4. 기타
- tar 추출이 절대경로 멤버를 거부하지 않음 (`TC-SEC-020`, tarfile 경로 탈출 계열)
- `write_json_atomic` 이 기존 파일의 제한적 권한(0600)을 넓힘 (`TC-SEC-030`)
- `vault unlink-global <없는 이름>` 이 exit 0 + `✓` 로 성공 보고 (`TC-SEC-007`)

---

## B. IMPL_BUG — 명백한 결함 (10건, 수정 대상)

| # | 증상 | 스펙 |
|---|---|---|
| B-1 | `skill link <없는 경로>` 가 **깨진 심링크를 만들고** `exit 0 ✓ Skill linked.` | US-LNK02 AC3 |
| B-2 | `usage --since notadate` 를 **조용히 무시**하고 exit 0 → 엉뚱한 기간 리포트를 정답처럼 반환 | US-USG02 AC1 |
| B-3 | `usage --since > --until` 도 exit 0 + "No usage data" | US-USG02 AC2 |
| B-4 | `usage --since/--until` 가 **적용되지 않고** 기본 today 윈도우가 쓰임 | US-USG02 AC3 |
| B-5 | `vault add` 가 같은 이름 **파일**을 조용히 덮어씀 (디렉터리는 `copytree` 가 막음) | US-VLT03 AC4 |
| B-6 | `update <type> <없는 name>` 이 exit 0 + 빈 리포트 → CI가 "업데이트했다"고 통과 | US-UPD04 AC3 |
| B-7 | `migrate` 가 일부 스킬을 **심링크 없이** vault로 이동 → Claude Code가 못 찾음 | US-VLT01 AC1 |
| B-8 | 빈 Vault 화면이 `m`·`F` 를 누르라고 3곳에서 안내하지만 **포커스가 content 층에 못 내려가** 키가 도달하지 않음 | US-VLT01, US-TUI06 |
| B-9 | `i`(import) 후 Vault 목록이 갱신되지 않음 (`vault_items` stale) | US-LNK05 AC3 |
| B-10 | 제어문자(`\n`·`\t`·`\x01`)가 `addnstr` 에 그대로 도달 — 터미널 렌더 깨짐 | US-TUI10 |

B-8 이 특히 나쁘다. 빈 Vault 는 **첫 실행 사용자가 보는 화면**이고, 화면이 시키는 대로 눌렀는데 아무 일도 일어나지 않는다.

---

## C. DESIGN_DECISION — 설계 판단 필요 (18건, 보고만)

### C-1. 손상 JSON 처리 정책 (10건)
`read_json` docstring 이 *"Return `fallback` if **missing**"* 이라 **파일 부재만** 처리하고
파싱 실패는 그대로 전파한다. 그래서 설정 파일 하나가 깨지면 무관한 명령이 전부 죽는다:
```
plugin list / market list / skill list  →  exit 1  ✗ Expecting ',' delimiter: ...
```
`read_json_dict` 는 자기 docstring 에 *"corruption. Treat as empty rather than crash"* 라고 적어 두고도
가장 흔한 손상 형태(쓰다 만 파일)에서 그 약속을 지키지 못한다.

**단순 수정이 위험한 이유**: 파싱 실패에 fallback 을 주면 `_set_settings_flag` 같은
**읽고-고쳐-쓰는 경로**가 손상 파일을 `{}` 로 읽은 뒤 덮어써 **사용자의 실제 설정을 날릴 수 있다**.
(`write_json_atomic` 이 `.bak` 을 남기긴 한다.)

→ 올바른 답은 경로별로 다르다: **읽기 전용은 우아하게 degrade, 읽고-쓰기는 거부**.
   현재는 양쪽 다 거부하는 안전하지만 불친절한 상태다. 임의 변경하지 않는다.
관련: `TC-CHAOS-002~008`, `TC-UNIT-013`, `TC-SEC-016`, `TC-SEC-018`

### C-2. `actionable` 의 의미 (G-4, 1건)
US-CTX02 AC2 는 `mcp-tools` 를 조정 가능으로 보지만 구현은 `mcp-tools`·`plugins` 를 `actionable=False` 로 둔다.
axt 자신이 `mcp disable`·`plugin disable` 을 제공하므로 스펙 쪽이 맞아 보이나,
`actionable` 이 "Context 탭 안에서 바로 조작 가능"을 뜻한다면 구현이 맞다. **정의 확정이 먼저다.**

### C-3. 메인 탭 바 색맹 안전성 (1건)
`render_tab_bar` 는 활성 탭을 **curses 속성(색)으로만** 구분한다 — 그려지는 문자열은 동일하다.
반면 `_render_subtab_bar` 는 `[ Skills ]` 대괄호를 쓰고 코드에 *"brackets retained for color-blind safety"* 주석이 있다.
**같은 프로젝트 안에서 규약이 갈린다.** 메인 탭 바에도 대괄호를 주면 해소되나 UI 변경이라 판단을 올린다.

### C-4. 백그라운드 워커 실패 가시성 (2건)
vault scan / usage load / update check 워커가 죽어도 **화면에 흔적이 없다**.
사용자는 죽은 워커와 "결과가 비었음"을 구분할 수 없다. `Upd` 컬럼의 `!` 처럼 표면화하는 설계가 필요하다.

### C-5. 컨텍스트 수집 중복 읽기 (1건)
`collect_context_sources` 가 파일 200개를 **각각 2회** 읽는다. 정확성 문제는 아니나
컨텍스트 분석이 세션 시작마다 도는 경로라 개선 여지가 있다.

### C-6. 기타 (3건)
`vault install` 의 레지스트리 경유 소스 해석, v1 캐시 폐기 후 재사용, project 스코프 명시적 false 처리.

---

## D. NOT_IMPLEMENTED — 미구현 기능 (3건)

문서가 약속하지만 **코드에 존재하지 않는다**. 버그가 아니라 미구현이므로 기능 추가는 별건이다.
스킬 규칙(F-6)에 따라 스텁을 만들지 않고, 해당 테스트는 제거하며 문서를 정정한다.

| 기능 | 문서 | 구현 |
|---|---|---|
| `usage --export <path>` | FEATURES.md §1.9 공통 옵션에 명시 | argparse 에 **없음** (`SystemExit: 2`) |
| `usage --breakdown` | 동상 | 동상 |
| `settings.local.json` 의 `enabledPlugins` 우선순위 | FEATURES.md §3.3 "project local > project > global" | hooks·context 분석은 읽지만 **enabledPlugins 는 안 읽음** |

---

## E. TEST_ERROR — 테스트가 과함 (2건)

- `test_usage_export_writes_the_requested_file` / `test_usage_export_to_unwritable_path_exits_1`
  → 미구현 기능을 버그처럼 단언한다. D 항목으로 재분류하고 테스트를 제거한다.

---

## 조치 요약

| 단계 | 내용 |
|---|---|
| Phase F-1 | A(보안 12) + B(명백한 결함 10) 구현 수정 |
| Phase F-6 | D(미구현 3) 보고 + `FEATURES.md` 정정 + 해당 테스트 제거 |
| 보류 | C(설계 판단 18) — 사용자 결정 후 별건 |
