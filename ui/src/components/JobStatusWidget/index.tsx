/**
 * JobStatusWidget — polls job status and shows step-by-step pipeline progress.
 *
 * Props:
 *   jobId          job_id returned by the ingest endpoint
 *   statusUrl      base URL of the status endpoint (GET {statusUrl}/{jobId})
 *   pollIntervalMs how often to poll in ms (default 1500)
 *   onComplete     called when the job reaches "completed" state
 *   onFailed       called with the error string when the job fails
 *   getHeaders     async function that returns auth headers for polling requests
 */

import React, { useEffect, useRef, useState } from "react";
import type { JobState, JobStatus, JobStep } from "../../types";

export interface JobStatusWidgetProps {
  jobId: string;
  statusUrl: string;
  pollIntervalMs?: number;
  onComplete?: () => void;
  onFailed?: (error: string) => void;
  getHeaders?: () => Promise<Record<string, string>>;
}

const STEPS: JobStep[] = ["read", "ground", "chunk", "embed", "upsert"];

const STEP_LABELS: Record<JobStep, string> = {
  read:   "Read file",
  ground: "Temporal grounding",
  chunk:  "Chunk text",
  embed:  "Embed chunks",
  upsert: "Store in knowledge base",
};

type StepStatus = "pending" | "active" | "done" | "failed";

function stepStatus(step: JobStep, jobStatus: JobStatus): StepStatus {
  if (jobStatus.completed_steps.includes(step)) return "done";
  if (jobStatus.current_step === step) {
    return jobStatus.state === "failed" ? "failed" : "active";
  }
  if (jobStatus.state === "failed") {
    const steps = jobStatus.completed_steps;
    const lastCompleted = steps.length > 0 ? steps[steps.length - 1] : undefined;
    const lastIdx = lastCompleted ? STEPS.indexOf(lastCompleted) : -1;
    const thisIdx = STEPS.indexOf(step);
    return thisIdx === lastIdx + 1 ? "failed" : "pending";
  }
  return "pending";
}

export function JobStatusWidget({
  jobId,
  statusUrl,
  pollIntervalMs = 1500,
  onComplete,
  onFailed,
  getHeaders,
}: JobStatusWidgetProps) {
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const doneRef = useRef(false);

  useEffect(() => {
    doneRef.current = false;

    const poll = async () => {
      if (doneRef.current) return;
      try {
        const headers = getHeaders ? await getHeaders() : {};
        const res = await fetch(`${statusUrl}/${jobId}`, { headers });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: JobStatus = await res.json();
        setStatus(data);

        if (data.state === "completed") {
          doneRef.current = true;
          onComplete?.();
          return;
        }
        if (data.state === "failed") {
          doneRef.current = true;
          onFailed?.(data.error ?? "Unknown error");
          return;
        }
      } catch (err) {
        setFetchError(err instanceof Error ? err.message : String(err));
      }
      timerRef.current = setTimeout(poll, pollIntervalMs);
    };

    poll();
    return () => {
      doneRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [jobId, statusUrl, pollIntervalMs, onComplete, onFailed, getHeaders]);

  if (fetchError) {
    return (
      <div style={styles.wrapper}>
        <p style={styles.errorText}>Failed to fetch status: {fetchError}</p>
      </div>
    );
  }

  if (!status) {
    return (
      <div style={styles.wrapper}>
        <p style={styles.muted}>Connecting…</p>
      </div>
    );
  }

  return (
    <div style={styles.wrapper}>
      <div style={styles.header}>
        <StateIndicator state={status.state} />
        <span style={styles.jobId}>{jobId}</span>
      </div>

      <ol style={styles.stepList}>
        {STEPS.map((step) => {
          const st = stepStatus(step, status);
          return (
            <li key={step} style={styles.stepItem}>
              <StepIcon status={st} />
              <span style={{ ...styles.stepLabel, color: st === "pending" ? "#94a3b8" : "#1e293b" }}>
                {STEP_LABELS[step]}
              </span>
            </li>
          );
        })}
      </ol>

      {status.state === "failed" && status.error && (
        <p style={styles.errorText}>{status.error}</p>
      )}
    </div>
  );
}

function StateIndicator({ state }: { state: JobState }) {
  const map: Record<JobState, { label: string; color: string }> = {
    pending:    { label: "Pending",    color: "#94a3b8" },
    processing: { label: "Processing", color: "#3b82f6" },
    completed:  { label: "Completed",  color: "#22c55e" },
    failed:     { label: "Failed",     color: "#ef4444" },
  };
  const { label, color } = map[state];
  return (
    <span style={{ ...styles.badge, background: color + "22", color }}>
      {label}
    </span>
  );
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === "done")   return <span style={{ ...styles.stepIcon, color: "#22c55e" }}>✓</span>;
  if (status === "failed") return <span style={{ ...styles.stepIcon, color: "#ef4444" }}>✗</span>;
  if (status === "active") return <span style={{ ...styles.stepIcon, color: "#3b82f6" }}>◎</span>;
  return <span style={{ ...styles.stepIcon, color: "#cbd5e1" }}>○</span>;
}

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    fontFamily: "system-ui, sans-serif",
    maxWidth: 400,
    border: "1px solid #e2e8f0",
    borderRadius: 12,
    padding: "20px 24px",
    background: "#fff",
    marginTop: 12,
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 16,
  },
  badge: {
    fontSize: 12,
    fontWeight: 600,
    padding: "2px 10px",
    borderRadius: 999,
  },
  jobId: {
    fontSize: 12,
    color: "#94a3b8",
    fontFamily: "monospace",
  },
  stepList: {
    listStyle: "none",
    margin: 0,
    padding: 0,
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  stepItem: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    fontSize: 14,
  },
  stepIcon: {
    fontSize: 16,
    width: 20,
    textAlign: "center",
    flexShrink: 0,
  },
  stepLabel: { fontWeight: 500 },
  errorText: {
    marginTop: 12,
    fontSize: 13,
    color: "#dc2626",
    background: "#fef2f2",
    padding: "8px 12px",
    borderRadius: 6,
  },
  muted: { color: "#94a3b8", fontSize: 14 },
};
