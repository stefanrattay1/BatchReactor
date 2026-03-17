"""OPC Tool configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class OPCToolSettings(BaseSettings):
    """Settings for the OPC Tool, loaded from OPC_TOOL_* env vars."""

    web_port: int = 8001
    data_dir: str = "opc_tool_data"
    default_server_port: int = 4840
    cors_origins: list[str] = ["*"]
    build_frontend: bool = True

    model_config = {"env_prefix": "OPC_TOOL_"}
