"""Plotting helpers for reports and README figures."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

sns.set_theme(style="whitegrid", context="talk")


def plot_price_overview(
    price: pd.Series,
    out_path: Path | str,
    title: str = "German Day-Ahead Electricity Price (EUR/MWh)",
) -> None:
    fig, ax = plt.subplots(figsize=(12, 4))
    price.plot(ax=ax, lw=0.6, color="#245B7A")
    ax.set_title(title)
    ax.set_ylabel("EUR/MWh")
    ax.set_xlabel("")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_backtest_mae(
    summary: pd.DataFrame,
    out_path: Path | str,
    title: str = "Backtest MAE by Window (Conservative Protocol)",
) -> None:
    """Bar chart comparing SN24 / HGB / Ridge / Ensemble MAE."""
    metrics = ["mae_sn24", "mae_hgb", "mae_ridge", "mae_ens"]
    labels = ["Seasonal Naive 24h", "HistGradientBoosting", "Ridge", "Ensemble"]
    x = np.arange(len(summary))
    width = 0.2

    fig, ax = plt.subplots(figsize=(10, 5))
    for i, (m, lab) in enumerate(zip(metrics, labels)):
        ax.bar(x + i * width, summary[m], width, label=lab)

    ax.set_xticks(x + 1.5 * width)
    ax.set_xticklabels([f"W{w}" for w in summary["window"]])
    ax.set_ylabel("MAE (EUR/MWh)")
    ax.set_title(title)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_prediction_vs_actual(
    y_true: pd.Series,
    y_pred: pd.Series,
    out_path: Path | str,
    title: str = "Predicted vs Actual Price",
    max_points: int = 500,
) -> None:
    if len(y_true) > max_points:
        idx = y_true.index[:: max(1, len(y_true) // max_points)]
        y_true = y_true.loc[idx]
        y_pred = y_pred.loc[idx]

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(y_true.index, y_true.values, label="Actual", lw=1.0, color="#17324D")
    ax.plot(y_pred.index, y_pred.values, label="Ensemble", lw=1.0, color="#C45C26", alpha=0.85)
    ax.set_title(title)
    ax.set_ylabel("EUR/MWh")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
