# PaperFlow 라이브 TTS 설계 — Codex Round 2 응답

검토 대상:

- `docs/reviews/2026-05-31-live-tts-design-claude-meta-review.md`
- `docs/reviews/2026-05-31-live-tts-design-codex.md`
- `docs/research/2026-05-31-live-tts-design-considerations.md`

판정: **메타리뷰 D1~D4 모두 수용. 잔존 이견 0건.**

## D1. `manifest.json` + `timeline.json` → 단일 `manifest.json`

**동의.**

R1에서 두 파일을 나눈 것은 개념 설명용이었다. 실제 구현에서는 `manifest.json` 하나에 cache key, job metadata, audio artifact, chunk/timeline/dom mapping을 모두 담는 편이 더 낫다. 두 파일을 분리하면 같은 `chunk_id`, `text`, `start_sec`, `end_sec`, `dom_id`가 중복되고, publish/rollback 중 한쪽만 갱신되는 드리프트 위험이 생긴다. MVP에서 분리할 실익은 없다.

권장 단일 구조:

```json
{
  "schema_version": 1,
  "status": "complete",
  "source": {
    "path": "_ko_audio.md",
    "sha256": "...",
    "mtime": "..."
  },
  "tts": {
    "model": "Chatterbox-Multilingual",
    "model_revision": "...",
    "language_id": "ko",
    "voice_id": "default",
    "chunker_version": "paperflow-tts-chunker-v1"
  },
  "audio": {
    "file": "paper_ko_audio.mp3",
    "mime_type": "audio/mpeg",
    "duration_sec": 1234.56,
    "sample_rate": 24000
  },
  "chunks": [
    {
      "id": 0,
      "kind": "heading",
      "dom_id": "tts-s-000000",
      "section_id": "intro",
      "paragraph_index": 0,
      "sentence_index": 0,
      "text": "서론",
      "start_sec": 0.0,
      "end_sec": 1.12
    }
  ]
}
```

`timeline.json`은 v2에서 외부 플레이어 호환이나 매우 큰 manifest 최적화가 필요해질 때만 분리하면 된다.

## D2. MVP에서는 per-chunk 오디오 파일을 stitch 후 폐기

**동의.**

메타리뷰의 지적이 맞다. R1에서 청크 파일 보존을 권한 근거는 부분 재생성과 내부 캐시 안정성이었는데, 부분 재생성은 내가 직접 v1.1로 미룬 항목이다. MVP가 source sha 변경 시 전체 재생성 정책이라면 청크 오디오를 공개 캐시로 계속 보존할 이유가 약하다.

MVP 권장 publish 모델:

```text
audio/.jobs/{job_id}/
  chunks/000001.wav 또는 .mp3
  chunks/000002.wav 또는 .mp3
  manifest.draft.json
  paper_ko_audio.tmp.mp3

검증 통과 후 공개:
audio/
  paper_ko_audio.mp3
  manifest.json

그리고 audio/.jobs/{job_id}/는 삭제 또는 짧은 보존 TTL 적용
```

이렇게 하면 R1에서 내가 약점으로 든 수백 파일, shard directory, inode 관리 문제가 MVP에서 사라진다. 품질 검증은 `.jobs/{job_id}` 단계에서 청크별 duration/text ratio, 파일 존재, concat duration 검증으로 충분하다.

단, 디버깅을 위해 실패 job의 `.jobs/{job_id}`는 즉시 삭제하지 말고 최근 N개 또는 24시간 TTL로 보존하는 대안은 유용하다. 성공 job은 삭제가 맞다. 부분 재생성이 v1.1로 들어갈 때 청크 보존 정책을 다시 도입하면 된다.

## D3. DOM 세그먼테이션 구현 방식 — 서버 렌더 권고

**동의. 서버 렌더가 MVP의 정답이다.**

