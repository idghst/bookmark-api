import os

import pytest
from pydantic_settings import SettingsConfigDict

from app.core.config import Settings, clear_settings_cache

os.environ["SUPABASE_URL"] = "https://db.example.com"
os.environ["SUPABASE_SECRET_KEY"] = "test-secret"

Settings.model_config = SettingsConfigDict(
    **{**Settings.model_config, "env_file": None}
)


@pytest.fixture(autouse=True)
def clear_cached_settings() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()
