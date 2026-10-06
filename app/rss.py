from __future__ import annotations

import calendar
import html
import ipaddress
import logging
import re
import socket
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Article, Feed, utcnow

logger = logging.getLogger(__name__)
MAX_FEED_BYTES = 3_000_000
MAX_IMAGE_BYTES = 2_000_000
DEMO_FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>DailyNews Démo</title>
<item><title>La France prépare un nouveau plan de transition énergétique</title>
<link>https://demo.dailynews.invalid/france-energie</link><description>
Le gouvernement présente un calendrier d'investissements régionaux pour accélérer
la rénovation et les énergies renouvelables.</description>
<pubDate>Tue, 06 Oct 2026 08:00:00 GMT</pubDate><category>France</category></item>
<item><title>Les laboratoires européens dévoilent une avancée en calcul quantique</title>
<link>https://demo.dailynews.invalid/sciences-quantique</link><description>
Une équipe internationale a publié des résultats qui améliorent la stabilité
des nouveaux processeurs expérimentaux.</description>
<pubDate>Tue, 06 Oct 2026 10:30:00 GMT</pubDate><category>Sciences</category></item>
<item><title>Les marchés mondiaux attendent les nouvelles prévisions économiques</title>
<link>https://demo.dailynews.invalid/economie-marches</link><description>
Les investisseurs évaluent les indicateurs publiés cette semaine dans un contexte
de croissance contrastée.</description>
<pubDate>Tue, 06 Oct 2026 13:00:00 GMT</pubDate><category>Économie</category></item>
<item><title>Un festival de cinéma indépendant annonce sa sélection annuelle</title>
<link>https://demo.dailynews.invalid/culture-cinema</link><description>
Plus de quarante films seront présentés lors de cette édition consacrée aux
nouvelles voix du documentaire.</description>
<pubDate>Tue, 06 Oct 2026 16:15:00 GMT</pubDate><category>Culture</category></item>
</channel></rss>"""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_html(value: str) -> str:
    parser = _TextOnly()
    parser.feed(value)
    return " ".join(html.unescape(" ".join(parser.parts)).split())


def _validate_feed_url(url: str) -> None:
    parts = urlsplit(url)
    if url == "mock://demo":
        return
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Seules les URL RSS HTTP(S) publiques sont autorisées.")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        }
    except OSError as exc:
        raise ValueError("Le nom d'hôte du flux ne peut pas être résolu.") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Les flux RSS pointant vers un réseau privé ne sont pas autorisés.")


def _entry_date(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime.fromtimestamp(calendar.timegm(parsed), UTC)
        except (OverflowError, ValueError, TypeError):
            return None
    return None


def fetch_feed(feed: Feed, db: Session) -> int:
    """Fetch one feed; failures are recorded without interrupting other feeds."""
    try:
        _validate_feed_url(feed.url)
        if feed.url == "mock://demo":
            yesterday = datetime.now(UTC) - timedelta(days=1)
            payload = re.sub(
                rb"Tue, 06 Oct 2026 (\d{2}):\d{2}:\d{2} GMT",
                lambda match: format_datetime(
                    yesterday.replace(hour=int(match.group(1)), minute=0, second=0, microsecond=0)
                ).encode(),
                DEMO_FEED.encode(),
            )
        else:
            request = Request(feed.url, headers={"User-Agent": "DailyNews/1.0 (+RSS reader)"})
            with build_opener(_NoRedirect).open(request, timeout=12) as response:
                payload = response.read(MAX_FEED_BYTES + 1)
            if len(payload) > MAX_FEED_BYTES:
                raise ValueError("Flux trop volumineux (limite de 3 Mo).")
        parsed = feedparser.parse(payload)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Flux RSS invalide : {parsed.bozo_exception}")
        count = 0
        for entry in parsed.entries:
            url = entry.get("link", "").strip()
            title = clean_html(entry.get("title", ""))[:500]
            if not title or not url:
                continue
            article = db.scalar(select(Article).where(Article.feed_id == feed.id, Article.url == url))
            if article is None:
                article = Article(feed_id=feed.id, url=url, title=title)
                db.add(article)
            article.title = title
            article.summary = clean_html(entry.get("summary", ""))[:6000]
            article.author = clean_html(entry.get("author", ""))[:200] or None
            article.published_at = _entry_date(entry)
            article.fetched_at = utcnow()
            article.image_url = next(
                (link.get("href") for link in entry.get("links", []) if link.get("type", "").startswith("image/")), None
            )
            article.categories = ",".join(tag.get("term", "") for tag in entry.get("tags", []) if tag.get("term"))[:500]
            count += 1
        feed.last_fetched_at = utcnow()
        feed.last_status = "OK"
        feed.last_error = None
        db.commit()
        logger.info("RSS feed fetched", extra={"feed": feed.name, "articles": count})
        return count
    except Exception as exc:
        db.rollback()
        feed = db.get(Feed, feed.id)
        feed.last_fetched_at = utcnow()
        feed.last_status = "Erreur"
        feed.last_error = str(exc)[:1000]
        db.commit()
        logger.warning("RSS feed failed", extra={"feed": feed.name, "error": str(exc)})
        return 0


def fetch_all(db: Session) -> dict[str, int]:
    results = {}
    for feed in db.scalars(select(Feed).where(Feed.active.is_(True))).all():
        results[feed.name] = fetch_feed(feed, db)
    return results


def download_image(url: str | None, directory) -> str | None:
    """Cache one small public image locally; reject redirects and private hosts."""
    if not url:
        return None
    try:
        _validate_feed_url(url)
        request = Request(url, headers={"User-Agent": "DailyNews/1.0"})
        with build_opener(_NoRedirect).open(request, timeout=4) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                return None
            payload = response.read(MAX_IMAGE_BYTES + 1)
        if len(payload) > MAX_IMAGE_BYTES:
            return None
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{sha256(url.encode()).hexdigest()}{suffix}"
        if not path.exists():
            path.write_bytes(payload)
        return path.resolve().as_uri()
    except Exception as exc:
        logger.info("RSS image skipped", extra={"error": str(exc)})
        return None
