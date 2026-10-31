import { useState } from "react";
import { api, J } from "../api";
import { coin, price, signed, time, tone, usd } from "../format";
import { Badge, Card, Empty, ErrorBox, Loading, PageTitle, usePoll } from "../ui";

export default function History() {
  const [tab, setTab] = useState<"trades" | "orders">("trades");
  const [limit, setLimit] = useState(50);
  const trades = usePoll(() => api.get(`/trades?status=CLOSED&limit=${limit}`), 10000, [limit]);
  const orders = usePoll(() => api.get(`/orders?limit=${limit}`), 10000, [limit]);
  const d = tab === "trades" ? trades : orders;
  return (
    <>
      <PageTitle>İşlem Geçmişi</PageTitle>
      <div className="seg">
        <button className={tab === "trades" ? "on" : ""} onClick={() => setTab("trades")}>İşlemler</button>
        <button className={tab === "orders" ? "on" : ""} onClick={() => setTab("orders")}>Emirler (dolumlar)</button>
      </div>
      {!d.data ? (d.error ? <ErrorBox message={d.error} /> : <Loading />) : tab === "trades" ? (
        <Card>
          {d.data.items.length === 0 ? <Empty>Henüz kapanmış işlem yok.</Empty> : (
            <ul className="list">
              {d.data.items.map((p: J) => (
                <li key={p.id} className="li col">
                  <div className="between"><strong>{coin(p.symbol)}</strong><span className={`big ${tone(p.realized_pnl)}`}>{signed(p.realized_pnl, 3)} USDT</span></div>
                  <div className="small muted">{time(p.opened_at)} → {time(p.closed_at)} · <Badge>{p.close_reason_tr}</Badge></div>
                  <div className="small muted">Alış {price(p.entry_price)} · Hedef {price(p.tp1_price)}/{price(p.tp2_price)} · Stop {price(p.stop_price)} · Puan {usd(p.score, 0)}</div>
                  <div className="small muted">Komisyon: tahmini {usd(p.est_fees, 4)} · gerçekleşen {usd(p.fees_total, 4)}</div>
                  {p.rationale && <details><summary className="small">Gerekçe</summary><p className="small">{p.rationale}</p></details>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : (
        <Card>
          {d.data.items.length === 0 ? <Empty>Henüz emir yok.</Empty> : (
            <div className="tbl-wrap"><table className="tbl">
              <thead><tr><th>Zaman</th><th>Coin</th><th>Yön</th><th className="r">Fiyat</th><th className="r">Miktar</th><th className="r">Kom.</th></tr></thead>
              <tbody>{d.data.items.map((o: J) => (
                <tr key={o.id}><td className="small">{time(o.created_at)}</td><td>{coin(o.symbol)}<div className="small muted">{o.reason_tr}</div></td>
                  <td><Badge kind={o.side === "BUY" ? "ok" : "warn"}>{o.side === "BUY" ? "AL" : "SAT"}</Badge></td>
                  <td className="r">{price(o.price)}</td><td className="r">{usd(o.quantity, 5)}</td><td className="r">{usd(o.fee, 4)}</td></tr>
              ))}</tbody></table></div>
          )}
        </Card>
      )}
      {d.data && d.data.items.length >= limit && <button className="btn block" onClick={() => setLimit(limit + 50)}>Daha fazla göster</button>}
    </>
  );
}
