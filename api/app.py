from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv

from server.db import get_weather_history
import os


# Încărcăm .env ca să fim siguri că avem variabilele
load_dotenv()


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = Flask(__name__, template_folder=TEMPLATES_DIR)
@app.route("/")
def index():
    """
    Pagina principală: UI pentru graficul temperaturii.
    """
    return render_template("index.html")

@app.route("/api/weather", methods=["GET"])
def weather_history():
    """
    Endpoint HTTP:
      GET /api/weather?city=Bucharest

    Returnează ultimele înregistrări meteo pentru orașul dat.
    """
    city = (request.args.get("city") or "").strip()

    if not city:
        return jsonify({"error": "Missing 'city' query parameter"}), 400

    try:
        history = get_weather_history(city, limit=50)
    except Exception as e:
        return jsonify({"error": f"Database error: {e}"}), 500

    return jsonify({
        "city": city,
        "count": len(history),
        "data": history,
    })


if __name__ == "__main__":
    # Pornește serverul Flask pe portul 8000
    app.run(host="0.0.0.0", port=8000, debug=True)