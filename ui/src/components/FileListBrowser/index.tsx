/**
 * FileListBrowser — displays a list of ingested files with delete, preview,
 * and download actions. Structured files support an expandable row slot.
 *
 * Props:
 *   filesUrl         GET endpoint returning { files: IngestedFile[] }
 *   getHeaders       async function that returns auth headers
 *   refreshKey       increment to trigger a re-fetch of the file list
 *   domainId         used to strip the sd_ prefix for human-readable table labels
 *   onPreviewFile    called when the Preview button is clicked (id, filename)
 *   onDownloadFile   called when the Raw button is clicked (id, filename)
 *   onDeleteFile     called after user confirms delete; parent performs the DELETE request
 *   renderExpandedRow  optional slot rendered below a row when expanded (structured files only)
 */

import React, { useCallback, useEffect, useState } from "react";
import type { IngestedFile } from "../../types";
import { sourceIcon, tableLabel } from "../../utils";

export interface FileListBrowserProps {
  filesUrl: string;
  getHeaders?: () => Promise<Record<string, string>>;
  refreshKey?: number | string;
  domainId?: string;
  onPreviewFile?: (fileId: string, filename: string) => void;
  onDownloadFile?: (fileId: string, filename: string) => void;
  onDeleteFile?: (fileId: string) => Promise<void> | void;
  renderExpandedRow?: (file: IngestedFile) => React.ReactNode;
}

export { IngestedFile };

export function FileListBrowser({
  filesUrl,
  getHeaders,
  refreshKey,
  domainId = "",
  onPreviewFile,
  onDownloadFile,
  onDeleteFile,
  renderExpandedRow,
}: FileListBrowserProps) {
  const [files, setFiles] = useState<IngestedFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const headers = getHeaders ? await getHeaders() : {};
      const res = await fetch(filesUrl, { headers });
      if (!res.ok) return;
      const data = await res.json();
      setFiles(data.files ?? []);
    } finally {
      setLoading(false);
    }
  }, [filesUrl, getHeaders]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const handleDelete = async (file: IngestedFile) => {
    if (!confirm(`Delete "${file.filename}"? This cannot be undone.`)) return;
    setDeletingId(file.id);
    try {
      await onDeleteFile?.(file.id);
      setFiles(prev => prev.filter(f => f.id !== file.id));
      if (expandedId === file.id) setExpandedId(null);
    } finally {
      setDeletingId(null);
    }
  };

  const toggleExpand = (id: string) =>
    setExpandedId(prev => prev === id ? null : id);

  if (loading && files.length === 0) {
    return <p style={s.hint}>Loading…</p>;
  }

  if (!loading && files.length === 0) {
    return <p style={s.hint}>No files ingested yet.</p>;
  }

  return (
    <div style={s.list}>
      {files.map(file => {
        const isStructured = file.source_type === "structured";
        const tableName = file.tables_created?.[0] ?? "";
        const label = tableName && domainId ? tableLabel(domainId, tableName) : tableName;
        const isExpanded = expandedId === file.id;
        const canExpand = isStructured && !!tableName && !!renderExpandedRow;

        return (
          <div key={file.id} style={s.row}>
            <div style={s.rowMain}>
              <span style={s.icon}>{sourceIcon(file.source_type)}</span>

              <div style={s.meta}>
                <span style={s.filename}>{file.filename}</span>
                <span style={s.sub}>
                  {isStructured
                    ? (label ? `table: ${label}` : "SQL table")
                    : `${file.chunks_count} chunks`}
                  {" · "}{new Date(file.created_at).toLocaleDateString()}
                </span>
              </div>

              <div style={s.actions}>
                {canExpand && (
                  <button style={s.editBtn} onClick={() => toggleExpand(file.id)}>
                    {isExpanded ? "hide" : "Edit"}
                  </button>
                )}
                {!isStructured && file.has_preview && onPreviewFile && (
                  <button style={s.smBtn} onClick={() => onPreviewFile(file.id, file.filename)}>
                    Preview
                  </button>
                )}
                {file.has_raw && onDownloadFile && (
                  <button
                    style={{ ...s.smBtn, background: "#f1f5f9", color: "#475569" }}
                    onClick={() => onDownloadFile(file.id, file.filename)}
                  >
                    Raw
                  </button>
                )}
                {onDeleteFile && (
                  <button
                    style={s.deleteBtn}
                    onClick={() => handleDelete(file)}
                    disabled={deletingId === file.id}
                  >
                    {deletingId === file.id ? "…" : "✕"}
                  </button>
                )}
              </div>
            </div>

            {isExpanded && canExpand && (
              <div style={s.expandedSlot}>
                {renderExpandedRow!(file)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  list: { display: "flex", flexDirection: "column" },
  row: { borderBottom: "1px solid #f1f5f9" },
  rowMain: {
    display: "flex", alignItems: "center", gap: 10, padding: "10px 0",
  },
  icon: { fontSize: 18, flexShrink: 0 },
  meta: { flex: 1, minWidth: 0 },
  filename: {
    display: "block", fontSize: 13, fontWeight: 600,
    color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
  },
  sub: { display: "block", fontSize: 11, color: "#94a3b8", marginTop: 2 },
  actions: { display: "flex", gap: 6, flexShrink: 0 },
  smBtn: {
    padding: "4px 10px", background: "#2563eb", color: "#fff",
    border: "none", borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: "pointer",
  },
  editBtn: {
    background: "none", border: "1px solid #d1fae5", color: "#166534",
    borderRadius: 6, fontSize: 11, padding: "2px 8px", cursor: "pointer",
  },
  deleteBtn: {
    background: "none", border: "none", color: "#94a3b8",
    cursor: "pointer", fontSize: 16, padding: "0 4px",
  },
  expandedSlot: { paddingBottom: 12, paddingLeft: 28 },
  hint: { margin: 0, fontSize: 13, color: "#94a3b8" },
};
