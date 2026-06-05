# G-0004 — Grounding mode per source: set once at bootstrap, never per request

**Status:** Recommended for consumer applications

## Guidance

Decide grounding mode (`PERSONAL`, `DOCUMENT`, `AUTO`) once at application bootstrap, per file source type. Pass it as `meta["grounding_mode"]` to `IngestionPipeline.submit()`. Do not expose the choice to end users in upload UIs.

Reference table (mirror of ADR-0004, applied to a typical assistant):

| Source                                       | Mode       | Rationale                                                |
|----------------------------------------------|------------|----------------------------------------------------------|
| Chat / Discord channel                       | `PERSONAL` | Always first-person; hardcoded in `EpisodicMemoryGrounder`. |
| Receipts, invoices, expense images           | `PERSONAL` | First-person records; dates should be calendar-grounded. |
| Personal financial spreadsheets              | `PERSONAL` | Same as receipts.                                         |
| Books, reference PDFs, articles              | `DOCUMENT` | Preserve original text — don't rewrite "tomorrow" in a quote. |
| Audio recordings of meetings / journal       | `PERSONAL` | First-person; speakers say "yesterday" and mean it.       |
| Unknown bulk uploads                         | `AUTO`     | Sentence-level heuristic; safe default.                   |

Bootstrap example:

```python
pipeline = IngestionPipeline(
    readers={
        ".csv":  AgnoSpreadsheetReader(grounding_mode="personal"),
        ".xlsx": AgnoSpreadsheetReader(grounding_mode="personal"),
        ".pdf":  IntelligentPdfReader(),  # mode set per-domain at submit time
        ".jpg":  AgnoImageReader(grounding_mode="personal"),
        ".png":  AgnoImageReader(grounding_mode="personal"),
        ".mp3":  AgnoAudioReader(),
    },
    memory_store=knowledge_store,
    grounder=grounder,
)
```

The `meta` passed at `pipeline.submit(source, filename, meta={"grounding_mode": "..."})` overrides the reader-level default when the same reader is used for different source types.

## Why

A user-facing toggle ("Treat dates as personal" / "Treat dates as literal") makes the wrong action easy: pick the wrong mode once and the domain accumulates a mix of grounded and ungrounded records that no later query can reliably disambiguate.

Setting the mode at bootstrap also matches how applications actually evolve. Adding a new domain (e.g. "Receipts") implies adding a route that uses `PERSONAL`; adding a "Reference" domain implies a route that uses `DOCUMENT`. The mode is a property of the route, not of the upload.

## Apply when

- Wiring `IngestionPipeline` in any consumer.
- Adding a new source type or domain category to an existing app.

## Apply if not

- A test fixture that needs explicit control of the mode (pass it directly).

## Related ADRs

- agno-plus ADR-0004 (three modes + bootstrap-time choice).
- agno-plus ADR-0005 (chat-channel `PERSONAL` is hardcoded in the wrapper).
