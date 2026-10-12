"""Persistent, offline document knowledge base.

The database is deliberately SQLite so an office installation has one portable
file to back up.  FTS5 handles exact terms and a small local embedding index
handles fuzzy matches.  If a sentence-transformers model is configured it is
used; otherwise a deterministic hashing vector keeps the system fully offline.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import struct
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx
import numpy as np
import pandas as pd
import pymupdf
import docx


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".docm", ".xlsx", ".xls", ".csv", ".txt", ".md"}
DB_PATH = os.environ.get("KNOWLEDGE_DB_PATH", os.environ.get("OFFLINE_QA_DB", "data/knowledge.db"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3")
MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", str(100 * 1024 * 1024)))

_OCR_READER: Any = None
_EMBEDDER: Any = None

STOP_WORDS = {
    "about", "after", "again", "against", "also", "because", "being", "between",
    "could", "does", "from", "have", "into", "more", "other", "over", "same",
    "should", "that", "their", "there", "these", "they", "this", "those", "under",
    "using", "were", "which", "while", "with", "would", "your", "document", "page",
    "sheet", "table", "shall", "will", "than", "then", "them", "only", "such",
    "the", "and", "for", "are", "was", "has", "from", "onto", "into", "not", "but",
    "all", "any", "can", "may", "our", "out", "its", "via", "per", "one", "two",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_path() -> str:
    return DB_PATH


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    initialize(conn)
    return conn


def initialize(conn: sqlite3.Connection | None = None) -> None:
    owned = conn is None
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = conn or sqlite3.connect(DB_PATH, timeout=30)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            source_path TEXT,
            extension TEXT NOT NULL,
            byte_size INTEGER NOT NULL,
            content_hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'ready',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            location TEXT NOT NULL,
            text TEXT NOT NULL,
            UNIQUE(document_id, ordinal)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            chunk_id UNINDEXED, text, filename, topics
        );
        CREATE TABLE IF NOT EXISTS chunk_vectors (
            chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
            dimensions INTEGER NOT NULL,
            vector BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            frequency INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chunk_topics (
            chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            weight REAL NOT NULL DEFAULT 1,
            PRIMARY KEY(chunk_id, topic_id)
        );
        CREATE TABLE IF NOT EXISTS topic_relations (
            subject_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            predicate TEXT NOT NULL,
            object_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            weight INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(subject_id, predicate, object_id)
        );
        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            entity_type TEXT NOT NULL DEFAULT 'term',
            frequency INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chunk_entities (
            chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            confidence REAL NOT NULL DEFAULT 0.5,
            PRIMARY KEY(chunk_id, entity_id)
        );
        CREATE TABLE IF NOT EXISTS entity_relations (
            subject_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            predicate TEXT NOT NULL,
            object_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            evidence_chunk_id INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
            confidence REAL NOT NULL DEFAULT 0.35,
            PRIMARY KEY(subject_id, predicate, object_id, evidence_chunk_id)
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_chunk_topics_topic ON chunk_topics(topic_id);
        CREATE INDEX IF NOT EXISTS idx_chunk_entities_entity ON chunk_entities(entity_id);
        """
    )
    conn.commit()
    if owned:
        conn.close()


def _reader() -> Any:
    global _OCR_READER
    if _OCR_READER is None:
        import easyocr
        _OCR_READER = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _OCR_READER


def extract_pdf(data: bytes) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    doc = pymupdf.open(stream=data, filetype="pdf")
    for page_no, page in enumerate(doc, 1):
        text = page.get_text().strip()
        if not text:
            pix = page.get_pixmap()
            image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            text = " ".join(_reader().readtext(image, detail=0)).strip()
        if text:
            result.append((f"page {page_no}", text))
    return result


def extract_docx(data: bytes) -> list[tuple[str, str]]:
    document = docx.Document(io.BytesIO(data))
    result = [(f"paragraph {i}", p.text.strip()) for i, p in enumerate(document.paragraphs, 1) if p.text.strip()]
    for table_no, table in enumerate(document.tables, 1):
        rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
        text = "\n".join(row for row in rows if row.strip())
        if text:
            result.append((f"table {table_no}", text))
    return result


def extract_text_file(data: bytes) -> list[tuple[str, str]]:
    return [("text", data.decode("utf-8-sig", errors="replace"))]


