===SPEC_APPROVED===

# PaperFlow 라이브 한국어 TTS MVP 스펙 최종 검토 — Codex

검토 대상:

- `docs/superpowers/specs/2026-05-31-paperflow-live-tts-design.md`
- `docs/reviews/2026-05-31-live-tts-design-codex-round2.md`
- `docs/reviews/2026-05-31-live-tts-design-claude-meta-review.md`

판정: **승인. Blocking 이슈 없음.**

## 합의 반영 확인

- **D1 단일 manifest**: 반영됨. `manifest.json`이 cache key, timeline, DOM mapping, 완료 마커를 모두 가진다.
- **D2 MVP 청크 폐기**: 반영됨. 청크 파일은 `.jobs/{job_id}/chunks/`의 임시 산출물이며 성공 publish 후 삭제한다.
- **D3 서버 렌더**: 반영됨. 오디오 모드는 `marked.parse` 기반 클라이언트 wrapping이 아니라 manifest segmentation과 같은 입력으로 문장 span HTML을 만든다.
- **D4 헤딩 재작성 제외**: 반영됨. 헤딩은 별도 청크 + 긴 뒷쉼으로 처리하고 TTS 단계에서 텍스트를 재작성하지 않는다.
- **Round 2 보완 5가지**: Range smoke test, 청크 폐기와 진행률 양립, 서버 HTML/manifest 일치, 1문장=1합성단위, manifest 완료 마커가 모두 반영됐다.

## 구현 관점

엔드포인트, 데이터 모델, 원자적 publish, 동시성, 검증, UI 동작이 MVP 구현에 충분한 수준으로 구체화되어 있다. 특히 `audio/` 하위 격리, `safe_paper_dir*` 재사용, `status != complete` 차단, source/model/chunker 기반 cache miss, 읽기/듣기 진행률 분리는 구현자가 임의 해석할 여지를 잘 줄인다.

MVP 범위도 적절하다. progressive playback, per-chunk 공개 캐시, 부분 재생성, word karaoke, voice preset, 브라우저 알림을 제외한 결정은 과설계를 막는 방향으로 맞다.

## Non-blocking Nit

1. **라우트 표기는 `{name:path}`로 맞추는 편이 좋다.**
   - 기존 API가 `@router.get("/papers/{name:path}/...")` 패턴을 쓰고 있고 논문 이름에 slash-like encoded path가 들어갈 수 있으므로, §5의 `/api/papers/{name}/audio/...` 표기는 구현 스펙에서 `{name:path}`로 적는 것이 더 정확하다.

2. **blockquote 처리 규칙을 한 줄 추가하면 좋다.**
   - §2는 `_ko_audio.md`에 "배너 blockquote 1줄"이 있다고 확인하면서 §4는 서버 렌더러를 heading/paragraph만 처리한다고 한다. 현재 데이터상 blockquote가 실제로 있으므로, `>` banner는 paragraph 또는 callout paragraph로 렌더하고 chunk/span count에 포함한다고 명시하면 구현자가 헷갈리지 않는다.

3. **`/audio/html` 설명에서 "(또는 manifest로 클라 렌더)"는 문구를 좁히는 것이 좋다.**
   - 합의의 핵심은 클라이언트가 Markdown을 다시 파싱하거나 문장 wrapping을 재구현하지 않는 것이다. manifest chunks를 클라이언트가 단순 span으로 렌더하는 것은 가능하지만, 스펙 문구만 보면 D3 서버 렌더 합의를 약화시킬 수 있다. "서버 렌더 HTML을 기본으로 하고, 클라이언트 렌더는 manifest chunks를 그대로 span으로 출력하는 fallback에 한정" 정도가 더 안전하다.

4. **`start_sec/end_sec`의 silence 포함 의미를 더 명시하면 좋다.**
   - 현재 "무음 패딩 포함"이라고 되어 있어 충분히 읽히지만, 하이라이트 UX 관점에서 `end_sec`가 "다음 청크 시작 전까지의 표시 구간"인지 "실제 발화 종료 시점"인지 명시하면 좋다. MVP에서는 전자가 단순하다.

5. **`perth 워터마커`는 오탈자/정책 항목으로 분리하는 것이 좋다.**
   - §9.6의 "perth 워터마커"는 `resemble-perth`로 표기하고, MVP blocking dependency인지 optional watermark policy인지 명확히 하면 된다. 현재는 non-blocking 운영 주의점으로 보면 충분하다.

6. **Range는 "Starlette가 자동 지원" 전제와 별개로 실제 smoke를 유지해야 한다.**
   - 스펙이 이미 반영했으므로 추가 변경은 필요 없다. 구현 체크리스트에서 `curl -I`, Range request, Safari seek를 묶어 검증하면 된다.

## 최종 의견

이 스펙은 R1~R2 합의 내용을 정확히 반영했고, 구현자가 바로 plan/task로 쪼갤 수 있을 만큼 충분히 구체적이다. 위 nit들은 문구 정리와 작은 edge case 명시 수준이며, 구현 착수를 막을 사안은 아니다.

