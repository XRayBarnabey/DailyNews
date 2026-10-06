from __future__ import annotations

import hmac
import io
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode
from urllib.request import Request as URLRequest
from urllib.request import urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bootstrap import initialize
from app.config import ADMIN_PASSWORD, ADMIN_USER, LOG_LEVEL, PDF_DIR, TIMEZONE, ensure_directories
from app.database import SessionLocal, get_db
from app.logging_config import configure_logging
from app.models import Article, Edition, Feed, PrintJob, Schedule
from app.printing import CupsPrintProvider
from app.rss import fetch_all, fetch_feed
from app.scheduler import configure_jobs, start_scheduler, stop_scheduler
from app.services import generate_edition, save_settings, settings_dict
from app.version import APP_VERSION
from app.weather import OpenMeteoProvider

configure_logging(LOG_LEVEL)
logger = logging.getLogger(__name__)
security = HTTPBasic()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_version"] = APP_VERSION


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    valid_user = hmac.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
    valid_password = hmac.compare_digest(credentials.password.encode(), ADMIN_PASSWORD.encode())
    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants invalides",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_directories()
    with SessionLocal() as db:
        initialize(db)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="DailyNews", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
web = APIRouter(dependencies=[Depends(require_admin)])
api = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


class FeedInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    category: str = "Divers"
    weight: float = Field(default=1, ge=0, le=100)
    priority: int = Field(default=0, ge=-10, le=10)
    minimum: int = Field(default=0, ge=0, le=100)
    maximum: int | None = Field(default=None, ge=0, le=100)
    active: bool = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if value != "mock://demo" and not value.startswith(("http://", "https://")):
            raise ValueError("Utilisez une URL HTTP(S) ou mock://demo")
        return value


class GenerateInput(BaseModel):
    force: bool = False


class WeatherLocationInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = "auto"


class SettingsInput(BaseModel):
    newspaper_name: str = Field(min_length=1, max_length=100)
    timezone: str = TIMEZONE
    city: str = "Paris"
    latitude: float = Field(default=48.8566, ge=-90, le=90)
    longitude: float = Field(default=2.3522, ge=-180, le=180)
    maximum_articles: int = Field(ge=1, le=200)
    minimum_articles: int = Field(ge=0, le=200)
    period_days: int = Field(ge=1, le=7)
    columns: int = Field(ge=1, le=3)
    max_pages: int = Field(default=4, ge=1, le=32)
    weather_locations: list[WeatherLocationInput] = Field(
        default_factory=lambda: [
            WeatherLocationInput(name="Paris", latitude=48.8566, longitude=2.3522, timezone="Europe/Paris")
        ],
        min_length=1,
        max_length=10,
    )
    meteo_api_key: str | None = Field(default=None, max_length=300)
    clear_meteo_api_key: bool = False
    title_font: Literal["DejaVu Serif", "DejaVu Sans", "Liberation Serif", "Liberation Sans"] = "DejaVu Serif"
    article_font: Literal["DejaVu Serif", "DejaVu Sans", "Liberation Serif", "Liberation Sans"] = "DejaVu Serif"
    show_images: bool = False
    show_descriptions: bool = True
    show_source_url: bool = False
    show_qr_codes: bool = False


def persist_settings_model(db: Session, values: SettingsInput) -> None:
    stored = {
        key: value if key == "weather_locations" else str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in values.model_dump(exclude={"meteo_api_key", "clear_meteo_api_key"}).items()
    }
    if values.clear_meteo_api_key:
        stored["meteo_api_key"] = ""
    elif values.meteo_api_key and values.meteo_api_key.strip():
        stored["meteo_api_key"] = values.meteo_api_key.strip()
    save_settings(db, stored)


def public_settings(db: Session) -> dict:
    values = settings_dict(db)
    values["weather_locations"] = json.loads(values["weather_locations"])
    values["meteo_api_key_configured"] = bool(values.get("meteo_api_key"))
    values.pop("meteo_api_key", None)
    return values


