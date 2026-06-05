"""personal-aide-minimal — FastAPI shell.

This file is intentionally short: every interesting concern lives in a
sibling module so the agno-plus boundary stays visible:

  config.py      env-driven Settings (USER_ID and DOMAIN_ID constants)
  bootstrap.py   singletons (engine, storage, grounder, knowledge_store,
                 IngestionPipeline, Agno Agent, optional Langfuse client)
  db.py          schema setup for the `aide_files` registry table
  jobs.py        in-memory job tracker (JobStatus shape, G-0002)
  ingestion.py   run_semantic / run_structured / run_image
  chat.py        Agno Agent + DomainKnowledge

The routes themselves are wired here so the file map of the example reads
like the API map.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from starlette.requests import Request

from agno_plus.adapters.llm import call_llm
from agno_plus.core.structured import drop_table, fetch_sample_rows

import bootstrap
import chat
import db
import ingestion
import jobs
import tracing
from bootstrap import DOMAIN_ID, USER_ID, engine, knowledge_store, storage
from config import settings
from ingestion import annotations

app = FastAPI(title="Personal Aide — agno-plus minimal example")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def _cors_safe_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        {"detail": str(exc)},
        status_code=500,
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.on_event("startup")
def _startup() -> None:
    db.init_schema()
    tracing.setup()  # Agno OTel → Langfuse OTLP (auto-instruments tool calls)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


_SPREADSHEET_EXTS = {".csv", ".tsv", ".xlsx", ".xls"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _classify(filename: str, ingest_mode: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ingest_mode == "structured" and ext in _SPREADSHEET_EXTS:
        return "structured"
    if ingest_mode == "semantic":
        return "document"
    return "structured" if ext in _SPREADSHEET_EXTS else "document"


def _run_ingest(jid: str, file_id: str, content: bytes, filename: str, src_type: str) -> None:
    try:
        if src_type == "structured":
            ingestion.run_structured(jid, file_id, content, filename)
        elif src_type == "image":
            ingestion.run_image(jid, file_id, content, filename)
        else:
            ingestion.run_semantic(jid, file_id, content, filename)
    except Exception as exc:
        jobs.finish(jid, error=str(exc))


@app.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    ingest_mode: str = Form("auto"),  # "auto" | "structured" | "semantic"
) -> dict[str, str]:
    content = await file.read()
    filename = file.filename or "upload"
    src_type = _classify(filename, ingest_mode)

    file_id = f"f_{uuid.uuid4().hex[:10]}"
    storage_key = storage().save(USER_ID, file_id, filename, content)

    with engine().begin() as conn:
        conn.execute(
            text("INSERT INTO aide_files (id, filename, source_type, storage_key) "
                 "VALUES (:id,:fn,:st,:sk)"),
            {"id": file_id, "fn": filename, "st": src_type, "sk": storage_key},
        )

    jid = jobs.new_job()
    threading.Thread(
        target=_run_ingest, args=(jid, file_id, content, filename, src_type), daemon=True
    ).start()
    return {"job_id": jid, "file_id": file_id}


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **job}


# ---------------------------------------------------------------------------
# Files registry
# ---------------------------------------------------------------------------


@app.get("/files")
def list_files() -> dict[str, Any]:
    with engine().connect() as conn:
        rows = conn.execute(
            text("SELECT id, filename, source_type, chunks_count, tables_created, "
                 "extraction_preview, created_at FROM aide_files ORDER BY created_at DESC")
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
    with engine().connect() as conn:
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
    with engine().begin() as conn:
        row = conn.execute(
            text("SELECT storage_key, tables_created, filename FROM aide_files WHERE id=:id"),
            {"id": file_id},
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="File not found")

        for tbl in (row.tables_created or []):
            try:
                drop_table(engine(), tbl)
            except Exception:
                pass
        if row.storage_key:
            storage().delete(row.storage_key)
        conn.execute(text("DELETE FROM aide_files WHERE id=:id"), {"id": file_id})

    try:
        knowledge_store().delete_by_file(DOMAIN_ID, row.filename)
    except Exception:
        pass
    return {"status": "deleted"}


@app.get("/files/{file_id}/raw")
def raw_file(file_id: str) -> FileResponse:
    with engine().connect() as conn:
        row = conn.execute(
            text("SELECT storage_key, filename FROM aide_files WHERE id=:id"), {"id": file_id}
        ).first()
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    path = storage().resolve(row.storage_key)
    if not path:
        raise HTTPException(status_code=404, detail="File not on disk")
    return FileResponse(path, filename=row.filename)


# ---------------------------------------------------------------------------
# Structured-domain schema endpoints (consumed by TableSchemaEditor)
# ---------------------------------------------------------------------------


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
    return {"rows": fetch_sample_rows(engine(), table_name, limit=5)}


@app.get("/ingest/structured/{domain_id}/{table_name}/annotation")
def get_annotation(domain_id: str, table_name: str) -> dict[str, Any]:
    with engine().connect() as conn:
        cols = conn.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t AND column_name != '_row_id' "
                "ORDER BY ordinal_position"
            ),
            {"t": table_name},
        ).fetchall()
        try:
            row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0
        except Exception:
            row_count = 0

    stored = annotations.get(table_name, {})
    stored_col_map: dict[str, dict] = (
        {c["name"]: c for c in stored.get("columns", [])}
        if isinstance(stored.get("columns"), list) else {}
    )
    return {
        "annotation": {
            "description": stored.get("description", ""),
            "row_count": row_count,
            "columns": {
                col: {
                    "type": stored_col_map.get(col, {}).get("type")
                            or _PG_TYPE_MAP.get(dtype.lower(), "TEXT"),
                    "description": stored_col_map.get(col, {}).get("description", ""),
                }
                for col, dtype in cols
            },
        }
    }


@app.patch("/ingest/structured/{domain_id}/{table_name}/annotation")
async def save_annotation(domain_id: str, table_name: str, body: dict[str, Any]) -> dict[str, str]:
    annotations[table_name] = body
    return {"status": "ok"}


@app.post("/domains/{domain_id}/infer-schema")
async def infer_schema(domain_id: str) -> dict[str, Any]:
    prefix = f"sd_{domain_id[:8]}_"
    with engine().connect() as conn:
        tables = [
            r[0] for r in conn.execute(
                text("SELECT table_name FROM information_schema.tables "
                     "WHERE table_schema='public' AND table_name LIKE :p"),
                {"p": f"{prefix}%"},
            ).fetchall()
        ]

    schema_annotation: dict[str, Any] = {}
    for tname in tables:
        sample = fetch_sample_rows(engine(), tname, limit=3)
        sample_text = "\n".join(str(r) for r in sample)
        with engine().connect() as conn:
            cols = [
                c[0] for c in conn.execute(
                    text("SELECT column_name FROM information_schema.columns "
                         "WHERE table_name=:t ORDER BY ordinal_position"),
                    {"t": tname},
                ).fetchall() if c[0] != "_row_id"
            ]
        try:
            raw = call_llm(
                f"Given a database table named '{tname}' with columns: {', '.join(cols)}\n"
                f"Sample rows:\n{sample_text}\n\n"
                "For each column write a short (max 15 words) description. "
                'Reply only with JSON: {"col_name": "description", ...}',
                backend=settings.llm_backend,
                model=settings.llm_model,
                api_key=settings.openai_api_key,
                base_url=settings.ollama_url,
                json_response=True,
            )
            import json
            descs = json.loads(raw)
        except Exception:
            descs = {}
        schema_annotation[tname] = {
            "description": "",
            "columns": {c: {"type": "TEXT", "description": descs.get(c, "")} for c in cols},
        }

    return {"schema_annotation": schema_annotation}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
async def post_chat(body: ChatRequest) -> dict[str, str]:
    return {"reply": chat.reply(body.message)}
