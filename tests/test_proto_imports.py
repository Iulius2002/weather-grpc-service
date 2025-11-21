def test_can_import_generated_proto_modules():
    from proto import weather_pb2, weather_pb2_grpc  # noqa: F401
    assert True


def test_weather_service_stub_exists():
    from proto import weather_pb2_grpc
    assert hasattr(weather_pb2_grpc, "WeatherServiceStub")