# axt 기능 인벤토리

본 문서는 axt가 제공하는 기능을 정리한 자료다. CLI 명령 / TUI 탭 / core 도메인 / usage·pricing·context 흐름을 한눈에 보기 위한 참조용으로 사용한다.

> **v1.0.0: Claude-only.** 이전 multi-platform (v0.2.x) 지원은 제거되었다. 사용량 / 비용 / 플랜 / 컨텍스트 분석은 모두 Claude 한정.

집계 결과:
- **CLI 명령**: 11개 그룹 × 총 40개 서브명령 (`tui` 포함)
- **TUI 탭**: 4개 메인 + Extensions 8개 서브탭 + Scope 글로벌 필터
- **Usage 플랫폼**: Claude 단일 → `UnifiedUsageEntry` 어댑터 → 모델별 pricing

---

## 1. CLI 명령

`axt --help` 가 sources of truth. 변경 시 본 문서를 함께 업데이트할 것.

### 1.1 `axt` (no args) / `axt tui`
TUI 대시보드 실행.

### 1.2 `axt context` (1)
세션 시작 컨텍스트 사용량 분석.
- 옵션: `--detail`, `--json`, `--category <name>`, `--model <id>`
- 출력: 카테고리별 토큰/비용 표 또는 JSON

### 1.3 `axt market` (4)
| 서브명령 | 인자 | 설명 |
|---|---|---|
| `list` | — | 등록된 마켓플레이스 + 버전 표 |
| `add <source>` | `github:user/repo` / `git:url` / `dir:path` | 마켓플레이스 등록 |
| `sync [name]` | 선택적 이름 | 단일 또는 전체 원격 동기화 |
| `remove <name>` | 이름 | 등록 해제 + 설치 dir 삭제(소유 시) |

### 1.4 `axt mcp` (4)
| 서브명령 | 인자 | 설명 |
|---|---|---|
| `list` | — | 활성 플러그인의 MCP 서버 표 |
| `info <name>` | 이름 | command/args/env 상세 |
| `enable <name>` | 이름 | 현재 프로젝트의 `disabledMcpServers`에서 제거 |
| `disable <name>` | 이름 | 현재 프로젝트의 `disabledMcpServers`에 추가 (Claude Code 재시작 필요) |

### 1.4b `axt hook` (3)
| 서브명령 | 인자 | 설명 |
|---|---|---|
| `list` | — | 훅 표 (토글용 인덱스 + `[off]` 표시) |
| `enable <index>` | `hook list` 인덱스 | `disabledHooks` → `hooks` 복원 |
| `disable <index>` | `hook list` 인덱스 | `hooks` → 같은 파일의 `disabledHooks`로 이동. plugin 훅은 거부 |

### 1.5 `axt plan` (2)
| 서브명령 | 인자 | 설명 |
|---|---|---|
| `overview` (기본) | — | Claude 플랜·예측 요약 |
| `set <plan_name>` | 플랜명 | Claude 플랜 변경 |

### 1.6 `axt plugin` (6)
| 서브명령 | 인자 | 설명 |
|---|---|---|
| `list` | — | 설치된 플러그인 + 활성 상태 |
| `enable <id>` | id | 활성화 (Claude Code 재시작 필요) |
| `disable <id>` | id | 비활성화 |
| `info <id>` | id | 상세 (version, marketplace, path, dates) |
| `remove <id>` | id | 설치 dir 삭제 + 설정 제거 |
| `search <query>` | 검색어 | 마켓플레이스 검색 |

### 1.7 `axt project` (5)
| 서브명령 | 인자 | 설명 |
|---|---|---|
| `init` | — | `.axt-profile.json` 빈 프로필 생성 |
| `add <type> <names...>` | skill/command/agent + 이름들 | vault → project symlink |
| `remove <type> <name>` | 타입 + 이름 | symlink 제거 |
| `sync` | — | profile ↔ symlink 동기화 |
| `status` | — | profile vs 실제 symlink 비교 |

### 1.8 `axt skill` (3)
| 서브명령 | 인자 | 설명 |
|---|---|---|
| `list` | — | 독립형 스킬 표 |
| `link <path>` | 경로 + `-n/--name` | 디렉터리 symlink (Windows 미지원) |
| `unlink <name>` | 이름 | symlink 제거 |

### 1.9 `axt usage` (5)
공통 옵션: `--since YYYY-MM-DD`, `--until YYYY-MM-DD`, `--model <name>`, `--project <name>`, `--breakdown`, `--timezone <tz>`, `--locale <loc>`, `--json`, `--csv`, `--export <path>`.

