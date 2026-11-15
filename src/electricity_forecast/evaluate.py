"""Backtesting, baselines, relative metrics and Diebold-Mariano test."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
from scipy import stats

from .features import make_features, regularize_hourly
from .train import fit_ensemble, predict_ensemble

DEFAULT_WINDOWS = [
    ("2026-07-27", "2026-08-25 23:00"),
    ("2026-08-26", "2026-09-24 23:00"),
    ("2026-09-25", "2026-10-23 23:00"),
]


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def mae(y, p) -> float:
    return float(np.nanmean(np.abs(np.asarray(y, float) - np.asarray(p, float))))


def rmse(y, p) -> float:
    return float(np.sqrt(np.nanmean((np.asarray(y, float) - np.asarray(p, float)) ** 2)))


def rmae(y, p, p_bench) -> float:
    """MAE(model) / MAE(benchmark). < 1 means the model beats the benchmark."""
    return mae(y, p) / mae(y, p_bench)


def seasonal_naive(y: pd.Series, lag: int = 24) -> pd.Series:
    """SN24 = same hour yesterday; SN168 = same hour last week (use lag=168)."""
    return y.shift(lag)


# --------------------------------------------------------------------------- #
# Diebold-Mariano (Harvey-Leybourne-Newbold small-sample correction)
# --------------------------------------------------------------------------- #
def dm_test(err_model, err_bench, h: int = 1, power: int = 1) -> dict:
    """
    One-sided-capable DM test on a loss-differential series d = L(bench) - L(model).
    d > 0 on average  => model is better.
    Feed it DAILY mean losses (one value per delivery day) so intra-day
    dependence between the 24 hourly errors does not inflate significance.
    """
    e1 = np.asarray(err_model, float)
    e2 = np.asarray(err_bench, float)
    m = ~(np.isnan(e1) | np.isnan(e2))
    d = np.abs(e2[m]) ** power - np.abs(e1[m]) ** power
    n = len(d)
    if n < 8:
        return {"n": n, "mean_diff": float("nan"), "dm": float("nan"), "p_two_sided": float("nan"), "p_model_better": float("nan")}
    dbar = d.mean()
    gamma0 = np.var(d, ddof=0)
    lrv = gamma0
    for k in range(1, h):
        gk = np.mean((d[k:] - dbar) * (d[:-k] - dbar))
        lrv += 2 * gk
    lrv = max(lrv, 1e-12)
    dm = dbar / np.sqrt(lrv / n)
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_adj = dm * hln
    p2 = 2 * (1 - stats.t.cdf(abs(dm_adj), df=n - 1))
    p1 = 1 - stats.t.cdf(dm_adj, df=n - 1)
    return {"n": n, "mean_diff": float(dbar), "dm": float(dm_adj), "p_two_sided": float(p2), "p_model_better": float(p1)}


def daily_mean_abs(err: pd.Series) -> pd.Series:
    """Collapse hourly errors to one |error| mean per UTC day."""
    return err.abs().groupby(err.index.normalize()).mean()


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #
def backtest_predictions(
    df: pd.DataFrame,
    external_shift: int = 24,
    windows: Iterable[tuple[str, str]] = DEFAULT_WINDOWS,
    hgb_weight: float = 0.65,
    price_info: str = "gate",
    weather_shift: int | None = None,
) -> pd.DataFrame:
    """Hourly out-of-sample predictions for all windows (expanding training set)."""
    df = regularize_hourly(df)
    X_all, y_all = make_features(
        df, external_shift=external_shift, price_info=price_info, weather_shift=weather_shift
    )
    price = df["price_eur_mwh"]
    out = []
    for i, (start, end) in enumerate(windows, 1):
        start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
        tr = y_all.index < start_ts
        te = (y_all.index >= start_ts) & (y_all.index <= end_ts)
        if te.sum() < 50:
            continue
        models = fit_ensemble(X_all.loc[tr], y_all.loc[tr], hgb_weight=hgb_weight)
        Xte = X_all.loc[te]
        part = pd.DataFrame(
            {
                "window": i,
                "y": y_all.loc[te],
                "ens": predict_ensemble(models, Xte),
                "hgb": models["hgb"].predict(Xte),
                "ridge": models["ridge"].predict(Xte),
                "sn24": price.shift(24).reindex(Xte.index),
                "sn168": price.shift(168).reindex(Xte.index),
            }
        )
        out.append(part)
    return pd.concat(out) if out else pd.DataFrame()


def run_backtest(
    df: pd.DataFrame,
    external_shift: int = 24,
    windows: Iterable[tuple[str, str]] = DEFAULT_WINDOWS,
    hgb_weight: float = 0.65,
    price_info: str = "gate",
    weather_shift: int | None = None,
) -> pd.DataFrame:
    """Per-window summary (MAE for every model + SN24/SN168 + relative MAE)."""
    windows = list(windows)
    pred = backtest_predictions(df, external_shift, windows, hgb_weight, price_info, weather_shift)
    rows = []
    for w, g in pred.groupby("window"):
        g = g.dropna(subset=["sn24", "sn168"])
        start, end = windows[int(w) - 1]
        rows.append(
            {
                "window": int(w),
                "start": start,
                "end": end,
                "n_test": len(g),
                "mae_sn24": mae(g.y, g.sn24),
                "mae_sn168": mae(g.y, g.sn168),
                "mae_hgb": mae(g.y, g.hgb),
                "mae_ridge": mae(g.y, g.ridge),
                "mae_ens": mae(g.y, g.ens),
                "rmse_ens": rmse(g.y, g.ens),
                "rmae_vs_sn24": rmae(g.y, g.ens, g.sn24),
                "rmae_vs_sn168": rmae(g.y, g.ens, g.sn168),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Live scoring of daily forecast files (with baselines)
# --------------------------------------------------------------------------- #
def score_forecast_frame(fc: pd.DataFrame, price: pd.Series) -> dict | None:
    """
    Score one forecast file against realised prices and the two naive baselines.
    Baselines are computed from the same realised series, using only data that
    was available before the delivery day (lag >= 24 h).
    """
    fc = fc.copy()
    fc["timestamp_utc"] = pd.to_datetime(fc["timestamp_utc"], utc=True)
    fc = fc.set_index("timestamp_utc")
    common = fc.index.intersection(price.index)
    if len(common) == 0:
        return None
    y = price.loc[common]
    pred = fc.loc[common, "yhat_eur_mwh"]
    sn24 = price.shift(24, freq="h").reindex(common)
    sn168 = price.shift(168, freq="h").reindex(common)
    row = {
        "n_hours_scored": int(len(common)),
        "mae": round(mae(y, pred), 2),
        "rmse": round(rmse(y, pred), 2),
        "mae_sn24": round(mae(y, sn24), 2) if sn24.notna().any() else np.nan,
        "mae_sn168": round(mae(y, sn168), 2) if sn168.notna().any() else np.nan,
    }
    row["rmae_sn24"] = round(row["mae"] / row["mae_sn24"], 3) if row["mae_sn24"] else np.nan
    row["rmae_sn168"] = round(row["mae"] / row["mae_sn168"], 3) if row["mae_sn168"] else np.nan
    if "yhat_raw_eur_mwh" in fc.columns:
        row["mae_raw"] = round(mae(y, fc.loc[common, "yhat_raw_eur_mwh"]), 2)
    row["complete_day"] = bool(len(common) >= 23)
    row["pre_gate"] = bool(fc["pre_gate"].iloc[0]) if "pre_gate" in fc.columns else np.nan
    return row
