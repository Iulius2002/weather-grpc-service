import grpc
from proto import weather_pb2, weather_pb2_grpc

API_KEY = "super-secret-key-123"

def run():
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = weather_pb2_grpc.WeatherServiceStub(channel)

        city = input("Enter city name: ")
        response = stub.GetForecast(
            weather_pb2.WeatherRequest(city=city),
            metadata=[("x-api-key", API_KEY)]
        )

        print(f"Forecast for {response.city}:")
        for e in response.entries:
            print(f"{e.timestamp} | {e.temperature_celsius:.1f} °C | {e.description} | wind {e.wind_speed} m/s")

if __name__ == "__main__":
    run()