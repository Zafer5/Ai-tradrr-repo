import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Inbox, X, XCircle } from "lucide-react";
import { ApiError } from "./api";

/* ---------------- veri çekme ---------------- */
/** Düzenli aralıkla veri çeker; sekme arka plandayken durur. */
export function usePoll<T>(fn: () => Promise<T>, ms = 5000, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const load = useCallback(async () => {
    try {
      setData(await fnRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Sunucuya ulaşılamıyor");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    load();
    if (!ms) return;
    const id = setInterval(() => {
      if (!document.hidden) load();
    }, ms);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, load, ...deps]);

  return { data, error, loading, reload: load };
}

/* ---------------- bildirim (toast) ---------------- */
type ToastKind = "ok" | "bad" | "warn" | "info";
const ToastCtx = createContext<(text: string, kind?: ToastKind) => void>(() => undefined);
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; text: string; kind: ToastKind }[]>([]);
  const push = useCallback((text: string, kind: ToastKind = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x.slice(-2), { id, text, kind }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "bad" ? 8000 : 4500);
  }, []);
  const Icon = { ok: CheckCircle2, bad: XCircle, warn: AlertTriangle, info: Info };
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => {
          const I = Icon[t.kind];
          return (
            <div key={t.id} className={`toast ${t.kind}`}>
              <I />
              <div>{t.text}</div>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------------- yüzeyler ---------------- */
export function Card({ title, subtitle, icon, actions, children, className = "", flush = false, pad = true }: {
  title?: ReactNode; subtitle?: ReactNode; icon?: ReactNode; actions?: ReactNode; children?: ReactNode; className?: string; flush?: boolean; pad?: boolean;
}) {
  return (
    <section className={`card ${flush ? "flush" : ""} ${className}`}>
      {(title || actions) && (
        <header className="card-h">
          {icon && <span className="ic" aria-hidden>{icon}</span>}
          <div className="grow">
            <h2>{title}</h2>
            {subtitle && <div className="sub">{subtitle}</div>}
          </div>
          {actions}
        </header>
      )}
      {children !== undefined && <div className={pad ? "card-b" : ""}>{children}</div>}
    </section>
  );
}

export function KPI({ label, value, unit, delta, tone, icon, spark }: {
  label: string; value: ReactNode; unit?: string; delta?: ReactNode; tone?: "pos" | "neg" | ""; icon?: ReactNode; spark?: ReactNode;
}) {
  return (
    <div className="card kpi">
      <div className="l">{icon}{label}</div>
      <div className={`v ${tone ?? ""}`}>{value}{unit && <small>{unit}</small>}</div>
      {delta && <div className={`d ${tone ?? ""}`}>{delta}</div>}
      {spark && <div className="sp">{spark}</div>}
    </div>
  );
}

export function Badge({ children, kind = "", dot = false }: { children: ReactNode; kind?: string; dot?: boolean }) {
  return <span className={`badge ${kind}`}>{dot && <i className="dot live" />}{children}</span>;
}

export function riskKind(r: string | null | undefined) {
  return r === "Düşük" ? "ok" : r === "Orta" ? "warn" : r === "Yüksek" ? "bad" : "";
}

export function ScoreRing({ score, size = 46 }: { score: number | null | undefined; size?: number }) {
  const has = score !== null && score !== undefined;
  const s = has ? Math.max(0, Math.min(100, score!)) : 0;
  const color = !has ? "var(--text-3)" : s >= 85 ? "var(--pos)" : s >= 70 ? "var(--accent)" : s >= 50 ? "var(--warn)" : "var(--text-3)";
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  return (
    <span className="ring" style={{ width: size, height: size }} role="img" aria-label={has ? `AI puanı ${s.toFixed(0)} / 100` : "Puan yok"}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth="4" />
        {has && <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="4" strokeLinecap="round" strokeDasharray={`${(s / 100) * c} ${c}`} />}
      </svg>
      <b className="sc" style={{ fontSize: size * 0.32, color }}>{has ? s.toFixed(0) : "–"}</b>
    </span>
  );
}

export function Tags({ tags }: { tags?: string[] }) {
  if (!tags || tags.length === 0) return null;
  return (
    <div className="tags">
      {tags.map((t) => <span key={t} className={`tag ${t === "Aşırı yükselmiş" ? "hot" : t === "Yeni trend" || t === "Toparlanma" ? "good" : ""}`}>{t}</span>)}
    </div>
  );
}

const PALETTE = ["#6c86ff", "#2dd4bf", "#f6bb4b", "#f4586d", "#a78bfa", "#38bdf8", "#fb923c", "#4ade80", "#e879f9", "#94a3b8"];
export function CoinAvatar({ symbol, size = 34 }: { symbol: string; size?: number }) {
  const base = symbol.replace(/USDT$/, "");
  let h = 0;
  for (const ch of base) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const c = PALETTE[h % PALETTE.length];
  return <span className="av" style={{ width: size, height: size, background: `linear-gradient(135deg, ${c}, color-mix(in srgb, ${c} 55%, #000))`, fontSize: size * 0.32 }} aria-hidden>{base.slice(0, 4)}</span>;
}

export function CoinCell({ symbol, sub }: { symbol: string; sub?: ReactNode }) {
  return (
    <div className="coin">
      <CoinAvatar symbol={symbol} />
      <div style={{ minWidth: 0 }}><b>{symbol.replace(/USDT$/, "")}</b><span>{sub ?? "USDT"}</span></div>
    </div>
  );
}

export function Progress({ value, max, tone = "" }: { value: number; max: number; tone?: string }) {
  const r = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  return <div className="bar" role="progressbar" aria-valuenow={Math.round(r * 100)} aria-valuemin={0} aria-valuemax={100}><i className={tone} style={{ width: `${r * 100}%` }} /></div>;
}

export function Meter({ label, value, max, text, warnAt = 0.7 }: { label: string; value: number; max: number; text: ReactNode; warnAt?: number }) {
  const r = max > 0 ? value / max : 0;
  return (
    <div className="meter">
      <div className="between"><span className="muted">{label}</span><b className="num">{text}</b></div>
      <Progress value={value} max={max} tone={r >= 1 ? "bad" : r >= warnAt ? "warn" : ""} />
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, full = false }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; full?: boolean }) {
  return (
    <div className={`seg ${full ? "full" : ""}`} role="tablist">
      {options.map((o) => <button key={o.id} role="tab" aria-selected={value === o.id} className={value === o.id ? "on" : ""} onClick={() => onChange(o.id)}>{o.label}</button>)}
    </div>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <span className="switch">
      <input type="checkbox" role="switch" aria-label={label} checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <i />
    </span>
  );
}

export function Banner({ kind = "info", children, icon }: { kind?: "info" | "warn" | "bad" | "ok"; children: ReactNode; icon?: ReactNode }) {
  const I = { info: Info, warn: AlertTriangle, bad: XCircle, ok: CheckCircle2 }[kind];
  return <div className={`banner ${kind}`} role={kind === "bad" ? "alert" : "status"}>{icon ?? <I />}<div>{children}</div></div>;
}

export const ErrorBox = ({ message }: { message: string | null }) => (message ? <Banner kind="bad">{message}</Banner> : null);

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-h">
      <div className="grow"><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
      {actions}
    </div>
  );
}

