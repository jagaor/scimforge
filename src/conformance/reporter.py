import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


@dataclass
class TestResult:
    """Resultado individual de un test de conformidad SCIM."""

    group: str
    name: str
    method: str
    path: str
    expected_status: int
    got_status: int | None
    duration_ms: float
    passed: bool
    error: str | None = None


@dataclass
class ConformanceReport:
    """Informe agregado de una ejecución de la suite de conformidad."""

    base_url: str
    started_at: str
    finished_at: str
    total_duration_ms: float
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.error is None)

    @property
    def errored(self) -> int:
        return sum(1 for r in self.results if r.error is not None)

    @property
    def score(self) -> float:
        total = len(self.results)
        if total == 0:
            return 0.0
        return round((self.passed / total) * 100, 2)


class ConformanceReporter:
    """Renderiza y persiste informes de conformidad SCIM 2.0."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def print_summary(self, report: ConformanceReport) -> None:
        """Imprime la tabla de resultados agrupada por grupo de test."""
        groups: dict[str, list[TestResult]] = {}
        for result in report.results:
            groups.setdefault(result.group, []).append(result)

        for group_name, results in groups.items():
            table = Table(title=f"Grupo: {group_name}", show_lines=False)
            table.add_column("Método", style="cyan", no_wrap=True)
            table.add_column("Path", style="white")
            table.add_column("Esperado", justify="right")
            table.add_column("Obtenido", justify="right")
            table.add_column("Duración (ms)", justify="right")
            table.add_column("Estado", justify="center")

            for r in results:
                got = str(r.got_status) if r.got_status is not None else "-"
                if r.error is not None:
                    status = "[bold red]ERROR[/bold red]"
                elif r.passed:
                    status = "[bold green]PASS[/bold green]"
                else:
                    status = "[bold red]FAIL[/bold red]"
                table.add_row(
                    r.method,
                    r.path,
                    str(r.expected_status),
                    got,
                    f"{r.duration_ms:.1f}",
                    status,
                )
            self.console.print(table)

        summary = (
            f"Base URL: {report.base_url}\n"
            f"Inicio: {report.started_at}\n"
            f"Fin: {report.finished_at}\n"
            f"Total tests: {len(report.results)}\n"
            f"PASS: {report.passed}  FAIL: {report.failed}  ERROR: {report.errored}\n"
            f"Tiempo total: {report.total_duration_ms:.1f} ms\n"
            f"Puntuación de conformidad: {report.score}%"
        )
        self.console.print(Panel(summary, title="Resumen de conformidad", expand=False))

    def save_json(self, report: ConformanceReport, path: str | Path) -> None:
        """Serializa el informe a JSON con indentación de 2 espacios."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(asdict(report), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_json(self, path: str | Path) -> ConformanceReport:
        """Carga un informe previamente guardado y reconstruye el dataclass."""
        data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        results = [TestResult(**item) for item in data.pop("results", [])]
        return ConformanceReport(results=results, **data)
