# Offline Office Knowledge Base

A privacy-first local knowledge base for PDF, Word, and Excel files. Documents are indexed once into a portable SQLite database and queried through a FastAPI web interface or an MCP server.

## Features

- Offline Ollama inference; document content stays on the office machine.
- PDF, DOCX, DOCM, XLSX, XLS, CSV, Markdown, and text extraction, including OCR for image-only PDF pages.
- SHA-256 document identity so unchanged files are not extracted again.
- Chunked source-aware storage with page, paragraph, table, or sheet locations.
- SQLite FTS5 keyword search plus a local vector index with an offline hashing fallback.
- Topic extraction, entity extraction, co-occurrence relationships, and source provenance.
- Web API and MCP tools for ingestion, querying, document management, and graph inspection.

## Setup

1. Install Ollama and run `ollama pull llama3` once.
2. Install dependencies: `pip install fastapi uvicorn 'mcp<2' pymupdf easyocr python-docx pandas openpyxl httpx numpy python-multipart`.
3. Run the web GUI with `python main.py`.
4. Ingest documents once, then query the index. The database is `data/knowledge.db` by default.
5. Configure `mcp_server.py` in your MCP client for folder ingestion and persistent queries.

## API

`POST /api/ingest` or `POST /api/ingest/upload` indexes uploaded files once. `POST /api/ingest/folder` indexes an approved server-side folder. `POST /api/search` returns retrieval evidence without an LLM, while `POST /api/query` and `/api/qa/query` search the persistent index and ask Ollama. `GET /api/documents` lists indexed files, `DELETE /api/documents/{sha256}` removes one, and `GET /api/graph?q=topic` returns related topics and entities.

Set `KNOWLEDGE_DB_PATH` or `OFFLINE_QA_DB` to place the database outside the checkout, `OLLAMA_MODEL` to select a local model, `EMBEDDING_MODEL` to use an installed sentence-transformers model, `OFFICE_API_KEY` to require an `X-API-Key`, and `ALLOWED_DOCUMENT_ROOT` or `OFFLINE_QA_ALLOWED_ROOTS` to restrict folder access. Set `OFFLINE_QA_ALLOW_ANY_PATH=1` only for a deliberately isolated deployment.
