import { useState } from "react";
import { Activity, ArrowDownRight, ArrowUpRight, BriefcaseBusiness, ChevronRight, Coins, Gauge, Pause, Play, Power, Radar, Receipt, Sparkles, Wallet } from "lucide-react";
import { api, J } from "../api";
import { AreaChart } from "../charts";
import { CoinSheet } from "../components";
import { coin, pct, price, signed, time, tone, usd } from "../format";
import { Badge, Card, CoinCell, Confirm, Empty, ErrorBox, KPI, Loading, ScoreRing, Tags, riskKind, useToast, usePoll } from "../ui";

function Rail({ p }: { p: J }) {
  const lo = p.stop_price, hi = p.tp2_price, cur = p.current_price ?? p.entry_price;
  const x = (v: number) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  return (
    <div>
      <div className="rail" aria-hidden>
        <div className="line" />
        <i className="mk stop" style={{ left: "0%" }} /><i className="mk entry" style={{ left: `${x(p.entry_price)}%` }} />
        <i className="mk tp" style={{ left: `${x(p.tp1_price)}%` }} /><i className="mk tp" style={{ left: "100%" }} />
        <i className="now" style={{ left: `${x(cur)}%` }} />
      </div>
      <div className="rail-l"><span>Stop {price(p.stop_price)}</span><span>H2 {price(p.tp2_price)}</span></div>
    </div>
  );
}

