#!/usr/bin/env python3
"""Contract tests for scope locking and item-level resume."""

import hashlib
import json
import tempfile
from pathlib import Path

import item_checkpoint
from item_checkpoint import latest_items, record_item, resumable_items, validate_checkpoints
from run_plan import build_plan, init_plan, validate_plan


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main():
    with tempfile.TemporaryDirectory(prefix="zl-run-state-") as temp:
        root = Path(temp)
        plan = init_plan(root, ["messages", "links", "pins"])
        assert plan["operations"] == {"messages": True, "links": True, "pins": True, "media": False}
        assert plan["phase_policy"]["pins"] == "REQUIRED"
        assert plan["phase_policy"]["media_fetch"] == "SKIPPED"
        assert validate_plan(root) == []
        assert init_plan(root, ["messages"], force=False) == plan
        try:
            build_plan(root, ["pins"])
        except ValueError as exc:
            assert "requires links" in str(exc)
        else:
            raise AssertionError("pins without links must be rejected")

        cached_root = root / "cached"
        original_reader = item_checkpoint._read_events
        read_calls = []
        def counted_reader(path):
            read_calls.append(path)
            return original_reader(path)
        item_checkpoint._read_events = counted_reader
        try:
            for index in range(10):
                key = f"page-{index}"
                record_item(cached_root, "messages", key, digest(key), "COMPLETE")
        finally:
            item_checkpoint._read_events = original_reader
        assert len(read_calls) == 1, "repeated item records should reuse the in-process checkpoint index"

        input_hash = digest("media-1")
        output_hash = digest("bytes-1")
        first = record_item(root, "media", "m1", input_hash, "RUNNING")
        assert first["changed"] is True and first["event"]["attempt"] == 1
        second = record_item(root, "media", "m1", input_hash, "COMPLETE", output_path="attachments/a.jpg", output_sha256=output_hash)
        assert second["changed"] is True
        third = record_item(root, "media", "m1", input_hash, "COMPLETE", output_path="attachments/a.jpg", output_sha256=output_hash)
        assert third["changed"] is False and third["reason"] == "already_complete"
        record_item(root, "media", "m2", digest("media-2"), "FAILED", error="network timeout")
        failed_retry = record_item(root, "media", "m2", digest("media-2"), "RUNNING")
        assert failed_retry["event"]["attempt"] == 2
        record_item(root, "links", "url-1", digest("url-1"), "COMPLETE")
        assert [item["item_key"] for item in resumable_items(root, "media")] == ["m2"]
        assert len(latest_items(root)) == 3
        assert validate_checkpoints(root) == []

        checkpoint = root / "source/item-checkpoints.jsonl"
        with checkpoint.open("a", encoding="utf-8") as handle:
            handle.write('{"schema_version": 1')
        assert validate_checkpoints(root)
        assert latest_items(root, "media")[0]["item_key"] == "m1"
    print("run_state_tests=PASS")


if __name__ == "__main__":
    main()
