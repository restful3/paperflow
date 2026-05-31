# PaperFlow HLS 실시간 한국어 TTS — 설계 스펙

_작성: 2026-05-31 · 개정: R2(Codex 재리뷰 반영) · 상태: 사용자 리뷰 대기(BLOCKING 0)_

> **R1**: Codex 1차 리뷰([…-codex.md](../../reviews/2026-05-31-hls-tts-spec-codex.md))의 BLOCKING 5 + HIGH 3 + MEDIUM/LOW 반영(세그먼트 URI·TARGETDURATION 하드게이트·signed token·2층 매니페스트·sweep OFF·원자 publish·file lock·TTL 정리·partial 정책·MIME/cache·하위호환).
> **R2**: Codex 재리뷰([…-codex-round2.md](../../reviews/2026-05-31-hls-tts-spec-codex-round2.md)) — **잔존 BLOCKING 0**, HIGH 4 반영: ①signed **playlist** URL 1급화(쿠키 게이트 제거) ②token 재발급 cadence + tokenized playlist no-cache + 401 remount ③query token 로그 redaction/Referrer-Policy ④sub-split 그룹 스키마(`sentence_group_id` 등).

## 0. 배경 / 목표

라이브 한국어 TTS MVP(배치판)는 `_ko_audio.md`(낭독 텍스트) 전체를 문장별 합성·stitch 한 뒤에야 재생 가능 — 긴 논문(854문장)은 첫 재생까지 ~40분 대기. 병목은 전처리/stitch 가 아니라 **GPU 문장 합성 전체**이며, 단일 mp3 라 "전부 끝나야 재생" 구조다.

**목표:** 합성과 동시에 **점진적으로 들을 수 있게** 한다 — 첫 1\~3 세그먼트(~수초)부터 재생, 나머지는 백그라운드로 이어짐. 표준 `<audio>` 단일 mp3 는 "재생 중 파일 append" 불가(고정 Content-Length)이고 iPhone Safari 는 오디오 MSE 사실상 미지원이므로 **HLS(HTTP Live Streaming) — Apple 네이티브 progressive 재생** 로 구현한다.

**선행 MVP:** [2026-05-31-paperflow-live-tts-design.md](2026-05-31-paperflow-live-tts-design.md) (배치판, 구현·검증 완료). 본 스펙은 그 위에 스트리밍 전달 계층을 얹는다.

## 1. 승인된 결정

| # | 결정 | 선택 |
|---|------|------|
| 1 | mp3 와 공존 | HLS 주력 + 최종 mp3(다운로드·폴백) 유지. 기존 단일-mp3 논문도 계속 재생 |
| 2 | 세그먼트 단위 | 문장 1개 = 세그먼트 1개 (단, TARGETDURATION 초과 문장은 §5.3 sub-split) |
| 3 | 비-iOS 지원 | iOS 네이티브 + hls.js 폴백(pinned+SRI+vendoring 옵션) |
| 4 | 스코프 | HLS 스트리밍 + 유휴 사전생성 sweep |
| 5 | **HLS 인증** | **HMAC signed token** — 쿠키 의존 제거(§7). iOS 네이티브 AVPlayer 쿠키 불확실성 대응 |
| 6 | **sweep v1 정책** | **기본 OFF(`SWEEP_ENABLED=false`) + 캡**(짧은 논문 N개/최대 M분). 완전 preemption 은 v1.1 |
| 7 | **TARGETDURATION** | **구현 전 실측 단계(§12.0)** 에서 corpus duration 분포 측정 후 확정 + 초과 문장 sub-split |

## 2. 아키텍처

문장별 합성(Chatterbox-Multilingual)은 MVP 그대로. 변경점은 **전달**:

