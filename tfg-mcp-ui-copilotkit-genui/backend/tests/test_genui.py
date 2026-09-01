import json
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from agents.chat_agent import ChatAgent
from llm.base import ChatMessage


class QueueLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    async def generate_response(self, messages):
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("No queda ninguna respuesta LLM preparada")
        return self.responses.pop(0)


class DummyUyuniClient:
    async def list_tools(self):
        return []


BAR_TOOL = {
    "name": "render_bar_chart",
    "description": "Gráfico de barras para comparar magnitudes entre categorías.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "subtitle": {"type": "string"},
            "data": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "value": {"type": "number"},
                    },
                    "required": ["label", "value"],
                },
            },
        },
        "required": ["title", "data"],
    },
}

TABLE_TOOL = {
    "name": "render_table",
    "description": "Tabla de filas y columnas.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "columns": {"type": "array"},
            "rows": {"type": "array"},
        },
        "required": ["title", "columns", "rows"],
    },
}


def make_agent(llm):
    return ChatAgent(llm_provider=llm, uyuni_client=DummyUyuniClient())


def test_genui_filters_only_render_components():
    agent = make_agent(QueueLLM([]))
    tools = [
        BAR_TOOL,
        {"name": "dangerous_frontend_action", "parameters": {}},
        TABLE_TOOL,
    ]

    selected = agent._get_genui_frontend_tools(tools)

    assert [tool["name"] for tool in selected] == [
        "render_bar_chart",
        "render_table",
    ]


def test_genui_rejects_unknown_component_and_unknown_arguments():
    agent = make_agent(QueueLLM([]))
    calls = agent._normalize_genui_calls(
        [
            {
                "name": "render_nonexistent",
                "arguments": {"title": "No"},
            },
            {
                "name": "render_bar_chart",
                "arguments": {
                    "title": "Estados",
                    "data": [{"label": "OK", "value": 2}],
                    "invented": "must disappear",
                },
            },
        ],
        [BAR_TOOL],
    )

    assert len(calls) == 1
    assert calls[0].name == "render_bar_chart"
    assert calls[0].arguments == {
        "title": "Estados",
        "data": [{"label": "OK", "value": 2}],
    }


def test_genui_rejects_component_missing_required_props():
    agent = make_agent(QueueLLM([]))

    calls = agent._normalize_genui_calls(
        [
            {
                "name": "render_bar_chart",
                "arguments": {"title": "Sin datos"},
            }
        ],
        [BAR_TOOL],
    )

    assert calls == []


def test_genui_limits_output_to_two_components():
    agent = make_agent(QueueLLM([]))
    raw = [
        {
            "name": "render_bar_chart",
            "arguments": {
                "title": f"Chart {index}",
                "data": [{"label": "A", "value": index}],
            },
        }
        for index in range(4)
    ]

    calls = agent._normalize_genui_calls(raw, [BAR_TOOL])

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_llm_can_choose_bar_chart_for_same_mcp_result():
    llm = QueueLLM(
        [
            json.dumps(
                {
                    "answer": "Hay dos sistemas.",
                    "ui_calls": [
                        {
                            "name": "render_bar_chart",
                            "arguments": {
                                "title": "Sistemas por estado",
                                "data": [
                                    {"label": "online", "value": 1},
                                    {"label": "offline", "value": 1},
                                ],
                            },
                        }
                    ],
                }
            )
        ]
    )
    agent = make_agent(llm)

    response = await agent._generate_final_answer_and_genui(
        original_user_message="Hazme un gráfico de barras con los sistemas.",
        tool_name="list_systems",
        tool_result='[{"name":"a"},{"name":"b"}]',
        structured_data=[
            {"name": "a", "status": "online"},
            {"name": "b", "status": "offline"},
        ],
        frontend_tools=[BAR_TOOL, TABLE_TOOL],
    )

    assert response.text == "Hay dos sistemas."
    assert [call.name for call in response.ui_calls] == ["render_bar_chart"]
    assert response.ui_calls[0].arguments["data"][0]["label"] == "online"

    system_prompt = llm.calls[0][0].content
    assert "NO existe ninguna correspondencia fija" in system_prompt
    assert "list_systems" not in system_prompt


