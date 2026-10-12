"""Local web API for the persistent offline document knowledge base."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from knowledge_base import get_knowledge_base

app = FastAPI(title="Offline Document Knowledge Base", version="2.0.0")


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=8, ge=1, le=30)
    use_llm: bool = True


class FolderRequest(BaseModel):
    folder_path: str
    recursive: bool = True


def _allowed_folder(path: Path) -> bool:
    if os.getenv("OFFLINE_QA_ALLOW_ANY_PATH", "0").lower() in {"1", "true", "yes"}:
        return True
    configured = os.getenv("OFFLINE_QA_ALLOWED_ROOTS", str(Path.cwd()))
    roots = [Path(item).expanduser().resolve() for item in configured.split(os.pathsep) if item.strip()]
    return any(path == root or root in path.parents for root in roots)


def _results(results: list[Any]) -> dict[str, Any]:
    return {"stats": get_knowledge_base().stats(), "files": [result.__dict__ for result in results]}


async def _ollama_answer(question: str, context: str) -> str | None:
    if not context or os.getenv("OFFLINE_QA_DISABLE_OLLAMA", "0").lower() in {"1", "true", "yes"}:
        return None
    try:
        import httpx  # type: ignore
        base_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3")
        payload = {"model": model, "messages": [
            {"role": "system", "content": "Answer only from the supplied office documents. Cite the source filename and page when available. If the documents do not contain the answer, say so."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}], "stream": False}
        async with httpx.AsyncClient(timeout=float(os.getenv("OLLAMA_TIMEOUT", "90"))) as client:
            response = await client.post(f"{base_url.rstrip('/')}/api/chat", json=payload)
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "").strip() or None
    except Exception:
        return None


def _extractive_answer(context: dict[str, Any]) -> str:
    if not context["hits"]:
        return "No matching content was found in the indexed documents."
    lines = ["Relevant passages from the knowledge base:"]
    for hit in context["hits"][:5]:
        page = f" (page {hit['page_start']})" if hit.get("page_start") else ""
        lines.append(f"\n[{hit['filename']}{page}]\n{hit['text']}")
    return "\n".join(lines)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    kb = get_knowledge_base()
    return {"status": "ok", "database": str(kb.db_path), "stats": kb.stats()}


@app.get("/api/documents")
async def documents() -> dict[str, Any]:
    kb = get_knowledge_base()
    return {"documents": kb.documents(), "stats": kb.stats()}


@app.post("/api/ingest/upload")
async def ingest_upload(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    kb = get_knowledge_base()
    results = []
    for file in files:
        if not file.filename:
            continue
        try:
            results.append(kb.ingest_bytes(file.filename, await file.read()))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _results(results)


@app.post("/api/ingest/folder")
async def ingest_folder(request: FolderRequest) -> dict[str, Any]:
    path = Path(request.folder_path).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder does not exist: {path}")
    if not _allowed_folder(path):
        raise HTTPException(status_code=403, detail="Folder is outside OFFLINE_QA_ALLOWED_ROOTS")
    try:
        results = get_knowledge_base().ingest_path(path, request.recursive)
        return _results(results)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/qa/query")
async def query(request: QueryRequest) -> dict[str, Any]:
    kb = get_knowledge_base()
    context = kb.answer_context(request.question, request.top_k)
    answer = await _ollama_answer(request.question, context["context"]) if request.use_llm else None
    return {"answer": answer or _extractive_answer(context), "llm_used": bool(answer),
            "related_topics": context["related_topics"], "sources": context["hits"]}


@app.get("/api/graph")
async def graph(topic: str | None = None, limit: int = 50) -> dict[str, Any]:
    return get_knowledge_base().graph(topic, max(1, min(limit, 200)))


@app.post("/api/qa/upload_folder")
async def backwards_compatible_upload(question: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Keep the original endpoint working while making ingestion persistent."""
    await ingest_upload(files)
    return await query(QueryRequest(question=question))


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return """
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Offline Knowledge Base</title><style>
body{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;background:#f4f7f6;color:#17202a}.card{background:#fff;border-radius:12px;padding:1.25rem;margin:1rem 0;box-shadow:0 2px 12px #0001}h1{margin-bottom:.25rem}input,button{font:inherit;padding:.7rem;border:1px solid #ccd4d8;border-radius:7px;box-sizing:border-box}input{width:100%;margin:.35rem 0 .8rem}button{background:#1259a8;color:#fff;cursor:pointer}.secondary{background:#3d556b}.row{display:grid;grid-template-columns:1fr 1fr;gap:1rem}#answer{white-space:pre-wrap;background:#eef8f0;padding:1rem;border-radius:8px;min-height:4rem}.muted{color:#5d6b75}.pill{display:inline-block;background:#e7eef8;padding:.3rem .55rem;border-radius:999px;margin:.15rem}@media(max-width:700px){.row{grid-template-columns:1fr}}
</style></head><body><h1>Offline Document Knowledge Base</h1><p class="muted">Ingest once. Search the persistent local index and topic graph without uploading the same files again.</p>
<div class="card"><h2>1. Ingest documents</h2><div class="row"><div><label>Upload files (deduplicated by SHA-256)</label><input id="files" type="file" multiple accept=".pdf,.docx,.docm,.xlsx,.xls,.csv,.txt,.md"><button onclick="upload()">Index selected files</button></div><div><label>Server-side folder path (Ubuntu/Linux)</label><input id="folder" placeholder="/srv/office-documents"><button class="secondary" onclick="scanFolder()">Scan folder once</button></div></div><p id="ingest" class="muted"></p></div>
<div class="card"><h2>2. Ask a question</h2><input id="question" placeholder="Which documents describe the procurement budget?"><button onclick="ask()">Search and answer</button><div id="answer">Ask a question after indexing documents.</div><div id="topics"></div></div><div class="card"><h2>Knowledge base</h2><p id="stats" class="muted">Loading…</p><button class="secondary" onclick="loadStats()">Refresh statistics</button></div>
<script>async function json(url,opts){let r=await fetch(url,opts);let d=await r.json();if(!r.ok)throw Error(d.detail||'Request failed');return d}async function loadStats(){let d=await json('/api/health');document.getElementById('stats').textContent=`${d.stats.documents} documents · ${d.stats.chunks} chunks · ${d.stats.topics} topics · ${d.stats.edges} topic links`}async function upload(){let fs=document.getElementById('files').files;if(!fs.length)return;let f=new FormData();for(let x of fs)f.append('files',x);try{let d=await json('/api/ingest/upload',{method:'POST',body:f});document.getElementById('ingest').textContent=JSON.stringify(d.files);loadStats()}catch(e){document.getElementById('ingest').textContent=e.message}}async function scanFolder(){let path=document.getElementById('folder').value;try{let d=await json('/api/ingest/folder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({folder_path:path})});document.getElementById('ingest').textContent=JSON.stringify(d.files);loadStats()}catch(e){document.getElementById('ingest').textContent=e.message}}async function ask(){let q=document.getElementById('question').value;if(!q)return;try{let d=await json('/api/qa/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})});document.getElementById('answer').textContent=d.answer;document.getElementById('topics').innerHTML=d.related_topics.map(t=>`<span class="pill">${t}</span>`).join('')}catch(e){document.getElementById('answer').textContent=e.message}}loadStats();</script></body></html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("OFFLINE_QA_HOST", "127.0.0.1"), port=int(os.getenv("OFFLINE_QA_PORT", "8000")), reload=False)
