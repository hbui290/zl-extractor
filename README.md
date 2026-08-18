# ZL Extractor

Portable Codex skill for safely extracting Zalo PC chat history into an organized folder.

## What it does

- Maps a requested Zalo conversation from the logged-in app instead of guessing DB filenames.
- Reads encrypted/app-managed local messages through Zalo's read-only runtime.
- Exports UTF-8 TXT/CSV messages and optionally retrieves requested attachments.
- Uses the authenticated Zalo renderer for session-bound media URLs.
- Sorts messages and attachments deterministically and records hashes/statuses.

## Export layout

```text
<group>-export-<timestamp>/
  01-messages/
    messages.txt
    messages.csv
  02-attachments/
    images/
    gifs/
    videos/
    audio/
    files/
    stickers/
    other/
  03-reports/
    attachments.csv
    manifest.json
```

## Use in Codex

Copy this folder into `~/.codex/skills/zl-extractor`, then invoke it with:

```text
Use $zl-extractor to export the Zalo group "<group name>".
```

The workflow resolves machine-specific paths at runtime. It does not include or upload chat content, media, account IDs, or session tokens.

## Attachment status

`copied`, `downloaded`, `preview_only`, `not_found`, `remote_only`, `failed_404`, `failed_500`, `network_error`, and `unreadable` are recorded per media row. Missing or expired media makes the export `PARTIAL`; message text and metadata are preserved.

## Safety

The skill does not crack Zalo encryption or call send/delete/import APIs. It leaves the source Zalo data untouched and closes any temporary CDP session after extraction.
