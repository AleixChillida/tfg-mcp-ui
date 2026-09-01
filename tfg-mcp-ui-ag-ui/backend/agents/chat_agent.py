import json
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from agents.visualization_builder import build_visualizations
from llm.base import ChatMessage, LLMProvider
from llm.factory import create_llm_provider
from mcp_clients.uyuni_client import MCPToolDefinition, MCPToolResult, UyuniMCPClient


@dataclass(frozen=True)
class AgentResponse:
    """Respuesta del agente: texto compatible + visuales opcionales para AG-UI."""

    text: str
    visualizations: list[dict[str, Any]] = field(default_factory=list)


class ChatAgent:
    """
    Agente conversacional principal del backend.

    Flujo optimizado (experimento de 2 llamadas LLM para consultas Uyuni):
    1. Recibe mensajes desde AG-UI.
    2. Convierte los mensajes a ChatMessage.
    3. Descubre/cachea las tools de lectura reales del MCP.
    4. Una única llamada LLM decide si usar Uyuni y, en caso afirmativo,
       selecciona la tool y construye sus argumentos.
    5. El backend valida la decisión y ejecuta la tool MCP.
    6. Una segunda llamada LLM redacta la respuesta final con el resultado real.
    7. Si no hace falta MCP, una segunda llamada responde normalmente.
    """

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        uyuni_client: UyuniMCPClient | None = None,
    ):
        self.llm_provider = llm_provider or create_llm_provider()
        self.uyuni_client = uyuni_client or UyuniMCPClient()

        # Cache del catálogo MCP para no volver a arrancar Docker solo para
        # descubrir las mismas tools en cada turno. Se rellena en el primer uso.
        self._cached_uyuni_tools: list[MCPToolDefinition] | None = None

    async def generate_response(self, agui_messages: Sequence[Any]) -> str:
        """
        Contrato textual original. Se conserva para no romper tests ni otros
        consumidores que esperan exactamente un ``str``.
        """

        response = await self.generate_rich_response(agui_messages)
        return response.text

    async def generate_rich_response(
        self,
        agui_messages: Sequence[Any],
    ) -> AgentResponse:
        """
        Punto de entrada usado por AG-UI.

        En el modo optimizado se unifican router + selector + argumentos en
        una única inferencia. Para una consulta Uyuni el flujo queda:

            LLM decisión completa -> MCP -> LLM respuesta final

        Es decir, dos llamadas LLM en lugar de hasta cuatro.
        """

        chat_messages = [
            self._convert_agui_message_to_chat_message(message)
            for message in agui_messages
        ]

        last_user_message = self._get_last_user_message(chat_messages)

        tool_decision = await self._decide_tool_and_arguments(
            last_user_message
        )

        print("Unified tool decision:", tool_decision)

        if tool_decision.get("should_call_tool") is True:
            return await self._execute_tool_decision_rich(
                original_user_message=last_user_message,
                tool_decision=tool_decision,
            )

        clarification = tool_decision.get("clarification")
        if isinstance(clarification, str) and clarification.strip():
            return AgentResponse(text=clarification.strip())

        # Si la primera llamada concluye que no hace falta Uyuni, la segunda
        # llamada responde como chatbot normal usando el historial completo.
        text = await self.llm_provider.generate_response(chat_messages)
        return AgentResponse(text=text)

    async def _get_available_tools(
        self,
    ) -> list[MCPToolDefinition]:
        """
        Devuelve el catálogo de tools de lectura y lo cachea durante la vida
        del proceso del backend.

        Esto evita repetir list_tools() y arrancar un contenedor MCP solo para
        redescubrir el mismo catálogo en cada mensaje.
        """

        if self._cached_uyuni_tools is None:
            tools = await self.uyuni_client.list_tools()
            self._cached_uyuni_tools = list(tools)

        return self._cached_uyuni_tools

    async def _decide_tool_and_arguments(
        self,
        user_message: str,
    ) -> dict[str, Any]:
        """
        Unifica en UNA llamada LLM:
        - decidir si la petición necesita Uyuni;
        - elegir una tool real del catálogo;
        - construir sus argumentos.

        El backend sigue validando que la tool exista realmente y que no se
        envíen nombres de argumentos inexistentes.
        """

        available_tools = await self._get_available_tools()

        if not available_tools:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "El MCP de Uyuni no ha anunciado ninguna herramienta "
                    "de lectura disponible."
                ),
            }

        tool_catalog = self._build_tool_decision_catalog(available_tools)

        decision_messages = [
            ChatMessage(
                role="system",
                content=f"""
Eres el router y selector de herramientas de lectura del servidor MCP de Uyuni.

Debes resolver en UNA sola decisión estas tres tareas:
1. Decidir si la petición necesita consultar datos reales de Uyuni.
2. Si los necesita, elegir exactamente UNA tool del catálogo real.
3. Construir los argumentos de esa tool respetando su input_schema.

CATÁLOGO REAL DE HERRAMIENTAS:
{tool_catalog}

Cuándo usar Uyuni:
- sistemas, servidores o hosts registrados;
- detalles o búsqueda de sistemas por nombre/IP;
- actualizaciones, parches, erratas o CVE;
- reinicios pendientes;
- eventos o acciones programadas;
- activation keys;
- grupos de sistemas;
- o si el usuario pide explícitamente una tool disponible del MCP de Uyuni.

No uses Uyuni para conversación general, explicaciones teóricas ni preguntas
que no necesiten datos reales del servidor.

Reglas obligatorias:
- Devuelve exclusivamente JSON válido, sin Markdown ni explicaciones.
- Solo puedes seleccionar una tool cuyo nombre aparezca exactamente en el catálogo.
- No inventes tools ni nombres de argumentos.
- Usa exclusivamente argumentos definidos en input_schema.
- Respeta los tipos del input_schema.
- Omite argumentos opcionales que el usuario no haya pedido.
- Si falta un argumento obligatorio que no puedas deducir con seguridad,
  devuelve should_call_tool=false y una pregunta breve en clarification.
- Si no hace falta Uyuni, devuelve should_call_tool=false sin inventar una tool.

Formato cuando hay que ejecutar una tool:
{{
  "should_call_tool": true,
  "server": "mcp_uyuni",
  "tool": "nombre_exacto",
  "arguments": {{}}
}}

Formato cuando no hace falta Uyuni:
{{
  "should_call_tool": false,
  "server": null,
  "tool": null,
  "arguments": {{}}
}}

Formato cuando falta un dato obligatorio:
{{
  "should_call_tool": false,
  "server": null,
  "tool": null,
  "arguments": {{}},
  "clarification": "pregunta breve"
}}
""".strip(),
            ),
            ChatMessage(role="user", content=user_message),
        ]

        raw_response = await self.llm_provider.generate_response(
            decision_messages
        )
        print("LLM unified decision raw response:", raw_response)

        parsed = self._parse_json_from_text(raw_response)

        if parsed is None:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "reason": "invalid_json_from_unified_tool_decision",
                "raw_response": raw_response,
            }

        decision = self._normalize_tool_decision(parsed)
        decision = self._validate_tool_decision(
            decision,
            available_tools,
        )

        if decision.get("should_call_tool") is not True:
            return decision

        selected_tool_name = decision.get("tool")
        selected_tool = next(
            (
                tool
                for tool in available_tools
                if tool.name == selected_tool_name
            ),
            None,
        )

        if selected_tool is None:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "No he podido seleccionar una herramienta válida de Uyuni."
                ),
            }

        return self._validate_generated_arguments(
            decision=decision,
            selected_tool=selected_tool,
        )

    def _validate_generated_arguments(
        self,
        decision: dict[str, Any],
        selected_tool: MCPToolDefinition,
    ) -> dict[str, Any]:
        """
        Validación determinista mínima de los argumentos generados por el LLM.

        No sustituye la validación del propio MCP, pero evita ejecutar una tool
        si el modelo inventa nombres de parámetros o omite uno obligatorio.
        """

        arguments = decision.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}

        input_schema = selected_tool.input_schema or {}
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])

        if not isinstance(properties, dict):
            properties = {}

        if not isinstance(required, list):
            required = []

        unknown_arguments = [
            key for key in arguments
            if key not in properties
        ]

        if unknown_arguments:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "El modelo ha generado argumentos que no existen en el "
                    f"schema de {selected_tool.name}: "
                    f"{', '.join(sorted(unknown_arguments))}."
                ),
            }

        missing_required = [
            key for key in required
            if key not in arguments
        ]

        if missing_required:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "Falta información obligatoria para ejecutar "
                    f"{selected_tool.name}: "
                    f"{', '.join(missing_required)}."
                ),
            }

        return {
            "should_call_tool": True,
            "server": "mcp_uyuni",
            "tool": selected_tool.name,
            "arguments": arguments,
        }

    async def _execute_tool_decision(
        self,
        original_user_message: str,
        tool_decision: dict[str, Any],
    ) -> str:
        """Compatibilidad con el contrato textual anterior."""

        response = await self._execute_tool_decision_rich(
            original_user_message=original_user_message,
            tool_decision=tool_decision,
        )
        return response.text

    async def _execute_tool_decision_rich(
        self,
        original_user_message: str,
        tool_decision: dict[str, Any],
    ) -> AgentResponse:
        """Ejecuta la tool y prepara texto + visuales sin alterar los datos MCP."""

        server = tool_decision.get("server")
        tool = tool_decision.get("tool")
        arguments = tool_decision.get("arguments", {})

        if server != "mcp_uyuni":
            return AgentResponse(
                text=(
                    "El modelo ha solicitado una herramienta de un servidor MCP "
                    f"no soportado todavía: {server}"
                )
            )

        available_tools = {
            available_tool.name: available_tool
            for available_tool in await self._get_available_tools()
        }

        if not isinstance(tool, str) or tool not in available_tools:
            return AgentResponse(
                text=(
                    "El modelo ha solicitado una herramienta que no está disponible "
                    f"entre las tools de lectura de Uyuni: {tool}"
                )
            )

        if not isinstance(arguments, dict):
            arguments = {}

        print(f"Ejecutando MCP Uyuni tool={tool} arguments={arguments}")

        call_tool_with_data = getattr(self.uyuni_client, "call_tool_with_data", None)
        if callable(call_tool_with_data):
            tool_result = await call_tool_with_data(tool, arguments)
        else:
            # Compatibilidad defensiva con dobles de prueba o clientes antiguos
            # que solo implementen el contrato textual ``call_tool``.
            legacy_text = await self.uyuni_client.call_tool(tool, arguments)
            tool_result = MCPToolResult(text=legacy_text)

        print("MCP Uyuni raw result:", tool_result.text)

        text = await self._generate_final_answer_from_tool_result(
            original_user_message=original_user_message,
            tool_name=tool,
            tool_result=tool_result.text,
        )

        visualizations = build_visualizations(
            user_message=original_user_message,
            tool_name=tool,
            tool_result=tool_result.text,
            structured_data=tool_result.structured_data,
        )

        return AgentResponse(text=text, visualizations=visualizations)

    async def _generate_final_answer_from_tool_result(
        self,
        original_user_message: str,
        tool_name: str,
        tool_result: str,
    ) -> str:
        """
        Pide al LLM que redacte la respuesta final usando el resultado real
        devuelto por la herramienta MCP.
        """

        final_answer_messages = [
            ChatMessage(
                role="system",
                content="""
Eres el asistente conversacional de TFG MCP UI.

Has recibido el resultado real de una herramienta MCP ya ejecutada por el backend.

Reglas:
- No inventes datos.
- Usa únicamente el resultado de la herramienta.
- No digas que no tienes acceso al sistema, porque el backend ya ha consultado la herramienta.
- No menciones detalles internos innecesarios.
- Responde en el mismo idioma que el usuario.
- Sé claro y breve.
- Si el resultado contiene JSON, explícalo de forma legible.
""".strip(),
            ),
            ChatMessage(
                role="user",
                content=f"""
Mensaje original del usuario:
{original_user_message}

Herramienta ejecutada:
{tool_name}

Resultado real de la herramienta:
{tool_result}

Redacta la respuesta final para el usuario.
""".strip(),
            ),
        ]

        return await self.llm_provider.generate_response(final_answer_messages)

    def _build_tool_decision_catalog(
        self,
        tools: Sequence[MCPToolDefinition],
    ) -> str:
        """
        Catálogo completo para la decisión unificada.

        Incluye nombre, descripción e input_schema porque el LLM debe elegir la
        tool y generar sus argumentos en la misma inferencia.
        """

        catalog = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema or {},
            }
            for tool in tools
        ]

        return json.dumps(
            catalog,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _validate_tool_decision(
        self,
        decision: dict[str, Any],
        available_tools: Sequence[MCPToolDefinition],
    ) -> dict[str, Any]:
        """
        Nunca confía ciegamente en el nombre de tool escrito por el LLM.
        Solo permite ejecutar nombres descubiertos realmente por el MCP.
        """

        if decision.get("should_call_tool") is not True:
            return decision

        valid_tool_names = {tool.name for tool in available_tools}

        if decision.get("server") != "mcp_uyuni":
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "La selección de herramienta no pertenece al servidor MCP de Uyuni."
                ),
            }

        selected_tool = decision.get("tool")

        if not isinstance(selected_tool, str) or selected_tool not in valid_tool_names:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "clarification": (
                    "No he podido seleccionar de forma segura una herramienta de lectura válida de Uyuni."
                ),
            }

        return decision

    def _parse_json_from_text(self, text: str) -> dict[str, Any] | None:
        """
        Intenta extraer JSON aunque el modelo lo devuelva rodeado de texto
        o bloques Markdown.
        """

        clean_text = text.strip()

        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```json\s*", "", clean_text)
            clean_text = re.sub(r"^```\s*", "", clean_text)
            clean_text = re.sub(r"\s*```$", "", clean_text)

        try:
            return json.loads(clean_text)
        except json.JSONDecodeError:
            pass

        first_brace = clean_text.find("{")
        last_brace = clean_text.rfind("}")

        if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
            return None

        json_candidate = clean_text[first_brace : last_brace + 1]

        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            return None

    def _normalize_tool_decision(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Normaliza la decisión del LLM para que el resto del backend trabaje
        siempre con una estructura conocida.
        """

        should_call_tool = bool(data.get("should_call_tool", False))

        server = data.get("server")
        tool = data.get("tool")
        arguments = data.get("arguments", {})
        clarification = data.get("clarification")

        if not isinstance(arguments, dict):
            arguments = {}

        normalized = {
            "should_call_tool": should_call_tool,
            "server": server,
            "tool": tool,
            "arguments": arguments,
        }

        if isinstance(clarification, str):
            normalized["clarification"] = clarification

        return normalized

    def _convert_agui_message_to_chat_message(self, message: Any) -> ChatMessage:
        """
        Convierte un mensaje recibido desde AG-UI al formato interno ChatMessage.
        """

        role = getattr(message, "role", None)
        content = getattr(message, "content", None)

        if isinstance(message, dict):
            role = message.get("role", role)
            content = message.get("content", content)

        if role is None:
            role = "user"

        if content is None:
            content = ""

        if not isinstance(content, str):
            content = str(content)

        return ChatMessage(
            role=str(role),
            content=content,
        )

    def _get_last_user_message(self, messages: Sequence[ChatMessage]) -> str:
        """
        Obtiene el último mensaje enviado por el usuario.
        """

        for message in reversed(messages):
            if message.role.lower().strip() == "user":
                return message.content.strip()

        return ""