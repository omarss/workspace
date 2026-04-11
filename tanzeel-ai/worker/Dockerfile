FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev git wget ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Download and convert the Tarteel Quran ASR model to CTranslate2 format
RUN pip3 install --no-cache-dir ctranslate2 transformers[torch] && \
    ct2-transformers-converter \
        --model tarteel-ai/whisper-base-ar-quran \
        --output_dir /model/whisper-base-ar-quran-ct2 \
        --quantization float16 && \
    pip3 uninstall -y torch transformers && \
    rm -rf /root/.cache/huggingface

# Copy handler
COPY handler.py .

ENV MODEL_PATH=/model/whisper-base-ar-quran-ct2
ENV DEVICE=cuda
ENV COMPUTE_TYPE=float16

CMD ["python3", "handler.py"]
