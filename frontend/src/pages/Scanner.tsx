import { useState } from "react";
import { ListFilter, Radar, ShieldBan, Star } from "lucide-react";
import { api, J } from "../api";
import { CoinSheet } from "../components";
import { compact, pct, price, tone, usd } from "../format";
import { Badge, Card, CoinCell, Empty, ErrorBox, Loading, PageHeader, ScoreRing, Segmented, Tags, riskKind, usePoll } from "../ui";

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
  const remove = (list: "watch" | "exclude", s: string) => save(list === "watch" ? data.watch.filter((y: string) => y !== s) : data.watch, list === "exclude" ? data.exclude.filter((y: string) => y !== s) : data.exclude);
  const chips = (list: "watch" | "exclude") => (
    <div className="chips" style={{ margin: "8px 0" }}>
      {data[list].map((s: string) => <button key={s} className="chip on" aria-label={`${s} listeden çıkar`} onClick={() => remove(list, s)}>{s.replace("USDT", "")} ✕</button>)}
      {data[list].length === 0 && <span className="small dim">Liste boş</span>}
    </div>
  );
  return (
    <div className="grid split-even">
      <Card title="Takip listem" icon={<Star />} subtitle="Tarayıcı elese bile analiz edilir">
        {chips("watch")}
        <div className="row"><input aria-label="Takip listesine coin" placeholder="örn. SOL" value={w} onChange={(e) => setW(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add("watch", w, () => setW(""))} /><button className="btn" onClick={() => add("watch", w, () => setW(""))}>Ekle</button></div>
      </Card>
      <Card title="İşlem dışı bırakılanlar" icon={<ShieldBan />} subtitle="Bu coinlere asla alım yapılmaz">
        {chips("exclude")}
        <div className="row"><input aria-label="İşlem dışı coin" placeholder="örn. DOGE" value={x} onChange={(e) => setX(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add("exclude", x, () => setX(""))} /><button className="btn" onClick={() => add("exclude", x, () => setX(""))}>Ekle</button></div>
      </Card>
    </div>
  );
}

export default function Scanner() {
  const { data: d, error } = usePoll(() => api.get("/scanner"), 10000);
  const [sort, setSort] = useState<Sort>("score");
  const [cat, setCat] = useState("Tümü");
  const [sheet, setSheet] = useState<string | null>(null);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  if (!d.ready) return (<><PageHeader title="Coin Tarayıcı" /><Card><Empty icon={<Radar size={22} />} title="İlk tarama sürüyor">{d.error ? `Hata: ${d.error}` : "Birkaç saniye içinde hazır olur."}</Empty></Card></>);

  const rows: J[] = [...d.candidates].filter((c: J) => cat === "Tümü" || (c.tags ?? []).includes(cat)).sort((a, b) =>
    sort === "volume" ? b.quote_volume - a.quote_volume : sort === "change" ? b.change_pct - a.change_pct : (b.score ?? -1) - (a.score ?? -1));
  const rej = Object.entries(d.rejected as Record<string, number>);
  return (
    <>
      <PageHeader title="Coin Tarayıcı" subtitle={`${d.total_pairs} USDT paritesi tarandı → ${d.passed_filters} tanesi filtreleri geçti → ilk ${d.candidates.length} coin takipte.`}
        actions={<Segmented value={sort} onChange={setSort} options={[{ id: "score", label: "AI puanı" }, { id: "volume", label: "Hacim" }, { id: "change", label: "24s" }]} />} />
      <div className="chips scroll" role="tablist" aria-label="Kategori">{CATS.map((c) => <button key={c} role="tab" aria-selected={cat === c} className={`chip ${cat === c ? "on" : ""}`} onClick={() => setCat(c)}>{c}</button>)}</div>
      <Card flush pad={false}>
        {rows.length === 0 ? <Empty title="Bu kategoride şu an coin yok" /> : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Coin</th><th>AI puanı</th><th className="r">Fiyat</th><th className="r">24s</th><th className="r">Hacim</th><th className="r">Spread</th></tr></thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.symbol} className="click" onClick={() => setSheet(c.symbol)}>
                    <td><CoinCell symbol={c.symbol} sub={c.trend ?? c.skip_reason ?? "-"} />{c.tags?.length > 0 && <div style={{ marginTop: 6 }}><Tags tags={c.tags} /></div>}</td>
                    <td><div className="row" style={{ gap: 10 }}><ScoreRing score={c.score} size={40} />{c.risk && <Badge kind={riskKind(c.risk)}>{c.risk}</Badge>}</div></td>
                    <td className="r">{price(c.price)}</td>
                    <td className={`r ${tone(c.change_pct)}`}>{pct(c.change_pct, 2, true)}</td>
                    <td className="r">{compact(c.quote_volume)}</td>
                    <td className="r">{usd(c.spread_pct, 3)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Elenen coinler" icon={<ListFilter />} subtitle="Stablecoin, kaldıraçlı token, düşük hacim, yüksek spread, aşırı hareket ve işlem kısıtlı coinler otomatik elenir; yeni listelenmişler analizde elenir.">
        <div className="chips">{rej.length === 0 ? <span className="dim small">Hiç coin elenmedi.</span> : rej.map(([k, v]) => <Badge key={k}>{k} · {v}</Badge>)}</div>
      </Card>
      <Lists />
      {sheet && <CoinSheet symbol={sheet} onClose={() => setSheet(null)} />}
    </>
  );
}