| 서브명령 | 설명 |
|---|---|
| `today` (기본) | 오늘 요약 (sessions/models/tokens/cost) |
| `week` | 주간 일별 분석 |
| `month` | 월간 누적 (예산 바 포함) |
| `blocks` | 5h 빌링 블록 (옵션 `--active`) |
| `session <id>` | 세션 prefix 매칭 상세 |

### 1.10 `axt vault` (6)
| 서브명령 | 인자 | 설명 |
|---|---|---|
| `list` | — | vault의 모든 확장 표 |
| `migrate` | — | `~/.claude/skills,commands,agents` → vault 이동 |
| `add <path>` | 경로 + `-t/--type` | vault 추가 (파일/디렉터리 복사) |
| `install <marketplace> <name>` | 마켓 + 이름 + `-t/--type` (기본 `skill`) | 마켓→vault 직접 설치 |
| `link-global <type> <name>` | 타입 + 이름 | `~/.claude/{type}s/`에 symlink |
| `unlink-global <type> <name>` | 타입 + 이름 | symlink 제거 |

### 1.11 글로벌 옵션
- `--help, -h` / `--version, -V` / `--json` (지원 명령에 한해)

---

## 2. TUI

### 2.1 메인 탭 (3개)
1. **Extensions** (Ext) — 1
2. **Context** (Ctx) — 2
3. **Usage** (Use) — 3

### 2.2 글로벌 필터 (헤더 칩)
- **Scope**: `Project` / `All` — 키 `P`
  - `Project` 일 때 Context 탭에 프로젝트 파일 패널이 함께 표시됨.

(v0.2.x의 Platform 필터는 v1.0.0에서 Claude 전용이 되면서 제거됨.)

### 2.3 Focus Layer (3단계)
`mainTab` ↔ `subTab` ↔ `content`. 메인탭은 `← →` 또는 숫자 1~3, 포커스 이동은 `↑ ↓ Return`.
포커스 가능한 본문이 없는 탭(Usage)은 mainTab에서 `↓`를 받아도 포커스가 그대로 mainTab에 머무름 — capability 기반 분기.

### 2.4 Extensions 탭 (8개 서브탭)
- **Vault** (기본) — `# Name Type Vault Added Updated Project Global Used in`
- **Plugins** — `Plugin Version Status Scope Marketplace Updated`
- **Skills** — `Skill Source Type Proj Path`
- **Commands** — `Command Source Proj Description`
- **Agents** — `Agent Source Proj Description`
- **MCP** — MCP 서버 / command / args / env
- **Hooks** — `Event Type Source Match Detail`
- **Market** — `Marketplace Version Updated Source`

### 2.5 키바인딩 (Vault 전체)
```
j/k ↓/↑     이동             g           global 토글
PgUp/PgDn   페이지           Tab         필터(all/skill/command/agent/plugin)
Space       project 토글     s           정렬 순환(컬럼순→added→updated), 활성 컬럼 헤더 ▲/▼
Enter       적용 또는 detail i           import to vault (global-only)
Esc         폐기/뒤로        f           scan mode toggle (default/full)
/           검색             m           migrate (글로벌→vault)
o           터미널 열기       S           sync project
U           모든 프로젝트에서 unlink (스캔 인덱스 기준, 확인 모달)
```

### 2.6 키바인딩 (서브탭별 고유)
- **공통(모든 서브탭)**: `o` 포커스된 항목의 저장 경로에서 새 터미널 열기 (cst 방식 — TERM_PROGRAM 매칭, cmux 안에서는 workspace/window 선택 모달)
- **공통(모든 서브탭)**: `s` 정렬 순환 (Vault와 동일 방식 — 활성 정렬 컬럼 헤더에 ▲/▼ 표시, 상태바에 `s:sort(<key>)` 노출). 서브탭별 순환 키:
  - **Plugins**: Name→Version→Marketplace
  - **Skills**: Name→Source→Type
  - **Commands** / **Agents**: Name→Source
  - **MCP**: Name→Scope→Transport
  - **Hooks**: Event→Type→Source
  - **Market**: Name→Source→Updated
