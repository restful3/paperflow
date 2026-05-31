# PaperFlow 라이브 TTS 설계 2차 의견 — Codex

검토 대상:

- `docs/research/2026-05-31-live-tts-design-considerations.md`
- `docs/research/2026-05-31-paperflow-live-tts-opensource.md`

판정: **MVP는 A 계열로 단순화하되, 캐시 단위는 처음부터 "청크 + 매니페스트"로 잡는 것이 좋다. 단, 사용자 재생 표면은 청크 플레이리스트가 아니라 단일 stitched audio를 우선하라.**

## 핵심 결론

현재 설계의 중심축인 **청크별 오디오 파일 + 문장↔청크 매니페스트(JSON)** 는 R1(캐싱), R2(현재 문장 표시), R3(문장 단위 이동)을 동시에 만족시키는 좋은 내부 저장 구조다. 다만 이것을 그대로 브라우저 재생 구조로 노출하면 복잡도가 커진다. 특히 iOS Safari, 백그라운드 재생, 순차 자동재생, 전역 seek, 잠금화면 컨트롤에서 위험이 커진다.

추천 구조는 다음이다.

```text
canonical cache:
  audio/chunks/000001.mp3
  audio/chunks/000002.mp3
  ...
  audio/manifest.json

playback artifact:
  audio/paper_ko_audio.mp3 또는 .m4a
  audio/timeline.json  # chunk_id -> start_sec/end_sec/text/dom_anchor
```

즉, **청크 파일은 생성/부분 재생성/품질 검증의 원천 캐시**로 두고, **브라우저에는 단일 오디오 파일 + 타임라인 매니페스트**를 기본 제공하는 편이 더 견고하다. 문장 이동은 `<audio>.currentTime = timeline[i].start_sec`로 해결한다. 현재 문장 하이라이트도 `timeupdate`에서 `currentTime`을 timeline에 매핑하면 된다.

이 방식은 사용자가 제안한 A/B/C 중 정확히는 **A+** 다. "전체 사전생성 + 캐싱"이지만, 내부는 청크 기반이고, stitched audio까지 만든다. 긴 논문 대기 문제는 첫 MVP에서 C식 실시간 청크 재생으로 풀기보다 **백그라운드 잡 + 진행률 + 생성 완료 후 재생**으로 푸는 것이 PaperFlow의 개인용·간헐 청취 맥락에 맞다. 이후 정말 필요할 때 C를 붙이면 된다.

## 1. 청크 경계 이음새 최소화

### 권장: crossfade보다 "청크 품질 + 명시적 호흡 + 단일 파일 stitching"

청크 경계의 운율 단절은 세 층에서 줄이는 것이 좋다.

1. **청크를 너무 잘게 자르지 않는다.**
   - "문장 1개 = 청크 1개"를 원칙으로 삼되, 너무 짧은 문장은 같은 문단 안에서 2~3개 묶는다.
   - 추천 범위는 대략 80~180자, 상한 220자 정도다. 이미 360자/40초에서 끝부분 품질 저하가 관찰됐으므로 300자대는 피한다.
   - 헤딩, 문단, 목록 항목, 그림/표 설명 경계를 넘겨 묶지 않는다. 의미 단위가 바뀌면 약간의 단절이 오히려 자연스럽다.

2. **모델 입력에 "호흡 가능한 문장"을 제공한다.**
   - 문장 끝에는 종결 부호를 반드시 둔다.
   - 괄호·영문 약어·숫자 단위는 `_ko_audio.md` 생성 단계에서 이미 낭독형으로 바꿨다는 전제를 유지한다.
   - 짧은 헤딩 뒤 첫 문장을 바로 붙여 합성하지 말고, 헤딩은 별도 짧은 청크로 만들거나 "다음 절에서는 ..." 식의 자연어 문장으로 풀어주는 편이 낫다.

3. **오디오 후처리에서 고정된 silence padding을 둔다.**
   - 문장 사이: 120~250ms
   - 문단 사이: 300~500ms
   - 섹션/헤딩 뒤: 600~900ms
   - 이 padding은 manifest에 반영해야 한다. 그래야 하이라이트와 seek가 밀리지 않는다.

