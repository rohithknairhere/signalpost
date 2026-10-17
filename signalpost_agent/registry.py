"""Official Norwegian registry sources (Brønnøysundregistrene).

Bulk snapshot (Enhetsregisteret CSV, NLOD 2.0) anchors identity with zero requests.
Live APIs add current status, roles, registered workplaces, annual accounts and
filing-copy years. Every value keeps its source URL, retrieval time and hash.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .net import BudgetExhausted, Fetcher, Response
from .util import sha256_bytes, utc_now

BULK_URL = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv"
ENTITY = "https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
ROLES = ENTITY + "/roller"
SUBUNITS = "https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=200"
ACCOUNTS = "https://data.brreg.no/regnskapsregisteret/regnskap/{org}"
ACCOUNT_YEARS = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/aar"
ACCOUNT_PDF = "https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/{year}"
ENTITY_PAGE = "https://virksomhet.brreg.no/nb/oppslag/enheter/{org}"


def _open_text(path: Path) -> io.TextIOBase:
    with path.open("rb") as probe:
        magic = probe.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")  # type: ignore[return-value]
    return path.open("r", encoding="utf-8-sig", newline="")


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nest(flat: dict[str, str]) -> dict[str, Any]:
    """Turn 'forretningsadresse.adresse' style CSV keys into the API's nested shape."""
    out: dict[str, Any] = {}
    for key, value in flat.items():
        if value in ("", None):
            continue
        node = out
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                break
        else:
            node[parts[-1]] = value
    for address_key in ("forretningsadresse", "postadresse"):
        address = out.get(address_key)
        if isinstance(address, dict) and isinstance(address.get("adresse"), str):
            address["adresse"] = [part.strip() for part in address["adresse"].split(",") if part.strip()]
    if "antallAnsatte" in out:
        try:
            out["antallAnsatte"] = int(out["antallAnsatte"])
        except ValueError:
            pass
    for flag in ("konkurs", "underAvvikling", "underTvangsavviklingEllerTvangsopplosning", "erIKonsern",
                 "registrertIMvaRegisteret", "registrertIForetaksregisteret", "harRegistrertAntallAnsatte"):
        if flag in out:
            out[flag] = str(out[flag]).strip().lower() in {"true", "ja", "1"}
    for list_key in ("aktivitet", "vedtektsfestetFormaal"):
        if isinstance(out.get(list_key), str):
            out[list_key] = [out[list_key]]
    return out


