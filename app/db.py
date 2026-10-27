from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.db_url, pool_pre_ping=True, pool_recycle=3600,
                       pool_size=settings.db_pool_size,
                       max_overflow=settings.db_max_overflow,
                       pool_timeout=settings.db_pool_timeout)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind=None) -> None:
    import app.models  # noqa: F401
    Base.metadata.create_all(bind or engine)
