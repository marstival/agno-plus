# Three temporal-grounding modes, chosen at bootstrap not runtime

**Status:** Accepted

## Decision

`GroundingMode` is a closed enum: `PERSONAL`, `DOCUMENT`, `AUTO`.

- **`PERSONAL`** — normalize every relative time expression in text. Used when text is a first-person utterance, receipt, or financial record. Replacement format: `2026-05-15 [yesterday]` (resolved date + original token).
- **`DOCUMENT`** — preserve the original text. Used for literary or reference text where "tomorrow" inside a quoted passage must not be rewritten to a calendar date.
- **`AUTO`** — sentence-level heuristic: if the sentence containing the relative expression also contains a first-person pronoun (EN / PT / ES, including `eu`, `meu`, `nosotros`), normalize that sentence only; otherwise preserve.

The mode is chosen at application bootstrap per source, not per request. The reference configuration:

| Source type            | Mode       |
|------------------------|------------|
| Chat / Discord channel | `PERSONAL` (hardcoded in `EpisodicMemoryGrounder` / `TemporalGrounderDb`) |
| Receipt / invoice      | `PERSONAL` |
| Financial spreadsheet  | `PERSONAL` |
| Book / reference PDF   | `DOCUMENT` |
| Unknown upload         | `AUTO`     |

End users do not select a grounding mode. The pipeline reads the mode from `meta["grounding_mode"]`, which the application sets when registering the reader for a file extension.

## Rationale

Three modes cover the production distribution of inputs in personal/domain assistants. Two are not enough: pure `PERSONAL` is wrong for ingested reference documents; pure `DOCUMENT` defeats the whole point of episodic memory. Four would mean splitting `AUTO` into "auto-strict" vs "auto-loose," which the heuristic does not need.

Setting the mode at bootstrap (not as a UI control) avoids two failure modes:

1. **Inconsistent grounding within a domain.** If users pick the mode per upload, a single Sales domain accumulates a mix of grounded and ungrounded receipts.
2. **Mode drift between read and recall.** The grounded `event_at` is written at ingest time; queries assume it is present. A per-upload toggle introduces a class of records where `event_at` is silently null.

The sentence-level `AUTO` heuristic (first-person pronoun + relative expression → normalize) handles mixed documents (a memoir, a journal export) without requiring document-level classification.

## Alternatives considered

**LLM-based mode selection.** Have an LLM read the first chunk and choose a mode. Adds latency, cost, and a class of "model changed its mind" bugs. The static per-source mapping is more predictable.

**Single global mode.** All grounding either on or off per app. Forces apps to choose between losing first-person grounding or corrupting reference texts. Rejected — the cost of three modes is one enum and one branch.

**`STRICT` and `LOOSE` modes (modifier-only).** Tried implicitly in early drafts; replaced because the real axis is the source type, not the grounder's confidence.

## Consequences

- `TemporalGrounder.ground(text, mode, reference_date)` is the entire user-facing API; there are no other knobs.
- `EpisodicMemoryGrounder` and `TemporalGrounderDb` hardcode `PERSONAL` for chat channels and do not expose a mode parameter — chat-channel memory grounding is not negotiable.
- `confidence` on a `TimeGrounding` is scaled by 0.9 inside `AUTO` to mark the heuristic path. Downstream UIs can surface low-confidence groundings differently if they choose.
