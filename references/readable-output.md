# Human-readable output

Read this reference whenever the user asks for an organized folder, readable
messages, link reports, or a presentation suitable for non-technical readers.

## Design decision

Keep two layers with different jobs:

```text
readable/  = the first thing a person opens
raw/       = machine-readable inputs for audit/reprocessing
source/    = manifest and provenance; never the main reading view
```

Do not make people read CSV/JSON to understand the conversation. Do not put
human summaries back into raw files. The readable layer may normalize spacing,
group by date, shorten labels, and add navigation, but must not change message
meaning or invent context.

## Canonical folder

```text
<slug>-export-<timestamp>/
├── readable/
│   ├── index.md
│   ├── messages.md
│   ├── pins.md
│   ├── links.csv
│   ├── media.csv       (only when attachments exist)
│   └── review.csv      (only when unresolved links exist)
├── attachments/
│   ├── images/
│   ├── videos/
│   ├── audio/
│   ├── files/
│   └── other/
├── raw/
│   ├── messages.csv
│   ├── links.csv
│   ├── links-occurrences.csv
│   ├── pins.csv
│   ├── attachments.csv
│   ├── zalo-media-links.csv
│   ├── link-review.csv
│   └── link-review-resolutions.csv
└── source/
    ├── manifest.json
    ├── link-archive-audit.json   (when Zalo's Link tab is checked)
    ├── pin-audit.json
    ├── phase-ledger.json
    ├── run-plan.json
    └── item-checkpoints.jsonl
```

For compatibility, an old `01-messages/`, `02-attachments/`, and `03-reports/`
export may be read. The renderer mirrors those files into `raw/` without
deleting or editing the legacy files; signed internal Zalo media query strings
are removed from the derived mirror.

## Message presentation

`readable/messages.md` is the main transcript:

```markdown
# AFF Siêu Dễ - 30 Ngày Ăn Ngủ Cùng AFF

## 2026-07-16

### 10:15 — Nguyễn Văn A

> Nội dung tin nhắn giữ nguyên, chỉ đổi cách trình bày.

### 10:18 — Trần B

> Tin nhắn tiếp theo...
```

Rules:

- Sort oldest-to-newest and group by local calendar date.
- Show sender and local time on every message block.
- Preserve the original message text; only wrap it for readability.
- Mark non-text records as `[image]`, `[file]`, `[system]`, etc.; do not dump opaque objects.
- Show a short attachment marker next to the message; link the binary only when it was actually saved.
- Keep the transcript chronological. Do not merge separate messages into an invented summary.
- Render epoch timestamps in `Asia/Ho_Chi_Minh` by default; set `ZL_DISPLAY_TIMEZONE` for another reader timezone.

## Link presentation

`readable/links.csv` contains one compact row per canonical URL. Keep the
reader-facing table focused on action and verification fields; do not place
long message context into the table. Its columns are:

```text
STT | Link | Phân loại | Số lần | Thời gian gửi đầu tiên | Review
```

Keep the exact URL in the CSV. Filter its `category` column instead of
generating category subfolders. Full context, IDs, source evidence, and
classification details remain in `raw/` and optional `review.csv`. Internal Zalo CDN URLs and signed query strings are
not reader-facing data: keep only normalized host/status or a fingerprint
unless the user explicitly asks for the raw token-bearing value.

`readable/pins.md` is a separate pin-first view. It must show the number of
enumerated pinned records, each record's time/sender/context, external links,
message-window scope (including older out-of-window pins), and internal media
references separately. Do not hide pin links inside the
general link count. The index must show the message scope, user-facing unique
links, all exact URLs, message/pin/media occurrence counts, pinned-record
count, Link-archive status/count when available, and pin-audit status.
If the export starts at a date boundary, make that boundary visible so a
reader does not compare a partial-period export with Zalo's all-history link
counter.

`readable/links.csv` is an intentionally narrow six-column reading table:
`sequence`, `url`, `category`,
`occurrence_count`, `first_seen`, and `review_status`. They are the default
choice for quick sorting/filtering in Excel, Numbers, or Google Sheets. Full
context, source IDs, classification evidence, and canonicalization details
remain in `raw/` and `review.csv`. Do not create XLSX by default; add it only
when the user needs formulas, pivots, or a styled workbook.

## Media and review presentation

- `readable/media.csv` is created only when saved attachment records exist; it is a five-column sortable attachment table.
- `readable/review.csv` is created only when unresolved classifications exist; it is a filterable review queue.
- `readable/index.md` is the landing page: status, counts, date range when known, and links to every view.
- Keep warnings visible on the index; do not bury `PARTIAL` or missing Pin coverage in raw JSON.

## Why this shape

The layout follows patterns used by established export formats: offline
human-readable Markdown, a title and metadata header, timestamped sender
blocks, date grouping, and a separate machine-readable layer. Markdown is the
default because it stays portable and diffable; CSV is used only for compact
tables that benefit from sorting or filtering.

Reference examples:

- [Telegram Data Export Schema](https://core.telegram.org/import-export) — offline human-readable export alongside JSON.
- [AI Chat Archive Markdown format](https://docs.aichatarchive.app/spec/markdown-format/) — title, timestamps, sender turns, and attachment markers.
- [AI Chat Archive HTML format](https://docs.aichatarchive.app/spec/html-format/) — self-contained offline presentation with semantic sender/timestamp blocks.
- [Slack: How to read data exports](https://slack.com/help/articles/220556107-How-to-read-Slack-data-exports) — raw JSON/date files separated from readable message views.
- [Chat Trail](https://github.com/rasalas/chat-trail) — transcript plus manifest, hashes, and evidence files.
