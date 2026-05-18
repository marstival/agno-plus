/**
 * KnowledgeBrowser — search and list ingested memory records.
 *
 * Props:
 *   memoriesUrl    GET endpoint: {memoriesUrl}?query=&user_id= → { records: MemoryRecord[] }
 *   userId         passed as ?user_id= query param
 *   pageSize       records per page (default 20)
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import type { MemoryRecord } from "../../types";

export interface KnowledgeBrowserProps {
  memoriesUrl: string;
  userId: string;
  pageSize?: number;
}

type LoadState = "idle" | "loading" | "done" | "error";

export function KnowledgeBrowser({ memoriesUrl, userId, pageSize = 20 }: KnowledgeBrowserProps) {
  const [query, setQuery] = useState("");
  const [records, setRecords] = useState<MemoryRecord[]>([]);
  const [page, setPage] = useState(0);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchRecords = useCallback(
    async (q: string) => {
      setLoadState("loading");
      setErrorMsg(null);
      try {
        const params = new URLSearchParams({ user_id: userId });
        if (q.trim()) params.set("query", q.trim());
        const res = await fetch(`${memoriesUrl}?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: { records: MemoryRecord[] } = await res.json();
        setRecords(data.records ?? []);
        setPage(0);
        setLoadState("done");
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
        setLoadState("error");
      }
    },
    [memoriesUrl, userId],
  );

  // Initial load
  useEffect(() => {
    fetchRecords("");
  }, [fetchRecords]);

  // Debounced search
  const handleSearch = (value: string) => {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchRecords(value), 350);
  };

  const totalPages = Math.ceil(records.length / pageSize);
  const visible = records.slice(page * pageSize, (page + 1) * pageSize);

  return (
    <div style={styles.wrapper}>
      {/* Search bar */}
      <div style={styles.searchRow}>
        <input
          type="search"
          placeholder="Search memories…"
          value={query}
          onChange={(e) => handleSearch(e.target.value)}
          style={styles.searchInput}
          aria-label="Search"
        />
        {loadState === "loading" && <span style={styles.loadingDot}>●</span>}
      </div>

      {/* Error */}
      {loadState === "error" && (
        <p style={styles.errorText}>{errorMsg}</p>
      )}

      {/* Empty state */}
      {loadState === "done" && records.length === 0 && (
        <p style={styles.emptyText}>
          {query ? `No results for "${query}"` : "No memories yet. Upload a file to get started."}
        </p>
      )}

      {/* Record list */}
      {visible.length > 0 && (
        <ul style={styles.list}>
          {visible.map((record) => (
            <MemoryCard key={record.id} record={record} />
          ))}
        </ul>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={styles.pagination}>
          <button
            style={styles.pageBtn}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            aria-label="Previous page"
          >
            ‹
          </button>
          <span style={styles.pageInfo}>
            {page + 1} / {totalPages}
          </span>
          <button
            style={styles.pageBtn}
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            aria-label="Next page"
          >
            ›
          </button>
        </div>
      )}
    </div>
  );
}

function MemoryCard({ record }: { record: MemoryRecord }) {
  const blockType = record.metadata.block_type as string | undefined;
  const sourceName = record.metadata.source_name as string | undefined;
  const eventAt = record.event_at
    ? new Date(record.event_at).toLocaleDateString()
    : null;

  return (
    <li style={styles.card}>
      <div style={styles.cardHeader}>
        {blockType && <Tag label={blockType} />}
        {sourceName && <span style={styles.sourceLabel}>{sourceName}</span>}
        {eventAt && <span style={styles.dateLabel}>{eventAt}</span>}
      </div>
      <p style={styles.cardContent}>{truncate(record.content, 240)}</p>
    </li>
  );
}

function Tag({ label }: { label: string }) {
  const colors: Record<string, string> = {
    table:   "#3b82f6",
    kv_pair: "#8b5cf6",
    note:    "#f59e0b",
  };
  const color = colors[label] ?? "#64748b";
  return (
    <span style={{ ...styles.tag, background: color + "18", color }}>
      {label}
    </span>
  );
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + "…" : text;
}

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    fontFamily: "system-ui, sans-serif",
    maxWidth: 640,
  },
  searchRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginBottom: 16,
  },
  searchInput: {
    flex: 1,
    padding: "8px 14px",
    fontSize: 14,
    border: "1px solid #cbd5e1",
    borderRadius: 8,
    outline: "none",
  },
  loadingDot: {
    color: "#3b82f6",
    fontSize: 10,
    animation: "pulse 1s infinite",
  },
  errorText: {
    color: "#dc2626",
    fontSize: 13,
    padding: "8px 12px",
    background: "#fef2f2",
    borderRadius: 6,
    marginBottom: 12,
  },
  emptyText: {
    color: "#94a3b8",
    fontSize: 14,
    textAlign: "center",
    padding: "32px 0",
  },
  list: {
    listStyle: "none",
    margin: 0,
    padding: 0,
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  card: {
    border: "1px solid #e2e8f0",
    borderRadius: 10,
    padding: "14px 16px",
    background: "#fff",
  },
  cardHeader: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginBottom: 8,
    flexWrap: "wrap",
  },
  tag: {
    fontSize: 11,
    fontWeight: 600,
    padding: "2px 8px",
    borderRadius: 999,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
  },
  sourceLabel: {
    fontSize: 12,
    color: "#64748b",
    fontFamily: "monospace",
  },
  dateLabel: {
    fontSize: 12,
    color: "#94a3b8",
    marginLeft: "auto",
  },
  cardContent: {
    margin: 0,
    fontSize: 13,
    color: "#334155",
    lineHeight: 1.6,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  pagination: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    marginTop: 16,
  },
  pageBtn: {
    padding: "4px 14px",
    fontSize: 18,
    border: "1px solid #e2e8f0",
    borderRadius: 6,
    background: "#fff",
    cursor: "pointer",
    lineHeight: 1,
  },
  pageInfo: {
    fontSize: 13,
    color: "#64748b",
  },
};
