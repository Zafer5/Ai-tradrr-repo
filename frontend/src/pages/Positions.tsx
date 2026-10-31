import { useState } from "react";
import { api, J } from "../api";
import { coin, pct, price, signed, time, tone, usd } from "../format";
import { Badge, Card, Confirm, Empty, ErrorBox, Loading, PageTitle, usePoll } from "../ui";

function Level({ p }: { p: J }) {
  const lo = p.stop_price, hi = p.tp2_price, cur = p.current_price ?? p.entry_price;
  const x = (v: number) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  return (
    <div className="level" aria-label="Stop - giriş - hedef konumu">
      <div className="level-track">
        <i className="mk stop" style={{ left: "0%" }} />
        <i className="mk entry" style={{ left: `${x(p.entry_price)}%` }} />
        <i className="mk tp1" style={{ left: `${x(p.tp1_price)}%` }} />
        <i className="mk tp2" style={{ left: "100%" }} />
        <i className="mk now" style={{ left: `${x(cur)}%` }} />
      </div>
      <div className="level-l small muted"><span>Stop {price(p.stop_price)}</span><span>Hedef1 {price(p.tp1_price)}</span><span>Hedef2 {price(p.tp2_price)}</span></div>
    </div>
  );
}

function Edit({ p, onDone }: { p: J; onDone: () => void }) {
  const [v, setV] = useState({ stop_price: String(p.stop_price), tp1_price: String(p.tp1_price), tp2_price: String(p.tp2_price) });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    setErr(null);
    try {
      await api.patch(`/positions/${p.id}`, { stop_price: parseFloat(v.stop_price), tp1_price: parseFloat(v.tp1_price), tp2_price: parseFloat(v.tp2_price) });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className="edit">
      <ErrorBox message={err} />
      {(["stop_price", "tp1_price", "tp2_price"] as const).map((k) => (
        <label key={k}>{k === "stop_price" ? "Stop-loss fiyatı" : k === "tp1_price" ? "1. hedef (sabit fiyat)" : "2. hedef (sabit fiyat)"}
          <input inputMode="decimal" value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
        </label>
      ))}
      <div className="row"><button className="btn" onClick={onDone}>Vazgeç</button><button className="btn primary" onClick={save}>Kaydet</button></div>
    </div>
  );
}

export default function Positions() {
  const { data: d, error, reload } = usePoll(() => api.get("/positions"), 3000);
  const [closing, setClosing] = useState<J | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const close = async () => {
    try {
      await api.post(`/positions/${closing!.id}/close`);
    } catch (e) {
      setErr((e as Error).message);
    }
    setClosing(null);
    reload();
  };
  return (
    <>
      <PageTitle sub="Sanal (paper) pozisyonlar · fiyatlar canlı akıştan güncellenir">Açık Pozisyonlar</PageTitle>
      <ErrorBox message={err} />
      {d.items.length === 0 ? <Card><Empty>Açık pozisyon yok. Bot açıkken ve fırsat risk kontrolünü geçince burada görünür.</Empty></Card> : d.items.map((p: J) => (
        <Card key={p.id} title={<>{coin(p.symbol)} <Badge>{p.mode === "paper" ? "SANAL" : p.mode}</Badge></>} right={<span className={`big ${tone(p.unrealized_pnl)}`}>{signed(p.unrealized_pnl, 3)} USDT</span>}>
          <div className="kv">
            <span>Giriş / Şimdi</span><b>{price(p.entry_price)} → {price(p.current_price)}</b>
            <span>Net K/Z (şimdi satılsa)</span><b className={tone(p.unrealized_pnl)}>{pct(p.unrealized_pct, 2, true)}</b>
            <span>Miktar</span><b>{usd(p.quantity, 6)} ({usd(p.value, 2)} USDT)</b>
            <span>AI puanı / Risk</span><b>{usd(p.score, 0)} / {p.risk_level}</b>
            <span>Durum</span><b>{p.tp1_done ? "1. hedef alındı · stop başa baş üstünde" : p.trailing_active ? "Trailing stop aktif" : "Stop & hedef bekleniyor"}</b>
            <span>Açılış</span><b>{time(p.opened_at)}</b>
            <span>Tahmini / gerçekleşen komisyon</span><b>{usd(p.est_fees, 4)} / {usd(p.fees_total, 4)}</b>
          </div>
          <Level p={p} />
          {p.rationale && <details><summary>İşlem gerekçesi</summary><p className="small">{p.rationale}</p></details>}
          {editing === p.id ? <Edit p={p} onDone={() => { setEditing(null); reload(); }} /> : (
            <div className="row mt"><button className="btn" onClick={() => setEditing(p.id)}>Stop / hedef düzenle</button><button className="btn danger" onClick={() => setClosing(p)}>Kapat</button></div>
          )}
        </Card>
      ))}
      {closing && <Confirm text={`${coin(closing.symbol)} pozisyonu piyasa fiyatından (sanal) kapatılsın mı?`} onYes={close} onNo={() => setClosing(null)} />}
    </>
  );
}
