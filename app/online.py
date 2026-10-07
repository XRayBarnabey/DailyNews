from __future__ import annotations

import html
import json
import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from app import config

logger = logging.getLogger(__name__)

QUOTES_URL = "https://citation.lecog.fr/public/api/quote-of-the-day.php"
WORDS_URL = "https://trouve-mot.fr/api/random/{count}"
DEFINITION_URL = "https://fr.wiktionary.org/api/rest_v1/page/definition/{word}"
QUOTES_TTL = 86400
WORDS_TTL = 90 * 86400
WORDS_TARGET = 400
LENGTHS = {"debutant": (5, 7), "normal": (7, 9), "avance": (9, 13)}


def _get_json(url: str, timeout: int = 10):
    request = Request(url, headers={"User-Agent": "DailyNews/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _cache_path(name: str) -> Path:
    return config.DATA_DIR / "cache" / name


def _load_cache(name: str, ttl: int, allow_stale: bool = False):
    path = _cache_path(name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if allow_stale or time.time() - payload.get("fetched_at", 0) < ttl:
        return payload.get("data")
    return None


def _save_cache(name: str, data) -> None:
    path = _cache_path(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": time.time(), "data": data}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.warning("Impossible d’écrire le cache %s", name)


def fetch_quotes() -> list[dict]:
    """Fetches the French quote of the day, cached locally."""
    cached = _load_cache("quotes.json", QUOTES_TTL)
    if cached:
        return cached
    try:
        payload = _get_json(QUOTES_URL, timeout=15)
        item = payload.get("data", {})
        text = str(item.get("text", "")).strip()
        author = item.get("author", "")
        if isinstance(author, dict):
            author = " ".join(part.strip() for part in (author.get("forename", ""), author.get("name", "")) if part)
        quotes = [{"text": text, "author": str(author).strip()}] if text else []
        if quotes:
            _save_cache("quotes.json", quotes)
            return quotes
    except Exception as exc:
        logger.warning("Citations en ligne indisponibles : %s", exc)
    return _load_cache("quotes.json", QUOTES_TTL, allow_stale=True) or []


def _normalize(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word.upper()) if not unicodedata.combining(c))


def _clean_definition(raw: str, word: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) < 8 or len(text) > 140:
        return ""
    if _normalize(word) in _normalize(text).replace(" ", ""):
        return ""
    return text[0].upper() + text[1:]


def _definition(word: str) -> str:
    try:
        payload = _get_json(DEFINITION_URL.format(word=quote(word)), timeout=8)
        for entry in payload.get("fr", []):
            for item in entry.get("definitions", []):
                clue = _clean_definition(item.get("definition", ""), word)
                if clue:
                    return clue
    except Exception:
        pass
    return ""


def fetch_crossword_words() -> dict[str, list[tuple[str, str]]]:
    """French words from trouve-mot.fr with Wiktionary definitions as clues, grouped by level."""
    cached = _load_cache("crossword_words.json", WORDS_TTL)
    if cached:
        return {level: [tuple(item) for item in items] for level, items in cached.items()}
    try:
        candidates: dict[str, str] = {}
        for _ in range(6):
            payload = _get_json(WORDS_URL.format(count=200), timeout=15)
            for item in payload:
                name = str(item.get("name", "")).strip().lower()
                if re.fullmatch(r"[a-zàâäçéèêëîïôöùûüÿœ]{5,13}", name) and item.get("cat", item.get("categorie", "nom")) in (
                    "nom",
                    "adj",
                    "adjectif",
                    None,
                ):
                    candidates[_normalize(name)] = name
            if len(candidates) >= WORDS_TARGET * 2:
                break
        names = list(candidates.values())[: WORDS_TARGET * 2]
        with ThreadPoolExecutor(max_workers=8) as pool:
            clues = list(pool.map(_definition, names))
        banks: dict[str, list[tuple[str, str]]] = {level: [] for level in LENGTHS}
        for name, clue in zip(names, clues):
            if not clue:
                continue
            word = _normalize(name)
            for level, (low, high) in LENGTHS.items():
                if low <= len(word) <= high:
                    banks[level].append((word, clue))
                    break
        if all(len(items) >= 12 for items in banks.values()):
            _save_cache("crossword_words.json", banks)
            return banks
    except Exception as exc:
        logger.warning("Mots de grille en ligne indisponibles : %s", exc)
    stale = _load_cache("crossword_words.json", WORDS_TTL, allow_stale=True)
    return {level: [tuple(i) for i in items] for level, items in stale.items()} if stale else {}
