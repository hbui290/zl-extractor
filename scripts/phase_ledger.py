#!/usr/bin/env python3
"""Create and validate a resumable ZL Extractor phase ledger."""

import argparse
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_PHASES = (
    "resolve",
    "preflight",
    "messages",
    "pins",
    "media_prepare",
    "media_fetch",
    "post_process",
)
PHASE_STATUSES = {"PENDING", "COMPLETE", "PARTIAL", "BLOCKED", "SKIPPED"}
FINAL_STATUSES = {"COMPLETE", "PARTIAL", "BLOCKED"}


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ledger_path(root):
    return Path(root).resolve() / "source" / "phase-ledger.json"


def _atomic_write(path, value):
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


def _load(root):
    path = ledger_path(root)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _blank_phase():
    return {
        "started_at": None,
        "finished_at": None,
        "duration_ms": 0,
        "items": 0,
        "bytes": 0,
        "retries": 0,
        "status": "PENDING",
    }


def init_ledger(root, force=False):
    path = ledger_path(root)
    if path.exists() and not force:
        return _load(root)
    ledger = {
        "schema_version": 1,
        "run_id": uuid.uuid4().hex,
        "started_at": _now(),
        "finished_at": None,
        "status": "RUNNING",
        "phases": {phase: _blank_phase() for phase in REQUIRED_PHASES},
    }
    _atomic_write(path, ledger)
    return ledger


def _nonnegative_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def record_phase(root, phase, items, bytes_count, retries, duration_ms, status,
                 started_at=None, finished_at=None):
    if phase not in REQUIRED_PHASES:
        raise ValueError(f"unknown phase: {phase}")
    if status not in PHASE_STATUSES - {"PENDING"}:
        raise ValueError(f"invalid phase status: {status}")
    for name, value in (
        ("items", items),
        ("bytes", bytes_count),
        ("retries", retries),
        ("duration_ms", duration_ms),
    ):
        _nonnegative_int(name, value)
    path = ledger_path(root)
    if not path.exists():
        raise ValueError(f"missing phase ledger: {path}")
    ledger = _load(root)
    ledger.setdefault("phases", {})[phase] = {
        "started_at": started_at or _now(),
        "finished_at": finished_at or _now(),
        "duration_ms": duration_ms,
        "items": items,
        "bytes": bytes_count,
        "retries": retries,
        "status": status,
    }
    _atomic_write(path, ledger)
    return ledger


def finalize_ledger(root, status):
    if status not in FINAL_STATUSES:
        raise ValueError(f"invalid final status: {status}")
    path = ledger_path(root)
    if not path.exists():
        raise ValueError(f"missing phase ledger: {path}")
    ledger = _load(root)
    if status == "COMPLETE":
        unfinished = [
            phase for phase, data in ledger.get("phases", {}).items()
            if not isinstance(data, dict) or data.get("status") not in {"COMPLETE", "SKIPPED"}
        ]
        if unfinished:
            raise ValueError(f"cannot finalize COMPLETE; unfinished phases: {', '.join(unfinished)}")
    ledger["status"] = status
    ledger["finished_at"] = _now()
    _atomic_write(path, ledger)
    return ledger


def validate_ledger(root):
    path = ledger_path(root)
    if not path.exists():
        return [f"missing phase ledger: {path}"]
    try:
        ledger = _load(root)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid phase ledger: {path} ({exc})"]
    issues = []
    if ledger.get("schema_version") != 1:
        issues.append("unsupported phase ledger schema_version")
    for field in ("run_id", "started_at", "status"):
        if not ledger.get(field):
            issues.append(f"missing ledger field: {field}")
    if ledger.get("status") not in {"RUNNING", *FINAL_STATUSES}:
        issues.append(f"invalid ledger status: {ledger.get('status')}")
    if ledger.get("status") in FINAL_STATUSES and not ledger.get("finished_at"):
        issues.append("missing ledger field: finished_at")
    phases = ledger.get("phases")
    if not isinstance(phases, dict):
        return issues + ["missing phases object"]
    for phase in REQUIRED_PHASES:
        data = phases.get(phase)
        if not isinstance(data, dict):
            issues.append(f"missing phase: {phase}")
            continue
        for field in ("started_at", "finished_at", "duration_ms", "items", "bytes", "retries", "status"):
            if field not in data or data[field] in (None, ""):
                issues.append(f"phase {phase} missing {field}")
        status = data.get("status")
        if status not in PHASE_STATUSES:
            issues.append(f"phase {phase} has invalid status: {status}")
        elif status == "PENDING":
            issues.append(f"phase {phase} was not recorded")
        elif status in {"PARTIAL", "BLOCKED"}:
            issues.append(f"phase {phase} ended with status={status}")
        for field in ("duration_ms", "items", "bytes", "retries"):
            value = data.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                issues.append(f"phase {phase} has invalid {field}")
    if ledger.get("status") == "RUNNING":
        issues.append("ledger was not finalized")
    elif ledger.get("status") in {"PARTIAL", "BLOCKED"}:
        issues.append(f"ledger status={ledger.get('status')}")
    if ledger.get("status") == "COMPLETE" and any(
        not isinstance(phases.get(phase), dict)
        or phases[phase].get("status") not in {"COMPLETE", "SKIPPED"}
        for phase in REQUIRED_PHASES
    ):
        issues.append("ledger claims COMPLETE with incomplete phases")
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("export_root", type=Path)
    init_parser.add_argument("--force", action="store_true")

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("export_root", type=Path)
    record_parser.add_argument("phase", choices=REQUIRED_PHASES)
    record_parser.add_argument("--items", type=int, required=True)
    record_parser.add_argument("--bytes", dest="bytes_count", type=int, required=True)
    record_parser.add_argument("--retries", type=int, required=True)
    record_parser.add_argument("--duration-ms", type=int, required=True)
    record_parser.add_argument("--status", choices=sorted(PHASE_STATUSES - {"PENDING"}), required=True)

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("export_root", type=Path)
    finalize_parser.add_argument("--status", choices=sorted(FINAL_STATUSES), required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("export_root", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "init":
            result = init_ledger(args.export_root, force=args.force)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "record":
            result = record_phase(
                args.export_root, args.phase, args.items, args.bytes_count,
                args.retries, args.duration_ms, args.status,
            )
            print(json.dumps(result["phases"][args.phase], ensure_ascii=False, indent=2))
            return 0
        if args.command == "finalize":
            result = finalize_ledger(args.export_root, args.status)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        issues = validate_ledger(args.export_root)
        print(json.dumps({"status": "PASS" if not issues else "PARTIAL", "issues": issues}, ensure_ascii=False, indent=2))
        return 0 if not issues else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
