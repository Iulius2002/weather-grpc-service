from concurrent import futures

import grpc
import pytest

from proto import weather_pb2, weather_pb2_grpc
import server.weather_server as ws  # ws = modulul server.weather_server


def start_test_server():
    """
    Pornește un server gRPC de test, folosind WeatherService,
    pe un port aleator (localhost:0). Returnează (server, port).
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    weather_pb2_grpc.add_WeatherServiceServicer_to_server(ws.WeatherService(), server)
    port = server.add_insecure_port("localhost:0")  # 0 = alege un port liber
    server.start()
    return server, port


def test_get_current_weather_success(monkeypatch):
    """
    Test de integrare:
    - Monkeypatch la fetch_weather_from_openweather ca să nu apelăm API-ul real
    - Server gRPC pornește in-process
    - Clientul apelează GetCurrentWeather cu x-api-key corect
    - Verificăm că primim un WeatherResponse coerent
    """

    # Setăm cheile necesare
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")
    monkeypatch.setenv("GRPC_API_KEY", "test-key")

    # Fake pentru răspunsul OpenWeather
    def fake_fetch(city: str):
        return {
            "name": "TestCity",
            "main": {
                "temp": 20.5,
                "humidity": 60
            },
            "weather": [
                {"description": "clear sky"}
            ],
            "wind": {
                "speed": 3.0
            }
        }

    monkeypatch.setattr(ws, "fetch_weather_from_openweather", fake_fetch)

    server, port = start_test_server()

    try:
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = weather_pb2_grpc.WeatherServiceStub(channel)

            request = weather_pb2.WeatherRequest(city="Bucharest")

            response = stub.GetCurrentWeather(
                request,
                metadata=[("x-api-key", "test-key")]
            )

        assert response.city == "TestCity"
        assert response.temperature_celsius == pytest.approx(20.5)
        assert response.humidity == 60
        assert response.description == "clear sky"
        assert response.wind_speed == pytest.approx(3.0)
        assert response.timestamp  # să nu fie string gol
    finally:
        server.stop(0)


def test_missing_api_key_yields_unauthenticated(monkeypatch):
    """
    Dacă nu trimitem deloc x-api-key, serverul trebuie să răspundă cu UNAUTHENTICATED.
    """
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")
    monkeypatch.setenv("GRPC_API_KEY", "test-key")

    # Nu ne interesează apelul real către OpenWeather în acest test
    def fake_fetch(city: str):
        return {}

    monkeypatch.setattr(ws, "fetch_weather_from_openweather", fake_fetch)

    server, port = start_test_server()

    try:
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = weather_pb2_grpc.WeatherServiceStub(channel)

            request = weather_pb2.WeatherRequest(city="Bucharest")

            with pytest.raises(grpc.RpcError) as exc:
                # fără metadata => fără x-api-key
                stub.GetCurrentWeather(request)

            assert exc.value.code() == grpc.StatusCode.UNAUTHENTICATED
            assert "Missing x-api-key" in exc.value.details()
    finally:
        server.stop(0)


def test_invalid_api_key_yields_permission_denied(monkeypatch):
    """
    Dacă trimitem un x-api-key greșit, serverul trebuie să răspundă cu PERMISSION_DENIED.
    """
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")
    monkeypatch.setenv("GRPC_API_KEY", "correct-key")

    def fake_fetch(city: str):
        return {}

    monkeypatch.setattr(ws, "fetch_weather_from_openweather", fake_fetch)

    server, port = start_test_server()

    try:
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = weather_pb2_grpc.WeatherServiceStub(channel)

            request = weather_pb2.WeatherRequest(city="Bucharest")

            with pytest.raises(grpc.RpcError) as exc:
                stub.GetCurrentWeather(
                    request,
                    metadata=[("x-api-key", "wrong-key")]
                )

            assert exc.value.code() == grpc.StatusCode.PERMISSION_DENIED
            assert "Invalid x-api-key" in exc.value.details()
    finally:
        server.stop(0)


def test_empty_city_yields_invalid_argument(monkeypatch):
    """
    Dacă city este gol, serverul trebuie să răspundă cu INVALID_ARGUMENT.
    """
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")
    monkeypatch.setenv("GRPC_API_KEY", "test-key")

    def fake_fetch(city: str):
        return {}

    monkeypatch.setattr(ws, "fetch_weather_from_openweather", fake_fetch)

    server, port = start_test_server()

    try:
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = weather_pb2_grpc.WeatherServiceStub(channel)

            request = weather_pb2.WeatherRequest(city="")

            with pytest.raises(grpc.RpcError) as exc:
                stub.GetCurrentWeather(
                    request,
                    metadata=[("x-api-key", "test-key")]
                )

            assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT
            assert "City name must not be empty" in exc.value.details()
    finally:
        server.stop(0)