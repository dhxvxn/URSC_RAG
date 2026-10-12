# Offline Office Knowledge Base

This project is a local document ingestion, retrieval, and question-answering system for secure Ubuntu/Linux offices. Documents stay on the office machine. The same persistent SQLite database is used by the web API and the MCP server.

## What is included

- PDF, DOCX, DOCM, XLSX, XLS, CSV, Markdown, and plain-text extraction.
- EasyOCR for image-only PDF pages.
- SHA-256 content identity. Re-ingesting an unchanged file returns `existing` and does not extract it again.
- Chunked storage with source locations such as PDF page, Word paragraph/table, or Excel sheet.
- SQLite FTS5 keyword search and a local vector index. The default hashing embedder works offline; a local Sentence Transformers model can be enabled with `EMBEDDING_MODEL`.
- Topic extraction, topic co-occurrence links, entity extraction, typed entity relationships, confidence values, and source evidence.
- FastAPI web interface and API.
- MCP tools for folder ingestion, search, question answering, and graph inspection.
- Extractive answers remain available when Ollama is stopped or the language model is not installed.

## Ubuntu/Linux installation

The commands below assume Ubuntu 22.04 or newer and a checkout at `~/URSC_RAG`.

### 1. Install system prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-dev build-essential
```

For some EasyOCR/OpenCV installations, these system libraries may also be needed:

```bash
sudo apt install -y libgl1 libglib2.0-0
```

### 2. Clone the repository

```bash
git clone https://github.com/dhxvxn/URSC_RAG.git ~/URSC_RAG
cd ~/URSC_RAG
```

If the repository is already present:

```bash
cd ~/URSC_RAG
git pull --ff-only origin main
```

### 3. Create and activate the virtual environment

```bash
cd ~/URSC_RAG
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -r requirements.txt
python -m pip check
```

Activate the environment again whenever a new terminal is opened:

```bash
cd ~/URSC_RAG
source .venv/bin/activate
```

The virtual environment is local to this checkout and is ignored by Git if you name it `.venv`.

### 4. Install and prepare Ollama

Install Ollama using its official Ubuntu instructions, then start the local service in a separate terminal. Pull the model once:

```bash
ollama serve
```

In another terminal, with the virtual environment active:

```bash
ollama pull llama3
curl http://127.0.0.1:11434/api/tags
```

The application uses `llama3` by default. Select another locally installed model with `OLLAMA_MODEL`.

If Ollama is unavailable, document search still works and `/api/query` returns the relevant source passages instead of silently returning an empty answer.

## Start the application

Create a private document directory and keep the database outside the source tree if desired:

```bash
cd ~/URSC_RAG
mkdir -p documents data
export KNOWLEDGE_DB_PATH="$PWD/data/knowledge.db"
export ALLOWED_DOCUMENT_ROOT="$PWD/documents"
source .venv/bin/activate
python main.py
```

The service listens on `127.0.0.1:8000` by default. Open `http://127.0.0.1:8000` on the same laptop. For an office-network deployment, put the service behind an authenticated HTTPS reverse proxy. If direct LAN binding is required, set `OFFLINE_QA_HOST=0.0.0.0` and configure the firewall deliberately.

Useful optional settings:

```bash
export OFFLINE_QA_HOST=127.0.0.1       # server bind address
export OFFLINE_QA_PORT=8000            # server port
export OFFICE_API_KEY='choose-a-secret' # protects API routes with X-API-Key
export MAX_FILE_BYTES=$((100*1024*1024))
export OLLAMA_MODEL=llama3
```

Do not put `OFFICE_API_KEY` in Git or in a shared README. Supply it through the service manager or a protected environment file.

## Ingest documents once

The browser can upload files through the web page. For a server-side office folder, use the folder endpoint. The folder must be inside `ALLOWED_DOCUMENT_ROOT` or one of the roots in `OFFLINE_QA_ALLOWED_ROOTS`.

```bash
curl -X POST http://127.0.0.1:8000/api/ingest/folder \
  -H 'Content-Type: application/json' \
  -d '{"folder_path":"/home/YOUR_USER/URSC_RAG/documents","recursive":true}'
```

Alternatively upload files directly:

