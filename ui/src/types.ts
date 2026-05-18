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
