#!/usr/bin/env python3
"""Fetch only new rows from SMARD + Open-Meteo weather + ENTSO-E load and append to CSVs."""

from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

PRICE_CSV = RAW / "germany_electricity_hourly.csv"
SMARD_CSV = RAW / "germany_smard_day_ahead_forecasts.csv"
WEATHER_CSV = RAW / "germany_weather_forecast_archive.csv"
LOAD_CSV = RAW / "germany_load_forecast.csv"

BASE = "https://www.smard.de/app/chart_data"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "germany-electricity-forecast/1.2"})

PRICE_FILTER = "4169"
SMARD_FILTERS = {
    "5097": "forecast_wind_solar_combined",
    "3791": "forecast_wind_offshore",
    "123": "forecast_wind_onshore",
    "125": "forecast_solar",
}

WEATHER_POINTS = {
    "north": (53.55, 10.00),
    "east": (52.52, 13.40),
    "south": (48.14, 11.58),
    "west": (50.94, 6.96),
}

ENTSOE_URL = "https://web-api.tp.entsoe.eu/api"
ENTSOE_AREA = "10Y1001A1001A83F"
ENTSOE_NS = {"ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"}


def last_ts(path: Path, col: str = "timestamp_utc") -> pd.Timestamp | None:
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, usecols=[col])
    except ValueError:
        df = pd.read_csv(path)
        if col not in df.columns:
            return None
    if df.empty:
        return None
    return pd.to_datetime(df[col], utc=True).max()


def fetch_smard_series(filter_id: str, start: pd.Timestamp, end: pd.Timestamp) -> list[tuple]:
    index_url = f"{BASE}/{filter_id}/DE/index_hour.json"
    r = SESSION.get(index_url, timeout=90)
    r.raise_for_status()
    timestamps = r.json().get("timestamps", [])

    selected = [
        int(ts)
        for ts in timestamps
        if start - pd.Timedelta(days=14)
        <= pd.Timestamp(ts, unit="ms", tz="UTC")
        <= end + pd.Timedelta(days=2)
    ]

    points: list[tuple] = []
    for i, chunk_ts in enumerate(selected, 1):
        url = f"{BASE}/{filter_id}/DE/{filter_id}_DE_hour_{chunk_ts}.json"
        try:
            resp = SESSION.get(url, timeout=90)
            resp.raise_for_status()
            for item in resp.json().get("series", []):
                if len(item) < 2 or item[1] is None:
                    continue
                t = pd.to_datetime(item[0], unit="ms", utc=True)
                if start < t <= end + pd.Timedelta(days=2):
                    points.append((t, float(item[1])))
        except Exception as exc:
            print(f"  warn chunk {chunk_ts}: {exc}")
        if i % 25 == 0:
            print(f"  chunks {i}/{len(selected)}")
        time.sleep(0.05)
    return points


def append_csv(path: Path, new: pd.DataFrame, key: str = "timestamp_utc") -> None:
    new = new.copy()
    new[key] = pd.to_datetime(new[key], utc=True)
    if path.exists():
        old = pd.read_csv(path)
        old[key] = pd.to_datetime(old[key], utc=True)
        for c in new.columns:
            if c not in old.columns:
                old[c] = pd.NA
        for c in old.columns:
            if c not in new.columns and c != key:
                new[c] = pd.NA
        cols = list(dict.fromkeys(list(old.columns) + list(new.columns)))
        merged = pd.concat([old[cols], new[cols]], ignore_index=True)
        merged = merged.drop_duplicates(key, keep="last").sort_values(key)
    else:
        merged = new.sort_values(key)
    merged.to_csv(path, index=False)
    print(f"  saved {path.name}: rows={len(merged)} last={merged[key].max()}")


def update_price() -> None:
    print("Updating prices ...")
    end = pd.Timestamp.now(tz="UTC")
    start = last_ts(PRICE_CSV) or (end - pd.Timedelta(days=60))
    points = fetch_smard_series(PRICE_FILTER, start, end)
    if not points:
        print("  no new price rows")
        return
    new = pd.DataFrame(points, columns=["timestamp_utc", "price_eur_mwh"])
    new = new.drop_duplicates("timestamp_utc")
    append_csv(PRICE_CSV, new)


def update_smard_forecasts() -> None:
    print("Updating SMARD forecasts ...")
    end = pd.Timestamp.now(tz="UTC")
    start = last_ts(SMARD_CSV) or (end - pd.Timedelta(days=60))
    frames = {}
    for fid, name in SMARD_FILTERS.items():
        print(f"  {name}")
        pts = fetch_smard_series(fid, start, end)
        if not pts:
            continue
        s = (
            pd.DataFrame(pts, columns=["timestamp_utc", name])
            .drop_duplicates("timestamp_utc")
            .set_index("timestamp_utc")[name]
        )
        frames[name] = s
    if not frames:
        print("  no new forecast rows")
        return
    new = pd.concat(frames.values(), axis=1).sort_index().reset_index()
    append_csv(SMARD_CSV, new)


