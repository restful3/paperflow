# PaperFlow `paper-audio-korean` 스펙 v2 재검토 — Codex Round 2

검토 대상: `docs/superpowers/specs/2026-05-31-paper-audio-korean-design.md`

판정: **REFINE**

v2는 Round 1의 핵심 이슈 대부분을 제대로 반영했습니다. 특히 출력 위치를 `audio/` 하위로 옮긴 결정은 기존 viewer/MCP 비재귀 스캔 구조와 맞아 가장 큰 충돌을 깔끔하게 피합니다. 다만 구현 전에 정리해야 할 운영상 모순이 하나 남아 있어 GO까지는 아직 이릅니다.

## Round 1 지적 반영 판정

| Round 1 항목 | v2 반영 판정 | 코멘트 |
|---|---:|---|
| High #1 `_ko_audio.md` 파일 감지 충돌 | **해소** | `audio/<basename>_ko_audio.md`로 이동했습니다. 현재 `papers.py`, `chat.py`, `mcp_zip.py` 경로는 논문 폴더 직하위만 보므로 백엔드 수정 없이 충돌을 피합니다. README/CLAUDE 문서화도 구현 범위에 들어갔습니다. |
| High #2 부분 파일 skip | **대체로 해소** | `.part` 작성 후 검증 통과 시 atomic rename, marker+source freshness skip 조건은 적절합니다. 단 marker를 최종 MD 내부에 넣는 방식은 아래 Medium 이슈를 보세요. |
| High #3 2단계 의존/소스 정책 | **부분 해소** | Phase 1/2 분리와 번역본 직접 변환 제외는 명확해졌습니다. 그러나 `_ko_explained.md`의 completion marker 요구가 기존 `paper-explainer` 출력과 맞지 않습니다. 아래 High 이슈입니다. |
| High #4 검증 불충분 | **대체로 해소** | Source Inventory와 항목별 대응 검증이 추가되어 단순 grep보다 훨씬 안전합니다. 다만 inline math inventory가 빠져 있습니다. |
| Medium #1 코드 블록 | **해소** | code/prompt/log/algorithm 유형별 변환 규칙과 code fence 0건 검증이 들어갔습니다. |
| Medium #2 표 데이터 보존 | **해소** | 핵심 실험표 4~8문장, 대표 수치 보존, 예외/기준선 차이 보존으로 보강됐습니다. |
| Medium #3 각주 의미 손실 | **해소** | 표식 제거와 의미 있는 각주 본문 병합 기준이 들어갔습니다. |
| Medium #4 batch 구체성 | **대체로 해소** | exclusion, `.part`, stale audio 재생성 기준이 들어갔습니다. symlink 안전성 표현은 충분합니다. |
| Medium #5 YAML | **부분 해소** | Quarto 헤더 제거 방향은 맞습니다. 다만 "최소 `lang: ko` 한 줄"은 raw TTS 목적과 YAML 문법 양쪽에서 애매합니다. |
| Low #1 문서화 | **해소** | README/CLAUDE.md 갱신이 구현 범위에 포함됐습니다. |
| Low #2 상태표기 | **해소** | Draft로 내려갔습니다. |
| Low #3 약어 사전 | **해소** | 변환 시작 시 낭독 사전 작성 규칙이 추가됐습니다. |

## High

1. **Phase 1의 `_ko_explained.md` completion marker 요구가 기존 `paper-explainer`와 맞지 않아 재생성 루프/대량 재작업 위험이 있습니다.**

   v2 §5는 `_ko_explained.md`가 없거나 "미완성(completion marker 없음/coverage 실패)"이면 `paper-explainer`를 실행한다고 합니다. 문제는 현재 `paper-explainer` 스킬은 `_ko_explained.md` 말미에 completion marker를 쓰는 규칙이 없습니다. 실제 기존 `outputs/`의 해설판들도 marker가 없습니다. 이 조건을 그대로 구현하면 이미 완성된 해설판을 모두 미완성으로 판단하거나, `paper-explainer`를 재실행해도 marker가 생기지 않아 Phase 1을 계속 통과하지 못할 수 있습니다.

   권장 수정안:
   - 기존 해설판은 marker가 없어도 `paper-explainer`의 품질 기준에 해당하는 legacy validation으로 완료 판정합니다. 예: `_ko_explained.md` 존재, 비어 있지 않음, YAML/제목 정상, source 대비 heading coverage 통과, References 등 예외를 제외한 주요 섹션 존재.
   - completion marker는 audio 산출물에만 요구하거나, paper-explainer 스킬 자체를 별도 변경해 future marker를 쓰게 하되 기존 파일에는 legacy path를 둡니다.
   - 문구를 "`_ko_explained.md` 없음 또는 legacy completion validation 실패"로 바꾸는 것이 안전합니다.

