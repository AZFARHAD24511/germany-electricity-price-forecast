"""Feature engineering with explicit, testable availability rules.

Information set (gate-closure protocol)
---------------------------------------
Day-ahead prices for delivery day D are fixed at ~12:00 CET on D-1.
At that moment the *only* price information available is: every price up to
and including the last hour of day D-1 (those were published ~12:45 on D-2).

Therefore, for a target hour ``ts`` on local day D:

* same-hour price lags use lag >= 24 h  -> always inside D-1 or earlier
* "rolling" context is computed from COMPLETE local days up to D-1
  (never from the hours of D that precede ``ts``)

``price_info="legacy"`` reproduces the original ``shift(1).rolling(...)``
features. They use price(ts-1), which is NOT known when bids are placed.
Legacy mode exists only to quantify how much that leak flattered the backtest.

ENTSO-E day-ahead load forecast is treated as available for the target hour
(no 24h shift): it is published for use in the day-ahead market.
SMARD wind/solar stay under external_shift (default 24h, conservative).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

LOCAL_TZ = "Europe/Berlin"
PRICE_LAGS = [24, 48, 72, 168, 336]
SMARD_COLS = [
    "forecast_wind_solar_combined",
    "forecast_wind_offshore",
    "forecast_wind_onshore",
    "forecast_solar",
]
WEATHER_COLS = ["avg_wind", "avg_temp", "avg_rad"]
LOAD_COLS = ["load_forecast_mw"]
EXTERNAL_COLS = SMARD_COLS + WEATHER_COLS

CONTEXT_COLS = [
    "ctx_mean_1d",
    "ctx_std_1d",
    "ctx_min_1d",
    "ctx_max_1d",
    "ctx_last_1d",
    "ctx_mean_7d",
    "ctx_std_7d",
]
LEGACY_ROLL_COLS = ["roll_mean_24", "roll_std_24", "roll_mean_168", "roll_std_168"]


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


def local_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index.tz_convert(LOCAL_TZ).tz_localize(None).normalize()


def delivery_day_utc_index(target_date: date | str | pd.Timestamp) -> pd.DatetimeIndex:
    d = pd.Timestamp(target_date).tz_localize(None).normalize()
    start = d.tz_localize(LOCAL_TZ)
    end = (d + pd.Timedelta(days=1)).tz_localize(LOCAL_TZ)
    return pd.date_range(start.tz_convert("UTC"), end.tz_convert("UTC"), freq="h", inclusive="left")


def gate_closure_utc(target_date: date | str | pd.Timestamp) -> pd.Timestamp:
    d = pd.Timestamp(target_date).tz_localize(None).normalize() - pd.Timedelta(days=1)
    return (d + pd.Timedelta(hours=12)).tz_localize(LOCAL_TZ).tz_convert("UTC")


def _calendar_block(index: pd.DatetimeIndex) -> pd.DataFrame:
    X = pd.DataFrame(index=index)
    X["hour"] = index.hour
    X["dow"] = index.dayofweek
    X["month"] = index.month
    X["hour_sin"] = np.sin(2 * np.pi * X["hour"] / 24)
    X["hour_cos"] = np.cos(2 * np.pi * X["hour"] / 24)
    X["dow_sin"] = np.sin(2 * np.pi * X["dow"] / 7)
    X["dow_cos"] = np.cos(2 * np.pi * X["dow"] / 7)
    X["month_sin"] = np.sin(2 * np.pi * X["month"] / 12)
    X["month_cos"] = np.cos(2 * np.pi * X["month"] / 12)
    X["season"] = ((X["month"] % 12) // 3) + 1
    X["is_weekend"] = (X["dow"] >= 5).astype(np.int8)

    hols = _holiday_set_for_index(index)
    dates = pd.Series(index.date, index=index)
    before = {d - timedelta(days=1) for d in hols}
    after = {d + timedelta(days=1) for d in hols}
    X["is_holiday"] = dates.map(lambda d: 1 if d in hols else 0).astype(np.int8)
    X["is_holiday_eve"] = dates.map(lambda d: 1 if d in before else 0).astype(np.int8)
    X["is_holiday_next"] = dates.map(lambda d: 1 if d in after else 0).astype(np.int8)
    return X


def daily_context(s: pd.Series, min_hours: int = 20) -> pd.DataFrame:
    ld = local_dates(s.index)
    g = s.groupby(ld)
    cnt = g.count()
    out = pd.DataFrame(
        {
            "ctx_mean_1d": g.mean(),
            "ctx_std_1d": g.std(),
            "ctx_min_1d": g.min(),
            "ctx_max_1d": g.max(),
            "ctx_last_1d": g.last(),
        }
    )
    out.loc[cnt < min_hours, :] = np.nan
    r_mean = s.rolling(168, min_periods=84).mean()
    r_std = s.rolling(168, min_periods=84).std()
    out["ctx_mean_7d"] = r_mean.groupby(ld).last()
    out["ctx_std_7d"] = r_std.groupby(ld).last()
    out.loc[cnt < min_hours, ["ctx_mean_7d", "ctx_std_7d"]] = np.nan
    return out


def _gate_context_for_index(s: pd.Series, index: pd.DatetimeIndex) -> pd.DataFrame:
    ctx = daily_context(s)
    prev_day = local_dates(index) - pd.Timedelta(days=1)
    vals = ctx.reindex(prev_day)
    vals.index = index
    return vals


def _build(
    df: pd.DataFrame,
    external_shift: int,
    price_col: str,
    price_info: str,
    weather_shift: int | None,
) -> pd.DataFrame:
    if price_info not in {"gate", "legacy"}:
        raise ValueError("price_info must be 'gate' or 'legacy'")
    if weather_shift is None:
        weather_shift = external_shift

    s = df[price_col]
    X = _calendar_block(df.index)

    for lag in PRICE_LAGS:
        X[f"lag_{lag}"] = s.shift(lag)

    if price_info == "gate":
        X = X.join(_gate_context_for_index(s, df.index))
    else:
        X["roll_mean_24"] = s.shift(1).rolling(24, min_periods=12).mean()
        X["roll_std_24"] = s.shift(1).rolling(24, min_periods=12).std()
        X["roll_mean_168"] = s.shift(1).rolling(168, min_periods=84).mean()
        X["roll_std_168"] = s.shift(1).rolling(168, min_periods=84).std()

    for c in SMARD_COLS:
        if c in df.columns:
            X[c] = df[c].shift(external_shift)
    for c in WEATHER_COLS:
        if c in df.columns:
            X[c] = df[c].shift(weather_shift)
    # Day-ahead load forecast: available for target hour (no conservative shift)
    for c in LOAD_COLS:
        if c in df.columns:
            X[c] = df[c]
    return X


def make_features(
    df: pd.DataFrame,
    external_shift: int = 24,
    price_col: str = "price_eur_mwh",
    price_info: str = "gate",
    weather_shift: int | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    df = regularize_hourly(df)
    X = _build(df, external_shift, price_col, price_info, weather_shift)
    y = df[price_col]
    valid = X.dropna().index.intersection(y.dropna().index)
    return X.loc[valid], y.loc[valid]


def make_target_features(
    df: pd.DataFrame,
    target_date: date | str | pd.Timestamp,
    external_shift: int = 24,
    price_col: str = "price_eur_mwh",
    weather_shift: int | None = None,
    feature_cols: list[str] | None = None,
) -> pd.DataFrame:
    tgt_idx = delivery_day_utc_index(target_date)
    hist = df.loc[df.index < tgt_idx[0]].copy()
    if hist.empty:
        raise ValueError("No history before target date")
    ext = hist.reindex(hist.index.union(tgt_idx)).sort_index()
    ext.index.name = hist.index.name
    full = pd.date_range(ext.index.min(), ext.index.max(), freq="h", tz="UTC")
    ext = ext.reindex(full)
    X = _build(ext, external_shift, price_col, "gate", weather_shift).loc[tgt_idx]
    if feature_cols is not None:
        X = X.reindex(columns=feature_cols)
    return X


def regularize_hourly(df: pd.DataFrame) -> pd.DataFrame:
    full = pd.date_range(df.index.min(), df.index.max(), freq="h", tz="UTC")
    return df[~df.index.duplicated(keep="last")].sort_index().reindex(full)