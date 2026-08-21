#!/usr/bin/env python3
"""Apply deterministic host/path category rules to an existing exact-URL export."""

import argparse
import csv
import json
from pathlib import Path
from urllib.parse import urlsplit

from export_paths import assert_source_read_only, export_paths, safe_category_slug
from url_rules import parseable_url


FIELDS = [
    "sequence", "message_id", "message_ids", "pin_id", "pin_ids", "timestamp", "first_seen", "last_seen",
    "sender", "senders", "source", "sources", "category", "original_category", "classification_rule",
    "observed_categories", "context_name", "context_alternatives", "context_summary", "confidence",
    "occurrence_count", "url", "canonical_url",
]


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    fields = list(FIELDS)
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def unique(values):
    return list(dict.fromkeys(value for value in values if value))


def is_domain(host, domain):
    return host == domain or host.endswith("." + domain)


def is_google_flow_path(path):
    parts = [part for part in path.split("/") if part]
    return parts[:3] == ["fx", "tools", "flow"] or (len(parts) >= 4 and parts[0] == "fx" and parts[2:4] == ["tools", "flow"])


def parsed(url):
    try:
        value = urlsplit(parseable_url(url))
        return (value.hostname or "").lower(), value.path.lower(), value.fragment.lower()
    except ValueError:
        return "", "", ""


def is_media_host(host):
    return host.endswith((".zdn.vn", ".zadn.vn", ".dlmd.me", ".dlfl.vn")) and any(
        token in host for token in ("stal", "ava-talk", "zpg-r", "photo-link-talk")
    )


def category_rule(url):
    host, path, fragment = parsed(url)
    if is_media_host(host):
        return "zalo-media", "media_host_rule"
    if is_domain(host, "docs.google.com") or is_domain(host, "drive.google.com") or is_domain(host, "notion.so") or is_domain(host, "notion.site"):
        return "training-guide", "host_path_rule:training-guide"
    if is_domain(host, "youtube.com") or host == "youtu.be":
        return "training-guide", "host_path_rule:training-guide"
    if (is_domain(host, "labs.google") and is_google_flow_path(path)) or is_domain(host, "chromewebstore.google.com"):
        return "tool-platform", "host_path_rule:tool-platform"
    if any(is_domain(host, domain) for domain in {"github.com", "gemini.google.com", "grok.com", "virustotal.com", "dashlane.com", "vmedia.vn", "xaykenh.me", "snap2wear.xyz", "aimediagen.com", "geminiwatermarkremover.io"}):
        return "tool-platform", "host_path_rule:tool-platform"
    if is_domain(host, "chatgpt.com") and path.startswith(("/g/", "/share/")):
        return "tool-platform", "host_path_rule:tool-platform"
    if is_domain(host, "telegram.org") and host.startswith("web."):
        username = fragment.lstrip("@").split("/", 1)[0].split("?", 1)[0]
        return ("tool-platform", "host_path_rule:telegram-bot") if username.endswith("_bot") else ("social-community", "host_path_rule:social")
    if is_domain(host, "t.me"):
        username = path.strip("/").split("/", 1)[0]
        return ("tool-platform", "host_path_rule:telegram-bot") if username.endswith("_bot") else ("social-community", "host_path_rule:social")
    if is_domain(host, "tiktok.com") and path.startswith("/university/"):
        return "training-guide", "host_path_rule:training-guide"
    if is_domain(host, "zalo.me") and path.startswith("/g/"):
        return "social-community", "host_path_rule:social"
    if any(is_domain(host, domain) for domain in {"shopee.vn", "shopee.com", "shope.ee", "shp.ee"}):
        return "shopee-affiliate", "host_path_rule:shopee"
    if any(is_domain(host, domain) for domain in {"bit.ly", "tinyurl.com", "t.co", "cutt.ly", "t.ly", "shorturl.at", "lnkd.in"}):
        return "tracking-redirect", "host_path_rule:shortener"
    if any(is_domain(host, domain) for domain in {"facebook.com", "fb.watch", "tiktok.com", "instagram.com", "threads.net", "x.com"}):
        return "social-community", "host_path_rule:social"
    return None, "existing_classifier"


