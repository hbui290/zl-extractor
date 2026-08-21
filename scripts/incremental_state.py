#!/usr/bin/env python3
"""Track a message watermark and merge a later normalized message delta."""

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from export_paths import assert_source_read_only, has_signed_internal_media_query
from time_order import message_id_key, watermark_sort_key


SCHEMA_VERSION = 1
ID_FIELDS = ("message_id", "msg_id", "msgId", "messageId", "id")
TIME_FIELDS = ("timestamp", "sent_at_local", "sent_at_utc", "sendDttm", "sent_at")
SAFE_MESSAGE_FIELDS = {
    "sequence", "timestamp", "message_id", "message_ids", "msg_id", "msgId", "messageId",
    "conversation_id", "conversation_name", "sender", "sender_id", "sender_name", "senderName",
    "msg_type", "message_type", "type", "origin_msg_type", "text", "quote", "quote_text",
    "reference_text", "structured_links", "attachment_name", "original_name", "file_name", "filename", "sendDttm",
    "sent_at_local", "sent_at_utc", "sent_at",
}
SIGNED_URL_TOKEN = re.compile(r"https?://[^\s<>'\"`]+", re.IGNORECASE)


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def state_path(root):
    return Path(root).resolve() / "source" / "incremental-state.json"


def message_path(root):
    root = Path(root).resolve()
    for canonical in (root / "source" / "raw" / "messages.csv", root / "raw" / "messages.csv"):
        if canonical.exists():
            return canonical
    legacy = root / "01-messages" / "messages.csv"
    return legacy if legacy.exists() else root / "source" / "raw" / "messages.csv"


def _read_table(path):
    if not path.exists():
        return [], []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _pick(row, fields):
    for field in fields:
        value = str(row.get(field, "") or "").strip()
        if value:
            return value
    return ""


def _message_id(row):
    return _pick(row, ID_FIELDS)


def _timestamp(row):
    return _pick(row, TIME_FIELDS)


def _sort_key(row):
    return (watermark_sort_key(_timestamp(row)), message_id_key(_message_id(row)))


def _row_key(row):
    message_id = _message_id(row)
    if message_id:
        return f"id:{message_id}"
    stable = {key: str(value or "") for key, value in sorted(row.items()) if key != "sequence"}
    digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"row:{digest}"


def _contains_signed_internal_media_url(value):
    value = str(value or "").strip()
    candidates = [value, *SIGNED_URL_TOKEN.findall(value)]
    for candidate in candidates:
        candidate = candidate.rstrip(".,;:!?)]}")
        if has_signed_internal_media_query(candidate):
            return True
    return False


def _watermark(rows):
    if not rows:
        return None
    row = max(rows, key=_sort_key)
    return {"timestamp": _timestamp(row), "message_id": _message_id(row)}


def _build_state(root, conversation_id="", created_at=None):
    rows = _read_table(message_path(root))[1]
    ids = {_message_id(row) for row in rows if _message_id(row)}
    return {
        "schema_version": SCHEMA_VERSION,
        "conversation_id": conversation_id,
        "created_at": created_at or _now(),
        "updated_at": _now(),
        "message_count": len(rows),
        "unique_message_ids": len(ids),
        "watermark": _watermark(rows),
    }


def _load_state(root):
    path = state_path(root)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def init_state(root, conversation_id=""):
    root = Path(root).resolve()
    assert_source_read_only(root)
    existing = _load_state(root)
    if existing is not None:
        stored = str(existing.get("conversation_id") or "")
        if conversation_id and stored and conversation_id != stored:
            raise ValueError("conversation_id does not match incremental state")
        return existing
    if not str(conversation_id or "").strip():
        raise ValueError("conversation_id is required when initializing incremental state")
    state = _build_state(root, conversation_id)
    _write_json(state_path(root), state)
    return state


def refresh_state(root, conversation_id=None):
    root = Path(root).resolve()
    assert_source_read_only(root)
    existing = _load_state(root)
    if existing is None:
        raise ValueError("incremental state is not initialized; run init first")
    stored = str(existing.get("conversation_id") or "") if existing else ""
    if conversation_id and stored and conversation_id != stored:
        raise ValueError("conversation_id does not match incremental state")
    state = _build_state(root, conversation_id or stored, existing.get("created_at") if existing else None)
    _write_json(state_path(root), state)
    return state


