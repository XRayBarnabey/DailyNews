from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
PDF_DIR = Path(os.getenv("PDF_DIR", str(DATA_DIR / "pdf")))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'database' / 'dailynews.db'}")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Paris")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
APP_ENV = os.getenv("APP_ENV", "production")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")
CUPS_SERVER = os.getenv("CUPS_SERVER", "")
CUPS_PORT = int(os.getenv("CUPS_PORT", "631"))


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "database").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