코드 교차검증 결과와 같이 현재 뷰어는 `mdKoAudioContent`를 클라이언트에서 `marked.parse`로 렌더링하고, 문장 span이 없다. 이 상태에서 클라이언트가 manifest 오프셋에 맞춰 deterministic wrapping을 시도하면 다음 문제가 생긴다.

- Markdown parsing 전후로 텍스트 노드가 바뀐다.
- punctuation/공백 normalization으로 offset이 흔들린다.
- 링크, 강조, 리스트, 헤딩이 섞이면 문장 경계와 DOM 경계가 갈라진다.
- 서버의 TTS chunker와 클라이언트 wrapping 로직이 이중 구현된다.

따라서 MVP는 오디오 모드 전용 endpoint가 서버에서 다음을 한 번에 생성하는 구조가 맞다.

- `_ko_audio.md` 로드
- 동일 chunker로 문장/헤딩/문단 segmentation
- `manifest.json` 생성
- 각 문장에 stable `dom_id` 부여
- 오디오 모드 전용 HTML 생성

예:

```html
<h2 id="section-method">
  <span id="tts-s-000042" data-tts-chunk="42">방법</span>
</h2>
<p>
  <span id="tts-s-000043" data-tts-chunk="43">이 절에서는 제안 방법을 설명합니다.</span>
</p>
```

`_ko_audio.md`가 이미 수식·표·기호 제거와 낭독 최적화를 거친 텍스트라는 전제를 두면, 오디오 모드는 기존 KaTeX/복잡한 Markdown 렌더 파이프라인을 우회해도 된다. 충돌 여지는 낮다. 다만 완전한 plain text라고 가정하지는 말고, 최소 Markdown subset은 지원해야 한다.

MVP 서버 렌더 지원 범위:

- heading: `#`, `##`, `###`
- paragraph
- ordered/unordered list
- emphasis 정도는 허용 가능
- raw HTML, code fence, table, image는 `_ko_audio.md` 생성 단계에서 없어야 하며 남아 있으면 audio readiness 검증 실패로 처리

즉, "marked 우회"는 기존 문서 뷰어 전체를 바꾸는 것이 아니라 **audio mode에 한정된 단순 렌더러**를 두는 것이다. 기존 KO/EN/Easy 렌더링과 분리하면 KaTeX/Markdown 호환성 리스크는 작다.

## D4. 헤딩 "다음 절에서는..." 재작성 제안 제외

**동의.**

R1의 표현은 합성 단계가 아니라 `_ko_audio.md` 생성 단계에서 고려할 수 있는 예시였는데, 지금 합의하는 live TTS MVP 범위에서는 제외하는 편이 맞다. `_ko_audio.md`는 이미 `paper-audio-korean` 스킬의 책임 산출물이다. TTS 합성 단계에서 헤딩을 다시 자연어로 재작성하면 책임 경계가 흐려지고, manifest의 텍스트와 실제 화면 텍스트가 어긋날 수 있다.

MVP 정책:

- 헤딩은 짧은 별도 청크로 합성한다.
- 헤딩 뒤에는 600~900ms 긴 쉼을 둔다.
- 문단/문장 재작성은 하지 않는다.
- 낭독 품질을 위해 헤딩 표현 자체를 바꾸고 싶다면 `_ko_audio.md` 생성 스킬에서 처리한다.

이 정책이 더 단순하고, 캐시 freshness도 명확하다. TTS 단계의 입력은 `_ko_audio.md`의 텍스트 그대로여야 한다.

## 메타리뷰에서 보완하거나 주의할 점

큰 방향은 모두 맞다. 다만 spec으로 옮길 때 아래 사항은 빠지면 안 된다.

1. **Range 리스크는 낮아졌지만 검증 항목에서는 유지해야 한다.**
   - 기존 API가 `FileResponse`를 쓰는 점은 좋은 확인이다.
   - 그래도 최종 audio endpoint, Docker/reverse proxy, 인증 경로를 통과한 실제 URL에서 `Accept-Ranges`, `Content-Length`, seek 동작을 smoke test로 확인해야 한다.

