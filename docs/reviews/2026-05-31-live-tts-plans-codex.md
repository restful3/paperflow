# PaperFlow 라이브 한국어 TTS 구현 플랜 리뷰 — Codex

판정: **BLOCKING 이슈 있음.** 아직 `===PLANS_APPROVED===`를 줄 수 없습니다.

두 플랜은 승인된 스펙의 큰 구조(A+, 단일 manifest, 임시 청크 폐기, 서버 렌더, 단일 audio element)를 대부분 잘 반영했습니다. 하지만 몇몇 코드 스텝은 그대로 구현하면 실제 동작이 깨지거나 스펙의 핵심 보장(원자적 publish, GPU 상호배제, 오디오 모드 서버 HTML, 프론트 API URL)이 무너집니다.

## Blocking

1. **Backend Task 6 `run_job`: 기존 캐시 갱신 시 atomic publish가 깨집니다.**

   위치: Plan 1 Task 6 Step 1

   현재 순서:

   ```python
   os.replace(tmp_mp3, audio_pub)
   ...
   os.replace(tmp_man, man_path)
   ```

   신규 생성에서는 대체로 괜찮지만, 기존 complete manifest/audio가 있는 상태에서 재생성하면 문제가 생깁니다. `audio_pub`를 먼저 교체하는 순간, 기존 `manifest.json`은 여전히 `status=complete`이고 old timeline/source sha를 가리킵니다. 그 짧은 구간에 viewer가 manifest와 audio를 읽으면 **old manifest + new audio** 조합이 노출됩니다. 스펙의 "manifest publish = 완료 마커"와 충돌합니다.

   해결안:
   - 가장 안전한 MVP: audio 파일명을 content/version 기반으로 publish합니다. 예: `<base>_ko_audio.<source_sha[:12]>.mp3`, manifest의 `audio.file`이 그 파일을 가리키고, manifest를 마지막에 `os.replace`합니다. `/audio/file`은 manifest를 읽어 현재 audio.file을 서빙합니다.
   - 단일 고정 파일명을 유지하려면 paper별 publish lock을 viewer read 경로까지 포함해야 합니다. 이건 과합니다.

   이 이슈는 R1/R2 합의의 "manifest가 완료 마커" 보장을 직접 깨므로 blocking입니다.

2. **Backend Task 8: converter GPU lock 경로가 현재 Docker mount와 맞지 않습니다.**

   위치: Plan 1 Task 8 Step 3

   현재 compose에서 converter는 `./outputs:/app/outputs`, viewer는 `./outputs:/data/outputs`입니다. Plan 1은 TTS에 `./outputs:/data/outputs`를 추가하고 `PF_GPU_LOCK=/data/outputs/.gpu.lock`를 씁니다. 그런데 Task 8은 `main_terminal.py`도 "동일 `/data/outputs/.gpu.lock`"으로 감싸라고 합니다. converter 컨테이너에는 `/data/outputs` mount가 없으므로 그대로 구현하면 lock file 경로가 없거나 별도 경로가 되어 상호배제가 완성되지 않습니다.

   해결안:
   - converter에도 `./outputs:/data/outputs`를 추가하고 `/data/outputs/.gpu.lock`로 통일하거나,
   - converter는 `/app/outputs/.gpu.lock`, TTS는 `/data/outputs/.gpu.lock`를 쓰되 둘이 같은 host bind mount의 같은 파일이라는 점을 명시합니다.

   지금 문구대로면 MinerU와 TTS 동시 GPU 점유 차단이 실패할 수 있어 blocking입니다.

3. **Backend Task 5 `synth.py`: `perth` 누락 fallback이 import 단계에서 실패합니다.**

   위치: Plan 1 Task 5 Step 1

   현재 코드:

   ```python
   import perth
   ...
   if perth.PerthImplicitWatermarker is None:
       perth.PerthImplicitWatermarker = perth.DummyWatermarker
   ```

   `perth` 모듈 자체가 설치되지 않은 경우 `import perth`에서 바로 `ModuleNotFoundError`가 나므로 Dummy fallback에 도달하지 못합니다. 스펙 §9.6이 `resemble-perth`를 non-blocking 정책 항목으로 둔 이유와도 맞지 않습니다.

   해결안:
   - `try/except ImportError`로 `perth` 모듈 stub을 만들거나,
   - `resemble-perth`를 requirements에 명시 설치하고 fallback 문구를 제거하거나,
   - Chatterbox import 전에 실제 샘플에서 썼던 monkeypatch 방식을 정확히 재현합니다.

   TTS sidecar가 시작도 못 할 수 있는 결함이라 blocking입니다.

