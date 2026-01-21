---
lang: ko
format:
  html:
    toc: true
    toc-location: left
    toc-depth: 3
    theme: cosmo
    embed-resources: true
    code-fold: true
    code-tools: true
    smooth-scroll: true
    css: |
      body {
        margin-top: 0 !important;
        padding-top: 0 !important;
      }
      #quarto-header {
        display: none !important;
      }
      .quarto-title-block {
        display: none !important;
      }
      /* Center content with equal padding */
      body, #quarto-content, .content, #quarto-document-content, main, .main {
        max-width: 100% !important;
        width: 100% !important;
        margin: 0 auto !important;
        padding-left: 1em !important;
        padding-right: 1em !important;
        box-sizing: border-box !important;
      }
      .container, .container-fluid, article {
        max-width: 100% !important;
        width: 100% !important;
        margin: 0 auto !important;
        padding-left: 1em !important;
        padding-right: 1em !important;
        box-sizing: border-box !important;
      }
---

# FLEX: 신뢰할 수 있는 Text-to-SQL 벤치마크를 위한 전문가 수준의 거짓 오류 최소화 실행 지표

Heegyu Kim<sup>1</sup>, Taeyang Jeon<sup>1</sup>, Seunghwan Choi<sup>1</sup>, Seungtaek Choi, Hyunsouk Cho<sup>1,2*</sup>

<sup>1</sup>인공지능학과, <sup>2</sup>소프트웨어 및 컴퓨터공학과,
아주대학교, 수원 16499, 대한민국

{khk6435, dnwn3311, dexrf, hyunsouk}@ajou.ac.kr, hist0134@naver.com

#### **초록 (Abstract)**

Text-to-SQL 시스템은 다양한 산업에서 자연어를 SQL 쿼리로 변환하는 데 핵심적인 역할을 하게 되었으며, 비기술 사용자들이 복잡한 데이터 작업을 수행할 수 있게 해준다. 이러한 시스템이 더욱 정교해짐에 따라 정확한 평가 방법의 필요성도 증가하고 있다. 그러나 가장 널리 사용되는 평가 지표인 실행 정확도(Execution Accuracy, EX)는 여전히 많은 거짓 양성(false positive)과 거짓 음성(false negative)을 보인다. 따라서 본 논문에서는 FLEX(False-Less EXecution)를 소개한다. 이는 대규모 언어 모델(LLM)을 활용하여 SQL 쿼리에 대한 인간 전문가 수준의 평가를 모방하는 새로운 text-to-SQL 시스템 평가 접근법이다. 우리의 지표는 포괄적인 맥락과 정교한 기준을 통해 인간 전문가와의 일치도를 향상시킨다(Cohen's kappa 기준 62에서 87.04로 상승). 광범위한 실험을 통해 여러 핵심 통찰을 얻었다: (1) 모델 성능이 평균 2.6점 이상 증가하여 Spider 및 BIRD 벤치마크의 순위에 상당한 영향을 미친다; (2) EX에서의 모델 과소평가는 주로 어노테이션 품질 문제에서 비롯된다; (3) 특히 어려운 질문에서 모델 성능이 과대평가되는 경향이 있다. 본 연구는 text-to-SQL 시스템의 보다 정확하고 세밀한 평가에 기여하며, 이 분야의 최첨단 성능에 대한 우리의 이해를 재정립할 가능성이 있다.

#### 1 서론 (Introduction)

Text-to-SQL 시스템은 자연어 질문을 SQL 쿼리로 변환하는 시스템으로, 데이터 접근을 민주화하고 데이터 기반 의사결정을 촉진함으로써 다양한 산업에서 필수적인 역할을 하게 되었다 (Shi et al., 2024; Hong et al., 2024). 이러한 시스템이 더욱 복잡해짐에 따라 정확하고 효율적인 평가 방법의 중요성이 점점 더 커지고 있다. 초기 평가는 인간 전문가에 의존했지만, 이 접근법은 대규모 평가에 있어 너무 시간 소모적이고 비용이 많이 드는 것으로 판명되었다. 이를 해결하기 위해

<span id="page-0-1"></span>표 1: **FLEX**로 재순위된 BIRD 상위 10개 리더보드. Δ는 과소평가 오류(FLEX – EX)를 나타낸다.

| 순위                 | 모델              | FLEX  | EX    | Δ     |
|----------------------|--------------------|-------|-------|-------|
| 1 ( ↑ 2)  | SuperSQL 🐸         | 64.08 | 57.37 | +6.71 |
| 2 (1)                | CHESS-GPT-4o-mini  | 62.71 | 59.13 | +3.59 |
| 3 ( ↑ 2)  | TA-ACL             | 59.97 | 55.67 | +4.30 |
| 4 ( ↑ 3)  | DAIL_SQL_9-SHOT_MP | 59.26 | 53.52 | +5.74 |
| 5 ( ↑ 4)  | DAIL_SQL_9-SHOT_QM | 58.47 | 53.06 | +5.41 |
| 5 ( ↓ 3)  | DTS-SQL-BIRD-GPT4o | 58.47 | 58.08 | +0.39 |
| 7 ( ↓ 3)  | SFT_CodeS_15B_EK   | 56.98 | 56.52 | +0.46 |
| 8 (↓2)               | SFT_CodeS_7B_EK    | 53.59 | 54.89 | -1.30 |
| 9 (↓1)               | SFT_CodeS_3B_EK    | 53.26 | 53.46 | -0.20 |
| 10 ( ↑ 2) | DAIL_SQL           | 51.83 | 45.89 | +5.93 |

Spider (Yu et al., 2018)와 같은 벤치마크가 실행 정확도(EX) 지표를 도입했으며, 이는 BIRD (Li et al., 2023c)와 같은 다른 벤치마크에서도 널리 채택되었다.

그러나 실행 결과를 기반으로 쿼리를 평가하는 EX 지표는 인간 전문가와의 평가가 괴리되는 상당한 한계를 가지고 있다. 우리의 분석에 따르면 EX는 우연한 데이터베이스 상태로 인해 쿼리를 잘못 검증하거나, 모호한 질문 때문에 올바른 쿼리를 부당하게 패널티를 부과하여 모델이 정확하고 유효한 SQL 쿼리를 생성하는 능력을 잘못 추정한다 (Pourreza and Rafiei, 2023b).

LLM 기반 평가 방법 (Kim et al., 2023; Zheng et al., 2023; Zhao et al., 2024)이 제안되었지만, 제한된 맥락으로 인해 차선의 성능을 보인다. 이러한 방법들은 중요한 맥락 정보를 활용하지 못하고, 노이즈가 있는 정답 문제에 어려움을 겪으며, text-to-SQL 평가에 부적절한 모호한 기준을 사용한다. 결과적으로 확립된 text-to-SQL 벤치마크에서 평가할 때 전통적인 EX 지표보다도 성능이 떨어진다.

이러한 문제를 해결하기 위해 우리는 **FLEX** (**False-Less EXecution**)를 제안한다. 이는 LLM을 활용하여 SQL 쿼리에 대한 전문가 수준의 평가를 모방하는 새로운 접근법이다. **FLEX**는 text-to-SQL 작업 평가를 위해 특별히 설계되었으며

<sup>*</sup> 교신 저자

<span id="page-1-1"></span>![](_page_1_Figure_0.jpeg)

그림 1: Spider 벤치마크에서 EX 대 FLEX 지표의 성능 비교. 빨간색 동일선은 동등한 점수를 나타낸다.

자연어 질문, 데이터베이스 스키마, 외부 지식을 고려하는 포괄적인 맥락 분석을 통해 기존 한계를 극복한다. 또한 쿼리 정확성을 평가하기 위한 상세한 지침과 함께 정교하게 고안된 평가 기준을 활용한다. 우리의 접근법은 FLEX 판단과 인간 전문가 평가 간의 강력한 일관성을 통해 검증되었으며, 기존 EX 지표(62.00)보다 유의하게 높은 일치도(Cohen's kappa 87.04)를 보이고 이전 LLM 기반 방법들을 능가한다.

FLEX의 실질적 영향을 입증하기 위해 Spider 및 BIRD<sup>1</sup> 벤치마크에서 공개적으로 이용 가능한 50개의 text-to-SQL 모델을 재평가하여 여러 핵심 통찰을 도출했다. 표 1에서 볼 수 있듯이, 특히 BIRD에서 모델 순위의 상당한 변화가 나타나 모델 능력에 대한 보다 정확한 평가를 제공한다. 또한 FLEX는 오류 사례를 분류하고 노이즈가 있는 어노테이션이 현재 벤치마크에서 모델 성능을 과소평가하는 주요 요인임을 식별했다. 그림 1에서 볼 수 있듯이, FLEX 점수는 일반적으로 EX 점수보다 높으며, 이는 FLEX가 이전에 과소평가되었던 모델 능력의 측면을 포착함을 시사한다. 더 나아가 FLEX는 BIRD의 어려운 질문에서 모델이 과대평가된다는 것을 감지하여 향후 연구의 초점 영역을 강조한다.

우리의 핵심 기여는 다음과 같다: 1) 현재 text-to-SQL 평가 지표, 특히 실행 정확도(EX) 지표의 주요 한계를 식별하고, 2) 인간 전문가의 추론과 일치하며 전문가 평가와 더 나은 일치도를 보이는

