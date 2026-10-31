import { useState } from "react";
import { api, J } from "../api";
import { coin, pct, price, signed, time, tone, usd } from "../format";
import { Card, Confirm, Empty, ErrorBox, Loading, riskKind, ScorePill, Spark, Stat, Badge, usePoll } from "../ui";

export default function Home() {
  const { data: d, error, reload } = usePoll(() => api.get("/dashboard"), 5000);
  const daily = usePoll(() => api.get("/reports/daily"), 60000);
  const pf = usePoll(() => api.get("/portfolio"), 15000);
  const [confirmEmergency, setConfirmEmergency] = useState(false);
  const [closeAll, setCloseAll] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const a = d.account;
  const b = d.bot;

  const toggle = async () => {
    setMsg(null);
    try {
      await api.post(b.enabled ? "/bot/stop" : "/bot/start");
      reload();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  const emergency = async () => {
    setConfirmEmergency(false);
    const r = await api.post("/bot/emergency-stop", { close_positions: closeAll });
    setMsg(`Acil durdurma uygulandı. Kapatılan pozisyon: ${r.closed_positions}`);
    reload();
  };

  return (
    <>
      <ErrorBox message={error} />
      <Card className="hero">
        <div className="muted small">Toplam sanal bakiye</div>
        <div className="hero-v">{usd(a.equity)} <small>USDT</small></div>
        <div className={`hero-s ${tone(a.total_pnl)}`}>
          Toplam kâr/zarar: {signed(a.total_pnl)} USDT ({pct(a.total_pnl_pct, 2, true)})
        </div>
        <Spark values={d.equity_curve.map((p: J) => p.equity)} />
        <div className="row mt">
          <button className={`btn ${b.enabled ? "" : "primary"} grow`} onClick={toggle} disabled={b.emergency}>
            {b.enabled ? "⏸ Botu durdur" : "▶ Botu başlat"}
          </button>
          <button className="btn danger" onClick={() => setConfirmEmergency(true)}>🛑 Acil durdur</button>
        </div>
        {msg && <div className="alert warn mt">{msg}</div>}
      </Card>

      <div className="grid2">
        <Stat label="Günlük kâr/zarar" value={`${signed(a.day_pnl)} USDT`} sub={pct(a.day_pnl_pct, 2, true)} tone={tone(a.day_pnl)} />
        <Stat label="Bugün gerçekleşen" value={`${signed(d.realized_today)} USDT`} tone={tone(d.realized_today)} />
        <Stat label="Açık işlemler" value={d.open_positions.length} />
        <Stat label="Takip edilen coin" value={d.tracked_coins} />
        <Stat label="Günlük işlem sayısı" value={d.trades_today} />
        <Stat label="Komisyon toplamı" value={`${usd(d.fees_total, 4)} USDT`} />
      </div>

      {pf.data && pf.data.items.length > 0 && (
        <Card title="Mevcut coinlerim" right={<a href="#/portfolio" className="link">Detay →</a>}>
          <div className="between"><span>Portföy değeri</span><b>{usd(pf.data.totals.value)} USDT</b></div>
          <div className="between"><span>Gerçekleşmemiş K/Z</span><b className={tone(pf.data.totals.unrealized_pnl)}>{signed(pf.data.totals.unrealized_pnl)} USDT</b></div>
        </Card>
      )}

      <Card title="En iyi fırsatlar" right={<a href="#/analyses" className="link">Tümü →</a>}>
        {d.top_opportunities.length === 0 ? (
          <Empty>Henüz analiz yok. İlk tarama tamamlanınca burada görünür.</Empty>
        ) : (
          <ul className="list">
            {d.top_opportunities.map((o: J) => (
              <li key={o.symbol} className="li">
                <ScorePill score={o.score} />
                <div className="grow">
                  <strong>{coin(o.symbol)}</strong> <span className="muted small">{o.label}</span>
                  <div className="small muted">{o.trend} · <Badge kind={riskKind(o.risk)}>Risk: {o.risk}</Badge></div>
                </div>
                <div className="right"><div>{price(o.price)}</div></div>
              </li>
            ))}
          </ul>
        )}
        <p className="small muted">Puan tek başına alım emri değildir; her alım ayrıca risk kontrolünden geçer.</p>
      </Card>

      <Card title="Açık işlemler" right={<a href="#/positions" className="link">Detay →</a>}>
        {d.open_positions.length === 0 ? (
          <Empty>Açık pozisyon yok.</Empty>
        ) : (
          <ul className="list">
            {d.open_positions.map((p: J) => (
              <li key={p.id} className="li">
                <div className="grow"><strong>{coin(p.symbol)}</strong><div className="small muted">Giriş {price(p.entry_price)} → Şimdi {price(p.current_price)}</div></div>
                <div className={`right ${tone(p.unrealized_pnl)}`}>{signed(p.unrealized_pnl)} USDT<div className="small">{pct(p.unrealized_pct, 2, true)}</div></div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {daily.data && (
        <Card title="Günlük işlem raporu"><p className="small" style={{ whiteSpace: "pre-wrap" }}>{daily.data.body}</p></Card>
      )}

      <Card title="Son işlemler" right={<a href="#/history" className="link">Geçmiş →</a>}>
        {d.recent_trades.length === 0 ? (
          <Empty>Henüz kapanmış işlem yok.</Empty>
        ) : (
          <ul className="list">
            {d.recent_trades.map((p: J) => (
              <li key={p.id} className="li">
                <div className="grow"><strong>{coin(p.symbol)}</strong><div className="small muted">{p.close_reason_tr} · {time(p.closed_at)}</div></div>
                <div className={`right ${tone(p.realized_pnl)}`}>{signed(p.realized_pnl, 3)} USDT</div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <p className="small muted center">Binance istek ağırlığı (son 1 dk): {d.market.used_weight_1m ?? "-"} / 6000</p>

      {confirmEmergency && (
        <Confirm text="Acil durdurma: bot kapanır ve yeni alım tamamen engellenir. Devam edilsin mi?" onYes={emergency} onNo={() => setConfirmEmergency(false)}>
          <label className="check"><input type="checkbox" checked={closeAll} onChange={(e) => setCloseAll(e.target.checked)} /> Açık pozisyonları da piyasa fiyatından kapat</label>
        </Confirm>
      )}
    </>
  );
}
