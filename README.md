# Offline Document Knowledge Base

This is a local-first document retrieval system for secure Ubuntu/Linux offices. It indexes PDF, Word, Excel, CSV, Markdown, and text files into a persistent SQLite database. Files are identified by SHA-256, so the same document is skipped after its first successful ingestion.

The index contains:

- extracted document chunks with page references where available;
- a SQLite FTS5 full-text index for fast local search;
- document and chunk topic terms;
- a topic co-occurrence graph for related-topic exploration;
- optional local Ollama answer generation grounded in retrieved passages.

No document data is sent to a cloud service. If Ollama is unavailable, the API still returns ranked passages from the local index.

## Ubuntu/Linux setup

```bash
sudo apt update
sudo apt install -y python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional local answer model
ollama pull llama3
python main.py
```

Open `http://127.0.0.1:8000`. For a server on an office network, set `OFFLINE_QA_HOST=0.0.0.0` and put the service behind the office firewall or a reverse proxy with authentication.

## One-time ingestion

Use the web page's **Server-side folder path** field or call the API directly:

```bash
curl -X POST http://127.0.0.1:8000/api/ingest/folder \
  -H 'Content-Type: application/json' \
  -d '{"folder_path":"/srv/office-documents","recursive":true}'
```

The database is stored at `data/knowledge.db` by default. Change it with `OFFLINE_QA_DB=/secure/path/knowledge.db`. By default, folder ingestion is limited to the current working directory. Set `OFFLINE_QA_ALLOWED_ROOTS=/srv/office-documents:/opt/shared-docs` to allow approved roots. For a trusted isolated deployment only, `OFFLINE_QA_ALLOW_ANY_PATH=1` disables that path check.

Ingesting the same folder again is safe: unchanged files return `already_indexed`; changed files get a new hash and are indexed as a new version. Uploaded files use the same deduplication logic.

## Query and graph APIs

```bash
curl -X POST http://127.0.0.1:8000/api/qa/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which documents describe the procurement budget?","top_k":8}'

curl http://127.0.0.1:8000/api/graph
curl 'http://127.0.0.1:8000/api/graph?topic=procurement'
```

The query response includes an answer, ranked source chunks, and related topics. With Ollama running, the answer is generated locally from the retrieved context. Without it, the response is extractive and still includes the source passages.

## MCP server

The MCP server uses the same `data/knowledge.db` as the web API. It exposes `ingest_local_folder`, `search_knowledge_base`, `query_local_documents`, and `get_knowledge_graph`.

```bash
python mcp_server.py
```

Configure the command in an MCP-compatible desktop client with the absolute path to the repository's Python interpreter and `mcp_server.py`.

## OCR and security notes

Text-based PDFs work without extra model downloads. To OCR scanned PDFs, install the optional `easyocr` dependency and set `OFFLINE_QA_ENABLE_OCR=1`; the OCR model is loaded locally and cached by EasyOCR. Keep the service bound to `127.0.0.1` unless the office network and reverse proxy are configured deliberately.
