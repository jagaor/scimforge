import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

# Importaciones internas del proyecto ScimForge
from src.server.app import create_app
from src.conformance.runner import run_conformance_suite
from src.conformance.reporter import ConformanceReporter

# Consola Rich compartida para toda la CLI
console = Console()

# Aplicación Typer principal
app = typer.Typer(
    name="scimforge",
    help="Servidor SCIM 2.0 de referencia y suite de conformidad para validar conectores IGA.",
    add_completion=False,
    no_args_is_help=True,
)

VERSION = "1.0.0"


def _version_callback(value: bool) -> None:
    """Callback que imprime la versión y sale cuando se pasa --version."""
    if value:
        console.print(f"ScimForge v{VERSION}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Muestra la versión de ScimForge y termina.",
    ),
) -> None:
    """ScimForge: servidor SCIM 2.0 de referencia con suite de conformidad."""
    # El callback solo gestiona --version; el resto lo hacen los subcomandos.
    return None


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Dirección de escucha del servidor."),
    port: int = typer.Option(8080, "--port", help="Puerto de escucha del servidor."),
    reload: bool = typer.Option(False, "--reload", help="Activa la recarga automática en desarrollo."),
    db_path: str = typer.Option("scimforge.db", "--db-path", help="Ruta del fichero SQLite de persistencia."),
) -> None:
    """Arranca el servidor SCIM 2.0 de referencia con Uvicorn."""
    import uvicorn

    console.print(
        Panel.fit(
            f"ScimForge v{VERSION}\n"
            f"Host: {host}\n"
            f"Puerto: {port}\n"
            f"Base de datos: {db_path}\n"
            f"Recarga: {'activada' if reload else 'desactivada'}",
            title="Servidor SCIM 2.0",
            border_style="cyan",
        )
    )

    # Construimos la app FastAPI con la ruta de base de datos indicada.
    application = create_app(db_path=db_path)

    uvicorn.run(
        application,
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command()
def test(
    base_url: str = typer.Option(
        ...,
        "--base-url",
        help="URL base del servidor SCIM contra el que ejecutar la suite.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        help="Ruta opcional donde guardar el informe JSON de resultados.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Muestra el detalle de cada aserción ejecutada.",
    ),
) -> None:
    """Ejecuta la suite de conformidad SCIM 2.0 contra una URL base."""
    console.print(f"Ejecutando suite de conformidad contra [bold cyan]{base_url}[/bold cyan]")

    try:
        results = asyncio.run(run_conformance_suite(base_url=base_url, verbose=verbose))
    except Exception as exc:  # noqa: BLE001 - queremos reportar cualquier fallo de red
        console.print(f"[bold red]Error ejecutando la suite:[/bold red] {exc}")
        raise typer.Exit(code=2)

    # Renderizamos el resumen con Rich (tabla PASS/FAIL y puntuación).
    reporter = ConformanceReporter(console=console)
    reporter.print_summary(results)

    # Si se pidió, serializamos el informe a JSON.
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = reporter.to_json(results)
        output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"Informe guardado en [bold green]{output}[/bold green]")

    # Código de salida distinto de cero si hay fallos de conformidad.
    if not reporter.all_passed(results):
        raise typer.Exit(code=1)


@app.command()
def report(
    input: Path = typer.Option(
        ...,
        "--input",
        help="Ruta del fichero JSON con resultados previos de conformidad.",
    ),
) -> None:
    """Muestra formateado con Rich un informe JSON de conformidad guardado."""
    if not input.exists():
        console.print(f"[bold red]No existe el fichero:[/bold red] {input}")
        raise typer.Exit(code=2)

    try:
        payload = json.loads(input.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(f"[bold red]JSON inválido:[/bold red] {exc}")
        raise typer.Exit(code=2)

    reporter = ConformanceReporter(console=console)
    reporter.print_from_payload(payload)


if __name__ == "__main__":
    app()
