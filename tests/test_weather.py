import io
import json
import unittest
from datetime import UTC, date, datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from app.weather import OpenMeteoProvider


class WeatherTests(unittest.TestCase):
    def test_openmeteo_keeps_morning_data_when_generated_in_afternoon(self):
        zone = ZoneInfo("Europe/Paris")
        day = date(2026, 10, 6)

        def item(hour, temperature, probability, description):
            local = datetime.combine(day, datetime.min.time(), tzinfo=zone).replace(hour=hour)
            return {
                "dt": int(local.astimezone(UTC).timestamp()),
                "main": {"temp": temperature},
                "pop": probability,
                "weather": [{"description": description}],
            }

        payload = {
            "timezone": "Europe/Paris",
            "hourly": {
                "time": ["2026-10-05T15:00", "2026-10-06T09:00", "2026-10-06T15:00"],
                "temperature_2m": [14.0, 11.5, 18.0],
                "precipitation_probability": [10, 20, 65],
                "weather_code": [1, 61, 0],
            },
        }
        with patch("app.weather.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            forecast = OpenMeteoProvider().forecast("Paris", 48.8, 2.3, day, "Europe/Paris")

        self.assertEqual(forecast.morning.temperature, 11.5)
        self.assertEqual(forecast.morning.precipitation_probability, 20)
        self.assertEqual(forecast.morning.condition, "Pluie faible")
        self.assertEqual(forecast.morning.icon, "☂")
        self.assertEqual(forecast.afternoon.temperature, 18.0)
        self.assertEqual(forecast.afternoon.precipitation_probability, 65)
        request_url = request.call_args.args[0]
        self.assertIn("api.open-meteo.com/v1/forecast", request_url)
        query = parse_qs(urlsplit(request_url).query)
        self.assertEqual(query["past_days"], ["1"])
        self.assertEqual(query["timezone"], ["Europe/Paris"])

    def test_openmeteo_uses_customer_key_when_configured(self):
        day = date(2026, 10, 6)
        payload = {"hourly": {"time": [], "temperature_2m": [], "precipitation_probability": [], "weather_code": []}}
        with patch("app.weather.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            OpenMeteoProvider(api_key="customer-test-key").forecast("Paris", 48.8, 2.3, day, "Europe/Paris")
        request_url = request.call_args.args[0]
        self.assertIn("customer-api.open-meteo.com", request_url)
        self.assertEqual(parse_qs(urlsplit(request_url).query)["apikey"], ["customer-test-key"])

    def test_provider_failure_returns_fallback(self):
        day = date(2026, 10, 6)
        with patch("app.weather.urlopen", side_effect=TimeoutError):
            failed = OpenMeteoProvider().forecast("Paris", 48.8, 2.3, day, "Europe/Paris")
        self.assertEqual(failed.afternoon.condition, "Prévision indisponible")


if __name__ == "__main__":
    unittest.main()
