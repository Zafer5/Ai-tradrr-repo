import { useEffect, useState } from "react";
import { Bell, BrainCircuit, BriefcaseBusiness, Cable, CandlestickChart, LayoutDashboard, LineChart, LogOut, LucideIcon, Menu, Moon, Radar, ReceiptText, ScrollText, ShieldCheck, SlidersHorizontal, Sun, SunMoon, Wallet, Lock, AlertOctagon, TrendingDown, ShieldAlert } from "lucide-react";
import { api, J } from "./api";
import { ago } from "./format";
import { applyTheme, getTheme, ThemePref } from "./theme";
import { Badge, Banner, Loading, PageHeader, usePoll } from "./ui";
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
import Portfolio from "./pages/Portfolio";
import Notifications from "./pages/Notifications";

type Route = { id: string; label: string; short: string; icon: LucideIcon; el: () => JSX.Element; group: string };

export const ROUTES: Route[] = [
  { id: "home", label: "Ana Sayfa", short: "Ana Sayfa", icon: LayoutDashboard, el: Home, group: "Genel" },
  { id: "portfolio", label: "Portföyüm", short: "Portföy", icon: Wallet, el: Portfolio, group: "Genel" },
  { id: "positions", label: "Açık Pozisyonlar", short: "Pozisyon", icon: BriefcaseBusiness, el: Positions, group: "Genel" },
  { id: "scanner", label: "Coin Tarayıcı", short: "Tarayıcı", icon: Radar, el: Scanner, group: "Piyasa" },
  { id: "analyses", label: "AI Analizleri", short: "Analiz", icon: BrainCircuit, el: Analyses, group: "Piyasa" },
  { id: "history", label: "İşlem Geçmişi", short: "Geçmiş", icon: ReceiptText, el: History, group: "Raporlar" },
  { id: "report", label: "Kâr-Zarar Raporu", short: "Rapor", icon: LineChart, el: Report, group: "Raporlar" },
  { id: "notifications", label: "Bildirimler", short: "Bildirim", icon: Bell, el: Notifications, group: "Raporlar" },
  { id: "risk", label: "Risk Yönetimi", short: "Risk", icon: ShieldCheck, el: Risk, group: "Sistem" },
  { id: "settings", label: "Bot Ayarları", short: "Ayarlar", icon: SlidersHorizontal, el: Settings, group: "Sistem" },
  { id: "connections", label: "API Bağlantıları", short: "API", icon: Cable, el: Connections, group: "Sistem" },
  { id: "logs", label: "Sistem Günlükleri", short: "Günlük", icon: ScrollText, el: Logs, group: "Sistem" },
];
const TABS = ["home", "portfolio", "scanner", "positions"];

const routeId = () => {
  const h = location.hash.replace(/^#\/?/, "").split("?")[0];
  return ROUTES.some((r) => r.id === h) || h === "menu" ? h : "home";
};

function Brand({ sub = false }: { sub?: boolean }) {
  return (
    <>
      <span className="logo"><CandlestickChart /></span>
      {sub ? <div><b>AI Kripto Yöneticisi</b><span>Sanal portföy yönetimi</span></div> : <span>AI Kripto Yöneticisi</span>}
    </>
  );
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
    <main className="auth">
      <div className="card auth-card">
        <span className="logo lg" style={{ margin: "0 auto" }}><CandlestickChart /></span>
        <h1>AI Kripto Yöneticisi</h1>
        <p className="muted small">Piyasayı 7/24 izleyen, risk kontrollü portföy yöneticisi</p>
        <form onSubmit={submit}>
          <label className="lb" htmlFor="pw">Panel şifresi</label>
          <input id="pw" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
          {err && <div className="mt"><Banner kind="bad">{err}</Banner></div>}
          <button className="btn primary block mt" disabled={busy || !pw}>{busy ? "Giriş yapılıyor…" : "Giriş yap"}</button>
        </form>
        <div className="row mt" style={{ justifyContent: "center", gap: 8 }}><Badge kind="warn"><Lock size={11} /> Sanal mod</Badge><Badge>Gerçek para kilitli</Badge></div>
      </div>
    </main>
  );
}

function Alerts({ s }: { s: J }) {
  const b = s.bot, m = s.market;
  return (
    <>
      {b.emergency && <Banner kind="bad" icon={<AlertOctagon />}><b>Acil durdurma aktif.</b> Yeni alım yapılmaz. Risk Yönetimi sayfasından kaldırabilirsiniz.</Banner>}
      {m.shock_active && <Banner kind="bad" icon={<TrendingDown />}><b>Ani düşüş koruması:</b> {m.regime?.shock_reason ?? "BTC sert düştü"}. Yeni alımlar geçici olarak durduruldu.</Banner>}
      {b.safe_mode && <Banner kind="warn" icon={<ShieldAlert />}><b>Güvenli mod:</b> {b.safe_mode}. Yeni alım yapılmıyor.</Banner>}
      {m.scan_error && <Banner kind="warn">Piyasa verisi hatası: {m.scan_error}</Banner>}
    </>
  );
}

