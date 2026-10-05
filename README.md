# fastapi-bookmark

`supabase.idghst.co.kr`의 `bookmark` 스키마에 있는 `items`, `folders`,
`sections`, `folder_sections`를 Supabase PostgREST로 사용하는 FastAPI 서비스입니다.

## 실행

Python 3.12와 uv가 필요합니다.

```bash
uv sync --locked --dev
# .env.local이 없는 경우에만 .env.example을 복사합니다.
# .env.local에 SUPABASE_URL, SUPABASE_SECRET_KEY, BOOKMARK_API_KEY 설정
uv run python -m uvicorn app.main:app --reload
```

로컬에서는 저장소 루트의 `.env`, `.env.local` 순서로 읽습니다.
실제 환경 변수가 파일보다 우선하므로 운영에서는 같은 이름을 Vercel에 등록합니다.
`SUPABASE_URL=https://supabase.idghst.co.kr`, `SUPABASE_SECRET_KEY`가 필수이며,
리소스 접근에는 웹과 동일한 `BOOKMARK_API_KEY`를 설정합니다.
비밀 키는 API 서버에만 보관합니다. `SUPABASE_TIMEOUT_SECONDS`는 기본 10초입니다.

`BOOKMARK_USER_ID`를 UUID로 지정하면 해당 소유자로 동작합니다.
미설정이면 네 테이블의 `user_id` 최소·최대값을 비교해 유일한 소유자를
선택합니다. 테이블당 최대 두 행만 받으며, 최대 네 테이블을 병렬 조회합니다.
데이터가 없거나 소유자가 복수이거나 NULL이면 503으로 거부합니다.
빈 DB를 시작할 때는 `BOOKMARK_USER_ID`가 필요합니다.

## 인증과 데이터 접근

리소스와 `GET /api/v1/auth/me`는 `X-Bookmark-Key`만 받습니다.
`Authorization: Bearer` JWT 지원은 제거됐습니다.
`auth/me` 응답은 `{ "id": "<소유자 UUID>", "email": null }`입니다.
브라우저에는 키를 전달하지 않고 웹 BFF에서만 보관합니다.

모든 리소스 요청에 `user_id` 조건을 강제하고 부모 폴더·섹션의 소유자를 확인합니다.
목록은 페이지를 끝까지 조회해 서버의 페이지 제한으로 데이터가 잘리지 않게 합니다.
고유 `id`로 조회하는 부모 확인·이동 전 조회는 한 번의 DB 요청으로 끝냅니다.
폴더 삭제와 여러 항목의 정렬은 `delete_folder`, `reorder_resources` RPC에서
각각 한 트랜잭션으로 처리합니다. 중간 실패 시 해당 RPC 전체가 취소됩니다.

API와 readiness 검사는 앱 lifespan 동안 하나의 HTTPX 연결 풀을 공유하고,
앱 종료 시 닫습니다. ASGI lifespan을 끈 호출에서는 요청별 연결을 사용합니다.
소유자와 리소스 응답은 캐시하지 않아 DB 변경을 다음 요청에 반영합니다.

`bookmark` 스키마와 네 테이블이 Supabase PostgREST에 노출되어 있어야 합니다.
`supabase/migrations/20260913090000_atomic_rest_operations.sql`에 RPC 정의가 있습니다.
현재 Supabase에는 이 마이그레이션을 적용했습니다. 다른 인스턴스를 준비할 때는
해당 인스턴스의 마이그레이션 이력을 확인한 뒤 적용합니다.
애플리케이션 시작 시 스키마나 권한을 자동 변경하지 않습니다.

## API

- `GET /`, `GET /health`, `GET /health/live`
- `GET /health/ready`: Supabase의 `bookmark.items` 읽기 연결 확인
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
uv run python -m ruff format --check app tests
uv run python -m ruff check --no-cache app tests
uv run python -m mypy app
uv run python -m pytest --cov=app --cov-report=term-missing
uv run python -m pip_audit
```

자동 테스트는 HTTP 응답을 모의해 CRUD, 소유자 격리, RPC 호출,
페이지 처리와 오류를 검증하며 실제 Supabase 데이터를 변경하지 않습니다.
로컬 실행 후 `/health/ready`와 인증된 리소스 조회로 실제 연결을 확인합니다.

## 배포

Vercel project: `idghst/api-bookmark`. Preview/Production 서버 환경에
`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `BOOKMARK_API_KEY`, 필요 시
`BOOKMARK_USER_ID`를 설정합니다. 서버에서 Supabase HTTPS 주소로 접근할 수 있어야 합니다.

CI 통과 후 Preview에서 `/health/live`, `/health/ready`, 잘못된 키의 401,
실제 키의 CRUD를 확인하고 Production으로 승격합니다.

```bash
vercel build --target=preview
vercel deploy --target=preview
vercel inspect <preview-url>
vercel promote <preview-url>
```

문제는 `X-Request-ID`로 추적하고 비밀 키를 로그·커밋에 남기지 않습니다.
