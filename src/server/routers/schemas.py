from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["Discovery"])

SCHEMA_URN_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCHEMA_URN_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCHEMA_URN_ENTERPRISE_USER = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"


def _attr(name, type_, multi=False, required=False, case_exact=False,
          mutability="readWrite", returned="default", uniqueness="none",
          sub_attributes=None, canonical_values=None):
    """Construye un atributo de esquema SCIM segun RFC 7643 seccion 7."""
    attr = {
        "name": name,
        "type": type_,
        "multiValued": multi,
        "required": required,
        "caseExact": case_exact,
        "mutability": mutability,
        "returned": returned,
        "uniqueness": uniqueness,
    }
    if sub_attributes is not None:
        attr["subAttributes"] = sub_attributes
    if canonical_values is not None:
        attr["canonicalValues"] = canonical_values
    return attr


USER_SCHEMA = {
    "id": SCHEMA_URN_USER,
    "name": "User",
    "description": "User Account",
    "attributes": [
        _attr("userName", "string", required=True, case_exact=True, uniqueness="server"),
        _attr("name", "complex", sub_attributes=[
            _attr("formatted", "string"),
            _attr("familyName", "string", case_exact=True),
            _attr("givenName", "string", case_exact=True),
            _attr("middleName", "string", case_exact=True),
            _attr("honorificPrefix", "string", case_exact=True),
            _attr("honorificSuffix", "string", case_exact=True),
        ]),
        _attr("displayName", "string"),
        _attr("nickName", "string"),
        _attr("profileUrl", "reference"),
        _attr("title", "string"),
        _attr("userType", "string"),
        _attr("preferredLanguage", "string"),
        _attr("locale", "string"),
        _attr("timezone", "string"),
        _attr("active", "boolean"),
        _attr("password", "string", mutability="writeOnly", returned="never"),
        _attr("emails", "complex", multi=True, sub_attributes=[
            _attr("value", "string"),
            _attr("display", "string"),
            _attr("type", "string"),
            _attr("primary", "boolean"),
        ]),
        _attr("phoneNumbers", "complex", multi=True, sub_attributes=[
            _attr("value", "string"),
            _attr("display", "string"),
            _attr("type", "string"),
            _attr("primary", "boolean"),
        ]),
        _attr("ims", "complex", multi=True, sub_attributes=[
            _attr("value", "string"),
            _attr("display", "string"),
            _attr("type", "string"),
            _attr("primary", "boolean"),
        ]),
        _attr("photos", "complex", multi=True, sub_attributes=[
            _attr("value", "reference"),
            _attr("display", "string"),
            _attr("type", "string"),
            _attr("primary", "boolean"),
        ]),
        _attr("addresses", "complex", multi=True, sub_attributes=[
            _attr("formatted", "string"),
            _attr("streetAddress", "string"),
            _attr("locality", "string"),
            _attr("region", "string"),
            _attr("postalCode", "string"),
            _attr("country", "string"),
            _attr("type", "string"),
            _attr("primary", "boolean"),
        ]),
        _attr("groups", "complex", multi=True, mutability="readOnly", sub_attributes=[
            _attr("value", "string"),
            _attr("display", "string"),
            _attr("type", "string"),
        ]),
        _attr("entitlements", "complex", multi=True, sub_attributes=[
            _attr("value", "string"),
            _attr("display", "string"),
            _attr("type", "string"),
            _attr("primary", "boolean"),
        ]),
        _attr("roles", "complex", multi=True, sub_attributes=[
            _attr("value", "string"),
            _attr("display", "string"),
            _attr("type", "string"),
            _attr("primary", "boolean"),
        ]),
        _attr("x509Certificates", "complex", multi=True, sub_attributes=[
            _attr("value", "string"),
            _attr("display", "string"),
            _attr("type", "string"),
            _attr("primary", "boolean"),
        ]),
    ],
    "meta": {
        "resourceType": "Schema",
        "location": "/Schemas/" + SCHEMA_URN_USER,
    },
}

GROUP_SCHEMA = {
    "id": SCHEMA_URN_GROUP,
    "name": "Group",
    "description": "Group",
    "attributes": [
        _attr("displayName", "string", required=True, uniqueness="server"),
        _attr("members", "complex", multi=True, sub_attributes=[
            _attr("value", "string", required=True),
            _attr("display", "string", mutability="readOnly"),
            _attr("type", "string", mutability="readOnly",
                  canonical_values=["User", "Group"]),
            _attr("$ref", "reference", mutability="readOnly"),
        ]),
    ],
    "meta": {
        "resourceType": "Schema",
        "location": "/Schemas/" + SCHEMA_URN_GROUP,
    },
}

ENTERPRISE_USER_SCHEMA = {
    "id": SCHEMA_URN_ENTERPRISE_USER,
    "name": "EnterpriseUser",
    "description": "Enterprise User",
    "attributes": [
        _attr("employeeNumber", "string"),
        _attr("costCenter", "string"),
        _attr("organization", "string"),
        _attr("division", "string"),
        _attr("department", "string"),
        _attr("manager", "complex", sub_attributes=[
            _attr("value", "string"),
            _attr("$ref", "reference"),
            _attr("displayName", "string"),
        ]),
    ],
    "meta": {
        "resourceType": "Schema",
        "location": "/Schemas/" + SCHEMA_URN_ENTERPRISE_USER,
    },
}

ALL_SCHEMAS = [USER_SCHEMA, GROUP_SCHEMA, ENTERPRISE_USER_SCHEMA]


@router.get("/ServiceProviderConfig")
async def get_service_provider_config(request: Request):
    """Devuelve las capacidades soportadas por este proveedor SCIM (RFC 7643 seccion 5)."""
    base_url = str(request.base_url).rstrip("/")
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "https://www.rfc-editor.org/rfc/rfc7644",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [],
        "meta": {
            "resourceType": "ServiceProviderConfig",
            "location": base_url + "/ServiceProviderConfig",
        },
    }


@router.get("/Schemas")
async def list_schemas(request: Request):
    """Lista todos los esquemas disponibles en formato ListResponse (RFC 7644 seccion 3.4.2)."""
    base_url = str(request.base_url).rstrip("/")
    resources = []
    for schema in ALL_SCHEMAS:
        item = dict(schema)
        meta = dict(item.get("meta", {}))
        meta["location"] = base_url + "/Schemas/" + item["id"]
        item["meta"] = meta
        resources.append(item)
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": len(resources),
        "startIndex": 1,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


@router.get("/Schemas/{schema_id}")
async def get_schema(schema_id: str, request: Request):
    """Devuelve un esquema concreto por su URN o por su nombre corto."""
    for schema in ALL_SCHEMAS:
        if schema["id"] == schema_id or schema["name"] == schema_id:
            base_url = str(request.base_url).rstrip("/")
            item = dict(schema)
            meta = dict(item.get("meta", {}))
            meta["location"] = base_url + "/Schemas/" + item["id"]
            item["meta"] = meta
            return item
    raise HTTPException(
        status_code=404,
        detail={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "detail": f"Schema '{schema_id}' not found",
            "status": "404",
        },
    )
