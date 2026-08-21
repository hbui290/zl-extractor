"""Resolve canonical v2 or legacy ZL Extractor paths."""

import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


csv.field_size_limit(sys.maxsize)


INTERNAL_MEDIA_SUFFIXES = (".zdn.vn", ".zadn.vn", ".dlmd.me", ".dlfl.vn")
INTERNAL_MEDIA_HOST_TOKENS = ("stal", "ava-talk", "zpg-r", "photo-link-talk")


def export_paths(root):
    root = Path(root).resolve()
    nested_machine = root / "source" / "raw"
    compact_machine = root / "raw"
    nested_layout = nested_machine.exists() or (
        (root / "source" / "manifest.json").exists() and not compact_machine.exists()
    )
    if nested_layout:
        return {
            "machine": nested_machine,
            "metadata": root / "source",
            "attachments": root / "source" / "attachments",
            "categories": nested_machine / "links-by-category",
            "new_layout": True,
            "nested_layout": True,
        }
    if compact_machine.exists() or (root / "readable").exists() or (root / "source").exists():
        return {
            "machine": compact_machine,
            "metadata": root / "source",
            "attachments": root / "attachments",
            "categories": compact_machine / "links-by-category",
            "new_layout": True,
            "nested_layout": False,
        }
    return {
        "machine": root / "01-messages",
        "metadata": root / "03-reports",
        "attachments": root / "attachments",
        "categories": root / "01-messages" / "links-by-category",
        "new_layout": False,
        "nested_layout": False,
    }


def safe_category_slug(value, fallback="other"):
    """Return a filename-safe category without trusting export data."""
    value = str(value or "").strip().lower()
    return value if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) else fallback


def is_internal_media_url(url):
    """Identify Zalo's signed media hosts without treating external URLs as media."""
    try:
        host = (urlsplit(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return False
    return host.endswith(INTERNAL_MEDIA_SUFFIXES) and any(
        token in host for token in INTERNAL_MEDIA_HOST_TOKENS
    )


def has_signed_internal_media_query(url):
    """Return whether an internal Zalo media URL still carries a query token."""
    if not is_internal_media_url(url):
        return False
    try:
        return bool(urlsplit(str(url or "").strip()).query)
    except ValueError:
        return False


def redact_internal_media_url(url):
    """Remove query/fragment tokens from a Zalo media URL; preserve other URLs exactly."""
    value = str(url or "")
    if not is_internal_media_url(value):
        return value
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def contained_attachment(root, relative_path):
    """Resolve a non-symlink attachment only under the export's attachment root."""
    if not relative_path:
        return None
    relative = Path(str(relative_path))
    if relative.is_absolute():
        return None
    root = Path(root).resolve()
    paths = export_paths(root)
    candidates = [root / relative]
    if paths.get("nested_layout") and relative.parts and relative.parts[0] == "attachments":
        candidates.append(paths["attachments"] / Path(*relative.parts[1:]))
    attachments = paths["attachments"].resolve()
    for raw_candidate in candidates:
        if raw_candidate.is_symlink():
            continue
        candidate = raw_candidate.resolve()
        try:
            candidate.relative_to(attachments)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def assert_source_read_only(root, metadata=None):
    """Abort derived writes when a manifest says the source was modified."""
    metadata = Path(metadata) if metadata else Path(root) / "source"
    manifest_path = metadata / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot verify source-write guard: {manifest_path}") from exc
    if manifest.get("sourceWriteIssued") is True:
        raise RuntimeError(f"refusing derived write: sourceWriteIssued=true in {manifest_path}")
