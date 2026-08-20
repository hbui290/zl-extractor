#!/usr/bin/env python3
"""Write a focused review queue for uncertain or conflicting user-facing links."""

import argparse
import csv
import json
from pathlib import Path

from export_paths import assert_source_read_only, export_paths


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path)
    args = parser.parse_args()
    root = args.export_root.resolve()
    paths = export_paths(root)
    assert_source_read_only(root, paths["metadata"])
    machine = paths["machine"]
    metadata = paths["metadata"]
    source = machine / "links-classified.csv"
    review_root = machine if paths["new_layout"] else metadata
    output = review_root / "link-review.csv"
    resolution_path = review_root / "link-review-resolutions.csv"
    resolutions = {}
    if resolution_path.exists():
        for resolved in read_csv(resolution_path):
            if resolved.get("status") in {"resolved", "rule_verified"}:
                resolutions[(resolved.get("url") or "").strip()] = resolved.get("status")
    rows = []
    for row in read_csv(source):
        if (row.get("url") or "").strip() in resolutions:
            continue
        reasons = []
        deterministic_rule = row.get("classification_rule", "existing_classifier") != "existing_classifier"
        if row.get("confidence") == "low":
            reasons.append("low_confidence")
        if "|" in row.get("observed_categories", ""):
            reasons.append("rule_override_audit" if deterministic_rule else "category_conflict")
        if row.get("context_alternatives"):
            reasons.append("context_alternative")
        if not reasons:
            continue
        rows.append({
            "sequence": row.get("sequence", ""),
            "url": row.get("url", ""),
            "category": row.get("category", ""),
            "original_category": row.get("original_category", ""),
            "classification_rule": row.get("classification_rule", ""),
            "observed_categories": row.get("observed_categories", ""),
            "context_name": row.get("context_name", ""),
            "context_alternatives": row.get("context_alternatives", ""),
            "context_summary": row.get("context_summary", ""),
            "confidence": row.get("confidence", ""),
            "occurrence_count": row.get("occurrence_count", ""),
            "message_ids": row.get("message_ids", ""),
            "review_reasons": "|".join(reasons),
        })
    fields = [
        "sequence", "url", "category", "original_category", "classification_rule", "observed_categories", "context_name", "context_alternatives",
        "context_summary", "confidence", "occurrence_count", "message_ids", "review_reasons",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    report_path = metadata / "link-classification.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["classificationReviewRows"] = len(rows)
        report["classificationStatus"] = "REVIEW_REQUIRED" if rows else "READY"
        report["reviewResolutionRows"] = len(resolutions)
        report.setdefault("verification", {})["classificationQueue"] = len(rows)
        report["verification"]["reviewResolutionRows"] = len(resolutions)
        resolution_output = "raw/link-review-resolutions.csv" if paths["new_layout"] else "03-reports/link-review-resolutions.csv"
        if isinstance(report.get("outputs"), list) and resolution_output not in report["outputs"]:
            report["outputs"].append(resolution_output)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = metadata / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        links = manifest.setdefault("links", {})
        links["classificationReviewRows"] = len(rows)
        links["classificationStatus"] = "REVIEW_REQUIRED" if rows else "READY"
        links.setdefault("verification", {})["classificationQueue"] = len(rows)
        links["reviewResolutionRows"] = len(resolutions)
        pin_status = links.get("pinAuditStatus", "unknown")
        pin_complete = links.get("pinAuditCompleteness", "unknown")
        if rows or pin_status not in {"complete", "complete_with_zero_links"} or pin_complete not in {"complete", "complete_with_zero_links"}:
            manifest["exportStatus"] = "PARTIAL"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"review_rows={len(rows)} output={output}")


if __name__ == "__main__":
    main()
