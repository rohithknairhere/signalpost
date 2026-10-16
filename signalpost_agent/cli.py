"""One-command batch runner.

    signalpost --organisations companies.jsonl --bulk brreg-enheter.csv --output out/envelopes.jsonl

Reads a JSON/JSONL/TXT list of organisation numbers and writes exactly one terminal
envelope per input, a profiles file, a machine-readable run report and a static
viewer. Flags mirror the Builderr starter's `run_competition_batch.py` so the
evaluator's existing command keeps working.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from . import AGENT_NAME, __version__
from .assemble import FAMILIES, build_profile
from .jobs import NavJobIndex
from .net import BudgetExhausted, Fetcher
from .refresh import apply_refresh, load_previous, load_previous_jsonl
from .registry import fetch_account_years, fetch_registry, load_bulk, normalize_subunits
from .reviews import applies as reviews_applies, fetch_rating
from .synthesis import synthesize
from .wikidata import best_website, lookup as wikidata_lookup
from .util import clean_text, normalized_name, sha256_json, utc_now
from .website import build_identity, email_domain, name_domain_candidates, normalize_url, research_website

STARTER_STATE = {"available": "complete", "not_available": "not_found", "blocked": "blocked_policy", "not_applicable": "not_applicable", "ambiguous": "not_found", "failed": "source_error"}
FAMILY_TO_MODULE = {
    "legal_identity": "registry_live", "annual_accounts": "financials", "account_history": "financial_history",
    "leadership": "roles", "registered_workplaces": "locations", "official_website": "website",
    "company_profiles": "social_profiles", "hiring": "jobs", "public_activity": "activity", "ratings_reviews": "reviews",
}


def read_inputs(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    stripped = text.lstrip()
    values: list[Any]
    if stripped.startswith("["):
        values = json.loads(stripped)
    elif stripped.startswith("{") and "\n" not in stripped.strip():
        body = json.loads(stripped)
        values = body.get("organisation_numbers") or body.get("companies") or [body]
    elif stripped.startswith("{"):
        try:
            body = json.loads(stripped)
            values = body.get("organisation_numbers") or body.get("companies") or [body]
        except ValueError:
            values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = [line.strip().split(",")[0] for line in text.splitlines() if line.strip()]
    orgs: list[str] = []
    for value in values:
        raw = value.get("organisation_number") or value.get("organisasjonsnummer") or value.get("orgnr") if isinstance(value, dict) else value
        org = "".join(ch for ch in str(raw or "") if ch.isdigit())
        if len(org) == 9 and org not in orgs:
            orgs.append(org)
        elif len(org) != 9 and str(raw or "").strip() not in ("", "organisation_number", "orgnr"):
            orgs.append(str(raw).strip())  # kept so it still gets a terminal envelope
    return orgs


def plan_for(n: int, max_requests: int) -> dict[str, Any]:
    nav_pages = 200 if n <= 200 else 80 if n <= 600 else 30
    allowance = (max_requests - nav_pages - 30) / max(n, 1)
    if allowance >= 12:
        return {"tier": "full", "years": n <= 400, "registry": ["registry_live", "roles", "locations", "financials"], "candidates": 4, "pages": 7, "nav_pages": nav_pages, "allowance": round(allowance, 1)}
    if allowance >= 6:
        return {"tier": "reduced", "years": False, "registry": ["registry_live", "roles", "locations", "financials"], "candidates": 1, "pages": 3, "nav_pages": nav_pages, "allowance": round(allowance, 1)}
    return {"tier": "minimal", "years": False, "registry": ["roles", "financials"], "candidates": 1, "pages": 2, "nav_pages": min(nav_pages, 30), "allowance": round(allowance, 1)}


def website_candidates(entity: dict[str, Any], tier: str, wikidata_entry: dict[str, Any] | None = None, subunit_names: list[str] | None = None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    registered = normalize_url(entity.get("hjemmeside"))
    if registered:
        out.append((registered, "registry_website"))
    if wikidata_entry:
        wd_site = normalize_url(best_website(wikidata_entry))
        if wd_site:
            out.append((wd_site, "wikidata_website"))
    domain = email_domain(entity.get("epostadresse"))
    if domain:
        out.append((f"https://{domain}/", "registry_email_domain"))
    if tier != "minimal":
        for candidate in name_domain_candidates(entity.get("navn") or ""):
            out.append((f"https://{candidate}/", "name_derived"))
        # Former names and trading names of registered workplaces often own the domain.
        extra_names = [item.get("navn") for item in entity.get("historiskeNavn") or [] if item.get("navn")]
        extra_names += [name for name in (subunit_names or []) if name]
        seen = {normalized_name(entity.get("navn"))}
        for name in extra_names:
            key = normalized_name(name)
            if not key or key in seen:
                continue
            seen.add(key)
            for candidate in name_domain_candidates(name, limit=2)[:1]:
                out.append((f"https://{candidate}/", "name_derived"))
            if len(seen) > 3:
                break
    return out


def failed_envelope(org: str, run: dict[str, Any], error: str) -> dict[str, Any]:
    families = {family: {"availability": "failed", "reason": error} for family in FAMILIES}
    return {
        "organisation_number": org,
        "run_id": run["run_id"],
        "state": "source_error",
        "terminal_status": "failed",
        "availability": "failed",
        "started_at": run["started_at"],
        "completed_at": utc_now(),
        "run": {**run, "terminal_status": "failed", "completed_at": utc_now()},
        "name": org,
        "families": families,
        "modules": {module: {"state": "source_error", "availability": "failed", "retry_count": 0, "final_timestamp": utc_now()} for module in FAMILY_TO_MODULE.values()},
        "claims": [],
        "evidence": [],
        "changes": [],
        "history": [],
        "synthesis": {"summary": f"Research failed for {org}: {error}", "sentences": [], "unknowns": [], "changes": []},
        "errors": [{"stage": "pipeline", "error": error}],
        "operations": {"requests": 0, "third_party_cost_usd": 0},
    }


def starter_compat(profile: dict[str, Any], registry: dict[str, Any], website: dict[str, Any] | None) -> dict[str, Any]:
    """A compact copy in the starter kit's profile shape for evaluators built on it."""
    def module(name: str, value: Any) -> dict[str, Any]:
        item = registry.get(name) or {}
        meta = item.get("meta") or {}
        status = "available" if meta.get("status") == 200 else "not_found" if meta.get("status") in (404, 410) else "source_error"
        return {"field": name, "status": status, "source_url": meta.get("url"), "retrieved_at": meta.get("retrieved_at"), "content_sha256": meta.get("sha256"), "value": value}

    claims = {claim["field"]: claim["value"] for claim in profile["claims"]}
    site = {"field": "website", "status": "not_found", "source_url": None, "value": None}
    if website and website.get("verdict") == "exact":
        socials = [{"platform": c["key"], "url": c["value"]} for c in profile["claims"] if c["family"] == "company_profiles"]
        site = {"field": "website", "status": "available", "source_type": "verified_company_website", "source_url": website.get("final_url"),
                "value": {"final_url": website.get("final_url"), "registered_domain": website.get("domain"), "social_links": socials,
                          "identity_assessment": {"status": "exact", "publishable": True, "score": website.get("score"), "reasons": website.get("signals")}}}
    elif website and website.get("verdict") == "blocked":
        site["status"] = "blocked"
    return {
        "organisation_number": profile["organisation_number"],
        "name": profile.get("name"),
        "legal_form": (claims.get("legal_form") or {}).get("code"),
        "website": claims.get("official_website"),
        "evidence": {
            "registry_live": module("registry_live", {"organisation_number": profile["organisation_number"], "name": profile.get("name")}),
            "financials": module("financials", {"records": [c for c in profile["claims"] if c["family"] == "annual_accounts"]}),
            "roles": module("roles", {"roles": claims.get("roles") or []}),
            "locations": module("locations", {"locations": claims.get("workplaces") or []}),
            "website": site,
        },
    }


