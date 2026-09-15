from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=1800)


@event.listens_for(engine, "connect")
def _force_utc_session(dbapi_connection, connection_record):
    # The host OS can be set to any local time zone (this one runs on
    # Kuwait time, UTC+3). All Python-side timestamps use naive UTC
    # (datetime.utcnow()); without this, MySQL's own CURRENT_TIMESTAMP /
    # NOW() defaults would be 3 hours ahead and silently corrupt any
    # comparison between an app-computed time and a database-computed one
    # (e.g. an upload grant's expiry looking earlier than its grant time).
    cursor = dbapi_connection.cursor()
    cursor.execute("SET time_zone = '+00:00'")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