4. **Frontend Task 3/4/6/7: `this.paperName` / `this.paperTitle`가 viewerApp 상태에 없습니다.**

   위치: Plan 2 Task 3 Step 2, Task 4 Step 2, Task 6 Step 1, Task 7 Step 1

   기존 `viewer.html`은 closure 변수 `const name = '{{ paper_name_encoded }}';`를 사용하고, return 객체에 `paperName`/`paperTitle` 속성이 없습니다. Plan 2의 코드들은 반복해서 다음처럼 호출합니다.

   ```javascript
   encodeURIComponent(this.paperName)
   this.paperTitle || this.paperName
   ```

   그대로 구현하면 URL이 `/api/papers/undefined/audio/...`가 되고 MediaSession title도 비어 동작이 깨집니다.

   해결안:
   - return 객체에 명시적으로 추가합니다.

   ```javascript
   paperName: decodeURIComponent(name),
   paperNameEncoded: name,
   paperTitle: '{{ paper_title|default(paper_name, true)|e }}',
   ```

   - API URL은 `this.paperNameEncoded` 또는 기존 closure `name`을 일관되게 씁니다. 이미 encoded된 `name`을 다시 `encodeURIComponent`하지 않도록 주의해야 합니다.

5. **Frontend Task 3: `loadAudio()` 삽입 위치가 기존 `loadMdForCurrentLang()`에 의해 덮어써질 수 있습니다.**

   위치: Plan 2 Task 3 Step 3

   기존 `toggleAudio()`는 `audioMode=true` 후 `await this.loadMdForCurrentLang()`를 호출합니다. 플랜 문구는 "`audioMode=true` 분기 끝에 `await this.loadAudio();` 추가"라고 되어 있는데, 이를 기존 `if (newMode) { ... }` 내부 끝에 넣으면 이후 `loadMdForCurrentLang()`이 기존 `/md-ko-audio`를 `marked.parse`로 렌더해 `mdKoAudioContent`를 다시 덮어쓸 수 있습니다. 그러면 D3 합의인 서버 렌더 HTML이 무력화됩니다.

   해결안:
   - audio mode에서는 `loadMdForCurrentLang()`이 `md-ko-audio`를 marked로 로드하지 않도록 분기하거나,
   - 기존 load 후 마지막에 `await this.loadAudio()`를 호출해 서버 HTML이 최종값이 되게 합니다.
   - 더 명확히는 `if (this.audioMode) await this.loadAudio(); else await this.loadMdForCurrentLang();` 구조가 좋습니다.

6. **Frontend Task 5는 Task 6 전까지 런타임 에러가 납니다.**

   위치: Plan 2 Task 5 Step 1

   `onTimeUpdate()`가 `this.throttledSaveListening()`을 호출하지만, 이 메서드는 Task 6에서야 추가됩니다. Task 5의 수동 검증 시점에는 `TypeError: this.throttledSaveListening is not a function`가 발생할 수 있습니다.

   해결안:
   - Task 5에서 저장 호출을 빼고 Task 6에서 추가하거나,
   - `if (this.throttledSaveListening) this.throttledSaveListening();`로 guard를 둡니다.

7. **Frontend Task 4: 기존 markdown click handler를 대체하면 회귀가 생깁니다.**

   위치: Plan 2 Task 4 Step 3

   현재 markdown container는 이미 `@click="handleMarkdownClickDesktop($event)"`를 갖고 있습니다. 플랜은 이를 `@click="onSentenceTap($event)"`로 바꾸는 예시를 제시합니다. 그대로 바꾸면 기존 데스크톱 click behavior가 사라질 수 있습니다.

   해결안:
   - 단일 handler에서 둘 다 호출합니다.

   ```html
   @click="onMarkdownClick($event)"
   ```

   ```javascript
   onMarkdownClick(e) {
     this.onSentenceTap(e);
     this.handleMarkdownClickDesktop(e);
   }
   ```

   기존 뷰어 상호작용 회귀 가능성이 있어 blocking으로 봅니다.

## Non-blocking Nit

