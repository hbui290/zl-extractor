#!/usr/bin/env python3
"""Append-only, item-level checkpoints for safe resume and idempotence."""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
STATUSES = {"PENDING", "RUNNING", "COMPLETE", "PARTIAL", "FAILED", "SKIPPED"}
RESUMABLE_STATUSES = {"PENDING", "RUNNING", "PARTIAL", "FAILED"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SAFE_QUEUE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_LATEST_CACHE = {}


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def checkpoint_path(root):
    return Path(root).resolve() / "source" / "item-checkpoints.jsonl"


def _valid_hash(name, value):
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _valid_queue(queue):
    if not isinstance(queue, str) or not SAFE_QUEUE.fullmatch(queue):
        raise ValueError("queue must contain only lowercase letters, digits, '_' or '-'")


def _valid_item_key(item_key):
    if not isinstance(item_key, str) or not item_key.strip() or "\n" in item_key or "\r" in item_key:
        raise ValueError("item_key must be a non-empty single-line string")


def _valid_relative_path(value):
    if value in (None, ""):
        return ""
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("output_path must be relative to the export root")
    return path.as_posix()


def _event_valid(event):
    required = ("schema_version", "recorded_at", "queue", "item_key", "input_sha256", "status", "attempt")
    issues = [f"missing event field: {field}" for field in required if field not in event]
    if issues:
        return issues
    if event.get("schema_version") != SCHEMA_VERSION:
        issues.append("unsupported checkpoint schema_version")
    try:
        _valid_queue(event.get("queue"))
        _valid_item_key(event.get("item_key"))
        _valid_hash("input_sha256", event.get("input_sha256"))
    except ValueError as exc:
        issues.append(str(exc))
    if event.get("status") not in STATUSES:
        issues.append(f"invalid checkpoint status: {event.get('status')}")
    attempt = event.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        issues.append("attempt must be a non-negative integer")
    try:
        _valid_relative_path(event.get("output_path", ""))
        output_hash = event.get("output_sha256", "")
        if output_hash:
            _valid_hash("output_sha256", output_hash)
    except ValueError as exc:
        issues.append(str(exc))
    return issues


def _read_events(root):
    path = checkpoint_path(root)
    if not path.exists():
        return [], []
    events = []
    issues = []
    lines = path.read_text(encoding="utf-8").splitlines()
    nonempty_indices = [index for index, line in enumerate(lines) if line.strip()]
    last_nonempty = nonempty_indices[-1] if nonempty_indices else None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            # A crash can leave only the final JSONL line incomplete. It is safe
            # to ignore that tail for resume; validation still reports it.
            if index == last_nonempty:
                issues.append(f"truncated trailing checkpoint event at line {index + 1}: {exc}")
                continue
            issues.append(f"invalid checkpoint JSON at line {index + 1}: {exc}")
            continue
        if not isinstance(event, dict):
            issues.append(f"checkpoint line {index + 1} is not an object")
            continue
        event_issues = _event_valid(event)
        issues.extend(f"line {index + 1}: {issue}" for issue in event_issues)
        if not event_issues:
            events.append(event)
    return events, issues


def _cache_signature(path):
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def _latest_map(root):
    path = checkpoint_path(root)
    cache_key = str(path)
    signature = _cache_signature(path)
    cached = _LATEST_CACHE.get(cache_key)
    if cached and cached["signature"] == signature:
        return cached["latest"]

    events, _ = _read_events(root)
    latest = {}
    for event in events:
        latest[(event["queue"], event["item_key"])] = event
    _LATEST_CACHE[cache_key] = {"signature": _cache_signature(path), "latest": latest}
    return latest


def _remember_event(root, event):
    path = checkpoint_path(root)
    cache_key = str(path)
    cached = _LATEST_CACHE.get(cache_key)
    latest = cached["latest"] if cached else _latest_map(root)
    latest[(event["queue"], event["item_key"])] = event
    _LATEST_CACHE[cache_key] = {"signature": _cache_signature(path), "latest": latest}


def latest_items(root, queue=None):
    if queue is not None:
        _valid_queue(queue)
    latest = _latest_map(root)
    if queue is not None:
        latest = {key: event for key, event in latest.items() if key[0] == queue}
    return [latest[key] for key in sorted(latest)]


def resumable_items(root, queue=None):
    return [event for event in latest_items(root, queue) if event["status"] in RESUMABLE_STATUSES]


def _append(path, event):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def record_item(root, queue, item_key, input_sha256, status, attempt=None,
                output_path="", output_sha256="", error=""):
    _valid_queue(queue)
    _valid_item_key(item_key)
    _valid_hash("input_sha256", input_sha256)
    if status not in STATUSES:
        raise ValueError(f"invalid checkpoint status: {status}")
    output_path = _valid_relative_path(output_path)
    if output_sha256:
        _valid_hash("output_sha256", output_sha256)
    if "\n" in str(error) or "\r" in str(error):
        raise ValueError("error must be a single-line string")

    current = _latest_map(root).get((queue, item_key))
    same_input = current and current.get("input_sha256") == input_sha256
    if same_input and current.get("status") == "COMPLETE":
        # Completed artifacts are immutable; use a new input hash/item key to
        # deliberately invalidate one. This is the idempotence guard.
        return {"changed": False, "reason": "already_complete", "event": current}

    if attempt is None:
        work_statuses = {"RUNNING", "PARTIAL", "FAILED", "COMPLETE"}
        if current and same_input:
            current_attempt = current.get("attempt", 0)
            if status == "RUNNING":
                attempt = max(1, current_attempt + (0 if current.get("status") == "PENDING" else 1))
            elif current.get("status") == "RUNNING":
                attempt = max(1, current_attempt)
            elif status in work_statuses and current.get("status") in work_statuses:
                attempt = max(1, current_attempt + 1)
            else:
                attempt = current_attempt
        else:
            attempt = 1 if status in work_statuses else 0
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 0:
        raise ValueError("attempt must be a non-negative integer")

    event = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": _now(),
        "queue": queue,
        "item_key": item_key,
        "input_sha256": input_sha256,
        "status": status,
        "attempt": attempt,
        "output_path": output_path,
        "output_sha256": output_sha256,
        "error": str(error),
    }
    _append(checkpoint_path(root), event)
    _remember_event(root, event)
    return {"changed": True, "reason": "recorded", "event": event}


