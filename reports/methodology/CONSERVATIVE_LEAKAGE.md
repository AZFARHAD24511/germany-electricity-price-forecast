# Methodology Note – Leakage Control & SMARD Data Limitations
**Project:** Day-ahead Electricity Price Forecasting – Germany  
**Date:** 29 October 2026  
**Author:** Azizallah Farhadi  

---

## 1. Official Clarification from SMARD (Bundesnetzagentur)

On 29 October 2026 we received the following response from the official SMARD team:

> “The API you mentioned is a project by an individual or a group. The Federal Network Agency is not involved. Therefore, we unfortunately cannot answer any questions about it.  
> However, we are currently working on providing our own SMARD API…”

**Implications:**

- The endpoint `https://www.smard.de/app/chart_data/...` is **not an official API** of the Bundesnetzagentur.
- The field `meta_data.created` that appears in the JSON responses cannot be interpreted as the original publication / issue time of the day-ahead forecasts.
- Historical forecast files appear to be re-generated or re-served with recent creation timestamps. Consequently, point-in-time reconstruction of true availability is not possible with this source.

---

## 2. Chosen Leakage-Control Strategy: Conservative (24 h lag)

According to the official *SMARD.de User guide* (September 2021), TSOs must transmit day-ahead wind and solar generation forecasts to the ENTSO-E Transparency Platform **no later than 18:00 on the day before** (Art. 14(1)(d) of Regulation (EU) No 543/2013). Forecasted consumption must be submitted no later than two hours before day-ahead gate closure. All times on SMARD are in CET/CEST.

However, the guide only states the legal submission deadline to ENTSO-E. It does **not** document:

- when the data actually appear on SMARD,
- a recoverable historical issue timestamp, or
- a fixed revision schedule (historical series may be updated later).

In addition, the chart-data endpoint used to download the series is **not an official Bundesnetzagentur API**, so fields such as `meta_data.created` cannot be treated as original publication times.

Because the true issue time remains unknown, we adopt a **strictly conservative** protocol:

| Feature group              | Availability rule                                      | Rationale |
|----------------------------|--------------------------------------------------------|-----------|
| Price lags, rolling stats  | Only values up to the end of day D−1                   | Always known |
| Calendar features          | Deterministic                                          | Always known |
| SMARD wind/solar forecasts | Shifted by **+24 hours** (use D−1 forecast for day D)  | Avoids any chance of using information published after the day-ahead auction |
| Weather archive            | Same 24 h shift                                        | Same reason |

This rule guarantees that **no information that could have become available only after the day-ahead market closed** enters the feature set. All primary results in this study refer exclusively to this protocol.

## 3. Reported Performance (Conservative Protocol Only)

Three expanding-window backtests (Jul–Aug, Aug–Sep, Sep–Oct 2026):

| Model                        | MAE (EUR/MWh) | RMSE (EUR/MWh) | Improvement vs Seasonal-Naive 24 h |
|-----------------------------|----------------|----------------|------------------------------------|
| Seasonal Naive (24 h)       | 37.79          | —              | —                                  |
| Ridge (lags + calendar + external shifted) | 28.31     | —              | ≈ 25 %                             |
| HistGradientBoosting        | 26.85          | —              | ≈ 29 %                             |
| **Ensemble (HGB 65 % + Ridge 35 %)** | **26.27** | **35.14**     | **≈ 30 %**                         |

(Optimistic results that ignore the 24 h shift are retained only for sensitivity analysis and are **not** used as primary claims.)

---

## 4. Explicit Statements for the Final Report

The following paragraphs should appear in the methodology / limitations section of the project report:

> The day-ahead wind and solar generation forecasts were obtained from the publicly accessible SMARD chart-data endpoint. According to an official reply from the SMARD team of the Bundesnetzagentur (29 October 2026), this endpoint is **not an official API** maintained by the agency; it is a third-party project. Consequently, the `meta_data.created` timestamps supplied by the endpoint do not represent the original publication time of the forecasts.

> Because the true issue time of these forecasts cannot be reconstructed, a conservative availability assumption was imposed: all external forecast features were lagged by 24 hours. This ensures that only information that would have been known at the close of the previous day’s day-ahead auction is used. All primary performance figures reported in this study refer exclusively to this conservative protocol.

> An official SMARD API is currently under development by the Bundesnetzagentur. Once it becomes available and provides reliable issue-time metadata, the leakage-control procedure can be refined.

---

## 5. Next Steps

1. Lock all subsequent modelling work to the **Conservative** feature set.
2. Proceed with priority 4 – extraction of electricity intensity from FIGARO product-by-product tables and sectoral price-shock simulation.
3. Keep the optimistic numbers only as a sensitivity appendix, clearly labelled as upper-bound performance under perfect availability assumptions.

---

*Document prepared to ensure full transparency and reproducibility of the leakage-control design.*
