# 세션 핸드오프 — PaperFlow 한국어 TTS (MVP 배포 + HLS Plan 1·2 구현·검증 완료)
_최종 갱신: 2026-05-31 (HLS Plan 1·2 완료 + 액세스로그 redaction 버그픽스·워밍업 문구 개선)_

## 🎯 목표
`_ko_audio.md`(한국어 낭독 텍스트)를 뷰어에서 듣는 기능. **두 단계**:
1. **라이브 TTS MVP**(배치 합성→단일 mp3) — **구현·검증·배포 완료, 동작 중.**
2. **HLS 실시간 스트리밍**(첫 문장부터 점진 재생) — **백엔드 Plan 1 + 프론트 Plan 2 구현·검증 완료. 남은 것: 실기기(iPhone) preflight 만.**

## ✅ 완료
### A. 라이브 TTS MVP (구현·검증·배포 — 동작 중)
- Plan 1 백엔드 10태스크 + Plan 2 프론트 8태스크 전부 TDD 구현·커밋. tts 사이드카(`tts_service/`, Chatterbox-Multilingual) 신규 + viewer 오디오 플레이어.
- Docker 3컨테이너 가동: `paperflow-tts`(9.45GB), `paperflow-viewer`, `paperflow-converter`. **`http://localhost:8090`** 듣기 토글 → ▶ 재생.
- 통합 스모크 PASS("The next evolution of the Agents SDK", 256문장→26.7분 오디오). 끝부분 샘플 `_tail30s_sample.mp3`(임시).
- 프론트 Playwright 검증: 로그인→듣기→재생+하이라이트→prev/next→탭→이어듣기 전부 ✅.
- **테스트 중 발견·수정한 버그 3건**: ① 라우트 섀도잉(`/audio/progress`→`/audio/position`) ② 하이라이트 미표시(`this.$el`→`document` + `audioCurChunk=-1` 리셋) ③ chunker `re.sub` raw `\x00` `bad escape`.
- **MVP 후속 픽스**: ① 빈 `.jobs/` 정리 ② 캐시히트 job이 `segmenting`에 멈추던 버그(`_worker`가 `run_job` 반환 후 `ready` 보장) ③ `.dockerignore`에 `model_cache/` 추가(converter 빌드 6분→2.5초).

### B. HLS 백엔드 Plan 1 (구현·통합 스모크 완료 — main 직접 커밋)
- **전 11개 태스크(Task 0\~10) TDD 구현·커밋.** tts: `segtoken.py`/`hls.py`/`sweep.py` 신규 + `chunker.py`/`manifest.py`/`job.py`/`main.py` 수정. viewer: `services/audio.py`(v1/v2 경로·reconcile)·`routers/api.py`(stream-url/m3u8/seg)·`main.py`(로그 redaction)·`services/tts_token.py`(segtoken byte-identical 복제). compose에 SWEEP_*/AUDIO_TOKEN_SECRET env.
- **Task 0 실측 결정**(`docs/research/2026-05-31-hls-tts-measurement.md`): n=200 표본 → **TARGETDURATION=16s, SENTENCE_CHAR_CAP=85자**, 세그먼트 음량 `alimiter=limit=0.95`. glitch(모델 토큰반복) 5.5%는 길이게이트+재합성으로 처리, cap엔 정상 worst sec/char(0.1692) 사용.
- **테스트**: tts 30 passed, viewer audio+token 16 passed.
- **통합 스모크 PASS**(실 합성): 업프런트 223청크 publish→status=streaming, 증분 타이밍, stream-url ptoken, playlist 토큰 주입, 세그먼트 **Range 206**(video/mp2t), bad-token **403**.
- **스모크 중 발견·수정한 버그 1건**: `reconcile_stale`가 갓 시작한(heartbeat=None) streaming manifest를 즉시 failed로 뒤집어 failed↔streaming 깜빡임 → `run_job`이 **생성 시점에 heartbeat 설정**(commit a7d92a7) + viewer 회귀 테스트.
- **커밋 트레일**(main): 1472836(측정) · 6893c5b(segtoken) · 9a2eaac(chunker) · 2a9e840(hls) · a22fb38(manifest v2) · f7b3a26(job) · dbe361a(sweep) · d303f06(main) · 1ce63b5(viewer audio) · 3518ca7(viewer api) · a7d92a7(heartbeat fix) · e9f7308(compose).
- 미반영: 스펙 §5.3의 "재분할 1회" 는 플랜대로 **재합성(TTS 분산) 1회**로 구현(upfront-publish 모델 유지). sweep 기본 OFF.

