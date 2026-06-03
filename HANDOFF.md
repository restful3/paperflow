# 세션 핸드오프 — PaperFlow 한국어 TTS (MVP 배포 + HLS Plan 1·2 구현·검증 완료)
_최종 갱신: 2026-06-01 (위 + **VoxCPM2 교체 §F + 생성-먼저·MCP 오디오/배치·Codex 3R 리뷰 §G**)_

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
- **추가 픽스 — 듣기 토글 언어 게이팅 (commit `eac1c35`)**: "듣기" 토글이 `hasMdKoAudio` 만으로 떠서 **EN 보기 중에도 표시**됐음(문서 "KO 전용" 의도와 불일치). → 두 버튼(`viewer.html:345,564`) `x-show` 에 `$store.lang.ko &&` 추가 → 현재 언어에 낭독 오디오가 있을 때만 표시(오늘은 KO 오디오만 존재, EN 분기는 자연 숨김; 없는 `hasMdEnAudio` 미리 안 만듦=추측성 배제). **동반 수정**: lang `$watch` 가 EN 전환 시 audioMode 자동 해제(버튼이 lang 게이트라 안 그러면 audioMode 켜진 채 버튼 숨겨져 빠져나올 길 없음 — 내 변경이 유발한 stuck 방지). Playwright 5/5 PASS(KO 표시·EN 숨김·KO 듣기진입 audioMode=true·EN전환 자동해제·버튼숨김).
- **추가 픽스 2건 — 속도표시 + live-edge 자동재개 (commit `ccaef64`)**: ① **속도 0.8 오표시**: 속도 드롭다운이 `x-for` 옵션이라 `x-model` 초기화 시점에 옵션이 없어 첫 항목(0.8)으로 떨어졌음(실재생은 1.0). → 정적 `<option>`(값은 `x-model.number` 매칭 위해 1.0→`"1"`)으로 교체. 검증: 1.0x 표시·`audioRate=1`·1.5x 선택 시 `playbackRate=1.5`. ② **live-edge 스톨**: 스트리밍(EVENT 플레이리스트) 재생이 합성된 마지막 세그먼트를 따라잡으면 멈추고 자동재개 안 돼 사용자가 듣기 토글로 수동 복구해야 했음(=재부착). → `@waiting`→`onAudioStall()`: 6s 디바운스 후에도 같은 currentTime·`status==='streaming'` 이면 `remountAudio()`(플레이리스트 재로드+새 토큰=토글과 동일). HLS+스트리밍 한정, 완성본 정상 EOF, remount 30s/3회 백오프로 루프방지, `@playing` 이 타이머 클리어. 검증: 핸들러 wiring + 정상재생 무영향(currentTime 전진). **실 live-edge 복구는 헤드리스 재현 곤란 → 실청취/iPhone preflight 에서 최종 확인**. (콘솔 `require is not defined` 는 CDN UMD 라이브러리發 기존 무관 에러.)
- **TTS 엔진 교체: Chatterbox → Qwen3-TTS (commit `3076599`)**: Chatterbox 가 한국어 숫자/연도(2025년·55.34·1.1)를 오독 + 여성화자 없음 → **Qwen3-TTS-12Hz-1.7B-CustomVoice** 로 교체. 내장 한국어 여성화자 **Sohee**, **숫자 정규화 내장**(사용자 청취 확인 "숫자가 아주 깔끔해"). **수술적 교체** — `synth.py`(엔진)+`requirements.txt`(qwen-tts+torch/torchaudio 2.10.0+cu128)+`Dockerfile`(apt sox; numpy/typing_extensions 선설치 후 pysox `--no-build-isolation` 빌드)만 변경, `load_model`/`synth_chunk`/`model_revision` 시그니처·HLS 파이프라인·워치독·tts 33 테스트 그대로. `model_revision`=`모델@화자` 라 artifact_version 변경→모든 논문 차회 청취 시 Qwen 으로 재생성(구 Chatterbox 버전은 `_cleanup_old_versions` 로 grace 후 정리). 검증: 컨테이너 합성 4.0s→5.9s(RTF 0.68, VRAM 4.8GB), POST /jobs end-to-end 로 새 Qwen 버전 dir(e489f27e335f)+HLS 세그먼트 생성 확인. env `QWEN_TTS_MODEL`/`QWEN_TTS_SPEAKER` 로 모델·화자 교체 가능. **호스트 PoC venv `~/qwen-tts-poc`** 는 삭제됨. textnorm_ko(숫자 정규화 레이어)는 Qwen 이 내장 처리하므로 **불필요해짐**.
- **아나운서 톤 (commit `3ee67c5`)**: Sohee 기본이 감정 풍부 → `generate_custom_voice(instruct=...)` 로 중립 뉴스 아나운서 딜리버리 지시. `QWEN_TTS_INSTRUCT` env(기본=아나운서 지시), `model_revision` 에 포함→톤 변경 시 재생성. timbre 는 Sohee 유지.
- **협조적 선점 + 모델 사전로드 (commit `270d40d`)**: GPU 1개·FIFO·선점부재로 거대 논문(980청크)이 큐를 막아 "준비중 안 끝남" → **최신 요청 논문이 foreground target**, 백그라운드 `run_job` 이 청크 사이 `is_active()` 체크해 target 바뀌면 `Preempted`(gpu_lock 해제) → 새 논문 즉시 GPU 획득. 양보된 작업은 `preempted`(재트리거 가능). 부팅 시 모델 사전로드 스레드로 첫 작업 ~80s 콜드로드 제거(= "플레이버튼 떠도 한참 후 재생" latency 큰 원인). 검증: 부팅 후 무작업 GPU 4.4GB(로드됨), A 합성 중 B 트리거→A=preempted·B=synthesizing, tts 34 테스트(선점 테스트 포함). **기존 오디오 전체 삭제됨**(사용자 요청, 8 audio dir 제거; `_ko_audio.md` 11개 보존) — 재생 시 Qwen+아나운서로 새로 생성. **남은 한계**: 980청크 같은 큰 논문은 합성이 ~실시간이라 워밍업 latency 는 본질적(선점·사전로드로 완화하나 0 아님).
- **추가 픽스 — 잠금화면 prev/next 문장 단위 (commit `3909358`)**: iPad 제어콘솔/잠금화면의 앞·뒤 버튼이 문장이 아니라 ±초 스킵으로 동작. 원인: MediaSession 에 prev/next(문장)와 seekbackward/forward(±10s)를 둘 다 등록했는데 **iOS/iPadOS 는 seek 핸들러가 있으면 잠금화면에 ±초 스킵 버튼을 우선 노출**. → `seekbackward`/`seekforward` 를 `null` 등록(제거)해 iOS 가 ⏮/⏭(previoustrack/nexttrack=`prevSentence`/`nextSentence`) 버튼을 띄우게 함. 트레이드오프: 잠금화면 ±10초 스킵 사라짐(앱 내 ⏮/⏭·문장 탭 시크는 유지). 헤드리스로 **핸들러 등록 상태 검증 PASS**(prev/next=fn, seek=null) — **실제 잠금화면 버튼 동작은 iPad 실기기 확인 필요(preflight)**.
- **인시던트 + 워치독 — 합성 wedge로 "준비 중" 무한 (commit `f020ece`)**: "AI Agent Frameworks" 스트리밍 job이 **첫 청크에서 wedge** — 모델/GPU가 ~3\~7 it/s(정상 ~45)로 열화돼 `synth_chunk(chunk 0)` 가 4분+ 반환 안 함. GPU는 바쁜데 세그먼트 0, heartbeat 동결(시작값), status streaming 고정(실패도 안 함) → 뷰어 "오디오 준비 중" 무한. **즉시 해소**: `docker compose restart paperflow-tts`(멈춘 generate 종료 + 모델 신규 로드). 재시작 후 1청크 합성 2.3s로 정상 회복 확인 → 코드 아닌 **런타임 열화**. **근본 갭 수정**: `job.py` `_synth_with_timeout` 워치독 스레드 추가 — `SYNTH_CHUNK_TIMEOUT`(기본 90s) 초과 시 `_synth_encode_with_retry` 가 None→`_fail_partial` 로 풀어 무한 대기 대신 앞부분 재생/실패 표면화. fail-fast(타임아웃 시 재시도 안 함)로 GPU 동시 generate 회피. **한계**: CUDA 커널 인터럽트 불가 → wedge 된 데몬 스레드는 컨테이너 재시작 전까지 GPU 점유(단 job 상태/락은 즉시 해제). tts 33 passed(워치독 회귀 테스트 포함).

