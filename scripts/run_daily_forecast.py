#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from bias_correction import collect_errors, hourly_bias, apply_bias_correction
from forecast_horizon import direct_forecast
from electricity_forecast.evaluate import score_forecast_frame
from electricity_forecast.features import delivery_day_utc_index

RAW = ROOT / "data" / "raw"
OUT_DIR = ROOT / "outputs" / "forecasts"
FIG_DIR = ROOT / "outputs" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

PRICE = RAW / "germany_electricity_hourly.csv"
SMARD = RAW / "germany_smard_day_ahead_forecasts.csv"
WEATHER = RAW / "germany_weather_forecast_archive.csv"
LOAD = RAW / "germany_load_forecast.csv"
README = ROOT / "README.md"
MARKER_START = "<!-- DAILY_FORECAST_START -->"
MARKER_END = "<!-- DAILY_FORECAST_END -->"


def rotate_x_labels(ax) -> None:
    for label in ax.get_xticklabels():
        label.set_rotation(90)
        label.set_ha("center")
        label.set_fontsize(8)
    ax.tick_params(axis="x", which="major", pad=2)


def update_data() -> None:
    script = ROOT / "scripts" / "update_data.py"
    print("Running update_data.py ...")
    subprocess.run([sys.executable, str(script)], check=False)


def print_data_ranges() -> None:
    print("\n--- DATA RANGES AFTER UPDATE ---")
    for label, path in [("price", PRICE), ("smard", SMARD), ("weather", WEATHER), ("load", LOAD)]:
        if not path.exists():
            print(label, "MISSING")
            continue
        d = pd.read_csv(path, usecols=["timestamp_utc"])
        t = pd.to_datetime(d["timestamp_utc"], utc=True)
        print(f"{label}: rows={len(d):,}  {t.min()} -> {t.max()}")
    print("--- END DATA RANGES ---\n")


