-- 운영 DB bookmark의 스키마 사본(테스트 픽스처). 갱신: pg_dump -s --no-owner --no-privileges -d bookmark 결과에서 psql 메타 명령 줄을 뺀다.
--
-- PostgreSQL database dump
--


-- Dumped from database version 17.12 (Debian 17.12-1.pgdg12+1)
-- Dumped by pg_dump version 17.12 (Debian 17.12-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: auth; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA auth;


--
-- Name: bookmark; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA bookmark;


--
-- Name: extensions; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA extensions;


--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS '';


--
-- Name: btree_gist; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA extensions;


--
-- Name: EXTENSION btree_gist; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION btree_gist IS 'support for indexing common datatypes in GiST';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: jwt(); Type: FUNCTION; Schema: auth; Owner: -
--

CREATE FUNCTION auth.jwt() RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb
$$;


--
-- Name: role(); Type: FUNCTION; Schema: auth; Owner: -
--

CREATE FUNCTION auth.role() RETURNS text
    LANGUAGE sql STABLE
    AS $$
  select coalesce(nullif(current_setting('request.jwt.claim.role', true), ''), auth.jwt() ->> 'role')
$$;


--
-- Name: uid(); Type: FUNCTION; Schema: auth; Owner: -
--

CREATE FUNCTION auth.uid() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$
  select nullif(coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''), auth.jwt() ->> 'sub'), '')::uuid
$$;


--
-- Name: clear_folder_section_on_folder_change(); Type: FUNCTION; Schema: bookmark; Owner: -
--

CREATE FUNCTION bookmark.clear_folder_section_on_folder_change() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'bookmark'
    AS $$
begin
  if new.folder_id is distinct from old.folder_id
    and new.folder_section_id is not distinct from old.folder_section_id then
    new.folder_section_id := null;
  end if;
  return new;
end;
$$;


--
-- Name: delete_folder(uuid, uuid, uuid); Type: FUNCTION; Schema: bookmark; Owner: -
--

CREATE FUNCTION bookmark.delete_folder(p_folder_id uuid, p_destination_folder_id uuid, p_user_id uuid) RETURNS TABLE(id uuid)
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'bookmark'
    AS $$
declare
  start_position integer;
begin
  if p_user_id is null then
    raise exception using errcode = '22004', message = 'A folder owner is required';
  end if;
  if (select auth.uid()) is not null and (select auth.uid()) <> p_user_id then
    raise exception using errcode = '42501', message = 'Folder owner does not match caller';
  end if;
  if p_destination_folder_id = p_folder_id then
    raise exception using errcode = '23514', message = 'A folder cannot be its own deletion destination';
  end if;

  -- Serialize deletion appends, including the destination with no folder row.
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  perform folder.id from bookmark.folders as folder
  where folder.user_id = p_user_id
    and folder.id in (p_folder_id, p_destination_folder_id)
  order by folder.id for update;
  if not exists (select 1 from bookmark.folders as folder
    where folder.id = p_folder_id and folder.user_id = p_user_id) then
    raise exception using errcode = 'P0002', message = 'Folder not found';
  end if;
  if p_destination_folder_id is not null and not exists (
    select 1 from bookmark.folders as folder
    where folder.id = p_destination_folder_id and folder.user_id = p_user_id
  ) then
    raise exception using errcode = 'P0002', message = 'Deletion destination folder not found';
  end if;

  perform item.id from bookmark.items as item
  where item.user_id = p_user_id and (
    item.folder_id = p_folder_id or
    (item.folder_id is not distinct from p_destination_folder_id and item.folder_section_id is null)
  ) order by item.id for update;
  select coalesce(max(item.position) + 1, 0) into start_position
  from bookmark.items as item where item.user_id = p_user_id
    and item.folder_id is not distinct from p_destination_folder_id
    and item.folder_section_id is null;

  with moved as (
    select item.id, row_number() over (order by item.position, item.id) - 1 as offset_position
    from bookmark.items as item where item.user_id = p_user_id and item.folder_id = p_folder_id
  )
  update bookmark.items as item
  set folder_id = p_destination_folder_id,
      folder_section_id = null,
      position = start_position + moved.offset_position,
      updated_at = now()
  from moved where item.id = moved.id and item.user_id = p_user_id;
  delete from bookmark.folder_sections as section
  where section.folder_id = p_folder_id and section.user_id = p_user_id;
  delete from bookmark.folders as folder
  where folder.id = p_folder_id and folder.user_id = p_user_id;
  return query select p_folder_id;
