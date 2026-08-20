"""Small, conservative URL rules shared by extraction and readable views."""

import re
from urllib.parse import urlsplit


EXPLICIT_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
BARE_URL_RE = re.compile(
    r"(?<![@\w])(?:www\.)?(?:[a-z0-9-]+\.)+[a-z]{2,}"
    r"(?:/[^\s<>\"'`)]*)?",
    re.IGNORECASE,
)

# Keep this allowlist narrow so prices, filenames, and prose such as "2.5k"
# do not become links. Add a suffix only when a real export demonstrates it.
BARE_TLDS = frozenset({
    "ai", "app", "biz", "cc", "co", "com", "dev", "digital", "fun",
    "gg", "io", "me", "net", "online", "org", "pro", "site", "tech",
    "tv", "video", "vn", "xin", "xyz",
})


def trim_url(value):
    text = str(value or "").strip()
    while text and text[-1] in ".,;:!?":
        text = text[:-1]
    for closing, opening in ((")", "("), ("]", "["), ("}", "{")):
        while text.endswith(closing) and text.count(closing) > text.count(opening):
            text = text[:-1]
    return text


def is_bare_url(value):
    text = trim_url(value)
    if not text or re.match(r"https?://", text, re.IGNORECASE):
        return False
    try:
        parsed = urlsplit(f"//{text}")
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().removeprefix("www.")
    labels = host.split(".")
    return (
        len(labels) >= 2
        and labels[-1] in BARE_TLDS
        and any(char.isalpha() for char in labels[0])
    )


def find_url_occurrences(value):
    """Return every explicit or conservative bare-domain occurrence."""
    text = str(value or "")
    found = []
    spans = []
    for match in EXPLICIT_URL_RE.finditer(text):
        url = trim_url(match.group(0))
        if url:
            found.append(url)
            spans.append(match.span())
    for match in BARE_URL_RE.finditer(text):
        if any(start < match.end() and match.start() < end for start, end in spans):
            continue
        url = trim_url(match.group(0))
        if url:
            if is_bare_url(url):
                found.append(url)
                spans.append(match.span())
    return found


def find_urls(value):
    """Return unique explicit and conservative bare-domain URLs in source order."""
    return list(dict.fromkeys(find_url_occurrences(value)))


def parseable_url(value):
    text = str(value or "").strip()
    return f"https://{text}" if is_bare_url(text) else text


def strip_urls(value):
    text = str(value or "")
    explicit_spans = [match.span() for match in EXPLICIT_URL_RE.finditer(text)]
    spans = [(span, False) for span in explicit_spans]
    spans.extend(
        (match.span(), True)
        for match in BARE_URL_RE.finditer(text)
        if is_bare_url(match.group(0))
        and not any(start < match.end() and match.start() < end for start, end in explicit_spans)
    )
    for (start, end), is_bare in sorted(spans, reverse=True):
        text = text[:start] + " " + text[end:]
    return re.sub(r"\s+", " ", text).strip(" \t|:,-")
