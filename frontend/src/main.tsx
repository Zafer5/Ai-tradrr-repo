import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import App from "./App";
import { applyTheme, getTheme } from "./theme";
import { ToastProvider } from "./ui";
import "./styles.css";

applyTheme(getTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>,
);

// PWA: yalnızca uygulama kabuğu önbelleğe alınır (API yanıtları asla önbelleğe alınmaz)
if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
  navigator.serviceWorker?.register("/sw.js").catch(() => undefined);
}
