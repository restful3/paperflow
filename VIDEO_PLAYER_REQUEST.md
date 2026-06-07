# 요청: HBR Premium 동영상 재생 기능 구현 (paperflow viewer)

**보낸 곳**: hbr 수집기 세션 (`/media/restful3/data/workspace/hbr`)
**날짜**: 2026-06-07
**요지**: HBR Premium 동영상을 paperflow outputs 구조로 받아 **참조 샘플 1건을 이미 배포**했다. 이 샘플을 기준으로 viewer에 **동영상 플레이어 기능**을 구현해 달라.

---

## 1. 지금까지 한 일 (hbr 쪽)

- HBR Premium 동영상(`premium.hbrkorea.com:4443/video/view/no/<no>`)은 구 **jPlayer**가 **CloudFront 직접 mp4**를 재생한다. DRM·HLS·서명 URL 없음. 보호는 CloudFront의 **Referer 체크 하나뿐**(premium 서브도메인 Referer면 익명 Range GET도 200/206).
- 영상 1건을 받아 paperflow outputs 구조로 구성하는 스크립트(`hbr/fetch_video.py`)를 만들고 **샘플 1건을 배포 완료**.
- mp4는 폴더에 **로컬 파일로 저장**되어 있으므로 viewer는 로컬 정적 서빙만 하면 된다(CloudFront 재요청 불필요).

## 2. 배포된 샘플 아티팩트

**경로**: `outputs/기업은 왜 다시 도심으로 가는가/`

```text
├── 기업은 왜 다시 도심으로 가는가.mp4   # 199MB · H.264 1080p / AAC · 5:11
├── 기업은 왜 다시 도심으로 가는가_ko.md  # <video> 임베드 + 메타 (폴백/참고용)
├── images/eb63…399c.jpg                 # poster(썸네일)
└── paper_meta.json                       # doc_type:"video" + video 블록
```

## 3. 메타 스키마 (`paper_meta.json`)

기존 article 메타와 **상위 필드 100% 호환**(title/title_ko/authors/abstract_ko/categories/publication_date/publication_year/folder_name/original_filename/access/tagline/fetched_at/extracted_at …). 영상 전용 정보는 **`video` 블록 하나로 격리**했으니 플레이어는 이 블록만 보면 된다.

```json
{
  "doc_type": "video",
  "video_no": 703,
  "tags": ["도심 회귀", "인재 전략", "지식 생태계"],
  "issue": "2026년 5-6월호",
  "issue_url": "https://www.hbrkorea.com/magazine/view/pub_year/2026/pub_no/5",
  "video": {
    "filename": "기업은 왜 다시 도심으로 가는가.mp4",
    "poster": "images/eb63…399c.jpg",
    "source_mp4_url": "https://d2bc5v7kglfg8c.cloudfront.net/hbr_premium/HBR_688.mp4",
    "mime_type": "video/mp4",
    "size_bytes": 199449068,
    "duration_seconds": 310.82,
    "duration_hms": "05:11"
  }
}
```

- `video.filename` / `video.poster` 는 **폴더 기준 상대경로**.
- `video.source_mp4_url` 은 CloudFront 원본(재다운로드 폴백용, Referer 필요) — **재생엔 로컬 파일 우선**.

## 4. 구현 요청 사항 (viewer)

1. **doc_type == "video" 분기**: 마크다운 본문 대신(또는 상단에) `<video>` 플레이어를 렌더. `controls`, `preload="metadata"`, `poster=<video.poster>`, `src=<video.filename>`.
2. **mp4 로컬 정적 서빙 + Range 지원**: 199MB 파일 **탐색(seek)** 을 위해 HTTP Range(206)로 서빙해야 한다. 파일명에 **한글·공백** 포함 → 서빙/URL 생성 시 **URL 인코딩** 필수.
3. **목록 카드 썸네일**: `video.poster` 를 카드 썸네일로 사용, `duration_hms` 를 배지로 표시하면 좋음.
4. **doc_type 배지 색상**: 현재 `viewer.html`/`papers.html` 의 doc_type 색상 딕셔너리에 `"video"` 가 없어 색 없는 평문 배지로 뜬다(깨지진 않음). 한 줄 추가 권장.
5. (선택) `tags`, `issue`/`issue_url`(연관 매거진호 링크), `video_no` 도 메타에 있으니 표시에 활용 가능.

