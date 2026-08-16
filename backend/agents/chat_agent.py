import json
import re
from typing import Any, Sequence

from llm.base import ChatMessage, LLMProvider
from llm.factory import create_llm_provider
from mcp_clients.uyuni_client import UyuniMCPClient


class ChatAgent:
    """
    Agente conversacional principal del backend.

    Flujo:
    1. Recibe mensajes desde AG-UI.
    2. Convierte los mensajes a ChatMessage.
    3. Pregunta al LLM local si hace falta usar una herramienta MCP.
    4. Si el LLM pide una tool permitida, el backend la ejecuta.
    5. El resultado real de la tool se pasa otra vez al LLM para redactar la respuesta final.
    6. Si no hace falta tool, responde normalmente con el LLM.
    """

    def __init__(self, llm_provider: LLMProvider | None = None):
        self.llm_provider = llm_provider or create_llm_provider()
        self.uyuni_client = UyuniMCPClient()

    async def generate_response(self, agui_messages: Sequence[Any]) -> str:
        """
        Punto de entrada principal del agente.
        Recibe mensajes AG-UI y devuelve una respuesta textual.
        """

        chat_messages = [
            self._convert_agui_message_to_chat_message(message)
            for message in agui_messages
        ]

        last_user_message = self._get_last_user_message(chat_messages)

        tool_decision = await self._decide_tool(last_user_message)

        print("Tool decision:", tool_decision)

        if tool_decision.get("should_call_tool") is True:
            return await self._execute_tool_decision(
                original_user_message=last_user_message,
                tool_decision=tool_decision,
            )

        return await self.llm_provider.generate_response(chat_messages)

    async def _decide_tool(self, user_message: str) -> dict[str, Any]:
        """
        Usa el LLM local como router de herramientas.

        El LLM no ejecuta nada.
        Solo devuelve una decisión en JSON.
        """

        router_messages = [
            ChatMessage(
                role="system",
                content="""
Eres un router de herramientas MCP.

Tu única tarea es decidir si el mensaje del usuario necesita llamar a una herramienta.

Herramientas disponibles:

1. Servidor: mcp_uyuni
   Tool: list_systems
   Descripción: lista los sistemas registrados en Uyuni.
   Argumentos: {}

Reglas:
- Devuelve exclusivamente JSON válido.
- No escribas explicaciones.
- No uses Markdown.
- No inventes herramientas.
- Si el usuario pide listar sistemas de Uyuni, usar mcp_uyuni/list_systems.
- Si el usuario menciona list_systems, usar mcp_uyuni/list_systems.
- Si el usuario dice "usa list_systems de mcp_uyuni", usar mcp_uyuni/list_systems.
- Si no hace falta herramienta, should_call_tool debe ser false.

Formato obligatorio si hay que usar herramienta:
{
  "should_call_tool": true,
  "server": "mcp_uyuni",
  "tool": "list_systems",
  "arguments": {}
}

Formato obligatorio si no hay que usar herramienta:
{
  "should_call_tool": false,
  "server": null,
  "tool": null,
  "arguments": {}
}
""".strip(),
            ),
            ChatMessage(
                role="user",
                content=user_message,
            ),
        ]

        raw_response = await self.llm_provider.generate_response(router_messages)

        print("Ollama router raw response:", raw_response)

        parsed = self._parse_json_from_text(raw_response)

        if parsed is None:
            return {
                "should_call_tool": False,
                "server": None,
                "tool": None,
                "arguments": {},
                "reason": "invalid_json_from_router",
                "raw_response": raw_response,
            }

        return self._normalize_tool_decision(parsed)

    async def _execute_tool_decision(
        self,
        original_user_message: str,
        tool_decision: dict[str, Any],
    ) -> str:
        """
        Ejecuta una herramienta MCP si la decisión del LLM es válida.
        """

        server = tool_decision.get("server")
        tool = tool_decision.get("tool")
        arguments = tool_decision.get("arguments", {})

        if server != "mcp_uyuni":
            return (
                "El modelo ha solicitado una herramienta de un servidor MCP "
                f"no soportado todavía: {server}"
            )

        if tool != "list_systems":
            return (
                "El modelo ha solicitado una herramienta MCP que todavía no está "
                f"integrada en el backend: {tool}"
            )

        tool_result = await self.uyuni_client.call_tool(
            "list_systems",
            arguments,
        )

        return await self._generate_final_answer_from_tool_result(
            original_user_message=original_user_message,
            tool_name="list_systems",
            tool_result=tool_result,
        )

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

        if not isinstance(arguments, dict):
            arguments = {}

        return {
            "should_call_tool": should_call_tool,
            "server": server,
            "tool": tool,
            "arguments": arguments,
        }

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