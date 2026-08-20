# Verification and closeout

Read this reference before reporting an export as complete or partial.

## Independent checks

Do not trust the classifier's own counters. Recompute from the raw occurrence
ledger and normalized source messages. If subagents are available, use one
independent data verifier for every link export; use a second reviewer when
classification or workflow risk is material. Reviewers must not edit the export.
If no subagent is available, run the bundled verifier and say so in the report.

Verify all applicable invariants:

- Exact user-facing URL key is `trim(url)` only; query, fragment, scheme, path, encoding, and affiliate parameters are preserved. Signed internal media queries are the deliberate redaction exception.
- `links.csv` and every category view have one row per canonical URL, with no duplicate canonical URLs.
- User-facing and internal-media URL partitions match the raw ledger exactly.
- The sum of `occurrence_count` for each partition equals its raw occurrence rows, and both partitions reconcile to the total ledger.
- Each canonical URL's `occurrence_count` reconciles to its own raw URL group; equal grand totals are not enough.
- Every canonical row retains all related message IDs, pin IDs, timestamps, sources, and context evidence.
- Internal media URLs do not leak into user-facing links.
- Pin status, completeness, enumerated count, and end condition are recorded independently.
- When available, `source/link-archive-audit.json` records the Zalo Link-tab count, enumerated rows, status, and end condition; a missing or unreconciled archive audit keeps the export `PARTIAL`.
- Message IDs are unique or duplicate/update events are explained; counts match the selected snapshot.
- CSV files round-trip with Unicode, commas, quotes, and embedded newlines intact.
- Output paths stay inside the export; copied/downloaded binaries are non-empty and hash-match.
- `sourceWriteIssued: false` and source DB metadata are recorded.
- `source/phase-ledger.json` exists, every phase is closed, and each phase has duration, item count, bytes, retries, and status.
- `source/run-plan.json` exists, matches the requested scope, and does not enable an unrequested phase.
- `source/item-checkpoints.jsonl` exists; each page/media item has a stable input hash, and completed items are not rerun.
- For a later continuation, `source/incremental-state.json` matches the merged
  message table, has no duplicate message IDs, and its watermark is the newest
  exported `(timestamp, message_id)` tuple.
- When media is in scope, the source manifest records `candidateSource=snapshot`
  (or an explicit blocked reason) and the media phase does not rescan message
  history; the temporary candidate file is absent from the final export.
- When links/pins are in scope, `raw/messages.csv` exists, required
  `raw/pins.csv` exists, and the link report/manifest counters include both
  canonical and occurrence partitions.
- `python3 scripts/run_plan.py validate <OUTPUT_ROOT>`, `python3 scripts/item_checkpoint.py validate <OUTPUT_ROOT>`, and `python3 scripts/phase_ledger.py validate <OUTPUT_ROOT>` pass; out-of-scope pins/media are explicitly `SKIPPED`.
- `readable/` contains the index, chronological message view, link views, media view, and review view.
- Human views reconcile to raw counts; they may reformat text but must not invent or drop in-scope records.

If an invariant fails, fix the source transformation. Never edit only a report
JSON to make counts agree.

## Bundled checks

Run from the skill directory:

```bash
python3 -B scripts/test_phase_ledger.py
python3 -B scripts/test_run_state.py
python3 -B scripts/test_attachment_policy.py
python3 -B scripts/test_incremental_state.py
python3 -B scripts/test_link_rules.py
python3 -B scripts/test_human_views.py
python3 -B scripts/test_extract_links.py
node runtime/test_runtime_optimizations.mjs
node runtime/test_full_snapshot_contracts.mjs
node runtime/test_pin_contracts.mjs
node runtime/test_media_contracts.mjs
node runtime/test_zalo_cdp_contracts.mjs
swiftc -typecheck runtime/ocr_zalo_media.swift
node --check runtime/zalo_cdp.mjs
node --check runtime/fetch_zalo_message_snapshot.mjs
node --check runtime/fetch_zalo_pins.mjs
node --check runtime/fetch_zalo_media.mjs
python3 -m py_compile scripts/*.py
python3 -B scripts/extract_links.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/apply_category_rules.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/write_link_review.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/enforce_attachment_policy.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/render_human_views.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/audit_links.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/incremental_state.py validate <OUTPUT_ROOT>/<slug>-export-<timestamp>  # only for continuation runs
```

Run the attachment policy command only when media is in scope. `audit_links.py`
checks the link ledger plus canonical URL, source-write guard, and basic saved
attachment path/size safety; it is not a substitute for the runtime verifier's
message cursor, pin-panel, MIME/magic-byte, or SHA-256 acquisition checks.
It also reports missing/incomplete phase-ledger data and rejects signed internal
media query strings.

The audit exit codes are:

```text
0 = PASS      no failures and no warnings
2 = PARTIAL   no invariant failure, but pin/review/media warnings remain
1 = FAIL      one or more invariants failed
```

`PARTIAL` is expected when the exact conversation's pins were not enumerated,
pin completeness is unknown, unresolved review rows remain, or requested
non-GIF/sticker media is missing. A deterministic rule does not bypass review
until it is independently resolved in the resolution ledger.

When diagnosing a slow run, report phase timings from the ledger rather than a
single wall-clock number. The runtime snapshot, pin audit, media queue, and
post-processing must be distinguishable; the run plan, checkpoint counts, and
CDP/AI call counts should identify whether the delay is runtime, retry, review,
or rendering. A missing ledger, plan, or checkpoint file is itself a workflow
defect.

## Idempotence and stress checks

When changing link rules, review logic, or output transforms, run the adversarial
rule and human-view tests and rerun the pipeline on a copy. The second run
should not add rows, reopen resolved URLs, or change output hashes. For a large export, use a
synthetic fixture to verify dedupe, partition counts, and duplicate detection;
do not use private chat content as a test fixture.

For resume testing, interrupt after a page or media item, run the same plan
again, and confirm that completed item keys remain unchanged while only
resumable keys are processed. Do not benchmark by adding parallel CDP calls;
parallelize only independent local post-processing or media downloads after a
measured canary.

## Report format

```text
Group / conversation ID:
Source and encryption state:
Counted / exported:
Text / attachment scope:
Links: raw / exact-unique / user-facing / media
Review: unresolved / resolved
Pin audit: status / completeness / enumerated count
Link archive: observed / enumerated / reconciled count
Validation: PASS | PARTIAL | FAIL + warnings/failures
Source changed: no | unknown
Cleanup: temporary tools removed; debug port closed
```
