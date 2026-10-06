from __future__ import annotations

import json
import logging
from datetime import date
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)
FRENCH_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def format_french_date(value: date) -> str:
    return f"{FRENCH_WEEKDAYS[value.weekday()]} {value.day} {FRENCH_MONTHS[value.month - 1]} {value.year}"


@lru_cache(maxsize=366)
def fete_du_jour(value: date) -> str:
    query = urlencode({"jour": value.day, "mois": value.month, "annee": value.year})
    request = Request(
        f"https://nominis.cef.fr/json/nominis.php?{query}",
        headers={"User-Agent": "DailyNews/1.0 (French calendar)"},
    )
    try:
        with urlopen(request, timeout=3) as response:
            data = json.loads(response.read(100_000))
        names = data.get("response", {}).get("prenoms", {}).get("majeurs", {})
        if not names:
            names = data.get("response", {}).get("prenoms", {}).get("majeur", {})
        if not names:
            return ""
        name, details = next(iter(names.items()))
        prefix = "Sainte" if details.get("sexe") == "féminin" else "Saint"
        return f"{prefix} {name}"
    except Exception as exc:
        logger.warning("French name-day provider unavailable", extra={"error": type(exc).__name__})
        return ""
