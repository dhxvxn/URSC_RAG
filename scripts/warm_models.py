from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")
model.save("/models/embeddings/all-MiniLM-L6-v2")

import easyocr

easyocr.Reader(
    ["en"],
    model_storage_directory="/models/easyocr",
    download_enabled=True,
    verbose=False,
)