def load_bulk(path: str | Path | None, wanted: Iterable[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Return {org: api-shaped entity} for the requested organisation numbers.

    Accepts the Brreg CSV (gzip or plain) or a JSON/JSONL(.gz) list of entity rows.
    A missing file is allowed: the live API then anchors identity.
    """
    wanted_set = set(wanted)
    found: dict[str, dict[str, Any]] = {}
    if not path:
        return found, {"source": None, "rows_scanned": 0}
    source = Path(path)
    if not source.exists():
        return found, {"source": str(source), "error": "bulk file not found", "rows_scanned": 0}
    started = time.monotonic()
    scanned = 0
    with _open_text(source) as handle:
        head = handle.read(4096)
        handle.seek(0)
        stripped = head.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            text = handle.read()
            rows = json.loads(text) if stripped.startswith("[") else [json.loads(line) for line in text.splitlines() if line.strip()]
            for row in rows:
                scanned += 1
                org = str(row.get("organisasjonsnummer") or row.get("organisation_number") or "")
                if org in wanted_set:
                    found[org] = _from_universe_row(row) if "organisation_number" in row else row
        else:
            dialect = csv.Sniffer().sniff(head, delimiters=";,\t")
            reader = csv.reader(handle, dialect=dialect)
            header = next(reader)
            for row in reader:
                scanned += 1
                if row and row[0] in wanted_set:
                    found[row[0]] = _nest(dict(zip(header, row)))
                    if len(found) == len(wanted_set):
                        break
    return found, {
        "source": str(source),
        "sha256": _file_sha256(source),
        "rows_scanned": scanned,
        "matched": len(found),
        "seconds": round(time.monotonic() - started, 1),
    }


def _from_universe_row(row: dict[str, Any]) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "organisasjonsnummer": row.get("organisation_number"),
        "navn": row.get("name"),
        "organisasjonsform": {"kode": row.get("legal_form")},
        "konkurs": bool(row.get("bankrupt")),
        "underAvvikling": bool(row.get("liquidating")),
        "naeringskode1": {"kode": row.get("industry_code"), "beskrivelse": row.get("industry_label")},
        "forretningsadresse": {"kommune": row.get("municipality"), "kommunenummer": row.get("municipality_number")},
        "sisteInnsendteAarsregnskap": row.get("latest_submitted_accounts"),
    }
    if row.get("employees") is not None:
        entity["antallAnsatte"] = row.get("employees")
    if row.get("website"):
        entity["hjemmeside"] = row.get("website")
    return entity


# ---------------------------------------------------------------- live API

_years_lock = threading.Lock()
_years_last = 0.0


def _pace_years() -> None:
    """The filing-copy endpoint allows roughly 30 requests per minute."""
    global _years_last
    with _years_lock:
        wait = 2.1 - (time.monotonic() - _years_last)
        if wait > 0:
            time.sleep(wait)
        _years_last = time.monotonic()


def fetch_json(fetcher: Fetcher, url: str, module: str) -> tuple[Response, Any]:
    response = fetcher.get(url, module=module, respect_robots=False, accept="application/json", timeout=20, attempts=2)
    body = None
    if response.ok and response.body:
        try:
            body = response.json()
        except ValueError:
            body = None
    return response, body


def fetch_registry(fetcher: Fetcher, org: str, *, want_years: bool = True, modules: list[str] | None = None) -> dict[str, Any]:
    """Fetch live registry modules. Returns {module: {"response": meta, "body": parsed}}."""
    out: dict[str, Any] = {}
    urls = {
        "registry_live": ENTITY.format(org=org),
        "roles": ROLES.format(org=org),
        "locations": SUBUNITS.format(org=org),
        "financials": ACCOUNTS.format(org=org),
    }
    plan = [(module, urls[module]) for module in (modules or ["registry_live", "roles", "locations", "financials"]) if module in urls]
    if want_years:
        plan.append(("financial_history", ACCOUNT_YEARS.format(org=org)))
    for module, url in plan:
        try:
            if module == "financial_history":
                _pace_years()
            response, body = fetch_json(fetcher, url, module)
        except BudgetExhausted as exc:
            out[module] = {"meta": {"url": url, "status": 0, "error": str(exc), "retrieved_at": utc_now(), "budget": True}, "body": None}
            continue
        out[module] = {
            "meta": {
                "url": url,
                "status": response.status,
                "error": response.error,
                "retrieved_at": response.retrieved_at,
                "sha256": sha256_bytes(response.body) if response.body else None,
            },
            "body": body,
        }
    return out


def fetch_account_years(fetcher: Fetcher, org: str) -> dict[str, Any]:
    url = ACCOUNT_YEARS.format(org=org)
    try:
        _pace_years()
        response, body = fetch_json(fetcher, url, "financial_history")
    except BudgetExhausted as exc:
        return {"meta": {"url": url, "status": 0, "error": str(exc), "retrieved_at": utc_now(), "budget": True}, "body": None}
    return {"meta": {"url": url, "status": response.status, "error": response.error, "retrieved_at": response.retrieved_at, "sha256": sha256_bytes(response.body) if response.body else None}, "body": body}


# ---------------------------------------------------------------- normalizers

def _get(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def address_text(address: Any) -> str | None:
    if not isinstance(address, dict):
        return None
    lines = address.get("adresse") or []
    if isinstance(lines, str):
        lines = [lines]
    parts = [", ".join(line for line in lines if line)]
    tail = " ".join(part for part in [address.get("postnummer"), address.get("poststed")] if part)
    if tail:
        parts.append(tail)
    country = address.get("land")
    if country and country not in ("Norge", "Norway"):
        parts.append(country)
    text = ", ".join(part for part in parts if part)
    return text or None


def normalize_roles(body: Any) -> list[dict[str, Any]]:
    roles = []
    for group in (body or {}).get("rollegrupper", []) if isinstance(body, dict) else []:
        for item in group.get("roller", []):
            if item.get("fratraadt") or item.get("avregistrert"):
                continue
            person = item.get("person") or {}
            name = person.get("navn") or {}
            entity = item.get("enhet") or {}
            person_name = " ".join(filter(None, [name.get("fornavn"), name.get("mellomnavn"), name.get("etternavn")]))
            entity_name = entity.get("navn")
            if isinstance(entity_name, list):
                entity_name = " ".join(entity_name)
            display = person_name or entity_name
            if not display:
                continue
            roles.append({
                "name": display,
                "kind": "person" if person_name else "organisation",
                "organisation_number": entity.get("organisasjonsnummer"),
                "role_code": _get(item, "type", "kode"),
                "role": _get(item, "type", "beskrivelse"),
                "group_code": _get(group, "type", "kode"),
                "last_changed": group.get("sistEndret"),
            })
    return roles


def normalize_subunits(body: Any) -> list[dict[str, Any]]:
    rows = _get(body, "_embedded", "underenheter") or []
    out = []
    for item in rows:
        if item.get("nedleggelsesdato"):
            continue
        out.append({
            "organisation_number": item.get("organisasjonsnummer"),
            "name": item.get("navn"),
            "address": address_text(item.get("beliggenhetsadresse") or item.get("postadresse")),
            "municipality": _get(item, "beliggenhetsadresse", "kommune"),
            "industry": _get(item, "naeringskode1", "beskrivelse"),
            "employees": item.get("antallAnsatte"),
            "started": item.get("oppstartsdato"),
        })
    return out


def subunit_total(body: Any) -> int | None:
    return _get(body, "page", "totalElements")


def normalize_accounts(body: Any) -> list[dict[str, Any]]:
    records = body if isinstance(body, list) else []
    out = []
    for item in records:
        period = item.get("regnskapsperiode") or {}
        result = item.get("resultatregnskapResultat") or {}
        operating = result.get("driftsresultat") or {}
        out.append({
            "account_type": item.get("regnskapstype"),
            "period_start": period.get("fraDato"),
            "period_end": period.get("tilDato"),
            "year": str(period.get("tilDato") or "")[:4] or None,
            "currency": item.get("valuta"),
            "revenue": _get(operating, "driftsinntekter", "sumDriftsinntekter"),
            "operating_costs": _get(operating, "driftskostnad", "sumDriftskostnad"),
            "operating_result": operating.get("driftsresultat"),
            "net_financial_items": _get(result, "finansresultat", "nettoFinans"),
            "profit_before_tax": result.get("ordinaertResultatFoerSkattekostnad"),
            "annual_result": result.get("aarsresultat"),
            "total_assets": _get(item, "eiendeler", "sumEiendeler"),
            "equity": _get(item, "egenkapitalGjeld", "egenkapital", "sumEgenkapital"),
            "total_debt": _get(item, "egenkapitalGjeld", "gjeldOversikt", "sumGjeld"),
            "cash": _get(item, "eiendeler", "sumBankinnskuddOgKontanter"),
            "audited": not bool(_get(item, "revisjon", "ikkeRevidertAarsregnskap")),
            "small_company_rules": _get(item, "regnkapsprinsipper", "smaaForetak"),
            "record_id": item.get("id"),
        })
    out.sort(key=lambda row: (row.get("period_end") or "", row.get("account_type") or ""), reverse=True)
    return out
