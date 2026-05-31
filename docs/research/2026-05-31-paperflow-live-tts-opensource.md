# PaperFlow 라이브 TTS — 오픈소스 모델/솔루션 리서치

**작성일**: 2026-05-31  
**대상**: PaperFlow 한국어 듣기 파일(`_ko_audio.md`) 라이브 TTS 제공 기능  
**방법**: deep-research 하니스(6각도 · 24소스 · 110주장) + 핵심 사실 수동 교차검증  
**환경**: RTX 3060 12GB 1장(배치 변환이 GPU 점유 중), Docker, FastAPI/Alpine.js

---

## 0. 리서치 신뢰도 고지 (중요)

deep-research 자동 파이프라인에서 **검증(Verify) 단계가 기계적으로 고장**났다. 주장당 적대적 검증 에이전트 3명이 전원 `StructuredOutput` 도구 호출에 실패(기권)해, 모든 주장이 `0-0`(반박 0 / 확인 0)으로 집계됐고 시스템이 이를 "전부 반박됨 → inconclusive"로 **오판**했다. 이는 실제 반박이 아니라 투표 수집 버그다.

반면 **Search/Fetch 단계는 정상 작동**했고, 수집된 주장 다수가 GitHub·HuggingFace 공식 저장소(1차 출처)에서 나왔다. 따라서 본 리포트는:

- 1차 출처 주장을 기본 신뢰하되,
- **의사결정을 좌우하는 핵심 사실 3건**(MeloTTS 한국어/MIT/CPU, Kokoro 한국어 미지원, XTTS 라이선스)은 **저자가 직접 모델 카드를 재확인**했다(§7 출처에 ✔ 표기).

---

## 1. TL;DR — 결론부터

> **[2026-05-31 최종 갱신]** CPU 옵션 제외 + GPU VRAM 실측(여유 11.7/12GB) 반영 후 순위. 초기 합성(MeloTTS 1순위)은 §4.5·아래 표로 대체됨.

| 순위 | 솔루션 | 한 줄 요약 |
|------|--------|-----------|
| **1순위 (권장)** | **Chatterbox-Turbo** | MIT · 한국어(23개 언어) · 음성 클로닝 · 블라인드 선호 65.3% · ~75ms · **~4.5GB** (12GB에 여유 적재). 한국어 음질 청취 확인 권장 |
| 2순위 (경량·스트리밍) | **CosyVoice2-0.5B** | Apache-2.0 · 한국어 · **150ms bi-streaming** · ~1\~2GB. 저지연/경량 우선 시 |
| 차선 (클로닝) | **XTTS-v2** | 한국어 + 6초 클로닝, 그러나 **CPML 비상용** + GPU ~2GB |
| 영어 전용 | **Kokoro-82M / Kokoro-FastAPI** | Apache-2.0 · 초경량 · 진짜 청크 스트리밍, **한국어 미지원** |
| 제외 | MeloTTS(CPU 느림) · Fish Speech(제한 라이선스·4B) | — |

**핵심 통찰**: 당초 "배치와 VRAM 공존(1\~2GB)" 제약이 1순위를 좌우했으나, **실측 결과 RTX 3060은 평상시 11.7GB가 비어 있고 MinerU 배치는 변환 중에만 일시 점유**한다. 따라서 ~4.5GB의 Chatterbox-Turbo가 12GB에 무리 없이 올라가며, 변환 피크와 겹치는 드문 경우만 TTS 큐잉으로 회피하면 된다. 결과적으로 **한국어 + 최신 최고 품질 + MIT 상용 + 클로닝**을 갖춘 Chatterbox-Turbo가 1순위다.

---

## 2. 환경 제약 재확인 (왜 한국어 + 경량이 핵심인가)

- **언어**: `_ko_audio.md` 는 한국어 낭독 텍스트 → **한국어 음질이 1순위**. 한국어 미지원 모델은 아무리 좋아도 탈락(영어 논문 보조용으로만 검토).
- **VRAM 공존**: 배치 변환이 GPU를 크게 점유 → TTS 소용 VRAM이 1\~2GB급이거나, 아예 **CPU에서 실시간**이어야 충돌이 없다.
- **제공 방식 (둘 다 검토)**:
  - (a) **온디맨드 파일 생성**: 논문 열 때 전체 mp3를 한 번 생성·캐싱(RTF<1이면 충분).
  - (b) **스트리밍**: 문장/문단 단위로 합성해 즉시 재생(저지연 TTFB).
- **통합**: Python/FastAPI에서 호출, Docker 컨테이너로 격리.

---

