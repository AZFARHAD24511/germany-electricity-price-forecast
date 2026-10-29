#!/usr/bin/env python3
"""
End-to-end pipeline (Conservative protocol only).

Usage (from repo root):
  python scripts/run_pipeline.py \\
      --price data/raw/germany_electricity_hourly.csv \\
      --smard data/raw/germany_smard_day_ahead_forecasts.csv \\
      --weather data/raw/germany_weather_forecast_archive.csv \\
      --out reports
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from electricity_forecast.data import join_all
from electricity_forecast.evaluate import run_backtest
from electricity_forecast.visualize import plot_backtest_mae, plot_price_overview


def main() -> None:
    p = argparse.ArgumentParser(description="Conservative day-ahead price forecast pipeline")
    p.add_argument("--price", type=Path, required=True)
    p.add_argument("--smard", type=Path, required=True)
    p.add_argument("--weather", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("reports"))
    p.add_argument("--shift", type=int, default=24, help="External feature lag (hours). 24 = conservative.")
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "figures").mkdir(exist_ok=True)
    (args.out / "metrics").mkdir(exist_ok=True)

    print("Joining data …")
    df = join_all(args.price, args.smard, args.weather)
    print(f"  rows={len(df):,}  range={df.index.min()} → {df.index.max()}")

    print(f"Running backtest (external_shift={args.shift}h) …")
    summary = run_backtest(df, external_shift=args.shift)
    summary_path = args.out / "metrics" / "backtest_summary.csv"
    summary.to_csv(summary_path, index=False)
    print(summary.to_string(index=False))
    print(f"Saved → {summary_path}")

    # Figures
    plot_price_overview(
        df["price_eur_mwh"],
        args.out / "figures" / "price_overview.png",
    )
    plot_backtest_mae(
        summary,
        args.out / "figures" / "backtest_mae.png",
        title=f"Backtest MAE (shift={args.shift}h)",
    )

    meta = {
        "external_shift_hours": args.shift,
        "protocol": "conservative" if args.shift >= 24 else "optimistic",
        "n_rows_joined": len(df),
        "windows": summary[["window", "start", "end", "n_test"]].to_dict(orient="records"),
        "weighted_mae_ensemble": float(
            (summary["mae_ens"] * summary["n_test"]).sum() / summary["n_test"].sum()
        ),
    }
    with open(args.out / "metrics" / "run_metadata.json", "w") as f:
        json.dump(meta, f, indent=2, default=str)

    print("Done.")


if __name__ == "__main__":
    main()
