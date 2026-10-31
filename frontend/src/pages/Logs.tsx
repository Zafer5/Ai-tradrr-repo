import { useState } from "react";
import { ScrollText, Search } from "lucide-react";
import { api, J } from "../api";
import { timeFull } from "../format";
import { Card, Empty, ErrorBox, Loading, PageHeader, Segmented, usePoll } from "../ui";

export default function Logs() {
  const [level, setLevel] = useState("INFO");
  const [q, setQ] = useState("");
  const { data, error } = usePoll(() => api.get(`/logs?limit=300&level=${level}${q ? `&q=${encodeURIComponent(q)}` : ""}`), 5000, [level, q]);
  return (
    <>
      <PageHeader title="Sistem Günlükleri" subtitle="Gizli bilgiler (API anahtarı, imza, şifre) günlüklerde otomatik maskelenir."
        actions={<Segmented value={level} onChange={setLevel} options={[{ id: "INFO", label: "Tümü" }, { id: "WARNING", label: "Uyarı+" }, { id: "ERROR", label: "Hatalar" }]} />} />
      <div style={{ position: "relative" }}><Search size={16} style={{ position: "absolute", left: 14, top: 14, color: "var(--text-3)" }} /><input aria-label="Günlükte ara" placeholder="Günlükte ara…" style={{ paddingLeft: 40 }} value={q} onChange={(e) => setQ(e.target.value)} /></div>
      {!data ? (error ? <ErrorBox message={error} /> : <Loading />) : (
        <Card flush>
          {data.items.length === 0 ? <Empty icon={<ScrollText size={22} />} title="Kayıt yok" /> : (
            <div className="logs">{data.items.map((l: J) => <div key={l.id} className={`log ${l.level.toLowerCase()}`}><span className="t">{timeFull(l.ts)}</span><span className="lv">{l.level}</span><span><span className="dim">[{l.source}]</span> {l.message}</span></div>)}</div>
          )}
        </Card>
      )}
    </>
  );
}
