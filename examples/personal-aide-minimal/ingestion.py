"""Ingestion flows for the personal-aide-minimal demo.

Three paths, all built on agno-plus primitives:

  run_semantic(...)   PDF, text, markdown, image       → IngestionPipeline
  run_structured(...) CSV, XLSX                        → core.structured DDL
                                                         + IngestionPipeline
                                                           dual-write for RAG
  run_image(...)      images                           → IngestionPipeline
                                                         + LLM entity extraction

Job state is mirrored from the pipeline's JobStatus into the in-memory
tracker (see jobs.py) so the UI step bar renders the same READ → GROUND →
CHUNK → EMBED → UPSERT progression for every ingest type.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from agno_plus.adapters.llm import call_llm
from agno_plus.core.models import JobState, JobStep
from agno_plus.core.readers.spreadsheet import SpreadsheetReader
from agno_plus.core.structured import (
    bulk_insert,
    create_dynamic_table,
    fetch_sample_rows,
    infer_column_types,
    safe_col_name,
)

import jobs
from bootstrap import DOMAIN_ID, USER_ID, engine, pipeline
from config import settings

# Stored column annotations: table_name → annotation dict (mirrors agentic-aide
# schema_annotation JSONB without persisting in this minimal demo).
annotations: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Pipeline dispatch
# ---------------------------------------------------------------------------


def _meta(file_id: str) -> dict[str, Any]:
    return {
        "user_id": USER_ID,
        "domain_id": DOMAIN_ID,
        "file_id": file_id,
        "grounding_mode": "auto",
    }


def _mirror_status(jid: str, pipeline_job_id: str) -> Any:
    """Copy completed_steps + state from the pipeline JobStatus into the
    in-memory tracker the API exposes. The pipeline runs synchronously inside
    submit(), so by the time this is called the job is terminal."""
    status = pipeline().status(pipeline_job_id)
    for step in status.completed_steps:
        jobs.set_step(jid, step)
    jobs.finish(jid, error=status.error if status.state == JobState.FAILED else None)
    return status


def _record_file(file_id: str, chunks: int, preview: dict, tables: list[str] | None = None) -> None:
    with engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE aide_files SET chunks_count=:c, tables_created=:t, "
                "extraction_preview=cast(:p as jsonb) WHERE id=:id"
            ),
            {"c": chunks, "t": tables or [], "p": json.dumps(preview), "id": file_id},
        )


# ---------------------------------------------------------------------------
# Semantic ingestion (PDF, text, markdown)
# ---------------------------------------------------------------------------


def run_semantic(jid: str, file_id: str, content: bytes, filename: str) -> None:
    """Submit to the agno-plus pipeline; chunks land in KnowledgeStore."""
    try:
        pipeline_jid = pipeline().submit(content, filename, _meta(file_id))
    except ValueError as exc:
        jobs.finish(jid, error=str(exc))
        return

    status = _mirror_status(jid, pipeline_jid)
    preview = {
        "source_type": Path(filename).suffix.lstrip("."),
        "filename": filename,
        "blocks": [
            {"block_type": doc.get("source_type", "text"),
             "content": (doc.get("content") or "")[:400],
             "metadata": doc.get("metadata", {})}
            for doc in (status.extraction_payload or [])
        ],
        "chunks": status.chunks_count,
    }
    _record_file(file_id, status.chunks_count, preview)


# ---------------------------------------------------------------------------
# Image ingestion (pipeline + LLM entity extraction)
# ---------------------------------------------------------------------------


def run_image(jid: str, file_id: str, content: bytes, filename: str) -> None:
    """OCR via pipeline (ImageReader) + application-layer entity extraction.

    Entity extraction is an LLM call outside the pipeline — keeping the
    deterministic pipeline guarantee (ADR-0003) intact while still allowing
    optional enrichment.
    """
    try:
        pipeline_jid = pipeline().submit(content, filename, _meta(file_id))
    except ValueError as exc:
        jobs.finish(jid, error=str(exc))
        return

    status = _mirror_status(jid, pipeline_jid)
    ocr_text = status.extraction_payload[0]["content"] if status.extraction_payload else ""

    entities: dict = {}
    if ocr_text:
        try:
            raw = call_llm(
                f"Given this OCR text extracted from an image:\n{ocr_text[:2000]}\n\n"
                "Extract key facts as key-value pairs (dates, amounts, names, IDs). "
                'Reply only with JSON: {"key": "value", ...}',
                backend=settings.llm_backend,
                model=settings.llm_model,
                api_key=settings.openai_api_key,
                base_url=settings.ollama_url,
                json_response=True,
            )
            entities = json.loads(raw)
        except Exception as exc:
            print(f"[warn] entity extraction failed: {exc}")

    preview = {
        "source_type": "image",
        "filename": filename,
        "layer1_ocr": ocr_text,
        "layer2_entities": entities,
        "layer3_chunks": status.chunks_count,
    }
    _record_file(file_id, status.chunks_count, preview)


# ---------------------------------------------------------------------------
# Structured ingestion (CSV/XLSX → SQL + RAG dual-write)
# ---------------------------------------------------------------------------


def run_structured(jid: str, file_id: str, content: bytes, filename: str) -> None:
    """CSV/XLSX → dynamic PG table + dual-write to KnowledgeStore.

    Step model (mirrors pipeline naming for UX consistency):
        read   — SpreadsheetReader.extract_tables() returns headers + rows
        upsert — create_dynamic_table + bulk_insert
        embed  — pipeline.submit() embeds a text representation
    """
    jobs.set_step(jid, JobStep.READ)
    try:
        reader = SpreadsheetReader()
        tables = reader.extract_tables(content, filename)
    except Exception as exc:
        jobs.finish(jid, error=f"read failed: {exc}")
        return

    if not tables or not tables[0]["headers"]:
        jobs.finish(jid)
        return

    headers = tables[0]["headers"]
    rows = tables[0]["rows"]
    safe_name = safe_col_name(Path(filename).stem)[:32]
    table_name = f"sd_{DOMAIN_ID[:8]}_{safe_name}"

    jobs.set_step(jid, JobStep.UPSERT)
    col_types = infer_column_types(headers, rows)
    try:
        create_dynamic_table(engine(), table_name, headers, col_types)
        bulk_insert(engine(), table_name, headers, rows)
    except Exception as exc:
        jobs.finish(jid, error=f"sql ingest failed: {exc}")
        return

    _infer_annotations(table_name, col_types)

    jobs.set_step(jid, JobStep.EMBED)
    chunks = _dual_write_csv(file_id, filename, headers, rows)

    preview = {
        "source_type": "structured",
        "filename": filename,
        "table_name": table_name,
        "columns": {c: {"type": col_types.get(safe_col_name(c), "TEXT"), "description": ""} for c in headers},
        "row_count": len(rows),
        "sample_rows": rows[:5],
    }
    _record_file(file_id, chunks, preview, tables=[table_name])
    jobs.finish(jid)


def _dual_write_csv(file_id: str, filename: str, headers: list[str], rows: list[dict]) -> int:
    """Send a flattened text representation of the table through the pipeline
    so KnowledgeStore can answer natural-language questions over the data."""
    text_repr = "\n".join(
        ", ".join(f"{safe_col_name(h)}: {row.get(h, '')}" for h in headers)
        for row in rows[:200]
    )
    bytes_repr = text_repr.encode()
    pseudo_name = f"{Path(filename).stem}.txt"
    try:
        pid = pipeline().submit(bytes_repr, pseudo_name, _meta(file_id))
    except ValueError as exc:
        print(f"[warn] structured dual-write failed: {exc}")
        return 0
    return pipeline().status(pid).chunks_count


def _infer_annotations(table_name: str, col_types: dict[str, str]) -> None:
    col_names = list(col_types.keys())
    sample = fetch_sample_rows(engine(), table_name, limit=3)
    sample_text = "\n".join(str(r) for r in sample)
    try:
        raw = call_llm(
            f"Database table '{table_name}' columns: {', '.join(col_names)}\n"
            f"Sample rows:\n{sample_text}\n\n"
            "Write a short description (max 15 words) for each column. "
            'Reply only with JSON: {"col_name": "description", ...}',
            backend=settings.llm_backend,
            model=settings.llm_model,
            api_key=settings.openai_api_key,
            base_url=settings.ollama_url,
            json_response=True,
        )
        descs = json.loads(raw)
    except Exception as exc:
        print(f"[warn] schema inference failed for {table_name}: {exc}")
        descs = {}

    annotations[table_name] = {
        "description": "",
        "columns": [
            {"name": col, "type": col_types.get(col, "TEXT"), "description": descs.get(col, "")}
            for col in col_names
        ],
    }