### F. TTS 엔진 교체: Qwen3-TTS → VoxCPM2 (commit `551b88b`, main 로컬·미push)
- **동기**: 사용자가 VoxCPM2 한국어 숫자/연도 발음을 Qwen보다 선호. PoC 3단계 청취 검증 후 결정 — (1) 숫자 문단 단발 합성 OK, (2) voice-design 프롬프트는 **청크마다 다른 사람** 됨(일관성 실패), (3) **고정 참조 WAV 클로닝**(`prompt_wav_path`+`prompt_text`)으로 청크 간 음색 고정 확인 → 이 방식 채택.
- **음성 라이브러리**: voice-design 으로 20대 중반 여성·중립 아나운서 톤 10종 생성 후 사용자가 선별 → **활성 4종(4 수아·6 예린·7 다은·9 채원), 기본=9 채원**. voice-design 은 비결정적이라 **생성된 WAV 가 그 목소리의 유일 원본** → `tts_service/voices/<key>.wav` + `voices.json`(전사) 번들, 이미지에 COPY. (8·10 비활성 보관: `~/voxcpm-poc/voices/`. 1·2·3·5 는 사용자 요청 삭제됨=복구불가.)
- **수술 범위**(Qwen 교체와 동일): `synth.py`(엔진+음성해석+`model_revision`) + `requirements.txt`(voxcpm + **torch 2.5.1+cu121**, qwen-tts/2.10+cu128 대체) + `Dockerfile`(pysox/sox 제거, voices COPY) + `docker-compose.yml`(`VOXCPM_VOICE=09_chaewon`, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`). `synth_chunk`/`model_revision` 시그니처·HLS·gpulock·선점 그대로. `model_revision`=`openbmb/VoxCPM2@<voice>` → **음성 바꾸면 artifact_version 달라져 오디오 자동 재생성**(Codex Finding 2 캐시키 메커니즘).
- **스모크 중 발견·수정한 실버그 (TDD)**: **모델 이중로드 OOM** — 부팅 프리로드 스레드가 VoxCPM2 로드(~80s, torch.compile 워밍업) 중 `_MODEL=None` 인 사이 job 워커가 **두 번째 인스턴스 동시 로드** → 12GB 카드에 모델 2개 → OOM/실패. `load_model` 에 **double-checked 락**(`_MODEL_LOCK`) 추가 → 동시 호출이 단일 인스턴스 공유. 회귀 테스트 `test_load_model_loads_once_under_concurrency`(동시 5호출→1회 로드) RED→GREEN.
- **테스트**: `tts_service/tests/test_synth_voice.py` 6종 신규(음성 해석·env override·model_revision·동시 로드). **tts 43 passed**.
- **스모크 PASS**(실 파이프라인): "The next evolution of the Agents SDK"(282청크) POST /jobs → expandable_segments + 단일 인스턴스로 **OOM 없이 synthesizing 진행**, 9번 채원 목소리 세그먼트 생성. 첫 6청크 청취 샘플 `pipeline_voice9_sample.mp3`(repo root, git 미추적).
- **VoxCPM2 운영 메모(중요)**: 12GB RTX 3060 에서 **모델 상주 ~5.5\~7GB + 합성 피크 ~8GB**(Qwen 4.8GB 보다 큼). 단일 인스턴스+expandable_segments 로 안정. **RTF ~1.3(실시간보다 느림)** — Qwen 0.68 보다 느려 워밍업/live-edge 지연은 본질적(완전 제거 불가). 모델 가중치는 `model_cache` 볼륨에 사전시드(`./model_cache/huggingface/hub/models--openbmb--VoxCPM2`, 컨테이너 재다운로드 없음). Apache-2.0(라이선스 깔끔).
- **PoC 환경(휘발성·정리 후보)**: 호스트 venv `~/voxcpm-poc`(torch 2.5.1+cu121 + voxcpm + 음성 원본 6종 + PoC 스크립트). 호스트 `~/.cache/huggingface` VoxCPM2 4.7GB(model_cache 에 사본 있음→삭제가능). 샘플 mp3들(`voice_samples/`, `pipeline_voice9_sample.mp3`, `voxcpm2_*.mp3`). **`~/voxcpm-poc/voices/` 의 비활성 8·10 + 활성 원본은 voice-design 비결정성 때문에 유일본 — 삭제 주의.**
- **뷰어 무변경**: HLS 스트리밍이 엔진-불가지(viewer 는 m3u8/세그먼트만 재생) → 뷰어 재빌드 불필요. 기존 논문은 재생 시 VoxCPM2/채원으로 자동 재생성.
- **음성 추가/교체 방법**: voice-design 으로 새 WAV 생성(`~/voxcpm-poc/` 참고) → `tts_service/voices/` 에 wav + `voices.json` 엔트리 추가 → 이미지 재빌드. 기본 음성 변경은 compose `VOXCPM_VOICE` 또는 `.env`.

### G. 생성-먼저 정책 + MCP 오디오/배치 도구 (commit `c547f04`, main 로컬·미push)
- **동기**: 사용자가 라이브 스트리밍을 실제로 써보니 ① 재생 멈춤 ② 따라가기(하이라이트)가 음성보다 먼저 멈춤. 원인 측정 결과 **VoxCPM2 RTF≈1.3(실시간보다 느림, RTX 3060)** — timesteps 를 10→4 로 낮춰도 1.36→1.26밖에 안 떨어짐(병목=AR 토큰생성, diffusion 아님) → **라이브 스트리밍은 이 HW에서 불가**. 사용자가 "둘 다(속도+생성먼저)" 택했으나 속도는 막다른 길로 판명 → **생성-먼저(VOD) 단일 정책**.
- **인시던트(재생 중 자폭)**: 멈췄을 때 사용자가 "재생성"을 눌러 `DELETE /audio` 가 합성 중 디렉터리를 통째로 지움 → 워커가 `.w000017.wav` 쓰다 죽음. → **삭제 가드** 도입.
- **생성-먼저 구현(viewer.html 무변경 원칙 최대 유지)**: `api.py` stream-url 이 `AUDIO_REQUIRE_COMPLETE`(config 기본 True)면 status 가 complete/failed_partial 아니면 **425** → 프론트가 기존 "준비 중 N/총" 표시·재시도 → 완료 시 mount(끊김 없는 VOD·따라가기 정합). 프론트는 `audioStreamingPlayback: true→false` 한 줄(라이브 머신러리는 opt-in 으로 잔존). delete 가드: `audio.py is_synthesis_active`(status=streaming + heartbeat<120s) → `DELETE /audio` 409.
- **MCP 6도구**(`mcp_router.py`): `generate_audio`·`get_audio_status`·`get_audio_result`·`delete_audio(confirm)`·`generate_audio_batch`·`get_audio_batch_status`. 논문참조=`paper`(name)+`location`. `audio.py resolve_for_audio`(outputs 전용·`_ko_audio.md` 필요, 아니면 ValueError) + `_tts_json`(httpx 에러를 agent용 ValueError 로 정규화). **배치=기존 sweep 재사용**: tts `POST /sweep`(on-demand)·`GET /sweep`(상태) 신규.
- **배치 동시성 모델(Codex 3R로 다듬음)**: `run_sweep` 가 `_worker` 의미(progress_cb·terminal state·선점)를 `process_one` 으로 재사용 + idle-gate(`should_start`) + 실패후보 skip. 배치는 `_current_target`(foreground 전용) 안 건드리고 **`_foreground_epoch` 스냅샷**으로 선점 판단(foreground /jobs 오면 epoch↑ → 배치 양보). **`_SWEEP_RUN_LOCK`** single-flight(daemon↔on-demand 상호배제). **`_try_claim_batch`** atomic claim(`_lock` 안 활성 job 재확인+epoch+등록 → should_start↔snapshot TOCTOU 차단, 활성이면 "skipped").
- **Codex 리뷰 3라운드(peer-council, paperflow 세션, 캡쳐 `/tmp/codex_response_2026060*.txt`)**: R1 BLOCKING(run_sweep `_jobs` 영구 segmenting)+HIGH(idle/선점 우회, MCP httpx 에러) → R2 HIGH(배치가 _current_target 역선점 race, daemon↔on-demand 미배제, `_jobs` lock없는 순회) → R3 HIGH(claim TOCTOU). **R3까지 전부 TDD 수정**. R3의 마지막 claim atomicity 는 코드 수정·테스트 통과했으나 **max 3R 캡 도달로 Codex 4차 재리뷰는 안 받음**(Codex 가 "이 race만 막으면 BLOCKING/HIGH 없음"이라 한 지점).
- **테스트**: tts 52 passed(sweep·동시성 신규), viewer 200 passed. 라이브 스모크 OK(6도구·아카이브 거부·confirm 가드·에러 정규화·배치 sweep).
- **남은 한계/결정(Codex non-blocking 동의)**: ① **아카이브 논문 오디오 불가**(tts outputs 전용, `safe_paper_dir` 가 archives 반환 시 거부) ② 삭제 가드 좁은 race(job accepted~manifest publish 전, defer) ③ `failed_partial` stream-url 허용(의도적 부분재생) ④ `_SWEEP_RUN_LOCK` 점유 중 `/sweep` 은 `started:true` 후 즉시 종료(메시지 약간 부정확).
- **커밋 범위 주의**: c547f04 는 같은 파일 얽힘 때문에 §G(생성먼저·MCP) + 세션 시작 시점의 미커밋 M1(failed_partial)·M2(lock 대기 heartbeat)·delete_audio 안정화를 **한 커밋에 묶음**. viewer.html 307줄 diff 대부분은 기존 스트리밍 작업(내 변경은 flag 1줄).

## ✅ 남은 것 (BLOCKING — 자동화 불가, 수동)
- **실기기 iPhone Safari preflight**(스펙 §12.3): signed token 으로 m3u8/segment 쿠키없이 통과 · 첫 audible(1\~3 세그) · 잠금화면/백그라운드/네트워크전환 지속재생 · 완료 VOD seek · MediaSession/AirPods. 통과 시 HLS 기능 GA.

## 🔄 진행 중
- **활성 Qwen 합성 3건(streaming, 선점 테스트·논문열기 잔여)**: "Anthropic launches…"(21/223), "Building effective agents"(88/406), "Multi-Agent…"(4/980). 선점 구조라 마지막 요청 1개만 실제 진행, 나머지는 양보(preempted)되거나 대기. **정리 불필요** — 재생 시 foreground 우선 처리됨. 클리어해도 tts 가 계속 처리(핸들만 잃음).
- **아나운서 톤 사용자 청취 확인 미완**: 톤 instruct 적용·배포됐으나 사용자가 최종 "괜찮다" 확인 전. 별로면 `QWEN_TTS_INSTRUCT` 조정(env 또는 synth.py).

## ⏭️ 다음 단계
1. **아나운서 톤 청취 확인** — 뷰어에서 논문 재생해 중립 아나운서 톤 적절한지 판단. 조정 필요 시 `QWEN_TTS_INSTRUCT` 수정 → tts 재빌드(COPY app, 빠름).
2. **미push 커밋 2건 push** — `3ee67c5`(아나운서)·`270d40d`(선점) (원하면).
3. **실기기 iPhone Safari preflight**(스펙 §12.3) — HLS 의 유일 BLOCKING. 통과 시 GA. (Qwen 전환 무관하게 여전히 필요.)
4. (선택) v1.1: 선점 ping-pong 방지(빠른 논문 전환 시), generation counter.

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
- **TTS 엔진 = Qwen3-TTS (이번 세션 교체)**: `tts_service` 컨테이너 안에서 실행(host venv 아님 — `~/qwen-tts-poc` 삭제됨). 모델 가중치는 `model_cache` 볼륨(`/root/.cache`)에 캐시. RTF ~0.68, VRAM ~4.8GB. 화자 Sohee(한국어 여성)+아나운서 instruct. **숫자/연도 내장 정규화**(Chatterbox 의 오독 문제 해결). Qwen Flash 는 voice clone 미지원이나 CustomVoice 의 preset 화자+instruct 로 충분.
- **한글 폴더명 NFC/NFD 함정**: outputs 의 한글 폴더/파일명은 디스크에 **NFD(자모 분해)** 로 저장됨. tts `/jobs` 에 경로를 보낼 때 NFC 문자열을 하드코딩하면 **404(파일 못 찾음)**. → `glob.glob` 로 실제 경로를 얻거나 `unicodedata.normalize('NFC', p)` 로 매칭. (이번 세션 트리거 시 실제 발생.)
- **선점/사전로드 (이번 세션)**: 최신 요청 논문이 foreground, 백그라운드는 `Preempted` 로 양보(gpu_lock 해제). 모델은 부팅 시 사전로드(첫 작업 콜드로드 제거). 큰 논문(980청크)의 ~실시간 합성 워밍업 지연은 본질적 한계(완전 제거 불가).
- **기존 오디오 전체 삭제됨**(사용자 요청): 모든 `outputs/*/audio` 제거, `_ko_audio.md` 11개 보존. 재생 시 Qwen+아나운서로 새로 생성.

## ⚠️ 클리어 전 주의
- **이번 세션 HLS 산출물은 전부 main 에 로컬 커밋됨**(Plan1+2 + Codex 픽스 + 후속 버그픽스 §E + Qwen 교체·아나운서톤·선점, 마지막 `270d40d`). **`f5752e4` 까지 origin/main 에 push 됨**; 이후 `3ee67c5`·`270d40d` 는 로컬(미push).
- **커밋 안 된 변경 = 전부 세션 무관(건드리지 말 것)**: `.gitignore`(M), PNG 16개 삭제(D), `test_container_tui.txt`(D), `_tail30s_sample.mp3`(??), `docs/superpowers/plans/2026-05-26-*-plan.md`(??) — **세션 시작 시점부터 있던 기존 워킹트리 상태.**
  - 단, **이 핸드오프 갱신으로 `HANDOFF.md`가 다시 M 상태**가 됨(상태 파일, 커밋은 사용자 결정 — `git add HANDOFF.md && git commit` 으로 별도 커밋 가능).
- **백그라운드**: 활성 bash 셸 없음(전부 foreground 종료). docker **3컨테이너 실행 중**(converter/tts/viewer, 정상). **tts 가 Qwen 합성 진행 중**(streaming 3건, GPU ~72%) — 클리어해도 계속 처리되나 핸들 잃음. `peer-council-codex.service` 상시(클리어 후 유지).
- **임시(휘발성, 재부팅 시 소실)**: `/tmp/pwverify`(playwright venv). `~/qwen-tts-poc` 는 삭제됨. Qwen 모델 가중치는 `./model_cache`(영구, 컨테이너 `/root/.cache`).
- **미완료 todo**: 없음(이번 세션 task 전부 completed).

## 📂 관련 파일
- `docs/superpowers/specs/2026-05-31-paperflow-hls-streaming-design.md` — HLS 스펙 R2(승인)
- `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-backend.md` — HLS Plan 1(백엔드, 승인, Task0 실측부터)
- `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-frontend.md` — HLS Plan 2(프론트, 승인)
- `docs/reviews/2026-05-31-hls-tts-*.md` — Codex 합의 트레일(spec R1/R2, plans R1/R2)
- `tts_service/app/` — MVP 백엔드(chunker/manifest/stitch/synth/gpulock/job/main). HLS는 여기에 segtoken/hls/sweep 추가 + job/manifest 수정.
- `viewer/app/{services/audio.py,routers/api.py,config.py,templates/viewer.html}` — MVP 뷰어. HLS는 stream-url/m3u8/seg 추가 + 플레이어 HLS 전환.
- `docs/superpowers/specs/2026-05-31-paperflow-live-tts-design.md` + `plans/2026-05-31-paperflow-live-tts-{backend,frontend}.md` — MVP 선행 문서(구현 완료).