export function Empty({ title, children, icon }: { title?: ReactNode; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="empty">
      <div className="ei">{icon ?? <Inbox size={22} />}</div>
      {title && <b>{title}</b>}
      {children && <p>{children}</p>}
    </div>
  );
}

export function Skeleton({ h = 16, w = "100%", r }: { h?: number; w?: number | string; r?: number }) {
  return <div className="skel" style={{ height: h, width: w, borderRadius: r }} aria-hidden />;
}

export function Loading() {
  return (
    <div className="col" aria-busy="true" aria-label="Yükleniyor">
      <Skeleton h={30} w="40%" />
      <div className="grid g4"><Skeleton h={92} r={16} /><Skeleton h={92} r={16} /><Skeleton h={92} r={16} /><Skeleton h={92} r={16} /></div>
      <Skeleton h={240} r={16} />
    </div>
  );
}

/* ---------------- sheet / onay ---------------- */
export function Sheet({ title, onClose, children, footer, wide = false }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", k); document.body.style.overflow = prev; };
  }, [onClose]);
  return (
    <div className="sheet-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`sheet ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}>
        <div className="sheet-h"><h2>{title}</h2><button className="btn ghost icon sm" onClick={onClose} aria-label="Kapat"><X /></button></div>
        <div className="sheet-b">{children}</div>
        {footer && <div className="sheet-f">{footer}</div>}
      </div>
    </div>
  );
}

export function Confirm({ title = "Onay", text, onYes, onNo, yesLabel = "Onayla", danger = true, children }: { title?: string; text: string; onYes: () => void; onNo: () => void; yesLabel?: string; danger?: boolean; children?: ReactNode }) {
  return (
    <Sheet title={title} onClose={onNo} footer={<><button className="btn" onClick={onNo}>Vazgeç</button><button className={`btn ${danger ? "danger" : "primary"}`} onClick={onYes}>{yesLabel}</button></>}>
      <p className="muted">{text}</p>
      {children}
    </Sheet>
  );
}
