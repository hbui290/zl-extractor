#!/usr/bin/env python3
"""Contract test for the export phase ledger."""

import tempfile
from pathlib import Path

from phase_ledger import REQUIRED_PHASES, finalize_ledger, init_ledger, record_phase, validate_ledger


def main():
    with tempfile.TemporaryDirectory(prefix="zl-phase-ledger-") as temp:
        root = Path(temp)
        ledger = init_ledger(root)
        assert ledger["status"] == "RUNNING"
        assert set(ledger["phases"]) == set(REQUIRED_PHASES)
        assert validate_ledger(root), "a new ledger must not validate before phases are recorded"

        for phase in REQUIRED_PHASES:
            status = "SKIPPED" if phase.startswith("media_") else "COMPLETE"
            record_phase(root, phase, items=1, bytes_count=10, retries=0, duration_ms=5, status=status)
        finalize_ledger(root, "COMPLETE")
        assert validate_ledger(root) == []
        assert (root / "source/phase-ledger.json").is_file()
    print("phase_ledger_tests=PASS")


if __name__ == "__main__":
    main()
