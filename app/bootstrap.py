from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.models import Feed, Schedule, Setting
from app.services import DEFAULT_SETTINGS


def initialize(db: Session) -> None:
    Base.metadata.create_all(bind=engine)
    for key, value in DEFAULT_SETTINGS.items():
        if db.get(Setting, key) is None:
            db.add(Setting(key=key, value=value))
    if db.get(Schedule, 1) is None:
        db.add(Schedule(id=1))
    if db.scalar(select(Feed.id).where(Feed.url == "mock://demo")) is None:
        db.add(Feed(name="DailyNews Démo", url="mock://demo", category="Divers", weight=1, priority=1))
    db.commit()
