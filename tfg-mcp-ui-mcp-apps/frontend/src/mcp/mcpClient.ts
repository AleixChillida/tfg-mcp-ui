import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { CallToolResult, Resource, Tool } from "@modelcontextprotocol/sdk/types.js";
import {
  getToolUiResourceUri,
  type McpUiResourceCsp,
  type McpUiResourcePermissions,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import { RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps";

export const MCP_APPS_URL =
  import.meta.env.VITE_MCP_APPS_URL ?? "http://127.0.0.1:8000/mcp-app/";

const configuredTimeout = Number(import.meta.env.VITE_MCP_TIMEOUT_MS ?? "180000");
const MCP_TIMEOUT_MS =
  Number.isFinite(configuredTimeout) && configuredTimeout > 0
    ? configuredTimeout
    : 180000;

const HOST_INFO = { name: "TFG MCP Apps Host", version: "1.0.0" };

export interface McpAppCall {
  client: Client;
  tool: Tool;
  input: Record<string, unknown>;
  result: CallToolResult;
  html: string;
  csp?: McpUiResourceCsp;
  permissions?: McpUiResourcePermissions;
  clientReadyMs: number;
  discoveryMs: number;
  resourceMs: number;
  mcpMs: number;
}

export interface PresentationInfo {
  upstreamMcpMs?: number;
  presentationLlmMs?: number;
  adapterTotalMs?: number;
  selectedView?: string;
  selectionMode?: string;
  selectionReason?: string;
}

type UiMeta = {
  ui?: {
    csp?: McpUiResourceCsp;
    permissions?: McpUiResourcePermissions;
  };
};

type MetaCarrier = {
  _meta?: UiMeta;
  // Some Python MCP implementations have historically surfaced this as meta.
  meta?: UiMeta;
};

let clientPromise: Promise<Client> | null = null;

export async function getMcpClient(): Promise<Client> {
  if (!clientPromise) {
    clientPromise = (async () => {
      const client = new Client(HOST_INFO);
      const transport = new StreamableHTTPClientTransport(new URL(MCP_APPS_URL));
      await client.connect(transport);
      return client;
    })().catch((error) => {
      clientPromise = null;
      throw error;
    });
  }
  return clientPromise;
}

function getUiMeta(
  content: unknown,
  listingResource: Resource | undefined,
): UiMeta["ui"] | undefined {
  const contentCarrier = content as MetaCarrier;
  const listingCarrier = listingResource as (Resource & MetaCarrier) | undefined;
  return (
    contentCarrier._meta?.ui ??
    contentCarrier.meta?.ui ??
    listingCarrier?._meta?.ui ??
    listingCarrier?.meta?.ui
  );
}

export async function callUyuniMcpApp(
  input: Record<string, unknown>,
): Promise<McpAppCall> {
  const clientStarted = performance.now();
  const client = await getMcpClient();
  const clientReadyMs = performance.now() - clientStarted;

  const discoveryStarted = performance.now();
  const [tools, resources] = await Promise.all([
    client.listTools(),
    client.listResources(),
  ]);
  const discoveryMs = performance.now() - discoveryStarted;
  const tool = tools.tools.find((candidate) => candidate.name === "query_uyuni");

  if (!tool) {
    throw new Error("El servidor MCP Apps no anuncia la tool query_uyuni.");
  }

  const resourceUri = getToolUiResourceUri(tool);
  if (!resourceUri) {
    throw new Error("query_uyuni no anuncia _meta.ui.resourceUri.");
  }

  const listingResource = resources.resources.find(
    (resource) => resource.uri === resourceUri,
  );

  const resourceStarted = performance.now();
  const resourcePromise = client.readResource({ uri: resourceUri }).then((resource) => ({
    resource,
    resourceMs: performance.now() - resourceStarted,
  }));

  const started = performance.now();
  const result = (await client.callTool(
    {
      name: tool.name,
      arguments: input,
    },
    undefined,
    {
      timeout: MCP_TIMEOUT_MS,
      resetTimeoutOnProgress: true,
    },
  )) as CallToolResult;
  const mcpMs = performance.now() - started;

  const { resource, resourceMs } = await resourcePromise;
  const content = resource.contents[0];
  if (!content) {
    throw new Error(`El recurso MCP App ${resourceUri} está vacío.`);
  }
  if (content.mimeType !== RESOURCE_MIME_TYPE) {
    throw new Error(
      `MIME inesperado para la MCP App: ${content.mimeType ?? "sin MIME"}.`,
    );
  }

  const html = "text" in content ? content.text : atob(content.blob);
  const uiMeta = getUiMeta(content, listingResource);

  return {
    client,
    tool,
    input,
    result,
    html,
    csp: uiMeta?.csp,
    permissions: uiMeta?.permissions,
    clientReadyMs,
    discoveryMs,
    resourceMs,
    mcpMs,
  };
}

export function extractToolText(result: CallToolResult): string {
  const parts: string[] = [];
  for (const item of result.content ?? []) {
    if (item.type === "text" && "text" in item && typeof item.text === "string") {
      parts.push(item.text);
    }
  }
  return parts.join("\n").trim();
}

export function extractPresentationInfo(result: CallToolResult): PresentationInfo {
  const structured = (result.structuredContent ?? {}) as Record<string, unknown>;
  const timing = (structured.timing ?? {}) as Record<string, unknown>;
  const selection = (structured.presentationSelection ?? {}) as Record<string, unknown>;

  const numberValue = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value) ? value : undefined;
  const stringValue = (value: unknown) =>
    typeof value === "string" && value ? value : undefined;

  return {
    upstreamMcpMs: numberValue(timing.upstreamMcpMs),
    presentationLlmMs: numberValue(timing.presentationLlmMs),
    adapterTotalMs: numberValue(timing.adapterTotalMs),
    selectedView: stringValue(selection.selectedView) ?? stringValue(structured.initialView),
    selectionMode: stringValue(selection.mode) ?? stringValue(structured.selectionMode),
    selectionReason: stringValue(selection.reason),
  };
}
