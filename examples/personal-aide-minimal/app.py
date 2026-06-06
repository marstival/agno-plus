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

import json
import threading
import time
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
from agno_plus.core.readers.spreadsheet import SpreadsheetReader
from agno_plus.core.structured import (
    ALLOWED_PG_TYPES,
    bulk_insert,
    create_dynamic_table,
    drop_table,
    fetch_sample_rows,
    infer_column_types,
    safe_col_name,
)

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
_VALID_MODES = {"structured", "semantic"}


def _classify(filename: str, ingest_mode: str) -> str:
    """Route to one of: 'structured' | 'document' | 'image'.

    The caller MUST pick `structured` or `semantic` explicitly — there is no
    extension-based auto routing. Images are the one exception: they always
    go through the image OCR path regardless of mode, because semantic vs
    structured doesn't apply.
    """
    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ingest_mode not in _VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"ingest_mode must be one of {sorted(_VALID_MODES)} "
                f"(got {ingest_mode!r}). Images are auto-routed; everything "
                "else requires an explicit choice."
            ),
        )
    if ingest_mode == "structured":
        if ext not in _SPREADSHEET_EXTS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"structured mode only supports {sorted(_SPREADSHEET_EXTS)}. "
                    "Re-upload as semantic to embed the content for RAG."
                ),
            )
        return "structured"
    return "document"


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
    ingest_mode: str = Form(...),  # "structured" | "semantic" — must be explicit
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
# Two-step structured ingest: preview (read + infer) → commit (write)
#
# /ingest/preview/structured parses the file in memory, returns the inferred
# table name + column types + LLM-suggested descriptions for the user to
# review/edit. /ingest/commit/structured takes the edited annotation and
# does the actual SQL create + insert + aide_files row.
#
# Preview state lives in an in-process dict with a 30-minute TTL. A real
# app would use Redis or DB-backed preview rows (see G-0002).
# ---------------------------------------------------------------------------

_PREVIEW_TTL_SECONDS = 30 * 60
_previews: dict[str, dict[str, Any]] = {}


def _gc_previews() -> None:
    now = time.time()
    expired = [pid for pid, pv in _previews.items() if now - pv["created_at"] > _PREVIEW_TTL_SECONDS]
    for pid in expired:
        _previews.pop(pid, None)


def _suggest_column_descriptions(
    table_name: str, headers: list[str], rows: list[dict[str, str]]
) -> dict[str, str]:
    """Best-effort LLM call to pre-fill column descriptions. Empty dict on failure."""
    sample = rows[:3]
    sample_text = "\n".join(str(r) for r in sample)
    try:
        raw = call_llm(
            f"Database table '{table_name}' columns: {', '.join(headers)}\n"
            f"Sample rows:\n{sample_text}\n\n"
            "Write a short description (max 15 words) for each column. "
            'Reply only with JSON: {"col_name": "description", ...}',
            backend=settings.llm_backend,
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            base_url=settings.ollama_url,
            json_response=True,
        )
        return json.loads(raw)
    except Exception:
        return {}


@app.post("/ingest/preview/structured")
async def preview_structured(file: UploadFile = File(...)) -> dict[str, Any]:
    """Parse a spreadsheet, infer the schema, return a preview for the user
    to edit before committing. The file bytes stay in memory until commit."""
    _gc_previews()
    content = await file.read()
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in _SPREADSHEET_EXTS:
        raise HTTPException(400, f"preview only supports {sorted(_SPREADSHEET_EXTS)}")

    reader = SpreadsheetReader()
    try:
        tables = reader.extract_tables(content, filename)
    except Exception as exc:
        raise HTTPException(400, f"could not parse file: {exc}")
    if not tables or not tables[0]["headers"]:
        raise HTTPException(
            422,
            "No tabular structure detected. The file looks like a styled "
            "template or free-form note rather than a clean table. Upload "
            "this file under the Semantic tab to embed it for RAG instead.",
        )

    headers = tables[0]["headers"]
    rows = tables[0]["rows"]
    safe_name = safe_col_name(Path(filename).stem)[:32]
    table_name = f"sd_{DOMAIN_ID[:8]}_{safe_name}"
    col_types = infer_column_types(headers, rows)
    suggestions = _suggest_column_descriptions(table_name, headers, rows)

    preview_id = f"pre_{uuid.uuid4().hex[:10]}"
    _previews[preview_id] = {
        "created_at": time.time(),
        "filename": filename,
        "content": content,
        "table_name": table_name,
        "headers": headers,
        "rows": rows,
        "col_types": col_types,
    }

    return {
        "preview_id": preview_id,
        "filename": filename,
        "table_name": table_name,
        "row_count": len(rows),
        "sample_rows": rows[:5],
        "description": "",  # user fills in
        "columns": [
            {
                "name": h,                                  # original header (for display)
                "safe_name": safe_col_name(h),              # what the SQL column will be
                "type": col_types.get(safe_col_name(h), "TEXT"),
                "description": suggestions.get(h, ""),       # LLM-suggested, user-editable
                "allowed_types": sorted(ALLOWED_PG_TYPES),
            }
            for h in headers
        ],
    }


