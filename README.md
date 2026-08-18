# ZL Extractor

> Turn a logged-in Zalo PC account into a clean, searchable conversation archive—without cracking encryption or uploading private data.

ZL Extractor is a privacy-first Codex skill for turning Zalo PC chat history into useful, portable output: readable messages, organized links, pinned-content links, and only the media you actually need.

## Why it is useful

A raw chat dump is hard to search and even harder to reuse. ZL Extractor gives each conversation structure:

- Map the exact Zalo conversation by name and runtime ID.
- Export messages to UTF-8 TXT/CSV.
- Collect links from message text and the conversation's pinned content.
- Classify links by chat context, sort them, and create safe context-based names.
- Retrieve requested images, videos, audio, and files through the authenticated Zalo renderer.
- Skip GIF and sticker binaries by default while preserving their metadata.
- Verify counts, file hashes, paths, and partial results in a manifest.

The result is an archive you can search, review, hand off, or use as a foundation for affiliate and content research.

## Quick start

Install the skill into your Codex skills directory:

```bash
cp -R zl-extractor ~/.codex/skills/zl-extractor
```

Then ask Codex:

```text
Use $zl-extractor to export the Zalo group "AFF Siêu Dễ - 30 Ngày Ăn Ngủ Cùng AFF".
Include messages, links, pinned content, and requested media from 2026-07-16 onward.
```

Paths, account IDs, conversation IDs, and CDP ports are resolved at runtime for the current machine.

## Skill structure

The entrypoint stays focused on the portable workflow. Detail is loaded only
when the request needs it:

```text
SKILL.md
references/
├── links-and-pins.md   # Pin audit, exact dedupe, context classification
├── attachments.md      # Images/files, GIF/sticker policy, hashes
└── verification.md     # Independent audit, statuses, closeout
scripts/                # Deterministic implementation and checks
```

This keeps normal chat-export requests short while preserving the strict link,
media, and verification rules for the runs that need them.

## Link intelligence

Links are treated as useful records, not just a pile of URLs. Repeated links are merged before the final classification step: the archive keeps one canonical row per user-facing URL while preserving the full occurrence history for audit.

### Deduplicate, then understand context

For each URL, ZL Extractor:

1. Keeps the raw occurrences in `03-reports/links-occurrences.csv`.
2. Groups only the exact same URL after trimming whitespace; scheme, path, query, fragment, and affiliate/tracking parameters are retained as distinct variants.
3. Reads every related message, quote, and pinned record.
4. Combines the evidence into one context summary and one final category.
5. Stores occurrence count, related message/pin IDs, sources, time range, alternate categories, and context conflicts.

The canonical `links.csv`, `links-classified.csv`, and category files therefore contain one row per canonical user-facing URL. Repeated sharing is not silently deleted—it is represented by `occurrence_count` and the related IDs. Internal Zalo media refs are reported separately.

### Context-aware categories

The skill classifies each link using its host/path plus the nearest message, quote, pin title, and timestamp:

| Category | Typical meaning |
|---|---|
| `shopee-affiliate` | Products, campaigns, commissions, and affiliate links |
| `training-guide` | Courses, tutorials, YouTube, Drive, and Notion |
| `tool-platform` | Dashboards, SaaS, tools, and platform links |
| `social-community` | Facebook, Telegram, TikTok, and community links |
| `tracking-redirect` | Shorteners, trackers, and redirect-only URLs |
| `zalo-media` | Internal Zalo CDN/media references, kept separate from user-facing links |
| `other` | No reliable category evidence |

Internal Zalo CDN/media URLs are not user-facing chat links. They are kept in the media audit and attachment records so the main link list stays useful.

Every run has an independent verification gate: counts are recomputed from the raw ledger, exact URL variants are checked for accidental merging, media leakage is checked, and pin-audit status is reported separately. A mismatch leaves the export `PARTIAL`/`REVIEW_REQUIRED`.

The package includes a review-queue writer and a separate read-only verifier:

```bash
python3 scripts/write_link_review.py /absolute/path/to/group-export-<timestamp>  # writes review files
python3 scripts/audit_links.py /absolute/path/to/group-export-<timestamp>        # read-only; 0=PASS, 2=PARTIAL, 1=FAIL
python3 scripts/test_link_rules.py                                                    # adversarial host/path smoke tests
python3 scripts/enforce_attachment_policy.py /absolute/path/to/group-export-<timestamp>
```

