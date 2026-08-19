# ZL Extractor

> Turn your Zalo PC chats into a clean, searchable archive.

ZL Extractor helps you save the conversations that matter—messages, useful
links, pinned links, and requested media—into one organized folder you can
search, review, and reuse.

## Why use it?

Zalo chats are full of ideas, resources, campaigns, and files that are hard to
find later. ZL Extractor turns that noise into a practical archive:

- Keep the full conversation in readable TXT and CSV files.
- Open a human-first Markdown view grouped by day and sender.
- Find and organize links shared in messages and pinned content.
- Merge repeated shares into a clear link list while keeping the context.
- Export images and files when you need them.
- Skip GIFs and stickers by default so the archive stays useful.
- See clearly what was exported, what needs review, and what Zalo did not expose.

It is useful for affiliate groups, community research, content research, and
personal knowledge archives.

## Quick start

Copy the skill into your Codex skills directory:

```bash
cp -R zl-extractor ~/.codex/skills/zl-extractor
```

Then ask Codex:

```text
Use $zl-extractor to export the Zalo group "AFF Siêu Dễ - 30 Ngày Ăn Ngủ Cùng AFF".
Include messages, links, pinned content, and requested media from 2026-07-16 onward.
```

The skill discovers the current machine's Zalo paths, account, conversation,
and temporary connection automatically.

## What you receive

```text
group-export/
├── readable/          the folder people open first
├── attachments/       images/files when requested
├── raw/               exact CSV/JSON for audit and reprocessing
└── source/            manifest and extraction provenance
```

The result is designed to be portable: open `readable/index.md`, search the
conversation, or hand the useful parts to another workflow. Raw files stay
available without cluttering the reading experience.

## Privacy first

- Uses your already logged-in Zalo session as the read boundary.
- Does not crack encryption or extract keys.
- Does not send, delete, import, or modify Zalo data.
- Does not upload chats or media to a third-party service.
- Resolves paths and identifiers for each machine instead of hard-coding them.

## Honest results

Zalo may keep some content behind its live app or may not expose every pinned
item or media file. ZL Extractor reports those limits instead of pretending the
archive is complete. Readable messages and metadata remain available even when
some optional content needs review.

## Technical documentation

The README stays intentionally simple. The detailed workflow lives here:

- [SKILL.md](SKILL.md) — core workflow and safety rules
- [readable-output.md](references/readable-output.md) — human-first folder and transcript layout
- [links-and-pins.md](references/links-and-pins.md) — pinned content, dedupe, and link context
- [attachments.md](references/attachments.md) — media retrieval and GIF/sticker policy
- [verification.md](references/verification.md) — audits, statuses, and closeout checks
