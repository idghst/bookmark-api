import os

import pytest
from pydantic_settings import SettingsConfigDict

from app.core.config import Settings, clear_settings_cache

os.environ.setdefault("DATABASE_URL", "postgresql://postgres@localhost/bookmark_test")

Settings.model_config = SettingsConfigDict(env_file=None, extra="ignore")


@pytest.fixture(autouse=True)
def clear_cached_settings() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()
