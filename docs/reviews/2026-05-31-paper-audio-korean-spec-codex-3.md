===CODEX_FINAL_APPROVAL===

# PaperFlow `paper-audio-korean` 스펙 v3 재검토 — Codex Round 3

검토 대상: `docs/superpowers/specs/2026-05-31-paper-audio-korean-design.md`

판정: **GO**

## Round 2 지적 반영 판정

| Round 2 항목 | v3 반영 판정 | 코멘트 |
|---|---:|---|
| R2 High #1 `paper-explainer` completion marker 부재 | **해소** | Phase 1 완료 판정이 marker 요구에서 legacy completion validation으로 바뀌었습니다. 기존 `_ko_explained.md`와 현재 `paper-explainer` SKILL.md의 marker 부재 현실을 반영합니다. |
| R2 Medium #1 본문 marker TTS 노이즈 | **해소** | completion metadata가 본문 HTML comment에서 `audio/<basename>_ko_audio.meta.json` sidecar로 이동했습니다. 최종 `.md`는 순수 낭독 텍스트로 유지됩니다. |
| R2 Medium #2 인라인 수식 inventory 누락 | **해소** | Source Inventory에 인라인 수식/변수 표현의 문단별 자연어 대응 검증이 추가됐습니다. 모든 `$x$`를 기계적으로 세지 않는 방식도 적절합니다. |
| R2 Medium #3 `lang: ko` 한 줄 애매함 | **해소** | raw TTS 기본 경로에서는 YAML/front matter를 완전히 생략하고, 언어 메타는 sidecar로 분리했습니다. |
| R2 Low #1 mtime 단독 freshness 약함 | **해소** | sidecar에 `source_mtime`, `source_size`, `source_sha256`을 함께 기록하도록 보강됐습니다. |
| R2 Low #2 Markdown footnote 누락 | **해소** | 변환 규칙과 grep 검증에 `[^1]`, `[^1]: ...` 형태가 추가됐습니다. |

## 최종 검토

v3는 Round 1/2의 핵심 통합 리스크를 모두 닫았습니다.

- `audio/` 하위 출력으로 viewer/MCP의 비재귀 직하위 파일 감지와 충돌하지 않습니다.
- section-safe `.part`와 atomic rename, sidecar 기반 완료 판정으로 부분 파일 skip 문제가 해결됐습니다.
- `_ko_explained.md`는 기존 자산과 호환되는 legacy validation으로 판정하고, audio 산출물만 sidecar freshness를 사용합니다.
- Source Inventory가 표/그림/수식/인라인 수식/코드/각주까지 포괄해 "grep은 깨끗하지만 내용이 빠진" 실패를 줄입니다.
- raw TTS 목적에 맞게 최종 `.md` 본문에서 YAML과 운영 메타데이터를 제거한 점이 좋습니다.

남은 이견은 없습니다. 구현 단계로 넘겨도 됩니다.
