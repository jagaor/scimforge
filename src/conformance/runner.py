import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

import httpx


USER_SCHEMA_URN = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA_URN = "urn:ietf:params:scim:schemas:core:2.0:Group"
PATCH_OP = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


@dataclass
class TestResult:
    group: str
    name: str
    method: str
    path: str
    expected_status: int
    actual_status: Optional[int]
    passed: bool
    duration_ms: float
    failure_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConformanceReport:
    target_url: str
    started_at: str
    finished_at: str = ""
    results: list[TestResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def score(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.passed / self.total * 100.0, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_url": self.target_url,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "score": self.score,
            "results": [r.to_dict() for r in self.results],
        }


class _Suite:
    """Acumula resultados y ejecuta peticiones contra la URL base."""

    def __init__(self, client: httpx.AsyncClient, report: ConformanceReport) -> None:
        self.client = client
        self.report = report

    async def call(
        self,
        group: str,
        name: str,
        method: str,
        path: str,
        expected_status: int,
        json_body: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        validate: Optional[Any] = None,
    ) -> httpx.Response:
        started = time.perf_counter()
        actual_status: Optional[int] = None
        failure_reason: Optional[str] = None
        response: Optional[httpx.Response] = None
        try:
            response = await self.client.request(
                method, path, json=json_body, headers=headers
            )
            actual_status = response.status_code
            if actual_status != expected_status:
                failure_reason = (
                    f"Se esperaba HTTP {expected_status} y se obtuvo {actual_status}"
                )
            elif validate is not None:
                try:
                    ok = validate(response)
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    failure_reason = f"Error evaluando validación: {exc}"
                if not ok and failure_reason is None:
                    failure_reason = "La validación semántica del cuerpo falló"
        except httpx.HTTPError as exc:
            failure_reason = f"Error de transporte: {exc}"
        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        passed = failure_reason is None
        self.report.results.append(
            TestResult(
                group=group,
                name=name,
                method=method,
                path=path,
                expected_status=expected_status,
                actual_status=actual_status,
                passed=passed,
                duration_ms=duration_ms,
                failure_reason=failure_reason,
            )
        )
        return response  # type: ignore[return-value]


async def run_conformance_suite(
    base_url: str, verbose: bool = False
) -> ConformanceReport:
    """Ejecuta la suite de conformidad SCIM 2.0 contra la URL indicada."""
    base = base_url.rstrip("/")
    report = ConformanceReport(
        target_url=base,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(base_url=base, timeout=timeout) as client:
        suite = _Suite(client, report)
        await _run_schema_discovery(suite)
        created_user_id, created_user_name = await _run_user_crud(suite)
        await _run_user_filtering(suite, created_user_name)
        await _run_pagination(suite)
        await _run_group_crud(suite, created_user_id)
    report.finished_at = datetime.now(timezone.utc).isoformat()
    if verbose:
        for r in report.results:
            estado = "PASS" if r.passed else "FAIL"
            print(f"[{estado}] {r.group} :: {r.name} ({r.actual_status})")
    return report


async def _run_schema_discovery(suite: _Suite) -> None:
    group = "Schema Discovery"
    await suite.call(group, "ServiceProviderConfig", "GET", "/ServiceProviderConfig", 200)

    def _schemas_ok(resp: httpx.Response) -> bool:
        body = resp.json()
        return isinstance(body.get("Resources"), list) and body.get("totalResults", 0) >= 2

    await suite.call(
        group, "Schemas listado", "GET", "/Schemas", 200, validate=_schemas_ok
    )
    await suite.call(
        group,
        "Schema User por URN",
        "GET",
        f"/Schemas/{USER_SCHEMA_URN}",
        200,
    )


async def _run_user_crud(suite: _Suite) -> tuple[str, str]:
    group = "User CRUD"
    user_name = "conformance.user@example.com"
    minimal = {
        "schemas": [USER_SCHEMA_URN],
        "userName": user_name,
        "name": {"givenName": "Conformance", "familyName": "User"},
        "emails": [{"value": user_name, "primary": True}],
        "active": True,
    }

    def _has_location(resp: httpx.Response) -> bool:
        return bool(resp.headers.get("Location"))

    post = await suite.call(
        group, "POST /Users", "POST", "/Users", 201, json_body=minimal, validate=_has_location
    )
    user_id = ""
    if post is not None and post.status_code == 201:
        try:
            user_id = post.json().get("id", "")
        except Exception:  # noqa: BLE001
            user_id = ""

    if user_id:
        await suite.call(group, "GET /Users/{id}", "GET", f"/Users/{user_id}", 200)
        full = dict(minimal)
        full["displayName"] = "Conformance User"
        full["phoneNumbers"] = [{"value": "+34600000000", "type": "work"}]
        await suite.call(
            group, "PUT /Users/{id}", "PUT", f"/Users/{user_id}", 200, json_body=full
        )
        await _patch(suite, group, user_id, [{"op": "replace", "path": "active", "value": False}], "PATCH replace active")
        await _patch(
            suite,
            group,
            user_id,
            [{"op": "add", "path": "emails", "value": [{"value": "extra@example.com"}]}],
            "PATCH add email",
        )
        await _patch(
            suite,
            group,
            user_id,
            [{"op": "remove", "path": "phoneNumbers"}],
            "PATCH remove phoneNumbers",
        )
        await suite.call(group, "DELETE /Users/{id}", "DELETE", f"/Users/{user_id}", 204)
    return user_id, user_name


async def _patch(
    suite: _Suite, group: str, user_id: str, operations: list[dict[str, Any]], name: str
) -> None:
    await suite.call(
        group,
        name,
        "PATCH",
        f"/Users/{user_id}",
        200,
        json_body={"schemas": [PATCH_OP], "Operations": operations},
        headers={"Content-Type": "application/scim+json"},
    )


async def _run_user_filtering(suite: _Suite, user_name: str) -> None:
    group = "User Filtering"
    # Se crea un usuario efímero para validar filtros de forma independiente.
    payload = {
        "schemas": [USER_SCHEMA_URN],
        "userName": user_name,
        "emails": [{"value": user_name, "primary": True}],
    }
    post = await suite.call(group, "POST usuario filtro", "POST", "/Users", 201, json_body=payload)
    ephemeral_id = ""
    if post is not None and post.status_code == 201:
        try:
            ephemeral_id = post.json().get("id", "")
        except Exception:  # noqa: BLE001
            ephemeral_id = ""

    def _at_least_one(resp: httpx.Response) -> bool:
        return resp.json().get("totalResults", 0) >= 1

    await suite.call(
        group,
        "filter userName eq",
        "GET",
        f'/Users?filter=userName eq "{user_name}"',
        200,
        validate=_at_least_one,
    )
    await suite.call(
        group,
        "filter emails.value co",
        "GET",
        '/Users?filter=emails.value co "example.com"',
        200,
    )
    if ephemeral_id:
        await suite.call(
            group, "cleanup usuario filtro", "DELETE", f"/Users/{ephemeral_id}", 204
        )


async def _run_pagination(suite: _Suite) -> None:
    group = "Pagination"

    def _items_ok(resp: httpx.Response) -> bool:
        body = resp.json()
        return body.get("itemsPerPage", 0) <= 2

    await suite.call(
        group,
        "startIndex/count",
        "GET",
        "/Users?startIndex=1&count=2",
        200,
        validate=_items_ok,
    )


async def _run_group_crud(suite: _Suite, member_id: str) -> None:
    group = "Group CRUD"
    payload: dict[str, Any] = {
        "schemas": [GROUP_SCHEMA_URN],
        "displayName": "conformance-group",
    }
    post = await suite.call(group, "POST /Groups", "POST", "/Groups", 201, json_body=payload)
    group_id = ""
    if post is not None and post.status_code == 201:
        try:
            group_id = post.json().get("id", "")
        except Exception:  # noqa: BLE001
            group_id = ""

    if group_id:
        ops = [
            {
                "op": "add",
                "path": "members",
                "value": [{"value": member_id, "display": "Conformance User"}],
            }
        ]
        await suite.call(
            group,
            "PATCH members add",
            "PATCH",
            f"/Groups/{group_id}",
            200,
            json_body={"schemas": [PATCH_OP], "Operations": ops},
            headers={"Content-Type": "application/scim+json"},
        )
        await suite.call(group, "DELETE /Groups/{id}", "DELETE", f"/Groups/{group_id}", 204)
