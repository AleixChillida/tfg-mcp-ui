import os
import time
from typing import Sequence

import httpx

from llm.base import ChatMessage


class OpenRouterProvider:
    """
    Proveedor LLM que usa OpenRouter mediante su API compatible con OpenAI.

    La API key, el modelo y el timeout se configuran mediante variables
    de entorno para poder cambiar de modelo sin modificar código.
    """

    def __init__(self) -> None:
        self.api_key = os.getenv(
            "OPENROUTER_API_KEY",
            "",
        ).strip()

        self.base_url = os.getenv(
            "OPENROUTER_BASE_URL",
            "https://openrouter.ai/api/v1",
        ).rstrip("/")

        self.model = os.getenv(
            "OPENROUTER_MODEL",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
        ).strip()

        self.timeout_seconds = float(
            os.getenv("OPENROUTER_TIMEOUT_SECONDS", "120")
        )

        self.site_url = os.getenv(
            "OPENROUTER_SITE_URL",
            "",
        ).strip()

        self.app_name = os.getenv(
            "OPENROUTER_APP_NAME",
            "TFG MCP UI",
        ).strip()

        if not self.api_key:
            raise RuntimeError(
                "Falta OPENROUTER_API_KEY en backend/.env."
            )

        if not self.model:
            raise RuntimeError(
                "Falta OPENROUTER_MODEL en backend/.env."
            )

    async def generate_response(
        self,
        messages: Sequence[ChatMessage],
    ) -> str:
        openrouter_messages = self._build_messages(messages)

        payload = {
            "model": self.model,
            "messages": openrouter_messages,
            "stream": False,
            "usage": {
                "include": True,
            },
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Cabeceras opcionales de OpenRouter.
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url

        if self.app_name:
            headers["X-Title"] = self.app_name

        print("Ejecutando OpenRouter")
        print("OpenRouter URL:", f"{self.base_url}/chat/completions")
        print("OpenRouter model:", self.model)
        print("OpenRouter timeout:", self.timeout_seconds)

        started_at = time.perf_counter()

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )

            response.raise_for_status()

        except httpx.ConnectError as error:
            raise RuntimeError(
                "No se ha podido conectar con OpenRouter. "
                "Comprueba tu conexión a Internet."
            ) from error

        except httpx.TimeoutException as error:
            raise RuntimeError(
                "OpenRouter ha tardado más de "
                f"{self.timeout_seconds} segundos en responder."
            ) from error

        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            detail = error.response.text

            if status_code == 401:
                raise RuntimeError(
                    "OpenRouter ha rechazado la API key. "
                    "Comprueba OPENROUTER_API_KEY."
                ) from error

            if status_code == 402:
                raise RuntimeError(
                    "OpenRouter indica que no hay crédito suficiente "
                    "para ejecutar esta petición."
                ) from error

            if status_code == 429:
                raise RuntimeError(
                    "OpenRouter ha aplicado un rate limit (HTTP 429). "
                    "Prueba de nuevo más tarde."
                ) from error

            raise RuntimeError(
                "OpenRouter ha devuelto un error HTTP. "
                f"Código: {status_code}. "
                f"Detalle: {detail}"
            ) from error

        elapsed_seconds = time.perf_counter() - started_at

        data = response.json()

        choices = data.get("choices", [])

        if not choices:
            raise RuntimeError(
                "OpenRouter ha respondido, pero no contiene choices. "
                f"Respuesta completa: {data}"
            )

        message = choices[0].get("message", {})
        content = message.get("content", "")

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(
                "OpenRouter ha respondido, pero no ha devuelto "
                f"contenido textual útil. Respuesta completa: {data}"
            )

        usage = data.get("usage", {})

        print(
            "OpenRouter elapsed:",
            f"{elapsed_seconds:.2f}s",
        )

        if usage:
            print(
                "OpenRouter usage:",
                {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "cost": usage.get("cost"),
                },
            )

        return content.strip()

    def _build_messages(
        self,
        messages: Sequence[ChatMessage],
    ) -> list[dict[str, str]]:
        openrouter_messages: list[dict[str, str]] = []

        for message in messages:
            role = message.role.lower().strip()

            if role not in {"system", "user", "assistant"}:
                role = "user"

            content = message.content.strip()

            if not content:
                continue

            openrouter_messages.append(
                {
                    "role": role,
                    "content": content,
                }
            )

        return openrouter_messages