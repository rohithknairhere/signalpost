"""Official-website discovery, exact-entity verification and company-owned extraction.

Candidates come from the registry website field, the registry e-mail domain and
name-derived domains (checked with DNS first, which costs no HTTP request).
A candidate is published only when the site itself proves it belongs to this
organisation number: the number on the site, or the legal name corroborated by a
registry phone, e-mail or address. A site that shows another company's number
and not ours is never published.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from .net import BudgetExhausted, Fetcher, Response, local_dns_available, resolves
from .util import ascii_fold, clean_text, compact_org_pattern, digits, distinctive_tokens, name_tokens, org_numbers_in_text, tokens

FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.no", "outlook.com", "outlook.no", "live.com", "live.no",
    "msn.com", "yahoo.com", "yahoo.no", "icloud.com", "me.com", "mac.com", "online.no", "frisurf.no", "start.no",
    "c2i.net", "broadpark.no", "lyse.net", "getmail.no", "altibox.no", "telenor.com", "telia.no", "netcom.no",
    "chello.no", "bluezone.no", "ebnett.no", "tele2.no", "nextgentel.com", "haugnett.no", "tussa.com", "enivest.net",
    "sensewave.com", "mimer.no", "aol.com", "protonmail.com", "proton.me", "gmx.com", "gmx.net", "mail.com",
    "eunet.no", "tdcnorge.no", "powertech.no", "hesbynett.no", "loqal.no", "neasnett.no", "kvinnherad.net",
    "styrerommet.net", "styrerommet.no", "obos.no", "usbl.no", "bate.no", "boligbyggelag.no", "vestbo.no",
    "regnskapsbyraa.no", "visma.com", "uni.no", "epost.no", "epost.com", "post.com", "privat.no", "home.no",
}

PARKED_MARKERS = (
    "domain is for sale", "domain for sale", "this domain may be for sale", "hugedomains", "parked at",
    "domenet er til salgs", "domenet kan være til salgs", "her flytter snart", "web hosting", "coming soon",
    "denne siden er under oppbygging", "site under construction", "domeneshop", "is parked", "godaddy",
    "this site can't be reached", "default web site page", "it works!", "welcome to nginx", "index of /",
)

SOCIAL_HOSTS = {
    "linkedin.com": "linkedin", "facebook.com": "facebook", "fb.com": "facebook", "instagram.com": "instagram",
    "x.com": "x", "twitter.com": "x", "youtube.com": "youtube", "tiktok.com": "tiktok", "pinterest.com": "pinterest",
    "vimeo.com": "vimeo",
}
SOCIAL_REJECT_FIRST = {
    "facebook": {"sharer", "sharer.php", "share.php", "dialog", "policy.php", "privacy", "groups", "plugins", "tr", "login", "watch", "hashtag", "help", "legal", "business", "ads"},
    "instagram": {"p", "reel", "reels", "stories", "explore", "accounts", "about", "legal"},
    "x": {"intent", "share", "home", "search", "i", "hashtag", "privacy", "tos"},
    "linkedin": {"shareArticle", "sharing", "feed", "in", "pub", "jobs", "posts", "pulse", "legal"},
    "youtube": {"watch", "embed", "results", "playlist", "shorts", "t", "about"},
    "pinterest": {"pin", "search"},
    "vimeo": {"channels", "groups", "video", "categories"},
}
# Generic accounts that platform widgets, themes and agencies link to.
SOCIAL_GENERIC_HANDLES = {
    "wix", "wordpress", "squarespace", "shopify", "facebook", "instagram", "linkedin", "youtube", "twitter", "x",
    "google", "elementor", "godaddy", "webflow", "hubspot", "mailchimp", "tiktok", "pinterest", "vimeo",
}

SHARED_SERVICE_DOMAINS = {
    "obos.no", "usbl.no", "bate.no", "boligbyggelag.no", "vestbo.no", "bob.no", "tobb.no", "nbbo.no", "hsbo.no",
    "boligpartner.no", "ibbl.no", "mbbl.no", "sbbl.no", "abbl.no", "tbbl.no", "hbbl.no", "nobl.no", "styrerommet.no",
    "proff.no", "gulesider.no", "1881.no", "finn.no", "facebook.com", "linkedin.com", "instagram.com", "wix.com",
    "wixsite.com", "squarespace.com", "webnode.com", "weebly.com", "blogspot.com", "wordpress.com", "github.io",
    "mittanbud.no", "fagfolkguiden.no", "purehelp.no", "brreg.no", "google.com", "sites.google.com",
}
FOREIGN_LEGAL_SUFFIXES = {"ab", "aps", "oy", "oyj", "gmbh", "ag", "ltd", "limited", "inc", "llc", "bv", "nv", "sarl", "sas", "srl", "spa", "plc", "corp", "group"}
CREDIT_RE = re.compile(r"(levert av|utviklet av|laget av|designet av|design av|design:|nettside av|webdesign|powered by|designed by|developed by|theme by|made by|built by|drevet av)")
SOCIAL_VENDOR_HANDLES = {"theme_fusion", "themefusion", "envato", "elegantthemes", "elegant_themes", "wix", "wixcom", "squarespace",
                         "webflow", "framer", "godaddy", "onecom", "one_com", "domeneshop", "hostinger", "wordpressdotcom",
                         "woocommerce", "shopify", "mailchimp", "hubspot", "visma", "tripletex", "fiken", "nettsidegruppen",
                         "24sevenoffice", "proff", "gulesider", "1881", "finn", "finnno", "mittanbud"}

PAGE_HINTS = [
    ("contact", ("kontakt", "contact", "kontakt-oss", "contact-us", "finn-oss")),
    ("about", ("om-oss", "om_oss", "omoss", "about", "om-firmaet", "om-selskapet", "hvem-er-vi", "who-we-are", "selskapet", "firmaet", "historie")),
    ("legal", ("personvern", "privacy", "cookie", "vilkar", "salgsbetingelser", "terms", "kjopsvilkar", "imprint")),
    ("careers", ("karriere", "career", "careers", "jobb", "jobs", "ledige-stillinger", "stillinger", "jobbe-hos", "work-with-us", "join")),
    ("news", ("nyheter", "aktuelt", "news", "blogg", "blog", "presse", "press", "artikler", "nytt", "siste-nytt")),
    ("people", ("ansatte", "team", "folk", "medarbeidere", "ledelse", "management", "people", "vare-ansatte")),
]

PHONE_RE = re.compile(r"(?<!\d)(?:\+47[\s.-]?|0047[\s.-]?)?((?:\d[\s.-]?){8})(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
DATE_PATTERNS = [
    re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{1,2})\.\s?(\d{1,2})\.\s?(20\d{2})(?!\d)"),
]
NO_MONTHS = {"januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7, "august": 8,
             "september": 9, "oktober": 10, "november": 11, "desember": 12, "jan": 1, "feb": 2, "mar": 3,
             "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "okt": 10, "nov": 11, "des": 12,
             "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "october": 10, "december": 12}
TEXT_MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})\.?\s+(" + "|".join(sorted(NO_MONTHS, key=len, reverse=True)) + r")\.?\s+(20\d{2})(?!\d)", re.I)


# ---------------------------------------------------------------- domains

def registered_domain(host: str) -> str:
    host = (host or "").lower().rstrip(".").removeprefix("www.")
    parts = host.split(".")
    two_level = {"co.uk", "org.uk", "com.au", "co.nz", "com.br", "co.za", "priv.no", "co.no"}
    if len(parts) >= 3 and ".".join(parts[-2:]) in two_level:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def normalize_url(value: str | None) -> str | None:
    value = clean_text(value)
    if not value or " " in value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.lstrip("/")
    parsed = urllib.parse.urlparse(value)
    if not parsed.hostname or "." not in parsed.hostname:
        return None
    return urllib.parse.urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", "", ""))


def email_domain(email: str | None) -> str | None:
    email = clean_text(email).lower()
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip(".")
    if not domain or "." not in domain or domain in FREE_MAIL_DOMAINS or registered_domain(domain) in FREE_MAIL_DOMAINS:
        return None
    return domain


def name_domain_candidates(name: str, limit: int = 7) -> list[str]:
    folded = re.sub(r"\ba\s*/\s*s\b", " ", ascii_fold(name), flags=re.I)
    raw = [token for token in tokens(folded.replace("&", " ")) if token not in {"as", "asa", "ans", "da", "sa", "nuf", "enk", "ba"}]
    if not raw:
        return []
    variants: list[str] = []
    joined = "".join(raw)
    hyphen = "-".join(raw)
    without_og = [token for token in raw if token != "og"]
    for stem in (joined, hyphen, "".join(without_og), "-".join(without_og)):
        if 3 <= len(stem) <= 40 and stem not in variants:
            variants.append(stem)
    out = []
    for stem in variants:
        out.append(stem + ".no")
    if variants and len(variants[0]) <= 30:
        out.append(variants[0] + "as.no")  # e.g. brandmakeras.no
    for stem in variants:
        out.append(stem + ".com")
    return list(dict.fromkeys(out))[:limit]


# ---------------------------------------------------------------- parsing helpers

@dataclass
class Page:
    url: str
    kind: str
    status: int
    retrieved_at: str
    sha256: str | None
    title: str = ""
    text: str = ""
    soup: Any = None
    jsonld: list[Any] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    raw: str = ""


def _parse(response: Response, kind: str) -> Page:
    page = Page(response.final_url or response.url, kind, response.status, response.retrieved_at, response.sha256, error=response.error)
    if not response.ok or not response.body:
        return page
    content_type = response.headers.get("content-type", "")
    if content_type and "html" not in content_type.lower() and "xml" not in content_type.lower():
        page.error = f"unsupported content type {content_type[:60]}"
        return page
    page.raw = response.text()[:600_000]
    try:
        soup = BeautifulSoup(page.raw, "lxml")
    except Exception as exc:  # pragma: no cover - parser failure
        page.error = f"parse error {type(exc).__name__}"
        return page
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text() or ""
        try:
            page.jsonld.append(json.loads(raw.strip()))
        except ValueError:
            continue
    for tag in soup.select("meta[content]"):
        key = (tag.get("property") or tag.get("name") or "").strip().lower()
        if key and key not in page.meta:
            page.meta[key] = clean_text(tag.get("content"), 1000)
    page.title = clean_text(soup.title.get_text(" ") if soup.title else "", 300)
    for node in soup(["script", "style", "noscript", "svg", "template"]):
        node.decompose()
    page.soup = soup
    page.text = clean_text(soup.get_text(" "), 60_000)
    return page


def _walk_jsonld(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_jsonld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_jsonld(child)


def _jsonld_types(node: dict[str, Any]) -> set[str]:
    kind = node.get("@type")
    return set(kind if isinstance(kind, list) else [kind]) - {None}


ORG_TYPES = {"Organization", "Corporation", "LocalBusiness", "Store", "Restaurant", "ProfessionalService",
             "HomeAndConstructionBusiness", "AutomotiveBusiness", "LegalService", "MedicalBusiness", "Dentist",
             "FoodEstablishment", "LodgingBusiness", "RealEstateAgent", "AccountingService", "Electrician",
             "Plumber", "GeneralContractor", "RoofingContractor", "HVACBusiness", "TravelAgency", "Hotel"}


def normalize_social(url: str) -> dict[str, str] | None:
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("no.").removeprefix("nb-no.")
    platform = next((label for domain, label in SOCIAL_HOSTS.items() if host == domain or host.endswith("." + domain)), None)
    if not platform:
        return None
    parts = [urllib.parse.unquote(part).strip() for part in parsed.path.split("/") if part.strip()]
    if not parts:
        return None
    first_part = parts[0]
    if first_part.lower() in {item.lower() for item in SOCIAL_REJECT_FIRST.get(platform, set())}:
        return None
    if platform == "facebook" and first_part.lower() in {"profile.php", "people", "pages"}:
        if first_part.lower() == "profile.php":
            query_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
            if not query_id.isdigit():
                return None
            return {"platform": platform, "url": f"https://www.facebook.com/profile.php?id={query_id}", "handle": query_id}
        if first_part.lower() == "pages" and len(parts) >= 2:
            handle = parts[-1] if parts[-1].isdigit() and len(parts) >= 3 else parts[1]
            return {"platform": platform, "url": "https://www.facebook.com/" + "/".join(parts[:3]), "handle": parts[1]}
        return None
    if platform == "linkedin":
        if first_part.lower() not in {"company", "school", "showcase"} or len(parts) < 2:
            return None
        return {"platform": platform, "url": f"https://www.linkedin.com/{first_part.lower()}/{parts[1]}", "handle": parts[1]}
    if platform == "youtube":
        if first_part.startswith("@"):
            return {"platform": platform, "url": f"https://www.youtube.com/{first_part}", "handle": first_part[1:]}
        if first_part.lower() in {"channel", "user", "c"} and len(parts) >= 2:
            return {"platform": platform, "url": f"https://www.youtube.com/{first_part.lower()}/{parts[1]}", "handle": parts[1]}
        return None
    if platform == "tiktok":
        if not first_part.startswith("@"):
            return None
        return {"platform": platform, "url": f"https://www.tiktok.com/{first_part}", "handle": first_part[1:]}
    handle = first_part.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9._\-ÆØÅæøå]{2,80}", handle):
        return None
    canonical = {"facebook": "www.facebook.com", "instagram": "www.instagram.com", "x": "x.com", "pinterest": "www.pinterest.com", "vimeo": "vimeo.com"}[platform]
    return {"platform": platform, "url": f"https://{canonical}/{handle}", "handle": handle}


def _phones(text: str) -> set[str]:
    out = set()
    for match in PHONE_RE.finditer(text):
        number = digits(match.group(1))
        if len(number) == 8 and number[0] in "2345679":
            out.add(number)
    return out


def _parse_date(text: str) -> str | None:
    text = text or ""
    match = DATE_PATTERNS[0].search(text)
    try:
        if match:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
        match = DATE_PATTERNS[1].search(text)
        if match:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
        match = TEXT_MONTH_RE.search(text)
        if match:
            return date(int(match.group(3)), NO_MONTHS[match.group(2).lower().rstrip(".")], int(match.group(1))).isoformat()
    except (ValueError, KeyError):
        return None
    return None


# ---------------------------------------------------------------- verification

@dataclass
class Identity:
    org: str
    name: str
    phones: set[str]
    emails: set[str]
    postcodes: set[str]
    streets: set[str]
    subunit_orgs: set[str]
    historical_names: list[str]
    postal_places: set[tuple[str, str]] = field(default_factory=set)


def build_identity(org: str, entity: dict[str, Any], subunits: list[dict[str, Any]]) -> Identity:
    phones = {digits(entity.get(key))[-8:] for key in ("telefon", "mobil") if digits(entity.get(key))}
    emails = {clean_text(entity.get("epostadresse")).lower()} - {""}
    postcodes, streets, places = set(), set(), set()
    for key in ("forretningsadresse", "postadresse"):
        address = entity.get(key) or {}
        if address.get("postnummer"):
            postcodes.add(str(address["postnummer"]))
            if address.get("poststed"):
                places.add((str(address["postnummer"]), ascii_fold(address["poststed"])))
        for line in address.get("adresse") or []:
            street = " ".join(token for token in tokens(line) if not token.isdigit())
            if len(street) >= 5 and "postboks" not in street and "boks" not in street.split():
                streets.add(street)
    historical = [item.get("navn") for item in entity.get("historiskeNavn") or [] if item.get("navn")]
    for unit in subunits:
        text = ascii_fold(unit.get("address") or "")
        match = re.search(r"(\d{4}) ([a-z .-]+)$", text)
        if match:
            places.add((match.group(1), match.group(2).strip()))
    return Identity(org, entity.get("navn") or "", phones, emails, postcodes, streets,
                    {item["organisation_number"] for item in subunits if item.get("organisation_number")}, historical, places)


def _name_phrase_regex(name: str, with_suffix: bool) -> re.Pattern[str] | None:
    words = tokens(name.replace("&", " og "))
    if not with_suffix:
        words = [word for word in words if word not in {"as", "asa", "ans", "da", "sa", "nuf", "enk", "ba"}]
    if not words:
        return None
    return re.compile(r"(?<![a-z0-9])" + r"[\s\-_.,&]*(?:og[\s\-_.]*)?".join(re.escape(word) for word in words) + r"(?![a-z0-9])")


def _name_in_head(identity: Identity, home: Page) -> bool:
    """The company's own name is the site's title / site name (not just mentioned in a list)."""
    pattern = _name_phrase_regex(identity.name, False)
    head = ascii_fold(" ".join([home.title, home.meta.get("og:site_name", ""), home.meta.get("og:title", "")]))
    return bool(pattern and pattern.search(head))


def assess(identity: Identity, pages: list[Page], source: str, host: str, ignore_orgs: set[str] | None = None) -> dict[str, Any]:
    good = [page for page in pages if page.text or page.raw]
    if not good:
        return {"verdict": "unreachable", "score": 0.0, "signals": [], "other_orgs": []}
    all_text = " ".join(page.text for page in good)
    folded = ascii_fold(all_text)
    lowered_head = ascii_fold(" ".join([good[0].title, good[0].meta.get("og:site_name", ""), good[0].meta.get("description", ""), good[0].text[:3000]]))
    signals: list[str] = []
    if any(marker in lowered_head for marker in PARKED_MARKERS) and len(good[0].text) < 1500:
        return {"verdict": "parked", "score": 0.05, "signals": ["parked_or_placeholder_page"], "other_orgs": []}
    found_orgs = org_numbers_in_text(all_text)
    for page in good:
        for node in _walk_jsonld(page.jsonld):
            for key in ("taxID", "vatID", "leiCode", "identifier", "duns"):
                value = node.get(key)
                if isinstance(value, (str, int)):
                    found_orgs |= org_numbers_in_text(str(value)) | ({digits(value)} if len(digits(value)) == 9 else set())
    own = identity.org in found_orgs or bool(found_orgs & identity.subunit_orgs)
    if not own:
        # JavaScript-built sites (Wix, Squarespace...) keep footer text in script data.
        pattern = compact_org_pattern(identity.org)
        own = any(pattern.search(page.raw) for page in good if page.raw)
    others = sorted(found_orgs - {identity.org} - identity.subunit_orgs - (ignore_orgs or set()))
    if own:
        signals.append("organisation_number_on_site")
    names = [identity.name] + identity.historical_names
    legal_phrase = any((pattern := _name_phrase_regex(name, True)) and pattern.search(folded) for name in names)
    base_phrase = any((pattern := _name_phrase_regex(name, False)) and pattern.search(folded) for name in names)
    if legal_phrase:
        signals.append("legal_name_on_site")
    elif base_phrase:
        signals.append("name_on_site")
    site_phones = _phones(all_text)
    if identity.phones & site_phones:
        signals.append("registry_phone_on_site")
    site_emails = {email.lower().rstrip(".") for email in EMAIL_RE.findall(all_text)}
    if identity.emails & site_emails:
        signals.append("registry_email_on_site")
    address_hit = any(street in folded for street in identity.streets) and any(code in all_text for code in identity.postcodes)
    if address_hit:
        signals.append("registry_address_on_site")
    elif any(re.search(r"(?<!\d)" + re.escape(code) + r"\s+" + re.escape(place), folded) for code, place in identity.postal_places):
        signals.append("registry_postal_place_on_site")
    distinct = distinctive_tokens(identity.name) or [t for t in name_tokens(identity.name) if len(t) > 2]
    host_compact = re.sub(r"[^a-z0-9]", "", registered_domain(host).split(".")[0] if host else "")
    domain_matches_name = bool(distinct) and all(token in host_compact for token in distinct) and len("".join(distinct)) >= 3
    if domain_matches_name:
        signals.append("domain_matches_name")
    corroborators = {"registry_phone_on_site", "registry_email_on_site", "registry_address_on_site", "registry_postal_place_on_site"} & set(signals)

    site_domain = registered_domain(host)
    # Housing managers, accountants and e-mail providers serve many companies from one domain.
    shared_domain = site_domain in FREE_MAIL_DOMAINS or site_domain in SHARED_SERVICE_DOMAINS
    if shared_domain and not own:
        return {"verdict": "ambiguous" if (legal_phrase or base_phrase or corroborators) else "unrelated", "score": 0.5,
                "signals": signals + ["shared_service_domain"], "other_orgs": others[:5]}

    # Phone, e-mail and address only prove co-location (shared offices, accountants,
    # housing managers). Identity needs the organisation number or the company's own name.
    if own and len(others) >= 3 and not (legal_phrase or base_phrase):
        # Many organisation numbers and no name: a directory or group listing, not this company's own site.
        verdict, score = "ambiguous", 0.6
        signals.append("many_organisation_numbers_on_site")
    elif own:
        verdict, score = "exact", 0.99
    elif others:
        verdict, score = "different_entity", 0.2
        signals.append("other_organisation_number_on_site")
    elif source in {"registry_website", "wikidata_website", "previous_verified"} and legal_phrase:
        verdict, score = "exact", 0.96
    elif source in {"registry_website", "wikidata_website", "previous_verified"} and base_phrase and (domain_matches_name or corroborators):
        verdict, score = "exact", 0.94
    elif source in {"registry_website", "previous_verified"} and {"registry_phone_on_site", "registry_email_on_site", "registry_address_on_site"} <= set(signals) and not shared_domain:
        # The company declared this website in the official registry and the site shows its registry contact details.
        verdict, score = "exact", 0.93
    elif domain_matches_name and legal_phrase:
        verdict, score = "exact", 0.95
    elif source == "nav_employer_homepage" and legal_phrase and (domain_matches_name or corroborators):
        verdict, score = "exact", 0.93
    elif legal_phrase and {"registry_phone_on_site", "registry_address_on_site"} <= set(signals) and _name_in_head(identity, good[0]):
        verdict, score = "exact", 0.92
    elif source == "registry_email_domain" and domain_matches_name and len(corroborators) >= 2:
        # The company's own registered e-mail domain is named like it and shows its registry contact details.
        verdict, score = "exact", 0.92
    elif domain_matches_name and base_phrase and (corroborators or source == "registry_email_domain"):
        verdict, score = "exact", 0.92
    elif base_phrase or legal_phrase or corroborators:
        verdict, score = "ambiguous", 0.6
    else:
        verdict, score = "unrelated", 0.2
    return {"verdict": verdict, "score": score, "signals": signals, "other_orgs": others[:5]}


# ---------------------------------------------------------------- crawling

def _same_site(url: str, domain: str) -> bool:
    return registered_domain(urllib.parse.urlparse(url).hostname or "") == domain


def _classify_links(page: Page, domain: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {kind: [] for kind, _ in PAGE_HINTS}
    if page.soup is None:
        return found
    seen = set()
    for anchor in page.soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urllib.parse.urljoin(page.url, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not _same_site(url, domain):
            continue
        if re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?|mp4|webp|svg)$", parsed.path, re.I):
            continue
        clean = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, ""))
        if clean in seen or clean.rstrip("/") == page.url.rstrip("/"):
            continue
        seen.add(clean)
        haystack = ascii_fold(parsed.path + " " + anchor.get_text(" ", strip=True))
        haystack = re.sub(r"[\s_]+", "-", haystack)
        for kind, hints in PAGE_HINTS:
            if any(hint in haystack for hint in hints):
                if len(parsed.path) <= 80:
                    found[kind].append(clean)
                break
    for kind in found:
        found[kind].sort(key=len)
    return found


def _fetch_page(fetcher: Fetcher, url: str, kind: str) -> Page:
    response = fetcher.get(url, module="website", timeout=15)
    return _parse(response, kind)


def research_website(fetcher: Fetcher, identity: Identity, candidates: list[tuple[str, str]], *, max_candidates: int = 3, max_pages: int = 6) -> dict[str, Any]:
    """Try candidates in priority order; return the verified site with extracted facts.

    candidates: [(url, source)] where source is registry_website | registry_email_domain | name_derived.
    """
    attempts: list[dict[str, Any]] = []
    tried_domains: set[str] = set()
    fetched = 0
    for url, source in candidates:
        if fetched >= max_candidates:
            break
        host = urllib.parse.urlparse(url).hostname or ""
        domain = registered_domain(host)
        if domain in tried_domains:
            continue
        tried_domains.add(domain)
        if source in {"name_derived", "previous_verified"} and not resolves(host, fetcher):
            attempts.append({"url": url, "source": source, "verdict": "no_dns"})
            continue
        if source != "name_derived" and local_dns_available() and not resolves(host) and not resolves("www." + host.removeprefix("www.")):
            attempts.append({"url": url, "source": source, "verdict": "no_dns"})
            continue
        if not fetcher.can_spend(3):
            attempts.append({"url": url, "source": source, "verdict": "budget_skipped"})
            break
        fetched += 1
        try:
            result = _research_one(fetcher, identity, url, source, max_pages=max_pages)
        except BudgetExhausted:
            attempts.append({"url": url, "source": source, "verdict": "budget_exhausted"})
            break
        attempts.append({key: result.get(key) for key in ("url", "final_url", "source", "verdict", "score", "signals", "other_orgs", "error")})
        if result["verdict"] == "exact":
            result["attempts"] = attempts
            return result
    previous = next((item for item in attempts if item.get("source") == "previous_verified"), None)
    if previous and previous.get("verdict") in {"unreachable", "budget_skipped", "budget_exhausted"} and _transient(previous.get("error")):
        # Last run's verified site could not be read now: unknown, not removed.
        return {"verdict": "failed", "error": f"previously verified site unreachable this run ({previous.get('error')})", "attempts": attempts}
    blocked = any(item.get("error") == "robots_disallowed" for item in attempts)
    ambiguous = [item for item in attempts if item.get("verdict") in {"ambiguous", "different_entity"}]
    return {"verdict": "blocked" if blocked and not ambiguous else ("ambiguous" if ambiguous else "not_found"), "attempts": attempts}


def _transient(error: str | None) -> bool:
    """A fetch failure that does not prove the site is gone (the DNS check already passed)."""
    return not any(code in (error or "") for code in ("HTTP 404", "HTTP 410"))


def _research_one(fetcher: Fetcher, identity: Identity, url: str, source: str, *, max_pages: int) -> dict[str, Any]:
    home = _fetch_page(fetcher, url, "home")
    if not home.text and url.startswith("https://") and home.error and "robots" not in home.error:
        alts = [url.replace("https://", "https://www.", 1)] if "://www." not in url else [url.replace("://www.", "://", 1), url.replace("https://", "http://", 1)]
        for alt in alts:
            if not fetcher.can_spend(2):
                break
            home = _fetch_page(fetcher, alt, "home")
            if home.text:
                break
    if not home.text and not home.raw:
        return {"url": url, "final_url": home.url, "source": source, "verdict": "blocked" if home.error == "robots_disallowed" else "unreachable", "score": 0, "signals": [], "error": home.error or f"HTTP {home.status}"}
    final_host = urllib.parse.urlparse(home.url).hostname or ""
    domain = registered_domain(final_host)
    pages = [home]
    links = _classify_links(home, domain)
    first_check = assess(identity, pages, source, final_host)
    order = ["contact", "about", "legal", "careers", "news", "people"]
    if first_check["verdict"] == "exact":
        order = ["contact", "about", "careers", "news", "people", "legal"]
    elif first_check["verdict"] in {"parked", "unrelated"} and source == "name_derived":
        return {"url": url, "final_url": home.url, "source": source, **first_check}
    guesses = {"contact": "/kontakt", "about": "/om-oss"}
    for kind, path in guesses.items():
        if not links.get(kind):
            # Menus built by JavaScript hide links; the common Norwegian paths often still exist.
            links[kind] = [urllib.parse.urljoin(home.url, path)]
    queue: list[tuple[str, str]] = []
    for kind in order:
        for link in links.get(kind, [])[:(2 if kind in {"news", "careers"} and first_check["verdict"] == "exact" else 1)]:
            if link not in {item[0] for item in queue}:
                queue.append((link, kind))
    budget_pages = max_pages - 1
    verdict = first_check
    for link, kind in queue:
        if budget_pages <= 0 or not fetcher.can_spend(2):
            break
        page = _fetch_page(fetcher, link, kind)
        budget_pages -= 1
        if page.text and _same_site(page.url, domain):
            pages.append(page)
            if kind in {"news", "careers"} and page.soup is not None:
                pass
        verdict = assess(identity, pages, source, final_host)
        # Unverified sites: stop early once verification pages are exhausted.
        if verdict["verdict"] in {"different_entity"}:
            break
        if verdict["verdict"] != "exact" and kind in {"careers", "news", "people"}:
            break
    if verdict["verdict"] == "different_entity" and ({"legal_name_on_site", "name_on_site"} & set(verdict["signals"])) and fetcher.can_spend(3):
        # Footers often carry the web agency's or accountant's organisation number. Look the
        # other numbers up: only numbers belonging to a company with a related name block us.
        unrelated = set()
        ours = set(distinctive_tokens(identity.name)) or set(name_tokens(identity.name))
        for other in verdict["other_orgs"][:2]:
            other_name, other_industry = _registry_name(fetcher, other)
            if other_name is None:
                break
            service_provider = str(other_industry or "")[:2] in SERVICE_PROVIDER_SECTIONS
            if service_provider and not (ours & (set(distinctive_tokens(other_name)) or set(name_tokens(other_name)))):
                unrelated.add(other)
        if unrelated and unrelated >= set(verdict["other_orgs"][:2]) and len(verdict["other_orgs"]) <= 2:
            retry = assess(identity, pages, source, final_host, ignore_orgs=unrelated)
            retry["signals"] = retry["signals"] + ["other_numbers_belong_to_unrelated_companies"]
            retry["ignored_orgs"] = sorted(unrelated)
            verdict = retry
    candidate_domain = registered_domain(urllib.parse.urlparse(url).hostname or "")
    if verdict["verdict"] == "exact" and domain != candidate_domain and "organisation_number_on_site" not in verdict["signals"] and "domain_matches_name" not in verdict["signals"]:
        # Redirected to another organisation's platform (franchise, chain or directory page).
        verdict = {**verdict, "verdict": "ambiguous", "score": 0.6, "signals": verdict["signals"] + ["redirected_to_unrelated_domain"]}
    result = {"url": url, "final_url": home.url, "domain": domain, "source": source, **verdict}
    if verdict["verdict"] == "exact":
        result["pages"] = [_page_record(page) for page in pages]
        result["extracted"] = extract_facts(pages, identity, domain)
    return result


# Web agencies, IT/hosting, marketing and accounting firms put their own number in site footers.
SERVICE_PROVIDER_SECTIONS = {"62", "63", "73", "74", "69", "58", "18"}
_NAME_CACHE: dict[str, tuple[str | None, str | None]] = {}


def _registry_name(fetcher: Fetcher, org: str) -> tuple[str | None, str | None]:
    if org in _NAME_CACHE:
        return _NAME_CACHE[org]
    response = fetcher.get(f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}", module="website_identity", respect_robots=False, accept="application/json", timeout=15)
    result: tuple[str | None, str | None] = (None, None)
    if response.ok:
        try:
            body = json.loads(response.body.decode("utf-8"))
            result = (body.get("navn") or "", (body.get("naeringskode1") or {}).get("kode"))
        except ValueError:
            pass
    _NAME_CACHE[org] = result
    return result


def _page_record(page: Page) -> dict[str, Any]:
    return {"url": page.url, "kind": page.kind, "status": page.status, "retrieved_at": page.retrieved_at, "sha256": page.sha256, "title": page.title}


# ---------------------------------------------------------------- extraction

def extract_facts(pages: list[Page], identity: Identity, domain: str) -> dict[str, Any]:
    home = pages[0]
    socials: dict[tuple[str, str], dict[str, Any]] = {}
    jsonld_orgs: list[dict[str, Any]] = []
    for page in pages:
        candidates: list[tuple[str, str]] = []
        if page.soup is not None:
            for node in page.soup.select("a[href]"):
                before = node.previous_sibling
                before_text = before if isinstance(before, str) else (before.get_text(" ") if before is not None and hasattr(before, "get_text") else "")
                context = ascii_fold(" ".join([node.get_text(" "), str(node.get("title") or ""), str(node.get("aria-label") or ""), str(before_text)[-60:]]))
                if CREDIT_RE.search(context):
                    continue  # "designed by / levert av / theme by" credits link to vendors, not the company
                candidates.append((str(node.get("href") or ""), "link"))
            for node in page.soup.select("iframe[src]"):
                src = str(node.get("src") or "")
                if "facebook.com/plugins" in src:
                    embedded = urllib.parse.parse_qs(urllib.parse.urlparse(src).query).get("href", [])
                    candidates.extend((item, "embed") for item in embedded)
        for node in _walk_jsonld(page.jsonld):
            if _jsonld_types(node) & ORG_TYPES:
                jsonld_orgs.append(node)
                same_as = node.get("sameAs")
                for item in same_as if isinstance(same_as, list) else [same_as]:
                    if isinstance(item, str):
                        candidates.append((item, "jsonld_sameAs"))
        for raw, how in candidates:
            social = normalize_social(urllib.parse.urljoin(page.url, raw))
            if not social or social["handle"].lower() in SOCIAL_GENERIC_HANDLES:
                continue
            key = (social["platform"], social["url"].lower())
            entry = socials.setdefault(key, {**social, "found_on": page.url, "found_on_sha256": page.sha256, "retrieved_at": page.retrieved_at, "methods": set(), "pages": set()})
            entry["methods"].add(how)
            entry["pages"].add(page.url)
    brand_hint = clean_text(home.meta.get("og:site_name"), 120)
    # One canonical profile per platform: prefer sameAs, then the link present on most pages, then name match.
    name_compact = "".join(name_tokens(identity.name))
    distinct = distinctive_tokens(identity.name)
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for entry in socials.values():
        handle_compact = re.sub(r"[^a-z0-9]", "", ascii_fold(entry["handle"]))
        domain_stem = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
        brand_compact = re.sub(r"[^a-z0-9]", "", ascii_fold(brand_hint))
        entry["handle_matches_name"] = bool(
            (distinct and (name_compact in handle_compact or all(token in handle_compact for token in distinct)))
            or (len(domain_stem) >= 4 and domain_stem in handle_compact)
            or (len(brand_compact) >= 4 and brand_compact in handle_compact)
            or any(len(token) >= 5 and token[:6] in handle_compact for token in distinct)
        )
        if entry["handle"].lower().replace("-", "_") in SOCIAL_VENDOR_HANDLES:
            entry["handle_matches_name"] = False
        handle_parts = re.split(r"[^a-z0-9]+", ascii_fold(entry["handle"]))
        if handle_parts and handle_parts[-1] in FOREIGN_LEGAL_SUFFIXES and handle_parts[-1] not in tokens(identity.name):
            # e.g. "protech-ab" on a Norwegian AS's group site: the foreign parent's profile.
            entry["handle_matches_name"] = False
            entry["methods"].discard("jsonld_sameAs")
        by_platform.setdefault(entry["platform"], []).append(entry)
    profiles = []
    for platform, entries in by_platform.items():
        entries.sort(key=lambda item: ("jsonld_sameAs" not in item["methods"], not item["handle_matches_name"], -len(item["pages"]), len(item["url"])))
        best = entries[0]
        unique = len(entries) == 1
        # Company-owned: declared in structured data, named like the company, or the only
        # profile on that platform linked site-wide (header/footer on several pages).
        # A single link on one page (e.g. an employee's personal account) is not enough.
        # Company-owned only when declared in structured data or named like the company,
        # its domain or its brand. Unnamed links (owners' personal accounts, theme vendors) are quarantined.
        confident = "jsonld_sameAs" in best["methods"] or best["handle_matches_name"]
        profiles.append({
            "platform": platform,
            "url": best["url"],
            "handle": best["handle"],
            "found_on": best["found_on"],
            "found_on_sha256": best["found_on_sha256"],
            "retrieved_at": best["retrieved_at"],
            "method": sorted(best["methods"]),
            "handle_matches_name": best["handle_matches_name"],
            "alternatives": [item["url"] for item in entries[1:4]],
            "publishable": confident,
        })
    profiles.sort(key=lambda item: item["platform"])

    contact_pages = [page for page in pages if page.kind in {"home", "contact", "about"}]
    contact_text = " ".join(page.text for page in contact_pages)
    site_emails = sorted({email.lower() for email in EMAIL_RE.findall(contact_text) if registered_domain(email.split("@")[1]) == domain or email.lower() in identity.emails})[:5]
    site_phones = sorted(_phones(contact_text))[:5]
    brand = clean_text(home.meta.get("og:site_name"), 120)
    description = clean_text(home.meta.get("description") or home.meta.get("og:description"), 600)
    for node in jsonld_orgs:
        if not brand and isinstance(node.get("name"), str):
            brand = clean_text(node["name"], 120)
        if not description and isinstance(node.get("description"), str):
            description = clean_text(node["description"], 600)
    if not brand and home.title:
        brand = clean_text(re.split(r"\s[|\-–—:·]\s", home.title)[-1] if re.search(r"\s[|\-–—:·]\s", home.title) else home.title, 120)
    about_text = ""
    for page in pages:
        if page.kind == "about" and page.text:
            about_text = page.text[:1200]
            break
    careers = next((page for page in pages if page.kind == "careers" and page.text), None)
    news = extract_news(pages, domain)
    job_postings = extract_job_postings(pages, domain)
    founding = next((str(node.get("foundingDate")) for node in jsonld_orgs if node.get("foundingDate")), None)
    return {
        "brand_name": brand or None,
        "description": description or None,
        "about_excerpt": about_text or None,
        "social_profiles": profiles,
        "emails": site_emails,
        "phones": site_phones,
        "careers_page": {"url": careers.url, "title": careers.title, "retrieved_at": careers.retrieved_at, "sha256": careers.sha256} if careers else None,
        "news": news,
        "job_postings": job_postings,
        "jsonld_founding_date": founding,
        "language": (home.soup.html.get("lang") if home.soup is not None and home.soup.html else None),
    }


def extract_job_postings(pages: list[Page], domain: str, limit: int = 15) -> list[dict[str, Any]]:
    """schema.org JobPosting published on the company's own pages (still open only)."""
    today_iso = date.today().isoformat()
    found: dict[str, dict[str, Any]] = {}
    for page in pages:
        for node in _walk_jsonld(page.jsonld):
            if "JobPosting" not in _jsonld_types(node):
                continue
            title = clean_text(node.get("title") or node.get("name"), 160)
            posted = str(node.get("datePosted") or "")[:10]
            valid = str(node.get("validThrough") or "")[:10]
            if not title or (valid and valid < today_iso):
                continue
            url = node.get("url") or page.url
            location = node.get("jobLocation")
            if isinstance(location, list):
                location = location[0] if location else None
            city = ((location or {}).get("address") or {}).get("addressLocality") if isinstance(location, dict) and isinstance((location or {}).get("address"), dict) else None
            found.setdefault(f"{title}|{url}", {"title": title, "date_posted": posted or None, "valid_through": valid or None, "location": city,
                                               "employment_type": node.get("employmentType") if isinstance(node.get("employmentType"), str) else None,
                                               "url": str(url), "found_on": page.url, "sha256": page.sha256, "retrieved_at": page.retrieved_at})
    return sorted(found.values(), key=lambda item: item.get("date_posted") or "", reverse=True)[:limit]


