# PaperFlow MCP v1.1 bugfixes spec rev4 review

## R3 finding closure

- R3 H#1 outputs metadata priority: 해결됐습니다. spec §5.2.2에서 `_resolve_completed_candidate()`가 더 이상 `papers.find_processed_paper()`를 호출하지 않고, `_find_metadata_match_in_dir(settings.outputs_dir, expected_filename)` → `_scan_outputs_dir_only()` → archives metadata → archives filesystem 순서로 직접 검사합니다. T22도 archives mtime이 더 최신인 metadata-only edge를 커버합니다.
- R3 M#1 scan helper symlink escape: 해결됐습니다. `_is_safe_direct_child()`가 `base.resolve(strict=True)`와 `candidate.resolve(strict=True)`를 비교하고, 모든 scan/metadata helper가 이 guard를 통과한 direct child만 후보로 씁니다. `FileNotFoundError`/`OSError`는 false 처리하므로 race로 사라진 폴더도 안전하게 제외됩니다.
- R3 M#2 명칭 불일치: 해결됐습니다. T7/T15와 §11 risk가 `_scan_outputs_dir_only` / `_find_metadata_match_in_dir` 기준으로 정리됐고, legacy `_scan_outputs_for_filename` 제거 절차도 §5.2.2와 §7에 남아 있습니다.
- R3 M#3 risk mitigation 문구: 해결됐습니다. §11 첫 번째 risk가 `MCP_REQUIRE_TRANSLATION=false` 힌트를 primary mitigation으로 설명합니다.

## Critical

없습니다.

## High

없습니다.

## Medium / Notes

1. [medium] §5.4의 operator mismatch 설명이 §11보다 약간 오래된 표현을 남깁니다.
   - 인용: §5.4는 operator가 `MCP_REQUIRE_TRANSLATION=false`를 빼먹었을 때 error message가 "resubmit with force_reprocess=true"를 안내하고, disabled-translation pipeline이 다시 성공한다고 설명합니다.
   - 현재 rev4 실제 error message와 §11은 `MCP_REQUIRE_TRANSLATION=false` 설정 힌트를 추가했으므로, §5.4도 "env를 고친 뒤 필요하면 cleanup/resubmit" 순서로 맞추면 더 일관됩니다.
   - ship blocker는 아닙니다. 핵심 동작과 테스트 경계에는 영향이 없고, §11에는 이미 정확한 mitigation이 있습니다.

2. [low] `_is_safe_direct_child()`는 symlink escape는 차단하지만 base 내부 direct child를 가리키는 symlink는 허용할 수 있습니다.
   - `cand_resolved.parent == base_resolved` 조건상 외부 escape는 막힙니다. 내부 symlink까지 완전히 금지하려면 `candidate.is_symlink()` false 조건을 추가해야 합니다.
   - 현재 요구사항은 escape 차단이므로 blocker는 아닙니다. cleanup 시 내부 symlink가 후보가 되면 `shutil.rmtree()`가 warning으로 실패할 수 있지만, 외부 data-loss 위험은 낮습니다.

## Test Coverage

T1-T23은 이번 v1.1 regression surface를 충분히 덮습니다. 특히 T13/T14/T19가 stale complete migration과 downstream zip/result 차단을 잡고, T21/T22가 filesystem-vs-metadata priority 양쪽을 나눠 검증하며, T23이 symlink escape를 고정합니다.

## Overall

rev4는 R1-R3의 critical/high finding을 모두 닫았고, 남은 항목은 문구 정리 또는 implementation-time hardening 수준입니다. v1.1 bugfix 설계로 구현 진행해도 됩니다.

===CODEX_FINAL_APPROVAL===
