import { useEffect, useState } from "react";
import { BrainCircuit, ChevronDown, ChartCandlestick, ClipboardCheck, ScanSearch, Target } from "lucide-react";
import { api, J } from "../api";
import { CoinSheet } from "../components";
import { pct, price, timeFull, usd } from "../format";
import { Badge, Banner, Card, Empty, ErrorBox, Loading, PageHeader, Progress, ScoreRing, Tags, riskKind, usePoll } from "../ui";

function Fit({ label, v, tone }: { label: string; v: number; tone: string }) {
  return <div style={{ flex: 1, minWidth: 110 }}><div className="between small"><span className="muted">{label}</span><b className="num">{usd(v, 0)}</b></div><div style={{ marginTop: 6 }}><Progress value={v} max={100} tone={tone} /></div></div>;
}

function Detail({ a, onChart }: { a: J; onChart: () => void }) {
  return (
    <div style={{ padding: "4px 18px 18px" }}>
      <div className="row wrap" style={{ gap: 18, marginBottom: 14 }}>
        <Fit label="Alım uygunluğu" v={a.score} tone="accent" /><Fit label="Satış uygunluğu" v={a.sell_fit} tone="warn" /><Fit label="Düşüş riski" v={a.downside_risk} tone="bad" />
      </div>
      <div className="grid split-even" style={{ gap: 18 }}>
        <div>
          <div className="small bold" style={{ marginBottom: 6 }}>Gerekçe</div>
          <ul className="small muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>{a.rationale.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
          {a.warnings.length > 0 && <div className="mt"><Banner kind="warn"><ul style={{ margin: 0, paddingLeft: 16 }}>{Array.from(new Set(a.warnings as string[])).map((w, i) => <li key={i}>{w}</li>)}</ul></Banner></div>}
        </div>
        <div>
          <div className="small bold" style={{ marginBottom: 6 }}>Plan (öneri) · brüt risk/getiri 1 : {usd(a.expected_rr, 2)}</div>
          <dl className="kv">
            <dt>Giriş</dt><dd className="num">{price(a.entry)}</dd>
            <dt>Stop-loss</dt><dd className="num neg">{price(a.stop)} ({pct((a.stop / a.entry - 1) * 100, 2)})</dd>
            <dt>1. hedef</dt><dd className="num pos">{price(a.tp1)} ({pct((a.tp1 / a.entry - 1) * 100, 2, true)})</dd>
            <dt>2. hedef</dt><dd className="num pos">{price(a.tp2)} ({pct((a.tp2 / a.entry - 1) * 100, 2, true)})</dd>
            <dt>ATR (1sa)</dt><dd className="num">{usd(a.atr_pct)}%</dd>
          </dl>
          <button className="btn sm mt" onClick={onChart}><ChartCandlestick /> Grafiği aç</button>
        </div>
      </div>
      <div className="tbl-wrap mt"><table className="tbl"><thead><tr><th>Grafik</th><th>Puan</th><th>Trend</th><th className="r">RSI</th><th className="r">MACD</th><th className="r">Hacim</th><th className="r">ATR</th></tr></thead>
        <tbody>{Object.entries(a.tf as Record<string, J>).map(([tf, s]) => (
          <tr key={tf}><td className="bold">{tf}</td><td className="mono">{usd(s.score, 0)}</td><td>{s.trend}</td><td className="r">{usd(s.rsi, 0)}</td><td className={`r ${s.macd_hist > 0 ? "pos" : "neg"}`}>{s.macd_hist > 0 ? "▲" : "▼"}</td><td className="r">{s.vol_ratio ? `${usd(s.vol_ratio, 1)}x` : "-"}</td><td className="r">{usd(s.atr_pct)}%</td></tr>
        ))}</tbody></table></div>
    </div>
  );
}

