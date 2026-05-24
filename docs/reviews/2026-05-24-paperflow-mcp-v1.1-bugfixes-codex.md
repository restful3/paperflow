# PaperFlow MCP v1.1 bugfixes spec rev1 review

## Critical

1. [critical] 기존 v1 `status=complete` 잡은 재검증되지 않습니다.
   - 인용: spec §8 line 271은 "Existing partial outputs ... will, on next `reconcile_job` call (next status query or next list_jobs), transition from `status=complete` to `status=error`"라고 합니다.
   - 코드 근거: `viewer/app/services/mcp_jobs.py:315-316`은 `rec.status in ("complete", "error", "cancelled")`면 즉시 반환합니다. 따라서 v1에서 이미 `complete`로 저장된 partial job은 spec의 신규 `_ko.md` 검사를 전혀 타지 않습니다. 또한 `viewer/app/routers/mcp_router.py:68`의 `get_job_result()`가 `reconcile_job()`을 호출해도 동일하게 early return 됩니다.
   - 제안: `reconcile_job()`에서 `complete`는 무조건 terminal로 취급하지 말고, `paper_name/location/expected_filename`이 있는 MCP job에 한해 `_ko.md` completeness를 재검증하는 별도 branch를 early return 전에 두십시오. 최소한 v1.1 migration 대상인 "complete + outputs + translation_required + missing `_ko.md`"는 `error`로 전환해야 합니다. T14로 "legacy complete partial job + get_job_result/status query -> error"를 추가해야 합니다.

2. [critical] zip endpoint는 여전히 reconcile을 호출하지 않아서 stale `complete` 상태를 HTTP 200으로 서빙할 수 있습니다.
   - 인용: spec §5.2.3 lines 142-153은 zip endpoint "no code change"를 전제로 "Once Fix #2 turns partial jobs into `status=error`, the zip endpoint inherits the rejection automatically"라고 합니다.
   - 코드 근거: `viewer/app/routers/mcp_router.py:209-214`는 `mcp_jobs.get_job(job_id)`만 호출하고 `reconcile_job()`을 호출하지 않습니다. 따라서 위 critical #1의 stale `complete` job은 direct download URL로 바로 zip 생성까지 진행됩니다.
   - 제안: zip endpoint도 `rec = await mcp_jobs.reconcile_job(job_id)`로 바꾸십시오. 동시에 T12를 "status=error reject"만이 아니라 "legacy `status=complete` + missing `_ko.md` + direct zip call -> 404/409"로 강화해야 합니다.

3. [critical] `_config_translation_enabled()`가 현재 viewer 구성에서 `config.json`을 읽을 수 없습니다.
   - 인용: spec §5.2.1 lines 83-90은 `cfg_path = settings.base_dir / "config.json"`을 제안하고, §5.4 lines 227-233은 translation-disabled 환경에서 기존 동작이 보존된다고 합니다.
   - 코드 근거: `viewer/app/config.py:17`에는 `BASE_DIR` 필드만 있고 `settings.base_dir` 속성은 없습니다. 또한 `docker-compose.yml:43-47`의 viewer volume에는 `./config.json:/data/config.json` 또는 유사 mount가 없습니다. converter에는 `./config.json:/app/config.json`이 있지만(`docker-compose.yml:11-15`), viewer에는 없습니다.
   - 영향: helper는 AttributeError 또는 missing file로 항상 fail-closed `True`가 되어, `translate_to_korean=false` deploy에서도 English-only 정상 결과를 `translation_missing`으로 오분류합니다. 이는 spec §5.4의 "No regression for translation-disabled users"와 정면 충돌합니다.
   - 제안: 둘 중 하나를 명시해야 합니다. 첫째, `viewer/app/config.py`에 `config_json_path` 같은 property를 추가하고 `docker-compose.yml`에서 `./config.json:/data/config.json:ro`를 mount합니다. 둘째, viewer 전용 env로 "translation required"를 명시하고 converter config와 동기화하는 운영 규칙을 둡니다. 현 spec의 `settings.base_dir`는 그대로 구현하면 동작하지 않습니다.