새로운 LLM 기반 평가 방법인 FLEX를 도입한다. 3) FLEX를 사용하여 50개의 text-to-SQL 모델을 재평가함으로써 상당한 순위 변화를 밝히고 벤치마크 및 최첨단 모델에 대한 보다 명확한 이해를 제공하여 고급 평가 방법의 필요성을 강조한다. FLEX 프레임워크는 공개적으로 이용 가능하다<sup>2</sup>.

<span id="page-1-0"></span><sup>1</sup>우리 연구는 BIRD-dev 세트의 20240627 버전을 사용했으며, 수정된 정답으로 인해 이전 연구와 다른 EX 점수를 산출한다.

<span id="page-1-2"></span><sup>2</sup> <https://github.com/HeegyuKim/FLEX>

## 2 관련 연구 (Related Work)

정확 매칭(Exact Matching, EM)과 실행 정확도(Execution Accuracy, EX)는 Spider (Yu et al., 2018)에서 text-to-SQL 시스템을 평가하기 위해 제안되었다. EM은 두 쿼리의 구문 수준 동등성을 평가하지만, 동일한 논리적 의도가 다양한 쿼리 형태로 표현될 수 있기 때문에 높은 거짓 음성률에 취약하다. 따라서 EX는 구문적 형태보다 실행 결과에 초점을 맞추어 BIRD (Li et al., 2023c)에서 쿼리 정확도의 주요 지표로 활용되어 왔다. 이러한 개선에도 불구하고, EX는 여전히 어노테이션 품질 문제로 인한 거짓 음성을 겪으며, 우연히 정답과 동일한 결과를 산출하는 잘못된 쿼리에 보상을 주어 거짓 양성을 생성할 수 있다. 이러한 한계는 더욱 강건한 의미적 평가 접근법의 필요성을 강조한다.

LLM 기반 평가는 자연어 생성 모델에서 인간 선호도를 평가하기 위한 인간 평가자의 대안으로 인기를 얻고 있다. MT-Bench (Zheng et al., 2023) 및 AlpacaEval (Li et al., 2023e)과 같은 프레임워크는 LLM을 판정자로 활용하여 인간 평가보다 더 빠르고 비용 효율적인 평가를 제공한다. 그러나 이러한 프레임워크는 주로 독점적인 GPT-4 (OpenAI et al., 2024)에 의존하며, 제공업체가 예고 없이 모델을 변경하거나 중단할 수 있어 재현성 위험을 초래한다. 이에 대응하여 Kim et al.은 GPT-4 수준의 성능을 제공하는 재현 가능하고 비용이 들지 않는 대안인 오픈소스 LLM 판정자 *Prometheus*를 도입했다. 그럼에도 불구하고 *Prometheus*는 주로 일반적인 인간 선호도 평가에 초점을 맞추고 있으며 text-to-SQL 평가와 같은 특수 작업에는 적합하지 않다. text-to-SQL 평가에 LLM을 특별히 활용하기 위해 Zhao et al.은 *LLM-SQL-Solver*를 제안했다. 거짓 양성과 거짓 음성을 구분하지 않고, 이 접근법은 두 프롬프팅 전략을 사용하여 두 쿼리 간의 실행 동등성을 평가하는 LLM의 능력을 보여준다: 두 쿼리 간의 의미적 동등성을 평가하는 *Miniature-and-Mull*과 LLM에게 중요한 논리적 차이를 비교하도록 요청하는 *Explain-and-Compare*이다.

<span id="page-3-2"></span><sup>3</sup>외부 지식은 BIRD의 *evidence* 필드를 나타내며, text-to-SQL 시스템이 정확하게 예측하도록 지원한다.

그 발전에도 불구하고 *LLM-SQL-Solver*는 평가 지표로서 EX를 완전히 대체하기에는 여전히 불충분하다. 이러한 상세한 한계는 섹션 4.3에서 조사할 것이다.

#### 3 사전 지식 (Preliminaries)

이 섹션에서는 본 논문 전체에 걸쳐 사용되는 표기법과 정의를 소개한다. 다음과 같은 규약을 수립하는 것으로 시작한다: D를 데이터베이스, S를 그 스키마, X를 자연어 질문의 집합이라 하자. 각 질문 $x \in X$에 대해, 지표 평가를 지원하는 맥락 정보 $\mathbb{C}$를 정의한다. 여기에는 질문 x에 대한 정답 SQL 쿼리 $Q_{gt}(x)$와 text-to-SQL 모델이 x에 대해 생성한 SQL 쿼리 $Q_{gen}(x)$가 포함된다. 그런 다음 이러한 쿼리를 데이터베이스 D에서 실행하여 실행 결과 집합을 얻는다. 구체적으로, $R_{gt}(x) = \text{Execute}(Q_{gt}(x), D)$를 정답 쿼리의 결과로, $R_{gen}(x) = \text{Execute}(Q_{gen}(x), D)$를 생성된 쿼리의 결과로 정의한다. 평가 지표 EM, EX, LLM 기반 평가(LX)를 다음과 같이 정의한다:

$$EM = \frac{1}{|X|} \sum_{x \in X} \mathbb{I}\left(Q_{gen}(x) = Q_{gt}(x)\right) \quad (1)$$

$$EX = \frac{1}{|X|} \sum_{x \in X} \mathbb{I}\left(R_{gen}(x) = R_{gt}(x)\right) \quad (2)$$

$$LX = \frac{1}{|X|} \sum_{x \in X} \mathbb{I}\left(x \underset{\mathbb{C}}{\leftrightarrow} Q_{gen}(x)\right)$$
(3)

여기서 $\mathbb{I}(\cdot)$는 괄호 안의 조건이 참이면 1을, 그렇지 않으면 0을 반환하는 지시 함수이다. 표기법 $x \leftrightarrow Q_{gen}(x)$는 생성된 쿼리 $Q_{gen}(x)$가 LLM을 기반으로 맥락 정보 $\mathbb{C}$ 하에서 질문 x와 의미적으로 일치함을 나타낸다.

EM의 경우, 조건은 $Q_{gen}(x)$가 $Q_{gt}(x)$와 구문적으로 정확히 일치하는지 확인한다. EX의 경우, 조건은 $R_{gen}(x)$가 $R_{gt}(x)$와 정확히 일치하는지 확인한다. 그러나 LX는 맥락 정보 하에서 $Q_{gen}(x)$와 질문 x 간의 의미적 일치를 처리한다. $\mathbb{C}$는 평가 방법에 따라 달라질 수 있다. 이러한 지표들은 0과 1 사이의 점수를 생성하며, 1은 완벽한 성능(100% 정확도)을, 0은 완전한 실패(0% 정확도)를 나타낸다.

<span id="page-2-0"></span>표 2: 거짓 양성 / 거짓 음성의 예시.

질문: 누가 가장 높은 점수를 받았나요?

**정답 쿼리**

SELECT fname, lname FROM student

ORDER BY score DESC LIMIT 1

> Emily, Carter

**예시 1: 거짓 양성**

SELECT fname, lname FROM student

WHERE age < 19 # 불필요한 조건.

ORDER BY score DESC LIMIT 1

> Emily, Carter

**예시 2: 거짓 음성**

SELECT lname, fname FROM student

ORDER BY score DESC LIMIT 1

> Carter, Emily # 컬럼 순서가 다름

**예시 3: 거짓 음성**

SELECT fname, lname FROM student

WHERE score == (SELECT MAX (score) FROM student)

> Emily, Carter | Liam, Thompson

# 두 학생이 최고 점수를 가지고 있음.

## 4 현재 Text-to-SQL 평가 방법의 한계 분석

이 섹션에서는 기존 text-to-SQL 평가 지표의 단점을 조사하기 위해 핵심 연구 질문들을 다룬다. 이러한 지표들이 어떤 유형의 오류를 생성하는지 이해하고 LLM이 더 나은 대안을 제공할 수 있는지 탐구하고자 한다.

