#!/usr/bin/env python3
"""Build human-readable Markdown views from a ZL Extractor export.

The renderer is non-destructive: it mirrors legacy machine-readable files into
``raw/`` only when the new raw copy does not already exist, then writes views to
``readable/``. It never edits the source DB or the legacy export files.
"""

import argparse
import csv
import html
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from export_paths import (
    assert_source_read_only,
    contained_attachment,
    has_signed_internal_media_query,
    is_internal_media_url,
    redact_internal_media_url,
    safe_category_slug,
)


CATEGORY_LABELS = {
    "shopee-affiliate": "Shopee / affiliate",
    "training-guide": "Training / guides",
    "tool-platform": "Tools / platforms",
    "social-community": "Social / communities",
    "tracking-redirect": "Tracking / redirects",
    "other": "Other",
}

RAW_MIRRORS = {
    "messages.csv": "01-messages/messages.csv",
    "messages.txt": "01-messages/messages.txt",
    "links.csv": "01-messages/links.csv",
    "links-classified.csv": "01-messages/links-classified.csv",
    "links-occurrences.csv": "03-reports/links-occurrences.csv",
    "links-classified-occurrences.csv": "03-reports/links-classified-occurrences.csv",
    "zalo-media-links.csv": "03-reports/zalo-media-links.csv",
    "attachments.csv": "03-reports/attachments.csv",
    "link-review.csv": "03-reports/link-review.csv",
    "link-review-resolutions.csv": "03-reports/link-review-resolutions.csv",
}

SOURCE_MIRRORS = {
    "manifest.json": "03-reports/manifest.json",
    "link-classification.json": "03-reports/link-classification.json",
}


def read_csv(path):
    if not path or not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_table_csv(path, rows, preferred_fields):
    """Write a curated table; raw CSVs retain the full provenance columns."""
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(preferred_fields),
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(
            {
                field: safe_csv_value(row.get(field, ""))
                for field in preferred_fields
            }
            for row in rows
        )


def read_json(path):
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def pick(row, *names):
    for name in names:
        value = row.get(name) if isinstance(row, dict) else None
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def split_values(value):
    value = str(value or "").strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in re.split(r"\s*[|;]\s*", value) if item.strip()]


def clean_heading(value, fallback="Untitled"):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value or fallback


def markdown_literal(value):
    """Keep untrusted conversation text from becoming Markdown or URL syntax."""
    value = html.escape(str(value or ""), quote=False)
    for character in ("\\", "`", "*", "_", "[", "]", "(", ")"):
        value = value.replace(character, "\\" + character)
    return value


def safe_csv_value(value):
    """Prevent spreadsheet apps from interpreting a readable cell as a formula."""
    value = "" if value is None else str(value)
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


