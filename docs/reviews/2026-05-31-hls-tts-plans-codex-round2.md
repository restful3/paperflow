# HLS TTS 구현 플랜 R1 재리뷰 - Codex Round 2

_작성: 2026-05-31_

## 결론

R1 플랜은 1차 리뷰의 BLOCKING 4개를 실질적으로 해소했습니다. 구현 착수는 가능합니다. 다만 1차 HIGH 중 TTL cleanup 의 "active token grace"가 아직 약하고, 생성 중 mount 경로에는 빈 playlist 조기 attach race 가 남아 있어 HIGH 2개는 구현 태스크에 접어 넣어야 합니다.

- 잔존 BLOCKING: 0
- 잔존 HIGH: 2

## BLOCKING 재검토

1. **과길이 처리: 해소. 재합성 절충은 수용 가능.**
   - 백엔드 플랜은 `encode_segment()` 길이 게이트 후 `_synth_encode_with_retry()` 로 1회 재합성하고, 2회 실패 시 `failed_partial` 로 전이합니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:621-665`
   - 이는 스펙 §5.3 의 "재분할 1회"와 문자 그대로 같지는 않습니다. 다만 R1 플랜은 `SENTENCE_CHAR_CAP` 를 Task 0 실측 기반으로 보수 고정하고, post-encode 초과를 "모델 이상치"로 취급하며, invalid EXTINF 를 publish 하지 않고 partial 로 닫습니다. upfront-publish/id-keyed manifest 모델을 깨지 않는 절충으로 구현 착수에는 충분합니다.
   - 전제: Task 0 의 전체/long-tail 실측과 placeholder grep guard 를 반드시 통과해야 합니다.

2. **생성 중 streaming mount 진입점: BLOCKING 은 해소, HIGH race 는 아래에 남김.**
   - 프론트 `pollAudioJob()` 이 `segmenting/synthesizing/stitching` 중에도 `loadAudio()` 를 호출하도록 바뀌었습니다. `ready` 전 HLS attach 진입점 자체는 생겼습니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-frontend.md:137-156`
   - `failed_partial` 도 폴링 종료 후 partial mount 로 처리됩니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-frontend.md:147-150`

3. **viewer token import: 해소.**
   - `tts_service/app/segtoken.py` 를 `viewer/app/services/tts_token.py` 로 복제하고, import 를 `from ..services.tts_token import ...` 로 고정했습니다. `get_current_user_page` import 도 명시됐습니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:1138-1154`
   - viewer test vector 복제도 포함되어 drift 방어가 생겼습니다.

4. **stale streaming 복구: 해소.**
   - `reconcile_stale()` 가 `heartbeat > 30min` streaming manifest 를 atomic `failed` 로 전이합니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:1039-1058`
   - `/audio/stream-url` 진입 시 호출되고, `/audio/manifest` 및 sweep candidate 진입에도 호출하라는 지시가 있습니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:1061`, `:1169-1174`

## 잔존 HIGH

1. **생성 중 attach 가 빈 playlist 에 너무 일찍 성공할 수 있습니다.**
   - `run_job()` 은 manifest publish 직후 `LivePlaylist()` 를 생성하며, 이 시점의 `stream.m3u8` 는 header 만 있고 segment line 이 없을 수 있습니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:606-612`
   - viewer `stream-url` 은 playlist 파일 존재만 보면 200 을 반환합니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:1169-1174`
   - 프론트는 `attachHls()` 가 200 을 받으면 `_audioMounted=true` 로 볼 수 있습니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-frontend.md:93-98`
   - hls.js/Safari 가 빈 EVENT playlist 를 fatal parse/error 로 취급하면 첫 세그먼트 생성 후 재attach 가 보장되지 않습니다. 수정: `stream-url` 또는 `stream.m3u8` 가 최소 1개 `seg/` line 이 있을 때만 200 을 주거나, 프론트가 `audioManifest.chunks.some(c => c.start_sec != null)` 전에는 attach 하지 않도록 하세요. Playwright 에 "0 segment streaming -> no mounted, 1 segment -> mounted" assertion 을 추가하면 충분합니다.

2. **TTL cleanup 이 active token grace 를 아직 보장하지 않습니다.**
   - R1 플랜은 HLS dir+mp3 를 sha12 버전 단위로 묶는 점은 고쳤지만, 최근 `keep=2` 만 보존하고 age/duration/token TTL 기준을 보지 않습니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:685-706`
   - 짧은 시간에 3회 이상 재생성하면 아직 유효한 segment token 을 가진 클라이언트가 삭제된 구버전 segment 를 요청할 수 있습니다.
   - 수정: 스펙 §8.3 그대로 "최근 N 보존 또는 age > max(duration_sec, 1h, AUDIO_TOKEN_TTL + AUDIO_RESUME_GRACE)" 일 때만 삭제하도록 하고, old version 3개를 빠르게 만든 뒤 TTL 미만 버전은 삭제되지 않는 테스트를 추가하세요.

## HIGH 9 반영 상태

- HIGH#1 로그 redaction: 반영. 실제 `uvicorn.access` filter wiring 과 테스트가 있습니다.
- HIGH#2 v2 mp3 fallback: 반영. `/audio/file` 이 `mp3_file_path()` 를 쓰도록 명시됐고 v2 200 테스트가 있습니다.
- HIGH#3 v1 playback freshness: 반영. schema<2 는 legacy 로 cachekey 를 skip 합니다.
- HIGH#4 sweep freshness: 반영. candidate 가 `_ko_audio.md` sha 를 계산해 `is_fresh_for_hls()` 로 판단합니다.
- HIGH#5 TTL cleanup: 부분 반영. version 단위+mp3 동시 정리는 반영됐지만 active token grace 기준이 부족해 잔존 HIGH 입니다.
- HIGH#6 segment TTL/cache: 반영. `max(AUDIO_TOKEN_TTL, duration + resume_grace)` 와 streaming/complete playlist cache 분리가 있습니다.
- HIGH#7 failed_partial frontend: 반영.
- HIGH#8 frontend 자동테스트: 반영. Playwright assertion 세트가 생겼습니다. 빈 playlist race assertion 만 추가 권장입니다.
- HIGH#9 Task 0: 반영. 전체/long-tail 표본, TARGETDURATION/SENTENCE_CHAR_CAP 공식, grep guard 가 있습니다.

## 정합성 메모 반영

- heading 포함 합성으로 정합성이 맞춰졌습니다. `kind!="text" continue` 경로가 사라지고, `total=len(chunks)`, stitch 도 전체 chunks 기준입니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:613-636`, `:709-711`
- manifest v1/v2 분리, token 복제/import, `/audio/html` streaming 허용 방향도 Plan 1/2 사이 타입이 맞습니다.

## 구현 착수 판단

구현 착수 가능입니다. 단, 위 HIGH 2개는 별도 후속으로 미루지 말고 해당 Task 구현 중 같이 반영해야 합니다. 특히 빈 playlist race 는 "첫 1~3 세그먼트부터 mount" acceptance 에 직접 닿으므로 Task 9 API 또는 Plan 2 Task 2 에 작은 guard 를 추가한 뒤 진행하는 것이 맞습니다.