function Ribbon({ s }: { s: J }) {
  const b = s.bot, m = s.market;
  return (
    <div className="ribbon">
      <span className="paper-pill"><Lock size={12} /> SANAL İŞLEM · gerçek para kullanılmıyor</span>
      <Badge kind={b.enabled ? "ok" : ""} dot={b.enabled}>{b.enabled ? "Bot çalışıyor" : "Bot durdu"}</Badge>
      <Badge kind={m.ws_connected ? "ok" : "warn"}>{m.ws_connected ? "Canlı akış" : "REST yedek"}</Badge>
      {m.regime && <Badge kind={m.regime.direction === "Yükseliş" ? "ok" : m.regime.direction === "Düşüş" ? "bad" : ""}>BTC {m.regime.direction}</Badge>}
      <span className="xs dim">Son tarama {ago(m.last_scan_age_sec)}</span>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [route, setRoute] = useState(routeId());
  const [theme, setTheme] = useState<ThemePref>(getTheme());

  useEffect(() => {
    api.get("/auth/me").then((r) => setAuthed(r.authenticated)).catch(() => setAuthed(false));
    const un = () => setAuthed(false);
    const hc = () => { setRoute(routeId()); window.scrollTo(0, 0); };
    window.addEventListener("unauthorized", un);
    window.addEventListener("hashchange", hc);
    return () => { window.removeEventListener("unauthorized", un); window.removeEventListener("hashchange", hc); };
  }, []);

  const status = usePoll(() => (authed ? api.get("/status") : Promise.resolve(null)), 5000, [authed]);
  const notes = usePoll(() => (authed ? api.get("/notifications?limit=1") : Promise.resolve({ unread: 0 })), 15000, [authed, route]);
  const unread: number = notes.data?.unread ?? 0;

  const cycleTheme = () => {
    const next: ThemePref = theme === "system" ? "dark" : theme === "dark" ? "light" : "system";
    setTheme(next);
    applyTheme(next);
  };
  const ThemeIcon = theme === "dark" ? Moon : theme === "light" ? Sun : SunMoon;
  const themeLabel = theme === "dark" ? "Koyu tema" : theme === "light" ? "Açık tema" : "Sistem teması";

  if (authed === null) return <div className="auth"><span className="logo lg"><CandlestickChart /></span></div>;
  if (!authed) return <Login onDone={() => setAuthed(true)} />;

  const R = ROUTES.find((r) => r.id === route);
  const Page = R?.el;
  const logout = async () => { await api.post("/auth/logout"); location.hash = ""; location.reload(); };
  const groups = Array.from(new Set(ROUTES.map((r) => r.group)));

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Ana gezinme">
        <div className="brand"><Brand sub /></div>
        {groups.map((g) => (
          <div key={g}>
            <div className="nav-sec">{g}</div>
            {ROUTES.filter((r) => r.group === g).map((r) => (
              <a key={r.id} href={`#/${r.id}`} className={`nav ${route === r.id ? "on" : ""}`} aria-current={route === r.id ? "page" : undefined}>
                <r.icon size={18} />{r.label}{r.id === "notifications" && unread > 0 && <span className="cnt">{unread > 99 ? "99+" : unread}</span>}
              </a>
            ))}
          </div>
        ))}
        <div className="foot">
          <button className="nav" onClick={cycleTheme}><ThemeIcon size={18} />{themeLabel}</button>
          <button className="nav" onClick={logout}><LogOut size={18} />Çıkış yap</button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="brand-m"><Brand /></div>
          <span className="sp" />
          <button className="btn ghost icon sm" onClick={cycleTheme} aria-label={`Tema: ${themeLabel}`} title={themeLabel}><ThemeIcon /></button>
          <a href="#/notifications" className="btn ghost icon sm" style={{ position: "relative" }} aria-label={`Bildirimler${unread ? `, ${unread} okunmamış` : ""}`}>
            <Bell />{unread > 0 && <span style={{ position: "absolute", top: 2, right: 1, minWidth: 16, height: 16, borderRadius: 8, background: "var(--neg)", color: "#fff", fontSize: 10, fontWeight: 700, display: "grid", placeItems: "center", padding: "0 4px" }}>{unread > 9 ? "9+" : unread}</span>}
          </a>
        </header>
        <main className="content">
          {status.data && <><Ribbon s={status.data} /><Alerts s={status.data} /></>}
          {route === "menu" ? <MenuPage unread={unread} onLogout={logout} /> : Page ? <Page /> : <Loading />}
        </main>
      </div>

      <nav className="tabbar" aria-label="Alt menü">
        {TABS.map((id) => {
          const r = ROUTES.find((x) => x.id === id)!;
          return <a key={id} href={`#/${id}`} className={route === id ? "on" : ""} aria-current={route === id ? "page" : undefined}><r.icon size={21} />{r.short}</a>;
        })}
        <a href="#/menu" className={!TABS.includes(route) ? "on" : ""}><Menu size={21} />Menü</a>
      </nav>
    </div>
  );
}

function MenuPage({ unread, onLogout }: { unread: number; onLogout: () => void }) {
  const groups = Array.from(new Set(ROUTES.map((r) => r.group)));
  return (
    <>
      <PageHeader title="Menü" />
      {groups.map((g) => (
        <section key={g} className="card" style={{ overflow: "hidden" }}>
          <div className="nav-sec" style={{ display: "block", padding: "14px 18px 4px" }}>{g}</div>
          <ul className="list">
            {ROUTES.filter((r) => r.group === g).map((r) => (
              <li key={r.id}><a className="li click" href={`#/${r.id}`}><r.icon size={19} /><span className="grow bold">{r.label}</span>{r.id === "notifications" && unread > 0 && <Badge kind="bad">{unread}</Badge>}</a></li>
            ))}
          </ul>
        </section>
      ))}
      <button className="btn block" onClick={onLogout}><LogOut /> Çıkış yap</button>
    </>
  );
}
