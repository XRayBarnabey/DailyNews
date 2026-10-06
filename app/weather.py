from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import urlopen

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Weather:
    city: str
    date: str
    temperature: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    condition: str = "Météo indisponible"
    precipitation_probability: int | None = None


class WeatherProvider(Protocol):
    def current(self, city: str, latitude: float, longitude: float) -> Weather: ...


class OpenMeteoProvider:
    def current(self, city: str, latitude: float, longitude: float) -> Weather:
        query = urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max",
                "forecast_days": 1,
                "timezone": "auto",
            }
        )
        try:
            with urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=5) as response:
                data = json.loads(response.read(200_000))
            current, daily = data.get("current", {}), data.get("daily", {})
            code = int(current.get("weather_code", -1))
            conditions = {
                0: "Ciel dégagé",
                1: "Peu nuageux",
                2: "Éclaircies",
                3: "Couvert",
                45: "Brouillard",
                48: "Brouillard givrant",
                51: "Bruine",
                61: "Pluie faible",
                63: "Pluie",
                65: "Forte pluie",
                71: "Neige faible",
                73: "Neige",
                80: "Averses",
                95: "Orage",
            }
            return Weather(
                city,
                daily.get("time", [""])[0],
                current.get("temperature_2m"),
                (daily.get("temperature_2m_min") or [None])[0],
                (daily.get("temperature_2m_max") or [None])[0],
                conditions.get(code, "Conditions variables"),
                (daily.get("precipitation_probability_max") or [None])[0],
            )
        except Exception as exc:
            logger.warning("Weather provider unavailable", extra={"error": str(exc)})
            return Weather(city, "", condition="Météo indisponible")
