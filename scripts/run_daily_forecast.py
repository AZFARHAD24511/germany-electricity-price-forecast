#!/usr/bin/env python3
"""هر روز: داده را به‌روز کن، بعد قیمت ۲۴ ساعت آینده را پیش‌بینی کن."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electricity_forecast.data import join_all
from electricity_forecast.features import make_features
from electricity_forecast.train import fit_ensemble, predict_ensemble

RAW = ROOT / "data" / "raw"
OUT_DIR = ROOT / "outputs" / "forecasts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PRICE = RAW / "germany_electricity_hourly.csv"
SMARD = RAW / "germany_smard_day_ahead_forecasts.csv"
WEATHER = RAW / "germany_weather_forecast_archive.csv"


def update_data() -> None:
    script = ROOT / "scripts" / "update_data.py"
    print("Running update_data.py …")
    subprocess.run([sys.executable, str(script)], check=False)


def main() -> None:
    now = pd.Timestamp.now(tz="UTC")
    print("START daily forecast", now)

    # 1) داده جدید
    update_data()

    # 2) بارگذاری
    if not WEATHER.exists():
        print("ERROR: weather file missing:", WEATHER)
        return

    df = join_all(PRICE, SMARD, WEATHER)
    print(f"Joined rows={len(df)}  last={df.index.max()}")

    # 3) ویژگی‌ها — Conservative
    X, y = make_features(df, external_shift=24)
    if len(X) < 500:
        print("ERROR: not enough data")
        return

    # 4) آموزش روی همه داده موجود
    models = fit_ensemble(X, y, hgb_weight=0.65)

    # 5) افق پیش‌بینی: از آخرین ساعت موجود تا +48 ساعت
    last = y.index.max()
    horizon_end = last + pd.Timedelta(hours=48)

    # برای ساعت‌های آینده، ردیف ویژگی کامل نداریم؛
    # از آخرین ردیف‌های موجود برای ارزیابی اخیر استفاده می‌کنیم
    # و یک پیش‌بینی ساده برای «فردا» بر اساس آخرین الگوی مدل + naive
    recent = X.iloc[-24 * 7 :]  # یک هفته آخر
    pred_recent = predict_ensemble(models, recent)

    # پیش‌بینی عملیاتی ساده برای ۲۴ ساعت آینده:
    # میانگین پیش‌بینی مدل روی همین ساعت در ۷ روز گذشته (ساعت‌مشابه)
    future_hours = pd.date_range(last + pd.Timedelta(hours=1), periods=24, freq="h", tz="UTC")
    rows = []
    for ts in future_hours:
        # ساعت‌های مشابه در گذشته اخیر
        mask = recent.index.hour == ts.hour
        if mask.any():
            yhat = float(np.mean(pred_recent[mask]))
        else:
            yhat = float(pred_recent[-1])
        rows.append({"timestamp_utc": ts, "yhat_eur_mwh": round(yhat, 2)})

    out = pd.DataFrame(rows)
    out_path = OUT_DIR / f"forecast_{now.strftime('%Y-%m-%d')}.csv"
    out.to_csv(out_path, index=False)

    print("Forecast next 24h after last data hour:")
    print(out.to_string(index=False))
    print("Saved →", out_path)
    print("DONE")


if __name__ == "__main__":
    main()