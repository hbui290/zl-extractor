#!/usr/bin/env python3
"""Create and validate a portable, scope-locked extraction plan."""

import argparse
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
SCOPES = ("messages", "links", "pins", "media")
CRITICAL_PATH = (
    "resolve",
    "preflight",
    "messages",
    "pins",
    "media_prepare",
    "media_fetch",
    "post_process",
)
PLAN_STATUSES = {"REQUIRED", "SKIPPED"}
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def plan_path(root):
    return Path(root).resolve() / "source" / "run-plan.json"


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


def _load_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _run_id(root):
    ledger_path = Path(root).resolve() / "source" / "phase-ledger.json"
    if ledger_path.exists():
        ledger = _load_json(ledger_path)
        if ledger.get("run_id"):
            return ledger["run_id"]
    return uuid.uuid4().hex


def _ordered_scopes(scopes):
    requested = set(scopes or ("messages",))
    unknown = requested - set(SCOPES)
    if unknown:
        raise ValueError(f"unknown scope: {', '.join(sorted(unknown))}")
    requested.add("messages")
    if "pins" in requested and "links" not in requested:
        raise ValueError("pins scope requires links scope")
    return [scope for scope in SCOPES if scope in requested]


def build_plan(root, scopes):
    scope = _ordered_scopes(scopes)
    links_requested = "links" in scope
    pins_requested = "pins" in scope
    media_requested = "media" in scope
    phase_policy = {
        phase: "REQUIRED" for phase in ("resolve", "preflight", "messages", "post_process")
    }
    phase_policy.update({
        "pins": "REQUIRED" if pins_requested else "SKIPPED",
        "media_prepare": "REQUIRED" if media_requested else "SKIPPED",
        "media_fetch": "REQUIRED" if media_requested else "SKIPPED",
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_id": uuid.uuid4().hex,
        "run_id": _run_id(root),
        "created_at": _now(),
        "scope": scope,
        "critical_path": list(CRITICAL_PATH),
        "phase_policy": phase_policy,
        "operations": {
            "messages": True,
            "links": links_requested,
            "pins": pins_requested,
            "media": media_requested,
        },
        "policies": {
            "url_key": "url.strip()",
            "url_variant_merging": "disabled",
            "classification": "deterministic_rules_then_review_queue",
            "ai_context": "only_uncertain_row_and_related_occurrences",
            "media_excluded_types": ["gif", "sticker"],
            "checkpoint_file": "source/item-checkpoints.jsonl",
            "artifact_hash": "sha256",
            "completed_items_are_immutable": True,
        },
    }


def init_plan(root, scopes=None, force=False):
    path = plan_path(root)
    if path.exists() and not force:
        return _load_json(path)
    plan = build_plan(root, scopes)
    _atomic_write(path, plan)
    return plan


def validate_plan(root):
    path = plan_path(root)
    if not path.exists():
        return [f"missing run plan: {path}"]
    try:
        plan = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid run plan: {path} ({exc})"]

    issues = []
    if plan.get("schema_version") != SCHEMA_VERSION:
        issues.append("unsupported run plan schema_version")
    for field in ("plan_id", "run_id", "created_at"):
        if not plan.get(field):
            issues.append(f"missing plan field: {field}")
    scope = plan.get("scope")
    if not isinstance(scope, list):
        issues.append("scope must be a unique, ordered list and include messages")
    else:
        try:
            expected_scope = _ordered_scopes(scope)
        except ValueError as exc:
            expected_scope = None
            issues.append(str(exc))
        if expected_scope is not None and scope != expected_scope:
            issues.append("scope must be a unique, ordered list and include messages")

    critical_path = plan.get("critical_path")
    if critical_path != list(CRITICAL_PATH):
        issues.append("critical_path does not match the supported phase order")
    phase_policy = plan.get("phase_policy")
    if not isinstance(phase_policy, dict):
        issues.append("missing phase_policy object")
    else:
        if set(phase_policy) != set(CRITICAL_PATH):
            issues.append("phase_policy must cover every critical-path phase")
        if any(value not in PLAN_STATUSES for value in phase_policy.values()):
            issues.append("phase_policy contains an invalid status")
        for phase in ("resolve", "preflight", "messages", "post_process"):
            if phase_policy.get(phase) != "REQUIRED":
                issues.append(f"phase_policy.{phase} must be REQUIRED")
        for phase in ("pins", "media_prepare", "media_fetch"):
            requested = phase == "pins" and isinstance(scope, list) and "pins" in scope
            requested = requested or phase.startswith("media_") and isinstance(scope, list) and "media" in scope
            expected = "REQUIRED" if requested else "SKIPPED"
            if phase_policy.get(phase) != expected:
                issues.append(f"phase_policy.{phase} must be {expected}")

    operations = plan.get("operations")
    expected_operations = {
        "messages": True,
        "links": isinstance(scope, list) and "links" in scope,
        "pins": isinstance(scope, list) and "pins" in scope,
        "media": isinstance(scope, list) and "media" in scope,
    }
    if operations != expected_operations:
        issues.append("operations do not match scope")

    policies = plan.get("policies")
    if not isinstance(policies, dict):
        issues.append("missing policies object")
    else:
        if policies.get("url_key") != "url.strip()":
            issues.append("url_key must remain url.strip()")
        if policies.get("url_variant_merging") != "disabled":
            issues.append("url variant merging must remain disabled")
        if policies.get("checkpoint_file") != "source/item-checkpoints.jsonl":
            issues.append("unexpected checkpoint file")
        media_types = policies.get("media_excluded_types")
        if media_types != ["gif", "sticker"]:
            issues.append("GIF/sticker exclusion policy changed")
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("export_root", type=Path)
    init_parser.add_argument("--scope", nargs="+", choices=SCOPES, default=["messages"])
    init_parser.add_argument("--force", action="store_true")

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("export_root", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "init":
            result = init_plan(args.export_root, args.scope, force=args.force)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        issues = validate_plan(args.export_root)
        print(json.dumps({"status": "PASS" if not issues else "FAIL", "issues": issues}, ensure_ascii=False, indent=2))
        return 0 if not issues else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
