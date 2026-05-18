import { render, screen, waitFor, act } from "@testing-library/react";
import { vi, describe, it, expect, afterEach } from "vitest";
import { JobStatusWidget } from "./index";
import type { JobStatus } from "../../types";

const STATUS_URL = "http://api/jobs";
const JOB_ID = "job_test001";

function makeStatus(partial: Partial<JobStatus>): JobStatus {
  return {
    job_id: JOB_ID,
    state: "pending",
    current_step: null,
    completed_steps: [],
    error: null,
    ...partial,
  };
}

function mockFetchStatus(statuses: JobStatus[]) {
  let call = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() => {
      const s = statuses[Math.min(call++, statuses.length - 1)];
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(s),
      });
    }),
  );
}

describe("JobStatusWidget", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  // ------------------------------------------------------------------
  // Initial state
  // ------------------------------------------------------------------

  it("shows connecting message before first poll resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} />);
    expect(screen.getByText(/connecting/i)).toBeInTheDocument();
  });

  it("fetches from statusUrl/jobId on mount", async () => {
    mockFetchStatus([makeStatus({ state: "completed", completed_steps: ["read", "ground", "chunk", "embed", "upsert"] })]);
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(`${STATUS_URL}/${JOB_ID}`));
  });

  // ------------------------------------------------------------------
  // Step rendering
  // ------------------------------------------------------------------

  it("renders all 5 pipeline steps", async () => {
    mockFetchStatus([makeStatus({ state: "processing", current_step: "read" })]);
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} />);
    await waitFor(() => expect(screen.getByText("Read file")).toBeInTheDocument());

    expect(screen.getByText("Temporal grounding")).toBeInTheDocument();
    expect(screen.getByText("Chunk text")).toBeInTheDocument();
    expect(screen.getByText("Embed chunks")).toBeInTheDocument();
    expect(screen.getByText("Store in knowledge base")).toBeInTheDocument();
  });

  it("shows ✓ for completed steps", async () => {
    mockFetchStatus([makeStatus({
      state: "processing",
      current_step: "chunk",
      completed_steps: ["read", "ground"],
    })]);
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} />);
    await waitFor(() => expect(screen.getAllByText("✓")).toHaveLength(2));
  });

  it("shows ◎ for the active step", async () => {
    mockFetchStatus([makeStatus({
      state: "processing",
      current_step: "embed",
      completed_steps: ["read", "ground", "chunk"],
    })]);
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} />);
    await waitFor(() => expect(screen.getByText("◎")).toBeInTheDocument());
  });

  it("shows all ✓ and Completed badge when job completes", async () => {
    mockFetchStatus([makeStatus({
      state: "completed",
      completed_steps: ["read", "ground", "chunk", "embed", "upsert"],
    })]);
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} />);
    await waitFor(() => expect(screen.getAllByText("✓")).toHaveLength(5));
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("shows ✗ for the failing step on failed state", async () => {
    mockFetchStatus([makeStatus({
      state: "failed",
      current_step: "embed",
      completed_steps: ["read", "ground", "chunk"],
      error: "Embedding service unavailable",
    })]);
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} />);
    await waitFor(() => expect(screen.getByText("✗")).toBeInTheDocument());
    expect(screen.getByText(/embedding service unavailable/i)).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("displays the job_id in the header", async () => {
    mockFetchStatus([makeStatus({ state: "processing", current_step: "read" })]);
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} />);
    await waitFor(() => expect(screen.getByText(JOB_ID)).toBeInTheDocument());
  });

  // ------------------------------------------------------------------
  // Callbacks
  // ------------------------------------------------------------------

  it("calls onComplete when job reaches completed state", async () => {
    const onComplete = vi.fn();
    mockFetchStatus([makeStatus({ state: "completed", completed_steps: ["read", "ground", "chunk", "embed", "upsert"] })]);
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} onComplete={onComplete} />);
    await waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
  });

  it("calls onFailed with error string when job fails", async () => {
    const onFailed = vi.fn();
    mockFetchStatus([makeStatus({
      state: "failed",
      error: "Out of memory",
      completed_steps: ["read"],
    })]);
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} onFailed={onFailed} />);
    await waitFor(() => expect(onFailed).toHaveBeenCalledWith("Out of memory"));
  });

  it("passes 'Unknown error' to onFailed when error field is null", async () => {
    const onFailed = vi.fn();
    mockFetchStatus([makeStatus({ state: "failed", error: null, completed_steps: ["read"] })]);
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} onFailed={onFailed} />);
    await waitFor(() => expect(onFailed).toHaveBeenCalledWith("Unknown error"));
  });

  // ------------------------------------------------------------------
  // Polling behaviour — fake timers scoped to these tests only
  // ------------------------------------------------------------------

  it("polls again after pollIntervalMs when job is still processing", async () => {
    vi.useFakeTimers();
    mockFetchStatus([
      makeStatus({ state: "processing", current_step: "read" }),
      makeStatus({ state: "processing", current_step: "ground", completed_steps: ["read"] }),
    ]);
    render(
      <JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} pollIntervalMs={500} />,
    );

    // Flush the first poll (microtask chain; no timer involved)
    await act(async () => {});
    expect(global.fetch).toHaveBeenCalledTimes(1);

    // Advance past pollIntervalMs — fires the scheduled setTimeout and flushes its promise
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("stops polling after completed state", async () => {
    vi.useFakeTimers();
    mockFetchStatus([
      makeStatus({ state: "completed", completed_steps: ["read", "ground", "chunk", "embed", "upsert"] }),
    ]);
    render(
      <JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} pollIntervalMs={500} />,
    );

    await act(async () => {});
    const callsAfterComplete = (global.fetch as ReturnType<typeof vi.fn>).mock.calls.length;

    // Advance well past multiple poll intervals — no further fetches should occur
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterComplete);
  });

  // ------------------------------------------------------------------
  // Fetch error
  // ------------------------------------------------------------------

  it("shows fetch error message when network call fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Connection refused")));
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} />);
    await waitFor(() =>
      expect(screen.getByText(/failed to fetch status/i)).toBeInTheDocument(),
    );
  });

  it("shows HTTP error code in fetch error message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404 }),
    );
    render(<JobStatusWidget jobId={JOB_ID} statusUrl={STATUS_URL} />);
    await waitFor(() =>
      expect(screen.getByText(/http 404/i)).toBeInTheDocument(),
    );
  });
});
