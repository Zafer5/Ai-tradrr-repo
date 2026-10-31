import { useState } from "react";
import { api, J } from "../api";
import { coin, compact, pct, price, tone, usd } from "../format";
import { Badge, Card, Empty, ErrorBox, Loading, PageTitle, riskKind, ScorePill, usePoll } from "../ui";

type Sort = "score" | "volume" | "change";
const CATS = ["Tümü", "Günün yükseleni", "Günün düşeni", "Hacim artışı", "Yeni trend", "Toparlanma", "Desteğe yakın"];

function Lists() {
  const { data, reload } = usePoll(() => api.get("/coin-lists"), 0);
  const [w, setW] = useState("");
  const [x, setX] = useState("");
  if (!data) return null;
  const save = async (watch: string[], exclude: string[]) => { await api.put("/coin-lists", { watch, exclude }); reload(); };
  const add = (list: "watch" | "exclude", raw: string, clear: () => void) => {
    const v = raw.trim().toUpperCase().replace(/USDT$/, "");
    if (!v) return;
    const sym = v + "USDT";
    save(list === "watch" ? [...data.watch, sym] : data.watch, list === "exclude" ? [...data.exclude, sym] : data.exclude);
    clear();
  };
  const chips = (list: "watch" | "exclude") => (
    <div className="chips">{data[list].map((s: string) => (
      <button key={s} className="badge" aria-label={`${s} listeden çıkar`} onClick={() => save(list === "watch" ? data.watch.filter((y: string) => y !== s) : data.watch, list === "exclude" ? data.exclude.filter((y: string) => y !== s) : data.exclude)}>{coin(s)} ✕</button>
    ))}{data[list].length === 0 && <span className="small muted">Boş</span>}</div>
  );
  return (
    <Card title="Benim listelerim">
      <label htmlFor="wl">Takip listesine ekle (tarayıcı elese bile analiz edilir)</label>
      {chips("watch")}
      <div className="row"><input id="wl" placeholder="örn. SOL" value={w} onChange={(e) => setW(e.target.value)} /><button className="btn" onClick={() => add("watch", w, () => setW(""))}>Ekle</button></div>
      <label htmlFor="xl">İşlem dışı bırak (bu coine asla alım yapılmaz)</label>
      {chips("exclude")}
      <div className="row"><input id="xl" placeholder="örn. DOGE" value={x} onChange={(e) => setX(e.target.value)} /><button className="btn" onClick={() => add("exclude", x, () => setX(""))}>Ekle</button></div>
    </Card>
  );
}

export default function Scanner() {
  const { data: d, error } = usePoll(() => api.get("/scanner"), 10000);
  const [sort, setSort] = useState<Sort>("score");
  const [cat, setCat] = useState("Tümü");
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  if (!d.ready) {
    return (
      <>
        <PageTitle>Coin Tarayıcı</PageTitle>
        <Card><Empty>İlk tarama henüz tamamlanmadı. {d.error ? `Hata: ${d.error}` : "Birkaç saniye içinde hazır olur."}</Empty></Card>
      </>
    );
  }
  const rows: J[] = [...d.candidates].filter((c: J) => cat === "Tümü" || (c.tags ?? []).includes(cat)).sort((a, b) =>
    sort === "volume" ? b.quote_volume - a.quote_volume : sort === "change" ? b.change_pct - a.change_pct : (b.score ?? -1) - (a.score ?? -1),
  );
  const rej = Object.entries(d.rejected as Record<string, number>);
  return (
    <>
      <PageTitle sub={`${d.total_pairs} USDT paritesi tarandı → ${d.passed_filters} tanesi filtreleri geçti → ilk ${d.candidates.length} takipte`}>Coin Tarayıcı</PageTitle>
      <Card title="Elenen coinler" >
        {rej.length === 0 ? <Empty>Hiç coin elenmedi.</Empty> : (
          <div className="chips">{rej.map(([k, v]) => <Badge key={k}>{k}: {v}</Badge>)}</div>
        )}
        <p className="small muted">Stablecoin, kaldıraçlı token, düşük hacim, yüksek spread, aşırı fiyat hareketi ve işlem kısıtlı coinler otomatik elenir. Yeni listelenmiş coinler (yetersiz geçmiş) analiz aşamasında elenir.</p>
      </Card>
      <div className="seg" role="tablist" aria-label="Sıralama">
        {(["score", "volume", "change"] as Sort[]).map((s) => (
          <button key={s} role="tab" aria-selected={sort === s} className={sort === s ? "on" : ""} onClick={() => setSort(s)}>
            {s === "score" ? "AI puanı" : s === "volume" ? "Hacim" : "24s değişim"}
          </button>
        ))}
      </div>
      <div className="chips" role="tablist" aria-label="Kategori">
        {CATS.map((c) => <button key={c} role="tab" aria-selected={cat === c} className={`badge ${cat === c ? "ok" : ""}`} onClick={() => setCat(c)}>{c}</button>)}
      </div>
      <Card>
        {rows.length === 0 && <Empty>Bu kategoride şu an coin yok.</Empty>}
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Coin</th><th>AI</th><th className="r">Fiyat</th><th className="r">24s</th><th className="r">Hacim</th><th className="r">Spread</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.symbol} onClick={() => (location.hash = `#/analyses?s=${c.symbol}`)} className="click">
                  <td><strong>{coin(c.symbol)}</strong><div className="small muted">{c.trend ?? c.skip_reason ?? ""}{c.risk && <> · <Badge kind={riskKind(c.risk)}>{c.risk}</Badge></>}</div>
                    {c.tags?.length > 0 && <div className="tagrow">{c.tags.map((t: string) => <span key={t} className={`tag ${t === "Aşırı yükselmiş" ? "hot" : ""}`}>{t}</span>)}</div>}</td>
                  <td><ScorePill score={c.score} /></td>
                  <td className="r">{price(c.price)}</td>
                  <td className={`r ${tone(c.change_pct)}`}>{pct(c.change_pct, 1, true)}</td>
                  <td className="r">{compact(c.quote_volume)}</td>
                  <td className="r">{usd(c.spread_pct, 3)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Lists />
    </>
  );
}
