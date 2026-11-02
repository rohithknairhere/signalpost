"""Workforce facts from the official annual-account filing copy (Regnskapsregisteret).

The filing copies are scanned images, so this module needs the `pdftoppm`
(poppler) and `tesseract` command-line tools. When they are not installed the
module is skipped and the run report says so; nothing else changes.

We OCR page by page and stop as soon as the workforce statement is found or the
auditor's report begins. Only explicit statements are published: the number of
full-time equivalents (årsverk), the average number of employees, or an explicit
"no employees" statement. Every claim carries the filing URL, its SHA-256 and the
OCR'd sentence it came from.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .net import BudgetExhausted, Fetcher
from .registry import ACCOUNT_PDF, _pace_years
from .util import clean_text, sha256_bytes

NUM = r"([0-9O][0-9O ]{0,6}(?:[.,][0-9O]{1,2})?)"
ARSVERK = r"(?:aarsverk|arsverk|årsverk|arsverk|ärsverk|drsverk|arsvérk)"
PATTERNS = [
    ("full_time_equivalents", re.compile(rf"(?i)(?:antall|antal|tal\s+p[aå])\s+{ARSVERK}(?:\s+(?:sysselsatt|syssetsatt|tilsett))?\s+i\s+(?:regnskaps|rekneskaps)[aå]ret\s*(?:er|var|:|=)?\s*{NUM}")),
    ("full_time_equivalents", re.compile(rf"(?i)antall\s+{ARSVERK}\s*(?:er|var|:|=)\s*{NUM}")),
    ("full_time_equivalents", re.compile(rf"(?i)selskapet\s+har(?:\s+i\s+\d{{4}})?\s+(?:sysselsatt|hatt)\s+{NUM}\s+{ARSVERK}")),
    ("full_time_equivalents", re.compile(rf"(?i)(?:selskapet|foretaket|stiftelsen)\s+har\s+{NUM}\s+{ARSVERK}")),
    ("average_employees", re.compile(rf"(?i)gjennomsnittlig(?:e)?\s+antall\s+ansatte(?:\s+i\s+(?:regnskaps|rekneskaps)[aå]ret)?\s*(?:er|var|:|=)?\s*{NUM}")),
    ("average_employees", re.compile(rf"(?i)(?:selskapet|foretaket)\s+har(?:\s+hatt)?\s+{NUM}\s+ansatte\b")),
]
NONE_RE = re.compile(r"(?i)\b(?:selskapet|foretaket|stiftelsen|sameiet|det)\s+(?:har\s+ikke\s+hatt\s+(?:noen\s+)?ansatte|har\s+ingen\s+(?:ansatte|" + ARSVERK + r")|hadde\s+ingen\s+ansatte|har\s+ikke\s+ansatte)")
STOP_RE = re.compile(r"(?i)(uavhengig\s+revisors\s+beretning|revisjonsberetning)")

_OCR_SLOTS = threading.Semaphore(max(1, (os.cpu_count() or 2)))


# OCR runs at low CPU priority so it never slows the research workers sharing the machine.
NICE = ["nice", "-n", "15"] if shutil.which("nice") else []


def ocr_available() -> tuple[bool, str]:
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        return False, "OCR tools (pdftoppm, tesseract) not installed; annual-report text not read"
    try:
        langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10).stdout
    except Exception as exc:  # pragma: no cover
        return False, f"tesseract unavailable: {exc}"
    if "nor" in langs.split():
        return True, "nor"
    if "eng" in langs.split():
        return True, "eng"
    return False, "no tesseract language data installed"


def _number(raw: str) -> float | None:
    text = raw.replace("O", "0").replace(" ", "").replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if 0 <= value < 100_000 else None


def parse_workforce(text: str) -> dict[str, Any] | None:
    flat = re.sub(r"\s+", " ", text)
    for kind, pattern in PATTERNS:
        match = pattern.search(flat)
        if match:
            value = _number(match.group(1))
            if value is not None:
                return {"kind": kind, "value": value, "span": clean_text(flat[max(0, match.start() - 20):match.end() + 10], 220)}
    match = NONE_RE.search(flat)
    if match:
        return {"kind": "no_employees", "value": 0, "span": clean_text(flat[max(0, match.start() - 10):match.end() + 10], 220)}
    return None


def download_filing(fetcher: Fetcher, org: str, year: str, *, min_seconds_left: float = 240) -> dict[str, Any]:
    """Paced download of the filing copy (Regnskapsregisteret allows ~30 requests/minute)."""
    url = ACCOUNT_PDF.format(org=org, year=year)
    if fetcher.seconds_left() < min_seconds_left:
        return {"status": "failed", "error": "time budget reserved; annual report not read", "url": url}
    if not fetcher.can_spend(1):
        return {"status": "failed", "error": "request budget reserved for core official records", "url": url}
    try:
        _pace_years()
        response = fetcher.get(url, module="annual_report", respect_robots=False, accept="*/*", timeout=40, max_bytes=25_000_000, attempts=2, max_wait=30)
    except BudgetExhausted as exc:
        return {"status": "failed", "error": str(exc), "url": url}
    if response.status in (404, 410):
        return {"status": "not_available", "url": url, "error": "no filing copy for this year"}
    if not response.ok or not response.body.startswith(b"%PDF"):
        return {"status": "failed", "url": url, "error": response.error or f"HTTP {response.status}"}
    return {"status": "downloaded", "url": url, "year": year, "body": response.body, "sha256": sha256_bytes(response.body), "retrieved_at": response.retrieved_at}


def ocr_filing(download: dict[str, Any], *, language: str, seconds_left, max_pages: int = 14, stop_below: float = 90) -> dict[str, Any]:
    """OCR a downloaded filing page by page; stop at the workforce note or the auditor's report."""
    url, year = download["url"], download["year"]
    started = time.monotonic()
    base = {"url": url, "sha256": download["sha256"], "retrieved_at": download["retrieved_at"], "year": year}
    with tempfile.TemporaryDirectory(prefix="signalpost-ar-") as tmp:
        pdf = Path(tmp) / "report.pdf"
        pdf.write_bytes(download["body"])
        try:
            info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=20).stdout if shutil.which("pdfinfo") else ""
            pages = int(re.search(r"Pages:\s+(\d+)", info).group(1)) if "Pages:" in info else max_pages
        except Exception:
            pages = max_pages
        pages_read = 0
        for page in range(1, min(pages, max_pages) + 1):
            if seconds_left() < stop_below:
                return {"status": "failed", **base, "pages_read": pages_read, "error": "time budget reached while reading the annual report"}
            prefix = Path(tmp) / f"p{page}"
            try:
                subprocess.run(NICE + ["pdftoppm", "-f", str(page), "-l", str(page), "-r", "110", "-gray", str(pdf), str(prefix)], check=True, capture_output=True, timeout=60)
                image = next(Path(tmp).glob(f"p{page}*.pgm"))
                text = subprocess.run(NICE + ["tesseract", str(image), "-", "-l", language, "--psm", "6"], capture_output=True, text=True, timeout=60, env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout
                image.unlink(missing_ok=True)
            except Exception:
                continue
            pages_read += 1
            found = parse_workforce(text)
            if found:
                return {"status": "available", **base, "page": page, "pages_read": pages_read, "ocr_seconds": round(time.monotonic() - started, 1), **found}
            if STOP_RE.search(text):
                break
    return {"status": "not_available", **base, "pages_read": pages_read, "error": "no workforce statement found in the filing copy"}


def read_workforce(fetcher: Fetcher, org: str, year: str, *, language: str, max_pages: int = 14, min_seconds_left: float = 420) -> dict[str, Any]:
    download = download_filing(fetcher, org, year, min_seconds_left=min_seconds_left)
    if download["status"] != "downloaded":
        return download
    return ocr_filing(download, language=language, seconds_left=fetcher.seconds_left, max_pages=max_pages)


class FilingPipeline:
    """Background pipeline: one paced downloader feeds parallel OCR workers.

    Research workers enqueue companies as soon as their registry record is known, so
    the ~30/minute filing endpoint never stalls website or registry research.
    """

    def __init__(self, fetcher: Fetcher, *, language: str, allowed: set[str], want_years: bool, years_fetcher=None) -> None:
        import queue
        from concurrent.futures import ThreadPoolExecutor

        self.fetcher = fetcher
        self.language = language
        self.allowed = allowed
        self.want_years = want_years
        self.years_fetcher = years_fetcher
        self.queue: "queue.Queue[tuple[str, str | None] | None]" = queue.Queue()
        self.results: dict[str, dict[str, Any]] = {}
        self.ocr_pool = ThreadPoolExecutor(max_workers=max(1, (os.cpu_count() or 2)))
        self.futures: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, org: str, year: str | None) -> None:
        self.queue.put((org, year))

    def close(self) -> None:
        self.queue.put(None)

    def _store(self, org: str, key: str, value: Any) -> None:
        with self._lock:
            self.results.setdefault(org, {})[key] = value

    def _run(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                return
            org, year = item
            try:
                if self.want_years and self.years_fetcher and self.fetcher.seconds_left() > 300:
                    self._store(org, "years", self.years_fetcher(self.fetcher, org))
                if org not in self.allowed or not year:
                    continue
                download = download_filing(self.fetcher, org, year)
                if download["status"] != "downloaded":
                    self._store(org, "workforce", download)
                    continue
                self.futures[org] = self.ocr_pool.submit(ocr_filing, download, language=self.language, seconds_left=self.fetcher.seconds_left)
            except Exception as exc:  # never break the pipeline for one company
                self._store(org, "workforce", {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:160]}"})

    def finish(self, deadline_seconds_left: float = 45) -> None:
        """Stop taking new downloads and collect OCR results while time allows."""
        self.close()
        self.thread.join(timeout=max(0.0, self.fetcher.seconds_left() - deadline_seconds_left))
        for org, future in list(self.futures.items()):
            remaining = self.fetcher.seconds_left() - deadline_seconds_left
            try:
                self._store(org, "workforce", future.result(timeout=max(0.1, remaining)))
            except Exception as exc:
                self._store(org, "workforce", {"status": "failed", "error": "time budget reached before the annual report was read" if remaining <= 0.1 else f"{type(exc).__name__}"})
        self.ocr_pool.shutdown(wait=False, cancel_futures=True)

    def get(self, org: str) -> dict[str, Any]:
        with self._lock:
            return dict(self.results.get(org, {}))
