import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


class UyuniMCPClient:
    """
    Cliente MCP para hablar con mcp-server-uyuni usando Docker + stdio.
    """

    def __init__(self) -> None:
        self.enabled = (
            os.getenv("MCP_UYUNI_ENABLED", "false").lower().strip()
            in {"1", "true", "yes", "on"}
        )

        self.command = os.getenv("MCP_UYUNI_COMMAND", "docker").strip()

        raw_args = os.getenv("MCP_UYUNI_ARGS", "").strip()
        self.args = [arg.strip() for arg in raw_args.split(",") if arg.strip()]

        self.timeout_seconds = float(
            os.getenv("MCP_UYUNI_TIMEOUT_SECONDS", "60")
        )

    async def list_tools(self) -> list[str]:
        if not self.enabled:
            raise RuntimeError("MCP Uyuni está desactivado en .env.")

        async with self._session() as session:
            tools_response = await session.list_tools()
            return [tool.name for tool in tools_response.tools]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> str:
        if not self.enabled:
            raise RuntimeError("MCP Uyuni está desactivado en .env.")

        async with self._session() as session:
            result = await session.call_tool(
                tool_name,
                arguments=arguments or {},
            )

        return self._format_tool_result(result)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        if not self.args:
            raise RuntimeError(
                "MCP_UYUNI_ARGS está vacío. "
                "Configura el comando Docker para arrancar mcp-server-uyuni."
            )

        print("Arrancando MCP Uyuni")
        print("MCP command:", self.command)
        print("MCP args:", self.args)

        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=None,
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session

    def _format_tool_result(self, result: Any) -> str:
        if getattr(result, "isError", False):
            return f"La tool MCP ha devuelto error: {result}"

        text_parts: list[str] = []

        for item in getattr(result, "content", []):
            if isinstance(item, TextContent):
                text_parts.append(item.text)
            else:
                text_parts.append(str(item))

        if text_parts:
            return "\n".join(text_parts)

        return str(result)