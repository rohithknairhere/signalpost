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


def test_annual_report_workforce_parsing():
    from signalpost_agent.annual_report import parse_workforce

    assert parse_workforce("Note 2 - Antall arsverk\nAntall arsverk sysselsatt i regnskapsaret: 8,87")["value"] == 8.87
    assert parse_workforce("Selskapet har ikke hatt noen ansatte i 2025.")["kind"] == "no_employees"
    assert parse_workforce("Gjennomsnittlig antall ansatte i regnskapsaret: 12")["kind"] == "average_employees"
    assert parse_workforce("Lonnskostnader 1 234 567") is None


def test_jobposting_structured_data_on_company_site():
    from signalpost_agent.website import extract_job_postings

    html = ('<html><head><script type="application/ld+json">{"@type":"JobPosting","title":"Elektriker","datePosted":"2026-10-01",'
            '"validThrough":"2099-01-01","jobLocation":{"address":{"addressLocality":"Sandnes"}}}</script>'
            '<script type="application/ld+json">{"@type":"JobPosting","title":"Old job","validThrough":"2020-01-01"}</script></head><body>Jobb</body></html>')
    jobs = extract_job_postings([page(html, kind="careers")], "sandneselektriske.no")
    assert [job["title"] for job in jobs] == ["Elektriker"] and jobs[0]["location"] == "Sandnes"


def test_foreign_parent_profile_not_published_for_norwegian_company():
    html = '<html><body><a href="https://www.linkedin.com/company/sandnes-elektriske-ab">LinkedIn</a></body></html>'
    pages = [page(html), page(html, url="https://sandneselektriske.no/om-oss", kind="about")]
    facts = extract_facts(pages, identity(), "sandneselektriske.no")
    assert not [p for p in facts["social_profiles"] if p["publishable"]]


def test_contact_page_addresses():
    from signalpost_agent.website import extract_addresses

    text = "Kontakt oss: Strandgata 21, 4307 Sandnes. Postboks 32, 4301 Sandnes. Tlf 51 66 00 00"
    assert extract_addresses(text) == ["Strandgata 21, 4307 Sandnes"]


def test_parent_group_site_is_not_published():
    from signalpost_agent.website import classify_ownership

    ident = build_identity("999999999", {**ENTITY, "navn": "PROTECH NORGE AS"}, [])
    p = page("<html><body>Protech AB is the parent of Protech Norge AS and Protech Danmark ApS.</body></html>", url="https://www.protech.se/")
    assert classify_ownership(ident, [p], "protech.se", ["legal_name_on_site", "domain_matches_name"])[0] == "group"


def test_shared_site_takes_no_profiles_news_or_jobs():
    html = ('<html><body><a href="https://www.facebook.com/voltbyen">fb</a><a href="https://www.instagram.com/sandneselektriske">ig</a>'
            '<script type="application/ld+json">{"@type":"JobPosting","title":"Elektriker","validThrough":"2099-01-01"}</script></body></html>')
    pages = [page(html, url="https://voltbyen.no/"), page(html, url="https://voltbyen.no/kontakt", kind="contact")]
    facts = extract_facts(pages, identity(), "voltbyen.no", ownership="shared")
    assert not [p for p in facts["social_profiles"] if p["publishable"]]  # shared/brand site: no profiles at all
    assert facts["job_postings"] == [] and facts["news"] == []
    own = extract_facts(pages, identity(), "voltbyen.no", ownership="own")
    assert {p["platform"] for p in own["social_profiles"] if p["publishable"]} == {"facebook", "instagram"}


def test_group_and_vendor_profiles_rejected_even_on_own_site():
    html = ('<html><body><a href="https://www.facebook.com/sandneselektriskegruppen">fb</a>'
            '<a href="https://www.instagram.com/themeisle">ig</a><a href="https://www.linkedin.com/company/sandnes-elektriske">li</a></body></html>')
    pages = [page(html), page(html, url="https://sandneselektriske.no/om-oss", kind="about")]
    facts = extract_facts(pages, identity(), "sandneselektriske.no", ownership="own")
    assert {p["platform"] for p in facts["social_profiles"] if p["publishable"]} == {"linkedin"}


def test_backs_off_after_too_many_requests():
    import time as _time

    from signalpost_agent.net import Fetcher

    fetcher = Fetcher(max_requests=10, deadline_monotonic=_time.monotonic() + 600)
    assert fetcher._back_off("example.com", "120", 429) == 120  # honours Retry-After
    response = fetcher.get("https://example.com/", module="test", respect_robots=False, max_wait=5)
    assert response.status == 429 and "rate_limited" in (response.error or "")
    assert fetcher.used == 0  # no request was sent while the host is cooling down
    assert fetcher._back_off("slow.example.com", None, 429) == 10 and fetcher._back_off("slow.example.com", None, 429) == 20


