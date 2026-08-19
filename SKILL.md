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
ZALO_DATA_ROOT  = verified ZaloData directory for the active user
DB_ROOT         = ZALO_DATA_ROOT/Database/_production
ACCOUNT_ID      = discovered active account directory
ZALO_APP_PATH   = discovered Zalo.app bundle containing app.asar
CDP_PORT        = free loopback port selected for this run
OUTPUT_ROOT     = absolute output directory
TEMP_ROOT       = fresh temporary directory
```

On macOS, verify `USER_HOME/Library/Application Support/ZaloData` and its
`Database/_production` directory first. On other systems, use the OS path API;
do not apply the macOS path literally. Search for an official export separately
under the verified media/account paths (`.zdb` or `backup_zalo_*.zl.zip`).

## Speed and resumability guardrails

The post-process scripts are fast; the expensive phases are authenticated
runtime reads and media retrieval. Keep one runtime session and one normalized
message snapshot per run. Do not write a new inline extractor for each group.
If the runtime adapter/recipe is unavailable, stop with `BLOCKED` and report the
missing adapter instead of starting an unbounded ad-hoc scrape.

Record a small phase ledger in `source/` with `started_at`, `finished_at`,
duration, item count, bytes, retries, and status for `resolve`, `messages`,
`pins`, `media`, and `post_process`. Use these defaults unless the current
renderer proves a safer limit:

```text
MESSAGE_BATCH_SIZE = 9000
MAX_MESSAGE_PAGES  = 100
MEDIA_CONCURRENCY  = 4   # use 1 when the renderer serializes requests
MEDIA_TIMEOUT      = 30s per item
MEDIA_ATTEMPTS     = 2   # initial attempt + one retry for 429/5xx/network only
```

Checkpoint after each message page and each verified media item. Resume from
the checkpoint and SHA-256-verified artifacts; do not re-download them. Build a
unique media work queue before fetching. Associate a binary only by an exact
message/media reference or verified local path—never by nearest timestamp or
sender heuristic. A failed association is `PARTIAL`/review, not a guessed link.

Never persist an opaque runtime snapshot or signed CDN query in the final raw
layer. Keep such data temporary, or store only normalized fields, host/status,
and a fingerprint. This preserves auditability without turning the export into
a reusable credential cache.

## Workflow

### 1. Resolve the conversation

1. Discover the active account under `DB_ROOT` and correlate it with the logged-in Zalo renderer.
2. Use Zalo's group/conversation list (the tested build exposes `Gm1y`) to map the exact display name to its ID and metadata. Do not identify a group from a DB filename.
3. Require an independent check: opened conversation, preview text, recent sender/time, member count, or conversation-key membership. Stop if the name is ambiguous.
4. A `file is not a database` error means encrypted/app-managed state may be present; it does not prove that messages are missing.

The usual group partition is `DB_ROOT/ACCOUNT_ID/Core/Message/g<GROUP_ID>.db`,
but mapping must come from Zalo first. Official exports and live partitions are
different sources.

### 2. Read through the logged-in runtime

Use a temporary loopback CDP connection only when needed. Select the page titled
`Zalo` from `/json/list`. Use the app's read-only `DataAccess` service; module
IDs such as `AY7h` are version-dependent. If the tested module is absent, inspect
the installed app bundle read-only for methods such as
`loadMessagesForBackup`, `countMessages`, and `getAllConvKeys`.

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

### 3. Process links and pinned content

When links are in scope, read [references/links-and-pins.md](references/links-and-pins.md)
before extraction. It defines the exact pin audit, URL dedupe boundary,
context merge, classification rules, review queue, and link output schema.

Run the bundled checks in this order after the runtime snapshot exists:

```bash
python3 -B scripts/test_link_rules.py
python3 -B scripts/test_human_views.py
python3 -B scripts/apply_category_rules.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/write_link_review.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/enforce_attachment_policy.py <OUTPUT_ROOT>/<slug>-export-<timestamp>  # only when media is in scope
python3 -B scripts/render_human_views.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/audit_links.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
```

`write_link_review.py` writes review files. `audit_links.py` is read-only and
returns `0=PASS`, `2=PARTIAL`, `1=FAIL`.

### 4. Retrieve attachments only when requested

Read [references/attachments.md](references/attachments.md) before copying or
downloading binaries. GIFs and stickers are excluded by default and recorded as
`skipped_by_policy`; do not silently omit other requested media.

### 5. Write the export

Read [references/readable-output.md](references/readable-output.md) before
writing a folder intended for people. Write outside the source DB, under a
resolved absolute path, with the readable layer first:

```text
<OUTPUT_ROOT>/<slug>-export-<timestamp>/
  readable/          Markdown reading views + curated CSV tables
  attachments/       only requested and verified binaries
  raw/               exact CSV/JSON inputs for audit/reprocessing
  source/            manifest, classification report, provenance
```

Generate the human views after the normalized message/link/media files exist:

```bash
python3 scripts/render_human_views.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
```

`readable/messages.md` is chronological and grouped by local date. `links.md`
and `links-by-category/` show context, category, confidence, occurrences, and
clickable labels. `readable/links.csv` and the category CSVs are intentionally
narrow, five-column, one-row-per-canonical-URL reading tables: category,
context, URL, and occurrence count. `media.csv` has five columns and
`review.csv` has six; both use the same compact-reader principle. Keep confidence, IDs,
classification evidence, hashes, and other provenance in `raw/` or the Markdown
review view; never make a reader open raw CSV to understand the conversation. Do
not create XLSX unless formulas, pivots, or a styled workbook are explicitly
requested. The renderer is non-destructive and can mirror a legacy `01-messages/` +
`03-reports/` export into the new layers.

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

## Completion report

```text
Group / conversation ID:
Source and encryption state:
Counted / exported:
Text / attachment scope:
Link scope / pin audit:
Phase timings / retries:
Output folder:
Validation: COMPLETE | PARTIAL | BLOCKED + reason
Source changed: no | unknown
Cleanup: debug port closed; temporary files removed
```
