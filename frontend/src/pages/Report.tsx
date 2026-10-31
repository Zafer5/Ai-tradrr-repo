import { Banknote, CalendarDays, LineChart, Percent, Scale, TrendingDown, Trophy } from "lucide-react";
import { api, J } from "../api";
import { BarsChart } from "../charts";
import { pct, signed, tone, usd } from "../format";
import { Card, Empty, ErrorBox, KPI, Loading, PageHeader, Banner, usePoll } from "../ui";

export default function Report() {
  const { data: d, error } = usePoll(() => api.get("/reports/pnl"), 15000);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const s = d.summary;
  const t = (n: number | null) => (tone(n) as "pos" | "neg" | "");
  return (
    <>
      <PageHeader title="Kâr-Zarar Raporu" subtitle="Tüm rakamlar komisyon dahil net sonuçlardır." />
      <div className="grid g4">
        <KPI icon={<Banknote />} label="Net kâr/zarar" value={signed(s.net_pnl)} unit="USDT" tone={t(s.net_pnl)} delta={`${s.trades} işlem`} />
        <KPI icon={<Trophy />} label="Kazanç oranı" value={s.win_rate === null ? "-" : pct(s.win_rate, 0)} delta={`${s.wins} kazanç · ${s.losses} kayıp`} />
        <KPI icon={<Scale />} label="Profit factor" value={s.profit_factor === null ? "-" : usd(s.profit_factor)} delta="1 üstü = kârlı" tone={s.profit_factor === null ? "" : s.profit_factor >= 1 ? "pos" : "neg"} />
        <KPI icon={<TrendingDown />} label="Maks. düşüş" value={s.max_drawdown_pct === null ? "-" : pct(s.max_drawdown_pct, 2)} delta="özkaynak zirvesinden" />
        <KPI icon={<Percent />} label="Ort. kazanç / kayıp" value={`${usd(s.avg_win, 2)} / ${usd(s.avg_loss, 2)}`} />
        <KPI icon={<LineChart />} label="İşlem başı beklenti" value={signed(s.expectancy, 3)} unit="USDT" tone={t(s.expectancy)} />
        <KPI label="En iyi / en kötü" value={`${signed(s.best, 2)} / ${signed(s.worst, 2)}`} />
        <KPI label="Toplam komisyon" value={usd(s.fees_total, 4)} unit="USDT" />
      </div>
      <div className="grid split-even">
        <Card title="Günlük net sonuç" icon={<CalendarDays />} subtitle="Son 14 gün">
          {d.daily.length === 0 ? <Empty title="Henüz kapanmış işlem yok" /> : <BarsChart data={d.daily.slice(-14).map((x: J) => ({ label: x.date.slice(5), v: x.pnl }))} format={(v) => `${signed(v, 2)} USDT`} />}
        </Card>
        <Card title="Çıkış nedenine göre" subtitle="Hangi kural ne kadar kazandırdı/kaybettirdi" flush>
          {d.by_reason.length === 0 ? <Empty title="Veri yok" /> : (
            <ul className="list">{d.by_reason.map((r: J) => <li key={r.reason} className="li"><div className="grow"><b>{r.reason}</b><div className="xs dim">{r.n} işlem</div></div><b className={`num ${tone(r.pnl)}`}>{signed(r.pnl, 3)} USDT</b></li>)}</ul>
          )}
        </Card>
      </div>
      <Banner kind="info">{d.note}</Banner>
    </>
  );
}