class ScheduleInput(BaseModel):
    fetch_time: str
    generate_time: str
    print_time: str
    active_days: list[int] = Field(min_length=1, max_length=7)
    auto_generate: bool = True
    auto_print: bool = False
    printer_name: str = ""
    copies: int = Field(default=1, ge=1, le=20)
    duplex: bool = True

    @field_validator("fetch_time", "generate_time", "print_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        try:
            hour, minute = (int(part) for part in value.split(":"))
            if len(value) != 5 or not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
        except ValueError as exc:
            raise ValueError("L'heure doit être au format HH:MM") from exc
        return value


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION}


@web.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    feed_count = db.scalar(select(func.count()).select_from(Feed).where(Feed.active.is_(True))) or 0
    article_count = db.scalar(select(func.count()).select_from(Article)) or 0
    edition = db.scalar(select(Edition).order_by(Edition.edition_date.desc()))
    schedule = db.get(Schedule, 1)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "feed_count": feed_count,
            "article_count": article_count,
            "edition": edition,
            "schedule": schedule,
            "recent_feeds": db.scalars(select(Feed).order_by(Feed.name)).all(),
            "recent_print": db.scalar(select(PrintJob).order_by(PrintJob.created_at.desc())),
        },
    )


@web.post("/actions/fetch")
def action_fetch(db: Session = Depends(get_db)):
    fetch_all(db)
    return RedirectResponse("/?notice=Flux%20r%C3%A9cup%C3%A9r%C3%A9s", status_code=303)


@web.post("/actions/generate")
def action_generate(db: Session = Depends(get_db)):
    edition = generate_edition(db, force=True)
    return RedirectResponse(f"/editions/{edition.id}?notice=Journal%20g%C3%A9n%C3%A9r%C3%A9", status_code=303)


@web.get("/feeds", response_class=HTMLResponse)
def feeds_page(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(Feed).order_by(Feed.priority.desc(), Feed.name)).all()
    counts = dict(db.execute(select(Article.feed_id, func.count(Article.id)).group_by(Article.feed_id)).all())
    return templates.TemplateResponse(
        request,
        "feeds.html",
        {
            "active": "feeds",
            "feeds": rows,
            "counts": counts,
            "categories": [
                "À la une",
                "France",
                "International",
                "Économie",
                "Technologie",
                "Sciences",
                "Culture",
                "Sport",
                "Divers",
            ],
        },
    )


@web.post("/feeds/create")
def feed_create(
    name: str = Form(),
    url: str = Form(),
    category: str = Form("Divers"),
    weight: float = Form(1),
    priority: int = Form(0),
    minimum: int = Form(0),
    maximum: str = Form(""),
    db: Session = Depends(get_db),
):
    data = FeedInput(
        name=name,
        url=url,
        category=category,
        weight=weight,
        priority=priority,
        minimum=minimum,
        maximum=int(maximum) if maximum else None,
    )
    db.add(Feed(**data.model_dump()))
    db.commit()
    return RedirectResponse("/feeds", status_code=303)


@web.post("/feeds/{feed_id}/update")
def feed_update(
    feed_id: int,
    name: str = Form(),
    url: str = Form(),
    category: str = Form("Divers"),
    weight: float = Form(1),
    priority: int = Form(0),
    minimum: int = Form(0),
    maximum: str = Form(""),
    active: bool = Form(False),
    db: Session = Depends(get_db),
):
    feed = db.get(Feed, feed_id)
    if feed is None:
        raise HTTPException(404, "Flux introuvable")
    data = FeedInput(
        name=name,
        url=url,
        category=category,
        weight=weight,
        priority=priority,
        minimum=minimum,
        maximum=int(maximum) if maximum else None,
        active=active,
    )
    for key, value in data.model_dump().items():
        setattr(feed, key, value)
    db.commit()
    return RedirectResponse("/feeds", status_code=303)


@web.post("/feeds/{feed_id}/delete")
def feed_delete(feed_id: int, db: Session = Depends(get_db)):
    feed = db.get(Feed, feed_id)
    if feed is not None:
        db.delete(feed)
        db.commit()
    return RedirectResponse("/feeds", status_code=303)


@web.post("/feeds/{feed_id}/test")
def feed_test(feed_id: int, db: Session = Depends(get_db)):
    feed = db.get(Feed, feed_id)
    if feed is None:
        raise HTTPException(404, "Flux introuvable")
    count = fetch_feed(feed, db)
    return RedirectResponse(f"/feeds?notice={count}%20articles%20r%C3%A9cup%C3%A9r%C3%A9s", status_code=303)


