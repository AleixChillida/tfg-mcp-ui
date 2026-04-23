import { useMemo, useState } from "react";
import { HttpAgent } from "@ag-ui/client";
import "./App.css";

type UiMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

function App() {
  const [uiMessages, setUiMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const agent = useMemo(
    () =>
      new HttpAgent({
        url: import.meta.env.VITE_AGUI_URL ?? "http://127.0.0.1:8000/agui",
        threadId: "tfg-thread-1",
      }),
    []
  );

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMessage: UiMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };

    setUiMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    agent.messages.push({
      id: userMessage.id,
      role: "user",
      content: text,
    });

    const assistantMessageId = crypto.randomUUID();

    try {
      await agent.runAgent(
        {
          runId: crypto.randomUUID(),
        },
        {
          onTextMessageStartEvent() {
            setUiMessages((prev) => [
              ...prev,
              {
                id: assistantMessageId,
                role: "assistant",
                content: "",
              },
            ]);
          },
          onTextMessageContentEvent({ event }) {
            setUiMessages((prev) =>
              prev.map((message) =>
                message.id === assistantMessageId
                  ? { ...message, content: message.content + event.delta }
                  : message
              )
            );
          },
          onRunFinishedEvent() {
            setLoading(false);
          },
        }
      );
    } catch (error) {
      console.error(error);
      setUiMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "Error conectando con el backend AG-UI.",
        },
      ]);
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <h1>TFG MCP UI</h1>
      <p className="subtitle">MVP de texto sobre AG-UI</p>

      <div className="chat-box">
        {uiMessages.length === 0 && (
          <p className="empty-state">Escribe un mensaje para probar AG-UI.</p>
        )}

        {uiMessages.map((message) => (
          <div
            key={message.id}
            className={`message ${message.role === "user" ? "user" : "assistant"}`}
          >
            <strong>{message.role === "user" ? "Tú" : "Asistente"}:</strong>{" "}
            {message.content}
          </div>
        ))}
      </div>

      <div className="input-row">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Escribe tu mensaje..."
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              sendMessage();
            }
          }}
        />
        <button onClick={sendMessage} disabled={loading}>
          {loading ? "Enviando..." : "Enviar"}
        </button>
      </div>
    </div>
  );
}

export default App;