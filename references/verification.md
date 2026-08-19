# Verification and closeout

Read this reference before reporting an export as complete or partial.

## Independent checks

Do not trust the classifier's own counters. Recompute from the raw occurrence
ledger and normalized source messages. If subagents are available, use one
independent data verifier for every link export; use a second reviewer when
classification or workflow risk is material. Reviewers must not edit the export.
If no subagent is available, run the bundled verifier and say so in the report.

Verify all applicable invariants:

- Exact URL key is `trim(url)` only; query, fragment, scheme, path, encoding, and affiliate parameters are preserved.
- `links.csv` and every category view have one row per canonical URL, with no duplicate canonical URLs.
- User-facing and internal-media URL partitions match the raw ledger exactly.
- The sum of `occurrence_count` for each partition equals its raw occurrence rows, and both partitions reconcile to the total ledger.
- Every canonical row retains all related message IDs, pin IDs, timestamps, sources, and context evidence.
- Internal media URLs do not leak into user-facing links.
- Pin status, completeness, enumerated count, and end condition are recorded independently.
- Message IDs are unique or duplicate/update events are explained; counts match the selected snapshot.
- CSV files round-trip with Unicode, commas, quotes, and embedded newlines intact.
- Output paths stay inside the export; copied/downloaded binaries are non-empty and hash-match.
- `sourceWriteIssued: false` and source DB metadata are recorded.
- `readable/` contains the index, chronological message view, link views, media view, and review view.
- Human views reconcile to raw counts; they may reformat text but must not invent or drop in-scope records.

If an invariant fails, fix the source transformation. Never edit only a report
JSON to make counts agree.

## Bundled checks

Run from the skill directory:

```bash
python3 -B scripts/test_link_rules.py
python3 -B scripts/test_human_views.py
python3 -B scripts/apply_category_rules.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/write_link_review.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/enforce_attachment_policy.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/render_human_views.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/audit_links.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
```

Run the attachment policy command only when media is in scope. `audit_links.py`
checks the link ledger plus canonical URL, source-write guard, and basic saved
attachment path/size safety; it is not a substitute for the runtime verifier's
message cursor, pin-panel, MIME/magic-byte, or SHA-256 acquisition checks.

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

## Idempotence and stress checks

When changing link rules, review logic, or output transforms, run the adversarial
rule and human-view tests and rerun the pipeline on a copy. The second run
should not add rows, reopen resolved URLs, or change output hashes. For a large export, use a
synthetic fixture to verify dedupe, partition counts, and duplicate detection;
do not use private chat content as a test fixture.

## Report format

```text
Group / conversation ID:
Source and encryption state:
Counted / exported:
Text / attachment scope:
Links: raw / exact-unique / user-facing / media
Review: unresolved / resolved
Pin audit: status / completeness / enumerated count
Validation: PASS | PARTIAL | FAIL + warnings/failures
Source changed: no | unknown
Cleanup: temporary tools removed; debug port closed
```
