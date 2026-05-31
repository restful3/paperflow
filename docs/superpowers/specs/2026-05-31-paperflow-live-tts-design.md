# PaperFlow 라이브 한국어 TTS — 설계 스펙 (MVP)

**작성일**: 2026-05-31 · **상태**: 설계 합의 완료(Claude ↔ Codex, 잔존 이견 0건) · **범위**: MVP(A+)

**선행 산출물**
- 모델 리서치: [docs/research/2026-05-31-paperflow-live-tts-opensource.md](../../research/2026-05-31-paperflow-live-tts-opensource.md)
- 설계 고려사항: [docs/research/2026-05-31-live-tts-design-considerations.md](../../research/2026-05-31-live-tts-design-considerations.md)
- 코덱스 합의 트레일: `docs/reviews/2026-05-31-live-tts-design-codex.md`, `...-claude-meta-review.md`, `...-codex-round2.md`

---

## 1. 목표 / 비목표

**목표**: `_ko_audio.md`(한국어 낭독 텍스트)를 PaperFlow 뷰어에서 들을 수 있게 한다. 한 번 생성한 오디오는 캐싱해 재사용하고(R1), UI에서 지금 듣는 문장을 표시하며(R2), 문장 단위로 앞/뒤 이동(R3)한다.

**비목표(MVP 제외)**: 실시간 청크 스트리밍(C), per-chunk 공개 캐시, 부분 재생성, 단어 단위 카라오케, 합성 단계 텍스트 재작성, 음성 클로닝 UI, 다중 voice preset, 브라우저 알림, 오프라인 다운로드.

---

## 2. 아키텍처 — A+ (내부 청크, 외부 단일 파일)

```text
[생성 요청] → TTS 사이드카(CUDA, GPU global lock)
   1. _ko_audio.md 로드
   2. 서버 chunker: 문장/헤딩 단위 segmentation (1문장=1합성단위)
   3. 백그라운드 job: .jobs/{job}/chunks/ 에 청크별 임시 합성 + 검증
   4. ffmpeg concat(+무음 패딩) → stitched 단일 오디오 + ffprobe duration
   5. manifest.json 생성(청크·타임라인·캐시키·완료마커)
   6. 검증 통과 → atomic publish → .jobs/ 청크 삭제
[공개 산출물]
   outputs/<paper>/audio/<base>_ko_audio.mp3   (단일 stitched, FileResponse=Range)
   outputs/<paper>/audio/<base>_ko_audio.manifest.json
[재생] 단일 <audio> + currentTime ↔ manifest timeline 매핑
```

**핵심 원칙**: 합성/캐시 단위(청크)와 재생 표면(단일 파일)을 분리한다. 브라우저는 청크를 순차 재생하지 않는다 → iOS Safari 자동재생 함정 회피.

### 검증된 전제(코드·데이터 확인)
- `_ko_audio.md`는 **헤딩 + 문단 + 배너 blockquote 1줄**만 사용(11개 파일 스캔: heading 473, blockquote 11, list/bold/table/code/image/math/link = 0). → 서버 렌더러는 heading/paragraph만 처리하면 됨.
- **배너 blockquote(`>` "이 글은 듣기판입니다…") 처리**: 메타 안내문이므로 **합성에서 제외**(읽어주지 않음). 화면에는 인트로 노트로 표시하되 **TTS 청크/문장 span에는 포함하지 않는다**(chunk count·dom_id 대상 아님).
- 기존 파일 서빙은 `FileResponse`(Starlette가 HTTP Range 자동 지원) → stitched 오디오 seek/resume 기존 패턴으로 동작.
- 경로 안전 헬퍼 존재: `safe_paper_dir`, `safe_paper_dir_at_location`, `_is_within`(symlink 방어) → 재사용.
- 현재 듣기 콘텐츠는 클라이언트 `marked.parse` 렌더(문장 span 없음) → 오디오 모드는 서버 렌더로 전환 필요.

---

## 3. 데이터 모델 — 단일 manifest.json

```json
{
  "schema_version": 1,
  "status": "complete",
  "source": { "path": "<base>_ko_audio.md", "sha256": "...", "mtime": "..." },
  "tts": {
    "model": "Chatterbox-Multilingual",
    "model_revision": "...",
    "language_id": "ko",
    "voice_id": "default",
    "chunker_version": "paperflow-tts-chunker-v1",
    "audio_format": "mp3"
  },
  "audio": { "file": "<base>_ko_audio.mp3", "mime_type": "audio/mpeg", "duration_sec": 1234.56, "sample_rate": 24000 },
  "generated_at": "2026-05-31T...",
  "chunks": [
    { "id": 0, "kind": "heading", "dom_id": "tts-s-000000", "section_id": "intro",
      "paragraph_index": 0, "sentence_index": 0, "text": "서론", "start_sec": 0.0, "end_sec": 1.12 }
  ]
}
```

