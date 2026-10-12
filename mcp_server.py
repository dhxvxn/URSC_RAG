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
    allowed = os.environ.get("ALLOWED_DOCUMENT_ROOT")
    if allowed:
        permitted = Path(allowed).resolve()
        if root != permitted and permitted not in root.parents:
            raise ValueError(f"Folder must be inside ALLOWED_DOCUMENT_ROOT ({permitted})")
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
        return f"Error: {exc}"


@mcp.tool()
async def query_local_documents(folder_path: str, question: str) -> str:
    """Index a folder if needed, then answer from the persistent knowledge base."""
    ingest_result = ingest_local_folder(folder_path)
    if ingest_result.startswith("Error:"):
        return ingest_result
    try:
        return await answer(question)
    except RuntimeError as exc:
        return f"Error: {exc}"


@mcp.tool()
def knowledge_graph(query: str = "", limit: int = 30) -> str:
    """Return topic and entity relationships with query-relevant graph seeds."""
    return str(kb.graph(query or None, max(1, min(limit, 100))))


if __name__ == "__main__":
    mcp.run()
