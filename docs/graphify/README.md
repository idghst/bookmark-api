# Graphify 지식 그래프

이 저장소는 [Graphify](https://github.com/Graphify-Labs/graphify)로 코드 구조 그래프를 유지한다.
질의 가능한 산출물은 `graphify-out/`에 있다. AST 캐시(`graphify-out/cache/`)는 커밋하지 않는다.
공개 API는 REST만 있다. GraphQL(`/graphql`, strawberry)은 제거됐다.

추출 기준 커밋은 `graphify-out/GRAPH_REPORT.md`의 Graph Freshness를 본다.
코드 전용 추출(`--code-only`)이라 커뮤니티 이름은 `Community N`이다. 아래 표가 실제 모듈 매핑이다.

## 산출물

| 파일 | 용도 |
| --- | --- |
| `graphify-out/GRAPH_REPORT.md` | 커뮤니티·허브·고드 노드 요약 |
| `graphify-out/graph.json` | `query` / `path` / `explain` 원본 |
| `graphify-out/graph.html` | 인터랙티브 그래프 |
| `graphify-out/GRAPH_TREE.html` | 파일 트리 뷰 |
| `graphify-out/api-bookmark-callflow.html` | 호출 흐름 |

기존 스냅샷: **396 nodes · 1129 edges · 20 communities**. PostgreSQL 전환 이전 산출물입니다.
2026-09-07 `graphify query/path/explain/update`를 시도했으나 CLI가 없어 AST 갱신은 미완료입니다.
현재 런타임 경로는 아래 레이어 설명을 따릅니다.

## 워크스페이스

형제 저장소 `bookmark`와 런타임으로만 연결된다. 그래프를 합치려면:

```bash
graphify merge-graphs \
  graphify-out/graph.json \
  ../bookmark/graphify-out/graph.json \
  --out /tmp/workspace-merged-graph.json
```

```mermaid
flowchart LR
  WebUI["bookmark BookmarksPage"] --> BFF["bookmark /api BFF"]
  BFF -->|"REST + X-Bookmark-Key"| REST["api-bookmark /api"]
  Mobile["bookmark mobile Expo"] -->|"REST + X-Bookmark-Key"| REST
  REST --> Domain["services bookmarks/folders/sections"]
  Domain --> DB["services/_db.py execute"]
  DB --> PG[PostgreSQL psycopg 3]
```

웹 브라우저는 API 비밀을 보지 않는다. 모바일은 사용자가 입력한 키로 REST를 직접 호출한다.

## 레이어

```mermaid
flowchart TB
  subgraph entry [진입]
    Factory["create_app() / app/main.py"]
    Health["app/api/routes/health.py"]
    AuthAPI["/api/v1 auth"]
  end
  subgraph http [HTTP]
    REST["/api bookmarks folders sections"]
  end
  subgraph auth [인증]
    Ctx["get_resource_auth_context"]
    Key["X-Bookmark-Key"]
  end
  subgraph domain [도메인]
    BM[services/bookmarks.py]
    FD[services/folders.py]
    SC[services/sections.py]
    DB["services/_db.py"]
  end
  subgraph data [데이터]
    PG[PostgreSQL psycopg 3]
    TX["요청별 트랜잭션 / rollback"]
  end
  Factory --> REST
  Factory --> Health
  Factory --> AuthAPI
  REST --> Ctx
  AuthAPI --> Ctx
  Ctx --> Key
  REST --> BM
  REST --> FD
  REST --> SC
  BM --> DB
  FD --> DB
  SC --> DB
  DB --> PG
  FD --> TX
  SC --> TX
```

## 커뮤니티 해석

| ID | 실제 의미 | 대표 심볼·파일 |
| --- | --- | --- |
| C2 | 도메인 서비스 + REST + 스키마 | `app/services/*`, `app/api/routes/{bookmarks,folders,sections,resources}.py`, `app/schemas.py` |
| C3 | (제거됨) 옛 GraphQL 스냅샷 | 현재 코드에 `app/graphql/` 없음 |
| C5 | 인증·설정 접근 | `get_resource_auth_context()`, `connect()`, `_get_service_user()` in `app/integrations/postgres.py` |
| C1 | 설정·헬스 | `Settings` / `app/core/config.py`, `app/api/routes/health.py` |
| C6 | 앱 조립·로깅·오류 봉투 | `app/main.py`, `app/core/logging.py`, `register_exception_handlers()`, `RequestContextMiddleware` |
| C0 | 리소스 테스트 더블 + `create_app` 일부 | `Connection`, `request()` in `tests/test_resources.py` |
| C4 | HTTP 오류 응답 | `_error_response()`, `JSONResponse` |
| C7 | 통합 테스트 | `tests/integration/test_postgres.py` |
| C9 | 배포 메타 | `vercel.json` (`maxDuration`, `fluid`) |

고드 노드: `Settings`(56), `AuthContext`(40), `Connection`(35), `_client()`(33), `ApiError`(29), `create_app()`, `execute()`.

설정·인증·테스트 더블이 허브인 것은 정상이다. 도메인 CRUD를 그 파일들에 더 넣지 않는다. 다음 병목은 `execute()` — 북마크/폴더/섹션 REST 서비스가 여기를 경유한다.

## 그래프가 놓치는 런타임 엣지

FastAPI `Depends`는 파이썬 함수 호출이 아니라서 directed path가 비어 있을 수 있다.

| 질의 | 결과 | 해석 |
| --- | --- | --- |
| `path create_app list_bookmarks` | directed 없음 | import 조립이다. `--undirected`면 `create_app ← main → resources → bookmarks → list_bookmarks` (4 hops) |
| `path get_resource_auth_context execute` | directed 없음 | 라우트가 Depends로 인증하고 서비스가 `execute()`를 호출한다. 직접 호출 아님 |
| `path AuthContext execute --undirected` | 2 hops | `AuthContext ← services/bookmarks.py → execute()` |
| `affected execute` | 서비스 CRUD + REST 라우트 | DB 실행이 도메인 허브 |

## 자주 쓰는 질의

```bash
graphify query "how do REST bookmark routes reach PostgreSQL"
graphify explain "app_services_db_execute"
graphify god-nodes
graphify path "create_app" "list_bookmarks" --undirected
graphify affected "app_services_db_execute"
```

## 갱신

```bash
# AST만, API 키 불필요
graphify update .

# 리팩터로 노드가 줄면
graphify update . --force
```

시맨틱 커뮤니티 이름이 필요하면 API 키를 넣고 `graphify extract .` 또는 `graphify label .`를 실행한다.
SQL 마이그레이션을 그래프에 넣으려면 `uv tool install 'graphifyy[sql]'` 후 재추출한다.