## <span id="page-2-1"></span>**4.1** Text-to-SQL 평가에서 어떤 유형의 오류가 발생하는가?

현재 평가 방법의 한계를 식별하기 위해, 먼저 실행 정확도(EX) 지표를 사용할 때 발생하는 오류인 거짓 양성(FP)과 거짓 음성(FN)을 표 2를 통해 검토한다.

**거짓 양성** $(x \leftrightarrow Q_{gen}(x), \text{그러나 } R_{gen}(x) = R_{gt}(x))$: 의미적으로 다른 구조나 논리를 가진 생성된 쿼리 $Q_{gen}(x)$가 현재 데이터베이스 상태로 인해 동일한 실행 결과를 생성할 수 있으며, 이는 시스템 성능의 과대평가로 이어진다. 예시 1은 불필요한 조건 age < 19를 포함하지만, 데이터베이스에 18세 이상의 학생이 없기 때문에 우연히 정답과 동일한 결과를 생성한다. 인간과 달리 EX는 생성된 SQL이 자연어 질문의 의도를 정확하게 나타내는지 평가하지 않아, 잘못된 방법으로 올바른 결과를 산출하는 쿼리에 보상을 줄 가능성이 있다.

**거짓 음성** $(x \leftrightarrow Q_{gen}(x), \text{그러나 } R_{gen}(x) \neq R_{gt}(x))$: 자연어 질문을 정확하게 번역한 의미적으로 올바른 쿼리가 정답 쿼리와 다른 결과를 생성할 수 있어, 시스템 능력을 과소평가하게 된다. 이전 연구들 (Pourreza and Rafiei, 2023b; Wretblad et al., 2024)은 어노테이션 품질에 대한 우려를 제기하여 평가 중 거짓 음성을 유발할 수 있다고 보고했다. 그들은 Spider와 BIRD 벤치마크에 많은 어노테이션 문제가 있다고 보고했으며—특정 데이터베이스에서 최대 49%에 달함—이는 모호한 질문과 잘못 어노테이션된 정답을 포함한다.

모호한 질문은 출력 구조에 대한 지시가 제한되어 여러 쿼리로 변환될 수 있다. 예를 들어, *예시 2*는 단순히 컬럼 순서에서 lname이 fname보다 앞에 있다는 이유로 오답으로 표시된다. 평가에서의 이러한 구조적 경직성은 거짓 음성을 유발하여 의미적으로 올바른 쿼리를 간과할 가능성이 있다. 또한 *예시 3*은 노이즈가 있는 정답을 보여주는데, 이는 여러 학생이 동일한 최고 점수를 가질 때 발생할 수 있다. 쿼리는 이 문제를 올바르게 처리하지만 실행 결과가 정답과 다르기 때문에 오답으로 평가된다.

이러한 한계는 신뢰성을 감소시키고 더욱 강건한 text-to-SQL 시스템의 개발을 방해하여, 실제 시나리오에서 실패하는 배포된 시스템으로 이어질 수 있다. 이러한 문제를 해결하기 위해 인간 판단과 더욱 밀접하게 일치하는 평가 방법을 탐구해야 한다.

### 4.2 EX는 인간 전문가 평가와 얼마나 밀접하게 일치하는가?

식별된 오류에 대한 분석을 바탕으로, SQL 쿼리 정확성 평가에서 EX와 인간 전문가 간의 일치도를 평가하기 위해 인간 평가 연구를 수행했다. TA-ACL (Qu et al., 2024)과 SuperSQL (Li et al., 2024a)이 생성한 BIRD 데이터셋에서 200개의 쿼리 쌍을 무작위로 샘플링했다. 샘플은 정답과 동일한 결과를 생성한 쿼리(*동등 집합*)와 다른 결과를 가진 쿼리(*비동등 집합*) 사이에 균등하게 분배되었다. 3년 이상의 경험을 가진 세 명의 SQL 전문가가 이러한 쿼리의 의미적 정확성을 독립적으로 평가했다. 불일치는 합의를 통해 해결되었다. 합의에 도달하기 전, Fleiss' kappa로 측정한 평가자 간 일치도는 79.32로 강한 일치를 나타냈다.

인간 전문가와 EX 간의 일치도를 측정하기 위해 Cohen's kappa와 정확도 점수를 사용했다. 인간 합의와 EX 간의 일치도는 Cohen's kappa 62.0을 산출하여 상당한 일치를 나타내지만 개선의 여지가 많이 남아있으며, 인간 평가자들은 *비동등 집합*에서 21개의 거짓 양성과

<span id="page-3-1"></span>표 3: 인간 합의와 다른 평가 방법 간의 일치도. Acc는 전체 정확도 점수, EQ는 *동등 집합* 정확도 점수, NEQ는 *비동등 집합* 정확도 점수를 나타낸다.

| 모델             | Kappa | Acc  | EQ | NEQ |
|-------------------|-------|------|----|-----|
| EX                | 62.00 | 81.0 | 79 | 83  |
| LLM-SQL-Solver    | 52.29 | 76.5 | 70 | 83  |
| Prometheus-2-7B   | 61.14 | 80.5 | 78 | 83  |
| Prometheus-2-8x7B | 60.66 | 80.0 | 78 | 82  |

*동등 집합*에서 17개의 거짓 음성을 식별했다.

이러한 발견은 EX 지표의 신뢰성에 대한 우려를 제기하고 의미적 정확성을 고려하며 쿼리 정확도에 대한 보다 전문가 수준의 평가를 제공하는 인간 판단을 더 잘 반영하는 평가 방법의 필요성을 강조한다. 부록 C는 이러한 불일치를 보여주는 실제 예시를 제공한다.

## <span id="page-3-0"></span>4.3 LLM이 Text-to-SQL 시스템 평가에서 EX를 대체할 수 있는가?

EX의 한계와 인간 판단과의 불일치를 고려하여, text-to-SQL 시스템 평가의 잠재적 대안으로 LLM을 탐구한다. 따라서 두 가지 LLM 기반 평가 방법을 사용했다: 1) 오픈 LM 판정자인 *Prometheus-2* (Kim et al., 2024), 그리고 2) 독점 LLM을 활용하는 프롬프팅 방법인 GPT-4o (OpenAI et al., 2024)를 사용한 *LLM-SQL-Solver* (Zhao et al., 2024).

**인간 전문가 vs. LLM:** 표 3은 기존 LLM 기반 평가 방법이 EX 성능을 능가하지 못했음을 보여준다. *Prometheus-2*는 Cohen's kappa 61.14로 EX보다 약간 낮은 일치도를 보였으며, *LLM-SQL-Solver*는 플래그십 독점 LLM을 사용했음에도 상당히 낮은 성능을 보였다. 우리는 현재 LLM 기반 평가 방법의 저조한 성능에 기여하는 세 가지 주요 요인을 제안한다:

#### • 제한된 맥락과 노이즈가 있는 정답:
*LLM-SQL-Solver*는 자연어 질문, 외부 지식<sup>3</sup>, 실행 결과를 포함한 맥락 정보 $\mathbb{C}$를 무시한다. 스키마 S 하에서 쿼리 $Q_{gen}(x)$를 $Q_{gt}(x)$와 비교할 뿐이며, $Q_{gen}(x)$가 질문 x를 정확하게 나타내는지는 고려하지 않아 거짓 양성과 거짓 음성을 감지하는 능력이 제한된다. 이 문제는 섹션 4.1에서 논의된 어노테이션 품질 문제로 인해 Spider와 BIRD 벤치마크에서 특히 심각하다.

#### • 모호한 기준:
*LLM-SQL-Solver*는 고급 LLM을 사용해도 명시되지 않은 평가 기준으로 인해 저조한 성능을 보일 수 있다. *Explain-and-Compare* 전략은 "중요한 차이가 있는가?"와 같은 모호한 프롬프트를 사용한다. 마찬가지로 *Prometheus-2*는 1-5 루브릭 점수 체계를 사용하지만, 최적의 루브릭 설계는 휴리스틱하고 모호해지며, 특히 이진 결정(정답과 오답)에서 2와 4 사이의 점수에 대해서는 더욱 그렇다<sup>4</sup>. 우리는 LLM이 더 깊은 추론 단계와 여러 이진 기준을 사용하여 SQL 쿼리를 평가해야 한다고 주장한다; 그렇지 않으면 LLM은 모호한 기준으로 인해 낮은 평가 성능을 보인다.

우리의 연구는 이전 LLM 기반 평가 방법이 text-to-SQL 시스템 평가에서 EX에 비해 불충분함을 경험적으로 입증한다. 이는 현재의 한계를 해결하면서 LLM을 효과적으로 활용하는 더욱 발전된 평가 패러다임의 필요성을 강조한다.