### C. Codex 백엔드 리뷰 (peer-council, 회의실=paperflow 세션) — 전부 반영·검증
- **Finding 1 (BLOCKING)**: `encode_segment` 가 MPEG-TS `format.duration`(AAC priming/PTS로 ~0.25s 과소보고 → 누적 분 단위 드리프트 + 게이트 허술)을 씀 → **입력 wav+pad 권위 클록**으로 변경(stitch mp3와 동일 클록). 실 세그먼트로 EXTINF가 decoded와 ~0.05~0.08s(priming)까지 근접 확인. commit 0c89ab8.
- **Finding 2 (HIGH→재논의 후 MEDIUM)**: HLS dir/mp3/token 이 source sha 만으로 키잉 → model/cache-key 변경 재생성이 immutable 경로 덮어씀. Codex 재논의 결과 단일사용자 v1 blocker 아님이나 사용자 결정으로 **지금 수정**: `artifact_version = sha256(source_sha + CACHE_KEY_FIELDS)[:12]` 를 manifest.audio.version 에 저장→dir/mp3/token 바인딩(viewer 는 audio.version 으로 해석, v1 은 source sha 폴백). generation counter 는 v1 over-engineering이라 제외(same-source 재시도 오버랩은 v1 범위 밖). commit 5ff1ca0, e2e 검증(dir==manifest==expected digest).
- **Finding 3 (MEDIUM)**: cleanup grace 가 tts env TTL 을 읽는데 compose 미전달 → `AUDIO_TOKEN_TTL`/`AUDIO_RESUME_GRACE` 를 tts 에도 전달. commit 0c89ab8.
- **하드닝**: `reconcile_stale` 가 heartbeat 부재 시 manifest mtime 폴백(0c89ab8). flaky `test_tamper_rejected`(trailing base64 변조) → 결정적 byte-flip(a056a60).
- **Codex가 OK 한 것**: Task0 결정(16/85), heartbeat 픽스, 잠금 중첩, failed_partial, sweep denylist, traversal 이중가드, cache 헤더, 로그 redaction.
- 회의록: `council minutes`(paperflow 세션). 캡처: /tmp/codex_response_20260531_193701.txt(리뷰), _195152.txt(Finding2 재논의).
- **백엔드 최종 테스트**: tts 32 passed(×3 안정), viewer 18 passed(×3). 통합 스모크 PASS.

### D. HLS 프론트엔드 Plan 2 (구현·Playwright 검증 완료 — main 직접 커밋)
- **7태스크 구현**: base.html(hls.js 1.5.17 pinned+SRI, `referrer=same-origin`) + viewer.html `viewerApp()` HLS 플레이어.
  - `attachHls()`: 네이티브(`<audio src>`, iOS 1급 경로) / hls.js(withCredentials) 분기, signed playlist URL(`/audio/stream-url`); v1 단일 mp3 폴백.
  - 생성 중 streaming mount(첫 세그먼트부터; `pollAudioJob` 이 segmenting/synthesizing 중에도 mount, 425 → 재시도).
  - `pollStreamingManifest()`: id-keyed timing 머지(중복 append 금지).
  - `onTimeUpdate()`: v2 sentence_group 전체 강조 / v1(그룹 없음) 단일 chunk 폴백; `chunkAt` 은 start_sec=null 건너뜀.
  - `remountAudio`/`onAudioError`/`setupHlsErrorHandling`: 토큰 만료 remount(네이티브+hls.js), fatal 시 mp3 폴백.
  - 이어듣기: `audio.version` + currentTime, streaming-safe(time_sec ≤ duration_sec).
