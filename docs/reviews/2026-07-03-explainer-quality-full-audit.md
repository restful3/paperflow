# 해설판(`_ko_explained.md`) 전수 품질 감사 — 2026-07-03

- **대상**: `outputs/` 의 해설판 **508편** (archives 제외)
- **방법**: ① 전수 기계 스캔(508편) + ② 계층 표본 정독 **~90편**(1차 7리더 35편 + 2차 10리더 58편, 소스+해설판 대조)
- **평가 기준(사용자 5문항)**: ① 내용 반복 ② 기본 소개(출처·저자·작성일) ③ 원문 충실도 ④ 자명한 내용 과잉해설 ⑤ 어려운 내용 과소해설
- **스캐너/데이터**: `tmp/explainer_review/scan.py`, `scan_results.json`, `reading_paths.json`, `reading_paths_wave2.json`
- **선행 문서**: [`2026-06-19-explainer-duplication-scan.md`](2026-06-19-explainer-duplication-scan.md) (원인 진단 + 스킬 보정 이력)

---

## 0. 한줄 결론

라이브러리는 **큰 틀에서 건강**하다. 사용자가 우려한 5개 결함 중 **충실도(③)와 과소해설(⑤)은 전반적으로 문제가 없고**, 실질 결함은 **보정(6/18\~19) 이전에 생성된 269편의 유산**에 집중된 **② 중복(translate-then-restate)** 과 **④ 과잉해설(정형 비유마커·기초 과설명)** 두 가지다. **6/18 스킬 보정 이후 산출물은 중복이 사실상 소멸**(정독 표본 전부 CLEAN)했으나, 대신 **보정 후 새로운 회귀 — 전체 해라체 문체 위반 4편** 이 관측됐다.

---

## 1. 요약 스코어카드

| 기준 | 판정 | 근거 요지 |
|---|---|---|
| ① 내용 반복 | **부분 결함(pre-fix 집중)** | 확정 translate-then-restate(해라체) 12편. 합니다체 재진술 BAD는 pre-fix 고비율 뉴스 **~7%**(정독 45편 중 3, ratio ≥2.5x 집중), MILD ~53%. post-fix 스케일(12편) BAD 0 — 보정 실효 |
| ② 기본 소개 | **대체로 양호** | 배너 누락 0편. 실패 유형 둘: 매체 과잉설명 ~15편, 논문 저자/출처 헤더 누락 일부(예: TAO-RL) |
| ③ 원문 충실도 | **양호(최상급)** | 수식·표·부록 증명·수치까지 보존. 날조 없음. 부록 산문 일부 생략 2편(경미) |
| ④ 과잉해설 | **최대 계통 결함(pre-fix)** | 정형 마커 "비유로 설명하면 이렇습니다:" 문서당 13\~24회 기계 삽입 + GDP·표준편차·몬테카를로급 기초를 박사 독자에게 과설명 |
| ⑤ 과소해설 | **사실상 문제 없음** | 저비율 논문은 원문이 표·벤치마크·참고문헌 위주라 정당. 어려운 수식·증명도 회피 없이 해설 |

**신규 발견(보정 후 회귀)**: 전체 해라체 문체 위반 **4편**(전부 post-fix, 내용은 클린) + Iran편 OCR 오타 1건.

---

## 2. 기계 스캔 결과 (508편 전수)

보정 배포 시각(2026-06-18 20:46)을 기준으로 pre/post 를 가른다.

- **보정 전(pre-fix) 269편 · 보정 후(post-fix) 239편**

신뢰 가능한 기계 신호만으로 분류:

| 분류 | 편수 | pre/post | 신호 |
|---|---|---|---|
| **DUP_REGISTER** (확정 번역+재진술) | 12 | 12 / 0 | 해라체 미변환 번역문단 ≥4 **및** 합니다체 재설명문단 ≥3 공존 |
| **DUP_ADJ** (인접 near-dup, 논문) | 3 | 3 / 0 | 인접 산문 문단 어휘 Jaccard ≥0.5 가 4곳+ |
| **TONE_HAERACHE** (전체 해라체 문체위반) | 4 | 0 / 4 | 해라체 문단 다수 **이면서** 합니다체 문단 <3 |
| 정형 비유마커 ≥2회 | 116 | 대부분 pre | "비유로 설명하면/비유하자면" 계열 반복 |
| 매체 과잉설명 흔적 | 15 | 대부분 pre | "영국의 시사주간지" 류 |
| 저자 도입부 미노출 | 31 | 혼재 | paper_meta 저자가 해설 도입부에 없음 |

