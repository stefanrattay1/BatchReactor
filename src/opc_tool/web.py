"""FastAPI web server for the OPC Tool."""

from __future__ import annotations

import shutil
import subprocess
import logging
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .node_manager import NodeManager, OPCNode
from .client import OPCClientPool
from .server import ManagedOPCServer

logger = logging.getLogger("opc_tool.web")


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class CreateNodeRequest(BaseModel):
    id: str
    name: str
    node_id: str = ""
    source: str = "local"
    category: str = "sensor"
    data_type: str = "Double"
    writable: bool = False
    current_value: Any = None
    metadata: dict = {}


class UpdateNodeRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    data_type: str | None = None
    writable: bool | None = None
    metadata: dict | None = None


class WriteValueRequest(BaseModel):
    value: Any


class BulkReadRequest(BaseModel):
    node_ids: list[str]


class BulkWriteRequest(BaseModel):
    updates: list[dict[str, Any]]


class CreateServerRequest(BaseModel):
    server_id: str
    endpoint: str = "opc.tcp://0.0.0.0:4840"
    name: str = "OPC Tool Server"
    namespace_uri: str = "urn:opctool:server"


class ConnectionConfig(BaseModel):
    id: str
    endpoint: str
    security_mode: str = "None"
    security_policy: str | None = None
    certificate_path: str | None = None
    private_key_path: str | None = None
    username: str | None = None
    password: str | None = None
    enabled: bool = True


class CredentialsConfig(BaseModel):
    username: str | None = None
    password: str


class BrowseRequest(BaseModel):
    node_id: str | None = None


class SubscriptionConfig(BaseModel):
    id: str
    connection_id: str
    node_id: str
    catalog_node_id: str
    polling_rate_ms: int = 1000
    transform: str = "value"
    enabled: bool = True