def test_industry_word_alone_does_not_match_and_country_sections_are_group():
    from signalpost_agent.website import classify_ownership

    ident = build_identity("999999998", {**ENTITY, "navn": "LUCRA REGNSKAP AS"}, [])
    html = '<html><body><a href="https://www.facebook.com/evoregnskap">fb</a><a href="https://www.facebook.com/lucraregnskap">fb2</a></body></html>'
    pages = [page(html, url="https://lucraregnskap.no/"), page(html, url="https://lucraregnskap.no/om-oss", kind="about")]
    facts = extract_facts(pages, ident, "lucraregnskap.no", ownership="own")
    assert [p["url"] for p in facts["social_profiles"] if p["publishable"]] == ["https://www.facebook.com/lucraregnskap"]
    ident2 = build_identity("999999997", {**ENTITY, "navn": "SCANVAEGT SYSTEMS AS"}, [])
    section = page("<html><body>Scanvaegt Systems AS org.nr 999 999 997</body></html>", url="https://www.scanvaegt.com/no")
    assert classify_ownership(ident2, [section], "scanvaegt.com", ["organisation_number_on_site", "legal_name_on_site"])[0] == "group"


def test_chain_brand_profiles_not_published_for_member_company():
    ident = build_identity("999999998", {**ENTITY, "navn": "LUCRA REGNSKAP AS"}, [])
    html = ('<html><head><meta property="og:site_name" content="Evo Regnskap">'
            '<script type="application/ld+json">{"@type":"Organization","name":"Evo Regnskap","sameAs":["https://www.facebook.com/evoregnskap"]}</script>'
            '</head><body><a href="https://www.linkedin.com/company/evoregnskap">li</a></body></html>')
    pages = [page(html, url="https://lucraregnskap.no/"), page(html, url="https://lucraregnskap.no/om-oss", kind="about")]
    facts = extract_facts(pages, ident, "lucraregnskap.no", ownership="own")
    assert not [p for p in facts["social_profiles"] if p["publishable"]]


def test_sister_brand_profiles_and_own_language_sections():
    from signalpost_agent.website import classify_ownership

    ident = build_identity("999999996", {**ENTITY, "navn": "FRIHEIM AKADEMIET AS"}, [])
    html = ('<html><body><a href="https://www.instagram.com/friheimtrainingcenter">a</a>'
            '<a href="https://www.facebook.com/friheimakademiet">b</a></body></html>')
    pages = [page(html, url="https://friheimakademiet.no/"), page(html, url="https://friheimakademiet.no/om-oss", kind="about")]
    facts = extract_facts(pages, ident, "friheimakademiet.no", ownership="own")
    assert [p["platform"] for p in facts["social_profiles"] if p["publishable"]] == ["facebook"]
    spenn = build_identity("999999995", {**ENTITY, "navn": "SPENN GROUP AS"}, [])
    section = page("<html><body>Spenn Group AS</body></html>", url="https://spenngroup.com/nb-NO")
    assert classify_ownership(spenn, [section], "spenngroup.com", ["organisation_number_on_site", "domain_matches_name"])[0] == "own"


def test_menu_words_before_own_name_are_not_a_group():
    from signalpost_agent.website import classify_ownership

    ident = build_identity("999999994", {**ENTITY, "navn": "FLOTTE GULV AS"}, [])
    home = page("<html><body>Facebook-f Instagram Flotte Gulv AS. Kontakt Flotte Gulv AS</body></html>", url="https://flottegulv.no/")
    assert classify_ownership(ident, [home], "flottegulv.no", ["legal_name_on_site", "domain_matches_name"])[0] == "own"
    sister = page("<html><body>Flotte Gulv AS og Flotte Gulv Bergen AS</body></html>", url="https://flottegulv.no/")
    assert classify_ownership(ident, [sister], "flottegulv.no", ["legal_name_on_site", "domain_matches_name"])[0] == "group"


def test_glued_foreign_suffix_handle_rejected():
    ident = build_identity("999999993", {**ENTITY, "navn": "WHATEVER THE SEASON AS"}, [])
    html = ('<html><body><a href="https://www.facebook.com/whatevertheseasonltd">a</a>'
            '<a href="https://www.instagram.com/whatevertheseason">b</a></body></html>')
    pages = [page(html, url="https://whatevertheseason.com/"), page(html, url="https://whatevertheseason.com/about", kind="about")]
    facts = extract_facts(pages, ident, "whatevertheseason.com", ownership="own")
    assert [p["platform"] for p in facts["social_profiles"] if p["publishable"]] == ["instagram"]


def test_norwegian_letter_domains_and_place_names():
    from signalpost_agent.website import host_name_forms, name_domain_candidates

    candidates = name_domain_candidates("Bjørn Løkken Rør AS")
    assert "bjornlokkenror.no" in candidates and "bjoernloekkenroer.no" in candidates
    assert any(item.startswith("xn--") for item in candidates)
    assert name_domain_candidates("Ås Bygg AS")[0] == "asbygg.no"  # the place name Ås is kept
    assert name_domain_candidates("AS Vinmonopolet")[0] == "vinmonopolet.no"
    assert "bjornlokkenror" in host_name_forms("www.bjoernloekkenroer.no")


