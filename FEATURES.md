# axt 기능 인벤토리 — Python 재작성 1:1 매핑 자료

본 문서는 기존 TypeScript+Ink axt가 제공하는 **모든 기능**을 빠짐없이 정리한 자료다.
axt-new(Python+curses) 재작성 시 1:1 이식 체크리스트로 사용한다.

집계 결과:
- **CLI 명령**: 10개 그룹 × 총 44개 서브명령
- **TUI 탭**: 8개 메인 + Extensions 7개 서브탭 + Claude 2개 서브탭
- **core 도메인 함수**: 11개 모듈, 약 80개 export 함수
- **usage 플랫폼**: 4개 (Claude/Codex/Gemini/Cursor) + Unified 어댑터 + 모델별 pricing 13개

---

## 1. CLI 명령 (44개 서브명령)

### 1.1 `axt` (no args) / `axt tui`
TUI 대시보드 실행. (`launchTui()` → ink render)

### 1.2 `axt context`
세션 시작 컨텍스트 사용량 분석.
- 옵션: `--detail`, `--json`, `--category <name>`, `--model <id>` (기본 `claude-opus-4-6`)
- 출력: 카테고리별 토큰/비용 표 또는 JSON
- core: `analyzeContext()`

### 1.3 `axt market` (4개)
| 서브명령 | 인자 | 설명 | core |
|---|---|---|---|
| `list` | — | 등록된 마켓플레이스 + 버전 표 | `listMarketplaces`, `getMarketplaceVersion` |
| `add <source>` | `github:user/repo` / `git:url` / `dir:path` | 마켓플레이스 등록 | `parseMarketplaceSource`, `addMarketplace` |
| `sync [name]` | 선택적 이름 | 단일 또는 전체 원격 동기화 | `syncMarketplace`, `pooledMap` |
| `remove <name>` | 이름 | 등록 해제 + 설치 dir 삭제(소유 시) | `removeMarketplace` |

### 1.4 `axt mcp` (2개)
| 서브명령 | 인자 | 설명 | core |
|---|---|---|---|
| `list` | — | 활성 플러그인의 MCP 서버 표 | `listMcpServers`, `readEnabledPlugins` |
| `info <name>` | 이름 | command/args/env 상세 | `listMcpServers` (필터) |

### 1.5 `axt plan` (2개)
| 서브명령 | 인자 | 설명 | core |
|---|---|---|---|
| `overview` (기본) | — | 플랫폼별 플랜·예측 요약 | `loadUnifiedUsage`, `computePlanUsage`, `getDaysInBillingPeriod` |
| `set <platform> <planName>` | claude/codex/gemini + 플랜명 | 플랜 변경 | `loadConfig`, `saveConfig` |

### 1.6 `axt plugin` (6개)
| 서브명령 | 인자 | 설명 | core |
|---|---|---|---|
| `list` | — | 설치된 플러그인 + 활성 상태 | `listInstalledPlugins`, `readEnabledPlugins` |
| `enable <id>` | id | 활성화 (Claude Code 재시작 필요) | `setPluginEnabled` |
| `disable <id>` | id | 비활성화 | `setPluginEnabled` |
| `info <id>` | id | 상세 (version, marketplace, path, dates) | `getPluginInfo` |
| `remove <id>` | id | 설치 dir 삭제 + 설정 제거 | `removeInstalledPlugin`, `removePluginFromSettings` |
| `search <query>` | 검색어 | 마켓플레이스 검색 (현재 안내만) | (미구현) |

### 1.7 `axt project` (5개)
| 서브명령 | 인자 | 설명 | core |
|---|---|---|---|
| `init` | — | `.axt-profile.json` 빈 프로필 생성 | `readProfile`, `writeProfile`, `emptyProfile` |
| `add <type> <names...>` | skill/command/agent + 이름들 | vault → project symlink | `listVaultItems`, `linkToProject` |
| `remove <type> <name>` | 타입 + 이름 | symlink 제거 | `unlinkFromProject` |
| `sync` | — | profile ↔ symlink 동기화 | `syncProject` |
| `status` | — | profile vs 실제 symlink 비교 | `readProfile` + `lstat` |

