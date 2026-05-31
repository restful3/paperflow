# PaperFlow HLS 실시간 한국어 TTS 스펙 리뷰 (Codex)

작성일: 2026-05-31
리뷰 대상: `docs/superpowers/specs/2026-05-31-paperflow-hls-streaming-design.md`

## 결론

방향은 맞습니다. iPhone Safari의 오디오 MSE 제약 때문에 HLS를 주력 재생 표면으로 두고, 최종 mp3를 다운로드/폴백으로 유지하는 결정은 현재 제품 제약과 잘 맞습니다. `EVENT` 플레이리스트, 문장 단위 세그먼트, 버전드 산출물, 원자적 playlist rewrite도 큰 틀에서 정합합니다.

다만 이 스펙은 **그대로 구현 승인하기에는 아직 위험이 큽니다.** 특히 아래 5개는 구현 전에 스펙을 고쳐야 합니다.

1. `stream.m3u8` 안의 세그먼트 URI와 API 경로가 불일치합니다. 예시는 `seg_000000.ts`인데 실제 API는 `/audio/seg/{seg}`입니다.
2. `TARGETDURATION=16`의 근거가 현재 품질 게이트와 맞지 않습니다. `sec/char <= 1.5`는 절대 16초 상한이 아니며, 기존 실측 360자/40초도 이미 16초를 넘습니다.
3. iOS 네이티브 HLS의 쿠키 인증은 "동작할 가능성"은 있지만 설계의 단일 전제로 두기에는 치명점입니다. 반드시 signed URL/session token 대안을 스펙에 포함해야 합니다.
4. streaming manifest와 HTML/span 렌더링 모델이 비어 있습니다. 현재 구현의 `/audio/html`은 complete 전 409이고, 스펙의 "첫 세그먼트부터 하이라이트"와 충돌합니다.
5. sweep는 지금 설명대로면 foreground를 양보하지 않습니다. 한번 GPU 락을 잡은 sweep는 긴 논문 전체 합성 동안 사용자 요청을 막을 수 있습니다.

## 주요 Findings

### 1. BLOCKING: playlist 세그먼트 URI가 API 설계와 맞지 않음

스펙의 playlist 예시는 다음 형태입니다.

```m3u8
#EXTINF:3.214,
seg_000000.ts
```

하지만 새 API는 `/api/papers/{name}/audio/seg/{seg}`입니다. HLS 클라이언트는 media playlist URL 기준으로 상대 URI를 해석하므로, `/api/papers/X/audio/stream.m3u8` 안의 `seg_000000.ts`는 `/api/papers/X/audio/seg_000000.ts`로 요청됩니다. 스펙의 `/audio/seg/seg_000000.ts` 엔드포인트로 가지 않습니다.

제안:

- playlist URI를 `seg/seg_000000.ts`로 쓰거나,
- API를 `/audio/{seg}`로 바꾸거나,
- playlist에 절대 경로 `/api/papers/{encoded-name}/audio/seg/seg_000000.ts`를 넣으십시오.

개인적으로는 `seg/seg_000000.ts`가 가장 작고 안전합니다. 단, paper name에 slash가 들어갈 수 있으므로 절대 URL을 만들 경우에는 현재 라우팅과 동일한 인코딩 규칙을 명시해야 합니다.

근거: HLS media playlist는 media segment URI를 순서대로 제공하고 클라이언트가 해당 URI를 요청하는 구조입니다. Apple 문서도 index/playlist가 segment 파일 URL 목록을 제공한다고 설명합니다.

### 2. BLOCKING: `TARGETDURATION=16`은 현재 보장되지 않음

스펙은 `TARGETDURATION`을 16초 고정으로 두고, 품질 게이트 `sec/char <= 1.5`가 문장 길이를 제한한다고 설명합니다. 이 논리는 틀렸습니다. `sec/char`는 비율 상한이지 절대 duration 상한이 아닙니다. 20자 문장도 30초까지 통과할 수 있고, 360자 문장은 540초까지 통과할 수 있습니다. 선행 MVP 스펙의 실측도 360자/40초 합성이었으므로 16초를 이미 넘습니다.

