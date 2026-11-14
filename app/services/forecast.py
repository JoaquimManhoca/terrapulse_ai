"""Short-term forecast from Open-Meteo (free, no API key).

Open-Meteo supplies the 7-14 day horizon that a satellite observation product
cannot. The service is optional: when the network is unavailable the decision
engine falls back to NASA climatology and historical analogues only.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from ..config import Config

_CACHE_TTL_SECONDS = 15 * 60
_cache: dict[str, Any] = {"fetched_at": 0.0, "payload": None}


def fetch_open_meteo(
    lat: float | None = None,
    lon: float | None = None,
    timeout: float = 4.0,
    use_cache: bool = True,
) -> dict[str, Any] | None:
    now = time.monotonic()
    if use_cache and _cache["payload"] is not None and (now - _cache["fetched_at"]) < _CACHE_TTL_SECONDS:
        return _cache["payload"]

    params = {
        "latitude": Config.MANICA_LAT if lat is None else lat,
        "longitude": Config.MANICA_LON if lon is None else lon,
        "daily": "weather_code,precipitation_sum,precipitation_probability_max",
        "timezone": "Africa/Maputo",
        "past_days": 7,
        "forecast_days": 16,
    }

    try:
        response = requests.get(Config.OPEN_METEO_BASE, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    daily = payload.get("daily", {})
    dates = daily.get("time", [])
    weather_codes = daily.get("weather_code", [])
    rain = daily.get("precipitation_sum", [])
    probability = daily.get("precipitation_probability_max", [])

    rows = []
    for index, day in enumerate(dates):
        weather_code = weather_codes[index] if index < len(weather_codes) else None
        rain_value = rain[index] if index < len(rain) else None
        prob_value = probability[index] if index < len(probability) else None
        rows.append(
            {
                "date": day,
                "weather_code": int(weather_code) if weather_code is not None else None,
                "precip_mm": float(rain_value) if rain_value is not None else None,
                "probability_pct": float(prob_value) if prob_value is not None else None,
            }
        )

    result = {"source": "open-meteo", "rows": rows, "fetched_at": time.time()}
    _cache["fetched_at"] = now
    _cache["payload"] = result
    return result


def clear_cache() -> None:
    _cache["fetched_at"] = 0.0
    _cache["payload"] = None
