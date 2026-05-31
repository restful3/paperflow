# PaperFlow HLS 실시간 한국어 TTS — 설계 스펙

_작성: 2026-05-31 · 상태: 승인 대기(사용자 리뷰)_

## 0. 배경 / 목표

라이브 한국어 TTS MVP(배치판)는 `_ko_audio.md`(낭독 텍스트) 전체를 문장별로 합성·stitch 한 뒤에야 재생 가능하다 — 긴 논문(854문장)은 첫 재생까지 ~40분 대기. 병목은 전처리/stitch 가 아니라 **GPU 문장 합성 전체**이며, 단일 mp3 라 "전부 끝나야 재생" 구조다.

**목표:** 합성과 동시에 **점진적으로 들을 수 있게** 한다 — 첫 문장(~3초)부터 재생, 나머지는 백그라운드로 이어짐. 표준 `<audio>` 단일 mp3 로는 "재생 중 파일 append" 가 불가능하고(고정 Content-Length), iPhone Safari 는 오디오 MSE 를 사실상 미지원하므로, **HLS(HTTP Live Streaming) 라이브 플레이리스트** — Apple 네이티브 progressive 재생 — 로 구현한다.

**선행 MVP:** [2026-05-31-paperflow-live-tts-design.md](2026-05-31-paperflow-live-tts-design.md) (배치판, 구현·검증 완료). 본 스펙은 그 위에 스트리밍 전달 계층을 얹는다.

## 1. 승인된 결정 (브레인스토밍)

| # | 결정 | 선택 |
|---|------|------|
| 1 | mp3 와 공존 | **HLS 주력 + 최종 mp3(다운로드·폴백) 유지**. 기존 단일-mp3 논문도 계속 재생 |
| 2 | 세그먼트 단위 | **문장 1개 = 세그먼트 1개** (기존 청크/매니페스트/하이라이트와 1:1) |
| 3 | 비-iOS 지원 | **iOS 네이티브 + hls.js 폴백** (Chrome/Firefox/데스크톱) |
| 4 | 스코프 | **HLS 스트리밍 + 배치 사전생성** 함께 |
| 5 | 사전생성 트리거 | **tts 사이드카 주기 sweep — 리소스 유휴(GPU flock 비점유 + foreground job 없음)일 때만** |

## 2. 아키텍처

문장별 합성(Chatterbox-Multilingual)은 MVP 그대로 유지한다. 변경점은 **전달**:

- 합성 루프가 문장 wav 를 만들 때마다 → **무음 패딩을 baked-in 한 AAC MPEG-TS 세그먼트로 인코딩** → 라이브 `stream.m3u8` 에 세그먼트 줄을 **원자적으로 append** → 매니페스트에 해당 청크 타이밍 append.
- 뷰어는 `stream.m3u8` 을 재생한다(iOS 네이티브 `<audio src=m3u8>`, 그 외 hls.js). 라이브 플레이리스트가 자라면 플레이어가 자동으로 이어 재생하므로 **파일 swap 불필요 → gapless**.
- 모든 문장 완료 시 `#EXT-X-ENDLIST` 로 VOD 확정 + **다운로드/폴백용 단일 mp3** 를 stitch(기존 로직 재사용).
- 별도 백그라운드 **sweep** 가 유휴 시간에 `_ko_audio.md` 는 있으나 fresh 스트림이 없는 논문을 한 개씩 미리 생성.

GPU 동시성은 기존 공유 flock(`outputs/.gpu.lock`)으로 converter(MinerU)와 상호배제. sweep 는 그 위에 "유휴일 때만" 정책을 더한다.

```text
[합성 루프] 문장 i
   └─ wav_i (+pad) ──▶ hls.encode_segment ──▶ seg_i.ts
                          └─ playlist.append(#EXTINF, seg_i.ts)  (atomic)
                          └─ manifest.append(chunk_i: start/end_sec)  status="streaming"
   ... 모든 문장 후 ...
   └─ playlist.finalize(ENDLIST) + stitch_mp3 + manifest.status="complete"
```

## 3. 산출물 레이아웃

```text
outputs/<paper>/audio/
├── .jobs/<job_id>/                      # 합성 중 임시 wav (완료 후 폐기, 빈 .jobs/ 도 정리)
├── <base>_ko_audio.<sha12>/             # HLS 출력 디렉터리 (content-versioned)
│   ├── stream.m3u8                       # 라이브(EVENT) → 완료 시 ENDLIST
│   ├── seg_000000.ts                      # 문장당 1 세그먼트 (AAC-LC, 문장 뒤 무음 패딩 포함)
│   ├── seg_000001.ts
│   └── ...
├── <base>_ko_audio.<sha12>.mp3          # 완료 후 다운로드/폴백 단일 mp3 (기존 stitch)
└── <base>_ko_audio.manifest.json        # 문장 타임라인 + status + stream/mp3 포인터
```