def test_feed_news_is_dated_and_same_site():
    from signalpost_agent.website import Page, extract_news

    rss = ("<?xml version='1.0'?><rss><channel><item><title>Ny avdeling i Bergen</title><link>https://www.ex.no/ny/</link>"
           "<pubDate>Tue, 09 Sep 2025 10:00:00 +0000</pubDate></item><item><title>Elsewhere</title><link>https://other.no/a</link>"
           "<pubDate>Tue, 09 Sep 2025 10:00:00 +0000</pubDate></item><item><title>Undated</title><link>https://www.ex.no/u</link></item></channel></rss>")
    news = extract_news([Page("https://www.ex.no/feed/", "feed", 200, "t", "h", raw=rss)], "ex.no")
    assert [(item["date"], item["url"]) for item in news] == [("2025-09-09", "https://www.ex.no/ny/")]


def test_own_name_inside_menu_text_is_not_a_related_company():
    from signalpost_agent.website import classify_ownership

    ident = build_identity("999999996", {**ENTITY, "navn": "WONGRAVEN WINES AS"}, [])
    own = page("<html><body>Øl Wongraven Saison Wongraven Wines AS. Contact Wongraven Wines AS</body></html>", url="https://wongravenwines.no/")
    assert classify_ownership(ident, [own], "wongravenwines.no", ["legal_name_on_site", "domain_matches_name"])[0] == "own"
    parent = page("<html><body>Wongraven Wines AS er en del av Wongraven Holding AS</body></html>", url="https://wongravenwines.no/")
    assert classify_ownership(ident, [parent], "wongravenwines.no", ["legal_name_on_site", "domain_matches_name"])[0] == "group"


def test_parent_domains_holding_names_and_international_profiles():
    from signalpost_agent.website import classify_ownership

    ent = lambda name: build_identity("999999995", {**ENTITY, "navn": name}, [])
    home = lambda url, text="": page(f"<html><body>{text}</body></html>", url=url)
    corr = ["legal_name_on_site", "registry_phone_on_site", "registry_address_on_site"]
    assert classify_ownership(ent("OPSAHL EIENDOM AS"), [home("https://opsahlgruppen.no/")], "opsahlgruppen.no", corr + ["domain_matches_name"])[0] == "group"
    assert classify_ownership(ent("PELLERIN HOLDING AS"), [home("https://pellerin.no/")], "pellerin.no", ["name_on_site", "registry_phone_on_site", "domain_matches_name"])[0] == "group"
    assert classify_ownership(ent("RØDØY-LURØY KRAFTVERK AS"), [home("https://www.sks.no/")], "sks.no", corr + ["organisation_number_on_site"], "registry_email_domain")[0] == "group"
    assert classify_ownership(ent("INNVIK FRUKTLAGER SA"), [home("https://www.innvikfrukt.no/")], "innvikfrukt.no", corr, "registry_website")[0] == "own"
    assert classify_ownership(ent("MØLLER BIL INNLANDET AS"), [home("https://mollerbil.no/forhandler/hamar")], "mollerbil.no", corr, "registry_website")[0] == "shared"
    html = '<html><body><a href="https://www.linkedin.com/company/trescal">li</a><a href="https://www.facebook.com/trescalnorway">fb</a></body></html>'
    pages = [page(html, url="https://trescal.no/"), page(html, url="https://trescal.no/om-oss", kind="about")]
    facts = extract_facts(pages, ent("TRESCAL NORWAY AS"), "trescal.no", ownership="own")
    assert [p["url"] for p in facts["social_profiles"] if p["publishable"]] == ["https://www.facebook.com/trescalnorway"]


def test_own_number_on_shortened_email_domain_is_own():
    from signalpost_agent.website import classify_ownership

    ident = build_identity("999999994", {**ENTITY, "navn": "DAHLES DELESERVICE AS"}, [])
    signals = ["organisation_number_on_site", "legal_name_on_site", "registry_phone_on_site", "registry_address_on_site"]
    assert classify_ownership(ident, [page("<html><body>x</body></html>", url="https://dahledel.no/")], "dahledel.no", signals, "registry_email_domain")[0] == "own"


def test_single_letter_name_parts_and_named_investment_companies():
    from signalpost_agent.website import classify_ownership, name_domain_candidates

    assert "a-seafood.com" in name_domain_candidates("A-SEAFOOD AS", limit=12)
    ident = build_identity("999999993", {**ENTITY, "navn": "CARLIN INVEST AS"}, [])
    signals = ["legal_name_on_site", "registry_phone_on_site", "domain_matches_name"]
    assert classify_ownership(ident, [page("<html><body>Carlin Invest AS</body></html>", url="https://www.carlin.no/")], "carlin.no", signals)[0] == "own"
