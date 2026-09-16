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

1. create the validated legacy `TrackBPipelineState.bootstrap()` cursor;
2. persist it to `track-b/daily-pipeline`;
3. scan the existing Track B raw corpus into the SQLite serving index;
4. publish the content-addressed SQLite artifact and pointer;
5. persist serving-index sync evidence including `state_recovered=true`.

Existing pipeline state always wins and does not trigger a legacy corpus rescan just for recovery.

## Verification required after merge

The hotfix is not complete until a real Production run confirms:

- `Track B R2 Serving Index` = success;
- mode = `full-bootstrap` on the first successful run;
- `state_recovered = true` for the legacy-state recovery path;
- `objects_scanned`, `row_count`, compressed/uncompressed index sizes are non-zero and plausible;
- Streamlit can download the pointer-selected SQLite artifact and return transaction rows for a real lookup.
