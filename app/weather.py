from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import urlopen

from app.config import OPENMETEO_API_KEY

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WeatherPeriod:
    temperature: float | None = None
    precipitation_probability: int | None = None
    condition: str = "Prévision indisponible"
    icon: str = "?"


@dataclass(frozen=True, slots=True)
class Weather:
    city: str
    date: str
    morning: WeatherPeriod
    afternoon: WeatherPeriod


class WeatherProvider(Protocol):
    def forecast(
        self,
        city: str,
        latitude: float,
        longitude: float,
        forecast_date: date,
        timezone_name: str,
    ) -> Weather: ...


class OpenMeteoProvider:
    def __init__(self, api_key: str | None = None):
        self.api_key = OPENMETEO_API_KEY if api_key is None else api_key

    def forecast(
        self,
        city: str,
        latitude: float,
        longitude: float,
        forecast_date: date,
        timezone_name: str,
    ) -> Weather:
        unavailable = Weather(city, forecast_date.isoformat(), WeatherPeriod(), WeatherPeriod())
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "past_days": 1,
            "forecast_days": 2,
            "timezone": timezone_name or "auto",
        }
        endpoint = "https://api.open-meteo.com/v1/forecast"
        if self.api_key:
            endpoint = "https://customer-api.open-meteo.com/v1/forecast"
            params["apikey"] = self.api_key
        query = urlencode(params)
        try:
            with urlopen(f"{endpoint}?{query}", timeout=6) as response:
                data = json.loads(response.read(500_000))
            hourly = data["hourly"]
            forecasts = []
            for index, timestamp in enumerate(hourly.get("time", [])):
                local_time = datetime.fromisoformat(timestamp)
                if local_time.date() == forecast_date:
                    forecasts.append(
                        (
                            local_time,
                            hourly.get("temperature_2m", [None])[index],
                            hourly.get("precipitation_probability", [None])[index],
                            hourly.get("weather_code", [None])[index],
                        )
                    )
            return Weather(
                city,
                forecast_date.isoformat(),
                self._period(forecasts, forecast_date, time(9), (6, 12)),
                self._period(forecasts, forecast_date, time(15), (12, 21)),
            )
        except Exception as exc:
            logger.warning("Open-Meteo provider unavailable", extra={"city": city, "error": type(exc).__name__})
            return unavailable

    @staticmethod
    def _period(forecasts, forecast_date, target_time, hour_range) -> WeatherPeriod:
        start = datetime.combine(forecast_date, time(hour_range[0]))
        end = datetime.combine(forecast_date, time(hour_range[1]))
        candidates = [entry for entry in forecasts if start <= entry[0] < end]
        if not candidates:
            return WeatherPeriod()
        target = datetime.combine(forecast_date, target_time)
        _, temperature, probability, code = min(candidates, key=lambda entry: abs(entry[0] - target))
        conditions = {
            0: ("Ciel dégagé", "☀"),
            1: ("Peu nuageux", "◐"),
            2: ("Éclaircies", "◐"),
            3: ("Couvert", "☁"),
            45: ("Brouillard", "≋"),
            48: ("Brouillard givrant", "≋"),
            51: ("Bruine", "☂"),
            53: ("Bruine", "☂"),
            55: ("Bruine forte", "☂"),
            56: ("Bruine verglaçante", "❄"),
            57: ("Bruine verglaçante", "❄"),
            61: ("Pluie faible", "☂"),
            63: ("Pluie", "☂"),
            65: ("Forte pluie", "☔"),
            66: ("Pluie verglaçante", "❄"),
            67: ("Pluie verglaçante", "❄"),
            71: ("Neige faible", "❄"),
            73: ("Neige", "❄"),
            75: ("Forte neige", "❄"),
            77: ("Grains de neige", "❄"),
            80: ("Averses faibles", "☂"),
            81: ("Averses", "☂"),
            82: ("Fortes averses", "☔"),
            85: ("Averses de neige", "❄"),
            86: ("Fortes averses de neige", "❄"),
            95: ("Orage", "⚡"),
            96: ("Orage et grêle", "⚡"),
            99: ("Orage et forte grêle", "⚡"),
        }
        condition, icon = conditions.get(code, ("Conditions variables", "☁"))
        return WeatherPeriod(
            temperature=temperature,
            precipitation_probability=probability,
            condition=condition,
            icon=icon,
        )