Crossfade는 MVP에서는 권하지 않는다. 짧은 20~50ms fade-in/fade-out은 클릭 제거에는 도움이 될 수 있지만, 의미 있는 crossfade는 한국어 문장 끝/다음 문장 시작을 겹치게 만들어 발음이 뭉개질 수 있다. 또한 overlap 길이를 타임라인에 반영해야 하므로 동기화 복잡도를 키운다. 첫 구현은 **무교차 concat + 짧은 silence + loudness normalize**가 낫다.

구현상으로는 각 청크를 WAV/PCM 또는 동일 codec/spec의 중간 파일로 만들고, 마지막에 ffmpeg로 concat 후 MP3/M4A로 인코딩하는 편이 안전하다. 청크별 MP3를 단순 binary concat하거나 브라우저에서 이어 재생하면 경계 gap/click이 생길 가능성이 커진다.

추가로 넣을 만한 후처리:

- per-chunk peak normalize 또는 전체 loudness normalize. 단, 청크별 과한 정규화는 문장마다 음량이 흔들릴 수 있으니 최종 stitched audio 기준 normalize가 더 낫다.
- 각 청크 앞뒤 무음 trim. 모델이 앞뒤에 긴 무음을 만들면 전체 리듬이 늘어진다.
- 합성 실패/품질 저하 감지: duration이 텍스트 길이에 비해 비정상적으로 길거나 짧으면 재시도한다.

## 2. A/B/C 중 PaperFlow에 맞는 방식

### 결론: MVP는 A+, C는 v2

PaperFlow는 개인용·간헐 청취이고, 생성 오디오를 반드시 캐싱해야 한다. 이 맥락에서는 "즉시 첫 문장 재생"의 가치보다 "한 번 만들면 다시 안정적으로 듣기"의 가치가 더 크다. 따라서 C를 처음부터 구현하는 것은 과설계에 가깝다.

각 방식 평가는 다음과 같다.

### A. 사전생성 + 캐싱

장점:

- 가장 단순하고 실패 모드가 적다.
- 단일 `<audio>` 파일을 쓰면 iOS Safari, 백그라운드 재생, 잠금화면, seek가 가장 안정적이다.
- 재청취가 즉시 시작된다.
- 서버 API도 job 생성/status/result 정도면 충분하다.

단점:

- 최초 생성 대기가 길다.
- 전체 파일이 생성되기 전에는 들을 수 없다.

보완:

- 내부는 청크 단위로 합성해 진행률을 표시한다.
- 완료 시 stitched audio와 timeline을 만든다.
- 긴 논문은 백그라운드 잡으로 처리하고, 사용자는 다른 일을 하게 한다.

### B. 실시간 스트리밍

현재 PaperFlow에는 맞지 않는다. Chatterbox가 진짜 low-latency streaming API를 안정적으로 주는 전제가 아니고, R1 캐싱 요구와도 긴장이 있다. 스트리밍을 구현하더라도 결국 저장 캐시를 따로 만들어야 한다. 브라우저 MSE/StreamingResponse까지 들어가면 구현면이 넓어진다.

### C. 하이브리드

구조적으로는 매력적이지만, "브라우저가 생기는 청크를 순차 재생"하는 부분이 위험하다. 특히 다음 청크를 새 `<audio>` src로 바꾸거나 새 audio element로 재생하는 방식은 모바일 Safari에서 자동재생/백그라운드 동작이 흔들릴 수 있다. 사용자가 첫 청크 재생을 눌렀더라도, 다음 파일로 넘어가는 것이 항상 같은 사용자 제스처의 연장으로 취급된다고 기대하면 안 된다.

C를 하려면 최소한 다음이 필요하다.

- 단일 audio element 재사용
- 다음 청크 preload
- 실패 시 재시도와 gap 처리
- 청크 생성 속도가 재생 속도보다 늦을 때 buffering UI
- iOS 실제 기기 테스트
- MediaSession next/previous action과 내부 playlist state 연결

이 정도면 MVP 범위를 넘어선다.

### 추천 단계