def _atomic_write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", newline="", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in fields} for row in rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def merge_messages(root, delta_path):
    root = Path(root).resolve()
    assert_source_read_only(root)
    delta_path = Path(delta_path).resolve()
    if not delta_path.exists():
        raise ValueError(f"message delta not found: {delta_path}")
    state = _load_state(root)
    if state is None:
        raise ValueError("incremental state is not initialized; run init first")
    stored_conversation_id = str(state.get("conversation_id") or "")
    existing_path = message_path(root)
    existing_fields, existing_rows = _read_table(existing_path)
    delta_fields, delta_rows = _read_table(delta_path)
    if not delta_fields:
        raise ValueError(f"message delta has no CSV header: {delta_path}")
    unsupported = sorted(set(delta_fields) - SAFE_MESSAGE_FIELDS)
    if unsupported:
        raise ValueError(f"unsupported message field(s): {', '.join(unsupported)}")
    for line_number, row in enumerate(delta_rows, start=2):
        if not _message_id(row):
            raise ValueError(f"message delta row {line_number} is missing message_id")
        if "conversation_id" in delta_fields and str(row.get("conversation_id") or "").strip() != stored_conversation_id:
            raise ValueError(f"conversation_id does not match incremental state at delta row {line_number}")
        if any(_contains_signed_internal_media_url(value) for value in row.values()):
            raise ValueError(f"signed internal media URL in message delta row {line_number}")
    fields = list(existing_fields)
    fields.extend(field for field in delta_fields if field not in fields)
    merged = {}
    for row in existing_rows:
        merged[_row_key(row)] = row
    inserted = updated = unchanged = 0
    for row in delta_rows:
        key = _row_key(row)
        prior = merged.get(key)
        if prior is None:
            inserted += 1
            merged[key] = dict(row)
            continue
        merged_row = dict(prior)
        for field in delta_fields:
            merged_row[field] = row.get(field, "")
        comparable_fields = [field for field in fields if field != "sequence"]
        if {field: prior.get(field, "") for field in comparable_fields} != {field: merged_row.get(field, "") for field in comparable_fields}:
            updated += 1
        else:
            unchanged += 1
        merged[key] = merged_row
    rows = sorted(merged.values(), key=_sort_key)
    if "sequence" in fields:
        for index, row in enumerate(rows, start=1):
            row["sequence"] = f"{index:06d}"
    target = message_path(root)
    _atomic_write_csv(target, fields, rows)
    state = refresh_state(root)
    return {
        "path": str(target),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "total": len(rows),
        "watermark": state["watermark"],
    }


def validate_state(root):
    root = Path(root).resolve()
    path = state_path(root)
    if not path.exists():
        return [f"missing incremental state: {path}"]
    try:
        state = _load_state(root)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid incremental state: {path} ({exc})"]
    issues = []
    if state.get("schema_version") != SCHEMA_VERSION:
        issues.append("unsupported incremental state schema_version")
    for field in ("conversation_id", "created_at", "updated_at", "message_count", "unique_message_ids"):
        if field not in state or (field == "conversation_id" and not str(state.get(field) or "").strip()):
            issues.append(f"missing incremental state field: {field}")
    fields, rows = _read_table(message_path(root))
    if not fields and rows:
        issues.append("message table has rows without a header")
    ids = [_message_id(row) for row in rows if _message_id(row)]
    if len(ids) != len(set(ids)):
        issues.append("duplicate message_id remains in merged message table")
    if state.get("message_count") != len(rows):
        issues.append("incremental message_count does not match raw messages")
    if state.get("unique_message_ids") != len(set(ids)):
        issues.append("incremental unique_message_ids does not match raw messages")
    if state.get("watermark") != _watermark(rows):
        issues.append("incremental watermark does not match raw messages")
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("export_root", type=Path)
    init_parser.add_argument("--conversation-id", default="")

    for command in ("inspect", "refresh", "validate"):
        subparsers.add_parser(command).add_argument("export_root", type=Path)

    merge_parser = subparsers.add_parser("merge")
    merge_parser.add_argument("export_root", type=Path)
    merge_parser.add_argument("delta_csv", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "init":
            result = init_state(args.export_root, args.conversation_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "inspect":
            result = _load_state(args.export_root)
            if result is None:
                raise ValueError("incremental state is not initialized; run init first")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "refresh":
            print(json.dumps(refresh_state(args.export_root), ensure_ascii=False, indent=2))
            return 0
        if args.command == "merge":
            print(json.dumps(merge_messages(args.export_root, args.delta_csv), ensure_ascii=False, indent=2))
            return 0
        issues = validate_state(args.export_root)
        print(json.dumps({"status": "PASS" if not issues else "FAIL", "issues": issues}, ensure_ascii=False, indent=2))
        return 0 if not issues else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
