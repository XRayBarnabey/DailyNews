import importlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
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
                {"name": "Paris", "latitude": 48.8566, "longitude": 2.3522},
                {"name": "Lyon", "latitude": 45.764, "longitude": 4.8357},
            ],
        }
        response = self.client.put("/api/settings", auth=("admin", "change-me"), json=payload)
        self.assertEqual(response.status_code, 200)
        saved = response.json()
        self.assertEqual(saved["max_pages"], "2")
        self.assertEqual(json.loads(json.dumps(saved["weather_locations"])), payload["weather_locations"])
        self.assertEqual(saved["columns"], "3")
        self.assertEqual(saved["show_qr_codes"], "true")

    def test_settings_form_persists_weather_locations_and_page_options(self):
        locations = [
            {"name": "Paris", "latitude": 48.8566, "longitude": 2.3522},
            {"name": "Lyon", "latitude": 45.764, "longitude": 4.8357},
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
        self.assertEqual(saved["weather_locations"], locations)
        self.assertEqual(saved["max_pages"], "2")
        self.assertEqual(saved["columns"], "3")
        self.assertEqual(saved["show_qr_codes"], "true")


if __name__ == "__main__":
    unittest.main()
