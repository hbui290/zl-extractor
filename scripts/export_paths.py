"""Resolve canonical v2 or legacy ZL Extractor paths."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


INTERNAL_MEDIA_SUFFIXES = (".zdn.vn", ".zadn.vn", ".dlmd.me", ".dlfl.vn")
INTERNAL_MEDIA_HOST_TOKENS = ("stal", "ava-talk", "zpg-r", "photo-link-talk")


def export_paths(root):
    root = Path(root).resolve()
    new_layout = any((root / name).exists() for name in ("readable", "raw", "source"))
    if new_layout:
        return {
            "machine": root / "raw",
            "metadata": root / "source",
            "categories": root / "raw" / "links-by-category",
            "new_layout": True,
        }
    return {
        "machine": root / "01-messages",
        "metadata": root / "03-reports",
        "categories": root / "01-messages" / "links-by-category",
        "new_layout": False,
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
    """Resolve a non-symlink attachment only when it stays under attachments/."""
    if not relative_path:
        return None
    relative = Path(str(relative_path))
    if relative.is_absolute():
        return None
    root = Path(root).resolve()
    raw_candidate = root / relative
    if raw_candidate.is_symlink():
        return None
    candidate = raw_candidate.resolve()
    attachments = (root / "attachments").resolve()
    try:
        candidate.relative_to(attachments)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


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
