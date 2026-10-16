from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.server import database as db
from src.server.routers import users, groups, schemas, service_provider


# URN del esquema de error definido en RFC 7644 sección 3.12
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"


def create_app() -> FastAPI:
    """Construye y devuelve la aplicación FastAPI del servidor SCIM de referencia.

    La aplicación agrupa los routers de Users, Groups, Schemas y ServiceProviderConfig
    bajo el prefijo /scim/v2, habilita CORS permisivo para pruebas locales y registra
    el ciclo de vida de la base de datos SQLite.
    """
    app = FastAPI(
        title="ScimForge",
        description="Servidor SCIM 2.0 de referencia para validación de conectores IGA",
        version="1.0.0",
    )

    # CORS permisivo: la suite de conformidad puede ejecutarse desde cualquier origen local.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Inicialización de la base de datos al arrancar el servidor.
    @app.on_event("startup")
    async def _on_startup() -> None:
        await db.init_db()

    # Manejador global de ScimError: devuelve la estructura de error del RFC 7644.
    @app.exception_handler(db.ScimError)
    async def _scim_error_handler(request: Request, exc: db.ScimError) -> JSONResponse:
        payload = {
            "schemas": [ERROR_SCHEMA],
            "status": str(exc.status_code),
            "detail": exc.detail,
        }
        return JSONResponse(status_code=exc.status_code, content=payload)

    # Routers del protocolo SCIM bajo el prefijo común /scim/v2.
    app.include_router(users.router, prefix="/scim/v2")
    app.include_router(groups.router, prefix="/scim/v2")
    app.include_router(schemas.router, prefix="/scim/v2")
    app.include_router(service_provider.router, prefix="/scim/v2")

    return app


# Instancia a nivel de módulo para que uvicorn pueda referenciarla como 'src.server.app:app'.
app = create_app()
