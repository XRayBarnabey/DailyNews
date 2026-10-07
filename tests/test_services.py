import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from pypdf import PdfReader
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.calendar import format_french_date
from app.database import Base
from app.learning import daily_features
from app.models import Article, Edition, Feed, Setting
from app.printing import CupsPrintProvider
from app.rss import fetch_feed
from app.services import generate_edition
from app.weather import OpenMeteoProvider, Weather, WeatherPeriod


class TestWeather:
    __test__ = False

    def __init__(self):
        self.locations = []

    def forecast(self, city, latitude, longitude, forecast_date, timezone_name):
        self.locations.append(city)
        return Weather(
            city,
            forecast_date.isoformat(),
            WeatherPeriod(12, 10, "Éclaircies", "☀"),
            WeatherPeriod(16, 20, "Nuageux", "☁"),
        )


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
            weather = OpenMeteoProvider().forecast(
                "Paris", 48.8566, 2.3522, datetime.now(ZoneInfo("Europe/Paris")).date(), "Europe/Paris"
            )
        self.assertEqual(weather.city, "Paris")
        self.assertEqual(weather.morning.condition, "Prévision indisponible")
        self.assertIsNone(weather.morning.temperature)

    def test_cups_command_uses_duplex_and_isolated_provider(self):
        provider = CupsPrintProvider()
        with (
            tempfile.NamedTemporaryFile(suffix=".pdf") as pdf,
            patch.object(provider, "printers", return_value=["Office"]),
            patch("app.printing.subprocess.run") as run,
        ):
            pdf.write(b"%PDF-1.4 test")
            pdf.flush()
            run.return_value.stdout = b"job queued"
            run.return_value.check_returncode = lambda: None
            message = provider.print_pdf(pdf.name, "Office", copies=2, duplex=True)
        command = run.call_args.args[0]
        self.assertEqual(command[-1], "-")
        self.assertEqual(run.call_args.kwargs["input"], b"%PDF-1.4 test")
        self.assertIn("sides=two-sided-long-edge", command)
        self.assertIn("-n", command)
        self.assertEqual(message, "job queued")

    def test_cups_error_message_includes_stderr(self):
        provider = CupsPrintProvider()
        with (
            tempfile.NamedTemporaryFile(suffix=".pdf") as pdf,
            patch.object(provider, "printers", return_value=["Office"]),
            patch(
                "app.printing.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, ["lp"], stderr=b"lp: Forbidden"),
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                provider.print_pdf(pdf.name, "Office")
        self.assertIn("lp: Forbidden", str(ctx.exception))

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
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("app.services.PDF_DIR", Path(directory)),
            patch("app.services.fete_du_jour", return_value="Saint Bruno"),
        ):
            edition = generate_edition(self.db, edition_date=today, weather_provider=TestWeather())
            reader = PdfReader(edition.pdf_path)
            self.assertTrue(Path(edition.pdf_path).read_bytes().startswith(b"%PDF-"))
            self.assertEqual(len(reader.pages), edition.page_count)
            self.assertGreaterEqual(edition.page_count, 1)
            self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 595.28, delta=1)
            self.assertAlmostEqual(float(reader.pages[0].mediabox.height), 841.89, delta=1)
            self.assertEqual(edition.article_count, 4)
            self.assertIsNotNone(self.db.scalar(select(Edition).where(Edition.edition_date == today)))
            text = " ".join(page.extract_text() or "" for page in reader.pages)
            self.assertNotIn("À LA UNE", text)
            self.assertNotIn("FAITS MARQUANTS", text)
            self.assertIn(format_french_date(today), text)
            self.assertIn("Fête du jour : Saint Bruno", text)

    def test_daily_learning_features_are_deterministic_and_rendered(self):
        settings = {
            "show_daily_vocabulary": "true",
            "vocabulary_language": "pt-BR",
            "show_crossword": "true",
            "crossword_difficulty": "avance",
            "show_it_term": "true",
            "online_content": "false",
        }
        edition_date = datetime(2026, 10, 7).date()
        features = daily_features(edition_date, settings)
        self.assertGreaterEqual(features["crossword"]["word_count"], 5)
        self.assertNotEqual(
            features["vocabulary"]["word"], daily_features(edition_date.replace(day=8), settings)["vocabulary"]["word"]
        )

        self.db.add(Setting(key="show_daily_vocabulary", value="true"))
        self.db.add(Setting(key="vocabulary_language", value="pt-BR"))
        self.db.add(Setting(key="show_crossword", value="true"))
        self.db.add(Setting(key="crossword_difficulty", value="avance"))
        self.db.add(Setting(key="show_it_term", value="true"))
        self.db.add(Setting(key="online_content", value="false"))
        self.db.commit()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("app.services.PDF_DIR", Path(directory)),
            patch("app.services.fete_du_jour", return_value=""),
        ):
            edition = generate_edition(self.db, edition_date=edition_date, weather_provider=TestWeather())
            text = " ".join(page.extract_text() or "" for page in PdfReader(edition.pdf_path).pages)
        self.assertIn(features["vocabulary"]["word"], text)
        self.assertIn("Mots croisés · niveau avancé", text)
        self.assertIn(features["it_term"]["term"], text)
        self.assertNotIn("SEL / EGO / LOT", text)
        self.assertGreaterEqual(json.loads(edition.report)["daily_features"]["crossword"]["word_count"], 5)

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
            self.assertGreaterEqual(edition.page_count, 1)

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

    def test_page_limit_selects_fewer_articles_without_exceeding_cap(self):
        zone = ZoneInfo("Europe/Paris")
        today = datetime.now(zone).date()
        published = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=zone) + timedelta(hours=9)
        feed = Feed(name="Revue", url="mock://demo", category="Divers", weight=1)
        self.db.add_all([feed, Setting(key="max_pages", value="1"), Setting(key="maximum_articles", value="30")])
        self.db.flush()
        for index in range(20):
            self.db.add(
                Article(
                    feed_id=feed.id,
                    title=f"Article {index} : actualité importante du jour",
                    url=f"https://news.test/cap-{index}",
                    summary=("Le résumé détaille cette information et ses conséquences. " * 12),
                    published_at=published,
                )
            )
        self.db.commit()
        with tempfile.TemporaryDirectory() as directory, patch("app.services.PDF_DIR", Path(directory)):
            edition = generate_edition(self.db, edition_date=today, weather_provider=TestWeather())
        self.assertLess(edition.article_count, 20)
        self.assertLessEqual(edition.page_count, 1)

    def test_qr_option_embeds_codes_without_printing_urls(self):
        zone = ZoneInfo("Europe/Paris")
        today = datetime.now(zone).date()
        published = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=zone) + timedelta(hours=9)
        feed = Feed(name="Revue", url="mock://demo", category="Divers", weight=1)
        self.db.add_all([feed, Setting(key="show_qr_codes", value="true")])
        self.db.flush()
        article_url = "https://news.test/qr-destination"
        self.db.add(
            Article(
                feed_id=feed.id,
                title="Un article avec un QR code",
                url=article_url,
                summary="Résumé.",
                published_at=published,
            )
        )
        self.db.commit()
        with tempfile.TemporaryDirectory() as directory, patch("app.services.PDF_DIR", Path(directory)):
            edition = generate_edition(self.db, edition_date=today, weather_provider=TestWeather())
            from pypdf import PdfReader

            reader = PdfReader(edition.pdf_path)
            text = " ".join(page.extract_text() or "" for page in reader.pages)
            embedded_images = [image for page in reader.pages for image in page.images]
        self.assertIn("Un article avec un QR code", text)
        self.assertNotIn(article_url, text)
        self.assertTrue(embedded_images)

    def test_multiple_weather_locations_render_below_title(self):
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        locations = [
            {"name": "Paris", "latitude": 48.8566, "longitude": 2.3522, "timezone": "Europe/Paris"},
            {"name": "Lyon", "latitude": 45.764, "longitude": 4.8357, "timezone": "Europe/Paris"},
        ]
        self.db.add(Setting(key="weather_locations", value=json.dumps(locations)))
        self.db.commit()
        weather = TestWeather()
        with tempfile.TemporaryDirectory() as directory, patch("app.services.PDF_DIR", Path(directory)):
            edition = generate_edition(self.db, edition_date=today, weather_provider=weather)
            from pypdf import PdfReader

            text = " ".join(page.extract_text() or "" for page in PdfReader(edition.pdf_path).pages)
        self.assertEqual(weather.locations, ["Paris", "Lyon"])
        self.assertLess(text.index("Le Quotidien"), text.index("Paris"))
        self.assertIn("Lyon", text)
        self.assertIn("MATIN", text.upper())
        self.assertIn("APRÈS-MIDI", text.upper().replace("\n", ""))

    def test_logo_and_separate_fonts_are_embedded_in_pdf(self):
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        feed = Feed(name="Revue", url="mock://demo", category="Divers", weight=1)
        self.db.add_all(
            [
                feed,
                Setting(key="title_font", value="DejaVu Serif"),
                Setting(key="article_font", value="DejaVu Sans"),
            ]
        )
        self.db.commit()
        with tempfile.TemporaryDirectory() as directory, patch("app.services.PDF_DIR", Path(directory)):
            from PIL import Image

            logo_path = Path(directory) / "branding" / "logo.png"
            logo_path.parent.mkdir(parents=True)
            Image.new("RGBA", (40, 16), (255, 0, 0, 0)).save(logo_path)
            edition = generate_edition(self.db, edition_date=today, weather_provider=TestWeather())
            reader = PdfReader(edition.pdf_path)
            page = reader.pages[0]
            images = [image for page in reader.pages for image in page.images]
            font_names = " ".join(
                str(font.get("/BaseFont", "")) for font in page.get("/Resources").get("/Font").values()
            )
        self.assertTrue(images)
        self.assertIn("DejaVu-Serif", font_names)
        self.assertIn("DejaVu-Sans", font_names)


if __name__ == "__main__":
    unittest.main()
