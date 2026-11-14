from __future__ import annotations

from app.services import forecast
from app.services.decision import _weather_condition


def test_fetch_open_meteo_parses_weather_codes(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "daily": {
                    "time": ["2026-01-01"],
                    "weather_code": [2],
                    "precipitation_sum": [0.0],
                    "precipitation_probability_max": [10],
                }
            }

    def fake_get(url, params, timeout):
        captured.update(params)
        return Response()

    monkeypatch.setattr(forecast.requests, "get", fake_get)
    forecast.clear_cache()
    result = forecast.fetch_open_meteo(use_cache=False)
    forecast.clear_cache()

    assert "weather_code" in captured["daily"]
    assert result["rows"][0]["weather_code"] == 2


def test_weather_condition_uses_rain_probability_threshold():
    assert _weather_condition(
        {"weather_code": 53, "precip_mm": 2.5, "probability_pct": 24}
    ) == "cloudy"
    assert _weather_condition(
        {"weather_code": 53, "precip_mm": 2.5, "probability_pct": 49.9}
    ) == "cloudy"
    assert _weather_condition(
        {"weather_code": 53, "precip_mm": 2.5, "probability_pct": 50}
    ) == "rainy"
    assert _weather_condition(
        {"weather_code": 0, "precip_mm": 0, "probability_pct": 24}
    ) == "sunny"
    assert _weather_condition({"weather_code": 53}) == "rainy"
