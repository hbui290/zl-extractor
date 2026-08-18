---
name: zl-extractor
description: Use when a user asks to find, read, recover, inspect, or export Zalo PC chat history, message/pinned links, or requested chat attachments into a portable, organized folder.
---

# ZL Extractor

Use Zalo's logged-in runtime as the read/decryption boundary. Map the requested conversation inside Zalo, paginate records without skipping, write an organized export, verify it, and leave the source data unchanged.

## Safety and portability

- Process only the user's local account or an explicitly authorized scope.
- Never brute-force keys, crack encryption, upload chat data, or use send/delete/import APIs.
- Treat a live `Core/Message` partition as app-managed local data, not an official export.
- Resolve every path at runtime; never reuse a username, account ID, group ID, app path, port, or output path from another machine.
- Keep raw message bodies, signed URLs, tokens, and attachment contents out of terminal output.

Use these runtime variables:

```text
USER_HOME       = os.homedir() / Path.home()
ZALO_DATA_ROOT  = verified ZaloData directory
DB_ROOT         = ZALO_DATA_ROOT/Database/_production
ACCOUNT_ID      = discovered account directory
ZALO_APP_PATH   = discovered Zalo.app bundle
CDP_PORT        = temporary free loopback port
OUTPUT_ROOT     = absolute user/workspace output directory
TEMP_ROOT       = fresh temporary directory
```

## Workflow

### 1. Resolve and verify the conversation

1. Verify `ZALO_DATA_ROOT`, `DB_ROOT`, and the active account at runtime.
2. Use the Zalo renderer's group list (`Gm1y` on tested builds), not a filename, to map the exact display name to `userId`, `globalId`, type, and member count.
3. Require an independent check such as the open conversation, recent sender/time, preview text, member count, or conversation-key membership. Stop if the name is ambiguous.
4. Treat a DB error such as `file is not a database` as encrypted/app-managed state. Do not infer that messages are missing.

### 1a. Audit pinned content and links

When links are requested, inspect the verified conversation's pinned-message/pinned-content panel through the logged-in Zalo renderer in addition to `loadMessagesForBackup`. Pinned content may not be present in the normal message stream.

- Bind the pin lookup to the exact verified conversation ID; do not use Zalo's global pinned-chat list as a substitute.
- Discover the current build's read-only pin state/API/UI data at runtime. Pin APIs and field names are version-dependent; do not guess an endpoint or call unpin/delete actions.
- Extract URLs from both message text and pinned content. Write link rows with `source=message` or `source=pin`, preserve the pin/message reference when available, and deduplicate only exact repeated `(conversation, source record, URL)` occurrences.
- If the pin panel cannot be enumerated, set `pinAuditStatus=unknown`/`blocked` in the manifest and do not claim that all links were exported. A text-only link check is not sufficient.

### 2. Read through Zalo

Use a temporary CDP connection only when needed. Select the page titled `Zalo` from `/json/list`. The tested build exposes read `DataAccess` through `AY7h`; module IDs may change, so inspect the installed app read-only after updates and locate the service containing `loadMessagesForBackup`/`countMessages`.

Paginate by the app cursor, not SQL `OFFSET`:

```text
cursor = "9999999999999"
repeat:
  batch = loadMessagesForBackup(conversation_id, cursor, 9000)
  append batch
  stop when batch.length < 9000
  cursor = msgId of the last record
```

Guard against repeated cursors and cap pages. Normalize only required fields, prefer `msgText` then textual `content`, and label media/system rows instead of dumping opaque objects. Sort final messages oldest-to-newest by `sendDttm`, then `msgId`. Extract URLs from normalized text and relevant attachment fields, but treat that set as incomplete until the pinned-content audit above has run.

### 3. Export into a deterministic folder

Create this layout whenever the user asks for a folder export:

```text
<OUTPUT_ROOT>/<slug>-export-<timestamp>/
  01-messages/
    messages.txt
    messages.csv
    links.csv
  02-attachments/
    images/
    videos/
    audio/
    files/
    other/
  03-reports/
    attachments.csv
    manifest.json
```

Use UTF-8 and real CSV quoting. Sort message and attachment rows oldest-to-newest by `sendDttm`, `msgId`, then media ordinal. Use a zero-padded sequence in both the CSV and filenames, for example:

```text
000042-<msg_id>-01.jpg
```

