from __future__ import annotations

import os
from typing import Generator
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
load_dotenv()

def _local_database_url() -> str:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = quote_plus(os.getenv("POSTGRES_PASSWORD", ""))
    db_name = os.getenv("POSTGRES_DB", "flood_management_system")
    sslmode = os.getenv("POSTGRES_SSLMODE", "disable")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}?sslmode={sslmode}"


def _normalize_database_url(url: str) -> str:
    # SQLAlchemy expects postgresql:// (or postgresql+driver://), not postgres://
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def _build_database_url() -> str:
    """
    DB selection strategy:
    - APP_ENV=local (default): always use local POSTGRES_* settings
    - APP_ENV=production|cloud: use DATABASE_URL (Neon or other managed DB)
    """
    app_env = os.getenv("APP_ENV", "local").strip().lower()
    explicit_url = os.getenv("DATABASE_URL", "").strip()

    if app_env in {"production", "prod", "cloud"}:
        if not explicit_url:
            raise RuntimeError("APP_ENV is production/cloud but DATABASE_URL is not set.")
        return _normalize_database_url(explicit_url)

    return _local_database_url()


DATABASE_URL = _build_database_url()


engine = create_engine(DATABASE_URL, future=True, echo=False)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)

Base = declarative_base()


def get_db() -> Generator:
    """
    Scoped SQLAlchemy session dependency.

    In production, this is used by routers to talk to PostgreSQL.
    For now, routers can fall back to dummy data if the database
    is not yet provisioned.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> None:
    """
    Fail fast if PostgreSQL is unreachable or credentials are invalid.
    """
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def create_db_and_tables() -> None:
    """
    Import models and create tables that don't exist yet.
    """
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    seed_initial_data()


def seed_initial_data() -> None:
    """
    Seed small baseline data so operational pages are usable on first run.
    """
    from .models import District

    db = SessionLocal()
    try:
        if db.query(District).count() == 0:
            db.add_all(
                [
                    District(name="Dhaka", code="DHK"),
                    District(name="Chattogram", code="CTG"),
                    District(name="Sylhet", code="SYL"),
                ]
            )
            db.commit()

    finally:
        db.close()

