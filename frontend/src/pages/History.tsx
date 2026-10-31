import { useState } from "react";
import { ReceiptText } from "lucide-react";
import { api, J } from "../api";
import { price, signed, time, tone, usd } from "../format";
import { Badge, Card, CoinCell, Empty, ErrorBox, Loading, PageHeader, Segmented, usePoll } from "../ui";

export default function History() {
  const [tab, setTab] = useState<"trades" | "orders">("trades");
  const [limit, setLimit] = useState(50);
  const trades = usePoll(() => api.get(`/trades?status=CLOSED&limit=${limit}`), 10000, [limit]);
  const orders = usePoll(() => api.get(`/orders?limit=${limit}`), 10000, [limit]);
  const d = tab === "trades" ? trades : orders;
  return (
    <>
      <PageHeader title="İşlem Geçmişi" subtitle="Her işlem için alış/satış fiyatı, AI puanı, gerekçe ve komisyon kaydedilir."
        actions={<Segmented value={tab} onChange={setTab} options={[{ id: "trades", label: "İşlemler" }, { id: "orders", label: "Emirler" }]} />} />
      {!d.data ? (d.error ? <ErrorBox message={d.error} /> : <Loading />) : tab === "trades" ? (
        <Card flush>
          {d.data.items.length === 0 ? <Empty icon={<ReceiptText size={22} />} title="Henüz kapanmış işlem yok" /> : (
            <ul className="list">{d.data.items.map((p: J) => (
              <li key={p.id} className="li stack">
                <div className="between"><CoinCell symbol={p.symbol} sub={`${time(p.opened_at)} → ${time(p.closed_at)}`} /><b className={`num ${tone(p.realized_pnl)}`} style={{ fontSize: 16 }}>{signed(p.realized_pnl, 3)} USDT</b></div>
                <div className="row wrap" style={{ gap: 6 }}><Badge>{p.close_reason_tr}</Badge><Badge kind="accent">AI {usd(p.score, 0)}</Badge><span className="xs dim num">Alış {price(p.entry_price)} · Stop {price(p.stop_price)} · Hedef {price(p.tp1_price)} / {price(p.tp2_price)}</span></div>
                <div className="xs dim">Komisyon: tahmini {usd(p.est_fees, 4)} · gerçekleşen {usd(p.fees_total, 4)} USDT</div>
                {p.rationale && <details><summary className="small" style={{ cursor: "pointer", color: "var(--accent)" }}>Neden alındı?</summary><p className="small muted mt-s">{p.rationale}</p></details>}
              </li>))}</ul>
          )}
        </Card>
      ) : (
        <Card flush>
          {d.data.items.length === 0 ? <Empty title="Henüz emir yok" /> : (
            <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Zaman</th><th>Coin</th><th>Yön</th><th className="r">Fiyat</th><th className="r">Miktar</th><th className="r">Komisyon</th></tr></thead>
              <tbody>{d.data.items.map((o: J) => (
                <tr key={o.id}><td className="small dim">{time(o.created_at)}</td><td><CoinCell symbol={o.symbol} sub={o.reason_tr} /></td>
                  <td><Badge kind={o.side === "BUY" ? "ok" : "warn"}>{o.side === "BUY" ? "AL" : "SAT"}</Badge></td>
                  <td className="r">{price(o.price)}</td><td className="r">{usd(o.quantity, 5)}</td><td className="r">{usd(o.fee, 4)}</td></tr>))}</tbody></table></div>
          )}
        </Card>
      )}
      {d.data && d.data.items.length >= limit && <button className="btn block" onClick={() => setLimit(limit + 50)}>Daha fazla göster</button>}
    </>
  );
}
