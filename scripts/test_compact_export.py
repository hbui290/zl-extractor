#!/usr/bin/env python3
"""Contract test for the minimal human-facing export layout."""

import csv
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render_human_views import build  # noqa: E402


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory(prefix="zl-compact-export-") as temp:
        root = Path(temp)
        (root / "source/manifest.json").parent.mkdir(parents=True)
        (root / "source/manifest.json").write_text(json.dumps({
            "sourceWriteIssued": False,
            "conversationName": "Compact fixture",
            "exportStatus": "PARTIAL",
        }), encoding="utf-8")
        write_csv(root / "source/raw/messages.csv", ["timestamp", "sender", "text"], [
            {"timestamp": "2026-07-16 10:00", "sender": "A", "text": "Hello"},
        ])
        write_csv(root / "source/raw/links.csv", [
            "sequence", "category", "url", "occurrence_count", "first_seen", "last_seen",
            "sources", "confidence", "context_alternatives",
        ], [{
            "sequence": "000001", "category": "tool-platform", "url": "https://example.com/tool",
            "occurrence_count": "1", "first_seen": "2026-07-16 10:00", "last_seen": "2026-07-16 10:00",
            "sources": "message", "confidence": "high", "context_alternatives": "",
        }])
        write_csv(root / "source/raw/links-occurrences.csv", ["url"], [{"url": "https://example.com/tool"}])
        write_csv(root / "source/raw/pins.csv", ["timestamp", "sender", "title", "text", "urls"], [])

        build(root)
        generated = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
        }
        expected = {
            "readable/index.md",
            "readable/messages.md",
            "readable/links.csv",
            "readable/pins.md",
            "source/manifest.json",
        }
        assert expected <= generated
        forbidden = {
            "readable/links.md",
            "readable/review.md",
            "readable/review.csv",
            "readable/media.md",
            "readable/media.csv",
            "source/source-info.json",
        }
        assert not forbidden & generated, sorted(forbidden & generated)
        assert not any("links-by-category" in path for path in generated)
        assert not any(path.endswith(".DS_Store") for path in generated)
    print("compact_export_tests=PASS")


if __name__ == "__main__":
    main()