def extract_excel(data: bytes) -> list[tuple[str, str]]:
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    result = []
    for name, frame in sheets.items():
        text = frame.fillna("").to_string(index=False).strip()
        if text:
            result.append((f"sheet {name}", text))
    return result


def extract_document(filename: str, data: bytes) -> list[tuple[str, str]]:
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        return extract_pdf(data)
    if extension == ".docx":
        return extract_docx(data)
    if extension == ".docm":
        return extract_docx(data)
    if extension in {".xlsx", ".xls"}:
        return extract_excel(data)
    if extension in {".csv", ".txt", ".md"}:
        return extract_text_file(data)
    raise ValueError(f"Unsupported document type: {extension or 'none'}")


def chunk_text(sections: Iterable[tuple[str, str]], size: int = 1400, overlap: int = 180) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    for location, section in sections:
        words = section.split()
        if not words:
            continue
        start = 0
        part = 0
        while start < len(words):
            current: list[str] = []
            length = 0
            end = start
            while end < len(words) and (length + len(words[end]) + 1 <= size or not current):
                current.append(words[end])
                length += len(words[end]) + 1
                end += 1
            chunks.append((f"{location}, segment {part + 1}", " ".join(current)))
            part += 1
            if end >= len(words):
                break
            overlap_words = max(1, int(overlap / 7))
            start = max(start + 1, end - overlap_words)
    return chunks


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text) if t.lower() not in STOP_WORDS]


def topics_for(text: str, limit: int = 8) -> list[str]:
    counts = Counter(_tokens(text))
    return [word for word, _ in counts.most_common(limit)]


def entities_for(text: str) -> list[tuple[str, str, float]]:
    found: dict[str, tuple[str, float]] = {}
    patterns = [
        (r"\b[A-Z]{2,}[A-Z0-9_-]*\b", "acronym", 0.75),
        (r"\b[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){1,2}\b", "proper_noun", 0.65),
        (r"\b(?:ISO|MIL|DOC|PROJ|REQ)[-_]?[A-Z0-9-]+\b", "identifier", 0.85),
    ]
    for pattern, kind, confidence in patterns:
        for match in re.findall(pattern, text):
            name = re.sub(r"\s+", " ", match).strip()
            if len(name) >= 3 and name.lower() not in STOP_WORDS:
                found.setdefault(name, (kind, confidence))
    return [(name, kind, confidence) for name, (kind, confidence) in found.items()]


def relations_for(text: str) -> list[tuple[str, str, str, float]]:
    """Extract conservative typed relations and retain sentence-level evidence."""
    entities = entities_for(text)
    relations = []
    predicates = (
        ("depends_on", ("depends on", "requires", "required by")),
        ("uses", ("uses", "utilizes", "employs")),
        ("belongs_to", ("belongs to", "part of", "member of")),
        ("approved_by", ("approved by", "authorized by")),
        ("replaces", ("replaces", "supersedes")),
    )
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        present = [name for name, _, _ in entities if name in sentence]
        if len(present) < 2:
            continue
        predicate = "related_to"
        lowered = sentence.lower()
        for candidate, phrases in predicates:
            if any(phrase in lowered for phrase in phrases):
                predicate = candidate
                break
        for left, right in zip(present, present[1:]):
            relations.append((left, predicate, right, 0.65 if predicate != "related_to" else 0.35))
    return relations


class HashingEmbedder:
    """Small, deterministic offline vectors used when no model is installed."""

    dimensions = 384

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            words = _tokens(text)
            features = words + [f"{a}:{b}" for a, b in zip(words, words[1:])]
            for feature in features:
                digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
                index = struct.unpack("Q", digest)[0] % self.dimensions
                vectors[row, index] += 1.0
            norm = np.linalg.norm(vectors[row])
            if norm:
                vectors[row] /= norm
        return vectors


def embedder() -> Any:
    global _EMBEDDER
    if _EMBEDDER is None:
        model_name = os.environ.get("EMBEDDING_MODEL")
        if model_name:
            try:
                from sentence_transformers import SentenceTransformer
                _EMBEDDER = SentenceTransformer(model_name)
            except Exception:
                _EMBEDDER = HashingEmbedder()
        else:
            _EMBEDDER = HashingEmbedder()
    return _EMBEDDER


def _vector_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def _vector_from_blob(blob: bytes, dimensions: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32, count=dimensions)


