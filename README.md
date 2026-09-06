# fastapi-bookmark

`bookmark` PostgreSQL 스키마의 `items`, `folders`, `sections`,
`folder_sections`를 psycopg 3으로 직접 사용하는 FastAPI 서비스입니다.

## 실행

Python 3.12와 uv가 필요합니다.

```bash
uv sync --locked --dev
cp .env.example .env.local
# .env.local에 DATABASE_URL, BOOKMARK_API_KEY 설정
uv run python -m uvicorn app.main:app --reload
```

`DATABASE_URL`은 `postgresql://user:password@host:5432/database?sslmode=require`
형식의 서버 비밀값입니다. 네트워크와 TLS 옵션은 실제 DB에 맞게 지정합니다.
기존 Supabase URL, publishable/secret key, JWT는 사용하지 않습니다.

`BOOKMARK_USER_ID`를 UUID로 지정하면 해당 소유자로 동작합니다.
미설정이면 네 테이블 전체의 서로 다른 `user_id`를 조회해 유일한 소유자를
선택합니다. 데이터가 없거나 소유자가 복수이면 503으로 거부합니다.
빈 DB를 시작할 때는 `BOOKMARK_USER_ID`가 필요합니다.

## 인증과 데이터 접근

리소스와 `GET /api/v1/auth/me`는 `X-Bookmark-Key`만 받습니다.
`Authorization: Bearer` JWT 지원은 제거됐습니다.
`auth/me` 응답은 `{ "id": "<소유자 UUID>", "email": null }`입니다.
브라우저에는 키를 전달하지 않고 웹 BFF에서만 보관합니다.

각 요청에 PostgreSQL 연결과 트랜잭션 하나를 사용하며 응답 전에 commit합니다.
실패하면 전체 요청을 rollback하므로 reorder 도중 오류가 나도 일부만 저장되지
않습니다. 모든 리소스 쿼리에 `user_id` 조건을 강제하고 부모 폴더·섹션의
소유자를 확인합니다. SQL 값은 파라미터로 전달합니다.

DB 연결 역할에는 `bookmark` 스키마 USAGE와 네 테이블 CRUD 권한이 필요합니다.
기존 DB에 RLS가 활성화돼 있으면 서버 역할에 허용된 정책 또는 BYPASSRLS 권한이
있어야 합니다. 이 서비스는 `auth.uid()`, JWT 세션, PostgREST, DB RPC에
의존하지 않습니다. 기존 RLS/권한/스키마를 자동으로 바꾸지 않습니다.
`supabase/migrations`는 과거 스키마 변경 기록으로 보존합니다.
운영 테이블은 이미 존재해야 하며 테스트용 schema.sql을 운영에 적용하지 않습니다.

## API

- `GET /`, `GET /health`, `GET /health/live`
- `GET /health/ready`: PostgreSQL `SELECT 1` 확인
- `GET /api/v1/auth/me`
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
uv run ruff format --check app tests
uv run ruff check --no-cache app tests
uv run mypy app
uv run pytest -m "not integration" --cov=app --cov-report=term-missing
uv run pip-audit
```

통합 테스트는 별도의 로컬 PostgreSQL 17 이상 `*_test` DB만 허용합니다.
`tests/integration/schema.sql`로 테이블을 준비하고 테스트 소유자 데이터만 정리합니다.
운영 DB에는 실행하지 않습니다.

```bash
DATABASE_TEST_URL=postgresql://postgres@127.0.0.1:55439/bookmark_test \
uv run pytest -m integration -v
```

자격 증명이 없으면 통합 테스트는 skip됩니다. 실제 PostgreSQL에서 CRUD,
소유자 격리, 폴더 삭제 이동, 부분 실패 rollback을 확인합니다.

## 배포

Vercel project: `idghst/api-bookmark`. Preview/Production 서버 환경에
`DATABASE_URL`, `BOOKMARK_API_KEY`, 필요 시 `BOOKMARK_USER_ID`를 설정합니다.
서버에서 DB에 네트워크 연결할 수 있어야 합니다.

CI 통과 후 Preview에서 `/health/live`, `/health/ready`, 잘못된 키의 401,
실제 키의 CRUD를 확인하고 Production으로 승격합니다.

```bash
vercel build --target=preview
vercel deploy --target=preview
vercel inspect <preview-url>
vercel promote <preview-url>
```

문제는 `X-Request-ID`로 추적하고 DB URI와 키를 로그·커밋에 남기지 않습니다.