RFC 8216 기준으로 `EXTINF` duration은 반올림했을 때 `EXT-X-TARGETDURATION` 이하이어야 합니다. 또한 `TARGETDURATION` 값은 media playlist에서 바뀌면 안 됩니다. 따라서 "넘으면 경고 로그"는 충분하지 않고, 초과 세그먼트를 publish하지 않는 하드 게이트가 필요합니다.

제안:

- 구현 전 `_ko_audio.md` 전체 corpus에서 문장별 합성 duration 분포를 재측정하고 P99/P100 기준을 정하십시오.
- `TARGETDURATION=16`을 유지하려면 `duration > 16.49s` 세그먼트는 publish 전 실패 처리하거나 문장 내부를 더 쪼개야 합니다.
- "문장 1개 = 세그먼트 1개" 결정을 유지하려면 chunker 단계에서 문장 길이 hard cap을 두고, 초과 문장은 TTS용 sub-sentence로 분할하되 UI에서는 같은 문장 그룹으로 묶는 절충이 필요합니다.
- 아니면 `TARGETDURATION`을 더 크게 잡아야 하지만, 이 값은 live playlist reload cadence에도 영향을 주므로 startup/연속 재생 지연이 커질 수 있습니다.

관련 스펙 위치: `2026-05-31-paperflow-hls-streaming-design.md:92-109`.

### 3. BLOCKING: iOS 네이티브 HLS + 인증 쿠키는 단일 성공 조건으로 두면 안 됨

같은 origin, path `/`, `SameSite=Lax` 쿠키인 현재 viewer 인증 구조에서는 Safari가 media subrequest에 쿠키를 보낼 가능성이 높습니다. 현재 쿠키 설정은 `viewer/app/auth.py`의 `set_auth_cookie()`에서 `httponly=True`, `samesite="lax"`, `path="/"`로 되어 있습니다. 하지만 iOS 네이티브 HLS는 HTML fetch/XHR이 아니라 AVFoundation/AppleCoreMedia 경로로 playlist와 segment를 다시 가져갑니다. HTML `<audio>`에서는 hls.js처럼 요청 헤더를 직접 제어할 hook도 없습니다.

Apple 문서는 HLS가 인증을 지원하고, 네이티브 앱에서는 cookie-based 또는 HTTP credentials를 저장/공급할 수 있다고 설명합니다. 그러나 이것은 앱 코드의 credential challenge 처리 이야기이고, Safari `<audio src=m3u8>`에서 PaperFlow의 HttpOnly 세션 쿠키가 항상 segment 요청까지 붙는다는 보장은 아닙니다. 실제로 이 항목은 스펙의 "확인 항목"이 아니라 **ship 전 blocking preflight**가 되어야 합니다.

제안 대안:

- 1순위: `/audio/stream.m3u8`는 인증 후 짧은 TTL의 HLS session token을 발급하고, playlist 안의 segment URI를 `seg/seg_000000.ts?token=...` 또는 `/audio/hls/{token}/seg_000000.ts`로 씁니다. token은 paper, sha12, expiry, user/session에 묶고 HMAC 서명합니다.
- 2순위: 인증된 HTML/API에서 one-time signed stream URL로 redirect합니다. native player가 쿠키를 안 보내도 query token만으로 playlist/segment가 통과합니다.
- 3순위: HLS 디렉터리는 랜덤 high-entropy URL로 두고, manifest/API 접근만 인증합니다. 개인용이라도 만료/정리 정책은 필요합니다.
- hls.js 경로는 `xhrSetup` 또는 `fetchSetup`으로 credential 포함 설정을 명시하십시오. same-origin에서는 기본으로 충분할 수 있지만, reverse proxy나 public base URL이 바뀌면 바로 깨집니다.