**중요한 방법론 한계**: 기계 스캔은 **해라체 번역 반쪽이 남은** translate-then-restate 만 확실히 잡는다. **합니다체끼리의 패러프레이즈 재진술**(원문을 합니다체로 옮긴 뒤 같은 합니다체로 다시 푸는 형태)은 어휘가 달라져 기계로 안 잡힌다 — 이 맹점 때문에 정독 표본을 병행했다.

### 탐지기가 놓쳤던 이유 (선행 프레임 대비 개선)

선행 6/19 스캔은 difflib 기반 "충실복제 비율(frac)"로 verbatim 복제만 잡아 83편을 표시했다. 이번 스캔은 **문체 레지스터 혼용(해라체+합니다체 동시 존재)** 을 지표로 삼아, frac 이 놓치던 패러프레이즈형 번역+재진술을 더 정확히 포착한다. 예: `Abelardo`(3.83x)는 인접-Jaccard 0 이지만 해라체 9문단 + 합니다체 23문단 공존으로 명확히 검출된다.

---

## 3. 기준별 상세 (정독 35편 근거)

### 기준 ① 내용 반복 — pre-fix 에 집중, 세 가지 형태

**형태 A — translate-then-restate (가장 심각, 전부 pre-fix)**

각 섹션이 `## 헤딩` → **해라체 원문 충실 번역 문단** → **합니다체 재설명 문단** 의 쌍으로 기계 반복된다. 정독 6편 **전부 BAD** 확정.

- `Abelardo de la Espriella`(3.83x): "선거일 밤에는 깊은 양극화가 드러났다… 없었다고 했다"(해라체 번역) 직후 "여기서 양극화란… 장면이었습니다…"(합니다체 재설명)로 동일 내용 반복.
- `Tik-Tocqueville`, `American capitalism`, `An interview with SK president` 등 약 10\~15곳/편.
- 재설명 텍스트 자체의 품질(말장난·역사·개념 풀이)은 우수하나, **원문 문단을 통째 재게재**해 분량이 사실상 2배가 되는 구조적 중복.

확정 목록(DUP_REGISTER 12편, 전부 pre-fix): Tik-Tocqueville · Politics (3) · Are most celebrity book-clubs irritating · Fear of the SaaSpocalypse · American capitalism has taken an apocalyptic turn · An interview with South Korea's president · Build a prime minister · Donald Trump could be the man to save Cuba · Abelardo de la Espriella · Meet the jailscraper · [20260601~07] AIML 논문 모음 · Vibe-Coded Motherfucking Website.

**형태 B — 합니다체 패러프레이즈 재진술 (기계 맹점, 실제로는 경미)**

고비율 뉴스 6편 정독 결과 **BAD 0 · MILD 5 · CLEAN 1**. 높은 비율은 대부분 **짧은 소스** 탓이었고, 우려했던 심각한 합니다체 중복은 없었다. 잔존 형태는 문단 끝 "정리하면/쉽게 말해" 1\~2회 재진술 수준. 단 한국어 서문형(`"모든 것이 손에 잡히지 않을 때"`)처럼 **원문이 이미 합니다체 평이한 글** 이면 exp 가 1:1 재진술로 BAD 가 되는 예외가 있다.

**형태 C — 정형 비유마커 반복 (④와 겹침, 아래 참조)**

**post-fix 검증**: 보정 후 뉴스 5편(`Venezuela earthquakes`, `Andy Burnham`, `Bangladesh`, `To save Britain's economy` 등) **전부 CLEAN**. "정리하면/즉/다시 말해" 연속 재진술 루프가 사실상 소멸 → **6/18 스킬 보정이 실효적으로 작동**함을 입증.

**논문(DUP_ADJ) 3편**: 전부 **MILD**. "원문 충실번역 + 캐주얼 재설명 + 핵심 takeaway 박스" 템플릿이 인접 어휘중복을 만들어 기계 플래그를 유발했으나, 실제로는 의도된 교육적 부연이며 BAD 급 아님.

### 기준 ② 기본 소개 — 대체로 양호, 두 가지 실패 유형

배너 블록쿼트는 508편 전부 존재. 정독상 대부분 출처·저자·성격을 적절히 밝힌다(오히려 대통령 인터뷰편은 원문 정정문까지 반영). 실패 유형 둘:

1. **매체 과잉설명**(스킬이 금지한 패턴): "1843년 영국에서 창간된 세계적인 시사·경제 주간지 «이코노미스트»"(`condom-maker`), "영국의 권위 있는 시사·경제 주간지"(`Indonesia`) 등 ~15편.
2. **논문 헤더 누락**: `Tool-Aware Optimization(TAO-RL)` 은 저자·소속·학회·작성일이 도입부에 전무. 다수 논문이 **학회명·작성일**을 빠뜨림(저자·소속은 대체로 있음). `chocolate industry` 는 작성일 누락.

### 기준 ③ 원문 충실도 — 양호(라이브러리 최대 강점)

정독 35편 전부 충실도 OK. 논문은 **수식(식1\~5)·표(Table I\~IX)·부록 증명(SNR 엄밀증명)·수치**까지 보존하고, 뉴스는 모든 숫자·인과를 반영한다. 날조·왜곡 사례 없음. 유일한 완결성 흠:

- `Prompt Injection Landscape`·`FORMALJUDGE`: 부록 분석 산문(D1\~D5, FD1\~FD5, 사례연구)을 통째 생략. 다만 본문 방법·형식주의는 완전 해설 → **결함 수준 아님, 요약 보강 여지**. FORMALJUDGE 는 머리말 "빠짐없이 담되" 문구가 부록 생략과 모순되어 문구 수정 권장.

### 기준 ④ 과잉해설 — 최대 계통 결함(pre-fix 집중)

두 가지 형태가 라이브러리 전반의 가장 큰 실질 흠이다.

1. **정형 비유마커 기계 반복**: `**비유로 설명하면 이렇습니다:**` 를 토씨 하나 안 바꾸고 문서당 **13\~24회** 삽입. 최악 `LLM Multi-Agent Systems`(24회), `Infrastructure for AI Agents`(14회), `Agentic Systems`(13회). 기계 스캔상 정형 마커 ≥2회가 **116편**(대부분 pre-fix). 이 패턴은 글을 기계적으로 만들고 듣기판으로도 전이된다.
2. **자명한 기초 과설명(독자 수준 오판)**: 대상 독자(전자정보 박사+퀀트)에게 자명한 학부 교양 — **GDP·인플레이션·표준편차·z-점수·백분율·몬테카를로("다트 던지기")·이산시뮬("은행 창구")** — 을 비유로 과설명. `American capitalism` 은 인플레이션·채권·금리·GDP·FOMO 를 본문 + 16행 용어표로 이중 설명. `Developing AI Agents with Simulated Data` 는 욕조·다트·개미 비유가 전형.

단 `Config Repair`(마커 14회지만 비유 실질은 의사처방/회로도/탐정 등 매번 다르고 도메인 밀착)처럼 **마커 문구만 정형이고 내용은 양질** 인 경계 사례도 있어, 개선은 "마커 문구 제거 + 기초 비유 절제"에 집중해야 한다.

### 기준 ⑤ 과소해설 — 사실상 문제 없음

저비율(ratio<0.6) 18편을 정독 검증한 결과 **전부 legitimate**. `GPT-4 Technical Report`(0.11x)·`AI Index Report`(0.05x) 등은 원문의 대부분이 벤치마크 표·참고문헌·부록 덤프이고, **본문 산문·방법은 충실히 해설**된다. 어려운 수식(파라미터 시프트·리만 연산·SNR 증명)도 직관까지 풀어 회피가 없다. **전면 재생성이 필요한 과소해설 사례는 없음.**

---

## 4. 신규 회귀 — 전체 해라체 문체 위반 (post-fix 4편)

**전부 6/18 보정 이후** 생성(6/24\~30). 본문 서술 전체가 대화체 합니다체가 아니라 **평서형 해라체("~다/~했다/~한다")** 로 작성돼 스킬 Rule 2 를 위반한다. 합니다체는 상단 고정 배너와 인물 직접인용에만 남아 있다.