- **manifest가 완료 마커**: UI는 manifest 없거나 `status != "complete"`면 미완성으로 취급.
- **캐시 무효화 키**: `source.sha256` + `tts.model/model_revision/voice_id/language_id/chunker_version/audio_format` 중 하나라도 변하면 캐시 miss → 전체 재생성(MVP).
- `start_sec/end_sec`는 무음 패딩 포함, **ffprobe 실측 기준**(텍스트 길이 추정 금지). `end_sec`는 "다음 청크 시작 전까지의 **표시 구간**"으로 정의(실제 발화 종료가 아닌, 하이라이트가 유지되는 구간 — MVP에서 가장 단순).

### 무음 패딩(매니페스트 반영)
문장 사이 120\~250ms · 문단 사이 300\~500ms · 헤딩 뒤 600\~900ms. crossfade 없음(필요 시 20\~50ms fade로 클릭 제거만). 청크는 동일 spec WAV로 만들고 ffmpeg concat 후 MP3 인코딩, 최종 stitched 기준 loudness normalize.

---

## 4. 컴포넌트

| 컴포넌트 | 책임 | 비고 |
|----------|------|------|
| **TTS 사이드카 컨테이너** | Chatterbox-Multilingual 적재, 청크 합성 | CUDA, viewer와 분리 |
| **GPU global lock** | MinerU 배치와 동시 GPU 점유 차단 | coarse lock 1개 + 논문당 active job 1개 + 동일 sha/model 중복요청은 기존 job 반환 |
| **Chunker** (`chunker_version`) | 문장/헤딩 segmentation, dom_id 부여 | 1문장=1합성단위. heading=별도 청크 |
| **합성 Job** | `.jobs/{job}/`에서 청크 합성·검증·stitch·manifest·atomic publish | 실패 job은 24h TTL 보존(디버그), 성공 job은 삭제 |
| **서버 오디오 렌더러** | manifest segmentation으로 문장 span HTML 생성 | heading/paragraph만. marked 우회. manifest와 동일 입력 |
| **FastAPI 엔드포인트** | job 생성/상태/manifest/오디오/진행률 | 아래 §5 |
| **Alpine UI** | 재생/하이라이트/내비/진행률 | viewer.html 듣기 토글 연동 |

---

## 5. API 엔드포인트 (인증 필수)

| Method | Path | 용도 |
|--------|------|------|
| `POST` | `/api/papers/{name:path}/audio/jobs` | 생성 job 시작(이미 최신 캐시면 즉시 complete 반환) |
| `GET` | `/api/papers/{name:path}/audio/status` | job 상태(stage, completed/total chunks, ETA) |
| `GET` | `/api/papers/{name:path}/audio/manifest` | manifest.json |
| `GET` | `/api/papers/{name:path}/audio/file` | stitched 오디오(FileResponse, Range) |
| `GET` | `/api/papers/{name:path}/audio/html` | 서버 렌더 문장-span HTML(기본). 클라 렌더는 manifest.chunks를 그대로 span 출력하는 fallback에 한정 — Markdown 재파싱·문장 재분할 금지 |
| `POST` | `/api/papers/{name:path}/audio/progress` | 듣기 진행률 저장(읽기와 분리) |

> 라우트는 기존 API와 동일하게 `{name:path}`(논문명에 인코딩된 slash 포함 가능).

- 경로는 `safe_paper_dir*`로 resolve, `audio/` 하위 격리, symlink 방어.
- job stage: `segmenting → synthesizing → stitching → validating → ready` / `failed`.

---

## 6. UI/UX (viewer.html, 기존 듣기 토글 연동)