보안상 token은 mp3 다운로드 URL보다 더 민감합니다. playlist가 segment URL을 노출하므로 TTL, sha binding, traversal 방어, 로그 노출 가능성을 같이 적어야 합니다.

관련 스펙 위치: `2026-05-31-paperflow-hls-streaming-design.md:131-153`.

### 4. HIGH: `TARGETDURATION=16`은 reload/stall에도 불리할 수 있음

목표는 첫 문장 약 3초부터 재생입니다. 그런데 HLS client의 live playlist reload는 `TARGETDURATION`에 의해 강하게 영향을 받습니다. RFC 8216은 ENDLIST 없는 playlist에 대해 새 버전 제공 시점을 이전 playlist 기준 `0.5 * targetduration` 이후, `1.5 * targetduration` 이내로 설명합니다. `TARGETDURATION=16`이면 클라이언트가 새 playlist를 늦게 확인할 수 있고, 짧은 문장이 빠르게 생성되는 상황에서는 플레이어가 live edge를 따라가는 데 불필요한 대기나 stall이 생길 수 있습니다.

이 문제는 2번과 긴장 관계가 있습니다. 작은 targetduration은 startup/reload에 유리하지만 긴 문장 세그먼트를 허용하지 못합니다. 큰 targetduration은 spec compliance에는 편하지만 "첫 문장부터 자연스럽게 이어 재생" 목표에 불리합니다.

제안:

- 실측 후 `TARGETDURATION`을 정하되, "첫 세그먼트 publish 후 실제 iPhone Safari 첫 audible time"과 "첫 10개 문장 stall 여부"를 acceptance criterion으로 두십시오.
- 첫 playback을 반드시 1 segment부터 시작한다고 쓰지 말고, "1-3 segments available 시 자동 mount/play 가능"처럼 현실적인 하한을 잡는 편이 안전합니다.
- 짧은 문장 다수에서는 1문장=1세그먼트가 지나치게 작은 segment를 만들 수 있으므로 HLS 안정성 측면에서 최소 duration 정책도 필요합니다. 다만 승인 결정이 문장당 1세그먼트이므로, 여기서는 "너무 짧은 segment가 클라이언트별로 문제 없는지 검증"을 테스트에 넣는 수준이 적절합니다.

### 5. HIGH: segment publish도 원자적이어야 함

스펙은 playlist 원자적 rewrite를 잘 짚었습니다. 하지만 segment 파일 자체도 temp 파일에 인코딩한 뒤 `os.replace()`로 publish하고, 그 다음 playlist에 추가해야 합니다. ffmpeg가 `seg_000123.ts`를 직접 쓰는 동안 playlist가 아직 참조하지 않으면 일반적으로 괜찮지만, 실패/재시도/파일시스템 지연에서 0-byte 또는 partial segment가 남을 수 있습니다.

제안:

- `seg_000123.ts.tmp.<pid>`로 인코딩
- ffprobe로 codec/duration 검증
- `os.replace(tmp, final_ts)`
- 그 다음 manifest/playlist를 publish

실패 시에는 final 이름이 없는 상태로 유지해야 합니다. playlist가 참조한 segment는 절대 재작성하지 않는다는 불변식도 스펙에 넣으십시오.

### 6. HIGH: streaming manifest와 `/audio/html` 설계가 충돌함

스펙은 `status="streaming"` 동안 `chunks`가 늘어나고, 프론트가 이를 polling/merge해서 하이라이트 타임라인을 확장한다고 합니다. 하지만 기존 구현은 `/audio/html`이 `manifest.status != "complete"`이면 409를 반환합니다 (`viewer/app/routers/api.py:656-664`). 프론트도 `audioReady = manifest.status === 'complete'`로만 플레이어를 노출하고, `audioSrc()`는 mp3 `/audio/file`만 반환합니다 (`viewer/app/templates/viewer.html:1919-1960`).

