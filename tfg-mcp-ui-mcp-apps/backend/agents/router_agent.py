import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

from llm.base import ChatMessage, LLMProvider
from llm.factory import create_llm_provider
from mcp_clients.uyuni_client import MCPToolDefinition, UyuniMCPClient


@dataclass(frozen=True)
class RouteDecision:
    kind: str
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    clarification: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.tool_name is not None:
            payload["tool_name"] = self.tool_name
        if self.arguments is not None:
            payload["arguments"] = self.arguments
        if self.clarification:
            payload["clarification"] = self.clarification
        return payload


class RouterAgent:
    """First LLM stage: select a real read-only Uyuni MCP tool and arguments.

    Visual selection is deliberately NOT done here. It happens only after the
    real MCP result exists, inside ``PresentationAgent``.
    """

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        uyuni_client: UyuniMCPClient | None = None,
    ) -> None:
        self.llm_provider = llm_provider or create_llm_provider()
        self.uyuni_client = uyuni_client or UyuniMCPClient()
        self._cached_tools: list[MCPToolDefinition] | None = None

    async def route(self, messages: Sequence[ChatMessage]) -> RouteDecision:
        user_message = self._last_user_message(messages)

        if not user_message:
            return RouteDecision(kind="text")

        available_tools = await self._get_available_tools()
        if not available_tools:
            return RouteDecision(
                kind="clarification",
                clarification="El MCP de Uyuni no ha anunciado herramientas de lectura disponibles.",
            )

        catalog = json.dumps(
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema or {},
                }
                for tool in available_tools
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )

        prompt = [
            ChatMessage(
                role="system",
                content=f"""
Eres el router de herramientas de lectura de un servidor MCP de Uyuni.

Resuelve en UNA sola decisión:
1. Si la petición necesita datos reales de Uyuni.
2. Si los necesita, elige exactamente UNA herramienta del catálogo real.
3. Construye sus argumentos respetando su input_schema.

CATÁLOGO REAL:
{catalog}

Usa Uyuni para sistemas/hosts registrados, detalles o búsquedas, actualizaciones,
parches/erratas/CVE, reinicios, eventos, acciones, activation keys y grupos.
No uses Uyuni para conversación general ni teoría.

IMPORTANTE PARA ESTE EXPERIMENTO:
- NO decidas tabla/gráfico/timeline ni ninguna representación visual.
- La selección visual la hará otra llamada LLM DESPUÉS de recibir los datos reales.

Reglas:
- Devuelve SOLO JSON válido, sin Markdown.
- No inventes herramientas ni parámetros.
- Respeta tipos y argumentos obligatorios.
- Omite opcionales no solicitados.
- Si falta un obligatorio no deducible, pregunta en clarification.

Si hay tool:
{{"should_call_tool":true,"server":"mcp_uyuni","tool":"nombre","arguments":{{}}}}

Si no hace falta tool:
{{"should_call_tool":false,"server":null,"tool":null,"arguments":{{}}}}

Si falta información:
{{"should_call_tool":false,"server":null,"tool":null,"arguments":{{}},"clarification":"pregunta breve"}}
""".strip(),
            ),
            ChatMessage(role="user", content=user_message),
        ]

        raw = await self.llm_provider.generate_response(prompt)
        parsed = self._parse_json(raw)
        if parsed is None:
            return RouteDecision(kind="text")

        if parsed.get("should_call_tool") is not True:
            clarification = parsed.get("clarification")
            if isinstance(clarification, str) and clarification.strip():
                return RouteDecision(
                    kind="clarification",
                    clarification=clarification.strip(),
                )
            return RouteDecision(kind="text")

        if parsed.get("server") != "mcp_uyuni":
            return RouteDecision(
                kind="clarification",
                clarification="No he podido seleccionar de forma segura una herramienta de Uyuni.",
            )

        tool_name = parsed.get("tool")
        arguments = parsed.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}

        selected = next((tool for tool in available_tools if tool.name == tool_name), None)
        if selected is None:
            return RouteDecision(
                kind="clarification",
                clarification="No he podido seleccionar una herramienta de lectura válida de Uyuni.",
            )

        validation_error = self._validate_arguments(arguments, selected)
        if validation_error:
            return RouteDecision(
                kind="clarification",
                clarification=validation_error,
            )

        return RouteDecision(
            kind="tool",
            tool_name=selected.name,
            arguments=arguments,
        )

    async def general_response(self, messages: Sequence[ChatMessage]) -> str:
        return await self.llm_provider.generate_response(messages)

    async def _get_available_tools(self) -> list[MCPToolDefinition]:
        if self._cached_tools is None:
            self._cached_tools = list(await self.uyuni_client.list_tools())
        return list(self._cached_tools)

    @staticmethod
    def _last_user_message(messages: Sequence[ChatMessage]) -> str:
        for message in reversed(messages):
            if message.role.lower().strip() == "user" and message.content.strip():
                return message.content.strip()
        return ""

    @staticmethod
    def _validate_arguments(arguments: dict[str, Any], tool: MCPToolDefinition) -> str | None:
        schema = tool.input_schema or {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict):
            properties = {}
        if not isinstance(required, list):
            required = []

        unknown = sorted(key for key in arguments if key not in properties)
        if unknown:
            return f"Se han generado parámetros inexistentes para {tool.name}: {', '.join(unknown)}."

        missing = [key for key in required if key not in arguments]
        if missing:
            return f"Falta información obligatoria para {tool.name}: {', '.join(missing)}."
        return None

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        clean = text.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```json\s*", "", clean, flags=re.IGNORECASE)
            clean = re.sub(r"^```\s*", "", clean)
            clean = re.sub(r"\s*```$", "", clean)
        try:
            value = json.loads(clean)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass

        start, end = clean.find("{"), clean.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            value = json.loads(clean[start : end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
