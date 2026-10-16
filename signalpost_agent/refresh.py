"""Idempotent refresh: compare with the previous snapshot, keep earlier evidence.

- A change is a difference in a claim's normalized value (not in retrieval times).
- Re-running on the same source content produces zero changes and no duplicates.
- A family that failed or was blocked this run keeps the previous claims, marked
  `carried_forward`, instead of reporting a false removal.
- Earlier evidence is preserved in `history` with the snapshot it came from.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .util import sha256_json, stable_id

# Fields whose movement is worth flagging to a reader.
MATERIAL_FIELDS = {
    "legal_name", "registry_status", "business_address", "registered_employees", "share_capital", "industry",
    "revenue", "operating_result", "annual_result", "equity", "accounts_year", "chief_executive", "board_chair",
    "auditor", "workplace_count", "official_website", "active_job_posting_count", "latest_activity_date",
    "linkedin_profile", "facebook_profile", "instagram_profile", "youtube_profile", "brand_name", "in_corporate_group",
}
VOLATILE_FIELDS = {"registry_status_as_of"}


def claim_key(claim: dict[str, Any]) -> str:
    return f"{claim['family']}|{claim['field']}|{claim.get('key') or ''}"


def load_previous(path: Path | None, org: str) -> dict[str, Any] | None:
    if path is None:
        return None
    candidate = path / f"{org}.json"
    if candidate.exists():
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except ValueError:
            return None
    return None


def load_previous_jsonl(path: Path | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if path is None or not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            org = row.get("organisation_number")
            if org:
                out[org] = row
    return out


def _summary(field: str, before: Any, after: Any) -> str:
    def short(value: Any) -> str:
        if isinstance(value, dict) and "amount" in value:
            return f"{value.get('currency') or ''} {value['amount']:,.0f}".strip()
        if isinstance(value, list):
            return f"{len(value)} items"
        return str(value)[:80]

    label = field.replace("_", " ")
    if before is None:
        return f"{label} added: {short(after)}"
    if after is None:
        return f"{label} no longer found (was {short(before)})"
    return f"{label} changed from {short(before)} to {short(after)}"


def apply_refresh(profile: dict[str, Any], previous: dict[str, Any] | None, run_id: str, run_started: str) -> dict[str, Any]:
    """Mutates and returns profile with changes, carried-forward claims and history."""
    if not previous:
        profile["changes"] = []
        profile["history"] = []
        profile["refresh"] = {"previous_snapshot": None, "mode": "first_observation"}
        return profile
    prev_claims = {claim_key(claim): claim for claim in previous.get("claims", [])}
    prev_evidence = {item["id"]: item for item in previous.get("evidence", [])}
    current = {claim_key(claim): claim for claim in profile["claims"]}
    families = profile["families"]
    changes: list[dict[str, Any]] = []
    carried = 0
    for key, old in prev_claims.items():
        if key in current:
            continue
        family_state = (families.get(old["family"]) or {}).get("availability")
        if family_state in {"failed", "blocked"} or old.get("carried_forward"):
            # Source unavailable this run: keep the last verified value, clearly labelled.
            kept = {**old, "carried_forward": True, "carried_from_snapshot": previous.get("run", {}).get("run_id")}
            profile["claims"].append(kept)
            for evidence_id in old.get("evidence_ids", []):
                if evidence_id in prev_evidence and all(item["id"] != evidence_id for item in profile["evidence"]):
                    profile["evidence"].append({**prev_evidence[evidence_id], "carried_forward": True})
            carried += 1
            continue
        changes.append(_change(old, None, run_id))
    for key, new in current.items():
        old = prev_claims.get(key)
        if old is None:
            changes.append(_change(None, new, run_id))
        elif sha256_json(old.get("value")) != sha256_json(new.get("value")):
            changes.append(_change(old, new, run_id))
    for change in changes:
        if change["field"] in {"dated_events", "verification_signals", "roles", "workplaces", "financial_series", "filing_copies", "filed_account_years", "company_news", "active_job_postings"}:
            change["material"] = False
    history = list(previous.get("history") or [])
    prev_run = previous.get("run") or {}
    snapshot_entry = {
        "run_id": prev_run.get("run_id"),
        "completed_at": prev_run.get("completed_at"),
        "profile_sha256": previous.get("profile_sha256"),
        "evidence": [
            {key: item.get(key) for key in ("id", "source_url", "source_class", "retrieved_at", "content_sha256", "reporting_period")}
            for item in previous.get("evidence", [])
        ],
        "claims": [{key: claim.get(key) for key in ("id", "field", "key", "value", "evidence_ids")} for claim in previous.get("claims", []) if claim["field"] in MATERIAL_FIELDS],
    }
    if not history or history[-1].get("profile_sha256") != snapshot_entry["profile_sha256"]:
        if prev_run.get("run_id") != run_id:
            history.append(snapshot_entry)
    profile["changes"] = sorted(changes, key=lambda change: (not change["material"], change["field"]))
    profile["history"] = history[-10:]
    profile["refresh"] = {
        "previous_snapshot": prev_run.get("run_id"),
        "previous_completed_at": prev_run.get("completed_at"),
        "mode": "refresh",
        "changes": len(changes),
        "material_changes": sum(1 for change in changes if change["material"]),
        "carried_forward_claims": carried,
    }
    return profile


def _change(old: dict[str, Any] | None, new: dict[str, Any] | None, run_id: str) -> dict[str, Any]:
    ref = new or old
    assert ref is not None
    before = old.get("value") if old else None
    after = new.get("value") if new else None
    kind = "added" if old is None else "removed" if new is None else "changed"
    return {
        "id": stable_id(claim_key(ref), sha256_json(before), sha256_json(after), prefix="chg"),
        "type": kind,
        "family": ref["family"],
        "field": ref["field"],
        "key": ref.get("key"),
        "before": before,
        "after": after,
        "material": ref["field"] in MATERIAL_FIELDS,
        "summary": _summary(ref["field"], before, after),
        "evidence_ids": (new or {}).get("evidence_ids") or [],
        "previous_evidence_ids": (old or {}).get("evidence_ids") or [],
        "detected_in_run": run_id,
    }
