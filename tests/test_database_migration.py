from pathlib import Path

MIGRATION = (
    Path(__file__).parent.parent
    / "supabase"
    / "migrations"
    / "20260726160000_add_bookmark_resources.sql"
)
SECTION_COLOR_MIGRATION = (
    Path(__file__).parent.parent
    / "supabase"
    / "migrations"
    / "20260804222840_add_section_color.sql"
)
ITEM_COLOR_MIGRATION = (
    Path(__file__).parent.parent
    / "supabase"
    / "migrations"
    / "20260818120000_add_item_color.sql"
)
SECTION_FIRST_HIERARCHY_MIGRATION = (
    Path(__file__).parent.parent
    / "supabase"
    / "migrations"
    / "20260820100000_section_first_hierarchy.sql"
)
FOLDER_SECTIONS_MIGRATION = (
    Path(__file__).parent.parent
    / "supabase"
    / "migrations"
    / "20260821110000_add_folder_sections.sql"
)
FOLDER_SECTIONS_SERVICE_ROLE_GRANT = (
    Path(__file__).parent.parent
    / "supabase"
    / "migrations"
    / "20260821113000_grant_folder_sections_service_role.sql"
)
FOLDER_SECTIONS_DROP_AUTH_USERS_FKEY = (
    Path(__file__).parent.parent
    / "supabase"
    / "migrations"
    / "20260821120000_drop_folder_sections_auth_users_fkey.sql"
)
DROP_OBSOLETE_CLEAR_FOLDER_LINKS = (
    Path(__file__).parent.parent
    / "supabase"
    / "migrations"
    / "20260823140000_drop_obsolete_clear_folder_links.sql"
)


def test_resource_migration_creates_expected_tables() -> None:
    sql = MIGRATION.read_text()

    for table in ("folders", "sections", "items"):
        assert f"create table if not exists bookmark.{table}" in sql
        assert f"alter table bookmark.{table} enable row level security" in sql


def test_resource_migration_has_operation_specific_owner_policies() -> None:
    sql = MIGRATION.read_text()

    for table in ("folders", "sections", "items"):
        for operation in ("select", "insert", "update", "delete"):
            assert f"create policy {table}_{operation}_own" in sql
        assert sql.count(f"on bookmark.{table}") >= 5

    assert sql.count("(select auth.uid()) = user_id") == 15
    assert "to authenticated" in sql
    assert "to anon" not in sql


def test_section_color_migration_adds_nullable_color_column() -> None:
    assert SECTION_COLOR_MIGRATION.read_text() == (
        "alter table bookmark.sections\n  add column color text;\n"
    )


def test_item_color_migration_adds_nullable_color_column() -> None:
    assert ITEM_COLOR_MIGRATION.read_text() == (
        "alter table bookmark.items\n  add column if not exists color text;\n"
    )


def test_section_first_hierarchy_migration_reverses_resource_ownership() -> None:
    sql = SECTION_FIRST_HIERARCHY_MIGRATION.read_text()

    assert "drop column if exists parent_id" in sql
    assert "drop column if exists folder_id" in sql
    assert "drop column if exists section_id" in sql
    assert "add column if not exists section_id uuid" in sql
    assert "foreign key (section_id, user_id)" in sql
    assert "references bookmark.sections (id, user_id)" in sql
    assert "on delete set null (section_id)" in sql
    assert "folders_owner_section_position_idx" in sql
    assert "sections_owner_position_idx" in sql
    assert "drop function if exists bookmark.move_section" in sql
    assert "drop trigger if exists folders_parent_integrity" in sql
    assert "drop function if exists bookmark.enforce_folder_parent_integrity()" in sql
    assert "create or replace function bookmark.delete_folder(" in sql
    assert "set folder_id = p_destination_folder_id" in sql
    assert "and item.folder_id = p_folder_id" in sql
    assert "security invoker" in sql
    assert "set search_path = pg_catalog, bookmark" in sql
    assert (
        "revoke all on function bookmark.delete_folder(uuid, uuid, uuid) from public"
        in sql
    )
    assert "to authenticated, service_role" in sql


def test_folder_sections_migration_keeps_top_level_sections_separate() -> None:
    sql = FOLDER_SECTIONS_MIGRATION.read_text()

    assert "create table bookmark.folder_sections" in sql
    assert "folder_id uuid not null" in sql
    assert "add column folder_section_id uuid" in sql
    assert "references bookmark.folder_sections (id, folder_id, user_id)" in sql
    assert "on delete set null (folder_section_id)" in sql
    assert "delete from bookmark." not in sql
    assert "drop table" not in sql
    assert "create or replace function bookmark.move_bookmark_within_folder" in sql
    assert "destination.folder_id <> source.folder_id" in sql
    assert "folder_sections_select_own" in sql


def test_folder_sections_service_role_grant_does_not_wipe_data() -> None:
    sql = FOLDER_SECTIONS_SERVICE_ROLE_GRANT.read_text()

    assert "on bookmark.folder_sections" in sql
    assert "to service_role" in sql
    assert "delete from bookmark." not in sql
    assert "drop table" not in sql


def test_folder_sections_drop_auth_users_fkey_keeps_folder_ownership() -> None:
    sql = FOLDER_SECTIONS_DROP_AUTH_USERS_FKEY.read_text()

    assert "drop constraint folder_sections_user_id_fkey" in sql
    assert "delete from bookmark." not in sql
    assert "drop table" not in sql
    assert "drop constraint folder_sections_folder_id_user_id_fkey" not in sql


def test_drop_obsolete_clear_folder_links_removes_section_id_trigger() -> None:
    sql = DROP_OBSOLETE_CLEAR_FOLDER_LINKS.read_text()
    statements = "\n".join(
        line
        for line in sql.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    )

    assert (
        "drop trigger if exists folders_clear_item_links on bookmark.folders"
        in statements
    )
    assert "drop function if exists bookmark.clear_folder_links()" in statements
    assert "delete from bookmark." not in statements
    assert "drop table" not in statements
    assert "section_id" not in statements
