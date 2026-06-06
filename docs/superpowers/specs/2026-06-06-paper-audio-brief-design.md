# 축약 낭독판 (`_ko_audio_brief`) — 설계 스펙

**날짜**: 2026-06-06
**상태**: 설계 승인됨 (구현 계획 대기)
**관련**: [[paper-audio-korean]] 스킬, 첫화면 기본 표시 우선순위(`viewer.html`), 야간 배치 크론

## 1. 배경 / 동기

논문(paper)의 해설판·낭독판이 너무 길어 듣기가 괴롭다. 실측(outputs 199편, median, 한국어 TTS ~350자/분 가정):

| doc_type | 풀 낭독판(`_ko_audio.md`) median | 듣기 시간 |
|----------|---------------------------------|-----------|
| **paper** | ~24,500자 | **~69분** |
| article | ~13,200자 | ~37분 |
| blog | ~10,000자 | ~28분 |
| news | ~8,300자 | ~23분 |

논문 낭독판이 ~69분으로 압도적으로 길다. 다른 글들의 일반 분량(~20\~37분)에 맞춰, **원문의 핵심을 놓치지 않으면서 짧게 정리한 축약 낭독판**을 추가한다.

## 2. 목표 / 비목표

**목표**
- 긴 낭독판을 가진 글에 대해 **~20분(~7,000자)** 분량의 축약 낭독판 `_ko_audio_brief.md`를 **추가**(풀 낭독판은 유지).
- 뷰어 "듣기"에서 축약본을 **기본**으로 듣고, "전체"로 풀 낭독판 전환.
- 야간 배치 크론으로 자동 생성(길이 기준 게이팅).

**비목표 (이번 스펙 범위 밖)**
- 축약 낭독판의 **mp3 합성**(TTS 음원 생성) — 후속(phase 2). 이번엔 마크다운 생성 + 뷰어 표시까지.
- 읽기 전용 "축약 해설판" 텍스트(`_ko_brief.md`) — 만들지 않음. 축약 낭독 텍스트가 곧 축약본.
- 영어 축약본 — KO 전용.

## 3. 산출물 · 파일 규약

기존 `_ko_audio` 패턴을 그대로 따른다.

- **본문**: `<basename>_ko_audio_brief.md` — 폴더 직하위(1급 KO 포맷). 순수 낭독 텍스트(YAML/메타 없음).
- **sidecar**: `<basename>_ko_audio_brief.meta.json` — `status=complete` + **소스(`_ko_explained.md`)의 freshness**(mtime/size/sha256). 소스 해설판이 바뀌면 stale로 감지해 재생성 대상이 된다.
- **소스**: `_ko_explained.md` (해설판). 목표 분량 **~7,000자**(허용 6,000\~8,000), ~20분.

## 4. 생성기 스킬 — `paper-audio-brief-korean` (신규, 형제 스킬)

`paper-audio-korean`의 audio-description 원칙·위생규칙을 계승하되, **공격적 요약**을 추가한다.

**유지(계승)**
- 수식·표·그림·코드를 placeholder 없이 자연어로 서술.
- 듣기 무가치 요소(목차/페이지마커/저자소속/URL/참고문헌/푸터) 제거.
- 위생: CRITICAL grep 0건 통과, `.part` → `_ko_audio_brief.md` atomic rename, sidecar 기록(status + 소스 freshness), 본문에 메타데이터 금지.

**추가(요약 정책)** — 해설판에서 다음 우선순위로 핵심만 남긴다:
1. 문제의식 / 왜 중요한가
2. 핵심 기여(차별점)
3. 방법의 골자(직관 수준, 세부 유도·증명 생략)
4. 핵심 결과(주요 수치 1\~2개, 보조 실험·ablation·표 다수는 생략)
5. 한계 / 시사점

생략: 세부 실험 셋업, 증명/유도, 곁가지 논의, 반복 설명, 다수의 보조 그림/표.

분량 목표를 프롬프트에 명시(~7,000자), 초과 시 더 압축. 한 문서씩 처리.

## 5. 백엔드 (`viewer/app/services/papers.py`)

기존 `_ko_audio` 처리에 평행한 항목 추가.

- `_paper_info()`: `files["md_ko_audio_brief"]` 플래그. **감지 순서**: `_ko_audio_brief.md`를 `.md` catch-all보다 먼저 체크(안 그러면 md_en으로 오분류). `_ko_audio.md` 체크와 충돌 없음(`_ko_audio_brief.md`는 `_ko_audio.md`로 끝나지 않음).
- `get_md_ko_audio_brief_path(name)` 경로 리졸버.
- `/api/papers/{name}/md-ko-audio-brief` (api.py) — 기존 `/md-ko-audio`와 동일 패턴.
- **제외 가드**: `get_md_en_path()`/`save_markdown(...,"en")`/`get_md_ko_path()`/`chat.load_paper_chunks()`(RAG)에서 `_ko_audio_brief.md`도 `_ko_audio.md`처럼 제외.
- `mcp_zip` 포함 여부는 기존 audio와 동일 게이팅을 따른다.

