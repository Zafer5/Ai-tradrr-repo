import { useEffect } from "react";
import { Bell, CheckCheck, CircleDollarSign, Gauge, OctagonAlert, ShieldAlert, TrendingDown, TrendingUp, Wallet } from "lucide-react";
import { api, J } from "../api";
import { timeFull } from "../format";
import { Banner, Card, Empty, ErrorBox, Loading, PageHeader, usePoll } from "../ui";

const ICONS: Record<string, typeof Bell> = { buy: TrendingUp, sell: CircleDollarSign, stoploss: TrendingDown, loss_limit: OctagonAlert, safe: ShieldAlert, shock: TrendingDown, emergency: OctagonAlert, portfolio: Wallet, daily_report: Gauge };

export default function Notifications() {
  const { data, error, reload } = usePoll(() => api.get("/notifications?limit=100"), 10000);
  useEffect(() => {
    const t = setTimeout(() => api.post("/notifications/read-all").catch(() => undefined), 4000);
    return () => clearTimeout(t);
  }, []);
  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;
  return (
    <>
      <PageHeader title="Bildirimler" subtitle="Alımlar, satışlar, uyarılar ve günlük rapor. Her işlemin nedeni açıklanır."
        actions={<button className="btn" onClick={async () => { await api.post("/notifications/read-all"); reload(); }}><CheckCheck /> Hepsini okundu yap</button>} />
      <Banner kind={data.telegram ? "ok" : "info"}>{data.telegram ? "Telegram bildirimi açık: bildirimler telefonunuza da gönderiliyor." : "Telefona anlık bildirim için Telegram'ı bağlayabilirsiniz (README → Bildirimler). Şimdilik bildirimler bu ekranda görünür."}</Banner>
      <Card flush>
        {data.items.length === 0 ? <Empty icon={<Bell size={22} />} title="Henüz bildirim yok" /> : data.items.map((n: J) => {
          const I = ICONS[n.kind] ?? Bell;
          return (
            <div key={n.id} className={`note ${n.level} ${n.read ? "" : "unread"}`}>
              <span className="ni"><I /></span>
              <div className="grow"><div className="between"><b>{n.title}</b></div><div className="xs dim">{timeFull(n.ts)}</div>{n.body && <p>{n.body}</p>}</div>
            </div>
          );
        })}
      </Card>
    </>
  );
}
