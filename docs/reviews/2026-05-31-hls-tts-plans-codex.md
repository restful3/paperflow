# HLS 실시간 TTS 구현 플랜 리뷰 - Codex

_작성: 2026-05-31_

## 결론

아직 구현 착수 승인 수준은 아닙니다. R2 스펙의 큰 방향은 대부분 태스크로 내려왔지만, 핵심 스트리밍 동작과 보안/복구 항목에 잔존 BLOCKING 이 있습니다. 특히 프론트 플랜은 생성 시작 후 `ready` 전까지 HLS를 mount 하지 못해 "첫 1~3 세그먼트부터 재생" 목표가 깨지고, 백엔드 플랜은 TARGETDURATION 초과 시 재분할 재시도와 stale 복구가 빠져 있습니다.

- 잔존 BLOCKING: 4
- 잔존 HIGH: 9

## BLOCKING

1. **TARGETDURATION 초과 후 재분할 재시도가 빠졌습니다.**
   - 스펙 §5.3 은 "인코딩 후 `duration > TARGETDURATION` 이면 더 작은 sub-sentence 로 재분할 후 1회 재시도, 그래도 실패하면 `failed_partial`" 입니다.
   - 백엔드 플랜 Task 3 은 `encode_segment()` 에서 길이 초과를 `ValueError` 로만 만들고, Task 5 는 그 예외를 즉시 `_fail_partial()` 로 전이합니다. 재분할 재시도 태스크와 테스트가 없습니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:378`, `:622-625`
   - 수정: `job.py` 태스크에 post-encode over-length 전용 경로를 추가하세요. 원 chunk 텍스트를 더 작은 sub-chunk 로 분할하고 manifest/playlist/chunk id 전략을 명확히 해야 합니다. 구현 난이도 때문에 더 보수적인 대안은 Task 0 cap 에 안전계수를 높이는 것이지만, 그래도 스펙의 1회 재시도 acceptance 는 필요합니다.

2. **프론트 플랜은 생성 중 streaming mount 를 시작하지 않습니다.**
   - 기존 흐름은 `generateAudio()` 후 `pollAudioJob()` 이 `/audio/status` 만 보다가 `stage === 'ready'` 일 때만 `loadAudio()` 를 호출합니다. 프론트 플랜 Task 2 도 `loadAudio()` 자체만 streaming 대응으로 바꾸고, 생성 시작 후 `streaming` manifest/playlist 를 주기적으로 탐색하는 경로를 추가하지 않습니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-frontend.md:80-93`
   - 결과: 최초 생성 케이스에서 사용자는 HLS가 자라는 동안 플레이어를 mount 하지 못하고, 기존 배치판처럼 완료 후에야 `loadAudio()` 됩니다. 스펙의 핵심 목표인 첫 1~3 세그먼트 재생이 실패합니다.
   - 수정: `pollAudioJob()` 에서 `segmenting/synthesizing` 중에도 `loadAudio()` 또는 `tryAttachStreamingAudio()` 를 호출하고, `stream-url` 이 404 면 1~2초 후 재시도하세요. backend Task 5 도 manifest publish 와 playlist publish 순서의 짧은 404 window 를 고려해야 합니다.

3. **viewer 토큰 모듈 복제 경로가 코드와 맞지 않아 API가 런타임 실패합니다.**
   - 플랜은 사본을 `viewer/app/services/tts_token.py` 로 만들라고 하면서, 실제 import 예시는 `from app.tts_token import mint/verify` 입니다. 이 경로는 존재하지 않으므로 `/audio/stream-url`, `/audio/stream.m3u8`, `/audio/seg/{seg}` 가 500 이 됩니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:1035-1038`, `:1052`, `:1070`, `:1080`
   - 같은 코드 블록은 `get_current_user_page` 도 import 하지 않습니다. 기존 `viewer/app/routers/api.py` 는 `get_current_user_api` 만 import 합니다.
   - 수정: `from ..services.tts_token import mint, verify` 로 고정하고, 파일 경로/commit 대상/테스트 import 를 일치시키세요. 복제 자체는 컨테이너 경계상 수용 가능하지만, byte-identical 보장을 테스트해야 합니다.

4. **stale streaming manifest 복구가 구현 태스크에서 빠졌습니다.**
   - 스펙 §8.4 는 `status="streaming"` 이고 `heartbeat` 가 30분 이상 멈춘 경우 다음 접근/sweep 시 `failed` 로 전이하고 재생성을 허용해야 합니다.
   - 백엔드 플랜은 이를 self-review 에서 "후속" 으로 넘깁니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:1178`, `:1182-1183`
   - 수정: Task 8/9 또는 별도 Task 로 `audio_manifest`, `audio_stream_url`, sweep candidate 진입 시 stale 검사와 atomic manifest 전이를 추가하세요. 테스트는 frozen heartbeat 로 `streaming -> failed` 전이를 검증해야 합니다.

