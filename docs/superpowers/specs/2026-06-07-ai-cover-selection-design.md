# AI 비전 커버 선별 스테이지 — 설계

**날짜**: 2026-06-07
**대상**: PaperFlow 배치 파이프라인 (`main_terminal.py`)
**상태**: 설계 승인 대기 → 구현 계획 작성 예정

## 배경 / 문제

PaperFlow 카드 목록은 동영상(`doc_type=video`)과 HBR·economist 기사(`doc_type=article`, 수집기가 명시한 `cover` 필드)에서 커버 이미지를 표시한다. 이 시각적 카드가 좋은 반응을 얻어, **다른 컨텐츠 타입에도 대표 커버 이미지를 쓰고 싶다.**

현재 `cover`가 없는 타입(2026-06-07 기준 라이브러리):

| doc_type | 개수 | 비고 |
|----------|------|------|
| paper | 94 | figure 많음, 첫 그림이 수식·표일 수 있음 |
| blog | 83 | 본문 이미지 0\~21장 |
| news | 21 | 대부분 이미지 0장 |
| essay | 17 | 일부 이미지 보유 |
| report | 10 | 이미지 10\~25장 풍부 |
| video | 18 | 별도 `video.poster` 사용 — 대상 아님 |

뷰어 측은 이미 범용 커버를 렌더한다(커밋 `8c45199`): `papers.py`의 `_paper_info`가 `paper_meta.json`의 최상위 `cover`(폴더 상대경로)를 노출하고, `papers.html`의 `cardCoverSrc(paper)`가 비디오는 `video.poster`, 그 외는 `cover`를 사용한다. **즉 데이터(`cover` 필드)만 채우면 뷰어 변경 없이 표시된다.**

## 결정 사항 (브레인스토밍 합의)

1. **선택 전략**: AI 대표 이미지 선별 (휴리스틱·수동·첫이미지 아님)
2. **선별 메커니즘**: 비전 모델이 이미지를 직접 보고 판단 (텍스트 단서 추론 아님). 휴리스틱으로 후보를 추린 뒤 비전이 최종 1장 선택, 표지감 없으면 NONE
3. **적용 범위**: 모든 비-비디오 타입 (이미지가 있는 폴더 전부 시도)
4. **실행 시점**: PaperFlow 파이프라인(`main_terminal.py`)에 스테이지로 통합. **기존 ~225개 폴더 백필은 나중** (이번 범위 아님)
5. **통합 방식**: 독립 스테이지 (방식 A) — 메타 추출 스테이지에 흡수(방식 B)하지 않음. 단일 책임 + 토글 독립 + 백필 시 함수 재사용

## 아키텍처

### 신규 함수: `select_cover_image(output_dir, metadata, config)`

`main_terminal.py`에 추가. `process_single_pdf`에서 **메타 추출·웹검색·스마트 리네임 직후, 번역 전**에 호출한다.

호출 시점 근거:
- doc_type이 확정됨 (메타 추출 stage 이후)
- 이미지가 디스크에 존재함 (convert stage 1에서 추출 완료)
- 폴더 경로가 최종 확정됨 (스마트 리네임 이후 — `output_dir`은 리네임된 `new_dir` 사용)

반환/부작용: `metadata["cover"]`를 설정하고 `paper_meta.json`을 저장. 적합한 커버가 없으면 `cover`를 설정하지 않고 종료(필드 부재 = 텍스트 카드 폴백).

### 조기 종료 가드

1. `metadata.get("doc_type") == "video"` → 스킵 (video.poster 사용)
2. `metadata.get("cover")` 이미 존재 → 스킵 (HBR·economist 수집기가 채운 값 **절대 덮어쓰지 않음**)
3. 후보 이미지 0장 → 스킵

### config 토글

`processing_pipeline.select_cover` (기본 `true`). `_count_active_stages` / `total_stages` 계산 및 스테이지 진행 표시에 포함. 끄면 스테이지 전체 건너뜀.

## 컴포넌트

### 1. 후보 프리필터 (AI 없음)

순수 함수 — 폴더를 받아 비전에 보낼 후보 경로 리스트를 반환. 비용 절감을 위해 비전 호출 전에 명백히 부적합한 이미지를 거른다.

- **수집**: 폴더 루트 + `images/`·`figures/`·`assets/` 서브디렉토리. 확장자 `jpg`/`jpeg`/`png`/`webp`
- **크기 필터**: PIL로 dimension 측정 → 긴 변 < `min_dimension`(기본 200px)인 것 제거 (아이콘·로고·수식조각 배제)
- **랭킹**: 면적 내림차순, 동률 시 문서 등장 순서(파일명 정렬)로 타이브레이크
- **컷오프**: 상위 `max_candidates`장(기본 6) 반환
- 0장이면 빈 리스트 → 호출자가 스킵

### 2. 비전 선별

