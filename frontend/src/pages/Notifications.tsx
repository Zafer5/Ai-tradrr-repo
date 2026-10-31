import { useEffect } from "react";
import { api, J } from "../api";
import { timeFull } from "../format";
import { Card, Empty, ErrorBox, Loading, PageTitle, usePoll } from "../ui";

export default function Notifications() {
  const { data, error, reload } = usePoll(() => api.get("/notifications?limit=100"), 10000);
  useEffect(() => {
    const t = setTimeout(() => api.post("/notifications/read-all").catch(() => undefined), 3000);
    return () => clearTimeout(t);
  }, []);
  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;
  return (
    <>
      <PageTitle sub="Alımlar, satışlar, uyarılar ve günlük rapor. Her işlemin nedeni açıklanır.">Bildirimler</PageTitle>
      <div className={`alert ${data.telegram ? "ok" : "info"} small`}>
        {data.telegram ? "Telegram bildirimi AÇIK: bildirimler telefonunuza da gönderiliyor." : "Telefona anlık bildirim için Telegram'ı bağlayabilirsiniz (README → Bildirimler). Şimdilik bildirimler bu ekranda görünür."}
      </div>
      <Card right={<button className="btn" onClick={async () => { await api.post("/notifications/read-all"); reload(); }}>Hepsini okundu yap</button>}>
        {data.items.length === 0 ? <Empty>Henüz bildirim yok.</Empty> : (
          <ul className="list">
            {data.items.map((n: J) => (
              <li key={n.id} className={`note ${n.level} ${n.read ? "" : "unread"}`}>
                <div className="between"><strong>{n.title}</strong><span className="small muted">{timeFull(n.ts)}</span></div>
                {n.body && <p>{n.body}</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
