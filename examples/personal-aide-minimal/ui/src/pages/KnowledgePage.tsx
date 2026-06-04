import React, { useEffect, useState } from "react";
import {
  FileListBrowser,
  IngestedFile,
  JobStatusWidget,
  TableInfo,
  TableSchemaEditor,
  UploadWidget,
} from "@agno-plus/ui";

interface Props {
  apiBase: string;
}

type UploadMode = "structured" | "semantic";

/**
 * Fetches the annotation for a structured table then renders TableSchemaEditor.
 * Keeps the parent KnowledgePage free of per-row async state.
 */
function AnnotatedTableEditor({
  apiBase,
  tableName,
  onSaved,
}: {
  apiBase: string;
  tableName: string;
  onSaved: () => void;
}) {
  const [annotation, setAnnotation] = useState<TableInfo | undefined>(undefined);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${apiBase}/ingest/structured/personal/${tableName}/annotation`)
      .then((r) => r.json())
      .then((data) => setAnnotation(data.annotation))
      .catch(() => setAnnotation({ description: "", columns: {}, row_count: 0 }))
      .finally(() => setLoading(false));
  }, [apiBase, tableName]);

  if (loading) return <p style={{ fontSize: 12, color: "#94a3b8", margin: "8px 0" }}>Loading schema…</p>;

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

export default function KnowledgePage({ apiBase }: Props) {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [filesKey, setFilesKey] = useState(0);
  const [uploadMode, setUploadMode] = useState<UploadMode>("semantic");

  const handleSuccess = (result: Record<string, unknown>) => {
    if (result.job_id) setActiveJobId(result.job_id as string);
    setFilesKey((k) => k + 1);
  };

  const handleJobComplete = () => {
    setActiveJobId(null);
    setFilesKey((k) => k + 1);
  };

  const handleDeleteFile = async (fileId: string) => {
    await fetch(`${apiBase}/files/${fileId}`, { method: "DELETE" });
  };

  const handleDownloadFile = (_fileId: string, _filename: string) => {
    window.open(`${apiBase}/files/${_fileId}/raw`, "_blank");
  };

  return (
    <div style={s.page}>
      {/* Upload + status row */}
      <div style={s.topRow}>
        <section style={s.card}>
          <h2 style={s.title}>Upload</h2>

          {/* Mode toggle — only relevant for spreadsheets */}
          <div style={s.modeRow}>
            <ModeBtn active={uploadMode === "semantic"} onClick={() => setUploadMode("semantic")}>
              Semantic only
            </ModeBtn>
            <ModeBtn active={uploadMode === "structured"} onClick={() => setUploadMode("structured")}>
              Structured
            </ModeBtn>
          </div>
          <p style={s.hint}>
            {uploadMode === "semantic"
              ? "All files are chunked and embedded for semantic chat search. No SQL table is created."
              : "CSV / Excel files are loaded into a SQL table (queryable) and also embedded for semantic search. LLM auto-fills column descriptions after upload."}
          </p>

          <UploadWidget
            ingestUrl={`${apiBase}/ingest`}
            onSuccess={handleSuccess}
            extraFields={{ ingest_mode: uploadMode }}
            accept={[".txt", ".md", ".pdf", ".csv", ".xlsx", ".xls", ".tsv", ".jpg", ".jpeg", ".png", ".webp"]}
          />
        </section>

        {activeJobId && (
          <section style={s.card}>
            <h2 style={s.title}>Ingestion progress</h2>
            <JobStatusWidget
              jobId={activeJobId}
              statusUrl={`${apiBase}/jobs`}
              onComplete={handleJobComplete}
              pollIntervalMs={800}
            />
          </section>
        )}
      </div>

      {/* File list */}
      <section style={{ ...s.card, marginTop: 20 }}>
        <h2 style={s.title}>Ingested files</h2>
        <FileListBrowser
          key={filesKey}
          filesUrl={`${apiBase}/files`}
          domainId="personal"
          onDeleteFile={handleDeleteFile}
          onDownloadFile={handleDownloadFile}
          renderExpandedRow={(file: IngestedFile) => {
            const tableName = file.tables_created?.[0];
            if (!tableName) return null;
            return (
              <AnnotatedTableEditor
                apiBase={apiBase}
                tableName={tableName}
                onSaved={() => setFilesKey((k) => k + 1)}
              />
            );
          }}
        />
      </section>
    </div>
  );
}

function ModeBtn({
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
        padding: "4px 12px",
        fontSize: 12,
        fontWeight: 600,
        borderRadius: 6,
        cursor: "pointer",
        border: active ? "1.5px solid #2563eb" : "1.5px solid #e2e8f0",
        background: active ? "#eff6ff" : "#fff",
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
  topRow: { display: "flex", gap: 20, flexWrap: "wrap" },
  card: {
    background: "#fff",
    border: "1px solid #e2e8f0",
    borderRadius: 14,
    padding: "20px 24px",
    flex: "1 1 320px",
  },
  modeRow: { display: "flex", gap: 6, marginBottom: 10 },
  title: { margin: "0 0 10px", fontSize: 15, fontWeight: 700, color: "#1e293b" },
  hint: { margin: "0 0 14px", fontSize: 13, color: "#64748b", lineHeight: 1.5 },
};
