import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

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

export function Card({ title, right, children, className = "" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <header className="card-h">
          <h2>{title}</h2>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="stat">
      <div className="stat-l">{label}</div>
      <div className={`stat-v ${tone ?? ""}`}>{value}</div>
      {sub && <div className="stat-s">{sub}</div>}
    </div>
  );
}

export function Badge({ children, kind = "" }: { children: ReactNode; kind?: string }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}

export function ScorePill({ score }: { score: number | null | undefined }) {
  if (score === null || score === undefined) return <span className="score none">-</span>;
  const k = score >= 85 ? "s-top" : score >= 70 ? "s-good" : score >= 50 ? "s-wait" : "s-no";
  return <span className={`score ${k}`}>{score.toFixed(0)}</span>;
}

export function riskKind(r: string | null | undefined) {
  return r === "Düşük" ? "ok" : r === "Orta" ? "warn" : r === "Yüksek" ? "bad" : "";
}

export function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="alert bad" role="alert">{message}</div>;
}

export function Loading() {
  return <div className="loading">Yükleniyor…</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Bar({ value, max, warnAt = 0.7, label }: { value: number; max: number; warnAt?: number; label?: string }) {
  const r = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const k = r >= 1 ? "bad" : r >= warnAt ? "warn" : "ok";
  return (
    <div className="bar" role="progressbar" aria-valuenow={Math.round(r * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <div className={`bar-f ${k}`} style={{ width: `${r * 100}%` }} />
    </div>
  );
}

/** Basit SVG çizgi grafik (kütüphanesiz) */
export function Spark({ values, height = 56 }: { values: number[]; height?: number }) {
  if (values.length < 2) return <div className="spark-empty">Grafik için veri toplanıyor…</div>;
  const w = 300;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(height - 4 - ((v - min) / span) * (height - 8)).toFixed(1)}`);
  const up = values[values.length - 1] >= values[0];
  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="spark" preserveAspectRatio="none" role="img" aria-label="Özkaynak grafiği">
      <polyline points={pts.join(" ")} fill="none" stroke={up ? "var(--pos)" : "var(--neg)"} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Confirm({ text, onYes, onNo, children }: { text: string; onYes: () => void; onNo: () => void; children?: ReactNode }) {
  return (
    <div className="modal" role="dialog" aria-modal="true">
      <div className="modal-b">
        <p>{text}</p>
        {children}
        <div className="row">
          <button className="btn" onClick={onNo}>Vazgeç</button>
          <button className="btn danger" onClick={onYes}>Onayla</button>
        </div>
      </div>
    </div>
  );
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="page-title">
      <h1>{children}</h1>
      {sub && <p>{sub}</p>}
    </div>
  );
}
