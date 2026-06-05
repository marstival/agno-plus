"""
personal-aide-minimal — FastAPI backend

Showcases agno-plus modularity in ~300 lines:
  LocalStorageBackend  → raw file persistence to disk
  KnowledgeStore       → pgvector semantic search with user isolation
  call_llm()           → unified OpenAI / Ollama LLM interface
  Structured DDL       → CSV/Excel rows → PostgreSQL tables for SQL queries
  Langfuse (optional)  → observability via Python SDK

Quick start:
    cp .env.example .env          # add OPENAI_API_KEY
    docker compose up -d postgres
    pip install -r requirements.txt
    PYTHONPATH=../.. uvicorn app:app --reload --port 8000
"""

from __future__ import annotations

import csv
import io
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from starlette.requests import Request

from agno_plus.core.storage import LocalStorageBackend
from agno_plus.adapters.llm import call_llm
from agno_plus.core.structured import (
    bulk_insert,
    create_dynamic_table,
    drop_table,
    fetch_sample_rows,
    infer_column_types,
    safe_col_name,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL  = os.getenv("DATABASE_URL", "postgresql://aide:aide@localhost:5432/aide")
LLM_BACKEND   = os.getenv("LLM_BACKEND", "openai")
LLM_MODEL     = os.getenv("LLM_MODEL", "gpt-4o-mini")
EMBED_MODEL   = os.getenv("EMBED_MODEL", "text-embedding-3-small")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")
OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://localhost:11434")
UPLOADS_DIR   = Path(os.getenv("UPLOADS_DIR", "./uploads"))
VISION_MODEL  = os.getenv("VISION_MODEL", "gpt-4o" if os.getenv("LLM_BACKEND", "openai") == "openai" else "llava")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Single fixed user + domain for the minimal (no-auth) demo
USER_ID   = "local_user"
DOMAIN_ID = "personal"   # table prefix: sd_personal_<name>

# ---------------------------------------------------------------------------
# Database & agno-plus components
# ---------------------------------------------------------------------------

engine = sa.create_engine(DATABASE_URL)

storage = LocalStorageBackend(root=UPLOADS_DIR)


def _init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS ai"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS aide_files (
                id                  TEXT PRIMARY KEY,
                filename            TEXT NOT NULL,
                source_type         TEXT NOT NULL,
                chunks_count        INT  DEFAULT 0,
                storage_key         TEXT,
                tables_created      TEXT[],
                extraction_preview  JSONB,
                created_at          TIMESTAMPTZ DEFAULT now()
            )
        """))
        conn.execute(text(
            "ALTER TABLE aide_files ADD COLUMN IF NOT EXISTS extraction_preview JSONB"
        ))


def _build_knowledge_store() -> Any:
    """Lazy singleton — returns None if pgvector / embedder is unavailable."""
    global _ks
    if _ks is not None:
        return _ks
    try:
        from agno_plus.adapters.agno.knowledge_store import KnowledgeStore
        if LLM_BACKEND == "openai":
            from agno.knowledge.embedder.openai import OpenAIEmbedder
            embedder = OpenAIEmbedder(id=EMBED_MODEL, api_key=OPENAI_KEY)
        else:
            from agno.knowledge.embedder.ollama import OllamaEmbedder
            embedder = OllamaEmbedder(id="nomic-embed-text", host=OLLAMA_URL)
        _ks = KnowledgeStore(engine=engine, embedder=embedder, db_url=DATABASE_URL)
    except Exception as exc:
        print(f"[warn] KnowledgeStore unavailable: {exc}")
    return _ks


_ks: KnowledgeStore | None = None

# ---------------------------------------------------------------------------
# Langfuse (optional) — set LANGFUSE_HOST + keys to enable
# ---------------------------------------------------------------------------

_lf: Any = None


def _init_langfuse() -> None:
    global _lf
    host = os.getenv("LANGFUSE_HOST", "")
    pk   = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk   = os.getenv("LANGFUSE_SECRET_KEY", "")
    if not (host and pk and sk):
        return
    try:
        from langfuse import Langfuse
        client = Langfuse(public_key=pk, secret_key=sk, host=host)
        # Verify this is the v2 SDK that exposes the low-level trace() API
        if not callable(getattr(client, "trace", None)):
            print("[warn] langfuse SDK does not support the v2 trace() API; "
                  "pin langfuse<3.0 in requirements.txt — tracing disabled")
            return
        _lf = client
        print(f"[langfuse] tracing to {host}")
    except ImportError:
        print("[warn] langfuse package not installed; tracing disabled")


# ---------------------------------------------------------------------------
# Job tracking (in-memory; survives within a process)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict[str, Any]] = {}


def _new_job() -> str:
    jid = f"job_{uuid.uuid4().hex[:8]}"
    _jobs[jid] = {"state": "pending", "current_step": None, "completed_steps": [], "error": None}
    return jid


def _set_step(jid: str, step: str) -> None:
    job = _jobs.get(jid)
    if not job:
        return
    job["state"] = "processing"
    if job["current_step"]:
        job["completed_steps"].append(job["current_step"])
    job["current_step"] = step


def _finish_job(jid: str, *, error: str | None = None) -> None:
    job = _jobs.get(jid)
    if not job:
        return
    if error:
        job["state"] = "failed"
        job["error"] = error
    else:
        if job["current_step"]:
            job["completed_steps"].append(job["current_step"])
        job["state"] = "completed"
        job["current_step"] = None


# ---------------------------------------------------------------------------
# Ingestion logic
# ---------------------------------------------------------------------------


def _csv_to_dicts(content: bytes, filename: str) -> tuple[list[str], list[dict]]:
    """Parse CSV/TSV → (headers, row_dicts), auto-detecting the delimiter."""
    text = content.decode("utf-8", errors="replace")
    if filename.endswith(".tsv"):
        delimiter = "\t"
    else:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    headers = list(reader.fieldnames) if reader.fieldnames else (list(rows[0].keys()) if rows else [])
    return headers, rows


def _xlsx_to_dicts(content: bytes) -> tuple[list[str], list[dict]]:
    """Parse Excel → (headers, row_dicts) using openpyxl."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.active
    raw = [[cell.value for cell in row] for row in ws.iter_rows()]
    if not raw:
        return [], []
    headers = [str(h or f"col{i}") for i, h in enumerate(raw[0])]
    row_dicts = [
        {headers[i]: str(v) if v is not None else "" for i, v in enumerate(r)}
        for r in raw[1:]
        if any(v is not None for v in r)
    ]
    return headers, row_dicts


