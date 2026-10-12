"""Persistent offline document indexing, retrieval, and topic graph support.

The index is intentionally local: SQLite stores document metadata, extracted
chunks, an FTS5 search index, and the topic graph. A file is identified by its
SHA-256 hash, so uploading or scanning the same file again is a no-op.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".docm", ".xlsx", ".xls", ".csv", ".txt", ".md"
}
DEFAULT_DATA_DIR = Path(os.getenv("OFFLINE_QA_DATA_DIR", "data"))
DEFAULT_DB_PATH = Path(os.getenv("OFFLINE_QA_DB", str(DEFAULT_DATA_DIR / "knowledge.db")))

STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been",
    "before", "being", "between", "both", "but", "can", "could", "does",
    "each", "for", "from", "have", "has", "into", "its", "more", "most",
    "not", "only", "other", "our", "out", "over", "same", "should", "some",
    "such", "than", "that", "their", "there", "these", "they", "this", "those",
    "through", "under", "use", "used", "using", "was", "were", "what", "when",
    "where", "which", "while", "who", "will", "with", "would", "your", "you",
    "the", "a", "an", "as", "at", "by", "in", "is", "it", "of", "on", "or", "to",
}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]{2,}")


@dataclass
class ExtractedPage:
    text: str
    page_number: int | None = None


@dataclass
class IngestResult:
    filename: str
    sha256: str
    status: str
    chunks: int = 0
    topics: int = 0
    error: str | None = None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tokens(text: str) -> list[str]:
    return [t.lower().strip("'-_") for t in TOKEN_RE.findall(text)]


def extract_topics(text: str, limit: int = 12) -> list[tuple[str, float]]:
    """Return useful terms and short phrases for a lightweight local graph."""
    words = [w for w in _tokens(text) if w not in STOPWORDS and not w.isdigit()]
    counts = Counter(words)
    phrases = Counter(
        f"{a} {b}" for a, b in zip(words, words[1:])
        if a != b and len(a) > 3 and len(b) > 3
    )
    # Prefer terms that occur more than once; keep rare terms when the text is short.
    ranked: dict[str, float] = {}
    for term, count in counts.items():
        if count > 1 or len(words) < 80:
            ranked[term] = float(count)
    for phrase, count in phrases.items():
        if count > 1:
            ranked[phrase] = float(count) + 0.5
    return sorted(ranked.items(), key=lambda item: (-item[1], item[0]))[:limit]


def _chunk_pages(pages: Sequence[ExtractedPage], words_per_chunk: int = 220,
                overlap: int = 40) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page in pages:
        words = page.text.split()
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(start + words_per_chunk, len(words))
            chunks.append({
                "text": " ".join(words[start:end]),
                "page_start": page.page_number,
                "page_end": page.page_number,
            })
            if end >= len(words):
                break
            start = max(end - overlap, start + 1)
    return chunks


def _ocr_page_if_enabled(page: Any) -> str:
    """OCR only on demand; the base install remains usable without model files."""
    if os.getenv("OFFLINE_QA_ENABLE_OCR", "0").lower() not in {"1", "true", "yes"}:
        return ""
    try:
        import easyocr  # type: ignore
        import numpy as np  # type: ignore
        # The reader is cached on the module after the first scanned page.
        reader = getattr(_ocr_page_if_enabled, "reader", None)
        if reader is None:
            reader = easyocr.Reader([os.getenv("OFFLINE_QA_OCR_LANGUAGE", "en")],
                                    gpu=False, verbose=False)
            _ocr_page_if_enabled.reader = reader
        pix = page.get_pixmap()
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        return " ".join(reader.readtext(image, detail=0))
    except Exception:
        return ""


def extract_pages(filename: str, data: bytes) -> list[ExtractedPage]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        import pymupdf  # type: ignore
        doc = pymupdf.open(stream=data, filetype="pdf")
        pages: list[ExtractedPage] = []
        for number, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if not text:
                text = _ocr_page_if_enabled(page)
            if text:
                pages.append(ExtractedPage(text, number))
        return pages
    if ext in {".docx", ".docm"}:
        import docx  # type: ignore
        document = docx.Document(io.BytesIO(data))
        parts = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                values = [cell.text.strip() for cell in row.cells]
                if any(values):
                    parts.append(" | ".join(values))
        return [ExtractedPage("\n".join(parts), None)] if parts else []
    if ext in {".xlsx", ".xls"}:
        import pandas as pd  # type: ignore
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
        parts: list[str] = []
        for sheet_name, frame in sheets.items():
            parts.append(f"Excel sheet: {sheet_name}")
            parts.append(frame.fillna("").to_string(index=False))
        return [ExtractedPage("\n".join(parts), None)] if parts else []
    if ext == ".csv":
        return [ExtractedPage(data.decode("utf-8-sig", errors="replace"), None)]
    return [ExtractedPage(data.decode("utf-8-sig", errors="replace"), None)]


class KnowledgeBase:
    def __init__(self, db_path: str | os.PathLike[str] = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    sha256 TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    source_path TEXT,
                    extension TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    page_start INTEGER,
                    page_end INTEGER,
                    UNIQUE(document_id, chunk_index)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, filename);
                CREATE TABLE IF NOT EXISTS topics (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS document_topics (
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    weight REAL NOT NULL,
                    PRIMARY KEY(document_id, topic_id)
                );
                CREATE TABLE IF NOT EXISTS chunk_topics (
                    chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
                    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    weight REAL NOT NULL,
                    PRIMARY KEY(chunk_id, topic_id)
                );
                CREATE TABLE IF NOT EXISTS topic_edges (
                    topic_a INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    topic_b INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                    weight REAL NOT NULL,
                    PRIMARY KEY(topic_a, topic_b),
                    CHECK(topic_a < topic_b)
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
                CREATE INDEX IF NOT EXISTS idx_document_topics_topic ON document_topics(topic_id);
                CREATE INDEX IF NOT EXISTS idx_chunk_topics_topic ON chunk_topics(topic_id);
            """)

    def has_hash(self, digest: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM documents WHERE sha256=?", (digest,)).fetchone() is not None

    def _topic_id(self, conn: sqlite3.Connection, name: str) -> int:
        conn.execute("INSERT OR IGNORE INTO topics(name) VALUES (?)", (name,))
        return int(conn.execute("SELECT id FROM topics WHERE name=?", (name,)).fetchone()[0])

    def ingest_bytes(self, filename: str, data: bytes, source_path: str | None = None) -> IngestResult:
        digest = sha256_bytes(data)
        with self._lock:
            if self.has_hash(digest):
                return IngestResult(filename, digest, "already_indexed")
            try:
                pages = extract_pages(filename, data)
                chunks = _chunk_pages(pages)
                if not chunks:
                    return IngestResult(filename, digest, "empty")
                all_text = "\n".join(c["text"] for c in chunks)
                doc_topics = extract_topics(all_text)
                with self._connect() as conn:
                    cur = conn.execute(
                        "INSERT INTO documents(sha256,filename,source_path,extension,size_bytes) VALUES(?,?,?,?,?)",
                        (digest, Path(filename).name, source_path, Path(filename).suffix.lower(), len(data)),
                    )
                    document_id = int(cur.lastrowid)
                    topic_ids = {name: self._topic_id(conn, name) for name, _ in doc_topics}
                    for name, weight in doc_topics:
                        conn.execute("INSERT INTO document_topics VALUES (?,?,?)",
                                     (document_id, topic_ids[name], weight))
                    chunk_topic_sets: list[list[int]] = []
                    for index, chunk in enumerate(chunks):
                        cur = conn.execute(
                            "INSERT INTO chunks(document_id,chunk_index,text,page_start,page_end) VALUES(?,?,?,?,?)",
                            (document_id, index, chunk["text"], chunk["page_start"], chunk["page_end"]),
                        )
                        chunk_id = int(cur.lastrowid)
                        conn.execute("INSERT INTO chunks_fts(rowid,text,filename) VALUES(?,?,?)",
                                     (chunk_id, chunk["text"], Path(filename).name))
                        chunk_topics = extract_topics(chunk["text"], limit=8)
                        ids: list[int] = []
                        for name, weight in chunk_topics:
                            topic_id = self._topic_id(conn, name)
                            ids.append(topic_id)
                            conn.execute("INSERT OR REPLACE INTO chunk_topics VALUES (?,?,?)",
                                         (chunk_id, topic_id, weight))
                        chunk_topic_sets.append(ids)
                    # Co-occurrence edges connect the document's strongest topics.
                    for left, left_id in enumerate([topic_ids[n] for n, _ in doc_topics]):
                        for right_id in [topic_ids[n] for n, _ in doc_topics][left + 1:]:
                            a, b = sorted((left_id, right_id))
                            conn.execute(
                                "INSERT INTO topic_edges(topic_a,topic_b,weight) VALUES(?,?,1) "
                                "ON CONFLICT(topic_a,topic_b) DO UPDATE SET weight=weight+1", (a, b))
                    return IngestResult(filename, digest, "indexed", len(chunks), len(doc_topics))
            except Exception as exc:
                return IngestResult(filename, digest, "error", error=str(exc))

    def ingest_path(self, path: str | os.PathLike[str], recursive: bool = True) -> list[IngestResult]:
        root = Path(path).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(str(root))
        candidates = root.rglob("*") if recursive else root.glob("*")
        results: list[IngestResult] = []
        for file_path in sorted(p for p in candidates if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS):
            try:
                results.append(self.ingest_bytes(file_path.name, file_path.read_bytes(), str(file_path)))
            except OSError as exc:
                results.append(IngestResult(file_path.name, "", "error", error=str(exc)))
        return results

    @staticmethod
    def _fts_query(query: str) -> str:
        terms = [t for t in _tokens(query) if t not in STOPWORDS]
        return " OR ".join(f'"{t.replace(chr(34), "")}"' for t in terms[:24])

    def related_topics(self, query: str, limit: int = 8) -> list[str]:
        terms = set(_tokens(query))
        with self._connect() as conn:
            rows = conn.execute("SELECT id,name FROM topics").fetchall()
            matched = {int(row["id"]): row["name"] for row in rows
                       if row["name"] in terms or any(part in terms for part in row["name"].split())}
            if not matched:
                return []
            scores: defaultdict[int, float] = defaultdict(float)
            for topic_id in matched:
                for row in conn.execute(
                    "SELECT CASE WHEN topic_a=? THEN topic_b ELSE topic_a END id, weight "
                    "FROM topic_edges WHERE topic_a=? OR topic_b=?", (topic_id, topic_id, topic_id)):
                    scores[int(row["id"])] += float(row["weight"])
            names = {int(row["id"]): row["name"] for row in rows}
            return [names[i] for i, _ in sorted(scores.items(), key=lambda x: -x[1])[:limit]
                    if i in names]

    def search(self, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        fts_query = self._fts_query(query)
        expanded = self.related_topics(query)
        if expanded:
            fts_query = " OR ".join(filter(None, [fts_query] + [self._fts_query(t) for t in expanded]))
        if not fts_query:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT f.rowid chunk_id, f.filename, f.text, bm25(chunks_fts) score, "
                "c.page_start, c.page_end, d.source_path, d.sha256 "
                "FROM chunks_fts f JOIN chunks c ON c.id=f.rowid JOIN documents d ON d.id=c.document_id "
                "WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?", (fts_query, top_k)
            ).fetchall()
            return [dict(row) for row in rows]

    def answer_context(self, query: str, top_k: int = 8, max_chars: int = 14000) -> dict[str, Any]:
        hits = self.search(query, top_k)
        context_parts: list[str] = []
        used = 0
        for hit in hits:
            source = hit["filename"]
            page = f" page {hit['page_start']}" if hit.get("page_start") else ""
            part = f"[{source}{page}]\n{hit['text']}"
            if used + len(part) > max_chars:
                break
            context_parts.append(part)
            used += len(part)
        return {"hits": hits, "context": "\n\n".join(context_parts), "related_topics": self.related_topics(query)}

    def documents(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,filename,source_path,extension,size_bytes,ingested_at "
                "FROM documents ORDER BY ingested_at DESC").fetchall()]

    def graph(self, topic: str | None = None, limit: int = 50) -> dict[str, Any]:
        with self._connect() as conn:
            if topic:
                match = conn.execute("SELECT id,name FROM topics WHERE name LIKE ? LIMIT 1",
                                     (f"%{topic.lower()}%",)).fetchone()
                if not match:
                    return {"nodes": [], "edges": []}
                topic_id = int(match["id"])
                edge_rows = conn.execute(
                    "SELECT topic_a,topic_b,weight FROM topic_edges WHERE topic_a=? OR topic_b=? "
                    "ORDER BY weight DESC LIMIT ?", (topic_id, topic_id, limit)).fetchall()
            else:
                edge_rows = conn.execute(
                    "SELECT topic_a,topic_b,weight FROM topic_edges ORDER BY weight DESC LIMIT ?", (limit,)).fetchall()
            ids = {int(row["topic_a"]) for row in edge_rows} | {int(row["topic_b"]) for row in edge_rows}
            if topic and 'topic_id' in locals():
                ids.add(topic_id)
            nodes = []
            for row in conn.execute("SELECT id,name FROM topics WHERE id IN ({})".format(
                    ",".join("?" for _ in ids) if ids else "NULL"), tuple(ids)):
                count = conn.execute("SELECT COUNT(*) FROM document_topics WHERE topic_id=?", (row["id"],)).fetchone()[0]
                nodes.append({"id": row["id"], "label": row["name"], "documents": count})
            return {"nodes": nodes, "edges": [dict(row) for row in edge_rows]}

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "topics": conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0],
                "edges": conn.execute("SELECT COUNT(*) FROM topic_edges").fetchone()[0],
            }


_DEFAULT_KB: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    global _DEFAULT_KB
    if _DEFAULT_KB is None:
        _DEFAULT_KB = KnowledgeBase()
    return _DEFAULT_KB