2. **"청크 폐기"와 "청크 기반 진행률"은 양립한다.**
   - 공개 산출물에서 청크 파일을 폐기해도 job 중에는 청크 단위 합성과 검증을 해야 한다.
   - 진행률은 `completed_chunks / total_chunks`로 계산하고, 최종 공개 후에는 manifest chunks만 남기면 된다.

3. **서버 렌더 HTML도 manifest와 함께 원자적으로 publish해야 한다.**
   - 오디오 파일과 manifest만 공개하고 HTML은 매 요청마다 재생성할 수도 있지만, chunker version/source sha가 맞지 않으면 미묘하게 어긋날 수 있다.
   - 더 안전한 MVP는 `audio/ko_audio.html` 또는 API response cache를 manifest와 같은 source sha/chunker version으로 묶는 것이다.
   - 단, HTML을 파일로 저장하지 않고 매번 manifest의 chunk text로 렌더해도 된다. 중요한 것은 "HTML 생성 입력이 manifest와 동일한 segmentation 결과"라는 점이다.

4. **문장 단위 내비게이션과 짧은 문장 묶기 정책을 명확히 해야 한다.**
   - D2/D3를 수용하면 MVP는 문장별 `dom_id`와 stitched audio seek가 핵심이다.
   - 너무 짧은 문장을 합성 단위로 묶더라도 navigation target은 문장이어야 하는지, 묶음 청크 시작점으로 이동해도 되는지 spec에서 정해야 한다.
   - R3를 엄밀히 만족시키려면 MVP는 되도록 **1문장 1합성 단위**가 가장 단순하다. 너무 짧은 헤딩/문장은 silence와 padding으로 자연스럽게 처리하고, 묶기는 v1.1 품질 튜닝으로 미뤄도 된다.

5. **단일 manifest에는 publish marker 역할이 필요하다.**
   - `status: complete`, `source_sha256`, `audio.file`, `audio.duration_sec`, `chunks[].start_sec/end_sec`, `generated_at`, `schema_version`을 갖춘 manifest가 최종 완료 마커가 되어야 한다.
   - UI는 manifest가 없거나 `status != complete`이면 완성 오디오로 취급하지 않는다.

## 잔존 이견

**잔존 이견 0건.**

D1 단일 manifest, D2 MVP 청크 폐기, D3 서버 렌더, D4 헤딩 재작성 제외를 모두 수용한다. R1의 "내부 청크 캐시 보존"과 "manifest/timeline 분리"는 Round 2 합의에 따라 MVP 범위에서 철회한다.

## 합의된 MVP 설계

PaperFlow 라이브 TTS MVP는 Chatterbox-Multilingual TTS 사이드카와 GPU global lock을 두고, 사용자가 생성 요청을 누르면 `_ko_audio.md`를 서버에서 문장/헤딩 단위로 segmentation한 뒤 백그라운드 job에서 청크 단위로 임시 합성하고 검증한 다음 하나의 stitched `paper_ko_audio.mp3`와 단일 `manifest.json`만 원자적으로 공개한다. `manifest.json`은 source sha, 모델/voice/chunker version, audio duration, 각 문장의 `dom_id`와 `start_sec/end_sec`를 포함하며 완료 마커 역할도 한다. 오디오 모드 본문은 클라이언트 `marked.parse`가 아니라 서버가 같은 segmentation 결과로 생성한 문장 span HTML을 사용하고, 브라우저는 단일 `<audio>` element의 `currentTime`을 manifest timeline에 매핑해 현재 문장 하이라이트, 이전/다음 문장 이동, 문장 탭 재생, 이어듣기를 제공한다. 청크 파일은 `.jobs/{job_id}` 아래에서 합성·검증 중에만 보존하고 성공 publish 후 삭제하며, 읽기 진행률과 듣기 진행률은 분리한다. C식 progressive playback, per-chunk 공개 캐시, 부분 재생성, 단어 단위 karaoke, 합성 단계 텍스트 재작성은 MVP에서 제외한다.

