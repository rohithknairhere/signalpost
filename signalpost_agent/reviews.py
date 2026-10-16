"""Customer ratings from Fagfolkguiden (Norwegian trades and services directory).

Profiles are addressed by organisation number (/bedrift/<slug>-<orgnr>) and declare
the number in their structured data (schema.org identifier), which we check before
publishing. robots.txt allows /bedrift/. A missing profile is `not_available`.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from .net import BudgetExhausted, Fetcher
from .util import ascii_fold, digits

BASE = "https://www.fagfolkguiden.no/bedrift/{slug}-{org}"

# Industries (NACE 2-digit) where consumer/trade ratings do not apply.
NOT_APPLICABLE_SECTIONS = {"64", "65", "66", "68", "70", "84", "94", "97", "98", "99", "00"}
NOT_APPLICABLE_FORMS = {"BRL", "BBL", "ESEK", "SAM", "STI", "PK", "KIRK", "SPA", "VPFO", "ORGL"}


def slug(name: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", ascii_fold(name))) or "bedrift"


def applies(entity: dict[str, Any]) -> tuple[bool, str]:
    form = str((entity.get("organisasjonsform") or {}).get("kode") or "")
    code = str((entity.get("naeringskode1") or {}).get("kode") or "")
    if form in NOT_APPLICABLE_FORMS:
        return False, f"customer ratings do not apply to legal form {form}"
    if code[:2] in NOT_APPLICABLE_SECTIONS:
        return False, f"customer ratings do not apply to industry {code} (holding, finance, property or non-trading)"
    return True, ""


def fetch_rating(fetcher: Fetcher, org: str, name: str) -> dict[str, Any]:
    url = BASE.format(slug=slug(name), org=org)
    try:
        response = fetcher.get(url, module="reviews", timeout=15)
    except BudgetExhausted as exc:
        return {"status": "failed", "error": str(exc), "url": url}
    if response.status == 404:
        return {"status": "not_available", "url": url, "retrieved_at": response.retrieved_at}
    if response.error == "robots_disallowed" or response.status in (401, 403, 429):
        return {"status": "blocked", "url": url, "error": response.error or f"HTTP {response.status}"}
    if not response.ok:
        return {"status": "failed", "url": url, "error": response.error or f"HTTP {response.status}"}
    soup = BeautifulSoup(response.text(), "lxml")
    business = None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text() or "{}")
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict):
                continue
            identifier = node.get("identifier")
            values = identifier if isinstance(identifier, list) else [identifier]
            if any(digits((item or {}).get("value") if isinstance(item, dict) else item) == org for item in values):
                business = node
                break
        if business:
            break
    if not business:
        return {"status": "ambiguous", "url": response.final_url, "error": "profile does not declare this organisation number"}
    rating = business.get("aggregateRating") or {}
    google_link = soup.find("a", href=re.compile(r"(google\.[a-z.]+/maps|search\.google\.com/local/reviews|g\.page)"))
    out: dict[str, Any] = {
        "status": "available",
        "url": response.final_url,
        "retrieved_at": response.retrieved_at,
        "sha256": response.sha256,
        "listing_name": business.get("name"),
        "category": business.get("description"),
    }
    if rating.get("ratingValue") is not None and (rating.get("ratingCount") or rating.get("reviewCount")):
        out["rating"] = {
            "value": float(rating["ratingValue"]),
            "count": int(rating.get("ratingCount") or rating.get("reviewCount")),
            "best": rating.get("bestRating", 5),
            "worst": rating.get("worstRating", 1),
            "origin": "Google reviews (as shown by Fagfolkguiden)" if google_link else "Fagfolkguiden",
        }
    reviews = []
    for item in business.get("review") or []:
        if not isinstance(item, dict):
            continue
        reviews.append({
            "date": str(item.get("datePublished") or "")[:10] or None,
            "rating": (item.get("reviewRating") or {}).get("ratingValue"),
            "text": str(item.get("reviewBody") or "")[:300] or None,
        })
    if reviews:
        out["reviews"] = reviews[:10]
    return out
