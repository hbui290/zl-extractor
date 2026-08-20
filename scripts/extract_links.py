#!/usr/bin/env python3
"""Extract, classify, and exact-merge URLs from normalized messages and pins."""

import argparse
import csv
import json
import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from apply_category_rules import category_rule
from export_paths import (
    assert_source_read_only,
    export_paths,
    redact_internal_media_url,
    safe_category_slug,
)


URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
OCCURRENCE_FIELDS = [
    "sequence", "message_id", "pin_id", "timestamp", "sender", "source",
    "context_name", "context_summary", "category", "original_category",
    "classification_rule", "observed_categories", "confidence", "url",
    "canonical_url",
]
PRIMARY_FIELDS = [
    "sequence", "message_id", "message_ids", "pin_id", "pin_ids", "timestamp",
    "first_seen", "last_seen", "sender", "senders", "source", "sources",
    "category", "original_category", "classification_rule", "observed_categories",
    "context_name", "context_alternatives", "context_summary", "confidence",
    "occurrence_count", "url", "canonical_url",
]


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _pick(row, *fields):
    for field in fields:
        value = str(row.get(field, "") or "").strip()
        if value:
            return value
    return ""


def _unique(values):
    return list(OrderedDict.fromkeys(value for value in values if value))


def _clean_url(value):
    return str(value or "").strip()


def _trim_match(value):
    """Remove sentence punctuation without changing a dedicated URL field."""
    text = _clean_url(value)
    while text and text[-1] in ".,;:!?":
        text = text[:-1]
    for closing, opening in ((")", "("), ("]", "["), ("}", "{")):
        while text.endswith(closing) and text.count(closing) > text.count(opening):
            text = text[:-1]
    return text


def _redact_context(value):
    def replace(match):
        token = match.group(0)
        clean = _trim_match(token)
        suffix = token[len(clean):]
        return redact_internal_media_url(clean) + suffix

    return URL_RE.sub(replace, str(value or ""))


def _context(row, source):
    name = _pick(row, "context_name", "title", "subject", "name")
    summary = " | ".join(_unique(
        str(row.get(field, "") or "").strip()
        for field in ("context_summary", "text", "message", "content", "description", "caption", "quote_text", "quote", "reference_text", "reference", "url", "urls")
    ))
    summary = _redact_context(re.sub(r"\s+", " ", summary).strip())
    name = _redact_context(name)
    if not name and summary:
        name = summary[:140]
    if not name:
        name = "Pinned item" if source == "pin" else "Shared link"
    return name[:140], summary[:500]


def _scan_fields(row, source):
    if source == "pin":
        values = [str(value) for key, value in row.items() if key and value and (
            any(token in key.lower() for token in ("url", "link", "text", "title", "content", "description", "caption"))
        )]
    else:
        fields = ("text", "message", "content", "quote_text", "quote", "reference_text", "reference", "url", "link")
        values = [str(row.get(field, "")) for field in fields if row.get(field)]
    return _unique(values)


def _occurrences(rows, source):
    result = []
    for row in rows:
        message_id = _pick(row, "message_id", "msg_id", "msgId", "id") if source == "message" else _pick(row, "message_id", "msg_id", "msgId", "source_message_id")
        pin_id = _pick(row, "pin_id", "pinId", "id") if source == "pin" else ""
        timestamp = _pick(row, "timestamp", "sendDttm", "send_time", "sent_at", "time")
        sender = _pick(row, "sender", "sender_name", "from_name")
        context_name, context_summary = _context(row, source)
        seen_pin_urls = set()
        for field_value in _scan_fields(row, source):
            for match in URL_RE.findall(field_value):
                url = _trim_match(match)
                if not url:
                    continue
                if source == "pin" and url in seen_pin_urls:
                    continue
                seen_pin_urls.add(url)
                safe_url = redact_internal_media_url(url)
                category, rule = category_rule(safe_url)
                category = safe_category_slug(category or "other")
                result.append({
                    "sequence": "",
                    "message_id": message_id,
                    "pin_id": pin_id,
                    "timestamp": timestamp,
                    "sender": sender,
                    "source": source,
                    "context_name": context_name,
                    "context_summary": context_summary,
                    "category": category,
                    "original_category": category,
                    "classification_rule": rule,
                    "observed_categories": category,
                    "confidence": "high" if category != "other" else "low",
                    "url": safe_url,
                    "canonical_url": safe_url,
                    "_field_sequence": len(result),
                })
    return result


def _time_key(value):
    value = str(value or "").strip()
    try:
        number = float(value)
        if abs(number) < 100_000_000_000:
            number *= 1000
        return (0, number)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (1, parsed.timestamp())
    except ValueError:
        return (2, value)


def _merge(url, rows):
    message_ids = _unique([row["message_id"] for row in rows])
    pin_ids = _unique([row["pin_id"] for row in rows])
    senders = _unique([row["sender"] for row in rows])
    sources = _unique([row["source"] for row in rows])
    timestamps = sorted([row["timestamp"] for row in rows if row["timestamp"]], key=_time_key)
    contexts = _unique([row["context_name"] for row in rows])
    summaries = _unique([row["context_summary"] for row in rows])
    first = rows[0]
    category = first["category"]
    return {
        "sequence": "",
        "message_id": message_ids[0] if message_ids else "",
        "message_ids": "|".join(message_ids),
        "pin_id": pin_ids[0] if pin_ids else "",
        "pin_ids": "|".join(pin_ids),
        "timestamp": timestamps[0] if timestamps else "",
        "first_seen": timestamps[0] if timestamps else "",
        "last_seen": timestamps[-1] if timestamps else "",
        "sender": senders[0] if senders else "",
        "senders": "|".join(senders),
        "source": "|".join(sources),
        "sources": "|".join(sources),
        "category": category,
        "original_category": first["original_category"],
        "classification_rule": first["classification_rule"],
        "observed_categories": "|".join(_unique([row["category"] for row in rows])),
        "context_name": contexts[0] if contexts else "Shared link",
        "context_alternatives": "|".join(contexts[1:]),
        "context_summary": " | ".join(summaries[:3]),
        "confidence": "high" if category != "other" else "low",
        "occurrence_count": str(len(rows)),
        "url": url,
        "canonical_url": url,
        "_first_sequence": int(rows[0].get("sequence") or 0),
    }


