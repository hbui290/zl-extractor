# Human-readable output

Read this reference whenever the user asks for an organized folder, readable
messages, link reports, or a presentation suitable for non-technical readers.

## Design decision

Keep two layers with different jobs:

```text
readable/  = the first thing a person opens
raw/       = exact machine-readable inputs for audit/reprocessing
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
│   ├── links.md
│   ├── links-by-category/
│   │   └── <category>.md
│   ├── media.md
│   └── review.md
├── attachments/
│   ├── images/
│   ├── videos/
│   ├── audio/
│   ├── files/
│   └── other/
├── raw/
│   ├── messages.csv
│   ├── links.csv
│   ├── links-classified.csv
│   ├── links-occurrences.csv
│   ├── links-classified-occurrences.csv
│   ├── attachments.csv
│   ├── zalo-media-links.csv
│   ├── link-review.csv
│   └── link-review-resolutions.csv
└── source/
    ├── manifest.json
    ├── link-classification.json
    └── source-info.json
```

For compatibility, an old `01-messages/`, `02-attachments/`, and `03-reports/`
export may be read. The renderer mirrors those files into `raw/` without
deleting or editing the legacy files.

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

## Link presentation

`readable/links.md` contains one human-readable card per canonical URL and
groups cards by category. Each card should show:

```text
Context title
Open link
Category · confidence · occurrence count
First/last seen · message/pin source
Short evidence-backed context
```

Use `links-by-category/<category>.md` as filtered views, not a second source of
truth. Keep long URLs behind a descriptive link label, while retaining the
exact URL in `raw/links.csv`.

## Media and review presentation

- `readable/media.md` is a compact table: time, sender, type, filename, output path, and status.
- `readable/review.md` contains only unresolved classifications and the reason each needs attention.
- `readable/index.md` is the landing page: status, counts, date range when known, and links to every view.
- Keep warnings visible on the index; do not bury `PARTIAL` or missing Pin coverage in raw JSON.

## Why this shape

The layout follows patterns used by established export formats: offline
human-readable HTML/Markdown, a title and metadata header, timestamped sender
blocks, date grouping, and a separate machine-readable layer. Markdown is the
default because it stays portable and diffable; a browser UI can be added later
without changing the raw contract.

Reference examples:

- [Telegram Data Export Schema](https://core.telegram.org/import-export) — offline human-readable export alongside JSON.
- [AI Chat Archive Markdown format](https://docs.aichatarchive.app/spec/markdown-format/) — title, timestamps, sender turns, and attachment markers.
- [AI Chat Archive HTML format](https://docs.aichatarchive.app/spec/html-format/) — self-contained offline presentation with semantic sender/timestamp blocks.
- [Slack: How to read data exports](https://slack.com/help/articles/220556107-How-to-read-Slack-data-exports) — raw JSON/date files separated from readable message views.
- [Chat Trail](https://github.com/rasalas/chat-trail) — transcript plus manifest, hashes, and evidence files.
