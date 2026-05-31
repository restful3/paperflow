# PaperFlow 라이브 한국어 TTS 구현 플랜 리뷰 — Codex Round 2

판정: **BLOCKING 이슈 있음.** 아직 `===PLANS_APPROVED===`를 줄 수 없습니다.

1차 리뷰의 큰 blocking 7건은 대부분 방향성 있게 반영됐습니다. Atomic publish는 versioned audio로 개선됐고, GPU lock 경로도 host inode 기준으로 정리됐으며, perth import, 기존 click handler, audio-mode load 순서, 진행률 저장 guard도 반영됐습니다. 다만 갱신된 플랜 안에 그대로 실행하면 테스트나 런타임이 깨지는 코드 결함이 남아 있습니다.

## Blocking

1. **Plan 2 Task 3: `const name = name;`는 JavaScript TDZ 런타임 에러입니다.**

   위치: Plan 2 Task 3 Step 2 `loadAudio`, `mountAudioHtml`, `generateAudio`, `pollAudioJob`

   현재 코드:

   ```javascript
   async loadAudio() {
     const name = name;
     const r = await apiFetch(`/api/papers/${name}/audio/manifest`);
     ...
   }
   ```

   함수 안의 `const name`이 바깥 closure 변수 `name`을 shadowing하기 때문에 초기화 오른쪽의 `name`도 새 lexical binding을 가리킵니다. 결과는 `ReferenceError: Cannot access 'name' before initialization`입니다. B4의 의도는 맞지만 코드가 반대로 깨졌습니다.

   수정안:

   ```javascript
   async loadAudio() {
     const r = await apiFetch(`/api/papers/${name}/audio/manifest`);
     ...
   }
   ```

   또는 return 객체에 `paperNameEncoded: name`을 두고 모든 audio URL에서 `this.paperNameEncoded`를 쓰세요. 중요한 것은 이미 encoded된 closure `name`을 재인코딩하지 않는 것이지, 같은 이름의 `const`를 재선언하는 것이 아닙니다.

2. **Plan 1 Task 1: 닫는 따옴표 문장분할 테스트가 현재 구현으로 실패합니다.**

   위치: Plan 1 Task 1 Step 1/3

   테스트:

   ```python
   md = '그는 "좋다." 라고 말했다. 다음 문장.'
   assert texts == ['그는 "좋다."', "라고 말했다.", "다음 문장."]
   ```

   구현:

   ```python
   _SENT_END = re.compile(r'(?<=[.!?…])[”’"\')\]】」』]?\s+')
   parts = _SENT_END.split(...)
   ```

   이 패턴은 optional closing quote를 delimiter 일부로 소비합니다. 따라서 첫 조각은 `그는 "좋다.`처럼 닫는 따옴표가 사라질 수 있어 테스트 기대값과 맞지 않습니다. 즉 "nit 반영"이 오히려 failing test를 만듭니다.

   수정안은 quote를 split delimiter로 소비하지 않는 방식이어야 합니다. 예를 들어 문장 추출형 regex로 바꾸거나, split 전에 종결부호+닫는따옴표+공백 뒤에 sentinel을 삽입한 뒤 sentinel로 나누는 방식이 안전합니다. 현재 코드 그대로는 Task 1 PASS가 불가능하므로 blocking입니다.

3. **Plan 2 Task 2: test 경로가 Plan 1과 다시 불일치합니다.**

   위치: Plan 2 Task 2 Files/Step 1/Step 2/Step 5/Step 6

   Plan 1 Round 2는 nit를 반영해 `viewer/tests/test_audio_api.py`를 사용합니다. 그런데 Plan 2 Task 2는 다시 `viewer/app/tests/test_audio_api.py`와 `cd viewer && python -m pytest app/tests/test_audio_api.py...`를 사용합니다. 실제 저장소의 기존 관례도 `viewer/tests/*.py`입니다.

   Plan 2가 Plan 1의 test file에 append해야 하는 구조라면 이 경로 불일치는 실행 단계에서 바로 실패하거나, 같은 이름의 테스트 파일이 두 곳에 생기는 혼선을 만듭니다.

   수정안:

   - Plan 2 Task 2의 test path와 pytest command를 모두 `viewer/tests/test_audio_api.py`로 통일
   - commit 명령도 `viewer/tests/test_audio_api.py`로 수정

