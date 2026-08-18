#!/usr/bin/env python3
"""Small adversarial smoke test for deterministic URL classification rules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_category_rules import category_rule  # noqa: E402


CASES = {
    "https://chatgpt.com/share/example": "tool-platform",
    "https://chatgpt.com/g/example": "tool-platform",
    "https://seller-vn.tiktok.com/university/essay?id=1": "training-guide",
    "https://web.telegram.org/k/#@example_bot": "tool-platform",
    "https://web.telegram.org/k/#@example_bot?start=1": "tool-platform",
    "https://web.telegram.org/k/#@example_channel": "social-community",
    "https://t.me/example_bot": "tool-platform",
    "https://t.me/robotics": "social-community",
    "https://sub.shopee.vn/product/1": "shopee-affiliate",
    "https://evilshopee.vn/product/1": None,
    "https://sub.facebook.com/group/1": "social-community",
    "https://facebook.com.evil/group/1": None,
    "https://photo-link-talk.zadn.vn/image/1": "zalo-media",
    "https://labs.google/fx/en/tools/flow/shared/tool/1": "tool-platform",
    "https://labs.google/other/project/1": None,
    "not a URL": None,
}


def main():
    for url, expected in CASES.items():
        category, rule = category_rule(url)
        assert category == expected, (url, category, rule, expected)
    print(f"rule_tests={len(CASES)} status=PASS")


if __name__ == "__main__":
    main()