- 대상: `권한 주고 책임 묻는 '구조화된 권한위임'의 힘` · `야망이 당신을 지치게 하나요` · `With Iran emboldened, its neighbours…` · `The chocolate industry…`
- **원인**: 소스 `_ko.md`(뉴스/사설 번역본)가 번역 관례상 해라체인데, 해설판이 그 레지스터를 **합니다체로 전환하지 않고 그대로 상속**했다.
- **성격**: 순수 문체 결함 — 내용 충실도·중복·소개는 네 편 모두 양호. 수정은 본문 어미를 합니다체로 일괄 전환하면 된다.
- **부수 버그**: `With Iran emboldened` 8장 "**대체로가 늘어날수록**"은 '대체로(代替路/우회로)'가 OCR 로 깨진 오타 — 함께 수정 권장.

이 회귀는 6/18 보정(중복 차단)이나 배치 컨텍스트 워치독(오염 차단) **어느 쪽으로도 잡히지 않는다** — 스킬의 어조 규칙이 "한국어 소스는 이미 쉬우니 바로 재작성"으로 처리하면서 **해라체→합니다체 전환을 명시 강제하지 않기** 때문으로 보인다.

---

## 5. 근본 원인 심층 분석 — 스킬 + 배치 크론

해설판 생성 파이프라인 전체를 추적해 원인을 확정했다.

### 5.1 생성 경로

```
host cron (매 3분)  paperflow_batch_drain_tick.sh
   → paperflow_batch_choose_next_type.py (explainer/audio/brief 적응 선택)
   → dispatch_batch_explainer.sh --limit 1
       → find_missing_explainers.py (누락 대상 탐색)
       → 배치 프롬프트 파일 발행 (publish_prompt_file.py, sha256 재사용)
       → dispatch_common.sh :: dispatch_to_batch_window()
           → tmux paperflow:batch 창의 Claude Code(ccd)에
             "이 파일 읽고 실행" 한 줄만 paste
   → 그 세션의 Claude Code 가 paper-explainer 스킬로 _ko_explained.md 작성

host cron (매 2분)  ctx_watchdog.sh  → 배치창 컨텍스트 누적 감시 + /clear
```

관련 크론(`crontab -l`):
- `*/2 * * * *` `paperflow-claude-batch-explainer/scripts/ctx_watchdog.sh` — 컨텍스트 워치독
- `*/3 * * * *` `_common/paperflow_batch_drain_tick.sh` — 적응형 드레인(explainer/audio/brief 중 백로그 선택 디스패치)

### 5.2 원인 층위 (선행 진단 + 이번 확인)

**원인 1 — 스킬 규칙 충돌 (translate-then-restate 의 근본)**
구 `paper-explainer/SKILL.md` 의 Rule 0 이 "Expand, Never Shrink (SUPREME, overrides all)"로 분량 확장을 절대명령에 두어, 나중에 추가된 중복금지 규칙을 순위상 눌렀다. 그 결과 `[충실 번역 문단] → [재설명 문단]` 쌍 템플릿이 정착. **→ 6/18\~19 보정으로 해결**: Rule 0 을 "Completeness, Never Omit — Not Length Padding"으로 재프레이밍(완결성·정확성·중복금지 동급, 충돌 시 길이가 짐), 명시적 중복 쌍 금지 블록 추가, 비유 3\~5→0\~3, 검증에 "연속 패러프레이즈 중복 0건" CRITICAL 게이트 추가. 백업 `SKILL.md.bak-recur-20260619-203912` 가 증거.

**원인 2 — 배치 컨텍스트 오염 (후반부 품질 하락 증폭기)**
영속 tmux `paperflow:batch` 창에 `/clear` 없이 컨텍스트가 누적(선행 문서 기록상 269k/27%)돼 배치 후반부 산출물 품질이 떨어졌다. **→ 해결·가동 확인**: `dispatch_common.sh` 의 pre-dispatch `/clear`(fail-closed, decide=CLEAR 아니면 `exit 8`로 거부) + 공유 flock(`/tmp/paperflow_batch_dispatch.lock`) + `ctx_watchdog.sh` 매 2분 + drain tick 의 idle 체크·자동 재기동(Bun 세그폴트로 Claude 죽으면 쿨다운 600s 로 `claude --dangerously-skip-permissions` 재주입).

**배치 프롬프트가 개정 규칙을 참조함(확인)**: 현행 `dispatch_batch_explainer.sh` 가 발행하는 프롬프트는 ⑴ `paper-explainer` 스킬 명시 호출, ⑵ "같은 내용을 다른 말로 두 번 반복하지 마 — 번역 문단과 재설명 문단을 따로 두지 말고 한 번에 통합", ⑶ "Completeness, Never Omit — Not Length Padding 우선", ⑷ 기존 파일·video 스킵을 담는다. **즉 post-fix 파이프라인은 올바르게 배선돼 있고, 정독상 post-fix 산출물이 CLEAN 인 것과 정합한다.**

