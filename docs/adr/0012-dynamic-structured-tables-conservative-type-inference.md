# Dynamic PostgreSQL tables with conservative type inference

**Status:** Accepted

## Decision

`core/structured.py` provides DDL helpers for dynamic per-domain tables:

- `safe_col_name(s)` — lowercase, non-alphanumeric → `_`, trimmed to 40 chars. Never returns empty (`"col"` fallback).
- `infer_pg_type(values)` — tightest-fit cascade: `int → float → ISO date/datetime → TEXT`. Returns one of the allowed types only.
- `infer_column_types(headers, rows)` — applies `infer_pg_type` across the first 100 sample rows per column.
- `create_dynamic_table(engine, table_name, headers, col_types, grant_to=None)` — `DROP IF EXISTS + CREATE` with a `_row_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text`. Optional `GRANT SELECT` to a role.
- `bulk_insert`, `fetch_sample_rows`, `drop_table` — the rest of the CRUD surface.
- `ALLOWED_PG_TYPES = {TEXT, BIGINT, NUMERIC, DATE, TIMESTAMPTZ, BOOLEAN}` — the closed set the inferer can return.

Helpers depend only on SQLAlchemy. Table naming is the caller's concern (the helper does not escape `table_name` against injection because the contract is "the caller produces a safe name from a safe naming scheme").

## Rationale

Spreadsheet ingestion into a SQL backend is a recurring pattern (receipts, expenses, sales data, inventory). Doing it well requires three things every app re-invents otherwise:

1. **Safe column names.** Headers come in as "Total amount (USD)" — must become valid SQL identifiers without quoting workarounds at query time.
2. **Type inference.** Without it, every column is `TEXT` and date/numeric predicates fail. Without conservative rules, `"1.0"` becomes `NUMERIC` when the user meant a category code.
3. **Allowed-type closure.** Returning arbitrary PostgreSQL types from an inference helper invites surprises (`JSONB`, custom enums) that downstream queries can't predict.

Conservative cascade order — `int` first, then `float`, then date — matches user expectations: a column of `"1", "2", "3"` is `BIGINT`, a column with one `"1.5"` becomes `NUMERIC`, and only date-shaped strings become `DATE`. Anything ambiguous stays `TEXT`. The 100-row sample bounds inference cost.

`grant_to` is the integration point for SQL hardening (see consumer guidance G-0003). The helper does not assume a role exists; the GRANT runs only if the caller passes a non-None name.

## Alternatives considered

**Pandas-based inference.** `pandas.api.types.infer_dtype` is more nuanced and considerably heavier. The closed type set here is intentional: an assistant uploading a CSV does not benefit from 14 dtype variants.

**Defer typing to a separate annotation step.** All columns start `TEXT`; users edit types in a UI. Works but loses date arithmetic and numeric aggregation until the user remembers to set types. The conservative inferer gets it right on the common case and lets the UI override.

**SQL injection guard inside `create_dynamic_table`.** Re-validating `table_name` inside the function duplicates the caller's invariant. The caller already has a naming convention (`sd_{domain_id_8}_{safe_label}`) that produces safe names. Inline guarding makes the function look safer than it is — callers must still control naming end-to-end.

## Consequences

- Apps that name tables outside the documented convention can produce SQL-injectable names. The function trusts the caller; the README documents the contract.
- The `_row_id` column is always present and excluded from `fetch_sample_rows()` and any UI that lists columns. Callers should preserve that exclusion.
- `bulk_insert` row-by-row is slow for very large CSVs. Acceptable at personal-assistant scale; if needed, an `executemany` or `COPY` path can be added without breaking callers.
- Empty strings are stored as `NULL` to make `IS NULL` filters work as users expect.
