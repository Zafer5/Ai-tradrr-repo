import { useEffect, useState } from "react";
import { api, J } from "./api";
import { ago } from "./format";
import { Badge, usePoll } from "./ui";
import Home from "./pages/Home";
import Scanner from "./pages/Scanner";
import Analyses from "./pages/Analyses";
import Positions from "./pages/Positions";
import History from "./pages/History";
import Report from "./pages/Report";
import Settings from "./pages/Settings";
import Risk from "./pages/Risk";
import Connections from "./pages/Connections";
import Logs from "./pages/Logs";

type Route = { id: string; label: string; icon: string; el: () => JSX.Element };

export const ROUTES: Route[] = [
  { id: "home", label: "Ana Sayfa", icon: "🏠", el: Home },
  { id: "scanner", label: "Coin Tarayıcı", icon: "📡", el: Scanner },
  { id: "analyses", label: "AI Analizleri", icon: "🧠", el: Analyses },
  { id: "positions", label: "Açık Pozisyonlar", icon: "💼", el: Positions },
  { id: "history", label: "İşlem Geçmişi", icon: "🧾", el: History },
  { id: "report", label: "Kâr-Zarar Raporu", icon: "📈", el: Report },
  { id: "settings", label: "Bot Ayarları", icon: "⚙️", el: Settings },
  { id: "risk", label: "Risk Yönetimi", icon: "🛡️", el: Risk },
  { id: "connections", label: "API Bağlantıları", icon: "🔌", el: Connections },
  { id: "logs", label: "Sistem Günlükleri", icon: "📜", el: Logs },
];
const TABS = ["home", "scanner", "analyses", "positions"];

function currentRoute(): string {
  const h = location.hash.replace(/^#\/?/, "").split("?")[0];
  return ROUTES.some((r) => r.id === h) || h === "menu" ? h : "home";
}

function Login({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.post("/auth/login", { password: pw });
      onDone();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="login">
      <form className="card login-card" onSubmit={submit}>
        <div className="logo">AI</div>
        <h1>AI Kripto Trader</h1>
        <p className="muted">Panel şifrenizle giriş yapın.</p>
        <label htmlFor="pw">Şifre</label>
        <input id="pw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
        {err && <div className="alert bad" role="alert">{err}</div>}
        <button className="btn primary" disabled={busy || !pw}>{busy ? "Giriş yapılıyor…" : "Giriş yap"}</button>
        <p className="muted small">Sanal (paper) mod · Gerçek para kilitli</p>
      </form>
    </main>
  );
}

function StatusStrip({ s }: { s: J }) {
  if (!s) return null;
  const b = s.bot;
  const m = s.market;
  return (
    <>
      <div className="mode-banner">SANAL İŞLEM (PAPER) MODU — gerçek para kullanılmıyor</div>
      {b.emergency && <div className="alert bad" role="alert">🛑 ACİL DURDURMA AKTİF. Yeni alım yapılmaz. Risk Yönetimi sayfasından kaldırabilirsiniz.</div>}
      {b.safe_mode && <div className="alert warn" role="alert">⚠️ Güvenli mod: {b.safe_mode}. Yeni alım yapılmıyor.</div>}
      <div className="strip">
        <Badge kind={b.enabled ? "ok" : ""}>{b.enabled ? "Bot AÇIK" : "Bot KAPALI"}</Badge>
        <Badge kind={m.ws_connected ? "ok" : "warn"}>{m.ws_connected ? "Canlı akış" : "Akış yok"}</Badge>
        <span className="muted small">Son tarama: {ago(m.last_scan_age_sec)}</span>
      </div>
      {m.scan_error && <div className="alert warn">Piyasa verisi hatası: {m.scan_error}</div>}
    </>
  );
}

function Menu() {
  return (
    <div className="menu">
      {ROUTES.map((r) => (
        <a key={r.id} href={`#/${r.id}`} className="menu-item">
          <span aria-hidden>{r.icon}</span> {r.label}
        </a>
      ))}
      <button
        className="menu-item"
        onClick={async () => {
          await api.post("/auth/logout");
          location.hash = "";
          location.reload();
        }}
      >
        <span aria-hidden>🚪</span> Çıkış yap
      </button>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [route, setRoute] = useState(currentRoute());

  useEffect(() => {
    api.get("/auth/me").then((r) => setAuthed(r.authenticated)).catch(() => setAuthed(false));
    const un = () => setAuthed(false);
    const hc = () => setRoute(currentRoute());
    window.addEventListener("unauthorized", un);
    window.addEventListener("hashchange", hc);
    return () => {
      window.removeEventListener("unauthorized", un);
      window.removeEventListener("hashchange", hc);
    };
  }, []);

  const status = usePoll(() => api.get("/status"), 5000, [authed]);

  if (authed === null) return <div className="loading">Yükleniyor…</div>;
  if (!authed) return <Login onDone={() => setAuthed(true)} />;

  const R = ROUTES.find((r) => r.id === route);
  const Page = R?.el;
  return (
    <div className="app">
      <header className="top">
        <strong>AI Kripto Trader</strong>
        <span className="muted small">{R ? R.label : "Menü"}</span>
      </header>
      <main className="content">
        <StatusStrip s={status.data} />
        {route === "menu" ? <Menu /> : Page ? <Page /> : null}
      </main>
      <nav className="tabs" aria-label="Ana menü">
        {TABS.map((id) => {
          const r = ROUTES.find((x) => x.id === id)!;
          return (
            <a key={id} href={`#/${id}`} className={route === id ? "on" : ""} aria-current={route === id ? "page" : undefined}>
              <span aria-hidden>{r.icon}</span>
              <small>{r.label.replace("Coin ", "").replace("Açık ", "")}</small>
            </a>
          );
        })}
        <a href="#/menu" className={!TABS.includes(route) ? "on" : ""}>
          <span aria-hidden>☰</span>
          <small>Menü</small>
        </a>
      </nav>
    </div>
  );
}