새 스펙대로 가려면 "본문 HTML의 span은 언제 생기는가"가 결정되어야 합니다. segment가 준비된 문장만 HTML에 넣으면 글 본문이 앞부분만 보입니다. 기존 `_ko_audio.md` 정적 Markdown을 그대로 보여주면 문장 span이 없어서 하이라이트/문장 탭이 불가능합니다.

제안:

- chunker 결과는 합성 시작 전에 이미 알 수 있으므로, manifest v2를 두 층으로 나누십시오.
  - `chunks`: 전체 텍스트/DOM metadata는 segmenting 직후 전부 publish. `start_sec/end_sec`는 아직 null 가능.
  - `ready_until` 또는 `segments`: 실제 timing이 확정된 segment만 증가.
- `/audio/html`은 `streaming`에서도 전체 `chunks` 텍스트로 span HTML을 반환해야 합니다.
- `onTimeUpdate`는 `start_sec != null`인 chunk만 대상으로 삼아야 합니다.
- manifest merge는 배열 append가 아니라 `chunk.id` keyed replacement로 해야 합니다. 중복 polling, 재시도, 실패 전이에서 같은 chunk가 두 번 들어가면 currentTime mapping이 깨집니다.

이 부분을 정하지 않으면 HLS는 재생되지만 PaperFlow의 핵심 UX인 현재 문장 하이라이트가 streaming 동안 동작하지 않습니다.

### 7. HIGH: sweep는 foreground를 "양보"하지 않음

스펙은 sweep가 유휴일 때 `try_acquire`로 확인한 뒤 즉시 해제하고, 이후 기존 `run_job`이 GPU flock을 블로킹 획득한다고 합니다. 이 사이에는 race가 있습니다. 더 큰 문제는 sweep가 GPU lock을 먼저 획득하면, 현재 `run_job()` 구조상 논문 전체 합성 loop 동안 lock을 잡습니다 (`tts_service/app/job.py:61-74`). 854문장 논문이면 foreground 사용자 요청은 sweep가 끝날 때까지 기다릴 수 있습니다.

즉, 이 설계는 "착수 전에는 유휴였는지 확인"만 할 뿐, 착수 후에는 foreground/converter를 양보하지 않습니다.

제안:

- sweep는 lock check와 job start를 분리하지 말고, non-blocking으로 획득한 lock handle을 그대로 합성 함수에 넘겨야 합니다. 단, 이것만으로도 foreground preemption은 안 됩니다.
- foreground 우선순위를 보장하려면 sweep 합성은 문장 단위 또는 작은 batch 단위로 lock을 놓고, `_jobs`에 foreground pending이 생기면 중단/연기해야 합니다.
- 더 단순한 v1 정책은 sweep를 기본 off 또는 야간/수동 command로 제한하는 것입니다. 승인 결정에 sweep 포함이 있으므로, 최소한 `SWEEP_ENABLED=false` 기본값과 "짧은 논문 N개/최대 M분" cap을 두는 편이 안전합니다.
- sweep job도 `_jobs` 또는 별도 `_sweep_active`에 등록해야 foreground create가 같은 paper에 중복 job을 만들지 않습니다.

관련 코드: `tts_service/app/main.py:6-8`, `tts_service/app/main.py:47-58`, `tts_service/app/job.py:61-74`.

### 8. HIGH: in-memory `_jobs`만으로는 중복/동시성 불변식이 약함

기존 MVP도 `_jobs`가 in-memory dict입니다. HLS+sweep에서는 위험이 커집니다.

- sidecar가 재시작되면 진행 중 manifest/playlist가 남아도 `_jobs`는 `none`이 됩니다.
- uvicorn worker를 2개 이상으로 올리면 worker별 `_jobs`가 분리됩니다.
- sweep가 `run_job()`을 직접 호출하면 `_jobs`에 등록되지 않을 수 있습니다.
- 같은 paper의 foreground와 sweep가 동시에 같은 sha12 HLS 디렉터리에 쓰면 playlist/manifest 원자성만으로는 해결되지 않습니다.