- **Playwright 검증 PASS**(실 브라우저, 네이티브 HLS 경로 = iOS 경로): audioIsHls·stream-url 호출·m3u8+세그먼트 토큰 fetch·**실재생+그룹 하이라이트**(currentTime 5.9s)·id-keyed merge(282청크 중복0)·토큰만료 remount(stream-url 재발급)·425/200 게이팅. 4 hard assert PASS.
- **커밋**(main): 283d241(base.html hls.js+SRI), 704fd8b(viewer HLS 플레이어), 54ead15(Codex 리뷰 픽스).
- 플랜 대비 보강: onTimeUpdate 의 v1(sentence_group 없는 기존 manifest) 단일-chunk 폴백 추가(플랜 코드는 v1에서 전체강조 버그 가능) — 직접 수정.

#### Codex 프론트 리뷰 — 전부 반영·Playwright 검증 (commit 54ead15)
- **HIGH#1**: `<audio>` 가 `x-if="view==='md'"` 아래라 PDF/split/편집 전환 시 DOM 파괴되는데 `_audioMounted` 가 true 로 남아 복귀 시 빈 플레이어(내가 `:src` 제거하며 만든 회귀). → `reattachAudio()` 를 audio 엘리먼트 `x-init` 로 연결, 재생성된 엘리먼트에 재부착. 검증: 전환→파괴 확인, 복귀→source 재부착 확인.
- **HIGH#2**: remount 무한루프 위험(403/네트워크 지속 실패 시 stream-url 난타) → `remountAudio` 가 30s 창 3회 캡 후 mp3 폴백/중단. 검증: 6회 강제실패 → attachHls 3회만 시도.
- **MEDIUM**: `seekToChunk` 가 미생성 streaming chunk(start_sec=null)에 0.001 로 점프 → null 가드.
- **Cleanup**: `:src` 제거로 dead 가 된 `audioSrc()` 삭제.
- **Codex가 OK**: 폴링 race 없음, 토큰 노출 수용가능(same-origin+no-referrer), withCredentials+token 무해, v1/v2 폴백.
- **Playwright 8/8 PASS**(네이티브=iOS 경로): audioIsHls·stream-url·id-keyed merge·재생+그룹하이라이트·뷰전환 재부착·remount 백오프·게이팅. 캡처 /tmp/codex_response_20260531_203402.txt.

### E. 후속 버그픽스 — 액세스 로그 redaction + 워밍업 문구 (commit `ba62d30`, main)
- **증상**: 사용자가 듣기 오디오 생성 직후 "소리가 안 난다" → 조사 결과 **고장 아님**. HLS 합성 워밍업 구간에 `stream-url` 이 `425 Too Early`(세그먼트 0)를 반환하다가 첫 세그먼트 준비되면 200→m3u8→seg fetch 로 자동 재생됨(설계대로). 로그 순서로 확인(425×3 → 200 → m3u8 200 → seg 200).
- **곁에서 발견·수정한 실버그 (b)**: `viewer/app/main.py` `_TokenRedactFilter` 가 `str(a)` 로 **모든** 로그 arg 를 문자열화 → uvicorn.access msg 의 `%d`(상태코드 int)가 `"200"` 이 되어 `%d % "200"` → **모든 액세스 로그 줄**이 `TypeError` 로 깨져 `--- Logging error ---` + `Arguments: (...)` 폴백 출력만 나오고 있었음(토큰 유무 무관). → **문자열 arg 만 마스킹**(`isinstance(a, str)` 가드), 비문자열 통과. 토큰은 경로 문자열에만 들어가므로 마스킹 손실 없음. 회귀 테스트 `test_redact_filter_preserves_int_status_code`(실 uvicorn.access 레코드: msg `%d` + int arg) 추가 → **viewer 19 passed**. 라이브 검증: `"GET /login HTTP/1.1" 200 OK` 정상 + `seg_0.ts?token=REDACTED ... 403` (상태코드 렌더 + redaction 동시 확인, Logging error 없음).
- **개선 (a)**: 워밍업 인디케이터 문구 `생성 중… (stage done/total)` → `오디오 준비 중 — 곧 자동 재생됩니다 (stage done/total)`(`viewer.html:768`). 진행 스피너 자체는 이미 존재했음(`audioGenerating` 블록) — 425 구간 "왜 소리가 안 나지" 혼란만 문구로 해소.
- **반영**: `paperflow-viewer` 재빌드·재기동 완료(클린 기동, 3컨테이너 정상). 컨테이너 내 `main.py:25` `isinstance` 가드 확인.

