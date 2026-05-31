===PLANS_APPROVED===

# PaperFlow 라이브 한국어 TTS 구현 플랜 리뷰 — Codex Round 4

판정: **승인. Blocking 이슈 없음.**

Round 3의 단일 blocking이었던 Plan 1 Task 1 `_split_sentences`는 sentinel 방식으로 반영됐음을 확인했습니다.

```python
_SENT_BREAK = re.compile(r'([.!?…][”’"\')\]】」』]?)\s+')

def _split_sentences(para):
    marked = _SENT_BREAK.sub(r'\1\x00', para.strip())
    return [p.strip() for p in marked.split('\x00') if p.strip()]
```

이 방식은 종결부호와 닫는 따옴표를 캡처 그룹으로 보존한 뒤 sentinel만 split 기준으로 쓰므로, `test_closing_quote_after_period_splits`를 통과할 수 있습니다.

## 확인한 반영 사항

- R2/R3 blocking 해소 확인:
  - TDZ를 만들던 `const name = name` 제거
  - 닫는 따옴표 보존 sentinel sentence split 반영
  - Plan 2 테스트 경로 `viewer/tests/test_audio_api.py`로 통일
  - `/audio/file?file=<manifest.audio.file>`로 manifest/audio version 정합성 고정
- R3 nit 반영 확인:
  - File Structure의 test 경로 정리
  - Task 10 산출물 glob을 `*_ko_audio.*.mp3`로 수정
  - Self-Review의 품질 게이트 문구를 `_chunk_ok` + 1회 재시도 실제 구현으로 갱신
  - `_under_audio_dir(candidate, base)`를 base-relative 방식으로 강화

## 잔여 Nit

1. **Plan 2 Task 4의 컨트롤 UI는 실제 구현 때 기존 스타일로 다듬으세요.**
   - 플랜 예시는 emoji 버튼이라 기능 검증용으로는 충분합니다. 실제 viewer에는 기존 버튼/아이콘/다크모드 스타일과 맞추는 편이 좋습니다.

2. **Plan 1 Task 9의 `_under_audio_dir`는 구현 시 `candidate.resolve(strict=False)` 계열을 고려하세요.**
   - 파일이 아직 없을 때와 있을 때의 `Path.resolve()` 동작 차이를 피하려면, target 존재 확인 전 경로 검증이 실패하지 않도록 테스트를 하나 추가하면 좋습니다.

3. **Task 10 Range smoke는 `?file=` 경로도 한 번 확인하면 좋습니다.**
   - 기본 `/audio/file`뿐 아니라 manifest에서 `audio.file`을 뽑아 `/audio/file?file=...`로 Range 요청을 확인하면 B4 race 방지 경로까지 검증됩니다.

4. **Sidecar cache hit UX는 후속 개선 여지로 남습니다.**
   - 현재도 기능상 문제는 없지만, `POST /jobs`가 최신 캐시일 때 `cached: true`를 반환하면 프론트 진행 UX가 더 명확해집니다.

## 최종 의견

두 플랜은 승인된 스펙의 MVP 범위를 충분히 커버하고, 이전 리뷰에서 지적한 atomic publish, GPU lock, manifest/audio 정합성, 서버 렌더, Alpine 로드 순서, click handler 회귀 위험을 처리했습니다. 이제 구현 태스크로 넘겨도 됩니다.

