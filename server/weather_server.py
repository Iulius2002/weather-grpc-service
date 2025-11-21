"""
gRPC WeatherService server implementation.

- Fetches current weather & forecast from OpenWeatherMap.
- Caches latest current weather per city in MongoDB (TTL-driven).
- Exposes two RPCs: GetCurrentWeather, GetForecast.
"""

from concurrent import futures
import os
import time
from typing import Any, Dict, Optional

import grpc
import requests
import logging
from dotenv import load_dotenv

from proto import weather_pb2, weather_pb2_grpc
from server.db import save_weather_record, get_latest_weather_record

# -------------------------------------------------------------------------
# Initialization & configuration
# -------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | [SERVER] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

# Configurable via .env (safe defaults)
CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))          # 5 minutes
OPENWEATHER_TIMEOUT_SECONDS: int = int(os.getenv("OPENWEATHER_TIMEOUT_SECONDS", "5"))
FORECAST_STEPS_3H: int = int(os.getenv("FORECAST_STEPS_3H", "8"))            # ~24h (8 x 3h)

logging.info("CACHE_TTL_SECONDS = %s", CACHE_TTL_SECONDS)
logging.info("OPENWEATHER_TIMEOUT_SECONDS = %s", OPENWEATHER_TIMEOUT_SECONDS)
logging.info("FORECAST_STEPS_3H = %s", FORECAST_STEPS_3H)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def fetch_weather_from_openweather(city: str) -> Dict[str, Any]:
    """
    Call OpenWeatherMap current weather API and return JSON payload as dict.

    Raises:
        RuntimeError: for missing API key or non-200 HTTP responses.
        ValueError: when city is not found (404).
    """
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENWEATHER_API_KEY in environment or .env file")

    params = {"q": city, "appid": api_key, "units": "metric"}

    try:
        resp = requests.get(
            OPENWEATHER_BASE_URL,
            params=params,
            timeout=OPENWEATHER_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Error calling OpenWeatherMap: {e}") from e

    if resp.status_code == 404:
        raise ValueError("City not found")
    if resp.status_code != 200:
        raise RuntimeError(f"OpenWeatherMap API error: {resp.status_code} - {resp.text}")

    return resp.json()


def get_expected_api_key() -> str:
    """
    Read the gRPC API key from environment.
    """
    api_key = os.getenv("GRPC_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GRPC_API_KEY in environment or .env file")
    return api_key


def validate_api_key_from_metadata(context: grpc.ServicerContext) -> None:
    """
    Validate 'x-api-key' metadata header for all RPC calls.
    Abort with appropriate gRPC status if invalid/missing.
    """
    expected = get_expected_api_key()
    metadata = dict(context.invocation_metadata())
    received = metadata.get("x-api-key")

    if not received:
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "Missing x-api-key")
    if received != expected:
        context.abort(grpc.StatusCode.PERMISSION_DENIED, "Invalid x-api-key")


