# Production R2 serving-index bootstrap recovery — 2026-09-16

## Incident

After PR #154 merged to `main`, the first Production `Track B R2 Serving Index` run failed before reading the raw corpus:

```text
RuntimeError: Track B pipeline state is missing; run collection bootstrap first
```

The R2 raw Track B corpus predates the new daily-pipeline operational state object, so a missing state object does not imply an empty corpus.

## Recovery contract

The serving-index bootstrap may reconstruct the pipeline state only when the existing R2 corpus satisfies the same historical proof already used by the daily collector:

- at least `BOOTSTRAP_MIN_R2_OBJECTS` Track B raw page objects;
- the known validated batch-004 content-addressed object `BOOTSTRAP_LAST_OBJECT_KEY` is present.

If either condition is missing, bootstrap fails closed and does not write a guessed state.

When the proof passes:

1. synthesize the validated legacy `TrackBPipelineState.bootstrap()` cursor **in memory only**;
2. scan the existing Track B raw corpus into the SQLite serving index;
3. publish the content-addressed SQLite artifact and serving pointer;
4. only after successful pointer publication, persist `track-b/daily-pipeline` and serving-index sync evidence with `state_recovered=true`.

Deferring the state write is intentional. If the full scan or artifact/pointer publication fails, the retry still sees the state as missing and records the recovery path again instead of incorrectly reporting `state_recovered=false`.

Existing pipeline state always wins and does not trigger a legacy corpus rescan just for recovery.

## Production read-only proof

PR #155 added a read-only readiness gate against the real R2 bucket. It does not write state or index objects.

Observed on 2026-09-16:

- `state_present=False`
- `raw_object_count=4107`
- `legacy_bootstrap_proof=True`

## Verification required after merge

The hotfix is not complete until a real Production run confirms:

- `Track B R2 Serving Index` = success;
- mode = `full-bootstrap` on the first successful run;
- `state_recovered = true` for the legacy-state recovery path;
- `objects_scanned`, `row_count`, compressed/uncompressed index sizes are non-zero and plausible;
- the workflow's `FLOW-C` serving smoke can download the pointer-selected SQLite artifact;
- the smoke output records strict-quote/model-probe candidate/reference counts instead of `unavailable` or `not_ingested`.
