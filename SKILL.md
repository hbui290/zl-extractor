---
name: zl-extractor
description: Use when a user asks to find, read, recover, inspect, or export Zalo PC chat history, message/pinned links, or requested chat attachments into a portable, organized folder.
---

# ZL Extractor

Use Zalo's logged-in runtime as the read/decryption boundary. Resolve the exact
conversation, read it without writing to Zalo, export an organized folder, and
report what was verified versus what remains partial.

## Non-negotiables

- Process only the user's local account or an explicitly authorized scope.
- Never crack encryption, extract keys, upload chat data, or call send/delete/import APIs.
- A live `Core/Message` partition is app-managed local data, not automatically an official backup.
- Discover every machine-specific path, account ID, conversation ID, and CDP port during the current run.
- Keep raw message bodies, signed URLs, tokens, and opaque attachment objects out of terminal output.
- Leave the source Zalo data unchanged. Temporary copies must include DB `-wal` and `-shm` companions.

## Runtime discovery

Use variables, never paths copied from a previous machine:

```text
USER_HOME       = os.homedir() / Path.home()
SKILL_ROOT      = directory containing this SKILL.md
RUNTIME_ROOT    = SKILL_ROOT/runtime
ZALO_DATA_ROOT  = verified ZaloData directory for the active user
DB_ROOT         = ZALO_DATA_ROOT/Database/_production
ACCOUNT_ID      = discovered active account directory
ZALO_ACCOUNT_ID = verified active Zalo user/UIN used by the read-only adapter
GROUP_NAME      = exact requested conversation display name
CONVERSATION_ID = runtime-resolved stable conversation ID
ZALO_APP_PATH   = discovered Zalo.app bundle containing app.asar
CDP_PORT        = free loopback port selected for this run
ZALO_READY_TIMEOUT_MS = bounded wait for the logged-in renderer (default 30000)
OUTPUT_ROOT     = absolute output directory
TEMP_ROOT       = fresh temporary directory
START_AT        = optional lower message boundary (ISO-8601, YYYY-MM-DD, or epoch)
END_AT          = optional inclusive upper message boundary (ISO-8601, YYYY-MM-DD, or epoch)
```

On macOS, verify `USER_HOME/Library/Application Support/ZaloData` and its
`Database/_production` directory first. On other systems, use the OS path API;
do not apply the macOS path literally. Search for an official export separately
under the verified media/account paths (`.zdb` or `backup_zalo_*.zl.zip`).

## Speed, phase ledger, and resumability guardrails

The post-process scripts are fast; the expensive phases are authenticated
runtime reads and media retrieval. Keep one runtime session and one normalized
message snapshot per run. Keep the user's scope in a machine-readable run plan;
the AI must not infer extra phases after the run starts. Do not write a new
inline extractor for each group.
Use the bundled version-sensitive adapters under `RUNTIME_ROOT`. The snapshot
and delta adapters preserve URLs found in alternate structured message fields
under the normalized `structured_links` column; the post-processor consumes
that column without duplicating URLs already present in message text. If the
required adapter is unavailable or its module contract no longer matches the
installed Zalo build, stop with `BLOCKED` and report that exact gap instead of
starting an unbounded ad-hoc scrape.

Create `source/phase-ledger.json` before the first runtime call. Every phase
must have `started_at`, `finished_at`, `duration_ms`, `items`, `bytes`,
`retries`, and `status`; write it after each phase and in the final report.
Use this fixed critical path:

```text
resolve -> preflight -> messages -> pins -> media_prepare -> media_fetch -> post_process
```

Immediately after the phase ledger, create and validate
`source/run-plan.json`. The plan is the scope boundary for the whole run:

```bash
python3 "$SKILL_ROOT/scripts/phase_ledger.py" init "$OUTPUT_ROOT"
python3 "$SKILL_ROOT/scripts/run_plan.py" init "$OUTPUT_ROOT" \
  --scope messages links pins
python3 "$SKILL_ROOT/scripts/run_plan.py" validate "$OUTPUT_ROOT"
```

