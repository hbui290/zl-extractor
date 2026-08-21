#!/usr/bin/env python3
"""Contract tests for incremental message state and idempotent merging."""

import csv
import tempfile
from pathlib import Path

from incremental_state import init_state, merge_messages, refresh_state, validate_state


FIELDS = ["sequence", "timestamp", "message_id", "sender", "text", "structured_links"]


def write_csv(path, rows, fields=FIELDS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main():
    with tempfile.TemporaryDirectory(prefix="zl-incremental-") as temp:
        root = Path(temp)
        try:
            init_state(root, "")
        except ValueError as exc:
            assert "conversation_id is required" in str(exc)
        else:
            raise AssertionError("state initialization must require conversation_id")

        messages = root / "raw/messages.csv"
        write_csv(messages, [
            {"sequence": "000001", "timestamp": "2026-08-16 10:00:00", "message_id": "m1", "sender": "A", "text": "old"},
            {"sequence": "000002", "timestamp": "2026-08-16 10:01:00", "message_id": "m2", "sender": "B", "text": "keep"},
        ])
        state = init_state(root, "group-1")
        assert state["watermark"] == {"timestamp": "2026-08-16 10:01:00", "message_id": "m2"}
        assert state["message_count"] == 2
        assert validate_state(root) == []

        delta = root / "delta.csv"
        write_csv(delta, [
            {"sequence": "000002", "timestamp": "2026-08-16 10:01:00", "message_id": "m2", "sender": "B", "text": "updated"},
            {"sequence": "000003", "timestamp": "2026-08-17 09:00:00", "message_id": "m3", "sender": "C", "text": "new", "structured_links": "https://example.com/new"},
        ])
        result = merge_messages(root, delta)
        assert result["inserted"] == 1
        assert result["updated"] == 1
        assert [row["message_id"] for row in read_csv(messages)] == ["m1", "m2", "m3"]
        assert read_csv(messages)[1]["text"] == "updated"
        assert read_csv(messages)[1]["sender"] == "B"
        assert read_csv(messages)[2]["structured_links"] == "https://example.com/new"
        refreshed = refresh_state(root)
        assert refreshed["watermark"]["message_id"] == "m3"
        assert refreshed["message_count"] == 3
        assert validate_state(root) == []

        try:
            init_state(root, "another-group")
        except ValueError as exc:
            assert "does not match" in str(exc)
        else:
            raise AssertionError("state identity mismatch must be rejected")

        second = merge_messages(root, delta)
        assert second["inserted"] == 0
        assert second["updated"] == 0
        assert second["unchanged"] == 2

        sparse = root / "sparse.csv"
        write_csv(
            sparse,
            [{"timestamp": "2026-08-16 10:01:00", "message_id": "m2", "text": "sparse update"}],
            fields=["timestamp", "message_id", "text"],
        )
        sparse_result = merge_messages(root, sparse)
        sparse_row = read_csv(messages)[1]
        assert sparse_result["updated"] == 1
        assert sparse_row["sender"] == "B"
        assert sparse_row["text"] == "sparse update"

        unsafe = root / "unsafe.csv"
        write_csv(
            unsafe,
            [{"timestamp": "2026-08-18 10:00:00", "message_id": "m4", "text": "unsafe", "signed_url": "https://photo-stal-1.zdn.vn/x?token=secret"}],
            fields=["timestamp", "message_id", "text", "signed_url"],
        )
        try:
            merge_messages(root, unsafe)
        except ValueError as exc:
            assert "unsupported message field" in str(exc)
        else:
            raise AssertionError("unsafe delta fields must be rejected")

        embedded = root / "embedded-token.csv"
        write_csv(
            embedded,
            [{
                "timestamp": "2026-08-18 10:01:00",
                "message_id": "m5",
                "text": "see https://photo-stal-1.zdn.vn/x?token=secret",
            }],
            fields=["timestamp", "message_id", "text"],
        )
        try:
            merge_messages(root, embedded)
        except ValueError as exc:
            assert "signed internal media URL" in str(exc)
        else:
            raise AssertionError("signed media URLs embedded in text must be rejected")

        wrong_group = root / "wrong-group.csv"
        write_csv(
            wrong_group,
            [{
                "timestamp": "2026-08-18 10:02:00",
                "message_id": "m6",
                "conversation_id": "group-2",
            }],
            fields=["timestamp", "message_id", "conversation_id"],
        )
        try:
            merge_messages(root, wrong_group)
        except ValueError as exc:
            assert "conversation_id does not match" in str(exc)
        else:
            raise AssertionError("delta from another conversation must be rejected")
    print("incremental_state_tests=PASS")


if __name__ == "__main__":
    main()
