"""Small PostgREST transport; service methods always supply the resolved owner."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated, Any

import httpx
from fastapi import Depends, Header, Request

from app.core.config import Settings, get_settings
from app.core.errors import ApiError


@dataclass(frozen=True)
class ServiceUser:
    id: str
    email: None = None


@dataclass(frozen=True)
class AuthContext:
    user: ServiceUser
    client: httpx.AsyncClient


async def get_database_client(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[httpx.AsyncClient]:
    client = getattr(request.app.state, "database_client", None)
    if client is not None:
        yield client
    else:
        # ASGI callers that disable lifespan still get a correctly closed client.
        async with create_client(settings) as client:
            yield client


async def get_resource_auth_context(
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[httpx.AsyncClient, Depends(get_database_client)],
    service_key: Annotated[str | None, Header(alias="X-Bookmark-Key")] = None,
) -> AsyncIterator[AuthContext]:
    if service_key is None:
        raise ApiError(401, "authentication_required", "API key is required")
    configured_key = settings.BOOKMARK_API_KEY
    if configured_key is None or not compare_digest(
        service_key.encode(), configured_key.get_secret_value().encode()
    ):
        raise ApiError(401, "invalid_api_key", "Invalid API key")
    yield AuthContext(ServiceUser(await service_user_id(client, settings)), client)


def create_client(settings: Settings) -> httpx.AsyncClient:
    assert settings.SUPABASE_URL and settings.SUPABASE_SECRET_KEY
    key = settings.SUPABASE_SECRET_KEY.get_secret_value()
    return httpx.AsyncClient(
        base_url=f"{settings.SUPABASE_URL}/rest/v1/",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept-Profile": "bookmark",
            "Content-Profile": "bookmark",
            "Prefer": "return=representation",
        },
        timeout=settings.SUPABASE_TIMEOUT_SECONDS,
    )


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    body: object = None,
) -> list[dict[str, Any]]:
    try:
        response = await client.request(method, path, params=params, json=body)
    except httpx.RequestError as error:
        raise ApiError(
            503, "database_unavailable", "Database is unavailable"
        ) from error
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.is_error:
        code = data.get("code") if isinstance(data, dict) else None
        if code == "42501" or response.status_code in {401, 403}:
            raise ApiError(403, "database_access_denied", "Database access was denied")
        if code == "P0002":
            raise ApiError(404, "resource_not_found", "Resource not found")
        if code in {"23503", "23514", "23505", "23502"}:
            raise ApiError(
                409,
                "resource_conflict",
                "Resource conflicts with the current folder structure",
            )
        if code in {"22P02", "22004"}:
            raise ApiError(422, "validation_error", "Request validation failed")
        raise ApiError(502, "database_request_failed", "Database request failed")
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise ApiError(
            502, "database_response_invalid", "Database returned an invalid response"
        )
    return data


async def select(
    client: httpx.AsyncClient,
    table: str,
    params: dict[str, str],
) -> list[dict[str, Any]]:
    # Continue after every nonempty page, even if the server's row cap is smaller
    # than requested. Ordering must be stable (unique id as the last tie breaker).
    rows: list[dict[str, Any]] = []
    while True:
        page = await request(
            client,
            "GET",
            table,
            params={**params, "limit": "1000", "offset": str(len(rows))},
        )
        if not page:
            return rows
        rows.extend(page)


async def service_user_id(client: httpx.AsyncClient, settings: Settings) -> str:
    if settings.BOOKMARK_USER_ID is not None:
        return str(settings.BOOKMARK_USER_ID)

    async def owner_bounds(table: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        # Min/max detect every distinct owner without downloading every row.
        # Descending puts NULL first so invalid ownership also fails closed.
        for direction in ("asc", "desc"):
            page = await request(
                client,
                "GET",
                table,
                params={
                    "select": "user_id",
                    "order": f"user_id.{direction}",
                    "limit": "1",
                },
            )
            if not page:
                break
            rows.extend(page)
        return rows

    # At most four simultaneous reads. Await all tasks before propagating an
    # error so no reads outlive the request or its fallback transport.
    results = await asyncio.gather(
        *(
            owner_bounds(table)
            for table in ("items", "folders", "sections", "folder_sections")
        ),
        return_exceptions=True,
    )
    owners: set[str] = set()
    for result in results:
        if isinstance(result, BaseException):
            raise result
        for row in result:
            owner = row.get("user_id")
            if not isinstance(owner, str) or not owner:
                raise ApiError(
                    503,
                    "service_identity_unavailable",
                    "Service identity is unavailable",
                )
            owners.add(owner)
            if len(owners) > 1:
                raise ApiError(
                    503,
                    "service_identity_unavailable",
                    "Service identity is unavailable",
                )
    if len(owners) != 1:
        raise ApiError(
            503, "service_identity_unavailable", "Service identity is unavailable"
        )
    return owners.pop()
