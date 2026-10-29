import pandas as pd
import numpy as np
from electricity_forecast.features import make_features

def test_make_features_shapes():
    idx = pd.date_range("2024-01-01", periods=500, freq="h", tz="UTC")
    df = pd.DataFrame({
        "price_eur_mwh": np.random.randn(500).cumsum() + 50,
        "forecast_wind_solar_combined": np.random.rand(500) * 10000,
        "forecast_wind_offshore": np.random.rand(500) * 3000,
        "forecast_wind_onshore": np.random.rand(500) * 7000,
        "forecast_solar": np.random.rand(500) * 5000,
        "avg_wind": np.random.rand(500) * 10,
        "avg_temp": np.random.rand(500) * 20,
        "avg_rad": np.random.rand(500) * 200,
    }, index=idx)
    X, y = make_features(df, external_shift=24)
    assert len(X) == len(y)
    assert X.shape[0] > 100
    assert "lag_24" in X.columns
    assert "forecast_solar" in X.columns