제안:

- paper 단위 file lock을 추가하십시오: `audio/.locks/<sha12>.lock` 또는 `audio/<base>_ko_audio.<sha12>.lock`.
- sidecar startup에서 `workers == 1` 가정을 명시하거나, 다중 worker에서도 file lock으로 안전하게 만드십시오.
- stale streaming manifest 복구 정책을 넣으십시오. 예: manifest status `streaming`이고 heartbeat/update mtime이 30분 이상 멈췄으면 `failed` 또는 `abandoned`로 전이 후 재생성 허용.

### 9. MEDIUM: 최종 mp3 "2-pass loudnorm" 설명이 현재 구현과 다름

스펙은 현재 배치가 stitch 후 2-pass loudnorm이라고 설명하지만, 현재 구현은 ffmpeg `loudnorm=I=-16:TP=-1.5:LRA=11`를 한 번 적용합니다 (`tts_service/app/stitch.py:53-56`). 측정 pass 결과를 두 번째 pass에 넣는 true 2-pass loudnorm은 아닙니다.

트레이드오프 자체는 합리적입니다. streaming은 전체 신호를 기다릴 수 없으므로 segment 단위 single-pass 또는 fixed gain/peak normalization으로 가고, 최종 mp3는 완료 후 더 좋은 정규화를 하는 구조가 맞습니다. 다만 스펙은 실제 구현과 용어를 맞춰야 합니다.

제안:

- 현재 mp3 품질을 그대로 유지하려면 "최종 mp3도 현재와 동일한 ffmpeg loudnorm single-pass"라고 쓰십시오.
- 정말 2-pass를 목표로 한다면 `stitch.py` 변경 범위와 테스트를 스펙에 포함하십시오.
- segment별 `loudnorm`은 짧은 문장/무음이 많은 segment에서 gain pumping이 생길 수 있으므로, v1은 Chatterbox 출력 기준 fixed gain + true peak limiter가 더 예측 가능할 수 있습니다.

### 10. MEDIUM: HLS v2 manifest의 `audio.mime_type` 의미가 혼재됨

스키마 예시는 `audio.hls`, `audio.mp3`, `mime_type: "audio/mpeg"`을 같은 `audio` object에 둡니다. 이러면 `mime_type`이 HLS playlist인지 mp3인지 모호합니다. 기존 v1은 단일 mp3라 문제가 없었습니다.

제안:

```json
"audio": {
  "hls": {
    "playlist": "stream.m3u8",
    "mime_type": "application/vnd.apple.mpegurl",
    "segment_mime_type": "video/mp2t"
  },
  "mp3": {
    "file": "<base>_ko_audio.<sha12>.mp3",
    "mime_type": "audio/mpeg"
  },
  "duration_sec": 123.4,
  "sample_rate": 24000
}
```

단순화를 원하면 최소한 `audio.hls_mime_type`과 `audio.mp3_mime_type`을 분리하십시오.

### 11. MEDIUM: 하위호환 경로는 더 명시해야 함

스펙은 v1 manifest에서 `audio.hls`가 없으면 mp3 폴백한다고 되어 있습니다. 맞습니다. 하지만 실제 코드 기준으로는 다음 변경이 필요합니다.

- `viewer/app/services/audio.py:37-48`는 `audio.file`만 읽습니다. v2 `audio.mp3`를 읽도록 바꾸되, v1 `audio.file`도 계속 지원해야 합니다.
- `viewer.html:1957-1960`은 `/audio/file?file=<audio.file>`만 반환합니다. v2 HLS와 v1 mp3를 분기해야 합니다.
- `manifest.is_fresh()`는 v1 complete manifest를 "fresh"로 볼지 여부를 호출 맥락별로 나눠야 합니다. foreground 재생은 fresh로 인정해도 되지만, sweep의 "HLS 사전생성 대상" 판정에서는 v1을 stale로 봐야 합니다.