1. **MVP: A+**
   - chunk manifest 생성
   - chunk audio 생성
   - stitched audio 생성
   - timeline 기반 문장 하이라이트/이전/다음
   - 백그라운드 job 진행률

2. **v1.1: 부분 재생성**
   - `_ko_audio.md` sha 변경 시 바뀐 청크만 재합성
   - 전체 stitched audio 재생성

3. **v2: progressive playback**
   - 첫 N개 청크가 준비되면 "준비된 부분 듣기" 제공
   - 단, iOS에서는 실험 기능으로 두고 단일 파일 fallback 유지

## 3. 문장↔오디오 동기화

### 문장 단위 하이라이트면 충분하다

논문 듣기 UX에서 사용자가 원하는 것은 "지금 어느 설명을 듣고 있는지"이지, 노래방처럼 단어를 따라가는 것이 아니다. Chatterbox가 단어 타임스탬프를 기본으로 주지 않는다면 단어 단위 동기화는 비용 대비 가치가 낮다.

문장 단위 동기화는 다음을 만족한다.

- 지금 듣는 문장 표시
- 이전/다음 문장 이동
- 문장 탭해서 그 지점부터 듣기
- 섹션별 시작점 이동
- 이어듣기 저장

단어 단위 가라오케가 필요한 경우는 언어 학습, dictation, 자막 제작에 가깝다. PaperFlow의 학술 논문 청취 목적에는 과하다.

### DOM 매핑은 "문장 텍스트 재검색"보다 anchor-first

manifest에는 단순히 텍스트만 넣지 말고 DOM anchor를 넣는 것이 좋다.

```json
{
  "chunks": [
    {
      "id": 12,
      "section_id": "method",
      "paragraph_index": 4,
      "sentence_index": 2,
      "dom_id": "tts-s-000012",
      "text": "이 방법은 검색과 생성을 분리해...",
      "audio_file": "chunks/000012.mp3",
      "start_sec": 138.42,
      "end_sec": 146.90
    }
  ]
}
```

렌더링 시 `_ko_audio.md`에서 만든 문장 segmentation 결과를 그대로 HTML span에 반영해야 한다. 나중에 브라우저에서 문장 분리를 다시 하면 서버 manifest와 어긋날 수 있다. 즉, segmentation은 서버가 하고, UI는 manifest의 `dom_id`를 그대로 따른다.

### duration 신뢰성

각 chunk duration은 생성 직후 ffprobe 같은 도구로 실제 파일에서 읽어야 한다. 텍스트 길이로 추정하면 timeline이 금방 밀린다. stitched audio를 만든 뒤에도 최종 파일 기준 duration이 chunk sum과 맞는지 검증하는 것이 좋다.

## 4. 읽기 진행률 vs 듣기 진행률

분리하는 것이 맞다.

읽기 진행률과 듣기 진행률은 같은 논문에 대한 다른 행동이다. 사용자는 낮에 눈으로 70%까지 읽고, 이동 중에는 듣기를 처음부터 시작할 수 있다. 이 둘을 공유하면 "읽던 위치"와 "듣던 위치"가 서로 덮어써서 불쾌한 UX가 된다.

권장 데이터 모델:

```json
{
  "paper_id": "...",
  "reading_progress": {
    "percent": 72,
    "updated_at": "..."
  },
  "listening_progress": {
    "audio_version": "sha256:...",
    "chunk_id": 128,
    "time_sec": 934.2,
    "percent": 41,
    "updated_at": "..."
  }
}
```

UI에서는 둘을 느슨하게 연결할 수 있다.

- 문장 탭 후 듣기 시작하면 listening_progress만 갱신
- "현재 듣는 위치로 본문 이동" 버튼 제공
- "현재 읽는 섹션부터 듣기" 버튼 제공
- 전체 카드/목록의 단일 progress bar는 기존 reading_progress를 유지하고, 듣기 진행률은 오디오 플레이어 내부에 표시

API는 기존 `/progress`를 억지로 재사용하기보다 `mode=reading|listening` 또는 별도 `/audio/progress`가 낫다. 기존 API를 확장할 경우 backward compatibility를 깨지 않도록 기본값은 reading으로 둔다.

## 5. iOS Safari / MediaSession / 자동재생 함정

