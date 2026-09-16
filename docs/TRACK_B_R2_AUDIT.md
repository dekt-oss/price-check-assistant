# Track B R2 read-only audit

Run the audit against already collected `g2b-track-b-page-v1` raw objects:

```powershell
python -m purchase_price.scripts.audit_g2b_track_b_r2 --limit 1500
```

The command reads R2 with `ListObjectsV2` and `GetObject` only. It does not call
data.go.kr, write R2 objects, or write a database. `--limit` caps the number of
Track B JSON objects processed in this invocation; listing may examine additional
non-JSON keys. The reader uses prefix-filtered, lexical key order and verifies
object-key, metadata, gzip, and SHA-256 integrity before normalization.

The JSON report contains `objects_scanned`, `pages_parsed`, `invalid_pages`,
`rows_seen`, deduplicated `normalized_records`, `price_candidates`, replay counts,
issue counts, and price, identity, amount-check, and detail-code breakdowns.
Counts cover this invocation only. A successful report's `resume_cursor` is the
last fully processed R2 key; repeat with `--cursor '<resume_cursor>'` while
`has_more` is true. For a global duplicate/conflict audit, run from the beginning
with a sufficiently large limit in one invocation. Separate resumed reports are
partial slices and cannot by themselves establish global uniqueness.
R2 listing is not a snapshot: raw objects created during a run can sort before
an already issued cursor. After the parallel backfill finishes, run a fresh
audit from the beginning for complete coverage.

A corrupt R2 object stops the command with a nonzero exit and a `FAILED` JSON
report containing the last completed `resume_cursor`. Restarting there retries
the failing object. A malformed but integrity-valid Track B page is counted as
`invalid_pages` and does not produce normalized rows. Divergent payloads for one
stable identity fail closed; restart the batch from its original cursor after
investigating the raw evidence.

Normalized history retains `(cntrctDlvrReqNo, cntrctDlvrReqChgOrd, prdctSno)`.
`project_latest_track_b_records()` derives the current view by the highest numeric
change order for each `(cntrctDlvrReqNo, prdctSno)`; it does not mutate history.
Only an explicit positive `prdctUprc` can yield a price candidate. `prdctAmt /
prdctQty` is validation-only. The `TrackBNormalizedRepository` protocol is the
future DB1 persistence boundary; this change adds no tables or migrations.