def _infer_table_annotations(table_name: str, col_types: dict[str, str]) -> None:
    """Run LLM to generate column descriptions; store in _annotations."""
    col_names = list(col_types.keys())
    sample = fetch_sample_rows(engine, table_name, limit=3)
    sample_text = "\n".join(str(r) for r in sample)
    prompt = (
        f"Database table '{table_name}' columns: {', '.join(col_names)}\n"
        f"Sample rows:\n{sample_text}\n\n"
        "Write a short description (max 15 words) for each column. "
        'Reply only with JSON: {"col_name": "description", ...}'
    )
    try:
        raw = call_llm(prompt, backend=LLM_BACKEND, model=LLM_MODEL,
                       api_key=OPENAI_KEY, base_url=OLLAMA_URL, json_response=True)
        descs = json.loads(raw)
    except Exception as exc:
        print(f"[warn] schema inference failed for {table_name}: {exc}")
        descs = {}

    _annotations[table_name] = {
        "description": "",
        "columns": [
            {"name": col, "type": col_types.get(col, "TEXT"), "description": descs.get(col, "")}
            for col in col_names
        ],
    }


def _ingest_structured(jid: str, file_id: str, content: bytes, filename: str) -> None:
    _set_step(jid, "read")
    ext = Path(filename).suffix.lower()
    headers, row_dicts = (
        _xlsx_to_dicts(content) if ext in (".xlsx", ".xls")
        else _csv_to_dicts(content, filename)
    )
    if not headers:
        _finish_job(jid)
        return

    safe_name  = safe_col_name(Path(filename).stem)[:32]
    table_name = f"sd_{DOMAIN_ID[:8]}_{safe_name}"

    _set_step(jid, "upsert")
    col_types = infer_column_types(headers, row_dicts)
    create_dynamic_table(engine, table_name, headers, col_types)
    bulk_insert(engine, table_name, headers, row_dicts)

    # Auto-infer descriptions via LLM so the schema editor is populated on first open
    _infer_table_annotations(table_name, col_types)

    # Emit one semantic document so the chat endpoint can also answer table questions
    _set_step(jid, "embed")
    ks = _build_knowledge_store()
    chunks = 0
    if ks:
        text_repr = "\n".join(
            ", ".join(f"{safe_col_name(h)}: {row.get(h, '')}" for h in headers)
            for row in row_dicts[:200]
        )
        from agno.knowledge.document.base import Document as AgnoDoc
        chunks = ks.ingest_documents(
            [AgnoDoc(content=text_repr, name=filename, meta_data={"file_id": file_id})],
            domain_id=DOMAIN_ID, user_id=USER_ID, filename=filename,
        )

    preview = {
        "source_type": "structured",
        "filename": filename,
        "table_name": table_name,
        "columns": {col: {"type": col_types.get(col, "TEXT"), "description": ""} for col in headers},
        "row_count": len(row_dicts),
        "sample_rows": row_dicts[:5],
    }

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE aide_files SET chunks_count=:c, tables_created=:t, extraction_preview=cast(:p as jsonb) WHERE id=:id"),
            {"c": chunks, "t": [table_name], "p": json.dumps(preview), "id": file_id},
        )
    _finish_job(jid)


