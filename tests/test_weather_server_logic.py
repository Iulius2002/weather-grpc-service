import types
import pytest
import requests

from server.weather_server import fetch_weather_from_openweather


def test_missing_api_key(monkeypatch):
    """
    Dacă OPENWEATHER_API_KEY nu este setat, fetch_weather_from_openweather
    trebuie să arunce RuntimeError.
    """

    # Garantează că nu există variabila în environment
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)

    with pytest.raises(RuntimeError) as exc:
        fetch_weather_from_openweather("Bucharest")

    assert "OPENWEATHER_API_KEY" in str(exc.value)


def test_city_not_found_404(monkeypatch):
    """
    Dacă API-ul răspunde cu 404, funcția ar trebui să ridice ValueError("City not found").
    """

    # Setăm un API key „dummy” pentru a trece de prima verificare
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")

    # Creăm un obiect „fake response”
    fake_response = types.SimpleNamespace(
        status_code=404,
        text="city not found"
    )

    def fake_get(*args, **kwargs):
        return fake_response

    # Înlocuim requests.get cu fake_get
    import server.weather_server as ws
    monkeypatch.setattr(ws.requests, "get", fake_get)

    with pytest.raises(ValueError) as exc:
        fetch_weather_from_openweather("NoSuchCity")

    assert "City not found" in str(exc.value)


def test_other_status_code_raises_runtime_error(monkeypatch):
    """
    Dacă API-ul răspunde cu alt status decât 200/404, trebuie să ridicăm RuntimeError.
    """

    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")

    fake_response = types.SimpleNamespace(
        status_code=500,
        text="internal server error"
    )

    def fake_get(*args, **kwargs):
        return fake_response

    import server.weather_server as ws
    monkeypatch.setattr(ws.requests, "get", fake_get)

    with pytest.raises(RuntimeError) as exc:
        fetch_weather_from_openweather("Bucharest")

    assert "OpenWeatherMap API error" in str(exc.value)


def test_requests_exception_wrapped_in_runtime_error(monkeypatch):
    """
    Dacă requests.get aruncă o excepție de tip RequestException (probleme de rețea),
    funcția trebuie să o prindă și să ridice RuntimeError cu un mesaj clar.
    """

    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")

    def fake_get(*args, **kwargs):
        # Simulăm exact tipul de excepție pe care îl prinde codul real
        raise requests.RequestException("network down")

    import server.weather_server as ws
    monkeypatch.setattr(ws.requests, "get", fake_get)

    with pytest.raises(RuntimeError) as exc:
        fetch_weather_from_openweather("Bucharest")

    assert "Error calling OpenWeatherMap" in str(exc.value)