## HIGH

1. **query token 로그 redaction 이 실제 구현이 아닙니다.**
   - Task 9 의 미들웨어는 no-op 이고, 실제 대책은 docker-compose 주석으로 밀립니다. R2 합의 항목은 access log/reverse proxy/redaction 중 하나를 구현 플랜에 포함하는 것이었습니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:1092-1104`, `:1134-1138`
   - 수정: 최소한 uvicorn access log 를 viewer/tts 컨테이너에서 끄거나, logging filter 를 실제로 wiring 하세요. 테스트는 `token=`/`ptoken=` 이 로그 sink 에 남지 않는지 확인해야 합니다.

2. **v2 mp3 fallback/download 경로가 기존 router 와 연결되지 않습니다.**
   - Task 8 은 새 함수 `mp3_file_path()` 를 만들지만, 기존 `/audio/file` 라우터는 `audio_svc.audio_file_path()` 를 계속 호출합니다. 기존 함수는 v1 `audio.file` 만 읽습니다. `viewer/app/routers/api.py:667-685`, `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:913-919`
   - 결과: HLS 불가 시 v2 `audio.mp3.file` fallback 이 404 가 됩니다.
   - 수정: 기존 `audio_file_path()` 를 v1/v2 지원으로 확장하거나 router 를 `mp3_file_path()` 로 바꾸세요. 테스트는 v2 manifest 에서 `/audio/file` 200 을 검증해야 합니다.

3. **`is_fresh_for_playback()` v1 테스트가 현 구현 계획과 모순됩니다.**
   - 테스트는 `tts: {}` 인 v1 manifest 를 fresh 로 기대하지만, 제안 구현은 `_cachekey_match()` 를 호출하므로 `CACHE_KEY_FIELDS` 가 모두 missing 이라 False 입니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:466-470`, `:520-538`
   - 수정: v1도 기존 `is_fresh()` 와 같은 cachekey 정책을 유지할지, legacy missing-tts 를 허용할지 결정하고 테스트/구현을 맞추세요.

4. **sweep candidate 테스트와 구현이 sha/cachekey freshness 를 실제로 검증하지 않습니다.**
   - 테스트 주석은 "complete v2 manifest 있으면 후보 아님" 이라면서 sha 불일치면 후보라고 기대합니다. 구현은 sha 를 계산하지 않고 `schema_version>=2 && complete && audio.hls` 만 보면 fresh 로 간주합니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:716-721`, `:754-762`
   - 수정: sweep 은 `is_fresh_for_hls(manifest, current_sha)` 를 호출해야 합니다. `_ko_audio.md` sha 계산을 테스트에 포함하세요.

5. **TTL cleanup 이 스펙보다 약하고 mp3 를 정리하지 않습니다.**
   - Task 5 cleanup 은 HLS 디렉터리만 삭제하고, old mp3 는 남깁니다. 또 `glob` 결과에 mp3 파일도 섞인 상태에서 `dirs.index(p) >= keep` 를 쓰므로 보존 개수 계산이 왜곡됩니다. age 기준 `max(duration_sec, 1h)` 도 없습니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:664-671`
   - 수정: HLS dir 과 mp3 를 version 단위로 묶어 최근 N 또는 age 기준으로 정리하고, active token TTL 보다 짧게 삭제하지 않도록 테스트하세요.

