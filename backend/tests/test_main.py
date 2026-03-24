import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from main import app

client = TestClient(app)


def build_payload(messages):
    return {
        "thread_id": "test-thread",
        "run_id": "test-run",
        "messages": messages,
        "state": {},
        "tools": [],
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
    assert '"delta":"\\\'Hola "' in response.text or '"delta":"\'Hola "' in response.text
    assert '"delta":"backend\\\'. "' in response.text or '"delta":"backend\'. "' in response.text
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
    assert '"delta":"\\\'Último "' in response.text or '"delta":"\'Último "' in response.text
    assert '"delta":"mensaje\\\'. "' in response.text or '"delta":"mensaje\'. "' in response.text