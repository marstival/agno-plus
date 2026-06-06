import React, { useEffect, useState } from "react";
import {
  FileListBrowser,
  IngestedFile,
  JobStatusWidget,
  JsonPreviewModal,
  TableInfo,
  TableSchemaEditor,
  UploadWidget,
} from "@agno-plus/ui";

interface Props {
  apiBase: string;
}

type Tab = "semantic" | "structured";

// ---------------------------------------------------------------------------
// Tab shell
// ---------------------------------------------------------------------------

export default function KnowledgePage({ apiBase }: Props) {
  const [tab, setTab] = useState<Tab>("semantic");
  const [preview, setPreview] = useState<{ title: string; data: unknown } | null>(null);

  return (
    <div style={s.page}>
      {preview && (
        <JsonPreviewModal
          title={preview.title}
          data={preview.data}
          onClose={() => setPreview(null)}
        />
      )}
      <div style={s.tabBar}>
        <TabBtn active={tab === "semantic"} onClick={() => setTab("semantic")}>
          Semantic
        </TabBtn>
        <TabBtn active={tab === "structured"} onClick={() => setTab("structured")}>
          Structured
        </TabBtn>
      </div>
      {tab === "semantic" ? (
        <SemanticTab apiBase={apiBase} onPreviewFile={setPreview} />
      ) : (
        <StructuredTab apiBase={apiBase} onPreviewFile={setPreview} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Semantic tab — UploadWidget auto-uploads on drop. File list shows
// non-structured ingests (document, image).
// ---------------------------------------------------------------------------

function SemanticTab({
  apiBase,
  onPreviewFile,
}: {
  apiBase: string;
  onPreviewFile: (p: { title: string; data: unknown }) => void;
}) {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [filesKey, setFilesKey] = useState(0);

  const handleSuccess = (result: Record<string, unknown>) => {
    if (result.job_id) setActiveJobId(result.job_id as string);
    setFilesKey((k) => k + 1);
  };

  return (
    <>
      <div style={s.topRow}>
        <section style={s.card}>
          <h2 style={s.title}>Upload</h2>
          <p style={s.hint}>
            Files are chunked and embedded for semantic search. PDFs are parsed
            into prose and table blocks; each table row becomes its own retrievable
            chunk. No SQL table is created.
          </p>
          <UploadWidget
            ingestUrl={`${apiBase}/ingest`}
            onSuccess={handleSuccess}
            extraFields={{ ingest_mode: "semantic" }}
            accept={[".txt", ".md", ".pdf", ".jpg", ".jpeg", ".png", ".webp"]}
          />
        </section>
        {activeJobId && (
          <section style={s.card}>
            <h2 style={s.title}>Ingestion progress</h2>
            <JobStatusWidget
              jobId={activeJobId}
              statusUrl={`${apiBase}/jobs`}
              onComplete={() => {
                setActiveJobId(null);
                setFilesKey((k) => k + 1);
              }}
              pollIntervalMs={800}
            />
          </section>
        )}
      </div>
      <section style={{ ...s.card, marginTop: 20 }}>
        <h2 style={s.title}>Ingested files</h2>
        <FileListBrowser
          key={filesKey}
          filesUrl={`${apiBase}/files?source_type=document,image`}
          domainId="personal"
          onDeleteFile={(id) => fetch(`${apiBase}/files/${id}`, { method: "DELETE" }).then()}
          onDownloadFile={(id) => window.open(`${apiBase}/files/${id}/raw`, "_blank")}
          onPreviewFile={async (id, filename) => {
            const res = await fetch(`${apiBase}/files/${id}/preview`);
            const data = await res.json();
            onPreviewFile({ title: `Extraction Preview — ${filename}`, data: data.payload });
          }}
        />
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------
// Structured tab — file picker → preview-and-edit form → commit. Shows
// "Loaded Tables" below.
// ---------------------------------------------------------------------------

interface PreviewColumn {
  name: string;
  safe_name: string;
  type: string;
  description: string;
  allowed_types: string[];
}

interface StructuredPreview {
  preview_id: string;
  filename: string;
  table_name: string;
  row_count: number;
  sample_rows: Array<Record<string, string>>;
  description: string;
  columns: PreviewColumn[];
}

function StructuredTab({
  apiBase,
  onPreviewFile,
}: {
  apiBase: string;
  onPreviewFile: (p: { title: string; data: unknown }) => void;
}) {
  const [preview, setPreview] = useState<StructuredPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [tablesKey, setTablesKey] = useState(0);

  const handleFile = async (file: File) => {
    setPreviewError(null);
    setPreviewing(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`${apiBase}/ingest/preview/structured`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) {
        setPreviewError(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
      } else {
        setPreview(data);
      }
    } catch (e) {
      setPreviewError(String(e));
    } finally {
      setPreviewing(false);
    }
  };

  if (preview) {
    return (
      <StructuredPreviewForm
        apiBase={apiBase}
        preview={preview}
        onCancel={() => {
          fetch(`${apiBase}/ingest/preview/${preview.preview_id}`, { method: "DELETE" }).catch(() => {});
          setPreview(null);
        }}
        onCommitted={(jobId) => {
          setPreview(null);
          setActiveJobId(jobId);
        }}
      />
    );
  }

  return (
    <>
      <div style={s.topRow}>
        <section style={s.card}>
          <h2 style={s.title}>Add a structured table</h2>
          <p style={s.hint}>
            Pick a CSV / Excel file. The schema is parsed and the LLM proposes
            a description for each column. Review and edit the schema before
            committing — the SQL table is created only when you press
            <b> Ingest</b>.
          </p>
          <FilePicker
            accept={[".csv", ".tsv", ".xlsx", ".xls"]}
            disabled={previewing}
            onPicked={handleFile}
          />
          {previewing && <p style={s.hint}>Parsing &amp; inferring schema…</p>}
          {previewError && <p style={s.error}>{previewError}</p>}
        </section>
        {activeJobId && (
          <section style={s.card}>
            <h2 style={s.title}>Ingestion progress</h2>
            <JobStatusWidget
              jobId={activeJobId}
              statusUrl={`${apiBase}/jobs`}
              onComplete={() => {
                setActiveJobId(null);
                setTablesKey((k) => k + 1);
              }}
              pollIntervalMs={500}
            />
          </section>
        )}
      </div>
      <section style={{ ...s.card, marginTop: 20 }}>
        <h2 style={s.title}>Loaded tables</h2>
        <FileListBrowser
          key={tablesKey}
          filesUrl={`${apiBase}/files?source_type=structured`}
          domainId="personal"
          onDeleteFile={(id) => fetch(`${apiBase}/files/${id}`, { method: "DELETE" }).then()}
          onDownloadFile={(id) => window.open(`${apiBase}/files/${id}/raw`, "_blank")}
          onPreviewFile={async (id, filename) => {
            const res = await fetch(`${apiBase}/files/${id}/preview`);
            const data = await res.json();
            onPreviewFile({ title: `Extraction Preview — ${filename}`, data: data.payload });
          }}
          renderExpandedRow={(file: IngestedFile) => {
            const tableName = file.tables_created?.[0];
            if (!tableName) return null;
            return (
              <AnnotatedTableEditor
                apiBase={apiBase}
                tableName={tableName}
                onSaved={() => setTablesKey((k) => k + 1)}
              />
            );
          }}
        />
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------
// Schema preview-and-edit form
// ---------------------------------------------------------------------------

function StructuredPreviewForm({
  apiBase,
  preview,
  onCancel,
  onCommitted,
}: {
  apiBase: string;
  preview: StructuredPreview;
  onCancel: () => void;
  onCommitted: (jobId: string) => void;
}) {
  const [description, setDescription] = useState(preview.description);
  const [columns, setColumns] = useState(preview.columns);
  const [committing, setCommitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateColumn = (idx: number, patch: Partial<PreviewColumn>) =>
    setColumns((cs) => cs.map((c, i) => (i === idx ? { ...c, ...patch } : c)));

  const commit = async () => {
    setCommitting(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/ingest/commit/structured`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          preview_id: preview.preview_id,
          description,
          columns: columns.map((c) => ({
            name: c.name,
            type: c.type,
            description: c.description,
          })),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
      } else {
        onCommitted(data.job_id as string);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setCommitting(false);
    }
  };

  return (
    <section style={{ ...s.card, marginTop: 0 }}>
      <h2 style={s.title}>Review &amp; ingest — {preview.filename}</h2>
      <p style={s.hint}>
        Table <code>{preview.table_name}</code> · {preview.row_count} rows.
        Describe the table and review each column before pressing Ingest.
      </p>

      <label style={s.label}>Table description</label>
      <textarea
        style={s.textarea}
        rows={2}
        placeholder="e.g. Q1 2024 expense report"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />

      <div style={{ marginTop: 16 }}>
        <div style={s.colHead}>
          <span style={{ flex: "0 0 22%" }}>Column</span>
          <span style={{ flex: "0 0 18%" }}>Type</span>
          <span style={{ flex: 1 }}>Description</span>
        </div>
        {columns.map((c, i) => (
          <div key={c.safe_name} style={s.colRow}>
            <div style={{ flex: "0 0 22%" }}>
              <div style={s.colName}>{c.name}</div>
              <div style={s.colSafe}>SQL: {c.safe_name}</div>
            </div>
            <select
              style={{ ...s.input, flex: "0 0 18%" }}
              value={c.type}
              onChange={(e) => updateColumn(i, { type: e.target.value })}
            >
              {c.allowed_types.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <input
              style={{ ...s.input, flex: 1 }}
              placeholder="describe what this column holds"
              value={c.description}
              onChange={(e) => updateColumn(i, { description: e.target.value })}
            />
          </div>
        ))}
      </div>

      <details style={{ marginTop: 16, fontSize: 12 }}>
        <summary style={{ cursor: "pointer", color: "#64748b" }}>
          Sample rows ({preview.sample_rows.length})
        </summary>
        <pre style={s.samplePre}>{JSON.stringify(preview.sample_rows, null, 2)}</pre>
      </details>

      {error && <p style={s.error}>{error}</p>}

      <div style={s.actions}>
        <button style={s.btnSecondary} onClick={onCancel} disabled={committing}>
          Cancel
        </button>
        <button style={s.btnPrimary} onClick={commit} disabled={committing}>
          {committing ? "Ingesting…" : "Ingest"}
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Annotated table editor (re-used for post-commit edits)
// ---------------------------------------------------------------------------

function AnnotatedTableEditor({
  apiBase,
  tableName,
  onSaved,
}: {
  apiBase: string;
  tableName: string;
  onSaved: () => void;
}) {
  const [annotation, setAnnotation] = useState<TableInfo | undefined>();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${apiBase}/ingest/structured/personal/${tableName}/annotation`)
      .then((r) => r.json())
      .then((data) => setAnnotation(data.annotation))
      .catch(() => setAnnotation({ description: "", columns: {}, row_count: 0 }))
      .finally(() => setLoading(false));
  }, [apiBase, tableName]);

  if (loading) return <p style={s.hint}>Loading schema…</p>;
  return (
    <TableSchemaEditor
      domainId="personal"
      tableName={tableName}
      apiBase={apiBase}
      initialAnnotation={annotation}
      onSaved={onSaved}
    />
  );
}

// ---------------------------------------------------------------------------
// Small primitives
// ---------------------------------------------------------------------------

function FilePicker({
  accept,
  disabled,
  onPicked,
}: {
  accept: string[];
  disabled?: boolean;
  onPicked: (file: File) => void;
}) {
  return (
    <label style={{ ...s.filePicker, opacity: disabled ? 0.5 : 1 }}>
      <input
        type="file"
        accept={accept.join(",")}
        disabled={disabled}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPicked(f);
          e.target.value = ""; // allow re-picking same file
        }}
        style={{ display: "none" }}
      />
      <span style={s.filePickerInner}>
        Click to choose a file ({accept.join(", ")})
      </span>
    </label>
  );
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "8px 18px",
        fontSize: 13,
        fontWeight: 700,
        borderRadius: 0,
        cursor: "pointer",
        border: "none",
        borderBottom: active ? "2.5px solid #2563eb" : "2.5px solid transparent",
        background: "transparent",
        color: active ? "#2563eb" : "#64748b",
      }}
    >
      {children}
    </button>
  );
}

const s: Record<string, React.CSSProperties> = {
  page: {
    overflowY: "auto",
    padding: "24px",
    height: "100%",
    display: "flex",
    flexDirection: "column",
  },
  tabBar: {
    display: "flex",
    gap: 4,
    borderBottom: "1px solid #e2e8f0",
    marginBottom: 18,
  },
  topRow: { display: "flex", gap: 20, flexWrap: "wrap" },
  card: {
    background: "#fff",
    border: "1px solid #e2e8f0",
    borderRadius: 14,
    padding: "20px 24px",
    flex: "1 1 320px",
  },
  title: { margin: "0 0 10px", fontSize: 15, fontWeight: 700, color: "#1e293b" },
  hint: { margin: "0 0 14px", fontSize: 13, color: "#64748b", lineHeight: 1.5 },
  error: { margin: "10px 0", fontSize: 13, color: "#dc2626", lineHeight: 1.5 },
  label: { display: "block", fontSize: 12, fontWeight: 600, color: "#475569", marginBottom: 6 },
  textarea: {
    width: "100%",
    border: "1px solid #e2e8f0",
    borderRadius: 8,
    padding: "8px 10px",
    fontSize: 13,
    fontFamily: "inherit",
    resize: "vertical",
  },
  input: {
    border: "1px solid #e2e8f0",
    borderRadius: 6,
    padding: "6px 8px",
    fontSize: 13,
    fontFamily: "inherit",
    background: "#fff",
  },
  colHead: {
    display: "flex",
    gap: 10,
    fontSize: 11,
    fontWeight: 700,
    color: "#94a3b8",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    padding: "0 4px 6px",
    borderBottom: "1px solid #f1f5f9",
  },
  colRow: {
    display: "flex",
    gap: 10,
    alignItems: "center",
    padding: "8px 4px",
    borderBottom: "1px dashed #f1f5f9",
  },
  colName: { fontSize: 13, fontWeight: 600, color: "#1e293b" },
  colSafe: { fontSize: 11, color: "#94a3b8", fontFamily: "monospace" },
  samplePre: {
    background: "#0f172a",
    color: "#e2e8f0",
    fontSize: 11,
    padding: 10,
    borderRadius: 8,
    overflowX: "auto",
    margin: "8px 0 0",
  },
  actions: {
    display: "flex",
    gap: 10,
    justifyContent: "flex-end",
    marginTop: 18,
    paddingTop: 14,
    borderTop: "1px solid #f1f5f9",
  },
  btnPrimary: {
    padding: "8px 18px",
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    fontWeight: 600,
    fontSize: 13,
    cursor: "pointer",
  },
  btnSecondary: {
    padding: "8px 18px",
    background: "#fff",
    color: "#475569",
    border: "1px solid #e2e8f0",
    borderRadius: 8,
    fontWeight: 600,
    fontSize: 13,
    cursor: "pointer",
  },
  filePicker: {
    display: "block",
    maxWidth: 480,                   // match UploadWidget drop-zone width
    border: "2px dashed #cbd5e1",
    borderRadius: 12,
    padding: "32px 24px",            // match UploadWidget vertical/horizontal padding
    textAlign: "center",
    cursor: "pointer",
    background: "#f8fafc",
  },
  filePickerInner: { fontSize: 13, color: "#475569", fontWeight: 600 },
};