@web.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    settings = settings_dict(db)
    try:
        weather_locations = json.loads(settings["weather_locations"])
    except (KeyError, json.JSONDecodeError):
        weather_locations = []
    if not weather_locations:
        weather_locations = [
            {
                "name": settings.get("city", "Paris"),
                "latitude": settings.get("latitude", "48.8566"),
                "longitude": settings.get("longitude", "2.3522"),
                "timezone": settings.get("timezone", TIMEZONE),
            }
        ]
    settings["meteo_api_key_configured"] = bool(settings.get("meteo_api_key"))
    settings["meteo_api_key"] = ""
    logo_path = PDF_DIR / "branding" / "logo.png"
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active": "settings",
            "settings": settings,
            "weather_locations": weather_locations,
            "logo_present": logo_path.is_file(),
        },
    )


@api.get("/weather/cities")
def api_weather_cities(q: str = Query(min_length=2, max_length=80)):
    params = urlencode({"name": q, "count": 8, "language": "fr", "format": "json"})
    request = URLRequest(
        f"https://geocoding-api.open-meteo.com/v1/search?{params}", headers={"User-Agent": "DailyNews/1.0"}
    )
    try:
        with urlopen(request, timeout=5) as response:
            data = json.loads(response.read(200_000))
        return [
            {
                "name": item["name"],
                "admin1": item.get("admin1", ""),
                "country": item.get("country", ""),
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "timezone": item.get("timezone", "auto"),
            }
            for item in data.get("results", [])
            if item.get("country_code") == "FR" and "latitude" in item and "longitude" in item
        ]
    except Exception as exc:
        logger.warning("Open-Meteo city search failed", extra={"error": type(exc).__name__})
        return []


@api.get("/weather/preview")
def api_weather_preview(
    name: str = Query(min_length=1, max_length=100),
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    timezone: str = Query(default="auto", max_length=64),
    db: Session = Depends(get_db),
):
    try:
        zone = ZoneInfo(timezone) if timezone != "auto" else ZoneInfo(TIMEZONE)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Fuseau horaire invalide") from None
    provider = OpenMeteoProvider(settings_dict(db).get("meteo_api_key") or None)
    return asdict(provider.forecast(name, latitude, longitude, datetime.now(zone).date(), timezone))


@web.post("/settings/logo")
async def settings_logo(file: UploadFile = File(...)):
    payload = await file.read(2_000_001)
    if len(payload) > 2_000_000 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(415, "Choisissez un fichier PNG de moins de 2 Mo.")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(payload)) as image:
            if image.format != "PNG" or image.width > 3000 or image.height > 1500:
                raise ValueError("Dimensions invalides")
            image.load()
            logo_path = PDF_DIR / "branding" / "logo.png"
            logo_path.parent.mkdir(parents=True, exist_ok=True)
            image.convert("RGBA").save(logo_path, format="PNG", optimize=True)
    except Exception as exc:
        raise HTTPException(422, "Le fichier PNG ne peut pas être lu.") from exc
    return RedirectResponse("/settings?notice=Logo%20enregistré", status_code=303)


@web.post("/settings/logo/delete")
def settings_logo_delete():
    (PDF_DIR / "branding" / "logo.png").unlink(missing_ok=True)
    return RedirectResponse("/settings?notice=Logo%20retiré", status_code=303)


@web.get("/settings/logo")
def settings_logo_preview():
    logo_path = PDF_DIR / "branding" / "logo.png"
    if not logo_path.is_file():
        raise HTTPException(404, "Aucun logo enregistré")
    return FileResponse(logo_path, media_type="image/png")


