\# Offline Multi-Document QA System \& MCP Server



A fully offline, privacy-first AI question-answering system that scans local folders containing PDF, Word (docx), and Excel (xlsx) files. It features both a FastAPI web interface and a Model Context Protocol (MCP) server for direct integration with AI assistants like Claude Desktop.



\## Features

\* \*\*100% Offline:\*\* Uses local Llama 3 via Ollama. No data leaves your machine.

\* \*\*Multi-Format Support:\*\* Reads PDFs (PyMuPDF), Word docs (python-docx), and Excel sheets (pandas).

\* \*\*OCR Integrated:\*\* Extracts text from image-based PDFs using EasyOCR.

\* \*\*Smart Caching:\*\* Hashes and caches extracted text to prevent redundant processing.

\* \*\*Dual Interfaces:\*\* Includes a local web GUI (`main.py`) and a Claude Desktop MCP Tool (`mcp\_server.py`).



\## Setup

1\. Install \[Ollama](https://ollama.com/) and run `ollama run llama3`.

2\. Install dependencies: `pip install fastapi uvicorn mcp pymupdf easyocr python-docx pandas openpyxl httpx numpy`.

3\. Run the web GUI: `python main.py`

4\. Or configure `mcp\_server.py` in your Claude Desktop `claude\_desktop\_config.json` to use it directly in chat.

