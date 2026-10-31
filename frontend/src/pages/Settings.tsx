import { useEffect, useState } from "react";
import { Gauge, RotateCcw, Save, Shield, ShieldAlert, ShieldCheck, Trash2 } from "lucide-react";
import { api, J } from "../api";
import { Card, Confirm, ErrorBox, Loading, PageHeader, Switch, useToast, usePoll } from "../ui";

const PROFILES = [
  { id: "dusuk", name: "Düşük risk", sub: "Sermayeyi korumak öncelikli", Icon: ShieldCheck, brief: "%0,5 risk · %1 günlük limit · 3 pozisyon" },
  { id: "dengeli", name: "Dengeli", sub: "Başlangıç ayarı", Icon: Shield, brief: "%1 risk · %2 günlük limit · 5 pozisyon" },
  { id: "yuksek", name: "Yüksek risk", sub: "Daha fazla fırsat dener", Icon: ShieldAlert, brief: "%1,5 risk · %3 günlük limit · 7 pozisyon" },
];

export default function Settings() {
  const { data, error, reload } = usePoll(() => api.get("/settings"), 0);
  const [vals, setVals] = useState<Record<string, J>>({});
  const [resetAsk, setResetAsk] = useState(false);
  const [paperAsk, setPaperAsk] = useState(false);
  const toast = useToast();
  useEffect(() => { if (data) setVals(data.values); }, [data]);
  if (!data) return error ? <ErrorBox message={error} /> : <Loading />;

  const meta: J[] = data.meta.filter((m: J) => m.key !== "risk_profile");
  const groups = Array.from(new Set(meta.map((m) => m.group)));
  const dirty = JSON.stringify(vals) !== JSON.stringify(data.values);

  const save = async () => {
    try {
      const changed: Record<string, J> = {};
      for (const m of meta) if (vals[m.key] !== data.values[m.key]) changed[m.key] = vals[m.key];
      await api.put("/settings", { values: changed });
      toast("Ayarlar kaydedildi. Sonraki taramada geçerli olur.", "ok");
      reload();
    } catch (e) { toast((e as Error).message, "bad"); }
  };

  return (
    <>
      <PageHeader title="Bot Ayarları" subtitle="Varsayılanlar güvenli başlangıç test değerleridir. Tüm değişiklikler sınır kontrolünden geçer." />
      <Card title="Risk profili" icon={<Gauge />} subtitle="Profil seçmek ilgili tüm risk limitlerini topluca ayarlar. Hiçbir profil kaldıraç veya vadeli işlem açmaz.">
        <div className="profile-grid" role="radiogroup" aria-label="Risk profili">
          {PROFILES.map(({ id, name, sub, Icon, brief }) => (
            <button key={id} role="radio" aria-checked={data.values.risk_profile === id} className={`profile ${data.values.risk_profile === id ? "on" : ""}`}
              onClick={async () => { await api.post("/settings/profile", { profile: id }); toast(`${name} profili uygulandı.`, "ok"); reload(); }}>
              <Icon className="pi" /><div><b>{name}</b><span style={{ display: "block" }}>{sub}</span><span className="xs dim num" style={{ display: "block", marginTop: 4 }}>{brief}</span></div>
            </button>
          ))}
        </div>
        {data.values.risk_profile === "ozel" && <p className="small muted mt">Şu an <b>özel</b> ayarlar kullanılıyor (bir profille birebir eşleşmiyor).</p>}
      </Card>

      {groups.map((g) => (
        <Card key={g} title={g}>
          {meta.filter((m) => m.group === g).map((m) => (
            <div className="field" key={m.key}>
              <label className="fl" htmlFor={m.key}>{m.label}{m.unit && <span className="dim small"> · {m.unit}</span>}</label>
              {m.help && <div className="fh">{m.help}{m.min !== undefined && m.kind !== "bool" && m.kind !== "select" ? ` (${m.min} – ${m.max ?? "∞"})` : ""}</div>}
              <div className="ctl">
                {m.kind === "bool" ? <Switch checked={!!vals[m.key]} label={m.label} onChange={(v) => setVals({ ...vals, [m.key]: v })} />
                  : m.kind === "select" ? <select id={m.key} value={vals[m.key]} onChange={(e) => setVals({ ...vals, [m.key]: e.target.value })}>{m.options.map((o: string) => <option key={o} value={o}>{o}</option>)}</select>
                  : <input id={m.key} className="num" inputMode="decimal" value={vals[m.key] ?? ""} onChange={(e) => {
                    const t = e.target.value.replace(",", ".");
                    setVals({ ...vals, [m.key]: t === "" || /[.]$/.test(t) || t === "-" ? t : m.kind === "int" ? parseInt(t, 10) : Number(t) });
                  }} />}
              </div>
            </div>
          ))}
        </Card>
      ))}

      <Card title="Sanal hesap" subtitle="Sanal bakiyeyi ve tüm sanal işlem kayıtlarını sıfırlar. Bot kapalı olmalıdır.">
        <button className="btn danger" onClick={() => setPaperAsk(true)}><Trash2 /> Sanal hesabı sıfırla</button>
      </Card>

      <div className="sticky-actions">
        <button className="btn" onClick={() => setResetAsk(true)}><RotateCcw /> Varsayılana dön</button>
        <button className="btn primary grow" disabled={!dirty} onClick={save}><Save /> {dirty ? "Değişiklikleri kaydet" : "Kaydedildi"}</button>
      </div>
      {resetAsk && <Confirm title="Varsayılana dön" text="Tüm ayarlar varsayılana dönsün mü?" danger={false} yesLabel="Evet, sıfırla" onNo={() => setResetAsk(false)} onYes={async () => { setResetAsk(false); await api.post("/settings/reset"); toast("Varsayılan ayarlar geri yüklendi.", "ok"); reload(); }} />}
      {paperAsk && <Confirm title="Sanal hesabı sıfırla" text="Sanal bakiye ve TÜM sanal işlem geçmişi silinecek. Emin misiniz?" yesLabel="Sil ve sıfırla" onNo={() => setPaperAsk(false)} onYes={async () => {
        setPaperAsk(false);
        try { await api.post("/paper/reset", { confirm: true }); toast("Sanal hesap sıfırlandı.", "ok"); } catch (e) { toast((e as Error).message, "bad"); }
      }} />}
    </>
  );
}
