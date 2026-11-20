# fastapi-bookmark

메인 Postgres의 DB `bookmark`(스키마 `bookmark`)에 있는 `items`, `folders`,
`sections`, `folder_sections`를 psycopg로 직접 읽고 쓰는 FastAPI 서비스입니다.
DB에 붙는 것은 이 API뿐이고 웹·모바일은 이 API만 호출합니다.
Supabase(PostgREST, Auth, Realtime)는 쓰지 않습니다.

## 실행

Python 3.12와 uv가 필요합니다.

```bash
uv sync --locked --dev
# .env.local이 없는 경우에만 .env.example을 복사합니다.
# .env.local에 DATABASE_URL, BOOKMARK_API_KEY 설정
uv run python -m uvicorn app.main:app --reload
```

로컬에서는 저장소 루트의 `.env`, `.env.local` 순서로 읽습니다.
실제 환경 변수가 파일보다 우선하므로 운영에서는 같은 이름을 Vercel에 등록합니다.
`DATABASE_URL`(앱 전용 롤 `bookmark_app`)이 필수이며,
리소스 접근에는 웹과 동일한 `BOOKMARK_API_KEY`를 설정합니다.
비밀값은 API 서버에만 보관합니다. `DATABASE_TIMEOUT_SECONDS`(기본 10초)는
연결 대기와 쿼리(`statement_timeout`) 제한 시간입니다.
예전 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`는 더 읽지 않습니다. 기존 `.env.local`에
남아 있어도 무시되므로, `DATABASE_URL`을 추가한 뒤 두 줄을 지우고 Supabase 키는 폐기합니다.

`BOOKMARK_USER_ID`를 UUID로 지정하면 해당 소유자로 동작합니다.
미설정이면 네 테이블의 서로 다른 `user_id`를 한 쿼리로 최대 두 개까지 읽어
유일한 소유자를 선택합니다. 데이터가 없거나 소유자가 복수이면 503으로 거부합니다.
빈 DB를 시작할 때는 `BOOKMARK_USER_ID`가 필요합니다.

## 인증과 데이터 접근

리소스와 `GET /api/v1/auth/me`는 `X-Bookmark-Key`만 받습니다.
`Authorization: Bearer` JWT 지원은 제거됐습니다.
`auth/me` 응답은 `{ "id": "<소유자 UUID>", "email": null }`입니다.
브라우저에는 키를 전달하지 않고 웹 BFF에서만 보관합니다.

모든 리소스 요청에 `user_id` 조건을 강제하고 부모 폴더·섹션의 소유자를 확인합니다.
모든 쿼리는 파라미터 바인딩을 쓰고, 테이블·컬럼 이름은 코드에 고정된 값만 씁니다.
고유 `id`로 조회하는 부모 확인·이동 전 조회는 한 번의 DB 요청으로 끝냅니다.
폴더 삭제와 여러 항목의 정렬은 `delete_folder`, `reorder_resources` RPC에서
각각 한 트랜잭션으로 처리합니다. 중간 실패 시 해당 RPC 전체가 취소됩니다.

API와 readiness 검사는 앱 lifespan 동안 하나의 psycopg 연결 풀(최대 5)을 공유하고,
앱 종료 시 닫습니다. ASGI lifespan을 끈 호출에서는 요청별 연결을 사용합니다.
연결은 autocommit이며 세션 시간대는 UTC라 `createdAt` 등은 예전과 같은
`2026-01-01T00:00:00+00:00` 형식입니다.
소유자와 리소스 응답은 캐시하지 않아 DB 변경을 다음 요청에 반영합니다.

`supabase/migrations/`는 Supabase 시절 이력이고, 현재 운영 스키마 사본은
`tests/schema.sql`입니다. 애플리케이션 시작 시 스키마나 권한을 자동 변경하지 않습니다.

### DB 롤 준비 (운영 DB 관리자가 한 번 실행)

`db/bookmark_app.sql`은 로그인 롤 `bookmark_app`을 만들고 네 테이블 CRUD, RPC 두 개,
`auth.uid()`(RPC가 호출) 실행 권한과 RLS 정책 `bookmark_app_access`를 줍니다.
`audit_log`, 백업 테이블에는 권한이 없습니다. 여러 번 실행해도 됩니다.

```bash
docker exec -i -u postgres postgres psql -v ON_ERROR_STOP=1 -d bookmark < db/bookmark_app.sql
docker exec -it -u postgres postgres psql -d bookmark -c '\password bookmark_app'
```

그다음 API가 실행되는 docker 네트워크의 서브넷으로 `pg_hba.conf`에
`host bookmark bookmark_app <서브넷> scram-sha-256` 줄을 넣고 `select pg_reload_conf()`를
실행합니다(절차는 `데이터베이스/README.md`의 "접근 정책"). Postgres는
`127.0.0.1:5432`에만 열려 있으므로 API가 같은 호스트의 docker 네트워크에서 실행돼야 합니다.

## API

- `GET /`, `GET /health`, `GET /health/live`
- `GET /health/ready`: Postgres `bookmark.items` 읽기 연결 확인
- `GET /api/v1/auth/me`
- `GET /api/snapshot`: 한 번 인증한 뒤 네 리소스 목록을 병렬 조회합니다.
  응답은 `{ "bookmarks": [], "folders": [], "sections": [], "folderSections": [] }`이며,
  각 배열은 기존 개별 GET과 같은 필드·정렬·소유자 조건을 사용합니다.
  캐시 없이 읽으며, 네 조회가 하나의 DB 트랜잭션 스냅샷을 보장하지는 않습니다.
- `/api/bookmarks`, `/api/folders`, `/api/sections`, `/api/folder-sections`
  각각 GET/POST, `/{id}` PATCH/DELETE, `/reorder` POST
- 폴더 삭제: `DELETE /api/folders/{id}?destination_folder_id={id}`
  북마크를 대상 폴더 끝으로 옮기고 내부 섹션을 해제한 뒤 폴더를 삭제합니다.
  대상 생략 시 폴더 없는 북마크로 이동합니다.

기존 camelCase 필드(`isFavorite`, `folderId`, `folderSectionId`, `sectionId`,
`createdAt`, `updatedAt`, `userId`)를 유지합니다.
`/api/folders/tree`는 제공하지 않습니다.

```bash
curl -H "X-Bookmark-Key: $BOOKMARK_API_KEY" http://localhost:8000/api/bookmarks
```

오류는 `{ "code", "message", "request_id" }` 봉투와 `X-Request-ID`를 유지합니다.
DB 오류의 원문이나 자격 증명은 응답하지 않습니다.

환경은 요청 Host/URL로 판별합니다. production host에서는
`/docs`, `/redoc`, `/openapi.json`을 숨깁니다.
CORS는 `http://localhost:3000`, 로그는 INFO JSON으로 고정합니다.