## Medium

1. **완성 marker를 최종 MD 본문에 넣으면 raw TTS 노이즈가 될 수 있습니다.**

   v2는 raw 마크다운을 아이폰에서 직접 듣는 사용을 우선한다고 하면서, 최종본 말미에 HTML comment completion marker를 넣습니다. 렌더러가 HTML comment를 숨기면 괜찮지만, 파일 앱/일부 Markdown 뷰어/텍스트 뷰어의 화면 읽기에서는 주석 문자열 자체가 읽힐 수 있습니다. 이 스킬의 목적이 "귀로 듣기 좋은 텍스트"이므로 운영 메타데이터를 본문에 넣는 방식은 방향과 충돌합니다.

   권장 수정안: completion marker와 source metadata는 `audio/<basename>_ko_audio.meta.json` 같은 sidecar에 저장하세요. 최종 `.md` 본문은 순수 낭독 텍스트만 두는 편이 맞습니다. skip 조건은 sidecar의 `status=complete`, `source_path`, `source_mtime`, 가능하면 `source_sha256`으로 판단하면 됩니다.

2. **Source Inventory가 inline math를 별도로 세지 않습니다.**

   §9는 "수식 블록 개수"만 기록합니다. 하지만 §6과 §9 grep은 인라인 `$...$`도 제거 대상으로 봅니다. 학술 논문에서는 인라인 수식이 변수 정의, 조건, 지표명을 많이 담기 때문에 자연어 대응 없이 빠져도 inventory 검증이 잡지 못합니다.

   권장 수정안: inventory 항목을 "수식 블록 개수 + 의미 있는 인라인 수식/변수 표현 목록 또는 클러스터"로 확장하세요. 모든 `$x$`를 1개씩 세기보다, 문단별로 "이 문단의 인라인 수식/변수 표현을 자연어로 풀었는가"를 확인하는 방식이면 과도한 기계적 체크를 피할 수 있습니다.

3. **`lang: ko` 한 줄은 YAML 헤더도 아니고 raw TTS에서는 낭독 노이즈일 수 있습니다.**

   §7은 "최소 `lang: ko` 한 줄만 두거나 생략"이라고 합니다. 표준 Markdown YAML front matter라면 `---` delimiter가 필요하고, raw TTS 기준이라면 `lang: ko` 자체가 읽힐 수 있습니다.

   권장 수정안: raw TTS 기본값은 **헤더 생략**으로 고정하세요. HTML/Quarto 변환이 필요할 때만 `md-to-html` 단계에서 front matter를 주입한다고 명시하면 됩니다. 언어 메타데이터가 꼭 필요하면 위 sidecar meta에 넣는 편이 낫습니다.

## Low

1. **source freshness는 mtime만으로는 약합니다.**

   source mtime은 복사/복원/동기화 과정에서 흔들릴 수 있습니다. 큰 문제는 아니지만 재생성 여부 판단에는 `source_mtime`과 함께 `source_size` 또는 `source_sha256`을 저장하는 편이 안전합니다.

2. **Markdown footnote 문법도 명시하면 좋습니다.**

   각주 규칙이 `<sup>N</sup>` 중심입니다. PaperFlow 변환 결과에는 HTML 각주가 많지만, Markdown footnote `[^1]`, `[^1]: ...`가 섞일 수 있으므로 제거/병합 대상에 함께 넣으면 구현자가 덜 헷갈립니다.

## 잘 된 점

- Round 1의 가장 큰 통합 문제였던 viewer/MCP suffix 충돌은 `audio/` 하위 디렉터리로 잘 해결했습니다.
- `.part` 작성, atomic rename, stale source 재생성 기준은 section-safe 운영에 맞습니다.
- Source Inventory와 항목별 대응 검증이 들어가면서 "grep 0건인데 내용은 누락"되는 실패 모드를 상당히 줄였습니다.
- 코드 블록, 큰 실험표, 의미 있는 각주를 별도 정책으로 나눈 점이 실제 REACT/Search-o1/LongLM류 출력과 잘 맞습니다.

## 구현 단계 이관 판정

**REFINE**

남은 핵심 보완은 작지만 중요합니다. `paper-explainer`가 completion marker를 만들지 않는 현실을 반영해 Phase 1 완료 판정을 legacy validation으로 바꾸고, audio 최종 MD 내부 marker/YAML을 sidecar 또는 생략 방식으로 정리하면 구현 단계로 넘겨도 됩니다.
