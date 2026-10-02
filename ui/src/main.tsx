import "@xyflow/react/dist/style.css";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { Application } from "./Application";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Application />
  </StrictMode>,
);
