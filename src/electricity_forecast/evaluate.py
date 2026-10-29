"""Backtesting and metrics."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .features import make_features
from .train import fit_ensemble, predict_ensemble


DEFAULT_WINDOWS = [
    ("2026-07-27", "2026-08-25 23:00"),
    ("2026-08-26", "2026-09-24 23:00"),
    ("2026-09-25", "2026-10-23 23:00"),
]


def mae(y: np.ndarray | pd.Series, p: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(y) - p)))


def rmse(y: np.ndarray | pd.Series, p: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(y) - p) ** 2)))


def seasonal_naive(y: pd.Series, lag: int = 24) -> pd.Series:
    return y.shift(lag)


def run_backtest(
    df: pd.DataFrame,
    external_shift: int = 24,
    windows: Iterable[tuple[str, str]] = DEFAULT_WINDOWS,
    hgb_weight: float = 0.65,
) -> pd.DataFrame:
    """
    Expanding-window backtest.

    Returns a summary DataFrame with MAE/RMSE per window and model.
    """
    X_all, y_all = make_features(df, external_shift=external_shift)
    rows = []

    for i, (start, end) in enumerate(windows, 1):
        train_mask = y_all.index < start
        test_mask = (y_all.index >= start) & (y_all.index <= end)
        X_tr, y_tr = X_all.loc[train_mask], y_all.loc[train_mask]
        X_te, y_te = X_all.loc[test_mask], y_all.loc[test_mask]
        if len(X_te) < 50:
            continue

        models = fit_ensemble(X_tr, y_tr, hgb_weight=hgb_weight)
        pred_ens = predict_ensemble(models, X_te)
        pred_hgb = models["hgb"].predict(X_te)
        pred_ridge = models["ridge"].predict(X_te)
        sn24 = seasonal_naive(y_all, 24).loc[X_te.index]

        rows.append(
            {
                "window": i,
                "start": start,
                "end": end,
                "n_test": len(X_te),
                "mae_sn24": mae(y_te, sn24),
                "mae_hgb": mae(y_te, pred_hgb),
                "mae_ridge": mae(y_te, pred_ridge),
                "mae_ens": mae(y_te, pred_ens),
                "rmse_ens": rmse(y_te, pred_ens),
            }
        )

    return pd.DataFrame(rows)
