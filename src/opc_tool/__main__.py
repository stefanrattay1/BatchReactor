"""Main entry point for the OPC Tool."""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import subprocess
from pathlib import Path

from .config import OPCToolSettings
from .node_manager import NodeManager
from .client import OPCClientPool
from .server import ManagedOPCServer
from .web import create_app, start_web_server

logger = logging.getLogger("opc_tool")


def resolve_project_root() -> Path:
    """Resolve the project root for data/config lookups."""
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parent.parent.parent,
    ]
    for candidate in candidates:
        if (candidate / "opc_tool_data").is_dir() or (candidate / "configs").is_dir():
            return candidate
    return candidates[0]


async def run(settings: OPCToolSettings) -> None:
    """Start the OPC Tool: NodeManager, client pool, web server."""
    project_root = resolve_project_root()

    # Build frontend if requested
    if settings.build_frontend:
        frontend_dir = project_root / "opc_frontend"
        npm = shutil.which("npm")
        if not npm:
            logger.warning("npm not found; skipping OPC frontend build")
        elif not frontend_dir.exists():
            logger.warning("opc_frontend directory not found; skipping build")
        else:
            logger.info("Building OPC frontend (npm run build)...")
            try:
                subprocess.run([npm, "run", "build"], cwd=str(frontend_dir), check=True)
            except subprocess.CalledProcessError as exc:
                logger.warning("OPC frontend build failed: %s", exc)

    # Data directory
    data_dir = project_root / settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    # Initialize components
    node_manager = NodeManager(data_dir=data_dir)
    logger.info("Node manager initialized with %d nodes", len(node_manager.list_nodes()))

    # Client pool for external OPC connections
    client_config_path = data_dir / "connections.json"
    client_pool = OPCClientPool(node_manager, client_config_path)
    await client_pool.start()
    logger.info("OPC client pool started")

    # Managed OPC UA servers (created via API at runtime)
    servers: dict[str, ManagedOPCServer] = {}

    # Web server
    app = create_app(
        node_manager, client_pool, servers,
        cors_origins=settings.cors_origins,
    )
    logger.info("OPC Tool web interface at http://localhost:%d", settings.web_port)

    try:
        await start_web_server(app, settings.web_port)
    finally:
        # Cleanup
        for srv in servers.values():
            await srv.stop()
        await client_pool.stop()
        logger.info("OPC Tool shut down")


def main_sync() -> None:
    """Synchronous entry point for console_scripts."""
    parser = argparse.ArgumentParser(description="OPC Tool — OPC UA Server/Client Manager")
    parser.add_argument("--port", type=int, default=None,
                        help="Web server port (overrides OPC_TOOL_WEB_PORT)")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Data directory for persistent config")
    parser.add_argument("--no-build", action="store_true",
                        help="Skip frontend build on startup")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logging.getLogger("asyncua.server.address_space").setLevel(logging.WARNING)

    settings = OPCToolSettings()
    if args.port is not None:
        settings.web_port = args.port
    if args.data_dir is not None:
        settings.data_dir = args.data_dir
    if args.no_build:
        settings.build_frontend = False

    asyncio.run(run(settings))


if __name__ == "__main__":
    main_sync()