def research_company(org: str, ctx: dict[str, Any]) -> dict[str, Any]:
    fetcher: Fetcher = ctx["fetcher"]
    plan = ctx["plan"]
    run = ctx["run"]
    started = time.monotonic()
    used_before = fetcher.used
    errors: list[dict[str, Any]] = []
    bulk_entity = ctx["bulk"].get(org)
    registry: dict[str, Any] = {}
    try:
        registry = fetch_registry(fetcher, org, want_years=False) if len(org) == 9 else {}
        if plan["registry"] != ["registry_live", "roles", "locations", "financials"]:
            registry = {key: value for key, value in registry.items() if key in plan["registry"] or key == "financial_history"}
    except Exception as exc:
        errors.append({"stage": "registry", "error": f"{type(exc).__name__}: {exc}"})
    live = registry.get("registry_live") or {}
    entity = live.get("body") if (live.get("meta") or {}).get("status") == 200 and live.get("body") else (bulk_entity or {})
    if bulk_entity and entity is not bulk_entity:
        # Fields only the bulk file carries (or that the live record omits) fill gaps.
        for key, value in bulk_entity.items():
            entity.setdefault(key, value)
    if not entity and len(org) != 9:
        return failed_envelope(org, run, "input is not a valid 9-digit Norwegian organisation number")
    subunits = normalize_subunits((registry.get("locations") or {}).get("body")) if (registry.get("locations") or {}).get("body") else []
    previous = ctx["previous"].get(org) or load_previous(ctx["state_dir"], org)
    previous_site = next((claim["value"] for claim in (previous or {}).get("claims", []) if claim.get("field") == "official_website"), None)
    website: dict[str, Any] | None = None
    if entity:
        identity = build_identity(org, entity, subunits)
        candidates = website_candidates(entity, plan["tier"], ctx["wikidata"].get(org), [unit.get("name") for unit in subunits])
        if previous_site and normalize_url(previous_site):
            # Re-check the site verified last run first, so refreshes stay stable.
            candidates = [(normalize_url(previous_site), "previous_verified")] + [item for item in candidates if item[0] != normalize_url(previous_site)]
        try:
            website = research_website(fetcher, identity, candidates, max_candidates=plan["candidates"], max_pages=plan["pages"])
        except BudgetExhausted as exc:
            website = {"verdict": "failed", "error": str(exc), "attempts": []}
        except Exception as exc:
            errors.append({"stage": "website", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            website = {"verdict": "failed", "error": f"{type(exc).__name__}", "attempts": []}
    jobs = None
    nav: NavJobIndex = ctx["nav"]
    ctx["nav_ready"].wait(timeout=max(1.0, fetcher.seconds_left() - 60))
    try:
        names = [entity.get("navn") or ""] + [item.get("navn") for item in entity.get("historiskeNavn") or [] if item.get("navn")]
        names += [unit.get("name") for unit in subunits if unit.get("name")]
        if website and website.get("verdict") == "exact":
            brand = (website.get("extracted") or {}).get("brand_name")
            if brand:
                names.append(brand)
        jobs = nav.jobs_for(org, [name for name in names if name], {unit["organisation_number"] for unit in subunits if unit.get("organisation_number")})
    except Exception as exc:
        errors.append({"stage": "jobs", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        jobs = {"status": "failed", "error": str(exc), "jobs": []}

    # NAV ads confirmed by organisation number carry the employer's own homepage: one more lead.
    if entity and (not website or website.get("verdict") != "exact"):
        tried = {normalize_url(item.get("url")) for item in (website or {}).get("attempts", [])}
        homepages = []
        for job in (jobs or {}).get("jobs") or []:
            homepage = normalize_url(job.get("employer_homepage"))
            if homepage and job.get("matched_via") == "organisation" and homepage not in tried:
                parsed = homepage.split("/")
                homepages.append(("/".join(parsed[:3]) + "/", "nav_employer_homepage"))
        if homepages:
            try:
                second = research_website(fetcher, build_identity(org, entity, subunits), list(dict.fromkeys(homepages))[:1], max_candidates=1, max_pages=plan["pages"])
                if second.get("verdict") == "exact" or not website:
                    second["attempts"] = (website or {}).get("attempts", []) + second.get("attempts", [])
                    website = second
                else:
                    website["attempts"] = website.get("attempts", []) + second.get("attempts", [])
            except Exception as exc:
                errors.append({"stage": "website_nav_lead", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})

    reviews_result: dict[str, Any] | None = None
    if entity:
        ok, reason = reviews_applies(entity)
        if not ok:
            reviews_result = {"status": "not_applicable", "reason": reason}
        elif fetcher.can_spend(1, reserve=40):
            try:
                reviews_result = fetch_rating(fetcher, org, entity.get("navn") or org)
            except Exception as exc:
                errors.append({"stage": "reviews", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                reviews_result = {"status": "failed", "error": type(exc).__name__}
        else:
            reviews_result = {"status": "failed", "error": "request budget reserved for core sources"}

    if plan["years"] and len(org) == 9 and fetcher.seconds_left() > 120:
        # Rate-limited endpoint (~30/min): read last so it never delays the other sources.
        registry["financial_history"] = fetch_account_years(fetcher, org)
    bulk_meta = {"sha256": ctx["bulk_meta"].get("sha256"), "retrieved_at": ctx["bulk_meta"].get("loaded_at"), "source_url": ctx["bulk_meta"].get("source_url")}
    profile = build_profile(org, bulk_entity, bulk_meta, registry, website, jobs, run["started_at"], wikidata=ctx["wikidata"].get(org), wikidata_status=ctx["wikidata_status"], reviews=reviews_result)
    profile = apply_refresh(profile, previous, run["run_id"], run["started_at"])
    profile["synthesis"] = synthesize(profile, profile["changes"])
    completed = utc_now()
    families = profile["families"]
    modules = {}
    for family, module in FAMILY_TO_MODULE.items():
        availability = families[family]["availability"]
        modules[module] = {"state": STARTER_STATE[availability], "availability": availability, "retry_count": 0, "final_timestamp": completed}
    terminal_failed = families["legal_identity"]["availability"] == "failed"
    envelope = {
        "organisation_number": org,
        "run_id": run["run_id"],
        "state": "source_error" if terminal_failed else "complete",
        "terminal_status": "failed" if terminal_failed else "completed",
        "availability": "failed" if terminal_failed else "available",
        "started_at": run["started_at"],
        "completed_at": completed,
        "run": {"run_id": run["run_id"], "started_at": run["started_at"], "completed_at": completed, "terminal_status": "failed" if terminal_failed else "completed", "agent": f"{AGENT_NAME}/{__version__}"},
        "name": profile.get("name"),
        "summary": profile["synthesis"]["summary"],
        "families": families,
        "modules": modules,
        "claims": profile["claims"],
        "evidence": profile["evidence"],
        "changes": profile["changes"],
        "history": profile["history"],
        "refresh": profile["refresh"],
        "synthesis": profile["synthesis"],
        "website_research": {"verdict": (website or {}).get("verdict"), "attempts": (website or {}).get("attempts", [])},
        "errors": errors,
        "operations": {"requests": fetcher.used - used_before, "runtime_ms": int((time.monotonic() - started) * 1000), "third_party_cost_usd": 0},
        "profile": starter_compat(profile, registry, website),
    }
    envelope["profile_sha256"] = sha256_json({"claims": [(c["family"], c["field"], c.get("key"), c["value"]) for c in profile["claims"]]})
    return envelope


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="signalpost", description="Research Norwegian companies from organisation numbers; one evidence-backed envelope per input.")
    parser.add_argument("--organisations", "--input", "-i", required=True, help="JSON, JSONL or text list of organisation numbers")
    parser.add_argument("--bulk", help="Brreg Enhetsregisteret bulk snapshot (CSV, optionally gzipped). Optional: the live registry is used when absent.")
    parser.add_argument("--output", "-o", default="out/envelopes.jsonl", help="terminal envelope JSONL")
    parser.add_argument("--profiles-output", help="profile JSONL (defaults next to --output)")
    parser.add_argument("--report", help="run report JSON (defaults next to --output)")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--expected-count", type=int, default=None, help="fail fast if the input does not contain exactly this many companies")
    parser.add_argument("--previous", help="previous envelopes JSONL to refresh against (optional; --state-dir is used otherwise)")
    parser.add_argument("--state-dir", default="state", help="where snapshots and caches persist between runs")
    parser.add_argument("--max-requests", type=int, default=int(os.environ.get("SIGNALPOST_MAX_REQUESTS", 1900)))
    parser.add_argument("--time-budget-minutes", type=float, default=float(os.environ.get("SIGNALPOST_TIME_BUDGET_MINUTES", 40)))
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--viewer", default=None, help="write the static viewer here (default: <output dir>/site/index.html)")
    parser.add_argument("--no-viewer", action="store_true")
    parser.add_argument("--web-data", default=None, help="also write the dataset for the web app (e.g. public/data/profiles.json)")
    parser.add_argument("--resume", action="store_true", help="accepted for starter compatibility; snapshots make reruns idempotent")
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--modules", default=None, help="accepted for starter compatibility")
    args = parser.parse_args(argv)

    wall_start = time.monotonic()
    started_at = utc_now()
    run_id = args.run_id or f"run-{started_at.replace(':', '').replace('-', '')}"
    output = Path(args.output)
    profiles_output = Path(args.profiles_output) if args.profiles_output else output.with_name("profiles.jsonl")
    report_path = Path(args.report) if args.report else output.with_name("run-report.json")
    state_dir = Path(args.state_dir)
    (state_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    (state_dir / "cache").mkdir(parents=True, exist_ok=True)

    orgs = read_inputs(Path(args.organisations))
    if args.expected_count is not None and len(orgs) != args.expected_count:
        print(f"Expected {args.expected_count} organisations, received {len(orgs)}", file=sys.stderr)
        return 2
    deadline = wall_start + args.time_budget_minutes * 60
    fetcher = Fetcher(max_requests=args.max_requests, deadline_monotonic=deadline)
    plan = plan_for(len(orgs), args.max_requests)
    print(f"[signalpost] {len(orgs)} companies, plan={plan}", file=sys.stderr)

    bulk, bulk_meta = load_bulk(args.bulk, orgs)
    bulk_meta["loaded_at"] = utc_now()
    bulk_meta["source_url"] = "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv"
    print(f"[signalpost] bulk snapshot matched {len(bulk)}/{len(orgs)} in {bulk_meta.get('seconds')}s", file=sys.stderr)

    nav = NavJobIndex(fetcher, state_dir / "cache", max_pages=plan["nav_pages"])
    nav_ready = threading.Event()

    def build_nav() -> None:
        try:
            nav.build()
        finally:
            nav_ready.set()

    threading.Thread(target=build_nav, daemon=True).start()
    wikidata, wikidata_status = wikidata_lookup(fetcher, orgs)
    print(f"[signalpost] wikidata matched {len(wikidata)} companies ({wikidata_status['status']})", file=sys.stderr)
    run = {"run_id": run_id, "started_at": started_at}
    ctx = {
        "fetcher": fetcher, "plan": plan, "run": run, "wikidata": wikidata, "wikidata_status": wikidata_status, "bulk": bulk, "bulk_meta": bulk_meta, "nav": nav, "nav_ready": nav_ready,
        "previous": load_previous_jsonl(Path(args.previous)) if args.previous else {}, "state_dir": state_dir / "snapshots",
    }
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(research_company, org, ctx): org for org in orgs}
        for index, future in enumerate(as_completed(futures), 1):
            org = futures[future]
            try:
                results[org] = future.result()
            except Exception as exc:
                traceback.print_exc()
                results[org] = failed_envelope(org, run, f"{type(exc).__name__}: {str(exc)[:200]}")
            if index % args.checkpoint_every == 0:
                print(f"[signalpost] {index}/{len(orgs)} done, {fetcher.used} requests, {int(time.monotonic() - wall_start)}s", file=sys.stderr)
                write_jsonl(output.with_suffix(".partial.jsonl"), [results[o] for o in orgs if o in results])

    completed_at = utc_now()
    envelopes = [results.get(org) or failed_envelope(org, run, "missing result") for org in orgs]
    for envelope in envelopes:
        envelope["run"]["batch_completed_at"] = completed_at
    write_jsonl(output, envelopes)
    profiles = [{key: env.get(key) for key in ("organisation_number", "name", "summary", "families", "claims", "evidence", "changes", "synthesis", "refresh", "run")} for env in envelopes]
    write_jsonl(profiles_output, profiles)
    for env in envelopes:
        if env.get("terminal_status") == "completed":
            snapshot = state_dir / "snapshots" / f"{env['organisation_number']}.json"
            snapshot.write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")
    try:
        partial = output.with_suffix(".partial.jsonl")
        if partial.exists():
            partial.unlink()
    except OSError:
        pass

    orgs_seen = [env["organisation_number"] for env in envelopes]
    family_counts: dict[str, dict[str, int]] = {}
    for env in envelopes:
        for family, info in env["families"].items():
            family_counts.setdefault(family, {}).setdefault(info["availability"], 0)
            family_counts[family][info["availability"]] += 1
    validation = {
        "exact_expected_count": args.expected_count is None or len(envelopes) == args.expected_count,
        "one_envelope_per_input": len(envelopes) == len(orgs) and len(set(orgs_seen)) == len(orgs_seen),
        "all_terminal": all(env.get("terminal_status") in {"completed", "failed"} for env in envelopes),
        "all_family_states_valid": all(info["availability"] in {"available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"} for env in envelopes for info in env["families"].values()),
        "every_claim_has_evidence": all(set(claim["evidence_ids"]) <= {ev["id"] for ev in env["evidence"]} and claim["evidence_ids"] for env in envelopes for claim in env["claims"]),
    }
    validation["passed"] = all(validation.values())
    report = {
        "agent": f"{AGENT_NAME}/{__version__}",
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "runtime_seconds": round(time.monotonic() - wall_start, 1),
        "expected_count": args.expected_count,
        "input_count": len(orgs),
        "emitted_envelopes": len(envelopes),
        "plan": plan,
        "registry_snapshot": {key: bulk_meta.get(key) for key in ("source", "sha256", "rows_scanned", "matched", "seconds")},
        "operations": {**fetcher.report(), "third_party_cost_usd": 0.0, "llm_calls": 0},
        "wikidata": {**wikidata_status, "matched": len(wikidata)},
        "jobs_feed": {"status": nav.status, "error": nav.error, "pages_read": nav.pages_read, "items_indexed": len(nav.items), "window": {"from": nav.oldest_covered, "to": nav.newest_covered}},
        "family_availability": family_counts,
        "companies_with_verified_website": sum(1 for env in envelopes if env["families"].get("official_website", {}).get("availability") == "available"),
        "companies_with_job_postings": sum(1 for env in envelopes if any(c["field"] == "active_job_postings" for c in env["claims"])),
        "material_changes": sum(1 for env in envelopes for change in env.get("changes", []) if change.get("material")),
        "validation": validation,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.no_viewer:
        try:
            from .viewer import write_viewer

            viewer_path = Path(args.viewer) if args.viewer else output.parent / "site" / "index.html"
            write_viewer(viewer_path, envelopes, report, web_data=Path(args.web_data) if args.web_data else None)
            report["viewer"] = str(viewer_path)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:  # the viewer never blocks the data contract
            print(f"[signalpost] viewer not written: {exc}", file=sys.stderr)
    print(json.dumps({key: report[key] for key in ("run_id", "input_count", "emitted_envelopes", "runtime_seconds", "operations", "companies_with_verified_website", "companies_with_job_postings", "validation")}, indent=2))
    return 0 if validation["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
