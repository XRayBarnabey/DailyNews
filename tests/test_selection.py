import unittest
from datetime import UTC, datetime

from app.newsroom.selection import CandidateArticle, FeedQuota, select_articles


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 6, tzinfo=UTC)
        self.end = datetime(2026, 10, 7, tzinfo=UTC)

    def make_articles(self, feed_id, count, *, offset=0):
        return [
            CandidateArticle(
                offset + index,
                feed_id,
                f"Article {feed_id} {index} headline",
                f"https://news.test/{feed_id}/{index}",
                self.start,
            )
            for index in range(count)
        ]

    def test_weighted_selection_respects_availability_and_maximum(self):
        feeds = [FeedQuota(1, "A", weight=1), FeedQuota(2, "B", weight=2), FeedQuota(3, "C", weight=1)]
        articles = (
            self.make_articles(1, 100) + self.make_articles(2, 20, offset=100) + self.make_articles(3, 5, offset=200)
        )
        selected = select_articles(articles, feeds, period_start=self.start, period_end=self.end, maximum_total=30)
        counts = {feed.id: sum(article.feed_id == feed.id for article in selected) for feed in feeds}
        self.assertEqual(len(selected), 30)
        self.assertEqual(counts, {1: 8, 2: 17, 3: 5})

    def test_deduplicates_tracking_urls_and_titles(self):
        feeds = [FeedQuota(1, "A", weight=1), FeedQuota(2, "B", weight=1, priority=1)]
        articles = [
            CandidateArticle(
                1, 1, "Une grande nouvelle mondiale", "https://news.test/story?utm_source=rss", self.start
            ),
            CandidateArticle(2, 2, "Une grande nouvelle mondiale", "https://mirror.test/story", self.start),
        ]
        selected = select_articles(articles, feeds, period_start=self.start, period_end=self.end, maximum_total=10)
        self.assertEqual([article.id for article in selected], [2])

    def test_excludes_inactive_feeds_and_out_of_period_articles(self):
        feeds = [FeedQuota(1, "A", active=False), FeedQuota(2, "B")]
        articles = self.make_articles(1, 1) + [
            CandidateArticle(
                2, 2, "Outside article headline", "https://news.test/out", datetime(2026, 10, 5, tzinfo=UTC)
            )
        ]
        self.assertEqual(
            select_articles(articles, feeds, period_start=self.start, period_end=self.end, maximum_total=10), []
        )

    def test_maximum_and_missing_dates(self):
        feeds = [FeedQuota(1, "A", maximum=1)]
        articles = self.make_articles(1, 3)
        articles.append(CandidateArticle(4, 1, "Undated article headline", "https://news.test/undated", None))
        selected = select_articles(articles, feeds, period_start=self.start, period_end=self.end, maximum_total=10)
        self.assertEqual(len(selected), 1)

    def test_empty_single_feed_and_capped_feed(self):
        self.assertEqual(select_articles([], [], period_start=self.start, period_end=self.end, maximum_total=10), [])
        one_feed = [FeedQuota(1, "A", weight=0)]
        available = self.make_articles(1, 1)
        self.assertEqual(
            len(select_articles(available, one_feed, period_start=self.start, period_end=self.end, maximum_total=10)), 1
        )
        capped = [FeedQuota(1, "A", maximum=1), FeedQuota(2, "B", weight=1)]
        articles = self.make_articles(1, 10) + self.make_articles(2, 10, offset=100)
        selected = select_articles(articles, capped, period_start=self.start, period_end=self.end, maximum_total=6)
        self.assertEqual(len(selected), 6)
        self.assertEqual(sum(article.feed_id == 1 for article in selected), 1)

    def test_minimum_quotas_follow_priority_when_capacity_is_tight(self):
        feeds = [FeedQuota(1, "Prioritaire", minimum=3, priority=2), FeedQuota(2, "Secondaire", minimum=3)]
        articles = self.make_articles(1, 5) + self.make_articles(2, 5, offset=100)
        selected = select_articles(articles, feeds, period_start=self.start, period_end=self.end, maximum_total=4)
        self.assertEqual(sum(article.feed_id == 1 for article in selected), 3)
        self.assertEqual(sum(article.feed_id == 2 for article in selected), 1)


if __name__ == "__main__":
    unittest.main()
