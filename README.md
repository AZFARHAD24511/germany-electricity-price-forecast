# Germany Day-Ahead Electricity Price Forecast

Leakage-aware forecasting of German EPEX Spot day-ahead prices (EUR/MWh), with a transparent **Conservative** protocol for external forecasts.

**Author:** Azizallah Farhadi · `farhadmy1974@gmail.com`  
**Status:** Research prototype (Oct 2026)

---

## 1. Motivation

Accurate day-ahead price forecasts support:

- Trading and risk management on the German/Luxembourg bidding zone
- Demand-side flexibility and storage dispatch
- Sectoral impact analysis when electricity prices rise (linked to FIGARO input–output tables in the broader project)

The main modelling risk is **data leakage**: using wind/solar forecasts that were not yet published when the day-ahead auction closed (~12:00 CET on day *D* for delivery on *D+1*).

---

## 2. Data

| Source | Content | Coverage (approx.) |
|--------|---------|---------------------|
| Hourly market data | Day-ahead price, load, residual load, generation by technology | 2020–2026 |
| SMARD chart-data endpoint | Day-ahead wind & solar generation forecasts | 2022–2026 |
| Weather archive | Regional temperature, 100 m wind, shortwave radiation | 2022–2026 |

> **Important limitation (official clarification, 29 Oct 2026)**  
> The SMARD chart-data endpoint (`/app/chart_data/...`) is **not an official API** of the Bundesnetzagentur. It is a third-party project. The `meta_data.created` timestamps therefore **cannot** be treated as the original issue time of the forecasts. An official SMARD API is under development.

Raw files live under `data/raw/` and are **excluded from Git** (see `.gitignore`). Only small samples or processed summaries should be committed.

---

## 3. Leakage-Control Protocol (Conservative)

Because true issue times are unavailable, we enforce a strict rule:

| Feature family | Rule |
|----------------|------|
| Price lags & rolling statistics | Only information up to the end of day *D−1* |
| Calendar / cyclical encodings | Always available |
| SMARD wind/solar + weather | **Shifted by +24 hours** |

All **primary results** in this repository use `external_shift = 24`.  
Optimistic runs (`shift = 0`) are kept only as sensitivity analysis and are clearly labelled.

Full write-up: [`reports/methodology/CONSERVATIVE_LEAKAGE.md`](reports/methodology/CONSERVATIVE_LEAKAGE.md)

---

## 4. Method

1. **Features**  
   - Price lags: 24, 48, 72, 168, 336 h  
   - Rolling mean/std (24 h, 168 h)  
   - Hour / day-of-week / month + sine-cosine encodings  
   - External forecasts lagged by 24 h

2. **Models**  
   - `HistGradientBoostingRegressor` (tree-based)  
   - `Ridge` regression (linear baseline with scaling)  
   - **Ensemble** = 0.65 × HGB + 0.35 × Ridge

3. **Evaluation**  
   Expanding-window backtest on three recent periods (Jul–Aug, Aug–Sep, Sep–Oct 2026).  
   Metrics: MAE and RMSE (EUR/MWh).  
   Reference: seasonal naïve (lag 24 h).

---

## 5. Results (Conservative protocol – locked)

Weighted averages over the three test windows:

| Model | MAE (EUR/MWh) | RMSE (EUR/MWh) | Improvement vs SN24 |
|-------|----------------|----------------|---------------------|
| Seasonal Naive 24 h | 37.79 | — | — |
| Ridge | 28.31 | — | ≈ 25 % |
| HistGradientBoosting | 26.85 | — | ≈ 29 % |
| **Ensemble** | **26.27** | **35.14** | **≈ 30 %** |

Per-window detail is in [`reports/metrics/ensemble_summary.csv`](reports/metrics/ensemble_summary.csv).

### Figures

> Place generated plots under `reports/figures/`. After running the pipeline they appear as:

**Price series overview**

![Price overview](reports/figures/price_overview.png)

**Backtest MAE comparison**

![Backtest MAE](reports/figures/backtest_mae.png)

**Example prediction vs actual (one window)**

![Pred vs actual](reports/figures/pred_vs_actual_w1.png)

*(Run `scripts/run_pipeline.py` to regenerate the figures.)*

---

## 6. Repository Structure

```
germany-electricity-price-forecast/
├── data/
│   ├── raw/                  # large CSVs – not tracked by Git
│   └── processed/
├── models/                   # fitted model artefacts (optional)
├── reports/
│   ├── figures/              # PNG charts for README & paper
│   ├── metrics/              # CSV + JSON summaries
│   └── methodology/          # leakage protocol & SMARD note
├── scripts/
│   └── run_pipeline.py       # end-to-end Conservative run
├── src/
│   └── electricity_forecast/
│       ├── data.py           # load & join
│       ├── features.py       # leakage-aware feature engineering
│       ├── train.py          # HGB + Ridge ensemble
│       ├── evaluate.py       # expanding-window backtest
│       └── visualize.py      # report figures
├── tests/
├── notebooks/                # exploratory work (optional)
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 7. Quick Start

```bash
# clone & install
git clone <your-repo-url>
cd germany-electricity-price-forecast
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .

