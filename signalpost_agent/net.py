"""Budgeted, polite, SSRF-safe HTTP for the agent.

Every outbound request goes through `Fetcher.get`, which:
- refuses non-public hosts (also after redirects);
- enforces the run's global request budget and wall-clock deadline;
- honours robots.txt for non-API web pages (cached per host, one request per host);
- spaces requests to the same host;
- records request counts per module for the run report.
"""
from __future__ import annotations

import gzip
import os
import ipaddress
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from .util import sha256_bytes, utc_now

USER_AGENT = os.environ.get("SIGNALPOST_USER_AGENT") or f"SignalpostResearchAgent/{__version__} (+https://builderr.ai/challenges/signalpost; company research; respects robots.txt)"
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class BudgetExhausted(Exception):
    pass


class UnsafeURL(Exception):
    pass


@dataclass
class Response:
    url: str
    final_url: str
    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    retrieved_at: str = ""
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def sha256(self) -> str | None:
        return sha256_bytes(self.body) if self.body else None

    def text(self) -> str:
        charset = "utf-8"
        content_type = self.headers.get("content-type", "")
        if "charset=" in content_type:
            charset = content_type.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


_LOCAL_DNS: bool | None = None


def local_dns_available() -> bool:
    """False when this machine only reaches the web through an HTTP proxy that resolves names itself."""
    global _LOCAL_DNS
    if _LOCAL_DNS is None:
        try:
            socket.getaddrinfo("data.brreg.no", 443, type=socket.SOCK_STREAM)
            _LOCAL_DNS = True
        except OSError:
            _LOCAL_DNS = not bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
    return _LOCAL_DNS


def _literal_ip(host: str) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _host_is_public(host: str, port: int) -> bool:
    host = host.lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        return False
    literal = _literal_ip(host)
    if literal is not None:
        return literal.is_global
    if not local_dns_available():
        # Behind an egress proxy: the proxy resolves and enforces egress policy.
        return True
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise UnsafeURL("hostname did not resolve")
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            return False
    return True


def resolves(host: str, fetcher: "Fetcher | None" = None) -> bool:
    """Does the host exist? Local DNS costs no HTTP request; behind a proxy we use one DNS-over-HTTPS query."""
    if local_dns_available():
        try:
            return _host_is_public(host, 443)
        except UnsafeURL:
            return False
    if fetcher is None:
        return True
    return fetcher.doh_resolves(host)


