from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from src.server.database import ScimRepository, get_repository
from src.server.models import (
    Group,
    GroupResource,
    ListResponse,
    PatchOp,
    ScimError,
)

router = APIRouter(prefix="/Groups", tags=["Groups"])


def _error(status_code: int, detail: str, scim_type: str | None = None) -> JSONResponse:
    """Construye una respuesta de error conforme a RFC 7644 sección 3.12."""
    err = ScimError(status=str(status_code), detail=detail, scimType=scim_type)
    return JSONResponse(status_code=status_code, content=err.model_dump(exclude_none=True))


async def _validate_members(repo: ScimRepository, members: list[dict[str, Any]] | None) -> None:
    """Verifica que cada miembro referenciado exista como User en el repositorio."""
    if not members:
        return
    for member in members:
        user_id = member.get("value")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cada miembro debe incluir el atributo 'value' con el id del User",
            )
        existing = await repo.get_user(user_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El User '{user_id}' referenciado en members no existe",
            )


@router.post("", response_model=GroupResource, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: Group,
    repo: ScimRepository = Depends(get_repository),
) -> GroupResource:
    await _validate_members(repo, [m.model_dump(exclude_none=True) for m in (payload.members or [])])
    created = await repo.create_group(payload)
    return created


@router.get("/{group_id}", response_model=GroupResource)
async def get_group(
    group_id: str,
    repo: ScimRepository = Depends(get_repository),
) -> GroupResource:
    group = await repo.get_group(group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group no encontrado")
    return group


@router.get("", response_model=ListResponse)
async def list_groups(
    request: Request,
    filter: str | None = Query(default=None),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0),
    repo: ScimRepository = Depends(get_repository),
) -> ListResponse:
    resources, total = await repo.list_groups(filter_expr=filter, start_index=startIndex, count=count)
    base = str(request.base_url).rstrip("/")
    return ListResponse(
        totalResults=total,
        startIndex=startIndex,
        itemsPerPage=len(resources),
        Resources=[r.model_dump(exclude_none=True) for r in resources],
    )


@router.put("/{group_id}", response_model=GroupResource)
async def replace_group(
    group_id: str,
    payload: Group,
    repo: ScimRepository = Depends(get_repository),
) -> GroupResource:
    existing = await repo.get_group(group_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group no encontrado")
    await _validate_members(repo, [m.model_dump(exclude_none=True) for m in (payload.members or [])])
    updated = await repo.replace_group(group_id, payload)
    return updated


@router.patch("/{group_id}", response_model=GroupResource)
async def patch_group(
    group_id: str,
    payload: PatchOp,
    repo: ScimRepository = Depends(get_repository),
) -> GroupResource:
    existing = await repo.get_group(group_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group no encontrado")

    for op in payload.Operations:
        path = (op.path or "").lower()
        if path == "members" and op.op.lower() == "add":
            new_members = op.value if isinstance(op.value, list) else [op.value]
            await _validate_members(repo, new_members)
        elif path == "members" and op.op.lower() == "remove":
            pass

    updated = await repo.apply_patch_group(group_id, payload)
    return updated


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: str,
    repo: ScimRepository = Depends(get_repository),
) -> Response:
    existing = await repo.get_group(group_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group no encontrado")
    await repo.delete_group(group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
