import asyncio
import os
import re
import shutil
from typing import Sequence

from llm.base import ChatMessage


class GeminiCLIProvider:
    """
    Proveedor LLM que usa Gemini CLI en modo no interactivo.

    Este provider ejecuta un comando externo parecido a:

        gemini.cmd -p "prompt"

    En Windows normalmente usaremos gemini.cmd.
    En Linux/macOS normalmente sería gemini.

    Importante:
    - No mantiene una sesión interactiva abierta.
    - Cada mensaje lanza una llamada nueva al CLI.
    - Es más simple y fácil de entender para el TFG.
    - Más adelante se podría sustituir por Gemini API, OpenAI, Claude u Ollama.
    """

    def __init__(self) -> None:
        self.command = os.getenv(
            "GEMINI_CLI_COMMAND",
            "gemini.cmd" if os.name == "nt" else "gemini",
        )

        self.timeout_seconds = float(
            os.getenv("GEMINI_CLI_TIMEOUT_SECONDS", "90")
        )

        self.model = os.getenv("GEMINI_CLI_MODEL", "").strip()

    async def generate_response(self, messages: Sequence[ChatMessage]) -> str:
        prompt = self._build_prompt(messages)

        executable = self._resolve_executable()

        command = [executable]

        if self.model:
            command.extend(["--model", self.model])

        command.extend(["-p", prompt])

        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as error:
            raise RuntimeError(
                "No se ha encontrado Gemini CLI. "
                "Comprueba que puedes ejecutar 'gemini.cmd' desde PowerShell "
                "o configura GEMINI_CLI_COMMAND con la ruta correcta."
            ) from error

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as error:
            process.kill()
            await process.communicate()

            raise RuntimeError(
                f"Gemini CLI ha tardado más de {self.timeout_seconds} segundos. "
                "Puede estar colgado, no autenticado o intentando conectar con algún MCP."
            ) from error

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if process.returncode != 0:
            error_output = stderr.strip() or stdout.strip()

            raise RuntimeError(
                "Gemini CLI ha devuelto un error. "
                f"Código de salida: {process.returncode}. "
                f"Detalle: {error_output}"
            )

        response_text = self._clean_output(stdout)

        if not response_text:
            raise RuntimeError(
                "Gemini CLI no ha devuelto texto útil en stdout."
            )

        return response_text

    def _resolve_executable(self) -> str:
        """
        Busca el ejecutable en el PATH.

        En Windows normalmente resolverá:
            gemini.cmd

        También permite poner una ruta completa en GEMINI_CLI_COMMAND.
        """

        resolved = shutil.which(self.command)

        if resolved:
            return resolved

        return self.command

    def _build_prompt(self, messages: Sequence[ChatMessage]) -> str:
        """
        Construye un prompt simple a partir del historial de conversación.

        De momento no usamos herramientas MCP aquí.
        Solo queremos una respuesta conversacional.
        """

        recent_messages = list(messages)[-10:]

        conversation_lines: list[str] = []

        for message in recent_messages:
            role = self._normalize_role(message.role)
            content = message.content.strip()

            if not content:
                continue

            conversation_lines.append(f"{role}: {content}")

        conversation = "\n".join(conversation_lines)

        return f"""
Eres el asistente conversacional de un Trabajo de Fin de Grado sobre una interfaz web AG-UI para servidores MCP.

Tu tarea actual es responder mensajes normales del usuario.
Todavía no debes ejecutar herramientas MCP.
No debes modificar archivos.
No debes ejecutar comandos del sistema.
Responde de forma clara, breve y útil.
Responde en el mismo idioma que use el usuario.

Historial de conversación:
{conversation}

Respuesta del asistente:
""".strip()

    def _normalize_role(self, role: str) -> str:
        role = role.lower().strip()

        if role == "user":
            return "Usuario"

        if role == "assistant":
            return "Asistente"

        if role == "system":
            return "Sistema"

        return role.capitalize()

    def _clean_output(self, output: str) -> str:
        """
        Limpia la salida de Gemini CLI.

        A veces pueden aparecer códigos ANSI o mensajes relacionados con MCP.
        Para esta fase solo queremos texto final del asistente.
        """

        output = self._remove_ansi_codes(output)

        clean_lines: list[str] = []

        for line in output.splitlines():
            stripped_line = line.strip()

            if not stripped_line:
                continue

            if stripped_line.startswith("MCP STDERR"):
                continue

            clean_lines.append(stripped_line)

        return "\n".join(clean_lines).strip()

    def _remove_ansi_codes(self, text: str) -> str:
        ansi_escape_pattern = re.compile(
            r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
        )

        return ansi_escape_pattern.sub("", text)