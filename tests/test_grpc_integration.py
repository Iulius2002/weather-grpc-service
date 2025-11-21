from concurrent import futures

import grpc
import pytest

from proto import weather_pb2, weather_pb2_grpc
import server.weather_server as ws


def start_test_server():
    """Start an in-process gRPC server on a random port and return (server, port)."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    weather_pb2_grpc.add_WeatherServiceServicer_to_server(ws.WeatherService(), server)
    port = server.add_insecure_port("localhost:0")
    server.start()
    return server, port


def test_get_current_weather_success(monkeypatch):
    """Happy path: valid API key, mocked OpenWeather, coherent WeatherResponse."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")
    monkeypatch.setenv("GRPC_API_KEY", "test-key")

    def fake_fetch(city: str):
        return {
            "name": "TestCity",
            "main": {"temp": 20.5, "humidity": 60},
            "weather": [{"description": "clear sky"}],
            "wind": {"speed": 3.0},
        }

    monkeypatch.setattr(ws, "fetch_weather_from_openweather", fake_fetch)

    server, port = start_test_server()
    try:
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = weather_pb2_grpc.WeatherServiceStub(channel)
            req = weather_pb2.WeatherRequest(city="Bucharest")
            resp = stub.GetCurrentWeather(req, metadata=[("x-api-key", "test-key")])

        assert resp.city == "TestCity"
        assert resp.temperature_celsius == pytest.approx(20.5)
        assert resp.humidity == 60
        assert resp.description == "clear sky"
        assert resp.wind_speed == pytest.approx(3.0)
        assert resp.timestamp
    finally:
        server.stop(0)


def test_missing_api_key_yields_unauthenticated(monkeypatch):
    """Missing x-api-key → UNAUTHENTICATED."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")
    monkeypatch.setenv("GRPC_API_KEY", "test-key")

    def fake_fetch(city: str):
        return {}

    monkeypatch.setattr(ws, "fetch_weather_from_openweather", fake_fetch)

    server, port = start_test_server()
    try:
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = weather_pb2_grpc.WeatherServiceStub(channel)
            req = weather_pb2.WeatherRequest(city="Bucharest")
            with pytest.raises(grpc.RpcError) as exc:
                stub.GetCurrentWeather(req)
        assert exc.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert "Missing x-api-key" in exc.value.details()
    finally:
        server.stop(0)


def test_invalid_api_key_yields_permission_denied(monkeypatch):
    """Wrong x-api-key → PERMISSION_DENIED."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")
    monkeypatch.setenv("GRPC_API_KEY", "correct-key")

    def fake_fetch(city: str):
        return {}

    monkeypatch.setattr(ws, "fetch_weather_from_openweather", fake_fetch)

    server, port = start_test_server()
    try:
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = weather_pb2_grpc.WeatherServiceStub(channel)
            req = weather_pb2.WeatherRequest(city="Bucharest")
            with pytest.raises(grpc.RpcError) as exc:
                stub.GetCurrentWeather(req, metadata=[("x-api-key", "wrong-key")])
        assert exc.value.code() == grpc.StatusCode.PERMISSION_DENIED
        assert "Invalid x-api-key" in exc.value.details()
    finally:
        server.stop(0)


def test_empty_city_yields_invalid_argument(monkeypatch):
    """Empty city → INVALID_ARGUMENT."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "dummy-key")
    monkeypatch.setenv("GRPC_API_KEY", "test-key")

    def fake_fetch(city: str):
        return {}

    monkeypatch.setattr(ws, "fetch_weather_from_openweather", fake_fetch)

    server, port = start_test_server()
    try:
        with grpc.insecure_channel(f"localhost:{port}") as channel:
            stub = weather_pb2_grpc.WeatherServiceStub(channel)
            req = weather_pb2.WeatherRequest(city="")
            with pytest.raises(grpc.RpcError) as exc:
                stub.GetCurrentWeather(req, metadata=[("x-api-key", "test-key")])
        assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT
        assert "City name must not be empty" in exc.value.details()
    finally:
        server.stop(0)