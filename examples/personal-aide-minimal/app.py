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
import os
import threading
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text

from agno_plus.core.storage import LocalStorageBackend
from agno_plus.adapters.llm import call_llm
from agno_plus.adapters.agno.knowledge_store import KnowledgeStore
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

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://aide:aide@localhost:5432/aide")
LLM_BACKEND  = os.getenv("LLM_BACKEND", "openai")
LLM_MODEL    = os.getenv("LLM_MODEL", "gpt-4o-mini")
EMBED_MODEL  = os.getenv("EMBED_MODEL", "text-embedding-3-small")
OPENAI_KEY   = os.getenv("OPENAI_API_KEY", "")
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")
UPLOADS_DIR  = Path(os.getenv("UPLOADS_DIR", "./uploads"))
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
                id              TEXT PRIMARY KEY,
                filename        TEXT NOT NULL,
                source_type     TEXT NOT NULL,
                chunks_count    INT  DEFAULT 0,
                storage_key     TEXT,
                tables_created  TEXT[],
                created_at      TIMESTAMPTZ DEFAULT now()
            )
        """))


def _build_knowledge_store() -> KnowledgeStore | None:
    """Lazy singleton — returns None if embedder is unavailable."""
    global _ks
    if _ks is not None:
        return _ks
    try:
        if LLM_BACKEND == "openai":
            from agno.embedder.openai import OpenAIEmbedder
            embedder = OpenAIEmbedder(id=EMBED_MODEL, api_key=OPENAI_KEY)
        else:
            from agno.embedder.ollama import OllamaEmbedder
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
        _lf = Langfuse(public_key=pk, secret_key=sk, host=host)
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
    """Parse CSV/TSV → (headers, row_dicts)."""
    dialect = "excel-tab" if filename.endswith(".tsv") else "excel"
    reader = csv.DictReader(io.StringIO(content.decode("utf-8", errors="replace")), dialect=dialect)
    rows = list(reader)
    headers = reader.fieldnames or (list(rows[0].keys()) if rows else [])
    return list(headers), rows


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

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE aide_files SET chunks_count=:c, tables_created=:t WHERE id=:id"),
            {"c": chunks, "t": [table_name], "id": file_id},
        )
    _finish_job(jid)


def _ingest_document(jid: str, file_id: str, content: bytes, filename: str) -> None:
    _set_step(jid, "read")
    text_body = content.decode("utf-8", errors="replace")

    _set_step(jid, "chunk")
    chunk_size, overlap = 800, 160
    chunks = [
        text_body[i : i + chunk_size].strip()
        for i in range(0, max(1, len(text_body)), chunk_size - overlap)
        if text_body[i : i + chunk_size].strip()
    ]

    _set_step(jid, "embed")
    ks = _build_knowledge_store()
    count = 0
    if ks:
        from agno.knowledge.document.base import Document as AgnoDoc
        docs = [
            AgnoDoc(content=chunk, name=filename, meta_data={"file_id": file_id, "chunk_idx": i})
            for i, chunk in enumerate(chunks)
        ]
        count = ks.ingest_documents(docs, domain_id=DOMAIN_ID, user_id=USER_ID, filename=filename)

    _set_step(jid, "upsert")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE aide_files SET chunks_count=:c WHERE id=:id"),
            {"c": count, "id": file_id},
        )
    _finish_job(jid)


def _run_ingest(jid: str, file_id: str, content: bytes, filename: str) -> None:
    try:
        ext = Path(filename).suffix.lower()
        if ext in (".csv", ".tsv", ".xlsx", ".xls"):
            _ingest_structured(jid, file_id, content, filename)
        else:
            _ingest_document(jid, file_id, content, filename)
    except Exception as exc:
        _finish_job(jid, error=str(exc))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Personal Aide — agno-plus minimal example")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
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
async def ingest(file: UploadFile = File(...)) -> dict[str, str]:
    content  = await file.read()
    filename = file.filename or "upload"
    ext      = Path(filename).suffix.lower()
    src_type = "structured" if ext in (".csv", ".tsv", ".xlsx", ".xls") else "document"

    file_id     = f"f_{uuid.uuid4().hex[:10]}"
    storage_key = storage.save(USER_ID, file_id, filename, content)

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO aide_files (id, filename, source_type, storage_key) VALUES (:id,:fn,:st,:sk)"),
            {"id": file_id, "fn": filename, "st": src_type, "sk": storage_key},
        )

    jid = _new_job()
    threading.Thread(target=_run_ingest, args=(jid, file_id, content, filename), daemon=True).start()
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
            text("SELECT id, filename, source_type, chunks_count, tables_created, created_at FROM aide_files ORDER BY created_at DESC")
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
                "has_preview": (r.chunks_count or 0) > 0,
                "has_raw": True,
            }
            for r in rows
        ]
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


@app.get("/ingest/structured/{domain_id}/{table_name}/sample")
def table_sample(domain_id: str, table_name: str) -> dict[str, Any]:
    return {"rows": fetch_sample_rows(engine, table_name, limit=5)}


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
            import json
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
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if gen:
            gen.end(output=reply)
        if trace:
            trace.update(output=reply)
        if _lf:
            _lf.flush()

    return {"reply": reply}