- **Skills**: `u` unlink, `l` link (path 입력)
- **MCP**: `e` enable, `d` disable (현재 프로젝트 `disabledMcpServers`)
- **Hooks**: `e` enable, `d` disable (설정 파일 내 `hooks`↔`disabledHooks` 이동, plugin 훅 제외), `p` preview (dry-run)
- **Plugins**: `/` 필터, `i` install wizard, detail mode action list
- **Market**: `S` sync (대문자 — `s`는 정렬로 이동), `r` remove, `a` add (2-step name→source)
- **모든 서브탭 (Vault / Skills / Commands / Agents / MCP / Hooks / Plugins / Market)**: 리스트 하단에 detail panel 표시 (선택 항목 상세). `Tab` 패널 포커스 → `j/k`·`PgUp/PgDn` 스크롤 → `Tab` 다시 누르면 리스트로 복귀

### 2.7 Context 탭 모드
컨텍스트 윈도우 분석 (`categories → sources → preview`) + 5h/7d 쿼터 바 + cost impact 라인.
키: `j/k`, `Enter` (카테고리 소스 모달), `e` (첫 소스를 에디터로), `r` (새로고침).
**Scope=Project** 일 때 하단에 "Project files" 패널이 함께 표시됨 (CLAUDE.md / settings.json / memory 등 cwd 기준 컨텍스트 파일 목록).

### 2.8 Usage 탭
Plan 라벨 + 월간 예산 progress bar + Today/Week/Month 카드 + 14일 BarChart + Active Block + Insights(large-context %, parallel %, top model) + plan rate-limit(5h/7d) 라인. 키: `r` 새로고침. (v0.2.x의 platform/cursor 서브탭은 제거. 별도였던 Dashboard 탭은 이 탭의 상단(Plan/Budget 블록)으로 흡수됨.)

### 2.10 공통 위젯
- **Table**: prefix 4셀(`▸/space + ■/□` 또는 `▸/space + 번호`), 마지막 컬럼 자동 확장, selected는 cyan+bold (inverse 회피)
- **DetailPanel**: rich(컬러 보존) ↔ flat scroll(overflow 시) 2경로, focused → cyan border
- **PreviewPanel**: 라인 번호 3자리, 노란 더블 보더, `[start-end/total]` 인디케이터
- **Confirm**: `y/Y/n/N/q` + 더블 보더
- **BarChart**: 8셀 label + `█` cyan bar + dim value
- **SearchInput**: in-place input row
- **HelpPopup**: `?/q/Esc/Return`으로 닫기
- **TabBar**: 3 메인 탭 가로 배치, active inverse + focus 표시 (`▶` 마커)
- **FilterChips**: `Scope: [...]` 헤더 라인 좌측, 디폴트 외 값은 BOLD

### 2.11 글로벌 키
- `q` / `Esc`: 종료 (특정 탭의 subview 중에는 차단)
- `?`: HelpPopup 토글
- `r`: refresh
- `1-3`: 메인탭 점프
- `← →`: 메인탭 순회

---

## 3. core 도메인

### 3.1 paths (Section 1)
- 환경변수: `CLAUDE_CONFIG_DIR`
- Windows: `%APPDATA%` 대체 경로
- `Paths`: claudeDir, settings, knownMarketplaces, installedPlugins, blocklist, pluginCache, marketplaces, skills, projects, statsCache, usageSnapshot, axtDir, vault, vaultSkills, vaultCommands, vaultAgents
- `AXT_CONFIG_DIR`, `AXT_CONFIG_PATH` (XDG_CONFIG_HOME/axt 또는 AppData)

### 3.2 json_io (Section 2)
- `read_json(path, fallback=None)` — 파싱 + fallback
- `write_json_atomic(path, data)` — tmpfile + os.replace + .bak 백업

### 3.3 settings (Section 3, 단일 스코프, 호출자가 병합)
- `read_enabled_plugins`, `set_plugin_enabled`, `remove_plugin_from_settings`
- `read_favorite_plugins`, `set_plugin_favorite`
- `read_marked_for_update`, `set_marked_for_update`
- `read_extra_marketplaces`
- 우선순위: project local > project > global

### 3.4 vault (Section 5, 가장 큰 도메인)
- 타입: `ExtensionType`, `VaultItem`, `AxtProfile`, `SyncResult`, `MigrateResult`, `PluginRef`
- `parse_yaml_description(frontmatter)` — double/single quote, 블록 스칼라(`|`, `>`), CRLF 처리
- `list_vault_items`, `list_vault_items_with_project_state`
- `read_profile`, `write_profile` (`.axt-profile.json`)
- `link_to_project`, `unlink_from_project`, `sync_project`
- `link_to_global`, `unlink_from_global`
- `import_to_vault`, `migrate_to_vault`
- **Windows 미지원**: symlink 생성 fail-safe 메시지