## 3. 후보 비교표

| 모델 | 한국어 | 라이선스 | 크기 / 소용 자원 | 속도 | 스트리밍 | 음성 클로닝 | 통합 난이도 |
|------|:---:|------|------|------|:---:|:---:|------|
| **MeloTTS-Korean** | ✅ 네이티브 | **MIT (상용 O)** | 소형 · **CPU 실시간(GPU 0)** | RTF<1 (CPU) | ✖ (문단 청킹으로 의사 스트리밍) | ✖ (고정 화자) | 낮음 (`melo.api`) |
| **Kokoro-82M** | ❌ (8개 언어, 한국어 없음) | **Apache-2.0** | **82M (초경량, <1GB)** | 35\~100× 실시간(GPU), ~300ms TTFB | ✅ 진짜 청크 | ✖ | 낮음 (FastAPI 래퍼 존재) |
| **XTTS-v2** | ✅ (17개 언어 중 ko) | **CPML (비상용)** ⚠️ | ~1.8GB, GPU 권장 | GPU 실시간급 | 부분 | ✅ (6초) | 중간 (Coqui TTS) |
| **Chatterbox Multilingual** | △ (23개 언어, 한국어 포함 여부 확인 필요) | MIT | ~0.5B, GPU ~2\~3GB | GPU 실시간급 | 부분 | ✅ | 중간 |
| **Fish Speech S2** | △ (Tier 2) | 연구용 제한 ⚠️ | **4B (과대)** | GPU | ✅ | ✅ | 높음 |
| **Piper** | △ (커뮤니티 한국어 음성, 품질 편차) | MIT | 초경량 · **CPU 매우 빠름** | RTF≪1 (CPU) | ✅ (ONNX 스트림) | ✖ | 낮음 |
| **RealtimeTTS (래퍼)** | 엔진 의존 | MIT (엔진별 별도) | 엔진 의존 | 엔진 의존 | ✅ 통합 스트리밍 | 엔진 의존 | 낮음 |

> 표의 라이선스·언어·크기 값은 각 모델의 공식 저장소/모델 카드 기준(§7). Chatterbox 한국어 포함 여부와 Piper 한국어 음성 품질은 **추가 실측 필요**(§6).

---

## 4. 후보별 상세

### 4.1 MeloTTS-Korean ★ 권장

