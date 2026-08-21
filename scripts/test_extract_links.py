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
            json.dumps({"sourceWriteIssued": False, "source": {"conversationId": "g1"}}), encoding="utf-8"
        )
        write_csv(
            root / "raw/messages.csv",
            ["timestamp", "message_id", "sender", "text"],
            [
                {
                    "timestamp": "2026-07-16 10:01",
                    "message_id": "m1",
                    "sender": "A",
                    "text": "https://example.com/a?x=1 then https://example.com/a?x=1.",
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
                {
                    "timestamp": "2026-07-16 10:04",
                    "message_id": "m4",
                    "sender": "D",
                    "text": "Bare domain Vmedia.ai; price 2.5k and file video.mp4",
                },
            ],
        )
        (root / "source/link-archive-audit.json").write_text(
            json.dumps({"conversationId": "g1", "status": "COMPLETE", "enumeratedCardCount": 2, "endCondition": "fixture"}), encoding="utf-8"
        )
        write_csv(
            root / "raw/pins.csv",
            ["timestamp", "pin_id", "title", "content", "url"],
            [{
                "timestamp": "2026-07-16 10:04",
                "pin_id": "p1",
                "title": "Pinned resource",
                "content": "Pinned https://example.com/a?x=1 and make.com",
                "url": "https://example.com/a?x=1",
            }],
        )
        write_csv(
            root / "raw/link-archive.csv",
            ["archive_index", "message_id", "timestamp", "sender_id", "title", "url", "source"],
            [
                {
                    "archive_index": "1",
                    "message_id": "m1",
                    "timestamp": "2026-07-16 10:01",
                    "sender_id": "u1",
                    "title": "https://example.com/a?x=1 and https://archive.example/new",
                    "url": "https://preview.example/must-not-leak",
                    "source": "link_archive",
                },
                {
                    "archive_index": "2",
                    "message_id": "m5",
                    "timestamp": "2026-07-16 10:05",
                    "sender_id": "u2",
                    "title": "A card whose title has no URL",
                    "url": "https://fallback.example/item",
                    "source": "link_archive",
                },
            ],
        )

        result = extract_links(root)
        assert result["occurrences"] == 10
        assert result["user_links"] == 6
        assert result["media_links"] == 1

        occurrences = read_csv(root / "raw/links-occurrences.csv")
        assert len(occurrences) == 10
        primary = read_csv(root / "raw/links.csv")
        assert {row["url"] for row in primary} == {
            "https://example.com/a?x=1",
            "https://example.com/a?x=2",
            "https://archive.example/new",
            "https://fallback.example/item",
            "Vmedia.ai",
            "make.com",
        }
        assert all("preview.example" not in row["url"] for row in occurrences)
        duplicate = [row for row in occurrences if row["message_id"] == "m1" and row["url"].endswith("x=1")]
        assert len(duplicate) == 2
        assert [row["source"] for row in duplicate].count("message|link_archive") == 1
        merged = next(row for row in primary if row["url"].endswith("x=1"))
        assert merged["occurrence_count"] == "4"
        assert merged["message_ids"] == "m1|m2"
        assert merged["pin_ids"] == "p1"
        assert merged["sources"] == "message|link_archive|pin"
        assert "Pinned" in merged["context_summary"]
        manifest = json.loads((root / "source/manifest.json").read_text(encoding="utf-8"))
        assert manifest["links"]["userFacingCanonicalRows"] == 6
        assert manifest["links"]["internalMediaCanonicalRows"] == 1
        assert manifest["links"]["userFacingOccurrenceRows"] == 9
        assert manifest["links"]["internalMediaOccurrenceRows"] == 1
        assert not (root / "source/link-classification.json").exists()
        baseline = root / "manual-links.txt"
        baseline.write_text(
            "https://example.com/a?x=1\nhttps://example.com/a?x=1\nhttps://example.com/a?x=1\nhttps://example.com/a?x=1\nhttps://example.com/a?x=1\nhttps://missing.example/item\nhttps://photo-stal-1.zdn.vn/x?token=must-not-leak\n",
            encoding="utf-8",
        )
        reconcile = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "reconcile_link_baseline.py"), str(root), str(baseline)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert reconcile.returncode == 2, reconcile.stdout + reconcile.stderr
        reconciliation = json.loads((root / "source/manual-link-reconciliation.json").read_text(encoding="utf-8"))
        assert reconciliation["baselineUniqueUrls"] == 2
        assert reconciliation["baselineDuplicateOccurrences"] == 4
        assert reconciliation["missingUniqueUrls"] == 1
        assert reconciliation["missingOccurrences"] == 2
        assert (root / "source/manual-link-reconciliation.csv").exists()
        assert not (root / "readable/link-reconciliation.md").exists()
        for output in (root / "source/manual-link-reconciliation.csv", root / "source/manual-link-reconciliation.json"):
            assert "must-not-leak" not in output.read_text(encoding="utf-8")
        for output in ("links-occurrences.csv", "links.csv", "zalo-media-links.csv"):
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