## 검증

```bash
uv lock --check
uv run python -m ruff format --check app tests
uv run python -m ruff check --no-cache app tests
uv run python -m mypy app
uv run python -m pytest --cov=app --cov-report=term-missing
uv run python -m pip_audit
```

DB 테스트는 `TEST_DATABASE_URL`(DB 이름 `bookmark`, 슈퍼유저)이 있을 때만 돕니다.
그 DB의 `bookmark`·`auth`·`extensions` 스키마를 지우고 `tests/schema.sql`과
`db/bookmark_app.sql`을 적용한 뒤 `bookmark_app` 롤로 CRUD, 소유자 격리, RPC,
오류 변환을 검증합니다. 운영 DB를 가리키지 않게 임시 컨테이너를 씁니다.
CI는 같은 이미지를 서비스 컨테이너로 띄웁니다.

```bash
docker run -d --rm --name tmp-pg-bookmark -e POSTGRES_PASSWORD=test -e POSTGRES_DB=bookmark \
  -p 127.0.0.1:5561:5432 pgvector/pgvector:pg17
TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:5561/bookmark uv run python -m pytest
docker rm -f tmp-pg-bookmark
```

## 배포

Vercel project: `idghst/api-bookmark`. Preview/Production 서버 환경에
`DATABASE_URL`, `BOOKMARK_API_KEY`, 필요 시 `BOOKMARK_USER_ID`를 설정하고
`SUPABASE_URL`, `SUPABASE_SECRET_KEY`는 지웁니다.
서버에서 Postgres에 접속할 수 있어야 합니다. 메인 Postgres는 맥미니
`127.0.0.1:5432`에만 열려 있어 Vercel에서는 붙을 수 없습니다. 이 전환을 배포하기 전에
API 실행 위치(맥미니 docker 컨테이너 등)를 먼저 정합니다.

CI 통과 후 Preview에서 `/health/live`, `/health/ready`, 잘못된 키의 401,
실제 키의 CRUD를 확인하고 Production으로 승격합니다.

```bash
vercel build --target=preview
vercel deploy --target=preview
vercel inspect <preview-url>
vercel promote <preview-url>
```

문제는 `X-Request-ID`로 추적하고 비밀 키를 로그·커밋에 남기지 않습니다.
