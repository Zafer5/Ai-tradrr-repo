import { useState } from "react";
import { api, J } from "./api";
import { CandleChart, ChartData } from "./charts";
import { pct, price, usd } from "./format";
import { Badge, CoinCell, Banner, Segmented, Sheet, ScoreRing, Skeleton, Tags, riskKind, usePoll } from "./ui";

const TFS = [{ id: "15m", label: "15dk" }, { id: "1h", label: "1sa" }, { id: "4h", label: "4sa" }, { id: "1d", label: "Günlük" }];

/** Coin detayı: mum grafiği + AI özeti. Tarayıcı, analiz ve portföy ekranlarından açılır. */
export function CoinSheet({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const [tf, setTf] = useState("1h");
  const chart = usePoll<ChartData>(() => api.get(`/market/${symbol}/chart?tf=${tf}&limit=110`), 20000, [tf, symbol]);
  const an = usePoll<J>(() => api.get(`/analyses/${symbol}`), 20000, [symbol]);
  const a = an.data;
  return (
    <Sheet wide onClose={onClose} title={<CoinCell symbol={symbol} sub={a ? `${a.trend} · ${a.label}` : "Grafik ve analiz"} />}>
      <div className="row between wrap" style={{ marginBottom: 10 }}>
        <Segmented value={tf} options={TFS} onChange={setTf} />
        <span className="xs dim">EMA21 <i style={{ color: "var(--accent)" }}>━</i> · EMA50 <i style={{ color: "var(--warn)" }}>━</i></span>
      </div>
      {chart.data ? <CandleChart d={chart.data} /> : chart.error ? <Banner kind="bad">{chart.error}</Banner> : <Skeleton h={330} r={14} />}
      {a && (
        <>
          <div className="divider" />
          <div className="row" style={{ gap: 16, alignItems: "flex-start" }}>
            <ScoreRing score={a.score} size={64} />
            <div className="grow">
              <div className="row wrap" style={{ gap: 8 }}><b>{a.label}</b><Badge kind={riskKind(a.risk)}>Risk: {a.risk}</Badge>{a.held && <Badge kind="warn">Portföyde</Badge>}</div>
              <Tags tags={a.tags} />
              <dl className="kv mt">
                <dt>Satış uygunluğu · Düşüş riski</dt><dd className="num">{usd(a.sell_fit, 0)} · {usd(a.downside_risk, 0)}</dd>
                <dt>Beklenen risk/getiri (brüt)</dt><dd className="num">1 : {usd(a.expected_rr, 2)}</dd>
                <dt>Stop → Giriş → Hedefler</dt><dd className="num">{price(a.stop)} → {price(a.entry)} → {price(a.tp1)} / {price(a.tp2)}</dd>
                <dt>24s değişim</dt><dd className="num">{a.change_pct === null ? "-" : pct(a.change_pct, 1, true)}</dd>
              </dl>
            </div>
          </div>
          <ul className="small muted" style={{ margin: "14px 0 0", paddingLeft: 18 }}>{a.rationale.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
          {a.warnings.length > 0 && <div className="mt"><Banner kind="warn"><ul style={{ margin: 0, paddingLeft: 16 }}>{Array.from(new Set(a.warnings as string[])).map((w, i) => <li key={i}>{w}</li>)}</ul></Banner></div>}
        </>
      )}
    </Sheet>
  );
}
