"""Hourly bias correction from past forecast vs actual (no leakage)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "forecasts"


def collect_errors(price: pd.Series, forecast_dir: Path = OUT_DIR, max_files: int = 21) -> pd.DataFrame:
    rows = []
    files = sorted(forecast_dir.glob("forecast_*.csv"))[-max_files:]
    for fpath in files:
        fc = pd.read_csv(fpath)
        if "yhat_eur_mwh" not in fc.columns:
            continue
        fc["timestamp_utc"] = pd.to_datetime(fc["timestamp_utc"], utc=True)
        fc = fc.set_index("timestamp_utc")
        common = fc.index.intersection(price.index)
        if len(common) == 0:
            continue
        err = fc.loc[common, "yhat_eur_mwh"] - price.loc[common]
        for ts, e in err.items():
            rows.append({"timestamp_utc": ts, "hour": int(ts.hour), "error": float(e)})
    if not rows:
        return pd.DataFrame(columns=["timestamp_utc", "hour", "error"])
    return pd.DataFrame(rows).drop_duplicates("timestamp_utc", keep="last")


def hourly_bias(errors: pd.DataFrame, min_obs: int = 2, last_n_days: int = 14) -> pd.Series:
    if errors.empty:
        return pd.Series(dtype=float)
    e = errors.copy()
    e["timestamp_utc"] = pd.to_datetime(e["timestamp_utc"], utc=True)
    cutoff = e["timestamp_utc"].max() - pd.Timedelta(days=last_n_days)
    e = e[e["timestamp_utc"] >= cutoff]
    g = e.groupby("hour")["error"]
    bias = g.mean()
    counts = g.count()
    return bias[counts >= min_obs]


def apply_bias_correction(forecast: pd.DataFrame, bias: pd.Series) -> pd.DataFrame:
    out = forecast.copy()
    out["yhat_raw_eur_mwh"] = out["yhat_eur_mwh"]
    if bias is None or len(bias) == 0:
        out["bias_applied"] = 0.0
        return out
    hours = pd.to_datetime(out["timestamp_utc"], utc=True).dt.hour
    b = hours.map(lambda h: float(bias.get(h, 0.0)))
    out["bias_applied"] = b
    out["yhat_eur_mwh"] = (out["yhat_raw_eur_mwh"] - b).round(2)
    return out