Use only the requested scopes (`messages`, `links`, `pins`, `media`). `pins`
requires `links`; `messages` is always included. A phase marked `SKIPPED` in
the plan must not be called later. For a resumed run, load the existing plan;
do not regenerate it from the latest prompt.

Use the bundled helper instead of inventing a new ledger format:

```bash
python3 "$SKILL_ROOT/scripts/phase_ledger.py" record "$OUTPUT_ROOT" messages \
  --items "$MESSAGE_ITEMS" --bytes "$MESSAGE_BYTES" --retries "$RETRIES" \
  --duration-ms "$DURATION_MS" --status COMPLETE
python3 "$SKILL_ROOT/scripts/phase_ledger.py" finalize "$OUTPUT_ROOT" --status COMPLETE
python3 "$SKILL_ROOT/scripts/phase_ledger.py" validate "$OUTPUT_ROOT"
```

Record `SKIPPED` for `pins` when links/pins are outside scope, and for
`media_prepare`/`media_fetch` when the user did not request binaries. Record
`PARTIAL` or `BLOCKED` when a phase ends that way; never mark it complete by
guessing. `validate` is required before closeout.

Preflight once, before the full snapshot: use the bundled CDP readiness helper
to poll `/json/list` until the page title is exactly `Zalo` (default timeout is
30 seconds; override with bounded `ZALO_READY_TIMEOUT_MS`). A login/loading
page is not ready. Then verify the read-only adapter, active account, exact
conversation, pin adapter/end-marker, output root, and media field shape. Do
not inspect the app bundle, invent a new inline extractor, or rerun exploratory
pin calls after the full snapshot has started. If the renderer remains on the
login/loading page or any preflight check fails, stop `BLOCKED` instead of
spending time on a doomed run.

Use these defaults unless a measured 20-item media dry-run proves the renderer
requires a safer limit:

```text
MESSAGE_BATCH_SIZE = 9000
MAX_MESSAGE_PAGES  = 100
MEDIA_CONCURRENCY  = 4   # use 1 when the renderer serializes requests
MEDIA_TIMEOUT      = 30s per item
MEDIA_ATTEMPTS     = 2   # initial attempt + one retry for 429/5xx/network only
MEDIA_DRY_RUN      = 20 eligible items
MEDIA_PROGRESS     = every 25 items or 10 seconds, whichever comes later
```

Checkpoint after each message page and each media item in the append-only item
ledger. Initialize it before the first page/media request:

```bash
python3 "$SKILL_ROOT/scripts/item_checkpoint.py" init "$OUTPUT_ROOT"
```

Record `RUNNING` before work and `COMPLETE`, `PARTIAL`, `FAILED`, or `SKIPPED`
after work. Every item needs a stable `item_key` and input SHA-256. Resume only
the latest `PENDING`/`RUNNING`/`PARTIAL`/`FAILED` items; a matching
`COMPLETE` item is immutable and the helper turns a duplicate completion into
a no-op. Validate it at closeout:

```bash
python3 "$SKILL_ROOT/scripts/item_checkpoint.py" list "$OUTPUT_ROOT" --resumable
python3 "$SKILL_ROOT/scripts/item_checkpoint.py" validate "$OUTPUT_ROOT"
```

### Continue an existing export on a later day

Item checkpoints resume an interrupted run; the persistent incremental state
handles a new run against the same export folder. Initialize it once after the
first export:

```bash
python3 "$SKILL_ROOT/scripts/incremental_state.py" init "$OUTPUT_ROOT" \
  --conversation-id "$CONVERSATION_ID"
```

On the next run, read `source/incremental-state.json` and use its watermark
`(timestamp, message_id)`. Read newest runtime pages, keep only rows newer than
that tuple, and stop after a page crosses the watermark. Do not use a calendar
date alone: message IDs break ties and prevent same-second duplicates. Always
resolve and verify the exact conversation again. If the runtime cannot prove
ordered pagination, use a full snapshot instead of guessing.

The bundled delta adapter consumes the watermark, verifies the resolved
conversation ID, and writes only normalized fields to temporary files:

```bash
ZALO_CDP_PORT="$CDP_PORT" \
ZALO_GROUP_NAME="$GROUP_NAME" \
INCREMENTAL_STATE_PATH="$OUTPUT_ROOT/source/incremental-state.json" \
MESSAGES_DELTA_PATH="$TEMP_ROOT/messages-delta.csv" \
MEDIA_CANDIDATES_PATH="$TEMP_ROOT/media-candidates.jsonl" \
node "$RUNTIME_ROOT/fetch_zalo_message_delta.mjs"
```

The delta CSV schema is allowlisted. Opaque runtime fields, unknown fields, and
signed internal media queries are rejected by the merge step. Both temporary
files must stay outside `OUTPUT_ROOT` and are deleted after post-processing.

Write the delta to a temporary normalized CSV, merge it by `message_id`, and
refresh the watermark:

```bash
python3 "$SKILL_ROOT/scripts/incremental_state.py" merge \
  "$OUTPUT_ROOT" "$TEMP_ROOT/messages-delta.csv"
python3 "$SKILL_ROOT/scripts/incremental_state.py" validate "$OUTPUT_ROOT"
```

The merge is idempotent: an existing ID is updated at most once and rerunning
the same delta adds no duplicate. Then rerun link classification, the current
pin audit, requested media, and the readable renderer over the merged snapshot.
Pins are always checked live because an older message can become pinned later.

Build the unique media work queue before fetching, and remove policy-skipped /
not-found items before opening a network request. Associate a binary only by an
exact message/media reference or verified local path—never by nearest timestamp
or sender heuristic. A failed association is `PARTIAL`/review, not a guessed
link. JSONL is intentionally the first storage format: it is inspectable and
can be migrated to SQLite later without changing the item schema.

Never persist an opaque runtime snapshot or signed CDN query in the final raw
layer. Keep such data temporary, or store only normalized fields, host/status,
and a fingerprint. This preserves auditability without turning the export into
a reusable credential cache.

## Workflow

### 1. Resolve the conversation

1. Create the output root, phase ledger, run plan, and item checkpoint file, then discover the active account under `DB_ROOT` and correlate it with the logged-in Zalo renderer.
2. Use Zalo's group/conversation list (the tested build exposes `Gm1y`) to map the exact display name to its ID and metadata. Do not identify a group from a DB filename.
3. Require an independent check: opened conversation, preview text, recent sender/time, member count, or conversation-key membership. Stop if the name is ambiguous.
4. A `file is not a database` error means encrypted/app-managed state may be present; it does not prove that messages are missing.

The usual group partition is `DB_ROOT/ACCOUNT_ID/Core/Message/g<GROUP_ID>.db`,
but mapping must come from Zalo first. Official exports and live partitions are
different sources.

### 2. Read through the logged-in runtime

Use a temporary loopback CDP connection only when needed. Select the page titled
`Zalo` from `/json/list`. Use the app's read-only `DataAccess` service; module
IDs such as `AY7h` are version-dependent. If the tested module is absent, stop
`BLOCKED`; do not replace it with a new inline extractor.

For a first/full snapshot, write normalized messages directly to the export's
`raw/` layer and keep authenticated media candidates outside the export:

```bash
ZALO_CDP_PORT="$CDP_PORT" \
ZALO_ACCOUNT_ID="$ZALO_ACCOUNT_ID" \
ZALO_GROUP_NAME="$GROUP_NAME" \
OUTPUT_ROOT="$OUTPUT_ROOT" \
START_AT="${START_AT:-}" END_AT="${END_AT:-}" \
MESSAGES_PATH="$OUTPUT_ROOT/raw/messages.csv" \
MEDIA_CANDIDATES_PATH="$TEMP_ROOT/media-candidates.jsonl" \
node "$RUNTIME_ROOT/fetch_zalo_message_snapshot.mjs"
```

The snapshot adapter initializes `source/manifest.json` with the verified
conversation, read-only source metadata, message counts, and
`sourceWriteIssued: false`; later link/pin stages extend that manifest instead
of silently omitting it.

