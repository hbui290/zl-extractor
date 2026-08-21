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
from render_human_views import build, copy_legacy_input, link_card, read_csv, render_media, write_table_csv  # noqa: E402


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
                {"timestamp": "2026-07-16 10:02", "sender": "A", "text": "First [click](javascript:alert(1))", "message_type": "text"},
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
                "context_summary": "Shared [context](https://evil.example)", "confidence": "high", "occurrence_count": "2",
                "url": "https://example.com/tool", "first_seen": "2026-07-16 10:02",
                "last_seen": "2026-07-16 10:03", "sources": "message|pin",
                "original_category": "tool-platform", "classification_rule": "existing_classifier",
                "observed_categories": "tool-platform", "canonical_url": "https://example.com/tool",
                "message_ids": "m1|m2", "pin_ids": "p1",
            }
        write_csv(root / "01-messages/links.csv", link_fields, [link_row])
        write_csv(
            root / "03-reports/pins.csv",
            ["pin_id", "timestamp", "sender", "title", "text", "urls"],
            [{"pin_id": "p1", "timestamp": "2026-07-16 10:04", "sender": "A", "title": "Pinned tool", "text": "Try make.com", "urls": "make.com"}],
        )
        write_csv(
            root / "03-reports/links-occurrences.csv",
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
        assert (root / "readable/pins.md").exists()
        assert not (root / "readable/media.csv").exists()
        assert not (root / "readable/review.csv").exists()
        assert not (root / "readable/links.md").exists()
        assert not (root / "readable/links-by-category").exists()
        with (root / "readable/links.csv").open(newline="", encoding="utf-8") as handle:
            assert next(csv.reader(handle)) == [
                "sequence", "url", "category", "occurrence_count", "first_seen", "review_status",
            ]
        messages = (root / "readable/messages.md").read_text(encoding="utf-8")
        assert messages.index("First") < messages.index("Second")
        assert "[click](javascript:alert(1))" not in messages
        links = (root / "readable/links.csv").read_text(encoding="utf-8")
        assert "https://example.com/tool" in links
        bare_card = "\n".join(link_card({"url": "make.com", "category": "tool-platform"}))
        assert "https://make.com" in bare_card
        assert "unavailable" not in bare_card
        pins = (root / "readable/pins.md").read_text(encoding="utf-8")
        assert "make.com" in pins
        assert "**External links:** 1" in pins
        signed_card = "\n".join(link_card({
            "url": "https://photo-link-talk.zdn.vn/private/file.jpg?token=secret&sign=abc",
            "category": "other",
        }))
        assert "token=secret" not in signed_card
        assert "internal attachment" in signed_card.lower()
        legacy_media = root / "legacy-media.csv"
        legacy_media.write_text(
            "url,canonical_url\n"
            "https://photo-link-talk.zdn.vn/private/file.jpg?token=secret,"
            "https://photo-link-talk.zdn.vn/private/file.jpg?token=secret\n",
            encoding="utf-8",
        )
        sanitized_media = root / "raw-media.csv"
        copy_legacy_input(legacy_media, sanitized_media)
        sanitized_text = sanitized_media.read_text(encoding="utf-8")
        assert "token=secret" not in sanitized_text
        assert "file.jpg" in sanitized_text
        formula_path = root / "readable/formula.csv"
        write_table_csv(formula_path, [{"context_name": "=1+1"}], ["context_name"])
        with formula_path.open(newline="", encoding="utf-8") as handle:
            assert next(csv.reader(handle))[0] == "context_name"
            assert next(csv.reader(handle))[0] == "'=1+1"
        audit = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "audit_links.py"), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert audit.returncode == 2, audit.stdout + audit.stderr
        assert "Link archive" in audit.stdout
        before = digest_tree(root)
        build(root)
        assert before == digest_tree(root)
        primary_path = root / "raw/links.csv"
        primary_rows = read_csv(primary_path)
        primary_rows[0]["occurrence_count"] = "1"
        write_csv(primary_path, list(primary_rows[0]), primary_rows)
        mismatch_audit = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "audit_links.py"), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert mismatch_audit.returncode == 1
        assert "per-URL user-facing occurrence counts" in mismatch_audit.stdout
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
