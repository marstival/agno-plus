/**
 * Shared domain types mirroring the Python core models.
 * These match the JSON shape returned by a backend that uses agno-plus.
 */

export type JobState = "pending" | "processing" | "completed" | "failed";
export type JobStep = "read" | "ground" | "chunk" | "embed" | "upsert";

export interface JobStatus {
  job_id: string;
  state: JobState;
  current_step: JobStep | null;
  completed_steps: JobStep[];
  error: string | null;
}

export interface MemoryRecord {
  id: string;
  content: string;
  metadata: Record<string, unknown>;
  event_at: string | null; // ISO datetime string
}

// ---------------------------------------------------------------------------
// Ingested file types (structured + semantic)
// ---------------------------------------------------------------------------

export interface IngestedFile {
  id: string;
  filename: string;
  source_type: string; // "text" | "spreadsheet" | "audio" | "image" | "structured"
  chunks_count: number;
  has_preview: boolean;
  has_raw: boolean;
  created_at: string; // ISO datetime string
  tables_created: string[];
}

// ---------------------------------------------------------------------------
// Structured domain schema annotation types
// ---------------------------------------------------------------------------

export interface ColumnInfo {
  description: string;
  type?: string;   // PostgreSQL type: TEXT, BIGINT, NUMERIC, DATE, TIMESTAMPTZ, BOOLEAN
  source?: string; // "context" when injected via LLM metadata extraction
}

export interface TableInfo {
  description: string;
  columns: Record<string, ColumnInfo>;
  row_count: number;
}

export type SchemaAnnotation = Record<string, TableInfo>;
