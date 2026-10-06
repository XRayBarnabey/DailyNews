from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from app.config import OPENWEATHER_API_KEY

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WeatherPeriod:
    temperature: float | None = None
    precipitation_probability: int | None = None
    condition: str = "Prévision indisponible"


@dataclass(frozen=True, slots=True)
class Weather:
    city: str
    date: str
    morning: WeatherPeriod
    afternoon: WeatherPeriod


class WeatherProvider(Protocol):
    def forecast(
        self,
        city_id: int | None,
        city: str,
        forecast_date: date,
        timezone_name: str,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> Weather: ...


class OpenWeatherProvider:
    def __init__(self, api_key: str | None = None):
        self.api_key = OPENWEATHER_API_KEY if api_key is None else api_key

    def forecast(
        self,
        city_id: int | None,
        city: str,
        forecast_date: date,
        timezone_name: str,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> Weather:
        unavailable = Weather(city, forecast_date.isoformat(), WeatherPeriod(), WeatherPeriod())
        if not self.api_key:
            logger.warning("OpenWeather API key is not configured", extra={"city": city})
            return unavailable
        params = {"appid": self.api_key, "units": "metric", "lang": "fr"}
        if city_id is not None:
            params["id"] = city_id
        elif latitude is not None and longitude is not None:
            params.update({"lat": latitude, "lon": longitude})
        else:
            return unavailable
        query = urlencode(params)
        try:
            with urlopen(f"https://api.openweathermap.org/data/2.5/forecast?{query}", timeout=6) as response:
                data = json.loads(response.read(500_000))
            city = data.get("city", {}).get("name") or city
            offset = data.get("city", {}).get("timezone")
            location_timezone = (
                timezone(timedelta(seconds=int(offset))) if offset is not None else ZoneInfo(timezone_name)
            )
            forecasts = []
            for item in data.get("list", []):
                local_time = datetime.fromtimestamp(item["dt"], UTC).astimezone(location_timezone)
                if local_time.date() == forecast_date:
                    forecasts.append((local_time, item))
            morning = self._period(forecasts, forecast_date, time(9), location_timezone, (6, 12))
            afternoon = self._period(forecasts, forecast_date, time(15), location_timezone, (12, 21))
            return Weather(
                city,
                forecast_date.isoformat(),
                morning,
                afternoon,
            )
        except Exception as exc:
            logger.warning("OpenWeather provider unavailable", extra={"city": city, "error": type(exc).__name__})
            return unavailable

    @staticmethod
    def _period(forecasts, forecast_date, target_time, zone, hour_range) -> WeatherPeriod:
        start = datetime.combine(forecast_date, time(hour_range[0]), tzinfo=zone)
        end = datetime.combine(forecast_date, time(hour_range[1]), tzinfo=zone)
        candidates = [entry for entry in forecasts if start <= entry[0] <= end]
        if not candidates:
            return WeatherPeriod()
        target = datetime.combine(forecast_date, target_time, tzinfo=zone)
        _, item = min(candidates, key=lambda entry: abs(entry[0] - target))
        weather = item.get("weather", [{}])[0]
        probability = item.get("pop")
        return WeatherPeriod(
            temperature=item.get("main", {}).get("temp"),
            precipitation_probability=round(probability * 100) if probability is not None else None,
            condition=weather.get("description", "Conditions variables").capitalize(),
        )
