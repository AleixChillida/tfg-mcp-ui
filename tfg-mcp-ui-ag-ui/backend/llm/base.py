from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class LLMProvider(Protocol):
    async def generate_response(self, messages: Sequence[ChatMessage]) -> str:
        ...