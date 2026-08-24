import fakeredis
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models  # noqa: F401 register models with Base
from app import redis_client as redis_client_module


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Every test gets an isolated in-memory Redis so tests never talk to a
    real Redis instance and never leak state between tests."""
    server = fakeredis.FakeServer()
    client = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    monkeypatch.setattr(redis_client_module, "get_redis", lambda: client)
    return client


@pytest.fixture()
def project(db_session):
    p = models.Project(
        name="demo",
        repo_url="https://example.com/demo.git",
        pipeline_yaml=(
            "image: python:3.11-slim\n"
            "steps:\n"
            "  - name: test\n"
            "    run: pytest -q\n"
        ),
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


@pytest.fixture()
def worker(db_session):
    w = models.Worker(name="test-worker")
    db_session.add(w)
    db_session.commit()
    db_session.refresh(w)
    return w