제안:

- `is_fresh_for_playback()`와 `is_fresh_for_hls()`를 분리하십시오.
- v1 mp3 사용 중에 sweep가 HLS로 업그레이드해도 기존 재생이 깨지지 않도록 old mp3/HLS cleanup에 grace period를 두십시오.

### 12. MEDIUM: 버전드 HLS 디렉터리 즉시 정리는 active playback을 깨뜨릴 수 있음

스펙은 재생성 시 구버전 HLS 디렉터리/mp3를 정리한다고 합니다. mp3는 기존 구현처럼 에러 시 manifest reload로 회복할 수 있지만, HLS segment는 playlist가 이미 client 내부에 있고 다음 segment를 계속 요청합니다. 구버전 디렉터리를 즉시 지우면 active playback이 중간에 404로 끊깁니다.

RFC 8216도 playlist에서 제거되거나 presentation이 제거될 때 segment를 충분히 오래 유지해야 한다는 방향의 요구를 둡니다. EVENT playlist는 segment를 제거하지 않는 모델이므로, published playlist가 참조한 segment는 active client가 끝까지 읽을 수 있게 유지해야 합니다.

제안:

- 구버전 HLS 디렉터리는 즉시 삭제하지 말고 TTL cleanup으로 넘기십시오. 최소 `max(audio.duration_sec, 1h)` 또는 "최근 N개 버전 유지"가 안전합니다.
- manifest가 새 버전을 가리키더라도 old playlist URL을 잡은 client가 계속 segment를 요청할 수 있다는 점을 스펙에 넣으십시오.

### 13. MEDIUM: 실패 상태의 playlist/manifest 처리 규칙이 부족함

세그먼트 N개까지 publish한 뒤 N+1에서 실패하면 어떻게 할지 정해야 합니다.

선택지는 두 가지입니다.

- partial stream을 재생 가능한 산출물로 인정한다: playlist에 `ENDLIST`를 붙이고 manifest status를 `failed_partial` 또는 `complete_partial`로 둡니다. 사용자는 앞부분만 들을 수 있습니다.
- partial stream은 실패로 간주한다: playlist는 더 이상 append되지 않고 manifest status는 `failed`입니다. 프론트는 재시도 버튼을 보여줍니다.

현재 스펙은 job `failed`, manifest `failed`만 말하고 HLS 클라이언트가 이미 재생 중인 경우를 다루지 않습니다. 개인용 UX에서는 "앞부분은 들을 수 있게 ENDLIST를 붙이고 실패 배지를 노출"하는 쪽이 더 낫지만, 다운로드 mp3는 404여야 합니다.

### 14. MEDIUM: API MIME/cache header를 구체화해야 함

권장:

- playlist: `application/vnd.apple.mpegurl; charset=utf-8` 또는 최소 `application/vnd.apple.mpegurl`. 스펙의 `text/vnd.apple.mpegurl`도 쓰이는 경우가 있지만 Safari 호환성 기준으로는 Apple vendor MIME이 더 안전합니다.
- streaming playlist: `Cache-Control: no-cache, no-store` 또는 `no-cache, must-revalidate`. reverse proxy가 있다면 buffering/cache off도 확인해야 합니다.
- complete playlist: `Cache-Control: private, max-age=...` 가능. 단 manifest 재생성/구버전 TTL과 충돌하지 않게 합니다.
- segments: content-versioned이므로 `Cache-Control: private, max-age=31536000, immutable`가 가능합니다. 인증 토큰을 query에 넣는 경우 token expiry와 cache 정책을 맞춰야 합니다.
- segment endpoint는 `Accept-Ranges`가 실제로 붙는지 smoke test에 넣으십시오. Starlette `FileResponse`가 일반 파일 Range를 처리하지만, HLS client가 TS segment에 Range를 꼭 요구하지는 않습니다.

