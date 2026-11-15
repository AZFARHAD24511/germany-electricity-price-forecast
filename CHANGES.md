# Changes (availability-rule fix)

1. features.py   price_info="gate" (default): rolling stats replaced by complete-day context up to D-1;
                 "legacy" keeps the old behaviour for the ablation. Hourly-grid regularisation (holes
                 no longer misalign shift(k)). `weather_shift` option (36 h = strict for observed weather).
                 make_target_features(): live rows built by the same code as training rows.
2. forecast_horizon.py  recursive_forecast -> direct_forecast, horizon defined by delivery date (Berlin),
                 target-day prices masked, pre_gate flag, data_gap_hours, imputed-feature count.
3. bias_correction.py   errors from RAW yhat (old code used already-corrected yhat), min_obs 2->5, shrink 0.5.
4. evaluate.py   SN24/SN168, rMAE, HLN-corrected Diebold-Mariano on daily losses, live scoring with baselines.
5. run_daily_forecast.py  forecast_<delivery date>.csv, score table with baselines, figure shows the LATEST
                 scored day (old code plotted the best day with MAE<80 = cherry-picking), ffill 48 h -> 6 h.
6. scripts/run_ablation.py, tests/test_leakage.py (8 tests).
