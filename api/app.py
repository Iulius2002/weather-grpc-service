import os
import time
import grpc
from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv
from server.db import get_weather_history
from proto import weather_pb2, weather_pb2_grpc

# -------------------------------------------------------------------------
#  Initialization
# -------------------------------------------------------------------------
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = Flask(__name__, template_folder=TEMPLATES_DIR)


# -------------------------------------------------------------------------
#  Helper Functions
# -------------------------------------------------------------------------
def call_grpc_current_weather(city: str):
    """
    Calls the gRPC service (GetCurrentWeather) for a given city.
    Used when MongoDB doesn't yet contain weather data for that city
    or when existing data is stale.
    """
    api_key = os.getenv("GRPC_API_KEY")
    if not api_key:
        raise RuntimeError("GRPC_API_KEY not configured on API service")

    grpc_address = os.getenv("GRPC_SERVER_ADDRESS", "localhost:50051")

    with grpc.insecure_channel(grpc_address) as channel:
        stub = weather_pb2_grpc.WeatherServiceStub(channel)
        request_pb = weather_pb2.WeatherRequest(city=city)

        response_pb = stub.GetCurrentWeather(
            request_pb,
            metadata=[("x-api-key", api_key)]
        )

    return response_pb


def call_grpc_forecast(city: str):
    """
    Calls the gRPC service (GetForecast) for a given city.
    Returns structured forecast data as a Python list.
    """
    api_key = os.getenv("GRPC_API_KEY")
    if not api_key:
        raise RuntimeError("GRPC_API_KEY not configured on API service")

    grpc_address = os.getenv("GRPC_SERVER_ADDRESS", "localhost:50051")

    with grpc.insecure_channel(grpc_address) as channel:
        stub = weather_pb2_grpc.WeatherServiceStub(channel)
        request_pb = weather_pb2.WeatherRequest(city=city)

        response_pb = stub.GetForecast(
            request_pb,
            metadata=[("x-api-key", api_key)]
        )

    return response_pb


# -------------------------------------------------------------------------
#  Routes
# -------------------------------------------------------------------------
@app.route("/")
def index():
    """Frontend UI route — renders the main HTML template."""
    return render_template("index.html")


@app.route("/api/weather", methods=["GET"])
def weather_history():
    """
    REST API endpoint:
        GET /api/weather?city=Bucharest&hours=24&limit=100

    Returns historical weather data for a city, stored in MongoDB.

    If:
      - no records exist for that city, OR
      - the most recent record is older than CACHE_TTL_SECONDS,
    it automatically calls the gRPC service (GetCurrentWeather)
    to fetch and save a new record before returning data.
    """
    city = (request.args.get("city") or "").strip()

    if not city:
        return jsonify({"error": "Missing 'city' query parameter"}), 400

    # limit
    limit_param = request.args.get("limit", "50")
    try:
        limit = int(limit_param)
        if limit <= 0:
            raise ValueError
    except ValueError:
        return jsonify({"error": "Invalid 'limit' parameter"}), 400

    # hours (optional)
    hours_param = request.args.get("hours")
    hours = None
    if hours_param:
        try:
            hours = int(hours_param)
            if hours <= 0:
                raise ValueError
        except ValueError:
            return jsonify({"error": "Invalid 'hours' parameter"}), 400

    # TTL pentru cache (în secunde)
    cache_ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "300"))

    # 1️⃣ Citim istoricul pentru UI (cu filtrul hours, dacă este)
    try:
        history = get_weather_history(city, limit=limit, hours=hours)
    except Exception as e:
        return jsonify({"error": f"Database error: {e}"}), 500

    # 2️⃣ Verificăm dacă datele sunt prea vechi sau lipsesc complet
    needs_refresh = False

    # Pentru a verifica vechimea, luăm CEL MAI RECENT record din DB,
    # ignorând filtrul de hours (ca să nu fie exclus din cauza intervalului).
    try:
        latest_list = get_weather_history(city, limit=1, hours=None)
    except Exception as e:
        print(f"[API] Failed to read latest record for {city}: {e}")
        latest_list = []

    if latest_list:
        latest = latest_list[0]
        created_at = latest.get("created_at")
        if isinstance(created_at, (int, float)):
            age = time.time() - created_at
            print(f"[API] Latest record for {city} age={age:.1f}s (TTL={cache_ttl_seconds}s)")
            if age > cache_ttl_seconds:
                print(f"[API] Cache expired for {city}, will refresh via gRPC.")
                needs_refresh = True
        else:
            print(f"[API] Invalid or missing created_at for {city}, will refresh via gRPC.")
            needs_refresh = True
    else:
        print(f"[API] No records found for {city}, will fetch via gRPC.")
        needs_refresh = True

    # 3️⃣ Dacă avem nevoie de refresh → apelăm gRPC GetCurrentWeather
    if needs_refresh:
        try:
            print(f"[API] Calling gRPC GetCurrentWeather for {city}")
            _ = call_grpc_current_weather(city)
            # gRPC server salvează în Mongo, deci recitim istoricul
            history = get_weather_history(city, limit=limit, hours=hours)
        except grpc.RpcError as e:
            return jsonify({
                "error": f"gRPC error while fetching current weather: {e.code().name}",
                "details": e.details(),
            }), 502
        except Exception as e:
            return jsonify({"error": f"Failed to fetch current weather via gRPC: {e}"}), 500

    return jsonify({
        "city": city,
        "count": len(history),
        "hours": hours,
        "limit": limit,
        "data": history,
    })


@app.route("/api/forecast", methods=["GET"])
def forecast():
    """
    REST API endpoint:
        GET /api/forecast?city=Bucharest

    Calls the gRPC service (GetForecast) to return temperature predictions
    for the next hours/days for the requested city.
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
#  Main entry point (for local dev)
# -------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)