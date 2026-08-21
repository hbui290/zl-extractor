#!/usr/bin/env python3
"""Deterministic large-fixture stress test for the offline export pipeline."""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from extract_links import extract_links, read_csv  # noqa: E402
from run_plan import init_plan  # noqa: E402


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_stage(script, export_root):
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), str(export_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(f"{script} failed: {result.stdout[-1200:]}{result.stderr[-1200:]}")
    return time.perf_counter() - started


def build_fixture(root, message_count, pin_count):
    (root / "raw").mkdir(parents=True)
    (root / "source").mkdir(parents=True)
    (root / "source/manifest.json").write_text(json.dumps({
        "sourceWriteIssued": False,
        "source": {
            "conversationId": "stress-group",
            "conversationName": "Stress group",
            "startAt": "2026-07-16",
        },
    }), encoding="utf-8")
    init_plan(root, ["links", "pins"])
    (root / "source/item-checkpoints.jsonl").touch()
    (root / "source/pin-audit.json").write_text(json.dumps({
        "pinAuditStatus": "complete",
        "pinAuditCompleteness": "complete",
        "enumeratedPinCount": pin_count,
        "uniquePinLinkCount": pin_count,
        "uniquePinExternalLinkCount": pin_count,
        "endCondition": "stress_fixture",
    }), encoding="utf-8")

    message_rows = []
    for index in range(message_count):
        first = f"https://example.com/item/{index % 250}"
        second = f"https://labs.google/fx/tools/flow/shared/tool/{(index * 7) % 400}"
        if index % 4 == 0:
            second = f"https://photo-stal-1.zdn.vn/image/{index % 80}.jpg?token=secret"
        text = f"row {index} {first} {second}"
        if index % 5 == 0:
            text += f" duplicate {first}."
        if index % 11 == 0:
            text += " bare make.com, price 2.5k, foo@example.com"
        if index % 37 == 0:
            text += " www.example.com/path_(x)"
        message_rows.append({
            "timestamp": f"2026-07-{16 + index % 15:02d} 12:{index % 60:02d}:00",
            "message_id": f"m{index}",
            "sender": f"U{index % 17}",
            "text": text,
        })
    write_csv(root / "raw/messages.csv", ["timestamp", "message_id", "sender", "text"], message_rows)

    pin_rows = []
    for index in range(pin_count):
        url = f"https://labs.google/fx/tools/flow/shared/tool/p{index % 700}"
        pin_rows.append({
            "timestamp": "2026-07-14 12:00:00" if index % 9 == 0 else "2026-07-20 12:00:00",
            "pin_id": f"p{index}",
            "title": f"pin {index}",
            "text": f"{url} {url}",
            "urls": url,
            "message_scope": "pin_outside_message_window" if index % 9 == 0 else "pin_in_message_window",
        })
    write_csv(root / "raw/pins.csv", ["timestamp", "pin_id", "title", "text", "urls", "message_scope"], pin_rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", type=int, default=4000)
    parser.add_argument("--pins", type=int, default=800)
    args = parser.parse_args()
    if args.messages < 1 or args.pins < 1:
        raise SystemExit("--messages and --pins must be positive")

    with tempfile.TemporaryDirectory(prefix="zl-stress-") as temp:
        root = Path(temp)
        build_fixture(root, args.messages, args.pins)
        started = time.perf_counter()
        extracted = extract_links(root)
        extract_seconds = time.perf_counter() - started
        stage_seconds = {
            script: run_stage(script, root)
            for script in ("apply_category_rules.py", "write_link_review.py", "render_human_views.py")
        }
        audit = subprocess.run(
            [sys.executable, str(ROOT / "scripts/audit_links.py"), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        if audit.returncode not in (0, 2):
            raise AssertionError(audit.stdout[-3000:] + audit.stderr[-1000:])
        report = json.loads(audit.stdout)
        if report["failures"]:
            raise AssertionError(json.dumps(report["failures"], ensure_ascii=False))
        expected_message_occurrences = (
            args.messages * 2
            + (args.messages + 4) // 5
            + (args.messages + 10) // 11
            + (args.messages + 36) // 37
        )
        assert extracted["occurrences"] == expected_message_occurrences + args.pins
        assert len(read_csv(root / "raw/links-occurrences.csv")) == extracted["occurrences"]
        assert report["pin_audit_status"] == "complete"
        assert (root / "readable/index.md").exists()
        assert "token=secret" not in (root / "raw/links-occurrences.csv").read_text(encoding="utf-8")

        print(json.dumps({
            "messages": args.messages,
            "pins": args.pins,
            "occurrences": extracted["occurrences"],
            "user_links": extracted["user_links"],
            "media_links": extracted["media_links"],
            "extract_seconds": round(extract_seconds, 3),
            "stage_seconds": {key: round(value, 3) for key, value in stage_seconds.items()},
            "audit_status": report["status"],
            "audit_failures": len(report["failures"]),
            "audit_warnings": len(report["warnings"]),
            "status": "PASS",
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