- 단일 `<audio>` element 유지(교체 금지). 첫 `play()`는 사용자 탭에서.
- **현재 문장 하이라이트**: `timeupdate` → currentTime을 manifest chunk에 매핑 → 해당 `dom_id` 강조 + auto-scroll. `aria-current` 사용. live-region 매 문장 announce는 금지.
- **문장 내비**: 이전/다음 = `audio.currentTime = chunk[i±1].start_sec`. 문장 탭 = 그 청크 start로 점프.
- **auto-follow 토글**: 켜면 현재 문장으로 자동 스크롤, 끄면 자유 탐색.
- **배속**: `playbackRate` 0.8\~2.0.
- **이어듣기(resume)**: 듣기 진행률(chunk_id/time_sec/percent, audio sha 묶음) 저장·복원. 읽기 진행률과 별도 저장.
- **생성 UX**: "한국어 듣기 생성" 버튼 → 진행률(완료/총 청크, stage, 대략 ETA), 생성 중에도 읽기 가능, 완료 시 플레이어 활성. 개인용이라 polling으로 충분.
- **MediaSession**(progressive enhancement): 지원 시 metadata(제목/섹션)+play/pause/prev/next/seek. 미지원이어도 인앱 컨트롤 동작.

---

## 7. 진행률 모델 — 읽기 vs 듣기 분리

```json
{ "reading_progress": { "percent": 72, "updated_at": "..." },
  "listening_progress": { "audio_version": "sha256:...", "chunk_id": 128, "time_sec": 934.2, "percent": 41, "updated_at": "..." } }
```
- 기존 `/progress`는 읽기 유지(backward compat), 듣기는 `/audio/progress` 별도.
- UI 보조: "현재 듣는 위치로 본문 이동" / "현재 읽는 섹션부터 듣기" 버튼(선택).
- 목록/카드 단일 progress bar는 읽기 진행률 유지, 듣기 진행률은 플레이어 내부 표시.

---

## 8. 원자적 publish & 품질 검증

- 작업은 `audio/.jobs/{job_id}/`에서, 검증 통과 후 `audio/`로 atomic rename/publish. 미완성 manifest/오디오 노출 금지.
- 자동 검증: 청크 파일 존재 · duration>0 · duration/text_length ratio 허용범위 · 비정상 청크 1\~2회 재시도 · stitched duration ≈ Σ청크+패딩 · manifest chunk 수 = DOM span 수 · ffprobe codec/sr/channel 확인.
- audio readiness 게이트: `_ko_audio.md`에 table/code/image/raw HTML이 남아 있으면 검증 실패 처리(현재 데이터상 없음).

---

## 9. 통합 주의점(코덱스 보완 반영)

1. **Range smoke test**: 최종 audio endpoint를 인증·Docker reverse proxy 경로까지 통과한 실제 URL에서 `Accept-Ranges`/`Content-Length`/seek 동작 확인.
2. **청크 폐기 ⊥ 진행률**: 공개 산출물에서 청크를 폐기해도 job 중 청크 합성·검증·진행률은 정상. 진행률 = completed/total chunks.
3. **서버 HTML ↔ manifest 일치**: HTML은 파일 저장 없이 manifest.chunks[].text로 매 요청 렌더해도 됨. 핵심은 "HTML 생성 입력 = manifest와 동일 segmentation".
4. **navigation = 문장**: MVP는 1문장=1합성단위로 R3를 그대로 충족. 짧은 문장 묶기는 v1.1 품질 튜닝.
5. **zip/export 격리**: `audio/` 하위 격리. 기존 MCP zip/파일 스캔이 오디오를 md/pdf 후보로 오인하지 않도록(기존 `_ko_audio.md` 감지 제외 패턴과 동일 정신). zip 포함은 별도 옵션.
6. **`resemble-perth` 워터마커**(non-blocking, 운영 정책): 샘플 생성 때 의존성 누락으로 `DummyWatermarker` 대체했음. MVP 필수 의존성이 아니라 **선택적 워터마크 정책 항목** — 프로덕션 착수 시 `resemble-perth` 정상화 여부/워터마크 유지 여부를 결정(구현 blocking 아님).

---

## 10. 실측 근거(RTX 3060)
- Chatterbox-Multilingual, 360자/40초 합성: RTF 0.59(실시간보다 빠름), 적재 3.0GB / 생성 peak 7.3GB(reserved). 끝부분 품질 저하 → §2 청킹으로 해소.
- 샘플: `docs/research/samples/chatterbox_korean_sample.mp3`.

---

## 11. 향후(비-MVP) 로드맵
- v1.1: 부분 재생성(변경 청크만), 청크 보존 캐시 재도입, 짧은 문장 묶기 튜닝.
- v2: progressive playback(준비된 앞부분부터 듣기, iOS는 실험 + 단일파일 fallback), HLS/MSE, voice preset, 브라우저 알림.
