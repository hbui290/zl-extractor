#!/usr/bin/env python3
"""Small fixture test for the human-view renderer."""

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from export_paths import assert_source_read_only, contained_attachment, safe_category_slug  # noqa: E402
from render_human_views import build, render_media  # noqa: E402


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def digest_tree(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main():
    with tempfile.TemporaryDirectory(prefix="zl-human-views-") as temp:
        root = Path(temp)
        write_csv(
            root / "01-messages/messages.csv",
            ["timestamp", "sender", "text", "message_type"],
            [
                {"timestamp": "2026-07-16 10:02", "sender": "A", "text": "First", "message_type": "text"},
                {"timestamp": "2026-07-16 10:03", "sender": "B", "text": "Second", "message_type": "text"},
            ],
        )
        link_fields = [
            "sequence", "category", "original_category", "classification_rule", "observed_categories",
            "context_name", "context_summary", "context_alternatives", "confidence", "occurrence_count",
            "url", "canonical_url", "first_seen", "last_seen", "sources", "message_ids", "pin_ids",
        ]
        link_row = {
                "sequence": "000001", "category": "tool-platform", "context_name": "Demo tool",
                "context_summary": "Shared for testing", "confidence": "high", "occurrence_count": "2",
                "url": "https://example.com/tool", "first_seen": "2026-07-16 10:02",
                "last_seen": "2026-07-16 10:03", "sources": "message|pin",
                "original_category": "tool-platform", "classification_rule": "existing_classifier",
                "observed_categories": "tool-platform", "canonical_url": "https://example.com/tool",
                "message_ids": "m1|m2", "pin_ids": "p1",
            }
        write_csv(root / "01-messages/links.csv", link_fields, [link_row])
        write_csv(root / "01-messages/links-classified.csv", link_fields, [link_row])
        write_csv(
            root / "03-reports/links-classified-occurrences.csv",
            ["url"],
            [{"url": "https://example.com/tool"}, {"url": "https://example.com/tool"}],
        )
        write_csv(root / "03-reports/attachments.csv", ["timestamp", "sender", "type", "status"], [])
        write_csv(root / "03-reports/link-review.csv", ["url", "review_reasons"], [])
        (root / "03-reports").mkdir(parents=True, exist_ok=True)
        (root / "03-reports/manifest.json").write_text(
            json.dumps({
                "conversationName": "Demo group",
                "exportStatus": "PARTIAL",
                "links": {"rawOccurrenceRows": 2},
            }),
            encoding="utf-8",
        )

        first = build(root)
        assert first["messages"] == 2
        assert first["links"] == 1
        assert (root / "raw/messages.csv").exists()
        assert (root / "source/manifest.json").exists()
        assert (root / "readable/index.md").exists()
        assert (root / "readable/messages.md").exists()
        assert (root / "readable/links.csv").exists()
        assert (root / "readable/media.csv").exists()
        assert (root / "readable/review.csv").exists()
        assert (root / "readable/links-by-category/tool-platform.md").exists()
        assert (root / "readable/links-by-category/tool-platform.csv").exists()
        with (root / "readable/links.csv").open(newline="", encoding="utf-8") as handle:
            assert next(csv.reader(handle)) == [
                "sequence", "category", "context_name", "url", "occurrence_count",
            ]
        with (root / "readable/media.csv").open(newline="", encoding="utf-8") as handle:
            assert next(csv.reader(handle)) == [
                "sequence", "type", "original_name", "relative_output_path", "status",
            ]
        with (root / "readable/review.csv").open(newline="", encoding="utf-8") as handle:
            assert next(csv.reader(handle)) == [
                "sequence", "url", "category", "confidence", "context_name", "review_reasons",
            ]
        messages = (root / "readable/messages.md").read_text(encoding="utf-8")
        assert messages.index("First") < messages.index("Second")
        category_dir = root / "raw/links-by-category"
        category_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / "raw/links.csv", category_dir / "tool-platform.csv")
        audit = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "audit_links.py"), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert audit.returncode == 2, audit.stdout + audit.stderr
        before = digest_tree(root)
        build(root)
        assert before == digest_tree(root)
        assert safe_category_slug("../../escape") == "other"
        (root / "attachments").mkdir()
        (root / "attachments/ok.txt").write_text("ok", encoding="utf-8")
        assert contained_attachment(root, "attachments/ok.txt") == (root / "attachments/ok.txt").resolve()
        assert contained_attachment(root, "../escape.txt") is None
        media = render_media([{
            "original_name": "secret.txt", "relative_output_path": "../escape.txt", "status": "copied",
        }], root)
        assert "[secret.txt]" not in media
        (root / "source/manifest.json").write_text(json.dumps({"sourceWriteIssued": True}), encoding="utf-8")
        try:
            assert_source_read_only(root, root / "source")
        except RuntimeError:
            pass
        else:
            raise AssertionError("source write guard did not reject sourceWriteIssued=true")
    print("human_view_tests=PASS")


if __name__ == "__main__":
    main()
