import os
import secrets
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from pydantic_settings import SettingsConfigDict

from app.core.config import Settings, clear_settings_cache

ROOT = Path(__file__).resolve().parents[1]
# Closed port: requests that reach the database fail fast with 503.
UNREACHABLE_DATABASE_URL = "postgresql://bookmark_app@127.0.0.1:9/bookmark"
os.environ["DATABASE_URL"] = UNREACHABLE_DATABASE_URL

Settings.model_config = SettingsConfigDict(
    **{**Settings.model_config, "env_file": None}
)


@pytest.fixture(autouse=True)
def clear_cached_settings() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture(scope="session")
def app_database_url() -> str:
    """Load the production schema and app role into TEST_DATABASE_URL (a DB named
    bookmark, superuser) and return a connection string for bookmark_app."""
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url:
        pytest.skip("TEST_DATABASE_URL is not set")
    password = secrets.token_hex(16)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        for role in ("agent_crud", "agent_readonly", "authenticated"):
            if not conn.execute(
                "select 1 from pg_roles where rolname = %s", [role]
            ).fetchone():
                conn.execute(sql.SQL("create role {}").format(sql.Identifier(role)))
        conn.execute("drop schema if exists bookmark, auth, extensions cascade")
        conn.execute((ROOT / "tests" / "schema.sql").read_text())
        conn.execute((ROOT / "db" / "bookmark_app.sql").read_text())
        conn.execute(
            sql.SQL("alter role bookmark_app password {}").format(sql.Literal(password))
        )
    return make_conninfo(admin_url, user="bookmark_app", password=password)


@pytest.fixture
def db(app_database_url: str) -> Iterator[psycopg.Connection]:
    """Admin connection to an empty schema, for seeding and inspection."""
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as conn:
        conn.execute(
            "truncate bookmark.items, bookmark.folder_sections, bookmark.folders,"
            " bookmark.sections"
        )
        yield conn
