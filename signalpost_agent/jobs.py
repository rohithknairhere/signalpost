"""Job postings from NAV's public job-vacancy feed (pam-stilling-feed.nav.no).

The feed pages (1,000 items each) carry only the employer's display name, so we
read recent pages once per run, shortlist ads whose employer name matches a batch
company (or one of its registered workplaces), then confirm each shortlisted ad's
employer organisation number from the ad itself. Only confirmed, currently active
ads are published. Feed pages are cached on disk so later runs only read new pages.

Terms: https://arbeidsplassen.nav.no/vilkar-api (inactive ads are never published).
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from .net import BudgetExhausted, Fetcher
from .util import normalized_name, sha256_bytes, today, utc_now

BASE = "https://pam-stilling-feed.nav.no"
TOKEN_URL = BASE + "/api/publicToken"
FEED_URL = BASE + "/api/v1/feed"
ENTRY_URL = BASE + "/api/v1/feedentry/{uuid}"
PUBLIC_AD_URL = "https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}"


_NOISE = {"avd", "avdeling", "avdelingen", "filial", "norge"}


def _keys(name: Any) -> list[str]:
    """Exact normalized name, plus an order-insensitive token set ("Elkjøp Støren" = "STØREN ELKJØP AS")."""
    exact = normalized_name(name)
    if len(exact) < 3:
        return []
    words = sorted(set(exact.split()) - _NOISE)
    keys = [exact]
    if len(words) >= 2:
        keys.append("set:" + " ".join(words))
    return keys


class NavJobIndex:
    def __init__(self, fetcher: Fetcher, cache_dir: Path | None, *, lookback_days: int = 75, max_pages: int = 200) -> None:
        self.fetcher = fetcher
        self.cache_dir = cache_dir
        self.lookback_days = lookback_days
        self.max_pages = max_pages
        self.token: str | None = None
        self.items: dict[str, dict[str, Any]] = {}  # uuid -> latest feed item
        self.status = "not_run"
        self.error: str | None = None
        self.pages_read = 0
        self.oldest_covered: str | None = None
        self.newest_covered: str | None = None
        self._entry_cache: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._by_name: dict[str, list[str]] = {}

    # ---------------------------------------------------------- build
    def _get_token(self) -> str | None:
        response = self.fetcher.get(TOKEN_URL, module="jobs_nav", respect_robots=False, accept="text/plain", timeout=15, attempts=2)
        match = re.search(r"eyJ[A-Za-z0-9._-]+", response.text() if response.body else "")
        return match.group(0) if match else None

    def _cache_file(self) -> Path | None:
        return self.cache_dir / "nav_feed_items.json" if self.cache_dir else None

    def _load_cache(self) -> str | None:
        path = self._cache_file()
        if not path or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        self.items = payload.get("items", {})
        return payload.get("next_url")

    def _save_cache(self, next_url: str | None) -> None:
        path = self._cache_file()
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.lookback_days + 30)).isoformat()
        kept = {uuid: item for uuid, item in self.items.items() if (item.get("date_modified") or "") >= cutoff[:19]}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"next_url": next_url, "saved_at": utc_now(), "items": kept}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def build(self) -> None:
        try:
            self.token = self._get_token()
            if not self.token:
                self.status, self.error = "blocked", "public token unavailable"
                return
            headers = {"Authorization": f"Bearer {self.token}"}
            next_url = self._load_cache()
            if next_url:
                url = BASE + next_url if next_url.startswith("/") else next_url
                first_headers = headers
            else:
                start = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)
                url = FEED_URL
                first_headers = {**headers, "If-Modified-Since": format_datetime(start, usegmt=True)}
            pages = 0
            current_headers = first_headers
            last_next = next_url
            while url and pages < self.max_pages:
                if not self.fetcher.can_spend(1, reserve=50):
                    self.error = "feed paging stopped to protect the request budget"
                    break
                response = self.fetcher.get(url, module="jobs_nav", respect_robots=False, accept="application/json", headers=current_headers, timeout=30, attempts=2)
                current_headers = headers
                if response.status in (401, 403):
                    self.status, self.error = "blocked", f"HTTP {response.status}"
                    return
                if not response.ok:
                    self.error = response.error or f"HTTP {response.status}"
                    break
                body = response.json()
                pages += 1
                for item in body.get("items", []):
                    entry = item.get("_feed_entry") or {}
                    uuid = entry.get("uuid") or item.get("id")
                    if uuid:
                        self.items[uuid] = {
                            "uuid": uuid,
                            "status": entry.get("status"),
                            "title": entry.get("title") or item.get("title"),
                            "business_name": entry.get("businessName"),
                            "municipal": entry.get("municipal"),
                            "date_modified": item.get("date_modified") or entry.get("sistEndret"),
                        }
                if body.get("next_url"):
                    last_next = body["next_url"]
                    url = BASE + body["next_url"]
                else:
                    break
            self.pages_read = pages
            self._save_cache(last_next)
            dates = sorted(item.get("date_modified") or "" for item in self.items.values())
            self.oldest_covered = dates[0] if dates else None
            self.newest_covered = dates[-1] if dates else None
            self._index()
            self.status = "available" if self.items else "failed"
        except BudgetExhausted as exc:
            self.status, self.error = "failed", str(exc)
            self._index()
        except Exception as exc:  # keep the run alive; jobs become `failed` per company
            self.status, self.error = "failed", f"{type(exc).__name__}: {str(exc)[:160]}"
            self._index()

    def _index(self) -> None:
        by_name: dict[str, list[str]] = {}
        for uuid, item in self.items.items():
            if item.get("status") != "ACTIVE":
                continue
            for key in _keys(item.get("business_name")):
                by_name.setdefault(key, []).append(uuid)
        self._by_name = by_name

    # ---------------------------------------------------------- lookup
    def candidates(self, names: list[str]) -> list[str]:
        out: list[str] = []
        for name in names:
            for key in _keys(name):
                out.extend(self._by_name.get(key, []))
        return list(dict.fromkeys(out))

    def entry(self, uuid: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        with self._lock:
            if uuid in self._entry_cache:
                return self._entry_cache[uuid]
        url = ENTRY_URL.format(uuid=uuid)
        response = self.fetcher.get(url, module="jobs_nav", respect_robots=False, accept="application/json", headers={"Authorization": f"Bearer {self.token}"}, timeout=20, attempts=2)
        meta = {"url": url, "status": response.status, "retrieved_at": response.retrieved_at, "sha256": sha256_bytes(response.body) if response.body else None, "error": response.error}
        body = None
        if response.ok:
            try:
                body = response.json()
            except ValueError:
                body = None
        with self._lock:
            self._entry_cache[uuid] = (body, meta)
        return body, meta

    def jobs_for(self, org: str, names: list[str], workplace_orgs: set[str], max_details: int = 12) -> dict[str, Any]:
        if self.status not in {"available"}:
            return {"status": "failed" if self.status == "failed" else self.status, "error": self.error, "jobs": [], "checked": 0}
        uuids = self.candidates(names)
        jobs, rejected, checked = [], 0, 0
        for uuid in uuids[:max_details]:
            if not self.fetcher.can_spend(1, reserve=10):
                break
            try:
                body, meta = self.entry(uuid)
            except BudgetExhausted:
                break
            checked += 1
            ad = (body or {}).get("ad_content") or (body or {}).get("json") or {}
            employer = ad.get("employer") or {}
            employer_org = re.sub(r"\D", "", str(employer.get("orgnr") or ""))
            if body is None or (body.get("status") or ad.get("status")) not in (None, "ACTIVE"):
                continue
            expires = str(ad.get("expires") or "")[:10]
            if expires and expires < today():
                continue
            if employer_org != org and employer_org not in workplace_orgs:
                rejected += 1
                continue
            location = (ad.get("workLocations") or [{}])[0]
            jobs.append({
                "uuid": uuid,
                "title": ad.get("title") or ad.get("jobtitle"),
                "job_title": ad.get("jobtitle"),
                "employer_name": employer.get("name"),
                "employer_orgnr": employer_org,
                "employer_homepage": employer.get("homepage"),
                "matched_via": "organisation" if employer_org == org else "registered_workplace",
                "published": str(ad.get("published") or "")[:10] or None,
                "expires": expires or None,
                "application_due": ad.get("applicationDue"),
                "location": ", ".join(part for part in [location.get("city"), location.get("municipal")] if part) or None,
                "extent": ad.get("extent"),
                "engagement_type": ad.get("engagementtype"),
                "position_count": ad.get("positioncount"),
                "public_url": PUBLIC_AD_URL.format(uuid=uuid),
                "source_url": meta["url"],
                "retrieved_at": meta["retrieved_at"],
                "sha256": meta["sha256"],
            })
        jobs.sort(key=lambda job: job.get("published") or "", reverse=True)
        return {
            "status": "available" if jobs else "not_available",
            "jobs": jobs,
            "checked": checked,
            "name_matches": len(uuids),
            "rejected_other_employer": rejected,
            "coverage_window": {"from": self.oldest_covered, "to": self.newest_covered},
        }