1. **Segmentation(합성 전):** chunker 가 전체 문장/DOM 메타데이터를 먼저 산출 → 매니페스트의 `chunks[]` 를 **timing 없이(`start_sec=null`) 전부 publish** + `status="streaming"`. `/audio/html` 은 이 전체 chunks 로 span HTML 을 만들어 즉시 본문 표시(하이라이트는 timing 채워진 문장만).
2. **합성 루프:** 문장 i 의 wav(+무음 패딩)를 AAC MPEG-TS 세그먼트로 인코딩 → **temp→ffprobe→atomic rename** 으로 publish → playlist 에 `#EXTINF` append → 매니페스트 chunk i 의 `start_sec/end_sec` 를 **id-keyed 갱신**.
3. **재생:** 뷰어는 `stream.m3u8` 재생(iOS 네이티브 `<audio src=m3u8>`, 그 외 hls.js). 라이브 플레이리스트가 자라면 플레이어가 자동으로 이어 재생(파일 swap 불필요 → gapless). **1\~3 세그먼트 ready 시 자동 mount/play**.
4. **완료:** 모든 문장 후 playlist 에 `#EXT-X-ENDLIST` → VOD 확정 + 다운로드/폴백 mp3 stitch + `status="complete"`.
5. **사전생성 sweep:** (기본 OFF) 유휴 시 `_ko_audio.md` 있고 fresh HLS 없는 논문을 캡 내에서 미리 생성.

```text
chunker(전체) ─▶ manifest.chunks[](text/dom, start_sec=null), status=streaming, /audio/html 전체 span
   └─ 문장 i: wav+pad ─▶ seg_i.ts.tmp ─ffprobe─▶ os.replace seg_i.ts ─▶ playlist.append(#EXTINF)
                          └─▶ manifest.chunks[i].start_sec/end_sec 갱신(id-keyed)
   ... 전부 후 ...
   └─ playlist.ENDLIST + stitch mp3 + status=complete
   (중도 실패 시 §5.4: ENDLIST + status=failed_partial, mp3=null)
```

## 3. 산출물 레이아웃

```text
outputs/<paper>/audio/
├── .jobs/<job_id>/                      # 합성 중 임시 wav (완료 후 폐기, 빈 .jobs/ 도 정리)
├── .locks/<sha12>.lock                  # paper×버전 단위 file lock(§8 동시성)
├── <base>_ko_audio.<sha12>/             # HLS 출력(content-versioned)
│   ├── stream.m3u8                       # 디스크엔 토큰 없는 상대 URI. 라이브→완료 시 ENDLIST
│   ├── seg_000000.ts ... seg_NNNNNN.ts   # 문장당 1 세그먼트(AAC-LC, 문장 뒤 무음 패딩 포함)
├── <base>_ko_audio.<sha12>.mp3          # 완료 후 다운로드/폴백 단일 mp3
└── <base>_ko_audio.manifest.json        # 문장 텍스트/DOM + timing + status + hls/mp3 포인터
```

- **content-versioned**(sha12): old/new 경합 차단(B1). HLS 디렉터리와 mp3 가 같은 sha12 공유.
- **구버전 정리는 즉시 삭제 금지**(§8.3 TTL): active 재생 중 client 가 구버전 세그먼트를 계속 요청하므로.

## 4. 매니페스트 스키마 v2 (2층: 텍스트 vs 타이밍)

