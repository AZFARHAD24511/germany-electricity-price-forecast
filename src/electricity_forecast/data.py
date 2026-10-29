"""Data loading and joining utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_PRICE_COLS = ["timestamp_utc", "price_eur_mwh"]
SMARD_VALUE_COLS = [
    "forecast_wind_solar_combined",
    "forecast_wind_offshore",
    "forecast_wind_onshore",
    "forecast_solar",
]
WEATHER_AGG_COLS = ["avg_wind", "avg_temp", "avg_rad"]


def load_price_series(path: Path | str) -> pd.Series:
    """Load hourly day-ahead price (EUR/MWh) indexed by UTC timestamp."""
    df = pd.read_csv(path, usecols=DEFAULT_PRICE_COLS)
    df["ts"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    s = df.set_index("ts").sort_index()["price_eur_mwh"].astype(float)
    return s


def load_smard_forecasts(path: Path | str) -> pd.DataFrame:
    """Load SMARD day-ahead wind/solar forecasts."""
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    cols = [c for c in SMARD_VALUE_COLS if c in df.columns]
    out = df.set_index("ts").sort_index()[cols]
    return out


def load_weather(path: Path | str) -> pd.DataFrame:
    """Load regional weather and aggregate to national means."""
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.set_index("ts").sort_index()
    wind_cols = [c for c in df.columns if "wind_speed_100m" in c]
    temp_cols = [c for c in df.columns if "temperature_2m" in c]
    rad_cols = [c for c in df.columns if "shortwave" in c]
    out = pd.DataFrame(index=df.index)
    out["avg_wind"] = df[wind_cols].mean(axis=1) if wind_cols else float("nan")
    out["avg_temp"] = df[temp_cols].mean(axis=1) if temp_cols else float("nan")
    out["avg_rad"] = df[rad_cols].mean(axis=1) if rad_cols else float("nan")
    return out


def join_all(
    price_path: Path | str,
    smard_path: Path | str,
    weather_path: Path | str,
    ffill_limit: int = 2,
) -> pd.DataFrame:
    """Inner-join price, SMARD forecasts and weather on UTC timestamp."""
    price = load_price_series(price_path).to_frame("price_eur_mwh")
    smard = load_smard_forecasts(smard_path)
    weather = load_weather(weather_path)
    df = pd.concat([price, smard, weather], axis=1, join="inner")
    df = df.ffill(limit=ffill_limit)
    return df