export default function Analyses() {
  const { data: d, error } = usePoll(() => api.get("/analyses"), 10000);
  const perf = usePoll(() => api.get("/ai/performance"), 60000);
  const [open, setOpen] = useState<string | null>(null);
  const [sheet, setSheet] = useState<string | null>(null);
  useEffect(() => { const m = /[?&]s=([A-Z0-9]+)/.exec(location.hash); if (m) setOpen(m[1]); }, []);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const items: J[] = d.items;
  return (
    <>
      <PageHeader title="Yapay Zekâ Analizleri" subtitle="0-100 puan: 85+ çok güçlü · 70-84 değerlendirilebilir · 50-69 bekle · 50 altı işlem yapma." />
      <Banner kind="info">Bu puanlama kural tabanlı bir modeldir ve kâr garantisi vermez. Puan tek başına emir göndermez; her alım bağımsız risk kontrolünden geçer.</Banner>
      <Card flush icon={<BrainCircuit />} title="Coin analizleri" subtitle={`${items.length} coin`}>
        {items.length === 0 ? <Empty title="Analiz bekleniyor" /> : (
          <ul className="list">
            {items.map((a) => (
              <li key={a.symbol} id={a.symbol}>
                <div className="li click" role="button" tabIndex={0} aria-expanded={open === a.symbol} onClick={() => setOpen(open === a.symbol ? null : a.symbol)} onKeyDown={(e) => e.key === "Enter" && setOpen(open === a.symbol ? null : a.symbol)}>
                  <ScoreRing score={a.eligible ? a.score : null} />
                  <div className="grow"><div className="row wrap" style={{ gap: 8 }}><b>{a.symbol.replace("USDT", "")}</b>{a.eligible ? <><Badge kind={riskKind(a.risk)}>{a.risk}</Badge>{a.held && <Badge kind="warn">Portföyde</Badge>}</> : <Badge>Analiz dışı</Badge>}</div>
                    <div className="xs dim" style={{ margin: "2px 0 4px" }}>{a.eligible ? `${a.trend} · ${a.label}` : a.skip_reason}</div><Tags tags={a.tags} /></div>
                  {a.eligible && <ChevronDown style={{ transform: open === a.symbol ? "rotate(180deg)" : "none", transition: ".2s" }} className="dim" />}
                </div>
                {open === a.symbol && a.eligible && <Detail a={a} onChart={() => setSheet(a.symbol)} />}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <div className="grid split-even">
        <Card title="Karar günlüğü" icon={<ClipboardCheck />} subtitle="Risk kontrolü sonuçları" flush>
          {d.decisions.length === 0 ? <Empty title="Henüz değerlendirme yok">Bot açıkken ve puan eşiği aşılınca burada görünür.</Empty> : (
            <ul className="list">{d.decisions.map((x: J, i: number) => (
              <li key={i} className="li stack">
                <div className="between"><span className="row" style={{ gap: 8 }}><Badge kind={x.approved ? "ok" : "bad"}>{x.approved ? "Onaylandı" : "Reddedildi"}</Badge><b>{x.symbol.replace("USDT", "")}</b><span className="xs dim">puan {usd(x.score, 0)}</span></span><span className="xs dim">{timeFull(new Date(x.ts * 1000).toISOString())}</span></div>
                <div className="small muted">{x.reasons.join(" · ")}</div>
              </li>))}</ul>
          )}
        </Card>
        <Card title="AI karar performansı" icon={<Target />} subtitle="Ölçüm amaçlı; sistem kendi stratejisini değiştirmez">
          {!perf.data || perf.data.bands.every((b: J) => b.n === 0) ? <Empty icon={<ScanSearch size={22} />} title="Veri toplanıyor">Sonuç ölçümü için en az 1 saat gerekir.</Empty> : (
            <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Puan</th><th className="r">Adet</th><th className="r">1sa ort.</th><th className="r">İsabet</th><th className="r">4sa ort.</th></tr></thead>
              <tbody>{perf.data.bands.map((b: J) => <tr key={b.band}><td className="bold">{b.band}</td><td className="r">{b.n}</td><td className="r">{pct(b.avg_ret_1h, 2, true)}</td><td className="r">{pct(b.hit_rate_1h, 0)}</td><td className="r">{pct(b.avg_ret_4h, 2, true)}</td></tr>)}</tbody></table></div>
          )}
          <p className="xs dim mt">{perf.data?.note}</p>
        </Card>
      </div>
      {sheet && <CoinSheet symbol={sheet} onClose={() => setSheet(null)} />}
    </>
  );
}
