import { useEffect, useRef, useState } from "react";
import {
  AppBridge,
  PostMessageTransport,
  buildAllowAttribute,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import type { McpAppCall } from "./mcpClient";

interface Props {
  call: McpAppCall;
}

const SANDBOX_PROXY_URL =
  import.meta.env.VITE_SANDBOX_PROXY_URL ?? "http://127.0.0.1:8000/sandbox.html";

const PROXY_READY = "ui/notifications/sandbox-proxy-ready";

function waitForSandboxProxy(iframe: HTMLIFrameElement): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      window.removeEventListener("message", listener);
      reject(new Error("El sandbox proxy MCP Apps no ha respondido en 10 segundos."));
    }, 10_000);

    const listener = (event: MessageEvent) => {
      if (
        event.source === iframe.contentWindow &&
        event.data?.method === PROXY_READY
      ) {
        window.clearTimeout(timeout);
        window.removeEventListener("message", listener);
        resolve();
      }
    };

    window.addEventListener("message", listener);
  });
}

function waitForAppInitialized(bridge: AppBridge): Promise<void> {
  return new Promise((resolve) => {
    const previous = bridge.oninitialized;
    bridge.oninitialized = (...args) => {
      resolve();
      bridge.oninitialized = previous;
      previous?.(...args);
    };
  });
}

export function McpAppFrame({ call }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    const iframe = iframeRef.current!;
    if (!iframe) return;

    let disposed = false;
    let bridge: AppBridge | null = null;
    let resizeObserver: ResizeObserver | null = null;

    async function mountApp() {
      try {
        const sandboxUrl = new URL(SANDBOX_PROXY_URL);
        if (call.csp) {
          sandboxUrl.searchParams.set("csp", JSON.stringify(call.csp));
        }

        const allowAttribute = buildAllowAttribute(call.permissions);
        if (allowAttribute) {
          iframe.setAttribute("allow", allowAttribute);
        } else {
          iframe.removeAttribute("allow");
        }

        const proxyReady = waitForSandboxProxy(iframe);
        iframe.src = sandboxUrl.href;
        await proxyReady;

        if (disposed || !iframe.contentWindow) return;

        const serverCapabilities = call.client.getServerCapabilities();
        bridge = new AppBridge(
          call.client,
          { name: "TFG MCP Apps Host", version: "1.0.0" },
          {
            openLinks: {},
            serverTools: serverCapabilities?.tools,
            serverResources: serverCapabilities?.resources,
          },
          {
            hostContext: {
              theme: window.matchMedia("(prefers-color-scheme: dark)").matches
                ? "dark"
                : "light",
              platform: "web",
              locale: navigator.language || "es-ES",
              timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
              userAgent: "TFG MCP Apps Host/1.0.0",
              toolInfo: { tool: call.tool },
              containerDimensions: {
                width: Math.max(320, Math.round(iframe.clientWidth || 760)),
                // Inline MCP Apps are allowed to grow with their content.
                // A generous host hint avoids forcing an internal vertical scrollbar.
                maxHeight: 20_000,
              },
              displayMode: "inline",
              availableDisplayModes: ["inline"],
            },
          },
        );

        bridge.onsizechange = async ({ height }) => {
          if (height !== undefined && iframe) {
            // Do not cap the MCP App height: the chat owns vertical scrolling.
            iframe.style.height = `${Math.max(240, Math.ceil(height))}px`;
          }
        };

        bridge.onopenlink = async ({ url }) => {
          window.open(url, "_blank", "noopener,noreferrer");
          return {};
        };

        resizeObserver = new ResizeObserver(([entry]) => {
          const width = Math.round(entry.contentRect.width);
          if (width > 0) {
            bridge?.sendHostContextChange({
              containerDimensions: { width, maxHeight: 20_000 },
            });
          }
        });
        resizeObserver.observe(iframe);

        const initialized = waitForAppInitialized(bridge);
        await bridge.connect(
          new PostMessageTransport(iframe.contentWindow, iframe.contentWindow),
        );

        await bridge.sendSandboxResourceReady({
          html: call.html,
          csp: call.csp,
          permissions: call.permissions,
        });

        await initialized;
        if (disposed || !bridge) return;

        bridge.sendToolInput({ arguments: call.input });
        bridge.sendToolResult(call.result);
        setStatus("ready");
      } catch (caught) {
        if (!disposed) {
          setStatus("error");
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      }
    }

    void mountApp();

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      if (bridge) {
        void bridge.teardownResource({})
          .catch(() => undefined)
          .finally(() => void bridge?.close());
      }
      iframe.removeAttribute("src");
    };
  }, [call]);

  return (
    <div className="mcp-frame-shell">
      {status === "loading" && (
        <div className="frame-status">Inicializando sandbox proxy + MCP App…</div>
      )}
      {status === "error" && (
        <div className="frame-error">No se pudo montar la MCP App: {error}</div>
      )}
      <iframe
        ref={iframeRef}
        className={`mcp-app-frame ${status === "ready" ? "is-ready" : ""}`}
        title="Uyuni MCP App"
        sandbox="allow-scripts allow-same-origin allow-forms"
        referrerPolicy="strict-origin-when-cross-origin"
      />
    </div>
  );
}