`START_AT`/`END_AT` are inclusive. A date-only `START_AT` means local midnight;
a date-only `END_AT` means the end of that local day. Numeric epoch seconds and
milliseconds are accepted. The adapter refuses ambiguous group names, missing
active-account identity, repeated cursors, page-cap overflow, and unsafe output
paths; an invalid timestamp never becomes the stop condition and is excluded
when a date boundary is active.

Paginate with the app cursor, never SQL `OFFSET`:

```text
cursor = "9999999999999"
repeat:
  batch = loadMessagesForBackup(conversation_id, cursor, 9000)
  append batch
  stop when batch.length < 9000
  cursor = msgId of the last record
```

Guard against a repeated cursor and cap pages. Normalize only the fields needed
for output (`conversation_id`, message ID, timestamps, sender, type, text,
quote/reference, and attachment metadata), then sort oldest-to-newest by
`sendDttm`, `msgId`. Message-text links are incomplete until the pin audit runs.
Recognize explicit `http(s)://` URLs and conservative bare domains; keep
ambiguous domain-like prose in the review queue instead of guessing.
Use one runtime call per page, not one CDP evaluation per message. Record the
page cursor and input hash as one checkpoint item, persist the normalized page
before requesting the next page, and never fetch a completed page again.

When media is in scope, derive candidate rows while each message page is
already in memory and write them to a temporary
`TEMP_ROOT/media-candidates.jsonl` file. Each row contains `msgId`, `sendDttm`,
`url`, `urlKey`, and optional normalized media metadata; the file is staging data
and must stay outside the final output root. Pass it to the media fetcher as the required
`MEDIA_CANDIDATES_PATH`. The fetcher may attach to CDP for cookies but must not
call `loadMessagesForBackup` again. A missing or invalid candidate file is
`BLOCKED`; do not silently fall back to a second history scan. Candidate
validation allows only known Zalo media host families; external URLs are
rejected before any CDP cookie lookup.

### 3. Process links and pinned content

When links are in scope, read [references/links-and-pins.md](references/links-and-pins.md)
before extraction. It defines the exact pin audit, URL dedupe boundary,
context merge, classification rules, review queue, and link output schema.

Audit the exact conversation's pin panel with the bundled read-only adapter. It
writes a temporary normalized pin table and a small audit record; move only the
table into `raw/`:

```bash
ZALO_CDP_PORT="$CDP_PORT" \
ZALO_GROUP_NAME="$GROUP_NAME" \
OUTPUT_ROOT="$OUTPUT_ROOT" \
PINS_PATH="$TEMP_ROOT/pins.csv" \
PIN_AUDIT_PATH="$OUTPUT_ROOT/source/pin-audit.json" \
node "$RUNTIME_ROOT/fetch_zalo_pins.mjs"
mv "$TEMP_ROOT/pins.csv" "$OUTPUT_ROOT/raw/pins.csv"
```

If the app's pin service cannot resolve the exact conversation or does not
return an array from the bounded read-only call, record `BLOCKED`/`PARTIAL` and
do not claim pin completeness.

The conversation-info `Link` tab is a separate source from both the message
snapshot and the pinned-message panel. When the current runtime exposes it,
enumerate it into `source/link-archive-audit.json` with the reported UI count,
enumerated row count, and an explicit end condition. If it is unavailable,
keep the export `PARTIAL` and show that gap in `readable/index.md`; never use
the message/pin totals as a substitute for the Link-tab count.

Build the occurrence ledger and exact-URL merge before applying category rules:

```bash
python3 -B scripts/extract_links.py "$OUTPUT_ROOT"
python3 -B scripts/apply_category_rules.py "$OUTPUT_ROOT"
```

Run deterministic rules first. Send only uncertain/conflicting rows plus their
related occurrences to the review queue; do not send the whole conversation or
one AI call per URL.

Run these static smoke tests once after changing the skill or renderer:

```bash
python3 -B scripts/test_link_rules.py
python3 -B scripts/test_human_views.py
python3 -B scripts/test_incremental_state.py
python3 -B scripts/test_extract_links.py
node runtime/test_full_snapshot_contracts.mjs
node runtime/test_pin_contracts.mjs
node runtime/test_media_contracts.mjs
node runtime/test_zalo_cdp_contracts.mjs
```

