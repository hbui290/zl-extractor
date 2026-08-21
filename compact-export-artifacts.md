# Compact ZL Export Artifacts

## Goal

Reduce a completed export from 42 non-system files to about 18–20 files without losing readable chat, exact-link evidence, pin/Link-tab coverage, media references, resumability, or independent auditability.

## Target contract

```text
readable/
  index.md
  messages.md
  links.csv
  pins.md
  review.csv          # only when review rows exist
  media.csv           # only when requested media rows exist
raw/
  messages.csv
  pins.csv             # only when pins are in scope
  link-archive.csv     # only when Link tab is in scope
  links-occurrences.csv
  links.csv
  zalo-media-links.csv # only when rows exist
  link-review.csv      # only when review rows exist
  attachments.csv      # only when media is in scope
source/
  manifest.json
  run-plan.json
  phase-ledger.json
  item-checkpoints.jsonl
  pin-audit.json            # only when pins are in scope
  link-archive-audit.json   # only when Link tab is in scope
  incremental-state.json    # only after incremental state is initialized
  manual-link-reconciliation.{csv,json} # only for a supplied baseline
attachments/                # only when verified binaries were requested
```

## Tasks

- [x] 1. Lock the compact artifact contract in tests: assert the allowlist above, conditional outputs, no `.DS_Store`, and idempotent rerendering. → Verified: `test_compact_export.py` and `test_human_views.py` pass.
- [x] 2. Simplify `render_human_views.py`: keep `index.md`, `messages.md`, `links.csv`, `pins.md`; create `review.csv`/`media.csv` only when non-empty; stop creating `links.md`, `links-by-category/`, `review.md`, `media.md`, `source-info.json`, and the readable reconciliation copy. → Verified: renderer is idempotent on the AFF copy.
- [x] 3. Collapse link machine outputs: make `raw/links.csv` the only canonical link table and `raw/links-occurrences.csv` the only occurrence ledger; stop writing classified/category duplicates. → Verified: URL/message/pin/time/context identity, row counts, and merge fields match the pre-change baseline.
- [x] 4. Redirect consumers to canonical files: classify updates `raw/links.csv`, review reads it, and renderer reads `links-occurrences.csv`. → Verified: extract → classify → review → render passes target-contract fixtures and stress fixtures.
- [x] 5. Make audit independent of duplicate views: compute category counts directly from `raw/links.csv` and reconcile ledgers, media, pins, Link archive, and manifest. → Verified: AFF audit has zero failures; review is a warning only.
- [x] 6. Consolidate source reports: classification counts/status live in `manifest.json`; obsolete classification/recheck reports are not produced. → Verified: AFF final folder retains the canonical pin audit and Link-tab audit.
- [x] 7. Migrate the current AFF export on a copy first, compare, then move only verified obsolete derived files to Trash. → Verified: 5,243 messages, 154 occurrences, 125 user links, 3 media links, 3 pins, and 75 Link-tab cards remain unchanged.
- [x] 8. Run final regression and stress checks, then sync the installed local skill. → Verified: Python/Node/Swift checks, 4k/800 and 12k/2k stress fixtures, `git diff --check`, and repo/local-skill parity pass. The existing AFF phase ledger remains `PARTIAL` while all listed phases are `COMPLETE`/`SKIPPED`.

## Done when

- [x] Current export has at most 20 non-system files before requested attachments, with no empty optional CSVs or duplicate category views.
- [x] Audit has zero failures; its only current warning is the 24-link classification review queue.
- [x] Full reprocessing, incremental continuation, pin audit, Link-tab reconciliation, and media attachment verification still work in the bundled regression/stress checks.
- [x] The original export was kept until the compact copy passed every check; obsolete derived files were moved to Trash, not permanently deleted.

## Explicitly retained

`manifest.json`, `run-plan.json`, `phase-ledger.json`, `item-checkpoints.jsonl`, `pin-audit.json`, `link-archive-audit.json`, `messages.csv`, `links.csv`, `links-occurrences.csv`, `pins.csv`, and `link-archive.csv` are not clutter: removing them would weaken scope proof, resume support, or independent coverage verification.
