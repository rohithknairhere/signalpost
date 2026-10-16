"""Offline tests: identity rules, extraction, envelope contract and refresh idempotency.

Run: uv run --group dev pytest -q
"""
from __future__ import annotations

import copy

from signalpost_agent.assemble import STATES, build_profile
from signalpost_agent.net import Response
from signalpost_agent.refresh import apply_refresh
from signalpost_agent.synthesis import synthesize
from signalpost_agent.util import mod11_valid, org_numbers_in_text
from signalpost_agent.website import (
    _parse,
    assess,
    build_identity,
    email_domain,
    extract_facts,
    name_domain_candidates,
    normalize_social,
)

ORG = "810034882"  # SANDNES ELEKTRISKE AS (public registry data)
ENTITY = {
    "organisasjonsnummer": ORG,
    "navn": "SANDNES ELEKTRISKE AS",
    "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
    "naeringskode1": {"kode": "43.210", "beskrivelse": "Elektrisk installasjonsarbeid"},
    "forretningsadresse": {"adresse": ["Strandgata 21"], "postnummer": "4307", "poststed": "SANDNES", "kommune": "SANDNES"},
    "epostadresse": "post@sandneselektriske.no",
    "telefon": "+47 51 66 00 00",
    "antallAnsatte": 10,
    "stiftelsesdato": "1995-02-19",
    "registreringsdatoEnhetsregisteret": "1995-02-19",
    "sisteInnsendteAarsregnskap": "2025",
}


def page(html: str, url: str = "https://sandneselektriske.no/", kind: str = "home"):
    response = Response(url, url, 200, html.encode(), {"content-type": "text/html; charset=utf-8"}, None, "2026-10-15T00:00:00Z", 10)
    parsed = _parse(response, kind)
    return parsed


def identity():
    return build_identity(ORG, ENTITY, [])


# ------------------------------------------------------------------ identifiers

def test_mod11_and_org_detection():
    assert mod11_valid("810034882")
    assert not mod11_valid("810034883")
    assert org_numbers_in_text("Org.nr: 810 034 882 MVA") == {"810034882"}
    assert org_numbers_in_text("Tlf 810 034 883") == set()


def test_email_domain_filters_free_mail_and_shared_services():
    assert email_domain("post@sandneselektriske.no") == "sandneselektriske.no"
    assert email_domain("someone@gmail.com") is None
    assert email_domain("x@online.no") is None
    assert email_domain("styret@styrerommet.net") is None


def test_name_domain_candidates():
    assert name_domain_candidates("SANDNES ELEKTRISKE AS")[:2] == ["sandneselektriske.no", "sandnes-elektriske.no"]
    assert all("as" not in c.split(".")[0].split("-")[-1:] for c in name_domain_candidates("Bachke & Co. A/S"))


# ------------------------------------------------------------------ identity verdicts

def test_org_number_on_site_is_exact():
    p = page("<html><title>Sandnes Elektriske</title><body>Kontakt oss. Org nr 810 034 882</body></html>")
    assert assess(identity(), [p], "name_derived", "sandneselektriske.no")["verdict"] == "exact"


def test_other_company_number_is_never_published():
    p = page("<html><body>Sandnes Elektriske AS - Strandgata 21, 4307 Sandnes. Org nr 923 609 016</body></html>")
    result = assess(identity(), [p], "registry_email_domain", "sandneselektriske.no")
    assert result["verdict"] == "different_entity"


def test_shared_office_without_name_is_not_exact():
    # Accountant / manager site: same phone and address, but not this company's name.
    p = page("<html><body>Formue Regnskap. Strandgata 21, 4307 Sandnes. Tlf 51 66 00 00</body></html>", url="https://formue.no/")
    result = assess(identity(), [p], "registry_email_domain", "formue.no")
    assert result["verdict"] != "exact"


def test_legal_name_with_matching_domain_is_exact():
    p = page("<html><body>Velkommen til Sandnes Elektriske AS – din elektriker.</body></html>")
    assert assess(identity(), [p], "name_derived", "sandneselektriske.no")["verdict"] == "exact"


def test_name_only_on_unrelated_domain_is_ambiguous():
    p = page("<html><body>Sandnes Elektriske was mentioned in our list of partners.</body></html>", url="https://example.com/")
    assert assess(identity(), [p], "name_derived", "example.com")["verdict"] == "ambiguous"


