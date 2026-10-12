"""FastAPI interface for the persistent offline knowledge base."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from knowledge_base import KnowledgeBase, ask_ollama, extract_docx, extract_excel, extract_pdf


app = FastAPI(title="Offline Office Knowledge Base", version="2.0")
kb = KnowledgeBase()


# Compatibility helpers for callers of the original prototype.
def extract_text_from_pdf(file_bytes: bytes) -> str:
    return "\n".join(text for _, text in extract_pdf(file_bytes))


def extract_text_from_docx(file_bytes: bytes) -> str:
    return "\n".join(text for _, text in extract_docx(file_bytes))


def extract_text_from_excel(file_bytes: bytes) -> str:
    return "\n".join(text for _, text in extract_excel(file_bytes))


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    configured = os.environ.get("OFFICE_API_KEY")
    if configured and x_api_key != configured:
        raise HTTPException(status_code=401, detail="A valid X-API-Key is required")


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=50)
    model: str | None = None
    use_llm: bool = True


class FolderRequest(BaseModel):
    folder_path: str
    recursive: bool = True


async def answer_question(question: str, top_k: int = 8, model: str | None = None) -> dict:
    context, sources, graph = kb.context(question, top_k)
    llm_error = None
    try:
        answer = await ask_ollama(question, context, model)
    except RuntimeError as exc:
        llm_error = str(exc)
        if not sources:
            answer = "No matching content was found in the indexed documents."
        else:
            passages = "\n\n".join(f"[{s['filename']} — {s['location']}]\n{s['text']}" for s in sources[:5])
            answer = f"Ollama is unavailable, so these relevant passages are shown instead:\n\n{passages}"
    return {"answer": answer, "llm_used": llm_error is None, "llm_error": llm_error, "sources": sources, "graph": graph}


def allowed_folder(path: Path) -> bool:
    if os.environ.get("OFFLINE_QA_ALLOW_ANY_PATH", "0").lower() in {"1", "true", "yes"}:
        return True
    configured = os.environ.get("ALLOWED_DOCUMENT_ROOT") or os.environ.get("OFFLINE_QA_ALLOWED_ROOTS") or str(Path.cwd())
    roots = [Path(item).expanduser().resolve() for item in configured.split(os.pathsep) if item.strip()]
    return any(path == root or root in path.parents for root in roots)


@app.get("/", response_class=HTMLResponse)
async def get_web_interface() -> str:
    return """
    <!doctype html><html><head><meta charset="utf-8"><title>Office Knowledge Base</title>
    <style>body{font-family:Arial;max-width:900px;margin:35px auto;padding:20px;background:#f4f7f6}.box{background:white;padding:25px;border-radius:10px;box-shadow:0 2px 10px #ccc}input,button{width:100%;box-sizing:border-box;padding:11px;margin:7px 0}button{background:#0759a5;color:#fff;border:0;border-radius:4px;cursor:pointer}.result{white-space:pre-wrap;background:#eef7ee;padding:14px;margin-top:15px}.small{color:#555;font-size:.9em}</style></head>
    <body><div class="box"><h2>Offline Office Knowledge Base</h2>
    <p class="small">Ingest documents once. Later questions search the persistent local index.</p>
    <form id="ingest"><label>Documents (PDF, Word, Excel)</label><input id="files" type="file" multiple required><button>Index documents</button></form>
    <form id="query"><label>Question</label><input id="question" required placeholder="Ask about an indexed topic"><button>Search and answer</button></form>
    <div id="result" class="result" hidden></div></div>
    <script>
    const out=document.getElementById('result'); const show=x=>{out.hidden=false;out.textContent=typeof x==='string'?x:JSON.stringify(x,null,2)};
    document.getElementById('ingest').onsubmit=async e=>{e.preventDefault();const f=new FormData();for(const x of document.getElementById('files').files)f.append('files',x);show('Indexing…');const r=await fetch('/api/ingest',{method:'POST',body:f});show(await r.json())};
    document.getElementById('query').onsubmit=async e=>{e.preventDefault();show('Searching…');const r=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:document.getElementById('question').value})});show(await r.json())};
    </script></body></html>
    """


@app.get("/api/health")
async def health(_: None = Depends(require_api_key)) -> dict:
    return {"status": "ok", "database": kb.db_path, "documents": len(kb.documents())}


@app.post("/api/ingest")
async def ingest_documents(files: List[UploadFile] = File(...), _: None = Depends(require_api_key)) -> dict:
    results = []
    errors = []
    for upload in files:
        try:
            data = await upload.read()
            results.append(kb.ingest_bytes(Path(upload.filename or "document").name, data))
        except (ValueError, OSError, RuntimeError) as exc:
            errors.append({"filename": upload.filename, "error": str(exc)})
    if not results and errors:
        raise HTTPException(status_code=400, detail=errors)
    return {"indexed": results, "errors": errors, "documents": kb.documents()}


@app.post("/api/ingest/folder")
async def ingest_folder(request: FolderRequest, _: None = Depends(require_api_key)) -> dict:
    path = Path(request.folder_path).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder does not exist: {path}")
    if not allowed_folder(path):
        raise HTTPException(status_code=403, detail="Folder is outside the configured document roots")
    try:
        indexed = kb.ingest_folder(path, request.recursive)
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"indexed": indexed, "errors": [], "documents": kb.documents()}


@app.post("/api/query")
async def query_knowledge_base(request: QueryRequest, _: None = Depends(require_api_key)) -> dict:
    if not request.use_llm:
        _, sources, graph = kb.context(request.question, request.top_k)
        return {"answer": "\n\n".join(f"[{s['filename']} — {s['location']}]\n{s['text']}" for s in sources), "llm_used": False, "llm_error": None, "sources": sources, "graph": graph}
    return await answer_question(request.question, request.top_k, request.model)


@app.post("/api/search")
async def search_index(request: QueryRequest, _: None = Depends(require_api_key)) -> dict:
    """Return retrieval and graph evidence without requiring an LLM."""
    _, sources, graph = kb.context(request.question, request.top_k)
    return {"sources": sources, "graph": graph}


@app.post("/api/qa/upload_folder")
async def legacy_upload_and_query(
    question: str = Form(...), files: List[UploadFile] = File(...), _: None = Depends(require_api_key)
) -> dict:
    """Backward-compatible route: indexes new files, then searches the complete index."""
    ingestion = await ingest_documents(files)
    result = await answer_question(question)
    result["indexed"] = ingestion["indexed"]
    result["errors"] = ingestion["errors"]
    result["files_used"] = [source["filename"] for source in result["sources"]]
    return result


@app.post("/api/qa/query")
async def query_legacy_name(request: QueryRequest, _: None = Depends(require_api_key)) -> dict:
    return await query_knowledge_base(request, _)


@app.get("/api/documents")
async def list_documents(_: None = Depends(require_api_key)) -> dict:
    return {"documents": kb.documents()}


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str, _: None = Depends(require_api_key)) -> dict:
    if not kb.remove_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": document_id}


@app.get("/api/graph")
async def knowledge_graph(q: str | None = None, limit: int = 30, _: None = Depends(require_api_key)) -> dict:
    return kb.graph(q, max(1, min(limit, 100)))


if __name__ == "__main__":
    uvicorn.run("main:app", host=os.environ.get("HOST", os.environ.get("OFFLINE_QA_HOST", "127.0.0.1")), port=int(os.environ.get("PORT", os.environ.get("OFFLINE_QA_PORT", "8000"))))
