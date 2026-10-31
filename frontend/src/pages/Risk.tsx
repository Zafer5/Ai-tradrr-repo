import { useState } from "react";
import { Ban, CheckCircle2, ShieldCheck, Siren } from "lucide-react";
import { api } from "../api";
import { pct, usd } from "../format";
import { Banner, Card, Confirm, ErrorBox, Loading, Meter, PageHeader, useToast, usePoll } from "../ui";

export default function Risk() {
  const { data: d, error, reload } = usePoll(() => api.get("/risk"), 5000);
  const [ask, setAsk] = useState(false);
  const toast = useToast();
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const L = d.limits, U = d.usage;
  const lossUsed = Math.max(0, -U.day_pnl_pct);
  const clear = async () => {
    setAsk(false);
    try { await api.post("/bot/clear-emergency"); toast("Acil durdurma kaldırıldı. Bot kapalı; elle başlatın.", "ok"); reload(); } catch (e) { toast((e as Error).message, "bad"); }
  };
  return (
    <>
      <PageHeader title="Risk Yönetimi" subtitle="Limitler Bot Ayarları'ndan değiştirilebilir. Her alım bu kontrollerden geçmeden emir oluşmaz." />
      {d.emergency && <Banner kind="bad" icon={<Siren />}><b>Acil durdurma aktif.</b> Bot kapalı ve yeni alım engelli. Sorunu kontrol edip kaldırabilirsiniz (bot kapalı kalır, elle başlatırsınız).<div className="mt-s"><button className="btn danger sm" onClick={() => setAsk(true)}>Acil durdurmayı kaldır</button></div></Banner>}
      {d.halted_buys && <Banner kind="bad">Günlük zarar limiti aşıldı: gün sonuna kadar yeni alım yapılmaz. Açık pozisyonların stop/hedef takibi sürer.</Banner>}
      {d.safe_mode && <Banner kind="warn">Güvenli mod aktif: {d.safe_mode}</Banner>}
      <div className="grid split-even">
        <Card title="Limit kullanımı" icon={<ShieldCheck />} subtitle={`Özkaynak ${usd(d.equity)} USDT`}>
          <Meter label="Günlük zarar" value={lossUsed} max={L.daily_loss_limit_pct} text={`${pct(lossUsed, 2)} / ${pct(L.daily_loss_limit_pct, 1)}`} />
          <Meter label="Toplam açık maruziyet" value={d.exposure_pct} max={L.max_total_exposure_pct} text={`${pct(d.exposure_pct, 1)} / ${pct(L.max_total_exposure_pct, 0)}`} />
          <Meter label="Açık pozisyon" value={U.open_positions} max={L.max_open_positions} text={`${U.open_positions} / ${L.max_open_positions}`} />
          <Meter label="Bugünkü işlem" value={U.trades_today} max={L.max_trades_per_day} text={`${U.trades_today} / ${L.max_trades_per_day}`} />
          <div className="divider" />
          <dl className="kv"><dt>İşlem başına azami risk</dt><dd className="num">%{L.risk_per_trade_pct}</dd><dt>Tek coine azami sermaye</dt><dd className="num">%{L.max_symbol_alloc_pct}</dd></dl>
        </Card>
        <Card title="Değiştirilemeyen güvenlik kuralları" icon={<Ban />}>
          <ul className="list" style={{ margin: "-4px -18px" }}>{d.fixed_rules.map((r: string) => <li key={r} className="li" style={{ padding: "11px 18px" }}><CheckCircle2 size={18} style={{ color: "var(--pos)", flex: "none" }} /><span className="small">{r}</span></li>)}</ul>
        </Card>
      </div>
      {ask && <Confirm title="Acil durdurmayı kaldır" text="Acil durdurma kaldırılsın mı? Bot kapalı kalır." danger={false} yesLabel="Kaldır" onYes={clear} onNo={() => setAsk(false)} />}
    </>
  );
}