<span id="page-4-0"></span><sup>4</sup>따라서 우리는 가장 높은 일치도 점수를 산출하는 임계값(≥ 4)을 가진 루브릭을 경험적으로 선택했다.

## 5 제안하는 지표: FLEX

![](_page_4_Figure_4.jpeg)

그림 2: 기존 EM 및 EX와 비교하여, FLEX는 전체적이고 맥락적인 정보를 기반으로 질문과 쿼리 간의 의미적 동등성을 평가한다.

이 섹션에서는 제안하는 평가 지표 FLEX(False-Less EXecution)를 소개한다. FLEX는 LLM을 활용하여 생성된 SQL 쿼리에 대해 보다 정확하고 인간과 유사한 평가를 제공함으로써 기존 지표의 한계를 해결한다.

## 5.1 평가 과정

FLEX는 질문, $Q_{gen}(x)$ 및 최적의 맥락 정보

$\mathbb{C}_{FLEX}$로 LLM에 지시한다. 여기에는 질문 x, 생성된 쿼리 $Q_{gen}(x)$, 정답 쿼리 $Q_{gt}(x)$, 실행 결과 $R_{gt}(x)$와 $R_{gen}(x)$, 스키마 S, 외부 지식 K, 그리고 두 기준 $T_{EQ}$와 $T_{NEQ}$<sup>5</sup>가 포함된다. 다시 말해, FLEX는 $R_{gen}(x) = R_{gt}(x)$인지 여부의 EX 결과를 얻은 후 거짓 양성 또는 거짓 음성을 감지하는 데 집중하도록 LLM에 프롬프트한다.

$$\mathbb{C}_{FLEX} = \begin{cases}
\mathbb{C}_{EQ} & \text{if } R_{gen}(x) = R_{gt}(x) \\
\mathbb{C}_{NEQ} & \text{if } R_{gen}(x) \neq R_{gt}(x)
\end{cases}$$

$$\mathbb{C}_{base} = \{x, S, K, Q_{gt}(x), Q_{gen}(x)\}$$

$$\mathbb{C}_{EQ} = \mathbb{C}_{base} \cup \{T_{EQ}\}$$

$$\mathbb{C}_{NEQ} = \mathbb{C}_{base} \cup \{T_{NEQ}, R_{gt}(x), R_{gen}(x)\}$$
(4)

#### 5.2 최적 맥락 ($\mathbb{C}_{FLEX}$)

#### 1) 실행 결과 일치 ($\mathbb{C}_{EQ}$)

$R_{gen}(x) = R_{gt}(x)$인 경우, 거짓 양성—우연이나 잘못된 논리를 통해 올바른 결과를 생성하는 쿼리—의 가능성이 있다. 거짓 양성을 평가하기 위해, 1) $\mathbb{C}_{EQ}$는 $R_{gt}(x)$와 $R_{gen}(x)$를 포함하지 않는다. LLM은 때때로 동등한 실행 결과로 인해 거짓 양성을 정답으로 판단한다. 2) $\mathbb{C}_{EQ}$는 질문과 $Q_{gen}(x)$ 간의 의미적 정확성을 평가하기 위해 다음 기준($T_{EQ}$)을 활용한다:

- **스키마 정렬**: $Q_{gen}(x)$에서 사용된 테이블과 컬럼이 질문 q의 의도와 일치하고 스키마 S와 일관성이 있는지.
- **올바른 필터링 조건**: $Q_{gen}(x)$의 WHERE 절이 질문 x에서 지정된 조건을 정확하게 반영하는지.
- **Nullable 컬럼 처리**: WHERE 절의 집계 함수(SUM, COUNT, AVG)에서 nullable 컬럼을 $Q_{gen}(x)$가 적절히 처리하는지, 부적절한 처리는 예상치 못한 결과를 초래할 수 있으므로.
- **다중 행 고려**: $Q_{gen}(x)$가 일대다 관계 및 다중 min/max 튜플과 같이 쿼리 조건을 만족하는 다중 행의 경우를 올바르게 처리하는지.
- **절 남용**: GROUP BY, HAVING, ORDER BY, DISTINCT와 같은 절이 적절하게 사용되어 의도된 결과를 변경할 수 있는 불필요한 복잡성을 피하는지.

LLM은 $Q_{gen}(x)$와 $Q_{gt}(x)$ 간의 차이를 분석하여 현재 실행 결과에 영향을 미치지 않을 수 있지만

<span id="page-4-1"></span><sup>5</sup>자세한 프롬프트는 부록 F.1에 제공된다.

데이터베이스 상태가 변경되면 잘못된 결과를 초래할 수 있는 논리적 불일치를 감지한다.

#### 2) 실행 결과 불일치 ($\mathbb{C}_{NEQ}$)

$R_{gen}(x) \neq R_{gt}(x)$인 경우에도 질문의 모호성이나 정답 쿼리의 어노테이션 문제로 인해 $Q_{gen}(x)$가 여전히 올바를 수 있다. 이 시나리오에서 $\mathbb{C}_{NEQ}$는 $R_{gt}(x)$, $R_{gen}(x)$, 그리고 다음을 고려하여 질문과 $Q_{gen}(x)$ 간의 의미적 정확성을 평가하도록 설계된 $T_{NEQ}$를 포함한다:

- **허용 가능한 출력 구조 변형**: x의 표현 방식에 따라 출력 구조의 차이(예: 컬럼 순서, 추가 또는 누락된 컬럼)가 허용되는지.
- **값의 표현**: 값 형식의 차이(예: 수치 정밀도, 백분율 표현, YES/NO로서의 불리언 값)가 가독성을 위해 허용되며 의미를 변경하지 않는지.
- **다중 정답 가용성**: x가 여러 유효한 방식으로 해석될 수 있어 각각 다른 올바른 쿼리로 이어질 수 있는지.
- **잘못된 정답**: 정답 쿼리 $Q_{gt}(x)$가 잘못되었거나 차선인 반면 $Q_{gen}(x)$가 질문에 올바르게 답하는지.

따라서 LLM은 모호하거나 불충분하게 명시된 질문으로 인해 필요한 유연성을 고려하고 $Q_{gen}(x)$가 질문의 유효한 번역인지 평가한다. 의미적 정확성에 초점을 맞추고 인간 전문가 판단과 밀접하게 일치함으로써, **FLEX**는 전통적인 실행 기반 지표보다 text-to-SQL 모델의 더 신뢰할 수 있는 평가를 제공한다. 거짓 양성과 거짓 음성 문제를 효과적으로 완화하여 모델 성능에 대한 보다 정확한 평가를 제공한다.

#### 6 실험 (Experiments)

우리의 **FLEX** 접근법의 효과성을 검증하기 위해, LLM 판단과 인간 평가 간의 일치도를 비교하는 포괄적인 연구를 수행했다. 인간 판단과 가장 밀접하게 일치하는 모델을 결정하기 위해 다양한 최첨단 언어 모델을 테스트했다.

#### **6.1** FLEX가 다른 지표보다 우수한가?

그림 3에서 볼 수 있듯이, **FLEX**는 다양한 LLM에서 전통적인 EX 지표보다 일반적으로 우수한 성능을 보이며, GPT-4o가 인간 판단과 가장 높은 일치도를 달성한다. Mistral-small-Instruct-2409 (Jiang et al., 2023)와 같은 오픈소스 모델은

<span id="page-5-0"></span>![](_page_5_Figure_12.jpeg)

그림 3: 시간에 따른 LLM 모델별 인간 평가와 **FLEX** 간의 일치도. **빨간색** 선은 EX 지표 일치도를 나타낸다. 점들은 이전 SOTA보다 낮은 일치도를 보이는 다른 LLM을 나타낸다. 자세한 내용은 그림 8에 설명되어 있다.

EX 지표에 비해 상당한 개선을 보여, 독점 솔루션에 의존하지 않고도 전문가 수준의 평가가 달성 가능함을 나타낸다. LLM 성능은 시간이 지남에 따라 크게 향상되었으며, 최신 모델들이 일반적으로 더 높은 Cohen's Kappa 점수를 보인다. 오픈소스 모델은 GPT-4o와 같은 독점 모델보다 지속적으로 낮은 성능을 보였지만, 꾸준히 발전하며 격차를 좁히고 있다. 예를 들어, DeepSeek-V2-Chat (DeepSeek-AI et al., 2024)은 동시대 독점 LLM인 Claude-3.5-sonnet (Anthropic, 2024)과 근접한 성능을 보인다.