**원인 3 — 정형 비유마커·기초 과설명 (④의 근본)**
구 스킬이 도메인별 비유를 권장하고 분량 압력이 있던 탓에, LLM 이 개념마다 "비유로 설명하면 이렇습니다:"를 기계적으로 붙이고 자명한 기초까지 비유로 풀었다. **→ 6/18 보정으로 규칙은 개선**(비유 0\~3개, 정형 마커 금지, 독자 수준 가정 명문화)됐으나, **116편의 pre-fix 유산은 그대로**다.

**원인 4 — 신규 해라체 회귀 (미해결)**
4장 참조. 어느 보정으로도 커버되지 않는 새 실패 모드. 스킬에 "한국어/해라체 소스라도 본문 서술은 합니다체로 전환"을 명시 강제하는 규칙이 없다.

**원인 5 — 미해결 유산(가장 큰 잔존 문제)**
6/18 보정 전 생성된 **269편 해설판 본문은 소급 재생성되지 않았다.** 6/25 에는 **듣기판(`_ko_audio.md`) 83편만** 현행 스킬로 재생성했고(중복 병합), 해설판 본문 자체는 손대지 않았다. 뷰어 Easy 모드로 pre-fix 해설판을 읽으면 여전히 중복·정형마커가 보인다.

---

## 5.5 확장 정독(2차) — 합니다체 재진술 유병률 확정

1차 정독은 35편 표본이라 **합니다체끼리의 패러프레이즈 재진술**(기계 스캔 맹점)의 계통 유병률을 확정하지 못했다. 이를 위해 최대 미독 코호트 — **pre-fix 고비율 뉴스**(비논문·해라체 0·ratio ≥2.0x, 총 109편) — 의 **40편(37%)** 을 8리더로, 추가로 post-fix 뉴스 12편·선행(6/19) BAD 지목 6편을 2리더로 정독했다(중복 제거 후 뉴스 ~57편).

**핵심 결과 (pre-fix 고비율 뉴스 정독 45편, 중복 제거)**:

| 반복 등급 | 편수 | 비율 |
|---|---|---|
| BAD (전면 재진술) | 3 | ~7% |
| MILD (문단말 에코·1\~2곳) | 24 | ~53% |
| CLEAN | 18 | ~40% |

- **BAD 3편**: `How to win the World Cup`·`Who should win the World Cup`·`Was this Britain's George Floyd moment` — 매 섹션이 `[원문 합니다체 축자역] → [같은 내용 합니다체 재진술]` 2단 구조. 예: "가장 영향력 있는 요인은 부·인구·신장·지리였습니다…70%를 설명합니다" 직후 "가장 힘이 센 네 가지 열쇠는 부·인구·신장·지리였습니다…70%를 설명하니"로 동일 수치·예시 통째 재진술.
- 이 **~7% 유병률은 선행 6/19 정독의 "~8% BAD" 추정과 일치** → 안정적 수치.
- **중복 심각도가 ratio 와 상관**(정독 확인): ratio **≥2.5x** 는 순수 이중구조 BAD 위험, **~2.4x** 는 통합형 MILD, **<2.0x** 는 인라인 주석 CLEAN. → 소급 재생성은 **ratio 높은 순으로 우선순위**를 매기면 효율적. (선행 6/19 가 BAD 로 본 `strongmen`·`dead heat` 는 실제 ratio<2.0 인라인 CLEAN — frac 스캔의 과대추정.)
- **MILD 의 실체**: 문단 끝 "즉/정리하면/다시 말해/…셈입니다" 형태의 **해석성 마감 에코**. 대개 방금 진술에 해석·인과를 덧붙여 순수 중복은 아니나, 습관적으로 반복돼 분량을 늘린다.

**post-fix 스케일 검증 (12편)**: **BAD 0** — 6/18 보정이 규모에서도 심각한 재진술을 제거했음을 재확인(1차 5편 CLEAN + 2차 12편 BAD 0). 단 잔존 **MILD "해석성 마감 에코"가 8/12** 로, **보정은 BAD 를 없앴지 MILD 습관까지 없애지는 못했다.**

