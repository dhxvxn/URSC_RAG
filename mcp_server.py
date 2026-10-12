"""MCP tools backed by the same persistent database as the web API."""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from knowledge_base import KnowledgeBase, ask_ollama


mcp = FastMCP("Local_Office_Knowledge_Base")
kb = KnowledgeBase()


def allowed_folder(folder_path: str) -> Path:
    root = Path(folder_path).resolve()
    if os.environ.get("OFFLINE_QA_ALLOW_ANY_PATH", "0").lower() in {"1", "true", "yes"}:
        return root
    allowed = os.environ.get("ALLOWED_DOCUMENT_ROOT") or os.environ.get("OFFLINE_QA_ALLOWED_ROOTS") or str(Path.cwd())
    roots = [Path(item).expanduser().resolve() for item in allowed.split(os.pathsep) if item.strip()]
    if not any(root == permitted or permitted in root.parents for permitted in roots):
        raise ValueError(f"Folder must be inside an approved document root ({', '.join(map(str, roots))})")
    return root


async def answer(question: str, top_k: int = 8) -> str:
    context, sources, graph = kb.context(question, top_k)
    response = await ask_ollama(question, context)
    source_lines = "\n".join(f"- {s['filename']} ({s['location']})" for s in sources)
    return f"{response}\n\nSources:\n{source_lines}\n\nRelated topics: {', '.join(t['display_name'] for t in graph['topics'][:10])}"


@mcp.tool()
def ingest_local_folder(folder_path: str) -> str:
    """Index PDF, Word, and Excel files in a local folder once.

    Files are identified by SHA-256 content hash, so repeating this operation
    does not extract or index unchanged documents again.
    """
    try:
        results = kb.ingest_folder(allowed_folder(folder_path))
        return str({"documents": results, "database": kb.db_path})
    except (ValueError, OSError, RuntimeError) as exc:
        return f"Error: {exc}"


@mcp.tool()
async def query_knowledge_base(question: str, top_k: int = 8) -> str:
    """Search indexed documents with hybrid keyword and semantic retrieval."""
    try:
        return await answer(question, top_k)
    except RuntimeError as exc:
        context, sources, _ = kb.context(question, top_k)
        passages = "\n\n".join(f"[{s['filename']} — {s['location']}]\n{s['text']}" for s in sources[:5])
        return f"Ollama unavailable ({exc}). Relevant passages:\n\n{passages}" if passages else f"Error: {exc}"


@mcp.tool()
async def query_local_documents(folder_path: str, question: str) -> str:
    """Index a folder if needed, then answer from the persistent knowledge base."""
    ingest_result = ingest_local_folder(folder_path)
    if ingest_result.startswith("Error:"):
        return ingest_result
    try:
        return await answer(question)
    except RuntimeError as exc:
        return await query_knowledge_base(question)


@mcp.tool()
def knowledge_graph(query: str = "", limit: int = 30) -> str:
    """Return topic and entity relationships with query-relevant graph seeds."""
    return str(kb.graph(query or None, max(1, min(limit, 100))))


@mcp.tool()
async def search_knowledge_base(question: str, top_k: int = 8) -> str:
    """Compatibility alias for clients that call the search tool by this name."""
    context, sources, graph = kb.context(question, top_k)
    return str({"sources": sources, "topics": graph["topics"], "context": context})


@mcp.tool()
def get_knowledge_graph(query: str = "", limit: int = 30) -> str:
    """Compatibility alias for graph clients."""
    return knowledge_graph(query, limit)


if __name__ == "__main__":
    mcp.run()
