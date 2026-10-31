#!/usr/bin/env python3
"""هر روز فقط داده جدید را از SMARD می‌گیرد و به CSVها اضافه می‌کند."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

PRICE_CSV = RAW / "germany_electricity_hourly.csv"
SMARD_CSV = RAW / "germany_smard_day_ahead_forecasts.csv"

BASE = "https://www.smard.de/app/chart_data"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "research-daily-update/1.0"})

# قیمت day-ahead آلمان/لوکزامبورگ
PRICE_FILTER = "4169"
# پیش‌بینی باد/خورشید
SMARD_FILTERS = {
    "5097": "forecast_wind_solar_combined",
    "3791": "forecast_wind_offshore",
    "123": "forecast_wind_onshore",
    "125": "forecast_solar",
}


def last_ts(path: Path, col: str = "timestamp_utc") -> pd.Timestamp | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, usecols=[col])
    if df.empty:
        return None
    return pd.to_datetime(df[col], utc=True).max()


def fetch_series(filter_id: str, start: pd.Timestamp, end: pd.Timestamp) -> list[tuple]:
    index_url = f"{BASE}/{filter_id}/DE/index_hour.json"
    r = SESSION.get(index_url, timeout=60)
    r.raise_for_status()
    timestamps = r.json().get("timestamps", [])

    selected = [
        int(ts)
        for ts in timestamps
        if start - pd.Timedelta(days=10)
        <= pd.Timestamp(ts, unit="ms", tz="UTC")
        <= end
    ]

    points = []
    for i, chunk_ts in enumerate(selected, 1):
        url = f"{BASE}/{filter_id}/DE/{filter_id}_DE_hour_{chunk_ts}.json"
        try:
            resp = SESSION.get(url, timeout=60)
            resp.raise_for_status()
            for item in resp.json().get("series", []):
                if len(item) < 2 or item[1] is None:
                    continue
                t = pd.to_datetime(item[0], unit="ms", utc=True)
                if start < t <= end:
                    points.append((t, float(item[1])))
        except Exception as exc:
            print(f"  warn chunk {chunk_ts}: {exc}")
        if i % 20 == 0:
            print(f"  chunks {i}/{len(selected)}")
        time.sleep(0.05)
    return points


def update_price() -> None:
    print("Updating prices …")
    end = pd.Timestamp.now(tz="UTC")
    start = last_ts(PRICE_CSV) or (end - pd.Timedelta(days=30))
    points = fetch_series(PRICE_FILTER, start, end)
    if not points:
        print("  no new price rows")
        return
    new = pd.DataFrame(points, columns=["timestamp_utc", "price_eur_mwh"])
    new = new.drop_duplicates("timestamp_utc")
    if PRICE_CSV.exists():
        old = pd.read_csv(PRICE_CSV)
        old["timestamp_utc"] = pd.to_datetime(old["timestamp_utc"], utc=True)
        new["timestamp_utc"] = pd.to_datetime(new["timestamp_utc"], utc=True)
        # فقط ستون‌های مشترک را نگه می‌داریم اگر فایل قدیمی ستون‌های بیشتری دارد
        cols = [c for c in ["timestamp_utc", "price_eur_mwh"] if c in old.columns]
        merged = pd.concat([old[cols], new], ignore_index=True)
        merged = merged.drop_duplicates("timestamp_utc", keep="last").sort_values("timestamp_utc")
    else:
        merged = new.sort_values("timestamp_utc")
    merged.to_csv(PRICE_CSV, index=False)
    print(f"  price rows total={len(merged)}  last={merged['timestamp_utc'].max()}")


def update_smard_forecasts() -> None:
    print("Updating SMARD forecasts …")
    end = pd.Timestamp.now(tz="UTC")
    start = last_ts(SMARD_CSV) or (end - pd.Timedelta(days=30))

    frames = {}
    for fid, name in SMARD_FILTERS.items():
        print(f"  {name}")
        pts = fetch_series(fid, start, end)
        if not pts:
            continue
        s = pd.DataFrame(pts, columns=["timestamp_utc", name]).drop_duplicates("timestamp_utc")
        s = s.set_index("timestamp_utc")[name]
        frames[name] = s

    if not frames:
        print("  no new forecast rows")
        return

    new = pd.concat(frames.values(), axis=1).sort_index().reset_index()
    if SMARD_CSV.exists():
        old = pd.read_csv(SMARD_CSV)
        old["timestamp_utc"] = pd.to_datetime(old["timestamp_utc"], utc=True)
        new["timestamp_utc"] = pd.to_datetime(new["timestamp_utc"], utc=True)
        # ستون‌های پیش‌بینی مشترک
        value_cols = [c for c in SMARD_FILTERS.values() if c in old.columns or c in new.columns]
        keep_old = ["timestamp_utc"] + [c for c in value_cols if c in old.columns]
        keep_new = ["timestamp_utc"] + [c for c in value_cols if c in new.columns]
        merged = pd.concat([old[keep_old], new[keep_new]], ignore_index=True, sort=False)
        merged = merged.drop_duplicates("timestamp_utc", keep="last").sort_values("timestamp_utc")
    else:
        merged = new
    merged.to_csv(SMARD_CSV, index=False)
    print(f"  smard rows total={len(merged)}  last={merged['timestamp_utc'].max()}")


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
    print("DONE update_data")


if __name__ == "__main__":
    main()