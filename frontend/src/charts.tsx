import { ReactNode, useId, useMemo, useRef, useState } from "react";
import { price as fmtPrice } from "./format";

/** Fare/dokunma konumundan veri indeksi */
function useHover(n: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [idx, setIdx] = useState<number | null>(null);
  const handlers = {
    onPointerMove: (e: React.PointerEvent) => {
      const r = ref.current?.getBoundingClientRect();
      if (!r || n < 2) return;
      setIdx(Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1)))));
    },
    onPointerLeave: () => setIdx(null),
  };
  return { ref, idx, handlers };
}

export function Sparkline({ values, up, height = 34 }: { values: number[]; up?: boolean; height?: number }) {
  const id = useId();
  if (values.length < 2) return null;
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * 100, height - 3 - ((v - min) / span) * (height - 6)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const color = (up ?? values[values.length - 1] >= values[0]) ? "var(--pos)" : "var(--neg)";
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" width="100%" height={height} aria-hidden>
      <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".28" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
      <path d={`${line} L100,${height} L0,${height} Z`} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

export function AreaChart({ points, height = 200, format, baseline }: { points: { label: string; v: number }[]; height?: number; format: (v: number) => string; baseline?: number }) {
  const id = useId();
  const n = points.length;
  const { ref, idx, handlers } = useHover(n);
  const calc = useMemo(() => {
    if (n < 2) return null;
    const vs = points.map((p) => p.v);
    let min = Math.min(...vs, baseline ?? Infinity), max = Math.max(...vs, baseline ?? -Infinity);
    const pad = (max - min || Math.abs(max) * 0.01 || 1) * 0.12;
    min -= pad; max += pad;
    const W = 600, H = height;
    const x = (i: number) => (i / (n - 1)) * W;
    const y = (v: number) => H - ((v - min) / (max - min)) * H;
    const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
    return { W, H, x, y, line, min, max };
  }, [points, n, height, baseline]);
  if (!calc) return <div className="muted small center" style={{ padding: "48px 0" }}>Grafik için veri toplanıyor…</div>;
  const up = points[n - 1].v >= points[0].v;
  const color = up ? "var(--pos)" : "var(--neg)";
  const hi = idx ?? n - 1;
  return (
    <div className="chart" ref={ref} {...handlers}>
      <svg viewBox={`0 0 ${calc.W} ${calc.H}`} preserveAspectRatio="none" style={{ height }} role="img" aria-label="Özkaynak grafiği">
        <defs><linearGradient id={id} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".3" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
        {[0.25, 0.5, 0.75].map((f) => <line key={f} x1="0" x2={calc.W} y1={calc.H * f} y2={calc.H * f} stroke="var(--border)" strokeDasharray="3 5" vectorEffect="non-scaling-stroke" />)}
        {baseline !== undefined && <line x1="0" x2={calc.W} y1={calc.y(baseline)} y2={calc.y(baseline)} stroke="var(--text-3)" strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />}
        <path d={`${calc.line} L${calc.W},${calc.H} L0,${calc.H} Z`} fill={`url(#${id})`} />
        <path d={calc.line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
        {idx !== null && <line x1={calc.x(idx)} x2={calc.x(idx)} y1="0" y2={calc.H} stroke="var(--border-2)" vectorEffect="non-scaling-stroke" />}
      </svg>
      <span style={{ position: "absolute", left: `${(hi / (n - 1)) * 100}%`, top: `${(calc.y(points[hi].v) / calc.H) * 100}%`, width: 10, height: 10, borderRadius: "50%", background: color, border: "2px solid var(--surface)", transform: "translate(-50%,-50%)", pointerEvents: "none" }} />
      {idx !== null && <div className="tip" style={{ left: `${Math.max(14, Math.min(86, (idx / (n - 1)) * 100))}%` }}><b>{format(points[idx].v)}</b><span>{points[idx].label}</span></div>}
      <div className="axis"><span>{points[0].label}</span><span className="mid">{format(Math.min(...points.map((p) => p.v)))} – {format(Math.max(...points.map((p) => p.v)))}</span><span>{points[n - 1].label}</span></div>
    </div>
  );
}

export function BarsChart({ data, height = 150, format }: { data: { label: string; v: number }[]; height?: number; format: (v: number) => string }) {
  const n = data.length;
  const { ref, idx, handlers } = useHover(n);
  if (n === 0) return null;
  const max = Math.max(...data.map((d) => Math.abs(d.v)), 1e-9);
  const W = 600, mid = height / 2, bw = Math.min(34, (W / n) * 0.62);
  return (
    <div className="chart" ref={ref} {...handlers}>
      <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" style={{ height }} role="img" aria-label="Günlük net sonuç">
        <line x1="0" x2={W} y1={mid} y2={mid} stroke="var(--border-2)" vectorEffect="non-scaling-stroke" />
        {data.map((d, i) => {
          const h = Math.max(2, (Math.abs(d.v) / max) * (mid - 6));
          const x = (i + 0.5) * (W / n) - bw / 2;
          return <rect key={d.label} x={x} y={d.v >= 0 ? mid - h : mid} width={bw} height={h} rx="3" fill={d.v >= 0 ? "var(--pos)" : "var(--neg)"} opacity={idx === null || idx === i ? 1 : 0.45} />;
        })}
      </svg>
      {idx !== null && <div className="tip" style={{ left: `${Math.max(14, Math.min(86, ((idx + 0.5) / n) * 100))}%` }}><b className={data[idx].v >= 0 ? "pos" : "neg"}>{format(data[idx].v)}</b><span>{data[idx].label}</span></div>}
      <div className="axis"><span>{data[0].label}</span><span>{data[n - 1].label}</span></div>
    </div>
  );
}

export function Donut({ parts, size = 150, center }: { parts: { label: string; v: number; color: string }[]; size?: number; center?: ReactNode }) {
  const total = parts.reduce((a, p) => a + p.v, 0);
  const r = size / 2 - 11, c = 2 * Math.PI * r;
  let acc = 0;
  return (
    <div className="ring" style={{ width: size, height: size }} role="img" aria-label="Portföy dağılımı">
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth="14" />
        {total > 0 && parts.map((p) => {
          const len = (p.v / total) * c;
          const el = <circle key={p.label} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={p.color} strokeWidth="14" strokeDasharray={`${Math.max(0, len - 2)} ${c}`} strokeDashoffset={-acc} />;
          acc += len;
          return el;
        })}
      </svg>
      {center && <div className="mid">{center}</div>}
    </div>
  );
}

export type ChartData = { t: number[]; o: number[]; h: number[]; l: number[]; c: number[]; v: number[]; ema21: (number | null)[]; ema50: (number | null)[]; bb_up: (number | null)[]; bb_low: (number | null)[]; levels: Record<string, number | null | undefined> };

const LEVEL_STYLE: Record<string, { color: string; label: string }> = {
  entry: { color: "var(--text-2)", label: "Giriş" }, stop: { color: "var(--neg)", label: "Stop" }, tp1: { color: "var(--pos)", label: "Hedef 1" },
  tp2: { color: "var(--pos)", label: "Hedef 2" }, support: { color: "var(--info)", label: "Destek" }, resistance: { color: "var(--warn)", label: "Direnç" },
};

export function CandleChart({ d, height = 330 }: { d: ChartData; height?: number }) {
  const n = d.t.length;
  const { ref, idx, handlers } = useHover(n);
  const W = 800, padR = 74, plotW = W - padR, volH = 54, H = height, priceH = H - volH - 8;
  const calc = useMemo(() => {
    let lo = Math.min(...d.l), hi = Math.max(...d.h);
    const span0 = hi - lo || hi * 0.01;
    // plan seviyeleri yalnızca görünür aralığın makul çevresindeyse eklenir
    for (const v of Object.values(d.levels)) if (typeof v === "number" && v > lo - span0 * 0.35 && v < hi + span0 * 0.35) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
    const y = (v: number) => priceH - ((v - lo) / (hi - lo)) * priceH;
    const x = (i: number) => ((i + 0.5) / n) * plotW;
    const vmax = Math.max(...d.v, 1e-9);
    const path = (a: (number | null)[]) => a.map((v, i) => (v === null ? "" : `${i && a[i - 1] !== null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join(" ");
    const band = d.bb_up.every((v, i) => v !== null && d.bb_low[i] !== null) ? [...d.bb_up.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v as number).toFixed(1)}`), ...d.bb_low.map((_, i) => `L${x(n - 1 - i).toFixed(1)},${y(d.bb_low[n - 1 - i] as number).toFixed(1)}`)].join(" ") + " Z" : "";
    return { lo, hi, y, x, vmax, path, band };
  }, [d, n, priceH, plotW]);
  const i = idx ?? n - 1;
  const bw = Math.max(1.5, (plotW / n) * 0.66);
  const dt = (ms: number) => new Date(ms).toLocaleString("tr-TR", { timeZone: "Europe/Istanbul", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  const lvlY = Object.entries(d.levels).filter(([k, v]) => typeof v === "number" && LEVEL_STYLE[k] && v >= calc.lo && v <= calc.hi).map(([, v]) => calc.y(v as number));
  const gridVals = [0.2, 0.4, 0.6, 0.8].map((f) => calc.lo + (calc.hi - calc.lo) * f).filter((v) => lvlY.every((y) => Math.abs(y - calc.y(v)) > 16));
  return (
    <div>
      <div className="row wrap small mono" style={{ gap: "6px 14px", marginBottom: 8 }}>
        <span className="dim">{dt(d.t[i])}</span>
        <span>A <b>{fmtPrice(d.o[i])}</b></span><span>Y <b>{fmtPrice(d.h[i])}</b></span><span>D <b>{fmtPrice(d.l[i])}</b></span>
        <span className={d.c[i] >= d.o[i] ? "pos" : "neg"}>K <b>{fmtPrice(d.c[i])}</b></span>
        <span style={{ color: "var(--accent)" }}>EMA21 {d.ema21[i] === null ? "–" : fmtPrice(d.ema21[i])}</span>
        <span style={{ color: "var(--warn)" }}>EMA50 {d.ema50[i] === null ? "–" : fmtPrice(d.ema50[i])}</span>
      </div>
      <div className="chart" ref={ref} {...handlers}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ height: "auto" }} role="img" aria-label="Fiyat grafiği">
          {gridVals.map((v) => <g key={v}><line x1="0" x2={plotW} y1={calc.y(v)} y2={calc.y(v)} stroke="var(--border)" strokeDasharray="3 6" /><text x={plotW + 8} y={calc.y(v) + 3.5} fontSize="10.5" fill="var(--text-3)" fontFamily="var(--mono)">{fmtPrice(v)}</text></g>)}
          {calc.band && <path d={calc.band} fill="var(--accent)" opacity=".06" />}
          {d.h.map((_, k) => {
            const up = d.c[k] >= d.o[k], col = up ? "var(--pos)" : "var(--neg)", x = calc.x(k);
            const top = calc.y(Math.max(d.o[k], d.c[k])), bot = calc.y(Math.min(d.o[k], d.c[k]));
            return (
              <g key={k} opacity={idx === null || idx === k ? 1 : 0.8}>
                <line x1={x} x2={x} y1={calc.y(d.h[k])} y2={calc.y(d.l[k])} stroke={col} strokeWidth="1" />
                <rect x={x - bw / 2} y={top} width={bw} height={Math.max(1, bot - top)} fill={col} rx="0.8" />
                <rect x={x - bw / 2} y={H - (d.v[k] / calc.vmax) * volH} width={bw} height={(d.v[k] / calc.vmax) * volH} fill={col} opacity=".28" />
              </g>
            );
          })}
          <path d={calc.path(d.ema21)} fill="none" stroke="var(--accent)" strokeWidth="1.6" />
          <path d={calc.path(d.ema50)} fill="none" stroke="var(--warn)" strokeWidth="1.6" />
          {Object.entries(d.levels).map(([k, v]) => {
            if (typeof v !== "number" || v < calc.lo || v > calc.hi || !LEVEL_STYLE[k]) return null;
            const st = LEVEL_STYLE[k];
            return (
              <g key={k}>
                <line x1="0" x2={plotW} y1={calc.y(v)} y2={calc.y(v)} stroke={st.color} strokeDasharray={k === "support" || k === "resistance" ? "2 4" : "7 4"} strokeWidth="1.2" opacity=".85" />
                <rect x={plotW + 2} y={calc.y(v) - 8} width={padR - 4} height="16" rx="4" fill={st.color} opacity=".18" />
                <text x={plotW + 7} y={calc.y(v) + 3.5} fontSize="10" fontWeight="700" fill={st.color} fontFamily="var(--mono)">{st.label}</text>
              </g>
            );
          })}
          {idx !== null && <line x1={calc.x(idx)} x2={calc.x(idx)} y1="0" y2={H} stroke="var(--border-2)" />}
        </svg>
      </div>
    </div>
  );
}