def _ingest_image(jid: str, file_id: str, content: bytes, filename: str) -> None:
    """3-layer image ingestion: OCR → entity extraction → semantic embedding."""
    _set_step(jid, "read")

    # Layer 1: OCR via vision LLM
    ocr_text = ""
    try:
        from agno_plus.core.readers.image import ImageReader
        reader = ImageReader(
            backend=LLM_BACKEND,
            model=VISION_MODEL,
            api_key=OPENAI_KEY or None,
            ollama_base_url=OLLAMA_URL,
        )
        docs = reader.read(content, filename)
        ocr_text = docs[0].content if docs else ""
    except Exception as exc:
        print(f"[warn] ImageReader OCR failed ({exc}); image stored without text")

    # Layer 2: key-value entity extraction from OCR text
    entities: dict = {}
    if ocr_text:
        try:
            prompt = (
                f"Given this OCR text extracted from an image:\n{ocr_text[:2000]}\n\n"
                "Extract key facts as key-value pairs (dates, amounts, names, IDs, etc.). "
                'Reply only with JSON: {"key": "value", ...}'
            )
            raw = call_llm(prompt, backend=LLM_BACKEND, model=LLM_MODEL,
                           api_key=OPENAI_KEY, base_url=OLLAMA_URL, json_response=True)
            entities = json.loads(raw)
        except Exception as exc:
            print(f"[warn] Entity extraction failed: {exc}")

    preview = {
        "source_type": "image",
        "filename": filename,
        "layer1_ocr": ocr_text,
        "layer2_entities": entities,
        "layer3_chunks": 0,
    }

    # Layer 3: semantic embedding
    _set_step(jid, "embed")
    count = 0
    if ocr_text:
        ks = _build_knowledge_store()
        if ks:
            from agno.knowledge.document.base import Document as AgnoDoc
            count = ks.ingest_documents(
                [AgnoDoc(content=ocr_text, name=filename, meta_data={"file_id": file_id})],
                domain_id=DOMAIN_ID, user_id=USER_ID, filename=filename,
            )

    preview["layer3_chunks"] = count

    _set_step(jid, "upsert")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE aide_files SET chunks_count=:c, extraction_preview=cast(:p as jsonb) WHERE id=:id"),
            {"c": count, "p": json.dumps(preview), "id": file_id},
        )
    _finish_job(jid)


