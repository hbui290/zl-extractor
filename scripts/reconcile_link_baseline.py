#!/usr/bin/env python3
"""Compare a manually collected URL list with an export, preserving line evidence."""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from export_paths import assert_source_read_only, export_paths, is_internal_media_url
from url_rules import find_url_occurrences


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path)
    parser.add_argument("baseline_text", type=Path)
    args = parser.parse_args()
    root = args.export_root.resolve()
    baseline = args.baseline_text.resolve()
    paths = export_paths(root)
    assert_source_read_only(root, paths["metadata"])
    occurrence_root = paths["machine"] if paths["new_layout"] else paths["metadata"]
    occurrence_path = occurrence_root / "links-occurrences.csv"
    if not occurrence_path.exists():
        raise FileNotFoundError(f"missing occurrence ledger: {occurrence_path}")

    baseline_rows = []
    seen = Counter()
    for line_number, line in enumerate(baseline.read_text(encoding="utf-8").splitlines(), 1):
        for url in find_url_occurrences(line):
            if is_internal_media_url(url):
                continue
            seen[url] += 1
            baseline_rows.append({"line": line_number, "baseline_occurrence": seen[url], "url": url})

    occurrences = [row for row in read_csv(occurrence_path) if not is_internal_media_url(row.get("url", ""))]
    export_by_url = defaultdict(list)
    for row in occurrences:
        export_by_url[str(row.get("url", "")).strip()].append(row)

    detail = []
    for row in baseline_rows:
        matches = export_by_url.get(row["url"], [])
        if not matches:
            status = "MISSING"
        elif len(matches) < row["baseline_occurrence"]:
            status = "OCCURRENCE_NOT_PROVEN"
        else:
            status = "MATCH"
        detail.append({
            **row,
            "status": status,
            "export_occurrence_count": len(matches),
            "export_sources": "|".join(dict.fromkeys(part for match in matches for part in str(match.get("source", "")).split("|") if part)),
            "message_ids": "|".join(dict.fromkeys(str(match.get("message_id", "")).strip() for match in matches if match.get("message_id"))),
            "pin_ids": "|".join(dict.fromkeys(str(match.get("pin_id", "")).strip() for match in matches if match.get("pin_id"))),
        })

    baseline_urls = set(seen)
    export_urls = set(export_by_url)
    missing = sorted(baseline_urls - export_urls)
    occurrence_deficits = sorted(url for url, count in seen.items() if len(export_by_url.get(url, [])) < count)
    extra = sorted(export_urls - baseline_urls)
    for url in extra:
        matches = export_by_url[url]
        detail.append({
            "line": "",
            "baseline_occurrence": "",
            "url": url,
            "status": "EXPORT_ONLY",
            "export_occurrence_count": len(matches),
            "export_sources": "|".join(dict.fromkeys(part for match in matches for part in str(match.get("source", "")).split("|") if part)),
            "message_ids": "|".join(dict.fromkeys(str(match.get("message_id", "")).strip() for match in matches if match.get("message_id"))),
            "pin_ids": "|".join(dict.fromkeys(str(match.get("pin_id", "")).strip() for match in matches if match.get("pin_id"))),
        })
    summary = {
        "status": "PASS" if not missing else "PARTIAL",
        "baselinePath": str(baseline),
        "baselineUrlOccurrences": len(baseline_rows),
        "baselineUniqueUrls": len(baseline_urls),
        "baselineDuplicateOccurrences": len(baseline_rows) - len(baseline_urls),
        "exportOccurrenceRows": len(occurrences),
        "exportUniqueUrls": len(export_urls),
        "matchedUniqueUrls": len(baseline_urls & export_urls),
        "matchedOccurrences": sum(min(count, len(export_by_url.get(url, []))) for url, count in seen.items()),
        "missingOccurrences": sum(max(0, count - len(export_by_url.get(url, []))) for url, count in seen.items()),
        "occurrenceDeficitUrlCount": len(occurrence_deficits),
        "missingUniqueUrls": len(missing),
        "extraUniqueUrls": len(extra),
        "missingUrls": missing,
        "extraUrls": extra,
    }
    reports = paths["metadata"]
    readable_reconciliation = root / "readable" / "link-reconciliation.md"
    if readable_reconciliation.exists():
        readable_reconciliation.unlink()
    write_csv(
        reports / "manual-link-reconciliation.csv",
        detail,
        ["line", "baseline_occurrence", "status", "url", "export_occurrence_count", "export_sources", "message_ids", "pin_ids"],
    )
    (reports / "manual-link-reconciliation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key not in {"missingUrls", "extraUrls", "baselinePath"}}, ensure_ascii=False, indent=2))
    return 2 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
