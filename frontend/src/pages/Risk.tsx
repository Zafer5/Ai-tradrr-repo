import { useState } from "react";
import { api } from "../api";
import { pct, usd } from "../format";
import { Bar, Card, Confirm, ErrorBox, Loading, PageTitle, usePoll } from "../ui";

export default function Risk() {
  const { data: d, error, reload } = usePoll(() => api.get("/risk"), 5000);
  const [ask, setAsk] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const L = d.limits, U = d.usage;
  const lossUsed = Math.max(0, -U.day_pnl_pct);

  const clear = async () => {
    setAsk(false);
    try {
      await api.post("/bot/clear-emergency");
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <>
      <PageTitle sub="Limitler Bot Ayarları sayfasından değiştirilebilir. Her alım bu kontrollerden geçmeden emir oluşmaz.">Risk Yönetimi</PageTitle>
      <ErrorBox message={err} />
      {d.emergency && (
        <Card title="🛑 Acil durdurma aktif">
          <p className="small">Bot kapalı ve yeni alım engelli. Sorunu kontrol ettikten sonra kaldırabilirsiniz (bot yine de kapalı kalır, elle başlatmanız gerekir).</p>
          <button className="btn danger" onClick={() => setAsk(true)}>Acil durdurmayı kaldır</button>
        </Card>
      )}
      {d.halted_buys && <div className="alert bad">Günlük zarar limiti aşıldı: gün sonuna kadar yeni alım yapılmaz.</div>}
      <Card title="Limit kullanımı">
        <div className="meter"><div className="between"><span>Günlük zarar</span><b>{pct(lossUsed, 2)} / {pct(L.daily_loss_limit_pct, 1)}</b></div><Bar value={lossUsed} max={L.daily_loss_limit_pct} label="Günlük zarar" /></div>
        <div className="meter"><div className="between"><span>Toplam açık maruziyet</span><b>{pct(d.exposure_pct, 1)} / {pct(L.max_total_exposure_pct, 0)}</b></div><Bar value={d.exposure_pct} max={L.max_total_exposure_pct} label="Maruziyet" /></div>
        <div className="meter"><div className="between"><span>Açık pozisyon</span><b>{U.open_positions} / {L.max_open_positions}</b></div><Bar value={U.open_positions} max={L.max_open_positions} label="Pozisyon sayısı" /></div>
        <div className="meter"><div className="between"><span>Bugünkü işlem</span><b>{U.trades_today} / {L.max_trades_per_day}</b></div><Bar value={U.trades_today} max={L.max_trades_per_day} label="Günlük işlem" /></div>
        <p className="small muted">Özkaynak: {usd(d.equity)} USDT · işlem başına azami risk %{L.risk_per_trade_pct} · tek coine azami %{L.max_symbol_alloc_pct}</p>
      </Card>
      <Card title="Değiştirilemeyen güvenlik kuralları">
        <ul className="bullets">{d.fixed_rules.map((r: string) => <li key={r}>{r}</li>)}</ul>
      </Card>
      {d.safe_mode && <div className="alert warn">Güvenli mod aktif: {d.safe_mode}</div>}
      {ask && <Confirm text="Acil durdurma kaldırılsın mı? Bot kapalı kalır." onYes={clear} onNo={() => setAsk(false)} />}
    </>
  );
}
