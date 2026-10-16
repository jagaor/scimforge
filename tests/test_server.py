import os

# Forzar base de datos en memoria antes de importar la app
os.environ["DB_PATH"] = ":memory:"

import pytest
from httpx import AsyncClient, ASGITransport

from src.server.app import create_app


@pytest.fixture
async def scim_client():
    """Cliente httpx asíncrono contra la app ASGI en memoria."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://scimforge.test") as client:
        yield client


@pytest.fixture
async def created_user_id(scim_client: AsyncClient) -> str:
    """Crea un usuario de prueba y devuelve su id SCIM."""
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": "fixture.user@example.com",
        "name": {"givenName": "Fixture", "familyName": "User"},
        "emails": [{"value": "fixture.user@example.com", "primary": True}],
        "active": True,
    }
    resp = await scim_client.post("/scim/v2/Users", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
async def created_group_id(scim_client: AsyncClient) -> str:
    """Crea un grupo de prueba y devuelve su id SCIM."""
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "displayName": "Fixture Group",
    }
    resp = await scim_client.post("/scim/v2/Groups", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_service_provider_config_returns_200(scim_client: AsyncClient):
    resp = await scim_client.get("/scim/v2/ServiceProviderConfig")
    assert resp.status_code == 200
    body = resp.json()
    assert "patch" in body
    assert body["patch"]["supported"] is True


async def test_schemas_endpoint_returns_list(scim_client: AsyncClient):
    resp = await scim_client.get("/scim/v2/Schemas")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalResults"] >= 2
    ids = [s["id"] for s in body["Resources"]]
    assert "urn:ietf:params:scim:schemas:core:2.0:User" in ids


async def test_create_user_returns_201_with_location_header(scim_client: AsyncClient):
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": "alice@example.com",
        "name": {"givenName": "Alice", "familyName": "Doe"},
        "active": True,
    }
    resp = await scim_client.post("/scim/v2/Users", json=payload)
    assert resp.status_code == 201
    assert "Location" in resp.headers
    body = resp.json()
    assert body["userName"] == "alice@example.com"
    assert body["id"]


async def test_get_user_returns_correct_data(scim_client: AsyncClient, created_user_id: str):
    resp = await scim_client.get(f"/scim/v2/Users/{created_user_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == created_user_id
    assert body["userName"] == "fixture.user@example.com"


async def test_put_user_replaces_resource(scim_client: AsyncClient, created_user_id: str):
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": "replaced@example.com",
        "active": False,
    }
    resp = await scim_client.put(f"/scim/v2/Users/{created_user_id}", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["userName"] == "replaced@example.com"
    assert body["active"] is False


async def test_patch_user_replace_op(scim_client: AsyncClient, created_user_id: str):
    patch = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [
            {"op": "replace", "path": "userName", "value": "patched@example.com"}
        ],
    }
    resp = await scim_client.patch(f"/scim/v2/Users/{created_user_id}", json=patch)
    assert resp.status_code == 200
    assert resp.json()["userName"] == "patched@example.com"


async def test_patch_user_add_op(scim_client: AsyncClient, created_user_id: str):
    patch = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [
            {
                "op": "add",
                "path": "emails",
                "value": [{"value": "extra@example.com", "type": "work"}],
            }
        ],
    }
    resp = await scim_client.patch(f"/scim/v2/Users/{created_user_id}", json=patch)
    assert resp.status_code == 200
    emails = resp.json().get("emails", [])
    assert any(e["value"] == "extra@example.com" for e in emails)


async def test_patch_user_remove_op(scim_client: AsyncClient, created_user_id: str):
    patch = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "remove", "path": "name.givenName"}],
    }
    resp = await scim_client.patch(f"/scim/v2/Users/{created_user_id}", json=patch)
    assert resp.status_code == 200
    name = resp.json().get("name") or {}
    assert "givenName" not in name


async def test_delete_user_returns_204(scim_client: AsyncClient, created_user_id: str):
    resp = await scim_client.delete(f"/scim/v2/Users/{created_user_id}")
    assert resp.status_code == 204


async def test_get_deleted_user_returns_404(scim_client: AsyncClient, created_user_id: str):
    await scim_client.delete(f"/scim/v2/Users/{created_user_id}")
    resp = await scim_client.get(f"/scim/v2/Users/{created_user_id}")
    assert resp.status_code == 404


async def test_list_users_filter_by_username(scim_client: AsyncClient):
    for name in ("filter.one@example.com", "filter.two@example.com"):
        await scim_client.post(
            "/scim/v2/Users",
            json={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "userName": name,
            },
        )
    resp = await scim_client.get(
        "/scim/v2/Users", params={"filter": 'userName eq "filter.one@example.com"'}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["totalResults"] == 1
    assert body["Resources"][0]["userName"] == "filter.one@example.com"


async def test_list_users_pagination(scim_client: AsyncClient):
    for i in range(5):
        await scim_client.post(
            "/scim/v2/Users",
            json={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "userName": f"page.{i}@example.com",
            },
        )
    resp = await scim_client.get("/scim/v2/Users", params={"startIndex": 2, "count": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["startIndex"] == 2
    assert body["itemsPerPage"] == 2
    assert len(body["Resources"]) == 2


async def test_create_group_returns_201(scim_client: AsyncClient):
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "displayName": "Engineers",
    }
    resp = await scim_client.post("/scim/v2/Groups", json=payload)
    assert resp.status_code == 201
    assert resp.json()["displayName"] == "Engineers"


async def test_patch_group_add_member(
    scim_client: AsyncClient, created_group_id: str, created_user_id: str
):
    patch = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [
            {
                "op": "add",
                "path": "members",
                "value": [{"value": created_user_id, "type": "User"}],
            }
        ],
    }
    resp = await scim_client.patch(f"/scim/v2/Groups/{created_group_id}", json=patch)
    assert resp.status_code == 200
    members = resp.json().get("members", [])
    assert any(m["value"] == created_user_id for m in members)


async def test_delete_group_returns_204(scim_client: AsyncClient, created_group_id: str):
    resp = await scim_client.delete(f"/scim/v2/Groups/{created_group_id}")
    assert resp.status_code == 204