def _ingest_document(jid: str, file_id: str, content: bytes, filename: str) -> None:
    _set_step(jid, "read")
    ext = Path(filename).suffix.lower()

    # Use IntelligentPdfReader for PDFs to get layout-aware block extraction
    preview_blocks: list[dict] = []
    text_blocks: list[str] = []
    if ext == ".pdf":
        try:
            from agno_plus.core.readers.pdf import IntelligentPdfReader
            reader = IntelligentPdfReader()
            pdf_docs = reader.read(content, filename)
            for doc in pdf_docs:
                text_blocks.append(doc.content)
                preview_blocks.append({
                    "block_type": getattr(doc, "source_type", "text"),
                    "content": doc.content[:400],
                    "metadata": doc.metadata,
                })
        except Exception as exc:
            print(f"[warn] IntelligentPdfReader failed ({exc}), falling back to plain decode")

    if not text_blocks:
        text_body = content.decode("utf-8", errors="replace")
        text_blocks = [text_body]
        preview_blocks = [{"block_type": "text", "content": text_body[:400], "metadata": {}}]

    _set_step(jid, "chunk")
    chunk_size, overlap = 800, 160
    all_chunks = []
    for body in text_blocks:
        all_chunks.extend(
            body[i: i + chunk_size].strip()
            for i in range(0, max(1, len(body)), chunk_size - overlap)
            if body[i: i + chunk_size].strip()
        )

    _set_step(jid, "embed")
    ks = _build_knowledge_store()
    count = 0
    if ks:
        from agno.knowledge.document.base import Document as AgnoDoc
        docs = [
            AgnoDoc(content=chunk, name=filename, meta_data={"file_id": file_id, "chunk_idx": i})
            for i, chunk in enumerate(all_chunks)
        ]
        count = ks.ingest_documents(docs, domain_id=DOMAIN_ID, user_id=USER_ID, filename=filename)

    preview = {"source_type": ext.lstrip("."), "filename": filename, "blocks": preview_blocks, "chunks": count}

    _set_step(jid, "upsert")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE aide_files SET chunks_count=:c, extraction_preview=cast(:p as jsonb) WHERE id=:id"),
            {"c": count, "p": json.dumps(preview), "id": file_id},
        )
    _finish_job(jid)


def _run_ingest(jid: str, file_id: str, content: bytes, filename: str, src_type: str) -> None:
    try:
        if src_type == "structured":
            _ingest_structured(jid, file_id, content, filename)
        elif src_type == "image":
            _ingest_image(jid, file_id, content, filename)
        else:
            _ingest_document(jid, file_id, content, filename)
    except Exception as exc:
        _finish_job(jid, error=str(exc))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Personal Aide — agno-plus minimal example")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Ensure unhandled exceptions always carry CORS headers."""
    return JSONResponse(
        {"detail": str(exc)},
        status_code=500,
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.on_event("startup")
def _startup() -> None:
    _init_db()
    _init_langfuse()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


@app.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    ingest_mode: str = Form("auto"),  # "auto" | "structured" | "semantic"
) -> dict[str, str]:
    content  = await file.read()
    filename = file.filename or "upload"
    ext      = Path(filename).suffix.lower()
    is_spreadsheet = ext in (".csv", ".tsv", ".xlsx", ".xls")
    is_image       = ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")
    if is_image:
        src_type = "image"
    elif ingest_mode == "structured" and is_spreadsheet:
        src_type = "structured"
    elif ingest_mode == "semantic":
        src_type = "document"
    else:
        src_type = "structured" if is_spreadsheet else "document"

    file_id     = f"f_{uuid.uuid4().hex[:10]}"
    storage_key = storage.save(USER_ID, file_id, filename, content)

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO aide_files (id, filename, source_type, storage_key) VALUES (:id,:fn,:st,:sk)"),
            {"id": file_id, "fn": filename, "st": src_type, "sk": storage_key},
        )

    jid = _new_job()
    threading.Thread(target=_run_ingest, args=(jid, file_id, content, filename, src_type), daemon=True).start()
    return {"job_id": jid, "file_id": file_id}


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **job}


