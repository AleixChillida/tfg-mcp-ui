import { useMemo, useState } from "react";
import { HttpAgent } from "@ag-ui/client";
import "./App.css";

type TableVisualization = {
  type: "table";
  title: string;
  columns: Array<{ key: string; label: string }>;
  rows: Array<Record<string, string | number | boolean>>;
  truncated?: boolean;
  total_rows?: number;
};

type KeyValueVisualization = {
  type: "key_value";
  title: string;
  items: Array<{ label: string; value: string }>;
};

type ChartVisualization = {
  type: "bar_chart" | "line_chart";
  title: string;
  labels: string[];
  series: Array<{ name: string; values: number[] }>;
  truncated?: boolean;
};

type Visualization =
  | TableVisualization
  | KeyValueVisualization
  | ChartVisualization;

type UiMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  visualizations?: Visualization[];
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseVisualization(value: unknown): Visualization | null {
  if (!isObject(value) || typeof value.type !== "string") {
    return null;
  }

  if (value.type === "table") {
    if (!Array.isArray(value.columns) || !Array.isArray(value.rows)) {
      return null;
    }
    return value as TableVisualization;
  }

  if (value.type === "key_value") {
    if (!Array.isArray(value.items)) {
      return null;
    }
    return value as KeyValueVisualization;
  }

  if (value.type === "bar_chart" || value.type === "line_chart") {
    if (!Array.isArray(value.labels) || !Array.isArray(value.series)) {
      return null;
    }
    return value as ChartVisualization;
  }

  return null;
}

function formatCell(value: string | number | boolean | undefined) {
  if (value === undefined || value === "") return "—";
  return String(value);
}

function shortLabel(label: string, maxLength = 18) {
  if (label.length <= maxLength) return label;
  return `${label.slice(0, maxLength - 1)}…`;
}

