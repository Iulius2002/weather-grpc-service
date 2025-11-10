from concurrent import futures
import time
import os

import grpc
import requests
from dotenv import load_dotenv

from proto import weather_pb2, weather_pb2_grpc
from server.db import save_weather_record


OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

def get_expected_api_key() -> str:
    api_key = os.getenv("GRPC_API_KEY")
    if not api_key:
        # Dacă nu e setată, e o problemă de config la server
        raise RuntimeError("Missing GRPC_API_KEY in environment or .env file")
    return api_key


def validate_api_key_from_metadata(context) -> None:
    """
    Verifică header-ul x-api-key din metadata.
    Dacă e lipsă sau greșit, abortă RPC-ul.
    """
    expected = get_expected_api_key()
    metadata = dict(context.invocation_metadata())
    received = metadata.get("x-api-key")

    if not received:
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "Missing x-api-key")
    if received != expected:
        context.abort(grpc.StatusCode.PERMISSION_DENIED, "Invalid x-api-key")

def fetch_weather_from_openweather(city: str) -> dict:
    """
    Apelează API-ul OpenWeatherMap și întoarce răspunsul JSON ca dict.
    Aruncă excepții clare pentru diferite tipuri de probleme.
    """
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENWEATHER_API_KEY in environment or .env file")

    params = {
        "q": city,
        "appid": api_key,
        "units": "metric",
    }

    try:
        resp = requests.get(OPENWEATHER_BASE_URL, params=params, timeout=5)
    except requests.RequestException as e:
        # Probleme de rețea, timeout etc.
        raise RuntimeError(f"Error calling OpenWeatherMap: {e}") from e

    if resp.status_code == 404:
        # Oraș negăsit
        raise ValueError("City not found")
    if resp.status_code != 200:
        # Alte erori (ex. 401, 429 etc.)
        raise RuntimeError(f"OpenWeatherMap API error: {resp.status_code} - {resp.text}")

    return resp.json()


class WeatherService(weather_pb2_grpc.WeatherServiceServicer):
    """
    Implementarea serverului pentru WeatherService definit în weather.proto
    """

    def GetCurrentWeather(self, request, context):
        # Validăm API key din metadata
        validate_api_key_from_metadata(context)
        city = (request.city or "").strip()
        if not city:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "City name must not be empty")

        print(f"[SERVER] Received request for city: {city}")

        try:
            data = fetch_weather_from_openweather(city)
        except ValueError as e:
            # Oraș negăsit
            context.abort(grpc.StatusCode.NOT_FOUND, str(e))
        except RuntimeError as e:
            # Probleme cu API-ul sau config-ul
            context.abort(grpc.StatusCode.UNAVAILABLE, str(e))

        # Parsăm răspunsul
        name = data.get("name") or city
        main = data.get("main", {})
        weather_list = data.get("weather", [])
        wind = data.get("wind", {})

        temp = main.get("temp")
        humidity = main.get("humidity")
        description = weather_list[0].get("description") if weather_list else "n/a"
        wind_speed = wind.get("speed")

        response = weather_pb2.WeatherResponse(
            city=name,
            temperature_celsius=float(temp) if temp is not None else 0.0,
            description=description,
            humidity=int(humidity) if humidity is not None else 0,
            wind_speed=float(wind_speed) if wind_speed is not None else 0.0,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

        # Salvăm în MongoDB (fără să stricăm răspunsul dacă baza de date e down)
        try:
            save_weather_record(
                city=name,
                payload={
                    "temperature_celsius": response.temperature_celsius,
                    "description": response.description,
                    "humidity": response.humidity,
                    "wind_speed": response.wind_speed,
                    "timestamp": response.timestamp,
                },
            )
            print(f"[SERVER] Saved weather record for {name} in MongoDB.")
        except Exception as e:
            print(f"[SERVER] Failed to save to MongoDB: {e}")

        return response


def serve():
    """
    Pornește serverul gRPC pe portul 50051.
    """
    # Încărcăm variabilele din .env
    load_dotenv()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    weather_pb2_grpc.add_WeatherServiceServicer_to_server(
        WeatherService(), server
    )

    server.add_insecure_port("[::]:50051")

    print("🚀 Weather gRPC server running on port 50051...")
    server.start()

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server...")


if __name__ == "__main__":
    serve()