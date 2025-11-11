# 🌦 Weather gRPC Microservice

A simple yet complete weather microservice built in **Python**, using **gRPC**, **Flask**, **MongoDB**, and **Docker Compose**.  
It fetches live weather data from [OpenWeatherMap](https://openweathermap.org/), stores results in MongoDB, and provides both a REST API and a simple frontend UI for visualization.

---

## 🧭 Project Overview

### 🎯 Goal
Build a client-server architecture using gRPC in Python:
- The **gRPC server** communicates with OpenWeatherMap API.
- The **Flask API** exposes REST endpoints and a web interface.
- **MongoDB** stores historical weather data for caching and visualization.

### 🧱 Architecture
User (Browser)

│

▼
Flask API + UI  (port 8000)

│

▼
gRPC Server (port 50051)

│

▼
OpenWeatherMap API

│

▼
MongoDB (port 27017)

---

## 🚀 Getting Started

### 1️⃣ Clone the repository
```bash
git clone https://github.com/Iulius2002/weather-grpc-service.git
cd weather-grpc-service

```
### 2️⃣ Create your .env file

Copy the example configuration:
```bash
cp .env.example .env
```
Then edit .env and set your own OpenWeatherMap API key:

```bash
OPENWEATHER_API_KEY=your-api-key-here
```
You can get a free key from 👉 https://openweathermap.org/api

### 4️⃣ Open the application

Visit the frontend in your browser:

👉 http://localhost:8000


### ⚙️ Environment Variables

All configuration is handled through the .env file.

| Variable | Description | Default |
|-----------|--------------|----------|
| `OPENWEATHER_API_KEY` | Your OpenWeatherMap API key | *(required)* |
| `MONGO_URI` | MongoDB connection URI | `mongodb://mongo:27017` |
| `MONGO_DB_NAME` | Database name | `weather_db` |
| `MONGO_COLLECTION_NAME` | Collection name | `weather_history` |
| `GRPC_API_KEY` | API key required to access gRPC endpoints | `super-secret-key` |
| `CACHE_TTL_SECONDS` | Cache lifetime for weather data (in seconds) | `300` |
| `GRPC_SERVER_ADDRESS` | Host:port for gRPC server | `weather-grpc-server:50051` |


### Components

| Service | Description | Port |
|----------|--------------|------|
| 🧠 `weather-grpc-server` | gRPC microservice that fetches live weather data and saves results in MongoDB | 50051 |
| 🌐 `weather-api` | Flask-based REST API and web UI for users | 8000 |
| 💾 `weather-mongo` | MongoDB instance storing historical weather data | 27017 |


## 🧠 Features

### ✅ Core
	•	Live weather data from OpenWeatherMap
	•	gRPC communication between client and server
	•	REST API via Flask
	•	MongoDB integration for data persistence

### 🌡️ Caching & Performance
	•	Smart local cache with CACHE_TTL_SECONDS
	•	Automatically refreshes stale weather data
	•	Avoids redundant API calls to OpenWeatherMap

### 🗓️ Forecast
	•	Displays temperature predictions for the next hours/days using OpenWeather’s forecast endpoint
	•	Data visualized in charts

### 📊 Web UI
	•	Search weather by city name
	•	View current conditions & temperature fluctuations
	•	Interactive chart for historical data
	•	Time range filtering (e.g., last 6h, 12h, 24h, or full history)

### 🔐 Security
	•	gRPC endpoints protected with API key (x-api-key metadata header)

⸻

### 🧪 Testing

You can run all Python unit tests locally:
```bash
pytest
```
Tests cover:
	•	gRPC logic 
	•	cache validation
	•	MongoDB storage and retrieval
	•	Flask API endpoints

## 🐳 Docker Setup

All services are containerized and orchestrated with Docker Compose.

Services Overview:

```yaml
services:
  weather-grpc-server:
    build:
      context: .
      dockerfile: Dockerfile.grpc_server
    ports:
      - "50051:50051"
    env_file: .env
    depends_on:
      - weather-mongo

  weather-api:
    build:
      context: .
      dockerfile: Dockerfile.api
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - weather-grpc-server
      - weather-mongo

  weather-mongo:
    image: mongo:latest
    container_name: weather-mongo
    volumes:
      - mongo_data:/data/db
    ports:
      - "27017:27017"

volumes:
  mongo_data:
```

## 🧰 Development Tips
Rebuild only one service:
```bash
docker compose build weather-api
docker compose up weather-api
```

To view MongoDB data:
```bash 
docker exec -it weather-mongo mongosh
use weather_db
db.weather_history.find().pretty()
```

To clean up containers & volumes:
```bash
docker compose down -v
```

## 💡 Example Usage

### 1️⃣ Run the app
```bash
docker compose up --build
```

### 2️⃣ Open http://localhost:8000

### 3️⃣ Search “Bucharest”

Output example in UI:
```bash
Weather for Bucharest:
Temperature: 18.6 °C
Humidity: 82%
Conditions: light rain
Wind Speed: 4.6 m/s
```

### 4️⃣ View chart of temperature history
Select range: last 6h / 24h / full history

If no data exists, the app fetches and caches automatically

## Project Structure
````
weather-grpc-service/
│
├── api/
│   ├── app.py                  # Flask REST API + UI
│
├── server/
│   ├── weather_server.py       # gRPC server implementation
│   ├── db.py                   # MongoDB logic
│
├── proto/
│   ├── weather.proto           # gRPC schema
│   ├── weather_pb2.py
│   ├── weather_pb2_grpc.py
│
├── templates/
│   └── index.html              # Frontend template
│
├── Dockerfile.api
├── Dockerfile.grpc_server
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md

````