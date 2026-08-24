from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables if they don't exist. A real deployment would use Alembic
    migrations (scaffolded in alembic/); create_all is used here so the
    project runs out of the box with `docker compose up`."""
    from app import models  # noqa: F401 ensure models are registered
    Base.metadata.create_all(bind=engine)
