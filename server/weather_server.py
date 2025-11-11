from concurrent import futures
import time
import os
import datetime
import grpc
import requests
from dotenv import load_dotenv

from proto import weather_pb2, weather_pb2_grpc
from server.db import save_weather_record, get_latest_weather_record, get_weather_history

load_dotenv()

OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))  # 5 minute implicit



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
        raise RuntimeError(f"Error calling OpenWeatherMap: {e}") from e

    if resp.status_code == 404:
        raise ValueError("City not found")
    if resp.status_code != 200:
        raise RuntimeError(f"OpenWeatherMap API error: {resp.status_code} - {resp.text}")

    return resp.json()


def get_expected_api_key() -> str:
    api_key = os.getenv("GRPC_API_KEY")
    if not api_key:
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


def get_cached_weather_if_fresh(cache_key: str, city_fallback: str):
    """
    Încearcă să ia ultimul record pentru cache_key din MongoDB.
    Dacă este mai nou decât CACHE_TTL_SECONDS, îl returnează sub formă de WeatherResponse.
    Altfel, returnează None.
    Orice eroare de DB este logată, dar nu dărâmă serverul.
    """
    try:
        doc = get_latest_weather_record(cache_key)
    except Exception as e:
        print(f"[SERVER] Failed to read from MongoDB for cache: {e}")
        return None

    if not doc:
        print(f"[SERVER] No cache record found for {city_fallback}")
        return None

    created_at = doc.get("created_at")
    if created_at is None:
        print(f"[SERVER] Cache record for {city_fallback} has no created_at, skipping cache.")
        return None

    now = time.time()
    age = now - float(created_at)

    # 🔍 Log detaliat pentru debugging
    print(
        f"[SERVER] Cache check for {city_fallback}: "
        f"created_at={created_at} ({type(created_at)}), now={now}, "
        f"age={age:.1f}s, TTL={CACHE_TTL_SECONDS}s"
    )

    if age > CACHE_TTL_SECONDS:
        print(f"[SERVER] Cache expired for {city_fallback} (age={age:.1f}s > TTL={CACHE_TTL_SECONDS}s)")
        return None

    print(f"[SERVER] Using cached weather for {city_fallback}")

    return weather_pb2.WeatherResponse(
        city=doc.get("city", city_fallback),
        temperature_celsius=float(doc.get("temperature_celsius", 0.0)),
        description=doc.get("description", "n/a"),
        humidity=int(doc.get("humidity", 0)),
        wind_speed=float(doc.get("wind_speed", 0.0)),
        timestamp=doc.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


class WeatherService(weather_pb2_grpc.WeatherServiceServicer):
    """
    Implementarea serverului pentru WeatherService definit în weather.proto
    """

    def GetCurrentWeather(self, request, context):
        # securitate
        validate_api_key_from_metadata(context)

        city_input = (request.city or "").strip()
        if not city_input:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "City name must not be empty")

        # cache_key stabil (de ex. 'bucharest')
        cache_key = city_input.lower()

        print(f"[SERVER] Received request for city: {city_input}")

        # 1. încercăm cache
        cached_response = get_cached_weather_if_fresh(cache_key, city_input)
        if cached_response is not None:
            return cached_response

        # 2. fără cache valid → chemăm OpenWeather
        try:
            data = fetch_weather_from_openweather(city_input)
        except ValueError as e:
            context.abort(grpc.StatusCode.NOT_FOUND, str(e))
        except RuntimeError as e:
            context.abort(grpc.StatusCode.UNAVAILABLE, str(e))

        name = data.get("name") or city_input
        main = data.get("main", {})
        weather_list = data.get("weather", [])
        wind = data.get("wind", {})

        temp = main.get("temp")
        humidity = main.get("humidity")
        description = weather_list[0].get("description") if weather_list else "n/a"
        wind_speed = wind.get("speed")

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        response = weather_pb2.WeatherResponse(
            city=name,
            temperature_celsius=float(temp) if temp is not None else 0.0,
            description=description,
            humidity=int(humidity) if humidity is not None else 0,
            wind_speed=float(wind_speed) if wind_speed is not None else 0.0,
            timestamp=timestamp,
        )

        # 3. salvăm în Mongo pentru history + cache
        try:
            save_weather_record(
                cache_key=cache_key,
                payload={
                    "city": name,  # numele afișat în UI
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


    def GetForecast(self, request, context):
        """
        Returnează prognoza pentru următoarele ore/zile pentru orașul cerut.
        """
        validate_api_key_from_metadata(context)

        city_input = (request.city or "").strip()
        if not city_input:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "City name must not be empty")

        print(f"[SERVER] Received forecast request for city: {city_input}")

        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            context.abort(grpc.StatusCode.UNAVAILABLE, "Missing OPENWEATHER_API_KEY")

        url = "https://api.openweathermap.org/data/2.5/forecast"
        params = {
            "q": city_input,
            "appid": api_key,
            "units": "metric"
        }

        try:
            resp = requests.get(url, params=params, timeout=5)
        except requests.RequestException as e:
            context.abort(grpc.StatusCode.UNAVAILABLE, f"Error calling OpenWeatherMap: {e}")

        if resp.status_code == 404:
            context.abort(grpc.StatusCode.NOT_FOUND, "City not found")
        if resp.status_code != 200:
            context.abort(grpc.StatusCode.UNAVAILABLE, f"OpenWeatherMap API error: {resp.status_code}")

        data = resp.json()

        city_name = data.get("city", {}).get("name", city_input)
        forecast_list = data.get("list", [])

        entries = []
        for f in forecast_list[:8]:  # doar primele ~24h (8 intervale de 3h)
            main = f.get("main", {})
            weather = f.get("weather", [])
            wind = f.get("wind", {})
            entry = weather_pb2.ForecastEntry(
                timestamp=f.get("dt_txt", ""),
                temperature_celsius=float(main.get("temp", 0.0)),
                description=weather[0].get("description", "n/a") if weather else "n/a",
                humidity=int(main.get("humidity", 0)),
                wind_speed=float(wind.get("speed", 0.0))
            )
            entries.append(entry)

        return weather_pb2.ForecastResponse(city=city_name, entries=entries)

def serve():
    """
    Pornește serverul gRPC pe portul 50051.
    """
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