"""MCP interface for the same persistent local knowledge base used by the web API."""

from __future__ import annotations

import json

from knowledge_base import get_knowledge_base

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
except ImportError as exc:  # pragma: no cover - gives a useful setup error
    raise SystemExit("Install the optional MCP dependency with: pip install mcp") from exc

mcp = FastMCP("Offline_Document_Knowledge_Base")


@mcp.tool()
def ingest_local_folder(folder_path: str, recursive: bool = True) -> str:
    """Index PDF, Word, Excel, CSV, Markdown, and text files once from a local folder."""
    results = get_knowledge_base().ingest_path(folder_path, recursive)
    return json.dumps({"files": [item.__dict__ for item in results],
                       "stats": get_knowledge_base().stats()}, indent=2)


@mcp.tool()
def search_knowledge_base(query: str, top_k: int = 8) -> str:
    """Search the persistent local index and return ranked passages plus related topics."""
    context = get_knowledge_base().answer_context(query, top_k)
    return json.dumps({"related_topics": context["related_topics"], "sources": context["hits"]}, indent=2)


@mcp.tool()
async def query_local_documents(folder_path: str, question: str, top_k: int = 8) -> str:
    """Index a folder if needed, then answer from the persistent local knowledge base."""
    get_knowledge_base().ingest_path(folder_path)
    context = get_knowledge_base().answer_context(question, top_k)
    return json.dumps({"question": question, "related_topics": context["related_topics"],
                       "sources": context["hits"], "context": context["context"]}, indent=2)


@mcp.tool()
def get_knowledge_graph(topic: str | None = None, limit: int = 50) -> str:
    """Return topic nodes and co-occurrence edges for exploration or visualization."""
    return json.dumps(get_knowledge_base().graph(topic, limit), indent=2)


if __name__ == "__main__":
    mcp.run()
