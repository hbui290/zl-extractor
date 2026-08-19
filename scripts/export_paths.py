"""Resolve canonical v2 or legacy ZL Extractor paths."""

from pathlib import Path


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
