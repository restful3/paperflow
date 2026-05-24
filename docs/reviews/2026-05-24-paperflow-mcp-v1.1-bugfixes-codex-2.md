# PaperFlow MCP v1.1 bugfixes spec rev2 review

## Round 1 finding closure

- C#1 legacy `status=complete` 재검증: 해결 방향은 맞습니다. spec §5.2.3 lines 177-201에서 `error/cancelled`만 terminal로 두고 `complete`를 `_classify_completion()`으로 재검증합니다.
- C#2 zip stale direct path: 해결됐습니다. spec §5.2.4 lines 280-285에서 zip endpoint가 `get_job()` 대신 `reconcile_job()`을 호출합니다.
- C#3 config.json 접근 불일치: 해결됐습니다. spec §5.2.1 lines 88-105에서 `MCP_REQUIRE_TRANSLATION` env로 전환했고, §3 lines 47-50은 viewer에 env field만 추가한다고 명시합니다.
- H#1 primary/fallback partial gate: 대부분 해결됐습니다. spec §5.2.2-5.2.3이 `_resolve_completed_candidate()`와 `_classify_completion()`으로 통합합니다. 다만 아래 High #1/#2 때문에 fallback helper의 구현 세부가 아직 닫히지 않았습니다.
- H#2 smart-rename cleanup fallback: 방향은 해결됐습니다. spec §5.3.1 lines 308-327에서 cleanup이 `_resolve_completed_candidate()`를 재사용합니다. 다만 그 helper가 archives fallback을 outputs로 오인할 수 있어 아래 High #1 영향권입니다.
- H#3 outputs+archives 동시 match: 정책은 해결됐습니다. spec §5.2.2 lines 130-150과 T16에서 outputs 우선을 선언합니다. 다만 `find_processed_paper()` newest-wins를 완전히 우회하지 못하는 edge가 아래 High #2로 남습니다.
- H#4 list_jobs migration 문구: 해결됐습니다. spec §2 line 41과 §8 line 439가 list_jobs read-through를 명시합니다.
- M#1 folder disappearance 오분류: `complete` branch 기준으로 해결됐습니다. spec §5.2.2 lines 110-127과 §5.2.3 lines 195-199가 missing을 별도 error로 처리합니다. queued/processing branch에는 빠진 분기가 있어 아래 High #3이 남습니다.
- M#2 fail-closed config side effect: 해결됐습니다. config read 자체를 제거했습니다.
- M#3 cancel cleanup visibility: 해결됐습니다. spec §5.3.1-5.3.3이 structured cleanup response를 추가합니다.
- M#4 test coverage: 대체로 보강됐습니다. T13-T19가 핵심 회귀를 다룹니다. 아래 High #1/#3에 대응하는 테스트 보강이 추가로 필요합니다.
- M#5 timeout smoke: 해결됐습니다. spec §7 lines 431-434에 compose env 확인이 들어갔습니다.

## Critical

없습니다. rev2는 Round 1 critical 3건의 큰 설계 방향을 모두 바로잡았습니다.

## High

1. [high] `_resolve_completed_candidate()`가 archives fallback을 outputs로 오인할 수 있습니다.
   - 인용: spec §5.2.2 lines 145-148은 `_scan_outputs_for_filename(expected_filename)` 결과가 있으면 무조건 `return scan[0], "outputs"`를 반환합니다.
   - 코드 근거: 현행 `viewer/app/services/mcp_jobs.py:295-304`의 `_scan_outputs_for_filename()`은 이름과 달리 outputs뿐 아니라 archives도 스캔하고 `(sub.name, loc_name)`을 반환합니다.
   - 영향: metadata가 없고 archives에만 source PDF가 있는 경우, `_resolve_completed_candidate()`는 archives hit를 outputs hit로 라벨링합니다. 이후 `_classify_completion()`은 `settings.outputs_dir / name`을 검사해 missing/partial로 오판하거나, cleanup helper가 존재하지 않는 outputs path를 대상으로 동작합니다. 이는 §5.2.3 lines 256-258의 "Archives are user-curated; never flag as partial" 정책과 충돌합니다.
   - 제안: fallback scan 결과의 location을 반드시 확인하십시오. 예: `scan = _scan_outputs_for_filename(...); if scan and scan[1] == "outputs": return scan[0], "outputs"` 후, archives fallback은 `return scan[0], "archives"` 또는 primary `info`로만 처리합니다. 더 안전하게는 `_scan_outputs_for_filename`을 `_scan_for_filename`로 이름 변경하거나, outputs-only helper를 별도로 추가하십시오. T10/T4에 "archives only + paper_meta absent/corrupt + source PDF present" 케이스를 추가해야 합니다.

2. [high] outputs 우선 정책이 `find_processed_paper()` newest-wins를 완전히 이기지 못합니다.
   - 인용: spec §5.2.2 lines 140-152는 primary `find_processed_paper()`가 outputs면 즉시 반환하고, 아니면 fallback scan 후 primary 결과를 반환합니다.
   - 코드 근거: `viewer/app/services/papers.py:621-631`은 outputs와 archives 후보를 모두 모은 뒤 mtime 최신순으로 정렬합니다. 같은 `expected_filename`이 outputs와 archives 양쪽 metadata에 있을 때 archives가 더 최신이면 `find_processed_paper()`는 archives만 반환합니다. 그 다음 outputs fallback은 source PDF가 outputs folder 안에 있을 때만 찾을 수 있습니다.
   - 영향: outputs partial folder가 metadata match를 갖고 있어도 source PDF가 없거나 fallback scan 조건을 만족하지 않으면, archives 최신 hit가 complete로 처리되고 outputs partial cleanup/detection이 우회됩니다. spec §5.2.2 lines 134-135의 "if BOTH match, outputs wins"를 구현으로 보장하지 못합니다.
   - 제안: `_resolve_completed_candidate()`는 `find_processed_paper()` 단일 반환값에 의존하지 말고 outputs directory를 먼저 직접 검사해야 합니다. 우선순위는 "outputs metadata match → outputs file scan match → archives metadata/file match"가 되어야 합니다. T16은 archives mtime이 더 최신인 상태와 outputs source PDF가 없는 상태도 포함해야 합니다.