end;
$$;


--
-- Name: move_bookmark_within_folder(uuid, uuid, integer, uuid); Type: FUNCTION; Schema: bookmark; Owner: -
--

CREATE FUNCTION bookmark.move_bookmark_within_folder(p_item_id uuid, p_folder_section_id uuid, p_position integer, p_user_id uuid) RETURNS TABLE(id uuid, folder_section_id uuid, "position" integer)
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'bookmark'
    AS $$
declare
  source bookmark.items%rowtype;
  target_position integer;
begin
  if p_user_id is null then
    raise exception using errcode = '22004', message = 'A bookmark owner is required';
  end if;

  if (select auth.uid()) is not null
    and (select auth.uid()) <> p_user_id then
    raise exception using errcode = '42501', message = 'Bookmark owner does not match caller';
  end if;

  select item.*
  into source
  from bookmark.items as item
  where item.id = p_item_id
    and item.user_id = p_user_id
  for update;

  if not found then
    raise exception using errcode = 'P0002', message = 'Bookmark not found';
  end if;

  if p_folder_section_id is not null then
    if exists (
      select 1
      from bookmark.folder_sections as destination
      where destination.id = p_folder_section_id
        and destination.user_id = p_user_id
        and destination.folder_id <> source.folder_id
    ) then
      raise exception using
        errcode = '23514',
        message = 'Bookmark section must stay in the same folder';
    end if;

    if not exists (
      select 1
      from bookmark.folder_sections as destination
      where destination.id = p_folder_section_id
        and destination.user_id = p_user_id
        and destination.folder_id = source.folder_id
    ) then
      raise exception using errcode = 'P0002', message = 'Folder section not found';
    end if;
  end if;

  target_position := p_position;
  if target_position is null then
    select coalesce(max(item.position) + 1, 0)
    into target_position
    from bookmark.items as item
    where item.user_id = p_user_id
      and item.folder_id is not distinct from source.folder_id
      and item.folder_section_id is not distinct from p_folder_section_id
      and item.id <> p_item_id;
  end if;

  update bookmark.items as item
  set folder_section_id = p_folder_section_id,
      position = target_position,
      updated_at = now()
  where item.id = p_item_id
    and item.user_id = p_user_id;

  return query
  select item.id, item.folder_section_id, item.position
  from bookmark.items as item
  where item.id = p_item_id
    and item.user_id = p_user_id;
end;
$$;


--
-- Name: reorder_resources(text, jsonb, uuid); Type: FUNCTION; Schema: bookmark; Owner: -
--

CREATE FUNCTION bookmark.reorder_resources(p_table text, p_updates jsonb, p_user_id uuid) RETURNS TABLE(id uuid)
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'bookmark'
    AS $_$
declare
  change jsonb;
  changed_id uuid;
begin
  if p_user_id is null then
    raise exception using errcode = '22004', message = 'An owner is required';
  end if;
  if (select auth.uid()) is not null and (select auth.uid()) <> p_user_id then
    raise exception using errcode = '42501', message = 'Owner does not match caller';
  end if;
  if p_table is null or p_table not in ('items', 'folders', 'sections', 'folder_sections') then
    raise exception using errcode = '22P02', message = 'Invalid resource table';
  end if;
  if p_updates is null or jsonb_typeof(p_updates) <> 'array' then
    raise exception using errcode = '22P02', message = 'Updates must be an array';
  end if;
  -- Lock in a stable order before applying positions. Any missing/foreign row
  -- raises, rolling back every preceding update in this RPC call.
  execute format(
    'select resource.id from bookmark.%I as resource
     where resource.user_id = $1 and resource.id in
       (select (value->>''id'')::uuid from jsonb_array_elements($2))
     order by resource.id for update', p_table
  ) using p_user_id, p_updates;
  for change in select value from jsonb_array_elements(p_updates) loop
    if jsonb_typeof(change->'position') is distinct from 'number'
      or (change->>'position') !~ '^[0-9]+$'
      or change->>'id' is null then
      raise exception using errcode = '22P02', message = 'Invalid position update';
    end if;
    execute format(
      'update bookmark.%I set position = $1, updated_at = now()
       where id = $2 and user_id = $3 returning id', p_table
    ) into changed_id using (change->>'position')::integer, (change->>'id')::uuid, p_user_id;
    if changed_id is null then
      raise exception using errcode = 'P0002', message = 'Resource not found';
    end if;
    id := changed_id;
    return next;
  end loop;
