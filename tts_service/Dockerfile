FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y python3 python3-pip ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
RUN pip3 install --no-cache-dir --upgrade pip
# torch/torchaudio 는 cu121 인덱스에서(voxcpm PoC 검증 조합: torch 2.5.1). 나머지는 PyPI.
RUN pip3 install --no-cache-dir torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY voices ./voices
COPY app ./app
EXPOSE 8100
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8100"]
