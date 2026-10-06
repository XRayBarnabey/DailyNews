from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Feed(Base):
    __tablename__ = "feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    category: Mapped[str] = mapped_column(String(40), default="Divers")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    minimum: Mapped[int] = mapped_column(Integer, default=0)
    maximum: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(30), default="Jamais récupéré")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    articles: Mapped[list["Article"]] = relationship(back_populates="feed", cascade="all, delete-orphan")


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("feed_id", "url", name="uq_article_feed_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feeds.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(2048))
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    categories: Mapped[str] = mapped_column(String(500), default="")
    feed: Mapped[Feed] = relationship(back_populates="articles")


class Edition(Base):
    __tablename__ = "editions"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pdf_path: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(30), default="ready")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[str] = mapped_column(Text, default="")
    print_status: Mapped[str] = mapped_column(String(30), default="non imprimé")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Schedule(Base):
    __tablename__ = "schedule"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    fetch_time: Mapped[str] = mapped_column(String(5), default="05:30")
    generate_time: Mapped[str] = mapped_column(String(5), default="06:00")
    print_time: Mapped[str] = mapped_column(String(5), default="06:10")
    active_days: Mapped[str] = mapped_column(String(30), default="0,1,2,3,4,5,6")
    auto_generate: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_print: Mapped[bool] = mapped_column(Boolean, default=False)
    printer_name: Mapped[str] = mapped_column(String(200), default="")
    copies: Mapped[int] = mapped_column(Integer, default=1)
    duplex: Mapped[bool] = mapped_column(Boolean, default=True)


class PrintJob(Base):
    __tablename__ = "print_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("editions.id"))
    printer_name: Mapped[str] = mapped_column(String(200))
    copies: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