end;
$_$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: bookmark; Owner: -
--

CREATE FUNCTION bookmark.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO ''
    AS $$
begin
  new.updated_at = now();
  return new;
end
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: users; Type: TABLE; Schema: auth; Owner: -
--

CREATE TABLE auth.users (
    id uuid NOT NULL,
    email text,
    created_at timestamp with time zone
);


--
-- Name: _hierarchy_backup_20260820; Type: TABLE; Schema: bookmark; Owner: -
--

CREATE TABLE bookmark._hierarchy_backup_20260820 (
    captured_at timestamp with time zone DEFAULT now() NOT NULL,
    folders jsonb NOT NULL,
    sections jsonb NOT NULL,
    items jsonb NOT NULL
);


--
-- Name: audit_log; Type: TABLE; Schema: bookmark; Owner: -
--

CREATE TABLE bookmark.audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    admin_user_id uuid,
    action text NOT NULL,
    target_type text NOT NULL,
    target_id text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: folder_sections; Type: TABLE; Schema: bookmark; Owner: -
--

CREATE TABLE bookmark.folder_sections (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    folder_id uuid NOT NULL,
    name text NOT NULL,
    color text,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT folder_sections_position_check CHECK (("position" >= 0))
);


--
-- Name: folders; Type: TABLE; Schema: bookmark; Owner: -
--

CREATE TABLE bookmark.folders (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name text NOT NULL,
    color text,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    section_id uuid,
    CONSTRAINT folders_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT folders_position_nonnegative CHECK (("position" >= 0))
);


--
-- Name: items; Type: TABLE; Schema: bookmark; Owner: -
--

CREATE TABLE bookmark.items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    title text NOT NULL,
    url text NOT NULL,
    description text,
    is_favorite boolean DEFAULT false,
    color text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    folder_id uuid,
    "position" integer DEFAULT 0 NOT NULL,
    folder_section_id uuid,
    CONSTRAINT items_folder_section_requires_folder CHECK (((folder_section_id IS NULL) OR (folder_id IS NOT NULL))),
    CONSTRAINT items_position_nonnegative CHECK (("position" >= 0)),
    CONSTRAINT items_title_not_blank CHECK ((btrim(title) <> ''::text)),
    CONSTRAINT items_url_not_blank CHECK ((btrim(url) <> ''::text))
);


--
-- Name: sections; Type: TABLE; Schema: bookmark; Owner: -
--

CREATE TABLE bookmark.sections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    color text,
    CONSTRAINT sections_name_not_blank CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT sections_position_nonnegative CHECK (("position" >= 0))
);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: auth; Owner: -
--

ALTER TABLE ONLY auth.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: folder_sections folder_sections_id_folder_id_user_id_key; Type: CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.folder_sections
    ADD CONSTRAINT folder_sections_id_folder_id_user_id_key UNIQUE (id, folder_id, user_id);


--
-- Name: folder_sections folder_sections_id_user_id_key; Type: CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.folder_sections
    ADD CONSTRAINT folder_sections_id_user_id_key UNIQUE (id, user_id);


--
-- Name: folder_sections folder_sections_pkey; Type: CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.folder_sections
    ADD CONSTRAINT folder_sections_pkey PRIMARY KEY (id);


--
-- Name: folders folders_id_user_key; Type: CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.folders
    ADD CONSTRAINT folders_id_user_key UNIQUE (id, user_id);


--
-- Name: folders folders_pkey; Type: CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.folders
    ADD CONSTRAINT folders_pkey PRIMARY KEY (id);


--
-- Name: items items_pkey; Type: CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.items
    ADD CONSTRAINT items_pkey PRIMARY KEY (id);


--
-- Name: sections sections_id_user_key; Type: CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.sections
    ADD CONSTRAINT sections_id_user_key UNIQUE (id, user_id);


--
-- Name: sections sections_pkey; Type: CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.sections
    ADD CONSTRAINT sections_pkey PRIMARY KEY (id);


