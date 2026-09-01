import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent


@dataclass(frozen=True)
class MCPToolDefinition:
    """Metadatos mínimos de una herramienta MCP necesarios para el router."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class MCPToolResult:
    """Resultado MCP compatible con texto y contenido estructurado opcional."""

    text: str
    structured_data: Any | None = None


class UyuniMCPClient:
    """
    Cliente MCP para hablar con mcp-server-uyuni usando Docker + stdio.

    En esta fase el backend trabaja únicamente con herramientas de lectura.
    Las herramientas de escritura conocidas se filtran aunque el servidor MCP
    las exponga accidentalmente. Más adelante podrán pasar por Human in the Loop.
    """

    # Herramientas de escritura publicadas actualmente por mcp-server-uyuni.
    # Se bloquean aquí de forma explícita hasta implementar Human in the Loop.
    WRITE_TOOL_NAMES = {
        "schedule_pending_updates_to_system",
        "schedule_specific_update",
        "add_system",
        "remove_system",
        "schedule_system_reboot",
        "cancel_action",
        "create_system_group",
        "add_systems_to_group",
        "remove_systems_from_group",
    }

    # Salvaguarda conservadora para futuras tools de escritura con nombres similares.
    WRITE_TOOL_PREFIXES = (
        "schedule_",
        "add_",
        "remove_",
        "cancel_",
        "create_",
        "delete_",
    )

    def __init__(self) -> None:
        self.enabled = (
            os.getenv("MCP_UYUNI_ENABLED", "false").lower().strip()
            in {"1", "true", "yes", "on"}
        )

        self.command = os.getenv("MCP_UYUNI_COMMAND", "docker").strip()

        raw_args = os.getenv("MCP_UYUNI_ARGS", "").strip()
        self.args = [arg.strip() for arg in raw_args.split(",") if arg.strip()]

        self.timeout_seconds = float(
            os.getenv("MCP_UYUNI_TIMEOUT_SECONDS", "180")
        )

        # El catálogo se mantiene durante la vida del backend para no arrancar
        # un contenedor adicional en cada consulta al router.
        self._read_tools_cache: list[MCPToolDefinition] | None = None

    async def list_tools(
        self,
        force_refresh: bool = False,
    ) -> list[MCPToolDefinition]:
        """
        Descubre las herramientas expuestas por el MCP y devuelve únicamente
        las de lectura junto con su descripción y esquema de argumentos.
        """

        if not self.enabled:
            raise RuntimeError("MCP Uyuni está desactivado en .env.")

        if self._read_tools_cache is not None and not force_refresh:
            return list(self._read_tools_cache)

        async with self._session() as session:
            tools_response = await self._with_timeout(
                session.list_tools(),
                "listar las herramientas de Uyuni",
            )

        read_tools: list[MCPToolDefinition] = []

        for tool in tools_response.tools:
            tool_name = str(getattr(tool, "name", "")).strip()

            if not tool_name or not self._is_read_only_tool_name(tool_name):
                continue

            description = getattr(tool, "description", "") or ""
            input_schema = getattr(tool, "inputSchema", None)

            # Compatibilidad defensiva por si una versión del SDK expone
            # el atributo con snake_case.
            if input_schema is None:
                input_schema = getattr(tool, "input_schema", {})

            if not isinstance(input_schema, dict):
                try:
                    input_schema = dict(input_schema)
                except (TypeError, ValueError):
                    input_schema = {}

            read_tools.append(
                MCPToolDefinition(
                    name=tool_name,
                    description=str(description).strip(),
                    input_schema=input_schema,
                )
            )

        self._read_tools_cache = read_tools
        return list(read_tools)

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> str:
        """Contrato original: devuelve únicamente texto."""

        result = await self.call_tool_with_data(tool_name, arguments)
        return result.text

    async def call_tool_with_data(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPToolResult:
        """
        Ejecuta la misma tool de lectura, conservando además structuredContent
        si el servidor MCP lo proporciona. No cambia el comportamiento de
        ``call_tool`` ni las salvaguardas de solo lectura.
        """

        if not self.enabled:
            raise RuntimeError("MCP Uyuni está desactivado en .env.")

        if not self._is_read_only_tool_name(tool_name):
            raise RuntimeError(
                "La herramienta solicitada puede modificar Uyuni y está bloqueada "
                "hasta implementar Human in the Loop: "
                f"{tool_name}"
            )

        # Solo se puede ejecutar una tool que el propio servidor haya anunciado
        # como disponible en el catálogo de lectura de esta sesión del backend.
        available_tools = {
            tool.name: tool
            for tool in await self.list_tools()
        }

        if tool_name not in available_tools:
            raise RuntimeError(
                "La herramienta MCP solicitada no está disponible entre las "
                f"herramientas de lectura de Uyuni: {tool_name}"
            )

        async with self._session() as session:
            raw_result = await self._with_timeout(
                session.call_tool(
                    tool_name,
                    arguments=arguments or {},
                ),
                f"ejecutar la herramienta {tool_name}",
            )

        return MCPToolResult(
            text=self._format_tool_result(raw_result),
            structured_data=self._get_structured_tool_result(raw_result),
        )

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
                await self._with_timeout(
                    session.initialize(),
                    "inicializar la sesión MCP de Uyuni",
                )
                yield session

    async def _with_timeout(self, awaitable: Any, operation: str) -> Any:
        """Aplica MCP_UYUNI_TIMEOUT_SECONDS a las operaciones del MCP upstream."""

        try:
            return await asyncio.wait_for(
                awaitable,
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise RuntimeError(
                f"Timeout de Uyuni MCP tras {self.timeout_seconds:g} s al {operation}."
            ) from exc

    def _is_read_only_tool_name(self, tool_name: str) -> bool:
        """Bloquea las tools de escritura conocidas y nombres mutadores."""

        normalized_name = tool_name.lower().strip()

        if normalized_name in self.WRITE_TOOL_NAMES:
            return False

        return not normalized_name.startswith(self.WRITE_TOOL_PREFIXES)

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

    def _get_structured_tool_result(self, result: Any) -> Any | None:
        """Obtiene structuredContent sin depender de una única versión del SDK."""

        structured = getattr(result, "structuredContent", None)
        if structured is None:
            structured = getattr(result, "structured_content", None)

        if isinstance(structured, (dict, list)):
            return structured

        return None
