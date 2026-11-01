#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from electricity_forecast.features import make_features
from electricity_forecast.train import fit_ensemble, predict_ensemble
from bias_correction import collect_errors, hourly_bias, apply_bias_correction

RAW = ROOT / "data" / "raw"
OUT_DIR = ROOT / "outputs" / "forecasts"
FIG_DIR = ROOT / "outputs" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

PRICE = RAW / "germany_electricity_hourly.csv"
SMARD = RAW / "germany_smard_day_ahead_forecasts.csv"
WEATHER = RAW / "germany_weather_forecast_archive.csv"
README = ROOT / "README.md"
MARKER_START = "<!-- DAILY_FORECAST_START -->"
MARKER_END = "<!-- DAILY_FORECAST_END -->"


def update_data() -> None:
    script = ROOT / "scripts" / "update_data.py"
    print("Running update_data.py ...")
    subprocess.run([sys.executable, str(script)], check=False)


def load_frame() -> pd.DataFrame:
    p = pd.read_csv(PRICE)
    p["ts"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    price = p.set_index("ts").sort_index()[["price_eur_mwh"]].astype(float)

    sm = pd.read_csv(SMARD)
    sm["ts"] = pd.to_datetime(sm["timestamp_utc"], utc=True)
    sm = sm.set_index("ts").sort_index()
    sm_cols = [c for c in [
        "forecast_wind_solar_combined", "forecast_wind_offshore",
        "forecast_wind_onshore", "forecast_solar"
    ] if c in sm.columns]
    sm = sm[sm_cols]

    if WEATHER.exists():
        w = pd.read_csv(WEATHER)
        w["ts"] = pd.to_datetime(w["timestamp_utc"], utc=True)
        w = w.set_index("ts").sort_index()
        wind_cols = [c for c in w.columns if "wind_speed_100m" in c]
        temp_cols = [c for c in w.columns if "temperature_2m" in c]
        rad_cols = [c for c in w.columns if "shortwave" in c]
        weather = pd.DataFrame(index=w.index)
        weather["avg_wind"] = w[wind_cols].mean(axis=1) if wind_cols else np.nan
        weather["avg_temp"] = w[temp_cols].mean(axis=1) if temp_cols else np.nan
        weather["avg_rad"] = w[rad_cols].mean(axis=1) if rad_cols else np.nan
    else:
        weather = pd.DataFrame(columns=["avg_wind", "avg_temp", "avg_rad"])

    df = price.join(sm, how="left").join(weather, how="left")
    df = df.ffill(limit=6)
    return df.dropna(subset=["price_eur_mwh"])


def make_forecast(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    X, y = make_features(df, external_shift=24)
    if len(X) < 500:
        raise RuntimeError("Not enough rows after features")
    models = fit_ensemble(X, y, hgb_weight=0.65)
    last = y.index.max()
    future = pd.date_range(last + pd.Timedelta(hours=1), periods=24, freq="h", tz="UTC")
    recent = X.iloc[-24 * 14 :]
    pred_recent = predict_ensemble(models, recent)
    rows = []
    for ts in future:
        mask = recent.index.hour == ts.hour
        yhat = float(np.mean(pred_recent[mask])) if mask.any() else float(pred_recent[-1])
        rows.append({
            "timestamp_utc": ts,
            "yhat_eur_mwh": round(yhat, 2),
            "run_time_utc": now,
            "basis_last_data_utc": last,
        })
    return pd.DataFrame(rows)


def plot_forecast(forecast: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(forecast["timestamp_utc"], forecast["yhat_eur_mwh"], marker="o", lw=1.5, color="#245B7A")
    ax.set_title("Day-ahead price forecast (EUR/MWh) with bias correction")
    ax.set_ylabel("EUR/MWh")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def score_past(price_csv: Path) -> pd.DataFrame:
    p = pd.read_csv(price_csv)
    p["ts"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    price = p.set_index("ts")["price_eur_mwh"].astype(float)
    rows = []
    last_detail = last_mae = last_name = None
    for fpath in sorted(OUT_DIR.glob("forecast_*.csv")):
        fc = pd.read_csv(fpath)
        if "yhat_eur_mwh" not in fc.columns:
            continue
        fc["timestamp_utc"] = pd.to_datetime(fc["timestamp_utc"], utc=True)
        fc = fc.set_index("timestamp_utc")
        common = fc.index.intersection(price.index)
        if len(common) == 0:
            continue
        y = price.loc[common]
        pred = fc.loc[common, "yhat_eur_mwh"]
        mae = float(np.mean(np.abs(y - pred)))
        rmse = float(np.sqrt(np.mean((y - pred) ** 2)))
        rows.append({
            "forecast_file": fpath.name,
            "n_hours_scored": int(len(common)),
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
        })
        detail = pd.DataFrame({"actual": y, "forecast": pred}).sort_index()
        last_detail, last_mae, last_name = detail, mae, fpath.name
    if last_detail is not None:
        fig, ax = plt.subplots(figsize=(11, 4))
        ax.plot(last_detail.index, last_detail["actual"], label="Actual", color="#17324D")
        ax.plot(last_detail.index, last_detail["forecast"], label="Forecast", color="#C45C26")
        ax.set_title(f"Forecast vs actual - {last_name} (MAE={last_mae:.1f})")
        ax.set_ylabel("EUR/MWh")
        ax.legend(frameon=False)
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(FIG_DIR / "latest_vs_actual.png", dpi=140, bbox_inches="tight")
        plt.close(fig)
    return pd.DataFrame(rows)


def forecast_table_md(forecast: pd.DataFrame) -> str:
    lines = ["| Hour (UTC) | Forecast (EUR/MWh) | Bias |",
             "|------------|--------------------|------|"]
    for _, r in forecast.iterrows():
        h = pd.to_datetime(r["timestamp_utc"], utc=True).strftime("%Y-%m-%d %H:%M")
        bias = r["bias_applied"] if "bias_applied" in forecast.columns else 0.0
        lines.append(f"| {h} | {r['yhat_eur_mwh']:.2f} | {bias:.2f} |")
    return "\n".join(lines)


def score_table_md(score: pd.DataFrame) -> str:
    if score.empty:
        return "_No overlapping actual prices yet for previous forecasts._"
    lines = ["| Forecast file | Hours scored | MAE | RMSE |",
             "|---------------|--------------|-----|------|"]
    for _, r in score.iterrows():
        lines.append(
            f"| `{r['forecast_file']}` | {r['n_hours_scored']} | {r['mae']:.2f} | {r['rmse']:.2f} |"
        )
    return "\n".join(lines)


def update_readme(forecast: pd.DataFrame, score: pd.DataFrame, now: pd.Timestamp) -> None:
    if not README.exists():
        return
    basis = pd.to_datetime(forecast["basis_last_data_utc"].iloc[0], utc=True)
    f0 = pd.to_datetime(forecast["timestamp_utc"].min(), utc=True)
    f1 = pd.to_datetime(forecast["timestamp_utc"].max(), utc=True)
    block = f"""## Live daily forecast

**Generated (UTC):** {now.strftime('%Y-%m-%d %H:%M')}  
**Based on data up to (UTC):** {basis.strftime('%Y-%m-%d %H:%M')}  
**Forecast horizon (UTC):** {f0.strftime('%Y-%m-%d %H:%M')} to {f1.strftime('%Y-%m-%d %H:%M')}  
**Protocol:** Conservative (external_shift = 24) + hourly bias correction

### Forecast chart

![Daily forecast](outputs/figures/latest_forecast.png)

### Forecast table (EUR/MWh)

{forecast_table_md(forecast)}

### Previous forecasts vs realized prices

{score_table_md(score)}

![Forecast vs actual](outputs/figures/latest_vs_actual.png)

_If the vs-actual chart is missing, there is not yet enough overlap with realized prices._"""
    text = README.read_text(encoding="utf-8")
    if MARKER_START in text and MARKER_END in text:
        pre = text.split(MARKER_START)[0]
        post = text.split(MARKER_END)[-1]
        text = pre + MARKER_START + "\n\n" + block + "\n\n" + MARKER_END + post
    else:
        text = text.rstrip() + "\n\n" + MARKER_START + "\n\n" + block + "\n\n" + MARKER_END + "\n"
    README.write_text(text, encoding="utf-8")
    print("README.md updated")


def main() -> None:
    now = pd.Timestamp.now(tz="UTC")
    print("START daily forecast", now)
    update_data()
    df = load_frame()
    print(f"Joined rows={len(df)} last={df.index.max()}")

    forecast = make_forecast(df, now)

    # Bias correction (only past errors)
    price_s = df["price_eur_mwh"]
    errors = collect_errors(price_s)
    bias = hourly_bias(errors, min_obs=2, last_n_days=14)
    forecast = apply_bias_correction(forecast, bias)
    print("Bias hours available:", list(bias.index) if len(bias) else "none yet")

    out_csv = OUT_DIR / f"forecast_{now.strftime('%Y-%m-%d')}.csv"
    forecast.to_csv(out_csv, index=False)
    print(forecast[["timestamp_utc", "yhat_eur_mwh"]].to_string(index=False))
    print("Saved ->", out_csv)

    plot_forecast(forecast, FIG_DIR / "latest_forecast.png")
    print("Saved ->", FIG_DIR / "latest_forecast.png")

    score = score_past(PRICE)
    if not score.empty:
        score.to_csv(OUT_DIR / "score_summary.csv", index=False)
        print(score.to_string(index=False))
    else:
        print("No scored forecasts yet")

    update_readme(forecast, score, now)
    print("DONE")


if __name__ == "__main__":
    main()