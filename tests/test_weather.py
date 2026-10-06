import io
import json
import unittest
from datetime import UTC, date, datetime
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from app.weather import OpenWeatherProvider


class WeatherTests(unittest.TestCase):
    def test_openweather_forecast_selects_morning_and_afternoon(self):
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
            "city": {"name": "Paris", "timezone": 7200},
            "list": [item(9, 11.5, 0.2, "pluie faible"), item(15, 18.0, 0.65, "ciel dégagé")],
        }
        with patch("app.weather.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as request:
            forecast = OpenWeatherProvider(api_key="test-key").forecast(3029241, "Paris", day, "Europe/Paris")

        self.assertEqual(forecast.morning.temperature, 11.5)
        self.assertEqual(forecast.morning.precipitation_probability, 20)
        self.assertEqual(forecast.morning.condition, "Pluie faible")
        self.assertEqual(forecast.afternoon.temperature, 18.0)
        self.assertEqual(forecast.afternoon.precipitation_probability, 65)
        request_url = request.call_args.args[0]
        self.assertIn("api.openweathermap.org", request_url)
        self.assertEqual(parse_qs(urlsplit(request_url).query)["id"], ["3029241"])
        self.assertNotIn("lat", parse_qs(urlsplit(request_url).query))

    def test_missing_key_and_provider_failure_return_fallback(self):
        day = date(2026, 10, 6)
        forecast = OpenWeatherProvider(api_key="").forecast(3029241, "Paris", day, "Europe/Paris")
        self.assertEqual(forecast.morning.condition, "Prévision indisponible")

        with patch("app.weather.urlopen", side_effect=TimeoutError):
            failed = OpenWeatherProvider(api_key="test-key").forecast(3029241, "Paris", day, "Europe/Paris")
        self.assertEqual(failed.afternoon.condition, "Prévision indisponible")


if __name__ == "__main__":
    unittest.main()