이 영역은 C를 MVP에서 피해야 하는 가장 큰 이유다.

Apple의 오래된 iOS Safari 문서와 WebKit autoplay 정책 문서의 공통 메시지는 명확하다. iOS Safari는 네트워크 비용·배터리·사용자 의도를 이유로 미디어 자동재생과 preload를 강하게 제한해 왔고, 소리가 있는 미디어는 사용자 제스처 없이 재생된다고 가정하면 안 된다. WebKit의 iOS video policy 문서도 음성 있는 media의 자동재생을 조심스럽게 다루며, Apple의 iOS-specific HTML5 audio/video 문서도 iOS Safari에서 preload/autoplay가 제한된다고 설명한다.

따라서 설계 원칙은 다음이다.

1. **첫 재생은 반드시 사용자 탭에서 시작한다.**
   - "듣기" 버튼 클릭 핸들러 안에서 audio element의 `play()`를 호출한다.
   - `play()` Promise rejection을 UI에서 처리한다.

2. **하나의 `<audio>` element를 오래 유지한다.**
   - 단일 stitched audio를 src로 둔다.
   - 이전/다음 문장은 `currentTime` 변경으로 처리한다.
   - 청크마다 src를 교체하는 playlist 방식은 iOS에서 더 많은 예외를 만든다.

3. **MediaSession은 progressive enhancement다.**
   - 지원하면 metadata, play/pause, previoustrack/nexttrack, seekbackward/seekforward, seekto를 연결한다.
   - 미지원이어도 기본 `<audio>` 컨트롤과 인앱 버튼이 동작해야 한다.
   - 잠금화면 artwork는 없어도 된다. 논문 제목/저자/현재 섹션명 정도면 충분하다.

4. **백그라운드 재생은 실제 기기 검증 항목으로 둔다.**
   - iPhone Safari
   - iPhone Chrome/Edge도 WebKit 기반이므로 별도 브라우저라고 안심하지 않는다.
   - 화면 잠금, 앱 전환, 네트워크 전환, AirPods 컨트롤, 잠금화면 next/previous를 확인한다.

5. **오디오 포맷은 보수적으로 간다.**
   - MP3 또는 AAC/M4A 우선.
   - Opus/WebM은 Safari 최신 지원 상황이 좋아졌더라도 long-form mobile playback의 기본값으로 삼을 이유가 없다.
   - HTTP Range 요청 지원은 꼭 확인한다. 긴 단일 오디오에서 seek와 resume에 중요하다.

참고한 1차/준1차 자료:

- WebKit, "New video policies for iOS": https://webkit.org/blog/6784/new-video-policies-for-ios/
- WebKit, "Auto-Play Policy Changes for macOS": https://webkit.org/blog/7734/auto-play-policy-changes-for-macos/
- Apple archive, "iOS-Specific Considerations" for HTML5 Audio/Video: https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/Using_HTML5_Audio_Video/Device-SpecificConsiderations/Device-SpecificConsiderations.html
- Apple Developer WWDC21, "Coordinate media playback in Safari with Group Activities"에서 Media Session을 Safari media playback coordination의 표준 Web API로 설명: https://developer.apple.com/videos/play/wwdc2021/10189/

## 6. 긴 논문 사전생성 대기 UX

20분+ 논문에서 "생성 완료까지 페이지를 붙잡아 두는" UX는 피해야 한다. 백그라운드 job으로 취급하는 것이 맞다.

추천 UX:

1. 사용자가 "한국어 듣기 생성" 클릭
2. 서버가 job 생성
3. UI는 다음을 표시
   - 총 청크 수
   - 완료 청크 수
   - 예상 오디오 길이
   - 예상 남은 생성 시간
   - 현재 단계: segmenting / synthesizing / stitching / validating / ready
4. 생성 중에는 논문 읽기를 계속 가능하게 한다.
5. 완료되면 player가 활성화된다.

개인용이라면 알림까지는 과하다. 같은 페이지에 있으면 Alpine polling으로 충분하고, 페이지를 떠났다 돌아와도 status API가 job/cache 상태를 보여주면 된다. 나중에 필요하면 browser notification을 붙이면 된다.

