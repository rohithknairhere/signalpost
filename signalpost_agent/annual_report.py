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


def read_workforce(fetcher: Fetcher, org: str, year: str, *, language: str, max_pages: int = 14, min_seconds_left: float = 420) -> dict[str, Any]:
    url = ACCOUNT_PDF.format(org=org, year=year)
    if fetcher.seconds_left() < min_seconds_left:
        return {"status": "failed", "error": "time budget reserved; annual report not read", "url": url}
    try:
        _pace_years()
        response = fetcher.get(url, module="annual_report", respect_robots=False, accept="*/*", timeout=40, max_bytes=25_000_000)
    except BudgetExhausted as exc:
        return {"status": "failed", "error": str(exc), "url": url}
    if response.status in (404, 410):
        return {"status": "not_available", "url": url, "error": "no filing copy for this year"}
    if not response.ok or not response.body.startswith(b"%PDF"):
        return {"status": "failed", "url": url, "error": response.error or f"HTTP {response.status}"}
    digest = sha256_bytes(response.body)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="signalpost-ar-") as tmp:
        pdf = Path(tmp) / "report.pdf"
        pdf.write_bytes(response.body)
        try:
            info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=20).stdout if shutil.which("pdfinfo") else ""
            pages = int(re.search(r"Pages:\s+(\d+)", info).group(1)) if "Pages:" in info else max_pages
        except Exception:
            pages = max_pages
        pages_read = 0
        for page in range(1, min(pages, max_pages) + 1):
            if fetcher.seconds_left() < min_seconds_left / 2:
                break
            with _OCR_SLOTS:
                prefix = Path(tmp) / f"p{page}"
                try:
                    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", "110", "-gray", str(pdf), str(prefix)], check=True, capture_output=True, timeout=60)
                    image = next(Path(tmp).glob(f"p{page}*.pgm"))
                    text = subprocess.run(["tesseract", str(image), "-", "-l", language, "--psm", "6"], capture_output=True, text=True, timeout=60, env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout
                    image.unlink(missing_ok=True)
                except Exception:
                    continue
            pages_read += 1
            found = parse_workforce(text)
            if found:
                return {"status": "available", "url": url, "sha256": digest, "retrieved_at": response.retrieved_at, "year": year, "page": page, "pages_read": pages_read, "ocr_seconds": round(time.monotonic() - started, 1), **found}
            if STOP_RE.search(text):
                break
    return {"status": "not_available", "url": url, "sha256": digest, "retrieved_at": response.retrieved_at, "year": year, "pages_read": pages_read, "error": "no workforce statement found in the filing copy"}