- **출처**: [github.com/myshell-ai/MeloTTS](https://github.com/myshell-ai/MeloTTS), [huggingface.co/myshell-ai/MeloTTS-Korean](https://huggingface.co/myshell-ai/MeloTTS-Korean) (✔ 저자 재확인)
- **라이선스**: MIT — 상용·비상용 모두 자유.
- **한국어**: 네이티브 지원(EN/ES/FR/ZH/JP/**KR**).
- **자원**: "Fast enough for CPU real-time inference" 명시 → **GPU VRAM 0** 으로 배치와 완전 분리 가능.
- **Python API** (모델 카드 그대로):

```python
from melo.api import TTS

speed = 1.0
device = 'cpu'  # or 'cuda:0'
text = "안녕하세요! 오늘은 날씨가 정말 좋네요."
model = TTS(language='KR', device=device)
speaker_ids = model.hps.data.spk2id
model.tts_to_file(text, speaker_ids['KR'], 'kr.wav', speed=speed)
```

- **장점**: 한국어 + 상용 라이선스 + CPU 실시간 + 간단 API — 4대 제약 동시 충족.
- **한계**: (1) 네이티브 스트리밍 API 없음 → 문장/문단 단위로 쪼개 합성하면 의사 스트리밍 가능. (2) 고정 단일 화자(클로닝·화자 선택 없음). (3) 매우 표현적이진 않으나 **장시간 낭독 청취**에는 명료함·일관성이 더 중요해 적합.

### 4.2 Kokoro-82M / Kokoro-FastAPI (영어 논문 보조용)

- **출처**: [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (✔), [remsky/Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI)
- **라이선스**: Apache-2.0. **82M 파라미터** 초경량(StyleTTS2 + ISTFTNet, 디퓨전 없음). v1.0 = 8개 언어·54화자.
- **한국어**: **미지원** — 8개 언어는 영(US/GB)·스페인·프랑스·힌디·이탈리아·일본·포르투갈(BR)·중국. → **한국어 낭독엔 부적합**.
- **스트리밍**: Kokoro-FastAPI(FastKoko)가 **OpenAI 호환 `/v1/audio/speech`** + 진짜 청크 스트리밍(`stream=true`, PCM 24kHz 16-bit mono), GPU 35\~100× 실시간, ~300ms TTFB, **Docker 제공**.
- **결론**: 스트리밍·경량·품질·통합 모두 최상이나 **한국어가 없어 1순위 불가**. PaperFlow가 영어 듣기판도 만들 경우 영어 전용 엔진으로 매우 우수.

### 4.3 XTTS-v2 (한국어 + 클로닝, 단 라이선스 주의)

- **출처**: [coqui/XTTS-v2](https://huggingface.co/coqui/XTTS-v2) (✔)
- **라이선스**: **Coqui Public Model License (CPML)** — 비상용 한정으로 널리 알려짐. PaperFlow가 개인·비상용이면 사용 가능하나, 상용 전환 시 위험.
- **한국어**: 17개 언어 중 `ko` 포함. **6초 클립으로 음성 클로닝** + 감정/스타일 전이.
- **자원**: ~1.8GB, GPU 권장 → 배치와 VRAM 경합 발생(12GB 내 여유 있을 때만).
- **결론**: "내 목소리/특정 화자"로 낭독하고 싶거나 표현력이 필요하고 **비상용**이면 후보. 상용 가능성·VRAM 공존 측면에서 MeloTTS보다 불리.

### 4.4 기타

- **Fish Speech / OpenAudio S1·S2**: 연구용 제한 라이선스(상용 곤란), S2-Pro **4B**(VRAM 예산 초과), 한국어 Tier 2(최적화 낮음) → **보류**.
- **Chatterbox Multilingual** (resemble-ai, MIT, 23개 언어): MIT라 상용 친화적이나 **한국어 포함 여부·소용 VRAM 실측 필요**. GPU ~2\~3GB 추정.
- **Piper** (rhasspy, MIT): VITS 기반 초경량, **CPU에서 매우 빠름**, ONNX 스트리밍. 한국어는 **커뮤니티 음성**이라 품질 편차 → 한국어 품질 실측 후 보조 후보로 검토 가치.
- **RealtimeTTS** (KoljaB, MIT): Kokoro·Piper·XTTS·StyleTTS·Parler 등을 **단일 스트리밍 API**로 묶는 래퍼. 엔진별 라이선스는 따로 확인 필요. 스트리밍 인프라를 빠르게 구축할 때 유용.

---

## 4.5 최근(2025 Q4 \~ 2026) 신규 경량 모델 추적 ★ 추가 질의 반영

> 저자 지식 컷오프(2026-01) 이후 모델은 별도 웹 검증함(§7 신규 출처). **핵심 발견: 최근 공개된 '초경량(≤100M)·CPU' 모델은 대부분 한국어를 지원하지 않는다.**

| 모델 | 공개 | 한국어 | 크기 | 소용 VRAM | 라이선스 | 속도·품질 | 비고 |
|------|------|:---:|------|------|------|------|------|
| **Chatterbox-Turbo** (Resemble AI) | 2026 추정(’25 Q4 라인) | ✅ (23개 언어 중 ko) | 350M (1-step distilled) | **~4.0\~4.5GB** | **MIT** | ~75ms·6×실시간, 블라인드 선호 **65.3%** vs ElevenLabs 24.5% | 음성 클로닝·paralinguistic 태그, OpenAI 호환 셀프호스트 서버(devnen) 존재 |
| **CosyVoice2-0.5B** (FunAudioLLM) | 2024/12 | ✅ (9개 언어) | 0.5B | ~1\~2GB(추정) | **Apache-2.0** | bi-streaming **150ms** | 한국어+스트리밍+소형 균형 최고. '최근 3개월'은 아님 |
| **Kyutai Pocket TTS** | 2026/01 | ❌ (EN/FR/DE/ES/PT/IT) | **100M** | **CPU 실시간** | 확인 필요 | CPU 실시간·클로닝 | 초경량이나 한국어 없음 |
| **KittenTTS** | 2025\~ | ❌ | **15M (25MB)** | **CPU(GPU 0)** | Apache-2.0 | 실시간 | 영어 전용, 초소형 |
| **MOSS-TTS** | 2026/02 | △ 미확인 | ? | ? | "제한 없음" 주장 | 다국어 | 페이지 403으로 한국어 미확인 |
| **Voxtral TTS** (Mistral) | 2026/03 | ❌ (9개 언어, 한국어 없음) | 4B | 16GB 권장 | CC | 90ms TTFB | 너무 큼·한국어 없음 |
| **Qwen3-TTS** | 2026 | △ 미확인(Qwen 다국어→가능성) | ? | ? | ? | 클로닝 | 페이지 fetch 실패, 확인 필요 |

**트레이드오프 요약 (사용자 질의 직답):**

- 최근 나온 **초경량·CPU** 신모델(KittenTTS 15M, Kyutai Pocket 100M, Kokoro 82M)은 **거의 다 한국어 미지원** → 한국어 낭독엔 못 씀.
- 최근 모델 중 **한국어 + 최고 품질 + MIT(상용) = Chatterbox-Turbo**. 단 **소용 ~4.5GB** 로 "1\~2GB" 목표보다 커서, 12GB에서 배치와 공존은 배치 VRAM 피크에 따라 빠듯할 수 있음(배치 유휴 시 가동이 안전).
- **한국어 + 소형 + 스트리밍(150ms) + Apache = CosyVoice2-0.5B(~1\~2GB)** — '최근 3개월'은 아니지만 제약 적합도가 가장 높음.
- **GPU 0(완전 공존) + 한국어 = MeloTTS(CPU)** 는 여전히 유효(품질·표현력만 평범).

**[2026-05-31 갱신] 실측 데이터 + 제약 재조정:**

- **CPU 옵션 제외** (느림) → MeloTTS(CPU)는 후보에서 제외.
- **실측**: `nvidia-smi` 기준 GPU 12288MiB 중 **197MiB만 사용 / 11741MiB 여유**, GPU 점유 프로세스 없음. 컨버터(MinerU)는 watch 대기(newones 0건)라 평상시 VRAM 거의 0. 변환 중에만 일시 피크(추정 ~5\~8GB).
- 따라서 **"소용 1\~2GB" 제약은 과도하게 보수적**이었음. Chatterbox-Turbo의 ~4.5GB는 평상시 여유롭게 적재 가능, 변환 피크와 겹칠 때만 **TTS 요청 큐잉**으로 회피.

**재정리된 우선순위 (CPU 제외 · VRAM 제약 완화):**

1. ★ **Chatterbox-Turbo** (MIT·한국어·클로닝·최신 최고 품질, ~4.5GB) — 12GB에 무리 없이 적재. **새 1순위.** 단 한국어 음질 청취 확인 권장.
2. **CosyVoice2-0.5B** (Apache·한국어·150ms 스트리밍, ~1\~2GB) — 더 가볍고 저지연. 스트리밍 우선이거나 Chatterbox 한국어 품질이 미흡할 때의 대안.
3. **XTTS-v2** (한국어·클로닝, 단 CPML 비상용) — 위 둘이 막힐 때만.

---

## 5. PaperFlow 통합 아키텍처 권장

### 5.1 배치 방식 (1단계 — 가장 단순·안전)

`_ko_audio.md` 는 이미 순수 낭독 텍스트다. 가장 단순한 "라이브"는 **온디맨드 사전생성 + 캐싱**:

```text
1. 신규 TTS 사이드카 컨테이너 추가 (viewer·converter와 분리)
   - MeloTTS-Korean, device='cpu' → GPU 미사용(배치와 충돌 0)
2. FastAPI 엔드포인트: POST /tts  (paper_name 입력)
   - _ko_audio.md 로드 → 문장/문단 분할 → 합성 → 이어붙여 mp3
   - 결과를 논문 폴더에 캐싱:  <basename>_ko_audio.mp3
3. viewer: "듣기" 재생 버튼 → <audio src=".../md-ko-audio.mp3">
   - 캐시 있으면 즉시 재생, 없으면 생성 후 재생
```

- 장점: 구현 단순, 한 번 생성하면 재청취 즉시, GPU 무관.
- `_ko_audio.meta.json` sidecar처럼 **소스 freshness(mtime/sha256)** 로 캐시 무효화하면 듣기 텍스트 수정 시 자동 재생성.

### 5.2 스트리밍 방식 (2단계 — 저지연 체감)

```text
- FastAPI StreamingResponse 로 문단별 오디오 청크를 SSE/chunked 전송
- 브라우저: MediaSource Extensions 또는 순차 <audio> 청크 재생
- MeloTTS는 문단 단위 합성이 CPU에서도 빨라(RTF<1) 첫 문단 TTFB 수용 가능
```

진짜 토큰 단위 스트리밍이 꼭 필요하면 Kokoro-FastAPI의 청크 스트리밍이 기술적으로 우수하나, **한국어 미지원**이라 현 단계 적용 불가.

### 5.3 권장 결정 트리

```text
한국어 낭독이 목적이다
  └─ 상용 가능성 필요 or GPU를 배치와 공유해야 한다
        └─ ✅ MeloTTS-Korean (CPU, 배치 방식부터 시작 → 필요시 문단 스트리밍)
  └─ 비상용 + 화자 클로닝/표현력 중시 + GPU 여유 있음
        └─ XTTS-v2 (CPML 확인 필수)
영어 듣기판도 제공한다
  └─ Kokoro-FastAPI (Apache-2.0, 진짜 스트리밍) — 영어 전용 엔진으로 병행
```

---

## 6. 추가 검증이 필요한 항목 (자동 Verify 실패로 미완)

1. **MeloTTS 한국어 음질의 주관적 적합성** — 장시간 낭독 청취 기준으로 실제 샘플 생성·청취 필요(명료도 OK 예상, 표현력은 보통).
2. **Chatterbox의 한국어 포함 여부** 및 소용 VRAM 실측.
3. **Piper 한국어 커뮤니티 음성 품질** — MIT·CPU 초고속이라 품질만 받쳐주면 매력적.
4. **MeloTTS 문단 스트리밍 TTFB** — CPU에서 첫 문단 합성 지연 실측.
5. RTX 3060에서 **MeloTTS GPU 모드 소용 VRAM**(CPU로 충분하면 불필요).

→ 권장: §5.1 배치 방식으로 **MeloTTS 한국어 샘플을 먼저 1편 생성·청취**해 품질을 눈으로(귀로) 확인한 뒤 통합 진행.

---

## 7. 출처 (1차 출처 중심)

✔ = 저자가 모델 카드를 직접 재확인한 항목.

- ✔ MeloTTS: https://github.com/myshell-ai/MeloTTS · https://huggingface.co/myshell-ai/MeloTTS-Korean (MIT, 한국어, CPU 실시간, `melo.api`)
- ✔ Kokoro-82M: https://huggingface.co/hexgrad/Kokoro-82M (82M, Apache-2.0, v1.0 8개 언어·한국어 없음) · https://github.com/hexgrad/kokoro
- Kokoro-FastAPI: https://github.com/remsky/Kokoro-FastAPI (OpenAI 호환, 청크 스트리밍, Docker)
- ✔ XTTS-v2: https://huggingface.co/coqui/XTTS-v2 (CPML, 17개 언어 중 ko, 6초 클로닝)
- Fish Speech: https://github.com/fishaudio/fish-speech (연구용 제한, S2-Pro 4B, 한국어 Tier 2)
- Chatterbox: https://github.com/resemble-ai/chatterbox · https://www.resemble.ai/introducing-chatterbox-multilingual-open-source-tts-for-23-languages/
- Piper: https://github.com/rhasspy/piper/issues/821 · https://github.com/thewh1teagle/piper-onnx
- RealtimeTTS: https://github.com/KoljaB/RealtimeTTS
- 보조(블로그/벤치): bentoml.com TTS 비교, inferless.com TTS Part 2, spheron.network 2026 GPU TTS 배포, heyneo.com Kokoro vs Supertonic

**신규(2026) 모델 추적 — §4.5 검증 출처:**

- ✔ Chatterbox: https://github.com/resemble-ai/chatterbox (MIT, 23개 언어 중 ko, Turbo 350M 1-step 디코더)
- Chatterbox-Turbo VRAM/벤치: https://findskill.ai/blog/best-open-source-tts-2026/ (Turbo 350M·MIT·~75ms·선호 65.3%), Communeify/sonusahani Turbo 가이드(소용 ~4.0\~4.5GB), 셀프호스트 서버 https://github.com/devnen/Chatterbox-TTS-Server
- ✔ CosyVoice2: https://github.com/FunAudioLLM/CosyVoice (Apache-2.0, 9개 언어 중 Korean, 2024/12, bi-streaming 150ms)
- ✔ Kyutai TTS/Pocket: https://kyutai.org/tts (Pocket 100M, 2026/01, EN/FR/DE/ES/PT/IT — 한국어 없음)
- 경량 모델 일람: https://firethering.com/best-lightweight-open-source-tts-models/ (KittenTTS 15M/25MB CPU 등, 2026/03 작성)
- 미확인(추가 검증 필요): MOSS-TTS(qwen-image-2512.com, 403), Qwen3-TTS(medium.com/@zh.milo), IndexTTS-2, Voxtral(Mistral, 4B·한국어 없음)

---

## 부록 — 리서치 통계

- 검색 각도 6 / 수집 소스 24 / 추출 주장 110 / 검증 시도 25 (검증 단계 기계적 실패로 확정 0)
- deep-research 에이전트 106기 · 토큰 ~1.45M · 소요 ~221초
