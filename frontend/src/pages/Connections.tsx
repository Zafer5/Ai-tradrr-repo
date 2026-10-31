import { useState } from "react";
import { BellRing, Database, FlaskConical, KeyRound, Lock, Trash2 } from "lucide-react";
import { api, J } from "../api";
import { time } from "../format";
import { Badge, Banner, Card, ErrorBox, Loading, PageHeader, useToast, usePoll } from "../ui";

function KeyForm({ title, icon, status, hint, notice, saveUrl, testUrl, delUrl, reload }: { title: string; icon: React.ReactNode; status: J; hint: string; notice: React.ReactNode; saveUrl: string; testUrl: string; delUrl: string; reload: () => void }) {
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); } catch (e) { toast((e as Error).message, "bad"); } finally { setBusy(false); } };
  return (
    <Card title={title} icon={icon} actions={<Badge kind={status.configured ? "ok" : ""}>{status.configured ? "Kayıtlı" : "Kayıtsız"}</Badge>} subtitle={hint}>
      {status.configured && <p className="small mono" style={{ marginBottom: 10 }}>Kayıtlı anahtar: <code>{status.key_hint}</code> · {time(status.updated_at)}</p>}
      <Banner kind="info">{notice}</Banner>
      <form autoComplete="off" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.put(saveUrl, { api_key: key, api_secret: secret }); setKey(""); setSecret(""); toast("Anahtarlar şifreli olarak kaydedildi. Bir daha gösterilmez.", "ok"); reload(); }); }}>
        <label className="lb" htmlFor={`${saveUrl}-k`}>API Key</label><input id={`${saveUrl}-k`} type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
        <label className="lb" htmlFor={`${saveUrl}-s`}>Secret Key</label><input id={`${saveUrl}-s`} type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} />
        <div className="row wrap mt">
          <button className="btn primary grow" disabled={busy || key.length < 16 || secret.length < 16}><Lock /> Şifreli kaydet</button>
          <button type="button" className="btn" disabled={busy || !status.configured} onClick={() => run(async () => {
            const r: J = await api.post(testUrl);
            const warns: string[] = r.warnings ?? (r.warning ? [r.warning] : []);
            toast(warns.length ? warns.join(" ") : `Bağlantı başarılı. Yetkiler: ${r.permissions.join(", ")}. Para çekme yetkisi kapalı.`, warns.length ? "warn" : "ok");
          })}>Test et</button>
          <button type="button" className="btn danger icon" aria-label="Anahtarı sil" disabled={!status.configured} onClick={() => run(async () => { await api.del(delUrl); reload(); })}><Trash2 /></button>
        </div>
      </form>
    </Card>
  );
}

export default function Connections() {
  const { data: d, error, reload } = usePoll(() => api.get("/connections"), 10000);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;
  return (
    <>
      <PageHeader title="API Bağlantıları" subtitle="Anahtarlar sunucuda şifreli saklanır, loglara yazılmaz ve bu ekrana geri gönderilmez. Para çekme yetkisi hiçbir yerde gerekmez." />
      <div className="grid split-even">
        <Card title="Binance piyasa verisi" icon={<Database />} actions={<Badge kind={d.market_data.ws_connected ? "ok" : "warn"} dot={d.market_data.ws_connected}>{d.market_data.ws_connected ? "Canlı akış bağlı" : "REST yedek"}</Badge>}>
          <p className="small muted">Fiyat ve mum verisi Binance'in herkese açık uçlarından alınır; <b>API anahtarı gerekmez</b>.</p>
          <p className="small mono dim mt-s">{d.market_data.base_url}</p>
          {d.market_data.last_error && <div className="mt"><Banner kind="warn">Son hata: {d.market_data.last_error}</Banner></div>}
        </Card>
        <Card title="Bildirimler" icon={<BellRing />} actions={<Badge kind={d.telegram ? "ok" : ""}>{d.telegram ? "Telegram açık" : "Telegram kapalı"}</Badge>}>
          <p className="small muted">Bildirimler her zaman <a href="#/notifications" style={{ color: "var(--accent)" }}>Bildirimler</a> ekranında görünür. Telefona anlık gönderim için sunucu ayarlarına (<code>.env</code>) Telegram bot bilgisi eklenir; adımlar README'de.</p>
        </Card>
      </div>
      <div className="grid split-even">
        <KeyForm title="Binance hesabım — salt okunur" icon={<KeyRound />} status={d.readonly} hint="Mevcut coinlerinizi ve geçmiş alımlarınızı okumak için" saveUrl="/connections/readonly" testUrl="/connections/readonly/test" delUrl="/connections/readonly" reload={reload}
          notice={<>Binance → API Yönetimi'nde yeni anahtar oluşturun ve <b>yalnızca "Enable Reading"</b> seçin. <b>Para çekme, alım-satım ve diğer tüm yetkileri KAPALI bırakın</b>; mümkünse sunucunuzun IP'sini kısıtlayın. Sistem emir göndermez.</>} />
        <KeyForm title="Binance Spot Testnet — Aşama 2" icon={<FlaskConical />} status={d.testnet} hint="Sanal paralı test borsası" saveUrl="/connections/testnet" testUrl="/connections/testnet/test" delUrl="/connections/testnet" reload={reload}
          notice={<>Yalnızca <b>Testnet</b> anahtarı girin (testnet.binance.vision). Gerçek hesap anahtarınızı buraya girmeyin. {d.testnet.stage}</>} />
      </div>
      <KeyForm title="Binance GERÇEK hesap — alım-satım" icon={<Lock />} status={d.live} hint={d.live.active ? "Şu an gerçek mod AKTİF" : d.live.server_allowed ? "Sunucu gerçek işleme izin veriyor" : "Sunucuda gerçek işlem kilitli (ALLOW_LIVE_TRADING)"} saveUrl="/connections/live" testUrl="/connections/live/test" delUrl="/connections/live" reload={reload}
        notice={<>Binance → API Yönetimi: <b>yalnızca "Enable Spot &amp; Margin Trading"</b> seçin. <b>"Enable Withdrawals" KAPALI olmalı</b> (açıksa sistem anahtarı reddeder). Anahtarı <b>sunucunuzun IP adresiyle</b> kısıtlayın. Anahtar kaydetmek işlem başlatmaz; gerçek mod ayrıca <a href="#/mode" style={{ color: "var(--accent)" }}>İşlem Modu</a> ekranında onaylanır.</>} />
    </>
  );
}