### 15. LOW: `EVENT` 명칭은 맞지만 "live"와 "event"의 차이를 문서화하면 좋음

스펙은 HLS live playlist라고 부르면서 `EXT-X-PLAYLIST-TYPE:EVENT`를 씁니다. 이것은 의도에 맞습니다. "sliding live"가 아니라 "growing event playlist"입니다. 세그먼트를 제거하지 않고 처음부터 seek 가능하게 하려는 목표와 일치합니다. 단, 스펙에는 "진짜 live window가 아니라 EVENT growing VOD"라고 한 줄 더 적으면 구현자가 `MEDIA-SEQUENCE` 증가나 segment removal을 넣지 않습니다.

RFC 8216 기준으로 EVENT playlist는 segment를 끝에 추가만 할 수 있고, ENDLIST가 붙으면 더 이상 reload할 필요가 없습니다.

### 16. LOW: hls.js CDN 동적 로드는 운영 의존성으로 명시 필요

비-iOS 폴백에 hls.js CDN을 쓰는 것은 빠릅니다. 하지만 PaperFlow가 로컬/개인 서버 성격이면 외부 CDN이 막힌 환경에서 Chrome/Firefox 오디오가 깨집니다.

제안:

- CDN URL은 pinned version + SRI를 사용하십시오.
- 가능하면 viewer static asset으로 vendoring하는 옵션을 두십시오.
- hls.js error handling은 `MANIFEST_LOAD_ERROR`, `FRAG_LOAD_ERROR`, `BUFFER_STALLED_ERROR`별로 재시도/manifest reload/mp3 fallback을 나누십시오.

## 중점 검토 포인트별 답변

### 1. HLS EVENT + 문장당 1세그먼트 정합성

큰 방향은 정합합니다. EVENT playlist append-only, 원자적 rewrite, ENDLIST 종료는 맞습니다. 빠진 위험은 다음입니다.

- segment URI/API path 불일치
- fixed `TARGETDURATION=16` 미보장
- `TARGETDURATION`과 playlist reload cadence의 충돌
- segment 파일 원자 publish 누락
- 실패 중 partial playlist 정책 누락
- 구버전 HLS 디렉터리 즉시 삭제로 active playback 404 가능

### 2. 인증 endpoint와 iOS native cookie

same-origin cookie가 동작할 가능성은 있지만, 이것을 치명 경로의 단일 전제로 두면 안 됩니다. 특히 iOS native HLS는 요청 제어권이 JS에 없습니다. 반드시 iPhone Safari 실기기에서 다음을 확인해야 합니다.

- m3u8 요청에 `Cookie: paperflow_token=...`이 붙는가
- segment 요청에도 붙는가
- 잠금화면/백그라운드 전환 후에도 붙는가
- 네트워크 전환 후에도 붙는가
- HttpOnly/SameSite=Lax/Secure 조합별 차이가 없는가

깨질 경우 대안은 signed HLS session URL입니다. 이 대안은 "나중에"가 아니라 현재 스펙에 포함되어야 합니다.

### 3. segment 단위 single-pass normalization

트레이드오프는 합리적입니다. 다만 현재 최종 mp3가 실제 2-pass loudnorm이 아니라는 점을 고쳐야 합니다. segment별 loudnorm은 짧은 발화에서 gain pumping이 생길 수 있으므로, v1에서는 fixed gain/limiter를 먼저 검토하고 실측 샘플로 비교하는 것이 좋습니다.

### 4. 증분 manifest + polling merge

아이디어는 맞지만 현재 스펙은 DOM/span 문제를 놓치고 있습니다. 하이라이트가 동작하려면 segmentation metadata와 timing metadata를 분리해야 합니다. 전체 span HTML은 streaming 초기에 제공하고, timing만 점진적으로 채우는 모델이 가장 안정적입니다.