@web.post("/settings")
def settings_save(
    request: Request,
    newspaper_name: str = Form(),
    timezone: str = Form(TIMEZONE),
    weather_locations_json: str = Form("[]"),
    maximum_articles: int = Form(32),
    minimum_articles: int = Form(12),
    period_days: int = Form(1),
    columns: int = Form(2),
    max_pages: int = Form(4),
    meteo_api_key: str = Form(""),
    clear_meteo_api_key: bool = Form(False),
    title_font: str = Form("DejaVu Serif"),
    article_font: str = Form("DejaVu Serif"),
    show_images: bool = Form(False),
    show_descriptions: bool = Form(True),
    show_qr_codes: bool = Form(False),
    db: Session = Depends(get_db),
):
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(timezone)
        location_data = json.loads(weather_locations_json)
        if not location_data:
            raise ValueError("Ajoutez au moins une localisation météo.")
        locations = [WeatherLocationInput.model_validate(location) for location in location_data]
        first_location = locations[0]
        values = SettingsInput(
            newspaper_name=newspaper_name,
            timezone=timezone,
            city=first_location.name,
            latitude=first_location.latitude,
            longitude=first_location.longitude,
            maximum_articles=maximum_articles,
            minimum_articles=minimum_articles,
            period_days=period_days,
            columns=columns,
            max_pages=max_pages,
            weather_locations=locations,
            meteo_api_key=meteo_api_key or None,
            clear_meteo_api_key=clear_meteo_api_key,
            title_font=title_font,
            article_font=article_font,
            show_images=show_images,
            show_descriptions=show_descriptions,
            show_qr_codes=show_qr_codes,
        )
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    persist_settings_model(db, values)
    return RedirectResponse("/settings?notice=Param%C3%A8tres%20enregistr%C3%A9s", status_code=303)


@web.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request, db: Session = Depends(get_db)):
    printers, printer_error = [], None
    try:
        printers = CupsPrintProvider().printers()
    except Exception as exc:
        printer_error = str(exc)
    return templates.TemplateResponse(
        request,
        "schedule.html",
        {"active": "schedule", "schedule": db.get(Schedule, 1), "printers": printers, "printer_error": printer_error},
    )


@web.post("/schedule")
async def schedule_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    days = [int(value) for value in form.getlist("active_days")]
    try:
        data = ScheduleInput(
            fetch_time=str(form.get("fetch_time")),
            generate_time=str(form.get("generate_time")),
            print_time=str(form.get("print_time")),
            active_days=days,
            auto_generate=form.get("auto_generate") == "on",
            auto_print=form.get("auto_print") == "on",
            printer_name=str(form.get("printer_name", "")),
            copies=int(form.get("copies", 1)),
            duplex=form.get("duplex") == "on",
        )
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    schedule = db.get(Schedule, 1)
    for key, value in data.model_dump().items():
        setattr(schedule, key, ",".join(str(day) for day in value) if key == "active_days" else value)
    db.commit()
    configure_jobs()
    return RedirectResponse("/schedule?notice=Planning%20enregistr%C3%A9", status_code=303)


@web.post("/actions/print")
def action_print(edition_id: int = Form(), db: Session = Depends(get_db)):
    edition = db.get(Edition, edition_id)
    schedule = db.get(Schedule, 1)
    printer = schedule.printer_name if schedule else ""
    copies = schedule.copies if schedule else 1
    duplex = schedule.duplex if schedule else True
    if edition is None:
        raise HTTPException(404, "Édition introuvable")
    job = PrintJob(edition_id=edition.id, printer_name=printer, copies=copies, status="en cours")
    db.add(job)
    db.commit()
    try:
        job.message = CupsPrintProvider().print_pdf(edition.pdf_path, printer, copies, duplex)
        job.status = "terminée"
        edition.print_status = "imprimée"
    except Exception as exc:
        job.status = "erreur"
        job.message = str(exc)[:1000]
        edition.print_status = "erreur"
    db.commit()
    return RedirectResponse(f"/editions/{edition.id}?notice={job.status}", status_code=303)


@web.get("/editions", response_class=HTMLResponse)
def editions_page(request: Request, db: Session = Depends(get_db)):
    editions = db.scalars(select(Edition).order_by(Edition.edition_date.desc())).all()
    return templates.TemplateResponse(request, "editions.html", {"active": "editions", "editions": editions})


@web.get("/editions/{edition_id}", response_class=HTMLResponse)
def edition_page(edition_id: int, request: Request, db: Session = Depends(get_db)):
    edition = db.get(Edition, edition_id)
    if edition is None:
        raise HTTPException(404, "Édition introuvable")
    return templates.TemplateResponse(
        request,
        "edition.html",
        {
            "active": "editions",
            "edition": edition,
            "report": json.loads(edition.report or "{}"),
            "schedule": db.get(Schedule, 1),
            "last_print_job": db.scalar(
                select(PrintJob)
                .where(PrintJob.edition_id == edition.id)
                .order_by(PrintJob.created_at.desc(), PrintJob.id.desc())
                .limit(1)
            ),
        },
    )


