# Attachments

Read this reference only when the user explicitly requests images, videos,
audio, documents, or other binary files. A text/link export does not imply that
binary media was copied.

## Scope and source order

GIFs and stickers are excluded by default. Preserve their metadata with
`status=skipped_by_policy`; this expected exclusion does not make an otherwise
complete in-scope export partial.

For other media, use this order:

1. Verified local original under a Zalo media root → copy it.
2. Validated local preview → save as `preview_only`.
3. A URL already exposed by the record (`oriUrl`, `hdUrl`, `normalUrl`, `thumbUrl`) → fetch through the authenticated Zalo renderer with `credentials: include`.

Inspect only runtime fields such as `msgType`, `localPath`, `folderPath`,
`previewThumb`, filename, dimensions, size, and reference message ID. Reject
paths that escape verified Zalo media roots. Do not scan arbitrary paths, mutate
URLs, brute-force media paths, or use an unauthenticated Node request as the
final source.

Build the media queue once before fetching. First remove GIF/sticker,
not-found, and already hash-verified items; only eligible items enter the
network queue. Deduplicate by stable media ID or verified local path first, then
use a URL fingerprint only as a fallback; keep all exact message references.

The temporary media candidate file is required: reuse the message snapshot
instead of paginating history a second time. The generic fetcher handles
images, videos, audio, and files:

```bash
OUTPUT_ROOT="$OUTPUT_ROOT" ZALO_CDP_PORT="$CDP_PORT" ZALO_GROUP_NAME="$GROUP_NAME" \
MEDIA_CANDIDATES_PATH="$TEMP_ROOT/media-candidates.jsonl" \
  node "$RUNTIME_ROOT/fetch_zalo_media.mjs"
```

Use `fetch_zalo_photo_media_for_ocr.mjs` only for the separate, explicitly
requested OCR path. Both runtimes require the same candidate snapshot and do
not rescan message history.

The candidate file must be outside `OUTPUT_ROOT`, contain one JSON object per
line with `msgId`, `sendDttm`, `url`, and `urlKey`, and be deleted after the
media phase. Its URLs are temporary authenticated data; never copy the file to
`source/raw/`, commit it, or print its contents. A missing or invalid path must stop the
run before any history read; it must never trigger a hidden full-history rescan.
The runtime accepts only the known Zalo media host families; external URLs are
rejected before any CDP cookie lookup.

Run a 20-item dry-run and record elapsed time, success/failure counts, and
retries. Start with a bounded worker pool of 4; reduce to 1 when the renderer
serializes requests or the dry-run shows throttling. Never use unbounded
`Promise.all`. Apply a 30-second per-item deadline and at most one retry for
429/5xx/network errors. Do not retry 404. Checkpoint every completed item
atomically so interruption resumes instead of downloading from zero.

## Output and validation

Write files under:

```text
source/attachments/
  images/
  videos/
  audio/
  files/
  other/
source/raw/attachments.csv
```

Use a collision-safe name based on message ID and ordinal. Choose the extension
from verified MIME/magic bytes, not an unreliable record filename. Never
overwrite an existing output. For every copied/downloaded file, verify that it
exists, is non-empty, has valid MIME/magic bytes, and matches its SHA-256.

If the same local file is referenced more than once, store one binary and keep
all message references in the manifest.

Record at least:

```text
sequence, message_id, timestamp, sender, type, original_name,
relative_output_path, size, sha256, source_kind, status, error
```

Do not print or persist raw signed URLs; a redacted host/status or URL
fingerprint is sufficient for audit. Keep
opaque runtime attachment objects temporary and normalize only the fields in the
schema above.

When policy skips a GIF or sticker, clear both `relative_output_path` and
`output_path` so a readable view cannot imply that a binary exists. The audit
must reject a skipped row that still exposes either path.

## Statuses

```text
copied              = verified local binary copied
downloaded          = authenticated renderer returned and saved a valid binary
preview_only        = only a validated preview exists
not_found           = no usable local file or URL
remote_only         = remote/metadata reference exists but binary was not retrieved
failed_404          = renderer returned 404; likely expired/deleted media URL
failed_500          = renderer returned 500; server failure, retry once if useful
network_error       = no HTTP response; conclusion remains uncertain
unreadable          = MIME, magic-byte, or hash validation failed
skipped_by_policy   = GIF/sticker intentionally excluded
```

Any missing, expired, failed, or preview-only requested non-GIF/sticker media
makes attachment scope `PARTIAL`. A renderer 404 concerns media availability;
it is not evidence that message decryption failed.

## Optional OCR

OCR is not part of a normal message/media export. Run it only when the user
explicitly asks to read text inside images. The bundled macOS Vision runner
skips GIFs, hashes each image, reuses matching results, and uses bounded workers:

```bash
OCR_WORKERS=2 OCR_RECOGNITION_LEVEL=fast \
  swift "$RUNTIME_ROOT/ocr_zalo_media.swift" <ATTACHMENTS_DIR> <OCR_JSONL>
```

Use `OCR_RECOGNITION_LEVEL=accurate` or
`OCR_LANGUAGE_CORRECTION=1` only when the fast result is insufficient. The
default keeps OCR out of the critical extraction path and avoids spending time
on images already present in the previous OCR JSONL.