4. **Versioned audio publish는 개선됐지만 `/audio/file` race가 완전히 닫히지 않았습니다.**

   위치: Plan 1 Task 9 + Plan 2 Task 4 `audioSrc()`

   Backend는 manifest의 `audio.file`을 읽어 현재 versioned mp3를 서빙합니다. 이 자체는 B1의 fixed filename overwrite 문제를 크게 줄입니다. 하지만 frontend는 여전히 manifest를 먼저 받고, audio src는 항상 다음 고정 endpoint입니다.

   ```javascript
   audioSrc() { return `/api/papers/${name}/audio/file`; }
   ```

   이 경우 사용자가 old manifest를 받은 직후 재생 전 재생성이 완료되면 `/audio/file`은 new manifest의 new audio를 서빙할 수 있습니다. 그러면 old timeline + new audio 조합이 다시 생깁니다. fixed filename overwrite보다는 훨씬 좁은 race지만, "manifest가 완료 마커이고 audio.file이 그 manifest의 artifact"라는 설계와는 아직 어긋납니다.

   수정안 중 하나를 플랜에 명시하세요.

   - `/audio/file?version=<source_sha12>` 또는 `/audio/file?file=<manifest.audio.file>`을 지원하고, backend가 manifest/audio file 일치성을 검증한 뒤 해당 versioned file을 서빙한다.
   - 또는 `/audio/file/{filename}`처럼 manifest의 `audio.file`을 URL에 포함한다. 단 path traversal 방어 필요.
   - frontend `audioSrc()`는 `this.audioManifest.audio.file` 또는 `this.audioManifest.source.sha256`을 반영한 stable URL을 만든다.

   이 race는 드물지만, B1에서 고친 원자성 이슈의 남은 절반입니다. 구현 전에 닫는 것이 맞습니다.

## Non-blocking Nit

1. **Plan 1 산출물 설명이 아직 고정 mp3 파일명을 보여줍니다.**
   - File Structure의 산출물 예시는 `outputs/<paper>/audio/<base>_ko_audio.mp3`로 남아 있습니다.
   - 실제 Task 6은 `<base>_ko_audio.<sha12>.mp3`를 사용하므로 문서 상단 예시도 맞춰야 합니다.

2. **Plan 1 Task 1 Expected가 `PASS (3 passed)`로 남아 있습니다.**
   - 테스트가 4개가 됐으므로 `PASS (4 passed)`가 맞습니다.

3. **Plan 2 Task 1 이후 Plan 1 self-review의 type consistency 설명은 `level`을 빠뜨립니다.**
   - 실제 최종 manifest consumer는 `level`을 사용하므로 Plan 1 self-review도 `level` 포함으로 맞추면 좋습니다.

4. **Sidecar status API가 cache-hit instant complete를 명확히 표현하지 않습니다.**
   - `run_job`이 freshness skip으로 즉시 반환해도 `_worker` callback은 `segmenting` 후 `ready` 정도로 보일 수 있습니다.
   - 큰 문제는 아니지만 `POST /jobs`가 최신 캐시를 viewer side에서 먼저 감지하거나, sidecar response/status에 `cached: true`를 줄 수 있으면 UX가 더 명확합니다.

5. **`_chunk_ok` ratio 범위는 heading에 너무 엄격할 수 있습니다.**
   - `서론` 같은 2자 heading이 1초 이상이면 `sec_per_char=0.5`라 통과하지만, 짧은 heading에서 모델이 긴 pause/intonation을 만들면 재시도 후 실패할 수 있습니다.
   - MVP에서는 괜찮을 수 있으나 heading/text별 ratio를 분리하면 더 안정적입니다.

6. **`save_listening_progress` atomic write는 디렉터리 보장을 추가하면 좋습니다.**
   - 현재 `BASE_DIR`는 존재하겠지만, 일반화하려면 `pf.parent.mkdir(parents=True, exist_ok=True)`를 넣으면 더 안전합니다.

7. **MediaSession action handler도 `play()` rejection을 무시합니다.**
   - 인앱 버튼은 catch가 있지만 MediaSession play handler는 `a.play()`만 호출합니다. non-blocking이지만 `catch(() => {})` 정도는 붙일 수 있습니다.

## 종합

이전 blocking의 설계 방향은 거의 해소됐습니다. 남은 문제는 주로 갱신 과정에서 들어간 구체 코드 결함입니다. 특히 Plan 2의 `const name = name`과 Plan 1의 quote-consuming sentence split은 실제 실행 즉시 깨지므로 승인 전 수정이 필요합니다. `/audio/file` version race도 B1 원자성 보장을 완성하려면 이번 플랜에 명시하는 편이 맞습니다.

