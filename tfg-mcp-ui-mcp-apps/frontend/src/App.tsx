import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import "./App.css";
import { McpAppFrame } from "./mcp/McpAppFrame";
import {
  callUyuniMcpApp,
  extractPresentationInfo,
  extractToolText,
  type McpAppCall,
} from "./mcp/mcpClient";

const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

type ChatRole = "user" | "assistant";

interface Timing {
  routeMs?: number;
  clientReadyMs?: number;
  discoveryMs?: number;
  resourceMs?: number;
  mcpAppMs?: number;
  upstreamMcpMs?: number;
  presentationLlmMs?: number;
  adapterTotalMs?: number;
  totalMs?: number;
}

interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  appCall?: McpAppCall;
  timing?: Timing;
  toolName?: string;
  selectedView?: string;
  selectionMode?: string;
  selectionReason?: string;
}

interface RouteResponse {
  kind: "tool" | "text" | "clarification" | "error";
  tool_name?: string;
  arguments?: Record<string, unknown>;
  text?: string;
  route_ms?: number;
}

function uid() {
  return crypto.randomUUID();
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${path} ha devuelto HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function formatMs(value?: number) {
  if (value === undefined) return "—";
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(2)} s`;
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const prompt = input.trim();
    if (!prompt || busy) return;

    const userMessage: ChatMessage = { id: uid(), role: "user", text: prompt };
    const history = [...messages, userMessage];
    setMessages(history);
    setInput("");
    setBusy(true);
    const totalStarted = performance.now();

    try {
      const route = await postJson<RouteResponse>("/api/route", {
        messages: history.map((message) => ({ role: message.role, content: message.text })),
      });

      if (route.kind !== "tool") {
        setMessages((current) => [
          ...current,
          {
            id: uid(),
            role: "assistant",
            text: route.text || "No he podido resolver la petición.",
            timing: {
              routeMs: route.route_ms,
              totalMs: performance.now() - totalStarted,
            },
          },
        ]);
        return;
      }

      if (!route.tool_name) {
        throw new Error("El router ha pedido MCP pero no ha devuelto tool_name.");
      }

      const appInput: Record<string, unknown> = {
        tool_name: route.tool_name,
        arguments: route.arguments ?? {},
        user_request: prompt,
      };

      const appCall = await callUyuniMcpApp(appInput);
      const presentation = extractPresentationInfo(appCall.result);
      const toolText = extractToolText(appCall.result);

      setMessages((current) => [
        ...current,
        {
          id: uid(),
          role: "assistant",
          text: toolText || "La consulta MCP ha finalizado.",
          appCall,
          toolName: route.tool_name,
          selectedView: presentation.selectedView,
          selectionMode: presentation.selectionMode,
          selectionReason: presentation.selectionReason,
          timing: {
            routeMs: route.route_ms,
            clientReadyMs: appCall.clientReadyMs,
            discoveryMs: appCall.discoveryMs,
            resourceMs: appCall.resourceMs,
            mcpAppMs: appCall.mcpMs,
            upstreamMcpMs: presentation.upstreamMcpMs,
            presentationLlmMs: presentation.presentationLlmMs,
            adapterTotalMs: presentation.adapterTotalMs,
            totalMs: performance.now() - totalStarted,
          },
        },
      ]);
    } catch (caught) {
      setMessages((current) => [
        ...current,
        {
          id: uid(),
          role: "assistant",
          text: `Ha ocurrido un error: ${caught instanceof Error ? caught.message : String(caught)}`,
          timing: { totalMs: performance.now() - totalStarted },
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <strong>MCP Apps / FastMCP</strong>
      </header>

      <main className="chat-panel">
        <div className="chat-scroll">
          {messages.map((message) => (
            <article key={message.id} className={`message-row ${message.role}`}>
              <div className="avatar">{message.role === "user" ? "Tú" : "AI"}</div>
              <div className="message-stack">
                <div className="message-bubble">{message.text}</div>
                {message.appCall && <McpAppFrame call={message.appCall} />}
                {message.timing && (
                  <div className="timing-row" title="Tiempos orientativos de la consulta.">
                    <span>router IA {formatMs(message.timing.routeMs)}</span>
                    {message.timing.upstreamMcpMs !== undefined && <span>Uyuni MCP {formatMs(message.timing.upstreamMcpMs)}</span>}
                    {message.timing.presentationLlmMs !== undefined && <span>visual IA {formatMs(message.timing.presentationLlmMs)}</span>}
                    {message.timing.resourceMs !== undefined && <span>ui:// {formatMs(message.timing.resourceMs)}</span>}
                    {message.timing.mcpAppMs !== undefined && <span>MCP App {formatMs(message.timing.mcpAppMs)}</span>}
                    <strong>total {formatMs(message.timing.totalMs)}</strong>
                  </div>
                )}
                {(message.toolName || message.selectedView) && (
                  <div className="tool-meta-row">
                    {message.toolName && <div className="tool-chip">MCP · {message.toolName}</div>}
                    {message.selectedView && (
                      <div
                        className={`tool-chip visual-chip ${message.selectionMode === "fallback" ? "fallback" : ""}`}
                        title={message.selectionReason || "Vista seleccionada"}
                      >
                        {message.selectionMode === "fallback" ? "fallback" : "IA"} → {message.selectedView}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </article>
          ))}

          {busy && (
            <article className="message-row assistant">
              <div className="avatar">AI</div>
              <div className="thinking"><span></span><span></span><span></span><em>Consultando…</em></div>
            </article>
          )}
          <div ref={bottomRef} />
        </div>

        <form className="composer" onSubmit={handleSubmit}>
          <div className="composer-box">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="Pregunta algo sobre Uyuni…"
              rows={2}
              disabled={busy}
            />
            <button className="send-button" type="submit" disabled={busy || !input.trim()} aria-label="Enviar">↑</button>
          </div>
        </form>
      </main>
    </div>
  );
}
