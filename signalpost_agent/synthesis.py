"""Evidence-bound synthesis: what the company does, what changed and what is unknown.

Deterministic (no model, no cost). Every sentence carries the evidence ids it rests on,
and nothing is stated that is not a published claim.
"""
from __future__ import annotations

from typing import Any

from .assemble import FAMILIES, OPTIONAL_FAMILIES


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
    form = (value("legal_form") or {}).get("code")
    industry = value("industry") or []
    status = value("registry_status")
    founded = value("founded_date")
    municipality = value("municipality")

    # What it does
    form_label = (value("legal_form") or {}).get("label")
    what = f"{name} is registered as {form_label.lower() + ' (' + form + ')' if form_label and form else form or 'an entity'}"
    if industry:
        what += f" under industry code {industry[0]['code']} ({industry[0]['label']})"
    if municipality:
        what += f", based in {municipality.title()}"
    if founded:
        what += f", founded {founded}"
    say(what + ".", "legal_name", "legal_form", "industry", "municipality", "founded_date")
    if status and status != "active":
        say(f"The registry marks it as {status.replace('_', ' ')}.", "registry_status")
    if value("self_description"):
        say(f"Its website describes it as: “{value('self_description')[:240]}”", "self_description")
    elif value("stated_purpose"):
        say(f"Registered purpose: {value('stated_purpose')[:240]}", "stated_purpose")
    if value("brand_name") and value("brand_name").casefold() not in str(name).casefold():
        say(f"It presents itself publicly as “{value('brand_name')}”.", "brand_name")

    # Who leads it
    leaders = []
    if value("chief_executive"):
        leaders.append(f"CEO {value('chief_executive')}")
    if value("board_chair"):
        leaders.append(f"board chair {value('board_chair')}")
    if leaders:
        say("Leadership: " + " and ".join(leaders) + ".", "chief_executive", "board_chair")

    # Numbers
    revenue = _fmt_amount(value("revenue"))
    result = _fmt_amount(value("annual_result"))
    year = value("accounts_year")
    if year and (revenue or result):
        parts = []
        if revenue:
            parts.append(f"revenue of {revenue}")
        if result:
            parts.append(f"a net result of {result}")
        say(f"Its filed {year} accounts show " + " and ".join(parts) + ".", "revenue", "annual_result", "accounts_year")
    trend = value("revenue_change_yoy")
    if trend:
        direction = "grew" if trend["change_pct"] > 0 else "fell" if trend["change_pct"] < 0 else "was flat"
        say(f"Revenue {direction} {abs(trend['change_pct'])}% from {trend['from_year']} to {trend['to_year']} (computed from filed values).", "revenue_change_yoy")
    workforce = value("full_time_equivalents") or value("average_employees")
    if workforce:
        label = "full-time equivalents" if "full_time_equivalents" in claims else "employees on average"
        say(f"Its {workforce['year']} annual report states {workforce['value']:g} {label}.", "full_time_equivalents", "average_employees")
    employees = value("registered_employees")
    if isinstance(employees, int):
        say(f"It has {employees} registered employees.", "registered_employees")
    count = value("workplace_count")
    if count:
        say(f"It operates {count} registered workplace{'s' if count != 1 else ''}" + (f" in {', '.join(m.title() for m in value('workplace_municipalities')[:4])}." if value("workplace_municipalities") else "."), "workplace_count", "workplace_municipalities")

    # Presence and hiring
    if value("official_website"):
        profiles = [claim for claim in profile["claims"] if claim["family"] == "company_profiles"]
        text = f"Its verified website is {value('official_website')}"
        if profiles:
            text += " and it links to company profiles on " + ", ".join(sorted({claim['key'].title() for claim in profiles}))
        say(text + ".", "official_website", *[claim["field"] for claim in profiles])
    jobs = value("active_job_postings")
    if jobs:
        titles = ", ".join(sorted({str(job.get('title') or '')[:60] for job in jobs if job.get("title")})[:3])
        say(f"It appears to be hiring: {len(jobs)} active NAV posting{'s' if len(jobs) != 1 else ''} ({titles}).", "active_job_postings")
    elif value("website_job_postings"):
        site_jobs = value("website_job_postings")
        say(f"Its website lists {len(site_jobs)} open position{'s' if len(site_jobs) != 1 else ''} ({', '.join(job['title'][:50] for job in site_jobs[:3])}).", "website_job_postings")
    elif value("careers_page"):
        say("Its website has a careers page, but no active NAV postings were found.", "careers_page")
    rating = value("customer_rating")
    if rating:
        say(f"Customers rate it {rating['value']}/{rating.get('best', 5)} from {rating['count']} reviews ({rating.get('origin')}).", "customer_rating")
    events = value("dated_events") or []
    if events:
        recent = "; ".join(f"{event['date']} {event['description'][:70]}" for event in events[:3])
        sentences.append({"text": f"Most recent dated activity: {recent}.", "evidence_ids": sorted({event["evidence_id"] for event in events[:3]}), "fields": ["dated_events"]})

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
