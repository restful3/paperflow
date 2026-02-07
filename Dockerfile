# Base image with CUDA support for marker-pdf
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

# Prevent interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies
# python3-launchpadlib is often needed for universe repo
RUN apt-get update && apt-get install -u -y \
    software-properties-common \
    curl \
    wget \
    git \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -u -y \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    python3-pip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage cache
COPY requirements.txt .

# Create virtual environment and install dependencies
# We install directly into the container's python for simplicity,
# but using venv is safer to avoid system conflicts.
RUN python3.12 -m venv /app/.venv \
    && . /app/.venv/bin/activate \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install setuptools wheel

# Copy the rest of the application
COPY . .

# Make scripts executable
RUN chmod +x *.sh entrypoint.sh

# Environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

# Use entrypoint script
ENTRYPOINT ["./entrypoint.sh"]

# Default command
CMD ["./run_batch_watch.sh"]
