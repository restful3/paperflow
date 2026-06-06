# 세션 핸드오프 — PaperFlow 축약 낭독판(`_ko_audio_brief`) 기능
_최종 갱신: 2026-06-06 (세션 클리어 준비)_

> ⚠️ 이 파일은 **현재 세션(축약 낭독판 기능 + 목록 UI/크론)** 을 맨 위에 두고, 그 아래에 **이전 세션(콘텐츠 일괄생성)** 과 **더 이전 워크스트림(그림 임베딩 / 오디오 큐 UI / 절대금지)** 을 압축 보존했습니다. 아래 섹션들은 별개 작업이니 혼동 주의.

## 🎯 목표 (현재 세션)
논문 풀 낭독판(`_ko_audio.md`)이 너무 길어(~69분) 듣기 괴로움 → **축약 낭독판 `_ko_audio_brief.md`(~20분/~7천자)** 를 추가 tier로 구현. 해설판에서 핵심만 요약, 뷰어 "듣기"에서 축약을 기본 노출 + "전체" 스위치, 길이 게이팅 야간 크론으로 자동 생성.

## ✅ 완료 (현재 세션)
**축약 낭독판 기능 — main 병합 완료(8커밋, push 안 함), 255 테스트 green, 배포·실검증 끝:**
- 백엔드: `_ko_audio_brief.md` 감지(2블록)·`get_md_ko_audio_brief_path`·API `/md-ko-audio-brief`·en/ko/RAG/mcp_zip 제외 가드.
- 뷰어: 듣기=축약 우선 + "전체/요약" 스위치(`hasMdKoAudioBrief && hasMdKoAudio`일 때만), mp3는 full 전용(`!audioUsesBrief`), 첫화면 기본 `audio_brief>audio>해설>원문`. 헬퍼 `hasAudioText`/`audioUsesBrief`/`activeAudioApiType`.
- 스킬 신규: `.claude/skills/paper-audio-brief-korean/SKILL.md` (해설판→~7천자 요약, 위생규칙 계승).
- 자동화: `~/.openclaw/workspace/skills/paperflow-claude-batch-audio-brief/scripts/{find_missing_audio_brief.py,dispatch_batch_audio_brief.sh}` + **Tori 크론 `84813b2b…` 매일 06:00 KST**.
- 목록 UI: 듣기 스피커가 축약본 있으면 **틸(teal)** 색(없으면 sky), mp3는 emerald 링 직교. 커밋 `2028dd2`.
- **실검증**: `outputs/데이터 프라이버시가 성장 전략이다/` 에 수동으로 `_ko_audio_brief.md`(7,251자) 1편 생성·CRITICAL grep 0건·sidecar OK → 뷰어 `info.md_ko_audio_brief:true`·`/md-ko-audio-brief` 200 확인.

**이번 세션 그 외(이미 main 커밋):**
- `pub_label` 발행 연·월 배지(`publication_date→arXiv YYMM→year`, "25.12") + 모바일 리스트 연월/사이즈 노출 — `211f328`.
- viewer 첫화면 기본 우선순위(낭독>해설>원문) — `536fe0b`.
- `article` 정식 doc_type(추출기 canonical) + 목록 타입필터 데이터기반화 + 배지색 — `211f328`,`75368ea`.

**운영(크론) 변경:**
- 해설판 크론 `261432e6…` → `0 1-23/2 * * *`(홀수시), 낭독판 `989addee…` → `0 0-22/2 * * *`(짝수시). 2시간 간격으로 변경(원래 03:30/05:00 1회).
- busy-skip 집계 1회성 크론 `25e31ac4…` → 2026-06-08 09:00 KST 텔레그램 보고. 스크립트 `~/.openclaw/workspace/scripts/paperflow_busyskip_report.py`.

## 🔄 진행 중 (현재 세션)
- 없음. 축약 낭독판 전체 완료·병합·배포·실검증까지 끝.

