import { useEffect, useState } from "react";
import { api, J } from "../api";
import { Card, Confirm, ErrorBox, Loading, PageTitle, usePoll } from "../ui";

export default function Settings() {
  const { data, error, reload } = usePoll(() => api.get("/settings"), 0);
  const [vals, setVals] = useState<Record<string, J>>({});
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [resetAsk, setResetAsk] = useState(false);
  const [paperAsk, setPaperAsk] = useState(false);

  useEffect(() => {
    if (data) setVals(data.values);
  }, [data]);

  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;
  const meta: J[] = data.meta;
  const groups = Array.from(new Set(meta.map((m) => m.group)));
  const dirty = JSON.stringify(vals) !== JSON.stringify(data.values);

  const save = async () => {
    setMsg(null);
    try {
      const changed: Record<string, J> = {};
      for (const m of meta) if (vals[m.key] !== data.values[m.key]) changed[m.key] = vals[m.key];
      await api.put("/settings", { values: changed });
      setMsg({ ok: true, text: "Ayarlar kaydedildi. Sonraki taramada geçerli olur." });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };

  return (
    <>
      <PageTitle sub="Varsayılanlar güvenli başlangıç test değerleridir. Değişiklikler sınır kontrolünden geçer.">Bot Ayarları</PageTitle>
      {msg && <div className={`alert ${msg.ok ? "ok" : "bad"}`} role="status">{msg.text}</div>}
      {groups.map((g) => (
        <Card key={g} title={g}>
          {meta.filter((m) => m.group === g).map((m) => (
            <div className="field" key={m.key}>
              <label htmlFor={m.key}>{m.label}{m.unit && <span className="muted small"> ({m.unit})</span>}</label>
              {m.kind === "bool" ? (
                <input id={m.key} type="checkbox" className="tgl" checked={!!vals[m.key]} onChange={(e) => setVals({ ...vals, [m.key]: e.target.checked })} />
              ) : m.kind === "select" ? (
                <select id={m.key} value={vals[m.key]} onChange={(e) => setVals({ ...vals, [m.key]: e.target.value })}>
                  {m.options.map((o: string) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input id={m.key} inputMode="decimal" value={vals[m.key] ?? ""} min={m.min} max={m.max}
                  onChange={(e) => {
                    const t = e.target.value.replace(",", ".");
                    setVals({ ...vals, [m.key]: t === "" || /[.]$/.test(t) || t === "-" ? t : m.kind === "int" ? parseInt(t, 10) : Number(t) });
                  }} />
              )}
              {m.help && <div className="small muted">{m.help}</div>}
              {m.min !== undefined && m.kind !== "bool" && m.kind !== "select" && <div className="small muted">Aralık: {m.min} – {m.max ?? "∞"}</div>}
            </div>
          ))}
        </Card>
      ))}
      <div className="sticky-actions">
        <button className="btn" onClick={() => setResetAsk(true)}>Varsayılana dön</button>
        <button className="btn primary grow" disabled={!dirty} onClick={save}>Kaydet</button>
      </div>
      <Card title="Sanal hesap">
        <p className="small muted">Sanal bakiyeyi ve tüm sanal işlem kayıtlarını sıfırlar. Bot kapalı olmalıdır.</p>
        <button className="btn danger" onClick={() => setPaperAsk(true)}>Sanal hesabı sıfırla</button>
      </Card>
      {resetAsk && <Confirm text="Tüm ayarlar varsayılana dönsün mü?" onNo={() => setResetAsk(false)} onYes={async () => { setResetAsk(false); await api.post("/settings/reset"); reload(); }} />}
      {paperAsk && <Confirm text="Sanal bakiye ve TÜM sanal işlem geçmişi silinecek. Emin misiniz?" onNo={() => setPaperAsk(false)} onYes={async () => {
        setPaperAsk(false);
        try { await api.post("/paper/reset", { confirm: true }); setMsg({ ok: true, text: "Sanal hesap sıfırlandı." }); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
      }} />}
    </>
  );
}