def validate_checkpoints(root):
    path = checkpoint_path(root)
    if not path.exists():
        return [f"missing item checkpoint file: {path}"]
    _, issues = _read_events(root)
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("export_root", type=Path)

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("export_root", type=Path)
    record_parser.add_argument("queue")
    record_parser.add_argument("item_key")
    record_parser.add_argument("--input-sha256", required=True)
    record_parser.add_argument("--status", choices=sorted(STATUSES), required=True)
    record_parser.add_argument("--attempt", type=int)
    record_parser.add_argument("--output-path", default="")
    record_parser.add_argument("--output-sha256", default="")
    record_parser.add_argument("--error", default="")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("export_root", type=Path)
    list_parser.add_argument("--queue")
    list_parser.add_argument("--resumable", action="store_true")

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("export_root", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "init":
            path = checkpoint_path(args.export_root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            print(json.dumps({"status": "READY", "path": str(path)}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "record":
            result = record_item(
                args.export_root, args.queue, args.item_key, args.input_sha256,
                args.status, args.attempt, args.output_path, args.output_sha256, args.error,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "list":
            events = resumable_items(args.export_root, args.queue) if args.resumable else latest_items(args.export_root, args.queue)
            print(json.dumps({"count": len(events), "items": events}, ensure_ascii=False, indent=2))
            return 0
        issues = validate_checkpoints(args.export_root)
        print(json.dumps({"status": "PASS" if not issues else "PARTIAL", "issues": issues}, ensure_ascii=False, indent=2))
        return 0 if not issues else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