## High

1. [high] `_scan_outputs_for_filename()` fallback complete path에는 `_ko.md` 검사가 없습니다.
   - 인용: spec §5.2.2 lines 112-133은 `find_processed_paper()` success branch에만 partial translation 검사를 삽입합니다.
   - 코드 근거: 현재 `reconcile_job()`는 primary lookup 실패 후 `viewer/app/services/mcp_jobs.py:333-339`에서 `_scan_outputs_for_filename()` 결과를 곧바로 `status="complete"`로 저장합니다. 이 fallback은 paper_meta가 없거나 손상된 경우를 위해 존재합니다.
   - 영향: paper_meta가 없거나 corrupt인 partial output은 v1.1에서도 여전히 complete가 됩니다. 특히 spec §11 line 293은 "`papers.find_processed_paper` already implements a fallback scan"이라고 쓰지만, 실제 fallback scan은 `mcp_jobs._scan_outputs_for_filename()`입니다.
   - 제안: complete 판정 로직을 `_resolve_completed_candidate(rec.expected_filename)` 같은 helper로 합치고, primary와 fallback 모두에 동일한 translation completeness gate를 적용하십시오. T15로 "paper_meta missing/corrupt + source PDF present + missing `_ko.md` -> error"를 추가해야 합니다.

2. [high] smart-rename cleanup도 fallback scan을 사용하지 않아 paper_meta 손상 시 복구가 실패합니다.
   - 인용: spec §5.3 lines 202-219의 `_cleanup_smart_renamed_paper()`는 `_papers.find_processed_paper(original_filename=expected_filename)`만 호출합니다. spec §11 line 293은 이 함수가 fallback scan을 갖는다고 전제합니다.
   - 코드 근거: `viewer/app/services/papers.py:633-636`은 `paper_meta.json`의 `original_filename` match에서만 original_filename lookup을 반환합니다. 파일명 기반 fallback scan은 `viewer/app/services/mcp_jobs.py:295-304`에 별도 구현되어 있습니다.
   - 영향: metadata가 없거나 깨진 smart-renamed partial folder는 `cancel_job(delete_file=true)` 후에도 남습니다. 사용자가 spec의 recovery sequence를 따라도 다음 submit에서 self-duplicate 루프가 재발할 수 있습니다.
   - 제안: cleanup helper는 outputs 전용 scan을 직접 수행하거나 `_scan_outputs_for_filename()`을 재사용하되 archives는 절대 삭제하지 않도록 outputs 우선 전용 helper로 분리하십시오. T16으로 "paper_meta missing + outputs folder contains expected PDF + cancel error cleanup -> folder removed"를 추가해야 합니다.

3. [high] outputs와 archives가 동시에 match할 때 newest-wins가 cleanup과 partial detection을 우회시킬 수 있습니다.
   - 인용: spec §5.3 lines 209-214는 `find_processed_paper()` 결과가 archives면 cleanup을 하지 않는다고 합니다. 사용자 요청 범위에도 "find_processed_paper가 outputs+archives 둘 다 매치하는 경우"가 포함되어 있습니다.
   - 코드 근거: `viewer/app/services/papers.py:621-631`은 outputs와 archives 후보를 모두 모은 뒤 mtime 최신순으로 정렬합니다. archive 복사본이 더 최신이면 `find_processed_paper()`는 archives를 반환할 수 있습니다.
   - 영향: 같은 `expected_filename`을 가진 partial outputs folder와 archived folder가 동시에 있으면, cleanup helper가 archives hit를 보고 no-op 할 수 있습니다. reconcile도 archives hit를 complete로 처리하면서 outputs partial을 그대로 남길 수 있습니다.
   - 제안: MCP job recovery에서는 generic `find_processed_paper()`에 의존하지 말고, "outputs-side match가 있으면 outputs를 우선 검사/정리하고 archives는 보존"이라는 정책을 별도 helper로 고정하십시오. T17로 "outputs partial + archives complete both match -> reconcile flags outputs partial or cleanup removes outputs partial"을 추가해야 합니다.

