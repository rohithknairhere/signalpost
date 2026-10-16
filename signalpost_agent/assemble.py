"""Turn collected source material into claims, evidence and family availability.

Every published claim points at evidence with a source URL, retrieval time and a
content hash; registry financial values are copied as filed, never estimated.
"""
from __future__ import annotations

from typing import Any

from .registry import ACCOUNT_PDF, ENTITY_PAGE, _get, address_text, normalize_accounts, normalize_roles, normalize_subunits
from .util import clean_text, stable_id

STATES = ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")

FAMILIES = {
    "legal_identity": "Legal identity and registration",
    "public_brand": "Public brand",
    "annual_accounts": "Latest filed annual accounts",
    "account_history": "Annual-account history",
    "leadership": "Leadership and board",
    "registered_workplaces": "Registered workplaces",
    "official_website": "Verified official website",
    "company_profiles": "Company-owned social and video profiles",
    "website_contact": "Contact details published by the company",
    "hiring": "Hiring (job postings)",
    "public_activity": "Dated public activity",
    "ratings_reviews": "Customer ratings and reviews",
}

ROLE_PRIORITY = {"DAGL": 0, "LEDE": 1, "NEST": 2, "KOMP": 3, "INNH": 3, "DTPR": 3, "DTSO": 3, "BEST": 4, "MEDL": 5, "VARA": 7, "OBS": 8, "REVI": 9, "REGN": 10, "KONT": 11, "FFØR": 12}

ALWAYS_FILE = {"AS", "ASA", "BRL", "BBL", "STI", "SF", "VPFO"}


class Builder:
    def __init__(self, org: str) -> None:
        self.org = org
        self.claims: list[dict[str, Any]] = []
        self.evidence: dict[str, dict[str, Any]] = {}
        self.families: dict[str, dict[str, Any]] = {}
        self.errors: list[dict[str, Any]] = []

    def add_evidence(self, url: str, source_class: str, retrieved_at: str | None, sha256: str | None, *, span: str | None = None, period: str | None = None, extra: dict[str, Any] | None = None) -> str:
        evidence_id = stable_id(url, sha256 or retrieved_at or "", span or "", prefix="ev")
        if evidence_id not in self.evidence:
            record = {
                "id": evidence_id,
                "source_url": url,
                "source_class": source_class,
                "retrieved_at": retrieved_at,
                "content_sha256": sha256,
            }
            if span:
                record["claim_span"] = clean_text(span, 400)
            if period:
                record["reporting_period"] = period
            if extra:
                record.update(extra)
            self.evidence[evidence_id] = record
        return evidence_id

    def claim(self, family: str, field: str, value: Any, evidence_ids: list[str], *, confidence: float = 0.99, period: str | None = None, as_of: str | None = None, key: str | None = None, method: str | None = None) -> None:
        if value in (None, "", [], {}):
            return
        record = {
            "id": stable_id(self.org, family, field, key or "", prefix="cl"),
            "family": family,
            "field": field,
            "value": value,
            "availability": "available",
            "confidence": round(confidence, 3),
            "evidence_ids": evidence_ids,
        }
        if key:
            record["key"] = key
        if period:
            record["reporting_period"] = period
        if as_of:
            record["as_of"] = as_of
        if method:
            record["method"] = method
        self.claims.append(record)

    def family(self, family: str, availability: str, reason: str, **extra: Any) -> None:
        assert availability in STATES, availability
        self.families[family] = {"availability": availability, "reason": reason, **extra}


def _meta_ok(module: dict[str, Any] | None) -> bool:
    return bool(module) and module["meta"].get("status") == 200 and module.get("body") is not None


def _meta_state(module: dict[str, Any] | None) -> tuple[str, str]:
    """Map a failed/empty registry fetch to an honest availability state."""
    if not module:
        return "failed", "source not fetched"
    meta = module["meta"]
    status = meta.get("status")
    if meta.get("budget"):
        return "failed", "run budget exhausted before this source was read"
    if status in (404, 410):
        return "not_available", f"registry returned HTTP {status} (no record)"
    if status in (401, 403, 429):
        return "blocked", f"registry refused the request (HTTP {status})"
    return "failed", f"registry request failed ({meta.get('error') or status})"