def load_frame() -> pd.DataFrame:
    p = pd.read_csv(PRICE)
    p["ts"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    price = p.set_index("ts").sort_index()[["price_eur_mwh"]].astype(float)

    sm = pd.read_csv(SMARD)
    sm["ts"] = pd.to_datetime(sm["timestamp_utc"], utc=True)
    sm = sm.set_index("ts").sort_index()
    sm_cols = [
        c
        for c in [
            "forecast_wind_solar_combined",
            "forecast_wind_offshore",
            "forecast_wind_onshore",
            "forecast_solar",
        ]
        if c in sm.columns
    ]
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

    if LOAD.exists():
        ld = pd.read_csv(LOAD)
        ld["ts"] = pd.to_datetime(ld["timestamp_utc"], utc=True)
        load = ld.set_index("ts").sort_index()[["load_forecast_mw"]].astype(float)
    else:
        load = pd.DataFrame(columns=["load_forecast_mw"])

    df = price.join(sm, how="left").join(weather, how="left").join(load, how="left")
    df = df.ffill(limit=6)
    return df.dropna(subset=["price_eur_mwh"])


def plot_forecast(forecast: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(
        pd.to_datetime(forecast["timestamp_utc"], utc=True),
        forecast["yhat_eur_mwh"],
        marker="o",
        lw=1.5,
        color="#245B7A",
    )
    ax.set_title("Day-ahead price forecast (EUR/MWh) — direct 24h, gate-closure protocol")
    ax.set_ylabel("EUR/MWh")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    rotate_x_labels(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def score_past(price_csv: Path) -> pd.DataFrame:
    p = pd.read_csv(price_csv)
    p["ts"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    price = p.set_index("ts")["price_eur_mwh"].astype(float)
    rows = []
    latest = None

    for fpath in sorted(OUT_DIR.glob("forecast_*.csv")):
        fc = pd.read_csv(fpath)
        if "yhat_eur_mwh" not in fc.columns:
            continue
        r = score_forecast_frame(fc, price)
        if r is None:
            continue
        r["forecast_file"] = fpath.name
        rows.append(r)
        if r["complete_day"]:
            fc["timestamp_utc"] = pd.to_datetime(fc["timestamp_utc"], utc=True)
            fc = fc.set_index("timestamp_utc")
            common = fc.index.intersection(price.index)
            latest = (
                fpath.name,
                r["mae"],
                pd.DataFrame(
                    {
                        "actual": price.loc[common],
                        "forecast": fc.loc[common, "yhat_eur_mwh"],
                    }
                ).sort_index(),
            )

    if latest is not None:
        name, m, detail = latest
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(detail.index, detail["actual"], label="Actual", color="#17324D")
        ax.plot(detail.index, detail["forecast"], label="Forecast", color="#C45C26")
        ax.set_title(f"Latest scored day - {name} (MAE={m:.1f})")
        ax.set_ylabel("EUR/MWh")
        ax.legend(frameon=False)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        rotate_x_labels(ax)
        fig.tight_layout()
        fig.savefig(FIG_DIR / "latest_vs_actual.png", dpi=140, bbox_inches="tight")
        plt.close(fig)

    cols = [
        "forecast_file",
        "n_hours_scored",
        "complete_day",
        "pre_gate",
        "delivery_start_utc",
        "mae",
        "rmse",
        "mae_sn24",
        "mae_sn168",
        "rmae_sn24",
        "rmae_sn168",
    ]
    if rows and any("mae_raw" in r for r in rows):
        cols.insert(6, "mae_raw")
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).reindex(columns=cols)
    out["pre_gate_ok"] = out["pre_gate"].map(lambda v: v is True or v == True)  # noqa: E712
    out = out.sort_values(["delivery_start_utc", "pre_gate_ok", "forecast_file"])
    out["duplicate_delivery"] = out.duplicated("delivery_start_utc", keep="last")
    out["counted"] = out["complete_day"] & out["pre_gate_ok"] & ~out["duplicate_delivery"]
    return out.sort_values("forecast_file").reset_index(drop=True)


def forecast_table_md(forecast: pd.DataFrame) -> str:
    lines = [
        "| Hour (UTC) | Forecast (EUR/MWh) | Bias |",
        "|------------|--------------------|------|",
    ]
    for _, r in forecast.iterrows():
        h = pd.to_datetime(r["timestamp_utc"], utc=True).strftime("%Y-%m-%d %H:%M")
        bias = r["bias_applied"] if "bias_applied" in forecast.columns else 0.0
        lines.append(f"| {h} | {r['yhat_eur_mwh']:.2f} | {bias:.2f} |")
    return "\n".join(lines)


def score_table_md(score: pd.DataFrame) -> str:
    if score.empty:
        return "_No overlapping actual prices yet for previous forecasts._"

    def why(r) -> str:
        if r["counted"]:
            return "yes"
        if not r["complete_day"]:
            return "no: incomplete"
        if r["duplicate_delivery"]:
            return "no: same day as another file"
        if not r["pre_gate_ok"]:
            return "no: not pre-gate"
        return "no"

    lines = [
        "| Forecast file | Hours | MAE | SN24 | SN168 | rMAE vs SN24 | rMAE vs SN168 | Pre-gate | Counted |",
        "|---------------|-------|-----|------|-------|--------------|---------------|----------|---------|",
    ]
    for _, r in score.sort_values("forecast_file").iterrows():
        lines.append(
            f"| `{r['forecast_file']}` | {r['n_hours_scored']} | {r['mae']:.2f} | {r['mae_sn24']:.2f} | "
            f"{r['mae_sn168']:.2f} | {r['rmae_sn24']:.2f} | {r['rmae_sn168']:.2f} | {r['pre_gate']} | {why(r)} |"
        )
    ok = score[score["counted"]]
    lines.append("")
    if len(ok) == 0:
        lines.append(
            "**Valid scored days (complete, pre-gate, unique delivery day): 0 - no performance claim possible yet.**"
        )
    else:
        best = ok[["mae_sn24", "mae_sn168"]].min(axis=1)
        lines += [
            f"**Valid scored days: {len(ok)} | mean MAE model {ok['mae'].mean():.2f} | SN24 {ok['mae_sn24'].mean():.2f} | "
            f"SN168 {ok['mae_sn168'].mean():.2f} | best-of-baselines {best.mean():.2f}**",
            "",
            f"**Days model beats SN24: {(ok['mae'] < ok['mae_sn24']).sum()}/{len(ok)} | "
            f"beats the better of SN24/SN168: {(ok['mae'] < best).sum()}/{len(ok)}**",
        ]
    lines += [
        "",
        "_Only rows marked 'Counted = yes' enter the summary. Files from the old code (Pre-gate nan), "
        "post-gate runs and duplicate delivery days are shown for transparency but not counted. "
        "No statistical claim until >= 60 valid days._",
    ]
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
**Protocol:** gate-closure features (lags >= 24 h, complete-day context) + external_shift = 24 + ENTSO-E load (no shift) + direct 24h + shrunk hourly bias correction

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-date", default=None, help="Delivery date YYYY-MM-DD (default: tomorrow, Europe/Berlin)")
    ap.add_argument("--no-update", action="store_true", help="Skip data download")
    args = ap.parse_args()

    now = pd.Timestamp.now(tz="UTC")
    print("START daily forecast", now)
    if not args.no_update:
        update_data()
    print_data_ranges()

    df = load_frame()
    print(f"Joined rows={len(df)} last={df.index.max()}")
    if "load_forecast_mw" in df.columns:
        n_load = int(df["load_forecast_mw"].notna().sum())
        print(f"load_forecast_mw non-null: {n_load}")

    forecast = direct_forecast(df, now, target_date=args.target_date, external_shift=24)
    tgt = forecast["target_date"].iloc[0]
    print(
        "Target delivery day:",
        tgt,
        "| pre_gate:",
        bool(forecast["pre_gate"].iloc[0]),
        "| data_gap_hours:",
        forecast["data_gap_hours"].iloc[0],
        "| rows with imputed features:",
        forecast["rows_with_imputed_features"].iloc[0],
    )
    if forecast["data_gap_hours"].iloc[0] > 48:
        print("WARNING: price history ends >48 h before the delivery day; forecast quality is not comparable.")

    price_s = df["price_eur_mwh"]
    errors = collect_errors(price_s, before=delivery_day_utc_index(tgt)[0])
    bias = hourly_bias(errors, min_obs=5, last_n_days=14)
    forecast = apply_bias_correction(forecast, bias)
    print("Bias hours available:", list(bias.index) if len(bias) else "none yet")

    out_csv = OUT_DIR / f"forecast_{tgt}.csv"
    if out_csv.exists() and not bool(forecast["pre_gate"].iloc[0]):
        old = pd.read_csv(out_csv, usecols=lambda c: c == "pre_gate")
        if "pre_gate" in old.columns and bool(old["pre_gate"].iloc[0]):
            print("Existing PRE-GATE forecast kept; this late run is not saved over it.")
            out_csv = OUT_DIR / f"late_forecast_{tgt}.csv"
    forecast.to_csv(out_csv, index=False)
    print(forecast[["timestamp_utc", "yhat_eur_mwh"]].to_string(index=False))
    print("Saved ->", out_csv)

    plot_forecast(forecast, FIG_DIR / "latest_forecast.png")

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
