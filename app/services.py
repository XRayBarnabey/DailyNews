from __future__ import annotations

import base64
import io
import json
import logging
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session
from weasyprint import CSS, HTML

from app.calendar import fete_du_jour, format_french_date
from app.config import PDF_DIR, TIMEZONE
from app.models import Article, Edition, Feed, Setting
from app.newsroom.selection import CandidateArticle, FeedQuota, select_articles
from app.weather import OpenWeatherProvider, WeatherProvider

logger = logging.getLogger(__name__)
TEMPLATE_DIR = Path(__file__).parent / "templates"
SECTIONS = ["À la une", "France", "International", "Économie", "Technologie", "Sciences", "Culture", "Sport", "Divers"]
DEFAULT_SETTINGS = {
    "newspaper_name": "Le Quotidien",
    "timezone": TIMEZONE,
    "city": "Paris",
    "latitude": "48.8566",
    "longitude": "2.3522",
    "maximum_articles": "32",
    "minimum_articles": "12",
    "period_days": "1",
    "paper_size": "A4",
    "columns": "2",
    "max_pages": "4",
    "show_images": "false",
    "show_descriptions": "true",
    "show_source_url": "false",
    "show_qr_codes": "false",
    "weather_locations": '[{"name":"Paris","city_id":2988507}]',
}


def _qr_data_uri(url: str) -> str:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_L

    code = qrcode.QRCode(error_correction=ERROR_CORRECT_L, box_size=2, border=1)
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def settings_dict(db: Session) -> dict[str, str]:
    values = DEFAULT_SETTINGS.copy()
    values.update({setting.key: setting.value for setting in db.scalars(select(Setting)).all()})
    return values


def save_settings(db: Session, values: dict[str, str]) -> None:
    allowed = set(DEFAULT_SETTINGS)
    for key, value in values.items():
        if key not in allowed:
            continue
        setting = db.get(Setting, key)
        if setting is None:
            stored_value = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value)
            db.add(Setting(key=key, value=stored_value))
        else:
            setting.value = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value)
    db.commit()


def classify(article: Article, feed: Feed) -> str:
    categories = f"{article.categories} {article.title} {article.summary}".casefold()
    keywords = {
        "Technologie": ("technologie", "logiciel", "numérique", "cyber", "intelligence artificielle", "smartphone"),
        "Sciences": ("science", "recherche", "laboratoire", "climat", "espace", "santé"),
        "Économie": ("économie", "marché", "entreprise", "emploi", "finance", "inflation"),
        "Culture": ("culture", "cinéma", "livre", "musique", "exposition", "festival"),
        "Sport": ("sport", "football", "rugby", "tennis", "olympique", "match"),
        "International": ("international", "monde", "europe", "états-unis", "guerre", "sommet"),
        "France": ("france", "français", "paris", "gouvernement", "assemblée", "région"),
    }
    if feed.category in SECTIONS and feed.category != "Divers":
        return feed.category
    return next((section for section, terms in keywords.items() if any(term in categories for term in terms)), "Divers")


