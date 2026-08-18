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

## Output and validation

Write files under:

```text
02-attachments/
  images/
  videos/
  audio/
  files/
  other/
03-reports/attachments.csv
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

Do not print or persist raw signed URLs unless the user explicitly requests
them; a redacted host/status or URL fingerprint is sufficient for audit.

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
