#!/usr/bin/env python3
"""Build human-readable Markdown views from a ZL Extractor export.

The renderer is non-destructive: it mirrors legacy machine-readable files into
``source/raw/`` only when the canonical copy does not already exist, then
writes views to ``readable/``. It never edits the source DB or legacy files.
"""

import argparse
import csv
import html
import json
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from export_paths import (
    assert_source_read_only,
    contained_attachment,
    export_paths,
    has_signed_internal_media_query,
    is_internal_media_url,
    redact_internal_media_url,
    safe_category_slug,
)
from url_rules import find_urls, is_bare_url, parseable_url, strip_urls
from time_order import message_id_key, timestamp_sort_key


CATEGORY_LABELS = {
    "shopee-affiliate": "Shopee / affiliate",
    "training-guide": "Training / guides",
    "tool-platform": "Tools / platforms",
    "social-community": "Social / communities",
    "tracking-redirect": "Tracking / redirects",
    "other": "Other",
}

# Tie-break links that share a platform family and timestamp.
CATEGORY_PRIORITY = {
    "shopee-affiliate": 0,
    "training-guide": 1,
    "tool-platform": 2,
    "social-community": 3,
    "tracking-redirect": 4,
    "other": 5,
}

DISPLAY_TIMEZONE = ZoneInfo(os.environ.get("ZL_DISPLAY_TIMEZONE", "Asia/Ho_Chi_Minh"))

RAW_MIRRORS = {
    "messages.csv": "01-messages/messages.csv",
    "pins.csv": "03-reports/pins.csv",
    "messages.txt": "01-messages/messages.txt",
    "links.csv": "01-messages/links.csv",
    "links-occurrences.csv": "03-reports/links-occurrences.csv",
    "zalo-media-links.csv": "03-reports/zalo-media-links.csv",
    "attachments.csv": "03-reports/attachments.csv",
    "link-review.csv": "03-reports/link-review.csv",
    "link-review-resolutions.csv": "03-reports/link-review-resolutions.csv",
}

