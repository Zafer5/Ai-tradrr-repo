import { useState } from "react";
import { api, J } from "../api";
import { timeFull } from "../format";
import { Card, Empty, ErrorBox, Loading, PageTitle, usePoll } from "../ui";

export default function Logs() {
  const [level, setLevel] = useState("INFO");
  const [q, setQ] = useState("");
  const { data, error } = usePoll(() => api.get(`/logs?limit=300&level=${level}${q ? `&q=${encodeURIComponent(q)}` : ""}`), 5000, [level, q]);
  return (
    <>
      <PageTitle sub="Gizli bilgiler (API anahtarı, imza, şifre) günlüklerde otomatik maskelenir.">Sistem Günlükleri</PageTitle>
      <div className="row">
        <select aria-label="Seviye" value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="INFO">Tümü (INFO+)</option><option value="WARNING">Uyarı+</option><option value="ERROR">Yalnızca hatalar</option>
        </select>
        <input aria-label="Ara" placeholder="Ara…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {!data ? (error ? <ErrorBox message={error} /> : <Loading />) : (
        <Card>
          {data.items.length === 0 ? <Empty>Kayıt yok.</Empty> : (
            <ul className="logs">
              {data.items.map((l: J) => (
                <li key={l.id} className={`log ${l.level.toLowerCase()}`}>
                  <span className="small muted">{timeFull(l.ts)}</span> <b>{l.level}</b> <span className="muted">[{l.source}]</span> {l.message}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </>
  );
}
