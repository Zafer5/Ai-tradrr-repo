import { useState } from "react";
import { api, J } from "../api";
import { coin, pct, price, signed, time, tone, usd } from "../format";
import { Badge, Card, Confirm, Empty, ErrorBox, Loading, PageTitle, Stat, usePoll } from "../ui";

const ACTION_TR: Record<string, string> = { TAKE_PROFIT: "Kâr realizasyonu", TRAIL_EXIT: "Trailing stop", REDUCE_RISK: "Risk azaltma", STOP: "Zarar sınırı" };
const MODE_TR: Record<string, string> = { off: "Kapalı", watch: "İzle ve öner", manage: "Gölge yönetim (sanal)" };

function AddForm({ initial, onDone }: { initial?: J; onDone: () => void }) {
  const [v, setV] = useState({ asset: initial?.asset ?? "", quantity: initial ? String(initial.quantity) : "", avg_cost: initial?.avg_cost ? String(initial.avg_cost) : "" });
  const [err, setErr] = useState<string | null>(null);
  const num = (s: string) => parseFloat(s.replace(",", "."));
  const save = async () => {
    setErr(null);
    try {
      await api.post("/portfolio/holdings", { asset: v.asset, quantity: num(v.quantity), avg_cost: v.avg_cost ? num(v.avg_cost) : 0 });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className="edit">
      <ErrorBox message={err} />
      <label>Coin kodu (örn. BTC)<input value={v.asset} disabled={!!initial} onChange={(e) => setV({ ...v, asset: e.target.value.toUpperCase() })} autoCapitalize="characters" /></label>
      <label>Miktar<input inputMode="decimal" value={v.quantity} onChange={(e) => setV({ ...v, quantity: e.target.value })} /></label>
      <label>Ortalama alış maliyeti (USDT, birim başına; bilmiyorsanız boş bırakın)<input inputMode="decimal" value={v.avg_cost} onChange={(e) => setV({ ...v, avg_cost: e.target.value })} /></label>
      <div className="row"><button className="btn" onClick={onDone}>Vazgeç</button><button className="btn primary grow" disabled={!v.asset || !v.quantity} onClick={save}>Kaydet</button></div>
    </div>
  );
}

export default function Portfolio() {
  const { data: d, error, reload } = usePoll(() => api.get("/portfolio"), 5000);
  const conns = usePoll(() => api.get("/connections"), 0);
  const [adding, setAdding] = useState<J | boolean>(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [del, setDel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const T = d.totals;

  const sync = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.post("/portfolio/sync");
      setMsg({ ok: true, text: `Binance hesabı okundu: ${r.found} coin bulundu, ${r.cost_ok} coinin maliyeti geçmiş alımlardan hesaplandı.${r.cost_missing.length ? ` Maliyeti eksik (elle girin): ${r.cost_missing.join(", ")}.` : ""}` });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageTitle sub={`Yönetim modu: ${MODE_TR[d.mode]} (Bot Ayarları → Portföy)`}>Portföyüm</PageTitle>
      <div className="alert info small">{d.note}</div>
      {msg && <div className={`alert ${msg.ok ? "ok" : "bad"}`} role="status">{msg.text}</div>}
      <div className="grid2">
        <Stat label="Portföy değeri" value={`${usd(T.value)} USDT`} />
        <Stat label="Gerçekleşmemiş K/Z" value={`${signed(T.unrealized_pnl)} USDT`} tone={tone(T.unrealized_pnl)} sub={T.invested ? pct((T.unrealized_pnl / T.invested) * 100, 2, true) : undefined} />
        <Stat label="Yatırım tutarı" value={`${usd(T.invested)} USDT`} />
        <Stat label="Gerçekleşmiş K/Z" value={`${signed(T.realized_pnl)} USDT`} tone={tone(T.realized_pnl)} />
      </div>
      {T.unknown_cost > 0 && <div className="alert warn">{T.unknown_cost} coinin maliyeti bilinmiyor; kâr/zarar hesaplanamıyor. Coine dokunup maliyeti elle girin.</div>}

      <div className="row">
        <button className="btn primary grow" onClick={() => setAdding(true)}>＋ Coin ekle</button>
        <button className="btn" disabled={busy || !conns.data?.readonly?.configured} onClick={sync} title={conns.data?.readonly?.configured ? "" : "Önce API Bağlantıları'ndan salt okunur anahtar ekleyin"}>
          {busy ? "Okunuyor…" : "Binance'ten oku"}
        </button>
      </div>
      {!conns.data?.readonly?.configured && <p className="small muted">Binance hesabınızı otomatik okumak için <a className="link" href="#/connections">API Bağlantıları</a> ekranında <b>salt okunur</b> anahtar ekleyin.</p>}
      {adding && <Card title="Coin ekle / güncelle"><AddForm initial={typeof adding === "object" ? adding : undefined} onDone={() => { setAdding(false); reload(); }} /></Card>}

      {d.items.length === 0 ? <Card><Empty>Portföyde coin yok. Elle ekleyin veya Binance'ten okuyun.</Empty></Card> : d.items.map((h: J) => (
        <Card key={h.asset} title={<>{h.asset} <Badge>{h.source === "binance" ? "Binance" : "Elle"}</Badge> {!h.managed && <Badge kind="warn">İşlem dışı</Badge>}</>}
          right={<span className={`big ${tone(h.unrealized_pnl)}`}>{h.unrealized_pnl === null ? "K/Z ?" : `${signed(h.unrealized_pnl)} USDT`}</span>}>
          <div className="kv">
            <span>Miktar</span><b>{usd(h.quantity, 6)}</b>
            <span>Ort. maliyet → Güncel</span><b>{h.avg_cost ? price(h.avg_cost) : "bilinmiyor"} → {price(h.price)}</b>
            <span>Değer / Yatırım</span><b>{usd(h.value)} / {h.invested === null ? "-" : usd(h.invested)} USDT</b>
            <span>Net K/Z (şimdi satılsa)</span><b className={tone(h.unrealized_pnl)}>{pct(h.unrealized_pct, 2, true)}</b>
            <span>Hedef / Trailing stop</span><b>{price(h.target_price)} / {h.trail_stop ? price(h.trail_stop) : "-"}</b>
            <span>Gerçekleşmiş K/Z · komisyon</span><b>{signed(h.realized_pnl, 2)} · {usd(h.fees_paid, 3)}</b>
            <span>AI puanı · risk</span><b>{h.ai ? `${usd(h.ai.score, 0)} · ${h.ai.trend}` : "-"} · {h.risk ?? "-"}</b>
          </div>
          {h.decision_text && <div className={`alert ${h.decision === "HOLD" ? "info" : h.decision === "NO_COST" ? "warn" : "ok"} small`}><b>Yönetici notu:</b> {h.decision_text}</div>}
          <div className="row mt">
            <button className="btn" onClick={() => setAdding(h)}>Maliyet/miktar düzenle</button>
            <button className="btn" onClick={async () => { await api.patch(`/portfolio/holdings/${h.asset}`, { managed: !h.managed }); reload(); }}>{h.managed ? "İşlem dışı bırak" : "Yönetime al"}</button>
            {h.source === "manual" && <button className="btn danger" onClick={() => setDel(h.asset)}>Sil</button>}
          </div>
        </Card>
      ))}

      <Card title="Yönetici işlemleri / önerileri">
        {d.actions.length === 0 ? <Empty>Henüz öneri veya gölge işlem yok.</Empty> : (
          <ul className="list">{d.actions.map((a: J) => (
            <li key={a.id} className="li col">
              <div className="between"><span><Badge kind={a.mode === "golge" ? "warn" : ""}>{a.mode === "golge" ? "GÖLGE" : "ÖNERİ"}</Badge> <strong>{coin(a.asset)}</strong> {ACTION_TR[a.action] ?? a.action}</span><span className={tone(a.net_pnl)}>{signed(a.net_pnl, 2)} USDT</span></div>
              <div className="small muted">{time(a.ts)} · {usd(a.quantity, 6)} @ {price(a.price)}</div>
              <div className="small">{a.reason}</div>
            </li>))}</ul>
        )}
      </Card>
      {del && <Confirm text={`${del} kaydı silinsin mi? (Binance hesabınıza dokunulmaz.)`} onNo={() => setDel(null)} onYes={async () => { await api.del(`/portfolio/holdings/${del}`); setDel(null); reload(); }} />}
    </>
  );
}