- **content-versioned**: 디렉터리·mp3 파일명에 source sha12 포함 → "old manifest + new audio" 경합 원천 차단(기존 B1 패턴 유지). 재생성 시 구버전 디렉터리/ mp3 정리.
- HLS 디렉터리와 mp3 가 같은 sha12 를 공유하므로 freshness 판정 일관.

## 4. 매니페스트 스키마 (증분)

```jsonc
{
  "schema_version": 2,                       // HLS 필드 추가로 버전 업
  "status": "streaming" | "complete" | "failed",
  "generated_at": "<ISO8601, complete 시>",
  "source": { "path", "sha256", "mtime" },
  "tts": { ...DEFAULT_TTS, "chunker_version", "model_revision" },
  "audio": {
    "hls": "stream.m3u8",                    // 스트리밍 진입점(항상)
    "mp3": "<base>_ko_audio.<sha12>.mp3" | null,  // complete 전엔 null
    "mime_type": "audio/mpeg",
    "duration_sec": <누적, streaming 중엔 부분합>,
    "sample_rate": 24000
  },
  "chunks": [ { "id","kind","level?","dom_id","section_id","paragraph_index",
                "sentence_index","text","start_sec","end_sec" }, ... ]  // 세그먼트마다 append
}
```

- `status="streaming"` 동안 `chunks` 와 `audio.duration_sec` 가 점진적으로 늘어남. 프론트는 이를 주기 재조회해 하이라이트 타임라인을 확장.
- `is_fresh()`: `status=="complete"` + sha 일치 + cache key 일치일 때만 캐시 유효(스트리밍 중간본은 fresh 아님).
- **하위호환**: 구형 매니페스트(schema_version 1, `audio.file` 만 있음)는 `audio.hls` 부재 → 프론트가 단일-mp3 폴백 경로로 처리.

## 5. HLS 세그먼트 · 라이브 플레이리스트

### 5.1 세그먼트 포맷
- **MPEG-TS 컨테이너 + AAC-LC** (오디오 전용). iOS 네이티브 HLS + hls.js 모두 지원. ffmpeg `-c:a aac -b:a 96k -f mpegts`.
- 입력: 문장 wav(24kHz mono) + 문장 뒤 무음 패딩(기존 `pad_for(prev_kind,next_kind)`)을 **이어붙인 뒤** 인코딩 → 패딩이 세그먼트 안에 포함되어 HLS gapless.
- 각 세그먼트 duration 은 ffprobe 실측(패딩 포함).

### 5.2 라이브 플레이리스트 (`stream.m3u8`)
```text
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-PLAYLIST-TYPE:EVENT
#EXT-X-TARGETDURATION:16          # 문장 길이 상한(품질게이트 sec/char 상한)에 맞춘 안전 고정값
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:3.214,
seg_000000.ts
#EXTINF:2.880,
seg_000001.ts
... (세그먼트 추가마다 append) ...
#EXT-X-ENDLIST                    # 완료 시에만
```
- `EXT-X-PLAYLIST-TYPE:EVENT`: 세그먼트는 append 만, 제거 없음 → 처음부터 끝까지 seek 가능.
- 플레이리스트는 **tmp 파일에 전체 재작성 후 `os.replace`** (원자적). 부분 읽힘 방지.
- `TARGETDURATION` 은 정수 상한 고정(예: 16s). 품질게이트가 sec/char ≤ 1.5 로 문장당 길이를 제한하므로 실제 세그먼트는 이를 넘지 않음. (만약 초과 세그먼트 발생 시 — 방어적으로 인코딩 후 duration > TARGETDURATION 이면 경고 로그.)
- 완료 시 `#EXT-X-ENDLIST` append → VOD 로 확정(클라가 더 이상 폴링 안 함, 완전 seek/cache).

## 6. 음량 정규화 (트레이드오프)

- 현재 배치는 stitch 후 **2-pass loudnorm**(전체 신호 기준). 세그먼트 단위로는 불가(전체 신호 필요).
- **스트리밍 세그먼트**: **단일 패스** 정규화 — `loudnorm`(single-pass, 측정 없이 타깃 적용) 또는 고정 피크 정규화. 세그먼트 간 음량이 2-pass 대비 약간 덜 일정할 수 있음.
- **다운로드 mp3**: 완료 시 기존 2-pass loudnorm 그대로 적용(고품질).
- 수용 근거: Chatterbox 출력이 대체로 균일. 청취 체감 차이 작음. v1.1 에서 세그먼트 normalization 튜닝 가능.