4. [high] `list_jobs`가 reconcile을 수행한다는 migration 설명이 현재 코드와 맞지 않습니다.
   - 인용: spec §8 line 271은 "next status query or next list_jobs"에서 transition된다고 합니다.
   - 코드 근거: `viewer/app/routers/mcp_router.py:136-145`의 `list_jobs()` tool은 `mcp_jobs.list_jobs()`만 호출하고, `viewer/app/services/mcp_jobs.py:419-430`의 `list_jobs()`도 index를 읽어 반환할 뿐 reconcile하지 않습니다.
   - 영향: 오래된 partial job은 list 화면/도구 응답에서 계속 `complete`로 보일 수 있습니다. 사용자가 list 결과의 download URL 또는 저장된 URL을 사용하면 위 critical #2와 연결됩니다.
   - 제안: either spec의 migration 문구에서 list_jobs를 제거하거나, `list_jobs(reconcile=True)` 정책을 명시하고 구현하십시오. ship-ready 회귀 보호에는 "list_jobs legacy partial complete -> error로 갱신 또는 적어도 complete로 노출하지 않음" 테스트가 필요합니다.

## Medium

1. [medium] outputs folder가 reconcile 중 사라지는 race를 partial translation error로 오분류할 수 있습니다.
   - 인용: spec §5.2.1 lines 93-105의 `_paper_has_ko_md()`는 `iterdir()` 예외를 `False`로 반환합니다. spec §5.2.2 lines 120-128은 `False`를 곧바로 `translation_missing` error로 전환합니다.
   - 영향: cleanup_expired_jobs, 사용자 수동 archive/delete, 또는 외부 정리와 race가 나면 실제 상태는 "folder disappeared/moved"인데 사용자는 "translation_missing, cancel_job 후 resubmit" 안내를 받습니다.
   - 제안: `_paper_has_ko_md()`가 missing/inaccessible과 "present but no `_ko.md`"를 구분하게 하십시오. 예: `None` 또는 enum을 반환하고, paper_dir가 사라진 경우에는 `safe_paper_dir`/fallback 재조회 후 410-style error나 normal "file disappeared" branch로 보내십시오. T18로 reconcile 중 folder 삭제 race를 추가하십시오.

2. [medium] fail-closed 정책은 translation-disabled 배포에서 운영 회귀를 만들 수 있습니다.
   - 인용: spec §5.2.2 lines 140은 "False positives ... are recoverable"이라고 평가합니다.
   - 영향: config.json이 일시적으로 깨지거나 viewer mount가 누락되면, translation-disabled deploy의 정상 English-only 결과 전체가 error로 떨어집니다. 사용자 입장에서는 `cancel_job(delete_file=true)`를 실행하면 정상 결과를 삭제할 수 있어 "recoverable"이라고 보기 어렵습니다.
   - 제안: "missing/unreadable config"와 "corrupted config"를 같은 fail-closed로 묶지 마십시오. config를 viewer에서 안정적으로 읽을 수 있게 만든 뒤, corrupted JSON은 startup/runtime health error로 드러내는 편이 낫습니다. 최소한 error message에 "translation config unreadable; not deleting may be appropriate" 같은 다른 안내가 필요합니다.