def check_public_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURL("only public http(s) URLs are allowed")
    if parsed.username or parsed.password:
        raise UnsafeURL("credentials in URL are not allowed")
    if not _host_is_public(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        raise UnsafeURL("private, loopback or reserved address")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        check_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    def __init__(self, *, max_requests: int, deadline_monotonic: float, per_host_interval: float = 0.35, offline_cache: Any = None) -> None:
        self.max_requests = max_requests
        self.deadline = deadline_monotonic
        self.per_host_interval = per_host_interval
        self._lock = threading.Lock()
        self._used = 0
        self.by_module: Counter[str] = Counter()
        self.bytes = 0
        self.latencies: list[int] = []
        self._host_next: dict[str, float] = {}
        self._host_lock: dict[str, threading.Lock] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._robots_lock = threading.Lock()
        self._opener = urllib.request.build_opener(_SafeRedirect())
        self.cache = offline_cache
        self._doh: dict[str, bool] = {}
        self.reserve_fn = lambda: 0

    # ---- budget -------------------------------------------------------
    @property
    def used(self) -> int:
        return self._used

    def remaining(self) -> int:
        return self.max_requests - self._used

    def seconds_left(self) -> float:
        return self.deadline - time.monotonic()

    def can_spend(self, count: int = 1, reserve: int = 0) -> bool:
        try:
            reserve += int(self.reserve_fn())
        except Exception:
            pass
        return self.remaining() - reserve >= count and self.seconds_left() > 5

    def _reserve(self, module: str) -> None:
        with self._lock:
            if self._used >= self.max_requests:
                raise BudgetExhausted("request budget exhausted")
            if time.monotonic() >= self.deadline:
                raise BudgetExhausted("time budget exhausted")
            self._used += 1
            self.by_module[module] += 1

    def _pace(self, host: str) -> None:
        with self._lock:
            lock = self._host_lock.setdefault(host, threading.Lock())
        with lock:
            now = time.monotonic()
            wait = self._host_next.get(host, 0.0) - now
            if wait > 0:
                time.sleep(wait)
            self._host_next[host] = time.monotonic() + self.per_host_interval

    # ---- robots -------------------------------------------------------
    def robots_allowed(self, url: str, module: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        key = f"{parsed.scheme}://{parsed.netloc}".lower()
        with self._robots_lock:
            cached = key in self._robots
        if not cached:
            parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            response = self.get(key + "/robots.txt", module=module, respect_robots=False, timeout=8, accept="text/plain")
            if response.status in (401, 403):
                parser.disallow_all = True  # type: ignore[union-attr]
            elif response.ok and b"<html" not in response.body[:500].lower():
                parser.parse(response.text().splitlines())  # type: ignore[union-attr]
            else:
                parser = None  # missing robots.txt: allowed
            with self._robots_lock:
                self._robots[key] = parser
        parser = self._robots.get(key)
        if parser is None:
            return True
        try:
            return parser.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    # ---- fetch --------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        module: str,
        respect_robots: bool = True,
        timeout: float = 15.0,
        accept: str = BROWSER_ACCEPT,
        headers: dict[str, str] | None = None,
        max_bytes: int = 3_000_000,
        attempts: int = 1,
    ) -> Response:
        retrieved_at = utc_now()
        try:
            check_public_url(url)
        except UnsafeURL as exc:
            return Response(url, url, 0, error=f"unsafe_url: {exc}", retrieved_at=retrieved_at)
        if self.cache is not None:
            hit = self.cache.lookup(url)
            if hit is not None:
                return hit
        if respect_robots and not self.robots_allowed(url, module):
            return Response(url, url, 0, error="robots_disallowed", retrieved_at=retrieved_at)
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        last: Response | None = None
        attempt = -1
        while attempt + 1 < attempts:
            attempt += 1
            self._reserve(module)
            self._pace(host)
            started = time.monotonic()
            request_headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip, deflate", "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.6"}
            request_headers.update(headers or {})
            request = urllib.request.Request(url, headers=request_headers)
            try:
                with self._opener.open(request, timeout=timeout) as handle:
                    raw = handle.read(max_bytes + 1)
                    response_headers = {key.lower(): value for key, value in handle.headers.items()}
                    raw = _decode_body(raw, response_headers.get("content-encoding", ""))
                    elapsed = int((time.monotonic() - started) * 1000)
                    self._record(len(raw), elapsed)
                    result = Response(url, handle.geturl(), handle.status, raw[:max_bytes], response_headers, None if len(raw) <= max_bytes else "truncated", retrieved_at, elapsed)
                    if self.cache is not None:
                        self.cache.store(url, result)
                    return result
            except urllib.error.HTTPError as exc:
                elapsed = int((time.monotonic() - started) * 1000)
                try:
                    raw = exc.read(200_000)
                except Exception:
                    raw = b""
                self._record(len(raw), elapsed)
                last = Response(url, exc.geturl() or url, exc.code, raw, {k.lower(): v for k, v in (exc.headers or {}).items()}, f"HTTP {exc.code}", retrieved_at, elapsed)
                if exc.code not in (429, 500, 502, 503, 504):
                    break
            except UnsafeURL as exc:
                return Response(url, url, 0, error=f"unsafe_redirect: {exc}", retrieved_at=retrieved_at)
            except Exception as exc:  # network errors, TLS, timeouts
                elapsed = int((time.monotonic() - started) * 1000)
                self._record(0, elapsed)
                last = Response(url, url, 0, error=f"{type(exc).__name__}: {str(exc)[:160]}", retrieved_at=retrieved_at, elapsed_ms=elapsed)
                transient = any(marker in (last.error or "") for marker in ("reset by peer", "Tunnel connection failed", "timed out", "RemoteDisconnected", "EOF occurred", "Connection aborted"))
                if transient and attempt + 1 >= attempts and attempts < 2:
                    attempts = 2  # one retry for transient network failures
            if attempt + 1 < attempts:
                time.sleep(0.8 * (attempt + 1))
                continue
            break
        assert last is not None
        if self.cache is not None:
            self.cache.store(url, last)
        return last

    def doh_resolves(self, host: str) -> bool:
        with self._lock:
            cached = self._doh.get(host)
        if cached is not None:
            return cached
        if not self.can_spend(1):
            return False  # never spend reserved core requests on guessed domains
        url = "https://cloudflare-dns.com/dns-query?name=" + urllib.parse.quote(host) + "&type=A"
        response = self.get(url, module="dns", respect_robots=False, accept="application/dns-json", timeout=8)
        answer = False
        if response.ok:
            try:
                body = json.loads(response.body.decode("utf-8"))
                ips = [item.get("data") for item in body.get("Answer", []) if item.get("type") == 1]
                answer = bool(ips) and all(_literal_ip(ip) is not None and _literal_ip(ip).is_global for ip in ips)
            except ValueError:
                answer = False
        with self._lock:
            self._doh[host] = answer
        return answer

    def _record(self, size: int, elapsed: int) -> None:
        with self._lock:
            self.bytes += size
            self.latencies.append(elapsed)

    def report(self) -> dict[str, Any]:
        latencies = sorted(self.latencies)
        return {
            "requests": self._used,
            "request_budget": self.max_requests,
            "requests_by_module": dict(sorted(self.by_module.items())),
            "bytes": self.bytes,
            "p50_ms": latencies[len(latencies) // 2] if latencies else None,
            "p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None,
        }


def _decode_body(raw: bytes, encoding: str) -> bytes:
    encoding = (encoding or "").lower()
    try:
        if "gzip" in encoding:
            return gzip.decompress(raw)
        if "deflate" in encoding:
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except Exception:
        return raw
    return raw