function TableView({ visual }: { visual: TableVisualization }) {
  return (
    <div className="visual-card">
      <div className="visual-header">
        <h3>{visual.title}</h3>
        <span className="visual-badge">Tabla</span>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {visual.columns.map((column) => (
                <th key={column.key}>{column.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visual.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {visual.columns.map((column) => (
                  <td key={column.key} title={formatCell(row[column.key])}>
                    {formatCell(row[column.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {visual.truncated && (
        <p className="visual-note">
          Mostrando las primeras {visual.rows.length} filas
          {typeof visual.total_rows === "number"
            ? ` de ${visual.total_rows}`
            : ""}
          .
        </p>
      )}
    </div>
  );
}

function KeyValueView({ visual }: { visual: KeyValueVisualization }) {
  return (
    <div className="visual-card">
      <div className="visual-header">
        <h3>{visual.title}</h3>
        <span className="visual-badge">Detalle</span>
      </div>
      <dl className="detail-grid">
        {visual.items.map((item) => (
          <div className="detail-item" key={item.label}>
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ChartFrame({
  visual,
  children,
}: {
  visual: ChartVisualization;
  children: React.ReactNode;
}) {
  return (
    <div className="visual-card">
      <div className="visual-header">
        <h3>{visual.title}</h3>
        <span className="visual-badge">
          {visual.type === "line_chart" ? "Líneas" : "Barras"}
        </span>
      </div>
      <div className="chart-scroll">{children}</div>
      {visual.truncated && (
        <p className="visual-note">
          El gráfico muestra los primeros {visual.labels.length} elementos.
        </p>
      )}
    </div>
  );
}

function BarChartView({ visual }: { visual: ChartVisualization }) {
  const values = visual.series[0]?.values ?? [];
  const seriesName = visual.series[0]?.name ?? "Valor";

  if (values.length === 0 || visual.labels.length === 0) {
    return null;
  }

  const width = 760;
  const height = 320;
  const margin = { top: 20, right: 20, bottom: 82, left: 58 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const minValue = Math.min(0, ...values);
  const maxValue = Math.max(0, ...values);
  const range = maxValue - minValue || 1;
  const yFor = (value: number) =>
    margin.top + ((maxValue - value) / range) * plotHeight;
  const zeroY = yFor(0);
  const slotWidth = plotWidth / Math.max(values.length, 1);
  const barWidth = Math.max(8, Math.min(46, slotWidth * 0.62));

  return (
    <ChartFrame visual={visual}>
      <svg
        className="chart-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${visual.title}. Serie ${seriesName}`}
      >
        <line
          className="chart-axis"
          x1={margin.left}
          y1={zeroY}
          x2={width - margin.right}
          y2={zeroY}
        />
        <line
          className="chart-axis"
          x1={margin.left}
          y1={margin.top}
          x2={margin.left}
          y2={height - margin.bottom}
        />

        {values.map((value, index) => {
          const centerX = margin.left + slotWidth * index + slotWidth / 2;
          const valueY = yFor(value);
          const barY = value >= 0 ? valueY : zeroY;
          const barHeight = Math.max(1, Math.abs(zeroY - valueY));
          const label = visual.labels[index] ?? String(index + 1);

          return (
            <g key={`${label}-${index}`}>
              <rect
                className="chart-bar"
                x={centerX - barWidth / 2}
                y={barY}
                width={barWidth}
                height={barHeight}
                rx="4"
              >
                <title>{`${label}: ${value}`}</title>
              </rect>
              <text
                className="chart-value"
                x={centerX}
                y={Math.max(margin.top + 12, barY - 7)}
                textAnchor="middle"
              >
                {value}
              </text>
              <text
                className="chart-label"
                x={centerX}
                y={height - margin.bottom + 22}
                textAnchor="end"
                transform={`rotate(-32 ${centerX} ${height - margin.bottom + 22})`}
              >
                {shortLabel(label)}
              </text>
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}

function LineChartView({ visual }: { visual: ChartVisualization }) {
  const values = visual.series[0]?.values ?? [];
  const seriesName = visual.series[0]?.name ?? "Valor";

  if (values.length === 0 || visual.labels.length === 0) {
    return null;
  }

  const width = 760;
  const height = 320;
  const margin = { top: 24, right: 24, bottom: 82, left: 58 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const range = maxValue - minValue || 1;
  const xFor = (index: number) =>
    margin.left +
    (index / Math.max(values.length - 1, 1)) * plotWidth;
  const yFor = (value: number) =>
    margin.top + ((maxValue - value) / range) * plotHeight;
  const points = values
    .map((value, index) => `${xFor(index)},${yFor(value)}`)
    .join(" ");

  return (
    <ChartFrame visual={visual}>
      <svg
        className="chart-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${visual.title}. Serie ${seriesName}`}
      >
        <line
          className="chart-axis"
          x1={margin.left}
          y1={height - margin.bottom}
          x2={width - margin.right}
          y2={height - margin.bottom}
        />
        <line
          className="chart-axis"
          x1={margin.left}
          y1={margin.top}
          x2={margin.left}
          y2={height - margin.bottom}
        />
        <polyline className="chart-line" points={points} />

        {values.map((value, index) => {
          const x = xFor(index);
          const y = yFor(value);
          const label = visual.labels[index] ?? String(index + 1);

          return (
            <g key={`${label}-${index}`}>
              <circle className="chart-point" cx={x} cy={y} r="5">
                <title>{`${label}: ${value}`}</title>
              </circle>
              <text
                className="chart-value"
                x={x}
                y={Math.max(margin.top + 10, y - 10)}
                textAnchor="middle"
              >
                {value}
              </text>
              <text
                className="chart-label"
                x={x}
                y={height - margin.bottom + 22}
                textAnchor="end"
                transform={`rotate(-32 ${x} ${height - margin.bottom + 22})`}
              >
                {shortLabel(label)}
              </text>
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}

function VisualizationView({ visual }: { visual: Visualization }) {
  if (visual.type === "table") {
    return <TableView visual={visual} />;
  }

  if (visual.type === "key_value") {
    return <KeyValueView visual={visual} />;
  }

  if (visual.type === "line_chart") {
    return <LineChartView visual={visual} />;
  }

  return <BarChartView visual={visual} />;
}

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
                visualizations: [],
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
          onCustomEvent({ event }) {
            if (event.name !== "ui.visualization") return;

            const visualization = parseVisualization(event.value);
            if (!visualization) {
              console.warn("Visualización AG-UI no reconocida", event.value);
              return;
            }

            setUiMessages((prev) =>
              prev.map((message) =>
                message.id === assistantMessageId
                  ? {
                      ...message,
                      visualizations: [
                        ...(message.visualizations ?? []),
                        visualization,
                      ],
                    }
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
      <p className="subtitle">MVP AG-UI con respuestas de texto y visuales</p>

      <div className="chat-box">
        {uiMessages.length === 0 && (
          <p className="empty-state">Escribe un mensaje para probar AG-UI.</p>
        )}

        {uiMessages.map((message) => (
          <div
            key={message.id}
            className={`message ${message.role === "user" ? "user" : "assistant"}`}
          >
            <div className="message-text">
              <strong>{message.role === "user" ? "Tú" : "Asistente"}:</strong>{" "}
              {message.content}
            </div>

            {message.visualizations?.map((visual, index) => (
              <VisualizationView
                key={`${message.id}-${visual.type}-${index}`}
                visual={visual}
              />
            ))}
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