1. **Task 1 sentence regex가 실제 한국어/따옴표 문장을 충분히 못 나눕니다.**
   - `_SENT_END = re.compile(r'(?<=[.!?…])\s+')`는 `문장입니다.” 다음 문장`처럼 종결부호 뒤 닫는 따옴표가 있는 경우 분리하지 못합니다. 또한 공백 없는 `다.다음`도 놓칩니다.
   - MVP에서는 `_ko_audio.md`가 정제되어 있어 치명적이지 않을 수 있지만, tests에 따옴표/괄호 케이스를 추가하는 편이 좋습니다.

2. **Task 2 manifest에 `generated_at`이 빠져 있습니다.**
   - 승인 스펙의 manifest 예시와 완료 마커 보완 항목에 `generated_at`이 있습니다. 구현에 추가하세요.

3. **Task 3 stitcher는 입력 WAV spec 통일을 코드로 강제하지 않습니다.**
   - 스펙은 "동일 spec WAV"를 전제하지만 Chatterbox/torchaudio 저장 format이 바뀌면 concat demuxer가 실패할 수 있습니다.
   - concat 전에 모든 chunk를 `pcm_s16le, mono, target sample_rate`로 normalize하거나 concat filter를 쓰는 편이 더 견고합니다.

4. **Task 3 tempdir cleanup이 없습니다.**
   - `tempfile.mkdtemp()` 후 삭제하지 않습니다. `TemporaryDirectory()`를 쓰는 것이 좋습니다.

5. **Task 6 job_id가 초 단위 timestamp라 충돌 가능성이 있습니다.**
   - paper별 active job이 있어도 직접 호출/재시도/테스트에서 같은 초에 충돌할 수 있습니다. `uuid4`를 붙이세요.

6. **Task 6 검증/재시도는 주석 수준입니다.**
   - 스펙 §8은 duration/text ratio 이상치 재시도와 readiness gate를 요구합니다. 플랜 self-review에서 v1.1로 미루겠다고 했지만, 스펙 MVP에 들어간 항목입니다. 최소한 "duration=0, ffprobe 실패, 극단 ratio"에 대한 1회 재시도는 Task 6에 넣는 편이 좋습니다.

7. **Task 7 sidecar API는 내부 전용이라도 path trust boundary를 적어두는 편이 좋습니다.**
   - viewer가 검증한다는 전제는 괜찮지만, sidecar가 `paper_dir`/`src_md`를 임의 절대경로로 받습니다. 최소한 `/data/outputs` 하위인지 검사하면 방어층이 생깁니다.

8. **Task 8 compose GPU 설정은 기존 서비스와 맞추는 편이 좋습니다.**
   - 기존 converter는 `runtime: nvidia`와 NVIDIA env를 씁니다. TTS 서비스도 같은 패턴을 추가하면 환경 차이를 줄일 수 있습니다.

9. **Task 9 viewer tests 경로가 기존 관례와 다릅니다.**
   - 플랜은 `viewer/app/tests/test_audio_api.py`를 사용하지만 기존 저장소는 `viewer/tests/*.py` 패턴입니다. 불가능하진 않지만, 기존 pytest 구조와 맞춰 `viewer/tests/test_audio_api.py`가 낫습니다.

10. **Task 9 progress 저장은 atomic write가 아닙니다.**
    - 개인용이라 큰 문제는 아니지만 기존 `reading_progress.json`와 마찬가지로 동시 write에 취약합니다. temp file + replace를 쓰면 좋습니다.

11. **`/audio/html`은 blockquote intro note를 렌더하지 않습니다.**
    - 승인 스펙은 blockquote를 TTS chunk/span에서 제외하되 화면에는 intro note로 표시한다고 했습니다. MVP에서 생략해도 치명적이지 않지만, 스펙 충실도를 위해 non-chunk note 렌더 여부를 결정하세요.

12. **Task 4 UI 버튼은 기존 UI 스타일과 맞춰 다듬어야 합니다.**
    - 플랜 예시는 emoji 버튼입니다. 실제 구현에서는 기존 버튼 스타일/아이콘 체계와 맞추는 편이 좋습니다.

## 커버리지 요약

스펙 커버리지는 전반적으로 좋습니다. backend는 chunker, manifest, stitch, lock, sidecar, viewer proxy, Range smoke까지 포함하고 frontend는 server HTML, single audio, timeupdate highlight, prev/next/tap, auto-follow, rate, resume, MediaSession까지 포함합니다. 다만 위 blocking 항목들은 실제 구현 성공 여부를 좌우합니다. 특히 atomic publish, GPU lock path, `paperName` 상태, audio mode load 순서는 반드시 플랜에 반영한 뒤 실행해야 합니다.

