# Links and pinned content

Read this reference only when the user asks for links, pinned links, sorting,
classification, or context-based filenames.

## Pin audit

Inspect the exact conversation's pinned-message/pinned-content panel through the
logged-in Zalo renderer in addition to `loadMessagesForBackup`. Pinned content
may not be in the normal message stream.

- Bind the lookup to the verified conversation ID; a global pinned-chat list is not enough.
- Discover the current build's read-only pin state/API/UI data at runtime. Do not guess version-specific methods or call pin/unpin/delete actions.
- Add links from messages with `source=message` and pins with `source=pin`; retain `message_id`/`pin_id` when available.
- Record `pinAuditStatus`, `pinAuditCompleteness`, enumerated pin count, unique pin-link count, and the pagination/end condition.
- Mark complete only when the exact panel reaches its end or matches an explicit total. Otherwise use `unknown`/`blocked` and keep the export `PARTIAL`.
- Run the pin preflight immediately after conversation resolution, before media retrieval. A page cap, thrown request, unchanged cache, or missing `noMore`/explicit-total signal is not complete; do not turn it into `NO_MORE` by guesswork.
- Use one bounded pagination loop with a repeated-page guard. If the end marker is not observed, stop with `pinAuditCompleteness=unknown`/`PARTIAL` instead of probing the same panel dozens of times.

## Occurrence ledger and exact dedupe

1. Write every unmodified occurrence to `raw/links-occurrences.csv` before dedupe.
2. Set `canonical_url = url.strip()` only. Preserve scheme, host, port, path, query, fragment, encoding, and every affiliate/tracking parameter.
3. Do not resolve redirects, fuzzy-match domains, or merge URL variants. Different parameters or paths are different canonical URLs.
4. Group message and pin occurrences by `canonical_url`, then read every related message, quote, and pin record before classifying.
5. Write exactly one user-facing row per canonical URL. Merge occurrence count, all related message/pin IDs, senders, sources, timestamps, observed categories, and a short evidence-backed context summary.
6. Keep the raw ledger as the audit trail; repeated sharing is represented by `occurrence_count`, not by duplicate final rows.

The canonical schema includes:

```text
url, canonical_url, category, original_category, classification_rule,
context_name, context_summary, confidence, occurrence_count,
message_ids, pin_ids, sources, first_seen, last_seen,
observed_categories, context_alternatives
```

Internal Zalo CDN/media references are classified as `zalo-media` and written to
`raw/zalo-media-links.csv`, never to the user-facing link index.

## Classification

Use host/path evidence first, then the nearest message, quote, pin title, and
timestamp. Never use unrelated group-wide text to invent a label. Preserve
`original_category` and `classification_rule` whenever a deterministic rule
overrides a first-pass label.

Stable categories:

```text
shopee-affiliate   = products, campaigns, commission, or affiliate links
training-guide     = courses, tutorials, YouTube, Drive, Docs, or Notion
tool-platform      = dashboards, SaaS, tools, or platform links
social-community   = ordinary Facebook, Telegram, TikTok, Instagram, or community links
tracking-redirect  = shorteners/tracking/redirect-only links when no destination rule applies
zalo-media         = internal Zalo CDN/media references, kept separate
other              = no reliable category evidence
```

Deterministic rules currently include:

- Known Shopee hosts → `shopee-affiliate`.
- Docs/Drive/Notion/YouTube → `training-guide`.
- Google Flow only when `labs.google` has `/fx/tools/flow/` or `/fx/<locale>/tools/flow/`; other `labs.google` paths are not automatically Flow.
- ChatGPT GPT/share links, Chrome Web Store, and Telegram bot usernames with a real `_bot` boundary → `tool-platform`.
- TikTok Shop `/university/` → `training-guide`; ordinary TikTok → `social-community`.
- Ordinary Facebook, Telegram, and Instagram → `social-community`.
- Shortener hosts → `tracking-redirect` only when no known destination rule applies.

Domain rules must respect registrable-domain boundaries; lookalikes such as
`notshopee.vn` or `notfacebook.com` must not inherit a trusted host rule.

Generate safe local names from evidence-backed context, for example:

```text
2026-07-16__shopee-affiliate__chien-dich-30-ngay__001
```

Use `uncategorized` and low confidence when context is weak. If evidence
conflicts, keep the winning category but retain `observed_categories` and
`context_alternatives`.

## Review and commands

Write the review queue after classification:

```bash
python3 scripts/write_link_review.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
```

This command writes `raw/link-review.csv`; it is not read-only. Resolve
reviewed rows in `raw/link-review-resolutions.csv` with `status=rule_verified` or
`resolved`. Rerunning the writer preserves resolved rows and reopens only
unresolved rows. A resolution records evidence of review; it does not justify
inventing a category.

The canonical machine outputs are built from deduplicated rows only:

```text
raw/links.csv
raw/links-classified.csv
raw/links-by-category/<category>.csv
raw/links-occurrences.csv
raw/zalo-media-links.csv
raw/link-review.csv
raw/link-review-resolutions.csv
```

Human-facing views are written separately to `readable/links.md` and
`readable/links-by-category/<category>.md`. Category views are filtered views,
not another occurrence ledger. Sort them by category, time, and message/pin
sequence, and keep paths relative to the export.
