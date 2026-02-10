# Base image with CUDA support for PDF conversion
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

# PDF Converter selection: "marker" (default) or "mineru"
ARG PDF_CONVERTER=marker

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
# libgl1 + libglib2.0-0: required by OpenCV (used by MinerU)
RUN apt-get update && apt-get install -u -y \
    software-properties-common \
    curl \
    wget \
    git \
    libgl1 \
    libglib2.0-0 \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -u -y \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python3-pip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage cache
COPY requirements.txt requirements-marker.txt requirements-mineru.txt ./

# Create virtual environment and install dependencies
RUN python3.12 -m venv /app/.venv \
    && . /app/.venv/bin/activate \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && if [ "$PDF_CONVERTER" = "mineru" ]; then \
         pip install -r requirements-mineru.txt; \
       else \
         pip install -r requirements-marker.txt; \
       fi \
    && pip install setuptools wheel

# Copy the rest of the application
COPY . .

# Make scripts executable
RUN chmod +x *.sh entrypoint.sh

# Environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8
ENV PDF_CONVERTER=${PDF_CONVERTER}

# Use entrypoint script
ENTRYPOINT ["./entrypoint.sh"]

# Default command
CMD ["./run_batch_watch.sh"]
