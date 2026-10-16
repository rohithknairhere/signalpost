from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

# Words that never identify a specific company on their own.
LEGAL_SUFFIXES = {
    "as", "asa", "ans", "da", "enk", "iks", "sa", "sam", "sti", "nuf", "ba", "bbl", "brl",
    "ks", "kf", "fli", "esek", "ltd", "limited", "inc", "ab", "aps", "gmbh", "plc", "llc",
}
GENERIC_TOKENS = LEGAL_SUFFIXES | {
    "og", "and", "the", "i", "pa", "av", "for", "til", "med", "of", "&",
    "holding", "holdings", "invest", "investment", "investering", "eiendom", "eiendommer",
    "norge", "norway", "norsk", "norske", "nordic", "group", "gruppen", "selskap", "selskapet",
    "stiftelsen", "stiftelse", "borettslag", "sameie", "service", "services", "consulting",
    "drift", "utvikling", "handel", "co", "company", "kompani", "partner", "partners",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def stable_id(*parts: Any, prefix: str = "ev") -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


_TRANSLATE = str.maketrans({"ø": "o", "Ø": "o", "å": "a", "Å": "a", "æ": "ae", "Æ": "ae", "&": " og "})


def ascii_fold(value: Any) -> str:
    text = str(value or "").translate(_TRANSLATE)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def tokens(value: Any) -> list[str]:
    """All alphanumeric tokens after Norwegian-aware ASCII folding."""
    return re.findall(r"[a-z0-9]+", ascii_fold(value))


def name_tokens(value: Any) -> list[str]:
    """Tokens of a legal name without legal-form suffixes."""
    return [token for token in tokens(value) if token not in LEGAL_SUFFIXES]


def distinctive_tokens(value: Any) -> list[str]:
    return [token for token in name_tokens(value) if token not in GENERIC_TOKENS and len(token) > 1]


def normalized_name(value: Any) -> str:
    return " ".join(name_tokens(value))


def digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def compact_org_pattern(org: str) -> re.Pattern[str]:
    """Matches an organisation number written with spaces, dots or 'NO'/'MVA' around it."""
    groups = [org[0:3], org[3:6], org[6:9]]
    separator = r"[\s. -]?"
    return re.compile(r"(?<!\d)" + separator.join(groups) + r"(?!\d)")


NORWEGIAN_ORG_IN_TEXT = re.compile(r"(?<!\d)([89]\d{2})[\s. -]?(\d{3})[\s. -]?(\d{3})(?!\d)")


def mod11_valid(org: str) -> bool:
    if not re.fullmatch(r"\d{9}", org or ""):
        return False
    weights = [3, 2, 7, 6, 5, 4, 3, 2]
    total = sum(int(d) * w for d, w in zip(org[:8], weights))
    remainder = total % 11
    check = 0 if remainder == 0 else 11 - remainder
    return check != 10 and check == int(org[8])


def org_numbers_in_text(text: str) -> set[str]:
    found = set()
    for match in NORWEGIAN_ORG_IN_TEXT.finditer(text or ""):
        candidate = "".join(match.groups())
        if mod11_valid(candidate):
            found.add(candidate)
    return found


def clean_text(value: Any, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit] if limit else text


def first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None