진행률 계산은 두 종류로 나누는 편이 정확하다.

- synthesis progress: completed_chunks / total_chunks
- finalization progress: stitching/manifest validation 단계는 별도 표시

예상 시간은 처음에는 거칠게 잡아도 된다.

```text
estimated_synthesis_sec = total_chars * observed_sec_per_char
```

단, Chatterbox는 청크 길이와 punctuation에 따라 속도가 흔들릴 수 있으므로 "약 N분" 정도로만 보여준다.

실패 UX:

- 청크 단위 실패는 1~2회 자동 재시도
- 계속 실패하면 job status를 failed로 두고 실패 chunk id/text 일부를 보여준다
- partial audio를 완성본처럼 노출하지 않는다
- `.part` 또는 job temp directory에서 작업 후 atomic publish한다

## 7. MVP 첫 구현 범위

처음부터 C로 가지 말고 A+로 시작하는 것을 권장한다.

### MVP에 포함

- TTS sidecar container
- GPU 동시성 게이트. MinerU와 TTS가 동시에 GPU를 잡지 못하게 하는 coarse lock이면 충분
- `_ko_audio.md` segmentation
- `manifest.json`
- chunk audio 생성 및 캐시
- stitched audio 생성
- `timeline.json`
- FastAPI endpoint
  - `GET /papers/{id}/audio/status`
  - `POST /papers/{id}/audio/jobs`
  - `GET /papers/{id}/audio/manifest`
  - `GET /papers/{id}/audio/file`
  - `POST /papers/{id}/audio/progress`
- Alpine UI
  - 생성 버튼
  - 진행률
  - play/pause
  - previous/next sentence
  - playbackRate
  - current sentence highlight
  - auto-follow toggle
  - resume

### MVP에서 제외

- 실시간 청크 스트리밍
- 단어 단위 karaoke
- 복잡한 playlist engine
- 음성 클로닝 UI
- 사용자별 여러 voice preset
- 자동 browser notification
- 오프라인 다운로드 관리

### v2 후보

- first chunks ready 상태에서 preview playback
- changed chunks only regeneration
- background notification
- HLS/MSE 기반 progressive playback
- voice preset 선택

## "청크 파일 + 매니페스트" 접근의 약점

이 접근은 내부 모델로는 좋지만, 몇 가지 약점이 있다.

1. **파일 수가 많아진다.**
   - 긴 논문은 수백 개 청크가 될 수 있다.
   - inode/디렉터리 listing/backup 관리가 지저분해진다.
   - 해결: `audio/chunks/000/000123.mp3`처럼 shard하거나, MVP에서는 논문당 수백 파일 정도를 허용하되 cleanup 정책을 둔다.

2. **브라우저 playlist로 쓰면 gap과 autoplay 문제가 생긴다.**
   - 해결: 사용자 재생은 stitched audio 우선.

3. **manifest와 HTML DOM이 쉽게 어긋난다.**
   - 해결: 서버 segmentation 결과로 HTML span을 만들고, manifest의 stable `dom_id`를 사용한다.

4. **소스 변경 freshness가 복잡해진다.**
   - `_ko_audio.md`가 한 글자만 바뀌어도 기존 chunk mapping이 흔들릴 수 있다.
   - 해결: MVP는 source sha가 바뀌면 전체 재생성. 부분 재생성은 v1.1로 미룬다.

5. **모델/버전/voice 변경 캐시 무효화가 필요하다.**
   - manifest에 `source_sha256`, `tts_model`, `model_revision`, `voice_id`, `language_id`, `chunker_version`, `audio_format`, `created_at`을 기록해야 한다.
   - 이 중 하나라도 바뀌면 캐시 miss로 보는 것이 안전하다.

6. **문장 단위 jump와 자연스러운 낭독이 충돌할 수 있다.**
   - 너무 짧은 문장을 묶으면 jump 단위가 문장보다 커진다.
   - 해결: "navigation unit"과 "synthesis unit"을 분리할 수 있다. MVP에서는 한 synthesis chunk 안에 여러 sentence span이 들어갈 수 있게 하고, manifest에 sentence offsets는 chunk 내부 근사값 대신 chunk start만 둘 수 있다. 단, R3를 엄밀히 문장 단위로 해석하면 1문장 1청크가 더 단순하다.