## ⏭️ 다음 단계 (현재 세션)
1. **오늘 밤(06-07 06:00) 축약 크론 첫 실행** 관찰 — 텔레그램 "대상 N편" 보고 + 목록에서 그 논문들 스피커 틸 확인. (대기열 ~10편, dispatch `--limit 10`/밤.)
2. (사용자에게 물어본 미결) 크론 결과 **자동 집계 1회성 리포트** 만들지 여부 — 원하면 busy-skip 리포트처럼 추가.
3. (후속) **phase 2 — 축약본 mp3 합성**: 현재 텍스트만(iPhone 내장 TTS로 듣기). `tts_service` 큐에 `_ko_audio_brief.md` 태우는 별도 스펙 필요.
4. (선택) 며칠 써보고 teal 색·"전체/요약" pill 가독성·축약 분량(~7천자) 피드백 → 스킬 프롬프트/뷰어 미세조정.

## 🧠 대화에만 있던 핵심 컨텍스트 (현재 세션)
- **설계 결정(사용자 승인)**: ① 추가형(풀 낭독판 유지, 대체 아님) ② 소스=해설판(`_ko_explained`, 번역본 아님) ③ 목표 ~7천자/~20분 ④ 길이 게이팅: **풀 audio >10,000자**일 때만 ⑤ 스킬은 별도 형제 스킬(모드 아님) ⑥ 듣기=축약 우선 + 전체 스위치.
- **stale 재생성**: finder는 brief 있어도 sidecar 없음/`status!=complete`/`source_sha256` 불일치면 재생성(=해설판 갱신 시 자동). `is_brief_stale()`에 `isinstance(meta,dict)` 가드 있음(비-dict JSON 크래시 방지).
- **경로 동일성**: `/home/restful3/workspace` → `/media/restful3/data/workspace` **심링크**(동일 inode). cron이 쓰는 `/home/...outputs` = docker 뷰어가 읽는 `/media/...outputs`. 불일치 없음(검증함).
- **피어리뷰 3라운드(Codex)**: NO-GO×2 → GO. 잡은 실버그: split뷰 동기화 누락, RAG 테스트가 `.content`(ChatChunk) 아닌 `.text`로 빈검증하던 것, mcp_zip 누출, brief-only 경로. 회의록은 council(현 tmux 세션).
- **teal 색 주의**: venue 배지(틸 pill)와 색 계열 겹치나 모양·위치 달라 구분. amber는 해설 링과 겹쳐서 기각하고 teal 선택.
- **목록 발견성 phase-1**: 축약 전용 배지는 스피커 색만(별도 텍스트 칩 안 만듦). 더 또렷하게 원하면 추가 가능.
- **doc_type `article`**: 추출기 canonical 아니었고 웹임포트(HBR/네이버)만 붙이던 타입 → 추출기에 추가해 통일(기존 43편 그대로 일관).
- **한글/이모지 폴더 NFC/NFD 함정**: 리터럴 매칭 실패 잦음 → `find outputs -path "*ASCII조각*"` / `ls -d outputs/*/ | grep` 우회. `outputs/`는 gitignored.

## ⚠️ 클리어 전 주의 (현재 세션 기준)
- **커밋 안 됨(내 작업 아님 — 건드리지 않음)**: `M main_terminal.py`(이전 세션 dedup `check_duplicate_batch`, +28줄). untracked: `scripts/audio_finalize.sh`, `HANDOFF.codex-explainer-20260604.md`, `docs/superpowers/plans/2026-06-04-*-plan.md`, `samples/`, `scripts/dsba_poll/`, `tmp/`, `.claude/skills/paper-output-validator/`. **이번 세션 변경 아님 → 그대로 둠.**
- **내 작업은 전부 커밋됨(main, push 안 함)**: audio-brief 8커밋 + pub_label/article/뷰어우선순위 3커밋 + teal 1커밋. 미커밋 없음.
- **백그라운드**: 없음(converter 빌드 완료). docker 컨테이너·크론은 durable.
- **미완료 todo**: 없음(구현 9 Task 전부 완료).

## 📂 관련 파일 (현재 세션)
- `docs/superpowers/specs/2026-06-06-paper-audio-brief-design.md` — 스펙(상태=구현완료).
- `docs/superpowers/plans/2026-06-06-paper-audio-brief.md` — 구현계획(피어리뷰 3라운드 포함, 단계별 TDD).
- `viewer/app/services/papers.py`,`chat.py`,`mcp_zip.py`,`routers/api.py`,`routers/pages.py` — 백엔드 brief 배선.
- `viewer/app/templates/viewer.html` — 듣기 축약/전체, `papers.html` — 목록 teal 스피커.
- `viewer/tests/{test_papers_audio_brief.py,test_default_audio_brief.mjs,test_viewer_audio_brief_template.py}` — 회귀 테스트.
- `.claude/skills/paper-audio-brief-korean/SKILL.md` — 생성 스킬.
- `~/.openclaw/workspace/skills/paperflow-claude-batch-audio-brief/scripts/` — finder+dispatch(+테스트). **openclaw는 git repo 아님 → 디스크에만 저장**.

