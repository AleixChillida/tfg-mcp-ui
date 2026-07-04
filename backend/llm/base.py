from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class ChatMessage:
    """
    Representación interna y simple de un mensaje de chat.

    No usamos directamente los mensajes de AG-UI dentro de los providers
    porque queremos desacoplar el protocolo AG-UI del proveedor LLM.

    Así, Gemini, OpenAI, Claude u Ollama recibirán siempre el mismo formato.
    """

    role: str
    content: str


class LLMProvider(Protocol):
    """
    Interfaz común para cualquier proveedor de LLM.

    Cualquier implementación futura debe tener este método:
    - FakeLLMProvider
    - GeminiCLIProvider
    - OpenAIProvider
    - AnthropicProvider
    - OllamaProvider
    """

    async def generate_response(self, messages: Sequence[ChatMessage]) -> str:
        """
        Recibe el historial de mensajes y devuelve una respuesta de texto.
        """