def test_parked_domain_rejected():
    p = page("<html><title>Domenet er til salgs</title><body>This domain is for sale</body></html>")
    assert assess(identity(), [p], "name_derived", "sandneselektriske.no")["verdict"] == "parked"


# ------------------------------------------------------------------ extraction

def test_social_normalization():
    assert normalize_social("https://www.facebook.com/sharer/sharer.php?u=x") is None
    assert normalize_social("https://no.linkedin.com/company/sandnes-elektriske/about")["url"] == "https://www.linkedin.com/company/sandnes-elektriske"
    assert normalize_social("https://www.instagram.com/p/abc123/") is None
    assert normalize_social("https://www.youtube.com/@SandnesEl")["handle"] == "SandnesEl"


def test_personal_profile_on_one_page_not_published():
    home = page('<html><body><a href="https://www.facebook.com/sandneselektriske">fb</a> Org nr 810 034 882</body></html>')
    about = page('<html><body><a href="https://www.instagram.com/ola.nordmann">Ola</a><a href="https://www.facebook.com/sandneselektriske">fb</a></body></html>', url="https://sandneselektriske.no/om-oss", kind="about")
    facts = extract_facts([home, about], identity(), "sandneselektriske.no")
    published = {p["platform"]: p["url"] for p in facts["social_profiles"] if p["publishable"]}
    assert published == {"facebook": "https://www.facebook.com/sandneselektriske"}


# ------------------------------------------------------------------ envelope + refresh

def registry_fixture(revenue: float = 10021242.0):
    meta = lambda url: {"url": url, "status": 200, "retrieved_at": "2026-10-15T00:00:00Z", "sha256": "x" * 64, "error": None}  # noqa: E731
    return {
        "registry_live": {"meta": meta(f"https://data.brreg.no/enhetsregisteret/api/enheter/{ORG}"), "body": ENTITY},
        "roles": {"meta": meta("roles"), "body": {"rollegrupper": [{"type": {"kode": "DAGL"}, "sistEndret": "2016-07-11", "roller": [{"type": {"kode": "DAGL", "beskrivelse": "Daglig leder"}, "person": {"navn": {"fornavn": "Morten", "etternavn": "Aarrestad"}}}]}]}},
        "locations": {"meta": meta("subunits"), "body": {"_embedded": {"underenheter": []}}},
        "financials": {"meta": meta("accounts"), "body": [
            {"regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"}, "valuta": "NOK", "resultatregnskapResultat": {"aarsresultat": 500000.0, "driftsresultat": {"driftsresultat": 700000.0, "driftsinntekter": {"sumDriftsinntekter": revenue}}}},
            {"regnskapstype": "SELSKAP", "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}, "valuta": "NOK", "resultatregnskapResultat": {"aarsresultat": 400000.0, "driftsresultat": {"driftsresultat": 600000.0, "driftsinntekter": {"sumDriftsinntekter": 8524493.0}}}},
        ]},
    }


def make_profile(revenue: float = 10021242.0, jobs=None):
    jobs = jobs if jobs is not None else {"status": "not_available", "jobs": []}
    website = {"verdict": "not_found", "attempts": [{"url": "https://sandneselektriske.no/", "source": "name_derived", "verdict": "unreachable"}]}
    return build_profile(ORG, ENTITY, {"sha256": "y" * 64}, registry_fixture(revenue), website, jobs, "2026-10-15T00:00:00Z")


def test_every_family_has_a_valid_state_and_every_claim_has_evidence():
    profile = make_profile()
    assert set(profile["families"]) >= {"legal_identity", "annual_accounts", "leadership", "official_website", "hiring"}
    assert all(info["availability"] in STATES for info in profile["families"].values())
    evidence_ids = {item["id"] for item in profile["evidence"]}
    for claim in profile["claims"]:
        assert claim["evidence_ids"] and set(claim["evidence_ids"]) <= evidence_ids
    revenue = next(c for c in profile["claims"] if c["field"] == "revenue")
    assert revenue["value"] == {"amount": 10021242.0, "currency": "NOK"}
    assert revenue["reporting_period"] == "2025-01-01/2025-12-31"