- **클라이언트**: 기존 OpenAI 호환 클라이언트 재사용 (`OPENAI_BASE_URL`/`OPENAI_API_KEY`)
- **모델**: `COVER_MODEL` env → 없으면 `TRANSLATION_MODEL`(기본 `gemini-claude-sonnet-4-5`, 비전 지원) 폴백
- **메시지**: 후보 이미지를 다운스케일(긴 변 최대 `downscale_px`=768px)하여 base64 data URL로 변환, 1..N 번호를 붙여 멀티모달 user 메시지로 전송
- **프롬프트 요지**: "다음은 어떤 {doc_type}에서 추출한 후보 이미지들이다. 컨텐츠 카드의 표지(cover)로 가장 적합하고 대표성 있는 **1장**을 골라라. 전부 수식·표·플롯·로고·인물 증명샷 등 표지로 부적합하면 NONE." → 엄격 JSON `{"choice": <1..N 정수 | null>}`
- **파싱**: choice를 인덱스로 후보 리스트에서 폴더 상대경로 매핑. 범위 밖/파싱 실패/null → 커버 없음

### 3. 출력 / 데이터

- `metadata["cover"] = <폴더 상대경로>` (예: `images/fig3.jpg` 또는 `cover.jpeg`)
- `paper_meta.json`에 저장 (기존 저장 헬퍼/패턴 재사용)
- **폴더 상대경로**라 스마트 리네임·아카이브 이동에도 생존 (기존 cover 규약과 동일). 뷰어가 `/api/papers/{name}/assets/{rel}`로 서빙

## 데이터 흐름

```text
convert_to_markdown (stage1, 이미지 추출)
  → normalize_headings
  → extract_metadata (doc_type 확정, paper_meta.json 저장)
  → enrich_with_web_search
  → check_duplicate + smart rename (output_dir = new_dir)
  → [신규] select_cover_image(output_dir, metadata, config)
        ├─ 가드: video/기존cover/후보0 → 스킵
        ├─ 프리필터 → 후보 N장
        ├─ 비전 선별 → 인덱스 or NONE
        └─ cover 기록 → paper_meta.json 저장
  → translate_to_korean
```

## 에러 처리

스테이지는 **optional** (웹검색 스테이지와 동일 등급). 어떤 실패도 파이프라인을 중단시키지 않는다.

| 상황 | 동작 |
|------|------|
| 이미지 없음 / 전부 min_dimension 미만 | 커버 없음, 텍스트 카드 폴백 |
| 비전 NONE / 범위 밖 인덱스 / JSON 파싱 실패 | 커버 없음 |
| 모델 비전 미지원 / API 오류 / 타임아웃 | 커버 없음, 경고 로그, 파이프라인 계속 |
| 후보 0장 | 가드에서 조기 종료 |

타임아웃·재시도는 `cover_selection.timeout`·`max_retries` 설정.

## 설정

### config.json

```jsonc
"processing_pipeline": {
  // ...기존...
  "select_cover": true
},
"cover_selection": {
  "max_candidates": 6,
  "min_dimension": 200,
  "downscale_px": 768,
  "timeout_seconds": 60,
  "max_retries": 2
}
```

### .env

```text
COVER_MODEL=            # 선택. 비우면 TRANSLATION_MODEL 사용
```

## 테스트 (TDD — 구현 전 작성)

**프리필터 (순수 함수, mock 불필요)**
- 긴 변 < min_dimension 이미지가 후보에서 제외된다
- 면적 큰 순으로 랭킹, 동률은 파일명 순
- 루트 + images/figures/assets 서브디렉토리에서 수집
- jpg/jpeg/png/webp만 수집 (다른 확장자 무시)
- 후보가 max_candidates개로 잘린다
- 이미지 0장 → 빈 리스트

**가드**
- doc_type=="video" → 비전 호출 없이 스킵, cover 미설정
- cover 이미 존재 → 비전 호출 없이 스킵, 기존 값 유지
- 후보 0장 → 비전 호출 없이 스킵

**비전 선별 (클라이언트 mock)**
- choice=인덱스 → cover가 올바른 폴더 상대경로로 설정
- choice=null(NONE) → cover 미설정
- 범위 밖 인덱스 / 잘못된 JSON → cover 미설정
- 클라이언트 예외 발생 → cover 미설정, 예외 전파 안 됨

**영속성**
- cover 선택 시 paper_meta.json에 기록됨
- 스킵 시 paper_meta.json의 cover가 그대로 (None/부재)

## 범위 밖 (이번 작업 아님)

- 기존 ~225개 폴더 **백필** (나중에 같은 `select_cover_image` 함수를 폴더 순회 스크립트로 재사용)
- 뷰어 UI 변경 (이미 범용 커버 렌더 지원)
- 동영상 poster 생성 로직 (별도 경로)
- 수집기(HBR·economist) 측 변경 (이미 cover를 직접 설정 — 가드가 존중)