--
-- Name: audit_log_admin_user_created_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX audit_log_admin_user_created_idx ON bookmark.audit_log USING btree (admin_user_id, created_at DESC);


--
-- Name: audit_log_created_at_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX audit_log_created_at_idx ON bookmark.audit_log USING btree (created_at DESC);


--
-- Name: audit_log_target_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX audit_log_target_idx ON bookmark.audit_log USING btree (target_type, target_id);


--
-- Name: folder_sections_owner_folder_position_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX folder_sections_owner_folder_position_idx ON bookmark.folder_sections USING btree (user_id, folder_id, "position", id);


--
-- Name: folders_owner_section_position_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX folders_owner_section_position_idx ON bookmark.folders USING btree (user_id, section_id, "position", id);


--
-- Name: folders_user_name_key; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE UNIQUE INDEX folders_user_name_key ON bookmark.folders USING btree (user_id, lower(btrim(name)));


--
-- Name: folders_user_position_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX folders_user_position_idx ON bookmark.folders USING btree (user_id, "position", id);


--
-- Name: items_folder_owner_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX items_folder_owner_idx ON bookmark.items USING btree (folder_id, user_id);


--
-- Name: items_folder_position_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX items_folder_position_idx ON bookmark.items USING btree (folder_id, "position", id) WHERE (folder_id IS NOT NULL);


--
-- Name: items_owner_folder_section_position_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX items_owner_folder_section_position_idx ON bookmark.items USING btree (user_id, folder_id, folder_section_id, "position", id);


--
-- Name: items_user_position_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX items_user_position_idx ON bookmark.items USING btree (user_id, "position", id);


--
-- Name: sections_owner_position_idx; Type: INDEX; Schema: bookmark; Owner: -
--

CREATE INDEX sections_owner_position_idx ON bookmark.sections USING btree (user_id, "position");


--
-- Name: folders folders_set_timestamps; Type: TRIGGER; Schema: bookmark; Owner: -
--

CREATE TRIGGER folders_set_timestamps BEFORE INSERT OR UPDATE ON bookmark.folders FOR EACH ROW EXECUTE FUNCTION bookmark.set_updated_at();


--
-- Name: items items_clear_folder_section_on_folder_change; Type: TRIGGER; Schema: bookmark; Owner: -
--

CREATE TRIGGER items_clear_folder_section_on_folder_change BEFORE UPDATE OF folder_id ON bookmark.items FOR EACH ROW EXECUTE FUNCTION bookmark.clear_folder_section_on_folder_change();


--
-- Name: items items_set_timestamps; Type: TRIGGER; Schema: bookmark; Owner: -
--

CREATE TRIGGER items_set_timestamps BEFORE INSERT OR UPDATE ON bookmark.items FOR EACH ROW EXECUTE FUNCTION bookmark.set_updated_at();


--
-- Name: sections sections_set_timestamps; Type: TRIGGER; Schema: bookmark; Owner: -
--

CREATE TRIGGER sections_set_timestamps BEFORE INSERT OR UPDATE ON bookmark.sections FOR EACH ROW EXECUTE FUNCTION bookmark.set_updated_at();


--
-- Name: audit_log audit_log_admin_user_id_fkey; Type: FK CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.audit_log
    ADD CONSTRAINT audit_log_admin_user_id_fkey FOREIGN KEY (admin_user_id) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: folder_sections folder_sections_folder_id_user_id_fkey; Type: FK CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.folder_sections
    ADD CONSTRAINT folder_sections_folder_id_user_id_fkey FOREIGN KEY (folder_id, user_id) REFERENCES bookmark.folders(id, user_id) ON DELETE CASCADE;


--
-- Name: folders folders_section_owner_fkey; Type: FK CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.folders
    ADD CONSTRAINT folders_section_owner_fkey FOREIGN KEY (section_id, user_id) REFERENCES bookmark.sections(id, user_id) ON DELETE SET NULL (section_id);


--
-- Name: items items_folder_owner_fkey; Type: FK CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.items
    ADD CONSTRAINT items_folder_owner_fkey FOREIGN KEY (folder_id, user_id) REFERENCES bookmark.folders(id, user_id) ON DELETE SET NULL (folder_id);