```bash
curl -X POST http://127.0.0.1:8000/api/ingest \
  -F 'files=@/home/YOUR_USER/URSC_RAG/documents/handbook.pdf' \
  -F 'files=@/home/YOUR_USER/URSC_RAG/documents/budget.xlsx'
```

Ingestion stores extracted chunks, vectors, topics, entities, and graph evidence in `data/knowledge.db`. Repeating the command is safe. Unchanged files are skipped by SHA-256; a changed file receives a new content identity and can coexist as a new version.

## Search, answers, and graph APIs

Search without requiring Ollama:

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the parasite drag coefficient?","top_k":8}'
```

Ask for a grounded local answer:

```bash
curl -X POST http://127.0.0.1:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is the parasite drag coefficient?","top_k":8}'
```

Inspect indexed documents and related graph data:

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/documents
curl 'http://127.0.0.1:8000/api/graph?q=drag&limit=30'
```

The answer response includes `sources`, source locations, retrieval scores, topics, entities, and graph relationships. The older `/api/qa/upload_folder` and `/api/qa/query` routes remain available for compatibility.

## Optional semantic embedding model

The default hashing vectors require no model download and are useful for a small offline collection. For stronger semantic matching, install `sentence-transformers` and place a model on the office machine through your approved software-transfer process:

```bash
source .venv/bin/activate
python -m pip install sentence-transformers
export EMBEDDING_MODEL=/opt/office-models/all-MiniLM-L6-v2
```

Set `EMBEDDING_MODEL` before the first ingestion. If you change embedding models after indexing, rebuild the database so every stored vector uses the same dimensions and model.

## MCP server

The MCP server uses the same SQLite database and approved document roots as the web API:

```bash
cd ~/URSC_RAG
source .venv/bin/activate
export KNOWLEDGE_DB_PATH="$PWD/data/knowledge.db"
export ALLOWED_DOCUMENT_ROOT="$PWD/documents"
python mcp_server.py
```

Configure the MCP client with an absolute interpreter path:

```json
{
  "mcpServers": {
    "office-knowledge-base": {
      "command": "/home/YOUR_USER/URSC_RAG/.venv/bin/python",
      "args": ["/home/YOUR_USER/URSC_RAG/mcp_server.py"],
      "cwd": "/home/YOUR_USER/URSC_RAG",
      "env": {
        "KNOWLEDGE_DB_PATH": "/home/YOUR_USER/URSC_RAG/data/knowledge.db",
        "ALLOWED_DOCUMENT_ROOT": "/home/YOUR_USER/URSC_RAG/documents"
      }
    }
  }
}
```

Available tools are `ingest_local_folder`, `query_knowledge_base`, `query_local_documents`, `knowledge_graph`, plus compatibility aliases `search_knowledge_base` and `get_knowledge_graph`.

## Security and operations

- Keep the service on `127.0.0.1` unless a firewall and HTTPS reverse proxy are configured.
- Set `OFFICE_API_KEY` for API access control. MCP access is controlled by its process and `ALLOWED_DOCUMENT_ROOT`.
- Keep documents and `data/knowledge.db` on encrypted office storage and include the database in the backup plan.
- Do not set `OFFLINE_QA_ALLOW_ANY_PATH=1` on a shared machine unless the process is isolated and trusted.
- Back up the SQLite database while the service is stopped, or copy its WAL files consistently.
- Restrict model and dependency installation to approved, verified sources for an air-gapped office.

## Troubleshooting

Check the environment and service:

```bash
source .venv/bin/activate
python -m pip check
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:11434/api/tags
```

If the API reports `Ollama is unavailable`, `/api/search` should still return ranked passages. Start Ollama and confirm that the configured model appears in `/api/tags`.

If OCR fails, confirm that `easyocr` is installed and that its model files are available locally. Text-based PDFs, Word files, spreadsheets, CSV, Markdown, and plain-text files do not require OCR.

If folder ingestion returns `403`, use a path inside `ALLOWED_DOCUMENT_ROOT` or set `OFFLINE_QA_ALLOWED_ROOTS` to a colon-separated list of approved roots.

## Development checks

```bash
source .venv/bin/activate
python -m compileall -q main.py mcp_server.py knowledge_base.py
python -m pip check
git diff --check
```