6. **segment token TTL 이 R2 cadence/cache 정책과 덜 맞습니다.**
   - 스펙은 segment TTL 을 `max(AUDIO_TOKEN_TTL, audio.duration_sec + resume_grace)` 로 정의했습니다. 플랜은 `AUDIO_TOKEN_TTL + AUDIO_RESUME_GRACE` 로 고정합니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:1059`
   - 수정: manifest duration 을 읽어 `max()` 로 계산하고, complete VOD/streaming 각각의 cache header 도 테스트하세요. streaming playlist 는 `no-cache, no-store`, tokenized complete playlist 는 `private, no-cache` 로 분리해야 합니다.

7. **frontend `failed_partial` 처리가 빠져 polling 이 끝나지 않을 수 있습니다.**
   - 백엔드 Task 7 은 `_jobs` stage 를 `failed_partial` 로 둘 수 있지만, 프론트 기존 `pollAudioJob()` 은 `ready`/`failed` 만 처리합니다. 프론트 플랜도 이 부분을 수정하지 않습니다. `viewer/app/templates/viewer.html:1946-1953`, `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:821-825`
   - 수정: `failed_partial` 은 생성 polling 을 멈추고 `loadAudio()` 로 partial HLS 를 mount 해야 합니다.

8. **프론트 TDD 가 대부분 수동 검증이라 핵심 동작 회귀를 잡지 못합니다.**
   - Plan 2 는 hls attach, token remount, id-keyed merge, group highlight 를 대부분 "수동 검증" 으로 둡니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-frontend.md:127-129`, `:166-168`, `:268-270`, `:333-365`
   - 수정: 최소 Playwright/JSDOM 수준으로 `audio.hls` manifest -> `/stream-url` 호출, `start_sec` merge 중복 없음, `sentence_group_id` 전체 active, hls.js NETWORK_ERROR 시 remount 호출을 자동화하세요.

9. **Task 0 실측은 BLOCKING 으로 둔 점은 맞지만 표본/상수 고정 방식이 약합니다.**
   - 현재 예시는 `_ko_audio.md` 3개와 chunk 120개만 측정합니다. 긴 논문 tail/P100 을 결정하는 BLOCKING 단계라면 대표 표본 기준과 실패 시 fallback 을 더 명확히 해야 합니다. `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md:55-76`
   - 수정: corpus 전체 또는 최소 대표 long-tail 표본 수를 명시하고, Task 2/3 에 "placeholder scan fails if 16/220 remain" 같은 자동 검사를 추가하세요.

## 정합성 메모

- `job.py` 재작성은 기존 `_chunk_ok()` 와 GPU flock 을 유지하는 방향은 맞습니다. 다만 "heading 제외(MVP 동일)" 설명은 현재 코드와 다릅니다. 현재 `tts_service/app/job.py` 는 heading 도 합성합니다. 새 정책이 heading 제외라면 의도적으로 바뀌는 동작이므로 테스트와 UX 문구를 수정해야 합니다.
- `manifest.py` 에 v1 함수를 유지하며 v2 함수를 추가하는 방향은 안전합니다. 단, `is_fresh()` 를 새 `is_fresh_for_playback()` 으로 대체할 때 기존 v1 cachekey semantics 를 깨지 않아야 합니다.
- `/audio/stream-url`, `/audio/stream.m3u8`, `/audio/seg/{seg}` 라우트 자체는 기존 greedy `{name:path}` 패턴과 구조적으로 충돌하지 않습니다. 단, Live TTS 라우트 블록에 함께 두고 `/audio/progress` 같은 이름을 추가하지 않는 전제가 필요합니다.
- `get_current_user_page` 를 `stream.m3u8` fallback auth 에 쓰는 방식은 적절합니다. ptoken 이 있으면 쿠키 없이 통과하고, ptoken 이 없을 때만 쿠키를 개발 편의 경로로 쓰는 구조가 스펙과 맞습니다.
- token 모듈 복제는 컨테이너 경계 때문에 현실적인 선택입니다. 다만 drift 위험이 있으므로 동일 test vector 를 tts/viewer 양쪽에 두고, import 경로를 하나로 고정해야 합니다.

## 구현 착수 전 최소 수정 체크리스트

- post-encode over-length 재분할 재시도 태스크/테스트 추가
- 생성 중 streaming mount 진입점 추가
- viewer token import 경로와 `get_current_user_page` import 수정
- stale heartbeat 복구 태스크 추가
- 실제 log redaction 또는 access log disable 구현
- v2 `/audio/file` fallback 테스트 추가
- sweep freshness 를 sha/cachekey 기반으로 수정
- frontend 핵심 동작 자동 테스트 추가
