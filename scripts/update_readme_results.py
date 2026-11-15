#!/usr/bin/env python3
"""Rebuild README results block + figures from reports/metrics/*.csv (no recomputation)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from electricity_forecast.report import update_results  # noqa: E402

update_results(ROOT)