**FLEX**는 시간과 비용 모두에서 상당한 효율성 향상을 제공한다. GPT-4o는 BIRD dev 세트(1,534개 인스턴스)를 약 6달러에 20분 이내에 평가했으며, 자원봉사자들은 200개 인스턴스에 평균 2시간이 필요했다. 이러한 결과는 **FLEX**가 text-to-SQL 작업에서 EX와 인간 평가 모두에 대한 효율적(42배 빠름)이고 비용 효율적인 대안으로서의 실행 가능성을 입증한다. Batch API<sup>6</sup>를 사용하면 입력 처리 비용을 75% 줄일 수 있으며, 더 많은 스레드 수로 **FLEX**의 처리 시간을 단축할 수 있다.

#### **6.2** 어떤 요인이 유익한가?

<span id="page-5-2"></span>표 4: 실행 결과에 따른 인간 일치도 결과 비교.

| $\mathbb{C}_{EQ}$ |              | $\mathbb{C}_{NEQ}$ |                                        | Kappa          | Acc  | EQ | NEQ |
|----------------------------------------------------------------|--------------|----------------------------------------|----------------------------------------|----------------|------|----|-----|
| $\mathbf{R}_{\mathbf{gen}}(\mathbf{x})$ |              | $\mathbf{R_{gen}(x)}$ | $\mathbf{R}_{\mathbf{gt}}(\mathbf{x})$ |           |      |    |     |
| ·                                                              |              | ✓                                      | ✓                                      | 87.04          | 93.5 | 88 | 99  |
|                                                                |              |                                        |                                        | 82.06          | 91.0 | 88 | 94  |
| ✓                                                              | $\checkmark$ | ✓                                      | ✓                                      | 81.08          | 90.5 | 82 | 99  |

최적 맥락 $\mathbb{C}_{FLEX}$와 각 맥락 정보의 효과를 검증하기 위해 절제 연구를 수행했다.

<span id="page-5-1"></span><sup>6</sup>https://platform.openai.com/docs/guides/batch

<span id="page-6-0"></span>표 5: 다른 맥락 정보를 사용한 인간 일치도 결과 비교.

| 절제 설정 | Kappa | Acc  | EQ | NEQ |
|-------------------|-------|------|----|-----|
| 질문 없이      | 80.10 | 90.0 | 84 | 96  |
| 지식 없이     | 79.09 | 89.5 | 82 | 97  |
| 기준 없이      | 74.08 | 87.0 | 81 | 93  |
| 정답 없이  | 29.36 | 64.0 | 72 | 56  |

표 4에서 볼 수 있듯이, $\mathbb{C}_{NEQ}$에만 실행 결과를 포함하면 모든 지표에서 최고 성능을 달성한다. 실행 결과가 $\mathbb{C}_{EQ}$와 $\mathbb{C}_{NEQ}$ 모두에 포함될 때, *동등 집합*(참 양성 + 거짓 양성)에서는 성능이 강하지만 *비동등 집합*(참 양성 + 거짓 음성)에서는 하락한다. 두 맥락 모두에서 실행 결과를 제외하면 반대 경향을 보인다. 실행 결과의 포함은 모델의 오류 감지 능력에 영향을 미친다. 동등한 실행 결과는 생성된 쿼리가 잘못된 논리를 가지고 있더라도 거짓 양성 감지를 방해할 수 있다. 반대로 비동등 쿼리의 경우, 실행 결과를 포함하면 모델이 실행 결과의 사소한 차이를 직접 비교할 수 있어 거짓 음성을 줄이는 데 도움이 된다. 따라서 최적 맥락 선택 접근법은 $Q_{gen}(x)$에 대한 평가를 향상시켜 인간 전문가 평가와 더욱 밀접하게 일치시킨다.

표 5는 평가 맥락에서 다양한 구성 요소를 제거했을 때의 영향을 보여준다. 정답 쿼리와 결과를 제거하는 것이 가장 중요한 요인으로, 모든 지표에서 상당한 성능 하락을 야기한다. 이는 LLM 기반 text-to-SQL 평가에서 신뢰할 수 있는 참조점의 중요성을 강조한다. 자연어 질문이나 외부 지식을 제거해도 주목할 만한 성능 저하가 발생하여 포괄적인 평가 맥락 제공에서의 역할을 강조한다. 평가 기준의 제거도 성능에 영향을 미쳐 잘 정의된 지침의 중요성을 부각한다. 이 절제 연구는 FLEX의 성능이 모든 구성 요소의 시너지에서 비롯되며, 각각이 고품질 text-to-SQL 평가 달성에 중요한 역할을 한다는 것을 입증한다.

#### 7 리더보드 재평가 (Leaderboard Re-evaluation)

이 섹션에서는 FLEX의 강건한 능력을 사용하여 Spider 및 BIRD 벤치마크에서 발표된 결과를 평가했다. 현재 text-to-SQL 평가의 중요한 한계를 입증하기 위해 세 가지 핵심 발견이 관찰되었다. 먼저 실험 설정을 소개하고 세 가지 중요한 한계를 입증한다.

## 7.1 실험 설정

섹션 7.2와 7.4에서는 Spider 및 BIRD 벤치마크 모두에서 공개적으로 이용 가능한 50개 모델 전체를 사용하여 실험을 수행했다. 섹션 7.3에서는 BIRD와 Spider 벤치마크의 상위 10개 모델에서 오류 범주를 조사한다. 우리 연구는 BIRD 벤치마크의 테스트 세트가 공개되지 않았기 때문에 dev 세트를 활용한다. 공정한 비교를 위해 Spider 벤치마크의 dev 세트를 사용했다; 대부분의 연구가 dev 세트의 예측 결과를 발표했다. 인간 평가에서 뛰어난 일치도를 보이는 GPT-4o를 LLM 판정자로 사용했다.

<span id="page-6-2"></span>![](_page_6_Figure_6.jpeg)

그림 4: BIRD 벤치마크에서 EX 대 FLEX 지표의 성능 비교. 빨간색 동일선은 동등한 점수를 나타낸다.

#### <span id="page-6-1"></span>7.2 발견 1: 리더보드 변화

재평가에서 text-to-SQL 모델의 성능 변화는 리더보드에 상당한 변화를 가져온다. EX 지표가 대부분 모델을 과소평가한다는 것을 발견했다. 그림 1과 4에서 볼 수 있듯이, EX에서 FLEX로의 평균 증가는 Spider와 BIRD 벤치마크에서 각각 +2.63과 +2.6이다. 이 결과는 두 벤치마크에서 약 1.7과 2.2의 평균 순위 변화를 야기한다. 구체적으로, 최대 순위 변화는 BIRD에서 5위, Spider에서 8위에 달한다. 이러한 발견은 EX 지표가 모델의 실제 성능을 가리어 부정확한 리더보드 순위를 초래함을 입증한다.

이러한 변화의 정도는 모델 유형에 따라 다르다: 독점 모델, 오픈 사전훈련 언어 모델(open PLMs), 지도 미세조정을 적용한 오픈 언어 모델(open SFT). 그림 5에서 설명된 바와 같이,

<span id="page-7-2"></span>![](_page_7_Figure_0.jpeg)

그림 5: 다양한 모델 유형별 평균 모델 성능과 오류 비율.

독점 모델과 open PLM은 FLEX를 사용하여 재평가할 때 상당한 개선을 보이는 반면, open SFT 모델은 미미한 변화만 보인다. 오류 유형에 대한 면밀한 검토가 이 차이를 설명한다. Open SFT 모델은 독점 모델과 open PLM 모델보다 거짓 음성 비율이 낮다. 반면에 모든 모델 유형은 비교적 유사한 거짓 양성 비율을 보인다.

우리는 이 현상이 훈련 접근법의 차이에 기인할 수 있다고 가정한다. 지도 미세조정 과정은 SFT 모델이 훈련 데이터셋에 있는 것과 구조적으로 유사한 SQL 쿼리를 예측할 수 있게 한다 (Li et al., 2024a). 이러한 유사성은 정답 쿼리와 밀접하게 일치하는 실행 결과를 생성하여 거짓 음성을 줄인다. 반면에 독점 모델과 open PLM 모델은 더 다양한 SQL 쿼리를 생성할 가능성이 높다. 이러한 다양성은 예측된 쿼리와 정답 쿼리의 실행 결과 간의 구조적 차이 가능성을 증가시킨다. 결과적으로 이러한 모델들은 EX 지표 하에서 거짓 음성에 더 취약하며, FLEX는 이를 수정할 수 있다.

#### <span id="page-7-1"></span>7.3 발견 2: 모델이 어노테이션 품질로 인해 과소평가됨

