import React, { useState } from "react";
import ChatPage from "./pages/ChatPage";
import IngestPage from "./pages/IngestPage";

export const API_BASE = "http://localhost:8000";
export const USER_ID = "demo_user";

type Tab = "chat" | "ingest";

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");

  return (
    <div style={s.root}>
      <header style={s.header}>
        <span style={s.brand}>Personal Aide</span>
        <nav style={s.tabs}>
          <TabBtn active={tab === "chat"} onClick={() => setTab("chat")}>
            Chat
          </TabBtn>
          <TabBtn active={tab === "ingest"} onClick={() => setTab("ingest")}>
            Ingest
          </TabBtn>
        </nav>
        <span style={s.tagline}>powered by agno-plus</span>
      </header>

      <main style={s.main}>
        {tab === "chat" ? (
          <ChatPage apiBase={API_BASE} userId={USER_ID} />
        ) : (
          <IngestPage apiBase={API_BASE} userId={USER_ID} />
        )}
      </main>
    </div>
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
        ...s.tab,
        ...(active ? s.tabActive : {}),
      }}
    >
      {children}
    </button>
  );
}

const s: Record<string, React.CSSProperties> = {
  root: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    fontFamily: "system-ui, -apple-system, sans-serif",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 16,
    padding: "0 24px",
    height: 52,
    background: "#fff",
    borderBottom: "1px solid #e2e8f0",
    flexShrink: 0,
  },
  brand: {
    fontWeight: 700,
    fontSize: 16,
    color: "#1e293b",
    marginRight: 8,
  },
  tabs: {
    display: "flex",
    gap: 4,
  },
  tab: {
    padding: "4px 14px",
    fontSize: 14,
    fontWeight: 500,
    border: "none",
    borderRadius: 6,
    cursor: "pointer",
    background: "transparent",
    color: "#64748b",
    transition: "background 120ms, color 120ms",
  },
  tabActive: {
    background: "#eff6ff",
    color: "#2563eb",
  },
  tagline: {
    marginLeft: "auto",
    fontSize: 11,
    color: "#94a3b8",
  },
  main: {
    flex: 1,
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
  },
};