## ✅ 남은 것 (BLOCKING — 자동화 불가, 수동)
- **실기기 iPhone Safari preflight**(스펙 §12.3): signed token 으로 m3u8/segment 쿠키없이 통과 · 첫 audible(1\~3 세그) · 잠금화면/백그라운드/네트워크전환 지속재생 · 완료 VOD seek · MediaSession/AirPods. 통과 시 HLS 기능 GA.

## 🔄 진행 중
- 없음. 활성 합성 job 없음(tts 재시작으로 스모크 job 종료됨).
- **스모크 잔여 v2 오디오**(outputs/): "The next evolution of the Agents SDK"·"Anthropic launches enterprise…" = **complete**(정상 산출물). "7 Agentic AI Trends…"·"The 2026 MCP Roadmap" = **stale streaming**(재시작으로 중단됨, heartbeat 만료 → 다음 접근 시 `reconcile_stale`이 failed 로 전이, 또는 듣기 재생성으로 완료). 정리 불필요 — 정상 동작.

## ⏭️ 다음 단계
1. **실기기 iPhone Safari preflight**(위 "남은 것", 스펙 §12.3) — 유일한 BLOCKING. 통과 시 HLS GA.
   - 백엔드·프론트 모두 구현·Codex리뷰·Playwright(네이티브 경로) 검증 완료. 남은 건 실제 iPhone 동작뿐.
2. (선택) v1.1: artifact_version generation counter(same-source 재시도 오버랩), sweep 완전 preemption.

## 🧠 대화에만 있던 핵심 컨텍스트
- **왜 HLS인가**: 단일 `<audio>` mp3는 "재생 중 파일 append" 불가(고정 Content-Length), iPhone Safari는 오디오 MSE 사실상 미지원 → HLS(Apple 네이티브 progressive)가 무빙 윈도우의 정답. 사용자가 "무빙 스티치" 아이디어를 냈고 그게 HLS로 귀결됨.
- **왜 signed token(쿠키 아님)**: iOS 네이티브 AVPlayer는 playlist/segment를 AppleCoreMedia 경로로 가져가 HttpOnly/SameSite 쿠키가 안 붙을 수 있음 → HMAC signed token(playlist+segment 2종, paper×버전 바인딩)을 1급 설계로. signed playlist URL(`/audio/stream-url`→`?ptoken=`)이 iOS 1급 경로.
- **과길이 처리 절충**: 스펙 §5.3은 "재분할 1회 재시도"지만, upfront-publish(전체 chunks 고정 id) 모델을 깨지 않으려 **"재합성(TTS 분산) 1회"**로 구현. Task0 cap이 1차 방어. Codex 수용함.
- **heading 버그**: 내 초안 job.py가 `kind!="text" continue`로 heading 제외하며 "MVP 동일"이라 적었으나, **실제 MVP는 heading도 합성** → 수정(heading 포함 전체 chunk).
- **sweep 기본 OFF**: foreground preemption 미보장이라 v1은 `SWEEP_ENABLED=false`+캡. 완전 preemption은 v1.1.
- **Codex 채널**: `peer-council` 스킬(`council ask codex`)을 씀 — tmux `codex` 윈도우가 아니라 **상시 `peer-council-codex.service`**(허브 `~/.peer-council/hub.db`). 사용자가 "지금대로 council 서비스" 유지 선택. 회의록 세션 `hls-tts-spec`.
- **MVP 핵심**: 단일 stitched mp3 + manifest(문장 timeline) + 단일 `<audio>`+currentTime 하이라이트. `_ko_audio.md`는 paper-audio-korean 스킬이 디스크에 직접 생성(배치 파이프라인 아님).
- **실측**: Chatterbox RTF ~0.59, 0.35청크/s. 854문장 = ~40분(MVP 단일mp3의 대기 문제 → HLS 동기).
- **테스트 실행법(비자명 — 환경 함정 있음)**:
  - tts 단위테스트: `cd tts_service`; system `python3`엔 torch는 있으나 **torchaudio 없음** → `app.job/synth` import 실패. 우회: torchaudio stub 주입 후 pytest 호출 — `python3 -c "import sys,types; sys.modules['torchaudio']=types.ModuleType('torchaudio'); import pytest; sys.exit(pytest.main(['tests/','-q']))"`. (테스트는 monkeypatch라 실제 torchaudio 불요.) `/tmp/cbx-venv`엔 torchaudio 있으나 **pytest·pip 없음**(합성 전용).
  - viewer 단위테스트: `cd viewer && JWT_SECRET_KEY=$(python3 -c "print('x'*48)") python3 -m pytest tests/test_audio_api.py tests/test_tts_token.py -q`. (`.env`가 LOGIN_ID/PW를 덮으므로 TestClient 테스트의 `_client`가 settings를 monkeypatch함.)
  - **Playwright(실 브라우저)**: `/tmp/pwverify`(python playwright, 재부팅 시 소실). 스크립트는 **`/tmp` 밖**에 두거나 맨 위에서 `sys.path=[p for p in sys.path if p not in ('','/tmp')]` — `/tmp`에 누군가의 `inspect.py`가 있어 stdlib `inspect`를 가려 import 깨짐(measurement/playwright에서 실제 발생). 로그인은 page.evaluate fetch('/api/login')로 쿠키 주입. 이 Chromium은 `canPlayType('application/vnd.apple.mpegurl')`=truthy라 **네이티브 HLS 경로**(=iOS 경로)를 탐.
  - bash 출력에 가끔 **토렌트(FC2-PPV) 텍스트가 섞임**(다른 백그라운드 작업의 stdout 오염) — 무시. grep -v로 필터.
