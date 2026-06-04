import React, { useState } from "react";
import {
  FileListBrowser,
  IngestedFile,
  JobStatusWidget,
  TableSchemaEditor,
  UploadWidget,
} from "@agno-plus/ui";

interface Props {
  apiBase: string;
}

export default function KnowledgePage({ apiBase }: Props) {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [filesKey, setFilesKey] = useState(0);

  const handleSuccess = (result: Record<string, unknown>) => {
    if (result.job_id) {
      setActiveJobId(result.job_id as string);
    }
    // Optimistically refresh; the file row appears even before ingest completes
    setFilesKey((k) => k + 1);
  };

  const handleJobComplete = () => {
    setActiveJobId(null);
    // Refresh to pick up final chunks_count and tables_created
    setFilesKey((k) => k + 1);
  };

  const handleDeleteFile = async (fileId: string) => {
    await fetch(`${apiBase}/files/${fileId}`, { method: "DELETE" });
  };

  const handleDownloadFile = (fileId: string, filename: string) => {
    window.open(`${apiBase}/files/${fileId}/raw`, "_blank");
  };

  return (
    <div style={s.page}>
      {/* Upload + status row */}
      <div style={s.topRow}>
        <section style={s.card}>
          <h2 style={s.title}>Upload</h2>
          <p style={s.hint}>
            Documents (.txt, .md, .pdf) are chunked and embedded for semantic
            search. Spreadsheets (.csv, .xlsx) are also loaded into a SQL table
            you can annotate and query.
          </p>
          <UploadWidget
            ingestUrl={`${apiBase}/ingest`}
            onSuccess={handleSuccess}
            accept={[".txt", ".md", ".csv", ".xlsx", ".xls", ".tsv"]}
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
              <TableSchemaEditor
                domainId="personal"
                tableName={tableName}
                apiBase={apiBase}
                onSaved={() => setFilesKey((k) => k + 1)}
              />
            );
          }}
        />
      </section>
    </div>
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
  topRow: {
    display: "flex",
    gap: 20,
    flexWrap: "wrap",
  },
  card: {
    background: "#fff",
    border: "1px solid #e2e8f0",
    borderRadius: 14,
    padding: "20px 24px",
    flex: "1 1 320px",
  },
  title: {
    margin: "0 0 4px",
    fontSize: 15,
    fontWeight: 700,
    color: "#1e293b",
  },
  hint: {
    margin: "0 0 16px",
    fontSize: 13,
    color: "#64748b",
    lineHeight: 1.5,
  },
};
