"""
Normalisation used before records are compared (BA FR-10).

The original values are always kept for display; these helpers only produce
comparison keys.
"""

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

STATE_NAMES = {
    "act": "ACT",
    "australian capital territory": "ACT",
    "nsw": "NSW",
    "new south wales": "NSW",
    "nt": "NT",
    "northern territory": "NT",
    "qld": "QLD",
    "queensland": "QLD",
    "sa": "SA",
    "south australia": "SA",
    "tas": "TAS",
    "tasmania": "TAS",
    "vic": "VIC",
    "victoria": "VIC",
    "wa": "WA",
    "western australia": "WA",
}

PLACEHOLDER_NAMES = {"(unspecified)", "unspecified", "n/a", "na", "none"}


def collapse(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm_name(value):
    """Ignore case, spacing and punctuation; treat '&' as 'and'."""
    text = collapse(value).lower().replace("&", " and ")
    # Periods and apostrophes join letters ("F.C." -> "fc", "St. Mary's" ->
    # "st marys"); other punctuation separates words.
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return collapse(text)


def norm_state(value):
    """A standard state/territory code, or '' when it is not recognised."""
    key = norm_name(value)
    return STATE_NAMES.get(key, "")


def norm_email(value):
    return collapse(value).lower()


def norm_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))

    if digits.startswith("61") and len(digits) >= 11:
        digits = "0" + digits[2:]

    return digits


def norm_url(value):
    text = collapse(value).lower()

    if not text:
        return ""

    parsed = urlparse(text if "://" in text else "//" + text)
    host = parsed.netloc.removeprefix("www.")

    return host + parsed.path.rstrip("/")


def norm_place(value):
    return norm_name(value)


def norm_postcode(value):
    digits = re.sub(r"\D", "", str(value or ""))

    return digits if len(digits) == 4 else ""


# Words shared by many unrelated organisations. They are ignored when judging
# how similar two names are ("Community Bank Yea & District" and
# "Community Bank Kyabram & District" are different towns), but exact
# matching still uses the full normalised name.
GENERIC_WORDS = {
    "community", "bank", "banks", "district", "districts", "and", "the", "ltd",
    "limited", "pty", "branch", "club", "inc", "incorporated", "of", "association",
}


def distinctive_name(value):
    tokens = [t for t in norm_name(value).split() if t not in GENERIC_WORDS]

    return " ".join(tokens)


def similarity(a, b):
    """Name similarity as a percentage (0-100)."""
    full_a, full_b = norm_name(a), norm_name(b)

    if not full_a or not full_b:
        return 0

    key_a, key_b = distinctive_name(a), distinctive_name(b)

    if key_a and key_b:
        return round(SequenceMatcher(None, key_a, key_b).ratio() * 100, 1)

    return round(SequenceMatcher(None, full_a, full_b).ratio() * 100, 1)


def clean_contact_name(value):
    """'(unspecified)' and similar placeholders are not real names."""
    text = collapse(value)

    return "" if text.lower() in PLACEHOLDER_NAMES else text


def parse_bool(value):
    """TRUE/FALSE style values. Returns True, False, or None if unreadable."""
    if isinstance(value, bool):
        return value

    if value is None:
        return None

    text = collapse(value).lower()

    if text in {"true", "yes", "y", "1", "t"}:
        return True

    if text in {"false", "no", "n", "0", "f"}:
        return False

    return None
