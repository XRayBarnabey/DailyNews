import importlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Edition, PrintJob

bootstrap_module = importlib.import_module("app.bootstrap")
main_module = importlib.import_module("app.main")
scheduler_module = importlib.import_module("app.scheduler")
app = main_module.app


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls.patches = [
            patch.object(main_module, "SessionLocal", cls.session_factory),
            patch.object(scheduler_module, "SessionLocal", cls.session_factory),
            patch.object(bootstrap_module, "engine", cls.engine),
        ]
        for item in cls.patches:
            item.start()

        def override_db():
            with cls.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        app.dependency_overrides.clear()
        for item in reversed(cls.patches):
            item.stop()
        cls.engine.dispose()

    def test_admin_pages_require_authentication(self):
        self.assertEqual(self.client.get("/").status_code, 401)
        response = self.client.get("/", auth=("admin", "change-me"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("DailyNews", response.text)

    def test_demo_feed_api_can_fetch_and_report_articles(self):
        auth = ("admin", "change-me")
        feeds = self.client.get("/api/feeds", auth=auth)
        self.assertEqual(feeds.status_code, 200)
        demo = next(feed for feed in feeds.json() if feed["url"] == "mock://demo")
        result = self.client.post(f"/api/feeds/{demo['id']}/test", auth=auth)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["articles"], 4)

    def test_edition_can_be_regenerated_and_deleted_with_its_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "edition.pdf"
            pdf_path.write_bytes(b"%PDF-test")
            with self.session_factory() as session:
                edition = Edition(edition_date=date(2026, 10, 5), pdf_path=str(pdf_path), status="ready")
                session.add(edition)
                session.flush()
                edition_id = edition.id
                session.add(PrintJob(edition_id=edition_id, printer_name="Test", copies=1, status="terminée"))
                session.commit()
            with patch.object(main_module, "generate_edition", return_value=edition) as generate:
                response = self.client.post(f"/api/editions/{edition_id}/regenerate", auth=("admin", "change-me"))
            self.assertEqual(response.status_code, 200)
            generate.assert_called_once()
            with patch.object(main_module, "PDF_DIR", Path(directory)):
                deleted = self.client.delete(f"/api/editions/{edition_id}", auth=("admin", "change-me"))
            self.assertEqual(deleted.status_code, 204)
            self.assertFalse(pdf_path.exists())
            with self.session_factory() as session:
                self.assertIsNone(session.get(Edition, edition_id))
                self.assertEqual(session.query(PrintJob).filter_by(edition_id=edition_id).count(), 0)

    def test_edition_page_shows_last_print_job_message(self):
        auth = ("admin", "change-me")
        with self.session_factory() as session:
            edition = Edition(edition_date=date(2026, 10, 6), pdf_path="/tmp/none.pdf", status="ready")
            session.add(edition)
            session.flush()
            edition_id = edition.id
            session.commit()
        page = self.client.get(f"/editions/{edition_id}", auth=auth)
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("Dernière impression", page.text)
        with self.session_factory() as session:
            session.add(PrintJob(edition_id=edition_id, printer_name="P", status="terminée"))
            session.add(PrintJob(edition_id=edition_id, printer_name="P", status="erreur", message="lp: boom"))
            session.commit()
        page = self.client.get(f"/editions/{edition_id}", auth=auth)
        self.assertIn("Dernière impression : erreur", page.text)
        self.assertIn("lp: boom", page.text)

    def test_settings_api_saves_multiple_weather_locations_and_page_options(self):
        payload = {
            "newspaper_name": "Le Quotidien",
            "timezone": "Europe/Paris",
            "maximum_articles": 30,
            "minimum_articles": 5,
            "period_days": 1,
            "columns": 3,
            "max_pages": 2,
            "show_qr_codes": True,
            "show_descriptions": True,
            "weather_locations": [
                {"name": "Paris", "latitude": 48.8566, "longitude": 2.3522, "timezone": "Europe/Paris"},
                {"name": "Lyon", "latitude": 45.764, "longitude": 4.8357, "timezone": "Europe/Paris"},
            ],
        }
        response = self.client.put("/api/settings", auth=("admin", "change-me"), json=payload)
        self.assertEqual(response.status_code, 200)
        saved = response.json()
        self.assertEqual(saved["max_pages"], "2")
        self.assertEqual([location["name"] for location in saved["weather_locations"]], ["Paris", "Lyon"])
        self.assertEqual(saved["columns"], "3")
        self.assertEqual(saved["show_qr_codes"], "true")

    def test_settings_form_persists_weather_locations_and_page_options(self):
        locations = [
            {"name": "Paris", "latitude": 48.8566, "longitude": 2.3522, "timezone": "Europe/Paris"},
            {"name": "Lyon", "latitude": 45.764, "longitude": 4.8357, "timezone": "Europe/Paris"},
        ]
        response = self.client.post(
            "/settings",
            auth=("admin", "change-me"),
            data={
                "newspaper_name": "Le Quotidien",
                "timezone": "Europe/Paris",
                "weather_locations_json": json.dumps(locations),
                "maximum_articles": "30",
                "minimum_articles": "5",
                "period_days": "1",
                "columns": "3",
                "max_pages": "2",
                "show_qr_codes": "on",
                "show_descriptions": "on",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        saved = self.client.get("/api/settings", auth=("admin", "change-me")).json()
        self.assertEqual([location["name"] for location in saved["weather_locations"]], ["Paris", "Lyon"])
        self.assertEqual(saved["max_pages"], "2")
        self.assertEqual(saved["columns"], "3")
        self.assertEqual(saved["show_qr_codes"], "true")

    def test_city_search_returns_openmeteo_geocoding_suggestions(self):
        payload = {
            "results": [
                {
                    "name": "Caen",
                    "admin1": "Normandie",
                    "country": "France",
                    "country_code": "FR",
                    "latitude": 49.1846,
                    "longitude": -0.3722,
                    "timezone": "Europe/Paris",
                },
                {"name": "Caés", "country_code": "ES", "latitude": 43.4, "longitude": -5.4},
            ]
        }
        with patch("app.main.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            response = self.client.get("/api/weather/cities?q=caen", auth=("admin", "change-me"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["name"], "Caen")
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["latitude"], 49.1846)

    def test_version_is_shown_in_footer_and_health(self):
        from app.version import APP_VERSION

        page = self.client.get("/", auth=("admin", "change-me"))
        self.assertIn(APP_VERSION, page.text)
        self.assertEqual(self.client.get("/health").json()["version"], APP_VERSION)

    def test_weather_preview_returns_forecast_for_selected_city(self):
        from app.weather import Weather, WeatherPeriod

        period = WeatherPeriod(temperature=14.0, precipitation_probability=20, condition="Éclaircies", icon="◐")
        forecast = Weather("Caen", "2026-10-06", period, period)
        with patch.object(main_module.OpenMeteoProvider, "forecast", return_value=forecast):
            response = self.client.get(
                "/api/weather/preview?name=Caen&latitude=49.18&longitude=-0.36&timezone=Europe/Paris",
                auth=("admin", "change-me"),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["morning"]["temperature"], 14.0)
        bad = self.client.get(
            "/api/weather/preview?name=Caen&latitude=49&longitude=0&timezone=Nope/Zone", auth=("admin", "change-me")
        )
        self.assertEqual(bad.status_code, 422)

    def test_meteo_key_is_configurable_but_never_returned(self):
        payload = {
            "newspaper_name": "Le Quotidien",
            "timezone": "Europe/Paris",
            "maximum_articles": 30,
            "minimum_articles": 5,
            "period_days": 1,
            "columns": 2,
            "max_pages": 4,
            "weather_locations": [{"name": "Caen", "latitude": 49.1846, "longitude": -0.3722}],
            "meteo_api_key": "private-customer-key",
            "title_font": "Liberation Serif",
            "article_font": "DejaVu Sans",
        }
        response = self.client.put("/api/settings", auth=("admin", "change-me"), json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private-customer-key", response.text)
        self.assertTrue(response.json()["meteo_api_key_configured"])
        self.assertEqual(response.json()["title_font"], "Liberation Serif")
        self.assertEqual(response.json()["article_font"], "DejaVu Sans")

    def test_logo_upload_accepts_transparent_png_and_persists_it(self):
        image_buffer = io.BytesIO()
        Image.new("RGBA", (30, 12), (0, 0, 0, 0)).save(image_buffer, format="PNG")
        with tempfile.TemporaryDirectory() as directory, patch.object(main_module, "PDF_DIR", Path(directory)):
            response = self.client.post(
                "/settings/logo",
                auth=("admin", "change-me"),
                files={"file": ("brand.png", image_buffer.getvalue(), "image/png")},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            logo_path = Path(directory) / "branding" / "logo.png"
            self.assertTrue(logo_path.is_file())
            with Image.open(logo_path) as saved_logo:
                self.assertEqual(saved_logo.mode, "RGBA")
                self.assertEqual(saved_logo.getpixel((0, 0))[3], 0)


if __name__ == "__main__":
    unittest.main()