# place raw CSVs into data/raw/
# then run the Conservative pipeline
python scripts/run_pipeline.py \
  --price   data/raw/germany_electricity_hourly.csv \
  --smard   data/raw/germany_smard_day_ahead_forecasts.csv \
  --weather data/raw/germany_weather_forecast_archive.csv \
  --out     reports \
  --shift   24
```

Tests:

```bash
pytest tests/ -q
```

---

## 8. Analysis Highlights

- **Hardest periods** are those with high renewable penetration and negative or near-zero prices; residual-load and lag features help, but residual error remains elevated (see window 2).
- The 24 h shift costs roughly 4–5 EUR/MWh of MAE relative to an optimistic (and potentially leaking) setting. We accept this cost for methodological integrity.
- Tree models (HGB) capture non-linear interactions between wind/solar forecasts and the residual load better than pure linear Ridge; the ensemble improves further by blending both.
- Because the external forecasts lack a reliable issue time, any future improvement should prioritise a source that publishes true run times (official SMARD API or ENTSO-E with available-at timestamps).

---

## 9. Roadmap

- [x] Leakage-safe baseline & ensemble (Conservative)
- [x] Document SMARD API limitation
- [ ] Sectoral price-shock analysis via FIGARO product-by-product tables
- [ ] Optional LSTM / sequence model branch
- [ ] Switch to official SMARD API once issue-time metadata is available

---

## 10. Citation & Licence

If you use this code or results, please cite the repository and note the Conservative protocol.

Data attribution for SMARD-sourced series: *Bundesnetzagentur | SMARD.de* (even though the chart-data endpoint itself is third-party).

Licence: MIT (code). Underlying market data remain subject to their original licences.

<!-- DAILY_FORECAST_START -->

## Live daily forecast

**Generated (UTC):** 2026-11-12 22:44  
**Based on data up to (UTC):** 2026-11-13 22:00  
**Forecast horizon (UTC):** 2026-11-13 23:00 to 2026-11-14 22:00  
**Protocol:** Conservative (external_shift = 24) + hourly bias correction

### Forecast chart

![Daily forecast](outputs/figures/latest_forecast.png)

### Forecast table (EUR/MWh)

| Hour (UTC) | Forecast (EUR/MWh) | Bias |
|------------|--------------------|------|
| 2026-11-13 23:00 | 223.90 | -1.43 |
| 2026-11-14 00:00 | 225.85 | -7.86 |
| 2026-11-14 01:00 | 220.92 | -5.59 |
| 2026-11-14 02:00 | 217.67 | -4.20 |
| 2026-11-14 03:00 | 220.03 | -4.55 |
| 2026-11-14 04:00 | 224.02 | 3.08 |
| 2026-11-14 05:00 | 257.91 | 3.44 |
| 2026-11-14 06:00 | 301.80 | -5.92 |
| 2026-11-14 07:00 | 309.47 | -10.54 |
| 2026-11-14 08:00 | 286.37 | -8.20 |
| 2026-11-14 09:00 | 259.65 | -6.08 |
| 2026-11-14 10:00 | 244.20 | -4.44 |
| 2026-11-14 11:00 | 237.46 | -2.07 |
| 2026-11-14 12:00 | 239.55 | -1.31 |
| 2026-11-14 13:00 | 252.43 | -1.44 |
| 2026-11-14 14:00 | 281.99 | -3.91 |
| 2026-11-14 15:00 | 318.73 | -5.88 |
| 2026-11-14 16:00 | 331.76 | 0.11 |
| 2026-11-14 17:00 | 317.12 | 7.61 |
| 2026-11-14 18:00 | 306.20 | 7.10 |
| 2026-11-14 19:00 | 270.62 | 10.11 |
| 2026-11-14 20:00 | 240.16 | 13.69 |
| 2026-11-14 21:00 | 231.72 | 5.84 |
| 2026-11-14 22:00 | 212.63 | 6.86 |

### Previous forecasts vs realized prices

| Forecast file | Hours scored | MAE | RMSE |
|---------------|--------------|-----|------|
| `forecast_2026-10-31.csv` | 24 | 67.09 | 70.49 |
| `forecast_2026-11-01.csv` | 24 | 65.43 | 67.68 |
| `forecast_2026-11-02.csv` | 24 | 18.75 | 22.98 |
| `forecast_2026-11-03.csv` | 24 | 16.60 | 22.06 |
| `forecast_2026-11-04.csv` | 24 | 15.31 | 22.30 |
| `forecast_2026-11-05.csv` | 24 | 37.02 | 38.45 |
| `forecast_2026-11-07.csv` | 24 | 16.96 | 25.55 |
| `forecast_2026-11-08.csv` | 24 | 82.04 | 103.07 |
| `forecast_2026-11-10.csv` | 24 | 100.49 | 106.82 |
| `forecast_2026-11-11.csv` | 24 | 119.75 | 124.82 |

![Forecast vs actual](outputs/figures/latest_vs_actual.png)

_If the vs-actual chart is missing, there is not yet enough overlap with realized prices._

<!-- DAILY_FORECAST_END -->
