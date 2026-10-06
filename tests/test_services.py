import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from pypdf import PdfReader
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Article, Edition, Feed
from app.printing import CupsPrintProvider
from app.rss import fetch_feed
from app.services import generate_edition
from app.weather import OpenMeteoProvider


class TestWeather:
    def current(self, city, latitude, longitude):
        from app.weather import Weather

        return Weather(city, "2026-10-06", 12, 8, 16, "Éclaircies", 10)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_demo_feed_is_parsed_and_saved(self):
        feed = Feed(name="Démo", url="mock://demo")
        self.db.add(feed)
        self.db.commit()
        self.assertEqual(fetch_feed(feed, self.db), 4)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Article).where(Article.feed_id == feed.id)), 4)
        self.assertEqual(feed.last_status, "OK")
        self.assertTrue(all("<" not in article.summary for article in feed.articles))

    def test_public_feed_failures_are_recorded_without_raising(self):
        feed = Feed(name="Privé", url="http://127.0.0.1/private.xml")
        self.db.add(feed)
        self.db.commit()
        self.assertEqual(fetch_feed(feed, self.db), 0)
        self.assertEqual(feed.last_status, "Erreur")
        self.assertIn("privé", feed.last_error.lower())

    def test_weather_api_failure_returns_fallback(self):
        with patch("app.weather.urlopen", side_effect=TimeoutError("offline")):
            weather = OpenMeteoProvider().current("Paris", 48.8566, 2.3522)
        self.assertEqual(weather.city, "Paris")
        self.assertEqual(weather.condition, "Météo indisponible")
        self.assertIsNone(weather.temperature)

    def test_cups_command_uses_duplex_and_isolated_provider(self):
        provider = CupsPrintProvider()
        with (
            tempfile.NamedTemporaryFile(suffix=".pdf") as pdf,
            patch.object(provider, "printers", return_value=["Office"]),
            patch("app.printing.subprocess.run") as run,
        ):
            run.return_value.stdout = "job queued"
            run.return_value.check_returncode = lambda: None
            message = provider.print_pdf(pdf.name, "Office", copies=2, duplex=True)
        command = run.call_args.args[0]
        self.assertIn("sides=two-sided-long-edge", command)
        self.assertIn("-n", command)
        self.assertEqual(message, "job queued")

    def test_generation_writes_a4_pdf_and_archive_record(self):
        zone = ZoneInfo("Europe/Paris")
        today = datetime.now(zone).date()
        published = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=zone) + timedelta(hours=9)
        feed = Feed(name="Journal local", url="mock://demo", category="France", weight=1, priority=1)
        self.db.add(feed)
        self.db.flush()
        for index in range(4):
            self.db.add(
                Article(
                    feed_id=feed.id,
                    title=f"Titre de une numéro {index} et nouvelles du jour",
                    url=f"https://news.test/{index}",
                    summary="Résumé éditorial de longueur suffisante pour la lecture papier.",
                    published_at=published,
                )
            )
        self.db.commit()
        with tempfile.TemporaryDirectory() as directory, patch("app.services.PDF_DIR", Path(directory)):
            edition = generate_edition(self.db, edition_date=today, weather_provider=TestWeather())
            reader = PdfReader(edition.pdf_path)
            self.assertTrue(Path(edition.pdf_path).read_bytes().startswith(b"%PDF-"))
            self.assertEqual(len(reader.pages), edition.page_count)
            self.assertGreaterEqual(edition.page_count, 1)
            self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 595.28, delta=1)
            self.assertAlmostEqual(float(reader.pages[0].mediabox.height), 841.89, delta=1)
            self.assertEqual(edition.article_count, 4)
            self.assertIsNotNone(self.db.scalar(select(Edition).where(Edition.edition_date == today)))

    def test_no_feeds_or_candidates_produces_an_edition(self):
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        with tempfile.TemporaryDirectory() as directory, patch("app.services.PDF_DIR", Path(directory)):
            edition = generate_edition(self.db, edition_date=today, weather_provider=TestWeather())
            self.assertEqual(edition.article_count, 0)
            self.assertEqual(edition.status, "ready")
            self.assertTrue(Path(edition.pdf_path).is_file())

    def test_generation_handles_multiple_rubric_sections(self):
        zone = ZoneInfo("Europe/Paris")
        today = datetime.now(zone).date()
        published = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=zone) + timedelta(hours=9)
        feed = Feed(name="Revue", url="mock://demo", category="Divers", weight=1)
        titles = [
            "Technologie : nouvel outil numérique disponible",
            "Sciences : les chercheurs publient leurs résultats",
            "Économie : les marchés révisent leurs prévisions",
            "Culture : un festival annonce son programme",
            "Sport : le tournoi entre dans sa dernière phase",
            "International : les dirigeants se réunissent en Europe",
            "France : le gouvernement présente son calendrier",
            "Une enquête locale révèle une nouvelle tendance",
        ]
        self.db.add(feed)
        self.db.flush()
        for index, title in enumerate(titles):
            self.db.add(
                Article(
                    feed_id=feed.id,
                    title=title,
                    url=f"https://news.test/rubrique-{index}",
                    summary="Résumé court de la dépêche pour le journal.",
                    published_at=published,
                )
            )
        self.db.commit()
        with tempfile.TemporaryDirectory() as directory, patch("app.services.PDF_DIR", Path(directory)):
            edition = generate_edition(self.db, edition_date=today, weather_provider=TestWeather())
            self.assertEqual(edition.article_count, len(titles))
            self.assertGreaterEqual(json.loads(edition.report)["sections"], 5)
            self.assertGreaterEqual(edition.page_count, 2)

    def test_pdf_failure_is_recorded_in_edition_history(self):
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("app.services.PDF_DIR", Path(directory)),
            patch("app.services.HTML.render", side_effect=RuntimeError("renderer unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "renderer unavailable"):
                generate_edition(self.db, edition_date=today, weather_provider=TestWeather())
            edition = self.db.scalar(select(Edition).where(Edition.edition_date == today))
        self.assertEqual(edition.status, "error")
        self.assertIn("renderer unavailable", edition.error)
        self.assertEqual(edition.page_count, 0)


if __name__ == "__main__":
    unittest.main()
