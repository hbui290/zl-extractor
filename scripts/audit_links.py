#!/usr/bin/env python3
"""Independent, read-only audit for a ZL Extractor link export."""

import argparse
import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from export_paths import contained_attachment, export_paths


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def is_internal_media(url):
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host.endswith((".zdn.vn", ".zadn.vn", ".dlmd.me", ".dlfl.vn")) and any(
        token in host for token in ("stal", "ava-talk", "zpg-r", "photo-link-talk")
    )


def exact_url(row):
    return str(row.get("url", "")).strip()


def int_count(row):
    try:
        return int(row.get("occurrence_count", "1"))
    except (TypeError, ValueError):
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path)
    args = parser.parse_args()
    root = args.export_root.resolve()
    paths = export_paths(root)
    messages = paths["machine"]
    reports = paths["metadata"]
    raw_path = messages / "links-classified-occurrences.csv"
    if not raw_path.exists():
        raw_path = messages / "links-occurrences.csv"
    primary_path = messages / "links.csv"
    media_path = messages / "zalo-media-links.csv"
    manifest_path = reports / "manifest.json"
    classification_report_path = reports / "link-classification.json"

    failures = []
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {}
    if manifest.get("sourceWriteIssued") is True:
        failures.append("manifest says sourceWriteIssued=true")
    if not raw_path.exists():
        failures.append(f"missing raw occurrence ledger: {raw_path}")
        raw = []
    else:
        raw = read_csv(raw_path)
    primary = read_csv(primary_path) if primary_path.exists() else []
    media = read_csv(media_path) if media_path.exists() else []

    raw_groups = {}
    for row in raw:
        raw_groups.setdefault(exact_url(row), []).append(row)
    raw_user = {url: rows for url, rows in raw_groups.items() if not is_internal_media(url)}
    raw_media = {url: rows for url, rows in raw_groups.items() if is_internal_media(url)}
    primary_urls = [exact_url(row) for row in primary]
    media_urls = [exact_url(row) for row in media]
    if any(not row.get("canonical_url") or row.get("canonical_url") != exact_url(row) for row in primary + media):
        failures.append("canonical_url is missing or differs from trim(url) in canonical links")
    resolution_path = messages / "link-review-resolutions.csv"
    resolutions = {}
    if resolution_path.exists():
        for row in read_csv(resolution_path):
            if row.get("status") in {"resolved", "rule_verified"}:
                resolutions[exact_url(row)] = row.get("status")
    low_confidence_rows = [row for row in primary if row.get("confidence") == "low"]
    category_conflict_rows = [row for row in primary if "|" in row.get("observed_categories", "")]
    context_alternative_rows = [row for row in primary if row.get("context_alternatives")]
    resolved_rule_conflict_rows = [row for row in primary if "|" in row.get("observed_categories", "") and row.get("classification_rule", "existing_classifier") != "existing_classifier"]
    unresolved_category_conflict_rows = [row for row in primary if "|" in row.get("observed_categories", "") and row.get("classification_rule", "existing_classifier") == "existing_classifier"]
    review_rows = {
        exact_url(row)
        for row in primary
        if exact_url(row) not in resolutions
        and (row.get("confidence") == "low" or "|" in row.get("observed_categories", "") or row.get("context_alternatives"))
    }
    category_rows = 0
    category_counts = {}
    category_dir = paths["categories"]
    if category_dir.exists():
        for path in sorted(category_dir.glob("*.csv")):
            count = len(read_csv(path))
            category_counts[path.stem] = count
            category_rows += count

    if len(primary_urls) != len(set(primary_urls)):
        failures.append(f"duplicate canonical URL remains in {primary_path.relative_to(root)}")
    if any(is_internal_media(url) for url in primary_urls):
        failures.append(f"internal media URL leaked into {primary_path.relative_to(root)}")
    if set(primary_urls) != set(raw_user):
        failures.append("primary user-facing URL set does not match exact URL partition from raw ledger")
    if set(media_urls) != set(raw_media):
        failures.append("media URL set does not match exact URL partition from raw ledger")
    if category_rows != len(primary):
        failures.append("category view row sum does not equal primary canonical row count")
    if sum(int_count(row) for row in primary) != sum(len(rows) for rows in raw_user.values()):
        failures.append("user-facing occurrence sum does not reconcile with raw ledger")
    if sum(int_count(row) for row in media) != sum(len(rows) for rows in raw_media.values()):
        failures.append("media occurrence sum does not reconcile with raw ledger")
    if sum(int_count(row) for row in primary) + sum(int_count(row) for row in media) != len(raw):
        failures.append("combined occurrence sum does not equal raw occurrence rows")
    if any(not row.get("message_ids") and not row.get("pin_ids") for row in primary):
        failures.append("primary row is missing message_ids and pin_ids")
    attachments_path = messages / "attachments.csv"
    attachment_rows = read_csv(attachments_path) if attachments_path.exists() else []
    saved_statuses = {"copied", "downloaded", "preview_only"}
    for row in attachment_rows:
        status = (row.get("status") or "").strip()
        relative = (row.get("relative_output_path") or row.get("output_path") or "").strip()
        if status == "skipped_by_policy" and relative:
            failures.append("policy-skipped attachment still exposes an output path")
        elif status in saved_statuses:
            candidate = contained_attachment(root, relative)
            if candidate is None:
                failures.append(f"saved attachment path is missing or outside export: {relative}")
            elif candidate.stat().st_size <= 0:
                failures.append(f"saved attachment is empty: {relative}")
    review_path = messages / "link-review.csv"
    review_file_rows = read_csv(review_path) if review_path.exists() else []
    if review_rows and not review_path.exists():
        failures.append("classification review queue is missing")
    if review_path.exists() and len(review_file_rows) != len(review_rows):
        failures.append("classification review queue count does not match uncertain/conflicting primary rows")
    if set(resolutions) - set(primary_urls):
        failures.append("review resolution ledger contains URLs absent from primary links")

    raw_unique = len(raw_groups)
    expected_report = {
        "linkRows": len(primary),
        "uniqueLinks": len(primary),
        "rawOccurrenceRows": len(raw),
        "allExactUniqueUrls": raw_unique,
        "userFacingUniqueUrls": len(raw_user),
        "userFacingCanonicalRows": len(primary),
        "internalMediaCanonicalRows": len(media),
        "userFacingOccurrenceRows": sum(int_count(row) for row in primary),
        "internalMediaOccurrenceRows": sum(int_count(row) for row in media),
    }
    if classification_report_path.exists():
        classification_report = json.loads(classification_report_path.read_text(encoding="utf-8"))
        for key, expected in expected_report.items():
            if classification_report.get(key) != expected:
                failures.append(f"classification report counter mismatch: {key}")
        if "reviewResolutionRows" in classification_report and classification_report.get("reviewResolutionRows") != len(resolutions):
            failures.append("classification report review resolution count mismatch")
        report_categories = classification_report.get("categoryCounts")
        if report_categories is not None and report_categories != {k: v for k, v in sorted(category_counts.items())}:
            failures.append("classification report category counts do not match category views")

    manifest_links = manifest.get("links", {})
    expected_manifest = {
        "rawOccurrenceRows": len(raw),
        "canonicalRows": raw_unique,
        "canonicalRowsAll": raw_unique,
        "userFacingCanonicalRows": len(primary),
        "internalMediaCanonicalRows": len(media),
        "userFacingOccurrenceRows": sum(int_count(row) for row in primary),
        "internalMediaOccurrenceRows": sum(int_count(row) for row in media),
    }
    for key, expected in expected_manifest.items():
        if key in manifest_links and manifest_links.get(key) != expected:
            failures.append(f"manifest link counter mismatch: {key}")

    link_manifest = manifest.get("links", {})
    pin_audit_status = link_manifest.get("pinAuditStatus") or manifest.get("pinAuditStatus") or "unknown"
    pin_audit_completeness = link_manifest.get("pinAuditCompleteness") or manifest.get("pinAuditCompleteness") or "unknown"
    warnings = []
    if pin_audit_status not in {"complete", "complete_with_zero_links"} or pin_audit_completeness not in {"complete", "complete_with_zero_links"}:
        warnings.append("pin audit is not proven complete; link coverage is partial")
    if review_rows:
        warnings.append(f"{len(review_rows)} primary rows need classification review")
    if manifest.get("exportStatus") == "COMPLETE" and warnings:
        failures.append("manifest claims COMPLETE while audit has warnings")

    result = {
        "status": "PASS" if not failures and not warnings else ("PARTIAL" if not failures else "FAIL"),
        "export_root": str(root),
        "raw_occurrence_rows": len(raw),
        "all_exact_unique_urls": len(raw_groups),
        "raw_duplicate_url_groups": sum(len(rows) > 1 for rows in raw_groups.values()),
        "raw_merged_extra_occurrences": sum(len(rows) - 1 for rows in raw_groups.values() if len(rows) > 1),
        "user_facing_unique_urls": len(raw_user),
        "user_facing_occurrence_rows": sum(len(rows) for rows in raw_user.values()),
        "media_unique_urls": len(raw_media),
        "media_occurrence_rows": sum(len(rows) for rows in raw_media.values()),
        "primary_rows": len(primary),
        "primary_duplicate_rows": len(primary_urls) - len(set(primary_urls)),
        "category_view_rows": category_rows,
        "category_counts": category_counts,
        "low_confidence_rows": len(low_confidence_rows),
        "category_conflict_rows": len(category_conflict_rows),
        "resolved_rule_conflict_rows": len(resolved_rule_conflict_rows),
        "unresolved_category_conflict_rows": len(unresolved_category_conflict_rows),
        "context_alternative_rows": len(context_alternative_rows),
        "classification_review_rows": len(review_rows),
        "pin_audit_status": pin_audit_status,
        "pin_audit_completeness": pin_audit_completeness,
        "failures": failures,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else (2 if warnings else 0)


if __name__ == "__main__":
    sys.exit(main())