def generate_edition(
    db: Session,
    *,
    force: bool = False,
    edition_date: date | None = None,
    weather_provider: WeatherProvider | None = None,
) -> Edition:
    settings = settings_dict(db)
    timezone_name = settings.get("timezone", TIMEZONE)
    zone = ZoneInfo(timezone_name)
    edition_date = edition_date or datetime.now(zone).date()
    existing = db.scalar(select(Edition).where(Edition.edition_date == edition_date))
    if existing and not force and existing.status == "ready" and Path(existing.pdf_path).is_file():
        return existing
    local_day = edition_date - timedelta(days=max(1, int(settings.get("period_days", "1"))))
    start = datetime.combine(local_day, time.min, tzinfo=zone)
    end = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=zone) - timedelta(microseconds=1)
    feeds = db.scalars(select(Feed).where(Feed.active.is_(True))).all()
    quotas = [
        FeedQuota(feed.id, feed.name, feed.weight, feed.priority, feed.minimum, feed.maximum, feed.active)
        for feed in feeds
    ]
    articles = db.scalars(select(Article).join(Feed).where(Feed.active.is_(True))).all()
    candidates = [
        CandidateArticle(
            article.id,
            article.feed_id,
            article.title,
            article.url,
            article.published_at,
            article.summary,
            article.image_url,
        )
        for article in articles
    ]
    selected = select_articles(
        candidates,
        quotas,
        period_start=start,
        period_end=end,
        maximum_total=int(settings["maximum_articles"]),
        minimum_total=int(settings["minimum_articles"]),
    )
    selected_by_id = {article.id: article for article in articles}
    selected_rows = [selected_by_id[item.id] for item in selected]
    feeds_by_id = {feed.id: feed for feed in feeds}
    if settings.get("show_images") == "true":
        from app.rss import download_image

        image_dir = PDF_DIR / "assets"
        for article in selected_rows[:8]:
            article.local_image = download_image(article.image_url, image_dir)
    try:
        weather_locations = json.loads(settings["weather_locations"])
    except (KeyError, json.JSONDecodeError):
        weather_locations = []
    if not weather_locations:
        weather_locations = [
            {"name": settings["city"], "latitude": settings["latitude"], "longitude": settings["longitude"]}
        ]
    provider = weather_provider or OpenWeatherProvider()
    weather_reports = [
        provider.forecast(
            city_id=location.get("city_id"),
            city=location.get("name") or f"Ville {location.get('city_id', '')}",
            forecast_date=edition_date,
            timezone_name=timezone_name,
            latitude=float(location["latitude"]) if location.get("latitude") is not None else None,
            longitude=float(location["longitude"]) if location.get("longitude") is not None else None,
        )
        for location in weather_locations[:10]
    ]
    name_day = fete_du_jour(edition_date)
    if settings.get("show_qr_codes") == "true":
        for article in selected_rows:
            article.qr_code = _qr_data_uri(article.url)
    report_data = {
        "feeds_analyzed": len(feeds),
        "articles_retrieved": len(articles),
        "articles_in_period": sum(
            start
            <= (
                item.published_at.replace(tzinfo=UTC)
                if item.published_at and item.published_at.tzinfo is None
                else item.published_at
            )
            <= end
            for item in articles
            if item.published_at
        ),
        "articles_selected": len(selected_rows),
        "sections": len({classify(article, feeds_by_id[article.feed_id]) for article in selected_rows}),
        "by_feed": dict(Counter(feeds_by_id[item.feed_id].name for item in selected_rows)),
        "minimum_reached": len(selected_rows) >= int(settings["minimum_articles"]),
    }
    environment = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))
    output_path = PDF_DIR / f"{edition_date.isoformat()}.pdf"
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("PDF generation started", extra={"edition": edition_date.isoformat(), "articles": len(selected_rows)})
    try:
        ranked_rows = selected_rows
        limit = max(1, int(settings["max_pages"]))
        low, high = 0, len(ranked_rows)
        best_rendered = None
        best_count = -1
        while low <= high:
            article_count = (low + high) // 2
            selected_rows = ranked_rows[:article_count]
            html_content = environment.get_template("newspaper.html").render(
                name=settings["newspaper_name"],
                edition_date=edition_date,
                articles=selected_rows,
                weather=weather_reports,
                settings=settings,
                feeds=feeds_by_id,
                timezone_name=timezone_name,
                french_date=format_french_date(edition_date),
                name_day=name_day,
            )
            rendered = HTML(string=html_content, base_url=str(TEMPLATE_DIR)).render(
                stylesheets=[CSS(filename=str(TEMPLATE_DIR / "newspaper.css"))]
            )
            if len(rendered.pages) <= limit:
                best_rendered = rendered
                best_count = article_count
                low = article_count + 1
            else:
                high = article_count - 1
        if best_rendered is None:
            raise ValueError("La météo et l’en-tête dépassent à eux seuls la limite de pages.")
        selected_rows = ranked_rows[:best_count]
        rendered = best_rendered
        report_data["articles_selected"] = len(selected_rows)
        report_data["by_feed"] = dict(Counter(feeds_by_id[item.feed_id].name for item in selected_rows))
        report_data["minimum_reached"] = len(selected_rows) >= int(settings["minimum_articles"])
        rendered.write_pdf(output_path)
    except Exception as exc:
        if existing is None:
            existing = Edition(edition_date=edition_date, pdf_path=str(output_path))
            db.add(existing)
        existing.generated_at = datetime.now(UTC)
        existing.article_count = len(selected_rows)
        existing.page_count = 0
        existing.pdf_path = str(output_path)
        existing.status = "error"
        existing.error = str(exc)[:1000]
        existing.report = json.dumps(report_data, ensure_ascii=False)
        db.commit()
        logger.exception("PDF generation failed", extra={"edition": edition_date.isoformat(), "error": str(exc)})
        raise
    if existing is None:
        existing = Edition(edition_date=edition_date, pdf_path=str(output_path))
        db.add(existing)
    existing.generated_at = datetime.now(UTC)
    existing.article_count = len(selected_rows)
    existing.page_count = len(rendered.pages)
    existing.pdf_path = str(output_path)
    existing.status = "ready"
    existing.error = None
    existing.report = json.dumps(report_data, ensure_ascii=False)
    db.commit()
    logger.info("PDF generated", extra={"edition": edition_date.isoformat(), "pages": len(rendered.pages)})
    return existing
