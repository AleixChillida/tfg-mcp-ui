from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from llm.base import ChatMessage
from mcp_app.presentation import apply_ai_selection, build_presentation
from mcp_app.presentation_agent import PresentationAgent


class StaticProvider:
    def __init__(self, response: dict):
        self.response = response
        self.calls: list[Sequence[ChatMessage]] = []

    async def generate_response(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(messages)
        return json.dumps(self.response, ensure_ascii=False)


def _candidate_payload() -> dict:
    systems = {
        "systems": [
            {"name": "client1", "status": "online", "pending_updates": 2},
            {"name": "client2", "status": "offline", "pending_updates": 7},
        ]
    }
    return build_presentation(
        tool_name="list_systems",
        tool_result=json.dumps(systems),
        structured_data=systems,
        requested_view="auto",
    )


def test_same_mcp_data_can_be_selected_as_table_by_llm() -> None:
    provider = StaticProvider({
        "selected_view": "table",
        "assistant_text": "Hay dos sistemas registrados.",
        "reason": "La tabla permite comparar los campos de ambos sistemas.",
        "title": "Sistemas registrados",
    })
    agent = PresentationAgent(provider)
    payload = _candidate_payload()

    decision = asyncio.run(agent.choose(
        user_request="Lista los sistemas registrados",
        tool_name="list_systems",
        tool_result='{"systems":[]}',
        candidate_payload=payload,
    ))
    selected = apply_ai_selection(
        payload,
        selected_view=decision.selected_view,
        reason=decision.reason,
        title=decision.title,
    )

    assert selected["initialView"] == "table"
    assert selected["presentationSelection"]["mode"] == "llm"


def test_same_mcp_data_can_be_selected_as_bar_by_llm() -> None:
    provider = StaticProvider({
        "selected_view": "bar",
        "assistant_text": "La comparación visual muestra las actualizaciones pendientes.",
        "reason": "Las barras hacen visible la diferencia entre sistemas.",
        "title": "Actualizaciones pendientes",
    })
    agent = PresentationAgent(provider)
    payload = _candidate_payload()

    decision = asyncio.run(agent.choose(
        user_request="Compáralos visualmente y elige el gráfico que veas mejor",
        tool_name="list_systems",
        tool_result='{"systems":[]}',
        candidate_payload=payload,
    ))
    selected = apply_ai_selection(payload, selected_view=decision.selected_view)

    assert selected["initialView"] == "bar"
    assert selected["chart"]["metricKey"] == "pending_updates"


def test_llm_cannot_select_a_view_that_server_did_not_prepare() -> None:
    provider = StaticProvider({
        "selected_view": "3d-globe",
        "assistant_text": "Inventado",
        "reason": "",
        "title": "",
    })
    agent = PresentationAgent(provider)

    try:
        asyncio.run(agent.choose(
            user_request="Lista sistemas",
            tool_name="list_systems",
            tool_result="{}",
            candidate_payload=_candidate_payload(),
        ))
    except ValueError as error:
        assert "vista no permitida" in str(error)
    else:
        raise AssertionError("La selección inválida del LLM debería rechazarse.")


def test_prompt_explicitly_tells_llm_that_visual_selection_is_its_job() -> None:
    provider = StaticProvider({
        "selected_view": "table",
        "assistant_text": "OK",
        "reason": "OK",
        "title": "OK",
    })
    agent = PresentationAgent(provider)
    asyncio.run(agent.choose(
        user_request="elige la mejor vista",
        tool_name="list_systems",
        tool_result="{}",
        candidate_payload=_candidate_payload(),
    ))

    system_prompt = provider.calls[0][0].content
    assert "NO hay un mapeo fijo tool→gráfico" in system_prompt
    assert "selected_view" in system_prompt