## 6. 뷰어 (`viewer/app/templates/viewer.html`) — 듣기 축약 우선

- 신규 상태: `hasMdKoAudioBrief`, `mdKoAudioBriefContent`, 그리고 듣기 내 풀/축약 전환용 `audioFull`(기본 false = 축약).
- **듣기 토글 동작**: `audioMode=true`일 때 — 축약본이 있으면(`hasMdKoAudioBrief`) **축약본을 표시**(`audioFull=false`), 없으면 풀 낭독판. 듣기 헤더에 작은 **"전체" 스위치**로 `audioFull` 토글(축약 ↔ 풀). `audioFull`은 논문별 기억(localStorage `pf-audiofull-{name}`) — 선택 사항.
- `activeMdContent` getter 확장: `audioMode`이면 `(!audioFull && hasMdKoAudioBrief) ? brief : full`.
- `loadMdForCurrentLang()`: audioMode + 축약이면 `md-ko-audio-brief` 로드(폴백용 풀/`_ko.md`도 기존처럼).
- **첫화면 기본 우선순위 확장**: 자동 기본값을 `audio_brief > audio > explained > original` 로. 즉 축약본이 있으면 듣기-축약이 첫 화면. (기존 [[viewer-default-first-view-priority]] 로직에 brief 우선만 추가)
- 라벨(잠정): 듣기 토글 = "듣기", 전환 스위치 = "전체"/"요약". 추후 조정 가능.

## 7. 자동 생성 (배치 · 크론) + 게이팅

**의존 순서**: 해설판 → 풀 낭독판 → (길면) 축약 낭독판. 축약은 풀 낭독판 길이를 게이트로 쓰므로 풀 낭독판이 먼저 있어야 한다.

- **게이트**: `_ko_audio.md`가 존재하고 그 길이 **> 10,000자(~30분)** 이며 `_ko_audio_brief.md`가 없을 때만 대상. (→ 논문·긴 report·긴 article 자동 커버, 짧은 글 스킵)
- **finder**: `scripts/dsba_poll/...` 가 아니라 배치 스킬 쪽 — `find_missing_audio_brief.py` (기존 `find_missing_audio.py` 평행). 최신순, `--limit` 캡(기본 10).
- **dispatch**: `dispatch_batch_audio_brief.sh` (기존 audio dispatch 평행) — 전용 `batch` tmux 윈도우, busy-guard 동일.
- **크론(Tori/openclaw)**: `🌙 Paperflow tmux batch audio-brief nightly`, **매일 06:00 KST 1회**(그날 밤 해설·낭독 배치가 끝난 뒤). 게이팅 덕에 대부분 no-op. (필요 시 2시간 간격으로 확장 가능 — 단 explainer/audio와 batch 윈도우 경합은 busy-guard가 처리.)

## 8. mp3 합성 (phase 2, 범위 밖)

축약 `.md`도 기존 TTS 큐 경로(`tts_service`)에 태우면 mp3 생성 가능. 이번 스펙은 제외하되, 파일 규약을 `_ko_audio*`로 맞춰 후속에서 audio 서비스가 brief를 인식하도록 확장 여지를 남긴다.

## 9. 테스트 전략

- **백엔드(pytest)**: 감지 순서(`_ko_audio_brief.md` → `md_ko_audio_brief` 플래그, md_en/md_ko/md_ko_audio 로 오분류 안 됨), 경로 리졸버, en/ko/RAG 제외 가드. (`test_papers_audio.py` 평행으로 `test_papers_audio_brief.py`)
- **API**: `/api/papers/{name}/md-ko-audio-brief` 서빙 테스트.
- **finder**: `find_missing_audio_brief.py` 게이팅(풀 audio >임계, brief 없음) 단위 테스트.
- **뷰어 JS**: 첫화면 기본 우선순위 확장(`audio_brief > audio > explained > original`) 진리표를 node 미러로 검증 + 배포 후 브라우저 스모크.
- **스킬**: LLM 산출물이라 자동 테스트 없음 — 스킬 자체의 CRITICAL grep 위생 + 수동 검토.

## 10. 미해결 / 향후

- 듣기 전환 라벨("전체"/"요약") 최종 문구.
- 크론 주기를 2시간 간격으로 올릴지(explainer/audio처럼).
- phase 2: 축약 낭독판 mp3 합성 연동.
