import { useEffect, useState } from "react";
import { api, J } from "../api";
import { coin, pct, price, timeFull, usd } from "../format";
import { Badge, Card, Empty, ErrorBox, Loading, PageTitle, riskKind, ScorePill, usePoll } from "../ui";

function Detail({ a }: { a: J }) {
  return (
    <div className="detail">
      <p><strong>Gerekçe</strong></p>
      <ul className="bullets">{a.rationale.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
      {a.warnings.length > 0 && (
        <>
          <p><strong>Uyarılar</strong></p>
          <ul className="bullets warn">{Array.from(new Set(a.warnings as string[])).map((r, i) => <li key={i}>{r}</li>)}</ul>
        </>
      )}
      <p><strong>Plan (öneri)</strong></p>
      <div className="kv">
        <span>Giriş</span><b>{price(a.entry)}</b>
        <span>Stop-loss</span><b className="neg">{price(a.stop)} ({pct((a.stop / a.entry - 1) * 100, 2)})</b>
        <span>1. hedef</span><b className="pos">{price(a.tp1)} ({pct((a.tp1 / a.entry - 1) * 100, 2, true)})</b>
        <span>2. hedef</span><b className="pos">{price(a.tp2)} ({pct((a.tp2 / a.entry - 1) * 100, 2, true)})</b>
        <span>ATR (1sa)</span><b>{usd(a.atr_pct)}%</b>
      </div>
      <div className="tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Grafik</th><th>Puan</th><th>Trend</th><th className="r">RSI</th><th className="r">MACD</th><th className="r">Hacim</th></tr></thead>
          <tbody>
            {Object.entries(a.tf as Record<string, J>).map(([tf, s]) => (
              <tr key={tf}>
                <td>{tf}</td><td>{usd(s.score, 0)}</td><td>{s.trend}</td><td className="r">{usd(s.rsi, 0)}</td>
                <td className="r">{s.macd_hist > 0 ? "▲" : "▼"}</td><td className="r">{s.vol_ratio ? `${usd(s.vol_ratio, 1)}x` : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Analyses() {
  const { data: d, error } = usePoll(() => api.get("/analyses"), 10000);
  const perf = usePoll(() => api.get("/ai/performance"), 60000);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    const m = /[?&]s=([A-Z0-9]+)/.exec(location.hash);
    if (m) setOpen(m[1]);
  }, []);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const items: J[] = d.items;
  return (
    <>
      <PageTitle sub="0-100 puan: 85+ çok güçlü · 70-84 değerlendirilebilir · 50-69 bekle · 50 altı işlem yapma">Yapay Zekâ Analizleri</PageTitle>
      <div className="alert info">Bu puanlama kural tabanlı bir modeldir ve kâr garantisi vermez. Puan tek başına emir göndermez; her alım bağımsız risk kontrolünden geçer.</div>
      <Card>
        {items.length === 0 ? <Empty>Analiz bekleniyor…</Empty> : (
          <ul className="list">
            {items.map((a) => (
              <li key={a.symbol} className="li col" id={a.symbol}>
                <button className="li-btn" onClick={() => setOpen(open === a.symbol ? null : a.symbol)} aria-expanded={open === a.symbol}>
                  <ScorePill score={a.eligible ? a.score : null} />
                  <div className="grow left">
                    <strong>{coin(a.symbol)}</strong> <span className="muted small">{a.eligible ? a.label : "Analiz dışı"}</span>
                    <div className="small muted">{a.eligible ? <>{a.trend} · <Badge kind={riskKind(a.risk)}>Risk: {a.risk}</Badge></> : a.skip_reason}</div>
                  </div>
                  <span className="muted">{open === a.symbol ? "▲" : "▼"}</span>
                </button>
                {open === a.symbol && a.eligible && <Detail a={a} />}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Karar günlüğü (risk kontrolü sonuçları)">
        {d.decisions.length === 0 ? <Empty>Henüz alım değerlendirmesi yapılmadı. Bot açıkken ve puan eşiği aşılınca burada görünür.</Empty> : (
          <ul className="list">
            {d.decisions.map((x: J, i: number) => (
              <li key={i} className="li col">
                <div><Badge kind={x.approved ? "ok" : "bad"}>{x.approved ? "ONAYLANDI" : "REDDEDİLDİ"}</Badge> <strong>{coin(x.symbol)}</strong> <span className="muted small">puan {usd(x.score, 0)} · {timeFull(new Date(x.ts * 1000).toISOString())}</span></div>
                <div className="small muted">{x.reasons.join(" · ")}</div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="AI karar performansı (ölçüm)">
        {!perf.data || perf.data.bands.every((b: J) => b.n === 0) ? <Empty>Sonuç ölçümü için en az 1 saat veri gerekir.</Empty> : (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Puan</th><th className="r">Adet</th><th className="r">1sa ort.</th><th className="r">1sa isabet</th><th className="r">4sa ort.</th></tr></thead>
            <tbody>{perf.data.bands.map((b: J) => (
              <tr key={b.band}><td>{b.band}</td><td className="r">{b.n}</td><td className="r">{pct(b.avg_ret_1h, 2, true)}</td><td className="r">{pct(b.hit_rate_1h, 0)}</td><td className="r">{pct(b.avg_ret_4h, 2, true)}</td></tr>
            ))}</tbody></table></div>
        )}
        <p className="small muted">{perf.data?.note}</p>
      </Card>
    </>
  );
}
