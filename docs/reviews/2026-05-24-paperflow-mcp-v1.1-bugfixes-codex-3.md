# PaperFlow MCP v1.1 bugfixes spec rev3 review

## R2 finding closure

- R2 H#1 archives fallback을 outputs로 오인: 대부분 해결됐습니다. spec §5.2.2 lines 142-170에서 `_scan_outputs_dir_only()` / `_scan_archives_dir_only()`를 분리했고, legacy `_scan_outputs_for_filename()` 사용 중단도 §5.2.2 line 217에 명시했습니다.
- R2 H#2 outputs 우선 정책: 정책 선언은 해결됐지만, pseudocode가 아직 이 정책을 완전히 구현하지 못합니다. 아래 High #1이 남아 있습니다.
- R2 H#3 queued/processing branch의 `"missing"` verdict 누락: 해결됐습니다. spec §5.2.3 lines 270-286에서 queued/processing 완료 발견 branch도 `"missing"`을 명시적으로 error 처리합니다.
- R2 M#1 `cancel_job()` service return type 변경 영향: 해결됐습니다. spec §6 lines 486-487과 §7 lines 494-495에서 기존 `cancelled.status` 테스트 업데이트를 명시합니다.
- R2 M#2 translation-disabled operator mismatch 안내: 해결됐습니다. spec §5.2.3 lines 244-248과 273-277에 `MCP_REQUIRE_TRANSLATION=false` 힌트가 들어갔습니다.
- R2 M#3 `_classify_completion()` 4-state direct test: 해결됐습니다. spec §6 line 483에 T20이 추가됐습니다.

## Critical

없습니다.

## High

1. [high] `_resolve_completed_candidate()`의 "outputs metadata match 우선"이 여전히 `find_processed_paper()` newest-wins에 의존합니다.
   - 인용: spec §5.2.2 lines 173-188은 lookup order를 "1. outputs metadata match, 2. outputs filesystem scan, 3. archives metadata match, 4. archives filesystem scan"으로 선언하고, lines 186-188은 `find_processed_paper`의 newest-wins와 무관하게 outputs가 이겨야 한다고 말합니다.
   - 문제: pseudocode lines 190-193은 `info = _papers.find_processed_paper(original_filename=expected_filename)`를 한 번 호출한 뒤 `info["location"] == "outputs"`일 때만 outputs metadata hit로 처리합니다. 하지만 실제 `find_processed_paper()`는 outputs와 archives 후보를 합쳐 mtime 최신순으로 정렬한 뒤 첫 match를 반환합니다. archives copy가 더 최신이면 outputs에 matching `paper_meta.json`이 있어도 `info`는 archives가 됩니다.
   - 영향: outputs folder에 metadata match가 있지만 source PDF가 없거나 `_scan_outputs_dir_only()` 조건을 만족하지 않는 경우, resolver는 step 1의 outputs metadata match를 놓치고 step 3 archives metadata로 넘어갑니다. 그 결과 outputs partial detection/cleanup이 우회되어 rev2 H#2의 핵심 edge가 남습니다.
   - 제안: `_resolve_completed_candidate()`는 `find_processed_paper()`를 outputs metadata match 용도로 쓰지 말고 outputs directory를 직접 스캔해야 합니다. 예: `_find_metadata_match_in_dir(settings.outputs_dir, expected_filename)` → `_scan_outputs_dir_only()` → `_find_metadata_match_in_dir(settings.archives_dir, expected_filename)` → `_scan_archives_dir_only()`. `papers.py` 수정 없이 `mcp_jobs.py` 내부에서 `paper_meta.json`만 read-only로 읽으면 no-change 제약도 유지됩니다.
   - 테스트 보강: T6 또는 T21에 "outputs와 archives 모두 matching paper_meta가 있고 archives mtime이 더 최신이며 outputs folder에는 source PDF가 없음"을 추가해야 합니다. 현재 T21은 outputs filesystem scan이 이기는 케이스만 보장해서 metadata-only outputs hit 누락을 잡지 못합니다.

## Medium

1. [medium] 새 scan helper도 symlink escape 방어가 없습니다.
   - 인용: spec §5.2.2 lines 152-155와 165-168은 `for sub in base.iterdir(): if sub.is_dir() and (sub / expected_filename).is_file()` 패턴을 사용합니다.
   - 코드 맥락: `papers.find_processed_paper()`는 현재 `_safe_child_dir(base, item)`로 outputs/archives 하위 실제 디렉터리만 후보로 삼습니다. 새 helper는 `Path.is_dir()`가 symlink를 따라가므로 outputs 아래 symlink가 외부 디렉터리를 가리키면 그 안의 파일도 candidate가 될 수 있습니다.
   - 영향: reconcile은 잘못된 외부 candidate를 complete/partial 판정에 사용할 수 있고, cleanup은 symlink 자체에 대해 `shutil.rmtree()`를 호출하려다 실패 warning을 낼 가능성이 있습니다. 즉시 data-loss로 이어질 가능성은 낮지만, 기존 hardening 방향과 어긋납니다.
   - 제안: `_scan_outputs_dir_only()` / `_scan_archives_dir_only()`에도 `_safe_child_dir`와 동등한 containment check를 넣으십시오. `mcp_jobs.py` 내부 helper로 재구현해도 됩니다.

2. [medium] spec 내 일부 명칭이 rev3 helper와 맞지 않습니다.
   - 인용: T7/T15는 여전히 `_scan_outputs_for_filename`을 언급합니다(spec §6 lines 470, 478). §11 line 523도 `_resolve_completed_candidate`가 `_scan_outputs_for_filename`에 의존한다고 씁니다.
   - 영향: 구현자가 legacy function을 제거해야 하는지, 새 outputs-only helper를 써야 하는지 혼동할 수 있습니다. 특히 §5.2.2 line 217은 legacy function 제거를 지시하므로 같은 문서 안에서 용어가 충돌합니다.
   - 제안: T7/T15/§11 risk 문구를 `_scan_outputs_dir_only`로 갱신하고, "legacy `_scan_outputs_for_filename` removed"를 테스트/implementation note에 일관되게 반영하십시오.

3. [medium] `MCP_REQUIRE_TRANSLATION=false` mismatch risk 설명은 error message와 아직 약간 불일치합니다.
   - 인용: §11 line 520은 mitigation이 "`cancel_job(delete_file=true)` + resubmit" 안내라고 설명하지만, rev3 실제 error message에는 operator에게 `MCP_REQUIRE_TRANSLATION=false`를 설정하라는 힌트가 추가됐습니다.
   - 영향: 심각한 설계 결함은 아니지만, risk section만 읽으면 여전히 반복 resubmit loop가 주 mitigation처럼 보입니다.
   - 제안: §11 risk mitigation을 "error message includes MCP_REQUIRE_TRANSLATION=false hint; operator fixes env before cleanup/resubmit"로 갱신하십시오.

## Overall

rev3는 R2의 H#1/H#3과 medium 항목 대부분을 닫았고, 설계는 ship에 가까워졌습니다. 다만 `_resolve_completed_candidate()`가 아직 outputs metadata match를 직접 검사하지 않아 "strict 4-step priority"를 구현하지 못하는 high 문제가 남아 있습니다.

추가 라운드 필요: outputs metadata 우선순위를 `find_processed_paper()` newest-wins와 독립적으로 구현하도록 spec을 한 번 더 수정해야 합니다.