def update_row(row):
    original = row.get("original_category") or row.get("category", "other")
    current = row.get("category", "other")
    new_category, rule = category_rule(row.get("url", ""))
    if not new_category:
        new_category = current
    observed = unique((row.get("observed_categories", "").split("|") if row.get("observed_categories") else []) + [original, new_category])
    row["original_category"] = original
    row["category"] = new_category
    row["classification_rule"] = rule
    row["observed_categories"] = "|".join(observed)
    if rule != "existing_classifier":
        row["confidence"] = "high"
    return row


def sort_key(row):
    return (row.get("first_seen", row.get("timestamp", "")), row.get("canonical_url", row.get("url", "")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path)
    args = parser.parse_args()
    root = args.export_root.resolve()
    paths = export_paths(root)
    assert_source_read_only(root, paths["metadata"])
    messages = paths["machine"]
    occurrence_root = messages if paths["new_layout"] else paths["metadata"]
    reports = paths["metadata"]

    raw_classified_path = occurrence_root / "links-occurrences.csv"
    raw_classified = [update_row(row) for row in read_csv(raw_classified_path)]
    write_csv(raw_classified_path, raw_classified)

    raw_groups = {}
    for row in raw_classified:
        raw_groups.setdefault(row.get("url", "").strip(), []).append(row)
    raw_media = {url: rows for url, rows in raw_groups.items() if is_media_host(parsed(url)[0])}

    primary = [update_row(row) for row in read_csv(messages / "links.csv")]
    media_path = occurrence_root / "zalo-media-links.csv"
    media = [update_row(row) for row in read_csv(media_path)] if media_path.exists() else []
    all_rows = primary + media
    for row in all_rows:
        row["category"] = safe_category_slug(row.get("category"))
    primary = sorted([row for row in all_rows if row["category"] != "zalo-media"], key=sort_key)
    media = sorted([row for row in all_rows if row["category"] == "zalo-media"], key=sort_key)
    for index, row in enumerate(primary, 1):
        row["sequence"] = str(index).zfill(6)
    for index, row in enumerate(media, 1):
        row["sequence"] = str(index).zfill(6)

    write_csv(messages / "links.csv", primary)
    if media:
        write_csv(media_path, media)
    elif media_path.exists():
        media_path.unlink()
    for stale_path in (messages / "links-classified.csv", occurrence_root / "links-classified-occurrences.csv", reports / "link-classification.json"):
        if stale_path.exists():
            stale_path.unlink()
    category_dir = paths["categories"]
    if category_dir.exists():
        for old in category_dir.glob("*.csv"):
            old.unlink()
        try:
            category_dir.rmdir()
        except OSError:
            pass

    category_counts = {category: sum(row["category"] == category for row in primary) for category in sorted({row["category"] for row in primary})}
    user_facing_occurrences = sum(int(row.get("occurrence_count") or 1) for row in primary)
    media_occurrences = sum(int(row.get("occurrence_count") or 1) for row in media)
    classification_rule_set = "host/path precedence; media boundary first; exact URL grouping unchanged"

    manifest_path = reports / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("links", {})["categoryCounts"] = category_counts
        manifest["links"]["userFacingCanonicalRows"] = len(primary)
        manifest["links"]["internalMediaCanonicalRows"] = len(media)
        manifest["links"]["userFacingOccurrenceRows"] = user_facing_occurrences
        manifest["links"]["internalMediaOccurrenceRows"] = media_occurrences
        manifest["links"]["rawOccurrenceRows"] = len(raw_classified)
        manifest["links"]["allExactUniqueUrls"] = len(raw_groups)
        manifest["links"]["rawDuplicateUrlGroups"] = sum(len(rows) > 1 for rows in raw_groups.values())
        manifest["links"]["rawMergedExtraOccurrences"] = sum(len(rows) - 1 for rows in raw_groups.values() if len(rows) > 1)
        manifest["links"]["classificationRuleSet"] = classification_rule_set
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "primary_rows": len(primary),
        "media_rows": len(media),
        "category_counts": category_counts,
        "host_rule_overrides": sum(row["classification_rule"] != "existing_classifier" for row in all_rows),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