### 1.8 `axt skill` (3개)
| 서브명령 | 인자 | 설명 | core |
|---|---|---|---|
| `list` | — | 독립형 스킬 표 | `listSkills` |
| `link <path>` | 경로 + `-n/--name` | 디렉터리 symlink (Windows 미지원) | `linkSkill`, `isSymlinkSupported` |
| `unlink <name>` | 이름 | symlink 제거 | `unlinkSkill` |

### 1.9 `axt usage` (5개)
공통 옵션: `--since YYYYMMDD`, `--until YYYYMMDD`, `--model <name>`, `--project <name>`, `--breakdown`, `--timezone <tz>`, `--locale <loc>`, `--platform <name>` (기본 `all`), `--json`, `--csv`, `--export <path>`

| 서브명령 | 설명 | core |
|---|---|---|
| `today` (기본) | 오늘 요약 (sessions/models/tokens/cost) | `loadUnifiedUsage`, `aggregateDaily`, `calculateCost` |
| `week` | 주간 일별 분석 | 위 + 표 |
| `month` | 월간 누적 (예산 바 포함) | 위 |
| `blocks` | 5h 빌링 블록 (옵션 `--active`) | `computeBlocks` |
| `session <id>` | 세션 prefix 매칭 상세 | `aggregateBySession` |

### 1.10 `axt vault` (6개)
| 서브명령 | 인자 | 설명 | core |
|---|---|---|---|
| `list` | — | vault의 모든 확장 표 | `listVaultItems` |
| `migrate` | — | `~/.claude/skills,commands,agents` → vault 이동 | `migrateToVault` |
| `add <path>` | 경로 + `-t/--type` | vault 추가 (파일/디렉터리 복사) | `stat`, `cp` |
| `install <marketplace> <name>` | 마켓 + 이름 + `-t/--type` (기본 `skill`) | 마켓→vault 직접 설치 | `findPluginSourceDir`, `cp` |
| `link-global <type> <name>` | 타입 + 이름 | `~/.claude/{type}s/`에 symlink | `linkToGlobal` |
| `unlink-global <type> <name>` | 타입 + 이름 | symlink 제거 | `unlinkFromGlobal` |

### 1.11 글로벌 옵션 (commander 기본 + 일부)
- `--help, -h` / `--version, -V` / `--json` (지원 명령에 한해)

---

## 2. TUI (8 메인 탭 + 9 서브탭)

### 2.1 메인 탭 순서 (TabBar.tsx)
1. Extensions (Ext) — 1
2. Context (Ctx) — 2
3. Project (Prj) — 3
4. Dashboard (Dash) — 4
5. Claude (Cla) — 5
6. Codex (Cdx) — 6
7. Gemini (Gem) — 7
8. Cursor (Cur) — 8

### 2.2 Focus Layer (3단계)
`mainTab` ↔ `subTab` ↔ `content`. 메인탭은 `← →` 또는 숫자 1~8, 포커스 이동은 `↑ ↓ Return`.

### 2.3 Extensions 탭 (7개 서브탭)
- **Vault** (기본) — 표 컬럼: `# Name Type Vault Added Updated Project Global Used in`
- **Skills** — `Skill Source Type Proj Path`
- **Hooks** — `Event Type Source Match Detail`
- **Commands** — `Command Source Proj Description`
- **Agents** — `Agent Source Proj Description`
- **Plugins** — `Plugin Version Status Scope Marketplace Updated`
- **Marketplace** — `Marketplace Version Updated Source`

### 2.4 키바인딩 (Vault 전체)
```
j/k ↓/↑     이동             g           global 토글
PgUp/PgDn   페이지           Tab         필터(all/skill/command/agent/plugin)
Space       project 토글     s           정렬(name/type/vault/added/updated/project/global)
Enter       적용 또는 detail i           import to vault (global-only)
Esc         폐기/뒤로        f           scan mode toggle (default/full)
/           검색             m           migrate (글로벌→vault)
                             S           sync project
```