def update_weather_open_meteo() -> None:
    print("Updating weather (Open-Meteo) ...")
    end = pd.Timestamp.now(tz="UTC").normalize()
    start_ts = last_ts(WEATHER_CSV)
    start = (
        (start_ts - pd.Timedelta(days=2)).normalize()
        if start_ts is not None
        else end - pd.Timedelta(days=40)
    )

    if start > end:
        print("  weather already up to date")
        return

    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")
    hourly_vars = "temperature_2m,wind_speed_100m,shortwave_radiation"

    pieces = []
    for region, (lat, lon) in WEATHER_POINTS.items():
        url = (
            "https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat}&longitude={lon}"
            f"&start_date={start_date}&end_date={end_date}"
            f"&hourly={hourly_vars}&timezone=UTC"
        )
        try:
            r = SESSION.get(url, timeout=120)
            r.raise_for_status()
            h = r.json().get("hourly", {})
            t = pd.to_datetime(h.get("time", []), utc=True)
            part = pd.DataFrame(
                {
                    "timestamp_utc": t,
                    f"{region}_temperature_2m": h.get("temperature_2m"),
                    f"{region}_wind_speed_100m": h.get("wind_speed_100m"),
                    f"{region}_shortwave_radiation": h.get("shortwave_radiation"),
                }
            )
            pieces.append(part.set_index("timestamp_utc"))
            print(f"  {region}: {len(part)} rows")
            time.sleep(0.4)
        except Exception as exc:
            print(f"  weather warn {region}: {exc}")

    for region, (lat, lon) in WEATHER_POINTS.items():
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly={hourly_vars}&past_days=2&forecast_days=2&timezone=UTC"
        )
        try:
            r = SESSION.get(url, timeout=120)
            r.raise_for_status()
            h = r.json().get("hourly", {})
            t = pd.to_datetime(h.get("time", []), utc=True)
            part = pd.DataFrame(
                {
                    "timestamp_utc": t,
                    f"{region}_temperature_2m": h.get("temperature_2m"),
                    f"{region}_wind_speed_100m": h.get("wind_speed_100m"),
                    f"{region}_shortwave_radiation": h.get("shortwave_radiation"),
                }
            )
            pieces.append(part.set_index("timestamp_utc"))
            time.sleep(0.3)
        except Exception as exc:
            print(f"  forecast-api warn {region}: {exc}")

    if not pieces:
        print("  no weather rows")
        return

    new = pd.concat(pieces, axis=0)
    new = new.groupby(level=0).mean(numeric_only=True).sort_index().reset_index()
    append_csv(WEATHER_CSV, new)


def _entsoe_fetch_chunk(key: str, start: datetime, end: datetime) -> list[tuple]:
    params = {
        "securityToken": key,
        "documentType": "A65",
        "processType": "A01",
        "outBiddingZone_Domain": ENTSOE_AREA,
        "periodStart": start.strftime("%Y%m%d%H%M"),
        "periodEnd": end.strftime("%Y%m%d%H%M"),
    }
    r = SESSION.get(ENTSOE_URL, params=params, timeout=90)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    rows: list[tuple] = []
    for ts in root.findall("ns:TimeSeries", ENTSOE_NS):
        for period in ts.findall("ns:Period", ENTSOE_NS):
            start_txt = period.find("ns:timeInterval/ns:start", ENTSOE_NS).text
            t0 = datetime.fromisoformat(start_txt.replace("Z", "+00:00"))
            res = period.find("ns:resolution", ENTSOE_NS).text
            step = 15 if res == "PT15M" else 60
            for point in period.findall("ns:Point", ENTSOE_NS):
                pos = int(point.find("ns:position", ENTSOE_NS).text)
                qty = float(point.find("ns:quantity", ENTSOE_NS).text)
                ts_utc = t0 + timedelta(minutes=step * (pos - 1))
                rows.append((ts_utc, qty))
    return rows


def update_load_forecast(days_back: int = 14) -> None:
    print("Updating ENTSO-E load forecast ...")
    key = os.environ.get("ENTSOE_API_KEY")
    if not key:
        print("  skip load forecast: ENTSOE_API_KEY not set")
        return

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_ts = last_ts(LOAD_CSV)
    if start_ts is not None:
        start = (start_ts.to_pydatetime() - timedelta(days=2)).replace(tzinfo=timezone.utc)
    else:
        start = end - timedelta(days=days_back)

    all_rows: list[tuple] = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=7), end)
        try:
            all_rows.extend(_entsoe_fetch_chunk(key, cur, nxt))
        except Exception as exc:
            print(f"  load chunk error {cur.date()}->{nxt.date()}: {exc}")
        time.sleep(0.8)
        cur = nxt

    if not all_rows:
        print("  no new load rows")
        return

    new = pd.DataFrame(all_rows, columns=["timestamp_utc", "load_forecast_mw"])
    new["timestamp_utc"] = pd.to_datetime(new["timestamp_utc"], utc=True)
    new = (
        new.drop_duplicates("timestamp_utc")
        .set_index("timestamp_utc")
        .resample("h")
        .mean()
        .dropna()
        .reset_index()
    )
    append_csv(LOAD_CSV, new)


def main() -> None:
    print("START update_data", pd.Timestamp.now(tz="UTC"))
    try:
        update_price()
    except Exception as exc:
        print("PRICE ERROR:", exc)
    try:
        update_smard_forecasts()
    except Exception as exc:
        print("SMARD ERROR:", exc)
    try:
        update_weather_open_meteo()
    except Exception as exc:
        print("WEATHER ERROR:", exc)
    try:
        update_load_forecast(days_back=14)
    except Exception as exc:
        print("LOAD ERROR:", exc)
    print("DONE update_data")


if __name__ == "__main__":
    main()