Keep relative CSV paths synchronized with the final file locations. If a file is moved, rewrite the CSV/manifest paths and rerun existence/hash checks. Failed or metadata-only records stay in `03-reports/attachments.csv` with an empty output path; never silently omit them.

Persist requested message/pin links in `01-messages/links.csv`. Signed CDN/media URLs belong in the attachment audit unless the user explicitly asks for those raw URLs. The CSV should include at least `sequence`, `message_id` or `pin_id`, `timestamp`, `source`, and `url`.

### 4. Optional attachment retrieval

Only retrieve binary attachments when the user explicitly requests them. Inspect runtime fields such as `msgType`, `localPath`, `folderPath`, `previewThumb`, filename, dimensions, and size. Accept local paths only when they remain under verified Zalo media roots.

Attachment scope excludes GIFs and stickers by default: do not copy or fetch them. Preserve their metadata in `attachments.csv` as `status=skipped_by_policy`; this expected exclusion does not make an otherwise complete in-scope export `PARTIAL`. If the user explicitly overrides this policy, treat them as requested media and verify them normally.

Use this source order:

1. Verified local original → copy to the type folder.
2. Validated local preview → save as `preview_only`.
3. URL fields already present in the record (`oriUrl`, `hdUrl`, `normalUrl`, `thumbUrl`) → fetch through the logged-in Zalo renderer with `credentials: include`.

Do not mutate URLs, brute-force paths, contact unrelated hosts, or use an unauthenticated Node fetch as the final source. A direct Node request can be a diagnostic only; a renderer `200` with valid image MIME/magic bytes is the authoritative download. Choose the extension from verified bytes/MIME, not a bad record filename.

Record these fields in `03-reports/attachments.csv`:

```text
sequence, message_id, timestamp, sender, type, original_name,
relative_output_path, size, sha256, source_kind, status, error
```

Use explicit statuses:

```text
copied       = verified local binary copied
downloaded   = renderer/session returned and saved a valid binary
preview_only = only a validated preview exists
not_found    = no usable local file or URL
remote_only  = metadata/remote reference exists but binary was not retrieved
failed_404   = renderer received HTTP 404; likely expired/deleted media URL
failed_500   = renderer received HTTP 500; server error, retry once if useful
network_error= no HTTP response; keep the conclusion uncertain
unreadable   = file/response fails MIME, magic-byte, or hash validation
skipped_by_policy = GIF or sticker intentionally excluded from binary retrieval
```

Do not print or persist raw signed URLs unless the user explicitly asks for them; use a redacted host/status or fingerprint for audit.

### 5. Validate and report

Before claiming completion, verify:

- exact conversation mapping and independent content check;
- counted records equal exported records for the snapshot;
- when links are in scope, message-text URLs are all represented in `links.csv`, pin enumeration completed, and pin/message source counts are recorded;
- CSV parses with Unicode, quotes, commas, and newlines;
- message IDs are unique or duplicates are explained;
- first/middle/last samples and timestamp range are plausible;
- expected layout directories exist;
- every non-empty attachment path stays inside the export folder;
- every `copied`/`downloaded` file exists, is non-empty, has valid MIME/magic bytes, and matches its SHA-256;
- attachment status counts sum to requested media rows, including intentional `skipped_by_policy` rows;
- `sourceWriteIssued: false` and source DB metadata are recorded.

Use `COMPLETE` only when the requested scope is fully verified. If links were requested, an unknown/blocked pin audit makes the result `PARTIAL` even when message-text links are complete. Any missing, expired, failed, or preview-only in-scope attachment makes the result `PARTIAL`; GIF/sticker rows marked `skipped_by_policy` are expected. Preserve text and metadata. A renderer 404 means the media URL is unavailable, not that message decryption failed. A renderer 500 or network error is not proof of permanent deletion.

### 6. Cleanup

Remove temporary scripts, extracted app bundles, cloned repositories, and package directories created for the run. Close the temporary CDP session, relaunch Zalo normally, and verify the debug port is closed. Never delete the original Zalo data unless separately requested with a recoverable plan.

Completion report:

```text
Group / conversation ID:
Source and encryption state:
Counted / exported:
Text / attachment scope:
Link scope / pin audit:
Output folder:
Validation: COMPLETE | PARTIAL | BLOCKED + reason
Source changed: no | unknown
Cleanup: debug port closed; temporary files removed
```