@web.post("/editions/{edition_id}/regenerate")
def edition_regenerate(edition_id: int, db: Session = Depends(get_db)):
    edition = db.get(Edition, edition_id)
    if edition is None:
        raise HTTPException(404, "Édition introuvable")
    updated = generate_edition(db, force=True, edition_date=edition.edition_date)
    return RedirectResponse(f"/editions/{updated.id}?notice=Édition%20régénérée", status_code=303)


@web.post("/editions/{edition_id}/delete")
def edition_delete(edition_id: int, db: Session = Depends(get_db)):
    edition = db.get(Edition, edition_id)
    if edition is not None:
        pdf_path = Path(edition.pdf_path).resolve()
        pdf_root = PDF_DIR.resolve()
        if pdf_path.is_relative_to(pdf_root):
            pdf_path.unlink(missing_ok=True)
        db.query(PrintJob).filter(PrintJob.edition_id == edition.id).delete()
        db.delete(edition)
        db.commit()
    return RedirectResponse("/editions?notice=Édition%20supprimée", status_code=303)


@web.get("/editions/{edition_id}/pdf")
def edition_pdf(edition_id: int, db: Session = Depends(get_db)):
    edition = db.get(Edition, edition_id)
    if edition is None or edition.status != "ready" or not edition.pdf_path.startswith(str(PDF_DIR)):
        raise HTTPException(404, "PDF introuvable")
    return FileResponse(
        edition.pdf_path,
        media_type="application/pdf",
        filename=f"dailynews-{edition.edition_date}.pdf",
        content_disposition_type="inline",
    )


@api.get("/feeds")
def api_feeds(db: Session = Depends(get_db)):
    return [
        {
            "id": feed.id,
            "name": feed.name,
            "url": feed.url,
            "category": feed.category,
            "active": feed.active,
            "weight": feed.weight,
            "priority": feed.priority,
            "minimum": feed.minimum,
            "maximum": feed.maximum,
            "last_fetched_at": feed.last_fetched_at,
            "status": feed.last_status,
            "articles": len(feed.articles),
        }
        for feed in db.scalars(select(Feed).order_by(Feed.name)).all()
    ]


@api.post("/feeds", status_code=201)
def api_feed_create(data: FeedInput, db: Session = Depends(get_db)):
    feed = Feed(**data.model_dump())
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return {"id": feed.id, "name": feed.name, "url": feed.url}


@api.put("/feeds/{feed_id}")
def api_feed_update(feed_id: int, data: FeedInput, db: Session = Depends(get_db)):
    feed = db.get(Feed, feed_id)
    if feed is None:
        raise HTTPException(404, "Flux introuvable")
    for key, value in data.model_dump().items():
        setattr(feed, key, value)
    db.commit()
    return {"id": feed.id, "name": feed.name}


@api.delete("/feeds/{feed_id}", status_code=204)
def api_feed_delete(feed_id: int, db: Session = Depends(get_db)):
    feed = db.get(Feed, feed_id)
    if feed is not None:
        db.delete(feed)
        db.commit()
    return Response(status_code=204)


@api.post("/feeds/{feed_id}/test")
def api_feed_test(feed_id: int, db: Session = Depends(get_db)):
    feed = db.get(Feed, feed_id)
    if feed is None:
        raise HTTPException(404, "Flux introuvable")
    return {"feed": feed.name, "articles": fetch_feed(feed, db), "status": feed.last_status, "error": feed.last_error}


@api.post("/rss/fetch")
def api_fetch(db: Session = Depends(get_db)):
    return fetch_all(db)


@api.post("/editions/generate")
def api_generate(data: GenerateInput = GenerateInput(), db: Session = Depends(get_db)):
    edition = generate_edition(db, force=data.force)
    return {
        "id": edition.id,
        "date": edition.edition_date,
        "status": edition.status,
        "articles": edition.article_count,
        "pages": edition.page_count,
    }


@api.get("/editions")
def api_editions(db: Session = Depends(get_db)):
    return [
        {
            "id": item.id,
            "date": item.edition_date,
            "generated_at": item.generated_at,
            "articles": item.article_count,
            "pages": item.page_count,
            "status": item.status,
            "print_status": item.print_status,
        }
        for item in db.scalars(select(Edition).order_by(Edition.edition_date.desc())).all()
    ]


