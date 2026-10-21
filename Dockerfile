FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

# These downloads happen during the connected build only. The resulting image
# contains the embedding and OCR weights, so runtime does not need internet.
COPY scripts/warm_models.py /tmp/warm_models.py
RUN mkdir -p /models/embeddings /models/easyocr \
    && python /tmp/warm_models.py

COPY . ./

ENV DATA_DIR=/data \
    EMBEDDING_MODEL_DIR=/models/embeddings/all-MiniLM-L6-v2 \
    EASYOCR_MODULE_PATH=/models/easyocr \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN mkdir -p /data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
