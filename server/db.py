import os
import time
from typing import Any, Dict, List, Optional

from pymongo import MongoClient
from dotenv import load_dotenv


load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "weather_db")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "weather_history")

_client = MongoClient(MONGO_URI)
_db = _client[MONGO_DB_NAME]
_collection = _db[MONGO_COLLECTION_NAME]


def save_weather_record(cache_key: str, payload: Dict[str, Any]) -> None:
    """
    Salvează un document cu datele meteo în MongoDB.
    Include câmpul 'created_at' (epochtime) pentru verificarea TTL-ului cache-ului.
    """
    doc = {
        **payload,
        "cache_key": cache_key,
        "created_at": time.time(),  # pune mereu creat_at la final, ca să nu poată fi suprascris
    }
    _collection.insert_one(doc)


def get_weather_history(city: str, limit: int = 50, hours: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Returnează istoricul meteo pentru un oraș.

    city: numele afișat al orașului (ex: "Bucharest")
    limit: câte înregistrări maxim să întoarcem
    hours: dacă e setat, întoarcem doar înregistrările mai noi decât (acum - hours).
    """
    query: Dict[str, Any] = {
        "$or": [
            {"city": city},
            {"city": city.capitalize()},
            {"city": city.lower()},
            {"city": city.upper()},
        ]
    }

    if hours is not None:
        min_created_at = time.time() - hours * 3600
        query["created_at"] = {"$gte": min_created_at}

    cursor = _collection.find(
        query,
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit)

    return list(cursor)


def get_latest_weather_record(cache_key: str) -> Optional[Dict[str, Any]]:
    """
    Pentru cache: luăm cea mai recentă înregistrare după cache_key.
    """
    doc = _collection.find_one(
        {"cache_key": cache_key},
        {"_id": 0},
        sort=[("created_at", -1)]
    )
    return doc