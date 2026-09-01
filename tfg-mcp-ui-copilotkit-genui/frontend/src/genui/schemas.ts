import { z } from "zod";

export const cellValueSchema = z.union([
  z.string(),
  z.number(),
  z.boolean(),
  z.null(),
]);

export const tableSchema = z.object({
  title: z.string().describe("Título breve de la tabla."),
  subtitle: z
    .string()
    .optional()
    .describe("Contexto opcional en una frase breve."),
  columns: z
    .array(
      z.object({
        key: z.string().describe("Clave presente en las filas."),
        label: z.string().describe("Etiqueta visible de la columna."),
      }),
    )
    .min(1)
    .max(10),
  rows: z
    .array(z.record(z.string(), cellValueSchema))
    .max(50)
    .describe("Filas fieles a los datos reales devueltos por Uyuni."),
});

export const chartPointSchema = z.object({
  label: z.string().describe("Categoría o instante visible."),
  value: z.number().describe("Valor numérico real o derivado por conteo."),
});

const chartBaseSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  xLabel: z.string().optional(),
  yLabel: z.string().optional(),
  valueSuffix: z.string().optional(),
  data: z.array(chartPointSchema).min(1).max(20),
});

export const barChartSchema = chartBaseSchema;
export const lineChartSchema = chartBaseSchema;

export const pieChartSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  valueSuffix: z.string().optional(),
  data: z.array(chartPointSchema).min(1).max(12),
});

export const metricCardsSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  metrics: z
    .array(
      z.object({
        label: z.string(),
        value: z.union([z.string(), z.number()]),
        detail: z.string().optional(),
        tone: z
          .enum(["neutral", "positive", "warning", "danger", "info"])
          .optional(),
      }),
    )
    .min(1)
    .max(8),
});

export const detailCardSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  fields: z
    .array(
      z.object({
        label: z.string(),
        value: z.union([z.string(), z.number(), z.boolean()]),
      }),
    )
    .min(1)
    .max(18),
});

export const timelineSchema = z.object({
  title: z.string(),
  subtitle: z.string().optional(),
  items: z
    .array(
      z.object({
        title: z.string(),
        timestamp: z.string().optional(),
        description: z.string().optional(),
        status: z.string().optional(),
      }),
    )
    .min(1)
    .max(20),
});

export const emptyStateSchema = z.object({
  title: z.string(),
  message: z.string(),
});

export type TableProps = z.infer<typeof tableSchema>;
export type BarChartProps = z.infer<typeof barChartSchema>;
export type LineChartProps = z.infer<typeof lineChartSchema>;
export type PieChartProps = z.infer<typeof pieChartSchema>;
export type MetricCardsProps = z.infer<typeof metricCardsSchema>;
export type DetailCardProps = z.infer<typeof detailCardSchema>;
export type TimelineProps = z.infer<typeof timelineSchema>;
export type EmptyStateProps = z.infer<typeof emptyStateSchema>;
