"""Availability tests: nothing from delivery day D may influence features of D."""

import numpy as np
import pandas as pd
import pytest

from electricity_forecast.evaluate import dm_test
from electricity_forecast.features import (
    LOCAL_TZ, _build, delivery_day_utc_index, gate_closure_utc,
    local_dates, make_features, make_target_features, regularize_hourly,
)


def _frame(n_days=60, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=24 * n_days, freq="h", tz="UTC")
    h = idx.hour.values
    price = 60 + 25 * np.sin(2 * np.pi * (h - 7) / 24) + rng.normal(0, 8, len(idx)).cumsum() * 0.05
    return pd.DataFrame(
        {
            "price_eur_mwh": price,
            "forecast_wind_solar_combined": rng.random(len(idx)) * 1e4,
            "forecast_solar": rng.random(len(idx)) * 5e3,
            "avg_wind": rng.random(len(idx)) * 10,
            "avg_temp": rng.random(len(idx)) * 20,
            "avg_rad": rng.random(len(idx)) * 200,
        },
        index=idx,
    )


def _perturb_from(df, start_utc):
    d2 = df.copy()
    m = d2.index >= start_utc
    d2.loc[m, "price_eur_mwh"] = d2.loc[m, "price_eur_mwh"] + 500.0
    return d2


def test_gate_features_ignore_delivery_day_prices():
    df = _frame()
    day = pd.Timestamp("2025-02-10")
    idx = delivery_day_utc_index(day)
    a = _build(df, 24, "price_eur_mwh", "gate", None).loc[idx]
    b = _build(_perturb_from(df, idx[0]), 24, "price_eur_mwh", "gate", None).loc[idx]
    pd.testing.assert_frame_equal(a, b)


def test_legacy_features_do_leak_delivery_day_prices():
    """Documents the original bug: rolling stats of hour h>0 see price(ts-1)."""
    df = _frame()
    idx = delivery_day_utc_index(pd.Timestamp("2025-02-10"))
    a = _build(df, 24, "price_eur_mwh", "legacy", None).loc[idx]
    b = _build(_perturb_from(df, idx[0]), 24, "price_eur_mwh", "legacy", None).loc[idx]
    assert not a["roll_mean_24"].equals(b["roll_mean_24"])


def test_target_features_independent_of_target_day_prices_in_file():
    df = _frame()
    day = pd.Timestamp("2025-02-10")
    idx = delivery_day_utc_index(day)
    a = make_target_features(df, day)
    b = make_target_features(_perturb_from(df, idx[0]), day)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 24
    assert a.index[0] == idx[0]


def test_target_features_match_training_features():
    """Live path and training path must produce identical rows for the same day."""
    df = _frame()
    day = pd.Timestamp("2025-02-10")
    idx = delivery_day_utc_index(day)
    X, _ = make_features(df)
    live = make_target_features(df, day, feature_cols=list(X.columns))
    pd.testing.assert_frame_equal(X.loc[idx], live[X.columns], check_dtype=False)


def test_dst_days_have_23_and_25_hours():
    assert len(delivery_day_utc_index("2025-03-30")) == 23
    assert len(delivery_day_utc_index("2025-10-26")) == 25
    assert len(delivery_day_utc_index("2025-06-10")) == 24


def test_gate_closure_is_noon_berlin_previous_day():
    g = gate_closure_utc("2025-06-11")  # CEST: 12:00 local = 10:00 UTC
    assert g == pd.Timestamp("2025-06-10 10:00", tz="UTC")
    g = gate_closure_utc("2025-01-11")  # CET: 12:00 local = 11:00 UTC
    assert g == pd.Timestamp("2025-01-10 11:00", tz="UTC")


def test_holes_do_not_misalign_lags():
    df = _frame().drop(index=pd.date_range("2025-01-20", periods=5, freq="h", tz="UTC"))
    X, y = make_features(df)
    full = regularize_hourly(df)["price_eur_mwh"]
    ts = X.index[100]
    assert X.loc[ts, "lag_24"] == pytest.approx(full.loc[ts - pd.Timedelta(hours=24)])


def test_dm_detects_clearly_better_model():
    rng = np.random.default_rng(1)
    bench = rng.normal(0, 20, 120)
    model = rng.normal(0, 8, 120)
    r = dm_test(model, bench)
    assert r["p_model_better"] < 0.01
    r2 = dm_test(bench, model)
    assert r2["p_model_better"] > 0.99
