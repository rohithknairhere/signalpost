"""Wikidata (CC0) lookup by Norwegian organisation number (property P2333).

One SPARQL request covers a whole batch. Matching is exact on the organisation
number, so a returned item is about this company, not a namesake.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .net import BudgetExhausted, Fetcher
from .util import sha256_bytes

ENDPOINT = "https://query.wikidata.org/sparql"

PLATFORM_PROPS = {
    "website": "P856",
    "facebook": "P2013",
    "linkedin": "P4264",
    "instagram": "P2003",
    "x": "P2002",
    "youtube": "P2397",
    "tiktok": "P7085",
    "lei": "P1278",
    "inception": "P571",
    "employees": "P1128",
}

PROFILE_URL = {
    "facebook": "https://www.facebook.com/{}",
    "linkedin": "https://www.linkedin.com/company/{}",
    "instagram": "https://www.instagram.com/{}",
    "x": "https://x.com/{}",
    "youtube": "https://www.youtube.com/channel/{}",
    "tiktok": "https://www.tiktok.com/@{}",
}


def _query(orgs: list[str]) -> str:
    values = " ".join(f'"{org}"' for org in orgs)
    optionals = "\n".join(
        f"OPTIONAL {{ ?item wdt:{prop} ?{name}_ . }}" for name, prop in PLATFORM_PROPS.items()
    )
    selects = " ".join(f"(GROUP_CONCAT(DISTINCT STR(?{name}_); separator='|') AS ?{name})" for name in PLATFORM_PROPS)
    return f"""
SELECT ?org ?item (SAMPLE(?label_) AS ?label) (SAMPLE(?desc_) AS ?description)
       (SAMPLE(?nowiki_) AS ?nowiki) (SAMPLE(?enwiki_) AS ?enwiki) {selects}
WHERE {{
  VALUES ?org {{ {values} }}
  ?item wdt:P2333 ?org .
  OPTIONAL {{ ?item rdfs:label ?label_ . FILTER(LANG(?label_) IN ("nb", "nn", "en")) }}
  OPTIONAL {{ ?item schema:description ?desc_ . FILTER(LANG(?desc_) IN ("nb", "en")) }}
  OPTIONAL {{ ?nowiki_ schema:about ?item ; schema:isPartOf <https://no.wikipedia.org/> . }}
  OPTIONAL {{ ?enwiki_ schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }}
  {optionals}
}}
GROUP BY ?org ?item
"""


def lookup(fetcher: Fetcher, orgs: list[str], chunk: int = 200) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    status = {"status": "available", "requests": 0, "error": None}
    valid = [org for org in orgs if len(org) == 9 and org.isdigit()]
    for start in range(0, len(valid), chunk):
        part = valid[start:start + chunk]
        url = ENDPOINT + "?" + urllib.parse.urlencode({"query": _query(part), "format": "json"})
        try:
            response = fetcher.get(url, module="wikidata", respect_robots=False, accept="application/sparql-results+json", timeout=45, attempts=2)
        except BudgetExhausted as exc:
            status.update(status="failed", error=str(exc))
            break
        status["requests"] += 1
        if response.status in (403, 429):
            status.update(status="blocked", error=f"HTTP {response.status}")
            continue
        if not response.ok:
            status.update(status="failed", error=response.error or f"HTTP {response.status}")
            continue
        try:
            body = json.loads(response.body.decode("utf-8"))
        except ValueError:
            status.update(status="failed", error="invalid JSON")
            continue
        digest = sha256_bytes(response.body)
        for row in body.get("results", {}).get("bindings", []):
            org = row["org"]["value"]
            record = {key: value["value"] for key, value in row.items()}
            item = record.get("item", "")
            entry = {
                "item": item,
                "qid": item.rsplit("/", 1)[-1],
                "label": record.get("label"),
                "description": record.get("description"),
                "wikipedia_no": record.get("nowiki"),
                "wikipedia_en": record.get("enwiki"),
                "retrieved_at": response.retrieved_at,
                "sha256": digest,
                "query_url": ENDPOINT,
            }
            for name in PLATFORM_PROPS:
                values = [value for value in (record.get(name) or "").split("|") if value]
                entry[name] = values
            # Prefer the item with the most data if several items carry the number.
            previous = found.get(org)
            if previous is None or sum(bool(previous[name]) for name in PLATFORM_PROPS) < sum(bool(entry[name]) for name in PLATFORM_PROPS):
                found[org] = entry
    return found, status


def profiles(entry: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for platform, template in PROFILE_URL.items():
        for handle in entry.get(platform) or []:
            handle = handle.strip().lstrip("@")
            if handle:
                out.append({"platform": platform, "url": template.format(handle), "handle": handle})
                break
    return out


def best_website(entry: dict[str, Any]) -> str | None:
    sites = entry.get("website") or []
    if not sites:
        return None
    # Prefer Norwegian / .com roots over country mirrors and deep paths.
    def rank(url: str) -> tuple[int, int, int]:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        return (0 if host.endswith(".no") else 1 if host.endswith(".com") else 2, len(parsed.path.strip("/")), len(url))
    return sorted(sites, key=rank)[0]
