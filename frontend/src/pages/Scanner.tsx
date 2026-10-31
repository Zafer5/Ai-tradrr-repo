import { useState } from "react";
import { api, J } from "../api";
import { coin, compact, pct, price, tone, usd } from "../format";
import { Badge, Card, Empty, ErrorBox, Loading, PageTitle, riskKind, ScorePill, usePoll } from "../ui";

type Sort = "score" | "volume" | "change";

export default function Scanner() {
  const { data: d, error } = usePoll(() => api.get("/scanner"), 10000);
  const [sort, setSort] = useState<Sort>("score");
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  if (!d.ready) {
    return (
      <>
        <PageTitle>Coin Tarayıcı</PageTitle>
        <Card><Empty>İlk tarama henüz tamamlanmadı. {d.error ? `Hata: ${d.error}` : "Birkaç saniye içinde hazır olur."}</Empty></Card>
      </>
    );
  }
  const rows: J[] = [...d.candidates].sort((a, b) =>
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
      <Card>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Coin</th><th>AI</th><th className="r">Fiyat</th><th className="r">24s</th><th className="r">Hacim</th><th className="r">Spread</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.symbol} onClick={() => (location.hash = `#/analyses?s=${c.symbol}`)} className="click">
                  <td><strong>{coin(c.symbol)}</strong><div className="small muted">{c.trend ?? c.skip_reason ?? ""}{c.risk && <> · <Badge kind={riskKind(c.risk)}>{c.risk}</Badge></>}</div></td>
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
    </>
  );
}