def get_cached_weather_if_fresh(
    cache_key: str, city_fallback: str
) -> Optional[weather_pb2.WeatherResponse]:
    """
    Try to return the latest cached WeatherResponse for cache_key if still fresh (TTL).
    Return None if cache is missing or stale.
    """
    try:
        doc = get_latest_weather_record(cache_key)
    except Exception as e:
        logging.warning("Failed to read from MongoDB for cache: %s", e)
        return None

    if not doc:
        logging.info("No cache record found for %s", city_fallback)
        return None

    created_at = doc.get("created_at")
    if created_at is None:
        logging.info("Cache record for %s has no created_at, skipping cache.", city_fallback)
        return None

    now = time.time()
    try:
        age = now - float(created_at)
    except (TypeError, ValueError):
        logging.info("Invalid created_at format for %s, skipping cache.", city_fallback)
        return None

    logging.info(
        "Cache check for %s: created_at=%s (%s), now=%s, age=%.1fs, TTL=%ss",
        city_fallback, created_at, type(created_at).__name__, now, age, CACHE_TTL_SECONDS
    )

    if age > CACHE_TTL_SECONDS:
        logging.info(
            "Cache expired for %s (age=%.1fs > TTL=%ss)",
            city_fallback, age, CACHE_TTL_SECONDS
        )
        return None

    logging.info("Using cached weather for %s", city_fallback)
    return weather_pb2.WeatherResponse(
        city=doc.get("city", city_fallback),
        temperature_celsius=float(doc.get("temperature_celsius", 0.0)),
        description=doc.get("description", "n/a"),
        humidity=int(doc.get("humidity", 0)),
        wind_speed=float(doc.get("wind_speed", 0.0)),
        timestamp=doc.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


# -------------------------------------------------------------------------
# gRPC Service
# -------------------------------------------------------------------------
class WeatherService(weather_pb2_grpc.WeatherServiceServicer):
    """
    WeatherService RPC implementation (defined in weather.proto).
    """

    def GetCurrentWeather(
        self, request: weather_pb2.WeatherRequest, context: grpc.ServicerContext
    ) -> weather_pb2.WeatherResponse:
        """
        Returns current weather for the given city.
        Applies cache (MongoDB) with TTL before calling OpenWeatherMap.
        """
        # Security
        validate_api_key_from_metadata(context)

        # Input validation
        city_input = (request.city or "").strip()
        if not city_input:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "City name must not be empty")
        # Normalize key for cache (case-insensitive)
        cache_key = city_input.lower()

        logging.info("Received request for city: %s", city_input)

        # 1) Try cache
        cached_response = get_cached_weather_if_fresh(cache_key, city_input)
        if cached_response is not None:
            return cached_response

        # 2) No valid cache → call OpenWeather
        try:
            data = fetch_weather_from_openweather(city_input)
        except ValueError as e:
            context.abort(grpc.StatusCode.NOT_FOUND, str(e))
        except RuntimeError as e:
            context.abort(grpc.StatusCode.UNAVAILABLE, str(e))

        name = data.get("name") or city_input
        main = data.get("main", {}) or {}
        weather_list = data.get("weather", []) or []
        wind = data.get("wind", {}) or {}

        temp = main.get("temp")
        humidity = main.get("humidity")
        description = weather_list[0].get("description") if weather_list else "n/a"
        wind_speed = wind.get("speed")

        timestamp_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        response = weather_pb2.WeatherResponse(
            city=name,
            temperature_celsius=float(temp) if temp is not None else 0.0,
            description=description,
            humidity=int(humidity) if humidity is not None else 0,
            wind_speed=float(wind_speed) if wind_speed is not None else 0.0,
            timestamp=timestamp_str,
        )

        # 3) Persist in Mongo for history + future cache hits
        try:
            save_weather_record(
                cache_key=cache_key,
                payload={
                    "city": name,
                    "temperature_celsius": response.temperature_celsius,
                    "description": response.description,
                    "humidity": response.humidity,
                    "wind_speed": response.wind_speed,
                    "timestamp": response.timestamp,
                },
            )
            logging.info("Saved weather record for %s in MongoDB.", name)
        except Exception as e:
            # Non-fatal: we still return the fresh response to the client.
            logging.warning("Failed to save to MongoDB for %s: %s", name, e)

        return response

    def GetForecast(
        self, request: weather_pb2.WeatherRequest, context: grpc.ServicerContext
    ) -> weather_pb2.ForecastResponse:
        """
        Returns next ~24h forecast (3h steps) for the given city using OpenWeatherMap.
        """
        validate_api_key_from_metadata(context)

        city_input = (request.city or "").strip()
        if not city_input:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "City name must not be empty")

        logging.info("Received forecast request for city: %s", city_input)

        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            context.abort(grpc.StatusCode.UNAVAILABLE, "Missing OPENWEATHER_API_KEY")

        params = {"q": city_input, "appid": api_key, "units": "metric"}

        try:
            resp = requests.get(
                OPENWEATHER_FORECAST_URL,
                params=params,
                timeout=OPENWEATHER_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            context.abort(grpc.StatusCode.UNAVAILABLE, f"Error calling OpenWeatherMap: {e}")

        if resp.status_code == 404:
            context.abort(grpc.StatusCode.NOT_FOUND, "City not found")
        if resp.status_code != 200:
            context.abort(
                grpc.StatusCode.UNAVAILABLE,
                f"OpenWeatherMap API error: {resp.status_code}",
            )

        data = resp.json()

        city_name = (data.get("city") or {}).get("name", city_input)
        forecast_list = data.get("list", []) or []

        entries = []
        for f in forecast_list[:FORECAST_STEPS_3H]:
            main = f.get("main", {}) or {}
            weather = f.get("weather", []) or []
            wind = f.get("wind", {}) or {}
            entries.append(
                weather_pb2.ForecastEntry(
                    timestamp=f.get("dt_txt", ""),
                    temperature_celsius=float(main.get("temp", 0.0)),
                    description=weather[0].get("description", "n/a") if weather else "n/a",
                    humidity=int(main.get("humidity", 0)),
                    wind_speed=float(wind.get("speed", 0.0)),
                )
            )

        return weather_pb2.ForecastResponse(city=city_name, entries=entries)


# -------------------------------------------------------------------------
# Entrypoint
# -------------------------------------------------------------------------
def serve() -> None:
    """
    Starts the gRPC server on port 50051.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    weather_pb2_grpc.add_WeatherServiceServicer_to_server(WeatherService(), server)
    server.add_insecure_port("[::]:50051")

    logging.info(" Weather gRPC server running on port 50051...")
    server.start()

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logging.info(" Shutting down server...")


if __name__ == "__main__":
    serve()