@pytest.mark.asyncio
async def test_llm_can_choose_table_for_same_mcp_tool_on_another_prompt():
    llm = QueueLLM(
        [
            json.dumps(
                {
                    "answer": "Aquí tienes los sistemas.",
                    "ui_calls": [
                        {
                            "name": "render_table",
                            "arguments": {
                                "title": "Sistemas",
                                "columns": [
                                    {"key": "name", "label": "Nombre"},
                                ],
                                "rows": [{"name": "a"}, {"name": "b"}],
                            },
                        }
                    ],
                }
            )
        ]
    )
    agent = make_agent(llm)

    response = await agent._generate_final_answer_and_genui(
        original_user_message="Muéstrame esos sistemas en una tabla.",
        tool_name="list_systems",
        tool_result='[{"name":"a"},{"name":"b"}]',
        structured_data=[{"name": "a"}, {"name": "b"}],
        frontend_tools=[BAR_TOOL, TABLE_TOOL],
    )

    assert [call.name for call in response.ui_calls] == ["render_table"]


@pytest.mark.asyncio
async def test_no_frontend_components_falls_back_to_text_only():
    llm = QueueLLM(["Respuesta textual segura."])
    agent = make_agent(llm)

    response = await agent._generate_final_answer_and_genui(
        original_user_message="Lista los sistemas",
        tool_name="list_systems",
        tool_result="[]",
        structured_data=[],
        frontend_tools=[],
    )

    assert response.text == "Respuesta textual segura."
    assert response.ui_calls == []


class RecordingUyuniClient:
    def __init__(self):
        from mcp_clients.uyuni_client import MCPToolDefinition

        self.tools = [
            MCPToolDefinition(
                name="list_systems",
                description="List active systems",
                input_schema={"type": "object", "properties": {}},
            )
        ]
        self.calls = []

    async def list_tools(self):
        return list(self.tools)

    async def call_tool_with_data(self, tool_name, arguments):
        from mcp_clients.uyuni_client import MCPToolResult

        self.calls.append((tool_name, arguments))
        return MCPToolResult(
            text='[{"system_name":"srv-a","system_id":"1"}]',
            structured_data=[{"system_name": "srv-a", "system_id": "1"}],
        )


@pytest.mark.asyncio
async def test_full_uyuni_genui_flow_uses_two_llm_calls_and_no_fixed_mapping():
    llm = QueueLLM(
        [
            json.dumps(
                {
                    "should_call_tool": True,
                    "server": "mcp_uyuni",
                    "tool": "list_systems",
                    "arguments": {},
                }
            ),
            json.dumps(
                {
                    "answer": "Hay un sistema registrado.",
                    "ui_calls": [
                        {
                            "name": "render_table",
                            "arguments": {
                                "title": "Sistemas",
                                "columns": [
                                    {"key": "system_name", "label": "Sistema"},
                                    {"key": "system_id", "label": "ID"},
                                ],
                                "rows": [
                                    {"system_name": "srv-a", "system_id": "1"}
                                ],
                            },
                        }
                    ],
                }
            ),
        ]
    )
    uyuni = RecordingUyuniClient()
    agent = ChatAgent(llm_provider=llm, uyuni_client=uyuni)

    messages = [
        {"id": "u1", "role": "user", "content": "¿Qué sistemas tengo?"}
    ]
    response = await agent.generate_rich_response(
        messages,
        frontend_tools=[BAR_TOOL, TABLE_TOOL],
    )

    assert len(llm.calls) == 2
    assert uyuni.calls == [("list_systems", {})]
    assert response.text == "Hay un sistema registrado."
    assert [call.name for call in response.ui_calls] == ["render_table"]
    assert response.visualizations == []