우리 프레임워크<sup>7</sup>의 분류된 오류 요약을 활용하여 text-to-SQL 모델 성능의 과소평가를 초래하는 거짓 음성의 원인을 분석한다. 그림 6에서 볼 수 있듯이, 거짓 음성의 주요 원인은 다른 출력 구조(Struct)와 잘못된 정답(GT)이다. 질문의 고유한 모호성은 여러 가능한 답을 허용하여 다른 출력 구조로 인한 많은 거짓 음성을 초래한다(BIRD에서 58.13%). 잘못된 정답 SQL 쿼리도 거짓 음성의 상당 부분을 차지한다

<span id="page-7-4"></span>![](_page_7_Figure_7.jpeg)

그림 6: 상위 10개 모델의 FN 비율 분류 결과. Struct는 허용 가능한 출력 구조 변형, Value는 다른 값 표현, GT는 잘못된 정답, Multiple Ans는 다중 정답 가용성을 나타낸다.

(BIRD에서 54.54%). 이러한 결과는 이전 연구 (Wang et al., 2023a; Wretblad et al., 2024)의 관찰을 뒷받침하며, 이 한계가 최첨단 모델에서도 여전히 해결되지 않았음을 보여준다.

## <span id="page-7-0"></span>7.4 발견 3: 어려운 질문에서 모델이 과대평가됨

<span id="page-7-5"></span>![](_page_7_Figure_11.jpeg)

그림 7: 난이도 수준별 모델의 평균 FP 및 FN 비율. y축은 백분율(%)을 나타낸다. Spider에서는 질문이 더 어려워질수록 text-to-SQL 모델이 과소평가되는 경향이 있다. 반대로 BIRD에서는 더 어려운 질문에서 모델이 과대평가된다.

우리 연구는 text-to-SQL 모델이 BIRD의 어려운 질문에서 EX보다 낮은 FLEX 점수를 보이는 반면 쉬운 질문에서는 더 높음을 밝혀낸다. 이러한 불일치는 그림 7에 설명된 거짓 양성 및 거짓 음성 비율 분석을 통해 설명할 수 있다. BIRD보다 덜 복잡하다고 여겨지는 Spider에서는 text-to-SQL 모델의 거짓 양성 비율이 거짓 음성 비율보다 일관되게 낮아 text-to-SQL 모델이 EX보다 높은 FLEX를 보인다. 이 경향은 BIRD의 간단하고 중간 수준의 질문에서도 지속된다. 그러나 BIRD의 어려운 질문에서는 거짓 양성 비율이 거짓 음성 비율을 초과하여

<span id="page-7-3"></span><sup>7</sup>자세한 과정은 부록 B.3에 제공된다.

모델 성능의 하락을 초래한다. 이러한 결과는 text-to-SQL 평가에서 거짓 양성과 거짓 음성의 상당한 영향을 강조한다.

### 8 토론 (Discussion)

FLEX는 LLM 기반 text-to-SQL 평가에서 유망한 결과를 보여주지만, 주로 불충분한 맥락 정보로 인해 한계에 직면한다. LLM 기반 평가의 정확도를 향상시키기 위해, 향후 text-to-SQL 벤치마크는 질문당 다중 정답 쿼리, 더 포괄적인 스키마 세부 정보, 데이터베이스 관계 및 제약 조건에 관한 추가 맥락을 통합해야 한다. GPT-4o는 인간-AI 일치도에서 잠재적 편향을 보인다. 향후 이 문제를 해결하기 위해, LLM 판정자 앙상블 사용과 같은 고급 프롬프팅 기법 구현을 제안한다. 이러한 전략은 개별 모델 편향을 완화하고 LLM 기반 평가의 전반적인 신뢰성과 공정성을 향상시키는 것을 목표로 한다. 인간 전문가 피드백을 기반으로 한 평가 과정의 지속적인 미세조정은 시간이 지남에 따라 시스템 성능을 유지하고 개선하는 데 중요하다.

FLEX는 GPT-4와 같은 독점 모델과 CodeS (Li et al., 2024b) 및 RES-DSQL (Li et al., 2023a)과 같은 오픈 대안 간의 상당한 성능 격차를 밝혀냈다. 독점 모델이 우수한 성능을 보이지만, 실제 text-to-SQL 애플리케이션에서의 사용은 특히 데이터 오염 (Ranaldi et al., 2024)에 관한 우려를 제기한다. FLEX는 다양하고 고품질의 데이터 증강에 활용될 수 있어 잠재적으로 오픈 SFT 모델을 향상시킬 수 있다. 이는 오픈소스와 독점 모델 간의 성능 격차를 좁히고 text-to-SQL 번역 분야를 발전시킬 것이다.

#### 9 결론 (Conclusion)

본 논문에서 우리는 text-to-SQL 평가의 한계, 특히 거짓 양성과 거짓 음성에 취약한 EX 지표가 부정확한 모델 평가를 초래할 수 있음을 발견했다. LLM 기반 평가가 인간 평가자의 대안으로 등장했지만, 여전히 여러 한계를 드러낸다. 이를 극복하기 위해 우리는 새로운 지표 FLEX(False-Less EXecution)를 도입한다. 이는 포괄적인 맥락과 LLM의 고급 언어 이해를 기반으로 한 정교한 기준을 활용하여 보다 전문가 수준의 평가를 달성한다. 우리의 포괄적인 실험은 제안된 지표의 효과성을 보여주며 text-to-SQL 평가에 대한 향후 연구를 촉진하는 여러 경험적 발견을 제공한다.

## 10 한계 (Limitations)

우리의 FLEX 평가 접근법은 실행 정확도(EX)와 같은 전통적인 지표에 비해 상당한 개선을 제공하지만, 주목할 몇 가지 한계가 있다: FLEX는 Cohen's kappa 87.04로 강한 일치도를 보이지만 완벽하지 않으며, 고급 추론 (Wang et al., 2022; Madaan et al., 2024)이나 LLM 평가자의 미세조정 (Wang et al., 2023b; Zhu et al., 2023)을 통해 더욱 개선될 수 있다. 우리의 평가는 현재 Spider와 BIRD 벤치마크에 제한되어 있어 FLEX의 효과성을 완전히 검증하기 위해서는 다른 text-to-SQL 데이터셋과 실제 기업 데이터베이스에서의 추가 테스트가 필요하다. FLEX의 LLM 의존성은 계산 집약적이고 단순한 실행 기반 지표보다 시간이 더 소요되어 수백만 규모의 평가에서 확장성을 제한할 수 있다. 더불어 독점 LLM은 제공업체가 예고 없이 모델을 변경하거나 중단할 수 있어 재현성 위험을 초래한다. FLEX는 보다 포괄적인 평가를 제공하지만, 특히 중요한 애플리케이션에서 인간 검토의 필요성을 완전히 제거하지는 않는다. 이러한 한계를 해결하는 것은 text-to-SQL 시스템을 위한 LLM 기반 평가 접근법을 더욱 정교화하고 확장할 수 있는 향후 연구의 기회를 제시한다.

## 감사의 글 (Acknowledgements)

본 연구는 한국 정부(과학기술정보통신부) 지원을 받은 정보통신기획평가원(IITP) 과제(No. 2022-0-00680, 복잡한 인과 관계 이해를 위한 전방위 데이터 활용 귀추적 추론 프레임워크), 과학기술정보통신부 지원을 받은 국가연구재단(NRF) 국가 R&D 프로그램(RS-2024-00407282 및 RS-2024-00444182), 그리고 한국 정부(과학기술정보통신부) 지원을 받은 인공지능 융합혁신 인재양성 프로그램(IITP-2025-RS-2023-00255968)의 지원을 받았다.

## 참고문헌 (References)