class CommitStructuredRequest(BaseModel):
    preview_id: str
    description: str = ""
    columns: list[dict[str, Any]] = []  # [{name, type, description}, ...]


@app.post("/ingest/commit/structured")
async def commit_structured(body: CommitStructuredRequest) -> dict[str, Any]:
    """Dispatch the SQL upsert + registry write to a background thread and
    return a job_id immediately. The UI polls /jobs/{id} via JobStatusWidget
    to render the same READ → UPSERT progression the semantic path uses."""
    pv = _previews.pop(body.preview_id, None)
    if not pv:
        raise HTTPException(404, "Preview expired or not found — re-upload the file")

    # Resolve final column types + descriptions before backgrounding so the
    # worker is pure I/O. ALLOWED_PG_TYPES is the gate; anything else falls
    # back to the inferred type.
    headers = pv["headers"]
    inferred_types = pv["col_types"]
    type_by_original: dict[str, str | None] = {c.get("name"): c.get("type") for c in body.columns}
    final_types: dict[str, str] = {}
    for h in headers:
        safe = safe_col_name(h)
        chosen = (type_by_original.get(h) or "").upper()
        final_types[safe] = chosen if chosen in ALLOWED_PG_TYPES else inferred_types.get(safe, "TEXT")
    desc_by_original = {c.get("name"): c.get("description", "") for c in body.columns}

    file_id = f"f_{uuid.uuid4().hex[:10]}"
    jid = jobs.new_job()
    threading.Thread(
        target=_commit_structured_worker,
        args=(jid, file_id, pv, final_types, body.description, desc_by_original),
        daemon=True,
    ).start()
    return {"job_id": jid, "file_id": file_id, "table_name": pv["table_name"]}


def _commit_structured_worker(
    jid: str,
    file_id: str,
    pv: dict[str, Any],
    final_types: dict[str, str],
    table_description: str,
    desc_by_original: dict[str, str],
) -> None:
    """Background worker for /ingest/commit/structured.

    Step model (mirrors the structured ingest contract):
      READ   — data already in memory from the preview step (instant)
      UPSERT — create_dynamic_table + bulk_insert + aide_files registry
    """
    filename = pv["filename"]
    headers = pv["headers"]
    rows = pv["rows"]
    table_name = pv["table_name"]

    jobs.set_step(jid, "read")  # marker — data was read during preview

    jobs.set_step(jid, "upsert")
    storage_key = storage().save(USER_ID, file_id, filename, pv["content"])
    try:
        create_dynamic_table(engine(), table_name, headers, final_types)
        bulk_insert(engine(), table_name, headers, rows)
    except Exception as exc:
        try:
            storage().delete(storage_key)
        except Exception:
            pass
        jobs.finish(jid, error=f"SQL ingest failed: {exc}")
        return

    ingestion.annotations[table_name] = {
        "description": table_description,
        "columns": [
            {
                "name": safe_col_name(h),
                "type": final_types[safe_col_name(h)],
                "description": desc_by_original.get(h, ""),
            }
            for h in headers
        ],
    }

    extraction_preview = {
        "source_type": "structured",
        "filename": filename,
        "table_name": table_name,
        "description": table_description,
        "columns": {
            h: {
                "type": final_types[safe_col_name(h)],
                "description": desc_by_original.get(h, ""),
            }
            for h in headers
        },
        "row_count": len(rows),
        "sample_rows": rows[:5],
    }
    try:
        with engine().begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO aide_files (id, filename, source_type, chunks_count, "
                    "storage_key, tables_created, extraction_preview) "
                    "VALUES (:id, :fn, 'structured', 0, :sk, :tc, cast(:p as jsonb))"
                ),
                {"id": file_id, "fn": filename, "sk": storage_key,
                 "tc": [table_name], "p": json.dumps(extraction_preview)},
            )
    except Exception as exc:
        jobs.finish(jid, error=f"registry write failed: {exc}")
        return

    jobs.finish(jid)


@app.delete("/ingest/preview/{preview_id}")
def cancel_preview(preview_id: str) -> dict[str, str]:
    _previews.pop(preview_id, None)
    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# Files registry
# ---------------------------------------------------------------------------


@app.get("/files")
def list_files(source_type: str = "") -> dict[str, Any]:
    """List ingested files. `source_type` is an optional comma-separated
    filter (e.g. `document,image` for the semantic tab, `structured` for
    the structured tab)."""
    wanted = {s for s in source_type.split(",") if s.strip()}
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
            if not wanted or r.source_type in wanted
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
