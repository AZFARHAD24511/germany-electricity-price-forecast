"""Hourly bias correction from past forecast vs actual (no leakage).

Errors are always computed from the RAW model output (``yhat_raw_eur_mwh``).
The old version read ``yhat_eur_mwh`` which, in files written after a correction
was applied, is already corrected -> the estimated "bias" was the residual of a
corrected forecast and was then subtracted from the raw forecast again.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "forecasts"


def collect_errors(price: pd.Series, forecast_dir: Path = OUT_DIR, max_files: int = 21,
                   before: pd.Timestamp | None = None) -> pd.DataFrame:
    """
    Table of (timestamp, hour, error = raw_yhat - actual) from scored forecasts.
    `before`: only use realised hours strictly earlier than this instant, so a
    correction applied to delivery day D uses nothing from D.
    """
    rows = []
    for fpath in sorted(forecast_dir.glob("forecast_*.csv"))[-max_files:]:
        fc = pd.read_csv(fpath)
        col = "yhat_raw_eur_mwh" if "yhat_raw_eur_mwh" in fc.columns else "yhat_eur_mwh"
        if col not in fc.columns:
            continue
        fc["timestamp_utc"] = pd.to_datetime(fc["timestamp_utc"], utc=True)
        fc = fc.set_index("timestamp_utc")
        common = fc.index.intersection(price.index)
        if before is not None:
            common = common[common < before]
        if len(common) == 0:
            continue
        err = fc.loc[common, col] - price.loc[common]
        for ts, e in err.items():
            rows.append({"timestamp_utc": ts, "hour": int(ts.hour), "error": float(e)})
    if not rows:
        return pd.DataFrame(columns=["timestamp_utc", "hour", "error"])
    return pd.DataFrame(rows).drop_duplicates("timestamp_utc", keep="last")


def hourly_bias(errors: pd.DataFrame, min_obs: int = 5, last_n_days: int = 14,
                shrink: float = 0.5) -> pd.Series:
    """
    Mean error by hour-of-day over the last_n_days, shrunk toward zero.
    error = yhat - actual  =>  corrected = yhat - bias.
    min_obs=5 (was 2) and shrink=0.5 stop a single noisy day from driving the fix.
    """
    if errors.empty:
        return pd.Series(dtype=float)
    e = errors.copy()
    e["timestamp_utc"] = pd.to_datetime(e["timestamp_utc"], utc=True)
    e = e[e["timestamp_utc"] >= e["timestamp_utc"].max() - pd.Timedelta(days=last_n_days)]
    g = e.groupby("hour")["error"]
    bias = g.mean()[g.count() >= min_obs]
    return bias * shrink


def apply_bias_correction(forecast: pd.DataFrame, bias: pd.Series) -> pd.DataFrame:
    """Add yhat_raw_eur_mwh and overwrite yhat_eur_mwh with the corrected value."""
    out = forecast.copy()
    if "yhat_eur_mwh" not in out.columns:
        return out
    out["yhat_raw_eur_mwh"] = out["yhat_eur_mwh"]
    if bias is None or len(bias) == 0:
        out["bias_applied"] = 0.0
        return out
    hours = pd.to_datetime(out["timestamp_utc"], utc=True).dt.hour
    b = hours.map(lambda h: float(bias.get(h, 0.0)))
    out["bias_applied"] = b
    out["yhat_eur_mwh"] = (out["yhat_raw_eur_mwh"] - b).round(2)
    return out