export default function Home() {
  const { data: d, error, reload } = usePoll(() => api.get("/dashboard"), 5000);
  const daily = usePoll(() => api.get("/reports/daily"), 60000);
  const pf = usePoll(() => api.get("/portfolio"), 15000);
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const [closeAll, setCloseAll] = useState(false);
  const [sheet, setSheet] = useState<string | null>(null);

  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const a = d.account, b = d.bot;
  const curve = (d.equity_curve as J[]).map((p) => ({ label: time(p.ts), v: p.equity }));
  const up = a.total_pnl >= 0;

  const toggle = async () => {
    try {
      await api.post(b.enabled ? "/bot/stop" : "/bot/start");
      toast(b.enabled ? "Bot durduruldu. Açık pozisyonların stop/hedef takibi sürüyor." : "Bot başlatıldı. Fırsatlar risk kontrolüyle değerlendirilecek.", "ok");
      reload();
    } catch (e) {
      toast((e as Error).message, "bad");
    }
  };
  const emergency = async () => {
    setConfirm(false);
    const r = await api.post("/bot/emergency-stop", { close_positions: closeAll });
    toast(`Acil durdurma uygulandı. Kapatılan pozisyon: ${r.closed_positions}`, "warn");
    reload();
  };

  return (
    <>
      <div className="grid split">
        <Card className="hero" pad={false}>
          <div className="hero">
            <div className="top">
              <div>
                <div className="lab"><Wallet size={15} /> Toplam sanal portföy değeri</div>
                <div className="big">{usd(a.equity)}<small>USDT</small></div>
                <span className={`chg ${up ? "pos" : "neg"}`}>{up ? <ArrowUpRight /> : <ArrowDownRight />}{signed(a.total_pnl)} USDT · {pct(a.total_pnl_pct, 2, true)} <span className="dim" style={{ fontWeight: 500 }}>toplam</span></span>
              </div>
              <div className="controls">
                <button className={`btn ${b.enabled ? "" : "go"}`} onClick={toggle} disabled={b.emergency}>{b.enabled ? <><Pause /> Botu durdur</> : <><Play /> Botu başlat</>}</button>
                <button className="btn danger" onClick={() => setConfirm(true)}><Power /> Acil durdur</button>
              </div>
            </div>
            <div style={{ margin: "14px -6px 0" }}><AreaChart points={curve} format={(v) => `${usd(v)} USDT`} baseline={a.initial} height={190} /></div>
          </div>
        </Card>

        <Card title="En iyi fırsatlar" icon={<Sparkles />} subtitle="AI puanına göre · tek başına emir değildir" actions={<a href="#/analyses" className="btn ghost sm">Tümü <ChevronRight /></a>} flush>
          {d.top_opportunities.length === 0 ? <Empty icon={<Radar size={22} />} title="Analiz bekleniyor">İlk tarama tamamlanınca fırsatlar burada görünür.</Empty> : (
            <ul className="list">
              {d.top_opportunities.map((o: J) => (
                <li key={o.symbol} className="li click" onClick={() => setSheet(o.symbol)}>
                  <ScoreRing score={o.score} />
                  <div className="grow">
                    <div className="row" style={{ gap: 8 }}><b>{coin(o.symbol)}</b><Badge kind={riskKind(o.risk)}>{o.risk}</Badge></div>
                    <div className="xs dim" style={{ margin: "2px 0 4px" }}>{o.trend} · {o.label}</div>
                    <Tags tags={o.tags} />
                  </div>
                  <div className="num small" style={{ textAlign: "right" }}>{price(o.price)}<div className={tone(o.change_pct)}>{pct(o.change_pct, 1, true)}</div></div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid g4">
        <KPI icon={<Activity />} label="Günlük kâr/zarar" value={signed(a.day_pnl)} unit="USDT" delta={pct(a.day_pnl_pct, 2, true)} tone={tone(a.day_pnl) as "pos" | "neg" | ""} />
        <KPI icon={<Receipt />} label="Bugün gerçekleşen" value={signed(d.realized_today)} unit="USDT" delta={`${d.trades_today} işlem açıldı`} tone={tone(d.realized_today) as "pos" | "neg" | ""} />
        <KPI icon={<BriefcaseBusiness />} label="Açık işlem · takipteki coin" value={`${d.open_positions.length} · ${d.tracked_coins}`} delta={`Nakit ${usd(a.cash, 0)} USDT`} />
        <KPI icon={<Coins />} label="Komisyon toplamı" value={usd(d.fees_total, 3)} unit="USDT" delta={`İstek ağırlığı ${d.market.used_weight_1m ?? "-"}/6000`} />
      </div>

      <ErrorBox message={error} />
      <div className="grid split">
        <div className="col" style={{ gap: 16 }}>
          <Card title="Açık işlemler" icon={<BriefcaseBusiness />} actions={<a href="#/positions" className="btn ghost sm">Detay <ChevronRight /></a>} flush>
            {d.open_positions.length === 0 ? <Empty title="Açık pozisyon yok">Bot açıkken ve fırsat risk kontrolünü geçince burada görünür.</Empty> : (
              <ul className="list">
                {d.open_positions.map((p: J) => (
                  <li key={p.id} className="li stack">
                    <div className="between">
                      <div className="row" style={{ gap: 12 }} onClick={() => setSheet(p.symbol)}><CoinCell symbol={p.symbol} sub={`Giriş ${price(p.entry_price)}`} /></div>
                      <div className="num" style={{ textAlign: "right" }}><b className={tone(p.unrealized_pnl)}>{signed(p.unrealized_pnl, 3)} USDT</b><div className={`small ${tone(p.unrealized_pnl)}`}>{pct(p.unrealized_pct, 2, true)}</div></div>
                    </div>
                    <Rail p={p} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Son işlemler" icon={<Receipt />} actions={<a href="#/history" className="btn ghost sm">Geçmiş <ChevronRight /></a>} flush>
            {d.recent_trades.length === 0 ? <Empty title="Henüz kapanmış işlem yok" /> : (
              <ul className="list">
                {d.recent_trades.map((p: J) => (
                  <li key={p.id} className="li"><CoinCell symbol={p.symbol} sub={`${p.close_reason_tr} · ${time(p.closed_at)}`} /><span className="grow" /><b className={`num ${tone(p.realized_pnl)}`}>{signed(p.realized_pnl, 3)}</b></li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="col" style={{ gap: 16 }}>
          {pf.data && pf.data.items.length > 0 && (
            <Card title="Mevcut coinlerim" icon={<Wallet />} actions={<a href="#/portfolio" className="btn ghost sm">Detay <ChevronRight /></a>}>
              <dl className="kv">
                <dt>Portföy değeri</dt><dd className="num">{usd(pf.data.totals.value)} USDT</dd>
                <dt>Gerçekleşmemiş K/Z</dt><dd className={`num ${tone(pf.data.totals.unrealized_pnl)}`}>{signed(pf.data.totals.unrealized_pnl)} USDT</dd>
                <dt>Yönetim modu</dt><dd>{{ off: "Kapalı", watch: "İzle ve öner", manage: "Gölge yönetim" }[pf.data.mode as string]}</dd>
              </dl>
            </Card>
          )}
          {daily.data && (
            <Card title="Günlük işlem raporu" icon={<Gauge />}><p className="small muted" style={{ whiteSpace: "pre-wrap", lineHeight: 1.7 }}>{daily.data.body}</p></Card>
          )}
        </div>
      </div>

      {confirm && (
        <Confirm title="Acil durdurma" text="Bot kapanır ve yeni alım tamamen engellenir. Devam edilsin mi?" yesLabel="Acil durdur" onYes={emergency} onNo={() => setConfirm(false)}>
          <label className="row mt" style={{ gap: 10, cursor: "pointer" }}><input type="checkbox" style={{ width: 18, height: 18 }} checked={closeAll} onChange={(e) => setCloseAll(e.target.checked)} /><span className="small">Açık pozisyonları da piyasa fiyatından kapat</span></label>
        </Confirm>
      )}
      {sheet && <CoinSheet symbol={sheet} onClose={() => setSheet(null)} />}
    </>
  );
}