## 7. 사전생성 sweep (유휴 시)

`tts_service/app/sweep.py` — 백그라운드 데몬 스레드(사이드카 기동 시 시작).

루프(매 `SWEEP_INTERVAL`초, 기본 60s):
1. **유휴 게이트**: (a) in-memory `_jobs` 에 진행 중(stage ∉ {ready,failed,none}) 항목 없음 **AND** (b) GPU flock `try_acquire` non-blocking 성공(즉시 해제). 둘 중 하나라도 실패 → 이번 사이클 skip(다음 주기).
2. **스캔**: `outputs/` 직하위 각 폴더에서 `*_ko_audio.md` 존재 && (HLS 디렉터리 없음 || manifest status≠complete || sha mismatch)인 논문 수집.
3. **한 개** 선택(예: mtime 최신 우선) → 기존 `run_job` 과 동일 파이프라인으로 생성. 생성은 GPU flock 을 정상 획득(블로킹)하므로 도중 foreground/converter 가 들어오면 다음 작업은 양보됨.
4. 논문 단위 try/except 격리, 생성/skip 을 `log` 로 기록(무음 캡 금지).

- foreground(사용자 클릭) job 과 sweep job 은 같은 `run_job`/flock 을 공유하므로 자연히 직렬화. sweep 는 "유휴일 때 1개"만 착수하여 우선순위를 양보.
- converter 배치가 GPU 를 잡으면 flock try_acquire 실패 → sweep skip → 배치 우선.

## 8. 백엔드 API (viewer)

기존 엔드포인트 유지(`/audio/jobs`, `/status`, `/manifest`, `/file`(mp3), `/position`, `/html`). 추가:

| Method | Path | 용도 |
|--------|------|------|
| `GET` | `/api/papers/{name}/audio/stream.m3u8` | 라이브/완료 플레이리스트. `text/vnd.apple.mpegurl`. streaming 중 `Cache-Control: no-cache` |
| `GET` | `/api/papers/{name}/audio/seg/{seg}` | 세그먼트 `.ts`. `video/mp2t`. `FileResponse`(Range). `seg` 정규식 검증(`seg_[0-9]{6}\.ts`) + `_under_audio_dir` traversal 방어 |

- `/audio/file`(mp3 다운로드)은 `audio.mp3` 가 채워진(완료) 경우에만 200, 그 전엔 404.
- 경로 해석은 manifest 의 `audio.hls` 가 가리키는 버전드 디렉터리를 통해(B1 패턴) — old/new 경합 방지.
- 모든 audio 엔드포인트는 `get_current_user_api` 인증. (주의: `/stream.m3u8`·`/seg/*` 도 인증 게이트 — hls.js/네이티브가 **same-origin 쿠키**를 자동 전송하므로 동작. iOS 네이티브 AVPlayer 의 쿠키 전송은 통합 검증에서 확인 항목.)

## 9. 프론트엔드 (viewer.html)

- `audioSrc()` → 버전드 `stream.m3u8` URL.
- **HLS 부착**:
  - `audioEl.canPlayType('application/vnd.apple.mpegurl')` truthy(Safari/iOS) → `audioEl.src = m3u8`.
  - 아니면 **hls.js 동적 로드**(CDN, 1회) → `const hls = new Hls(); hls.loadSource(m3u8); hls.attachMedia(audioEl);`. 인스턴스는 컴포넌트에 보관, 모드 이탈/재로드 시 `hls.destroy()`.
- **스트리밍 확장**: 라이브 플레이리스트 성장은 네이티브/hls.js 가 자동 반영(swap 불필요). status="streaming" 동안 **매니페스트를 주기(예 3s) 재조회**해 새 청크를 하이라이트 타임라인(`audioManifest.chunks`)에 머지 → `onTimeUpdate` 하이라이트가 새 문장까지 따라감. status="complete" 되면 폴링 중단.
- **하이라이트/이어듣기/MediaSession**: currentTime 기반이라 그대로 동작.
- **공존/폴백**: manifest 에 `audio.hls` 없음(구형) → 기존 단일 `<audio src=mp3>` 경로. `audio.hls` 있으나 HLS 재생 불가(canPlayType 거짓 && hls.js 로드 실패) && `audio.mp3` 존재 → mp3 폴백.
- **생성 흐름**: 🎧 생성 → job POST → 매니페스트에 `status` 등장 + 세그먼트 ≥1 + stream.m3u8 존재하면 즉시 mount + 재생(첫 문장부터). 진행 표시는 status 폴링(기존 `pollAudioJob`) 유지.

## 10. 신규/변경 모듈

