# Track B daily backfill + PostgreSQL sync

## Purpose

The production pipeline completes the bounded one-year G2B Track B backfill and makes the collected R2 evidence queryable from the PostgreSQL serving index.

## Schedule and quota

- GitHub Actions schedule: every day at 03:10 KST (`10 18 * * *` UTC).
- G2B request budget: 900 requests per run, preserving headroom below the 1,000/day development-account limit used for the validated backfill.
- Workflow concurrency is serialized; a second scheduled/manual run never overlaps the active writer.
- The historical collection window remains fixed at 2025-09-12 through 2026-09-11 so resume indexes retain their original meaning.

## Bootstrap evidence

The durable cursor is bootstrapped only when all of these checks hold:

1. validated target-code snapshot SHA-256 is `0885d82d25beaa60eb740bca538253ce67a51234c20acd7ba05e40da9674b365`;
2. target-code count is 5,208 with the original segment ordering;
3. existing R2 Track B evidence contains at least the previously audited 3,488 objects;
4. the batch-004 last object is present;
5. the starting cursor is the independently preserved batch-004 result: code index 3,196, page 1.

The legacy GitHub artifact is used only to seed the validated snapshot into R2 operational state. After the first successful run, the R2 copy is authoritative and artifact expiry is harmless.

## Checkpoint model

`state/v1/track-b/daily-pipeline.json` stores public operational metadata only:

- collection cursor;
- backfill complete flag;
- exact pending R2 object-key manifest;
- PostgreSQL bootstrap cursor/completion;
- last collection and DB-sync summaries.

`state/v1/track-b/target-code-snapshot-20260913.json` stores the validated public target-code snapshot.

Raw evidence remains immutable under `raw/v1/`; operational state never contains hospital-private purchasing data.

## PostgreSQL loading

The first DB run applies Alembic migrations and performs a complete read of the current Track B R2 prefix. While a partial full-bootstrap cursor exists, collection pauses so newly created hash-addressed objects cannot appear lexically before that cursor.

After full bootstrap, PostgreSQL sync no longer uses a lexical R2 cursor for new data. Each collection run records the exact R2 keys touched by the batch. The DB job consumes that pending manifest and clears it only after every object succeeds. This avoids a correctness bug where new content-addressed SHA-256 keys could sort before an old `StartAfter` cursor and be skipped forever.

## Failure behavior

- Collection persists its next cursor and pending object manifest before returning a failed status.
- PostgreSQL sync runs even when the collection job fails, allowing already persisted evidence to catch up.
- Missing `DATABASE_URL` fails closed without discarding the collection checkpoint.
- A failed exact-manifest import leaves all pending keys intact for replay.
- Replays are safe because the existing serving-index ingestion is idempotent/conflict-aware.
