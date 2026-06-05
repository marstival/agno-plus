# Layout-aware spreadsheet reader: read_only=False + BFS block detection

**Status:** Accepted

## Decision

`SpreadsheetReader` parses Excel and CSV in three stages:

1. **Grid layer** — `openpyxl.load_workbook(..., read_only=False)`. Iterate `ws.merged_cells.ranges` and propagate each master cell value to all covered coordinates, producing a sparse `SheetGrid`.
2. **Block detection** — BFS connected-component scan over filled cells, classifying each region as `TABLE`, `KV_PAIR`, or `NOTE` with a confidence score.
3. **Record extraction** — for `TABLE` blocks emit typed rows; for `KV_PAIR` blocks emit `{key, value}` records; `NOTE` blocks become free text.

The reader emits one `Document` per detected block, not one per sheet.

CSV input uses `csv.Sniffer()` for delimiter detection and falls back to latin-1 if UTF-8 fails. Supported extensions: `.xlsx`, `.xls`, `.xlsm`, `.csv`, `.tsv`.

## Rationale

Agno's native `ExcelReader` opens workbooks with `read_only=True`, which silently drops the master-cell value of merged ranges — every cell except the top-left of a merge reads as `None`. Real-world spreadsheets (receipts, financial reports, key-value forms) routinely use merged cells for headers and section labels. The dropped values destroy the ingestion quality even when the chunker is good.

Per-block emission also matches how users think about spreadsheets. A single workbook might hold (a) a metadata key-value section at the top, (b) a transaction table in the middle, and (c) a notes block at the bottom. Treating each as a separate `Document` lets the downstream chunker apply boundary-aware merging and lets the chat UI cite the specific block instead of the whole sheet.

## Alternatives considered

**Use Agno's `ExcelReader` and post-process.** Re-running the workbook in `read_only=False` after Agno opened it doubles parsing cost. The fix has to live at the open call, so it has to be a new reader.

**Treat every sheet as one block.** Simpler, but loses the layout information that BFS block detection produces. Most receipts and forms collapse into a single noisy `Document` that the chunker has no signal to split cleanly.

**External heuristic libraries (e.g. `pandas.read_excel` with sheet-level handling).** Pandas does not solve merged-cell expansion either and adds a heavy dependency for what is essentially a layout heuristic.

## Consequences

- `openpyxl` is required (not optional) in the base install.
- `read_only=False` is materially slower than `read_only=True` for very large workbooks; this is acceptable for personal/domain assistant scale (typical inputs are <100 sheets).
- `SpreadsheetReader.read()` returns `list[Document]` where `source_type` indicates the block type (`spreadsheet:table`, `spreadsheet:kv`, `spreadsheet:note`) and metadata carries sheet name and cell range.
- Structured-domain ingestion still needs raw rows. For tabular CSV/XLSX → SQL flows, the application calls a thin row-extraction helper alongside `SpreadsheetReader`; the reader's Document output handles the semantic side.