| 파일 | 변경 |
|------|------|
| `tts_service/app/hls.py` | **신규**: `encode_segment(wav, pad, out_ts, sr)` (패딩 결합+AAC TS 인코딩+ffprobe duration), `LivePlaylist`(append/atomic rewrite/finalize ENDLIST) |
| `tts_service/app/job.py` | **변경**: 합성 루프에서 세그먼트 인코딩+플레이리스트 append+매니페스트 증분 publish, status 전이(streaming→complete), 종료 시 mp3 stitch |
| `tts_service/app/manifest.py` | **변경**: schema_version 2, `audio.hls`/`audio.mp3` 필드, streaming status, 증분 append 헬퍼 |
| `tts_service/app/sweep.py` | **신규**: 유휴 사전생성 루프 |
| `tts_service/app/main.py` | **변경**: 기동 시 sweep 스레드 시작, 환경변수(`SWEEP_INTERVAL`, `SWEEP_ENABLED`) |
| `viewer/app/services/audio.py` | **변경**: `stream_playlist_path`/`segment_path`(traversal 방어), manifest `audio.hls` 해석 |
| `viewer/app/routers/api.py` | **변경**: `/audio/stream.m3u8`, `/audio/seg/{seg}` 추가 |
| `viewer/app/templates/viewer.html` | **변경**: HLS 부착(네이티브/hls.js), 스트리밍 매니페스트 폴링 머지, 폴백 |

## 11. 에러 처리

- 세그먼트 인코딩 실패 → 기존 `_chunk_ok` 품질게이트 1회 재시도 → 지속 시 job `failed`, manifest `status="failed"`.
- 플레이리스트 쓰기 실패 → job 실패(원자적 rewrite 라 부분손상 없음).
- 플레이어: m3u8 404/stall(hls.js `ERROR`) → `audio.mp3` 존재 시 mp3 폴백, 없으면 재시도 버튼. 버전드 디렉터리 정리로 세그먼트 404 → manifest 재로드.
- sweep: 논문 단위 try/except, foreground 절대 차단 안 함(유휴 게이트), 예외 로깅.

## 12. 테스트 전략

- **`hls.py` 단위**(pytest, ffmpeg 실호출): `encode_segment` 가 유효 AAC TS 생성(ffprobe codec=aac, duration>0, 패딩 포함), `LivePlaylist` 포맷(EXTINF 수치/순서, ENDLIST 유무, 원자성).
- **`manifest.py` 단위**: schema v2 shape, streaming→complete 전이, `is_fresh` 가 streaming 중간본을 fresh 로 보지 않음.
- **job 통합 스모크**(GPU): 합성 시작 후 stream.m3u8 가 자라고 첫 세그먼트가 곧 재생가능, 완료 시 ENDLIST + mp3 생성 + .jobs 폐기.
- **viewer API**: `/stream.m3u8`·`/seg/*` 경로 해석/traversal 방어/Range, 구형 매니페스트 폴백.
- **프론트 Playwright**: (a) Chromium + hls.js 폴백으로 재생·하이라이트·seek·첫 세그먼트 startup 지연 측정; (b) Safari 네이티브 경로는 가능 시 webkit, 불가 시 수동 체크리스트.
- **sweep 단위**: 유휴 게이트(진행 중 job 있으면 skip, flock 점유 시 skip), stale 논문 선택, 논문 단위 예외 격리.
- **실기기 수동**: iPhone Safari 스트리밍 재생·잠금화면·seek, 데이터망 전환.

## 13. 마이그레이션 / 하위호환

- 기존 단일-mp3 매니페스트(schema 1) 논문: 프론트가 `audio.hls` 부재 감지 → 기존 mp3 경로로 재생(무손상). 재생성 트리거(소스 변경 또는 sweep)되면 HLS 로 업그레이드.
- 신규 생성은 항상 HLS(+완료 시 mp3).
- viewer 의 `md_ko_audio` 감지/듣기 토글/`/md-ko-audio`(정적 텍스트) 는 불변.

## 14. 비목표 (YAGNI)

- 적응형 비트레이트(ABR) 멀티 variant — 단일 24kHz/96k 고정.
- fMP4/CMAF 세그먼트 — TS 로 충분(추후 옵션).
- 실시간 음성 클로닝/화자 선택 — 별도.
- DRM/암호화 세그먼트.
- 세그먼트 단위 2-pass loudnorm(전체 신호 필요).

## 15. 미해결 → 구현 플랜에서 확정

- TARGETDURATION 고정값(16s 가정) 실측 검증.
- 스트리밍 단일패스 정규화 필터 정확한 파라미터.
- 매니페스트 스트리밍 폴링 주기(3s 가정) 튜닝.
- iOS 네이티브 AVPlayer 의 인증 쿠키 전송 동작 확인.
