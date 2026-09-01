import { useComponent } from "@copilotkit/react-core/v2";
import {
  DataTable,
  DetailCard,
  EmptyState,
  GenBarChart,
  GenLineChart,
  GenPieChart,
  MetricCards,
  Timeline,
} from "./components";
import {
  barChartSchema,
  detailCardSchema,
  emptyStateSchema,
  lineChartSchema,
  metricCardsSchema,
  pieChartSchema,
  tableSchema,
  timelineSchema,
} from "./schemas";

export const COPILOT_AGENT_ID = "uyuni-agent";

/**
 * Registra componentes display-only de CopilotKit Generative UI.
 *
 * No hay ninguna asociación entre una tool de Uyuni y uno de estos componentes.
 * Las definiciones viajan en RunAgentInput.tools y el LLM decide en cada turno
 * cuál usar a partir del prompt y del resultado real del MCP.
 */
export function GenUIRegistry() {
  useComponent({
    agentId: COPILOT_AGENT_ID,
    followUp: false,
    name: "render_table",
    description:
      "Muestra datos tabulares cuando comparar filas y varias columnas sea la forma más clara. No la uses por defecto solo porque el resultado sea una lista.",
    parameters: tableSchema,
    render: DataTable,
  });

  useComponent({
    agentId: COPILOT_AGENT_ID,
    followUp: false,
    name: "render_bar_chart",
    description:
      "Muestra un gráfico de barras bonito para comparar magnitudes o conteos entre categorías. Priorízalo si el usuario pide explícitamente barras y existen valores numéricos fieles o conteos derivables.",
    parameters: barChartSchema,
    render: GenBarChart,
  });

  useComponent({
    agentId: COPILOT_AGENT_ID,
    followUp: false,
    name: "render_line_chart",
    description:
      "Muestra un gráfico de líneas cuando los datos tengan un orden temporal o secuencial real. Priorízalo si el usuario pide líneas y los datos soportan esa representación.",
    parameters: lineChartSchema,
    render: GenLineChart,
  });

  useComponent({
    agentId: COPILOT_AGENT_ID,
    followUp: false,
    name: "render_pie_chart",
    description:
      "Muestra un gráfico donut/pastel para partes de un total o distribución por categorías. Úsalo si el usuario pide pastel/quesito/donut o si una distribución proporcional es especialmente informativa.",
    parameters: pieChartSchema,
    render: GenPieChart,
  });

  useComponent({
    agentId: COPILOT_AGENT_ID,
    followUp: false,
    name: "render_metric_cards",
    description:
      "Muestra tarjetas de métricas para un resumen con pocos indicadores importantes, contadores, estados o KPIs.",
    parameters: metricCardsSchema,
    render: MetricCards,
  });

  useComponent({
    agentId: COPILOT_AGENT_ID,
    followUp: false,
    name: "render_detail_card",
    description:
      "Muestra una tarjeta de detalle para una sola entidad con atributos heterogéneos, por ejemplo un sistema o un evento concreto.",
    parameters: detailCardSchema,
    render: DetailCard,
  });

  useComponent({
    agentId: COPILOT_AGENT_ID,
    followUp: false,
    name: "render_timeline",
    description:
      "Muestra un timeline para una secuencia de eventos, acciones o hitos con fecha/estado y orden natural.",
    parameters: timelineSchema,
    render: Timeline,
  });

  useComponent({
    agentId: COPILOT_AGENT_ID,
    followUp: false,
    name: "render_empty_state",
    description:
      "Muestra un estado vacío claro cuando la consulta es correcta pero Uyuni devuelve cero elementos o nada pendiente.",
    parameters: emptyStateSchema,
    render: EmptyState,
  });

  return null;
}
