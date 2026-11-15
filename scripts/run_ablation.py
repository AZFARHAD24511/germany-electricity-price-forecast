#!/usr/bin/env python3
"""
Ablation + significance table for the paper.

Runs the same expanding-window backtest under several availability rules and
reports MAE, relative MAE vs SN24/SN168 and a Diebold-Mariano test (daily loss
differentials, HLN-corrected) against SN168.

    python scripts/run_ablation.py \
        --price data/raw/germany_electricity_hourly.csv \
        --smard data/raw/germany_smard_day_ahead_forecasts.csv \
        --weather data/raw/germany_weather_forecast_archive.csv

Rows
  A_legacy_shift24      original code (rolling uses price(ts-1): LEAKY)
  B_gate_shift24        leak-free price features, external lag 24 h  <- primary
  C_gate_shift24_wx36   as B, observed weather lagged 36 h (strict availability)
  D_gate_shift0         external lag 0 h: upper bound, only valid with true
                        day-ahead forecasts; weather here is reanalysis/actuals
  E_gate_no_external    price-only model (is the external data worth anything?)
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electricity_forecast.data import join_all  # noqa: E402
from electricity_forecast.evaluate import (  # noqa: E402
    DEFAULT_WINDOWS, backtest_predictions, daily_mean_abs, dm_test, mae, rmse,
)

CONFIGS = {
    "A_legacy_shift24": dict(external_shift=24, price_info="legacy"),
    "B_gate_shift24": dict(external_shift=24, price_info="gate"),
    "C_gate_shift24_wx36": dict(external_shift=24, price_info="gate", weather_shift=36),
    "D_gate_shift0": dict(external_shift=0, price_info="gate"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price", type=Path, required=True)
    ap.add_argument("--smard", type=Path, required=True)
    ap.add_argument("--weather", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "metrics" / "ablation.csv")
    args = ap.parse_args()

    df = join_all(args.price, args.smard, args.weather)
    price_only = df[["price_eur_mwh"]]
    rows = []
    runs = {k: (df, v) for k, v in CONFIGS.items()}
    runs["E_gate_no_external"] = (price_only, dict(external_shift=24, price_info="gate"))

    for name, (data, kw) in runs.items():
        print("running", name, flush=True)
        pred = backtest_predictions(data, windows=DEFAULT_WINDOWS, **kw).dropna(subset=["sn24", "sn168"])
        e_m = pred["ens"] - pred["y"]
        d_sn168 = dm_test(daily_mean_abs(e_m).values, daily_mean_abs(pred["sn168"] - pred["y"]).values)
        d_sn24 = dm_test(daily_mean_abs(e_m).values, daily_mean_abs(pred["sn24"] - pred["y"]).values)
        rows.append(
            {
                "config": name,
                "n_hours": len(pred),
                "n_days": pred.index.normalize().nunique(),
                "mae_ens": mae(pred.y, pred.ens),
                "rmse_ens": rmse(pred.y, pred.ens),
                "mae_sn24": mae(pred.y, pred.sn24),
                "mae_sn168": mae(pred.y, pred.sn168),
                "rmae_vs_sn24": mae(pred.y, pred.ens) / mae(pred.y, pred.sn24),
                "rmae_vs_sn168": mae(pred.y, pred.ens) / mae(pred.y, pred.sn168),
                "dm_vs_sn168": d_sn168["dm"],
                "p_better_than_sn168": d_sn168["p_model_better"],
                "p_better_than_sn24": d_sn24["p_model_better"],
            }
        )
    res = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(args.out, index=False)
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(res.to_string(index=False))
    print("saved ->", args.out)


if __name__ == "__main__":
    main()