내 판단은 MVP에서는 **1문장 1청크를 기본으로 하되, 20~30자 이하의 짧은 문장만 앞뒤 문장과 묶는 제한적 휴리스틱**이 좋다. 이렇게 하면 R3를 거의 그대로 만족하면서도 너무 부자연스러운 짧은 발화를 줄일 수 있다.

## 추가로 놓치기 쉬운 리스크

### 1. Range request와 정적 서빙

긴 단일 MP3/M4A seek를 제대로 하려면 서버가 Range 요청을 처리해야 한다. FastAPI `FileResponse`/프록시/nginx 경로에서 `Accept-Ranges`, `Content-Length`, `Content-Type`이 제대로 나가는지 확인해야 한다. Docker reverse proxy가 있다면 그 경로도 포함한다.

### 2. 원자적 publish

완성되지 않은 manifest/audio가 UI에 보이면 안 된다.

권장:

```text
audio/.jobs/{job_id}/...
audio/.jobs/{job_id}/chunks/...
audio/.jobs/{job_id}/manifest.json
audio/.jobs/{job_id}/paper_ko_audio.mp3

검증 통과 후:
  atomic rename 또는 publish marker 생성
```

최종 공개 조건은 `manifest.status == "complete"`와 실제 파일 존재/size/duration 검증을 모두 통과해야 한다.

### 3. 보안/경로 안전성

논문 제목 기반 경로를 직접 받지 말고 기존 viewer의 paper id/path resolution을 재사용해야 한다. audio endpoint가 임의 파일 다운로드가 되지 않도록 `outputs/` 하위 검증과 symlink 방어를 유지한다.

### 4. 동시성

사용자 전제가 "MinerU와 TTS를 동시에 실행하지 않는다"여도 시스템은 coarse lock으로 강제해야 한다. 개인용이라도 버튼 두 번, 브라우저 탭 두 개, background watcher와 수동 요청이 겹칠 수 있다.

최소 정책:

- paper별 audio job은 1개만 active
- GPU global lock 1개
- 같은 source_sha/model이면 duplicate request는 기존 job/status 반환
- cancel은 v1에서는 queue 상태만 취소, running cancel은 best-effort로 둬도 됨

### 5. 재생 품질 검증 자동화

TTS는 텍스트 테스트만으로 품질을 잡기 어렵다. 그래도 최소한의 자동 검증은 가능하다.

- chunk 파일 존재
- duration > 0
- duration/text_length ratio가 허용 범위
- final audio duration이 chunk duration sum + padding과 근사
- manifest chunk count와 DOM span count 일치
- ffprobe로 codec/sample rate/channel 확인

### 6. accessibility

현재 문장 highlight는 색만 바꾸지 말고 `aria-current` 또는 적절한 class를 써야 한다. 다만 screen reader가 timeupdate마다 문장을 계속 읽게 만들면 방해가 되므로 live region으로 현재 문장을 매번 announce하는 것은 피한다.

### 7. 오디오 파일명과 zip/export

기존 MCP zip이나 viewer 파일 스캔이 audio artifacts를 논문 markdown/pdf 후보로 오인하지 않도록 `audio/` 하위에 격리한다. zip에 포함할지는 별도 옵션으로 둔다.

## 최종 권장안

PaperFlow의 첫 구현은 다음 한 문장으로 정리할 수 있다.

> **청크 단위로 합성하고 캐싱하되, 사용자에게는 단일 오디오 파일을 재생시키며, 문장 동기화는 manifest timeline으로 처리한다.**

이렇게 하면 R1~R3를 모두 만족하면서도 C의 가장 위험한 부분인 브라우저 순차 청크 자동재생을 피할 수 있다. 이후 사용자가 "첫 문장이라도 바로 듣고 싶다"는 요구를 실제로 느끼면, 그때 C를 확장하면 된다. 지금 단계에서는 C를 설계 중심에 놓기보다 내부 캐시 구조만 C-compatible하게 만들어 두는 것이 적정하다.

