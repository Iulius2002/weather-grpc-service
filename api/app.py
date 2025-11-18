import os
import time
import logging
from typing import Any, Dict, List, Optional

import grpc
from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv

from server.db import get_weather_history
from proto import weather_pb2, weather_pb2_grpc

# -------------------------------------------------------------------------
#  Initialization & logging
# -------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | [API] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = Flask(__name__, template_folder=TEMPLATES_DIR)


# -------------------------------------------------------------------------
#  Helpers
# -------------------------------------------------------------------------
def _grpc_address() -> str:
    """
    Returnează adresa serverului gRPC.
    Implicit folosește numele de serviciu din Docker Compose; pentru local, pune GRPC_SERVER_ADDRESS=localhost:50051 în .env.
    """
    return os.getenv("GRPC_SERVER_ADDRESS", "grpc_server:50051")


def _grpc_api_key() -> str:
    api_key = os.getenv("GRPC_API_KEY")
    if not api_key:
        raise RuntimeError("GRPC_API_KEY not configured on API service")
    return api_key


def call_grpc_current_weather(city: str) -> weather_pb2.WeatherResponse:
    """
    Apelează RPC-ul GetCurrentWeather pentru un oraș.
    Ridică grpc.RpcError pe erori de transport/serviciu.
    """
    api_key = _grpc_api_key()
    address = _grpc_address()
    with grpc.insecure_channel(address) as channel:
        stub = weather_pb2_grpc.WeatherServiceStub(channel)
        req = weather_pb2.WeatherRequest(city=city)
        return stub.GetCurrentWeather(req, metadata=[("x-api-key", api_key)])


def call_grpc_forecast(city: str) -> weather_pb2.ForecastResponse:
    """
    Apelează RPC-ul GetForecast pentru un oraș.
    Ridică grpc.RpcError pe erori de transport/serviciu.
    """
    api_key = _grpc_api_key()
    address = _grpc_address()
    with grpc.insecure_channel(address) as channel:
        stub = weather_pb2_grpc.WeatherServiceStub(channel)
        req = weather_pb2.WeatherRequest(city=city)
        return stub.GetForecast(req, metadata=[("x-api-key", api_key)])


def _parse_int(name: str, raw: Optional[str], *, default: Optional[int] = None, min_value: Optional[int] = None) -> Optional[int]:
    """Conversie robustă la int pentru parametrii query; ridică ValueError cu mesaj clar."""
    if raw is None:
        return default
    try:
        value = int(raw)
        if min_value is not None and value < min_value:
            raise ValueError
        return value
    except ValueError:
        raise ValueError(f"Invalid '{name}' parameter")


# -------------------------------------------------------------------------
#  Routes
# -------------------------------------------------------------------------
@app.route("/")
def index() -> str:
    """Frontend UI route — încarcă pagina principală."""
    return render_template("index.html")


@app.get("/api/health")
def health() -> Any:
    """Health check simplu."""
    return jsonify({"status": "ok"}), 200


@app.get("/api/weather")
def weather_history_route():
    """
    GET /api/weather?city=Bucharest&hours=24&limit=100

    Returnează istoricul meteo pentru un oraș din MongoDB.
    Dacă nu există date SAU cel mai nou record e mai vechi decât CACHE_TTL_SECONDS,
    declanșează un refresh via gRPC (GetCurrentWeather), apoi returnează datele actualizate.
    """
    city = (request.args.get("city") or "").strip()
    if not city:
        return jsonify({"error": "Missing 'city' query parameter"}), 400

    try:
        limit = _parse_int("limit", request.args.get("limit", "50"), default=50, min_value=1)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        hours = _parse_int("hours", request.args.get("hours"), default=None, min_value=1)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    cache_ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "300"))

    # 1) Citim istoricul pentru UI (respectând "hours", dacă e prezent)
    try:
        history: List[Dict[str, Any]] = get_weather_history(city, limit=limit, hours=hours)
    except Exception as e:
        logging.exception("Database error while reading history for %s", city)
        return jsonify({"error": f"Database error: {e}"}), 500

    # 2) Verificăm vechimea celui mai nou record ignorând filtrul "hours"
    try:
        latest_list = get_weather_history(city, limit=1, hours=None)
    except Exception as e:
        logging.exception("Failed to read latest record for %s", city)
        latest_list = []

    needs_refresh = False
    if latest_list:
        latest = latest_list[0]
        created_at = latest.get("created_at")
        if isinstance(created_at, (int, float)):
            age = time.time() - created_at
            logging.info("Latest record for %s age=%.1fs (TTL=%ss)", city, age, cache_ttl_seconds)
            if age > cache_ttl_seconds:
                logging.info("Cache expired for %s — will refresh via gRPC.", city)
                needs_refresh = True
        else:
            logging.info("Invalid/missing created_at for %s — will refresh via gRPC.", city)
            needs_refresh = True
    else:
        logging.info("No records found for %s — will fetch via gRPC.", city)
        needs_refresh = True

    # 3) Refresh via gRPC dacă e nevoie; serverul gRPC salvează în Mongo
    if needs_refresh:
        try:
            logging.info("Calling gRPC GetCurrentWeather for %s", city)
            _ = call_grpc_current_weather(city)
            # recitim istoricul pentru UI (respectând "hours")
            history = get_weather_history(city, limit=limit, hours=hours)
        except grpc.RpcError as e:
            return jsonify({
                "error": f"gRPC error while fetching current weather: {e.code().name}",
                "details": e.details(),
            }), 502
        except Exception as e:
            logging.exception("Internal error while calling gRPC for %s", city)
            return jsonify({"error": f"Failed to fetch current weather via gRPC: {e}"}), 500

    return jsonify({
        "city": city,
        "count": len(history),
        "hours": hours,
        "limit": limit,
        "data": history,
    })


@app.get("/api/forecast")
def forecast_route():
    """
    GET /api/forecast?city=Bucharest

    Returnează prognoza (următoarele ~24h în pași de 3h) via gRPC.
    """
    city = (request.args.get("city") or "").strip()
    if not city:
        return jsonify({"error": "Missing 'city' query parameter"}), 400

    try:
        response_pb = call_grpc_forecast(city)
    except grpc.RpcError as e:
        return jsonify({
            "error": f"gRPC error: {e.code().name}",
            "details": e.details(),
        }), 502
    except Exception as e:
        logging.exception("Internal error while calling GetForecast for %s", city)
        return jsonify({"error": f"Internal error calling gRPC: {e}"}), 500

    entries = [
        {
            "timestamp": entry.timestamp,
            "temperature_celsius": entry.temperature_celsius,
            "description": entry.description,
            "humidity": entry.humidity,
            "wind_speed": entry.wind_speed,
        }
        for entry in response_pb.entries
    ]

    return jsonify({
        "city": response_pb.city,
        "count": len(entries),
        "data": entries,
    })


# -------------------------------------------------------------------------
#  Main entry point (local dev)
# -------------------------------------------------------------------------
if __name__ == "__main__":
    # Local-only. În Docker, rulezi cu gunicorn/flask run dacă dorești.
    app.run(host="0.0.0.0", port=8000)