### 2.5 키바인딩 (서브탭별 고유)
- **Skills**: `u` unlink, `l` link (path 입력)
- **Hooks**: `p` preview (dry-run)
- **Plugins**: `/` 필터, `i` install wizard, detail mode action list
- **Marketplace**: `s` sync, `r` remove, `a` add (2-step name→source)

### 2.6 Context 탭 모드
`categories → sources → preview → (confirm)`. 키: `j/k`, `Enter` (확대), `Esc/Backspace/Delete` (뒤로), `e` (에디터), `d` (skills unlink / memory delete), `r` (새로고침), preview 모드의 `j/k/PgUp/PgDn`, `y/Y/n/N/q` (confirm).

### 2.7 Project 탭
파일 표 (`File Source Lines Path`). Source 아이콘: `●` global / `◆` user / `■` project / `◇` memory / `○` unknown. 키: `j/k`, `p` (preview), `Enter/Esc`. index 0에서 `↑` → `onFocusUp` (mainTab 복귀).

### 2.8 Dashboard 탭
플랫폼별 카드 (Cost/Input/Output/Cache) + 14일 BarChart + 월간 예산 바. 키: `r` 새로고침.

### 2.9 Claude 탭 (2 서브탭)
- **Overview**: Today/Week/Month 카드 + 14일 BarChart + Active Block + 예산 라인
- **Review** (insights): plan limits, subagent-heavy %, large context %, parallel sessions %, skill/agent/plugin breakdown
- 서브탭 키: `← → Tab Shift+Tab` (Overview ↔ Review)
- Review 내부 키: `o`(overview) `s`(skills) `a`(agents) `p`(plugins) `d`(1일) `w`(7일)

### 2.10 Codex / Gemini 탭
Claude Overview와 동일 구조 (sub-tab 없음). 키: `r`.

### 2.11 Cursor 탭
요약 카드 3개 (Summary / AI vs Human / AI Ratio bar) + 최대 50 커밋 표 (`Hash Message AI% Lines`). 키: `j/k`, `r`. `loadCursorMetrics`, `summarizeCursorMetrics`.

### 2.12 공통 위젯
- **Table**: prefix 4셀(`▸/space + ■/□` 또는 `▸/space + 번호`), 마지막 컬럼 자동 확장, selected는 cyan+bold (inverse 회피)
- **DetailPanel**: rich(컬러 보존) ↔ flat scroll(overflow 시) 2경로, AMBIGUOUS_SAFETY 6셀, focused → cyan border
- **DetailView (hook)**: detail/preview/loading 모드 전환, previewLoader 비동기
- **PreviewPanel**: 라인 번호 3자리, 노란 더블 보더, `[start-end/total]` 인디케이터
- **SourceSummary**: `{count} {label}(s) from {n} source(s)` + 컬러 source 리스트
- **Confirm**: `y/Y/n/N/q` + 더블 보더
- **BarChart**: 8셀 label + `█` cyan bar + dim value
- **SearchInput**: `ink-text-input` 래핑
- **HelpPopup**: `?/q/Esc/Return`으로 닫기, 네비/탭/단축키 안내
- **TabBar**: 8 메인 탭 가로 배치, active inverse + focus 표시
- **useDetailScroll**: focus 시 j/k/PgUp/PgDn 처리, Esc로 blur, resetKey로 0 리셋
- **useDetailMaxHeight**: termHeight - reservedRows (min 6)
- **flattenDetailFields**: widthNarrow vs widthWide 이중 측정, chunkByWidth, padToWidth

### 2.13 글로벌 키 (App.tsx)
- `q` / `Esc`: 종료 (특정 탭의 subview 중에는 차단)
- `?`: HelpPopup 토글
- `r`: refresh (refreshKey++)
- `1-8`: 메인탭 점프
- `← →`: 메인탭 순회

---

## 3. core 도메인 (~80개 함수)

