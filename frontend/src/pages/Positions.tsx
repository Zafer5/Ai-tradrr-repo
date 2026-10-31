import { useState } from "react";
import { BriefcaseBusiness, ChartCandlestick, Pencil, X } from "lucide-react";
import { api, J } from "../api";
import { CoinSheet } from "../components";
import { pct, price, signed, time, tone, usd } from "../format";
import { Badge, Card, CoinCell, Confirm, Empty, ErrorBox, Loading, PageHeader, Sheet, useToast, usePoll } from "../ui";

function Rail({ p }: { p: J }) {
  const lo = p.stop_price, hi = p.tp2_price, cur = p.current_price ?? p.entry_price;
  const x = (v: number) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  return (
    <div style={{ margin: "14px 0 4px" }}>
      <div className="rail" aria-label="Stop, giriş ve hedef konumu">
        <div className="line" /><i className="mk stop" style={{ left: "0%" }} /><i className="mk entry" style={{ left: `${x(p.entry_price)}%` }} />
        <i className="mk tp" style={{ left: `${x(p.tp1_price)}%` }} /><i className="mk tp" style={{ left: "100%" }} /><i className="now" style={{ left: `${x(cur)}%` }} />
      </div>
      <div className="rail-l"><span>Stop {price(p.stop_price)}</span><span>Giriş {price(p.entry_price)}</span><span>H1 {price(p.tp1_price)}</span><span>H2 {price(p.tp2_price)}</span></div>
    </div>
  );
}

function EditSheet({ p, onClose, onDone }: { p: J; onClose: () => void; onDone: () => void }) {
  const [v, setV] = useState({ stop_price: String(p.stop_price), tp1_price: String(p.tp1_price), tp2_price: String(p.tp2_price) });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    setErr(null);
    try {
      await api.patch(`/positions/${p.id}`, { stop_price: parseFloat(v.stop_price), tp1_price: parseFloat(v.tp1_price), tp2_price: parseFloat(v.tp2_price) });
      onDone();
    } catch (e) { setErr((e as Error).message); }
  };
  const L: Record<string, string> = { stop_price: "Stop-loss fiyatı", tp1_price: "1. hedef (sabit fiyat)", tp2_price: "2. hedef (sabit fiyat)" };
  return (
    <Sheet title={`${p.symbol.replace("USDT", "")} — stop ve hedef`} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Vazgeç</button><button className="btn primary" onClick={save}>Kaydet</button></>}>
      <ErrorBox message={err} />
      {(["stop_price", "tp1_price", "tp2_price"] as const).map((k) => (<div key={k}><label className="lb" htmlFor={k}>{L[k]}</label><input id={k} inputMode="decimal" value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></div>))}
      <p className="small dim mt">Stop güncel fiyatın altında, hedefler üstünde olmalıdır. Güncel fiyat: {price(p.current_price)}</p>
    </Sheet>
  );
}

export default function Positions() {
  const { data: d, error, reload } = usePoll(() => api.get("/positions"), 3000);
  const [closing, setClosing] = useState<J | null>(null);
  const [editing, setEditing] = useState<J | null>(null);
  const [chart, setChart] = useState<string | null>(null);
  const toast = useToast();
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const close = async () => {
    try { await api.post(`/positions/${closing!.id}/close`); toast("Pozisyon (sanal) kapatıldı.", "ok"); } catch (e) { toast((e as Error).message, "bad"); }
    setClosing(null); reload();
  };
  return (
    <>
      <PageHeader title="Açık Pozisyonlar" subtitle="Bot pozisyonları · fiyatlar her 3 saniyede güncellenir. Stop/hedef takibi bot çalışırken sunucuda yapılır." />
      {d.items.length === 0 ? <Card><Empty icon={<BriefcaseBusiness size={22} />} title="Açık pozisyon yok">Bot açıkken ve fırsat risk kontrolünü geçince burada görünür.</Empty></Card> : (
        <div className="grid split-even">
          {d.items.map((p: J) => (
            <Card key={p.id}>
              <div className="between">
                <CoinCell symbol={p.symbol} sub={`AI ${usd(p.score, 0)} · ${p.risk_level} risk`} />
                <div className="num" style={{ textAlign: "right" }}><b style={{ fontSize: 18 }} className={tone(p.unrealized_pnl)}>{signed(p.unrealized_pnl, 3)}</b><div className={`small ${tone(p.unrealized_pnl)}`}>USDT · {pct(p.unrealized_pct, 2, true)}</div></div>
              </div>
              <Rail p={p} />
              <div className="row wrap mt-s" style={{ gap: 6 }}>
                {p.mode === "live" ? <Badge kind="bad">GERÇEK</Badge> : p.mode === "testnet" ? <Badge kind="info">TESTNET</Badge> : <Badge kind="warn">SANAL</Badge>}
                {p.tp1_done && <Badge kind="ok">1. hedef alındı · stop başa baş üstünde</Badge>}
                {p.trailing_active && <Badge kind="info">Trailing aktif</Badge>}
              </div>
              <div className="divider" />
              <dl className="kv">
                <dt>Miktar</dt><dd className="num">{usd(p.quantity, 6)} · {usd(p.value)} USDT</dd>
                <dt>Şimdi</dt><dd className="num">{price(p.current_price)}</dd>
                <dt>Tahmini / gerçekleşen komisyon</dt><dd className="num">{usd(p.est_fees, 4)} / {usd(p.fees_total, 4)}</dd>
                <dt>Açılış</dt><dd>{time(p.opened_at)}</dd>
              </dl>
              {p.rationale && <details className="mt"><summary className="small bold" style={{ cursor: "pointer" }}>İşlem gerekçesi</summary><p className="small muted mt-s">{p.rationale}</p></details>}
              <div className="row mt wrap">
                <button className="btn sm" onClick={() => setChart(p.symbol)}><ChartCandlestick /> Grafik</button>
                <button className="btn sm" onClick={() => setEditing(p)}><Pencil /> Stop / hedef</button>
                <span className="grow" />
                <button className="btn sm danger" onClick={() => setClosing(p)}><X /> Kapat</button>
              </div>
            </Card>
          ))}
        </div>
      )}
      {closing && <Confirm title="Pozisyonu kapat" text={`${closing.symbol.replace("USDT", "")} pozisyonu piyasa fiyatından (sanal) kapatılsın mı?`} onYes={close} onNo={() => setClosing(null)} yesLabel="Kapat" />}
      {editing && <EditSheet p={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); toast("Stop/hedef güncellendi.", "ok"); reload(); }} />}
      {chart && <CoinSheet symbol={chart} onClose={() => setChart(null)} />}
    </>
  );
}
