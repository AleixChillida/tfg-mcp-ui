import { CopilotChat } from "@copilotkit/react-core/v2";
import "./App.css";
import { COPILOT_AGENT_ID, GenUIRegistry } from "./genui/GenUIRegistry";

function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="brand-kicker">TFG · Uyuni MCP</div>
          <h1>CopilotKit Generative UI</h1>
          <p>
            OpenRouter + NVIDIA · La IA decide dinámicamente cómo presentar cada
            resultado.
          </p>
        </div>
        <div className="topbar-badges" aria-label="Tecnologías activas">
          <span>CopilotKit v2</span>
          <span>AG-UI</span>
          <span>MCP Uyuni</span>
        </div>
      </header>

      <section className="experiment-note">
        <div className="experiment-dot" />
        <p>
          <strong>Generative UI no determinista por tool:</strong> los componentes
          disponibles (tabla, barras, líneas, donut, métricas, detalle o timeline)
          se envían al agente y el LLM elige según tu prompt y los datos reales de
          Uyuni. Si pides un tipo concreto de gráfico, esa preferencia tiene
          prioridad cuando los datos lo permiten.
        </p>
      </section>

      <main className="chat-panel">
        <GenUIRegistry />
        <CopilotChat
          className="genui-chat"
          agentId={COPILOT_AGENT_ID}
          labels={{
            chatInputPlaceholder:
              "Pregunta por Uyuni o pide una visualización concreta...",
          }}
          welcomeScreen={false}
        />
      </main>

      <footer className="app-footer">
        Variante experimental para comparar CopilotKit GenUI con AG-UI y MCP Apps.
      </footer>
    </div>
  );
}

export default App;
