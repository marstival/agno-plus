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
// Structured tab — file picker + table description input + Upload button.
// The schema is inferred during ingestion (no synchronous preview round-trip).
// Column descriptions stay empty until the user opens the schema editor below.
// ---------------------------------------------------------------------------

function StructuredTab({
  apiBase,
  onPreviewFile,
}: {
  apiBase: string;
  onPreviewFile: (p: { title: string; data: unknown }) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [uploading, setUploading] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [tablesKey, setTablesKey] = useState(0);

  const upload = async () => {
    if (!file) return;
    setUploadError(null);
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    form.append("ingest_mode", "structured");
    form.append("description", description);
    try {
      const res = await fetch(`${apiBase}/ingest`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) {
        setUploadError(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
      } else {
        setActiveJobId(data.job_id as string);
        setFile(null);
        setDescription("");
      }
    } catch (e) {
      setUploadError(String(e));
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      <div style={s.topRow}>
        <section style={s.card}>
          <h2 style={s.title}>Add a structured table</h2>
          <p style={s.hint}>
            Pick a CSV / Excel file and describe what's in it. On Upload the
            schema is inferred from the data and the table is created. Open
            the table in <b>Loaded tables</b> to add column descriptions or
            change column types later.
          </p>
          <FilePicker
            accept={[".csv", ".tsv", ".xlsx", ".xls"]}
            disabled={uploading}
            selectedName={file?.name}
            onPicked={setFile}
          />
          <label style={{ ...s.label, marginTop: 14 }}>Table description</label>
          <textarea
            style={s.textarea}
            rows={2}
            placeholder="e.g. Q1 2024 expense report"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={uploading}
          />
          <div style={{ ...s.actions, justifyContent: "flex-start" }}>
            <button
              style={{ ...s.btnPrimary, opacity: !file || uploading ? 0.5 : 1 }}
              onClick={upload}
              disabled={!file || uploading}
            >
              {uploading ? "Uploading…" : "Upload"}
            </button>
          </div>
          {uploadError && <p style={s.error}>{uploadError}</p>}
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
  selectedName,
  onPicked,
}: {
  accept: string[];
  disabled?: boolean;
  selectedName?: string;
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
        {selectedName ? `Selected: ${selectedName}` : `Click to choose a file (${accept.join(", ")})`}
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
  actions: {
    display: "flex",
    gap: 10,
    justifyContent: "flex-end",
    marginTop: 14,
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
