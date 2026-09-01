import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main as main_module
from agents.chat_agent import AgentResponse, UIComponentCall

client = TestClient(main_module.app)


class StubChatAgent:
    """Agente determinista para probar únicamente el transporte AG-UI."""

    def __init__(self, visualizations=None, ui_calls=None):
        self.visualizations = visualizations or []
        self.ui_calls = ui_calls or []
        self.last_frontend_tools = None

    async def generate_rich_response(self, messages, frontend_tools=None):
        self.last_frontend_tools = frontend_tools
        last_user_message = ""
        for message in reversed(messages):
            role = getattr(message, "role", None)
            content = getattr(message, "content", None)
            if isinstance(message, dict):
                role = message.get("role", role)
                content = message.get("content", content)
            if role == "user":
                last_user_message = str(content or "")
                break

        return AgentResponse(
            text=f"Respuesta AG-UI simulada: '{last_user_message}'.",
            ui_calls=self.ui_calls,
            visualizations=self.visualizations,
        )


@pytest.fixture(autouse=True)
def stub_chat_agent(monkeypatch):
    monkeypatch.setattr(main_module, "chat_agent", StubChatAgent())


def build_payload(messages, tools=None):
    return {
        "thread_id": "test-thread",
        "run_id": "test-run",
        "messages": messages,
        "state": {},
        "tools": tools or [],
        "context": [],
        "forwardedProps": {},
    }


def test_root_endpoint_returns_ok_message():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["message"] == "Backend funcionando"


def test_health_endpoint_returns_ok_status():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_agui_endpoint_returns_streaming_response():
    payload = build_payload(
        [
            {
                "id": "msg-1",
                "role": "user",
                "content": "Hola backend",
            }
        ]
    )

    response = client.post(
        "/agui",
        json=payload,
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert '"type":"RUN_STARTED"' in response.text
    assert '"type":"TEXT_MESSAGE_START"' in response.text
    assert '"type":"TEXT_MESSAGE_CONTENT"' in response.text
    assert '"delta":"Respuesta "' in response.text
    assert '"delta":"AG-UI "' in response.text
    assert '"delta":"simulada: "' in response.text
    assert '"delta":"\'Hola "' in response.text
    assert '"delta":"backend\'. "' in response.text
    assert '"type":"TEXT_MESSAGE_END"' in response.text
    assert '"type":"RUN_FINISHED"' in response.text


def test_agui_endpoint_handles_empty_messages():
    payload = build_payload([])

    response = client.post(
        "/agui",
        json=payload,
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert '"type":"RUN_STARTED"' in response.text
    assert '"type":"TEXT_MESSAGE_CONTENT"' in response.text
    assert '"delta":"Respuesta "' in response.text
    assert '"delta":"AG-UI "' in response.text
    assert '"delta":"simulada: "' in response.text
    assert '"type":"RUN_FINISHED"' in response.text


def test_agui_endpoint_uses_last_user_message():
    payload = build_payload(
        [
            {"id": "msg-1", "role": "user", "content": "Primer mensaje"},
            {"id": "msg-2", "role": "assistant", "content": "Respuesta anterior"},
            {"id": "msg-3", "role": "user", "content": "Último mensaje"},
        ]
    )

    response = client.post(
        "/agui",
        json=payload,
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert '"delta":"\'Último "' in response.text
    assert '"delta":"mensaje\'. "' in response.text


def test_agui_endpoint_forwards_copilotkit_frontend_tools(monkeypatch):
    agent = StubChatAgent()
    monkeypatch.setattr(main_module, "chat_agent", agent)

    tools = [
        {
            "name": "render_bar_chart",
            "description": "Renderiza un gráfico de barras",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
        }
    ]

    response = client.post(
        "/agui",
        json=build_payload(
            [{"id": "msg-1", "role": "user", "content": "Haz un gráfico"}],
            tools=tools,
        ),
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert agent.last_frontend_tools is not None
    assert len(agent.last_frontend_tools) == 1
    assert agent.last_frontend_tools[0].name == "render_bar_chart"


def test_agui_endpoint_emits_copilotkit_tool_call_events(monkeypatch):
    ui_call = UIComponentCall(
        name="render_bar_chart",
        arguments={
            "title": "Acciones por estado",
            "data": [
                {"label": "Completed", "value": 3},
                {"label": "Pending", "value": 1},
            ],
        },
    )
    monkeypatch.setattr(
        main_module,
        "chat_agent",
        StubChatAgent(ui_calls=[ui_call]),
    )

    response = client.post(
        "/agui",
        json=build_payload(
            [{"id": "msg-1", "role": "user", "content": "Haz barras"}]
        ),
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert '"type":"TOOL_CALL_START"' in response.text
    assert '"toolCallName":"render_bar_chart"' in response.text
    assert '"type":"TOOL_CALL_ARGS"' in response.text
    assert "Acciones por estado" in response.text
    assert '"type":"TOOL_CALL_END"' in response.text


def test_agui_endpoint_keeps_legacy_custom_visualization_channel(monkeypatch):
    visual = {
        "type": "table",
        "title": "List systems",
        "columns": [{"key": "hostname", "label": "Hostname"}],
        "rows": [{"hostname": "srv-a"}],
        "truncated": False,
        "total_rows": 1,
    }
    monkeypatch.setattr(
        main_module,
        "chat_agent",
        StubChatAgent(visualizations=[visual]),
    )

    response = client.post(
        "/agui",
        json=build_payload(
            [{"id": "msg-1", "role": "user", "content": "Lista sistemas"}]
        ),
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert '"type":"CUSTOM"' in response.text
    assert '"name":"ui.visualization"' in response.text
    assert '"type":"table"' in response.text
    assert '"hostname":"srv-a"' in response.text
