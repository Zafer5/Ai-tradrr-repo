import { useState } from "react";
import { api, J } from "../api";
import { time } from "../format";
import { Badge, Card, ErrorBox, Loading, PageTitle, usePoll } from "../ui";

export default function Connections() {
  const { data: d, error, reload } = usePoll(() => api.get("/connections"), 10000);
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  const t = d.testnet;

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.put("/connections/testnet", { api_key: key, api_secret: secret });
      setKey("");
      setSecret("");
      setMsg({ ok: true, text: "Anahtarlar şifreli olarak kaydedildi. Bir daha gösterilmez." });
      reload();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const test = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r: J = await api.post("/connections/testnet/test");
      setMsg({ ok: !r.warning, text: r.warning ?? `Bağlantı başarılı. Yetkiler: ${r.permissions.join(", ")} · Alım-satım: ${r.can_trade ? "açık" : "kapalı"}` });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    await api.del("/connections/testnet");
    reload();
  };

  return (
    <>
      <PageTitle>API Bağlantıları</PageTitle>
      {msg && <div className={`alert ${msg.ok ? "ok" : "bad"}`} role="status">{msg.text}</div>}
      <Card title="Binance piyasa verisi" right={<Badge kind={d.market_data.ws_connected ? "ok" : "warn"}>{d.market_data.ws_connected ? "Canlı akış bağlı" : "Akış bağlı değil"}</Badge>}>
        <p className="small">Fiyat ve mum verisi Binance'in herkese açık uçlarından alınır; <b>API anahtarı gerekmez</b>. Adres: {d.market_data.base_url}</p>
        {d.market_data.last_error && <div className="alert warn">Son hata: {d.market_data.last_error}</div>}
      </Card>

      <Card title="Binance Spot Testnet (Aşama 2)" right={<Badge kind={t.configured ? "ok" : ""}>{t.configured ? "Kayıtlı" : "Kayıtsız"}</Badge>}>
        <p className="small muted">{t.stage}</p>
        {t.configured && <p className="small">Kayıtlı anahtar: <code>{t.key_hint}</code> · {time(t.updated_at)}</p>}
        <div className="alert info small">Yalnızca <b>Testnet</b> anahtarı girin (testnet.binance.vision). Gerçek hesap anahtarınızı buraya girmeyin. Anahtarda <b>para çekme yetkisi olmamalıdır</b>; gerçek hesap için ayrıca IP kısıtlaması önerilir. Anahtarlar sunucuda şifreli saklanır, bu ekrana geri gönderilmez.</div>
        <form autoComplete="off" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <label htmlFor="ak">API Key</label>
          <input id="ak" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
          <label htmlFor="as">Secret Key</label>
          <input id="as" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} />
          <div className="row mt">
            <button className="btn primary grow" disabled={busy || key.length < 16 || secret.length < 16}>Şifreli kaydet</button>
            <button type="button" className="btn" disabled={busy || !t.configured} onClick={test}>Bağlantıyı test et</button>
            <button type="button" className="btn danger" disabled={!t.configured} onClick={remove}>Sil</button>
          </div>
        </form>
      </Card>

      <Card title="Gerçek hesap (Aşama 3)" right={<Badge kind="bad">KİLİTLİ</Badge>}>
        <p className="small">{d.live.message}</p>
      </Card>
    </>
  );
}