- <span id="page-9-12"></span>Josh Achiam, Steven Adler, Sandhini Agarwal, Lama Ahmad, Ilge Akkaya, Florencia Leoni Aleman, Diogo Almeida, Janko Altenschmidt, Sam Altman, Shyamal Anadkat, et al. 2023. [Gpt-4 technical report.](https://arxiv.org/abs/2303.08774) *arXiv preprint arXiv:2303.08774*.
- <span id="page-9-7"></span>Anthropic. 2024. [Introducing claude 3.5 sonnet.](https://www.anthropic.com/news/claude-3-5-sonnet)
- <span id="page-9-17"></span>Jinze Bai, Shuai Bai, Yunfei Chu, Zeyu Cui, Kai Dang, Xiaodong Deng, Yang Fan, Wenbin Ge, Yu Han, Fei Huang, Binyuan Hui, and et al. Luo Ji. 2023. Qwen technical report. *arXiv preprint arXiv:2309.16609*.
- <span id="page-9-19"></span>Cohere For AI. 2024. [c4ai-command-r-plus-08-2024.](https://doi.org/10.57967/hf/3135)
- <span id="page-9-6"></span>DeepSeek-AI, Aixin Liu, Bei Feng, Bin Wang, Bingxuan Wang, Bo Liu, Chenggang Zhao, Chengqi Dengr, Chong Ruan, Damai Dai, Daya Guo, Dejian Yang, et al. 2024. [Deepseek-v2: A strong, economical, and efficient mixture-of-experts language model.](https://arxiv.org/abs/2405.04434) *Preprint*, arXiv:2405.04434.
- <span id="page-9-20"></span>Xuemei Dong, Chao Zhang, Yuhang Ge, Yuren Mao, Yunjun Gao, Jinshu Lin, Dongfang Lou, et al. 2023. [C3: Zero-shot text-to-sql with chatgpt.](https://arxiv.org/abs/2302.05965) *arXiv preprint arXiv:2307.07306*.
- <span id="page-9-14"></span>Abhimanyu Dubey, Abhinav Jauhri, Abhinav Pandey, Abhishek Kadian, Ahmad Al-Dahle, Aiesha Letman, Akhil Mathur, Alan Schelten, Amy Yang, Angela Fan, Anirudh Goyal, Anthony Hartshorn, and Aobo Yang et al. 2024. [The llama 3 herd of models.](https://arxiv.org/abs/2407.21783) *Preprint*, arXiv:2407.21783.
- <span id="page-9-11"></span>Dawei Gao, Haibin Wang, Yaliang Li, Xiuyu Sun, Yichen Qian, Bolin Ding, and Jingren Zhou. 2023. Text-to-sql empowered by large language models: A benchmark evaluation. *arXiv preprint arXiv:2308.15363*.
- <span id="page-9-13"></span>Gemini Team, et al. 2024. [Gemini 1.5: Unlocking multimodal understanding across millions of tokens of context.](https://arxiv.org/abs/2403.05530) *Preprint*, arXiv:2403.05530.
- <span id="page-9-16"></span>Gemma Team, et al. 2024. [Gemma: Open models based on gemini research and technology.](https://arxiv.org/abs/2403.08295) *Preprint*, arXiv:2403.08295.
- <span id="page-9-18"></span>Daya Guo, Qihao Zhu, Dejian Yang, Zhenda Xie, Kai Dong, Wentao Zhang, Guanting Chen, Xiao Bi, Y. Wu, Y. K. Li, Fuli Luo, Yingfei Xiong, and Wenfeng Liang. 2024. [Deepseek-coder: When the large language model meets programming – the rise of code intelligence.](https://arxiv.org/abs/2401.14196) *Preprint*, arXiv:2401.14196.
- <span id="page-9-0"></span>Zijin Hong, Zheng Yuan, Qinggang Zhang, Hao Chen, Junnan Dong, Feiran Huang, and Xiao Huang. 2024. [Next-generation database interfaces: A survey of llm-based text-to-sql.](https://arxiv.org/abs/2406.08426) *Preprint*, arXiv:2406.08426.
- <span id="page-9-15"></span>Albert Q. Jiang, et al. 2024. [Mixtral of experts.](https://arxiv.org/abs/2401.04088)
- <span id="page-9-5"></span>AQ Jiang, A Sablayrolles, A Mensch, C Bamford, DS Chaplot, D de las Casas, F Bressand, G Lengyel, G Lample, L Saulnier, et al. 2023. Mistral 7b (2023). *arXiv preprint arXiv:2310.06825*.
- <span id="page-9-4"></span>Seungone Kim, Jamin Shin, Yejin Cho, Joel Jang, Shayne Longpre, Hwaran Lee, Sangdoo Yun, Seongjin Shin, Sungdong Kim, James Thorne, and Minjoon Seo. 2024. [Prometheus: Inducing fine-grained evaluation capability in language models.](https://arxiv.org/abs/2310.08491) *Preprint*, arXiv:2310.08491.
- <span id="page-9-2"></span>Seungone Kim, et al. 2023. Prometheus: Inducing fine-grained evaluation capability in language models. In *The Twelfth International Conference on Learning Representations*.
- <span id="page-9-10"></span>Woosuk Kwon, et al. 2023. Efficient memory management for large language model serving with pagedattention. In *Proceedings of the ACM SIGOPS 29th Symposium on Operating Systems Principles*.
- <span id="page-9-3"></span>Boyan Li, Yuyu Luo, Chengliang Chai, Guoliang Li, and Nan Tang. 2024a. [The dawn of natural language to sql: Are we fully ready?](https://arxiv.org/abs/2406.01265) *Preprint*, arXiv:2406.01265.
- <span id="page-9-9"></span>Haoyang Li, Jing Zhang, Cuiping Li, and Hong Chen. 2023a. [Resdsql: Decoupling schema linking and skeleton parsing for text-to-sql.](https://arxiv.org/abs/2302.05965) *Preprint*, arXiv:2302.05965.
- <span id="page-9-8"></span>Haoyang Li, et al. 2024b. [Codes: Towards building open-source language models for text-to-sql.](https://arxiv.org/abs/2402.16347) *Proceedings of the ACM on Management of Data*, 2(3):1–28.
- <span id="page-9-21"></span>Jinyang Li, et al. 2023b. Graphix-t5: Mixing pretrained transformers with graph-aware layers for text-to-sql parsing. In *Proceedings of the AAAI Conference on Artificial Intelligence*, volume 37, pages 13076–13084.
- <span id="page-9-1"></span>Jinyang Li, Binyuan Hui, Ge Qu, et al. 2023c. [Can llm already serve as a database interface? a big bench for large-scale database grounded text-to-sqls.](https://arxiv.org/abs/2305.03111) *arXiv:2305.03111*.
- <span id="page-10-18"></span>Raymond Li, et al. 2023d. [Starcoder: may the source be with you!](https://arxiv.org/abs/2305.06161) *Preprint*, arXiv:2305.06161.
- <span id="page-10-3"></span>Xuechen Li, et al. 2023e. Alpacaeval: An automatic evaluator of instruction-following models. [https://github.com/tatsu-lab/alpaca_eval](https://github.com/tatsu-lab/alpaca_eval).
- <span id="page-10-10"></span>Aman Madaan, et al. 2024. Self-refine: Iterative refinement with self-feedback. *Advances in Neural Information Processing Systems*, 36.
- <span id="page-10-4"></span>OpenAI, Josh Achiam, et al. 2024. [Gpt-4 technical report.](https://arxiv.org/abs/2303.08774) *Preprint*, arXiv:2303.08774.
- <span id="page-10-15"></span>Mohammadreza Pourreza and Davood Rafiei. 2023a. [DIN-SQL: Decomposed in-context learning of text-to-SQL with self-correction.](https://openreview.net/forum?id=p53QDxSIc5) In *Thirty-seventh Conference on Neural Information Processing Systems*.
- <span id="page-10-2"></span>Mohammadreza Pourreza and Davood Rafiei. 2023b. [Evaluating cross-domain text-to-sql models and benchmarks.](https://arxiv.org/abs/2310.18538) *arXiv preprint arXiv:2310.18538*.
- <span id="page-10-19"></span>Mohammadreza Pourreza and Davood Rafiei. 2024. [Dts-sql: Decomposed text-to-sql with small large language models.](https://arxiv.org/abs/2402.01117) *Preprint*, arXiv:2402.01117.
- <span id="page-10-6"></span>Ge Qu, et al. 2024. [Before generation, align it! a novel and effective strategy for mitigating hallucinations in text-to-sql generation.](https://arxiv.org/abs/2405.15307) *Preprint*, arXiv:2405.15307.
- <span id="page-10-14"></span>Qwen Team. 2024. [Qwen2.5: A party of foundation models.](https://qwenlm.github.io/blog/qwen2.5/)
- <span id="page-10-8"></span>Federico Ranaldi, et al. 2024. Investigating the impact of data contamination of large language models in text-to-sql translation. *arXiv preprint arXiv:2402.08100*.
- <span id="page-10-17"></span>Baptiste Rozière, et al. 2024. [Code llama: Open foundation models for code.](https://arxiv.org/abs/2308.12950) *Preprint*, arXiv:2308.12950.
- <span id="page-10-0"></span>Liang Shi, Zhengju Tang, and Zhi Yang. 2024. [A survey on employing large language models for text-to-sql tasks.](https://arxiv.org/abs/2407.15186) *arXiv preprint arXiv:2407.15186*.
- <span id="page-10-20"></span>Shayan Talaei, et al. 2024. [Chess: Contextual harnessing for efficient sql synthesis.](https://doi.org/10.48550/ARXIV.2405.16755) *arXiv preprint*.
- <span id="page-10-16"></span>Hugo Touvron, et al. 2023. [Llama 2: Open foundation and fine-tuned chat models.](https://arxiv.org/abs/2307.09288) *Preprint*, arXiv:2307.09288.
- <span id="page-10-7"></span>Bing Wang, Yan Gao, Zhoujun Li, and Jian-Guang Lou. 2023a. Know what i don't know: Handling ambiguous and unknown questions for text-to-sql. In *Findings of the Association for Computational Linguistics: ACL 2023*, pages 5701–5714.
- <span id="page-10-9"></span>Xuezhi Wang, et al. 2022. Self-consistency improves chain of thought reasoning in language models. *arXiv preprint arXiv:2203.11171*.
- <span id="page-10-11"></span>Yidong Wang, et al. 2023b. Pandalm: An automatic evaluation benchmark for llm instruction tuning optimization. *arXiv preprint arXiv:2306.05087*.
- <span id="page-10-21"></span>Jason Wei, et al. 2022. Chain-of-thought prompting elicits reasoning in large language models. *Advances in neural information processing systems*, 35:24824–24837.
- <span id="page-10-12"></span>Thomas Wolf, et al. 2020. [Transformers: State-of-the-art natural language processing.](https://www.aclweb.org/anthology/2020.emnlp-demos.6) In *Proceedings of the 2020 Conference on Empirical Methods in Natural Language Processing: System Demonstrations*, pages 38–45.
- <span id="page-10-5"></span>Niklas Wretblad, et al. 2024. [Understanding the effects of noise in text-to-sql: An examination of the bird-bench benchmark.](https://arxiv.org/abs/2402.12243) *arXiv preprint arXiv:2402.12243*.
- <span id="page-10-13"></span>An Yang, et al. 2024. Qwen2 technical report. *arXiv preprint arXiv:2407.10671*.
- <span id="page-10-1"></span>Tao Yu, et al. 2018. [Spider: A large-scale human-labeled dataset for complex and cross-domain semantic parsing and text-to-sql task.](https://doi.org/10.48550/ARXIV.1809.08887) *arXiv:1809.08887*.
- <span id="page-11-1"></span>Fuheng Zhao, et al. 2024. [Llm-sql-solver: Can llms determine sql equivalence?](https://arxiv.org/abs/2312.10321) *Preprint*, arXiv:2312.10321.
- <span id="page-11-0"></span>Lianmin Zheng, et al. 2023. [Judging llm-as-a-judge with mt-bench and chatbot arena.](https://arxiv.org/abs/2306.05685) *Preprint*, arXiv:2306.05685.
- <span id="page-11-2"></span>Lianghui Zhu, Xinggang Wang, and Xinlong Wang. 2023. Judgelm: Fine-tuned large language models are scalable judges. *arXiv preprint arXiv:2310.17631*.

## 부록 (Appendix)

### A 실험 설정 (Experiment Setting)

#### A.1 프레임워크 및 하드웨어 (Frameworks and Hardware)

We utilized NVIDIA A6000x4 GPUs with Huggingface transformers (Wolf et al., 2020) and VLLM (Kwon et al., 2023) for generating outputs from open LLMs. To evaluate open models larger than 30B, we utilize the [Huggingface Inference API](https://huggingface.co/docs/api-inference/index), [TogetherAI Inference](https://www.together.ai/), and [AI/ML API](https://aimlapi.com/).

#### A.2 생성 하이퍼파라미터 (Generation Hyperparameter)

We set the temperature to 0 in every experiment to ensure consistent results for each attempt and the maximum number of tokens to 2,048.

#### A.3 LLM 프롬프트에서의 실행 결과 (Execution Results in the LLM Prompt)

The execution results in the LLM prompt were converted to a markdown table. However, the SQL query can produce extensive rows, increasing the prompt length and API costs. To reduce the overhead, we truncated the middle of the table with a mark as '...' and left 50 heads and tails for more than 100 rows. The shape of the table is appended to the markdown table to help LLM's judgment. Some TEXT-type columns can also be longer. After the 50 characters, we truncated them and appended '*... k chars*', where k indicates an original number of characters.

#### A.4 예측 결과 출처 (Source of Prediction Results)

The prediction results were obtained from various sources, including NL2SQL360 (Li et al., 2024a) frameworks, published studies, and reproduced predictions.

#### A.5 인간 평가자 (Human Annotators)

Three of the authors are annotators. They have taken database classes at the university and have more than three years of experience operating the database system.

## B 추가 실험 결과 (Additional Experiment Result)

### B.1 다양한 LLM에서의 FLEX 인간 일치도 (FLEX Human Agreement across Various LLMs)

<span id="page-12-0"></span>![](_page_12_Figure_15.jpeg)

그림 8: 인간 평가와 LLM 모델별 FLEX 간의 일치도 상세 결과. 빨간색 선은 EX 지표의 일치도를 나타낸다. "-I"는 instruction-tuned 모델을 나타낸다.

For proprietary models, we employed OpenAI's GPT models (Achiam et al., 2023; OpenAI et al., 2024), Anthropic's Claude models (Anthropic, 2024), and Google's Gemini models (Gemini Team et al., 2024).

For open LMs, we employed Meta's Llama-3 and Llama-3.1 models (Dubey et al., 2024), MistralAI's models (Jiang et al., 2023, 2024), Google's Gemma-2 models (Gemma Team et al., 2024), Qwen-1.5 (Bai et al., 2023), Qwen-2 (Yang et al., 2024) and Qwen-2.5 models (Qwen Team, 2024), DeepSeek AI's DeepSeek-V2 (DeepSeek-AI et al., 2024) and DeepSeek-Coder (Guo et al., 2024), Cohere's Command-R (Cohere For AI, 2024).

#### B.2 전체 FLEX 결과 (Full FLEX results)

표 8: Spider 전체 결과

| 순위                 | 모델                        | FLEX  | EX    | Δ      |
|----------------------|------------------------------|-------|-------|--------|
| 1 (-)                | SuperSQL                     | 91.20 | 87.04 | +4.16  |
| 2 ( ↑ 7)              | DINSQL                       | 91.10 | 82.79 | +8.32  |
| 3 ( ↑ 3)              | DAILSQL_SC                   | 90.14 | 83.56 | +6.58  |
| 4 ( ↑ 4)              | DAILSQL                      | 88.88 | 83.08 | +5.80  |
| 5 ( ↑ 2)              | TA-ACL                       | 88.78 | 85.01 | +3.77  |
| 6 (↓4)               | SFT_CodeS_7B                 | 87.91 | 85.40 | +2.51  |
| 7 (↓1)               | SFT_CodeS_15B                | 87.33 | 84.91 | +2.42  |
| 8 ( ↑ 2)              | C3_SQL                       | 87.04 | 82.01 | +5.03  |
| 9 ( ↑ 5)              | SFT_Deepseek_Coder_7B        | 84.72 | 80.75 | +3.97  |
| 10 (↓2)              | SFT_CodeS_3B                 | 84.72 | 83.27 | +1.45  |

표 9: BIRD 전체 결과

| 순위                 | 모델                      | FLEX  | EX    | Δ     |
|----------------------|----------------------------|-------|-------|-------|
| 1 (↑2)               | SuperSQL                   | 64.08 | 57.37 | +6.71 |
| 2 (↓1)                | CHESS-GPT-4o-mini          | 62.71 | 59.13 | +3.59 |
| 3 ( ↑ 2)              | TA-ACL                     | 59.97 | 55.67 | +4.30 |
| 4 ( ↑ 3)              | DAIL_SQL_9-SHOT_MP         | 59.26 | 53.52 | +5.74 |
| 5 ( ↑ 4)              | DAIL_SQL_9-SHOT_QM         | 58.47 | 53.06 | +5.41 |
| 5 (↓3)              | DTS-SQL-BIRD-GPT4o-0823    | 58.47 | 58.08 | +0.39 |
| 7 (↓3)              | SFT_CodeS_15B_EK           | 56.98 | 56.52 | +0.46 |
| 8 (↓2)               | SFT_CodeS_7B_EK            | 53.59 | 54.89 | -1.30 |
| 9 (↓1)               | SFT_CodeS_3B_EK            | 53.26 | 53.46 | -0.20 |
| 10 ( ↑ 2)             | DAIL_SQL                   | 51.83 | 45.89 | +5.93 |

#### <span id="page-12-1"></span>B.3 FP 및 TN 오류 분석 (FP and TN Error Analysis)

We generate a comprehensive evaluation report after obtaining judgments for all generated queries in a dataset. This report includes an overall accuracy analysis.

