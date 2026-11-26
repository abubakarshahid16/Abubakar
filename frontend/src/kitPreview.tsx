/** The shared kit's preview (served by the practice server at /kit.html, ?theme=dark for dark; never in the built app). */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
import "./look.css";
import { KitPreview } from "./components/kit/KitPreview";

const saved = (() => { try { return localStorage.getItem("rag-intelligence-theme"); } catch { return null; } })();
const theme = (new URLSearchParams(window.location.search).get("theme") ?? saved) === "dark" ? "dark" : "light";
document.documentElement.dataset.theme = theme;
document.documentElement.dataset.look = "new";
document.body.className = "bg-ink-900 text-slateish-200";
createRoot(document.getElementById("root")!).render(<StrictMode><KitPreview /></StrictMode>);