def extract_links(root):
    root = Path(root).resolve()
    paths = export_paths(root)
    assert_source_read_only(root, paths["metadata"])
    machine = paths["machine"]
    occurrence_root = machine if paths["new_layout"] else paths["metadata"]
    messages_path = machine / "messages.csv"
    if not messages_path.exists():
        raise FileNotFoundError(f"missing normalized messages: {messages_path}")
    messages = read_csv(messages_path)
    pins_path = occurrence_root / "pins.csv"
    plan_path = paths["metadata"] / "run-plan.json"
    pins_required = False
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        pins_required = bool(plan.get("operations", {}).get("pins"))
    if pins_required and not pins_path.exists():
        raise FileNotFoundError(f"missing required pins: {pins_path}")
    pins = read_csv(pins_path)
    occurrences = _occurrences(messages, "message") + _occurrences(pins, "pin")
    for index, row in enumerate(occurrences, 1):
        row["sequence"] = str(index).zfill(6)

    grouped = OrderedDict()
    for row in occurrences:
        grouped.setdefault(row["canonical_url"], []).append(row)
    merged = [_merge(url, rows) for url, rows in grouped.items()]
    merged.sort(key=lambda row: (_time_key(row["first_seen"]), row.get("_first_sequence", 0), row["canonical_url"]))
    user_links = [row for row in merged if row["category"] != "zalo-media"]
    media_links = [row for row in merged if row["category"] == "zalo-media"]
    for index, row in enumerate(user_links, 1):
        row["sequence"] = str(index).zfill(6)
    for index, row in enumerate(media_links, 1):
        row["sequence"] = str(index).zfill(6)

    write_csv(occurrence_root / "links-occurrences.csv", occurrences, OCCURRENCE_FIELDS)
    write_csv(occurrence_root / "links-classified-occurrences.csv", occurrences, OCCURRENCE_FIELDS)
    write_csv(machine / "links.csv", user_links, PRIMARY_FIELDS)
    write_csv(machine / "links-classified.csv", user_links, PRIMARY_FIELDS)
    write_csv(occurrence_root / "zalo-media-links.csv", media_links, PRIMARY_FIELDS)

    category_dir = paths["categories"]
    category_dir.mkdir(parents=True, exist_ok=True)
    for old in category_dir.glob("*.csv"):
        old.unlink()
    by_category = {}
    for row in user_links:
        by_category.setdefault(row["category"], []).append(row)
    for category, rows in sorted(by_category.items()):
        write_csv(category_dir / f"{safe_category_slug(category)}.csv", rows, PRIMARY_FIELDS)

    media_url_set = {row["canonical_url"] for row in media_links}
    report_path = paths["metadata"] / "link-classification.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    report.update({
        "rawOccurrenceRows": len(occurrences),
        "allExactUniqueUrls": len(merged),
        "userFacingUniqueUrls": len(user_links),
        "mediaUniqueUrls": len(media_links),
        "userFacingCanonicalRows": len(user_links),
        "internalMediaCanonicalRows": len(media_links),
        "userFacingOccurrenceRows": sum(len(rows) for url, rows in grouped.items() if url not in media_url_set),
        "internalMediaOccurrenceRows": sum(len(rows) for url, rows in grouped.items() if url in media_url_set),
        "rawDuplicateUrlGroups": sum(len(rows) > 1 for rows in grouped.values()),
        "rawMergedExtraOccurrences": sum(len(rows) - 1 for rows in grouped.values() if len(rows) > 1),
        "linkRows": len(user_links),
        "uniqueLinks": len(user_links),
        "classificationRuleSet": "exact url.strip grouping; deterministic host/path rules",
    })
    pin_audit_path = paths["metadata"] / "pin-audit.json"
    if pin_audit_path.exists():
        pin_audit = json.loads(pin_audit_path.read_text(encoding="utf-8"))
        for key in ("pinAuditStatus", "pinAuditCompleteness", "enumeratedPinCount", "uniquePinLinkCount", "endCondition"):
            if key in pin_audit:
                report[key] = pin_audit[key]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = paths["metadata"] / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        links = manifest.setdefault("links", {})
        links.update({
            "rawOccurrenceRows": len(occurrences),
            "allExactUniqueUrls": len(merged),
            "userFacingCanonicalRows": len(user_links),
            "internalMediaCanonicalRows": len(media_links),
            "userFacingOccurrenceRows": report["userFacingOccurrenceRows"],
            "internalMediaOccurrenceRows": report["internalMediaOccurrenceRows"],
            "rawDuplicateUrlGroups": report["rawDuplicateUrlGroups"],
            "rawMergedExtraOccurrences": report["rawMergedExtraOccurrences"],
        })
        for key in ("pinAuditStatus", "pinAuditCompleteness", "enumeratedPinCount", "uniquePinLinkCount", "endCondition"):
            if key in report:
                links[key] = report[key]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"occurrences": len(occurrences), "user_links": len(user_links), "media_links": len(media_links)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(extract_links(args.export_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