**2차에서 보강된 부수 관찰**:
- **매체 과잉설명이 기계 추정(15편)보다 흔함** — 정독상 `franchises`·`immigration`·`Ferrari`·`Ben-Gvir`·`China`·`Beverly Gage`·`변화에 발맞추기` 등에서 "이코노미스트는 1843년 영국에서 창간된… 주간지" 류가 반복. ② 소개의 실제 실패 유형은 매체 과잉 쪽.
- **번호형 비유 스캐폴딩** ("이 글을 관통하는 첫 번째/두 번째/세 번째 핵심 비유")이 ④ 정형 마커의 변형으로 다수 편에 존재(`Tik-Tocqueville`·`British hard right`·`변화에 발맞추기` 등).
- 스킬이 금지한 **"학술 논문이 아니라 …" 도입 상투구**가 아직 잔존(`변화에 발맞추기가 어느 때보다 힘든 이유`).
- 사소 아티팩트: `A posh and peculiar British magazine` 은 소스 소제목이 **H2 헤더 + 본문으로 중복 인쇄**됨.

---

## 6. 권고 (우선순위순)

1. **[높음] pre-fix 확정 결함 소급 재생성 (ratio 우선순위)** — DUP_REGISTER 12편(해라체 이중구조) + 합니다체 BAD 확정분(`How to win the World Cup`·`Who should win the World Cup`·`Was this Britain's George Floyd moment`)을 현행 `paper-explainer` 스킬로 재생성. **pre-fix 비논문 뉴스는 ratio ≥2.5x 를 우선 대상**으로 삼으면 BAD 를 효율적으로 걷어낸다(정독상 BAD 가 이 구간에 집중). 이어서 정형 마커 ≥2회 116편 중 pre-fix 를 웨이브로 재생성(듣기판 83편 소급과 동일한 병렬 서브에이전트 방식). ratio<2.0x 인라인 주석형은 대체로 CLEAN 이므로 후순위.
2. **[높음] 신규 해라체 회귀 차단** — `paper-explainer/SKILL.md` Rule 2 에 "소스가 해라체(뉴스/사설 번역본)여도 본문 서술 어미는 합니다체로 전환한다(직접인용·배너 예외)"를 명문화하고, 검증 체크리스트에 문체 게이트 추가. 기존 4편은 어미 일괄 전환으로 수정.
3. **[중간] 매체 과잉설명·정형 마커 잔존 제거** — 스킬 규칙은 이미 금지하나 pre-fix 유산에 남음 → 1번 재생성에 포함.
4. **[낮음] 개별 수선** — `With Iran emboldened` "대체로가" OCR 오타, `TAO-RL` 저자/출처 헤더 추가, `FORMALJUDGE` 머리말 "빠짐없이" 문구 수정, `Prompt Injection`·`FORMALJUDGE` 부록 요약 보강.
5. **[운영] 재발 감시** — `scan.py` 의 레지스터 지표(해라체 문단 수)를 배치 완료 후 자동 게이트로 편입하면, translate-then-restate 와 전체 해라체 회귀를 생성 시점에 잡을 수 있다.

**하지 말 것**: ⑤ 과소해설을 이유로 한 저비율 논문 재생성(원문이 데이터·표 위주라 정당), post-fix 산출물 전면 재생성(이미 CLEAN).

---

## 7. 부록 — 산출물

- 전수 스캔 스크립트: `tmp/explainer_review/scan.py` (레지스터·비율·마커·헤딩커버 지표)
- 재분류: `tmp/explainer_review/reclassify.py`
- 원자료: `tmp/explainer_review/scan_results.json` (508편 전 지표)
- 정독 표본 경로: `tmp/explainer_review/reading_paths.json` (1차 7그룹 35편), `reading_paths_wave2.json` (2차 10그룹 58편)
- 1차 정독 근거: 7개 병렬 리더 — dup_register 6 · dup_adj 3 · tone 4 · hitratio_news_pre 6 · hitratio_news_post 5 · under_paper 6 · over_cliche+korean_biz 10
- 2차 정독 근거: 10개 병렬 리더 — pre_news_1\~8 (각 5편, pre-fix 고비율 뉴스 40편) · post_news_scale 12 · known_bad_recheck 6
- **정독 총 커버리지**: ~90편 (508편의 ~18%), 기준①(중복)은 최대 위험 코호트를 대표 표집

---

## 8. 권고 이행 진행 (2026-07-03, codex 선협의 후)

