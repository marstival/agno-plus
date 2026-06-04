/**
 * TableSchemaEditor — annotation editor for a structured domain SQL table.
 *
 * Manages table description, per-column type + description, and sample row preview.
 * Calls the backend to infer descriptions via LLM (auto-annotate) and to save.
 *
 * URL conventions (all derived from apiBase + domainId + tableName):
 *   GET  {apiBase}/ingest/structured/{domainId}/{tableName}/sample
 *   PATCH {apiBase}/ingest/structured/{domainId}/{tableName}/annotation
 *   POST {apiBase}/domains/{domainId}/infer-schema
 *
 * Props:
 *   domainId           domain UUID
 *   tableName          full sd_... table name
 *   apiBase            base URL without trailing slash (default "")
 *   getHeaders         async function returning auth headers
 *   initialAnnotation  pre-loaded TableInfo (skips sample fetch if sampleRows also given)
 *   initialSampleRows  pre-loaded sample rows (skips fetch)
 *   onSaved            called after a successful PATCH
 *   onSkip             if provided, renders a Skip button
 */

import React, { useEffect, useState } from "react";
import type { ColumnInfo, SchemaAnnotation, TableInfo } from "../../types";
import { tableLabel } from "../../utils";

export interface TableSchemaEditorProps {
  domainId: string;
  tableName: string;
  apiBase?: string;
  getHeaders?: () => Promise<Record<string, string>>;
  initialAnnotation?: TableInfo;
  initialSampleRows?: Record<string, string>[];
  onSaved?: () => void;
  onSkip?: () => void;
}

const PG_TYPES = ["TEXT", "BIGINT", "NUMERIC", "DATE", "TIMESTAMPTZ", "BOOLEAN"] as const;