---

# 📦 이전 세션 — 해설판/낭독판 콘텐츠 일괄 생성 (2026-06-05, 완료)

> 별개 작업. `paper-explainer`/`paper-audio-korean` 스킬로 `outputs/` 대상 해설판·낭독판 생성. 진행 중 없음(완료).

- **완료**: 낭독판 일괄 33편(누락 0), 소배치(How we contain Claude / AI in SRE / ruvnetruflo / shanraisshan / When AI builds itself 해설+낭독 각 4~5) + HBR 한국어 에세이 해설판 5편.
- **사용자 반복 지침**: ① 반드시 Skill 도구로 호출 ② 생성은 Claude Code 안에서(tmux 우회 금지) ③ 파이프라인은 paperflow MCP 우선 ④ 산출물 있으면 skip ⑤ 한 건씩, 끝나면 폴더·성공·경로 정리.
- **낭독판 확정(인라인)**: `.part`→CRITICAL grep 0건→`mv`→sidecar `_ko_audio.meta.json`(status=complete+source mtime/size/sha256). 본문 YAML/배너/메타 금지. grep 금지: `$$`/인라인`$…$`/`\(`/`\[`/표`|---`/코드펜스/`[n]`/`[^`/HTML/`](#`/URL=0, alt있는 이미지=0. 그림은 `![](상대경로)` 빈 alt만.
- **웹 해설판 디클러터링**: 히어로 장식·페이월·GitHub UI 제거; 본문 figure·인용링크·원문URL·저자약력 보존.
- **분량**: "원문 이상" 하드요구. HBR 정제 산문은 1.3~1.55x 경향. 저장 후 `grep '�'` 깨진 유니코드 점검.

---

# 📦 더 이전 워크스트림 (별개 — 미해결·주의 보존)

## 🅰️ 듣기판 그림 임베딩 재생성 — 미완 (22/32 후 중단)
- 그림 임베딩 규칙 생기기 전 만든 듣기판(소스 해설판엔 그림 있으나 듣기판 `![](경로)` 0개) 재생성. ※ 위 "낭독판 33편"과 다른 백로그.
- 남은 대상 재도출:
  ```bash
  cd /home/restful3/workspace/paperflow
  for base in outputs archives; do for f in "$base"/*/*_ko_audio.md; do [ -f "$f" ]||continue; dir=$(dirname "$f"); exp=$(ls "$dir"/*_ko_explained.md 2>/dev/null|head -1); [ -n "$exp" ]||continue; ia=$(grep -cE '!\[\]\(' "$f"); ie=$(grep -cE '!\[' "$exp"); [ "$ie" -gt 0 ]&&[ "$ia" -eq 0 ]&&echo "[$ie img] $dir"; done; done
  ```
- **⚠️ 데이터 위생(미해결)**: `outputs/Developer's guide to multi-agent patterns in ADK/` 에 직선(')·곡선(') 아포스트로피 basename 중복(explained+audio+meta). 동일본 확인 후 처리(임의 삭제 금지 — 사용자 확인).
- 임베딩 불가 예외: 외부 http URL 이미지 / 깨진·빈 경로 / 순수 장식(묘사만).

## 🅱️ 오디오 큐 UI / TTS(mp3) — 대체로 완료·배포
- **TTS 엔진 VoxCPM2**, `VOXCPM_VOICE=09_chaewon`, ~11.4GB VRAM(12GB 카드), 단일 GPU 순차.
- **CUDA 오염 복구**: `docker compose stop paperflow-tts` → `echo "[]" > outputs/.audio_queue.json` → 문제 논문 `audio/.locks`·`*_ko_audio.<sha>`·`*_ko_audio.manifest.json` rm → `start`.

## 🚫 절대 건드리지 말 것
- **`~/.openclaw/workspace/scripts/audio_watch/`** = 음성녹음(.m4a) 받아쓰기→회의록/랩노트 시스템. 논문 TTS와 무관. 정리하면 회의록 파이프라인 손상. cron `#PAUSED#`.
