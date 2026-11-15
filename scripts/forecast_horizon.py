"""Direct 24-hour day-ahead forecast for one delivery day (gate-closure protocol).

Why direct and not recursive
----------------------------
Every price feature is either a lag >= 24 h or a statistic of complete days up
to D-1, so *all* inputs for the 24 delivery hours are real observations. There
is nothing to feed back, hence no error accumulation and no train/inference
mismatch. Training rows and live rows are produced by the same code path.
"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electricity_forecast.features import (  # noqa: E402
    LOCAL_TZ,
    delivery_day_utc_index,
    gate_closure_utc,
    make_features,
    make_target_features,
    regularize_hourly,
)
from electricity_forecast.train import fit_ensemble, predict_ensemble  # noqa: E402


def default_target_date(now: pd.Timestamp) -> pd.Timestamp:
    """Tomorrow in Europe/Berlin (the delivery day whose auction closes today 12:00)."""
    local_today = now.tz_convert(LOCAL_TZ).tz_localize(None).normalize()
    return local_today + pd.Timedelta(days=1)


def direct_forecast(
    df: pd.DataFrame,
    now: pd.Timestamp,
    target_date: str | pd.Timestamp | None = None,
    external_shift: int = 24,
    weather_shift: int | None = None,
    hgb_weight: float = 0.65,
) -> pd.DataFrame:
    target = pd.Timestamp(target_date) if target_date is not None else default_target_date(now)
    tgt_idx = delivery_day_utc_index(target)

    # Hard rule: the model never sees anything from the delivery day itself.
    hist = regularize_hourly(df.loc[df.index < tgt_idx[0]])
    X, y = make_features(hist, external_shift=external_shift, weather_shift=weather_shift)
    if len(X) < 500:
        raise RuntimeError(f"Not enough training rows after features: {len(X)}")

    models = fit_ensemble(X, y, hgb_weight=hgb_weight)
    Xt = make_target_features(
        hist, target, external_shift=external_shift, weather_shift=weather_shift,
        feature_cols=list(X.columns),
    )
    n_missing = int(Xt.isna().any(axis=1).sum())
    yhat = predict_ensemble(models, Xt)

    last_price = hist["price_eur_mwh"].dropna().index.max()
    gate = gate_closure_utc(target)
    out = pd.DataFrame(
        {
            "timestamp_utc": tgt_idx,
            "yhat_eur_mwh": np.round(yhat, 2),
            "run_time_utc": now,
            "basis_last_data_utc": last_price,
            "target_date": target.strftime("%Y-%m-%d"),
            "gate_closure_utc": gate,
            "pre_gate": bool(now <= gate),
            "rows_with_imputed_features": n_missing,
            "data_gap_hours": float((tgt_idx[0] - last_price) / pd.Timedelta(hours=1)),
        }
    )
    return out