For each export, run only the data-dependent pipeline after the runtime
snapshot exists:

```bash
python3 -B scripts/extract_links.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/apply_category_rules.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/write_link_review.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/enforce_attachment_policy.py <OUTPUT_ROOT>/<slug>-export-<timestamp>  # only when media is in scope
python3 -B scripts/render_human_views.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/audit_links.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
```

`write_link_review.py` writes review files. `audit_links.py` is read-only and
returns `0=PASS`, `2=PARTIAL`, `1=FAIL`. It checks exact per-URL occurrence
counts, not only partition totals, and rejects signed internal media queries.

### 4. Retrieve attachments only when requested

Read [references/attachments.md](references/attachments.md) before copying or
downloading binaries. GIFs and stickers are excluded by default and recorded as
`skipped_by_policy` with no output path; do not silently omit other requested
media.

### 5. Write the export

Read [references/readable-output.md](references/readable-output.md) before
writing a folder intended for people. Write outside the source DB, under a
resolved absolute path, with the readable layer first:

```text
<OUTPUT_ROOT>/<slug>-export-<timestamp>/
  readable/          Markdown reading views + curated CSV tables
  attachments/       only requested and verified binaries
  raw/               machine-readable audit inputs; signed media queries redacted
  source/            manifest, run plan, checkpoints, provenance, and phase timings
```

Generate the human views after the normalized message/link/media files exist:

```bash
python3 scripts/render_human_views.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
```

`readable/messages.md` is chronological and grouped by local date. `links.md`,
`pins.md`, and `links-by-category/` show stable URL headings, context, category,
confidence, occurrences, and clickable labels. `pins.md` is the separate
reader-facing pin audit; external links and internal media references are shown
separately and must not be hidden inside the general link count.
`readable/links.csv`
and the category CSVs are intentionally
narrow, five-column, one-row-per-canonical-URL reading tables: category,
context, URL, and occurrence count. `media.csv` has five columns and
`review.csv` has six; both use the same compact-reader principle. Keep confidence, IDs,
classification evidence, hashes, and other provenance in `raw/` or the Markdown
review view; never make a reader open raw CSV to understand the conversation. Do
not create XLSX unless formulas, pivots, or a styled workbook are explicitly
requested. The renderer escapes untrusted message/context Markdown, protects
formula-like readable CSV cells, preserves external URLs exactly, and redacts
internal signed Zalo media URLs. It is non-destructive and can mirror a legacy
`01-messages/` + `03-reports/` export into the new layers.

Use UTF-8 and real CSV quoting. Use collision-safe filenames and relative paths
in CSV/manifest. Never overwrite existing binaries or edit immutable source
inputs; derived ledgers may be regenerated only after the source-write guard is
checked. Rerun the renderer and audit after moving anything.

### 6. Validate and report

Read [references/verification.md](references/verification.md) before closeout.
Validation must come from the raw ledger/source messages, not only the
classifier's report. Verify conversation mapping, counts, unique message IDs,
CSV round-trip, dedupe/media partitions, readable/raw reconciliation,
path containment, hashes, and pin coverage. Keep the source-write flag false.
Require `run_plan.py validate`, `item_checkpoint.py validate`, and
`phase_ledger.py validate` to pass. If timings, retries, plan, or checkpoints
are missing, report `PARTIAL` with the specific missing state rather than
claiming the workflow was fast or complete.

Use these statuses:

```text
COMPLETE = mapping, requested records, links/pins, and requested media are verified
PARTIAL  = records are readable but pin coverage, classifications, or requested media remain unresolved
BLOCKED  = no valid source/runtime, ambiguous conversation, or inconsistent source
```

Never call a text export complete when the requested pin audit is unknown or
blocked. An expected GIF/sticker exclusion does not make an otherwise complete
in-scope export partial.

### 7. Clean up

Remove temporary scripts, extracted app bundles, cloned repositories, and
temporary package directories. Close the temporary CDP session and relaunch
Zalo normally if it was started with a debug port. Never delete the original
Zalo data without a separately approved, recoverable plan.
