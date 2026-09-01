import asyncio
from typing import Sequence

from llm.base import ChatMessage


class FakeLLMProvider:
    """
    Proveedor LLM falso.

    No llama a ninguna IA real.
    Sirve para probar gratis que la arquitectura funciona.

    Más adelante lo sustituiremos por GeminiCLIProvider.
    """

    async def generate_response(self, messages: Sequence[ChatMessage]) -> str:
        # Simulamos un pequeño tiempo de respuesta para parecer más realista.
        await asyncio.sleep(0.2)

        last_user_message = self._get_last_user_message(messages)

        if not last_user_message:
            return (
                "Hola! Soy el proveedor LLM falso. "
                "No he recibido ningún mensaje de usuario."
            )

        normalized_message = last_user_message.lower().strip()

        if normalized_message in {"hola", "hello", "buenas", "bon dia", "bones"}:
            return (
                "Hola! Esta respuesta ya pasa por la capa LLM genérica del backend."
            )

        return (
            f'He recibido tu mensaje: "{last_user_message}". '
            "De momento responde el FakeLLMProvider, así podemos probar la "
            "arquitectura sin gastar créditos ni depender de servicios externos."
        )

    def _get_last_user_message(self, messages: Sequence[ChatMessage]) -> str:
        """
        Busca el último mensaje del usuario dentro del historial.
        """

        for message in reversed(messages):
            if message.role == "user":
                return message.content

        return ""