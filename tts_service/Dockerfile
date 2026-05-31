FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y python3 python3-pip ffmpeg sox && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
# pysox(qwen-tts 의존)만 빌드 시 numpy+sox 를 요구 → numpy 선설치 후 sox 만 격리 없이 빌드,
# 나머지(torch/qwen-tts 등)는 정상 빌드 격리로 설치(이미 깔린 sox 는 재빌드 안 함).
RUN pip3 install --no-cache-dir numpy setuptools wheel typing_extensions
RUN pip3 install --no-cache-dir --no-build-isolation sox
RUN pip3 install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8100
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8100"]
