# 세션 핸드오프 — PaperFlow 관리형 오디오 큐 UI + 듣기/합성 분리 + 시스템 상태 칩
_최종 갱신: 2026-06-04 17:17_

---

## ✅ 완료 (2026-06-04 17:17): URL 임포트 다운로드 4건 수정 + 배포

> 위 오디오 작업과 **무관**. `viewer` 의 "링크 주면 받아서 newones 에 넣기" (URL→PDF) 기능 버그 수정.

**증상**: 사용자가 "URL 임포트가 잘 안 된다" → 진단 결과 가장 흔한 입력(arXiv "Download PDF" 버튼 링크 `arxiv.org/pdf/<id>`)이 dead-end. 그 URL 자체가 이미 PDF인데도 site transformer 가 `/abs/` 만 매칭하고 arxiv.org 는 strict 도메인이라 다운로드 대신 예외를 던짐.

**수정 4건** (`viewer/app/services/papers.py`):
1. **arXiv `/pdf/` 링크 인식** — `_SITE_PDF_TRANSFORMERS` 에 신/구 스타일 `/pdf/` 패턴 추가 (확장자 유무·v1 모두).
2. **브라우저 UA 통일** — `_BROWSER_UA` 상수 신설, 직접 fetch/download(`_download_pdf`/`_fetch_url_html`/`_resolve_doi_redirect`)도 headless 와 동일한 진짜 Chrome UA 사용 (봇 차단 회피).
3. **strict 도메인 실패 메시지 구체화** — "페이월/자동접근 차단 가능, PDF 직접 링크 복사" 안내.
4. **품질 게이트 완화** — 인라인 로직을 순수 헬퍼 `_capture_rejection_reason()` 로 추출, 푸터 단어(terms/copyright/privacy)는 **짧은 캡처에서만** 거부(긴 본문 오탈락 제거); chromium 에 `--no-pdf-header-footer`·`--hide-scrollbars` 추가.

**TDD**: 실패 테스트 12개 선작성 → 구현 → 통과. `viewer/tests/test_papers_url_resolve.py` (16개 전체 green, viewer 전체 215개 회귀 없음).

**검증 (end-to-end, 실네트워크)**: `arxiv.org/pdf/2508.14052`·`…v1` → 2MB 다운로드 OK(이전 실패), IEEE strict → 새 안내 메시지, 일반 블로그 헤드리스 캡처 1.2MB(푸터 단어 있어도 통과).

**배포**: `docker compose build paperflow-viewer && up -d` 완료. 컨테이너 내부에서 수정 반영 + arxiv `/pdf/` 다운로드 재확인. converter 컨테이너 무영향.

