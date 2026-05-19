import React, { useEffect, useRef, useState } from "react";

interface Message {
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
}

interface Props {
  apiBase: string;
  userId: string;
}

const WELCOME: Message = {
  role: "assistant",
  content:
    "Hi! I'm your personal aide. Switch to the Ingest tab to upload spreadsheets into my memory, then come back here and ask me anything about them.",
};

export default function ChatPage({ apiBase, userId }: Props) {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "", pending: true },
    ]);
    setLoading(true);

    try {
      const res = await fetch(`${apiBase}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, user_id: userId }),
      });
      const data = await res.json();
      const reply = res.ok
        ? data.reply
        : `Error: ${data.detail ?? "Unknown error"}`;
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { role: "assistant", content: reply },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          role: "assistant",
          content: `Network error: ${err instanceof Error ? err.message : String(err)}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div style={s.page}>
      {/* Message list */}
      <div style={s.messages}>
        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              ...s.row,
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
            }}
          >
            {msg.role === "assistant" && <Avatar />}
            <div
              style={{
                ...s.bubble,
                ...(msg.role === "user" ? s.bubbleUser : s.bubbleAssistant),
              }}
            >
              {msg.pending ? <Cursor /> : msg.content}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div style={s.inputBar}>
        <textarea
          style={s.textarea}
          placeholder="Ask about your uploaded data… (Enter to send, Shift+Enter for new line)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          rows={2}
          disabled={loading}
        />
        <button
          style={{ ...s.sendBtn, opacity: loading || !input.trim() ? 0.5 : 1 }}
          onClick={send}
          disabled={loading || !input.trim()}
          aria-label="Send"
        >
          Send
        </button>
      </div>
    </div>
  );
}

function Avatar() {
  return (
    <div style={s.avatar} aria-hidden>
      AI
    </div>
  );
}

function Cursor() {
  return <span style={s.cursor}>▍</span>;
}

const s: Record<string, React.CSSProperties> = {
  page: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    maxWidth: 760,
    margin: "0 auto",
    width: "100%",
  },
  messages: {
    flex: 1,
    overflowY: "auto",
    padding: "24px 16px 8px",
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  row: {
    display: "flex",
    alignItems: "flex-end",
    gap: 8,
  },
  avatar: {
    width: 32,
    height: 32,
    borderRadius: "50%",
    background: "#2563eb",
    color: "#fff",
    fontSize: 10,
    fontWeight: 700,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  bubble: {
    maxWidth: "72%",
    padding: "10px 14px",
    borderRadius: 14,
    fontSize: 14,
    lineHeight: 1.55,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  bubbleUser: {
    background: "#2563eb",
    color: "#fff",
    borderBottomRightRadius: 4,
  },
  bubbleAssistant: {
    background: "#fff",
    color: "#1e293b",
    border: "1px solid #e2e8f0",
    borderBottomLeftRadius: 4,
  },
  cursor: {
    display: "inline-block",
    animation: "blink 0.8s step-end infinite",
    color: "#2563eb",
  },
  inputBar: {
    display: "flex",
    gap: 8,
    padding: "12px 16px",
    borderTop: "1px solid #e2e8f0",
    background: "#fff",
    flexShrink: 0,
  },
  textarea: {
    flex: 1,
    resize: "none",
    border: "1px solid #cbd5e1",
    borderRadius: 10,
    padding: "10px 14px",
    fontSize: 14,
    fontFamily: "inherit",
    outline: "none",
    lineHeight: 1.5,
  },
  sendBtn: {
    padding: "0 20px",
    background: "#2563eb",
    color: "#fff",
    border: "none",
    borderRadius: 10,
    fontWeight: 600,
    fontSize: 14,
    cursor: "pointer",
    transition: "opacity 120ms",
    alignSelf: "stretch",
  },
};
