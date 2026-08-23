-- items.section_id 는 section-first 계층 전환으로 제거됐다.
-- 남아 있던 BEFORE DELETE 트리거가 section_id 를 갱신하려 해
-- 폴더 삭제가 42703 으로 실패했다. delete_folder RPC 와
-- items.folder_id ON DELETE SET NULL 가 이미 정리하므로 제거한다.

drop trigger if exists folders_clear_item_links on bookmark.folders;
drop function if exists bookmark.clear_folder_links();
