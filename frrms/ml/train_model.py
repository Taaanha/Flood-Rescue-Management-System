"""
Trains the FRRMS flood-risk classifier.

Data: Gauhar et al. Bangladesh flood dataset (BMD weather + BWDB flood
reports, 33 stations, 1948-2013). See station_district_map.py for the
station -> district mapping used to attach predictions to FRRMS locations.

Run:
    python -m frrms.ml.train_model

Produces:
    frrms/ml/artifacts/flood_risk_model.joblib
    frrms/ml/artifacts/metrics.json
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    confusion_matrix,
)
from xgboost import XGBClassifier

from .station_district_map import STATION_TO_DISTRICT

HERE = Path(__file__).resolve().parent
ARTIFACT_DIR = HERE / "artifacts"
DATA_PATH = HERE / "data" / "FloodPrediction.csv"

FEATURE_COLUMNS = [
    "Max_Temp",
    "Min_Temp",
    "Rainfall",
    "Relative_Humidity",
    "Wind_Speed",
    "Cloud_Coverage",
    "Bright_Sunshine",
    "LATITUDE",
    "LONGITUDE",
    "ALT",
    "Month_sin",
    "Month_cos",
    "Is_Monsoon",
    "Rainfall_3mo_avg",
]


def load_and_engineer() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    df = df.rename(columns={"Flood?": "Flood"})

    # Missing label => not a recorded flood event (documented assumption,
    # see README / project report "Limitations").
    df["Flood"] = df["Flood"].fillna(0).astype(int)

    df["District"] = df["Station_Names"].map(STATION_TO_DISTRICT)
    df = df.dropna(subset=["District"])

    # Cyclical month encoding instead of raw 1-12 integer.
    df["Month_sin"] = np.sin(2 * np.pi * df["Month"] / 12)
    df["Month_cos"] = np.cos(2 * np.pi * df["Month"] / 12)
    df["Is_Monsoon"] = df["Month"].isin([6, 7, 8, 9]).astype(int)

    # 3-month trailing rainfall average per station, a cheap proxy for
    # soil saturation / antecedent moisture (a known real flood driver).
    df = df.sort_values(["Station_Names", "Year", "Month"])
    df["Rainfall_3mo_avg"] = (
        df.groupby("Station_Names")["Rainfall"]
        .transform(lambda s: s.rolling(3, min_periods=1).mean())
    )

    return df.reset_index(drop=True)


def temporal_split(df: pd.DataFrame, cutoff_year: int = 2005):
    train = df[df["Year"] < cutoff_year]
    test = df[df["Year"] >= cutoff_year]
    return train, test


def train_and_evaluate() -> dict:
    df = load_and_engineer()
    train_df, test_df = temporal_split(df)

    X_train, y_train = train_df[FEATURE_COLUMNS], train_df["Flood"]
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df["Flood"]

    candidates = {
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            max_depth=10,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        ),
        "xgboost": XGBClassifier(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            scale_pos_weight=(y_train == 0).sum() / max((y_train == 1).sum(), 1),
            random_state=42,
        ),
    }

    results = {}
    best_name, best_model, best_auc = None, None, -1.0

    for name, model in candidates.items():
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_test)[:, 1]
        preds = (proba >= 0.5).astype(int)

        metrics = {
            "accuracy": accuracy_score(y_test, preds),
            "precision": precision_score(y_test, preds, zero_division=0),
            "recall": recall_score(y_test, preds, zero_division=0),
            "f1": f1_score(y_test, preds, zero_division=0),
            "roc_auc": roc_auc_score(y_test, proba),
            "confusion_matrix": confusion_matrix(y_test, preds).tolist(),
        }
        results[name] = metrics
        print(f"\n=== {name} ===")
        for k, v in metrics.items():
            print(f"  {k}: {v}")

        if metrics["roc_auc"] > best_auc:
            best_name, best_model, best_auc = name, model, metrics["roc_auc"]

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": best_model,
            "model_name": best_name,
            "feature_columns": FEATURE_COLUMNS,
        },
        ARTIFACT_DIR / "flood_risk_model.joblib",
    )
    with open(ARTIFACT_DIR / "metrics.json", "w") as f:
        json.dump({"best_model": best_name, "results": results}, f, indent=2)

    print(f"\nBest model: {best_name} (ROC-AUC={best_auc:.3f}) saved to {ARTIFACT_DIR}")
    return results


if __name__ == "__main__":
    train_and_evaluate()
