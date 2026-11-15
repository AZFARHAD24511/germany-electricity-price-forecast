"""Feature engineering with explicit leakage control."""

from __future__ import annotations

from datetime import date, timedelta

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


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = ((h + ll - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def german_public_holidays(year: int) -> set[date]:
    """Federal public holidays in Germany (national set)."""
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        date(year, 5, 1),
        easter + timedelta(days=39),
        easter + timedelta(days=50),
        date(year, 10, 3),
        date(year, 12, 25),
        date(year, 12, 26),
    }


def _holiday_set_for_index(index: pd.DatetimeIndex) -> set[date]:
    years = range(int(index.min().year) - 1, int(index.max().year) + 2)
    out: set[date] = set()
    for y in years:
        out |= german_public_holidays(y)
    return out


def make_features(
    df: pd.DataFrame,
    external_shift: int = 24,
    price_col: str = "price_eur_mwh",
) -> tuple[pd.DataFrame, pd.Series]:
    s = df[price_col]
    X = pd.DataFrame(index=df.index)

    X["hour"] = df.index.hour
    X["dow"] = df.index.dayofweek
    X["month"] = df.index.month
    X["hour_sin"] = np.sin(2 * np.pi * X["hour"] / 24)
    X["hour_cos"] = np.cos(2 * np.pi * X["hour"] / 24)
    X["dow_sin"] = np.sin(2 * np.pi * X["dow"] / 7)
    X["dow_cos"] = np.cos(2 * np.pi * X["dow"] / 7)
    X["month_sin"] = np.sin(2 * np.pi * X["month"] / 12)
    X["month_cos"] = np.cos(2 * np.pi * X["month"] / 12)

    X["season"] = ((X["month"] % 12) // 3) + 1
    X["is_weekend"] = (X["dow"] >= 5).astype(np.int8)

    hols = _holiday_set_for_index(df.index)
    dates = pd.Series(df.index.date, index=df.index)
    X["is_holiday"] = dates.map(lambda d: 1 if d in hols else 0).astype(np.int8)
    hols_before = {d - timedelta(days=1) for d in hols}
    hols_after = {d + timedelta(days=1) for d in hols}
    X["is_holiday_eve"] = dates.map(lambda d: 1 if d in hols_before else 0).astype(np.int8)
    X["is_holiday_next"] = dates.map(lambda d: 1 if d in hols_after else 0).astype(np.int8)

    for lag in PRICE_LAGS:
        X[f"lag_{lag}"] = s.shift(lag)
    X["roll_mean_24"] = s.shift(1).rolling(24, min_periods=12).mean()
    X["roll_std_24"] = s.shift(1).rolling(24, min_periods=12).std()
    X["roll_mean_168"] = s.shift(1).rolling(168, min_periods=84).mean()
    X["roll_std_168"] = s.shift(1).rolling(168, min_periods=84).std()

    for c in EXTERNAL_COLS:
        if c in df.columns:
            X[c] = df[c].shift(external_shift)

    y = s.copy()
    valid = X.dropna().index.intersection(y.dropna().index)
    return X.loc[valid], y.loc[valid]