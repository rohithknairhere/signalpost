#!/usr/bin/env python3
"""Compatibility entry point with the Builderr starter kit's command name.

    python scripts/run_competition_batch.py --organisations batch.jsonl --bulk brreg.csv --output out/envelopes.jsonl ...
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from signalpost_agent.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
