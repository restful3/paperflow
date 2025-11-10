# PaperFlow

PDF 논문/문서를 Markdown으로 변환하고 한국어로 번역한 후 HTML로 출력하는 자동화 도구

## ✨ 주요 기능

### 📄 PDF 처리
- **PDF → Markdown** 변환 (이미지 자동 추출)
- **영문 → 한국어** 자동 번역
- **HTML** 출력 (깔끔한 웹 문서)
- **자동 배치 처리** (여러 PDF 일괄 처리)
- **GPU/CPU 자동 전환** (메모리 부족 시 자동 대응)

### 🖥️ 웹 뷰어 (Streamlit)
- **논문 관리**: 읽을 논문 / 읽은 논문 탭 분리
- **다중 포맷 지원**: 한국어(HTML), 영어(PDF), 영어(Markdown)
- **분할 보기**: 한국어 + 영어 동시 비교
- **PDF 목차**: 북마크 자동 추출 및 네비게이션
- **마크다운 편집**: YAML 헤더 보존하며 실시간 편집
- **논문 아카이브**: 읽은 논문 자동 분류 및 관리
- **다운로드**: PDF 파일 다운로드 지원
- **세션 유지**: 자동 로그인 기능

### 📝 기타
- **로그 기록** (모든 과정 저장)
- **완전 로컬** (개인정보 보호)

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

### Python 패키지 (자동 설치)
- `marker-pdf>=0.2.17` - PDF to Markdown 변환
- `streamlit>=1.28.0` - 웹 뷰어
- `pypdf2>=3.0.0` - PDF 목차 추출
- `torch>=2.0.0` - GPU 가속
- 기타 (requirements.txt 참조)

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

#### 방법 1: 일회성 배치 처리
```bash
# PDF 파일을 newones 폴더에 넣기
cp your_paper.pdf newones/

# 실행 (한번만 처리)
./run_batch.sh
```

#### 방법 2: Watch 모드 (자동 감시) ⭐ 권장
```bash
# Watch 모드 실행 (계속 실행되며 자동 처리)
./run_batch_watch.sh

# 다른 터미널에서 PDF 추가
cp your_paper.pdf newones/
# → 자동으로 감지되어 처리 시작

# 종료: Ctrl+C
```

### 4. 결과 확인

**방법 1: Streamlit 웹 뷰어 사용 (권장) ⭐**
```bash
# Streamlit 뷰어 실행
./run_app.sh

# 브라우저가 자동으로 열림 (http://localhost:8501)
```

**웹 뷰어 주요 기능:**
- 📚 **논문 목록**: 카드 형식으로 깔끔하게 표시
- 📑 **탭 관리**:
  - "읽을 논문" - 새로 변환된 논문들
  - "읽은 논문" - 아카이브된 논문들
- 📖 **다중 보기 모드**:
  - 한국어(HTML) - 번역본
  - 영어(PDF) - 원본 (목차 네비게이션 지원)
  - 영어(Markdown) - 편집 가능한 텍스트
  - 분할 보기 - 한국어 + 영어 동시 비교
- ⚙️ **사이드바 컨트롤**:
  - PDF: 파일 정보, 다운로드, 목차 표시
  - Markdown: 편집 모드 토글
  - 폰트 크기 조절 (HTML)
  - 화면 비율 조절 (분할 보기)
- ✏️ **마크다운 편집**:
  - 실시간 편집 및 저장
  - YAML 헤더 자동 보존
- 📦 **논문 관리**:
  - "✅ 완료" - 읽은 논문으로 이동
  - "↩️ 복원" - 읽을 논문으로 복원
  - "🗑️ 삭제" - 영구 삭제 (확인 필요)

**방법 2: 파일로 직접 열기**
```bash
# 결과물 확인
ls outputs/your_paper/

# HTML 파일 열기
firefox outputs/your_paper/your_paper_ko.html
```

## 📁 출력 구조

각 PDF당 하나의 폴더가 생성됩니다:

