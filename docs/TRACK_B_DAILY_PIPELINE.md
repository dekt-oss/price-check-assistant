# Track B daily backfill + R2 serving index

## Purpose

The production pipeline completes the bounded one-year G2B Track B backfill and keeps both durable raw evidence and the rebuildable query index in Cloudflare R2. No Supabase/PostgreSQL storage is required for the Track B corpus.

## Data scope

The current backfill is not all of G2B. It collects `ShoppingMallPrdctInfoService/getSpcifyPrdlstPrcureInfoList` for the validated 5,208 detail-product codes in top-level segments `42/41/43/44/23/27/46/39`, prioritized for hospital purchasing (medical, laboratory/measurement, IT, office, tools/industrial, safety and electrical categories).

The historical collection window remains fixed at 2025-09-12 through 2026-09-11 so the existing resume cursor remains reproducible.

## Schedule and quota

- Daily schedule: 03:10 KST (`10 18 * * *` UTC).
- G2B request budget: maximum 900 calls per run, leaving headroom below the validated 1,000/day development-account limit.
- Backfill concurrency is serialized.
- R2 raw evidence is immutable and content-addressed under `raw/v1/`.

## Bootstrap evidence

The durable cursor starts from the independently preserved batch-004 result only after all of these checks hold:

1. validated target-code snapshot SHA-256 is `0885d82d25beaa60eb740bca538253ce67a51234c20acd7ba05e40da9674b365`;
2. target-code count is 5,208 with the original segment ordering;
3. existing R2 Track B evidence contains at least the previously audited 3,488 objects;
4. the batch-004 last object is present;
5. starting cursor is code index 3,196, page 1.

The legacy Actions artifact is used only to seed the validated public snapshot into R2 operational state. After that, R2 is authoritative.

## R2 serving index

R2 is object storage rather than a SQL engine, so Streamlit must not scan thousands of compressed JSON objects for every user query. The serving layer is therefore a compact SQLite derivative stored in the same R2 bucket:

```text
G2B public API
  -> raw/v1/... immutable JSON.gz
  -> normalize
  -> local SQLite build/update in GitHub Actions
  -> derived/v1/track-b-serving/<sha>.sqlite.gz
  -> state/v1/track-b/serving-index.json pointer
  -> Streamlit downloads the current index to temporary local storage
  -> indexed model/class lookup
```

The SQLite file is disposable and rebuildable. Raw R2 evidence remains the source of truth.

The first serving-index run scans the complete current Track B raw prefix. Later runs ingest only the exact R2 object keys recorded by the preceding collection run. This avoids using a lexical cursor over SHA-256 object names, which could otherwise miss newly created keys that sort before an older cursor.

A new versioned SQLite object is uploaded before the pointer is changed. After the pointer is committed, the previous derived index is best-effort deleted to avoid daily storage growth.

## Checkpoint model

`state/v1/track-b/daily-pipeline.json` stores public operational metadata only:

- collection cursor;
- backfill complete flag;
- exact pending raw-object manifest;
- last collection summary;
- last R2 serving-index sync summary.

`state/v1/track-b/target-code-snapshot-20260913.json` stores the validated target-code snapshot.

`state/v1/track-b/serving-index.json` points to the currently published SQLite serving index and records its hash, size, row count and build time.

## Failure behavior

- Collection persists its next cursor and pending object manifest before returning a failed status.
- A serving-index failure never deletes or mutates raw evidence.
- Pending object keys are cleared only after a new index is uploaded and its pointer is committed.
- Replayed raw pages are safe because Track B stable identities are idempotent/conflict-aware.
- R2 zero-cost warning/hard-limit guards also apply to the derived serving index.
