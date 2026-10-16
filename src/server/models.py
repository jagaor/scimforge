from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ScimBase(BaseModel):
    """Base común: permite alias, ignora campos extra y serializa sin nulos."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


class ScimMeta(ScimBase):
    resourceType: Optional[str] = None
    created: Optional[datetime] = None
    lastModified: Optional[datetime] = None
    location: Optional[str] = None
    version: Optional[str] = None


class ScimName(ScimBase):
    formatted: Optional[str] = None
    familyName: Optional[str] = None
    givenName: Optional[str] = None
    middleName: Optional[str] = None
    honorificPrefix: Optional[str] = None
    honorificSuffix: Optional[str] = None


class ScimEmail(ScimBase):
    value: str
    type: Optional[str] = None
    primary: Optional[bool] = None


class ScimPhoneNumber(ScimBase):
    value: str
    type: Optional[str] = None
    primary: Optional[bool] = None


class ScimAddress(ScimBase):
    streetAddress: Optional[str] = None
    locality: Optional[str] = None
    region: Optional[str] = None
    postalCode: Optional[str] = None
    country: Optional[str] = None
    type: Optional[str] = None
    primary: Optional[bool] = None


class ScimGroupMember(ScimBase):
    value: str
    display: Optional[str] = None
    ref: Optional[str] = Field(default=None, alias="$ref")


class ScimGroupRef(ScimBase):
    """Referencia a grupo embebida en un usuario (atributo 'groups')."""

    value: str
    display: Optional[str] = None
    type: Optional[str] = None
    ref: Optional[str] = Field(default=None, alias="$ref")


class ScimManager(ScimBase):
    value: Optional[str] = None
    displayName: Optional[str] = None
    ref: Optional[str] = Field(default=None, alias="$ref")


class ScimEnterpriseUser(ScimBase):
    """Extensión enterprise de RFC 7643 §4.3."""

    employeeNumber: Optional[str] = None
    organization: Optional[str] = None
    division: Optional[str] = None
    department: Optional[str] = None
    manager: Optional[ScimManager] = None


class ScimUser(ScimBase):
    schemas: list[str] = Field(default_factory=lambda: ["urn:ietf:params:scim:schemas:core:2.0:User"])
    id: Optional[str] = None
    externalId: Optional[str] = None
    userName: str
    name: Optional[ScimName] = None
    displayName: Optional[str] = None
    nickName: Optional[str] = None
    profileUrl: Optional[str] = None
    title: Optional[str] = None
    userType: Optional[str] = None
    preferredLanguage: Optional[str] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    active: Optional[bool] = True
    password: Optional[str] = None
    emails: Optional[list[ScimEmail]] = None
    phoneNumbers: Optional[list[ScimPhoneNumber]] = None
    addresses: Optional[list[ScimAddress]] = None
    groups: Optional[list[ScimGroupRef]] = None
    meta: Optional[ScimMeta] = None

    # Extensión enterprise aplanada en el modelo pero serializada con su URN.
    enterprise: Optional[ScimEnterpriseUser] = Field(
        default=None,
        alias="urn:ietf:params:scim:schemas:extension:enterprise:2.0:User",
    )


class ScimGroup(ScimBase):
    schemas: list[str] = Field(default_factory=lambda: ["urn:ietf:params:scim:schemas:core:2.0:Group"])
    id: Optional[str] = None
    externalId: Optional[str] = None
    displayName: str
    members: Optional[list[ScimGroupMember]] = None
    meta: Optional[ScimMeta] = None


class ListResponse(ScimBase, Generic[T]):
    schemas: list[str] = Field(default_factory=lambda: ["urn:ietf:params:scim:api:messages:2.0:ListResponse"])
    totalResults: int = 0
    startIndex: int = 1
    itemsPerPage: int = 0
    Resources: list[T] = Field(default_factory=list)


class ScimPatchOperation(ScimBase):
    op: Literal["add", "replace", "remove"]
    path: Optional[str] = None
    value: Optional[Any] = None


class ScimPatchOp(ScimBase):
    schemas: list[str] = Field(default_factory=lambda: ["urn:ietf:params:scim:api:messages:2.0:PatchOp"])
    Operations: list[ScimPatchOperation]


class ScimError(ScimBase):
    schemas: list[str] = Field(default_factory=lambda: ["urn:ietf:params:scim:api:messages:2.0:Error"])
    detail: Optional[str] = None
    status: str
    scimType: Optional[str] = None