--
-- Name: items items_folder_section_same_folder_fkey; Type: FK CONSTRAINT; Schema: bookmark; Owner: -
--

ALTER TABLE ONLY bookmark.items
    ADD CONSTRAINT items_folder_section_same_folder_fkey FOREIGN KEY (folder_section_id, folder_id, user_id) REFERENCES bookmark.folder_sections(id, folder_id, user_id) ON DELETE SET NULL (folder_section_id);


--
-- Name: _hierarchy_backup_20260820; Type: ROW SECURITY; Schema: bookmark; Owner: -
--

ALTER TABLE bookmark._hierarchy_backup_20260820 ENABLE ROW LEVEL SECURITY;

--
-- Name: _hierarchy_backup_20260820 agent_backup_read; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_backup_read ON bookmark._hierarchy_backup_20260820 FOR SELECT TO agent_crud, agent_readonly USING (true);


--
-- Name: audit_log agent_crud_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_crud_access ON bookmark.audit_log TO agent_crud USING (true) WITH CHECK (true);


--
-- Name: folder_sections agent_crud_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_crud_access ON bookmark.folder_sections TO agent_crud USING (true) WITH CHECK (true);


--
-- Name: folders agent_crud_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_crud_access ON bookmark.folders TO agent_crud USING (true) WITH CHECK (true);


--
-- Name: items agent_crud_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_crud_access ON bookmark.items TO agent_crud USING (true) WITH CHECK (true);


--
-- Name: sections agent_crud_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_crud_access ON bookmark.sections TO agent_crud USING (true) WITH CHECK (true);


--
-- Name: _hierarchy_backup_20260820 agent_read_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_read_access ON bookmark._hierarchy_backup_20260820 FOR SELECT TO agent_readonly USING (true);


--
-- Name: audit_log agent_read_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_read_access ON bookmark.audit_log FOR SELECT TO agent_readonly USING (true);


--
-- Name: folder_sections agent_read_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_read_access ON bookmark.folder_sections FOR SELECT TO agent_readonly USING (true);


--
-- Name: folders agent_read_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_read_access ON bookmark.folders FOR SELECT TO agent_readonly USING (true);


--
-- Name: items agent_read_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_read_access ON bookmark.items FOR SELECT TO agent_readonly USING (true);


--
-- Name: sections agent_read_access; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY agent_read_access ON bookmark.sections FOR SELECT TO agent_readonly USING (true);


--
-- Name: audit_log; Type: ROW SECURITY; Schema: bookmark; Owner: -
--

ALTER TABLE bookmark.audit_log ENABLE ROW LEVEL SECURITY;

--
-- Name: folder_sections; Type: ROW SECURITY; Schema: bookmark; Owner: -
--

ALTER TABLE bookmark.folder_sections ENABLE ROW LEVEL SECURITY;

--
-- Name: folder_sections folder_sections_delete_own; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY folder_sections_delete_own ON bookmark.folder_sections FOR DELETE TO authenticated USING ((( SELECT auth.uid() AS uid) = user_id));


--
-- Name: folder_sections folder_sections_insert_own; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY folder_sections_insert_own ON bookmark.folder_sections FOR INSERT TO authenticated WITH CHECK ((( SELECT auth.uid() AS uid) = user_id));


--
-- Name: folder_sections folder_sections_select_own; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY folder_sections_select_own ON bookmark.folder_sections FOR SELECT TO authenticated USING ((( SELECT auth.uid() AS uid) = user_id));


--
-- Name: folder_sections folder_sections_update_own; Type: POLICY; Schema: bookmark; Owner: -
--

CREATE POLICY folder_sections_update_own ON bookmark.folder_sections FOR UPDATE TO authenticated USING ((( SELECT auth.uid() AS uid) = user_id)) WITH CHECK ((( SELECT auth.uid() AS uid) = user_id));


--
-- Name: folders; Type: ROW SECURITY; Schema: bookmark; Owner: -
--

ALTER TABLE bookmark.folders ENABLE ROW LEVEL SECURITY;

--
-- Name: items; Type: ROW SECURITY; Schema: bookmark; Owner: -
--

ALTER TABLE bookmark.items ENABLE ROW LEVEL SECURITY;

--
-- Name: sections; Type: ROW SECURITY; Schema: bookmark; Owner: -
--

ALTER TABLE bookmark.sections ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--