권고를 순차 이행. 안전 인프라(`tmp/explainer_review/`): `promote.py`(백업 `.md.bak`·manifest JSONL·atomic replace·형식검증·파생물 stale 검출), `gate.py`(멀티지표 게이트).

| 권고 | 상태 | 내역 |
|---|---|---|
| Rec 2 스킬 규칙 | ✅ 완료 | `paper-explainer/SKILL.md` Rule 2에 "해라체 소스→합니다체 전환 강제(직접인용·배너 예외)" + 검증 체크리스트 `hae_p` 게이트 추가 |
| Rec 2b 해라체 4편 | ✅ 완료 | constrained copyedit(문체만 전환, 내용 보존)로 hae_p 57→1·21→1·21→0·8→0. 게이트 PASS/REVIEW |
| Rec 5 품질 게이트 | ✅ 완료 | `gate.py` — hae_p+adj_dup+cliche+media_over+ratio 종합, hae_p는 REVIEW(직접인용 예외). 스모크테스트 통과 |
| Rec 3 116편 계층화 | ✅ 완료 | copyedit 가능 114 / 재생성 필요 2로 분류(`cliche_strata.json`) |
| Rec 1 확정 BAD 재생성 | 🔄 14/15 | 원본 소스에서 새로 작성(기존 해설판 미참조), 전부 게이트 PASS·ratio 정상화(예: Abelardo 3.83→1.58x, American capitalism 3.33→2.03x, How to win WC 2.66→PASS). 남은 1=AIML 다중논문 다이제스트(web 91KB, 특수처리) |
| Rec 4 개별 수선 | 🔄 4/6 | Iran "우회로가" 오타·posh 중복 H2·FORMALJUDGE 문구·TAO-RL 저자헤더 완료. 남음: FORMALJUDGE/Prompt Injection 부록 요약 |

### 이행 최종 상태 (전 권고 완료)

| 권고 | 결과 |
|---|---|
| Rec 1 확정 BAD | **15/15** — 14편 원본 소스에서 재생성(전부 게이트 PASS, ratio 3.8x대→1.5\~2.0x로 정상화), AIML 다이제스트는 문체 copyedit(본문 이미 합니다체 확인) |
| Rec 2 / 2b | 스킬 규칙 추가 + 해라체 4편 문체 전환(hae_p 57/21/21/8 → 1/1/0/0) |
| Rec 3 정형마커 | **87편에서 볼드마커 460개 제거**(잔존 0), 자연 비유사용 27편은 미변경 |
| Rec 4 개별 | Iran 오타·posh 중복 H2·FORMALJUDGE 문구·TAO-RL 헤더 + FORMALJUDGE/Prompt Injection 부록 요약 삽입 |
| Rec 5 게이트 | `gate.py` 완성·가동 |

**최종 전수 스캔(508편)**: DUP_REGISTER/TONE 실질 0(스킬 보정 전 12+4 → 0). 잔존 scan HIGH 4 = 정독에서 **MILD로 판정된 수식 논문 3편**(Chain-of-Thought·Plan Watch Recover·TAO-RL — 의도된 교육적 부연이라 재생성 제외) + AIML(논문 제목 헤딩을 문단으로 오분류한 **스캐너 false-positive**, 본문은 합니다체). 정형 볼드마커 라이브러리 전수 **0개**.

**부수 처리**: ① `Developer's guide…ADK` 폴더의 아포스트로피(straight ' vs curly ’) explainer 중복 2개 → 정본(curly, 소스 일치) 유지, orphan을 backups로 이동. ② 재생성/copyedit로 stale된 `_ko_audio.md` 18건은 manifest 기록 → 오디오 배치가 sidecar freshness로 재생성.

**후속 tooling 개선점(경미)**: `find_source`/`gate.py`/`scan.py` glob이 폴더명 대괄호 `[ ]`를 문자클래스로 오인(`glob.escape` 필요) · `register_paras`가 "…된다"로 끝나는 **논문 제목 헤딩**을 해라체 문단으로 오분류(헤딩 제외 필요) · copyedit 경로 처리가 curly/straight 아포스트로피 정규화 불일치 시 중복 파일 생성 가능.

**산출물**: `tmp/explainer_review/` — `promote.py`·`gate.py`·`strip_marker.py`·`manifest.jsonl`(이행 전건 기록)·`backups/`(원본 백업).
