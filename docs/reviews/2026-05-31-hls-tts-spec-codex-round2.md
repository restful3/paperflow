# PaperFlow HLS 실시간 한국어 TTS 스펙 재리뷰 R2 (Codex)

작성일: 2026-05-31
리뷰 대상: `docs/superpowers/specs/2026-05-31-paperflow-hls-streaming-design.md` R1
비교 기준: `docs/reviews/2026-05-31-hls-tts-spec-codex.md`

## 결론

R1은 1차 리뷰의 핵심 지적을 대부분 정확히 반영했습니다. 특히 세그먼트 URI, `TARGETDURATION` 하드 게이트, 세그먼트 원자 publish, 2층 manifest, `/audio/html` streaming 허용, sweep 기본 OFF+캡, file lock, TTL cleanup, partial 실패 정책은 구현 전에 반드시 필요했던 구조이고 지금 스펙에는 들어가 있습니다.

잔존 평가는 다음입니다.

- 남은 **BLOCKING: 0건**
- 남은 **HIGH: 4건**

즉, 원래 BLOCKING 5건은 "구현 금지" 수준에서는 해소됐습니다. 다만 signed token과 sub-split 쪽은 아직 구현자가 서로 다르게 해석할 수 있는 여지가 있어, 구현 착수 전에 아래 HIGH 4건을 스펙에 못 박는 편이 안전합니다.

## 1차 BLOCKING 반영 평가

### BLOCKING #1: playlist 세그먼트 URI/API 불일치

해소됐습니다. R1은 playlist URI를 `seg/seg_NNNNNN.ts`로 바꿨고, `/api/papers/X/audio/stream.m3u8` 기준 상대 해석이 `/api/papers/X/audio/seg/seg_NNNNNN.ts`가 된다고 명시했습니다 (`5.2`, 라인 101-118).

주의할 점은 이것이 URL 라우팅 규칙이지 파일시스템 레이아웃 규칙은 아니라는 점입니다. 산출물 레이아웃은 여전히 HLS 디렉터리 바로 아래 `seg_000000.ts`처럼 보입니다 (`3`, 라인 52-55). 구현자는 playlist의 `seg/`를 디스크 subdirectory로 해석하지 말고, `/audio/seg/{seg}` 라우터가 manifest의 HLS 디렉터리 아래 `seg_000000.ts`를 찾도록 해야 합니다. 이건 BLOCKING은 아니지만 구현 주석으로 남기는 것이 좋습니다.

### BLOCKING #2: `TARGETDURATION` 보장 부재

해소됐습니다. R1은 고정 16초를 제거하고, 구현 전 실측으로 `TARGETDURATION`과 문장 hard cap을 확정하며, publish 전 `duration > TARGETDURATION` 세그먼트를 금지한다고 적었습니다 (`5.3`, 라인 120-125, `12.0`, 라인 211-213).

다만 post-encode 하드 게이트가 걸렸을 때의 동작은 더 구체화해야 합니다. "publish 금지"만 있고, 해당 문장을 즉시 재분할해서 계속 진행할지, job을 `failed_partial`로 닫을지, 한 번 더 sub-split retry를 할지가 분명하지 않습니다. 권장 규칙은 다음입니다.

- chunker hard cap은 1차 예방책.
- 그래도 ffprobe duration이 초과하면 해당 chunk를 더 작은 sub-sentence로 재분할해 재시도.
- 재시도 후에도 초과하면 `failed_partial`로 ENDLIST를 붙이고 멈춤.

이 보강은 HIGH까지는 아니지만, 구현 플랜에 넣어야 합니다.

### BLOCKING #3: iOS native HLS 인증 쿠키 단일 의존

대체로 해소됐지만, signed token 설계는 아직 HIGH 이슈가 남아 있습니다. R1은 segment 요청을 쿠키 없이 HMAC token으로 통과시키고, playlist 요청도 쿠키 미전송 시 `?ptoken=` fallback을 둔다고 했습니다 (`7`, 라인 142-152). 원래 "signed URL/session token 대안을 스펙에 포함하라"는 blocking 요구는 충족했습니다.

하지만 현재 문구는 `/audio/stream.m3u8` 자체를 여전히 쿠키 게이트로 두고, `ptoken`은 "만약 네이티브가 playlist에도 쿠키를 안 붙이면" 쓰는 fallback입니다. iOS native path에서 가장 깨지기 쉬운 첫 playlist 요청을 optional fallback으로 두면 구현자가 기본 경로만 만들고 실기기에서 늦게 발견할 수 있습니다. 아래 HIGH #1에서 별도로 제안합니다.

### BLOCKING #4 / HIGH: streaming manifest와 `/audio/html` 충돌

