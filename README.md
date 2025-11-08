# PaperFlow

PDF 논문/문서를 Markdown으로 변환하고 한국어로 번역한 후 HTML로 출력하는 자동화 도구

## ✨ 주요 기능

- 📄 **PDF → Markdown** 변환 (이미지 자동 추출)
- 🌏 **영문 → 한국어** 자동 번역
- 🌐 **HTML** 출력 (깔끔한 웹 문서)
- 🔄 **자동 배치 처리** (여러 PDF 일괄 처리)
- 📝 **로그 기록** (모든 과정 저장)
- 🚀 **GPU/CPU 자동 전환** (메모리 부족 시 자동 대응)

## 🎯 워크플로우

```
PDF (원본)
  ↓ marker-pdf (로컬 라이브러리)
Markdown (영문) + 이미지 추출
  ↓ Ollama (로컬 LLM)
Markdown (한국어)
  ↓ Quarto
HTML (최종 결과물)
```

## 📋 요구사항

### 필수
- **Python 3.12+**
- **Ollama** - 로컬 LLM 서버 ([설치 가이드](https://ollama.com/))
- **Quarto** - 문서 변환 도구 ([설치 가이드](https://quarto.org/docs/get-started/))

### 선택 (성능 향상)
- **CUDA 지원 GPU** - PDF 변환 속도 향상 (없으면 자동으로 CPU 사용)

## 🚀 빠른 시작

### 1. 설치

```bash
# 저장소 클론
git clone <repository-url>
cd PaperFlow

# 가상환경 설정 및 패키지 설치
./setup_venv.sh
```

### 2. Ollama 모델 설치

```bash
# Ollama 서비스 시작
ollama serve

# 번역 모델 다운로드 (다른 터미널에서)
ollama pull qwen3-vl:30b-a3b-instruct
```

### 3. PDF 변환 실행

```bash
# PDF 파일을 newones 폴더에 넣기
cp your_paper.pdf newones/

# 실행
./run_batch_venv.sh
```

### 4. 결과 확인

```bash
# 결과물 확인
ls outputs/your_paper/

# HTML 파일 열기
firefox outputs/your_paper/your_paper_ko.html
```

## 📁 출력 구조

각 PDF당 하나의 폴더가 생성됩니다:

```
outputs/
└── your_paper/
    ├── your_paper.pdf         # 원본 PDF (자동 이동됨)
    ├── your_paper.md          # 영문 마크다운
    ├── your_paper_ko.md       # 한국어 마크다운
    ├── your_paper_ko.html     # 한국어 HTML ⭐
    ├── your_paper.json        # 메타데이터
    └── *.jpeg                 # 추출된 이미지
```

## ⚙️ 설정

### config.json

```json
{
  "ollama_url": "http://localhost:11434",
  "model_name": "qwen3-vl:30b-a3b-instruct",
  "Chunk_size": 5,
  "timeout": 200,
  "retries": 100,
  "retry_delay": 10,
  "temperature": 0.3
}
```

**주요 설정값:**
- `model_name`: Ollama 모델 (추천: `qwen3-vl:30b-a3b-instruct`)
- `Chunk_size`: 번역 청크 크기 (3-5 권장, 10 이상은 비권장)
- `temperature`: 번역 일관성 (0.2-0.4 권장)

### prompt.md

번역 프롬프트를 수정하여 번역 스타일 변경 가능

### header.yaml

HTML 출력 스타일 설정:
- 테마 변경
- 목차 설정
- 코드 블록 스타일 등

## 💡 추천 모델 (번역 품질 순)

1. **qwen3-vl:30b-a3b-instruct** ⭐ 최고 품질, 빠른 속도
2. **gpt-oss:20b** - 빠르고 안정적, 가끔 불완전
3. **qwen3:30b** - 번역 품질 우수, 느림

## 📊 성능 팁

### GPU 메모리
- 자동으로 사용 가능한 메모리 체크
- 4GB 미만이면 자동으로 CPU 모드 전환
- GPU 사용 시 훨씬 빠른 처리

### 번역 품질
- **Chunk Size**: 3-5 (작을수록 빠르지만 맥락 손실 가능)
- **Temperature**: 0.2-0.4 (낮을수록 일관성 증가)
- **큰 모델** 사용 시 품질 향상

### 로그 확인
```bash
# 최신 로그 보기
tail -f logs/paperflow_*.log

# 에러만 보기
grep "✗" logs/paperflow_*.log
```

## 🔍 문제 해결

### Ollama 연결 실패
```bash
# Ollama 서비스 확인
ollama serve

# 모델 확인
ollama list
```

### GPU 메모리 부족
- 자동으로 CPU 모드로 전환됨
- 또는 다른 GPU 프로세스 종료

### Quarto 없음
```bash
# Ubuntu/Debian
sudo apt install quarto

# 또는 공식 사이트에서 설치
# https://quarto.org/docs/get-started/
```

### 번역 실패
- `config.json`의 `timeout`, `retries` 값 증가
- 더 작은 모델 사용
- `Chunk_size` 줄이기

## 📝 로그

모든 실행 로그는 `logs/` 폴더에 타임스탬프와 함께 저장됩니다:
```
logs/paperflow_20251108_141325.log
```

## 🎯 사용 예시

```bash
# 여러 PDF 한번에 처리
cp paper1.pdf paper2.pdf paper3.pdf newones/
./run_batch_venv.sh

# 처리 완료 후 newones는 비어있음 (자동 정리)
ls newones/  # empty

# 모든 결과물은 outputs에
ls outputs/
# paper1/ paper2/ paper3/
```

## 📖 프로젝트 구조

```
PaperFlow/
├── main_terminal.py       # 메인 프로그램
├── run_batch_venv.sh      # 실행 스크립트
├── setup_venv.sh          # 설치 스크립트
├── config.json            # 설정
├── header.yaml            # HTML 포맷
├── prompt.md              # 번역 프롬프트
├── requirements.txt       # Python 패키지
├── newones/               # 입력 폴더
├── outputs/               # 출력 폴더
└── logs/                  # 로그 폴더
```

## 🤝 기여

이슈나 PR은 언제나 환영합니다!

## 📄 라이선스

이 프로젝트는 다음 오픈소스 도구들을 활용합니다:
- [Marker-pdf](https://github.com/datalab-to/marker) - PDF to Markdown
- [Ollama](https://ollama.com/) - Local LLM
- [Quarto](https://quarto.org/) - Document rendering

## 🌟 특징

- ✅ **완전 로컬** - 모든 처리가 로컬에서 진행 (개인정보 보호)
- ✅ **무료** - 유료 API 불필요
- ✅ **자동화** - PDF 넣고 스크립트 실행만 하면 끝
- ✅ **고품질** - 수식, 표, 이미지 모두 보존
- ✅ **배치 처리** - 여러 PDF 동시 처리
- ✅ **로그 기록** - 모든 과정 추적 가능
