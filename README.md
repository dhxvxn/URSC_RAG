# Offline Multi-Document QA System and MCP Server

This project is a local, privacy-first question-answering system for PDF, Word, and Excel files. It provides a FastAPI web interface and a Model Context Protocol (MCP) server for local AI assistants. Documents are processed locally and sent only to the Ollama service running on the same machine.

## Features

- PDF text extraction with EasyOCR fallback for image-only pages.
- Word (`.docx`) paragraph extraction.
- Excel (`.xlsx` and `.xls`) sheet extraction with pandas.
- Content-hash caching, so the same file is not extracted again.
- FastAPI web interface for selecting a folder and asking a question.
- MCP tool for scanning a local folder from an MCP-compatible assistant.
- Local Ollama inference with the `llama3` model by default.
- Extracted text and the document registry are stored in `doc_cache/`.

The current implementation caches extracted text. It does not create a persistent vector index or knowledge graph.

## Ubuntu/Linux setup

The commands below assume Ubuntu 22.04 or newer and a checkout at `~/URSC_RAG`.

### 1. Install system packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-dev build-essential
sudo apt install -y libgl1 libglib2.0-0
```

### 2. Clone or update the repository

```bash
git clone https://github.com/dhxvxn/URSC_RAG.git ~/URSC_RAG
cd ~/URSC_RAG
```

For an existing checkout:

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
python -m pip install fastapi uvicorn 'mcp<2' pymupdf easyocr python-docx pandas openpyxl xlrd httpx numpy python-multipart
python -m pip check
```

Activate it again in each new terminal:

```bash
cd ~/URSC_RAG
source .venv/bin/activate
```

The first EasyOCR startup may download model files. In a restricted office, transfer and verify those files through the approved process before running the application.

### 4. Install and prepare Ollama

Install Ollama using its official Linux instructions. Start it in a separate terminal:

```bash
ollama serve
```

In another terminal:

```bash
ollama pull llama3
curl http://127.0.0.1:11434/api/tags
```

The application calls `http://localhost:11434/api/chat` and uses `llama3` by default.

## Run the web application

For laptop-only use, bind the service to loopback:

```bash
cd ~/URSC_RAG
source .venv/bin/activate
EASYOCR_MODULE_PATH="$PWD/.easyocr" python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. If you run `python main.py` directly, the prototype binds to `0.0.0.0:8000`; use that only behind an office firewall or authenticated HTTPS reverse proxy. There is no built-in user authentication.

## Use the API

The browser uses `POST /api/qa/upload_folder`. It accepts a multipart form with `question` and one or more `files` fields:

```bash
curl -X POST http://127.0.0.1:8000/api/qa/upload_folder \
  -F 'question=What is the parasite drag coefficient?' \
  -F 'files=@/home/YOUR_USER/documents/handbook.pdf' \
  -F 'files=@/home/YOUR_USER/documents/report.docx' \
  -F 'files=@/home/YOUR_USER/documents/budget.xlsx'
```

The response contains `files_used` and `answer`. Supported extensions are `.pdf`, `.docx`, `.xlsx`, and `.xls`; other files are skipped. The cache avoids repeated extraction, but the current browser workflow still requires selecting files for each question.

## Run the MCP server

```bash
cd ~/URSC_RAG
source .venv/bin/activate
EASYOCR_MODULE_PATH="$PWD/.easyocr" python mcp_server.py
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "offline-document-qa": {
      "command": "/home/YOUR_USER/URSC_RAG/.venv/bin/python",
      "args": ["/home/YOUR_USER/URSC_RAG/mcp_server.py"],
      "cwd": "/home/YOUR_USER/URSC_RAG"
    }
  }
}
```

The MCP tool is `query_local_documents(folder_path, question)`.

## Privacy and troubleshooting

`doc_cache/registry.json` and the extracted text cache contain office content. Keep the directory on encrypted storage and include it in backups. The repository ignores `doc_cache/`, generated test documents, Python bytecode, `.env`, and `.venv/`.

```bash
source .venv/bin/activate
python -m pip check
curl http://127.0.0.1:11434/api/tags
python -m compileall -q main.py mcp_server.py create_test_folder.py
```

If `mcp.server.fastmcp` cannot be imported, install the MCP v1-compatible package with `python -m pip install --upgrade 'mcp<2'`. If the API returns an empty answer, confirm that Ollama is running and `llama3` appears in `/api/tags`. If scanned PDFs are not recognized, confirm that EasyOCR model files are available.
