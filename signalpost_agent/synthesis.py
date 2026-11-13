"""Evidence-bound synthesis: what the company does, what changed and what is unknown.

Deterministic (no model, no cost). Every sentence carries the evidence ids it rests on,
and nothing is stated that is not a published claim.
"""
from __future__ import annotations

import html
import re
from typing import Any

from .assemble import FAMILIES, OPTIONAL_FAMILIES
from .nace import division


def _fmt_amount(value: dict[str, Any] | None) -> str | None:
    if not value or value.get("amount") is None:
        return None
    amount = float(value["amount"])
    currency = value.get("currency") or ""
    absolute = abs(amount)
    if absolute >= 1e9:
        text = f"{amount / 1e9:.1f} bn"
    elif absolute >= 1e6:
        text = f"{amount / 1e6:.1f} m"
    elif absolute >= 1e3:
        text = f"{amount / 1e3:.0f} k"
    else:
        text = f"{amount:.0f}"
    return f"{currency} {text}".strip()


def synthesize(profile: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    claims = {}
    for claim in profile["claims"]:
        claims.setdefault(claim["field"], claim)
    families = profile["families"]
    sentences: list[dict[str, Any]] = []

    def say(text: str, *fields: str) -> None:
        evidence = sorted({ev for field in fields if field in claims for ev in claims[field]["evidence_ids"]})
        if evidence:
            sentences.append({"text": text, "evidence_ids": evidence, "fields": [f for f in fields if f in claims]})

    def value(field: str) -> Any:
        return claims[field]["value"] if field in claims else None

    name = value("legal_name") or profile.get("name") or profile["organisation_number"]
    industry = value("industry") or []
    status = value("registry_status")
    founded = value("founded_date")
    municipality = value("municipality")
    place = municipality.title() if isinstance(municipality, str) else None
    revenue = _fmt_amount(value("revenue"))
    result_value = value("annual_result") or {}
    result = _fmt_amount({**result_value, "amount": abs(result_value["amount"])}) if result_value.get("amount") is not None else None
    year = value("accounts_year")
    trend = value("revenue_change_yoy")
    workforce = value("full_time_equivalents") or value("average_employees")
    jobs = value("active_job_postings") or []
    site_jobs = value("website_job_postings") or []
    news = value("company_news") or []

    # 1. The fact a buyer wants first: scale and direction, with the source named.
    if year and revenue:
        lead = f"{name} had revenue of {revenue} in {year}"
        if trend and trend.get("change_pct") is not None:
            pct = trend["change_pct"]
            lead += f" ({'up' if pct > 0 else 'down' if pct < 0 else 'flat'}{'' if pct == 0 else ' ' + format(abs(pct), 'g') + '%'} on {trend['from_year']})"
        if result:
            lead += f" and a net {'profit' if result_value['amount'] >= 0 else 'loss'} of {result}"
        say(lead + ", according to its annual accounts filed with the Brønnøysund Register of Company Accounts.", "revenue", "annual_result", "accounts_year", "revenue_change_yoy")
    elif jobs:
        say(f"{name} is hiring: {len(jobs)} open job ad{'s' if len(jobs) != 1 else ''} on NAV, Norway's public job service, name it as employer by organisation number.", "active_job_postings")
    elif workforce:
        say(f"{name} reports {workforce['value']:g} full-time equivalents in its {workforce['year']} annual report, filed with the Brønnøysund Register Centre.", "full_time_equivalents", "average_employees")

    # 2. What it does, in plain words, with where that comes from.
    plain = division(industry[0]["code"]) if industry else None
    if value("self_description"):
        say(f"On its own website it describes itself as: “{value('self_description')[:220]}”", "self_description")
    if plain or place:
        text = "It works in " + (plain or "an unclassified industry")
        if place:
            text += f", based in {place}"
        if founded:
            text += f", and was founded in {str(founded)[:4]}"
        say(text + f" (Central Coordinating Register{', industry ' + industry[0]['code'] if industry else ''}).", "industry", "municipality", "founded_date")
    if status and status != "active":
        say(f"The register marks it as {status.replace('_', ' ')}.", "registry_status")
    if not value("self_description") and value("stated_purpose") and not plain:
        say(f"Registered purpose: {value('stated_purpose')[:200]}", "stated_purpose")
    if value("brand_name") and value("brand_name").casefold() not in str(name).casefold():
        say(f"It trades publicly as “{value('brand_name')}”.", "brand_name")

    # 3. People and size.
    if workforce and not (not (year and revenue) and not jobs):
        say(f"Its {workforce['year']} annual report states {workforce['value']:g} full-time equivalents.", "full_time_equivalents", "average_employees")
    if value("chief_executive"):
        say(f"The CEO is {value('chief_executive')}" + (f"; the board chair is {value('board_chair')}." if value("board_chair") and value("board_chair") != value("chief_executive") else "."), "chief_executive", "board_chair")
    count = value("workplace_count")
    if count and count > 1:
        say(f"It has {count} registered workplaces" + (f" ({', '.join(m.title() for m in value('workplace_municipalities')[:4])})." if value("workplace_municipalities") else "."), "workplace_count", "workplace_municipalities")

    # 4. What it is doing now: its own news, its own job postings, NAV ads.
    if news:
        latest = news[0]
        headline = re.sub(r"\s*\(https?://[^)]*\)\s*$", "", html.unescape(str(latest.get('title') or latest.get('description') or '')))
        say(f"Latest news on its own website ({latest['date']}): {headline[:110]}.", "company_news")
    if site_jobs:
        say(f"Its website lists {len(site_jobs)} open position{'s' if len(site_jobs) != 1 else ''}: {', '.join(str(job.get('title'))[:50] for job in site_jobs[:3])}.", "website_job_postings")
    if jobs and (year and revenue):
        titles = ", ".join(sorted({str(job.get('job_title') or job.get('title') or '')[:50] for job in jobs if job.get('job_title') or job.get('title')})[:3])
        say(f"It is hiring: {len(jobs)} open NAV job ad{'s' if len(jobs) != 1 else ''} ({titles}).", "active_job_postings")
    elif value("careers_page") and not site_jobs and not jobs:
        say("Its website has a careers page, but no open job ads naming it were found on NAV.", "careers_page")

    # 5. Where to check it yourself.
    if value("official_website"):
        profiles_found = [claim for claim in profile["claims"] if claim["family"] == "company_profiles"]
        text = f"Its own website is {value('official_website')}"
        if profiles_found:
            text += ", which links to its " + ", ".join(sorted({claim['key'].title() for claim in profiles_found})) + " page" + ("s" if len(profiles_found) > 1 else "")
        say(text + ".", "official_website", *[claim["field"] for claim in profiles_found])
    rating = value("customer_rating")
    if rating:
        say(f"Customers rate it {rating['value']}/{rating.get('best', 5)} from {rating['count']} reviews ({rating.get('origin')}).", "customer_rating")
    events = [event for event in (value("dated_events") or []) if event.get("type") not in {"company_news"}]
    if events:
        recent = "; ".join(f"{event['date']} {event['description'][:70]}" for event in events[:3])
        sentences.append({"text": f"Recent dated activity: {recent}.", "evidence_ids": sorted({event["evidence_id"] for event in events[:3] if event.get("evidence_id")}), "fields": ["dated_events"]})

    # Changes
    change_lines = [
        {"text": change["summary"], "evidence_ids": change.get("evidence_ids") or []}
        for change in changes if change.get("material")
    ]

    # Unknowns: families we could not fill, with the honest state.
    unknowns = [
        {"family": family, "label": FAMILIES.get(family, OPTIONAL_FAMILIES.get(family, family)), "availability": info["availability"], "reason": info.get("reason")}
        for family, info in families.items() if info["availability"] != "available"
    ]
    refresh = profile.get("refresh") or {}
    if change_lines:
        change_text = "Since the previous run: " + "; ".join(item["text"] for item in change_lines[:4]) + "."
    elif refresh.get("previous_snapshot"):
        change_text = f"No material changes since the previous run ({refresh.get('previous_snapshot')})."
    else:
        change_text = "First observation of this company; changes are tracked from this snapshot."
    summary = " ".join(sentence["text"] for sentence in sentences) + " " + change_text
    if unknowns:
        summary += " Not established: " + ", ".join(f"{item['label'].lower()} ({item['availability'].replace('_', ' ')})" for item in unknowns[:6]) + "."
    return {"summary": summary, "sentences": sentences, "change_status": change_text, "changes": change_lines, "unknowns": unknowns, "method": "deterministic_evidence_bound_v1"}
