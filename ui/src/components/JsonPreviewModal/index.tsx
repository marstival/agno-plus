/**
 * JsonPreviewModal — overlay modal for displaying and copying JSON data.
 *
 * Props:
 *   title   optional modal heading (default: "JSON Preview")
 *   data    any JSON-serializable value to display
 *   onClose called when the modal is dismissed
 */

import React from "react";

export interface JsonPreviewModalProps {
  title?: string;
  data: unknown;
  onClose: () => void;
}

export function JsonPreviewModal({ title = "JSON Preview", data, onClose }: JsonPreviewModalProps) {
  const json = JSON.stringify(data, null, 2);

  return (
    <div style={s.overlay} onClick={onClose}>
      <div style={s.modal} onClick={e => e.stopPropagation()}>
        <div style={s.header}>
          <h3 style={s.title}>{title}</h3>
          <button style={s.closeBtn} onClick={onClose} aria-label="Close">✕</button>
        </div>
        <textarea readOnly style={s.area} value={json} />
        <button
          style={s.copyBtn}
          onClick={() => navigator.clipboard.writeText(json)}
        >
          Copy JSON
        </button>
      </div>
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  overlay: {
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
    display: "flex", alignItems: "center", justifyContent: "center",
    zIndex: 200, fontFamily: "system-ui, sans-serif",
  },
  modal: {
    background: "#fff", borderRadius: 14, padding: 20,
    width: "min(720px, 90vw)", maxHeight: "80vh",
    display: "flex", flexDirection: "column",
    boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
  },
  header: {
    display: "flex", justifyContent: "space-between",
    alignItems: "center", marginBottom: 12,
  },
  title: { margin: 0, fontSize: 14, fontWeight: 700, color: "#1e293b" },
  closeBtn: {
    background: "none", border: "none", fontSize: 16,
    cursor: "pointer", color: "#64748b", padding: 4,
  },
  area: {
    flex: 1, fontFamily: "monospace", fontSize: 12,
    resize: "none", border: "1px solid #e2e8f0",
    borderRadius: 8, padding: 12, overflowY: "auto",
    minHeight: 300, maxHeight: "60vh", background: "#f8fafc",
    color: "#1e293b",
  },
  copyBtn: {
    marginTop: 8, padding: "6px 14px",
    background: "#f1f5f9", color: "#475569",
    border: "1px solid #e2e8f0", borderRadius: 7,
    fontSize: 13, fontWeight: 600, cursor: "pointer",
    alignSelf: "flex-start",
  },
};
