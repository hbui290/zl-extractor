"""Small shared ordering helpers for legacy and current Zalo exports."""

from datetime import datetime
import math
import re


_NUMERIC = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def timestamp_ms(value):
    text = str(value or "").strip()
    if not text:
        return None
    if _NUMERIC.fullmatch(text):
        number = float(text)
        if not math.isfinite(number):
            return None
        return number * 1000 if abs(number) < 100_000_000_000 else number
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp() * 1000


def timestamp_sort_key(value):
    parsed = timestamp_ms(value)
    return (0, parsed) if parsed is not None else (1, 0)


def watermark_sort_key(value):
    parsed = timestamp_ms(value)
    return (1, parsed) if parsed is not None else (0, 0)


def message_id_key(value):
    text = str(value or "").strip()
    if text.isdigit():
        return (0, int(text))
    return (1, text)
