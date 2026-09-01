import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware as StarletteCORSMiddleware

from agents.router_agent import RouterAgent
from llm.base import ChatMessage
from mcp_app.server import mcp as mcp_apps_server
from mcp_app.sandbox import sandbox_response


class MessageIn(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class RouteRequest(BaseModel):
    messages: list[MessageIn] = Field(default_factory=list)


_router_agent: RouterAgent | None = None


def get_router_agent() -> RouterAgent:
    global _router_agent
    if _router_agent is None:
        _router_agent = RouterAgent()
    return _router_agent


# Browser MCP client: CORS must expose mcp-session-id.
mcp_middleware = [
    Middleware(
        StarletteCORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "mcp-protocol-version",
            "mcp-session-id",
            "Authorization",
            "Content-Type",
        ],
        expose_headers=["mcp-session-id"],
    )
]

# path="/" because this ASGI app is mounted at /mcp-app below.
mcp_http_app = mcp_apps_server.http_app(
    path="/",
    middleware=mcp_middleware,
    host_origin_protection=True,
    allowed_hosts=["127.0.0.1:8000", "localhost:8000"],
    allowed_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
)

app = FastAPI(
    title="TFG MCP UI — MCP Apps",
    lifespan=mcp_http_app.lifespan,
)

api = FastAPI()
api.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "TFG MCP Apps backend funcionando",
        "mcp_endpoint": "/mcp-app/",
        "sandbox_proxy": "/sandbox.html",
        "visual_selection": "LLM after real Uyuni MCP result",
    }


@app.get("/sandbox.html")
def sandbox(request: Request):
    # Outer sandbox proxy is served from the backend origin (8000), different
    # from the Vite host origin (5173), following the MCP Apps web-host pattern.
    return sandbox_response(request)


@api.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "variant": "mcp-apps",
        "presentation_selection": "llm",
    }


@api.post("/route")
async def route(request: RouteRequest) -> dict:
    started = time.perf_counter()
    messages = [ChatMessage(role=m.role, content=m.content) for m in request.messages]
    agent = get_router_agent()

    try:
        decision = await agent.route(messages)
        payload = decision.to_dict()

        if decision.kind == "text":
            payload["text"] = await agent.general_response(messages)
        elif decision.kind == "clarification":
            payload["text"] = decision.clarification or "Necesito un dato adicional para continuar."

        payload["route_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return payload
    except Exception as error:
        return {
            "kind": "error",
            "text": (
                "Ha ocurrido un error preparando la consulta. "
                f"Tipo: {type(error).__name__}. Detalle: {error}"
            ),
            "route_ms": round((time.perf_counter() - started) * 1000, 2),
        }


app.mount("/api", api)
app.mount("/mcp-app", mcp_http_app)