# ---------------------------------------------------------------------------
# File management
# ---------------------------------------------------------------------------


@app.get("/files")
def list_files() -> dict[str, Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, filename, source_type, chunks_count, tables_created, extraction_preview, created_at FROM aide_files ORDER BY created_at DESC")
        ).fetchall()
    return {
        "files": [
            {
                "id": r.id,
                "filename": r.filename,
                "source_type": r.source_type,
                "chunks_count": r.chunks_count or 0,
                "tables_created": r.tables_created or [],
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "has_preview": r.extraction_preview is not None,
                "has_raw": True,
            }
            for r in rows
        ]
    }


@app.get("/files/{file_id}/preview")
def file_preview(file_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT filename, source_type, extraction_preview FROM aide_files WHERE id=:id"),
            {"id": file_id},
        ).first()
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    return {
        "file_id": file_id,
        "filename": row.filename,
        "source_type": row.source_type,
        "available": row.extraction_preview is not None,
        "payload": row.extraction_preview,
    }


@app.delete("/files/{file_id}")
def delete_file(file_id: str) -> dict[str, str]:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT storage_key, tables_created, filename FROM aide_files WHERE id=:id"),
            {"id": file_id},
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="File not found")

        for tbl in (row.tables_created or []):
            try:
                drop_table(engine, tbl)
            except Exception:
                pass
        if row.storage_key:
            storage.delete(row.storage_key)
        conn.execute(text("DELETE FROM aide_files WHERE id=:id"), {"id": file_id})

    ks = _build_knowledge_store()
    if ks:
        try:
            ks.delete_by_file(DOMAIN_ID, row.filename)
        except Exception:
            pass

    return {"status": "deleted"}


@app.get("/files/{file_id}/raw")
def raw_file(file_id: str) -> FileResponse:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT storage_key, filename FROM aide_files WHERE id=:id"), {"id": file_id}
        ).first()
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    path = storage.resolve(row.storage_key)
    if not path:
        raise HTTPException(status_code=404, detail="File not on disk")
    return FileResponse(path, filename=row.filename)


# ---------------------------------------------------------------------------
# Structured domain endpoints (consumed by TableSchemaEditor in the UI)
# ---------------------------------------------------------------------------

_annotations: dict[str, dict[str, Any]] = {}  # table_name → annotation dict


_PG_TYPE_MAP = {
    "integer": "BIGINT", "bigint": "BIGINT", "smallint": "BIGINT",
    "numeric": "NUMERIC", "real": "NUMERIC", "double precision": "NUMERIC",
    "text": "TEXT", "character varying": "TEXT", "character": "TEXT", "varchar": "TEXT",
    "date": "DATE",
    "timestamp with time zone": "TIMESTAMPTZ",
    "timestamp without time zone": "TIMESTAMPTZ",
    "boolean": "BOOLEAN",
}


@app.get("/ingest/structured/{domain_id}/{table_name}/sample")
def table_sample(domain_id: str, table_name: str) -> dict[str, Any]:
    return {"rows": fetch_sample_rows(engine, table_name, limit=5)}


