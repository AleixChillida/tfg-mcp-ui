import { createRoot } from "react-dom/client";
import { HttpAgent } from "@ag-ui/client";
import { CopilotKit } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import "./index.css";
import App from "./App.tsx";
import { COPILOT_AGENT_ID } from "./genui/GenUIRegistry";

const uyuniAgent = new HttpAgent({
  url: import.meta.env.VITE_AGUI_URL ?? "http://127.0.0.1:8000/agui",
});

createRoot(document.getElementById("root")!).render(
  <CopilotKit
    agents__unsafe_dev_only={{ [COPILOT_AGENT_ID]: uyuniAgent }}
    showDevConsole={false}
  >
    <App />
  </CopilotKit>,
);
