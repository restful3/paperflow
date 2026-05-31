# HLS TTS 합성 duration 실측 — TARGETDURATION / 문장 cap / 음량 결정

_측정일: 2026-05-31 · 모델: Chatterbox-Multilingual(ko) · 기존 검증 venv `/tmp/cbx-venv`_

선행 BLOCKING (스펙 §12.0, 백엔드 플랜 Task 0). 이 문서의 결정값이
`tts_service/app/hls.py`(TARGETDURATION) · `tts_service/app/chunker.py`(SENTENCE_CHAR_CAP) · 세그먼트 음량 필터의 근거다.

## 측정 방법

- 대상 corpus: `outputs/*/*_ko_audio.md` **11개 파일**, 총 **4,100개** 고유 text 문장.
- 문장 길이 분포 (합성 전): 최장 **159자**, P99 115자, P90 81자, P50 44자. 200자 초과 0개.
- 표본 **200개** = 최장 150개(P100·worst-case 지배) + 길이 층화 50개(짧은 문장의 고정 오버헤드 측정).
- 각 문장을 합성해 `ffprobe`로 duration 측정. 스크립트: `tts_service/.hls_measure/run.py`(측정 후 제거).
- 합성 1건 ~6.3초, 총 wall **1,268초**.

## 측정 결과

| 지표 | 전체(glitch 포함) | 정상(glitch 제외) |
|------|------------------|-------------------|
| duration P50 | 10.7s | — |
| duration P95 | 15.8s | — |
| duration P99 | 27.28s | 19.48s |
| **duration P100** | 31.68s | **22.24s** |
| median sec/char | 0.1061 | — |
| **worst sec/char** | 0.7578 (glitch) | **0.1692** |

### Glitch (모델 토큰 반복 이상치)

200개 중 **11개(5.5%)** 가 `sec/char > 1.6 × median`. 합성 로그에 `Detected 2x repetition of token … forcing EOS` 경고와 함께 duration이 2\~4배로 부풀려진다. 텍스트 길이와 무관한 **모델 stochastic 아티팩트**다.

- 큰 절대시간 glitch: 111자→31.68s, 36자→27.28s, 101자→18.2s
- 작은 절대시간 glitch: 17자→4.72s, 12자→4.2s 등 (짧은 문장의 고정 오버헤드 + 약한 반복 — 실무상 무해)

**중요**: glitch는 **문자 cap으로 막을 수 없고**(텍스트가 짧아도 발생), 길이게이트 + 재합성(TTS 분산 1회, Task 5 `_synth_encode_with_retry`)으로 처리한다. 따라서 cap 산정에는 glitch가 아닌 **정상 worst sec/char(0.1692)** 를 쓴다. 플랜의 문자대로 `worst_sec_per_char=0.7578`을 쓰면 `floor(16/0.7578×0.9)=19자`라는 비현실적 값이 나오므로 채택하지 않는다.

## 결정값

### TARGETDURATION = 16 (초)

- HLS `#EXT-X-TARGETDURATION`(세그먼트 상한)이자 `encode_segment` 과길이 게이트 임계.
- 스트리밍 점진 재생 UX를 위해 세그먼트를 16s 이하로 유지(placeholder 기본값과도 일치).
- 게이트: `round(dur) > 16` → reject → 재합성. 큰 glitch(31.68/27.28/18.2s)를 포착한다.
- 정상 문장이 게이트에 걸리지 않도록 SENTENCE_CHAR_CAP으로 (sub-)문장 길이를 제한(아래) → 정상 sub-chunk는 ≤ ~14.4s.
- 플랜의 `ceil(P100×1.3)` 공식은 glitch P100(31.68)→42, 정상 P100(22.24)→29를 주는데, 둘 다 게이트를 사실상 무력화(42)하거나 세그먼트가 과도하게 길어진다(29). cap으로 길이를 선제한 뒤 16으로 고정하는 편이 게이트·UX 모두 우수하다.

### SENTENCE_CHAR_CAP = 85 (자)

- `floor(TARGETDURATION / normal_worst_sec_per_char × 0.9) = floor(16 / 0.1692 × 0.9) = floor(85.1) = 85`.
- 85자 문장의 정상 worst-case = 85 × 0.1692 ≈ **14.4s** < 16(안전계수 0.9 적용 후).
- corpus 영향: 상위 ~12%(>85자, P90=81\~P100=159)만 sub-split → 2조각. 과도 분할 아님.
- `chunker.py` 의 `SENTENCE_CHAR_CAP` 에 적용.

### 음량

- **스트리밍 세그먼트**: 고정 리미터 `alimiter=limit=0.95` (per-segment loudnorm은 전체신호 분석이 필요해 부적합). MVP에서 음량 이슈 미관측이라 게인 추가 없이 리미터만.
- **다운로드 mp3**: 현행 `loudnorm=I=-16:TP=-1.5:LRA=11` 유지.

## 잔여 리스크

- 정상 long sub-chunk가 드물게 glitch로 >16s → 재합성 1회 → 그래도 초과면 `failed_partial`(앞부분 재생 가능). 이중 glitch 확률 ~0.3%, v1 수용.