3. [medium] `cancel_job(status=error, delete_file=true)`가 cleanup 성공/실패를 표현하지 않습니다.
   - 인용: spec §5.3 lines 180-190은 cleanup을 best-effort로 수행한 뒤 status를 그대로 `error`로 반환합니다. `mcp_router.py:127-133`의 tool 응답은 `{"job_id", "status"}`뿐입니다.
   - 영향: cleanup이 no-op이어도 사용자와 클라이언트는 구분할 수 없습니다. 이후 `submit_paper(force_reprocess=true)`가 다시 self-duplicate로 실패하면 recovery protocol이 불투명해집니다.
   - 제안: 새 tool은 필요 없지만 `cancel_job`의 return payload에 `cleanup_attempted`, `cleanup_deleted`, `cleanup_warning` 중 최소 하나를 추가하거나, JobRecord.error를 cleanup 결과로 갱신하는 정책을 spec에 명시하십시오. 상태 전이를 `cancelled`로 바꾸지 않는 결정 자체는 적절합니다.

4. [medium] 테스트 T1-T13은 핵심 regression 경계가 부족합니다.
   - 누락된 테스트: legacy `status=complete` partial 재검증, direct zip stale complete 차단, fallback scan path missing `_ko.md`, outputs+archives 동시 match, config path/mount translation-disabled, reconcile 중 outputs folder disappearance, metadata missing cleanup, repeated `cancel_job(delete_file=true)` after error cleanup.
   - 제안: 위 critical/high 항목의 T14-T18을 추가하십시오. 현재 T12/T13은 이미 `status=error`인 job만 검증해서 v1에서 실제로 발생한 "`status=complete`로 잘못 저장된 partial job" 회귀를 잡지 못합니다.

5. [medium] `PROCESS_TIMEOUT_SECONDS=7200`는 좋은 mitigation이지만 bug #1의 완료 조건은 "기본값 상승"뿐입니다.
   - 인용: spec §5.1 lines 57-64는 compose env var 추가만 제안합니다.
   - 영향: compose를 쓰지 않는 실행 경로나 이미 배포된 컨테이너가 env를 받지 못한 경우에는 기존 2400초 kill이 그대로입니다. no-change 제약 때문에 허용 가능한 선택이지만, v1.1의 manual smoke에는 converter 컨테이너 내부에서 `PROCESS_TIMEOUT_SECONDS=7200`이 실제 적용됐는지 확인하는 단계가 필요합니다.
   - 제안: 테스트/검증 계획에 `docker compose exec paperflow-converter sh -lc 'echo $PROCESS_TIMEOUT_SECONDS'` 또는 watch log의 timeout 값 확인을 넣으십시오.

## Checked Non-Issues / Opinion

- JobRecord의 `paper_name`이 None인 `cancel_job` 경로는 blocker로 보이지 않습니다. spec의 cleanup은 `rec.expected_filename`을 사용하므로 `paper_name`에 의존하지 않습니다.
- `translation_disabled`인데 기존 `_ko.md`가 있는 mixed state는 complete 처리되는 것이 맞습니다. config가 정상적으로 읽힌다는 전제에서는 `_ko.md` 존재 여부를 강제하지 않는 현재 정책이 기존 동작 보존에 부합합니다.
- `cancel_job(delete_file=true)`가 `status=error`에서 호출된 뒤 reconcile이 partial을 다시 감지하는 무한 루프는 현재 spec 형태에서는 크지 않습니다. `reconcile_job()`가 error를 terminal로 보는 한 반복 감지는 일어나지 않습니다. 다만 cleanup 실패가 숨겨지는 문제는 medium #3입니다.
- opinion: v1.1에서 `main_terminal.py`의 self-duplicate bug를 직접 고치지 않고 MCP recovery로 우회하는 방향은 제약을 지키려면 합리적입니다. 다만 그 선택은 MCP 쪽 detection/cleanup이 확실히 fail-closed해야만 성립합니다. 현재 rev1은 stale complete, zip direct path, fallback scan, config 접근 문제가 남아 있어 그 조건을 아직 만족하지 못합니다.

추가 라운드 필요: legacy `complete` 재검증, zip/list reconcile 경로, viewer의 config.json 접근, fallback/cleanup scan 경로가 닫히지 않아 v1.1 핵심 버그가 남을 수 있습니다.