@app.get("/ingest/structured/{domain_id}/{table_name}/annotation")
def get_annotation(domain_id: str, table_name: str) -> dict[str, Any]:
    """Return column types (from DB schema) merged with stored descriptions."""
    with engine.connect() as conn:
        cols = conn.execute(
            text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :t
                  AND column_name != '_row_id'
                ORDER BY ordinal_position
            """),
            {"t": table_name},
        ).fetchall()
        try:
            row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0
        except Exception:
            row_count = 0

    stored = _annotations.get(table_name, {})
    # stored["columns"] is a list [{name, description, type}] from the PATCH body
    stored_col_map: dict[str, dict] = {}
    if isinstance(stored.get("columns"), list):
        stored_col_map = {c["name"]: c for c in stored["columns"]}

    return {
        "annotation": {
            "description": stored.get("description", ""),
            "row_count": row_count,
            "columns": {
                col: {
                    "type": stored_col_map.get(col, {}).get("type") or _PG_TYPE_MAP.get(dtype.lower(), "TEXT"),
                    "description": stored_col_map.get(col, {}).get("description", ""),
                }
                for col, dtype in cols
            },
        }
    }


@app.patch("/ingest/structured/{domain_id}/{table_name}/annotation")
async def save_annotation(domain_id: str, table_name: str, body: dict[str, Any]) -> dict[str, str]:
    _annotations[table_name] = body
    return {"status": "ok"}


@app.post("/domains/{domain_id}/infer-schema")
async def infer_schema(domain_id: str) -> dict[str, Any]:
    """Use call_llm() to suggest column descriptions for all sd_ tables in this domain."""
    prefix = f"sd_{domain_id[:8]}_"
    with engine.connect() as conn:
        tables = [
            r[0] for r in conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE :p"),
                {"p": f"{prefix}%"},
            ).fetchall()
        ]

    schema_annotation: dict[str, Any] = {}
    for tname in tables:
        sample = fetch_sample_rows(engine, tname, limit=3)
        sample_text = "\n".join(str(r) for r in sample)
        with engine.connect() as conn:
            cols = conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name=:t ORDER BY ordinal_position"),
                {"t": tname},
            ).fetchall()
        col_names = [c[0] for c in cols if c[0] != "_row_id"]

        prompt = (
            f"Given a database table named '{tname}' with columns: {', '.join(col_names)}\n"
            f"Sample rows:\n{sample_text}\n\n"
            "For each column write a short (max 15 words) description of what it contains. "
            "Reply only with JSON: {\"col_name\": \"description\", ...}"
        )
        try:
            raw = call_llm(prompt, backend=LLM_BACKEND, model=LLM_MODEL, api_key=OPENAI_KEY,
                           base_url=OLLAMA_URL, json_response=True)
            descs = json.loads(raw)
        except Exception:
            descs = {}

        schema_annotation[tname] = {
            "description": "",
            "columns": {
                c: {"type": "TEXT", "description": descs.get(c, "")}
                for c in col_names
            },
        }

    return {"schema_annotation": schema_annotation}


# ---------------------------------------------------------------------------
# Chat (RAG over knowledge base)
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
async def chat(body: ChatRequest) -> dict[str, str]:
    trace = _lf.trace(name="chat", input=body.message) if _lf else None

    # 1. Semantic search over ingested knowledge
    ks = _build_knowledge_store()
    context = "(no relevant knowledge found)"
    if ks:
        span = trace.span(name="rag-search") if trace else None
        try:
            results = ks.search(body.message, user_id=USER_ID, domain_id=DOMAIN_ID, top_k=5)
            if results:
                context = "\n\n---\n\n".join(r.content for r in results)
        except Exception as exc:
            print(f"[warn] search failed: {exc}")
        if span:
            span.end()

    # 2. Call LLM via agno-plus helper
    prompt = (
        "You are a helpful personal assistant with access to a private knowledge base.\n"
        "Answer the user's question using the context below. "
        "If the context is not sufficient, answer from general knowledge.\n\n"
        f"=== Context ===\n{context}\n=== End ===\n\n"
        f"User: {body.message}\nAssistant:"
    )
    gen = trace.generation(name="llm", model=LLM_MODEL, input=prompt) if trace else None
    reply = ""
    try:
        reply = call_llm(prompt, backend=LLM_BACKEND, model=LLM_MODEL,
                         api_key=OPENAI_KEY, base_url=OLLAMA_URL, max_tokens=800)
    except Exception as exc:
        reply = f"Sorry, I could not reach the LLM: {exc}"
    try:
        if gen:
            gen.end(output=reply)
        if trace:
            trace.update(output=reply)
        if _lf:
            _lf.flush()
    except Exception:
        pass

    return {"reply": reply}
