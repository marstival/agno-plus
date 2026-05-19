import React, { useState } from "react";
import { UploadWidget } from "@agno-plus/ui";
import { JobStatusWidget } from "@agno-plus/ui";
import { KnowledgeBrowser } from "@agno-plus/ui";

interface Props {
  apiBase: string;
  userId: string;
}

export default function IngestPage({ apiBase, userId }: Props) {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [browserKey, setBrowserKey] = useState(0);

  const handleSuccess = (jobId: string) => {
    setActiveJobId(jobId);
  };

  const handleJobComplete = () => {
    // Force KnowledgeBrowser to remount and refetch fresh records
    setBrowserKey((k) => k + 1);
  };

  return (
    <div style={s.page}>
      {/* Upload + Status row */}
      <div style={s.topRow}>
        <section style={s.card}>
          <h2 style={s.sectionTitle}>Upload to Memory</h2>
          <p style={s.hint}>
            Supported: CSV, Excel (.xlsx, .xls). Files are read, chunked,
            and stored in the knowledge base.
          </p>
          <UploadWidget
            ingestUrl={`${apiBase}/ingest`}
            onSuccess={handleSuccess}
            accept={[".csv", ".xlsx", ".xls", ".tsv"]}
          />
        </section>

        {activeJobId && (
          <section style={s.card}>
            <h2 style={s.sectionTitle}>Ingestion Progress</h2>
            <JobStatusWidget
              jobId={activeJobId}
              statusUrl={`${apiBase}/jobs`}
              onComplete={handleJobComplete}
              pollIntervalMs={800}
            />
          </section>
        )}
      </div>

      {/* Knowledge Browser */}
      <section style={{ ...s.card, marginTop: 24 }}>
        <h2 style={s.sectionTitle}>Knowledge Base</h2>
        <KnowledgeBrowser
          key={browserKey}
          memoriesUrl={`${apiBase}/memories`}
          userId={userId}
          pageSize={10}
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
    gap: 24,
    flexWrap: "wrap",
  },
  card: {
    background: "#fff",
    border: "1px solid #e2e8f0",
    borderRadius: 14,
    padding: "20px 24px",
    flex: "1 1 320px",
  },
  sectionTitle: {
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
