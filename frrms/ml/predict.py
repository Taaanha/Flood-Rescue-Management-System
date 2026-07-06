"""
Loads the trained flood-risk model once at import time and exposes
predict_risk(), which turns raw weather features into a
(probability, severity) pair using FRRMS's existing Alert severity scale
(low / moderate / high / critical).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib

ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "flood_risk_model.joblib"

# Tune these against your validation set / local knowledge before the demo.
# They intentionally err toward flagging risk early (recall over precision)
# since a missed flood alert is worse than a false alarm in this domain.
SEVERITY_THRESHOLDS = [
    (0.85, "critical"),
    (0.60, "high"),
    (0.30, "moderate"),
    (0.0, "low"),
]


@lru_cache(maxsize=1)
def _load_bundle() -> dict[str, Any]:
    return joblib.load(ARTIFACT_PATH)


def predict_risk(features: dict[str, float]) -> dict[str, Any]:
    bundle = _load_bundle()
    model = bundle["model"]
    columns = bundle["feature_columns"]

    row = [[(features.get(col) if features.get(col) is not None else 0) for col in columns]]
    probability = float(model.predict_proba(row)[0][1])

    severity = next(label for threshold, label in SEVERITY_THRESHOLDS if probability >= threshold)

    return {
        "probability": round(probability, 4),
        "severity": severity,
        "model_name": bundle.get("model_name", "unknown"),
    }
