import os
from pathlib import Path

from sentence_transformers import SentenceTransformer


embedding_dir = Path(
    os.getenv("WARM_EMBEDDING_MODEL_DIR", "/models/embeddings/all-MiniLM-L6-v2")
)
ocr_dir = Path(os.getenv("WARM_OCR_MODEL_DIR", "/models/easyocr"))
embedding_dir.parent.mkdir(parents=True, exist_ok=True)
ocr_dir.mkdir(parents=True, exist_ok=True)

model = SentenceTransformer("all-MiniLM-L6-v2", cache_folder=str(embedding_dir.parent))
model.save(str(embedding_dir))

import easyocr

easyocr.Reader(
    ["en"],
    model_storage_directory=str(ocr_dir),
    download_enabled=True,
    verbose=False,
)