```
outputs/                      # 읽을 논문 (처리 완료된 논문)
└── your_paper/
    ├── your_paper.pdf         # 원본 PDF (자동 이동됨)
    ├── your_paper.md          # 영문 마크다운
    ├── your_paper_ko.md       # 한국어 마크다운
    ├── your_paper_ko.html     # 한국어 HTML ⭐
    ├── your_paper.json        # 메타데이터
    └── *.jpeg                 # 추출된 이미지

archives/                     # 읽은 논문 (아카이브)
└── your_paper/               # "완료" 버튼으로 이동된 논문
    └── (동일한 구조)
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

### 일회성 배치 처리
```bash
# 여러 PDF 한번에 처리
cp paper1.pdf paper2.pdf paper3.pdf newones/
./run_batch.sh

# 처리 완료 후 newones는 비어있음 (자동 정리)
ls newones/  # empty

# 모든 결과물은 outputs에
ls outputs/
# paper1/ paper2/ paper3/
```

### Watch 모드 (연속 처리) ⭐
```bash
# 터미널 1: Watch 모드 실행
./run_batch_watch.sh
# → "Watching for new PDF files in 'newones'..." 메시지 표시

# 터미널 2: PDF를 계속 추가
cp paper1.pdf newones/  # → 자동 처리 시작
# 처리 완료 대기...
cp paper2.pdf newones/  # → 다시 자동 처리
cp paper3.pdf newones/  # → 계속 처리

# Watch 모드는 계속 실행되며 새 파일을 기다림
# 종료하려면 Ctrl+C
```

## 📖 프로젝트 구조

```
PaperFlow/
├── main_terminal.py       # 메인 프로그램 (PDF 변환)
├── app.py                 # Streamlit 웹 뷰어
├── run_batch.sh           # 배치 처리 실행 (일회성)
├── run_batch_watch.sh     # Watch 모드 실행 (연속) ⭐
├── run_app.sh             # 웹 뷰어 실행
├── setup_venv.sh          # 설치 스크립트
├── config.json            # 설정
├── header.yaml            # HTML 포맷
├── prompt.md              # 번역 프롬프트
├── requirements.txt       # Python 패키지
├── newones/               # 입력 폴더 (PDF 넣는 곳)
├── outputs/               # 출력 폴더 (읽을 논문)
├── archives/              # 아카이브 폴더 (읽은 논문)
├── logs/                  # 로그 폴더
└── .sessions/             # 세션 파일 (자동 로그인)
```

## 🤝 기여

이슈나 PR은 언제나 환영합니다!

## 📄 라이선스

이 프로젝트는 다음 오픈소스 도구들을 활용합니다:
- [Marker-pdf](https://github.com/datalab-to/marker) - PDF to Markdown
- [Ollama](https://ollama.com/) - Local LLM
- [Quarto](https://quarto.org/) - Document rendering

## 🌟 특징

### 🔒 개인정보 보호
- ✅ **완전 로컬** - 모든 처리가 로컬에서 진행
- ✅ **무료** - 유료 API 불필요
- ✅ **오프라인 가능** - 인터넷 없이도 작동

### 🚀 자동화 & 성능
- ✅ **자동화** - PDF 넣고 스크립트 실행만 하면 끝
- ✅ **배치 처리** - 여러 PDF 동시 처리
- ✅ **Watch 모드** - 새 PDF 자동 감지 및 처리
- ✅ **GPU 가속** - CUDA 지원 (없으면 CPU 자동 전환)
- ✅ **메모리 관리** - GPU 메모리 자동 최적화

### 📚 고품질 변환
- ✅ **고품질** - 수식, 표, 이미지 모두 보존
- ✅ **목차 지원** - PDF 북마크 자동 추출
- ✅ **편집 가능** - 마크다운 실시간 편집
- ✅ **로그 기록** - 모든 과정 추적 가능

### 🖥️ 강력한 웹 뷰어
- ✅ **논문 관리** - 읽을/읽은 논문 분류
- ✅ **다중 포맷** - HTML, PDF, Markdown 지원
- ✅ **분할 보기** - 한영 동시 비교
- ✅ **사이드바 컨트롤** - 깔끔한 UI
- ✅ **세션 유지** - 자동 로그인