### 3.1 paths.ts
- 환경변수: `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `GEMINI_CLI_HOME`
- Windows: `%APPDATA%` 대체 경로
- `PATHS`: claudeDir, settings, knownMarketplaces, installedPlugins, blocklist, pluginCache, marketplaces, skills, projects, statsCache, usageSnapshot, codexDir, codexSessions, geminiDir, geminiTmp, geminiProjects, cursorDir, cursorTrackingDb, axtDir, vault, vaultSkills, vaultCommands, vaultAgents
- `AXT_CONFIG_DIR`, `AXT_CONFIG_PATH` (XDG_CONFIG_HOME/axt 또는 AppData)

### 3.2 json-io.ts
- `readJson(path, {fallback})` — 파싱 + fallback
- `writeJsonAtomic(path, data)` — tmpfile + rename + .bak 백업

### 3.3 settings.ts (단일 스코프, 호출자가 병합)
- `readEnabledPlugins`, `setPluginEnabled`, `removePluginFromSettings`
- `readFavoritePlugins`, `setPluginFavorite`
- `readMarkedForUpdate`, `setMarkedForUpdate`
- `readExtraMarketplaces`
- 우선순위: project local > project > global (호출자가 결정)

### 3.4 vault.ts (가장 큰 도메인)
- 타입: `ExtensionType`, `VaultItem`, `AxtProfile`, `SyncResult`, `MigrateResult`, `PluginRef`
- `parseYamlDescription(frontmatter)` — double/single quote, 블록 스칼라(`|`, `>`), CRLF 처리
- `listVaultItems`, `listVaultItemsWithProjectState`
- `readProfile`, `writeProfile` (`.axt-profile.json`)
- `linkToProject`, `unlinkFromProject`, `syncProject`
- `linkToGlobal`, `unlinkFromGlobal`
- `importToVault`, `migrateToVault`
- **Windows 미지원**: symlink 생성 throw

### 3.5 marketplace.ts
- 타입: `MarketplaceSource` (github/git/directory union), `MarketplaceInfo`, `SyncResult`, `VersionInfo`, `PooledError`, `PooledResult`
- `parseMarketplaceSource`, `listMarketplaces`, `addMarketplace`, `removeMarketplace`, `syncMarketplace`
- 버전: `getLocalVersion`, `getMarketplaceVersion`, `readShaFile`, `downloadAndExtractTarball`
- 유틸: `isGitRepo`, `pooledMap` (동시성 풀)
- 외부: `git clone --depth 1`, `git pull --ff-only`, `git fetch`, `git rev-parse`, `tar xzf`
- 데이터: `known_marketplaces.json` (`{[name]: {source, installLocation, lastUpdated, autoUpdate?}}`), `.gcs-sha` (GitHub SHA)

### 3.6 plugin.ts
- 타입: `PluginInfo` (id, name, marketplace, version, installPath, scope, installedAt, lastUpdated, author?, description?, homepage?, repository?), `UpdateResult`
- `listInstalledPlugins`, `getPluginInfo`
- `addInstalledPlugin`, `removeInstalledPlugin`, `updatePlugin`
- `findPluginSourceDir`
- 데이터: `installed_plugins.json` (`{version: 2, plugins: {[id]: [{scope, installPath, version, installedAt, lastUpdated, gitCommitSha?}]}}`)
- manifest: `.claude-plugin/plugin.json` 또는 `plugin.json`

### 3.7 skill.ts
- 타입: `SkillSource = "user"|"project"|"plugin"`, `SkillInfo`
- `listSkills`, `listAllSkills` (user + project + 활성 플러그인)
- `isSymlinkSupported` (Windows false)
- `linkSkill`, `unlinkSkill` (Windows throw)

### 3.8 mcp.ts
- 타입: `McpServerInfo` (name, pluginId, command, args, env)
- `listMcpServers(installedPlugins)` — plugin.json에서 mcpServers 추출

### 3.9 commands.ts / agents.ts
- 타입: `CommandSource|AgentSource = "user"|"project"|"plugin"`
- `listCommands({projectDir?})`, `listAllAgents({projectDir?})`
- `.md` frontmatter description 추출

### 3.10 hooks.ts
- 타입: `HookType = "command"|"http"|"mcp_tool"|"prompt"|"agent"`, `HookSource = "user"|"project"|"local"|"plugin"`, `HookEntry`, `HookRule`, `HookInfo`, `HookPreviewResult`
- `listHooks` (4 소스 병합), `previewHook` (dry-run, `sh -c`), `getHookDetail`
- **29개 이벤트**: SessionStart, Setup, UserPromptSubmit, UserPromptExpansion, PreToolUse, PermissionRequest, PermissionDenied, PostToolUse, PostToolUseFailure, PostToolBatch, Stop, StopFailure, SubagentStart, SubagentStop, TaskCreated, TaskCompleted, TeammateIdle, InstructionsLoaded, ConfigChange, CwdChanged, FileChanged, WorktreeCreate, WorktreeRemove, PreCompact, PostCompact, Elicitation, ElicitationResult, SessionEnd, Notification

### 3.11 project-context.ts
- 타입: `ProjectContextItem` (name, source, path, content, lines)
- `loadProjectContext(cwd)` — global/user/project CLAUDE.md + settings + memory 수집

### 3.12 project-usage.ts
- 타입: `ProjectRef`, `ExtensionUsage`, `UsageIndex = Map<string, ExtensionUsage>`
- `scanProjectUsage(projectsDir, vaultDir, mode)` — `default` (profile+symlink) / `full` (+settings)
- `getProjectCount`, `getProjects`
- 경로 인코딩: `/` 및 `.` → `-`

### 3.13 cache.ts
- 타입: `CacheFile` (version, lastUpdated, projectsDir?, files: {[path]: {mtime, entries}})
- `loadCachedUsage`, `saveCachedUsage`, `getFileMtime`, `isCacheValid` (기본 5분)
- 저장: `~/.config/axt/cache/{platform}-usage.json`

### 3.14 types.ts
- `Platform = "claude"|"codex"|"gemini"`
- `UnifiedUsageEntry`: platform, model, timestamp, sessionId, projectPath, inputTokens, outputTokens, cacheWriteTokens, cacheReadTokens, reasoningTokens, toolTokens
- `RateLimitInfo`: platform, usedPercent, windowMinutes, resetsAt

---

## 4. Usage / Pricing / Context

### 4.1 플랫폼별 데이터 포맷
| 항목 | Claude | Codex (OpenAI) | Gemini (Google) | Cursor |
|---|---|---|---|---|
| 파일 | JSONL per session | JSONL (session_meta + event_msg) | JSON/JSONL | SQLite `scored_commits` |
| 경로 | `~/.claude/projects/{proj}/{session}.jsonl` | `{codexSessionsDir}/**/*.jsonl` | `{geminiTmp}/*/chats/session-*.{json,jsonl}` | `~/.cursor/metrics.db` |
| token 필드 | `usage.{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}` | `info.last_token_usage.{input, cached_input, output, reasoning_output}` | `tokens.{input, output, cached, thoughts, tool}` | `linesAdded/Deleted` + AI/human 분할 |
| rate limit | 별도 snapshot 파일 | event_msg 내장 (`rate_limits.primary`) | N/A | N/A |
| 캐싱 | mtime per-file | 없음 | 없음 | 없음 |

### 4.2 5시간 빌링 블록 (Claude)
- 윈도우 길이: 18,000,000ms (5h)
- UTC 정렬: 00:00, 05:00, 10:00, 15:00, 20:00 UTC
- 계산: `windowIndex = floor(msSinceMidnight / 18M)`
- `isActive = now < windowEnd`
- burn rate: 활성 블록의 tokens / elapsed_min

### 4.3 모델별 가격 (per 1M tokens, USD)
| Model | Input | Output | Cache Write | Cache Read | Context Window |
|---|---|---|---|---|---|
| claude-opus-4-7 / 4-6 | 15.00 | 75.00 | 18.75 | 1.50 | 1,000,000 |
| claude-sonnet-4-6 | 3.00 | 15.00 | 3.75 | 0.30 | 1,000,000 |
| claude-haiku-4-5 | 0.80 | 4.00 | 1.00 | 0.08 | 200,000 |
| gpt-5 | 1.25 | 10.00 | 0 | 0.125 | — |
| gpt-5.2-codex / 5.3-codex | 1.75 | 14.00 | 0 | 0.175 | — |
| gpt-5.4 | 1.75 | 14.00 | 0 | 0.175 | — |
| gemini-2.5-pro | 1.25 | 10.00 | 0 | 0.125 | — |
| gemini-2.5-flash | 0.30 | 2.50 | 0 | 0.03 | — |
| gemini-2.5-flash-lite | 0.10 | 0.40 | 0 | 0.01 | — |
| gemini-3.1-pro-preview | 2.00 | 12.00 | 0 | 0.20 | — |
| gemini-3-flash-preview | 0.50 | 3.00 | 0 | 0.05 | — |

비용: `(input/1M)*Pin + (output/1M)*Pout + (cacheCreation/1M)*PcacheWrite + (cacheRead/1M)*PcacheRead`

### 4.4 컨텍스트 분석 (12 카테고리)
1. **system-prompt** (4,200 tok fixed)
2. **claude-md** — global/user/project + `.claude/CLAUDE.md` 등 5곳
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
- Codex: event_msg payload 내장 (`primary.used_percent`, `window_minutes`, `resets_at`)
- 신선도: 기본 5분 tolerance

### 4.6 Usage Insights (Claude 전용)
`loadUsageInsights({days: 1 | 7})`:
- planLimits (5h/7d %)
- subagentHeavyPct / largeContextPct (>150k input) / parallelSessionPct (3+ overlap)
- skillBreakdown / subagentBreakdown / pluginBreakdown — name + tokenPct
- 캐시: `~/.axt/cache/insights-{days}d.json` (5분 TTL)

---

## 5. Wizard / 보조 UI

- **InstallWizard**: search query → results (현재 안내)
- **RemoveWizard**: Confirm → removeInstalledPlugin + removePluginFromSettings + rm

---

## 6. 잡다한 상수

- `SOURCE_COLORS`: user=cyan, project=green, local=yellow, plugin=magenta
- `TUI_LOCALE = "en-US"` (config.locale 무시)
- 캐시 TTL: usage 5분, insights 5분

---

## 7. Python 재작성 시 명시적 주의 사항

1. **Windows symlink**: vault/skill의 link/unlink는 `os.symlink` 시도 후 `OSError` → 안내 메시지로 graceful degrade. tests에서 platform check.
2. **외부 명령**: git clone/pull/fetch/rev-parse, tar xzf, sh -c (hook preview), claude --version, git status — `subprocess.run` 사용. 실패 시 stderr 캡처.
3. **JSONL**: 큰 파일은 라인 단위 lazy read. mtime cache 필수.
4. **YAML frontmatter 파서**: `parseYamlDescription`을 cst의 robust 파서 패턴으로 이식. PyYAML 사용 안 함 (의존성 제로 원칙).
5. **timezone**: usage 집계는 사용자 timezone option, Claude 5h 블록은 UTC.
6. **SQLite (Cursor)**: stdlib `sqlite3`로 충분.
7. **HTTP (marketplace tarball)**: stdlib `urllib.request` + `tarfile` 사용.
8. **curses CJK width**: `unicodedata.east_asian_width()`로 사전 계산, `addnstr`에 wide 셀 폭 명시.
9. **profile lookup**: `~/.claude/projects/` 폴더명 인코딩(`/` 및 `.` → `-`) decode는 brute-force matching (cst 패턴 참고).
10. **pricing.json 분리**: 13개 모델 가격 표를 코드 외부로 빼면 가격 변동 시 코드 수정 불필요.