@api.get("/editions/{edition_id}")
def api_edition(edition_id: int, db: Session = Depends(get_db)):
    edition = db.get(Edition, edition_id)
    if edition is None:
        raise HTTPException(404, "Édition introuvable")
    return {
        "id": edition.id,
        "date": edition.edition_date,
        "status": edition.status,
        "articles": edition.article_count,
        "pages": edition.page_count,
        "report": json.loads(edition.report or "{}"),
        "error": edition.error,
    }


@api.post("/editions/{edition_id}/regenerate")
def api_regenerate_edition(edition_id: int, db: Session = Depends(get_db)):
    edition = db.get(Edition, edition_id)
    if edition is None:
        raise HTTPException(404, "Édition introuvable")
    updated = generate_edition(db, force=True, edition_date=edition.edition_date)
    return {
        "id": updated.id,
        "date": updated.edition_date,
        "status": updated.status,
        "articles": updated.article_count,
        "pages": updated.page_count,
    }


@api.delete("/editions/{edition_id}", status_code=204)
def api_delete_edition(edition_id: int, db: Session = Depends(get_db)):
    edition = db.get(Edition, edition_id)
    if edition is not None:
        pdf_path = Path(edition.pdf_path).resolve()
        if pdf_path.is_relative_to(PDF_DIR.resolve()):
            pdf_path.unlink(missing_ok=True)
        db.query(PrintJob).filter(PrintJob.edition_id == edition.id).delete()
        db.delete(edition)
        db.commit()
    return Response(status_code=204)


@api.get("/editions/{edition_id}/pdf")
def api_edition_pdf(edition_id: int, db: Session = Depends(get_db)):
    return edition_pdf(edition_id, db)


@api.post("/editions/{edition_id}/print")
def api_edition_print(edition_id: int, db: Session = Depends(get_db)):
    edition = db.get(Edition, edition_id)
    schedule = db.get(Schedule, 1)
    if edition is None or schedule is None:
        raise HTTPException(404, "Édition ou configuration introuvable")
    job = PrintJob(edition_id=edition.id, printer_name=schedule.printer_name, copies=schedule.copies, status="en cours")
    db.add(job)
    db.commit()
    try:
        job.message = CupsPrintProvider().print_pdf(
            edition.pdf_path, schedule.printer_name, schedule.copies, schedule.duplex
        )
        job.status, edition.print_status = "terminée", "imprimée"
    except Exception as exc:
        job.status, job.message, edition.print_status = "erreur", str(exc)[:1000], "erreur"
    db.commit()
    return {"status": job.status, "message": job.message}


@api.get("/settings")
def api_settings(db: Session = Depends(get_db)):
    return public_settings(db)


@api.put("/settings")
def api_save_settings(data: SettingsInput, db: Session = Depends(get_db)):
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(data.timezone)
    except Exception as exc:
        raise HTTPException(422, "Fuseau horaire inconnu") from exc
    persist_settings_model(db, data)
    return public_settings(db)


@api.get("/schedule")
def api_schedule(db: Session = Depends(get_db)):
    schedule = db.get(Schedule, 1)
    return {
        "fetch_time": schedule.fetch_time,
        "generate_time": schedule.generate_time,
        "print_time": schedule.print_time,
        "active_days": [int(day) for day in schedule.active_days.split(",")],
        "auto_generate": schedule.auto_generate,
        "auto_print": schedule.auto_print,
        "printer_name": schedule.printer_name,
        "copies": schedule.copies,
        "duplex": schedule.duplex,
    }


@api.put("/schedule")
def api_save_schedule(data: ScheduleInput, db: Session = Depends(get_db)):
    schedule = db.get(Schedule, 1)
    for key, value in data.model_dump().items():
        setattr(schedule, key, ",".join(str(day) for day in value) if key == "active_days" else value)
    db.commit()
    configure_jobs()
    return api_schedule(db)


@api.get("/printers")
def api_printers():
    try:
        return {"printers": CupsPrintProvider().printers(), "error": None}
    except Exception as exc:
        return {"printers": [], "error": str(exc)}


app.include_router(web)
app.include_router(api)
