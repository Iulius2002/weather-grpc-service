import os
import time
from typing import Any, Dict, List, Optional

from pymongo import MongoClient, ASCENDING, DESCENDING
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "weather_db")
MONGO_COLLECTION_NAME = os.getenv("MONGO_COLLECTION_NAME", "weather_history")

_client = MongoClient(MONGO_URI)
_db = _client[MONGO_DB_NAME]
_collection = _db[MONGO_COLLECTION_NAME]


def _ensure_indexes() -> None:
    """
    Creează index-uri utile pentru performanță:
      - cache_key + created_at (căutare cel mai recent record pentru cache)
      - created_at (filtrare după intervale)
    """
    try:
        _collection.create_index([("cache_key", ASCENDING), ("created_at", DESCENDING)], name="idx_cache_key_created_at")
        _collection.create_index([("created_at", DESCENDING)], name="idx_created_at")
    except Exception:
        # index-urile sunt opționale; dacă nu se pot crea, nu oprim aplicația
        pass


_ensure_indexes()


def save_weather_record(cache_key: str, payload: Dict[str, Any]) -> None:
    """
    Salvează un document cu datele meteo în MongoDB.
    Include câmpul 'created_at' (epochtime) pentru verificarea TTL-ului cache-ului.
    """
    doc = {
        **payload,
        "cache_key": cache_key,
        "created_at": time.time(),  # setat ultimul, pentru a evita suprascrieri accidentale
    }
    _collection.insert_one(doc)


def get_weather_history(city: str, limit: int = 50, hours: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Returnează istoricul meteo pentru un oraș.

    Logică:
      - folosim 'cache_key' (oraș în lowercase) pentru consistență și performanță
      - (fallback) suportăm și potrivire pe 'city' pentru înregistrări vechi/heterogene
      - dacă 'hours' este setat, filtrăm după 'created_at' >= now - hours*3600
      - sortare descrescătoare după 'created_at' pentru „cel mai nou mai întâi”
    """
    cache_key = (city or "").strip().lower()
    if not cache_key:
        return []

    query: Dict[str, Any] = {
        "$or": [
            {"cache_key": cache_key},
            # fallback pentru înregistrări vechi fără cache_key consecvent
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
    ).sort("created_at", DESCENDING).limit(int(limit))

    return list(cursor)


def get_latest_weather_record(cache_key: str) -> Optional[Dict[str, Any]]:
    """
    Returnează cel mai recent document pentru un cache_key (pentru cache TTL).
    """
    doc = _collection.find_one(
        {"cache_key": (cache_key or "").strip().lower()},
        {"_id": 0},
        sort=[("created_at", DESCENDING)],
    )
    return doc