Low-confidence, conflicting, and deterministic rule-override classifications are listed in `03-reports/link-review.csv`; they remain `REVIEW_REQUIRED` until independently reviewed.

Completed independent reviews are recorded in `03-reports/link-review-resolutions.csv`; rerunning the writer preserves those resolutions and only reopens unresolved rows. A resolution is evidence of review, not permission to invent a category.

Every canonical link record keeps the original URL plus:

```text
url, canonical_url, category, original_category, classification_rule,
context_name, context_summary, confidence,
occurrence_count, message_ids, pin_ids, sources, first_seen, last_seen,
observed_categories, context_alternatives
```

Known host/path evidence takes precedence over generic neighboring chat text. Overrides keep `original_category` and `classification_rule` so every correction remains auditable.

Category views are sorted by category, time, and message/pin sequence. Context-based names follow this pattern:

```text
2026-07-16__shopee-affiliate__chien-dich-30-ngay__001
```

The skill never invents context from unrelated messages. If the evidence is weak, it uses `uncategorized`/low confidence and preserves the original record.

## Export layout

```text
<group>-export-<timestamp>/
  01-messages/
    messages.txt
    messages.csv
    links.csv
    links-classified.csv
    links-by-category/
      <category>.csv
  02-attachments/  # created/populated when media retrieval is requested
    images/
    videos/
    audio/
    files/
    other/
  03-reports/
    links-occurrences.csv
    links-classified-occurrences.csv
    link-review.csv
    link-review-resolutions.csv
    zalo-media-links.csv
    attachments.csv
    manifest.json
```

The canonical `links.csv` is the deduplicated user-facing index. `03-reports/links-occurrences.csv` is the complete raw occurrence ledger; `03-reports/zalo-media-links.csv` contains internal media refs. Category files are deduplicated filtered views, not replacements for the audit records. The link reports do not by themselves prove that binary attachments were downloaded.

## Media policy

When attachments are requested, the in-scope binary types are images, videos, audio, files, and other verified documents.

GIFs and stickers are intentionally not downloaded by default because they add noise without helping the archive. Their metadata remains visible as `skipped_by_policy`. Other media is classified with explicit statuses such as `copied`, `downloaded`, `preview_only`, `not_found`, `failed_404`, and `unreadable`.

## How it works

1. Resolve the current machine's Zalo data root and active account.
2. Map the requested display name to the exact conversation in the logged-in Zalo renderer.
3. Read the app-managed message stream through the renderer's read-only DataAccess path.
4. Audit the exact conversation's pinned content for links outside the normal message stream.
5. Deduplicate repeated URLs, read all related context, merge the evidence, then classify and sort the canonical links.
6. Copy only requested, verified media and validate every output hash.
7. Write the review queue, run the independent read-only audit, and do not call the result complete while pins or classifications remain unresolved.

## Privacy and safety

- Read-only workflow: no send, delete, import, migration, or database repair APIs.
- No encryption-key extraction or brute-force decryption.
- No chat content or media is uploaded to a third party.
- Source Zalo data remains unchanged.
- Machine-specific paths and identifiers are discovered at runtime.
- Signed CDN URLs stay out of terminal output; media references are reported with safe status metadata unless raw URLs are explicitly requested.

## Honest limits

Zalo's local state is app-managed and may be encrypted. A renderer-based export is not automatically an official Zalo backup.

The result is marked `PARTIAL` when pinned content cannot be audited, live synchronization changes the snapshot, or requested in-scope media is missing/expired. A `PARTIAL` export still preserves the readable messages, links, metadata, and failure reasons.

## Attachment status

`copied`, `downloaded`, `preview_only`, `not_found`, `remote_only`, `failed_404`, `failed_500`, `network_error`, `unreadable`, and `skipped_by_policy` are recorded per media row.

## Safety boundary

ZL Extractor is an extraction workflow, not a Zalo decryptor. It uses the user's already logged-in Zalo session as the read/decryption boundary and closes any temporary CDP session after the run.