def build_profile(org: str, bulk_entity: dict[str, Any] | None, bulk_meta: dict[str, Any], registry: dict[str, Any], website: dict[str, Any] | None, jobs: dict[str, Any] | None, run_started: str, *, wikidata: dict[str, Any] | None = None, wikidata_status: dict[str, Any] | None = None, reviews: dict[str, Any] | None = None) -> dict[str, Any]:
    b = Builder(org)
    live = registry.get("registry_live") or {}
    entity = live.get("body") if _meta_ok(live) else None
    source_entity = entity or bulk_entity or {}
    if entity:
        ent_ev = b.add_evidence(live["meta"]["url"], "official_registry", live["meta"]["retrieved_at"], live["meta"]["sha256"], span=f"Enhetsregisteret record for {org}")
    else:
        ent_ev = b.add_evidence(bulk_meta.get("source_url") or "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv", "official_registry_bulk", bulk_meta.get("retrieved_at"), bulk_meta.get("sha256"), span=f"bulk snapshot row {org}")
    page_ev = ent_ev

    # ---------------- legal identity
    name = source_entity.get("navn")
    legal_form = _get(source_entity, "organisasjonsform", "kode")
    if source_entity:
        status = "bankrupt" if source_entity.get("konkurs") else "under_liquidation" if source_entity.get("underAvvikling") else "forced_dissolution" if source_entity.get("underTvangsavviklingEllerTvangsopplosning") else "active"
        b.claim("legal_identity", "legal_name", name, [ent_ev])
        b.claim("legal_identity", "organisation_number", org, [ent_ev])
        b.claim("legal_identity", "legal_form", {"code": legal_form, "label": _get(source_entity, "organisasjonsform", "beskrivelse")}, [ent_ev])
        b.claim("legal_identity", "registry_status", status, [ent_ev], as_of=(live.get("meta") or {}).get("retrieved_at", "")[:10] or None)
        b.claim("legal_identity", "founded_date", source_entity.get("stiftelsesdato"), [ent_ev])
        b.claim("legal_identity", "registered_date", source_entity.get("registreringsdatoEnhetsregisteret"), [ent_ev])
        industries = [
            {"code": _get(source_entity, key, "kode"), "label": _get(source_entity, key, "beskrivelse")}
            for key in ("naeringskode1", "naeringskode2", "naeringskode3") if _get(source_entity, key, "kode")
        ]
        b.claim("legal_identity", "industry", industries, [ent_ev])
        purpose = source_entity.get("vedtektsfestetFormaal") or source_entity.get("aktivitet")
        if isinstance(purpose, list):
            purpose = " ".join(str(part) for part in purpose)
        b.claim("legal_identity", "stated_purpose", clean_text(purpose, 800) or None, [ent_ev])
        b.claim("legal_identity", "business_address", address_text(source_entity.get("forretningsadresse")), [ent_ev])
        b.claim("legal_identity", "postal_address", address_text(source_entity.get("postadresse")), [ent_ev])
        b.claim("legal_identity", "municipality", _get(source_entity, "forretningsadresse", "kommune"), [ent_ev])
        if source_entity.get("antallAnsatte") is not None:
            b.claim("legal_identity", "registered_employees", source_entity.get("antallAnsatte"), [ent_ev], as_of=source_entity.get("registreringsdatoantallansatteNAVAaregisteret") or source_entity.get("registreringsdatoAntallAnsatteEnhetsregisteret"))
        elif source_entity.get("harRegistrertAntallAnsatte") is False:
            b.claim("legal_identity", "registered_employees", "none registered", [ent_ev], confidence=0.9)
        capital = source_entity.get("kapital") or {}
        if capital.get("belop"):
            b.claim("legal_identity", "share_capital", {"amount": float(capital["belop"]), "currency": capital.get("valuta") or "NOK", "shares": capital.get("antallAksjer")}, [ent_ev], as_of=capital.get("innfortDato"))
        b.claim("legal_identity", "vat_registered", source_entity.get("registrertIMvaRegisteret"), [ent_ev])
        b.claim("legal_identity", "in_corporate_group", source_entity.get("erIKonsern"), [ent_ev])
        b.claim("legal_identity", "registry_email", source_entity.get("epostadresse"), [ent_ev])
        b.claim("legal_identity", "registry_phone", source_entity.get("telefon") or source_entity.get("mobil"), [ent_ev])
        b.claim("legal_identity", "registry_website", source_entity.get("hjemmeside"), [ent_ev], confidence=0.9)
        b.claim("legal_identity", "latest_filed_accounts_year", source_entity.get("sisteInnsendteAarsregnskap"), [ent_ev])
        b.claim("legal_identity", "registry_profile_page", ENTITY_PAGE.format(org=org), [ent_ev])
        previous_names = [{"name": item.get("navn"), "from": str(item.get("fraDato") or "")[:10], "to": str(item.get("tilDato") or "")[:10]} for item in source_entity.get("historiskeNavn") or []]
        b.claim("legal_identity", "previous_names", previous_names, [ent_ev])
        b.family("legal_identity", "available", "official Enhetsregisteret record" + ("" if entity else " (bulk snapshot; live record unavailable)"))
    else:
        state, reason = _meta_state(live)
        b.family("legal_identity", state if state != "not_available" else "not_available", reason)

    # ---------------- financials
    accounts = registry.get("financials")
    records = normalize_accounts(accounts.get("body")) if _meta_ok(accounts) else []
    if records:
        acc_meta = accounts["meta"]
        company_records = [row for row in records if row.get("account_type") == "SELSKAP"] or records
        latest = company_records[0]
        period = f"{latest.get('period_start')}/{latest.get('period_end')}"
        ev = b.add_evidence(acc_meta["url"], "official_annual_accounts", acc_meta["retrieved_at"], acc_meta["sha256"], span=f"Regnskapsregisteret {latest.get('account_type')} accounts {period}", period=period)
        for field in ("revenue", "operating_result", "profit_before_tax", "annual_result", "total_assets", "equity", "total_debt", "cash"):
            if latest.get(field) is not None:
                b.claim("annual_accounts", field, {"amount": latest[field], "currency": latest.get("currency")}, [ev], period=period, key=latest.get("year"))
        b.claim("annual_accounts", "accounts_year", latest.get("year"), [ev], period=period)
        b.claim("annual_accounts", "audited", latest.get("audited"), [ev], period=period)
        group = [row for row in records if row.get("account_type") == "KONSERN"]
        if group:
            g = group[0]
            gperiod = f"{g.get('period_start')}/{g.get('period_end')}"
            for field in ("revenue", "operating_result", "annual_result"):
                if g.get(field) is not None:
                    b.claim("annual_accounts", f"group_{field}", {"amount": g[field], "currency": g.get("currency")}, [ev], period=gperiod, key=g.get("year"))
        b.family("annual_accounts", "available", f"filed {latest.get('account_type','').lower()} accounts for {latest.get('year')}")
        history = [
            {key: row.get(key) for key in ("year", "account_type", "currency", "revenue", "operating_result", "annual_result", "equity", "total_assets")}
            for row in records
        ]
        if len(history) > 1:
            b.claim("account_history", "financial_series", history, [ev], period=f"{records[-1].get('period_start')}/{records[0].get('period_end')}")
            # Derived, clearly labelled: year-over-year revenue change from two filed values.
            years = [row for row in company_records if row.get("revenue") is not None]
            if len(years) >= 2 and years[1]["revenue"]:
                change = (years[0]["revenue"] - years[1]["revenue"]) / abs(years[1]["revenue"])
                b.claim("account_history", "revenue_change_yoy", {"from_year": years[1]["year"], "to_year": years[0]["year"], "change_pct": round(change * 100, 1), "derived_from": "filed revenue values"}, [ev], confidence=0.97, method="derived")
    else:
        state, reason = _meta_state(accounts)
        if state == "not_available" and legal_form not in ALWAYS_FILE and not source_entity.get("sisteInnsendteAarsregnskap"):
            state, reason = "not_applicable", f"legal form {legal_form} is not always required to file accounts and none are registered"
        elif _meta_ok(accounts):
            state, reason = "not_available", "Regnskapsregisteret returned no normalized accounts"
        b.family("annual_accounts", state, reason)

    years_module = registry.get("financial_history")
    if _meta_ok(years_module) and isinstance(years_module["body"], list) and years_module["body"]:
        meta = years_module["meta"]
        years = sorted({str(year) for year in years_module["body"] if str(year).isdigit()}, reverse=True)
        ev = b.add_evidence(meta["url"], "official_annual_account_copies", meta["retrieved_at"], meta["sha256"], span=f"filing copies available for {', '.join(years[:5])}")
        b.claim("account_history", "filed_account_years", years, [ev])
        b.claim("account_history", "filing_copies", [{"year": year, "url": ACCOUNT_PDF.format(org=org, year=year)} for year in years[:6]], [ev])
    if any(claim["family"] == "account_history" for claim in b.claims):
        b.family("account_history", "available", "registry accounts history and filing copies")
    elif "annual_accounts" in b.families and b.families["annual_accounts"]["availability"] == "not_applicable":
        b.family("account_history", "not_applicable", "no filing obligation observed")
    else:
        state, reason = _meta_state(years_module) if years_module else ("not_available", "only one filed year returned")
        if _meta_ok(years_module):
            state, reason = "not_available", "no filing copies listed"
        b.family("account_history", state, reason)

    # ---------------- leadership
    roles_module = registry.get("roles")
    roles = normalize_roles(roles_module.get("body")) if _meta_ok(roles_module) else []
    if roles:
        meta = roles_module["meta"]
        ev = b.add_evidence(meta["url"], "official_roles", meta["retrieved_at"], meta["sha256"], span="Enhetsregisteret roles")
        roles.sort(key=lambda role: (ROLE_PRIORITY.get(role.get("role_code") or "", 20), role.get("name") or ""))
        for role in roles:
            if role["role_code"] == "DAGL":
                b.claim("leadership", "chief_executive", role["name"], [ev], as_of=role.get("last_changed"))
            elif role["role_code"] == "LEDE":
                b.claim("leadership", "board_chair", role["name"], [ev], as_of=role.get("last_changed"))
            elif role["role_code"] == "REVI":
                b.claim("leadership", "auditor", {"name": role["name"], "organisation_number": role.get("organisation_number")}, [ev], as_of=role.get("last_changed"))
            elif role["role_code"] == "REGN":
                b.claim("leadership", "accountant", {"name": role["name"], "organisation_number": role.get("organisation_number")}, [ev], as_of=role.get("last_changed"))
        b.claim("leadership", "roles", [{key: role.get(key) for key in ("name", "role", "role_code", "kind", "organisation_number", "last_changed")} for role in roles], [ev])
        b.family("leadership", "available", f"{len(roles)} active registered roles")
    else:
        state, reason = _meta_state(roles_module)
        if _meta_ok(roles_module):
            state, reason = "not_available", "no active roles registered"
        b.family("leadership", state, reason)

    # ---------------- workplaces
    sub_module = registry.get("locations")
    subunits = normalize_subunits(sub_module.get("body")) if _meta_ok(sub_module) else []
    if subunits:
        meta = sub_module["meta"]
        ev = b.add_evidence(meta["url"], "official_subunits", meta["retrieved_at"], meta["sha256"], span=f"{len(subunits)} registered workplaces")
        b.claim("registered_workplaces", "workplaces", subunits, [ev])
        b.claim("registered_workplaces", "workplace_count", len(subunits), [ev])
        municipalities = sorted({unit["municipality"] for unit in subunits if unit.get("municipality")})
        b.claim("registered_workplaces", "workplace_municipalities", municipalities, [ev])
        b.family("registered_workplaces", "available", f"{len(subunits)} registered workplaces")
    else:
        state, reason = _meta_state(sub_module)
        if _meta_ok(sub_module):
            state, reason = "not_available", "no registered workplaces (underenheter)"
        b.family("registered_workplaces", state, reason)

    # ---------------- website + profiles + contact
    site_state = (website or {}).get("verdict")
    extracted: dict[str, Any] = {}
    if site_state == "exact":
        pages = website.get("pages") or []
        home = pages[0] if pages else {}
        proof_page = home
        span = "; ".join(website.get("signals") or [])
        site_ev = b.add_evidence(home.get("url") or website["final_url"], "company_owned_website", home.get("retrieved_at"), home.get("sha256"), span=f"identity signals: {span}", extra={"verification": {"signals": website.get("signals"), "score": website.get("score"), "candidate_source": website.get("source")}})
        page_evs = [site_ev] + [b.add_evidence(page["url"], "company_owned_website", page.get("retrieved_at"), page.get("sha256"), span=f"{page.get('kind')} page") for page in pages[1:]]
        b.claim("official_website", "official_website", website["final_url"], page_evs[:3], confidence=website.get("score", 0.9), method=f"verified:{website.get('source')}")
        b.claim("official_website", "website_domain", website.get("domain"), [site_ev], confidence=website.get("score", 0.9))
        b.claim("official_website", "verification_signals", website.get("signals"), [site_ev], confidence=website.get("score", 0.9))
        b.family("official_website", "available", f"verified via {', '.join(website.get('signals') or [])}")
        extracted = website.get("extracted") or {}
        if extracted.get("brand_name"):
            b.claim("public_brand", "brand_name", extracted["brand_name"], [site_ev], confidence=0.9)
        if extracted.get("description"):
            b.claim("public_brand", "self_description", extracted["description"], [site_ev], confidence=0.95)
        about = next((page for page in pages if page.get("kind") == "about"), None)
        if extracted.get("about_excerpt") and about:
            about_ev = b.add_evidence(about["url"], "company_owned_website", about.get("retrieved_at"), about.get("sha256"), span="about page")
            b.claim("public_brand", "about_excerpt", extracted["about_excerpt"][:600], [about_ev], confidence=0.95)
        if extracted.get("language"):
            b.claim("public_brand", "website_language", extracted["language"], [site_ev], confidence=0.95)
        b.family("public_brand", "available" if any(c["family"] == "public_brand" for c in b.claims) else "not_available", "brand and self-description from the verified website")
        profiles = [item for item in extracted.get("social_profiles") or [] if item.get("publishable")]
        for item in profiles:
            ev = b.add_evidence(item["found_on"], "company_owned_website", item.get("retrieved_at"), item.get("found_on_sha256"), span=f"link to {item['url']} on the verified website ({', '.join(item.get('method') or [])})")
            b.claim("company_profiles", f"{item['platform']}_profile", item["url"], [ev], confidence=0.97 if item.get("handle_matches_name") or "jsonld_sameAs" in (item.get("method") or []) else 0.9, key=item["platform"], method="linked_from_verified_website")
        quarantined = [item["url"] for item in extracted.get("social_profiles") or [] if not item.get("publishable")]
        b.family("company_profiles", "available" if profiles else ("ambiguous" if quarantined else "not_available"),
                 f"{len(profiles)} profiles linked from the verified website" if profiles else ("links found but ownership unclear" if quarantined else "verified website links to no social or video profiles"),
                 quarantined=quarantined[:5])
        contact_page = next((page for page in pages if page.get("kind") == "contact"), home)
        contact_ev = b.add_evidence(contact_page.get("url") or home.get("url"), "company_owned_website", contact_page.get("retrieved_at"), contact_page.get("sha256"), span="contact details on the verified website")
        b.claim("website_contact", "website_emails", extracted.get("emails"), [contact_ev], confidence=0.95)
        b.claim("website_contact", "website_phones", ["+47 " + phone for phone in extracted.get("phones") or []], [contact_ev], confidence=0.9)
        careers = extracted.get("careers_page")
        if careers:
            careers_ev = b.add_evidence(careers["url"], "company_owned_website", careers.get("retrieved_at"), careers.get("sha256"), span="careers page")
            b.claim("hiring", "careers_page", careers["url"], [careers_ev], confidence=0.9)
        b.family("website_contact", "available" if any(c["family"] == "website_contact" for c in b.claims) else "not_available", "contact details on the verified website")
    else:
        attempts = (website or {}).get("attempts") or []
        if site_state == "ambiguous":
            state, reason = "ambiguous", "a candidate site was found but could not be proven to belong to this organisation"
        elif site_state == "blocked":
            state, reason = "blocked", "candidate website disallows automated access (robots.txt)"
        elif site_state == "failed":
            state, reason = "failed", (website or {}).get("error") or "website research failed"
        elif not attempts:
            state, reason = "not_available", "no website registered and no company-specific domain candidates"
        else:
            state, reason = "not_available", f"checked {len(attempts)} candidate domain(s); none proven to belong to this organisation"
        b.family("official_website", state, reason, candidates=[{key: item.get(key) for key in ("url", "source", "verdict", "signals", "other_orgs")} for item in attempts][:6])
        derived = "ambiguous" if state == "ambiguous" else ("blocked" if state == "blocked" else ("failed" if state == "failed" else "not_available"))
        b.family("public_brand", derived, "no verified website to read the public brand from")
        b.family("company_profiles", derived, "company-owned profiles are only taken from a verified official website")
        b.family("website_contact", derived, "no verified website")

    # ---------------- Wikidata (exact match on organisation number P2333)
    if wikidata:
        wd_ev = b.add_evidence(wikidata["item"], "open_knowledge_base_wikidata", wikidata.get("retrieved_at"), wikidata.get("sha256"), span=f"Wikidata {wikidata['qid']} has Norwegian organisation number (P2333) {org}")
        b.claim("public_brand", "wikidata_item", wikidata["item"], [wd_ev], confidence=0.98)
        if wikidata.get("label"):
            b.claim("public_brand", "common_name", wikidata["label"], [wd_ev], confidence=0.95)
        if wikidata.get("description"):
            b.claim("public_brand", "wikidata_description", wikidata["description"], [wd_ev], confidence=0.9)
        for key, field in (("wikipedia_no", "wikipedia_article_no"), ("wikipedia_en", "wikipedia_article_en")):
            if wikidata.get(key):
                b.claim("public_brand", field, wikidata[key], [wd_ev], confidence=0.97)
        if wikidata.get("lei"):
            b.claim("legal_identity", "lei", wikidata["lei"][0], [wd_ev], confidence=0.97)
        existing = {claim.get("key") for claim in b.claims if claim["family"] == "company_profiles"}
        from .wikidata import profiles as wd_profiles

        added = 0
        for item in wd_profiles(wikidata):
            if item["platform"] in existing:
                continue
            b.claim("company_profiles", f"{item['platform']}_profile", item["url"], [wd_ev], confidence=0.9, key=item["platform"], method="wikidata_org_number_match")
            added += 1
        if added and b.families.get("company_profiles", {}).get("availability") != "available":
            b.family("company_profiles", "available", f"{added} profiles from Wikidata (matched on organisation number)")
        if b.families.get("public_brand", {}).get("availability") != "available":
            b.family("public_brand", "available", "public name and references from Wikidata (matched on organisation number)")

    # ---------------- hiring
    if jobs is not None:
        if jobs.get("jobs"):
            items = []
            evs = []
            for job in jobs["jobs"]:
                ev = b.add_evidence(job["source_url"], "official_public_api_nav", job.get("retrieved_at"), job.get("sha256"), span=f"NAV ad {job['uuid']}: employer orgnr {job['employer_orgnr']}", extra={"public_url": job["public_url"]})
                evs.append(ev)
                items.append({key: job.get(key) for key in ("title", "job_title", "published", "expires", "location", "extent", "engagement_type", "position_count", "public_url", "matched_via")})
            b.claim("hiring", "active_job_postings", items, evs, confidence=0.99, method="nav_feed_orgnr_confirmed")
            b.claim("hiring", "active_job_posting_count", len(items), evs, confidence=0.99, as_of=run_started[:10])
            b.family("hiring", "available", f"{len(items)} active NAV job postings confirmed by employer organisation number", coverage_window=jobs.get("coverage_window"))
        elif jobs.get("status") in ("failed", "blocked"):
            if any(c["family"] == "hiring" for c in b.claims):
                b.family("hiring", "available", "careers page on the verified website; NAV feed unavailable this run")
            else:
                b.family("hiring", jobs["status"], f"NAV job feed {jobs['status']}: {jobs.get('error')}")
        else:
            if any(c["family"] == "hiring" for c in b.claims):
                b.family("hiring", "available", "careers page on the verified website; no active NAV postings found")
            else:
                b.family("hiring", "not_available", "no active NAV job postings for this organisation in the feed window", coverage_window=jobs.get("coverage_window"))

    # ---------------- ratings and reviews (Fagfolkguiden, keyed by organisation number)
    review_events: list[tuple[str, str, str]] = []
    if reviews is None:
        b.family("ratings_reviews", "failed", "ratings source not checked this run")
    elif reviews.get("status") == "available":
        rev_ev = b.add_evidence(reviews["url"], "third_party_directory_fagfolkguiden", reviews.get("retrieved_at"), reviews.get("sha256"), span=f"Fagfolkguiden profile declaring organisation number {org}")
        b.claim("ratings_reviews", "directory_listing", reviews["url"], [rev_ev], confidence=0.98, method="org_number_in_structured_data")
        if reviews.get("rating"):
            b.claim("ratings_reviews", "customer_rating", reviews["rating"], [rev_ev], confidence=0.97, as_of=(reviews.get("retrieved_at") or "")[:10])
            b.claim("ratings_reviews", "rating_count", reviews["rating"]["count"], [rev_ev], confidence=0.97, as_of=(reviews.get("retrieved_at") or "")[:10])
        if reviews.get("reviews"):
            b.claim("ratings_reviews", "recent_reviews", reviews["reviews"], [rev_ev], confidence=0.95)
            review_events = [(item["date"], f"Customer review ({item.get('rating')}/5)", rev_ev) for item in reviews["reviews"] if item.get("date")]
        has_rating = bool(reviews.get("rating"))
        b.family("ratings_reviews", "available", "customer rating from Fagfolkguiden" if has_rating else "listed on Fagfolkguiden; no ratings yet")
    else:
        b.family("ratings_reviews", reviews.get("status") or "failed", reviews.get("reason") or reviews.get("error") or "no Fagfolkguiden profile for this organisation number")

    # ---------------- dated public activity
    events = []
    def add_event(day: Any, kind: str, text: str, evidence_id: str) -> None:
        day = str(day or "")[:10]
        if len(day) == 10 and day[:2] in ("19", "20"):
            events.append({"date": day, "type": kind, "description": text, "evidence_id": evidence_id})
    if source_entity:
        add_event(source_entity.get("stiftelsesdato"), "founded", "Company founded", ent_ev)
        add_event(source_entity.get("registreringsdatoEnhetsregisteret"), "registered", "Registered in Enhetsregisteret", ent_ev)
        capital = source_entity.get("kapital") or {}
        add_event(capital.get("innfortDato"), "capital_change", f"Share capital registered as {capital.get('belop')} {capital.get('valuta') or 'NOK'}", ent_ev)
        for item in source_entity.get("historiskeNavn") or []:
            add_event(item.get("tilDato"), "name_change", f"Changed name from {item.get('navn')}", ent_ev)
        add_event(source_entity.get("vedtektsdato"), "articles_updated", "Articles of association dated", ent_ev)
        if source_entity.get("konkursdato"):
            add_event(source_entity.get("konkursdato"), "bankruptcy", "Bankruptcy registered", ent_ev)
    if roles:
        roles_ev = next(c["evidence_ids"][0] for c in b.claims if c["field"] == "roles")
        seen_groups = set()
        for role in roles:
            if role.get("last_changed") and role.get("group_code") not in seen_groups:
                seen_groups.add(role.get("group_code"))
                add_event(role["last_changed"], "roles_updated", f"Registered roles updated ({role.get('group_code')})", roles_ev)
    if records:
        latest = (([row for row in records if row.get("account_type") == "SELSKAP"] or records)[0])
        acc_ev = next(c["evidence_ids"][0] for c in b.claims if c["family"] == "annual_accounts")
        add_event(latest.get("period_end"), "accounts_period_end", f"Financial year {latest.get('year')} closed (accounts filed)", acc_ev)
    for job in (jobs or {}).get("jobs") or []:
        ev = next((e["id"] for e in b.evidence.values() if e["source_url"] == job["source_url"]), None)
        if ev:
            add_event(job.get("published"), "job_posted", f"Job posted: {job.get('title')}", ev)
    for day, text, evidence_id in review_events:
        add_event(day, "customer_review", text, evidence_id)
    for item in extracted.get("news") or []:
        ev = b.add_evidence(item["found_on"], "company_owned_website", item.get("retrieved_at"), item.get("sha256"), span=f"{item['date']}: {item['title']}")
        add_event(item["date"], "company_news", f"{item['title']} ({item['url']})", ev)
    events = sorted({(e["date"], e["type"], e["description"]): e for e in events}.values(), key=lambda e: e["date"], reverse=True)
    if events:
        b.claim("public_activity", "dated_events", events[:25], sorted({e["evidence_id"] for e in events[:25]}))
        b.claim("public_activity", "latest_activity_date", events[0]["date"], [events[0]["evidence_id"]])
        news = [e for e in events if e["type"] == "company_news"]
        if news:
            b.claim("public_activity", "company_news", news[:8], sorted({e["evidence_id"] for e in news[:8]}), confidence=0.93)
        b.family("public_activity", "available", f"{len(events)} dated events from registry, job and company sources")
    else:
        b.family("public_activity", "not_available", "no dated public activity found in checked sources")

    for family in FAMILIES:
        if family not in b.families:
            b.family(family, "failed", "module did not run")

    return {
        "organisation_number": org,
        "name": name,
        "claims": b.claims,
        "evidence": list(b.evidence.values()),
        "families": b.families,
        "subunit_orgs": sorted(unit["organisation_number"] for unit in subunits if unit.get("organisation_number")),
    }
