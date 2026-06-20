"""FastAPI application: x402 payment middleware over the REST routes, with the MCP server mounted.

One Cloud Run service serves both surfaces: the REST API (/v1/*) gated by the payment middleware,
and the MCP server at /mcp gated per-tool by the same x402 rails. The MCP session manager runs
inside the app lifespan (the documented pattern for mounting FastMCP on a host ASGI app).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from x402.http.middleware.fastapi import PaymentMiddlewareASGI

from .config import settings
from .db import close_db, init_db
from .mcp_server import build_mcp
from .routes import router
from .x402_server import build_routes, build_server

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    mcp = build_mcp()
    mcp_app = mcp.streamable_http_app()  # creates the session manager (referenced in lifespan)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_db(settings.database_url)
        async with mcp.session_manager.run():
            yield
        await close_db()

    app = FastAPI(title="x402-agent-api", lifespan=lifespan)
    app.add_middleware(PaymentMiddlewareASGI, routes=build_routes(), server=build_server())
    app.include_router(router)
    # Mount at root so the MCP endpoint is exactly /mcp (FastAPI's own routes are matched first,
    # since they are registered before this catch-all mount).
    app.mount("/", mcp_app)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.port)