def extract_news(pages: list[Page], domain: str, limit: int = 8) -> list[dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    today_iso = date.today().isoformat()
    for page in pages:
        for node in _walk_jsonld(page.jsonld):
            if _jsonld_types(node) & {"NewsArticle", "BlogPosting", "Article", "PressRelease"}:
                published = str(node.get("datePublished") or "")[:10]
                headline = clean_text(node.get("headline") or node.get("name"), 200)
                url = node.get("url") or node.get("mainEntityOfPage") or page.url
                if isinstance(url, dict):
                    url = url.get("@id") or page.url
                if headline and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", published) and published <= today_iso:
                    items.setdefault(str(url), {"title": headline, "date": published, "url": str(url), "found_on": page.url, "sha256": page.sha256, "retrieved_at": page.retrieved_at, "method": "jsonld"})
        if page.kind != "news" or page.soup is None:
            continue
        for container in page.soup.select("article, li, .post, .news-item, .card, .entry, div[class*=news], div[class*=post], div[class*=article]")[:200]:
            anchor = container.select_one("a[href]")
            if anchor is None:
                continue
            title = clean_text(anchor.get_text(" "), 200)
            heading = container.select_one("h1, h2, h3, h4")
            if heading is not None and len(clean_text(heading.get_text(" "))) > 8:
                title = clean_text(heading.get_text(" "), 200)
            if len(title) < 8:
                continue
            time_tag = container.select_one("time[datetime]")
            published = _parse_date(str(time_tag.get("datetime"))) if time_tag is not None else None
            if not published:
                published = _parse_date(clean_text(container.get_text(" "), 400))
            if not published or published > today_iso or published < "2015-01-01":
                continue
            url = urllib.parse.urljoin(page.url, str(anchor.get("href")))
            if not _same_site(url, domain):
                continue
            items.setdefault(url, {"title": title, "date": published, "url": url, "found_on": page.url, "sha256": page.sha256, "retrieved_at": page.retrieved_at, "method": "listing"})
    ordered = sorted(items.values(), key=lambda item: item["date"], reverse=True)
    return ordered[:limit]
