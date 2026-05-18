import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, afterEach } from "vitest";
import { KnowledgeBrowser } from "./index";
import type { MemoryRecord } from "../../types";

const MEMORIES_URL = "http://api/memories";
const USER_ID = "user_test";

function makeRecord(partial: Partial<MemoryRecord> & { id: string }): MemoryRecord {
  return {
    content: "some memory content",
    metadata: {},
    event_at: null,
    ...partial,
  };
}

function mockFetch(records: MemoryRecord[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ records }),
    }),
  );
}

describe("KnowledgeBrowser", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  // ------------------------------------------------------------------
  // Initial load
  // ------------------------------------------------------------------

  it("renders search input", async () => {
    mockFetch([]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);
    expect(screen.getByRole("searchbox", { name: /search/i })).toBeInTheDocument();
  });

  it("fetches records on mount without query param", async () => {
    mockFetch([]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledOnce());

    const [url] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain(MEMORIES_URL);
    expect(url).toContain(`user_id=${USER_ID}`);
    expect(url).not.toContain("query=");
  });

  it("shows empty state when no records returned", async () => {
    mockFetch([]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);
    await waitFor(() =>
      expect(screen.getByText(/no memories yet/i)).toBeInTheDocument(),
    );
  });

  // ------------------------------------------------------------------
  // Record rendering
  // ------------------------------------------------------------------

  it("renders a card for each record", async () => {
    mockFetch([
      makeRecord({ id: "r1", content: "bought groceries" }),
      makeRecord({ id: "r2", content: "went for a run" }),
    ]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);
    await waitFor(() => expect(screen.getByText("bought groceries")).toBeInTheDocument());
    expect(screen.getByText("went for a run")).toBeInTheDocument();
  });

  it("shows block_type tag when present in metadata", async () => {
    mockFetch([
      makeRecord({ id: "r1", content: "table data", metadata: { block_type: "table" } }),
    ]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);
    await waitFor(() => expect(screen.getByText("table")).toBeInTheDocument());
  });

  it("shows source_name when present in metadata", async () => {
    mockFetch([
      makeRecord({ id: "r1", content: "data", metadata: { source_name: "expenses.xlsx" } }),
    ]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);
    await waitFor(() => expect(screen.getByText("expenses.xlsx")).toBeInTheDocument());
  });

  it("shows formatted event_at date when present", async () => {
    mockFetch([
      makeRecord({ id: "r1", content: "data", event_at: "2026-05-17T00:00:00" }),
    ]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);
    await waitFor(() => {
      const cards = screen.getAllByRole("listitem");
      expect(cards[0]).toHaveTextContent(/2026|may|17/i);
    });
  });

  it("truncates long content at 240 chars", async () => {
    const long = "x".repeat(300);
    mockFetch([makeRecord({ id: "r1", content: long })]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);
    await waitFor(() => {
      const card = screen.getByRole("listitem");
      expect(card.textContent).toContain("…");
      expect(card.textContent!.length).toBeLessThan(300);
    });
  });

  // ------------------------------------------------------------------
  // Search — debounce tests use scoped fake timers; no waitFor inside
  // ------------------------------------------------------------------

  it("sends query param when search input changes", async () => {
    vi.useFakeTimers();
    mockFetch([]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);

    // Flush initial fetch (promise-based; not affected by fake timers)
    await act(async () => {});
    expect(global.fetch).toHaveBeenCalledTimes(1);

    // fireEvent.change is synchronous — no internal userEvent timers to deadlock on
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "groceries" } });

    // Fire the 350ms debounce and flush its resulting fetch promise
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    const calls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls;
    const lastUrl = calls[calls.length - 1][0] as string;
    expect(lastUrl).toContain("query=groceries");
  });

  it("shows 'No results' empty state when search returns empty", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ records: [makeRecord({ id: "r1", content: "unrelated" })] }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ records: [] }) });
    vi.stubGlobal("fetch", fetchMock);

    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);

    // Flush initial fetch
    await act(async () => {});
    expect(screen.getByText("unrelated")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "xyz" } });

    // Fire debounce and flush the second fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    expect(screen.getByText(/no results for "xyz"/i)).toBeInTheDocument();
  });

  it("debounces: only one fetch for rapid keystrokes", async () => {
    vi.useFakeTimers();
    mockFetch([]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);

    await act(async () => {});
    expect(global.fetch).toHaveBeenCalledTimes(1); // initial

    // Rapid keystrokes via synchronous fireEvent — each one resets the debounce timer
    const input = screen.getByRole("searchbox");
    fireEvent.change(input, { target: { value: "a" } });
    fireEvent.change(input, { target: { value: "ab" } });
    fireEvent.change(input, { target: { value: "abc" } });

    // Debounce hasn't fired yet (< 350ms)
    await act(async () => { vi.advanceTimersByTime(100); });
    expect(global.fetch).toHaveBeenCalledTimes(1);

    // Now past debounce — exactly one search fetch fires
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  // ------------------------------------------------------------------
  // Pagination
  // ------------------------------------------------------------------

  it("does not show pagination when records fit on one page", async () => {
    mockFetch([makeRecord({ id: "r1", content: "a" }), makeRecord({ id: "r2", content: "b" })]);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} pageSize={20} />);
    await waitFor(() => expect(screen.getByText("a")).toBeInTheDocument());

    expect(screen.queryByLabelText(/previous page/i)).not.toBeInTheDocument();
  });

  it("shows pagination controls when records exceed pageSize", async () => {
    const records = Array.from({ length: 5 }, (_, i) =>
      makeRecord({ id: `r${i}`, content: `record ${i}` }),
    );
    mockFetch(records);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} pageSize={2} />);
    await waitFor(() => expect(screen.getByLabelText(/next page/i)).toBeInTheDocument());
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
  });

  it("navigates to next page on › click", async () => {
    const records = Array.from({ length: 4 }, (_, i) =>
      makeRecord({ id: `r${i}`, content: `item ${i}` }),
    );
    mockFetch(records);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} pageSize={2} />);
    await waitFor(() => expect(screen.getByText("item 0")).toBeInTheDocument());

    // Page 1: shows item 0, item 1
    expect(screen.queryByText("item 2")).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText(/next page/i));
    // Page 2: shows item 2, item 3
    expect(screen.getByText("item 2")).toBeInTheDocument();
    expect(screen.queryByText("item 0")).not.toBeInTheDocument();
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
  });

  it("previous page button is disabled on first page", async () => {
    const records = Array.from({ length: 3 }, (_, i) =>
      makeRecord({ id: `r${i}`, content: `item ${i}` }),
    );
    mockFetch(records);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} pageSize={2} />);
    await waitFor(() => screen.getByLabelText(/previous page/i));
    expect(screen.getByLabelText(/previous page/i)).toBeDisabled();
  });

  it("next page button is disabled on last page", async () => {
    const records = Array.from({ length: 3 }, (_, i) =>
      makeRecord({ id: `r${i}`, content: `item ${i}` }),
    );
    mockFetch(records);
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} pageSize={2} />);
    await waitFor(() => screen.getByLabelText(/next page/i));

    await userEvent.click(screen.getByLabelText(/next page/i));
    expect(screen.getByLabelText(/next page/i)).toBeDisabled();
  });

  // ------------------------------------------------------------------
  // Error state
  // ------------------------------------------------------------------

  it("shows error message on fetch failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network down")));
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);
    await waitFor(() =>
      expect(screen.getByText(/network down/i)).toBeInTheDocument(),
    );
  });

  it("shows HTTP error code in error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 503 }),
    );
    render(<KnowledgeBrowser memoriesUrl={MEMORIES_URL} userId={USER_ID} />);
    await waitFor(() =>
      expect(screen.getByText(/http 503/i)).toBeInTheDocument(),
    );
  });
});
