import { api, J } from "../api";
import { pct, signed, tone, usd } from "../format";
import { Card, Empty, ErrorBox, Loading, PageTitle, Stat, usePoll } from "../ui";

function Bars({ data }: { data: { date: string; pnl: number }[] }) {
  const max = Math.max(...data.map((d) => Math.abs(d.pnl)), 1e-9);
  const w = 300, h = 110, mid = h / 2, bw = Math.min(28, (w / data.length) * 0.7);
  return (
    <svg viewBox={`0 0 ${w} ${h + 16}`} className="bars" role="img" aria-label="Günlük net kâr/zarar">
      <line x1="0" x2={w} y1={mid} y2={mid} stroke="var(--line)" />
      {data.map((d, i) => {
        const x = (i + 0.5) * (w / data.length) - bw / 2;
        const hh = (Math.abs(d.pnl) / max) * (mid - 4);
        return (
          <g key={d.date}>
            <rect x={x} y={d.pnl >= 0 ? mid - hh : mid} width={bw} height={Math.max(hh, 1)} rx="2" fill={d.pnl >= 0 ? "var(--pos)" : "var(--neg)"} />
            <text x={x + bw / 2} y={h + 12} textAnchor="middle" fontSize="8" fill="var(--muted)">{d.date.slice(5)}</text>
          </g>
        );
      })}
    </svg>
  );
}

export default function Report() {
  const { data: d, error } = usePoll(() => api.get("/reports/pnl"), 15000);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const s = d.summary;
  return (
    <>
      <PageTitle>Kâr-Zarar Raporu</PageTitle>
      <div className="grid2">
        <Stat label="Net kâr/zarar (komisyon dahil)" value={`${signed(s.net_pnl)} USDT`} tone={tone(s.net_pnl)} />
        <Stat label="İşlem sayısı" value={s.trades} sub={`${s.wins} kazanç · ${s.losses} kayıp`} />
        <Stat label="Kazanç oranı" value={s.win_rate === null ? "-" : pct(s.win_rate, 0)} sub="tek başına ölçüt değil" />
        <Stat label="Profit factor" value={s.profit_factor === null ? "-" : usd(s.profit_factor)} sub="1 üstü = kârlı" />
        <Stat label="Ort. kazanç / kayıp" value={`${usd(s.avg_win, 3)} / ${usd(s.avg_loss, 3)}`} />
        <Stat label="İşlem başı beklenti" value={`${signed(s.expectancy, 3)} USDT`} tone={tone(s.expectancy)} />
        <Stat label="Maks. düşüş" value={s.max_drawdown_pct === null ? "-" : pct(s.max_drawdown_pct, 2)} />
        <Stat label="Toplam komisyon" value={`${usd(s.fees_total, 4)} USDT`} />
      </div>
      <Card title="Günlük net sonuç">
        {d.daily.length === 0 ? <Empty>Henüz kapanmış işlem yok.</Empty> : <Bars data={d.daily.slice(-14)} />}
      </Card>
      <Card title="Çıkış nedenine göre">
        {d.by_reason.length === 0 ? <Empty>-</Empty> : (
          <ul className="list">{d.by_reason.map((r: J) => (
            <li key={r.reason} className="li"><div className="grow">{r.reason}<div className="small muted">{r.n} işlem</div></div><div className={`right ${tone(r.pnl)}`}>{signed(r.pnl, 3)} USDT</div></li>
          ))}</ul>
        )}
      </Card>
      <p className="small muted">{d.note}</p>
    </>
  );
}