해소됐습니다. R1은 segmentation 직후 전체 `chunks[]` 텍스트/DOM을 publish하고, `start_sec/end_sec`만 증분 갱신하며, `/audio/html`은 streaming 중에도 전체 span HTML을 반환한다고 명시했습니다 (`2`, 라인 31-33, `4`, 라인 81-92, `9`, 라인 176-179, `10`, 라인 188-190).

이 구조면 "본문 전체 표시"와 "timing 확정분만 하이라이트"가 공존합니다. `chunk.id` keyed replacement도 append 중복 문제를 잘 막습니다.

### BLOCKING #5: sweep foreground starvation

v1 기준으로 해소됐습니다. R1은 sweep를 기본 OFF로 바꾸고, 짧은 논문 N개/최대 M분 cap을 둔다고 했습니다 (`1`, 라인 22-25, `2`, 라인 35, `12.1`, 라인 221). 완전 preemption은 v1.1 비목표로 분리했습니다 (`14`, 라인 238).

이건 "foreground 선점 보장"을 구현한 것은 아니지만, 기본 OFF+캡이면 v1에서 사용자 요청을 장시간 막는 위험을 기본 동작에서 제거합니다. cap의 실제 기본값은 구현 플랜에서 숫자로 고정해야 합니다.

## 남은 HIGH

### HIGH #1: signed playlist URL fallback이 1급 API가 아님

현재 R1은 segment token은 1급 설계로 잘 들어갔지만, playlist token은 fallback 문구에 머물러 있습니다 (`7`, 라인 149-150, `10`, 라인 186, `15`, 라인 245). `/audio/stream.m3u8` endpoint 표에는 `ptoken` 검증 경로가 없습니다 (`9`, 라인 174-179).

이 상태의 위험은 두 가지입니다.

- iOS native `<audio src>`가 첫 playlist 요청에 쿠키를 안 붙이면 segment token 주입 단계까지 도달하지 못합니다.
- fallback이 "필요 시"라서 구현자가 실기기 실패 후에야 추가할 가능성이 큽니다.

권장 수정:

- `GET /audio/stream-url` 또는 manifest 응답에 `hls.signed_playlist_url`을 추가해, 인증된 HTML/API가 `stream.m3u8?ptoken=...`을 발급받는 흐름을 명시하십시오.
- iOS native 경로는 가능하면 signed playlist URL을 기본값으로 쓰고, 쿠키 playlist는 hls.js/개발 편의 경로로 두십시오.
- `/audio/stream.m3u8?ptoken=...`은 쿠키 없이 playlist token을 검증하고, 그 응답에서 segment URI에 fresh segment token을 주입한다고 endpoint 표에 넣으십시오.

### HIGH #2: token 재발급 cadence와 playlist cache 정책이 충돌할 수 있음

R1의 token TTL 기본값은 12h입니다 (`7`, 라인 146-152). streaming playlist는 `no-cache, no-store`라 괜찮지만, complete playlist는 `private, max-age` 가능하다고 되어 있습니다 (`9`, 라인 176). 그런데 서버가 playlist 응답마다 segment URI에 `?token=<fresh>`를 주입한다면, complete playlist response 자체도 bearer token 묶음입니다.

위험:

- VOD client가 playlist를 1회 fetch하고 12h 뒤 segment를 요청하면 token이 만료됩니다.
- browser/proxy가 complete playlist를 token TTL보다 오래 cache하면, 재생 재개 시 expired segment token만 보게 됩니다.
- native player는 segment 401을 받은 뒤 JS가 token을 갱신하기 어렵습니다.

권장 수정:

- tokenized playlist는 complete라도 `Cache-Control: private, no-cache` 또는 `max-age <= min(300s, token_remaining)`로 제한하십시오. segment 파일만 immutable cache 대상입니다.
- segment token TTL은 `max(AUDIO_TOKEN_TTL, audio.duration_sec + resume_grace)`처럼 VOD duration과 grace를 반영하거나, complete VOD에는 더 긴 별도 TTL을 쓰십시오.
- segment 401/403 발생 시 프론트가 audio element를 새 signed playlist URL로 remount하는 회복 경로를 명시하십시오. hls.js는 error handler에서 가능하고, native는 `audio.src` 재설정이 필요합니다.

### HIGH #3: query token 로그 노출 방어가 스펙에 없음

R1은 token이 paper×버전에 묶이고 유출 시 해당 오디오만 노출된다고 설명합니다 (`7`, 라인 146-149). 하지만 token은 query string에 들어가므로 다음 위치에 남습니다.

- viewer/tts reverse proxy access log
- FastAPI/uvicorn access log
- browser devtools, crash/error telemetry
- hls.js error log 또는 JS console
- 외부 origin으로 이동할 때 Referer 헤더 일부 환경

12h bearer token이 로그에 남는 것은 개인용이라도 운영 보안상 HIGH입니다.

권장 수정:

- access log에서 `token`/`ptoken` query parameter를 redaction하는 정책을 스펙에 넣으십시오.
- 프론트는 `audio.src` 전체 URL을 console/error report에 찍지 않는다고 명시하십시오.
- viewer 페이지에 `Referrer-Policy: same-origin` 또는 더 엄격한 정책을 적용하십시오.
- 가능하면 token 값을 짧은 opaque id로 두고 서버 측 HMAC/expiry 검증값을 별도 저장하지 않는 구조는 유지하되, 로그에는 token hash prefix만 남기십시오.

### HIGH #4: sub-split highlight schema가 아직 불완전함

sub-split 방향은 현실적입니다. "문장 1개 = 세그먼트 1개" 결정은 정확히는 "UI 문장 1개 = segment group 1개, TTS sub-sentence 1개 = HLS segment 1개"로 바뀐 것으로 봐야 합니다. 긴 한국어 문장, 괄호/수식/인용문을 생각하면 이 절충이 더 안전합니다.

다만 R1의 manifest schema에는 `sentence_group_id`가 없습니다 (`4`, 라인 81-85). `5.3`에서는 동일 문장 그룹으로 묶는다고 말하지만 (`5.3`, 라인 123-125), schema와 frontend merge 규칙에는 그 필드가 반영되지 않았습니다. 마지막 잔여 항목도 "그룹 단위 vs sub-span 표현"으로 남아 있습니다 (`15`, 라인 242-243).

권장 수정:

- `chunks[]`에 `sentence_group_id`, `sub_index`, `sub_count`, `display_sentence_index`를 추가하십시오.
- DOM span은 sub-span을 만들되 같은 `sentence_group_id`를 공유하게 하십시오. 그러면 currentTime 기준으로 sub-span만 칠하거나, 같은 group 전체를 칠하는 두 UX를 모두 지원할 수 있습니다.
- "이어듣기/position 저장"은 segment chunk id가 아니라 `sentence_group_id + currentTime` 기준으로도 복원 가능해야 합니다.
- 그룹 highlight를 택한다면 group의 active 조건을 `any subchunk start_sec <= t < end_sec`로 명시하십시오.

이 보강 없이는 구현자가 `sentence_index`만 유지한 채 sub-sentence 여러 개를 만들거나, 반대로 sub-sentence마다 새 문장처럼 표시해서 하이라이트와 문장 탭 UX가 깨질 수 있습니다.

## MEDIUM / 구현 메모

1. `AUDIO_TOKEN_SECRET`을 `JWT_SECRET_KEY`와 재사용 가능하다고 했는데, 가능하면 별도 secret을 권장합니다. 최소한 secret rotation 시 기존 HLS token invalidation이 어떤 UX가 되는지 적어야 합니다.
2. token payload는 `source_id|sha12|exp`만 포함합니다. PaperFlow가 다중 사용자/공유 환경으로 가면 user/session/audience binding이 필요합니다. 개인용 단일 사용자라면 지금도 허용 가능합니다.
3. stale streaming manifest 복구에서 `failed`와 `abandoned` 중 하나를 고르십시오. 프론트가 보여줄 상태와 재시도 버튼 조건이 달라집니다.
4. partial 실패 후 "이어서 생성/재시도"는 기존 segment를 재사용할지, 새 sha12/version으로 처음부터 재생성할지 정해야 합니다. v1은 새 version 재생성이 단순합니다.
5. complete playlist가 EVENT+ENDLIST이면 VOD로 동작합니다. 이 상태에서 seek 테스트를 iPhone Safari preflight에 포함한 점은 좋습니다.

## 요청 포인트별 답변

### 1. 반영이 충분/정확한가

대체로 충분하고 정확합니다. 기존 BLOCKING 5건은 모두 해소됐다고 봅니다. 단 signed playlist URL, token cache/reissue, query log redaction, sub-split schema는 구현 전에 HIGH로 보강해야 합니다.

### 2. signed token 설계 허점

segment token 자체는 방향이 맞습니다. 허점은 playlist가 아직 쿠키 게이트라는 점, 12h TTL이 "VOD playlist 1회 fetch 후 장시간 pause/resume"에는 약하다는 점, complete playlist cache와 token expiry가 충돌할 수 있다는 점, query token 로그 노출 방어가 빠졌다는 점입니다. 위 HIGH #1-#3을 반영하면 v1로 충분합니다.

### 3. sub-split과 하이라이트 span 그룹

현실적입니다. 오히려 긴 문장을 안전하게 HLS로 내보내려면 필요합니다. 하지만 schema가 아직 그룹 모델을 표현하지 못합니다. UI 문장과 HLS segment를 분리하는 필드를 manifest에 넣어야 합니다.

### 4. 남은 BLOCKING/HIGH

- BLOCKING: 0건
- HIGH: 4건
  1. signed playlist URL fallback을 1급 API로 명시 필요
  2. token 재발급 cadence와 complete playlist cache 정책 보강 필요
  3. query token 로그 노출 방어 필요
  4. sub-split highlight/group schema 보강 필요