SOURCE_MIRRORS = {
    "manifest.json": "03-reports/manifest.json",
    "link-archive-audit.json": "03-reports/link-archive-audit.json",
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
            return datetime.fromtimestamp(timestamp, tz=DISPLAY_TIMEZONE).strftime("%Y-%m-%d %H:%M %Z")
        except (OverflowError, OSError, ValueError):
            return value
    return value.replace("T", " ").replace("Z", " UTC", 1)


def date_part(value):
    formatted = format_time(value)
    match = re.match(r"(\d{4}-\d{2}-\d{2})", formatted)
    return match.group(1) if match else "Undated"


def sort_key(row):
    return (
        timestamp_sort_key(pick(row, "timestamp", "first_seen", "sent_at_local", "sent_at_utc", "sendDttm")),
        message_id_key(pick(row, "sequence", "message_id", "msg_id", "msgId")),
    )


def find_input(root, name, source=False):
    paths = export_paths(root)
    primary = (paths["metadata"] if source else paths["machine"]) / name
    if primary.exists():
        return primary
    legacy = root / (SOURCE_MIRRORS if source else RAW_MIRRORS).get(name, "")
    return legacy if legacy.exists() else None


def mirror_inputs(root):
    paths = export_paths(root)
    if paths["new_layout"]:
        raw_dir = paths["machine"]
        source_dir = paths["metadata"]
    else:
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
    if mirrored and not info_path.exists():
        info_path.write_text(
            json.dumps(
                {
                    "layout_version": 2,
                    "raw_policy": "source/raw files are machine-readable audit inputs; do not edit them",
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
        parsed = urlsplit(parseable_url(value))
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def display_url(value):
    value = str(value or "").strip()
    return parseable_url(value) if is_bare_url(value) else value


def human_context(value):
    text = html.unescape(str(value or ""))
    if text.strip().lower() in {"[object object]", "undefined", "null"}:
        return ""
    text = strip_urls(text)
    text = re.sub(r"[*_`~]+", "", text)
    text = re.sub(r"\\([\\[\\]\\(\\)])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip(" |:,-")
    if re.fullmatch(r"[@#][\wÀ-ỹ ._-]+", text):
        return ""
    return text[:200] if len(text) >= 8 else ""


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
    url = pick(row, "url", "canonical_url")
    try:
        parsed = urlsplit(parseable_url(url))
        label = (parsed.netloc + parsed.path).strip("/")
        return clean_heading(label, "Link")[:120]
    except ValueError:
        return clean_heading(url, "Link")[:140]


def link_family_key(row):
    """Group equivalent platforms before applying the date sort."""
    url = pick(row, "url", "canonical_url")
    try:
        parsed = urlsplit(parseable_url(url))
        host = (parsed.hostname or parsed.netloc).lower().removeprefix("www.")
        path = parsed.path.lower()
    except ValueError:
        return url.lower()

    if host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com"):
        return "youtube"
    if host.endswith("facebook.com") or host == "fb.watch":
        return "facebook"
    if host.endswith("tiktok.com"):
        return "tiktok"
    if host in {"t.me", "telegram.me"} or host.endswith(".telegram.org"):
        return "telegram"
    if host == "labs.google" and re.match(r"^/fx/(?:[^/]+/)?tools/flow(?:/|$)", path):
        return "labs.google/fx/tools/flow"
    if host == "docs.google.com":
        return "google/docs"
    if host == "drive.google.com":
        return "google/drive"
    if host == "gemini.google.com":
        return "google/gemini"
    if host == "chromewebstore.google.com":
        return "chrome-web-store"
    if host == "chatgpt.com":
        return "chatgpt"
    if not host:
        return "unknown"
    labels = host.split(".")
    return labels[-2] if len(labels) >= 3 else labels[0]


def link_sort_key(row):
    category = safe_category_slug(pick(row, "category"))
    url = pick(row, "url", "canonical_url")
    try:
        parsed = urlsplit(parseable_url(url))
        label = (parsed.netloc + parsed.path).lower()
    except ValueError:
        label = url.lower()
    return (
        link_family_key(row),
        timestamp_sort_key(pick(row, "first_seen", "timestamp")),
        CATEGORY_PRIORITY.get(category, len(CATEGORY_PRIORITY)),
        message_id_key(pick(row, "sequence", "message_id", "msg_id", "msgId")),
        label,
    )


def markdown_table(value):
    return markdown_literal(re.sub(r"[\r\n]+", " ", str(value or ""))).replace("|", "\\|").strip()


def markdown_quote(value):
    lines = str(value or "").splitlines() or ["_(no text)_"]
    return "\n".join("> " + markdown_literal(line) for line in lines)


def message_text(row):
    return pick(row, "text", "msgText", "content", "message", "body")


def message_sender(row):
    return clean_heading(pick(row, "sender_name", "sender", "senderName", "author"), "")


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
        sender = message_sender(row)
        heading = f"{time} — {sender}" if time and sender else sender or time or "Message"
        lines.extend([f"### {markdown_literal(heading)}", ""])
        kind = pick(row, "message_type", "msg_type", "type", "msgType")
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


def link_card(row, number=None):
    url = pick(row, "url", "canonical_url")
    category = safe_category_slug(pick(row, "category"))
    confidence = pick(row, "confidence") or "unknown"
    count = pick(row, "occurrence_count") or "1"
    first_seen = format_time(pick(row, "first_seen", "timestamp"))
    last_seen = format_time(pick(row, "last_seen"))
    sources = ", ".join(split_values(pick(row, "sources", "source"))) or "message"
    context = pick(row, "context_summary")
    if is_internal_media_url(url):
        link_line = "**Zalo media:** internal attachment; binary was not requested"
    elif safe_http_url(url):
        link_line = f"[Open link](<{display_url(url)}>)"
    else:
        link_line = "**URL:** unavailable or invalid"
    heading = url_title(row)
    if number is not None:
        heading = f"{number:02d}. {heading}"
    lines = [f"### {markdown_literal(heading)}", link_line, ""]
    lines.append(f"- **Category:** `{category}` · **Confidence:** `{confidence}`")
    lines.append(f"- **Shared:** {count} time(s) · **Source:** {markdown_literal(sources)}")
    if first_seen:
        seen = first_seen if not last_seen or last_seen == first_seen else f"{first_seen} → {last_seen}"
        lines.append(f"- **Seen:** {seen}")
    context = human_context(context)
    if context:
        lines.append(f"- **Context:** {markdown_literal(context)}")
    alternatives = human_context(pick(row, "context_alternatives"))
    if alternatives:
        lines.append(f"- **Needs attention:** {markdown_literal(alternatives)}")
    lines.append("")
    return lines


def link_review_status(row):
    confidence = pick(row, "confidence").lower()
    alternatives = pick(row, "context_alternatives", "review_reasons")
    return "review" if confidence == "low" or alternatives else "ok"


def readable_link_row(row):
    readable = dict(row, review_status=link_review_status(row))
    readable["first_seen"] = format_time(pick(row, "first_seen", "timestamp"))
    return readable


def link_table_row(row, number):
    url = pick(row, "url", "canonical_url")
    if is_internal_media_url(url):
        link = "_(internal media)_"
    elif safe_http_url(url):
        shown = markdown_literal(display_url(url))
        link = f"[{shown}](<{display_url(url)}>)"
    else:
        link = markdown_table(url) or "_(unavailable)_"
    category = CATEGORY_LABELS.get(safe_category_slug(pick(row, "category")), "Other")
    return "| " + " | ".join([
        str(number),
        link,
        markdown_table(category),
        markdown_table(pick(row, "occurrence_count") or "1"),
        markdown_table(format_time(pick(row, "first_seen", "timestamp"))),
        link_review_status(row),
    ]) + " |"


def render_links(rows, title="Links"):
    lines = [f"# {title}", "", "> One compact table row per exact URL; repeated shares stay in the count.", ""]
    if not rows:
        return "\n".join(lines + ["No classified links were found.", ""])
    lines.append(f"**Links:** {len(rows)}")
    lines.extend([
        "",
        "| STT | Link | Phân loại | Số lần | Thời gian gửi đầu tiên | Review |",
        "|---:|---|---|---:|---|---|",
    ])
    for number, row in enumerate(sorted(rows, key=link_sort_key), 1):
        lines.append(link_table_row(row, number))
    return "\n".join(lines)


def render_media(rows, root):
    lines = ["# Attachments", "", "> Binary files are listed here; GIFs and stickers are skipped by policy.", ""]
    if not rows:
        return "\n".join(lines + ["No downloaded attachment records were found.", "Internal Zalo media references, if any, are listed separately in `pins.md`.", ""])
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


def render_pins(rows):
    lines = ["# Pinned records", "", "> Pinned records are shown separately from the chronological message link list.", ""]
    if not rows:
        return "\n".join(lines + ["No normalized pinned records were found.", ""])
    lines.extend([f"**Pinned records:** {len(rows)}", ""])
    for index, row in enumerate(sorted(rows, key=sort_key), 1):
        urls = find_urls("\n".join(pick(row, field) for field in ("title", "text", "url", "urls")))
        title = human_context(pick(row, "title", "text"))
        if not title:
            title = next((url_title({"url": url}) for url in urls if not is_internal_media_url(url)), "Pinned item")
        lines.extend([f"## {index}. {markdown_literal(title)}", ""])
        when = format_time(pick(row, "timestamp"))
        sender = pick(row, "sender")
        if when or sender:
            lines.append(f"- **When:** {markdown_literal(when or 'Unknown time')} · **Sender:** {markdown_literal(sender or 'Unknown sender')}")
        scope = pick(row, "message_scope")
        if scope == "pin_outside_message_window":
            lines.append("- **Scope:** Pinned record outside the chronological message window")
        elif scope == "pin_window_unknown":
            lines.append("- **Scope:** Pinned record; message-window relation unknown")
        body = human_context(pick(row, "text"))
        if body:
            lines.append(f"- **Context:** {markdown_literal(body)}")
        external_urls = [url for url in urls if not is_internal_media_url(url)]
        media_urls = [url for url in urls if is_internal_media_url(url)]
        lines.append(f"- **External links:** {len(external_urls)}")
        for url in external_urls:
            if safe_http_url(url):
                lines.append(f"  - [{markdown_literal(url)}](<{display_url(url)}>)")
            else:
                lines.append(f"  - `{markdown_literal(url)}`")
        if media_urls:
            lines.append(f"- **Internal Zalo media references:** {len(media_urls)} (not exported)")
        if not external_urls and not media_urls:
            lines.append("- **Links:** none detected")
        lines.append("")
    return "\n".join(lines)


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


def render_index(root, title, messages, links, occurrences, pins, attachments, review, manifest):
    link_manifest = manifest.get("links", {}) if isinstance(manifest, dict) else {}
    status = manifest.get("exportStatus", "UNKNOWN") if isinstance(manifest, dict) else "UNKNOWN"
    raw_count = link_manifest.get("rawOccurrenceRows", len(occurrences))
    source = manifest.get("source", {}) if isinstance(manifest, dict) else {}
    link_archive = read_json(find_input(root, "link-archive-audit.json", source=True))
    archive_count = link_archive.get("reportedCardCount", link_archive.get("reportedLinkCount"))
    archive_status = str(link_archive.get("status") or "").strip().lower()
    source_start = source.get("startAt") or ""
    source_end = source.get("endAt") or ""
    source_counts = defaultdict(int)
    pin_external_urls = set()
    pin_external_occurrences = 0
    pin_media_occurrences = 0
    for row in occurrences:
        sources = split_values(pick(row, "source") or "unknown")
        if is_internal_media_url(pick(row, "url")):
            if "pin" in sources:
                pin_media_occurrences += 1
            continue
        for source_name in sources:
            source_counts[source_name] += 1
        if "pin" in sources:
            pin_external_occurrences += 1
            pin_external_urls.add(pick(row, "url"))
    scope = source_start or source_end or "all available messages"
    if source_start and source_end:
        scope = f"{source_start} → {source_end}"
    elif source_start:
        scope = f"from {source_start}"
    elif source_end:
        scope = f"through {source_end}"
    warnings = []
    if link_manifest.get("pinAuditStatus") not in {"complete", "complete_with_zero_links"} or link_manifest.get("pinAuditCompleteness") not in {"complete", "complete_with_zero_links"}:
        warnings.append("Pin coverage is not proven complete; compare `pins.md` with Zalo before treating the link total as final.")
    if review:
        warnings.append(f"{len(review)} link(s) need classification review.")
    if archive_count is None and not link_manifest.get("linkArchiveCount"):
        warnings.append("Zalo's Link archive was not enumerated by the runtime; compare its visible count before treating coverage as final.")
    elif archive_status not in {"complete", "verified"}:
        warnings.append("The Zalo Link archive count is observed but not reconciled to exported rows.")
    lines = [f"# {title}", "", "> Human-first index for this Zalo export.", ""]
    lines.extend([
        f"- **Status:** `{status}`",
        f"- **Message scope:** `{scope}`",
        f"- **Messages:** {len(messages)}",
        f"- **User-facing unique links:** {len(links)}",
        *([f"- **Zalo Link archive cards:** {archive_count} (`{archive_status or 'observed'}`)"] if archive_count is not None else []),
        f"- **All exact unique URLs:** {link_manifest.get('allExactUniqueUrls', len(links))}",
        f"- **Raw link occurrences:** {raw_count}",
        f"- **Message external-link occurrences:** {source_counts.get('message', 0)}",
        f"- **Link-archive external-link occurrences:** {source_counts.get('link_archive', 0)}",
        f"- **Pinned external-link occurrences:** {pin_external_occurrences}",
        f"- **Pinned internal-media references:** {pin_media_occurrences}",
        f"- **Pinned records:** {link_manifest.get('enumeratedPinCount', len(pins))}",
        f"- **Pinned external unique URLs:** {len(pin_external_urls)}",
        f"- **Attachment records:** {len(attachments)}",
        f"- **Unresolved review rows:** {len(review)}",
        "",
        "## Read first",
        "",
        "- [Conversation](messages.md)",
        "- [Link table](links.csv)",
        "- [Pinned links](pins.md)",
        *(["- [Attachment table](media.csv)"] if attachments else []),
        *(["- [Review table](review.csv)"] if review else []),
        "",
        "## Storage layers",
        "",
        "- `readable/` — Markdown views for people plus curated CSV tables for filtering.",
        "- `source/raw/` — machine-readable copies used for audit; do not edit.",
        "- `source/` — manifest, provenance, raw inputs, and attachments for this extraction.",
        "",
        "## Warnings",
        "",
        *(warnings or ["None."]),
        "",
        "## Notes",
        "",
        "The archive keeps original records in the raw layer while the readable layer groups messages by day, separates pinned links, and presents one compact row per unique link. A `PARTIAL` status is an honest limitation report, not a silent omission.",
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
    if (root / "source" / "manifest.json").exists():
        for stale_path in (root / "source" / "source-info.json", root / "source" / "link-classification.json", readable / "link-reconciliation.md"):
            if stale_path.exists():
                stale_path.unlink()
    for stale_name in ("links.md", "media.md", "review.md"):
        stale_path = readable / stale_name
        if stale_path.exists():
            stale_path.unlink()
    if category_dir.exists():
        for stale_path in category_dir.iterdir():
            if stale_path.is_file() and stale_path.suffix in {".md", ".csv"}:
                stale_path.unlink()
        try:
            category_dir.rmdir()
        except OSError:
            pass

    manifest = read_json(find_input(root, "manifest.json", source=True))
    title = clean_heading(
        manifest_value(manifest, ("conversation_name", "conversationName", "group_name", "groupName", "title")),
        "Zalo conversation",
    )
    messages = read_csv(find_input(root, "messages.csv"))
    pins = read_csv(find_input(root, "pins.csv"))
    links = read_csv(find_input(root, "links.csv"))
    occurrences = read_csv(find_input(root, "links-occurrences.csv"))
    attachments = read_csv(find_input(root, "attachments.csv"))
    review = read_csv(find_input(root, "link-review.csv"))
    readable_links = []
    for number, row in enumerate(sorted(links, key=link_sort_key), 1):
        readable_row = readable_link_row(row)
        readable_row["sequence"] = f"{number:06d}"
        readable_links.append(readable_row)

    (readable / "index.md").write_text(render_index(root, title, messages, links, occurrences, pins, attachments, review, manifest), encoding="utf-8")
    (readable / "messages.md").write_text(render_messages(messages, title, manifest), encoding="utf-8")
    (readable / "pins.md").write_text(render_pins(pins), encoding="utf-8")
    write_table_csv(
        readable / "links.csv",
        readable_links,
        [
            "sequence", "url", "category", "occurrence_count", "first_seen", "review_status",
        ],
    )
    optional_tables = {
        "media.csv": (attachments, ["sequence", "type", "original_name", "relative_output_path", "status"]),
        "review.csv": (review, ["sequence", "url", "category", "confidence", "context_name", "review_reasons"]),
    }
    for name, (rows, fields) in optional_tables.items():
        output = readable / name
        if rows:
            write_table_csv(output, rows, fields)
        elif output.exists():
            output.unlink()
    return {
        "title": title,
        "messages": len(messages),
        "links": len(links),
        "occurrences": len(occurrences),
        "pins": len(pins),
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