### 3.5 marketplace (Section 5)
- 타입: `MarketplaceSource` (github/git/directory union), `MarketplaceInfo`, `SyncResult`, `VersionInfo`
- `parse_marketplace_source`, `list_marketplaces`, `add_marketplace`, `remove_marketplace`, `sync_marketplace`
- 버전: `get_local_version`, `get_marketplace_version`, `read_sha_file`, `download_and_extract_tarball`
- 외부: `git clone --depth 1`, `git pull --ff-only`, `git fetch`, `git rev-parse`, `tar xzf`
- 데이터: `known_marketplaces.json`, `.gcs-sha` (GitHub SHA)

### 3.6 plugin (Section 4)
- 타입: `PluginInfo` (id, name, marketplace, version, installPath, scope, installedAt, lastUpdated, …)
- `list_installed_plugins`, `get_plugin_info`, `add_installed_plugin`, `remove_installed_plugin`, `update_plugin`, `find_plugin_source_dir`
- 데이터: `installed_plugins.json` (`{version: 2, plugins: {[id]: [{scope, installPath, version, …}]}}`)
- manifest: `.claude-plugin/plugin.json` 또는 `plugin.json`

### 3.7 skill (Section 4)
- 타입: `SkillSource = "user"|"project"|"plugin"`, `SkillInfo`
- `list_skills`, `list_all_skills` (user + project + 활성 플러그인)
- `is_symlink_supported` (Windows false)
- `link_skill`, `unlink_skill` (Windows fail-safe)

### 3.8 mcp (Section 4)
- 타입: `McpServerInfo` (name, pluginId, command, args, env, disabled)
- `list_mcp_servers(installed_plugins)` — plugin.json에서 mcpServers 추출
- `collect_mcp_servers(...)` — plugin + user/project/.mcp.json + claude.ai 커넥터(`claudeAiMcpEverConnected`, scope `claude.ai`) + built-in(`BUILTIN_MCP_SERVERS`, scope `built-in`) 병합. opt-out 소스는 `disabledMcpServers`, built-in은 opt-in(`enabledMcpServers`) 반영
- `set_mcp_disabled(name, disabled=...)` — `~/.claude.json` `projects[<dir>]` 토글 (프로젝트 단위). built-in은 `enabledMcpServers`, 그 외는 `disabledMcpServers`

### 3.9 commands / agents (Section 4)
- 타입: `CommandSource | AgentSource = "user"|"project"|"plugin"`
- `list_commands`, `list_all_agents`
- `.md` frontmatter description 추출

### 3.10 hooks (Section 4)
- 타입: `HookType`, `HookSource = "user"|"project"|"local"|"plugin"`, `HookEntry`, `HookRule`, `HookInfo` (`disabled` 플래그 포함), `HookPreviewResult`
- `list_hooks` (4 소스 병합 + `disabledHooks` 미러 파싱), `preview_hook` (dry-run, `sh -c`), `get_hook_detail`
- `set_hook_disabled(settings_path, hook, disabled=...)` — 같은 설정 파일 내 `hooks`↔`disabledHooks` 단일 훅 이동. Claude Code는 `disabledHooks` 무시 → 무손실 토글. plugin 훅은 호출자가 거부
- 다수 이벤트 (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, …)

### 3.11 project_context (Section 9)
- 타입: `ProjectContextItem` (name, source, path, content, lines)
- `load_project_context(cwd)` — global/user/project CLAUDE.md + settings + memory 수집

### 3.12 project_usage (Section 9)
- 타입: `ProjectRef`, `ExtensionUsage`, `UsageIndex`
- `scan_project_usage(projects_dir, vault_dir, mode)` — `default` / `full`
- 경로 인코딩: `/` 및 `.` → `-`

### 3.13 usage / cache (Section 6)
- `UnifiedUsageEntry`: platform("claude"), model, timestamp, sessionId, projectPath, inputTokens, outputTokens, cacheWriteTokens, cacheReadTokens, reasoningTokens, toolTokens
- `RateLimitInfo`: platform, usedPercent, windowMinutes, resetsAt
- 캐싱: 파일 mtime 기반, `~/.config/axt/cache/claude-usage.json`, 기본 5분 TTL

---

## 4. Usage / Pricing / Context

### 4.1 Claude 데이터 포맷
- 파일: JSONL per session
- 경로: `~/.claude/projects/{proj}/{session}.jsonl`
- token 필드: `usage.{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}`
- rate limit: 별도 snapshot 파일 (`~/.axt-profile.json` 또는 외부 snapshot)
- 캐싱: mtime per-file

