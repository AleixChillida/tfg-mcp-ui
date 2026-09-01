import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, ResourceCSP
from fastmcp.tools import ToolResult

from mcp_app.presentation import apply_ai_selection, build_presentation
from mcp_app.presentation_agent import PresentationAgent
from mcp_clients.uyuni_client import UyuniMCPClient

VIEW_URI = "ui://uyuni-tfg/dashboard.html"
VIEW_PATH = Path(__file__).with_name("view.html")

mcp = FastMCP("TFG Uyuni MCP Apps Adapter")
_upstream = UyuniMCPClient()
_presenter: PresentationAgent | None = None


def get_presenter() -> PresentationAgent:
    global _presenter
    if _presenter is None:
        _presenter = PresentationAgent()
    return _presenter


@mcp.tool(
    app=AppConfig(resource_uri=VIEW_URI),
)
async def query_uyuni(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    user_request: str = "",
) -> ToolResult:
    """Execute one read-only Uyuni MCP tool and return an AI-selected MCP App view.

    The upstream Uyuni MCP server is the source of truth. After its real result
    is received, a second LLM stage chooses one of the safe visual candidates
    prepared from that result. The LLM never supplies chart numbers or HTML.
    """

    started = time.perf_counter()

    upstream_started = time.perf_counter()
    result = await _upstream.call_tool_with_data(tool_name, arguments or {})
    upstream_ms = round((time.perf_counter() - upstream_started) * 1000, 2)

    # Build truthful visual candidates from the actual MCP data. "auto" here is
    # only a safe fallback; the normal final choice is made by PresentationAgent.
    presentation = build_presentation(
        tool_name=tool_name,
        tool_result=result.text,
        structured_data=result.structured_data,
        requested_view="auto",
    )

    selection_started = time.perf_counter()
    selection_mode = "llm"
    presentation_error: str | None = None
    try:
        decision = await get_presenter().choose(
            user_request=user_request,
            tool_name=tool_name,
            tool_result=result.text,
            candidate_payload=presentation,
        )
        presentation = apply_ai_selection(
            presentation,
            selected_view=decision.selected_view,
            reason=decision.reason,
            title=decision.title,
            mode=decision.mode,
        )
        assistant_text = decision.assistant_text
    except Exception as error:
        # A free model/provider can occasionally fail. Keep the MCP result usable
        # and mark the deterministic fallback explicitly for the TFG benchmark.
        selection_mode = "fallback"
        presentation_error = f"{type(error).__name__}: {error}"
        fallback_view = str(presentation.get("initialView") or "raw")
        presentation = apply_ai_selection(
            presentation,
            selected_view=fallback_view,
            reason="Fallback seguro porque la selección LLM no produjo una decisión válida.",
            mode="fallback",
        )
        assistant_text = result.text.strip() or "La consulta a Uyuni ha finalizado sin contenido textual."

    presentation_llm_ms = round((time.perf_counter() - selection_started) * 1000, 2)
    total_ms = round((time.perf_counter() - started) * 1000, 2)

    presentation["timing"] = {
        "upstreamMcpMs": upstream_ms,
        "presentationLlmMs": presentation_llm_ms,
        "adapterTotalMs": total_ms,
    }
    presentation["userRequest"] = user_request[:500]
    presentation["selectionMode"] = selection_mode
    if presentation_error:
        presentation["presentationError"] = presentation_error[:800]

    return ToolResult(
        content=assistant_text,
        structured_content=presentation,
        meta={
            "tfg": {
                "upstream_mcp_ms": upstream_ms,
                "presentation_llm_ms": presentation_llm_ms,
                "adapter_total_ms": total_ms,
                "presentation_selection": selection_mode,
                "selected_view": presentation.get("initialView"),
            }
        },
    )


@mcp.resource(
    VIEW_URI,
    app=AppConfig(
        csp=ResourceCSP(
            resource_domains=["https://unpkg.com"],
        ),
        prefers_border=True,
    ),
)
def uyuni_dashboard_view() -> str:
    """MCP Apps HTML resource served by the MCP server itself."""

    return VIEW_PATH.read_text(encoding="utf-8")
