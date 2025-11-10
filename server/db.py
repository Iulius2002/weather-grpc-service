import os
from typing import Any, Dict

from pymongo import MongoClient
from dotenv import load_dotenv


# Ne asigurăm că variabilele din .env sunt încărcate
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "weather_db")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "weather_history")

_client = MongoClient(MONGO_URI)
_db = _client[MONGO_DB_NAME]
_collection = _db[MONGO_COLLECTION_NAME]


def save_weather_record(city: str, payload: Dict[str, Any]) -> None:
    """
    Salvează un document cu datele meteo în MongoDB.
    `payload` poate conține orice câmpuri suplimentare (temperatură, descriere, etc).
    """
    doc = {
        "city": city,
        **payload,
    }
    _collection.insert_one(doc)

def get_weather_history(city: str, limit: int = 50):
    """
    Returnează ultimele înregistrări de vreme pentru un oraș, sortate descrescător după timp.
    """
    cursor = _collection.find(
        {"city": city},
        {"_id": 0}  # ascundem _id ca să fie JSON-serializable ușor
    ).sort("timestamp", -1).limit(limit)

    return list(cursor)