class DiscoveryRequest(BaseModel):
    discovery_url: str | None = None


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    node_manager: NodeManager,
    client_pool: OPCClientPool,
    servers: dict[str, ManagedOPCServer],
    *,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """Create the FastAPI application for the OPC Tool."""

    app = FastAPI(title="OPC Tool", version=__version__)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- Health ----

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__}

    # ---- Node CRUD ----

    @app.get("/api/nodes")
    async def list_nodes(category: str | None = None):
        nodes = node_manager.list_nodes(category=category)
        return {"nodes": [n.to_dict() for n in nodes]}

    @app.get("/api/nodes/{node_id}")
    async def get_node(node_id: str):
        node = node_manager.get_node(node_id)
        if node is None:
            return JSONResponse({"error": "Node not found"}, status_code=404)
        return node.to_dict()

    @app.post("/api/nodes")
    async def create_node(request: CreateNodeRequest):
        node = OPCNode(
            id=request.id,
            name=request.name,
            node_id=request.node_id or f"ns=2;s={request.name}",
            source=request.source,
            category=request.category,
            data_type=request.data_type,
            writable=request.writable,
            current_value=request.current_value,
            metadata=request.metadata,
        )
        node_manager.add_node(node)
        return {"status": "ok", "node": node.to_dict()}

    @app.put("/api/nodes/{node_id}")
    async def update_node(node_id: str, request: UpdateNodeRequest):
        updates = {k: v for k, v in request.model_dump().items() if v is not None}
        node = node_manager.update_node(node_id, updates)
        if node is None:
            return JSONResponse({"error": "Node not found"}, status_code=404)
        return {"status": "ok", "node": node.to_dict()}

    @app.delete("/api/nodes/{node_id}")
    async def delete_node(node_id: str):
        if not node_manager.remove_node(node_id):
            return JSONResponse({"error": "Node not found"}, status_code=404)
        return {"status": "ok"}

    # ---- Value read/write ----

    @app.get("/api/nodes/{node_id}/value")
    async def get_value(node_id: str):
        try:
            value, timestamp = node_manager.get_value(node_id)
            return {"value": value, "timestamp": timestamp}
        except KeyError:
            return JSONResponse({"error": "Node not found"}, status_code=404)

    @app.post("/api/nodes/{node_id}/value")
    async def write_value(node_id: str, request: WriteValueRequest):
        try:
            node_manager.set_value(node_id, request.value)
            # Also push to OPC UA server if one is running
            for srv in servers.values():
                if srv.running:
                    await srv.update_node(node_id, request.value)
            return {"status": "ok"}
        except KeyError:
            return JSONResponse({"error": "Node not found"}, status_code=404)

    @app.post("/api/values/bulk")
    async def read_bulk(request: BulkReadRequest):
        values = node_manager.get_values_bulk(request.node_ids)
        return {"values": values}

    @app.post("/api/values/write-bulk")
    async def write_bulk(request: BulkWriteRequest):
        node_manager.set_values_bulk(request.updates)
        # Push to OPC UA servers
        for srv in servers.values():
            if srv.running:
                for item in request.updates:
                    await srv.update_node(item["node_id"], item["value"])
        return {"status": "ok"}

    # ---- OPC UA Server management ----

    @app.get("/api/servers")
    async def list_servers():
        return {
            "servers": [
                {
                    "server_id": srv.server_id,
                    "endpoint": srv.endpoint,
                    "name": srv.name,
                    "running": srv.running,
                }
                for srv in servers.values()
            ]
        }

    @app.post("/api/servers")
    async def create_server(request: CreateServerRequest):
        if request.server_id in servers:
            return JSONResponse(
                {"error": f"Server '{request.server_id}' already exists"},
                status_code=400,
            )
        srv = ManagedOPCServer(
            server_id=request.server_id,
            endpoint=request.endpoint,
            name=request.name,
            namespace_uri=request.namespace_uri,
        )
        await srv.init(node_manager)
        await srv.start()
        servers[request.server_id] = srv
        return {"status": "ok", "server_id": request.server_id}

    @app.delete("/api/servers/{server_id}")
    async def delete_server(server_id: str):
        srv = servers.get(server_id)
        if srv is None:
            return JSONResponse({"error": "Server not found"}, status_code=404)
        await srv.stop()
        del servers[server_id]
        return {"status": "ok"}

    # ---- Client connection management ----

    @app.get("/api/connections")
    async def get_connections():
        return {
            "connections": client_pool.get_connection_status(),
            "subscriptions": client_pool.get_subscription_status(),
        }

    @app.post("/api/connections")
    async def add_connection(request: ConnectionConfig):
        try:
            conn = await client_pool.add_connection(request.dict())
            return {
                "status": "ok",
                "connection": {
                    "id": conn.id,
                    "endpoint": conn.endpoint,
                    "connected": conn.connected,
                },
            }
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.delete("/api/connections/{conn_id}")
    async def remove_connection(conn_id: str):
        try:
            await client_pool.remove_connection(conn_id)
            return {"status": "ok"}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/connections/{conn_id}/credentials")
    async def set_credentials(conn_id: str, request: CredentialsConfig):
        try:
            conn = await client_pool.set_connection_credentials(
                conn_id, username=request.username, password=request.password,
            )
            return {
                "status": "ok",
                "connection": {
                    "id": conn.id,
                    "endpoint": conn.endpoint,
                    "connected": conn.connected,
                    "needs_credentials": bool(conn.username and not conn.has_runtime_password),
                },
            }
        except KeyError:
            return JSONResponse({"error": "Connection not found"}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/connections/{conn_id}/browse")
    async def browse_nodes(conn_id: str, request: BrowseRequest):
        conn = client_pool.connections.get(conn_id)
        if not conn:
            return JSONResponse({"error": "Connection not found"}, status_code=404)
        if not conn.connected:
            return JSONResponse({"error": "Connection not active"}, status_code=400)
        try:
            nodes = await conn.browse_node(request.node_id)
            return {"nodes": nodes}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ---- Subscription management ----

    @app.post("/api/subscriptions")
    async def add_subscription(request: SubscriptionConfig):
        try:
            sub = client_pool.add_subscription(request.dict())
            return {
                "status": "ok",
                "subscription": {
                    "id": sub.id,
                    "connection_id": sub.connection_id,
                    "node_id": sub.node_id,
                    "catalog_node_id": sub.catalog_node_id,
                },
            }
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.delete("/api/subscriptions/{sub_id}")
    async def remove_subscription(sub_id: str):
        try:
            client_pool.remove_subscription(sub_id)
            return {"status": "ok"}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    # ---- Discovery ----

    @app.post("/api/discover")
    async def discover(request: DiscoveryRequest):
        discovery_url = request.discovery_url or client_pool.discovery_url
        servers_found = await OPCClientPool.discover_servers(discovery_url)
        return {"servers": servers_found}

    # ---- Static files (frontend) ----

    frontend_dist = Path(__file__).resolve().parent.parent.parent / "opc_frontend" / "dist"
    if frontend_dist.is_dir():
        @app.get("/favicon.ico")
        async def favicon_ico():
            for name in ("favicon.ico", "favicon.svg"):
                path = frontend_dist / name
                if path.exists():
                    return FileResponse(path)
            return JSONResponse(status_code=204, content=None)

        # Mount static assets (css/js) under /assets
        assets_dir = frontend_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{path:path}")
        async def spa_fallback(path: str):
            # Serve actual files if they exist, otherwise fall back to index.html
            file = frontend_dist / path
            if path and file.exists() and file.is_file():
                return FileResponse(file)
            return FileResponse(frontend_dist / "index.html")

    return app


async def start_web_server(app: FastAPI, port: int) -> None:
    """Run uvicorn in the current event loop."""
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
