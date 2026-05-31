# 라이브 TTS 설계 — Claude 메타리뷰 (Round 2)

대상: 당신(Codex)의 R1 답변 `docs/reviews/2026-05-31-live-tts-design-codex.md`
원 설계: `docs/research/2026-05-31-live-tts-design-considerations.md`

당신의 R1 핵심 판정에 **대체로 동의**합니다. 특히 "내부는 청크, 사용자에겐 단일 stitched 오디오 + timeline, 점프/하이라이트는 `audio.currentTime`, MVP는 A+ / C는 v2"는 제 원안(C 권장)보다 견고합니다 — iOS Safari 순차 자동재생 위험 지적이 정확합니다. 수용합니다.

아래는 코드로 교차검증한 결과와, 당신 안에 대한 4가지 보완/이견입니다. 각 항목에 **동의/반대/대안**으로 답해 주세요.

## 코드 교차검증 결과 (사실 확인)
- **Range**: 기존 서빙은 전부 `FileResponse`(Starlette가 HTTP Range 자동 지원). stitched 오디오 seek/resume은 기존 패턴 그대로면 동작 → 당신 우려보다 리스크 낮음. (단 reverse proxy 경로의 `Accept-Ranges`는 점검 유지)
- **DOM 세그먼테이션**: 듣기 콘텐츠는 클라이언트 `marked.parse`로 렌더(`mdKoAudioContent`)됨 → 현재 DOM에 문장 span이 없음. 당신의 "서버 세그먼테이션→안정 dom_id" 권고가 맞고, 이게 최대 통합 리스크임을 코드로 확인.
- **경로 안전 헬퍼**: `safe_paper_dir`, `_is_within`, `safe_paper_dir_at_location` 존재 → 당신의 "기존 resolution 재사용" 권고 즉시 실행 가능.

## 이견/보완 4가지

### D1. manifest.json + timeline.json → 단일 manifest.json 통합
당신은 `manifest.json`(청크 원천)과 `timeline.json`(chunk_id→start/end/text/dom_anchor)을 분리했지만, 제시한 예시를 보면 두 파일의 필드가 겹칩니다(start_sec/end_sec/dom_id/text). **단일 manifest.json**에 청크 메타 + 타임라인 + 캐시키를 모두 담는 게 단순하고 드리프트 위험이 적다고 봅니다. 분리할 실익이 있습니까?

### D2. MVP에서는 per-chunk 오디오 파일을 stitch 후 폐기
당신은 청크 파일을 "생성/부분재생성/품질검증의 원천 캐시"로 보존하자 했습니다. 그러나 청크 보존의 실질 근거는 **부분 재생성(당신 로드맵상 v1.1)** 뿐입니다. MVP는 소스 sha 변경 시 전체 재생성이므로:
- 청크 오디오는 `.jobs/{job}/chunks/`에서 **합성 중에만 임시 존재** → stitch+검증 후 **삭제**, 최종 공개 산출물은 **stitched 오디오 + manifest.json 둘뿐**.
- 이러면 당신이 약점으로 든 "수백 파일·shard 디렉터리·inode 관리"가 MVP에서 **아예 사라집니다.**
- 청크 보존은 v1.1(부분 재생성)에서 도입.
MVP에서 청크 보존이 꼭 필요한 다른 이유가 있습니까? (품질 재검증은 .jobs 단계에서 하면 됨)

### D3. DOM 세그먼테이션 구현 방식 — 서버 렌더 권고
오디오 모드 하이라이트의 핵심은 manifest의 dom_id와 실제 DOM span의 1:1 일치입니다. 현재는 클라이언트 marked.parse라 span이 없습니다. 두 대안:
- (a) **서버가 오디오 모드 전용으로 문장 분할된 HTML**(각 문장 `<span id="tts-s-000012">`)을 내려주고, 클라이언트는 그대로 주입(marked 우회).
- (b) 클라이언트가 manifest의 문장 오프셋에 맞춰 deterministic하게 span 래핑.
참고: `_ko_audio.md`는 낭독 텍스트라 **수식이 거의 없어** 기존 protectMath→marked→restoreMath 파이프라인의 math 보호가 사실상 무의미 → 오디오 모드는 단순 문단/문장 렌더로 충분. 저는 **(a) 서버 렌더가 단일 진실원천으로 더 견고**하다고 봅니다(세그먼테이션·dom_id·manifest를 서버 한 곳에서 생성). 동의합니까? marked 우회가 기존 KaTeX/마크다운 렌더와 충돌할 여지는?

### D4. 헤딩 "다음 절에서는…" 재작성 제안은 제외(스코프 크리프)
당신은 §1.2에서 헤딩을 자연어 문장으로 풀어주자 했지만, `_ko_audio.md`는 이미 paper-audio-korean 스킬이 낭독 최적화한 결과물입니다. 합성 단계에서 헤딩을 또 재작성하면 책임이 중복됩니다. MVP는 **헤딩=짧은 별도 청크 + 긴 뒷쉼(600\~900ms)** 으로 충분하다고 봅니다. 동의합니까?

## 요청
1. D1\~D4 각각 동의/반대/대안으로 답해 주세요(근거 포함).
2. 제 교차검증·보완에서 **제가 틀렸거나 놓친 점**이 있으면 지적해 주세요(무비판 합의 경계).
3. 남은 이견이 있으면 명시하고, 없으면 **"잔존 이견 0건"** 을 선언해 주세요.
4. 합의된 MVP 설계를 한 문단으로 재진술해 주세요(다음 단계로 spec 작성 예정).

전체 답변을 `/media/restful3/data/workspace/paperflow/docs/reviews/2026-05-31-live-tts-design-codex-round2.md` 에 저장해주세요. 화면에는 한 줄만: `===CODEX_DONE=== 저장 완료: <파일경로>`. 본문은 파일에만.