def test_refresh_is_idempotent_and_detects_real_changes():
    first = apply_refresh(make_profile(), None, "run-1", "2026-10-14T00:00:00Z")
    first["run"] = {"run_id": "run-1", "completed_at": "2026-10-14T01:00:00Z"}
    same = apply_refresh(make_profile(), copy.deepcopy(first), "run-2", "2026-10-15T00:00:00Z")
    assert same["changes"] == []
    changed = apply_refresh(make_profile(revenue=12_000_000.0), copy.deepcopy(first), "run-3", "2026-10-16T00:00:00Z")
    fields = {c["field"] for c in changed["changes"] if c["material"]}
    assert "revenue" in fields
    assert changed["history"] and changed["history"][-1]["run_id"] == "run-1"


def test_failed_source_carries_forward_instead_of_false_removal():
    first = make_profile(jobs={"status": "available", "jobs": [{"uuid": "u1", "title": "Elektriker", "published": "2026-10-01", "employer_orgnr": ORG, "matched_via": "organisation", "public_url": "https://arbeidsplassen.nav.no/stillinger/stilling/u1", "source_url": "https://pam-stilling-feed.nav.no/api/v1/feedentry/u1", "retrieved_at": "2026-10-14T00:00:00Z", "sha256": "z" * 64}], "coverage_window": {}})
    first = apply_refresh(first, None, "run-1", "2026-10-14T00:00:00Z")
    first["run"] = {"run_id": "run-1"}
    outage = apply_refresh(make_profile(jobs={"status": "failed", "error": "timeout", "jobs": []}), copy.deepcopy(first), "run-2", "2026-10-15T00:00:00Z")
    assert not [c for c in outage["changes"] if c["type"] == "removed" and c["family"] == "hiring"]
    assert any(c.get("carried_forward") for c in outage["claims"] if c["family"] == "hiring")


def test_synthesis_cites_evidence_and_lists_unknowns():
    profile = apply_refresh(make_profile(), None, "run-1", "2026-10-15T00:00:00Z")
    synthesis = synthesize(profile, [])
    assert synthesis["sentences"] and all(s["evidence_ids"] for s in synthesis["sentences"])
    assert any(u["family"] == "official_website" for u in synthesis["unknowns"])
    assert "Revenue grew" in synthesis["summary"]


def test_vendor_credit_and_unnamed_accounts_not_published():
    html = ('<html><body><footer><a href="https://www.facebook.com/sandneselektriske">Facebook</a>'
            '<span>Design av <a href="https://x.com/Theme_Fusion">ThemeFusion</a></span>'
            '<a href="https://www.instagram.com/ola.nordmann">Instagram</a></footer></body></html>')
    pages = [page(html), page(html, url="https://sandneselektriske.no/kontakt", kind="contact")]
    facts = extract_facts(pages, identity(), "sandneselektriske.no")
    published = {p["platform"] for p in facts["social_profiles"] if p["publishable"]}
    assert published == {"facebook"}


def test_registry_declared_site_with_contact_details_is_exact():
    p = page("<html><body>Elektro i Sandnes. Strandgata 21, 4307 Sandnes. Tlf 51 66 00 00. post@sandneselektriske.no</body></html>", url="https://elektro-sandnes.no/")
    assert assess(identity(), [p], "registry_website", "elektro-sandnes.no")["verdict"] == "exact"
    # The same page reached only through a guessed domain stays unproven.
    assert assess(identity(), [p], "name_derived", "elektro-sandnes.no")["verdict"] != "exact"


def test_org_number_hidden_in_script_data_counts():
    p = page('<html><body><div id="root"></div><script>window.__DATA__={"footer":"Org.nr 810 034 882"}</script></body></html>')
    assert assess(identity(), [p], "name_derived", "sandneselektriske.no")["verdict"] == "exact"


def test_housing_manager_site_never_verifies_a_member_company():
    p = page("<html><body>OBOS Eiendomsforvaltning. Strandgata 21, 4307 Sandnes. Tlf 51 66 00 00 post@sandneselektriske.no</body></html>", url="https://www.obos.no/")
    assert assess(identity(), [p], "registry_website", "www.obos.no")["verdict"] != "exact"
