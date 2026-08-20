#!/usr/bin/env python3
"""Fixture test for exact URL occurrence extraction and merge."""

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_links import extract_links, read_csv  # noqa: E402


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory(prefix="zl-extract-links-") as temp:
        root = Path(temp)
        (root / "source").mkdir()
        (root / "source/manifest.json").write_text(
            json.dumps({"sourceWriteIssued": False}), encoding="utf-8"
        )
        write_csv(
            root / "raw/messages.csv",
            ["timestamp", "message_id", "sender", "text"],
            [
                {
                    "timestamp": "2026-07-16 10:01",
                    "message_id": "m1",
                    "sender": "A",
                    "text": "https://example.com/a?x=1.",
                },
                {
                    "timestamp": "2026-07-16 10:02",
                    "message_id": "m2",
                    "sender": "B",
                    "text": "Again https://example.com/a?x=1 and variant https://example.com/a?x=2",
                },
                {
                    "timestamp": "2026-07-16 10:03",
                    "message_id": "m3",
                    "sender": "C",
                    "text": "https://photo-stal-1.zdn.vn/image.jpg?token=secret",
                },
            ],
        )
        write_csv(
            root / "raw/pins.csv",
            ["timestamp", "pin_id", "title", "content", "url"],
            [{
                "timestamp": "2026-07-16 10:04",
                "pin_id": "p1",
                "title": "Pinned resource",
                "content": "Pinned https://example.com/a?x=1",
                "url": "https://example.com/a?x=1",
            }],
        )

        result = extract_links(root)
        assert result["occurrences"] == 5
        assert result["user_links"] == 2
        assert result["media_links"] == 1

        occurrences = read_csv(root / "raw/links-occurrences.csv")
        assert len(occurrences) == 5
        primary = read_csv(root / "raw/links.csv")
        assert {row["url"] for row in primary} == {
            "https://example.com/a?x=1",
            "https://example.com/a?x=2",
        }
        merged = next(row for row in primary if row["url"].endswith("x=1"))
        assert merged["occurrence_count"] == "3"
        assert merged["message_ids"] == "m1|m2"
        assert merged["pin_ids"] == "p1"
        assert "Pinned" in merged["context_summary"]
        report = json.loads((root / "source/link-classification.json").read_text(encoding="utf-8"))
        assert report["userFacingCanonicalRows"] == 2
        assert report["internalMediaCanonicalRows"] == 1
        assert report["userFacingOccurrenceRows"] == 4
        assert report["internalMediaOccurrenceRows"] == 1
        for output in ("links-occurrences.csv", "links-classified-occurrences.csv", "links.csv", "links-classified.csv", "zalo-media-links.csv"):
            assert "token=secret" not in (root / "raw" / output).read_text(encoding="utf-8")
        assert "token=secret" not in (root / "raw/zalo-media-links.csv").read_text(encoding="utf-8")
        review = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "write_link_review.py"), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert review.returncode == 0, review.stdout + review.stderr
        audit = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "audit_links.py"), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert audit.returncode == 2, audit.stdout + audit.stderr
        assert '"status": "PARTIAL"' in audit.stdout
        assert len(read_csv(root / "raw/zalo-media-links.csv")) == 1

    print("extract_link_tests=PASS")


if __name__ == "__main__":
    main()
