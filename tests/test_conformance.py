import json
import pytest
from httpx import ASGITransport, AsyncClient

from src.server.app import create_app
from src.server.database import init_db
from src.conformance.runner import run_conformance_suite
from src.conformance.reporter import save_json, load_json, print_summary


@pytest.fixture
async def app_client():
    """Levanta la app en memoria con base de datos SQLite efímera."""
    app = create_app(database_url="sqlite:///:memory:")
    await init_db(app)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.anyio
async def test_full_conformance_suite_passes(app_client):
    """La suite completa contra el servidor local debe superar el 90% de conformidad."""
    report = await run_conformance_suite(
        base_url="http://testserver",
        client=app_client,
    )
    assert report.total > 0, "La suite no ejecutó ningún test"
    assert report.score >= 90.0, (
        f"Puntuación de conformidad insuficiente: {report.score:.1f}% "
        f"({report.passed}/{report.total} superados)"
    )


@pytest.mark.anyio
async def test_conformance_report_serializable(app_client, tmp_path):
    """El informe debe serializarse a JSON y recuperarse sin pérdida de datos."""
    report = await run_conformance_suite(
        base_url="http://testserver",
        client=app_client,
    )
    target = tmp_path / "conformance_report.json"
    save_json(report, target)
    assert target.exists(), "El fichero de informe no se creó"

    loaded = load_json(target)
    assert loaded.total == report.total
    assert loaded.passed == report.passed
    assert loaded.failed == report.failed
    assert loaded.score == pytest.approx(report.score)
    assert len(loaded.results) == len(report.results)
    for original, restored in zip(report.results, loaded.results):
        assert original.name == restored.name
        assert original.group == restored.group
        assert original.status_code == restored.status_code
        assert original.passed == restored.passed


def test_reporter_print_does_not_crash(capsys):
    """print_summary debe renderizar un informe de ejemplo sin lanzar excepciones."""
    sample = {
        "base_url": "http://testserver",
        "total": 3,
        "passed": 2,
        "failed": 1,
        "score": 66.67,
        "results": [
            {
                "name": "discover_schemas",
                "group": "Schema Discovery",
                "status_code": 200,
                "expected_status": 200,
                "passed": True,
                "duration_ms": 12.4,
            },
            {
                "name": "create_user",
                "group": "User CRUD",
                "status_code": 201,
                "expected_status": 201,
                "passed": True,
                "duration_ms": 8.1,
            },
            {
                "name": "patch_user_add_member",
                "group": "User PATCH",
                "status_code": 400,
                "expected_status": 200,
                "passed": False,
                "duration_ms": 5.7,
            },
        ],
    }
    print_summary(sample)
    captured = capsys.readouterr()
    assert "PASS" in captured.out or "FAIL" in captured.out
    assert "66.67" in captured.out