- **합성 시간 주의**: 한 논문(200\~280문장) 전체 합성 ~20\~30분. 스모크는 완주 대신 streaming 초반(첫 세그먼트~수 개)만 검증하면 충분.

## ⚠️ 클리어 전 주의
- **이번 세션 HLS 산출물은 전부 main 에 로컬 커밋됨**(Plan1+2 + Codex 픽스 + 후속 버그픽스 §E, 마지막 `ba62d30`). **push 안 함**(요청 없었음) — 원하면 사용자가 push.
- **커밋 안 된 변경 = 전부 세션 무관(건드리지 말 것)**: `.gitignore`(M), PNG 16개 삭제(D), `test_container_tui.txt`(D), `_tail30s_sample.mp3`(??), `docs/superpowers/plans/2026-05-26-*-plan.md`(??) — **세션 시작 시점부터 있던 기존 워킹트리 상태.**
  - 단, **이 핸드오프 갱신으로 `HANDOFF.md`가 다시 M 상태**가 됨(상태 파일, 커밋은 사용자 결정 — `git add HANDOFF.md && git commit` 으로 별도 커밋 가능).
- **백그라운드**: 활성 bash 셸 없음(측정·스모크·폴링 전부 종료). docker **3컨테이너 실행 중**(converter/tts/viewer, 정상). `peer-council-codex.service` 상시(클리어 후 유지). 활성 GPU 합성 job 없음.
- **임시(휘발성, 재부팅 시 소실)**: `/tmp/cbx-venv`(Chatterbox 합성 venv, pytest/pip 없음), `/tmp/pwverify`(playwright venv). 모델 가중치는 `~/.cache/huggingface`·`./model_cache`(영구).
- **미완료 todo**: 없음(이번 세션 task 전부 completed).

## 📂 관련 파일
- `docs/superpowers/specs/2026-05-31-paperflow-hls-streaming-design.md` — HLS 스펙 R2(승인)
- `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md` — HLS Plan 1(백엔드, 승인, Task0 실측부터)
- `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-frontend.md` — HLS Plan 2(프론트, 승인)
- `docs/reviews/2026-05-31-hls-tts-*.md` — Codex 합의 트레일(spec R1/R2, plans R1/R2)
- `tts_service/app/` — MVP 백엔드(chunker/manifest/stitch/synth/gpulock/job/main). HLS는 여기에 segtoken/hls/sweep 추가 + job/manifest 수정.
- `viewer/app/{services/audio.py,routers/api.py,config.py,templates/viewer.html}` — MVP 뷰어. HLS는 stream-url/m3u8/seg 추가 + 플레이어 HLS 전환.
- `docs/superpowers/specs/2026-05-31-paperflow-live-tts-design.md` + `plans/2026-05-31-paperflow-live-tts-{backend,frontend}.md` — MVP 선행 문서(구현 완료).