**커밋**: `27d93e2` (papers.py + test 만). 워킹트리의 다른 수정 파일들(main_terminal.py, tts_service/*, templates 등)은 **이 작업과 무관 — 건드리지 않음**.

---

## 🆕 별도 진행 작업 (2026-06-04 시작): 듣기판(`_ko_audio.md`) **그림 임베딩** 재생성

> 아래 "관리형 오디오 큐" 작업과 **무관**. 이건 mp3가 아니라 **낭독용 마크다운(`_ko_audio.md`) 텍스트**를, paper-audio-korean 스킬의 **그림 임베딩 규칙(규칙 #3)** 에 맞게 다시 쓰는 콘텐츠 작업.

**왜**: 기존 듣기판 다수가 그림 임베딩 규칙 생기기 전에 만들어져 `![](경로)` 이미지가 0개. 사용자가 "듣기판도 그림 임베딩하라"고 재확인 → 소스 해설판엔 그림 있는데 듣기판엔 임베딩 0개인 것을 전수 재생성.

**범위/방식 (사용자 확정)**: 대상 **32개 전부 재생성**, **메인 에이전트 순차 처리**(서브에이전트 X). 큰 파일도 메인이 직접.

**재개용 — 남은 대상 도출 grep** (outputs+archives 스캔, "소스 그림>0 && 듣기판 임베딩==0"):
```bash
cd /media/restful3/data/workspace/paperflow
for base in outputs archives; do for f in "$base"/*/*_ko_audio.md; do [ -f "$f" ]||continue; dir=$(dirname "$f"); exp=$(ls "$dir"/*_ko_explained.md 2>/dev/null|head -1); [ -n "$exp" ]||continue; ia=$(grep -cE '!\[\]\(' "$f"); ie=$(grep -cE '!\[' "$exp"); [ "$ie" -gt 0 ]&&[ "$ia" -eq 0 ]&&echo "[$ie img] $dir"; done; done
```

**작업 절차 (한 폴더당)**:
1. 소스 `_ko_explained.md` 전체 통독(인벤토리: 섹션/표/그림/수식/코드/각주). 그림 위치 `grep -nE '!\[' 소스`.
2. paper-audio-korean 스킬 규칙대로 `.part`에 **완전 낭독판** 작성. 그림은 **묘사 문장 바로 뒤(1문단 내)** 에 `![](상대경로)` **alt 비움**으로 임베딩.
3. 검증+확정: `scripts/audio_finalize.sh "<paper_dir>" "<basename>" <expected_img>` → CRITICAL grep 통과 시 `.part`→최종 rename + sidecar 기록.

**결정 사항(일관 적용)**:
- 순수 장식/빈 이미지(예: hero 배너, 빈 색면)도 **임베딩 유지** + 짧고 정직한 한 줄 묘사(disk-todo 정합 + 사용자 선호). 묘사 없는 단독 이미지 금지.
- 뉴스레터 광고/푸터 내비게이션/이메일/URL은 **제거**(듣기 무가치). References/감사의 글도 제거.
- 숫자·참조번호: 그림 N→"그림 N 번", 장/절→"제N 장/절", 수식·표는 자연어 서술.

**⚠️ 데이터 위생 이슈 (미해결, 신중 처리)**: `outputs/Developer's guide to multi-agent patterns in ADK/` 폴더 **1개 안에 직선(') / 곡선(') 아포스트로피 basename 이 각각 `_ko_explained.md`+`_ko_audio.md`+`.meta.json` 으로 중복** 존재. 두 explained 동일본인지 확인 후 처리(임의 삭제 금지, 사용자 확인).

**이미지 출처 분류 (중요)**: 소스의 `![](URL)` 이 **외부 http(s) URL 이면 임베딩 불가**(스킬: 내부 상대경로만, URL 금지 + 다운로드 안 함) → 자연어 묘사만, grep-todo 에 영구 잔류(예외). **외부 전용 2편**: `Can the stockmarket...`(ext=1, 완료) · `유휴 Inference GPU Pool...`(ext=9, describe-only 예정). 나머지는 로컬 이미지라 임베딩 가능.

**임베딩 불가 예외 3종**(0 embed, describe-only, grep-todo 영구 잔류):
1. 외부 http(s) URL 이미지 (스킬: 내부 상대경로만)
2. 깨진/빈 경로 이미지 — `![alt](images/)` 처럼 파일명 없음, images/ 폴더에 실제 파일 0개 (추출 실패). 처리 전 `ls "<dir>/images/"` 로 실제 파일 유무 확인할 것.
3. 순수 장식/빈 색면 — 이건 임베딩은 함(짧은 묘사).
→ expected_img 정할 때 소스 `![` 개수가 아니라 **실제 임베딩 가능한 로컬 파일 수**로 셀 것.

**진행 (22/32 완료)** — +✅ Developer's Guide to AI Agent Protocols(12).  (구) — 앞 20편 + ✅ 5 OpenClaw agents(9). (완료 전체: Attention5·OpenTelemetry1·AI Agent Frameworks 2026 LangChain1·Can the stockmarket0외부·Anthropic Agent Skills1·AIAgent 8 SDKs2·7 Agentic AI Trends2·Microsoft Build2026 0빈경로·AI Agent Frameworks Detailed5·A2A5·TurboQuant5·VIBEVOICE6·Six search engines6·Equipping agents6·Agent observability7·Developer's guide multi-agent ADK15(양쪽basename)·Build Better AI Agents7·2026년 기업AI전환7·Building effective agents8·SelfExtend8·5 OpenClaw9)

finalize: `scripts/audio_finalize.sh "<dir>" "<basename>" <expected_img>` (expected = 실제 로컬 그림 수 localref).

**남은 8편 (+ 유휴GPU 외부 describe-only 1) — 전부 대형, expected_img**:
- Multi-Agent Collaboration Mechanisms A Survey of LLMs — 8 (⚠️1427줄 서베이, 그림 alt에 설명 있음)
- Build Long-running AI agents that pause... ADK — 13
- State of Model Context Protocol in Software 2026 — 13
- LLM Powered Autonomous Agents — 14
- DeepSeek-V3 Technical Report — 15
- (arc)State of Agent Engineering — 17
- 2026 Physician Survey on Augmented Intelligence — 24
- Bitcoin trader recovers $400,000... — 42 (최대)
- (outputs)유휴 Inference GPU Pool... — 0 (외부URL 9개, describe-only)
> 재개: 위 grep으로 남은 대상 재도출 → 소스 통독 → .part 작성(그림 묘사 뒤 `![](경로)` alt비움) → finalize. 학술논문은 그림 캡션이 본문 "그림 N 해설/캡션"에 있으면 그걸로 묘사(이미지 직접 안 봐도 됨).
> NFD 한글 경로(예: 2026년 기업…) 처리 패턴: explained를 /tmp ASCII로 cp → Read → .part를 /tmp에 작성 → bash로 실제 경로에 cp + sidecar.

---

## 🎯 목표
논문 오디오(mp3) 생성을 **관리형 큐**로 통합(등록 큐 UX 미러)하고, 뷰어의 **듣기 모드와 합성을 분리**하며, 앱 전역 **시스템 상태(CPU/RAM/GPU/VRAM) 칩**을 추가. 계획서: `docs/superpowers/plans/2026-06-04-paperflow-audio-queue-ui-plan.md`(Phase 1 + Phase 2 일부 완료).

## ✅ 완료 (이번 세션, 전부 배포·검증됨 — 미커밋)
### 관리형 오디오 큐 (Phase 1)
- **`tts_service/app/queue.py`(신규)**: `AudioQueue` — 영속 `.audio_queue.json` + enqueue(중복무시)/remove(processing 거부)/snapshot/enqueue_missing + 순차 드레인 워커(`drain_once`/`run_worker`) + 재시작 복구(`_recover`: processing→pending, fresh면 done). stage→status 매핑: ready→done, preempted/skipped→pending, failed→failed.
- **`tts_service/tests/test_queue.py`(신규, TDD 12개)** + **`test_system.py`(신규 2개)**. TTS 전체 **70 passed**.
- **`tts_service/app/main.py`**: `POST/DELETE/GET /queue`, `POST /queue/enqueue-missing`(내부전용, 웹 노출 제거), startup 워커 스레드, `GET /system`(GPU util+VRAM via nvidia-smi). 기존 `_process_candidate`(epoch 선점)·`should_run`(idle 게이트) 재사용.
- **`viewer/app/routers/api.py`**: 프록시 `POST/DELETE/GET /api/audio/queue`, `GET /api/audio/candidates`(outputs, md_ko_audio && !audio_mp3), `POST /api/audio/queue/batch`, `GET /api/system`(psutil CPU/RAM + TTS /system 프록시→gpu). 뷰어 **203 passed**.

### 듣기/합성 분리 + 라이브 TTS 제거 (`viewer/app/templates/viewer.html`)
- 듣기 토글은 **합성 안 함** — 완성 mp3만 재생, 없으면 "아이폰 내장 TTS로 들으세요" + **🎧 오디오 생성(큐)** 버튼.
- `generateAudio()`: foreground `/jobs` → **큐 추가**(`POST /api/audio/queue`)로 전환. `pollAudioGen()` 큐 인지 폴러(대기/생성중→완료시 ▶ 플레이어). 라이브 스트리밍 재생 경로는 이미 비활성(`audioStreamingPlayback=false`)이라 死분기.

### UI (`viewer/app/templates/papers.html`)
- **"🎧 오디오 큐" 탭**: 생성중(단계 분할/합성/병합 + N/M %)·대기·실패(재시도)·완료 + **활동 로그**(큐 폴링 diff로 ＋추가/▶시작/✓완료/✗실패 타임라인, 접기/펼치기).
- **카드/목록 행 🎧 버튼**(md_ko_audio 있을 때만 활성, mp3 있으면 emerald).
- **"오디오 없는 논문 선택…" 모달**("누락 전체 추가" 대체): 후보 목록(정렬 추가일/최근읽음/제목 · 종류 필터 · 전체/개별 체크박스 · 제출→batch enqueue).

### 시스템 상태 칩 (`viewer/app/templates/base.html` + papers/viewer 헤더)
- `systemStat()` 컴포넌트(base.html) + **각 페이지 헤더 안 인라인 칩**(papers nav lg+, viewer 상단바 xl+). CPU·RAM 4초 폴링, GPU·VRAM은 TTS `/system` 프록시로 채움. **떠있는 fixed 오버레이는 제거**(헤더 버튼과 겹쳐서).
- `viewer/requirements.txt`에 `psutil` 추가.

## 🔄 진행 중
- 없음. 큐 비어 있고 GPU idle(0%). 시스템 정상.

## ⏭️ 다음 단계
1. **커밋** — 아래 "미커밋" 목록 참고. 사용자 결정 대기(자동 커밋 안 함).
2. **"Do Multimodal Agents" 논문 실패 처리 결정** — 아래 발견 참고. 꼭 필요하면 GPU 쉰 뒤 재시도(산발적이면 통과) 또는 청크 격리/입력 검증.
3. **(선택) TTS 견고성 하드닝** — 한 청크의 CUDA assert가 전체 작업 죽이고 컨텍스트 오염 → "assert 감지 시 해당 작업만 fail + 컨텍스트 자동 복구(프로세스 재시작)" 별도 작업.
4. **(선택) Phase 2 잔여** — 카드 상태 배지 고도화, 자동 등록(크론 연계).

## 🧠 대화에만 있던 핵심 컨텍스트
- **GPU 경쟁 범인 = 하네스 백그라운드 작업 `bt1ssrj3a` "Run 6-paper audio re-synthesis"**(이전 세션 잔존). `docker exec curl`로 **foreground `/jobs`**를 쏘며 124편 백로그를 돌려 새 큐와 GPU 경쟁 → 호스트/컨테이너 프로세스로 안 보였음(하네스 작업이라). **이번 세션 중 완료(사망).** audio_watch 아님.
- **CUDA 컨텍스트 오염 메커니즘**: foreground 드라이버 + 큐가 동시에 12GB VRAM 점유 → OOM/충돌 → **device-side assert(`index out of bounds: 0 <= tmp5 < 8192`)** → 컨텍스트 poison → 이후 모든 합성 즉시 실패(error 필드 None, assert는 비동기). **복구 = TTS 재기동(새 CUDA 컨텍스트)**.
- **TTS 클린 리셋 레시피**: `docker compose stop paperflow-tts` → `echo "[]" > outputs/.audio_queue.json` → 문제 논문 `audio/.locks`·`*_ko_audio.<sha>`·`*_ko_audio.manifest.json` rm → `docker compose start paperflow-tts`. (flock은 재시작 시 해제됨.)
- **audio_watch는 무관 — 절대 건드리지 말 것**: `~/.openclaw/workspace/scripts/audio_watch/`는 **음성 녹음(.m4a) 받아쓰기 → 회의록/랩노트** 시스템(watcher가 "새로운 녹음 40.m4a" 류 enqueue). 논문 TTS와 무관. cron은 `#PAUSED#`. 정리하면 회의록 파이프라인 손상.
- **설계 결정**: ① 듣기≠합성(듣기=텍스트+완성mp3, 합성은 명시적 큐) ② 라이브 TTS 스트리밍 제거(완성본만 재생) ③ "누락 전체 추가"는 위험 → 후보 선택 모달로 대체 ④ 시스템 칩은 헤더 인라인(오버레이 겹침 회피) ⑤ GPU/VRAM은 viewer에 GPU 없으니 TTS `/system` 프록시(viewer `/api/system`이 실패 시 gpu=null → TTS만 추가하면 자동 채워지게 배선).
- **"Do Multimodal Agents Really Benefit from Tool Use..." 논문 발견**: 12/105까지 정상 진행하다 **CUDA assert로 실패**. 청크 9\~14 텍스트는 지극히 정상(이상 유니코드/초장문 없음) → 단순 데이터 문제로 보긴 어려움. 이 논문 특정 입력이거나 오늘 혹사된 GPU 산발적 불안정. **자동 재시도 꺼둠(큐 비움)**.
- **큐 워커 메커니즘**: 큐 워커가 foreground와 **같은 `_jobs` 진행 dict 공유** → viewer `/audio/status` 폴링이 큐 진행률도 반영. `should_start`는 idle일 때만(foreground 선점). **실패 항목 재투입은 중복 생성**(enqueue 중복판정은 pending/processing만) → 실패 재시도 시 큐 파일 비우고 재enqueue 권장.
- **TTS 엔진 = VoxCPM2**(이전 핸드오프의 Qwen 아님). `VOXCPM_VOICE=09_chaewon`, ~11.4GB VRAM 피크(12GB 카드). 단일 GPU → 큐 순차.
- **이미지 스킵 청커**(`tts_service/app/chunker.py`, 세션 시작 전부터 M): 이미지 전용 라인(`![](...)`) 제거 — 긴 hex 파일명이 TTS wedge 유발 방지. 큐 워커가 그대로 사용.
- **테스트 실행**: tts `cd tts_service && rtk proxy python -m pytest`(70 passed), viewer `cd viewer && rtk proxy python -m pytest`(203 passed). **rtk proxy 필수**(아니면 pytest 출력이 "No tests collected"로 요약됨). JS 문법은 Jinja 렌더 후 `<script>` 추출 → `node --check`.
- **큐/시스템 런타임 조회**(TTS 외부포트 없음): `docker exec paperflow_viewer python3 -c "import urllib.request,json; print(urllib.request.urlopen('http://paperflow-tts:8100/queue',timeout=8).read().decode())"`. /system도 동일.

## ⚠️ 클리어 전 주의
- **미커밋(이번 세션 산출물 — 커밋은 사용자 결정)**:
  - 수정(M): `tts_service/app/main.py`, `viewer/app/routers/api.py`, `viewer/app/templates/{base,papers,viewer}.html`, `viewer/requirements.txt`
  - 신규(??): `tts_service/app/queue.py`, `tts_service/tests/test_queue.py`, `tts_service/tests/test_system.py`
  - **세션 무관(건드리지 말 것 — 세션 시작 전부터 있던 상태)**: `main_terminal.py`(M), `tts_service/app/chunker.py`(M), `docs/superpowers/plans/2026-06-04-*-plan.md`(??), `samples/`·`scripts/dsba_poll/`·`tests/`(??), `tts_service/tests/test_chunker_image_skip.py`(??).
  - 이 핸드오프 갱신으로 `HANDOFF.md`도 M 상태가 됨.
- **백그라운드**: 내 monitor/watch 스크립트 전부 종료(임시 `/tmp/wait_*.sh`·`watch_synth.sh` 삭제됨). 경쟁 드라이버 `bt1ssrj3a` 사망. docker **3컨테이너 정상 가동**(converter/tts/viewer) — 클리어해도 유지. **큐 비어있고 GPU idle**이라 진행 중 합성 없음.
- **미완료 todo**: 없음(이번 세션 task 전부 completed).
- **배포 상태**: 모든 변경이 **배포 이미지에 반영됨**(tts·viewer 재빌드 완료). 코드는 워킹트리에만, 이미지에는 빌드돼 있음. 브라우저는 하드 리프레시(Ctrl+Shift+R) 필요.

## 🧩 이전 작업(별개 워크스트림, 참고용)
- **HLS 실시간 스트리밍**(2026-06-01 세션): 구현·배포 완료, **유일 미해결 = 실기기 iPhone Safari preflight**(스펙 §12.3). 상세는 git 히스토리(commit 트레일 `f5752e4`까지 push) + `docs/superpowers/plans/2026-05-31-paperflow-hls-streaming-*.md`. 이번 듣기/합성 분리에서 라이브 스트리밍 재생 경로는 비활성화됨(완성 mp3만 재생).

## 📂 관련 파일
- `docs/superpowers/plans/2026-06-04-paperflow-audio-queue-ui-plan.md` — 이번 작업 계획(Phase 1 완료, Phase 2 일부)
- `tts_service/app/queue.py` — 큐 엔진(핵심)
- `tts_service/app/main.py` — 큐 4 엔드포인트 + `/system`(GPU) + 워커 기동
- `viewer/app/routers/api.py` — 큐 프록시 + `/api/audio/candidates` + `/api/audio/queue/batch` + `/api/system`
- `viewer/app/templates/papers.html` — 오디오 큐 탭 + 후보 모달 + 카드/목록 🎧
- `viewer/app/templates/viewer.html` — 듣기/합성 분리 + 큐 생성 버튼 + 시스템 칩(xl)
- `viewer/app/templates/base.html` — `systemStat()` 컴포넌트
- `~/.openclaw/workspace/scripts/audio_watch/` — ⚠️ 음성 녹음 받아쓰기(논문 무관, 건드리지 말 것)
