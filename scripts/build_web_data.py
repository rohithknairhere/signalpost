#!/usr/bin/env python3
"""Merge one or more envelope files into the web app dataset.

    python scripts/build_web_data.py out/envelopes.jsonl [more.jsonl ...] --report out/run-report.json --output public/data/profiles.json
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from signalpost_agent.viewer import web_dataset  # noqa: E402


def read(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("envelopes", nargs="+")
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", default="public/data/profiles.json")
    args = parser.parse_args()
    seen, rows = set(), []
    for path in args.envelopes:
        for row in read(path):
            if row["organisation_number"] not in seen:
                seen.add(row["organisation_number"])
                rows.append(row)
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    report["input_count"] = len(rows)
    dataset = web_dataset(rows, report)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(rows)} companies to {args.output}")


if __name__ == "__main__":
    main()