```jsonc
{
  "schema_version": 2,
  "status": "streaming" | "complete" | "failed_partial" | "failed",
  "generated_at": "<ISO8601, complete/실패 확정 시>",
  "heartbeat": "<ISO8601, 합성 진행 중 주기 갱신 — stale 복구용(§8.4)>",
  "source": { "path", "sha256", "mtime" },
  "tts": { ...DEFAULT_TTS, "chunker_version", "model_revision" },
  "audio": {
    "hls": { "playlist": "stream.m3u8",
             "mime_type": "application/vnd.apple.mpegurl",
             "segment_mime_type": "video/mp2t" },
    "mp3": { "file": "<base>_ko_audio.<sha12>.mp3" | null,   // complete 전 null
             "mime_type": "audio/mpeg" },
    "duration_sec": <timing 확정분 누적>,
    "sample_rate": 24000
  },
  "chunks": [                          // 1층: 전체 텍스트/DOM — segmenting 직후 전부 publish
    { "id","kind","level?","dom_id","section_id","paragraph_index","sentence_index","text",
      // sub-split(§5.3): UI 문장 1개 = sentence_group, TTS sub-sentence 1개 = 1 chunk = 1 HLS segment
      "sentence_group_id": <int>,      // 같은 UI 문장의 sub-chunk 들이 공유
      "sub_index": <int>, "sub_count": <int>,   // 그룹 내 위치(0..sub_count-1)
      "display_sentence_index": <int>, // UI 표시용 문장 인덱스(그룹 단위)
      "start_sec": <number|null>,      // 2층: 세그먼트 timing 확정 시 채움(id-keyed 갱신)
      "end_sec": <number|null> }, ...
  ]
}
```
- **sub-split schema(HIGH#4)**: 짧은 문장은 `sub_count=1`(그룹=자기 자신). DOM span 은 chunk 단위 sub-span 을 만들되 같은 `sentence_group_id` 를 공유 → 하이라이트는 (a) sub-span 만 칠하거나 (b) 그룹 전체 칠하는 두 UX 모두 지원. 그룹 active 조건 = `any sub-chunk 의 start_sec <= t < end_sec`. 이어듣기/position 은 `sentence_group_id + currentTime` 으로도 복원.

- `status="streaming"` 동안 `chunks` 의 **텍스트는 처음부터 전부 존재**, `start_sec/end_sec` 만 점진 확정. 프론트는 이를 **`chunk.id` keyed replacement 로 머지**(append 아님 — 중복 polling/재시도/실패 전이에서 중복 방지).
- `is_fresh_for_playback(manifest, sha)`: `status=="complete"` + sha/cachekey 일치 → 캐시 재생 가능. **v1 `audio.file` 매니페스트도 인정**.
- `is_fresh_for_hls(manifest, sha)`: `status=="complete"` + **schema_version≥2** + `audio.hls` 존재 + sha 일치 → sweep 의 "HLS 사전생성 불필요" 판정. v1(mp3-only)은 stale 로 보고 HLS 업그레이드 대상.
- **하위호환**: v1(schema 1, `audio.file`) 매니페스트는 `audio.hls` 부재 → 프론트가 단일-mp3 폴백(§9).

## 5. HLS 세그먼트 · 라이브 플레이리스트

### 5.1 세그먼트 포맷 · 원자 publish
- **MPEG-TS + AAC-LC**(오디오 전용). ffmpeg `-c:a aac -b:a 96k -f mpegts`. iOS 네이티브 + hls.js 지원.
- 입력: 문장 wav(24kHz mono) + 문장 뒤 무음 패딩(`pad_for`)을 이어붙인 뒤 인코딩 → 패딩 baked-in(HLS gapless).
- **원자 publish 순서(불변식):** `seg_NNNNNN.ts.tmp.<pid>` 로 인코딩 → ffprobe 로 codec=aac·duration>0 검증(+ §5.3 길이 게이트) → `os.replace(tmp, seg_NNNNNN.ts)` → **그 다음** playlist/manifest 갱신. **playlist 가 참조한 세그먼트는 절대 재작성하지 않는다.**

### 5.2 라이브 플레이리스트 (`stream.m3u8`)
디스크 저장본(토큰 없음, 상대 URI):
```text
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-PLAYLIST-TYPE:EVENT          # growing event VOD (sliding live 아님; segment 제거/ MEDIA-SEQUENCE 증가 없음)
#EXT-X-TARGETDURATION:<§12.0 실측 확정>
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:3.214,
seg/seg_000000.ts                   # ★ playlist URL(/api/papers/X/audio/stream.m3u8) 기준 상대 → /api/papers/X/audio/seg/seg_000000.ts
#EXTINF:2.880,
seg/seg_000001.ts
... (세그먼트 추가마다 append) ...
#EXT-X-ENDLIST                      # 완료(또는 §5.4 partial)에만
```
- **세그먼트 URI 는 `seg/seg_NNNNNN.ts`**(상대) — playlist 가 `/audio/stream.m3u8` 에서 서빙되므로 `/audio/seg/seg_NNNNNN.ts` 로 해석돼 API(§6)와 일치. (Codex BLOCKING #1)
- playlist 는 **tmp+`os.replace` 원자 재작성**. EXT-X-PLAYLIST-TYPE:EVENT(append-only). 완료 시 ENDLIST → 클라 reload 중단.
- **인증 토큰은 디스크 저장본에 넣지 않는다.** API(§6)가 매 요청 시 세그먼트 URI 에 `?token=…` 을 주입해 반환.

### 5.3 TARGETDURATION · 길이 하드 게이트 (Codex BLOCKING #2)
- `sec/char ≤ 1.5` 품질게이트는 **비율 상한이지 절대 duration 상한이 아님** → 긴 문장이 TARGETDURATION 을 넘을 수 있음. RFC 8216: 모든 `EXTINF` 는 반올림 시 `TARGETDURATION` 이하여야 하고 `TARGETDURATION` 은 불변.
- **§12.0 실측**으로 `TARGETDURATION`(예: P100 + 여유) 확정.
- **하드 게이트 + 처리 순서(Codex R2):**
  1. chunker **문장 길이 hard cap**(1차 예방) → 초과 문장은 **TTS sub-sentence 로 분할**(구두점/길이), `sentence_group_id` 공유(§4).
  2. 그래도 인코딩 후 ffprobe `duration > TARGETDURATION` 이면 → 해당 chunk 를 **더 작은 sub-sentence 로 재분할 후 1회 재시도**.
  3. 재시도 후에도 초과하면 → `failed_partial`(§5.4)로 ENDLIST 붙이고 멈춤.
- sub-sentence 각각이 1 세그먼트. 하이라이트 span 처리는 §4(그룹/sub-span) 참조.

### 5.4 partial 실패 정책 (Codex MEDIUM #13)
세그먼트 N 까지 publish 후 N+1 실패 시:
- playlist 에 `#EXT-X-ENDLIST` append → **앞부분은 재생 가능**. manifest `status="failed_partial"`, `audio.mp3=null`(다운로드 404).
- 프론트는 partial 배지 + "재생성" 버튼. **재생성은 기존 세그먼트 재사용이 아니라 새 sha12/version 으로 처음부터**(v1 단순성, Codex MEDIUM#4).
- 완전 실패(0 세그먼트 등)는 `status="failed"`, playlist 미생성, 재시도 버튼.

### 5.5 startup 하한 (Codex HIGH #4)
"첫 1 세그먼트부터" 를 단정하지 않는다 — **1\~3 세그먼트 available 시 자동 mount/play**. acceptance: 실기기에서 "첫 audible time" 과 "첫 10문장 stall 무" 를 기준으로 §12 에서 검증.

## 6. 음량 정규화 (용어 교정 — Codex MEDIUM #9)

- 현재 배치 stitch 는 **single-pass `loudnorm=I=-16:TP=-1.5:LRA=11`**(true 2-pass 아님). 스펙 용어를 구현에 맞춤.
- **스트리밍 세그먼트:** 짧은 발화에서 segment 별 loudnorm 은 gain pumping 위험 → **고정 gain + true-peak limiter**(예측 가능). §12.0 실측 샘플로 mp3 대비 비교.
- **다운로드 mp3:** 완료 후 **현재와 동일한 single-pass loudnorm** 유지(품질 불변).

## 7. HLS 인증 — HMAC signed token (Codex BLOCKING #3)

iOS 네이티브 AVPlayer 는 playlist/segment 를 AppleCoreMedia 경로로 가져가 HttpOnly/SameSite 쿠키가 안 붙을 수 있음 → **쿠키 의존을 playlist·segment 양쪽 모두 제거**(Codex HIGH#1: playlist 토큰도 1급 설계).

- **토큰(2종, 같은 HMAC):** `tok = base64url( exp "." hmac_sha256(AUDIO_TOKEN_SECRET, f"{kind}|{source_id}|{sha12}|{exp}") )`. `kind ∈ {playlist, segment}`.
  - `source_id`=durable paper 식별자, `sha12`=오디오 버전. **paper×버전 바인딩**(유출 시 해당 오디오만, mp3 download URL 과 동급 민감도).
  - **playlist 토큰 TTL**: 기본 12h(`AUDIO_PTOKEN_TTL`). **segment 토큰 TTL**: `max(AUDIO_TOKEN_TTL, audio.duration_sec + resume_grace)` — VOD 1회 fetch 후 장시간 pause/resume 커버(Codex HIGH#2). complete VOD 는 더 긴 별도 TTL 허용.
- **1급 흐름(쿠키 비의존):** 인증된(쿠키) HTML/API 가 **signed playlist URL 발급** — manifest 응답에 `audio.hls.signed_playlist_url = "…/stream.m3u8?ptoken=<fresh>"`(또는 `GET /audio/stream-url`). **iOS 네이티브 `<audio src>` 는 이 signed playlist URL 을 기본값으로 사용.**
  - `GET /audio/stream.m3u8?ptoken=…` → **쿠키 없이 ptoken 검증** → 디스크 playlist 를 읽어 **세그먼트 URI 에 fresh segment token `?token=<seg>` 주입**해 반환.
  - `GET /audio/seg/{seg}?token=…` → token HMAC+exp+sha+kind 검증(쿠키 불요) + traversal 방어(`seg` 정규식 + `_under_audio_dir`).
  - 쿠키 게이트(`?ptoken` 없는 `/audio/stream.m3u8`)는 hls.js/개발 편의 경로로만 유지.
- **hls.js 경로:** `xhrSetup`/`fetchSetup` 으로 `credentials:'include'` 또는 signed URL 사용(reverse proxy/public base URL 변경 대비).
- **로그 노출 방어(Codex HIGH#3):** token 은 query string 이라 access log·devtools·Referer 에 남을 수 있음 → ① viewer/tts access log 에서 `token`/`ptoken` 파라미터 **redaction**(또는 token hash prefix 만) ② viewer 페이지 `Referrer-Policy: same-origin`(이상) ③ 프론트는 `audio.src` 전체 URL 을 console/error report 에 찍지 않음.
- **설정:** `AUDIO_TOKEN_SECRET`(**JWT_SECRET_KEY 와 별도 secret 권장**; rotation 시 기존 HLS 토큰 무효화 → 재생 중 401→remount 로 회복, §10), `AUDIO_PTOKEN_TTL`(43200s), `AUDIO_TOKEN_TTL`/`resume_grace`.
- **멀티유저 주의:** 현재 payload 는 user/session binding 없음 — **개인용 단일 사용자 전제**. 공유 환경 전환 시 audience binding 추가(비목표).

## 8. 동시성 · 정리 (Codex HIGH #8, MEDIUM #12)

### 8.1 paper×버전 file lock
- 합성 시작 시 `audio/.locks/<sha12>.lock` 에 flock(GPU flock 과 별개 — 같은 paper 의 foreground/sweep 중복 쓰기 차단). 같은 sha12 디렉터리 동시 쓰기 방지.
- foreground create 가 진행 중 job 의 sha12 lock 을 못 잡으면 "이미 진행 중" 반환(기존 _jobs 게이트 보강).

### 8.2 worker 가정
- tts 사이드카 `workers==1` 명시(uvicorn 단일 워커). 다중 워커 시 in-memory `_jobs` 분리되므로 file lock 이 1차 방어.

### 8.3 구버전 HLS 디렉터리 TTL 정리 (즉시 삭제 금지)
- 재생성 시 구버전 HLS 디렉터리/mp3 **즉시 삭제 안 함** — active client 가 구버전 세그먼트를 계속 요청(즉시 삭제 시 404 끊김).
- **TTL cleanup**: 최근 N(기본 2) 버전 보존 또는 `age > max(duration_sec, 1h)`. 신규 job 시작 시 정리.

### 8.4 stale streaming manifest 복구
- `status="streaming"` 인데 `heartbeat` 가 30분 이상 정지 → 다음 접근/sweep 시 **`status="failed"`** 전이 후 새 version 재생성 허용(사이드카 재시작으로 `_jobs` 유실된 케이스 복구). (`abandoned` 미사용 — 프론트는 failed = 재시도 버튼 단일 규칙.)

## 9. 백엔드 API (viewer)

기존 유지(`/audio/jobs`, `/status`, `/manifest`, `/position`). 변경/추가:

| Method | Path | 용도 |
|--------|------|------|
| `GET` | `/audio/stream-url` | (쿠키 인증) signed playlist URL `…/stream.m3u8?ptoken=<fresh>` 발급. manifest 응답의 `audio.hls.signed_playlist_url` 로도 동등 제공 |
| `GET` | `/audio/stream.m3u8` | **`?ptoken=` 있으면 쿠키 없이 ptoken 검증**(iOS 네이티브 1급 경로); 없으면 쿠키 게이트(hls.js/dev). 디스크 playlist 읽어 **세그먼트 URI 에 fresh segment token 주입** 후 반환. `application/vnd.apple.mpegurl`. **tokenized playlist 는 complete 라도 `Cache-Control: private, no-cache`**(token 만료 vs cache 충돌 방지, Codex HIGH#2). streaming: `no-cache, no-store` |
| `GET` | `/audio/seg/{seg}` | segment token 검증(HMAC+exp+sha+kind) → `.ts`. `video/mp2t`. `FileResponse`(Range). **segment 파일만 immutable cache**: `private, max-age=31536000, immutable`. `seg` 정규식 `seg_[0-9]{6}\.ts` + `_under_audio_dir`. (playlist 의 `seg/` 는 URL 라우팅일 뿐 — 디스크는 HLS 디렉터리 직하위 `seg_NNNNNN.ts`) |
| `GET` | `/audio/html` | **streaming 에서도 전체 `chunks` 텍스트로 span HTML 반환**(409 제거; `status in {streaming,complete,failed_partial}` 허용) |
| `GET` | `/audio/file` | mp3 다운로드. `audio.mp3.file` 채워진(complete) 경우만 200, 아니면 404 |

- 경로 해석은 manifest 의 `audio.hls.playlist`/`audio.mp3.file`(버전드)을 통해(B1).
- access log 에서 `token`/`ptoken` redaction(§7). MIME/cache (Codex MEDIUM #14, HIGH#2) 위 표대로. segment `Accept-Ranges` smoke 확인.

## 10. 프론트엔드 (viewer.html)

- `audioSrc()` → **signed playlist URL**(`audio.hls.signed_playlist_url`, 즉 `stream.m3u8?ptoken=…`). iOS 네이티브 1급 경로.
- **HLS 부착:** `canPlayType('application/vnd.apple.mpegurl')` truthy(Safari/iOS) → `src` = signed playlist URL 직접. 아니면 **hls.js**(pinned version + SRI, vendoring 옵션) 동적 로드 → `xhrSetup` credentials → `loadSource`/`attachMedia`. 인스턴스 보관·`destroy()`.
- **token 만료 회복(HIGH#2):** segment 401/403 → `audio/stream-url` 재발급 → `<audio src>` 새 signed playlist URL 로 remount(hls.js 는 error handler, 네이티브는 `audio.src` 재설정) + currentTime 복원.
- **하이라이트(sub-split, §4):** currentTime → `start_sec != null` 인 chunk → 그 chunk 의 `sentence_group_id` 그룹을 active. 그룹 active = `any sub-chunk start_sec<=t<end_sec`. sub-span 단위 or 그룹 단위 칠하기(구현 플랜 택1).
- **보안:** `audio.src` 전체 URL 을 console/error report 에 로깅하지 않음(token 노출 방지, §7).
- **streaming 중 player mount**(complete 안 기다림): manifest `status in {streaming,complete,failed_partial}` && playlist+세그먼트 1\~3 ready → mount+play.
- **`/audio/html` 전체 span**: 본문은 처음부터 전체 문장 표시. `onTimeUpdate` 는 **`start_sec != null` 인 chunk 만** 대상.
- **매니페스트 머지 idempotent**: status="streaming" 동안 주기(예 3s) 재조회 → **`chunk.id` keyed 갱신**(append 금지). complete/실패 시 폴링 중단.
- 하이라이트·이어듣기·MediaSession: currentTime 기반 유지.
- **hls.js 에러 핸들링**(Codex LOW #16): `MANIFEST_LOAD_ERROR`/`FRAG_LOAD_ERROR`/`BUFFER_STALLED_ERROR` 별 재시도·manifest reload·mp3 폴백 분기.
- **공존/폴백**: manifest `audio.hls` 없음(v1) → 기존 `<audio src=mp3>`. HLS 재생 불가 && `audio.mp3` 존재 → mp3 폴백.

## 11. 신규/변경 모듈

| 파일 | 변경 |
|------|------|
| `tts_service/app/hls.py` | **신규**: `encode_segment`(패딩 결합+AAC TS+temp/atomic+ffprobe+길이게이트), `LivePlaylist`(append/atomic/ENDLIST/partial) |
| `tts_service/app/segtoken.py` | **신규**: HMAC signed token mint/verify(playlist+segment, kind 바인딩, §7) |
| `tts_service/app/job.py` | **변경**: segmentation 선-publish, 증분 세그먼트+playlist+manifest(id-keyed), heartbeat, status 전이, paper file lock, 종료 mp3 stitch, 구버전 TTL 정리 |
| `tts_service/app/manifest.py` | **변경**: schema v2(2층, audio.hls/mp3), `is_fresh_for_playback`/`is_fresh_for_hls`, id-keyed merge 헬퍼 |
| `tts_service/app/sweep.py` | **신규**: 유휴 사전생성(기본 OFF, 캡, _sweep_active 등록) |
| `tts_service/app/main.py` | **변경**: sweep 조건부 기동, 설정(`SWEEP_ENABLED`/캡/`AUDIO_TOKEN_*`) |
| `viewer/app/services/audio.py` | **변경**: v1 `audio.file`+v2 `audio.mp3` 동시 지원, hls playlist/seg 경로(traversal), token mint/verify 연동, 전체 span 렌더 |
| `viewer/app/routers/api.py` | **변경**: `/audio/stream-url`(signed URL 발급), `/audio/stream.m3u8`(ptoken 검증+segment token 주입), `/audio/seg/{seg}`(token 검증), `/audio/html` 409 제거, access-log token redaction |
| `viewer/app/templates/viewer.html` | **변경**: HLS 부착(네이티브/hls.js+SRI), streaming mount, id-keyed merge, 폴백·에러분기 |

## 12. 테스트 · 실측

### 12.0 (선행) 실측 단계 — 구현 전 BLOCKING
- 전체 `_ko_audio.md` corpus(또는 대표 표본)에서 **문장별 합성 duration 분포**(P50/P95/P99/P100) 측정 → `TARGETDURATION` 및 문장 길이 hard cap(sub-split 임계) 확정.
- 스트리밍 고정 gain+limiter vs 최종 mp3 loudnorm **샘플 비교**로 음량 정책 확정.

### 12.1 단위/통합
- **`hls.py`**(ffmpeg 실호출): 유효 AAC TS(ffprobe codec/duration), 패딩 포함, 길이게이트 동작, `LivePlaylist` 포맷(상대 URI `seg/…`, EXTINF, ENDLIST, partial, 원자성).
- **`segtoken.py`**: mint→verify 왕복, exp 만료 거부, sha/source 불일치 거부, 변조 거부.
- **`manifest.py`**: v2 2층 shape, streaming→complete/failed_partial 전이, id-keyed merge idempotent, `is_fresh_for_playback` vs `is_fresh_for_hls`(v1 mp3 → hls stale).
- **job 통합 스모크**(GPU): segmentation 선-publish → m3u8 성장 → 1\~3 세그먼트 곧 재생가능 → ENDLIST → mp3 → .jobs 폐기 → 구버전 TTL.
- **viewer API**: stream-url 발급, stream.m3u8 ptoken 검증(쿠키 없이)+segment token 주입, seg token 검증/traversal/Range, tokenized playlist no-cache 헤더, access-log token redaction, `/audio/html` streaming 전체 span, v1 폴백.
- **sweep**: 기본 OFF 확인, 캡 동작, 유휴 게이트(진행중 job/flock 점유 시 skip), file lock 중복 방지.

### 12.2 프론트 Playwright
- Chromium + hls.js: streaming mount → 재생 → start_sec 채워지며 하이라이트 → seek → 첫 세그먼트 startup 지연, BUFFER_STALLED 폴백.
- (가능 시) webkit 네이티브 경로.

### 12.3 실기기 — **ship 전 BLOCKING preflight** (Codex #3)
- iPhone Safari: m3u8/segment 요청에 인증(쿠키 or token)이 실제로 통과하는가 — **token 경로로 검증**. 잠금화면/백그라운드/네트워크 전환 후 지속 재생·seek. AirPods/MediaSession.

## 13. 마이그레이션 / 하위호환 (Codex MEDIUM #11)

- v1(schema 1, `audio.file`) 논문: `viewer/app/services/audio.py` 가 `audio.file`(v1)·`audio.mp3.file`(v2) 모두 읽음. 프론트는 `audio.hls` 부재 → 기존 mp3 경로(무손상).
- `is_fresh_for_playback`(v1 인정) vs `is_fresh_for_hls`(v1 stale → sweep 업그레이드 대상) 분리.
- v1→HLS 업그레이드 시 기존 재생 안 깨지게 old mp3/HLS **grace period(§8.3 TTL)**.

## 14. 비목표 (YAGNI)

- ABR 멀티 variant · fMP4/CMAF · 화자 선택 · DRM 암호화 세그먼트 · 세그먼트 2-pass loudnorm · sweep 완전 preemption(v1.1).

## 15. 구현 플랜에서 확정할 잔여

- §12.0 실측 결과로 `TARGETDURATION`·문장 hard cap·음량(fixed gain+limiter) 파라미터 확정.
- 하이라이트: sub-span 단위 vs 그룹 단위 칠하기 택1(§4 schema 는 둘 다 지원).
- 매니페스트 streaming 폴링 주기(3s 가정) 튜닝.
- hls.js vendoring vs pinned-CDN(+SRI) 최종 선택.
- segment 토큰 `resume_grace` 구체값.
