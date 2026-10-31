import { useState } from "react";
import { BookOpenCheck, ChartCandlestick, Link2, Pencil, Plus, RefreshCw, Trash2, Wallet } from "lucide-react";
import { api, J } from "../api";
import { Donut } from "../charts";
import { CoinSheet } from "../components";
import { coin, pct, price, signed, time, tone, usd } from "../format";
import { Badge, Banner, Card, CoinCell, Confirm, Empty, ErrorBox, KPI, Loading, PageHeader, Sheet, Switch, useToast, usePoll } from "../ui";

const ACTION_TR: Record<string, string> = { TAKE_PROFIT: "Kâr realizasyonu", TRAIL_EXIT: "Trailing stop", REDUCE_RISK: "Risk azaltma", STOP: "Zarar sınırı" };
const MODE_TR: Record<string, string> = { off: "Kapalı", watch: "İzle ve öner", manage: "Gölge yönetim (sanal)" };
const COLORS = ["#6c86ff", "#2dd4bf", "#f6bb4b", "#f4586d", "#a78bfa", "#38bdf8", "#fb923c", "#4ade80"];

function HoldingForm({ initial, onClose, onDone }: { initial?: J; onClose: () => void; onDone: () => void }) {
  const [v, setV] = useState({ asset: initial?.asset ?? "", quantity: initial ? String(initial.quantity) : "", avg_cost: initial?.avg_cost ? String(initial.avg_cost) : "" });
  const [err, setErr] = useState<string | null>(null);
  const num = (s: string) => parseFloat(s.replace(",", "."));
  const save = async () => {
    setErr(null);
    try { await api.post("/portfolio/holdings", { asset: v.asset, quantity: num(v.quantity), avg_cost: v.avg_cost ? num(v.avg_cost) : 0 }); onDone(); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Sheet title={initial ? `${initial.asset} — düzenle` : "Coin ekle"} onClose={onClose} footer={<><button className="btn" onClick={onClose}>Vazgeç</button><button className="btn primary" disabled={!v.asset || !v.quantity} onClick={save}>Kaydet</button></>}>
      <ErrorBox message={err} />
      <label className="lb" htmlFor="h-a">Coin kodu (örn. BTC)</label><input id="h-a" value={v.asset} disabled={!!initial} autoCapitalize="characters" onChange={(e) => setV({ ...v, asset: e.target.value.toUpperCase() })} />
      <label className="lb" htmlFor="h-q">Miktar</label><input id="h-q" inputMode="decimal" value={v.quantity} onChange={(e) => setV({ ...v, quantity: e.target.value })} />
      <label className="lb" htmlFor="h-c">Ortalama alış maliyeti (USDT, birim başına)</label><input id="h-c" inputMode="decimal" placeholder="Bilmiyorsanız boş bırakın" value={v.avg_cost} onChange={(e) => setV({ ...v, avg_cost: e.target.value })} />
    </Sheet>
  );
}

export default function Portfolio() {
  const { data: d, error, reload } = usePoll(() => api.get("/portfolio"), 5000);
  const conns = usePoll(() => api.get("/connections"), 0);
  const [form, setForm] = useState<J | boolean>(false);
  const [del, setDel] = useState<string | null>(null);
  const [chart, setChart] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const T = d.totals;
  const items: J[] = d.items;
  const parts = items.map((h, i) => ({ label: h.asset, v: h.value, color: COLORS[i % COLORS.length] }));
  const hasRO = !!conns.data?.readonly?.configured;

  const sync = async () => {
    setBusy(true);
    try {
      const r = await api.post("/portfolio/sync");
      toast(`${r.found} coin okundu, ${r.cost_ok} coinin maliyeti hesaplandı.${r.cost_missing.length ? ` Maliyeti eksik: ${r.cost_missing.join(", ")}.` : ""}`, r.cost_missing.length ? "warn" : "ok");
      reload();
    } catch (e) { toast((e as Error).message, "bad"); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="Portföyüm" subtitle={`Mevcut coinleriniz paper hesabından ayrı izlenir. Yönetim modu: ${MODE_TR[d.mode]}.`}
        actions={<div className="row wrap"><button className="btn" disabled={busy || !hasRO} onClick={sync} title={hasRO ? "" : "Önce salt okunur anahtar ekleyin"}><RefreshCw className={busy ? "spin" : ""} /> Binance'ten oku</button><button className="btn primary" onClick={() => setForm(true)}><Plus /> Coin ekle</button></div>} />
      <Banner kind="info">{d.note}</Banner>
      {!hasRO && <Banner kind="warn" icon={<Link2 />}>Binance hesabınızı otomatik okumak için <a href="#/connections" style={{ textDecoration: "underline" }}>API Bağlantıları</a> ekranında <b>salt okunur</b> anahtar ekleyin.</Banner>}
      {T.unknown_cost > 0 && <Banner kind="warn">{T.unknown_cost} coinin maliyeti bilinmiyor; kâr/zarar hesaplanamıyor. Kartta <b>Düzenle</b> ile maliyeti girin.</Banner>}

      <div className="grid split">
        <div className="grid g2" style={{ alignContent: "start" }}>
          <KPI icon={<Wallet />} label="Portföy değeri" value={usd(T.value)} unit="USDT" />
          <KPI label="Gerçekleşmemiş K/Z" value={signed(T.unrealized_pnl)} unit="USDT" delta={T.invested ? pct((T.unrealized_pnl / T.invested) * 100, 2, true) : undefined} tone={tone(T.unrealized_pnl) as "pos" | "neg" | ""} />
          <KPI label="Yatırım tutarı" value={usd(T.invested)} unit="USDT" />
          <KPI label="Gerçekleşmiş K/Z" value={signed(T.realized_pnl)} unit="USDT" tone={tone(T.realized_pnl) as "pos" | "neg" | ""} />
        </div>
        <Card title="Dağılım" icon={<BookOpenCheck />}>
          {items.length === 0 ? <Empty title="Portföy boş" /> : (
            <div className="row" style={{ gap: 20 }}>
              <Donut parts={parts} center={<div><b className="num" style={{ fontSize: 17 }}>{items.length}</b><div className="xs dim">coin</div></div>} />
              <div className="legend grow">{parts.slice(0, 6).map((p) => <div key={p.label}><i style={{ background: p.color }} /><span>{p.label}</span><span>{T.value ? pct((p.v / T.value) * 100, 1) : "-"}</span></div>)}</div>
            </div>
          )}
        </Card>
      </div>

      {items.length === 0 ? <Card><Empty icon={<Wallet size={22} />} title="Portföyde coin yok">Elle ekleyin veya Binance hesabınızdan okuyun.</Empty></Card> : (
        <div className="grid split-even">
          {items.map((h) => (
            <Card key={h.asset}>
              <div className="between">
                <CoinCell symbol={h.symbol} sub={<>{h.source === "binance" ? "Binance" : "Elle girildi"}{!h.managed && " · işlem dışı"}</>} />
                <div className="num" style={{ textAlign: "right" }}><b style={{ fontSize: 18 }} className={tone(h.unrealized_pnl)}>{h.unrealized_pnl === null ? "K/Z ?" : signed(h.unrealized_pnl)}</b><div className={`small ${tone(h.unrealized_pnl)}`}>{h.unrealized_pct === null ? "maliyet yok" : `USDT · ${pct(h.unrealized_pct, 2, true)}`}</div></div>
              </div>
              <div className="divider" />
              <dl className="kv">
                <dt>Miktar</dt><dd className="num">{usd(h.quantity, 6)}</dd>
                <dt>Ort. maliyet → Güncel</dt><dd className="num">{h.avg_cost ? price(h.avg_cost) : "bilinmiyor"} → {price(h.price)}</dd>
                <dt>Değer / Yatırım</dt><dd className="num">{usd(h.value)} / {h.invested === null ? "-" : usd(h.invested)}</dd>
                <dt>Hedef · Trailing stop</dt><dd className="num">{price(h.target_price)} · {h.trail_stop ? price(h.trail_stop) : "-"}</dd>
                <dt>Gerçekleşmiş K/Z · komisyon</dt><dd className="num">{signed(h.realized_pnl, 2)} · {usd(h.fees_paid, 3)}</dd>
                <dt>AI puanı · risk</dt><dd>{h.ai ? `${usd(h.ai.score, 0)} · ${h.ai.trend}` : "-"} · {h.risk ?? "-"}</dd>
              </dl>
              {h.decision_text && <div className="mt"><Banner kind={h.decision === "NO_COST" ? "warn" : h.decision === "HOLD" ? "info" : "ok"}><b>Yönetici notu:</b> {h.decision_text}</Banner></div>}
              <div className="row mt wrap">
                <label className="row" style={{ gap: 8 }}><Switch checked={h.managed} label={`${h.asset} yönetime dahil`} onChange={async (v) => { await api.patch(`/portfolio/holdings/${h.asset}`, { managed: v }); reload(); }} /><span className="small muted">Yönetime dahil</span></label>
                <span className="grow" />
                <button className="btn sm icon" aria-label="Grafik" onClick={() => setChart(h.symbol)}><ChartCandlestick /></button>
                <button className="btn sm" onClick={() => setForm(h)}><Pencil /> Düzenle</button>
                {h.source === "manual" && <button className="btn sm danger icon" aria-label="Sil" onClick={() => setDel(h.asset)}><Trash2 /></button>}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Card title="Yönetici işlemleri ve önerileri" icon={<BookOpenCheck />} flush>
        {d.actions.length === 0 ? <Empty title="Henüz öneri veya gölge işlem yok" /> : (
          <ul className="list">{d.actions.map((a: J) => (
            <li key={a.id} className="li stack">
              <div className="between"><span className="row" style={{ gap: 8 }}><Badge kind={a.mode === "golge" ? "warn" : "info"}>{a.mode === "golge" ? "Gölge" : "Öneri"}</Badge><b>{coin(a.asset)}</b><span className="muted small">{ACTION_TR[a.action] ?? a.action}</span></span><b className={`num ${tone(a.net_pnl)}`}>{signed(a.net_pnl, 2)} USDT</b></div>
              <div className="xs dim">{time(a.ts)} · {usd(a.quantity, 6)} @ {price(a.price)}</div>
              <div className="small muted">{a.reason}</div>
            </li>))}</ul>
        )}
      </Card>
      {form && <HoldingForm initial={typeof form === "object" ? form : undefined} onClose={() => setForm(false)} onDone={() => { setForm(false); toast("Kaydedildi.", "ok"); reload(); }} />}
      {del && <Confirm title="Kaydı sil" text={`${del} kaydı silinsin mi? Binance hesabınıza dokunulmaz.`} onNo={() => setDel(null)} onYes={async () => { await api.del(`/portfolio/holdings/${del}`); setDel(null); reload(); }} yesLabel="Sil" />}
      {chart && <CoinSheet symbol={chart} onClose={() => setChart(null)} />}
    </>
  );
}
