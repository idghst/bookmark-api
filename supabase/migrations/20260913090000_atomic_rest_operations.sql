-- PostgREST operations spanning several writes must run in one transaction.
-- Replacing delete_folder keeps its existing grants and SECURITY INVOKER.
create or replace function bookmark.delete_folder(
  p_folder_id uuid,
  p_destination_folder_id uuid,
  p_user_id uuid
)
returns table (id uuid)
language plpgsql
security invoker
set search_path = pg_catalog, bookmark
as $$
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

create function bookmark.reorder_resources(p_table text, p_updates jsonb, p_user_id uuid)
returns table (id uuid)
language plpgsql
security invoker
set search_path = pg_catalog, bookmark
as $$
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
$$;

revoke all on function bookmark.reorder_resources(text, jsonb, uuid) from public;
grant execute on function bookmark.reorder_resources(text, jsonb, uuid) to service_role;
notify pgrst, 'reload schema';