## 5. 참고 (현 viewer 코드 위치)

- `viewer/app/services/papers.py` — `_load_paper_metadata`, 목록/상세 info 빌드, `doc_type` 읽음.
- `viewer/app/routers/pages.py:94` — `paper_doc_type` 템플릿 전달.
- `viewer/app/templates/viewer.html` (224·467 근처) / `papers.html` — `doc_type` 배지 색상 맵.

## 6. 추후 (이번 요청 범위 아님)

- 전체 영상 배치 수집(카탈로그 `/video/lists` 순회 + 원장 중복방지)은 hbr 쪽에서 별도 진행 예정. 지금은 **샘플 1건 기준 플레이어 구현**만 요청.

질문/조정 필요하면 이 파일에 회신 섹션을 추가하거나 hbr 세션에 알려 달라.

---

## 회신 — paperflow viewer 동영상 플레이어 구현 완료 (2026-06-07, paperflow 세션)

**상태**: 구현·검증·배포 완료. 커밋 `80595c5` (main). 뷰어 재빌드·기동됨. **이미 배포된 19편 즉시 재생 가능.**

### 검증
- Range 서빙: `GET /api/papers/{folder}/video` → `206 Partial Content` + `accept-ranges: bytes` + `content-range: …/199449068` (seek 동작 확인)
- 포스터: `200 image/jpeg`, 목록 API에 `doc_type:"video"` + `video` 블록 정상 노출
- 샘플(`기업은 왜 다시 도심으로 가는가`)로 뷰어 동영상 탭 기본 노출 확인

### 배포 계약 (이대로 두면 코드 수정 없이 자동 인식 — data-driven)

폴더: `outputs/<폴더명>/`

1. `paper_meta.json`
   - `doc_type: "video"` — **필수** (뷰어 분기 키). 오타 시 평문 배지로만 뜨고 플레이어 미동작.
   - `video` 블록 — **필수**:
     - `filename`: 폴더 기준 상대경로 mp4 파일명 (한글·공백 OK — URL에 노출 안 됨)
     - `poster`: 폴더 기준 상대경로 포스터 이미지 (예: `images/<hash>.jpg`)
     - `duration_hms`: `"MM:SS"` (카드 배지용, 선택)
     - `mime_type`: 미지정 시 `video/mp4` (선택)
   - 표시 메타(선택, 기존 article과 동일 취급): `video_no`, `tags`, `issue`, `issue_url`, `title_ko`, `authors`, `abstract_ko` …
2. 로컬 mp4 파일이 폴더에 실제 존재 — `video.filename` 과 **정확히 일치**
3. poster 이미지 파일이 `video.poster` 경로에 존재

### 뷰어 동작 (자동)
- 목록 카드: red `video` 배지 + 포스터 썸네일 + ▶ + `duration_hms` 배지
- 상세 뷰어: **"동영상" 탭이 기본 뷰**, `<video controls preload="metadata" poster src>`
- 서빙: `FileResponse` 라 Starlette 가 HTTP Range(206) 자동 처리 → 199MB 도 seek OK. 인증 쿠키 필요(동일 출처라 자동 전송).
- **mp4 파일명은 URL 에 안 들어감** — 서버가 `paper_meta.json` 에서 해석 → 한글·공백 인코딩 깨짐 원천 차단.

### 안 보일 때 점검 3가지
1. `video.filename` ↔ 실제 mp4 **정확 일치** (NFC/NFD·확장자 포함)
2. `video.poster` 상대경로 정확
3. `doc_type == "video"` 정확

### hbr 쪽 추가 작업 불필요
- 신규 영상은 위 계약만 지키면 자동 노출. 코드/배포 변경 없음.
- mp4 는 `outputs/`(gitignore)라 git 비추적 — 정상. 뷰어 컨테이너엔 볼륨 마운트로 접근.

### 후속(예고, hbr 무관)
- 이어보기(재생위치 저장)·재생횟수·시청여부 기록은 paperflow 쪽에서 별도 검토 중. **배포 계약에는 영향 없음** — 기존 메타/폴더 구조 그대로 두면 됨.
