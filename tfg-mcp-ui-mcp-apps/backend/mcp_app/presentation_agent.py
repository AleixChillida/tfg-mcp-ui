from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from llm.base import ChatMessage, LLMProvider
from llm.factory import create_llm_provider


@dataclass(frozen=True)
class PresentationDecision:
    selected_view: str
    assistant_text: str
    reason: str = ""
    title: str | None = None
    mode: str = "llm"


class PresentationAgent:
    """Second LLM stage: choose the best safe MCP App view after the real tool result exists.

    The LLM chooses *how to present* the data, but never supplies chart values or HTML.
    All candidate values/rows/series are built from the real Uyuni MCP response first.
    """

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider or create_llm_provider()

    async def choose(
        self,
        *,
        user_request: str,
        tool_name: str,
        tool_result: str,
        candidate_payload: dict[str, Any],
    ) -> PresentationDecision:
        available_views = [
            str(view)
            for view in candidate_payload.get("views", [])
            if isinstance(view, str) and view
        ]
        if not available_views:
            available_views = ["raw"]

        digest = self._build_digest(candidate_payload)
        result_preview = self._truncate(tool_result, 9000)

        messages = [
            ChatMessage(
                role="system",
                content=f"""
Eres la capa de selección visual de una aplicación MCP Apps para un TFG.
Ya se ha ejecutado una herramienta REAL de Uyuni. Tu tarea es elegir la vista
que mejor comunica esos datos y redactar una respuesta breve para el usuario.

VISTAS PERMITIDAS EN ESTA RESPUESTA:
{json.dumps(available_views, ensure_ascii=False)}

REGLAS IMPORTANTES:
- Devuelve SOLO JSON válido, sin Markdown.
- selected_view DEBE ser exactamente una de las vistas permitidas.
- La selección visual la haces tú: NO hay un mapeo fijo tool→gráfico.
- Si el usuario pide explícitamente una vista y está permitida, priorízala.
- Si no pide una vista concreta, elige la más informativa para ESTA petición y ESTOS datos.
- No elijas un gráfico solo por ser vistoso: una tabla o detalle puede ser mejor.
- No inventes datos, valores, estados, fechas ni conclusiones.
- Los valores de gráficos ya están preparados y validados por el servidor; tú NO generas números.
- Si la única vista útil es empty/raw, úsala.
- assistant_text debe estar en el idioma del usuario y basarse únicamente en el resultado real.
- reason debe explicar en una frase por qué esa representación es apropiada; es metadata del experimento.
- title es opcional, corto y descriptivo.

FORMATO EXACTO:
{{
  "selected_view": "una_vista_permitida",
  "assistant_text": "respuesta breve y fiel",
  "reason": "motivo breve de la selección",
  "title": "título opcional"
}}
""".strip(),
            ),
            ChatMessage(
                role="user",
                content=f"""
PETICIÓN ORIGINAL:
{user_request}

HERRAMIENTA EJECUTADA:
{tool_name}

PERFIL DE DATOS Y VISTAS SEGURAS YA PREPARADAS:
{json.dumps(digest, ensure_ascii=False, separators=(",", ":"))}

RESULTADO REAL DE UYUNI (puede estar truncado solo para el prompt):
{result_preview}
""".strip(),
            ),
        ]

        raw = await self.llm_provider.generate_response(messages)
        parsed = self._parse_json(raw)
        if parsed is None:
            raise ValueError("La IA de presentación no ha devuelto JSON válido.")

        selected_view = parsed.get("selected_view")
        if not isinstance(selected_view, str) or selected_view not in available_views:
            raise ValueError(
                "La IA de presentación ha elegido una vista no permitida: "
                f"{selected_view!r}. Permitidas: {available_views}."
            )

        assistant_text = parsed.get("assistant_text")
        if not isinstance(assistant_text, str) or not assistant_text.strip():
            assistant_text = self._fallback_text(tool_result)

        reason = parsed.get("reason")
        if not isinstance(reason, str):
            reason = ""

        title = parsed.get("title")
        if not isinstance(title, str) or not title.strip():
            title = None

        return PresentationDecision(
            selected_view=selected_view,
            assistant_text=assistant_text.strip(),
            reason=self._truncate(reason.strip(), 300),
            title=self._truncate(title.strip(), 90) if title else None,
            mode="llm",
        )

    @staticmethod
    def _build_digest(payload: dict[str, Any]) -> dict[str, Any]:
        chart = payload.get("chart") if isinstance(payload.get("chart"), dict) else None
        digest: dict[str, Any] = {
            "available_views": payload.get("views", []),
            "row_count": payload.get("totalRows", 0),
            "empty": bool(payload.get("empty", False)),
            "columns": [
                column.get("label")
                for column in payload.get("columns", [])[:12]
                if isinstance(column, dict)
            ],
            "metric_labels": [
                item.get("label")
                for item in payload.get("metrics", [])[:8]
                if isinstance(item, dict)
            ],
            "has_detail": bool(payload.get("detail")),
            "timeline_items": len(payload.get("timeline", []) or []),
            "distribution_categories": len(payload.get("distribution", []) or []),
        }
        if chart:
            digest["chart_candidate"] = {
                "x_label": chart.get("xLabel"),
                "y_label": chart.get("yLabel"),
                "points": len(chart.get("values", []) or []),
                "derived": bool(chart.get("derived", False)),
                "supports_line": bool(chart.get("supportsLine", False)),
            }
        return digest

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        clean = text.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```json\s*", "", clean, flags=re.IGNORECASE)
            clean = re.sub(r"^```\s*", "", clean)
            clean = re.sub(r"\s*```$", "", clean)
        try:
            value = json.loads(clean)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass

        start, end = clean.find("{"), clean.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            value = json.loads(clean[start : end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _fallback_text(tool_result: str) -> str:
        clean = tool_result.strip()
        if not clean:
            return "La consulta a Uyuni ha finalizado sin contenido textual."
        return clean if len(clean) <= 1200 else clean[:1200] + "…"

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        return text if len(text) <= limit else text[:limit] + "…"
