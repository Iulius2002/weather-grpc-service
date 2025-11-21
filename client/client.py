import grpc

from proto import weather_pb2, weather_pb2_grpc

import os

import grpc
from dotenv import load_dotenv
from proto import weather_pb2, weather_pb2_grpc

load_dotenv()


def print_weather_response(response: weather_pb2.WeatherResponse) -> None:

    print("\n==============================")
    print(f"Weather for {response.city}:")
    print(f"  Temperature: {response.temperature_celsius:.1f} °C")
    print(f"  Humidity:    {response.humidity}%")
    print(f"  Conditions:  {response.description}")
    print(f"  Wind speed:  {response.wind_speed} m/s")
    print(f"  Timestamp:   {response.timestamp}")
    print("==============================\n")


def run():
    """
    Client CLI:
    - Cere utilizatorului un nume de oraș
    - Apelează RPC-ul GetCurrentWeather
    - Afișează rezultatul
    """

    api_key = os.getenv("GRPC_API_KEY")
    if not api_key:
        print("❌ Missing GRPC_API_KEY in .env or environment.")
        return
    # Ne conectăm la serverul local, portul 50051
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = weather_pb2_grpc.WeatherServiceStub(channel)

        print("🌤  Weather gRPC Client")
        print("Type a city name to get the weather. Type 'q' to quit.\n")

        while True:
            city = input("Enter city name: ").strip()

            if city.lower() in {"q", "quit", "exit"}:
                print("Bye! 👋")
                break

            if not city:
                print("Please enter a non-empty city name.\n")
                continue

            # Construim request-ul
            request = weather_pb2.WeatherRequest(city=city)

            try:
                # Apelăm metoda RPC de pe server
                response = stub.GetCurrentWeather(
                    request,
                    metadata=[("x-api-key", api_key)]
                )

                print_weather_response(response)

            except grpc.RpcError as e:
                # Tratare erori de la server / conexiune
                print(f"\n❌ gRPC error: {e.code().name} - {e.details()}\n")


if __name__ == "__main__":
    run()