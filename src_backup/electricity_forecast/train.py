"""Model training: HistGradientBoosting + Ridge ensemble."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def build_hgb(**kwargs: Any) -> Pipeline:
    params = dict(
        max_iter=200,
        max_depth=6,
        learning_rate=0.06,
        min_samples_leaf=25,
        random_state=42,
    )
    params.update(kwargs)
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(**params)),
        ]
    )


def build_ridge(alpha: float = 5.0) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=alpha)),
        ]
    )


def fit_ensemble(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    hgb_weight: float = 0.65,
) -> dict:
    """Fit HGB + Ridge and return a dict with both models and the weight."""
    hgb = build_hgb()
    ridge = build_ridge()
    hgb.fit(X_train, y_train)
    ridge.fit(X_train, y_train)
    return {"hgb": hgb, "ridge": ridge, "hgb_weight": hgb_weight}


def predict_ensemble(models: dict, X: pd.DataFrame) -> np.ndarray:
    w = models["hgb_weight"]
    ph = models["hgb"].predict(X)
    pr = models["ridge"].predict(X)
    return w * ph + (1.0 - w) * pr