class KnowledgeBase:
    def __init__(self, db_path: str | None = None):
        global DB_PATH
        if db_path and db_path != DB_PATH:
            self.db_path = db_path
        else:
            self.db_path = DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        if self.db_path != DB_PATH:
            connection = sqlite3.connect(self.db_path)
            initialize(connection)
            connection.close()
        else:
            initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def ingest_bytes(self, filename: str, data: bytes, source_path: str | None = None) -> dict[str, Any]:
        safe_name = Path(filename or "document").name
        extension = Path(safe_name).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported document type: {extension or 'none'}")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"File exceeds MAX_FILE_BYTES ({MAX_FILE_BYTES} bytes)")
        digest = hashlib.sha256(data).hexdigest()
        conn = self._connect()
        existing = conn.execute("SELECT id, filename FROM documents WHERE content_hash=?", (digest,)).fetchone()
        if existing:
            conn.close()
            return {"document_id": existing["id"], "filename": existing["filename"], "status": "existing", "chunks": 0}
        sections = extract_document(safe_name, data)
        chunks = chunk_text(sections)
        document_id = digest
        now = utc_now()
        conn.execute(
            "INSERT INTO documents(id,filename,source_path,extension,byte_size,content_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (document_id, safe_name, source_path, extension, len(data), digest, now, now),
        )
        vector_model = embedder()
        vectors = vector_model.encode([text for _, text in chunks]) if chunks else np.empty((0, 384), dtype=np.float32)
        for ordinal, ((location, text), vector) in enumerate(zip(chunks, vectors)):
            cur = conn.execute("INSERT INTO chunks(document_id,ordinal,location,text) VALUES(?,?,?,?)", (document_id, ordinal, location, text))
            chunk_id = cur.lastrowid
            topic_names = topics_for(text)
            conn.execute("INSERT INTO chunks_fts(chunk_id,text,filename,topics) VALUES(?,?,?,?)", (chunk_id, text, safe_name, " ".join(topic_names)))
            conn.execute("INSERT INTO chunk_vectors(chunk_id,dimensions,vector) VALUES(?,?,?)", (chunk_id, int(len(vector)), _vector_blob(vector)))
            topic_ids = []
            for topic_name in topic_names:
                row = conn.execute("SELECT id FROM topics WHERE name=?", (topic_name,)).fetchone()
                if row:
                    topic_id = row["id"]
                    conn.execute("UPDATE topics SET frequency=frequency+1 WHERE id=?", (topic_id,))
                else:
                    cur_topic = conn.execute("INSERT INTO topics(name,display_name,frequency) VALUES(?,?,1)", (topic_name, topic_name.replace("_", " ").title()))
                    topic_id = cur_topic.lastrowid
                topic_ids.append(topic_id)
                conn.execute("INSERT INTO chunk_topics(chunk_id,topic_id,weight) VALUES(?,?,?)", (chunk_id, topic_id, 1.0))
            for left in topic_ids:
                for right in topic_ids:
                    if left < right:
                        conn.execute(
                            "INSERT INTO topic_relations(subject_id,predicate,object_id,weight) VALUES(?,?,?,1) ON CONFLICT(subject_id,predicate,object_id) DO UPDATE SET weight=weight+1",
                            (left, "related_to", right),
                        )
            entity_ids = []
            for name, kind, confidence in entities_for(text):
                row = conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
                if row:
                    entity_id = row["id"]
                    conn.execute("UPDATE entities SET frequency=frequency+1 WHERE id=?", (entity_id,))
                else:
                    entity_id = conn.execute("INSERT INTO entities(name,entity_type,frequency) VALUES(?,?,1)", (name, kind)).lastrowid
                entity_ids.append(entity_id)
                conn.execute("INSERT INTO chunk_entities(chunk_id,entity_id,confidence) VALUES(?,?,?)", (chunk_id, entity_id, confidence))
            for left in entity_ids:
                for right in entity_ids:
                    if left != right:
                        conn.execute(
                            "INSERT OR IGNORE INTO entity_relations(subject_id,predicate,object_id,evidence_chunk_id,confidence) VALUES(?,?,?,?,?)",
                            (left, "related_to", right, chunk_id, 0.35),
                        )
            entity_by_name = {name: entity_id for (name, _, _), entity_id in zip(entities_for(text), entity_ids)}
            for subject, predicate, object_name, confidence in relations_for(text):
                if subject in entity_by_name and object_name in entity_by_name and subject != object_name:
                    conn.execute(
                        "INSERT OR IGNORE INTO entity_relations(subject_id,predicate,object_id,evidence_chunk_id,confidence) VALUES(?,?,?,?,?)",
                        (entity_by_name[subject], predicate, entity_by_name[object_name], chunk_id, confidence),
                    )
        conn.commit()
        conn.close()
        return {"document_id": document_id, "filename": safe_name, "status": "indexed", "chunks": len(chunks)}

    def ingest_path(self, path: str | Path) -> dict[str, Any]:
        resolved = Path(path).resolve()
        return self.ingest_bytes(resolved.name, resolved.read_bytes(), str(resolved))

    def ingest_folder(self, folder: str | Path, recursive: bool = True) -> list[dict[str, Any]]:
        root = Path(folder).resolve()
        if not root.is_dir():
            raise ValueError(f"Folder does not exist: {root}")
        results = []
        candidates = root.rglob("*") if recursive else root.glob("*")
        for path in sorted(p for p in candidates if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS):
            results.append(self.ingest_path(path))
        return results

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(limit, 50))
        conn = self._connect()
        terms = _tokens(query)
        fts_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms) or '""'
        lexical: dict[int, float] = {}
        try:
            rows = conn.execute("SELECT chunk_id, bm25(chunks_fts) AS rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT 100", (fts_query,)).fetchall()
            for rank, row in enumerate(rows):
                lexical[row["chunk_id"]] = 1.0 / (1.0 + rank)
        except sqlite3.OperationalError:
            pass
        qvec = embedder().encode([query])[0]
        vectors = conn.execute("SELECT chunk_id,dimensions,vector FROM chunk_vectors").fetchall()
        semantic: dict[int, float] = {}
        for row in vectors:
            vec = _vector_from_blob(row["vector"], row["dimensions"])
            score = float(np.dot(qvec, vec)) if len(qvec) == len(vec) else 0.0
            if score > 0:
                semantic[row["chunk_id"]] = score
        candidates = set(lexical) | set(sorted(semantic, key=semantic.get, reverse=True)[:100])
        scored = []
        for chunk_id in candidates:
            score = 0.62 * lexical.get(chunk_id, 0.0) + 0.38 * semantic.get(chunk_id, 0.0)
            # Hashing vectors are intentionally conservative.  A small
            # threshold prevents unrelated short chunks from surfacing merely
            # because they share a common character bucket.
            if score < 0.08:
                continue
            row = conn.execute(
                """SELECT c.id,c.text,c.location,d.id AS document_id,d.filename,
                   GROUP_CONCAT(DISTINCT t.display_name) AS topics
                   FROM chunks c JOIN documents d ON d.id=c.document_id
                   LEFT JOIN chunk_topics ct ON ct.chunk_id=c.id
                   LEFT JOIN topics t ON t.id=ct.topic_id WHERE c.id=? GROUP BY c.id""", (chunk_id,),
            ).fetchone()
            if row:
                scored.append((score, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        results = []
        for score, row in scored[:limit]:
            results.append({"chunk_id": row["id"], "document_id": row["document_id"], "filename": row["filename"], "location": row["location"], "text": row["text"], "score": round(float(score), 5), "topics": (row["topics"] or "").split(",") if row["topics"] else []})
        conn.close()
        return results

    def graph(self, query: str | None = None, limit: int = 30) -> dict[str, Any]:
        conn = self._connect()
        seed_chunks = [r["chunk_id"] for r in self.search(query, 3)] if query else []
        if seed_chunks:
            marks = ",".join("?" * len(seed_chunks))
            topics = conn.execute(f"SELECT DISTINCT t.id,t.name,t.display_name FROM topics t JOIN chunk_topics ct ON ct.topic_id=t.id WHERE ct.chunk_id IN ({marks})", seed_chunks).fetchall()
        else:
            topics = conn.execute("SELECT id,name,display_name FROM topics ORDER BY frequency DESC LIMIT ?", (limit,)).fetchall()
        topic_ids = [r["id"] for r in topics]
        relations = []
        if topic_ids:
            marks = ",".join("?" * len(topic_ids))
            relations = conn.execute(f"SELECT subject_id,predicate,object_id,weight FROM topic_relations WHERE subject_id IN ({marks}) OR object_id IN ({marks}) ORDER BY weight DESC LIMIT ?", topic_ids + topic_ids + [limit * 3]).fetchall()
        if seed_chunks:
            marks = ",".join("?" * len(seed_chunks))
            entities = conn.execute(
                f"SELECT DISTINCT e.id,e.name,e.entity_type,e.frequency FROM entities e JOIN chunk_entities ce ON ce.entity_id=e.id WHERE ce.chunk_id IN ({marks}) ORDER BY e.frequency DESC LIMIT ?",
                seed_chunks + [limit],
            ).fetchall()
        else:
            entities = conn.execute("SELECT id,name,entity_type,frequency FROM entities ORDER BY frequency DESC LIMIT ?", (limit,)).fetchall()
        relation_filter = ""
        relation_params: list[Any] = [limit * 3]
        if seed_chunks:
            marks = ",".join("?" * len(seed_chunks))
            relation_filter = f"WHERE er.evidence_chunk_id IN ({marks})"
            relation_params = seed_chunks + [limit * 3]
        entity_relations = conn.execute(
            f"""SELECT s.name AS subject, er.predicate, o.name AS object,
                      er.confidence, er.evidence_chunk_id, d.filename, c.location
               FROM entity_relations er
               JOIN entities s ON s.id=er.subject_id JOIN entities o ON o.id=er.object_id
               LEFT JOIN chunks c ON c.id=er.evidence_chunk_id
               LEFT JOIN documents d ON d.id=c.document_id
               {relation_filter}
               ORDER BY er.confidence DESC LIMIT ?""", relation_params
        ).fetchall()
        conn.close()
        return {
            "topics": [dict(row) for row in topics],
            "topic_relations": [dict(row) for row in relations],
            "entities": [dict(row) for row in entities],
            "entity_relations": [dict(row) for row in entity_relations],
        }

    def documents(self) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute("SELECT d.*,COUNT(c.id) AS chunks FROM documents d LEFT JOIN chunks c ON c.document_id=d.id GROUP BY d.id ORDER BY d.updated_at DESC").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def remove_document(self, document_id: str) -> bool:
        conn = self._connect()
        row = conn.execute("SELECT id FROM documents WHERE id=?", (document_id,)).fetchone()
        if not row:
            conn.close()
            return False
        chunk_ids = [r["id"] for r in conn.execute("SELECT id FROM chunks WHERE document_id=?", (document_id,)).fetchall()]
        if chunk_ids:
            marks = ",".join("?" * len(chunk_ids))
            conn.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({marks})", chunk_ids)
        conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
        conn.execute("DELETE FROM topic_relations WHERE subject_id IN (SELECT id FROM topics WHERE id NOT IN (SELECT DISTINCT topic_id FROM chunk_topics)) OR object_id IN (SELECT id FROM topics WHERE id NOT IN (SELECT DISTINCT topic_id FROM chunk_topics))")
        conn.execute("DELETE FROM topics WHERE id NOT IN (SELECT DISTINCT topic_id FROM chunk_topics)")
        conn.execute("DELETE FROM entity_relations WHERE subject_id IN (SELECT id FROM entities WHERE id NOT IN (SELECT DISTINCT entity_id FROM chunk_entities)) OR object_id IN (SELECT id FROM entities WHERE id NOT IN (SELECT DISTINCT entity_id FROM chunk_entities))")
        conn.execute("DELETE FROM entities WHERE id NOT IN (SELECT DISTINCT entity_id FROM chunk_entities)")
        conn.commit()
        conn.close()
        return True

    def context(self, query: str, limit: int = 8) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        results = self.search(query, limit)
        graph = self.graph(query, 20)
        context = "\n\n".join(f"[{r['filename']} — {r['location']}]\n{r['text']}" for r in results)
        return context, results, graph


async def ask_ollama(question: str, context: str, model: str | None = None) -> str:
    if not context:
        return "I could not find relevant indexed content for that question."
    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": "Answer only from the supplied office documents. Cite the source filename and location for each material claim. If the context is insufficient, say so."},
            {"role": "user", "content": f"Context:\n{context[:18000]}\n\nQuestion: {question}"},
        ],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(OLLAMA_URL, json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Ollama is unavailable: {exc}") from exc
    if response.status_code != 200:
        detail = response.json().get("error", response.text[:300])
        raise RuntimeError(f"Ollama request failed ({response.status_code}): {detail}")
    answer = response.json().get("message", {}).get("content", "").strip()
    if not answer:
        raise RuntimeError("Ollama returned an empty answer")
    return answer
