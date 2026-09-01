from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_mcp_app_contract_is_linked_tool_plus_ui_resource() -> None:
    server = (ROOT / "backend" / "mcp_app" / "server.py").read_text(encoding="utf-8")
    view = (ROOT / "backend" / "mcp_app" / "view.html").read_text(encoding="utf-8")

    assert 'VIEW_URI = "ui://uyuni-tfg/dashboard.html"' in server
    assert "@mcp.tool(" in server
    assert "AppConfig(resource_uri=VIEW_URI)" in server
    assert "@mcp.resource(" in server
    assert "structured_content=presentation" in server
    assert "PresentationAgent" in server
    assert "apply_ai_selection" in server
    assert "presentation_llm_ms" in server
    assert "@modelcontextprotocol/ext-apps@1.7.5/app-with-deps" in view
    assert "app.ontoolresult" in view
    assert "await app.connect()" in view
    assert "app.onteardown" in view


def test_web_host_uses_double_iframe_sandbox_proxy_pattern() -> None:
    frame = (ROOT / "frontend" / "src" / "mcp" / "McpAppFrame.tsx").read_text(encoding="utf-8")
    sandbox = (ROOT / "backend" / "mcp_app" / "sandbox.html").read_text(encoding="utf-8")

    assert 'sandbox="allow-scripts allow-same-origin allow-forms"' in frame
    assert "sandbox.html" in frame
    assert "ui/notifications/sandbox-proxy-ready" in frame
    assert "sendSandboxResourceReady" in frame
    assert "AppBridge" in frame
    assert "PostMessageTransport" in frame
    assert "teardownResource" in frame

    assert 'document.createElement("iframe")' in sandbox
    assert "ui/notifications/sandbox-resource-ready" in sandbox
    assert "window.parent.postMessage" in sandbox
    assert "inner.contentWindow" in sandbox


def test_router_does_not_preselect_visualization() -> None:
    router = (ROOT / "backend" / "agents" / "router_agent.py").read_text(encoding="utf-8")
    assert "detect_requested_view" not in router
    assert "NO decidas tabla/gráfico/timeline" in router


def test_upstream_write_tools_remain_blocked() -> None:
    client = (ROOT / "backend" / "mcp_clients" / "uyuni_client.py").read_text(encoding="utf-8")
    for dangerous_prefix in ("schedule_", "add_", "remove_", "cancel_", "create_", "delete_"):
        assert f'"{dangerous_prefix}"' in client
    assert "_is_read_only_tool_name" in client
