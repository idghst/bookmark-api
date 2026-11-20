-- bookmark-api 전용 최소 권한 롤. 슈퍼유저로 DB bookmark에서 실행한다(여러 번 실행해도 된다).
--   docker exec -i -u postgres postgres psql -v ON_ERROR_STOP=1 -d bookmark < db/bookmark_app.sql
-- 비밀번호는 이 파일에 두지 않는다. 실행 뒤 따로 정한다(README 참고).

do $$
begin
  if not exists (select from pg_roles where rolname = 'bookmark_app') then
    create role bookmark_app login;
  end if;
end
$$;

grant connect on database bookmark to bookmark_app;
-- auth: reorder_resources·delete_folder가 호환 함수 auth.uid()를 부른다.
grant usage on schema bookmark, auth to bookmark_app;
grant select, insert, update, delete
  on bookmark.items, bookmark.folders, bookmark.sections, bookmark.folder_sections
  to bookmark_app;
grant execute on function
  bookmark.reorder_resources(text, jsonb, uuid),
  bookmark.delete_folder(uuid, uuid, uuid),
  auth.uid(),
  auth.jwt()
  to bookmark_app;

-- 네 테이블은 RLS가 켜져 있다. 소유자 범위는 API가 모든 쿼리에 user_id 조건으로 건다.
drop policy if exists bookmark_app_access on bookmark.items;
create policy bookmark_app_access on bookmark.items
  to bookmark_app using (true) with check (true);
drop policy if exists bookmark_app_access on bookmark.folders;
create policy bookmark_app_access on bookmark.folders
  to bookmark_app using (true) with check (true);
drop policy if exists bookmark_app_access on bookmark.sections;
create policy bookmark_app_access on bookmark.sections
  to bookmark_app using (true) with check (true);
drop policy if exists bookmark_app_access on bookmark.folder_sections;
create policy bookmark_app_access on bookmark.folder_sections
  to bookmark_app using (true) with check (true);
