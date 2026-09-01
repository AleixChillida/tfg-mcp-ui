import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Sequence
from llm.fake_provider import FakeLLMProvider

from llm.base import ChatMessage


class GeminiCLIProvider:
    """
    Proveedor LLM que usa Gemini CLI en modo no interactivo.

    En esta fase solo lo usamos como chatbot.
    No debe usar MCP ni herramientas.
    """

    def __init__(self) -> None:
        self.command = os.getenv(
            "GEMINI_CLI_COMMAND",
            "gemini.cmd" if os.name == "nt" else "gemini",
        )

        self.timeout_seconds = float(
            os.getenv("GEMINI_CLI_TIMEOUT_SECONDS", "60")
        )

        self.model = os.getenv("GEMINI_CLI_MODEL", "").strip()

        self.disable_extensions = (
            os.getenv("GEMINI_CLI_DISABLE_EXTENSIONS", "true")
            .lower()
            .strip()
            in {"1", "true", "yes", "on"}
        )

        self.cwd = os.getenv("GEMINI_CLI_CWD", ".").strip()

    async def generate_response(self, messages: Sequence[ChatMessage]) -> str:
        prompt = self._build_prompt(messages)
        executable = self._resolve_executable()

        command = [executable]

        if self.disable_extensions:
            command.extend(["-e", "none"])

        if self.model:
            command.extend(["--model", self.model])

        command.extend(["-p", prompt])

        print("Ejecutando Gemini CLI:", command)
        print("Gemini cwd:", self._resolve_cwd())
        print("Gemini timeout:", self.timeout_seconds)
        print("Gemini model:", self.model or "<default>")
        print("Gemini disable extensions:", self.disable_extensions)

        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"

        try:
            completed_process = await asyncio.to_thread(
                subprocess.run,
                command,
                cwd=self._resolve_cwd(),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as error:
            raise RuntimeError(
                "No se ha encontrado Gemini CLI. "
                "Comprueba que puedes ejecutar 'gemini.cmd' desde PowerShell "
                "o configura GEMINI_CLI_COMMAND con la ruta completa."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"Gemini CLI ha tardado más de {self.timeout_seconds} segundos. "
                "Esto significa que Gemini ha sido invocado desde el backend, "
                "pero no ha respondido a tiempo."
            ) from error

        stdout = completed_process.stdout or ""
        stderr = completed_process.stderr or ""

        print("Gemini returncode:", completed_process.returncode)
        print("Gemini stdout:", stdout)
        print("Gemini stderr:", stderr)

        if completed_process.returncode != 0:
            error_output = self._clean_error(stderr or stdout)

            if (
                "RESOURCE_EXHAUSTED" in error_output
                or "quota" in error_output.lower()
                or "429" in error_output
            ):
                raise RuntimeError(
                    "Gemini CLI ha fallado por cuota o rate limit. "
                    "El CLI devuelve 429 / RESOURCE_EXHAUSTED. "
                    "Prueba más tarde o usa LLM_PROVIDER=fake para seguir desarrollando sin coste. "
                    f"Detalle original: {error_output}"
                )

            if (
                "UNAVAILABLE" in error_output
                or "Service Unavailable" in error_output
                or "503" in error_output
                or "high demand" in error_output.lower()
            ):
                raise RuntimeError(
                    "Gemini CLI ha fallado porque el modelo está temporalmente no disponible "
                    "o con alta demanda. El CLI devuelve 503 / UNAVAILABLE. "
                    "Prueba más tarde o usa LLM_PROVIDER=fake para seguir desarrollando sin coste. "
                    f"Detalle original: {error_output}"
                )

            raise RuntimeError(
                "Gemini CLI ha devuelto un error. "
                f"Código de salida: {completed_process.returncode}. "
                f"Detalle: {error_output}"
            )

        response_text = self._clean_output(stdout)

        if not response_text:
            raise RuntimeError(
                "Gemini CLI no ha devuelto texto útil en stdout. "
                f"stderr: {self._clean_error(stderr)}"
            )

        return response_text

    def _resolve_executable(self) -> str:
        resolved = shutil.which(self.command)

        if resolved:
            return resolved

        return self.command

    def _resolve_cwd(self) -> str:
        cwd_path = Path(self.cwd)

        if cwd_path.is_absolute():
            return str(cwd_path)

        return str(Path.cwd() / cwd_path)

    def _build_prompt(self, messages: Sequence[ChatMessage]) -> str:
        last_user_message = self._get_last_user_message(messages)

        return (
            "Responde directamente al siguiente mensaje del usuario. "
            f"Usuario: {last_user_message}. "
            "Asistente:"
        )

        return f"Usuario: {last_user_message}\nAsistente:"

    def _get_last_user_message(self, messages: Sequence[ChatMessage]) -> str:
        for message in reversed(messages):
            if message.role.lower().strip() == "user":
                return message.content.strip()

        return ""

    def _clean_output(self, output: str) -> str:
        output = self._remove_ansi_codes(output)

        clean_lines: list[str] = []

        ignored_fragments = [
            "Ripgrep is not available",
            "MCP issues detected",
            "Run /mcp list for status",
        ]

        for line in output.splitlines():
            stripped_line = line.strip()

            if not stripped_line:
                continue

            if any(fragment in stripped_line for fragment in ignored_fragments):
                continue

            clean_lines.append(stripped_line)

        return "\n".join(clean_lines).strip()

    def _clean_error(self, output: str) -> str:
        output = self._remove_ansi_codes(output)
        output = output.strip()

        if len(output) > 1500:
            return output[:1500] + "..."

        return output

    def _remove_ansi_codes(self, text: str) -> str:
        ansi_escape_pattern = re.compile(
            r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
        )

        return ansi_escape_pattern.sub("", text)