def format_time(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except (OverflowError, OSError, ValueError):
            return value
    return value.replace("T", " ").replace("Z", " UTC", 1)


def date_part(value):
    formatted = format_time(value)
    match = re.match(r"(\d{4}-\d{2}-\d{2})", formatted)
    return match.group(1) if match else "Undated"


def sort_key(row):
    return (
        pick(row, "timestamp", "first_seen", "sent_at_local", "sent_at_utc", "sendDttm"),
        pick(row, "sequence", "message_id", "msg_id", "msgId"),
    )


def find_input(root, name, source=False):
    primary = root / ("source" if source else "raw") / name
    if primary.exists():
        return primary
    legacy = root / (SOURCE_MIRRORS if source else RAW_MIRRORS).get(name, "")
    return legacy if legacy.exists() else None


def mirror_inputs(root):
    raw_dir = root / "raw"
    source_dir = root / "source"
    raw_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    mirrored = []
    for name, legacy_name in RAW_MIRRORS.items():
        destination = raw_dir / name
        legacy = root / legacy_name
        if not destination.exists() and legacy.is_file() and not legacy.is_symlink():
            try:
                legacy.resolve().relative_to(root)
            except ValueError:
                continue
            copy_legacy_input(legacy, destination)
            mirrored.append(str(destination.relative_to(root)))
    for name, legacy_name in SOURCE_MIRRORS.items():
        destination = source_dir / name
        legacy = root / legacy_name
        if not destination.exists() and legacy.is_file() and not legacy.is_symlink():
            try:
                legacy.resolve().relative_to(root)
            except ValueError:
                continue
            shutil.copy2(legacy, destination)
            mirrored.append(str(destination.relative_to(root)))
    info_path = source_dir / "source-info.json"
    if not info_path.exists():
        info_path.write_text(
            json.dumps(
                {
                    "layout_version": 2,
                    "raw_policy": "raw files are machine-readable audit inputs; do not edit them",
                    "legacy_layout_mirrored": bool(mirrored),
                    "mirrored_files": mirrored,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return mirrored


def copy_legacy_input(legacy, destination):
    """Mirror legacy data while removing signed internal media query strings."""
    if legacy.suffix.lower() != ".csv":
        shutil.copy2(legacy, destination)
        return
    with legacy.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            fields = next(reader)
        except StopIteration:
            shutil.copy2(legacy, destination)
            return
        rows = list(reader)
        url_indexes = [
            index for index, field in enumerate(fields)
            if "url" in field.lower() or "link" in field.lower()
        ]
        if not url_indexes:
            shutil.copy2(legacy, destination)
            return
        has_signed_media = any(
            has_signed_internal_media_query(row[index])
            for row in rows for index in url_indexes if index < len(row)
        )
        if not has_signed_media:
            shutil.copy2(legacy, destination)
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(fields)
            for row in rows:
                for index in url_indexes:
                    if index < len(row):
                        row[index] = redact_internal_media_url(row[index])
                writer.writerow(row)


def safe_http_url(value):
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def manifest_value(manifest, keys):
    if not isinstance(manifest, dict):
        return ""
    for key in keys:
        if manifest.get(key) not in (None, "", []):
            return str(manifest[key])
    for value in manifest.values():
        if isinstance(value, dict):
            found = manifest_value(value, keys)
            if found:
                return found
    return ""


def url_title(row):
    context = pick(row, "context_name", "context_summary")
    if context and context.lower() not in {"uncategorized", "unknown"}:
        return clean_heading(context, "Link")[:140]
    url = pick(row, "url", "canonical_url")
    try:
        parsed = urlsplit(url)
        return clean_heading((parsed.netloc + parsed.path).strip("/"), "Link")[:140]
    except ValueError:
        return clean_heading(url, "Link")[:140]


def markdown_table(value):
    return markdown_literal(re.sub(r"[\r\n]+", " ", str(value or ""))).replace("|", "\\|").strip()


def markdown_quote(value):
    lines = str(value or "").splitlines() or ["_(no text)_"]
    return "\n".join("> " + markdown_literal(line) for line in lines)


def message_text(row):
    return pick(row, "text", "msgText", "content", "message", "body")


def message_sender(row):
    return clean_heading(pick(row, "sender_name", "sender", "senderName", "author"), "Unknown sender")


def render_messages(rows, title, manifest):
    lines = [f"# {title}", "", "> Human-readable conversation view", ""]
    if not rows:
        return "\n".join(lines + ["No normalized message CSV was found.", ""])
    rows = sorted(rows, key=sort_key)
    lines.extend([f"**Messages:** {len(rows)}", "", "---", ""])
    current_date = None
    for row in rows:
        day = date_part(pick(row, "timestamp", "sent_at_local", "sent_at_utc", "sendDttm"))
        if day != current_date:
            lines.extend([f"## {day}", ""])
            current_date = day
        time = format_time(pick(row, "timestamp", "sent_at_local", "sent_at_utc", "sendDttm"))
        time = time.split(" ", 1)[1] if " " in time else time
        heading = f"{time} — {message_sender(row)}" if time else message_sender(row)
        lines.extend([f"### {markdown_literal(heading)}", ""])
        kind = pick(row, "message_type", "type", "msgType")
        if kind and kind.lower() not in {"text", "normal", "1"}:
            lines.append(f"> _[{kind}]_")
        quote = pick(row, "quote_text", "quote", "reference_text")
        if quote:
            lines.append(f"> ↪ {markdown_literal(quote.replace(chr(10), ' '))}")
        lines.append(markdown_quote(message_text(row)))
        attachment = pick(row, "attachment_name", "original_name", "file_name", "filename")
        if attachment:
            lines.append(f"> 📎 {markdown_literal(attachment)}")
        lines.append("")
    return "\n".join(lines)


def link_card(row):
    url = pick(row, "url", "canonical_url")
    category = safe_category_slug(pick(row, "category"))
    confidence = pick(row, "confidence") or "unknown"
    count = pick(row, "occurrence_count") or "1"
    first_seen = format_time(pick(row, "first_seen", "timestamp"))
    last_seen = format_time(pick(row, "last_seen"))
    sources = ", ".join(split_values(pick(row, "sources", "source"))) or "message"
    context = pick(row, "context_summary")
    if is_internal_media_url(url):
        redacted_url = redact_internal_media_url(url)
        link_line = f"**Zalo media URL:** redacted (signed query omitted) `{markdown_literal(redacted_url)}`"
    elif safe_http_url(url):
        link_line = f"[Open link](<{url}>)"
    else:
        link_line = "**URL:** unavailable or invalid"
    lines = [f"### {markdown_literal(url_title(row))}", link_line, ""]
    lines.append(f"- **Category:** `{category}` · **Confidence:** `{confidence}`")
    lines.append(f"- **Shared:** {count} time(s) · **Source:** {markdown_literal(sources)}")
    if first_seen:
        seen = first_seen if not last_seen or last_seen == first_seen else f"{first_seen} → {last_seen}"
        lines.append(f"- **Seen:** {seen}")
    if context:
        lines.append(f"- **Context:** {markdown_literal(context)}")
    alternatives = pick(row, "context_alternatives")
    if alternatives:
        lines.append(f"- **Needs attention:** {markdown_literal(alternatives)}")
    lines.append("")
    return lines


def render_links(rows, title="Links"):
    lines = [f"# {title}", "", "> One readable row per exact URL; repeated shares stay in the count.", ""]
    if not rows:
        return "\n".join(lines + ["No classified links were found.", ""])
    groups = defaultdict(list)
    for row in sorted(rows, key=sort_key):
        groups[pick(row, "category") or "other"].append(row)
    lines.append(f"**Links:** {len(rows)}")
    lines.append("")
    for category in sorted(groups):
        label = CATEGORY_LABELS.get(category, category.replace("-", " ").title())
        lines.extend([f"## {label} ({len(groups[category])})", ""])
        for row in groups[category]:
            lines.extend(link_card(row))
    return "\n".join(lines)


def render_media(rows, root):
    lines = ["# Attachments", "", "> Binary files are listed here; GIFs and stickers are skipped by policy.", ""]
    if not rows:
        return "\n".join(lines + ["No attachment records were found.", ""])
    lines.extend(["| When | Sender | Type | File | Status |", "|---|---|---|---|---|"])
    for row in sorted(rows, key=sort_key):
        relative = pick(row, "relative_output_path", "output_path")
        file_label = pick(row, "original_name", "filename", "type") or "(unnamed)"
        safe_file_label = markdown_literal(file_label)
        status = pick(row, "status") or "unknown"
        saved_status = status in {"copied", "downloaded", "preview_only"}
        if saved_status and contained_attachment(root, relative):
            file_label = f"[{safe_file_label}](../{relative})"
        else:
            file_label = safe_file_label
        lines.append("| " + " | ".join([
            markdown_table(format_time(pick(row, "timestamp", "sent_at_local"))),
            markdown_table(pick(row, "sender", "sender_name") or "Unknown"),
            markdown_table(pick(row, "type", "message_type") or "file"),
            file_label.replace("|", "\\|"),
            markdown_table(status),
        ]) + " |")
    return "\n".join(lines + [""])


def render_review(rows):
    lines = ["# Review queue", "", "> Only unresolved link classifications appear here.", ""]
    if not rows:
        return "\n".join(lines + ["No unresolved review rows.", ""])
    for row in rows:
        lines.extend(link_card(row))
        reasons = pick(row, "review_reasons")
        if reasons:
            lines.insert(len(lines) - 1, f"- **Review reason:** {markdown_literal(reasons)}")
    return "\n".join(lines)


def render_index(root, title, messages, links, occurrences, attachments, review, manifest):
    link_manifest = manifest.get("links", {}) if isinstance(manifest, dict) else {}
    status = manifest.get("exportStatus", "UNKNOWN") if isinstance(manifest, dict) else "UNKNOWN"
    raw_count = link_manifest.get("rawOccurrenceRows", len(occurrences))
    lines = [f"# {title}", "", "> Human-first index for this Zalo export.", ""]
    lines.extend([
        f"- **Status:** `{status}`",
        f"- **Messages:** {len(messages)}",
        f"- **Readable links:** {len(links)}",
        f"- **Raw link occurrences:** {raw_count}",
        f"- **Attachment records:** {len(attachments)}",
        f"- **Unresolved review rows:** {len(review)}",
        "",
        "## Read first",
        "",
        "- [Conversation](messages.md)",
        "- [Links](links.md)",
        "- [Link table](links.csv)",
        "- [Attachments](media.md)",
        "- [Attachment table](media.csv)",
        "- [Review queue](review.md)",
        "- [Review table](review.csv)",
        "",
        "## Storage layers",
        "",
        "- `readable/` — Markdown views for people plus curated CSV tables for filtering.",
        "- `raw/` — machine-readable copies used for audit; do not edit.",
        "- `source/` — manifest and provenance for this extraction.",
        "",
        "## Notes",
        "",
        "The archive keeps original records in the raw layer while the readable layer groups messages by day and presents links by category. A `PARTIAL` status is an honest limitation report, not a silent omission.",
        "",
    ])
    return "\n".join(lines)


def build(root):
    root = root.resolve()
    metadata = root / "source" if (root / "source" / "manifest.json").exists() else root / "03-reports"
    assert_source_read_only(root, metadata)
    mirrored = mirror_inputs(root)
    readable = root / "readable"
    category_dir = readable / "links-by-category"
    readable.mkdir(parents=True, exist_ok=True)
    category_dir.mkdir(parents=True, exist_ok=True)

    manifest = read_json(find_input(root, "manifest.json", source=True))
    title = clean_heading(
        manifest_value(manifest, ("conversation_name", "conversationName", "group_name", "groupName", "title")),
        "Zalo conversation",
    )
    messages = read_csv(find_input(root, "messages.csv"))
    links = read_csv(find_input(root, "links.csv"))
    occurrences = read_csv(find_input(root, "links-classified-occurrences.csv"))
    if not occurrences:
        occurrences = read_csv(find_input(root, "links-occurrences.csv"))
    attachments = read_csv(find_input(root, "attachments.csv"))
    review = read_csv(find_input(root, "link-review.csv"))

    (readable / "index.md").write_text(render_index(root, title, messages, links, occurrences, attachments, review, manifest), encoding="utf-8")
    (readable / "messages.md").write_text(render_messages(messages, title, manifest), encoding="utf-8")
    (readable / "links.md").write_text(render_links(links), encoding="utf-8")
    (readable / "media.md").write_text(render_media(attachments, root), encoding="utf-8")
    (readable / "review.md").write_text(render_review(review), encoding="utf-8")
    write_table_csv(
        readable / "links.csv",
        links,
        [
            "sequence", "category", "context_name", "url", "occurrence_count",
        ],
    )
    write_table_csv(
        readable / "media.csv",
        attachments,
        [
            "sequence", "type", "original_name", "relative_output_path", "status",
        ],
    )
    write_table_csv(
        readable / "review.csv",
        review,
        [
            "sequence", "url", "category", "confidence", "context_name", "review_reasons",
        ],
    )
    for path in category_dir.glob("*.md"):
        path.unlink()
    for path in category_dir.glob("*.csv"):
        path.unlink()
    grouped = defaultdict(list)
    for row in links:
        grouped[safe_category_slug(pick(row, "category"))].append(row)
    for category, rows in sorted(grouped.items()):
        (category_dir / f"{category}.md").write_text(
            render_links(rows, CATEGORY_LABELS.get(category, category.replace("-", " ").title())),
            encoding="utf-8",
        )
        write_table_csv(
            category_dir / f"{category}.csv",
            rows,
            [
                "sequence", "category", "context_name", "url", "occurrence_count",
            ],
        )
    return {
        "title": title,
        "messages": len(messages),
        "links": len(links),
        "occurrences": len(occurrences),
        "attachments": len(attachments),
        "review": len(review),
        "mirrored_raw_files": len(mirrored),
        "output": str(readable),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.export_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
