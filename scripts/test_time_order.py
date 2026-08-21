#!/usr/bin/env python3
"""Regression tests for mixed timestamp formats and numeric message IDs."""

from time_order import message_id_key, timestamp_ms, timestamp_sort_key, watermark_sort_key


def main():
    assert timestamp_ms("1700000000000") == timestamp_ms("2023-11-14T22:13:20Z")
    assert timestamp_ms("2027-01-15T08:00:00Z") > timestamp_ms("1700000000000")
    assert message_id_key("10") > message_id_key("9")

    rows = [
        {"timestamp": "1700000000000", "message_id": "9"},
        {"timestamp": "2023-11-14T22:13:20Z", "message_id": "10"},
        {"timestamp": "2027-01-15T08:00:00Z", "message_id": "11"},
    ]
    ordered = sorted(rows, key=lambda row: (timestamp_sort_key(row["timestamp"]), message_id_key(row["message_id"])))
    assert [row["message_id"] for row in ordered] == ["9", "10", "11"]
    watermark = max(rows, key=lambda row: (watermark_sort_key(row["timestamp"]), message_id_key(row["message_id"])))
    assert watermark["message_id"] == "11"
    print("time_order_tests=PASS")


if __name__ == "__main__":
    main()
