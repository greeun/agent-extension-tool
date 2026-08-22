# 스펙 결정 기록

테스트 작성 중 **스펙과 구현이 충돌**해 판정이 필요했던 항목과 그 근거를 남긴다.
`full-test-orchestrator` Phase E 의 `SPEC_AMBIGUOUS` 분류에 해당하는 건들이다.

---

## SD-001 — 마켓플레이스 sync 는 로컬 수정을 보존하지 않는다

**상태**: 결정 완료 (문서 정정) · 2026-08-22

### 충돌
| 출처 | 주장 |
|---|---|
| `FEATURES.md:255` (정정 전) | 외부 명령 목록에 `git pull --ff-only` |
| `tests/doc/user-stories.md` US-MKT05 (정정 전) | "로컬 수정이 있는 저장소를 강제로 덮어쓰지 않는다" |
| `axt/core.py` `sync_marketplace` | `git fetch` + `git reset --hard @{u}` (hard-sync) |
| `tests/test_marketplace.py::test_sync_marketplace_git_dirty_tree_hard_syncs` | hard-sync 를 회귀 방지 사양으로 고정 |

Phase B Agent 3 이 TC-CHAOS-018 을 `BLOCKED` 으로 표시하고 임의 판정을 거부했다.
어느 쪽으로 쓰든 반대편 계약을 깨뜨리는 상황이었기 때문이다. 올바른 대응이었다.

### 조사 결과
- hard-sync 는 `db132c0 feat(update): bulk update via Space marks + dirty-tree marketplace sync (v1.11.0)`
  에서 **의도적으로 도입**됨
- 사유가 코드 주석과 테스트 docstring 양쪽에 명시:
  Claude Code 자체 업데이터가 마켓 파일을 **커밋 없이 제자리에서 덮어쓰기** 때문에
  git 트리가 상시 dirty 가 되고, `pull --ff-only` 가 머지를 거부해 sync 가 깨졌다 (claude-hud 회귀)
- 그 커밋이 `FEATURES.md` 를 갱신하지 않아 §3.5 의 외부 명령 목록이 **낡은 상태로 남음**
- US-MKT05 는 그 낡은 줄에서 파생된 것이므로 **스토리 쪽이 틀렸다**

### 판정
**구현이 옳고 문서가 낡았다.** 구현을 `--ff-only` 로 되돌리면 claude-hud 회귀가 재발한다.

- `FEATURES.md:255` → 실제 명령(`git fetch`, `git reset --hard @{u}`)으로 정정하고
  캐시 성격·로컬 수정 미보존을 명문화
- US-MKT05 → "업데이터가 더럽힌 트리에서도 sync 가 성공한다"로 뒤집고 AC 4개 재작성
- 구현 **변경 없음**

### 남은 사용자 리스크 (의도적으로 수용)
`~/.claude/plugins/marketplaces/<name>` 에서 사람이 직접 수정한 내용은 sync 시 **경고 없이 사라진다**.
이 디렉터리는 캐시라는 것이 계약이므로 정상 동작이지만, 사용자가 그 사실을 모를 수 있다.
→ 후속 개선 후보: sync 전 dirty 트리 감지 시 폐기될 파일 수를 알리는 안내 (별건, 이번 범위 아님)

### 영향받은 TC
- `TC-CHAOS-018` — BLOCKED 해제. 방향을 뒤집어 "dirty 트리에서도 upstream 정렬 성공 +
  실패 시 레지스트리 무손상"으로 작성한다
