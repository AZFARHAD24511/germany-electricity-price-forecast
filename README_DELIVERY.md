# Delivery: leakage-fixed pipeline + real data starter

## What this package is
- Code reviewed/fixed for gate-closure availability (D-1 complete days, direct 24h forecast, raw bias, no cherry-picked chart).
- `data/raw/` contains **real** SMARD/Open-Meteo pulls (approx. 2026-09-16 → 2026-11-15), enough for a smoke test.
- For full history (2019/2022 → now) **replace** the three CSVs with your Windows copies from:
  `D:\projects\germany-electricity-price-forecast\data\raw\`

## Repo
https://github.com/AZFARHAD24511/germany-electricity-price-forecast

## Quick start
```bash
pip install -r requirements.txt
pip install -e .
# optional: refresh data
python scripts/update_data.py
python scripts/run_daily_forecast.py
```

## Main fixes (see CHANGES.md)
1. Features only from complete days through D-1 (`price_info="gate"`).
2. `direct_forecast` by Berlin delivery date; target-day prices masked; `pre_gate` flag.
3. Bias from **raw** yhat; stronger min_obs + shrink.
4. Score table: SN24, SN168, rMAE; figure = latest scored day.
5. `run_ablation.py` + `tests/test_leakage.py`.

## Important
Numbers on short samples are preliminary. After copying full CSVs, re-run daily scoring before any public claim.
