def test_can_import_generated_proto_modules():
    """
    Verifică faptul că fișierele generate din .proto există și pot fi importate.
    """
    from proto import weather_pb2, weather_pb2_grpc  # noqa: F401

    # Dacă ajungem aici fără ModuleNotFoundError, testul e OK
    assert True


def test_weather_service_stub_exists():
    """
    Verifică faptul că WeatherServiceStub a fost generat corect.
    """
    from proto import weather_pb2_grpc

    assert hasattr(weather_pb2_grpc, "WeatherServiceStub")