export function TableSchemaEditor({
  domainId,
  tableName,
  apiBase = "",
  getHeaders,
  initialAnnotation,
  initialSampleRows,
  onSaved,
  onSkip,
}: TableSchemaEditorProps) {
  const baseAnnotation: TableInfo = initialAnnotation ?? { description: "", columns: {}, row_count: 0 };
  const [draft, setDraft] = useState<TableInfo>(JSON.parse(JSON.stringify(baseAnnotation)));
  const [sampleRows, setSampleRows] = useState<Record<string, string>[]>(initialSampleRows ?? []);
  const [loadingSample, setLoadingSample] = useState(false);
  const [inferring, setInferring] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  // Fetch sample rows if not provided
  useEffect(() => {
    if (initialSampleRows && initialSampleRows.length > 0) return;
    setLoadingSample(true);
    (async () => {
      const headers = getHeaders ? await getHeaders() : {};
      try {
        const res = await fetch(
          `${apiBase}/ingest/structured/${domainId}/${tableName}/sample`,
          { headers },
        );
        const data = res.ok ? await res.json() : { rows: [] };
        setSampleRows(data.rows ?? []);
      } catch {
        // sample is non-critical — ignore errors
      } finally {
        setLoadingSample(false);
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase, domainId, tableName]);

  // Sync draft when initialAnnotation changes from outside (e.g. parent domain refresh)
  useEffect(() => {
    if (initialAnnotation) {
      setDraft(JSON.parse(JSON.stringify(initialAnnotation)));
    }
  }, [initialAnnotation]);

  const setColField = (col: string, field: "description" | "type", value: string) =>
    setDraft(prev => ({
      ...prev,
      columns: { ...prev.columns, [col]: { ...prev.columns[col], [field]: value } },
    }));

  const autoAnnotate = async () => {
    setInferring(true); setMsg("");
    try {
      const headers = getHeaders ? await getHeaders() : {};
      const res = await fetch(`${apiBase}/domains/${domainId}/infer-schema`, {
        method: "POST", headers,
      });
      if (!res.ok) { setMsg(`Error: ${(await res.json()).detail}`); return; }
      const data = await res.json();
      const suggested: SchemaAnnotation = data.schema_annotation ?? {};
      if (suggested[tableName]) {
        setDraft(prev => ({
          ...prev,
          columns: Object.fromEntries(
            Object.entries(prev.columns).map(([col, info]) => [
              col,
              {
                ...info,
                description: suggested[tableName].columns[col]?.description ?? info.description,
              },
            ]),
          ),
        }));
        setMsg("Draft generated — review and save.");
      }
    } catch (err) { setMsg(`Error: ${String(err)}`); }
    finally { setInferring(false); }
  };

  const save = async () => {
    setSaving(true); setMsg("");
    try {
      const headers = getHeaders ? await getHeaders() : {};
      const columns = Object.entries(draft.columns).map(([name, info]: [string, ColumnInfo]) => ({
        name,
        description: info.description ?? "",
        type: info.type ?? "",
      }));
      const res = await fetch(
        `${apiBase}/ingest/structured/${domainId}/${tableName}/annotation`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...headers },
          body: JSON.stringify({ description: draft.description, columns }),
        },
      );
      const data = await res.json();
      if (res.ok) {
        if (data.warnings?.length) setMsg(`Saved with warnings: ${data.warnings.join("; ")}`);
        else setMsg("Saved.");
        onSaved?.();
      } else {
        setMsg(`Error: ${data.detail}`);
      }
    } catch (err) { setMsg(`Error: ${String(err)}`); }
    finally { setSaving(false); }
  };

  const label = tableLabel(domainId, tableName);
  const colNames = Object.keys(draft.columns);

  return (
    <div style={s.box}>
      {/* Header */}
      <div style={s.header}>
        <span style={s.tableLabel}>{label}</span>
        <span style={s.rowCount}>{draft.row_count} rows</span>
        <div style={s.headerActions}>
          <button style={s.inferBtn} onClick={autoAnnotate} disabled={inferring}>
            {inferring ? "Inferring…" : "✨ Auto-annotate"}
          </button>
          {onSkip && (
            <button style={s.cancelBtn} onClick={onSkip}>Skip</button>
          )}
          <button style={s.saveBtn} onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {msg && (
        <p style={{ ...s.msg, color: msg.startsWith("Error") ? "#dc2626" : "#166534" }}>
          {msg}
        </p>
      )}

      {/* Table description */}
      <div style={{ marginBottom: 14 }}>
        <label style={s.label}>
          Table description
          <span style={s.labelHint}>helps the agent decide when to query this table</span>
        </label>
        <textarea
          style={{ ...s.textarea, minHeight: 52 }}
          rows={2}
          placeholder="e.g. Invoice line items for Q1 2024 — use to answer revenue and pricing questions"
          value={draft.description ?? ""}
          onChange={e => setDraft(prev => ({ ...prev, description: e.target.value }))}
        />
      </div>

      {/* Column grid */}
      {colNames.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={s.colGridHeader}>
            <span>Column</span><span>Type</span><span>Description</span>
          </div>
          <div style={s.colGrid}>
            {colNames.map(col => (
              <div key={col} style={s.colRow}>
                <span style={s.colName}>
                  {col}
                  {draft.columns[col]?.source === "context" && (
                    <span style={s.ctxBadge}>ctx</span>
                  )}
                </span>
                <select
                  style={s.typeSelect}
                  value={draft.columns[col]?.type ?? "TEXT"}
                  onChange={e => setColField(col, "type", e.target.value)}
                >
                  {PG_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
                <input
                  style={s.colInput}
                  placeholder="Add description…"
                  value={draft.columns[col]?.description ?? ""}
                  onChange={e => setColField(col, "description", e.target.value)}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sample rows */}
      <div>
        <div style={s.previewHeading}>
          Preview {loadingSample ? "(loading…)" : `(${sampleRows.length} rows)`}
        </div>
        {sampleRows.length > 0 ? (
          <div style={{ overflowX: "auto" }}>
            <table style={s.table}>
              <thead>
                <tr>
                  {Object.keys(sampleRows[0]).map(h => (
                    <th key={h} style={s.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sampleRows.map((row, i) => (
                  <tr key={i} style={i % 2 === 1 ? { background: "#f8fafc" } : {}}>
                    {Object.values(row).map((v, j) => (
                      <td key={j} style={s.td}>
                        {String(v).length > 32 ? String(v).slice(0, 31) + "…" : String(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : !loadingSample ? (
          <p style={{ fontSize: 12, color: "#94a3b8", margin: 0 }}>No data rows.</p>
        ) : null}
      </div>
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  box: {
    background: "#fff", border: "1px solid #e2e8f0",
    borderRadius: 12, padding: "16px 20px", marginBottom: 16,
    fontFamily: "system-ui, sans-serif",
  },
  header: {
    display: "flex", gap: 8, marginBottom: 12,
    alignItems: "center", flexWrap: "wrap",
  },
  tableLabel: {
    fontSize: 12, fontWeight: 700, color: "#166534",
    fontFamily: "monospace", background: "#f0fdf4",
    borderRadius: 4, padding: "2px 6px",
  },
  rowCount: { fontSize: 11, color: "#94a3b8" },
  headerActions: { marginLeft: "auto", display: "flex", gap: 6, flexWrap: "wrap" },
  msg: { fontSize: 11, margin: "0 0 10px" },
  label: {
    display: "block", fontSize: 11, fontWeight: 700,
    color: "#374151", marginBottom: 4,
  },
  labelHint: { fontWeight: 400, color: "#94a3b8", marginLeft: 6 },
  textarea: {
    display: "block", width: "100%", padding: "8px 10px",
    borderRadius: 8, border: "1px solid #cbd5e1",
    fontSize: 13, marginBottom: 0, resize: "vertical" as const,
    fontFamily: "inherit", boxSizing: "border-box" as const, lineHeight: 1.5,
  },
  colGridHeader: {
    display: "grid", gridTemplateColumns: "160px 120px 1fr",
    gap: 8, marginBottom: 4,
    fontSize: 10, fontWeight: 700, color: "#94a3b8",
    textTransform: "uppercase", letterSpacing: "0.05em",
  },
  colGrid: { display: "flex", flexDirection: "column", gap: 5 },
  colRow: { display: "grid", gridTemplateColumns: "160px 120px 1fr", gap: 8, alignItems: "center" },
  colName: {
    fontSize: 12, fontWeight: 600, color: "#374151",
    fontFamily: "monospace", background: "#f1f5f9",
    borderRadius: 4, padding: "4px 6px",
    overflow: "hidden", textOverflow: "ellipsis",
  },
  ctxBadge: {
    marginLeft: 4, fontSize: 9, background: "#fef9c3",
    color: "#854d0e", borderRadius: 3, padding: "1px 4px",
    fontWeight: 700, verticalAlign: "middle",
  },
  typeSelect: {
    padding: "4px 6px", borderRadius: 6,
    border: "1px solid #e2e8f0", fontSize: 12,
    background: "#fff", color: "#374151",
  },
  colInput: {
    width: "100%", padding: "4px 8px", borderRadius: 6,
    border: "1px solid #e2e8f0", fontSize: 12,
    boxSizing: "border-box" as const,
  },
  previewHeading: {
    fontSize: 11, fontWeight: 700, color: "#94a3b8",
    textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6,
  },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 12 },
  th: {
    textAlign: "left", padding: "4px 10px",
    background: "#f1f5f9", borderBottom: "1px solid #e2e8f0",
    fontWeight: 700, color: "#374151", whiteSpace: "nowrap",
  },
  td: {
    padding: "4px 10px", borderBottom: "1px solid #f1f5f9",
    color: "#475569", maxWidth: 200,
    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
  },
  inferBtn: {
    padding: "5px 10px", background: "#f0fdf4", color: "#166534",
    border: "1px solid #bbf7d0", borderRadius: 7,
    fontSize: 11, fontWeight: 600, cursor: "pointer",
  },
  saveBtn: {
    padding: "5px 14px", background: "#2563eb", color: "#fff",
    border: "none", borderRadius: 7, fontSize: 12, fontWeight: 600, cursor: "pointer",
  },
  cancelBtn: {
    padding: "5px 12px", background: "#f1f5f9", color: "#475569",
    border: "1px solid #e2e8f0", borderRadius: 7,
    fontSize: 12, fontWeight: 600, cursor: "pointer",
  },
};
