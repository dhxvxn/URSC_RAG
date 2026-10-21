"""MCP adapter for the persistent notebook QA service.

Run this over stdio for a local MCP client. It uses the same SQLite database,
embedding index, documents, and images as the FastAPI application.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from main import (
    ask_ollama,
    create_notebook_record,
    db,
    extractive_fallback,
    ingest_document,
    retrieve,
)


mcp = FastMCP("Offline_Notebook_Document_QA")


@mcp.tool()
def list_notebooks() -> list[dict]:
    """List notebooks and the number of documents indexed in each one."""
    with db() as connection:
        rows = connection.execute(
            "SELECT n.id, n.name, COUNT(nd.document_id) AS documents FROM notebooks n "
            "LEFT JOIN notebook_documents nd ON nd.notebook_id = n.id GROUP BY n.id ORDER BY n.created_at"
        ).fetchall()
    return [dict(row) for row in rows]


@mcp.tool()
def create_notebook(name: str) -> dict[str, str]:
    """Create a persistent notebook used to scope later retrieval."""
    return create_notebook_record(name)


@mcp.tool()
def ingest_folder(notebook_id: str, folder_path: str) -> list[dict]:
    """Recursively index supported files into a notebook.

    Files are content-hash deduplicated, so running this again after adding a
    file only embeds new or changed content.
    """
    root = Path(folder_path).expanduser().resolve()
    if not root.is_dir():
        return [{"status": "error", "reason": f"Folder does not exist: {root}"}]
    results = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            try:
                results.append(ingest_document(notebook_id, str(path.relative_to(root)), path.read_bytes()))
            except Exception as error:
                results.append({"filename": str(path), "status": "error", "reason": str(error)})
    return results


@mcp.tool()
async def ask_notebook(notebook_id: str, question: str, top_k: int = 8) -> dict:
    """Retrieve and answer a question using only one notebook's indexed content."""
    hits, images = retrieve(notebook_id, question, top_k)
    answer = await ask_ollama(question, hits, images)
    return {
        "answer": answer or extractive_fallback(hits),
        "sources": hits,
        "images": [{**image, "url": f"/media/{image['stored_path']}"} for image in images],
    }


if __name__ == "__main__":
    mcp.run()
