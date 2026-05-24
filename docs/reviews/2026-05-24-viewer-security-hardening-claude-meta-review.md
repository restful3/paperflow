# Meta-Review of Codex Round 1

대상: `docs/reviews/2026-05-24-viewer-security-hardening-codex.md`
계획서: `docs/superpowers/plans/2026-05-24-viewer-security-hardening.md`
검토자: Claude (PaperFlow 작업 세션)

## 검증 방법

코덱스가 인용한 각 라인을 actual 파일에서 확인했다. ACCEPT 항목은 모두 `grep`/`Read`로 직접 검증된 것만 포함한다.

| 코덱스 주장 | 실제 코드 | 결론 |
|---|---|---|
| `get_paper_info`가 `_resolve_paper_dir`를 안 거침 | `papers.py:587-588` `base / name` raw join | ✅ Confirmed |
| `viewer_page`가 raw join + touch_last_read 무조건 호출 | `pages.py:43` `paper_svc.touch_last_read(name)` + `:44` `get_paper_info(name)` | ✅ Confirmed |
| `enrich_paper_metadata`도 raw join | `web_search.py:183-187` `base / paper_name` | ✅ Confirmed |
| `archive_paper`/`restore_paper`도 raw join | `papers.py:853, 865` raw `base / name`, shutil.move | ✅ Confirmed |
| 현재 `.env`의 `JWT_SECRET_KEY=paperflow-secret-change-me-in-...`이 exact-list를 통과 | `.env`의 키 길이 40, prefix `paperflow-secret-change-me-in-` | ✅ Confirmed |
| `/api/upload`가 `file.filename`을 raw로 write_bytes | `api.py:537` 확장자만 체크, `papers.py:934` `newones_dir / filename` raw | ✅ Confirmed |
| `docker compose up -d` env_file 반영 보장 안 됨 | Compose 동작 사실 | ✅ Confirmed (공통 지식) |
| `ls outputs | head -1`가 json 파일 픽업 가능 | `outputs/`에 `reading_progress.json` 등 존재 | ✅ Confirmed |

## ACCEPT (계획에 반영)

1. **Task 3 확장 — 호출자 5곳 모두 safe resolver 적용**
   - `get_paper_info`, `enrich_paper_metadata`, `archive_paper`, `restore_paper`, `viewer_page`의 `touch_last_read` 호출 순서까지 포함.
   - 공통 path-safety helper `_safe_paper_dir(name)`를 `papers.py`에 두고 다른 모듈에서 import해 사용한다. `_resolve_paper_dir`은 내부 thin wrapper로 유지.

2. **Task 1 강화 — JWT 검증을 substring + length 기반으로 확장**
   - placeholder substring 차단: `change-me`, `changeme`, `replace-with`, `placeholder`, `your-secret`, `paperflow-secret` (정규화: lower + 공백 제거 후 검사).
   - 길이 하한 32자.
   - 실제 `.env` 회전을 검증 절차에 명시 (Step 5 추가).

3. **Task 5 신설 — `/api/upload` 파일명 traversal 차단**
   - `_safe_filename(filename)` 헬퍼 도입: 단일 component 강제, NUL/`/`/`\\`/절대경로/`.`/`..` 거부.
   - `save_upload`와 `api.py:547`의 `pdf_path` 산출에 모두 적용.
   - 검증: `-F 'file=@/tmp/sample.pdf;filename=../../tmp/x.pdf'` 거부.

4. **Task 2 검증 보강**
   - `docker compose up -d --force-recreate paperflow-viewer`로 변경.
   - `docker compose exec paperflow-viewer env | grep COOKIE_SECURE`로 env 반영 확인.
   - `SameSite=Lax` 선택 이유 1줄 명시 (cross-site embedding 미지원 전제).

5. **Task 3 정상 케이스 검증 수정**
   - `EXISTING=$(find outputs -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | head -1)`로 교체.

6. **검증 명령 보강**
   - `info`/`viewer`/`enrich`/`pdf`/`chat/history` 5개 엔드포인트에서 traversal 시도 → 404 기대.
   - `JWT_SECRET_KEY="paperflow-secret-change-me-in-production"`로 placeholder 변형이 startup에서 거부되는지 확인.

## DEFER (이번 plan scope-out, follow-up으로 명시)

1. **약한 `LOGIN_PASSWORD` startup guard**
   - 코덱스도 "이번 계획 목표를 유지한다면 별도 follow-up"으로 분리 가능하다고 언급.
   - 단일 admin + 로컬 운영 전제이므로 동일 plan에 묶지 않는다. scope-out 섹션에 follow-up High로 명시.

2. **Windows 운영 환경의 drive/colon/예약명**
   - 본 앱은 Linux Docker 전용 운영. POSIX 한정.

3. **pytest 도입 / 단위 테스트**
   - viewer/에 테스트 인프라 전무. 별도 plan에서 다룬다. 본 plan은 manual curl 검증 유지.

## REJECT

(없음) — 코덱스 지적 전부가 actual code로 검증됨.

## 변경 사항 요약

원 계획의 4개 Task → 5개 Task로 확장. 변경 라인 수 증가 추정:
- config.py: 15 → 25줄 (substring 차단 + 길이 하한)
- papers.py: 20 → 50줄 (호출자 5곳 일관 적용 + `_safe_filename`)
- web_search.py: 0 → 3줄 (`_safe_paper_dir` import + 사용)
- pages.py: 0 → 4줄 (`touch_last_read` 조건부 호출)
- api.py: 0 → 4줄 (`_safe_filename` 적용)
- .env.example, CLAUDE.md: 변경 동일

여전히 surgical: 무관한 리팩터/포맷 변경 없음, 신규 helper 2개만 도입.
