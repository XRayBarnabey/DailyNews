from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from app.config import DATA_DIR, ensure_directories


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("feed", "articles", "error", "edition", "pages"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    ensure_directories()
    formatter = JsonFormatter()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        DATA_DIR / "logs" / "dailynews.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[console, file_handler], force=True)
    logging.getLogger("weasyprint").setLevel(logging.WARNING)
    logging.getLogger("fontTools").setLevel(logging.WARNING)
