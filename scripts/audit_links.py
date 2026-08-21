#!/usr/bin/env python3
"""Independent, read-only audit for a ZL Extractor link export."""

import argparse
import csv
import json
import sys
from pathlib import Path

from item_checkpoint import checkpoint_path, validate_checkpoints
from export_paths import (
    contained_attachment,
    export_paths,
    has_signed_internal_media_query,
    is_internal_media_url,
)
from run_plan import plan_path, validate_plan
from url_rules import find_url_occurrences


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def exact_url(row):
    return str(row.get("url", "")).strip()


def int_count(row):
    try:
        return int(row.get("occurrence_count", "1"))
    except (TypeError, ValueError):
        return 0


def occurrence_counts(rows):
    counts = {}
    for row in rows:
        url = exact_url(row)
        counts[url] = counts.get(url, 0) + int_count(row)
    return counts


def signed_media_urls(rows):
    urls = set()
    for row in rows:
        for field, value in row.items():
            field_name = str(field or "").lower()
            if ("url" in field_name or "link" in field_name) and has_signed_internal_media_query(value):
                urls.add(str(value).strip())
    return sorted(urls)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path)
    args = parser.parse_args()
    root = args.export_root.resolve()
    paths = export_paths(root)
    messages = paths["machine"]
    reports = paths["metadata"]
    occurrence_root = messages if paths["new_layout"] else reports
    raw_path = occurrence_root / "links-occurrences.csv"
    if not raw_path.exists():
        raw_path = occurrence_root / "links-classified-occurrences.csv"
    primary_path = messages / "links.csv"
    media_path = occurrence_root / "zalo-media-links.csv"
    manifest_path = reports / "manifest.json"
    link_archive_path = reports / "link-archive-audit.json"
    run_plan_file = plan_path(root)
    checkpoint_file = checkpoint_path(root)

    failures = []
    run_plan_issues = validate_plan(root) if run_plan_file.exists() else []
    checkpoint_issues = validate_checkpoints(root) if checkpoint_file.exists() else []
    if run_plan_issues:
        failures.extend(f"run plan: {issue}" for issue in run_plan_issues)
    if checkpoint_issues:
        failures.extend(f"item checkpoint: {issue}" for issue in checkpoint_issues)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {}
    if link_archive_path.exists():
        try:
            link_archive = json.loads(link_archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failures.append("link archive audit file is not valid JSON")
            link_archive = {}
    else:
        link_archive = {}
    if manifest.get("sourceWriteIssued") is True:
        failures.append("manifest says sourceWriteIssued=true")
    if not raw_path.exists():
        failures.append(f"missing raw occurrence ledger: {raw_path}")
        raw = []
    else:
        raw = read_csv(raw_path)
    primary = read_csv(primary_path) if primary_path.exists() else []
    media = read_csv(media_path) if media_path.exists() else []
    archive_rows_path = occurrence_root / "link-archive.csv"
    archive_rows = read_csv(archive_rows_path) if archive_rows_path.exists() else []

    raw_groups = {}
    for row in raw:
        raw_groups.setdefault(exact_url(row), []).append(row)
    raw_user = {url: rows for url, rows in raw_groups.items() if not is_internal_media_url(url)}
    raw_media = {url: rows for url, rows in raw_groups.items() if is_internal_media_url(url)}
    primary_urls = [exact_url(row) for row in primary]
    media_urls = [exact_url(row) for row in media]
    if any(not row.get("canonical_url") or row.get("canonical_url") != exact_url(row) for row in primary + media):
        failures.append("canonical_url is missing or differs from trim(url) in canonical links")
    resolution_path = occurrence_root / "link-review-resolutions.csv"
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
    category_counts = {}
    for row in primary:
        category = (row.get("category") or "other").strip() or "other"
        category_counts[category] = category_counts.get(category, 0) + 1
    category_rows = len(primary)

    if len(primary_urls) != len(set(primary_urls)):
        failures.append(f"duplicate canonical URL remains in {primary_path.relative_to(root)}")
    if any(is_internal_media_url(url) for url in primary_urls):
        failures.append(f"internal media URL leaked into {primary_path.relative_to(root)}")
    signed_urls = set(signed_media_urls(raw + primary + media))
    for candidate_root in {messages, reports}:
        for candidate in candidate_root.rglob("*.csv"):
            signed_urls.update(signed_media_urls(read_csv(candidate)))
    signed_urls = sorted(signed_urls)
    if signed_urls:
        failures.append("signed internal media query remains in export data")
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
    if occurrence_counts(primary) != {url: len(rows) for url, rows in raw_user.items()}:
        failures.append("per-URL user-facing occurrence counts do not reconcile with raw ledger")
    if occurrence_counts(media) != {url: len(rows) for url, rows in raw_media.items()}:
        failures.append("per-URL media occurrence counts do not reconcile with raw ledger")
    if sum(int_count(row) for row in primary) + sum(int_count(row) for row in media) != len(raw):
        failures.append("combined occurrence sum does not equal raw occurrence rows")
    if any(not row.get("message_ids") and not row.get("pin_ids") for row in primary):
        failures.append("primary row is missing message_ids and pin_ids")
    attachments_path = occurrence_root / "attachments.csv"
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
    review_path = occurrence_root / "link-review.csv"
    review_file_rows = read_csv(review_path) if review_path.exists() else []
    if review_rows and not review_path.exists():
        failures.append("classification review queue is missing")
    if review_path.exists() and len(review_file_rows) != len(review_rows):
        failures.append("classification review queue count does not match uncertain/conflicting primary rows")
    if set(resolutions) - set(primary_urls):
        failures.append("review resolution ledger contains URLs absent from primary links")

    raw_unique = len(raw_groups)
    manifest_links = manifest.get("links", {})
    expected_manifest = {
        "rawOccurrenceRows": len(raw),
        "canonicalRows": raw_unique,
        "canonicalRowsAll": raw_unique,
        "userFacingCanonicalRows": len(primary),
        "internalMediaCanonicalRows": len(media),
        "userFacingOccurrenceRows": sum(int_count(row) for row in primary),
        "internalMediaOccurrenceRows": sum(int_count(row) for row in media),
        "categoryCounts": {k: v for k, v in sorted(category_counts.items())},
    }
    for key, expected in expected_manifest.items():
        if key in manifest_links and manifest_links.get(key) != expected:
            failures.append(f"manifest link counter mismatch: {key}")

    link_manifest = manifest.get("links", {})
    pin_audit_status = link_manifest.get("pinAuditStatus") or manifest.get("pinAuditStatus") or "unknown"
    pin_audit_completeness = link_manifest.get("pinAuditCompleteness") or manifest.get("pinAuditCompleteness") or "unknown"
    warnings = []
    if paths["new_layout"] and not run_plan_file.exists():
        warnings.append("run plan is missing; requested scope cannot be independently verified")
    if paths["new_layout"] and not checkpoint_file.exists():
        warnings.append("item checkpoint file is missing; resume coverage cannot be independently verified")
    if pin_audit_status not in {"complete", "complete_with_zero_links"} or pin_audit_completeness not in {"complete", "complete_with_zero_links"}:
        warnings.append("pin audit is not proven complete; link coverage is partial")
    if review_rows:
        warnings.append(f"{len(review_rows)} primary rows need classification review")
    if manifest.get("exportStatus") == "COMPLETE" and warnings:
        failures.append("manifest claims COMPLETE while audit has warnings")

    archive_reported = link_archive.get("reportedCardCount", link_archive.get("reportedLinkCount"))
    archive_enumerated = link_archive.get("enumeratedCardCount", link_archive.get("enumeratedLinkCount"))
    archive_status = str(link_archive.get("status", "")).lower()
    manifest_conversation_id = str(manifest.get("source", {}).get("conversationId") or manifest.get("conversationId") or "")
    archive_conversation_id = str(link_archive.get("conversationId") or "")
    if link_archive_path.exists() and manifest_conversation_id and archive_conversation_id != manifest_conversation_id:
        failures.append("Zalo Link archive conversation does not match manifest")
    if archive_status in {"complete", "verified"} and (archive_enumerated is None or not link_archive.get("endCondition") or not archive_rows_path.exists()):
        failures.append("complete Zalo Link archive audit is missing count, end condition, or archive CSV")
    if archive_reported is not None and archive_enumerated is not None and archive_reported != archive_enumerated:
        failures.append("Zalo Link archive reported card count does not match enumerated cards")
    if archive_enumerated is not None and len(archive_rows) != archive_enumerated:
        failures.append("Zalo Link archive CSV row count does not match enumerated cards")
    archive_pairs = set()
    for row in archive_rows:
        title_urls = find_url_occurrences(row.get("title", ""))
        urls = title_urls or find_url_occurrences(row.get("url", ""))
        archive_pairs.update((str(row.get("message_id", "")).strip(), url) for url in urls)
    raw_archive_pairs = {
        (str(row.get("message_id", "")).strip(), exact_url(row))
        for row in raw if "link_archive" in str(row.get("source", "")).split("|")
    }
    if link_archive and archive_pairs != raw_archive_pairs:
        failures.append("Zalo Link archive URL/message pairs do not reconcile with the raw occurrence ledger")
    if link_archive and archive_status not in {"complete", "verified"}:
        warnings.append("Zalo Link archive count is observed but not reconciled to exported rows")
    if not link_archive:
        warnings.append("Zalo Link archive was not enumerated; message/pin ledgers alone do not prove archive coverage")

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
        "signed_internal_media_query_urls": len(signed_urls),
        "run_plan_status": "PASS" if run_plan_file.exists() and not run_plan_issues else ("MISSING" if not run_plan_file.exists() else "FAIL"),
        "item_checkpoint_status": "PASS" if checkpoint_file.exists() and not checkpoint_issues else ("MISSING" if not checkpoint_file.exists() else "FAIL"),
        "pin_audit_status": pin_audit_status,
        "pin_audit_completeness": pin_audit_completeness,
        "link_archive_status": link_archive.get("status", "unknown"),
        "link_archive_reported_card_count": archive_reported,
        "link_archive_enumerated_card_count": archive_enumerated,
        "link_archive_exact_url_pairs": len(archive_pairs),
        "failures": failures,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else (2 if warnings else 0)


if __name__ == "__main__":
    sys.exit(main())
