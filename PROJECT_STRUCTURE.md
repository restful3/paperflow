# PaperFlow 프로젝트 구조

## 📁 디렉토리 구조

```
PaperFlow/
├── main_terminal.py       # 메인 프로그램 (터미널 UI)
├── run_batch_venv.sh      # 실행 스크립트
├── setup_venv.sh          # 가상환경 설정 스크립트
│
├── config.json            # 설정 파일
├── header.yaml            # HTML 출력 포맷 설정
├── prompt.md              # 번역 프롬프트
├── requirements.txt       # Python 패키지 의존성
│
├── CLAUDE.md              # AI 코드 어시스턴트용 프로젝트 가이드
├── README.md              # 원본 프로젝트 설명 (한국어)
│
├── newones/               # 📥 입력: 처리할 PDF 파일을 여기에 넣기
├── outputs/               # 📤 출력: 변환 결과물
│   └── {pdf_name}/
│       ├── {pdf_name}.pdf         # 원본 PDF (처리 후 이동됨)
│       ├── {pdf_name}.md          # 영문 마크다운
│       ├── {pdf_name}_ko.md       # 한국어 마크다운
│       ├── {pdf_name}_ko.html     # 한국어 HTML
│       ├── {pdf_name}.json        # 메타데이터
│       └── *.jpeg                 # 추출된 이미지
│
├── logs/                  # 📝 처리 로그 파일
│   └── paperflow_YYYYMMDD_HHMMSS.log
│
└── .venv/                 # Python 가상환경 (설치 후 생성됨)
```

## 🚀 사용 방법

### 1. 초기 설정 (최초 1회)
```bash
./setup_venv.sh
```

### 2. PDF 변환
```bash
# PDF 파일을 newones에 넣기
cp your_paper.pdf newones/

# 실행
./run_batch_venv.sh
```

### 3. 결과 확인
```bash
# 결과물 확인
ls outputs/your_paper/

# 로그 확인
cat logs/paperflow_*.log
```

## 📝 핵심 파일 설명

### main_terminal.py
- PDF → Markdown → 한국어 번역 → HTML 변환 처리
- 터미널에서 실행되며 컬러 UI 제공
- 로그 파일 자동 생성

### config.json
- Ollama URL 및 모델 설정
- 번역 파라미터 (chunk size, temperature 등)

### header.yaml
- Quarto HTML 출력 포맷 설정
- 테마, 목차, 코드 접기 등

### prompt.md
- Ollama 번역 프롬프트
- 번역 규칙 및 가이드라인

## 🔧 주요 기능

1. **PDF → Markdown 변환** (marker-pdf 라이브러리)
2. **이미지 추출** (자동)
3. **한국어 번역** (Ollama)
4. **HTML 생성** (Quarto)
5. **자동 정리** (처리된 PDF를 outputs로 이동)
6. **로그 기록** (모든 과정 저장)

## 🗑️ 삭제된 파일들

다음 파일들은 터미널 배치 워크플로우와 무관하여 삭제되었습니다:
- GUI 관련: main.py, PaperFlow.bat, paperflow.sh, PaperFlow.png, robot_1217_V02.ico
- 중복: run_batch.sh, pyproject.toml, uv.lock
- 기타: README_USAGE.md, test_setup.sh

## 📦 의존성

### Python 패키지
- marker-pdf (PDF 처리)
- torch (AI 모델)
- requests (API 통신)
- markdown-it-py (마크다운 파싱)

### 외부 도구
- Ollama (번역)
- Quarto (HTML 생성)
