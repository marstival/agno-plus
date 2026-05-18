import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, afterEach } from "vitest";
import { UploadWidget } from "./index";

const INGEST_URL = "http://api/ingest";

/** Returns a fetch mock that holds until you call resolve(). */
function deferredFetch(response: object) {
  let resolve!: (value: unknown) => void;
  const promise = new Promise((r) => { resolve = r; });

  vi.stubGlobal(
    "fetch",
    vi.fn().mockReturnValue(promise.then(() => ({
      ok: true,
      json: () => Promise.resolve(response),
    }))),
  );
  return () => resolve(undefined); // caller invokes this to unblock the fetch
}

function immediateFetch(response: object, ok = true, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status,
      json: () => Promise.resolve(response),
      text: () => Promise.resolve(JSON.stringify(response)),
    }),
  );
}

describe("UploadWidget", () => {
  afterEach(() => vi.unstubAllGlobals());

  // ------------------------------------------------------------------
  // Idle state
  // ------------------------------------------------------------------

  it("renders drop zone with upload prompt", () => {
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);
    expect(screen.getByText(/drag & drop or click to upload/i)).toBeInTheDocument();
  });

  it("shows accepted file type hints", () => {
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);
    expect(screen.getByText(/spreadsheets, audio, images/i)).toBeInTheDocument();
  });

  it("renders file input with correct accept attribute", () => {
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} accept={[".csv", ".xlsx"]} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.accept).toBe(".csv,.xlsx");
  });

  it("has accessible role=button on drop zone", () => {
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);
    expect(screen.getByRole("button", { name: /upload file/i })).toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Uploading state (fetch held open with deferred promise)
  // ------------------------------------------------------------------

  it("shows uploading state while fetch is in progress", async () => {
    const unblock = deferredFetch({ job_id: "j1" });
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);

    const input = document.querySelector("input[type='file']") as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "expenses.csv", { type: "text/csv" })] },
    });

    // Fetch is still pending — uploading state should be visible
    await waitFor(() => expect(screen.getByText(/uploading/i)).toBeInTheDocument());
    unblock();
  });

  it("shows filename during upload", async () => {
    const unblock = deferredFetch({ job_id: "j1" });
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);

    fireEvent.change(
      document.querySelector("input[type='file']") as HTMLInputElement,
      { target: { files: [new File(["x"], "report.xlsx")] } },
    );

    await waitFor(() => expect(screen.getByText("report.xlsx")).toBeInTheDocument());
    unblock();
  });

  it("shows file type label during upload", async () => {
    const unblock = deferredFetch({ job_id: "j1" });
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);

    fireEvent.change(
      document.querySelector("input[type='file']") as HTMLInputElement,
      { target: { files: [new File(["x"], "data.xlsx")] } },
    );

    await waitFor(() => expect(screen.getByText(/excel/i)).toBeInTheDocument());
    unblock();
  });

  // ------------------------------------------------------------------
  // Done state
  // ------------------------------------------------------------------

  it("calls onSuccess with job_id after successful upload", async () => {
    immediateFetch({ job_id: "job_abc123" });
    const onSuccess = vi.fn();
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={onSuccess} />);

    await userEvent.upload(
      document.querySelector("input[type='file']") as HTMLInputElement,
      new File(["data"], "expenses.csv", { type: "text/csv" }),
    );

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith("job_abc123"));
  });

  it("shows success icon and filename after upload", async () => {
    immediateFetch({ job_id: "j2" });
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);

    await userEvent.upload(
      document.querySelector("input[type='file']") as HTMLInputElement,
      new File(["x"], "notes.csv"),
    );

    await waitFor(() => expect(screen.getByText("✓")).toBeInTheDocument());
    expect(screen.getByText("notes.csv")).toBeInTheDocument();
    expect(screen.getByText(/ingested/i)).toBeInTheDocument();
  });

  it("posts to ingestUrl with multipart form data", async () => {
    immediateFetch({ job_id: "j3" });
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);

    await userEvent.upload(
      document.querySelector("input[type='file']") as HTMLInputElement,
      new File(["data"], "test.csv"),
    );

    await waitFor(() => expect(global.fetch).toHaveBeenCalledOnce());
    const [url, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(INGEST_URL);
    expect(opts.method).toBe("POST");
    expect(opts.body).toBeInstanceOf(FormData);
  });

  // ------------------------------------------------------------------
  // Reset
  // ------------------------------------------------------------------

  it("resets to idle when 'Upload another' is clicked", async () => {
    immediateFetch({ job_id: "j4" });
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);

    await userEvent.upload(
      document.querySelector("input[type='file']") as HTMLInputElement,
      new File(["x"], "data.csv"),
    );
    await waitFor(() => screen.getByText(/upload another/i));

    await userEvent.click(screen.getByText(/upload another/i));
    expect(screen.getByText(/drag & drop/i)).toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Error state
  // ------------------------------------------------------------------

  it("shows error state on server error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: () => Promise.resolve("Internal Server Error"),
      }),
    );
    const onError = vi.fn();
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} onError={onError} />);

    await userEvent.upload(
      document.querySelector("input[type='file']") as HTMLInputElement,
      new File(["x"], "bad.csv"),
    );

    await waitFor(() => expect(screen.getByText(/server error 500/i)).toBeInTheDocument());
    expect(onError).toHaveBeenCalled();
  });

  it("shows error state on network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network error")));
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);

    await userEvent.upload(
      document.querySelector("input[type='file']") as HTMLInputElement,
      new File(["x"], "bad.csv"),
    );

    await waitFor(() => expect(screen.getByText(/network error/i)).toBeInTheDocument());
  });

  it("drop zone remains visible after error so user can retry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("fail")));
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);

    await userEvent.upload(
      document.querySelector("input[type='file']") as HTMLInputElement,
      new File(["x"], "bad.csv"),
    );

    await waitFor(() => expect(screen.getByText(/fail/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /upload file/i })).toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Drag events
  // ------------------------------------------------------------------

  it("shows 'Drop file here' text when dragging over", () => {
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);
    fireEvent.dragOver(screen.getByRole("button", { name: /upload file/i }));
    expect(screen.getByText(/drop file here/i)).toBeInTheDocument();
  });

  it("reverts text on drag leave", () => {
    render(<UploadWidget ingestUrl={INGEST_URL} onSuccess={vi.fn()} />);
    const zone = screen.getByRole("button", { name: /upload file/i });
    fireEvent.dragOver(zone);
    fireEvent.dragLeave(zone);
    expect(screen.getByText(/drag & drop/i)).toBeInTheDocument();
  });
});
