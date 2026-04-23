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
)
from ag_ui.encoder import EventEncoder

import asyncio
import uuid

app = FastAPI()

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

    # Para este MVP solo usamos el último mensaje del usuario
    user_text = ""
    if input_data.messages:
        last_message = input_data.messages[-1]
        content = getattr(last_message, "content", "")
        user_text = content if isinstance(content, str) else str(content)

    response_text = f"Respuesta AG-UI simulada: has escrito '{user_text}'."

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

        for word in response_text.split(" "):
            yield encoder.encode(
                TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT,
                    message_id=message_id,
                    delta=word + " ",
                )
            )
            await asyncio.sleep(0.05)

        yield encoder.encode(
            TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=message_id,
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