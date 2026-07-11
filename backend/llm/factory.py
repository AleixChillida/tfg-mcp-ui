import os

from llm.base import LLMProvider
from llm.fake_provider import FakeLLMProvider
from llm.gemini_cli_provider import GeminiCLIProvider
from llm.ollama_provider import OllamaProvider


def create_llm_provider() -> LLMProvider:
    """
    Crea el proveedor LLM según configuración.

    LLM_PROVIDER=fake
        Usa un proveedor falso gratuito para pruebas.

    LLM_PROVIDER=gemini_cli
        Usa Gemini CLI en modo no interactivo.

    LLM_PROVIDER=ollama
        Usa Ollama en local.
    """

    provider_name = os.getenv("LLM_PROVIDER", "fake").lower().strip()

    if provider_name == "fake":
        return FakeLLMProvider()

    if provider_name == "gemini_cli":
        return GeminiCLIProvider()

    if provider_name == "ollama":
        return OllamaProvider()

    raise ValueError(
        f"Proveedor LLM no soportado: {provider_name}. "
        "Proveedores disponibles: fake, gemini_cli, ollama."
    )