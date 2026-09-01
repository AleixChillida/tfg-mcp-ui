import asyncio
import json
import uuid
from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ag_ui.core import (
    RunAgentInput,
    EventType,
    RunStartedEvent,
    RunFinishedEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    CustomEvent,
)
from ag_ui.encoder import EventEncoder

from agents.chat_agent import AgentResponse, ChatAgent

load_dotenv(dotenv_path=Path(__file__).parent / ".env")


app = FastAPI()

chat_agent = ChatAgent()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Backend funcionando"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/agui")
async def agui_endpoint(input_data: RunAgentInput, request: Request):
    accept_header = request.headers.get("accept")
    encoder = EventEncoder(accept=accept_header)

    async def event_generator():
        message_id = str(uuid.uuid4())

        yield encoder.encode(
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=input_data.thread_id,
                run_id=input_data.run_id,
            )
        )

        yield encoder.encode(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=message_id,
                role="assistant",
            )
        )

        try:
            response = await chat_agent.generate_rich_response(
                input_data.messages,
                frontend_tools=input_data.tools,
            )
        except Exception as error:
            print("ERROR generando respuesta del asistente:", repr(error))

            response = AgentResponse(
                text=(
                    "Ha ocurrido un error generando la respuesta del asistente. "
                    f"Tipo: {type(error).__name__}. "
                    f"Detalle: {repr(error)}"
                )
            )

        for word in response.text.split(" "):
            yield encoder.encode(
                TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=message_id,
                    delta=word + " ",
                )
            )
            await asyncio.sleep(0.02)

        # CopilotKit Generative UI: el LLM ha elegido uno o varios componentes
        # registrados en el frontend mediante useComponent(). Emitimos llamadas
        # de tool AG-UI estándar para que CopilotKit las pinte dentro del mismo
        # mensaje del asistente. No existe un mapa tool MCP -> componente.
        for ui_call in response.ui_calls:
            tool_call_id = str(uuid.uuid4())

            yield encoder.encode(
                ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool_call_id,
                    tool_call_name=ui_call.name,
                    parent_message_id=message_id,
                )
            )
            yield encoder.encode(
                ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool_call_id,
                    delta=json.dumps(
                        ui_call.arguments,
                        ensure_ascii=False,
                        default=str,
                    ),
                )
            )
            yield encoder.encode(
                ToolCallEndEvent(
                    type=EventType.TOOL_CALL_END,
                    tool_call_id=tool_call_id,
                )
            )

        yield encoder.encode(
            TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=message_id,
            )
        )

        # Compatibilidad con el experimento AG-UI anterior. Esta variante
        # CopilotKit no genera estos visuales deterministas, pero conservar el
        # canal evita romper consumidores externos que aún lo utilicen.
        for visualization in response.visualizations:
            yield encoder.encode(
                CustomEvent(
                    type=EventType.CUSTOM,
                    name="ui.visualization",
                    value=visualization,
                )
            )

        yield encoder.encode(
            RunFinishedEvent(
                type=EventType.RUN_FINISHED,
                thread_id=input_data.thread_id,
                run_id=input_data.run_id,
            )
        )

    return StreamingResponse(
        event_generator(),
        media_type=encoder.get_content_type(),
    )