import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

# Ruta por defecto del fichero SQLite. Se puede sobreescribir con la variable
# de entorno DB_PATH (por ejemplo, ':memory:' para los tests).
DEFAULT_DB_PATH = "scimforge.db"


# Patrón para parsear filtros SCIM sencillos: 'attr op "valor"'.
# Soporta eq, co, sw, pr (y también gt/ge/lt/le como passthrough básico).
_FILTER_RE = re.compile(
    r'^\s*([A-Za-z0-9_.]+)\s+(eq|co|sw|pr|gt|ge|lt|le)\s*(?:"([^"]*)")?\s*$',
    re.IGNORECASE,
)


def get_db_path() -> str:
    """Devuelve la ruta de la base de datos desde DB_PATH o la de por defecto."""
    return os.environ.get("DB_PATH", DEFAULT_DB_PATH)


def _now_iso() -> str:
    """Marca temporal UTC en formato ISO 8601 con sufijo Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_attr(resource: dict, path: str) -> Any:
    """Resuelve un atributo SCIM permitiendo rutas con puntos (name.givenName)."""
    current: Any = resource
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def _match_filter(resource: dict, filter_str: Optional[str]) -> bool:
    """Evalúa un filtro SCIM simple sobre un recurso ya deserializado."""
    if not filter_str:
        return True
    match = _FILTER_RE.match(filter_str)
    if not match:
        # Filtro no soportado: no descartamos el recurso para no romper listados.
        return True
    attr, op, value = match.group(1), match.group(2).lower(), match.group(3)
    target = _resolve_attr(resource, attr)
    if op == "pr":
        return target is not None and target != ""
    if target is None:
        return False
    target_str = str(target)
    if op == "eq":
        return target_str == (value or "")
    if op == "co":
        return (value or "") in target_str
    if op == "sw":
        return target_str.startswith(value or "")
    # Comparaciones numéricas/lexicográficas básicas.
    try:
        if op == "gt":
            return target_str > (value or "")
        if op == "ge":
            return target_str >= (value or "")
        if op == "lt":
            return target_str < (value or "")
        if op == "le":
            return target_str <= (value or "")
    except TypeError:
        return False
    return True


async def init_db(db_path: str) -> None:
    """Crea las tablas necesarias si no existen."""
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                external_id TEXT,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY,
                external_id TEXT,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await conn.commit()


class ScimRepository:
    """Repositorio asíncrono para recursos SCIM Users y Groups sobre SQLite."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        return conn

    async def _create(self, table: str, resource: dict) -> dict:
        resource_id = resource.get("id") or str(uuid.uuid4())
        resource["id"] = resource_id
        now = _now_iso()
        resource.setdefault("meta", {})
        resource["meta"].update(
            {
                "resourceType": "User" if table == "users" else "Group",
                "created": resource["meta"].get("created", now),
                "lastModified": now,
                "location": f"/scim/v2/{'Users' if table == 'users' else 'Groups'}/{resource_id}",
            }
        )
        async with await self._connect() as conn:
            await conn.execute(
                f"INSERT INTO {table} (id, external_id, data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    resource_id,
                    resource.get("externalId"),
                    json.dumps(resource),
                    now,
                    now,
                ),
            )
            await conn.commit()
        return resource

    async def _get(self, table: str, resource_id: str) -> Optional[dict]:
        async with await self._connect() as conn:
            async with conn.execute(
                f"SELECT data FROM {table} WHERE id = ?", (resource_id,)
            ) as cursor:
                row = await cursor.fetchone()
        return json.loads(row["data"]) if row else None

    async def _update(self, table: str, resource_id: str, resource: dict) -> Optional[dict]:
        existing = await self._get(table, resource_id)
        if existing is None:
            return None
        resource["id"] = resource_id
        now = _now_iso()
        meta = resource.setdefault("meta", {})
        meta.update(existing.get("meta", {}))
        meta["lastModified"] = now
        async with await self._connect() as conn:
            await conn.execute(
                f"UPDATE {table} SET external_id = ?, data = ?, updated_at = ? WHERE id = ?",
                (resource.get("externalId"), json.dumps(resource), now, resource_id),
            )
            await conn.commit()
        return resource

    async def _delete(self, table: str, resource_id: str) -> bool:
        async with await self._connect() as conn:
            cursor = await conn.execute(f"DELETE FROM {table} WHERE id = ?", (resource_id,))
            await conn.commit()
            return cursor.rowcount > 0

    async def _list(
        self, table: str, filter_str: Optional[str], start_index: int, count: int
    ) -> tuple[list[dict], int]:
        async with await self._connect() as conn:
            async with conn.execute(f"SELECT data FROM {table} ORDER BY created_at") as cursor:
                rows = await cursor.fetchall()
        resources = [json.loads(row["data"]) for row in rows]
        filtered = [r for r in resources if _match_filter(r, filter_str)]
        total = len(filtered)
        start = max(start_index - 1, 0)
        page = filtered[start : start + count] if count > 0 else filtered[start:]
        return page, total

    # Users
    async def create_user(self, user_dict: dict) -> dict:
        return await self._create("users", user_dict)

    async def get_user(self, user_id: str) -> Optional[dict]:
        return await self._get("users", user_id)

    async def update_user(self, user_id: str, user_dict: dict) -> Optional[dict]:
        return await self._update("users", user_id, user_dict)

    async def delete_user(self, user_id: str) -> bool:
        return await self._delete("users", user_id)

    async def list_users(
        self, filter_str: Optional[str], start_index: int, count: int
    ) -> tuple[list[dict], int]:
        return await self._list("users", filter_str, start_index, count)

    # Groups
    async def create_group(self, group_dict: dict) -> dict:
        return await self._create("groups", group_dict)

    async def get_group(self, group_id: str) -> Optional[dict]:
        return await self._get("groups", group_id)

    async def update_group(self, group_id: str, group_dict: dict) -> Optional[dict]:
        return await self._update("groups", group_id, group_dict)

    async def delete_group(self, group_id: str) -> bool:
        return await self._delete("groups", group_id)

    async def list_groups(
        self, filter_str: Optional[str], start_index: int, count: int
    ) -> tuple[list[dict], int]:
        return await self._list("groups", filter_str, start_index, count)
