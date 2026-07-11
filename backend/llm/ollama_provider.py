import os
from typing import Sequence

import httpx

from llm.base import ChatMessage


class OllamaProvider:
    """
    Proveedor LLM que usa Ollama en local.

    No usa cuotas.
    No usa API keys.
    No usa fallback.
    Si Ollama falla, lanza error.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv(
            "OLLAMA_BASE_URL",
            "http://localhost:11434",
        ).rstrip("/")

        self.model = os.getenv(
            "OLLAMA_MODEL",
            "qwen2.5:3b",
        ).strip()

        self.timeout_seconds = float(
            os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")
        )

    async def generate_response(self, messages: Sequence[ChatMessage]) -> str:
        ollama_messages = self._build_messages(messages)

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }

        print("Ejecutando Ollama")
        print("Ollama URL:", f"{self.base_url}/api/chat")
        print("Ollama model:", self.model)
        print("Ollama timeout:", self.timeout_seconds)

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )

            response.raise_for_status()

        except httpx.ConnectError as error:
            raise RuntimeError(
                "No se ha podido conectar con Ollama. "
                "Comprueba que Ollama está abierto y que funciona "
                "http://localhost:11434."
            ) from error

        except httpx.TimeoutException as error:
            raise RuntimeError(
                f"Ollama ha tardado más de {self.timeout_seconds} segundos en responder."
            ) from error

        except httpx.HTTPStatusError as error:
            raise RuntimeError(
                "Ollama ha devuelto un error HTTP. "
                f"Código: {error.response.status_code}. "
                f"Detalle: {error.response.text}"
            ) from error

        data = response.json()

        message = data.get("message", {})
        content = message.get("content", "")

        if not content or not isinstance(content, str):
            raise RuntimeError(
                "Ollama ha respondido, pero no ha devuelto contenido útil. "
                f"Respuesta completa: {data}"
            )

        return content.strip()

    def _build_messages(self, messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
        ollama_messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "Eres el asistente conversacional integrado en una interfaz web "
                    "llamada TFG MCP UI. "
                    "Responde en el mismo idioma que el usuario. "
                    "Sé claro, breve y natural. "
                    "No digas que eres Ollama ni menciones detalles internos del backend."
                ),
            }
        ]

        for message in messages:
            role = message.role.lower().strip()

            if role not in {"system", "user", "assistant"}:
                role = "user"

            content = message.content.strip()

            if not content:
                continue

            ollama_messages.append(
                {
                    "role": role,
                    "content": content,
                }
            )

        return ollama_messages