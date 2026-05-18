/**
 * UploadWidget — file drop zone with type detection and upload progress.
 *
 * Props:
 *   ingestUrl      POST endpoint that accepts multipart/form-data and returns { job_id }
 *   onSuccess      called with the job_id when the server accepts the file
 *   onError        called with an error message on failure
 *   accept         file extensions to accept (default: all agno-plus supported types)
 */

import React, { useCallback, useRef, useState } from "react";

export interface UploadWidgetProps {
  ingestUrl: string;
  onSuccess: (jobId: string) => void;
  onError?: (message: string) => void;
  accept?: string[];
}

const DEFAULT_ACCEPT = [
  ".xlsx", ".xls", ".xlsm", ".csv", ".tsv",
  ".mp3", ".m4a", ".wav", ".ogg", ".flac",
  ".jpg", ".jpeg", ".png", ".webp",
];

const TYPE_LABELS: Record<string, string> = {
  ".xlsx": "Excel", ".xls": "Excel", ".xlsm": "Excel",
  ".csv": "CSV", ".tsv": "TSV",
  ".mp3": "Audio", ".m4a": "Audio", ".wav": "Audio",
  ".ogg": "Audio", ".flac": "Audio",
  ".jpg": "Image", ".jpeg": "Image", ".png": "Image", ".webp": "Image",
};

function detectFileType(filename: string): string {
  const ext = ("." + filename.split(".").pop()?.toLowerCase()) as string;
  return TYPE_LABELS[ext] ?? "Document";
}

type UploadState = "idle" | "uploading" | "done" | "error";

export function UploadWidget({
  ingestUrl,
  onSuccess,
  onError,
  accept = DEFAULT_ACCEPT,
}: UploadWidgetProps) {
  const [state, setState] = useState<UploadState>("idle");
  const [dragging, setDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useCallback(
    async (file: File) => {
      setFileName(file.name);
      setState("uploading");
      setErrorMsg(null);

      const form = new FormData();
      form.append("file", file);
      form.append("filename", file.name);

      try {
        const res = await fetch(ingestUrl, { method: "POST", body: form });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(`Server error ${res.status}: ${text}`);
        }
        const data: { job_id: string } = await res.json();
        setState("done");
        onSuccess(data.job_id);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setState("error");
        setErrorMsg(msg);
        onError?.(msg);
      }
    },
    [ingestUrl, onSuccess, onError],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) upload(file);
    },
    [upload],
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) upload(file);
    },
    [upload],
  );

  const reset = () => {
    setState("idle");
    setFileName(null);
    setErrorMsg(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div style={styles.wrapper}>
      {state === "idle" || state === "error" ? (
        <div
          style={{
            ...styles.dropzone,
            ...(dragging ? styles.dropzoneDragging : {}),
            ...(state === "error" ? styles.dropzoneError : {}),
          }}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          role="button"
          aria-label="Upload file"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept={accept.join(",")}
            style={{ display: "none" }}
            onChange={handleChange}
          />
          <span style={styles.icon}>⬆</span>
          <p style={styles.primaryText}>
            {dragging ? "Drop file here" : "Drag & drop or click to upload"}
          </p>
          <p style={styles.secondaryText}>
            Spreadsheets, audio, images
          </p>
          <p style={styles.accepted}>
            {accept.join("  ")}
          </p>
          {state === "error" && (
            <p style={styles.errorText}>{errorMsg}</p>
          )}
        </div>
      ) : state === "uploading" ? (
        <div style={styles.status}>
          <span style={styles.spinner} aria-hidden />
          <p style={styles.primaryText}>
            Uploading <strong>{fileName}</strong>
            {fileName && <em style={styles.typeTag}> {detectFileType(fileName)}</em>}
          </p>
        </div>
      ) : (
        <div style={styles.status}>
          <span style={styles.successIcon}>✓</span>
          <p style={styles.primaryText}>
            <strong>{fileName}</strong> ingested
          </p>
          <button style={styles.resetBtn} onClick={reset}>
            Upload another
          </button>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    fontFamily: "system-ui, sans-serif",
    maxWidth: 480,
  },
  dropzone: {
    border: "2px dashed #94a3b8",
    borderRadius: 12,
    padding: "32px 24px",
    textAlign: "center",
    cursor: "pointer",
    background: "#f8fafc",
    transition: "border-color 150ms, background 150ms",
    outline: "none",
  },
  dropzoneDragging: {
    borderColor: "#3b82f6",
    background: "#eff6ff",
  },
  dropzoneError: {
    borderColor: "#ef4444",
    background: "#fef2f2",
  },
  icon: { fontSize: 32, display: "block", marginBottom: 8 },
  primaryText: { margin: "4px 0", fontWeight: 600, fontSize: 15 },
  secondaryText: { margin: "2px 0", color: "#64748b", fontSize: 13 },
  accepted: { margin: "8px 0 0", color: "#94a3b8", fontSize: 11 },
  errorText: { marginTop: 8, color: "#dc2626", fontSize: 13 },
  status: {
    border: "2px solid #e2e8f0",
    borderRadius: 12,
    padding: "32px 24px",
    textAlign: "center",
    background: "#f8fafc",
  },
  spinner: {
    display: "inline-block",
    width: 28,
    height: 28,
    border: "3px solid #e2e8f0",
    borderTopColor: "#3b82f6",
    borderRadius: "50%",
    animation: "spin 0.8s linear infinite",
    marginBottom: 12,
  },
  successIcon: { fontSize: 32, color: "#22c55e", display: "block", marginBottom: 8 },
  typeTag: { color: "#64748b", fontStyle: "italic" },
  resetBtn: {
    marginTop: 12,
    padding: "6px 16px",
    fontSize: 13,
    borderRadius: 6,
    border: "1px solid #cbd5e1",
    background: "#fff",
    cursor: "pointer",
  },
};
