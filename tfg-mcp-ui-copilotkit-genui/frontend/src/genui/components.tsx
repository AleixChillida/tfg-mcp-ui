import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  BarChartProps,
  DetailCardProps,
  EmptyStateProps,
  LineChartProps,
  MetricCardsProps,
  PieChartProps,
  TableProps,
  TimelineProps,
} from "./schemas";

const PIE_COLORS = [
  "#6366f1",
  "#06b6d4",
  "#10b981",
  "#f59e0b",
  "#f43f5e",
  "#8b5cf6",
  "#14b8a6",
  "#f97316",
  "#3b82f6",
  "#84cc16",
  "#ec4899",
  "#64748b",
];

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Sí" : "No";
  return String(value);
}

function CardHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="genui-card-header">
      <div>
        <div className="genui-eyebrow">{eyebrow}</div>
        <h3>{title}</h3>
        {subtitle && <p>{subtitle}</p>}
      </div>
      <span className="genui-ai-chip">AI selected</span>
    </div>
  );
}

export function DataTable({ title, subtitle, columns, rows }: TableProps) {
  return (
    <section className="genui-card genui-table-card">
      <CardHeader eyebrow="Structured view" title={title} subtitle={subtitle} />
      {rows.length === 0 ? (
        <div className="genui-inline-empty">No hay filas para mostrar.</div>
      ) : (
        <div className="genui-table-scroll">
          <table className="genui-table">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.key}>{column.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {columns.map((column) => (
                    <td key={column.key} title={formatValue(row[column.key])}>
                      {formatValue(row[column.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ChartCard({
  kind,
  title,
  subtitle,
  children,
}: {
  kind: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section className="genui-card genui-chart-card">
      <CardHeader eyebrow={kind} title={title} subtitle={subtitle} />
      <div className="genui-chart-area">{children}</div>
    </section>
  );
}

function ChartTooltip({
  active,
  payload,
  label,
  suffix = "",
}: {
  active?: boolean;
  payload?: Array<{ value?: number }>;
  label?: string;
  suffix?: string;
}) {
  if (!active || !payload?.length) return null;
  const value = payload[0]?.value;
  return (
    <div className="genui-tooltip">
      <strong>{label}</strong>
      <span>
        {value ?? "—"}
        {suffix}
      </span>
    </div>
  );
}

export function GenBarChart({
  title,
  subtitle,
  xLabel,
  yLabel,
  valueSuffix,
  data,
}: BarChartProps) {
  return (
    <ChartCard kind="Bar chart" title={title} subtitle={subtitle}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 12, right: 14, bottom: 28, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            interval={0}
            angle={data.length > 7 ? -24 : 0}
            textAnchor={data.length > 7 ? "end" : "middle"}
            height={data.length > 7 ? 58 : 34}
            label={xLabel ? { value: xLabel, position: "insideBottom", offset: -18 } : undefined}
          />
          <YAxis
            allowDecimals={false}
            tickLine={false}
            axisLine={false}
            label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft" } : undefined}
          />
          <Tooltip content={<ChartTooltip suffix={valueSuffix} />} />
          <Bar dataKey="value" fill="#6366f1" radius={[8, 8, 2, 2]} maxBarSize={54} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function GenLineChart({
  title,
  subtitle,
  xLabel,
  yLabel,
  valueSuffix,
  data,
}: LineChartProps) {
  return (
    <ChartCard kind="Line chart" title={title} subtitle={subtitle}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 18, bottom: 28, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            interval={0}
            angle={data.length > 7 ? -24 : 0}
            textAnchor={data.length > 7 ? "end" : "middle"}
            height={data.length > 7 ? 58 : 34}
            label={xLabel ? { value: xLabel, position: "insideBottom", offset: -18 } : undefined}
          />
          <YAxis
            allowDecimals={false}
            tickLine={false}
            axisLine={false}
            label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft" } : undefined}
          />
          <Tooltip content={<ChartTooltip suffix={valueSuffix} />} />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#0ea5e9"
            strokeWidth={3}
            dot={{ r: 4, fill: "#ffffff", strokeWidth: 3 }}
            activeDot={{ r: 6 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function GenPieChart({
  title,
  subtitle,
  valueSuffix,
  data,
}: PieChartProps) {
  const total = data.reduce((sum, point) => sum + point.value, 0);

  return (
    <ChartCard kind="Donut chart" title={title} subtitle={subtitle}>
      <div className="genui-pie-layout">
        <div className="genui-pie-chart">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="label"
                innerRadius="58%"
                outerRadius="84%"
                paddingAngle={3}
              >
                {data.map((point, index) => (
                  <Cell key={`${point.label}-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip content={<ChartTooltip suffix={valueSuffix} />} />
            </PieChart>
          </ResponsiveContainer>
          <div className="genui-pie-total">
            <strong>{total}</strong>
            <span>Total</span>
          </div>
        </div>
        <div className="genui-legend">
          {data.map((point, index) => {
            const percentage = total > 0 ? (point.value / total) * 100 : 0;
            return (
              <div className="genui-legend-row" key={`${point.label}-${index}`}>
                <span
                  className="genui-legend-dot"
                  style={{ background: PIE_COLORS[index % PIE_COLORS.length] }}
                />
                <span className="genui-legend-label">{point.label}</span>
                <strong>
                  {point.value}
                  {valueSuffix ?? ""}
                </strong>
                <span className="genui-legend-percent">{percentage.toFixed(0)}%</span>
              </div>
            );
          })}
        </div>
      </div>
    </ChartCard>
  );
}

export function MetricCards({
  title,
  subtitle,
  metrics,
}: MetricCardsProps) {
  return (
    <section className="genui-card">
      <CardHeader eyebrow="Summary metrics" title={title} subtitle={subtitle} />
      <div className="genui-metrics-grid">
        {metrics.map((metric, index) => (
          <article
            className={`genui-metric genui-tone-${metric.tone ?? "neutral"}`}
            key={`${metric.label}-${index}`}
          >
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
            {metric.detail && <small>{metric.detail}</small>}
          </article>
        ))}
      </div>
    </section>
  );
}

export function DetailCard({
  title,
  subtitle,
  fields,
}: DetailCardProps) {
  return (
    <section className="genui-card">
      <CardHeader eyebrow="Detail" title={title} subtitle={subtitle} />
      <dl className="genui-detail-grid">
        {fields.map((field, index) => (
          <div className="genui-detail-item" key={`${field.label}-${index}`}>
            <dt>{field.label}</dt>
            <dd>{formatValue(field.value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function Timeline({ title, subtitle, items }: TimelineProps) {
  return (
    <section className="genui-card">
      <CardHeader eyebrow="Timeline" title={title} subtitle={subtitle} />
      <div className="genui-timeline">
        {items.map((item, index) => (
          <article className="genui-timeline-item" key={`${item.title}-${index}`}>
            <div className="genui-timeline-marker" />
            <div className="genui-timeline-body">
              <div className="genui-timeline-topline">
                <strong>{item.title}</strong>
                {item.status && <span className="genui-status-chip">{item.status}</span>}
              </div>
              {item.timestamp && <time>{item.timestamp}</time>}
              {item.description && <p>{item.description}</p>}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export function EmptyState({ title, message }: EmptyStateProps) {
  return (
    <section className="genui-card genui-empty-card">
      <div className="genui-empty-icon">✓</div>
      <div>
        <div className="genui-eyebrow">No data</div>
        <h3>{title}</h3>
        <p>{message}</p>
      </div>
    </section>
  );
}
