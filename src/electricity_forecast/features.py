"""Feature engineering with explicit leakage control."""

from __future__ import annotations

import numpy as np
import pandas as pd

PRICE_LAGS = [24, 48, 72, 168, 336]
EXTERNAL_COLS = [
    "forecast_wind_solar_combined",
    "forecast_wind_offshore",
    "forecast_wind_onshore",
    "forecast_solar",
    "avg_wind",
    "avg_temp",
    "avg_rad",
]


def make_features(
    df: pd.DataFrame,
    external_shift: int = 24,
    price_col: str = "price_eur_mwh",
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Build feature matrix and target.

    Parameters
    ----------
    df : DataFrame
        Must contain price_col and the external forecast columns.
    external_shift : int
        Hours to lag external features.
        - 24  → Conservative protocol (default, leakage-safe)
        - 0   → Optimistic (assumes forecasts known at target hour)
    """
    s = df[price_col]
    X = pd.DataFrame(index=df.index)

    # Calendar / cyclical
    X["hour"] = df.index.hour
    X["dow"] = df.index.dayofweek
    X["month"] = df.index.month
    X["hour_sin"] = np.sin(2 * np.pi * X["hour"] / 24)
    X["hour_cos"] = np.cos(2 * np.pi * X["hour"] / 24)
    X["dow_sin"] = np.sin(2 * np.pi * X["dow"] / 7)
    X["dow_cos"] = np.cos(2 * np.pi * X["dow"] / 7)

    # Price lags & rolling stats (always causal)
    for lag in PRICE_LAGS:
        X[f"lag_{lag}"] = s.shift(lag)
    X["roll_mean_24"] = s.shift(1).rolling(24, min_periods=12).mean()
    X["roll_std_24"] = s.shift(1).rolling(24, min_periods=12).std()
    X["roll_mean_168"] = s.shift(1).rolling(168, min_periods=84).mean()
    X["roll_std_168"] = s.shift(1).rolling(168, min_periods=84).std()

    # External features with explicit shift
    for c in EXTERNAL_COLS:
        if c in df.columns:
            X[c] = df[c].shift(external_shift)

    y = s.copy()
    valid = X.dropna().index.intersection(y.dropna().index)
    return X.loc[valid], y.loc[valid]
