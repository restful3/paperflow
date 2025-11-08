# outputs 디렉토리

처리된 PDF 파일의 결과물이 저장되는 디렉토리입니다.

## 출력 구조

각 PDF 파일당 하나의 디렉토리가 생성됩니다:

```
outputs/
  └── example/
      ├── example.json       # Marker-pdf API 응답 (raw data)
      ├── example.md         # 영문 마크다운
      ├── example_ko.md      # 한국어 번역 마크다운
      ├── example_ko.pdf     # 렌더링된 한국어 PDF
      └── *.png, *.jpg       # 추출된 이미지 파일들
```

## 파일 설명

- **example.json**: Marker-pdf API의 원본 응답 데이터
- **example.md**: PDF에서 변환된 영문 마크다운
- **example_ko.md**: Ollama를 통해 번역된 한국어 마크다운
- **example_ko.pdf**: Quarto로 렌더링된 최종 PDF (한국어)
- **이미지 파일들**: PDF에서 추출된 이미지들
