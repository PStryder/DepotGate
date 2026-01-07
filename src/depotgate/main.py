"""Main entry point for DepotGate service."""

import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from depotgate import __version__
from depotgate.api.routes import router as api_router
from depotgate.config import settings
from depotgate.db.connection import close_databases, init_databases
from depotgate.mcp.routes import router as mcp_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await init_databases()

    # Ensure storage directories exist
    settings.storage_base_path.mkdir(parents=True, exist_ok=True)
    settings.sink_filesystem_base_path.mkdir(parents=True, exist_ok=True)

    yield

    # Shutdown
    await close_databases()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="DepotGate",
        description="Artifact staging, closure verification, and outbound logistics",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(api_router)

    # Include MCP routes
    app.include_router(mcp_router)

    # Root redirect to docs
    @app.get("/")
    async def root():
        return {
            "service": "DepotGate",
            "version": __version__,
            "docs": "/docs",
            "api": "/api/v1",
            "mcp": "/mcp",
        }

    return app


app = create_app()


def main():
    """Run the service."""
    uvicorn.run(
        "depotgate.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
