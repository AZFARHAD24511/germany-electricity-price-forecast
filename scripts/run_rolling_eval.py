#!/usr/bin/env python3
"""
Retrospective rolling-origin evaluation that mimics the LIVE procedure exactly.

For every delivery day D in [start, end]:
  * data from D (start of Berlin day) onward is hidden,
  * the ensemble is retrained on everything before D,
  * a direct 24 h forecast is made with the same code as run_daily_forecast.py
    (no bias correction here: it is evaluated separately),
  * it is scored against realised prices and SN24 / SN168.

This is NOT a live pre-gate record (the data already existed), but it uses the
same information rules, so it answers: "does the current code beat SN24 on the
recent weeks where the old live files looked bad?"

    py scripts/run_rolling_eval.py --price ... --smard ... --weather ... \
        --start 2026-10-24 --end 2026-11-16 --retrain-every 1
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from electricity_forecast.data import join_all  # noqa: E402
from electricity_forecast.evaluate import daily_mean_abs, dm_test, mae  # noqa: E402
from electricity_forecast.features import delivery_day_utc_index, gate_closure_utc  # noqa: E402
from forecast_horizon import direct_forecast  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price", type=Path, required=True)
    ap.add_argument("--smard", type=Path, required=True)
    ap.add_argument("--weather", type=Path, required=True)
    ap.add_argument("--start", required=True, help="first delivery date, YYYY-MM-DD (Berlin)")
    ap.add_argument("--end", required=True, help="last delivery date, YYYY-MM-DD (Berlin)")
    ap.add_argument("--external-shift", type=int, default=24)
    ap.add_argument("--price-only", action="store_true", help="drop SMARD/weather columns")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "metrics" / "rolling_eval.csv")
    args = ap.parse_args()

    df = join_all(args.price, args.smard, args.weather)
    if args.price_only:
        df = df[["price_eur_mwh"]]
    price = df["price_eur_mwh"]

    rows, hourly = [], []
    for d in pd.date_range(args.start, args.end, freq="D"):
        idx = delivery_day_utc_index(d)
        y = price.reindex(idx)
        if y.notna().sum() < 23:
            print(f"{d.date()}: actual prices incomplete, skipped")
            continue
        try:
            fc = direct_forecast(df, gate_closure_utc(d), target_date=d, external_shift=args.external_shift)
        except Exception as exc:  # keep going, but never silently
            print(f"{d.date()}: FAILED {exc}")
            continue
        p = fc.set_index("timestamp_utc")["yhat_eur_mwh"]
        sn24 = price.shift(24, freq="h").reindex(idx)
        sn168 = price.shift(168, freq="h").reindex(idx)
        rows.append(
            {
                "date": d.date(),
                "mae": mae(y, p.reindex(idx)),
                "mae_sn24": mae(y, sn24),
                "mae_sn168": mae(y, sn168),
                "imputed_rows": int(fc["rows_with_imputed_features"].iloc[0]),
                "data_gap_h": float(fc["data_gap_hours"].iloc[0]),
            }
        )
        hourly.append(pd.DataFrame({"y": y, "p": p.reindex(idx), "sn24": sn24, "sn168": sn168}))
        r = rows[-1]
        print(f"{r['date']}  model {r['mae']:7.2f} | SN24 {r['mae_sn24']:7.2f} | SN168 {r['mae_sn168']:7.2f}", flush=True)

    res = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(args.out, index=False)
    H = pd.concat(hourly).dropna()
    best = res[["mae_sn24", "mae_sn168"]].min(axis=1)
    print("\n=== summary ===")
    print(f"days {len(res)} | MAE model {res.mae.mean():.2f} | SN24 {res.mae_sn24.mean():.2f} | "
          f"SN168 {res.mae_sn168.mean():.2f} | best-of {best.mean():.2f}")
    print(f"days model < SN24: {(res.mae < res.mae_sn24).sum()}/{len(res)} | < best-of: {(res.mae < best).sum()}/{len(res)}")
    dm = dm_test(daily_mean_abs(H.p - H.y).values, daily_mean_abs(H.sn24 - H.y).values)
    print(f"DM vs SN24 (daily, HLN): stat {dm['dm']:.2f}, p(model better) {dm['p_model_better']:.4f}, n={dm['n']}")
    print("saved ->", args.out)
    try:
        from electricity_forecast.report import update_results
        update_results(ROOT)
    except Exception as exc:  # report generation must never break an evaluation run
        print("README/figure update skipped:", exc)


if __name__ == "__main__":
    main()
