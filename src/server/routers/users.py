from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from src.server.database import ScimRepository, get_repository
from src.server.models import (
    ListResponse,
    ScimError,
    ScimPatchOp,
    ScimUser,
)

router = APIRouter(prefix="/Users", tags=["Users"])

SCIM_CONTENT_TYPE = "application/scim+json"


def _scim_response(payload: Any, status_code: int = 200) -> JSONResponse:
    """Devuelve una respuesta JSON con el Content-Type exigido por RFC 7644 §3.1."""
    return JSONResponse(
        content=payload,
        status_code=status_code,
        media_type=SCIM_CONTENT_TYPE,
    )


def _error(status_code: int, detail: str, scim_type: str | None = None) -> JSONResponse:
    """Construye una respuesta de error conforme a RFC 7644 §3.12."""
    err = ScimError(
        status=str(status_code),
        detail=detail,
        scimType=scim_type,
    )
    return JSONResponse(
        content=err.model_dump(by_alias=True, exclude_none=True),
        status_code=status_code,
        media_type=SCIM_CONTENT_TYPE,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _location(request: Request, user_id: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/Users/{user_id}"


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request,
    payload: ScimUser,
    repo: ScimRepository = Depends(get_repository),
) -> JSONResponse:
    """RFC 7644 §3.3: crear un recurso User. Devuelve 201 Created con meta.location."""
    data = payload.model_dump(by_alias=True, exclude_none=True)
    user_id = data.get("id") or str(uuid.uuid4())
    data["id"] = user_id
    now = _now_iso()
    meta = data.get("meta") or {}
    meta["resourceType"] = "User"
    meta["created"] = meta.get("created") or now
    meta["lastModified"] = now
    meta["location"] = _location(request, user_id)
    meta["version"] = f'W/"{uuid.uuid4().hex}"'
    data["meta"] = meta

    existing = await repo.get_user(user_id)
    if existing is not None:
        return _error(409, f"El usuario {user_id} ya existe", scim_type="uniqueness")

    await repo.create_user(data)
    return _scim_response(data, status_code=status.HTTP_201_CREATED)


@router.get("/{user_id}")
async def get_user(
    user_id: str,
    repo: ScimRepository = Depends(get_repository),
) -> JSONResponse:
    """RFC 7644 §3.4.1: recuperar un User por id. 200 OK o 404 Not Found."""
    user = await repo.get_user(user_id)
    if user is None:
        return _error(404, f"Usuario {user_id} no encontrado")
    return _scim_response(user)


@router.put("/{user_id}")
async def replace_user(
    request: Request,
    user_id: str,
    payload: ScimUser,
    repo: ScimRepository = Depends(get_repository),
) -> JSONResponse:
    """RFC 7644 §3.5.1: reemplazo completo del recurso User."""
    existing = await repo.get_user(user_id)
    if existing is None:
        return _error(404, f"Usuario {user_id} no encontrado")

    data = payload.model_dump(by_alias=True, exclude_none=True)
    data["id"] = user_id
    now = _now_iso()
    meta = data.get("meta") or {}
    meta["resourceType"] = "User"
    meta["created"] = (existing.get("meta") or {}).get("created", now)
    meta["lastModified"] = now
    meta["location"] = _location(request, user_id)
    meta["version"] = f'W/"{uuid.uuid4().hex}"'
    data["meta"] = meta

    await repo.update_user(user_id, data)
    return _scim_response(data)


@router.patch("/{user_id}")
async def patch_user(
    request: Request,
    user_id: str,
    payload: ScimPatchOp,
    repo: ScimRepository = Depends(get_repository),
) -> JSONResponse:
    """RFC 7644 §3.5.2: aplicar operaciones add/replace/remove sobre el User."""
    user = await repo.get_user(user_id)
    if user is None:
        return _error(404, f"Usuario {user_id} no encontrado")

    try:
        updated = _apply_patch(user, payload)
    except ValueError as exc:
        return _error(400, str(exc), scim_type="invalidValue")

    now = _now_iso()
    meta = updated.get("meta") or {}
    meta["resourceType"] = "User"
    meta["lastModified"] = now
    meta["location"] = _location(request, user_id)
    meta["version"] = f'W/"{uuid.uuid4().hex}"'
    updated["meta"] = meta

    await repo.update_user(user_id, updated)
    return _scim_response(updated)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    repo: ScimRepository = Depends(get_repository),
) -> Response:
    """RFC 7644 §3.6: eliminar un User. Devuelve 204 No Content."""
    existing = await repo.get_user(user_id)
    if existing is None:
        return _error(404, f"Usuario {user_id} no encontrado")
    await repo.delete_user(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT, media_type=SCIM_CONTENT_TYPE)


@router.get("")
async def list_users(
    repo: ScimRepository = Depends(get_repository),
    filter: str | None = Query(default=None, description="Filtro SCIM RFC 7644 §3.4.2.2"),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0),
    sortBy: str | None = Query(default=None),
    sortOrder: str | None = Query(default=None),
) -> JSONResponse:
    """RFC 7644 §3.4.2: listar Users con filtro, paginación y ordenación."""
    try:
        total, items = await repo.list_users(
            filter_expr=filter,
            start_index=startIndex,
            count=count,
            sort_by=sortBy,
            sort_order=sortOrder,
        )
    except ValueError as exc:
        return _error(400, f"Filtro SCIM inválido: {exc}", scim_type="invalidFilter")

    list_payload = ListResponse(
        totalResults=total,
        startIndex=startIndex,
        itemsPerPage=len(items),
        Resources=items,
    )
    return _scim_response(list_payload.model_dump(by_alias=True, exclude_none=True))


def _apply_patch(user: dict[str, Any], patch: ScimPatchOp) -> dict[str, Any]:
    """Aplica operaciones PATCH SCIM sobre el dict del usuario (RFC 7644 §3.5.2)."""
    result = dict(user)
    for op in patch.Operations:
        path = op.path
        value = op.value
        if op.op == "add" or op.op == "replace":
            if path is None:
                if not isinstance(value, dict):
                    raise ValueError("La operación sin path requiere un objeto value")
                result.update(value)
            else:
                _set_path(result, path, value)
        elif op.op == "remove":
            if path is None:
                raise ValueError("La operación remove requiere path")
            _remove_path(result, path)
        else:
            raise ValueError(f"Operación PATCH no soportada: {op.op}")
    return result


def _split_path(path: str) -> list[str]:
    return [segment for segment in path.split(".") if segment]


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = _split_path(path)
    if not parts:
        raise ValueError("path vacío")
    cursor: dict[str, Any] = target
    for segment in parts[:-1]:
        nxt = cursor.get(segment)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[segment] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


def _remove_path(target: dict[str, Any], path: str) -> None:
    parts = _split_path(path)
    if not parts:
        raise ValueError("path vacío")
    cursor: dict[str, Any] = target
    for segment in parts[:-1]:
        nxt = cursor.get(segment)
        if not isinstance(nxt, dict):
            return
        cursor = nxt
    cursor.pop(parts[-1], None)
