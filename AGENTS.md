# Project Agent Instructions

[work]
- 사용자 요청 범위의 수정과 검증이 끝나면, 금지 지시가 없는 한 즉시 `git-commit-push-korean` skill을 적용해 이 세션이 수정한 파일만 한글 커밋·안전 푸시한다. 대상이 혼재했거나 push 복구가 필요하면 사용자에게 보고한다.

[workspace]
- 이 저장소는 FastAPI REST + Postgres(psycopg 직접 연결) 백엔드다. GraphQL은 없다. 형제 저장소는 `bookmark`(Next.js 웹 + Expo 모바일)다.
- 멀티 에이전트는 저장소와 레인을 나눠 동시에 일한다. 맡은 저장소·레인 밖은 읽기만 하고 수정하지 않는다.
- 형제 저장소 `bookmark`의 웹 BFF(`app/lib/bookmarks/store.ts`)와 모바일 REST 클라이언트(`mobile/src/lib/api.ts`)가 이 API를 소비한다. 계약이 바뀌면 소비자 작업을 같은 턴에 몰래 넣지 말고, 계약 완료 후 별도 에이전트에 넘긴다.

[graphify]
- 코드 탐색 전에 `graphify query "<질문>"`, `graphify path "<A>" "<B>"`, `graphify explain "<심볼>"`을 먼저 실행한다. 서브에이전트 프롬프트에도 이 규칙을 넣는다.
- 커뮤니티 의미와 런타임 경로는 `docs/graphify/README.md`를 본다. `GRAPH_REPORT.md`의 Community N 라벨은 코드 전용 추출이라 이름이 없다.
- FastAPI `Depends`는 호출 엣지가 아닐 수 있다. directed path가 없으면 `--undirected`를 치고, 그래도 비면 문서를 따른다.
- 코드 구조가 바뀌면 `graphify update .`로 AST 그래프를 갱신한다. `graphify-out/cache/`는 커밋하지 않는다.

[lanes]
한 레인에는 구현 에이전트를 하나만 둔다. 코디네이터는 디스패치 전에 허용 경로를 배타적으로 할당한다.

| 레인 | 허용 경로 | 같이 돌리면 안 되는 레인 |
| --- | --- | --- |
| `platform` | `app/core/`, `app/middleware/`, `app/main.py`, `app/api/router.py`, `app/api/routes/health.py`, `tests/test_config.py`, `tests/test_errors.py`, `tests/test_middleware.py`, `tests/test_health.py`, `vercel.json`, `tests/test_vercel_config.py` | 없음. GraphQL 라우트·의존성을 다시 넣지 않는다. |
| `auth` | `app/integrations/`, `app/api/routes/auth.py`, `tests/test_auth.py` | `domain`과 동시에 `app/integrations/database.py`를 수정하지 않는다. |
| `domain` | `app/schemas.py`, `app/services/`, `app/api/routes/resources.py`, `app/api/routes/bookmarks.py`, `app/api/routes/folders.py`, `app/api/routes/sections.py`, `tests/test_resources.py` | `db` |
| `db` | `db/`, `supabase/`, `tests/schema.sql`, `tests/test_database_migration.py`, `tests/integration/` | `domain` |
| `tooling` | `.github/`, `pyproject.toml`, `uv.lock`, `.python-version`, `README.md` | lockfile을 바꾸는 작업은 단독으로 한다. |

- 이 파일(`AGENTS.md`)은 지침 변경 요청이 있을 때만 수정한다.
- 마이그레이션 파일은 절대 고치지 말고 새 파일을 추가한다.

[contract]
아래는 한 번에 한 에이전트만 변경한다. 변경 후에는 소비자 레인(`bookmark` 웹·모바일)을 순차로 맞춘다.

- REST: `/api/bookmarks`, `/api/folders`, `/api/folders/tree`, `/api/sections`와 각 `reorder`·`PATCH`·`DELETE`
- 인증: `X-Bookmark-Key` (`BOOKMARK_API_KEY`)
- 오류 봉투: `{ "code", "message", "request_id" }`와 HTTP 상태. 코드 문자열을 바꾸지 않는다.
- 직렬화 별칭: `isFavorite`, `folderId`, `sectionId`, `parentId`, `createdAt`, `updatedAt`, `userId`
- 스키마: Postgres `bookmark` (`items`, `folders`, `sections`)와 RLS·RPC (`delete_folder`, `move_section`)
- 환경 변수: `.env.example`에 있는 이름만 사용한다. 새 변수는 계약 작업으로 명시한다.

[parallel]
- 서로 다른 레인의 독립 작업만 동시에 실행한다. 같은 파일을 두 에이전트가 열지 않는다.
- 계약·스키마·REST 경로 변경은 병렬 금지. `domain` 또는 `db`가 끝난 뒤에 소비자를 돌린다.
- 핫스팟(항상 단독): `app/services/bookmarks.py`, `app/schemas.py`, `app/api/routes/resources.py`, `app/integrations/database.py`
- 포맷/임포트 정리, lockfile 갱신, 전역 리네임은 병렬 세션에서 하지 않는다.
- 다른 에이전트 파일을 재포맷하거나 요청 밖 리팩터를 하지 않는다.

[dispatch]
코디네이터(부모 에이전트)는 서브에이전트에 세션 히스토리를 넘기지 않는다. 프롬프트에 다음을 모두 적는다.

1. 목표와 완료 조건
2. 레인 이름, 허용 경로, 금지 경로
3. 건드리면 안 되는 계약 항목
4. 검증 명령
5. 커밋 대상 파일 범위(이 저장소, 허용 경로만)
6. 보고 형식: 변경 파일, 검증 결과, 계약 영향 여부(`none` / 항목 나열)

서브에이전트는 허용 경로 밖을 수정해야 하면 중단하고 코디네이터에 막힌 경로를 보고한다. 추측으로 레인을 넓히지 않는다.

병렬 예시: `platform` 헬스 테스트 보강 + `tooling` CI 문서 수정.
순차 예시: 섹션 필드 추가 → `db` 마이그레이션 → `domain` 스키마/서비스 → `bookmark` 웹 store → 모바일 타입.

[verify]
맡은 레인 검증을 통과시키기 전에 완료로 보고하지 않는다. 이 저장소 기본 검증:

```bash
uv lock --check
uv run ruff format --check app tests
uv run ruff check --no-cache app tests
uv run mypy app
uv run pytest -m "not integration" --cov=app --cov-report=term-missing
```

- 커버리지 하한은 90%다. 통합 테스트는 자격 증명이 있을 때만 `pytest -m integration`을 실행한다.
- 병렬 작업이 모두 돌아온 뒤 코디네이터가 위 명령을 한 번 더 실행한다.

[git]
- 커밋·푸시는 이 저장소에서, 이 세션이 수정한 파일만 한다. `bookmark` 변경을 여기 커밋에 섞지 않는다.
- 시크릿, `.env.local`, 토큰, JWT 원문을 커밋하거나 로그에 남기지 않는다.
