"""
Fetches current/near-term weather for a lat/lon from Open-Meteo (free,
no API key) and converts it into the exact feature units the flood-risk
model was trained on:

    Rainfall             mm, trailing 30-day TOTAL (monthly-equivalent;
                          matches training data's monthly total, verified
                          against the dataset's actual scale -- NOT cm,
                          and NOT instantaneous current rain)
    Wind_Speed           m/s     (request windspeed_unit=ms)
    Cloud_Coverage       okta 0-8 (Open-Meteo gives % -> /12.5)
    Bright_Sunshine      hours   (Open-Meteo gives seconds -> /3600)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_current_features(latitude: float, longitude: float) -> dict[str, Any]:
    """
    Returns a dict of raw weather features for `latitude`/`longitude`,
    in the same units used during training. Includes a 90-day lookback
    so we can compute a trailing rainfall average (a proxy for soil
    saturation / antecedent moisture).
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,sunshine_duration",
        "past_days": 90,
        "forecast_days": 1,
        "timezone": "Asia/Dhaka",
        "windspeed_unit": "ms",
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    current = data.get("current", {})
    daily = data.get("daily", {})

    def clean(series: list) -> list:
        """Open-Meteo can return null for days whose data isn't finalized
        yet (often the current day). Drop those instead of crashing."""
        return [v for v in (series or []) if v is not None]

    precip_series = clean(daily.get("precipitation_sum"))  # Open-Meteo: mm/day
    # Trailing 30-day rainfall TOTAL, in mm -- this matches both the scale
    # AND the unit of the training data's "Rainfall" column, which is a
    # MONTHLY total in millimeters (verified against the dataset: mean of
    # 567mm across flood-positive months, up to 2072mm -- clearly mm, not
    # cm as originally assumed). No /10 conversion needed: Open-Meteo's
    # precipitation_sum is already in mm, the same unit as training data.
    last_30 = precip_series[-30:] if len(precip_series) >= 30 else precip_series
    rainfall_30d_total_mm = sum(last_30) if last_30 else 0.0

    # Trailing ~90-day daily rainfall average, scaled to a monthly figure,
    # used as a separate antecedent-moisture / soil-saturation proxy.
    rainfall_3mo_avg_mm = (sum(precip_series) / len(precip_series) * 30) if precip_series else 0.0

    temp_max_series = clean(daily.get("temperature_2m_max"))
    temp_min_series = clean(daily.get("temperature_2m_min"))
    sunshine_series = clean(daily.get("sunshine_duration"))

    sunshine_seconds = sunshine_series[-1] if sunshine_series else 0

    today = date.today()

    return {
        "Max_Temp": temp_max_series[-1] if temp_max_series else (current.get("temperature_2m") or 0),
        "Min_Temp": temp_min_series[-1] if temp_min_series else (current.get("temperature_2m") or 0),
        "Rainfall": rainfall_30d_total_mm,
        "Relative_Humidity": current.get("relative_humidity_2m") or 0,
        "Wind_Speed": current.get("wind_speed_10m") or 0,
        "Cloud_Coverage": (current.get("cloud_cover") or 0) / 12.5,  # % -> okta
        "Bright_Sunshine": sunshine_seconds / 3600,
        "LATITUDE": latitude,
        "LONGITUDE": longitude,
        # ALT is not available from Open-Meteo's basic endpoint; caller
        # should pass the station/location's known altitude if available,
        # else this default is used.
        "ALT": 10,
        "Month_sin": _month_sin(today.month),
        "Month_cos": _month_cos(today.month),
        "Is_Monsoon": int(today.month in (6, 7, 8, 9)),
        "Rainfall_3mo_avg": rainfall_3mo_avg_mm,
        "fetched_at": datetime.utcnow().isoformat(),
    }


def _month_sin(month: int) -> float:
    import math

    return math.sin(2 * math.pi * month / 12)


def _month_cos(month: int) -> float:
    import math

    return math.cos(2 * math.pi * month / 12)
