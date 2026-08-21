# Links and pinned content

Read this reference only when the user asks for links, pinned links, sorting,
classification, or context-based filenames.

## Pin audit

Inspect the exact conversation's pinned-message/pinned-content panel through the
logged-in Zalo renderer in addition to `loadMessagesForBackup`. Pinned content
may not be in the normal message stream.

- Bind the lookup to the verified conversation ID; a global pinned-chat list is not enough.
- Open the exact conversation's pin panel before the audit so its visible total can be bound to that conversation. Discover the current build's read-only pin state/API/UI data at runtime. Do not guess version-specific methods or call pin/unpin/delete actions.
- Add links from messages with `source=message` and pins with `source=pin`; retain `message_id`/`pin_id` when available.
- `START_AT`/`END_AT` belong only to the chronological message snapshot. They never remove a record from the independent pin panel; retain older pinned records with an out-of-window provenance marker.
- Record `pinAuditStatus`, `pinAuditCompleteness`, enumerated pin count, unique pin-link count, and the pagination/end condition.
- Mark complete only when the exact panel reaches its end or matches an exact UI total. A service/API row count by itself is not sufficient. Otherwise use `unknown`/`blocked` and keep the export `PARTIAL`.
- If the pin panel is not visible or cannot be matched to the requested conversation, keep `PARTIAL`; do not promote an API row count to completeness.
- Run the pin preflight immediately after conversation resolution, before media retrieval. A page cap, thrown request, unchanged cache, or missing `noMore`/explicit-total signal is not complete; do not turn it into `NO_MORE` by guesswork.
- Use one bounded pagination loop with a repeated-page guard. If the end marker is not observed, stop with `pinAuditCompleteness=unknown`/`PARTIAL` instead of probing the same panel dozens of times.

## Zalo's separate Link archive

The conversation-info `Link` tab is a separate Zalo repository. It is not
equivalent to the text returned by `loadMessagesForBackup`, and it is not the
same thing as the pinned-message panel. Keep these ledgers separate:

```text
message links       = URLs found in the chronological message snapshot
pinned links        = URLs found in the exact pinned-message panel
Link archive        = cards enumerated from Zalo's conversation-info Link tab
```

Open the exact conversation's full Link view and run the bundled
`fetch_zalo_link_archive.mjs` adapter. Record `source/link-archive-audit.json`
with `reportedCardCount`, `enumeratedCardCount`, `status`, and an explicit end
condition. The visible number is a card count, not a URL count; a single card
can contain several URLs. Extract URLs from `message.title`, falling back to
`message.href` only when the title contains no URL. Never recursively scan
thumbnail, icon, preview, or resolved-asset fields. If the archive cannot be enumerated, keep the export
`PARTIAL` and say so in `readable/index.md`; never present the message/pin
ledger as proof that the Link tab is complete. A visible UI count such as
`75 link trong 2026` is evidence to reconcile, not a substitute for the
enumerated rows.

## Occurrence ledger and exact dedupe

1. Write every unmodified occurrence to `source/raw/links-occurrences.csv` before dedupe.
2. Recognize explicit `http(s)://` URLs and conservative bare domains (for example `make.com`). Keep a bare domain's original spelling in raw output; the readable view adds `https://` only to make it clickable.
3. Set `canonical_url = url.strip()` only after that extraction step. Preserve scheme, host, port, path, query, fragment, encoding, and every affiliate/tracking parameter.
4. Do not resolve redirects, fuzzy-match domains, or merge URL variants. Different parameters or paths are different canonical URLs. Ambiguous domain-like text stays in review instead of becoming a link.
5. Group message, Link-archive, and pin occurrences by `canonical_url`, then read every related message, quote, and pin record before classifying.
6. Write exactly one user-facing row per canonical URL. Merge occurrence count, all related message/pin IDs, senders, sources, timestamps, observed categories, and a short evidence-backed context summary.
7. Keep the raw ledger as the audit trail; repeated sharing is represented by `occurrence_count`, not by duplicate final rows.

The canonical schema includes:

```text
url, canonical_url, category, original_category, classification_rule,
context_name, context_summary, confidence, occurrence_count,
message_ids, pin_ids, sources, first_seen, last_seen,
observed_categories, context_alternatives
```

Internal Zalo CDN/media references are classified as `zalo-media` and written to
`source/raw/zalo-media-links.csv`, never to the user-facing link index.

The normalized pin adapter recursively inspects the topic payload and resolved
message, including nested params/data/payload fields, before it writes
`source/raw/pins.csv` with `source=pin` and preserves
`pin_id`, related `message_id`, timestamp, sender, title/text, and extracted URL
fields. The link stage also consumes `source/raw/link-archive.csv` when present. A
Link-archive card and the chronological message with the same `(message_id,
exact URL)` are one message occurrence with merged source evidence
(`message|link_archive`), not two shares. Exact duplicates inside one card are
counted once; different exact URLs remain different.

```bash
python3 -B scripts/extract_links.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
python3 -B scripts/apply_category_rules.py <OUTPUT_ROOT>/<slug>-export-<timestamp>
```

If the run plan requires pins and `source/raw/pins.csv` is absent, stop the link phase
as `BLOCKED`/`PARTIAL`; do not silently treat the missing pin panel as zero pins.

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

This command writes `source/raw/link-review.csv`; it is not read-only. Resolve
reviewed rows in `source/raw/link-review-resolutions.csv` with `status=rule_verified` or
`resolved`. Rerunning the writer preserves resolved rows and reopens only
unresolved rows. A resolution records evidence of review; it does not justify
inventing a category.

The canonical machine outputs are built from deduplicated rows only:

```text
source/raw/links.csv
source/raw/links-occurrences.csv
source/raw/zalo-media-links.csv
source/raw/link-review.csv
source/raw/link-review-resolutions.csv
```

Human-facing views are written separately to `readable/links.csv` and
`readable/pins.md`; optional `readable/review.csv` is written only when needed.
The link CSV is the single reader table, not another occurrence ledger. `pins.md` is the
reader-facing pin audit and must show each pinned record and its extracted
links separately from the chronological message link list. Filter category
values in the table instead of creating category subfolders.

For a user-supplied manual list, run `scripts/reconcile_link_baseline.py`. It
writes line-level `source/manual-link-reconciliation.csv` and a JSON summary;
repeated identical URLs are labeled
`OCCURRENCE_NOT_PROVEN` when the export cannot independently prove a second
occurrence. Exact URL absence remains `MISSING`; do not conflate it with a
manual duplicate.
