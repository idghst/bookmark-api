from app.core.config import Settings


def test_runtime_uses_direct_postgresql_credentials() -> None:
    assert "DATABASE_URL" in Settings.model_fields
    assert "BOOKMARK_USER_ID" in Settings.model_fields
    assert not any(name.startswith("SUPABASE") for name in Settings.model_fields)
