from typing import Any, Sequence

from llm.base import ChatMessage, LLMProvider
from llm.factory import create_llm_provider


class ChatAgent:
    """
    Agente conversacional principal del backend.

    Su responsabilidad es:
    - recibir mensajes en formato AG-UI
    - convertirlos a un formato interno simple
    - llamar al proveedor LLM configurado
    - devolver la respuesta textual

    Este agente no sabe si detrás hay Gemini, OpenAI, Claude u otro proveedor.
    """

    def __init__(self, llm_provider: LLMProvider | None = None):
        self.llm_provider = llm_provider or create_llm_provider()

    async def generate_response(self, agui_messages: Sequence[Any]) -> str:
        """
        Genera una respuesta a partir de los mensajes recibidos desde AG-UI.
        """

        chat_messages = [
            self._convert_agui_message_to_chat_message(message)
            for message in agui_messages
        ]

        return await self.llm_provider.generate_response(chat_messages)

    def _convert_agui_message_to_chat_message(self, message: Any) -> ChatMessage:
        """
        Convierte un mensaje de AG-UI a nuestro formato interno ChatMessage.

        Lo hacemos así para no acoplar los providers LLM a AG-UI.
        """

        role = getattr(message, "role", None)
        content = getattr(message, "content", None)

        # Por si en algún test o caso concreto llega como diccionario.
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