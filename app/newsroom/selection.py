"""Date filtering, deduplication, and weighted editorial selection."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True, slots=True)
class FeedQuota:
    id: int
    name: str
    weight: float = 1.0
    priority: int = 0
    minimum: int = 0
    maximum: int | None = None
    active: bool = True


@dataclass(frozen=True, slots=True)
class CandidateArticle:
    id: int
    feed_id: int
    title: str
    url: str
    published_at: datetime | None
    summary: str = ""
    image_url: str | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normal_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _normal_url(value: str) -> str:
    parts = urlsplit(value.strip())
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query)
        if not key.casefold().startswith("utm_") and key.casefold() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), urlencode(sorted(query)), "")
    )


def select_articles(
    articles: list[CandidateArticle],
    feeds: list[FeedQuota],
    *,
    period_start: datetime,
    period_end: datetime,
    maximum_total: int,
    minimum_total: int = 0,
) -> list[CandidateArticle]:
    """Select a date-bounded, deduplicated set using capped weighted quotas.

    Feed minimums are satisfied first (higher-priority feeds break ties), then
    remaining places are apportioned by weight. Saturated or empty feeds return
    their unfillable places to the other feeds. Editorial ranking chooses the
    best available article inside each source quota.
    """
    if maximum_total <= 0:
        return []
    start, end = _utc(period_start), _utc(period_end)
    if start > end:
        raise ValueError("period_start must be before period_end")
    by_id = {feed.id: feed for feed in feeds if feed.active}

    def editorial_score(article: CandidateArticle) -> tuple[float, int, int]:
        feed = by_id[article.feed_id]
        published = _utc(article.published_at) if article.published_at else start
        freshness = max(0.0, (published - start).total_seconds())
        summary_score = min(len(article.summary), 600) / 600
        title_score = 1.0 if 25 <= len(article.title) <= 110 else 0.0
        score = feed.priority * 10 + max(feed.weight, 0) + summary_score + title_score + freshness / 86400
        return score, published.timestamp(), -article.id

    # Keep the strongest feed's version when syndicated copies share a URL or title.
    unique: dict[tuple[str, str], CandidateArticle] = {}
    for article in articles:
        if article.feed_id not in by_id or not article.title.strip() or not article.url.strip():
            continue
        if article.published_at is not None:
            published = _utc(article.published_at)
            if not start <= published <= end:
                continue
        url_key = _normal_url(article.url)
        title_key = _normal_title(article.title)
        key = ("url", url_key) if url_key else ("title", title_key)
        current = unique.get(key)
        if current is None or editorial_score(article) > editorial_score(current):
            unique[key] = article

    candidates: dict[int, list[CandidateArticle]] = {feed_id: [] for feed_id in by_id}
    title_owners: dict[str, CandidateArticle] = {}
    for article in unique.values():
        title_key = _normal_title(article.title)
        owner = title_owners.get(title_key)
        if owner is not None:
            if editorial_score(article) <= editorial_score(owner):
                continue
            candidates[owner.feed_id].remove(owner)
        title_owners[title_key] = article
        candidates[article.feed_id].append(article)

    available = {feed_id: len(items) for feed_id, items in candidates.items()}
    target = min(maximum_total, sum(available.values()))
    allocations = {feed_id: 0 for feed_id in by_id}
    remaining = target
    for feed in sorted(by_id.values(), key=lambda item: (-item.priority, item.id)):
        amount = min(max(feed.minimum, 0), available[feed.id], remaining)
        allocations[feed.id] += amount
        remaining -= amount

    # Iterative proportional apportionment redistributes exhausted-feed capacity.
    while remaining:
        eligible = [
            feed
            for feed in by_id.values()
            if allocations[feed.id] < available[feed.id]
            and (feed.maximum is None or allocations[feed.id] < max(feed.maximum, 0))
        ]
        if not eligible:
            break
        weights = {feed.id: max(feed.weight, 0.0) for feed in eligible}
        if not any(weights.values()):
            weights = {feed.id: 1.0 for feed in eligible}
        weight_sum = sum(weights.values())
        proposed = {feed.id: remaining * weights[feed.id] / weight_sum for feed in eligible}
        added = 0
        for feed in sorted(eligible, key=lambda item: (-item.priority, item.id)):
            room = available[feed.id] - allocations[feed.id]
            if feed.maximum is not None:
                room = min(room, max(feed.maximum, 0) - allocations[feed.id])
            amount = min(room, int(proposed[feed.id]))
            allocations[feed.id] += amount
            remaining -= amount
            added += amount
        if added == 0:
            feed = max(eligible, key=lambda item: (proposed[item.id] - int(proposed[item.id]), item.priority, -item.id))
            allocations[feed.id] += 1
            remaining -= 1

    selected = [
        article
        for feed_id, items in candidates.items()
        for article in sorted(items, key=editorial_score, reverse=True)[: allocations[feed_id]]
    ]
    return sorted(selected, key=editorial_score, reverse=True)