3. [high] queued/processing completion branch에서 `"missing"` verdict를 complete로 처리합니다.
   - 인용: spec §5.2.3 lines 211-225는 `cand`를 찾은 뒤 `_classify_completion(..., _precomputed=(name, location))`을 호출하고, `verdict == "partial"`만 error로 처리합니다. 그 외는 주석상 "complete or skip"으로 간주해 `status="complete"`를 씁니다.
   - 문제: `_classify_completion()`은 spec §5.2.3 lines 260-263에 따라 `_precomputed`가 있어도 folder가 race로 사라지면 `"missing"`을 반환할 수 있습니다. 이 `"missing"`이 queued/processing branch에서는 처리되지 않아 complete로 저장됩니다.
   - 영향: Round 1 M#1에서 닫으려던 race가 complete branch에서는 해결됐지만, 새로 완료를 발견하는 branch에서는 false complete가 남습니다. zip endpoint가 같은 reconcile 결과를 신뢰하면 direct zip에서 410/404가 뒤늦게 날 수 있고, JobRecord 상태는 잘못 complete가 됩니다.
   - 제안: queued/processing branch도 `verdict == "missing"`을 complete branch와 동일하게 `status="error", error="paper folder no longer present..."`로 처리하십시오. T17은 persisted complete뿐 아니라 queued/processing 상태에서 candidate 발견 후 folder disappearance를 시뮬레이션해야 합니다.

## Medium

1. [medium] `cancel_job()` service return type 변경은 내부 테스트/API 관점에서 명시가 조금 더 필요합니다.
   - 인용: spec §5.3.2 line 332는 `mcp_jobs.cancel_job()` 자체를 `dict | None` 반환으로 바꿉니다.
   - 코드 근거: 현행 `viewer/tests/test_mcp_jobs.py:265-266`은 service 함수 반환값을 `JobRecord`로 보고 `cancelled.status`를 읽습니다. production caller는 `viewer/app/routers/mcp_router.py:128-133`뿐이라 implementation impact는 작지만, service-level API는 breaking change입니다.
   - 제안: 기존 service tests를 dict shape로 업데이트한다는 점을 §6/T18 또는 §7에 명시하십시오. 더 보수적인 대안은 service는 `tuple[JobRecord, cleanup]` 또는 작은 Pydantic result model을 반환해 타입 안정성을 유지하는 것입니다. blocker는 아닙니다.

2. [medium] `MCP_REQUIRE_TRANSLATION=false` 운영 sharp-edge는 문서화됐지만, error message가 현재 원인을 잘못 안내할 수 있습니다.
   - 인용: spec §5.4 line 392와 §11 line 452는 operator가 env를 잘못 설정하면 error loop가 visible하므로 알아차릴 수 있다고 합니다.
   - 영향: 실제 error message는 §5.2.3 lines 190-192의 "prior run was killed mid-translation; cancel_job then resubmit"으로 고정되어 있습니다. translation-disabled 환경에서 env만 잘못 둔 경우 이 안내는 원인이 틀렸고, 사용자를 반복 delete/resubmit 루프로 유도합니다.
   - 제안: `translation_missing` error에 `MCP_REQUIRE_TRANSLATION=true` 전제를 포함하십시오. 예: "If this deployment intentionally disables Korean translation, set MCP_REQUIRE_TRANSLATION=false." 이 문구만 추가해도 운영 sharp-edge가 충분히 완화됩니다.

3. [medium] test plan이 `_classify_completion()`의 4-state를 완전히 분리 검증하지 않습니다.
   - 인용: spec §5.2.3 lines 237-244는 `"complete"`, `"partial"`, `"missing"`, `"skip"` 네 verdict를 정의하지만 §6의 tests는 대부분 reconcile 결과를 통해 간접 검증합니다.
   - 제안: helper unit test를 하나 추가해 `_classify_completion()`이 outputs+ko, outputs-no-ko+require, outputs-no-ko+not-require, missing, archives-no-ko 각각에서 정확한 verdict를 반환하는지 직접 확인하십시오. 특히 High #3처럼 caller가 특정 verdict를 빠뜨리는 regression을 잡기 쉽습니다.

## Opinion

- opinion: `MCP_REQUIRE_TRANSLATION` env var로 viewer와 converter config를 명시적으로 분리한 결정은 v1.1 범위에서는 타당합니다. config.json mount보다 coupling이 적고, default true도 현재 PaperFlow의 기본 번역 파이프라인에는 맞습니다. 다만 operator mismatch가 생겼을 때의 안내 문구는 반드시 보강하는 편이 낫습니다.
- opinion: `list_jobs`를 read-through로 유지하는 결정은 acceptable입니다. zip/get_job_status/get_job_result가 reconcile을 호출하도록 바뀌었기 때문에 data corruption path는 닫히고, list의 stale 표시는 문서화된 비용/정확도 tradeoff로 볼 수 있습니다.

추가 라운드 필요: archives fallback을 outputs로 오인하는 helper 버그와 queued/processing branch의 `"missing"` verdict 누락은 false complete 또는 archive 오분류를 만들 수 있어 rev2 그대로는 final approval 하기 어렵습니다.
