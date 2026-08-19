#!/usr/bin/env python3
"""Mark GIF/sticker attachment records as intentionally skipped."""

import argparse
import csv
from pathlib import Path

from export_paths import assert_source_read_only, export_paths


def is_excluded(row):
    kind = " ".join((row.get(field) or "").lower() for field in ("type", "source_kind"))
    name = (row.get("original_name") or "").lower()
    return "sticker" in kind or "gif" in kind or name.endswith(".gif")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path)
    args = parser.parse_args()
    paths = export_paths(args.export_root)
    assert_source_read_only(args.export_root, paths["metadata"])
    path = paths["machine"] / "attachments.csv"
    if not path.exists():
        print(f"policy_rows=0 status=SKIPPED output={path}")
        return
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = list(reader)
    changed = 0
    for row in rows:
        if is_excluded(row) and row.get("status") != "skipped_by_policy":
            row["status"] = "skipped_by_policy"
            row["error"] = "GIF/sticker binary excluded by policy"
            changed += 1
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"policy_rows={changed} output={path}")


if __name__ == "__main__":
    main()
