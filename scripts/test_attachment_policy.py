#!/usr/bin/env python3
"""Contract test for the GIF/sticker exclusion policy."""

import csv
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix="zl-policy-") as temp:
        root = Path(temp)
        messages = root / "01-messages"
        messages.mkdir(parents=True)
        path = messages / "attachments.csv"
        fields = ["type", "original_name", "status", "relative_output_path", "error"]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerow({
                "type": "sticker", "original_name": "sticker.webp", "status": "copied",
                "relative_output_path": "attachments/sticker.webp",
            })
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "enforce_attachment_policy.py"), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        with path.open(newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle))
        assert row["status"] == "skipped_by_policy"
        assert not row["relative_output_path"]
    print("attachment_policy_tests=PASS")


if __name__ == "__main__":
    main()
