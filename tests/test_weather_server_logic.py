import types
import pytest
import requests

from server.weather_server import fetch_weather_from_openweather


def test_missing_api_key(monkeypatch):
    """Missing OPENWEATHER_API_KEY → RuntimeError."""
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc:
        fetch_weather_from_openweather("Bucharest")
    assert "OPENWEATHER_API_KEY" in str(exc.value)


def test_city_not_found_404(monkeypatch):
    """404 from OpenWeather → ValueError('City not found')."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")

    fake_response = types.SimpleNamespace(status_code=404, text="city not found")

    def fake_get(*args, **kwargs):
        return fake_response

    import server.weather_server as ws
    monkeypatch.setattr(ws.requests, "get", fake_get)

    with pytest.raises(ValueError) as exc:
        fetch_weather_from_openweather("NoSuchCity")
    assert "City not found" in str(exc.value)


def test_other_status_code_raises_runtime_error(monkeypatch):
    """Non-200/404 → RuntimeError with status and body."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")

    fake_response = types.SimpleNamespace(status_code=500, text="internal server error")

    def fake_get(*args, **kwargs):
        return fake_response

    import server.weather_server as ws
    monkeypatch.setattr(ws.requests, "get", fake_get)

    with pytest.raises(RuntimeError) as exc:
        fetch_weather_from_openweather("Bucharest")
    assert "OpenWeatherMap API error" in str(exc.value)


def test_requests_exception_wrapped_in_runtime_error(monkeypatch):
    """requests.RequestException → RuntimeError."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")

    def fake_get(*args, **kwargs):
        raise requests.RequestException("network down")

    import server.weather_server as ws
    monkeypatch.setattr(ws.requests, "get", fake_get)

    with pytest.raises(RuntimeError) as exc:
        fetch_weather_from_openweather("Bucharest")
    assert "Error calling OpenWeatherMap" in str(exc.value)