### 5. sweep 동시성

현재 설명은 foreground를 정말 양보하지 않습니다. `try_acquire` 확인 후 release, 이후 blocking `run_job`은 race가 있고, sweep가 lock을 잡으면 논문 전체 동안 사용자 요청을 막습니다. sweep를 계속 포함하려면 foreground pending 감지와 문장/batch 단위 yield, paper file lock, sweep job state 등록이 필요합니다.

### 6. schema v1 하위호환

방향은 맞습니다. 하지만 구현 변경점이 명확해야 합니다. v1 `audio.file`과 v2 `audio.mp3`를 동시에 읽고, playback freshness와 HLS pregen freshness를 분리해야 합니다. old HLS/mp3 cleanup은 grace period를 두십시오.

### 7. 과설계/YAGNI 또는 누락 필수 요소

과설계보다는 누락 필수 요소가 더 큽니다. HLS 자체는 iOS 제약 때문에 정당합니다. sweep는 가치가 있지만 foreground preemption 없는 자동 sweep는 제품 리스크가 큽니다. hls.js CDN, signed URL token, streaming HTML/span, stale streaming recovery는 YAGNI가 아니라 이 설계가 실제로 동작하기 위한 필수 요소입니다.

## 스펙 수정 체크리스트

- [ ] playlist segment URI를 `/audio/seg/{seg}`와 맞춘다.
- [ ] `TARGETDURATION`을 실측 기반으로 재결정하고 초과 segment publish 금지 규칙을 넣는다.
- [ ] iOS cookie 실패 시 signed HLS session URL 대안을 기본 설계에 포함한다.
- [ ] segment temp encode -> ffprobe -> atomic rename -> playlist append 순서를 명시한다.
- [ ] manifest v2에서 전체 chunk metadata와 ready timing을 분리한다.
- [ ] `/audio/html`이 streaming 상태에서도 전체 span HTML을 반환하도록 정의한다.
- [ ] frontend가 `streaming`에서도 player를 mount하고, manifest merge를 idempotent하게 수행하도록 정의한다.
- [ ] sweep foreground 우선순위 보장 방식을 바꾼다. 최소한 기본 off/시간 cap/문장 단위 yield를 넣는다.
- [ ] paper 단위 file lock과 stale streaming manifest 복구 정책을 추가한다.
- [ ] v1 `audio.file` 및 v2 `audio.mp3` 하위호환 경로를 코드 레벨로 명시한다.
- [ ] 구버전 HLS 디렉터리 cleanup을 TTL/N-version 보존으로 바꾼다.
- [ ] partial failure playlist/manifest 정책을 정한다.
- [ ] MIME/cache headers를 확정한다.
- [ ] iPhone Safari 실기기 인증/재생 acceptance test를 blocking으로 올린다.

## 참고한 근거

- RFC 8216, HTTP Live Streaming: EVENT playlist append-only, atomic playlist update, targetduration 불변, ENDLIST/reload 규칙. https://datatracker.ietf.org/doc/html/rfc8216
- Apple Developer, Deploying a Basic HTTP Live Streaming Stream: browser/client receiver, HLS auth/credential 관련 설명. https://developer.apple.com/documentation/http-live-streaming/deploying-a-basic-http-live-streaming-hls-stream
- Apple Archive, HTTP Live Streaming Overview: HLS가 일반 HTTP 서버와 iOS/Safari native client에서 동작하고 인증/HTTPS 보호를 지원한다는 배경. https://developer.apple.com/library/archive/documentation/NetworkingInternet/Conceptual/StreamingMediaGuide/
- hls.js API: `xhrSetup`/`fetchSetup`으로 credentials 포함 요청 설정 가능. https://github.com/video-dev/hls.js/blob/master/docs/API.md#xhrsetup