### 4.2 5시간 빌링 블록 (Claude)
- 윈도우 길이: 18,000,000ms (5h)
- UTC 정렬: 00:00, 05:00, 10:00, 15:00, 20:00 UTC
- 계산: `windowIndex = floor(msSinceMidnight / 18M)`
- `isActive = now < windowEnd`
- burn rate: 활성 블록의 tokens / elapsed_min

### 4.3 모델별 가격 (per 1M tokens, USD) — `pricing.json`
| Model | Input | Output | Cache Write | Cache Read | Context Window |
|---|---|---|---|---|---|
| claude-opus-4-7 / 4-6 | 15.00 | 75.00 | 18.75 | 1.50 | 1,000,000 |
| claude-sonnet-4-6 | 3.00 | 15.00 | 3.75 | 0.30 | 1,000,000 |
| claude-haiku-4-5 | 0.80 | 4.00 | 1.00 | 0.08 | 200,000 |

비용: `(input/1M)*Pin + (output/1M)*Pout + (cacheCreation/1M)*PcacheWrite + (cacheRead/1M)*PcacheRead`

신규 모델 추가: `pricing.json`만 수정 (코드 변경 불필요).

### 4.4 컨텍스트 분석 카테고리
1. **system-prompt** (4,200 tok fixed)
2. **claude-md** — global/user/project + `.claude/CLAUDE.md` 등
3. **settings** — 4곳 (global/project + local)
4. **memory** — `~/.claude/projects/{key}/memory/*.md` (200줄/25KB 제한)
5. **skills** — `SKILL.md` frontmatter name+description
6. **mcp-tools** — 활성 플러그인의 MCP 서버 (deferred 추정)
7. **plugins** — settings의 enabledPlugins (메타데이터)
8. **hooks** — SessionStart / UserPromptSubmit (200 tok/hook fixed)
9. **commands** — `.claude/commands/*.md`
10. **agents** — `.claude/agents/*.md`
11. **git-status** (150 tok fixed) — `git status` 출력
12. **user-context** (280 tok fixed) — email, date, paths, platform, shell

actionable 플래그로 사용자 조정 가능 여부 구분. hints: 90일 이상 미수정 memory, top-3 consumer skills 등.

### 4.5 Rate Limit
- Claude: `~/.axt-profile.json` 또는 외부 snapshot (`five_hour.used_percentage`, `seven_day.used_percentage`, `resets_at`, `updated_at`)
- 신선도: 기본 5분 tolerance

### 4.6 Usage Insights
`load_usage_insights({days: 1 | 7})`:
- planLimits (5h/7d %)
- subagentHeavyPct / largeContextPct (>150k input) / parallelSessionPct (3+ overlap)
- skillBreakdown / subagentBreakdown / pluginBreakdown — name + tokenPct
- 캐시: `~/.axt/cache/insights-{days}d.json` (5분 TTL)

---

## 5. Wizard / 보조 UI

- **InstallWizard**: search query → results
- **RemoveWizard**: Confirm → remove_installed_plugin + remove_plugin_from_settings + rm

---

## 6. 잡다한 상수

- `SOURCE_COLORS`: user=cyan, project=green, local=yellow, plugin=magenta
- `TUI_LOCALE = "en-US"` (config.locale 무시)
- 캐시 TTL: usage 5분, insights 5분
- `PLATFORMS = ("claude",)` — v2 단일 플랫폼 상수

---

## 7. 구현 시 주의 사항

1. **Windows symlink**: vault/skill의 link/unlink는 `os.symlink` 시도 후 `OSError` → 안내 메시지로 graceful degrade. tests에서 platform check.
2. **외부 명령**: git clone/pull/fetch/rev-parse, tar xzf, sh -c (hook preview), claude --version, git status — `subprocess.run` 사용. 실패 시 stderr 캡처.
3. **JSONL**: 큰 파일은 라인 단위 lazy read. mtime cache 필수.
4. **YAML frontmatter 파서**: robust 패턴으로 직접 구현. PyYAML 사용 안 함 (의존성 제로 원칙).
5. **timezone**: usage 집계는 사용자 timezone option, Claude 5h 블록은 UTC.
6. **HTTP (marketplace tarball)**: stdlib `urllib.request` + `tarfile` 사용.
7. **curses CJK width**: `unicodedata.east_asian_width()`로 사전 계산, `addnstr`에 wide 셀 폭 명시.
8. **profile lookup**: `~/.claude/projects/` 폴더명 인코딩(`/` 및 `.` → `-`) decode는 brute-force matching.
9. **pricing.json 분리**: 모델 가격 표를 코드 외부로 빼서 가격 변동 시 코드 수정 불필요.
