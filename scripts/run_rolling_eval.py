#!/usr/bin/env python3
"""
Retrospective rolling-origin evaluation that mimics the LIVE procedure exactly.

For every delivery day D:
  * data from D (start of Berlin day) onward is hidden,
  * the ensemble is retrained on everything before D,
  * a direct 24 h forecast is made with the same code as run_daily_forecast.py
    (no bias correction: evaluated separately),
  * it is scored against realised prices and SN24 / SN168.

Typical use
  py scripts/run_rolling_eval.py                 # all days from --start to the latest complete day
  py scripts/run_rolling_eval.py --incremental   # only days not yet in reports/metrics/rolling_eval.csv
                                                 # (this is what the daily job runs: 1-2 model fits per day)

After every run the README figures/tables are rebuilt from the CSV.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from electricity_forecast.data import join_all  # noqa: E402
from electricity_forecast.evaluate import dm_test, mae  # noqa: E402
from electricity_forecast.features import delivery_day_utc_index, gate_closure_utc, local_dates  # noqa: E402
from forecast_horizon import direct_forecast  # noqa: E402

RAW = ROOT / "data" / "raw"


def last_complete_delivery_day(price: pd.Series) -> pd.Timestamp:
    s = price.dropna()
    cnt = s.groupby(local_dates(s.index)).count()
    return cnt[cnt >= 23].index.max()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price", type=Path, default=RAW / "germany_electricity_hourly.csv")
    ap.add_argument("--smard", type=Path, default=RAW / "germany_smard_day_ahead_forecasts.csv")
    ap.add_argument("--weather", type=Path, default=RAW / "germany_weather_forecast_archive.csv")
    ap.add_argument("--start", default="2026-10-24", help="first delivery date (Berlin), YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="last delivery date; default = latest day with complete prices")
    ap.add_argument("--incremental", action="store_true", help="only evaluate days missing from the output CSV")
    ap.add_argument("--external-shift", type=int, default=24)
    ap.add_argument("--price-only", action="store_true", help="drop SMARD/weather columns")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "metrics" / "rolling_eval.csv")
    args = ap.parse_args()

    df = join_all(args.price, args.smard, args.weather)
    if args.price_only:
        df = df[["price_eur_mwh"]]
    price = df["price_eur_mwh"]

    end = pd.Timestamp(args.end) if args.end else last_complete_delivery_day(price)
    days = pd.date_range(args.start, end, freq="D")

    old = pd.DataFrame()
    if args.incremental and args.out.exists():
        old = pd.read_csv(args.out)
        done = set(old["date"].astype(str))
        days = [d for d in days if str(d.date()) not in done]
    print(f"Delivery days to evaluate: {len(days)} (up to {end.date()})", flush=True)

    rows = []
    for d in days:
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
        p = fc.set_index("timestamp_utc")["yhat_eur_mwh"].reindex(idx)
        sn24 = price.shift(24, freq="h").reindex(idx)
        sn168 = price.shift(168, freq="h").reindex(idx)
        r = {
            "date": str(d.date()),
            "mae": mae(y, p),
            "mae_sn24": mae(y, sn24),
            "mae_sn168": mae(y, sn168),
            "imputed_rows": int(fc["rows_with_imputed_features"].iloc[0]),
            "data_gap_h": float(fc["data_gap_hours"].iloc[0]),
        }
        rows.append(r)
        print(f"{r['date']}  model {r['mae']:7.2f} | SN24 {r['mae_sn24']:7.2f} | SN168 {r['mae_sn168']:7.2f}", flush=True)

    res = pd.concat([old, pd.DataFrame(rows)], ignore_index=True) if len(old) or rows else pd.DataFrame()
    if res.empty:
        print("Nothing to evaluate.")
        return
    res = res.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(args.out, index=False)

    best = res[["mae_sn24", "mae_sn168"]].min(axis=1)
    dm = dm_test(res["mae"].values, res["mae_sn24"].values)
    print("\n=== summary ===")
    print(f"days {len(res)} | MAE model {res.mae.mean():.2f} | SN24 {res.mae_sn24.mean():.2f} | "
          f"SN168 {res.mae_sn168.mean():.2f} | best-of {best.mean():.2f}")
    print(f"days model < SN24: {(res.mae < res.mae_sn24).sum()}/{len(res)} | < best-of: {(res.mae < best).sum()}/{len(res)}")
    print(f"DM vs SN24 (daily, HLN): stat {dm['dm']:.2f}, p(model better) {dm['p_model_better']:.4f}, n={dm['n']}")
    print("saved ->", args.out)
    try:
        from electricity_forecast.report import update_results
        update_results(ROOT)
    except Exception as exc:  # report generation must never break an evaluation run
        print("README/figure update skipped:", exc)


if __name__ == "__main__":
    main()
