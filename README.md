# ZL Extractor

> Turn your Zalo PC chats into a clean, searchable archive.

ZL Extractor helps you save the conversations that matter—messages, useful
links, pinned links, and requested media—into one organized folder you can
search, review, and reuse.

## Why use it?

Zalo chats are full of ideas, resources, campaigns, and files that are hard to
find later. ZL Extractor turns that noise into a practical archive:

- Keep the full conversation in readable Markdown, with CSV tables for links,
  attachments, and review work.
- Open a human-first Markdown view grouped by day and sender.
- Find and organize links shared in messages and pinned content, while keeping
  Zalo's separate conversation-info Link archive as its own coverage check.
- Count Link-archive cards separately from URLs, so one multi-link card is not
  mistaken for one URL.
- Merge repeated shares into a clear link list while keeping the context.
- Export images and files when you need them.
- Skip GIFs and stickers by default so the archive stays useful.
- Reuse one message snapshot for media candidates so requested media does not
  trigger a second full history scan.
- Continue an existing export later using a saved message watermark and
  idempotent delta merge.
- Lock the requested scope before runtime work and resume completed items safely.
- Measure each workflow phase so slow runs have a clear cause.
- See clearly what was exported, what needs review, and what Zalo did not expose.

It is useful for affiliate groups, community research, content research, and
personal knowledge archives.

## Speed and resumability

The slow part is the authenticated Zalo runtime, not local formatting. The
workflow records each phase in `source/phase-ledger.json`, reuses one message
snapshot for links and media candidates, and resumes later runs from saved
watermarks/checkpoints.

Local post-processing is kept lightweight and phase timings are recorded so a
slow run can be traced to the runtime, downloads, OCR, or rendering. Live
performance remains dependent on the current Zalo session, network conditions,
history size, and requested media scope.

## Quick start

Copy the skill into your Codex skills directory:

```bash
cp -R ./zl-extractor ~/.codex/skills/zl-extractor
```

Then ask Codex:

```text
Use $zl-extractor to export the Zalo group "AFF Siêu Dễ - 30 Ngày Ăn Ngủ Cùng AFF".
Include messages, links, and all currently pinned content. Read messages from 2026-07-16 onward; keep pinned records older than that window separately. Include media only if I explicitly request it.
```

The skill discovers the current machine's Zalo paths, account, conversation,
and temporary connection automatically.

## Use it with other coding agents

Copy this folder as-is; keep `SKILL.md`, `references/`, `scripts/`, and
`runtime/` together when live Zalo extraction or media retrieval is in scope.
Choose user scope for a personal install or project scope for a team/project
install.

| Agent | Common skill folder | Invoke |
|---|---|---|
| Codex | `~/.codex/skills/zl-extractor` or `.agents/skills/zl-extractor` | `$zl-extractor` |
| Claude Code | `~/.claude/skills/zl-extractor` | `/zl-extractor` |
| DeepCode | `.deepcode/skills/zl-extractor` or `~/.agents/skills/zl-extractor` | skill name in the agent |
| Kimi Code | `.kimi-code/skills/zl-extractor` or `.agents/skills/zl-extractor` | `/zl-extractor` |
| ZCode | import this skill folder | imported skill name |

Host-specific discovery and import rules can change; use the official guides:
[Codex](https://developers.openai.com/codex/skills),
[Claude Code](https://code.claude.com/docs/en/skills),
[DeepCode](https://api-docs.deepseek.com/quick_start/agent_integrations/deepcode),
[Kimi Code](https://moonshotai.github.io/kimi-code/en/customization/skills),
[ZCode](https://zcode.z.ai/en/docs/skill).

## What you receive

```text
group-export/
├── readable/          Markdown reading views + curated CSV tables
├── attachments/       images/files when requested
├── raw/               machine-readable CSV/JSON for audit; signed media redacted
└── source/            manifest, run plan, checkpoints, provenance, and timings
```

The result is designed to be portable: open `readable/index.md`, search the
conversation, or hand the useful parts to another workflow. Raw files stay
available without cluttering the reading experience. The default readable
folder is intentionally small: `index.md`, `messages.md`, `links.csv`, and
`pins.md`, plus `review.csv` or `media.csv` only when they contain records.

## Privacy first

- Uses your already logged-in Zalo session as the read boundary.
- Does not crack encryption or extract keys.
- Does not send, delete, import, or modify Zalo data.
- Does not upload chats or media to a third-party service.
- Resolves paths and identifiers for each machine instead of hard-coding them.

## Honest results

Zalo may keep some content behind its live app or may not expose every pinned
item, Link-archive card, or media file. ZL Extractor reports those limits
instead of pretending the archive is complete. Message date boundaries apply
only to the chronological message snapshot; pinned content is audited
independently and older pinned records remain in scope. Message links, pinned
links, and Link-archive links are separate sources; a visible Zalo counter is
recorded as evidence until the records are enumerated and reconciled.
If you already collected a manual list, the bundled reconciliation check shows
matched, missing, additional, and repeated exact URLs with line-level evidence.

## Technical documentation

The README stays intentionally simple. The detailed workflow lives here:

- [SKILL.md](SKILL.md) — core workflow and safety rules
- [readable-output.md](references/readable-output.md) — human-first folder and transcript layout
- [links-and-pins.md](references/links-and-pins.md) — pinned content, dedupe, and link context
- [attachments.md](references/attachments.md) — media retrieval and GIF/sticker policy
- [verification.md](references/verification.md) — audits, statuses, and closeout checks
- [scripts/phase_ledger.py](scripts/phase_ledger.py) — phase timing ledger and validator
- [scripts/run_plan.py](scripts/run_plan.py) — scope lock and phase policy
- [scripts/item_checkpoint.py](scripts/item_checkpoint.py) — item-level resume ledger
- [scripts/incremental_state.py](scripts/incremental_state.py) — later-run watermark and delta merge
- [scripts/extract_links.py](scripts/extract_links.py) — exact occurrence ledger, context merge, and dedupe
- [runtime/](runtime/) — bundled, version-sensitive CDP adapters for messages, pins, media, and OCR
- [runtime/fetch_zalo_media.mjs](runtime/fetch_zalo_media.mjs) — bounded authenticated media export
- [evals/evals.json](evals/evals.json) — small private-data-free behavior contracts
