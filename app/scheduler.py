from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import TIMEZONE
from app.database import SessionLocal
from app.models import Edition, PrintJob, Schedule
from app.printing import CupsPrintProvider
from app.rss import fetch_all
from app.services import generate_edition, settings_dict

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone=TIMEZONE, daemon=True)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def scheduled_fetch() -> None:
    with SessionLocal() as db:
        logger.info("Scheduled RSS refresh started")
        fetch_all(db)


def scheduled_generate() -> None:
    with SessionLocal() as db:
        logger.info("Scheduled edition generation started")
        generate_edition(db)


def scheduled_print() -> None:
    with SessionLocal() as db:
        schedule = db.get(Schedule, 1)
        if not schedule or not schedule.auto_print or not schedule.printer_name:
            return
        today = datetime.now(ZoneInfo(settings_dict(db)["timezone"])).date()
        edition = db.scalar(select(Edition).where(Edition.status == "ready").order_by(Edition.edition_date.desc()))
        if edition is None or edition.edition_date != today:
            logger.warning("Scheduled print skipped: no edition")
            return
        job = PrintJob(
            edition_id=edition.id, printer_name=schedule.printer_name, copies=schedule.copies, status="en cours"
        )
        db.add(job)
        db.commit()
        try:
            job.message = CupsPrintProvider().print_pdf(
                edition.pdf_path, schedule.printer_name, schedule.copies, schedule.duplex
            )
            job.status = "terminée"
            edition.print_status = "imprimée"
        except Exception as exc:
            job.status = "erreur"
            job.message = str(exc)[:1000]
            edition.print_status = "erreur"
            logger.error("Scheduled print failed", extra={"error": str(exc)})
        db.commit()


def configure_jobs() -> None:
    with SessionLocal() as db:
        schedule = db.get(Schedule, 1)
        if schedule is None:
            return
        timezone_name = settings_dict(db)["timezone"]
        active_days = ",".join(
            DAYS[int(day)] for day in schedule.active_days.split(",") if day.isdigit() and 0 <= int(day) <= 6
        )
        jobs = [
            ("rss_refresh", scheduled_fetch, schedule.fetch_time),
            ("edition_generation", scheduled_generate, schedule.generate_time),
            ("edition_print", scheduled_print, schedule.print_time),
        ]
        for job_id, function, value in jobs:
            scheduler.remove_job(job_id) if scheduler.get_job(job_id) else None
            if job_id == "edition_generation" and not schedule.auto_generate:
                continue
            hour, minute = (int(part) for part in value.split(":"))
            scheduler.add_job(
                function,
                CronTrigger(
                    day_of_week=active_days or "mon-sun", hour=hour, minute=minute, timezone=ZoneInfo(timezone_name)
                ),
                id=job_id,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )


def start_scheduler() -> None:
    configure_jobs()
    if not scheduler.running:
        scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
