import { useState } from "react";
import { AlertOctagon, CheckCircle2, Circle, FlaskConical, KeyRound, Lock, ShieldAlert, Wallet, Zap } from "lucide-react";
import { api, J } from "../api";
import { usd } from "../format";
import { Badge, Banner, Card, ErrorBox, Loading, PageHeader, Sheet, useToast, usePoll } from "../ui";

function Check({ ok, children, hint }: { ok: boolean; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <li className="li" style={{ alignItems: "flex-start", padding: "10px 0", borderTop: 0 }}>
      {ok ? <CheckCircle2 size={19} style={{ color: "var(--pos)", flex: "none", marginTop: 1 }} /> : <Circle size={19} style={{ color: "var(--text-3)", flex: "none", marginTop: 1 }} />}
      <div><div className={ok ? "" : "muted"}>{children}</div>{!ok && hint && <div className="xs dim" style={{ marginTop: 2 }}>{hint}</div>}</div>
    </li>
  );
}

export default function TradingMode() {
  const { data: d, error, reload } = usePoll(() => api.get("/trading-mode"), 5000);
  const toast = useToast();
  const [capT, setCapT] = useState("1000");
  const [capL, setCapL] = useState("");
  const [phrase, setPhrase] = useState("");
  const [pw, setPw] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [liveTest, setLiveTest] = useState<J | null>(null);
  const [confirm, setConfirm] = useState<"live" | null>(null);
  if (!d) return error ? <ErrorBox message={error} /> : <Loading />;

  const num = (s: string) => parseFloat(s.replace(",", "."));
  const blocked = d.bot_running || d.open_positions > 0;
  const call = async (body: J, ok: string) => {
    setBusy(true);
    try { await api.post("/trading-mode", body); toast(ok, "ok"); setPw(""); setPhrase(""); setAck(false); reload(); } catch (e) { toast((e as Error).message, "bad"); } finally { setBusy(false); }
  };
  const testLive = async () => {
    setBusy(true);
    try { setLiveTest(await api.post("/connections/live/test")); } catch (e) { toast((e as Error).message, "bad"); setLiveTest(null); } finally { setBusy(false); }
  };
  const liveReady = d.server_allows_live && d.live_key && liveTest?.ok && num(capL) >= d.min_live_capital && phrase.trim().length > 10 && pw.length > 0 && ack;

  return (
    <>
      <PageHeader title="İşlem Modu" subtitle="Bot üç modda çalışabilir. Önce sanal, sonra Testnet, en son — hazırsanız — gerçek hesap." />
      <Banner kind={d.mode === "live" ? "bad" : d.mode === "testnet" ? "info" : "warn"} icon={d.mode === "live" ? <AlertOctagon /> : <Lock />}>
        <b>Şu an: {d.label} mod.</b>{" "}
        {d.mode === "paper" && "Hiçbir emir borsaya gitmiyor; her şey simülasyon."}
        {d.mode === "testnet" && `Emirler Binance Testnet'e gidiyor (sanal paralı test borsası). Sermaye tavanı ${usd(d.capital)} USDT.`}
        {d.mode === "live" && `Bot GERÇEK hesabınızda gerçek parayla emir veriyor. Kullanabileceği azami sermaye: ${usd(d.capital)} USDT.`}
        {d.mode !== "paper" && !d.executor_ok && <div className="mt-s"><b>Borsa bağlantısı yok:</b> {d.executor_error}</div>}
      </Banner>
      {d.halt && <Banner kind="bad" icon={<ShieldAlert />}><b>Yeni emirler durduruldu:</b> {d.halt}</Banner>}
      {blocked && <Banner kind="info">Mod değiştirmek için botu durdurun ve açık pozisyonları kapatın ({d.bot_running ? "bot çalışıyor" : ""}{d.bot_running && d.open_positions > 0 ? ", " : ""}{d.open_positions > 0 ? `${d.open_positions} açık pozisyon var` : ""}).</Banner>}

      <div className="grid split-even">
        <Card title="1 · Sanal (paper)" icon={<Wallet />} actions={d.mode === "paper" && <Badge kind="ok">Aktif</Badge>} subtitle="Gerçek piyasa fiyatı, sanal bakiye. Risksiz deneme.">
          <button className="btn block" disabled={busy || blocked || d.mode === "paper"} onClick={() => call({ mode: "paper" }, "Sanal moda geçildi.")}>Sanal moda geç</button>
        </Card>

        <Card title="2 · Testnet" icon={<FlaskConical />} actions={d.mode === "testnet" && <Badge kind="ok">Aktif</Badge>} subtitle="Gerçek emir akışı, sanal parayla (testnet.binance.vision). Testnet fiyatları gerçek piyasadan farklıdır.">
          <ul className="list" style={{ margin: "0 0 4px" }}><Check ok={d.testnet_key} hint={<>Önce <a href="#/connections" style={{ color: "var(--accent)" }}>API Bağlantıları</a>'nda Testnet anahtarını kaydedin.</>}>Testnet API anahtarı kayıtlı</Check></ul>
          <label className="lb" htmlFor="capT">Azami sermaye (USDT)</label>
          <input id="capT" inputMode="decimal" value={capT} onChange={(e) => setCapT(e.target.value)} />
          <button className="btn primary block mt" disabled={busy || blocked || !d.testnet_key || d.mode === "testnet"} onClick={() => call({ mode: "testnet", capital: num(capT) }, "Testnet moduna geçildi.")}><FlaskConical /> Testnet'e geç</button>
        </Card>
      </div>

      <Card title="3 · GERÇEK hesap" icon={<Zap />} actions={d.mode === "live" ? <Badge kind="bad" dot>Aktif</Badge> : <Badge kind="bad">Gerçek para</Badge>} subtitle="Gerçek Binance hesabınızda gerçek emirler. Bu adımı yalnızca Testnet'te davranışı gözlemledikten sonra atın.">
        <Banner kind="bad" icon={<AlertOctagon />}>
          <b>Açık uyarı.</b> Kâr garantisi yoktur ve para kaybedebilirsiniz. Strateji gerçek piyasa verisiyle doğrulanmış (backtest edilmiş) değildir. Stop-loss'lar <b>bot çalışırken</b> sunucu tarafından uygulanır; sunucu/bağlantı kesilirse borsada bekleyen koruma emri <b>yoktur</b>. Yalnızca kaybetmeyi göze alabileceğiniz küçük bir tutarla başlayın.
        </Banner>
        <ul className="list" style={{ margin: "12px 0 4px" }}>
          <Check ok={d.server_allows_live} hint={<>Sunucudaki <code>.env</code> dosyasına <code>ALLOW_LIVE_TRADING=true</code> ekleyip <code>docker compose up -d</code> ile yeniden başlatın.</>}>Sunucu sahibi gerçek işleme izin verdi</Check>
          <Check ok={d.live_key} hint={<><a href="#/connections" style={{ color: "var(--accent)" }}>API Bağlantıları</a>'nda gerçek hesap anahtarını kaydedin (yalnızca Spot alım-satım; <b>para çekme KAPALI</b>; IP kısıtlı).</>}>Gerçek hesap API anahtarı kayıtlı</Check>
          <Check ok={!!liveTest?.ok} hint="Aşağıdaki 'Anahtar izinlerini kontrol et' düğmesine basın.">Anahtar izinleri güvenli (alım-satım açık, para çekme kapalı)</Check>
        </ul>
        <button className="btn sm" disabled={busy || !d.live_key} onClick={testLive}><KeyRound /> Anahtar izinlerini kontrol et</button>
        {liveTest && <div className="mt"><Banner kind={liveTest.ok ? "ok" : "bad"}>{liveTest.ok ? `İzinler uygun. Hesapta serbest ${usd(liveTest.usdt_free)} USDT var.` : liveTest.problems.join(" ")}</Banner></div>}

        <label className="lb" htmlFor="capL">Botun kullanabileceği AZAMİ sermaye (USDT) — en az {d.min_live_capital}</label>
        <input id="capL" inputMode="decimal" placeholder="örn. 100" value={capL} onChange={(e) => setCapL(e.target.value)} />
        <p className="xs dim mt-s">Hesabınızda daha fazla para olsa bile bot bu tutarın ötesine geçmez. Hesapta aynı coinden bakiyeniz varsa bot o coine alım yapmaz (sizin coininize dokunmaz).</p>

        <label className="lb" htmlFor="ph">Onay cümlesi — aynen yazın:</label>
        <div className="small bold" style={{ padding: "8px 12px", background: "var(--neg-soft)", color: "var(--neg)", borderRadius: 10, marginBottom: 8 }}>{d.confirm_phrase}</div>
        <input id="ph" autoComplete="off" value={phrase} onChange={(e) => setPhrase(e.target.value)} />
        <label className="lb" htmlFor="pw2">Panel şifreniz</label>
        <input id="pw2" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} />
        <label className="row mt" style={{ gap: 10, cursor: "pointer", alignItems: "flex-start" }}>
          <input type="checkbox" style={{ width: 20, height: 20, marginTop: 2 }} checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span className="small">Para kaybedebileceğimi, stratejinin kanıtlanmadığını ve botun çalışmadığı anlarda stop-loss'un işlemeyeceğini anlıyorum.</span>
        </label>
        <button className="btn danger block mt" disabled={busy || blocked || !liveReady || d.mode === "live"} onClick={() => setConfirm("live")}><Zap /> Gerçek işlemi etkinleştir</button>
        {d.mode === "live" && <button className="btn block mt" disabled={busy || blocked} onClick={() => call({ mode: "paper" }, "Sanal moda dönüldü.")}>Sanal moda dön</button>}
        <p className="xs dim mt-s">Etkinleştirdikten sonra bot yine KAPALI kalır; Ana Sayfa'dan elle başlatırsınız. Acil durdurma her zaman çalışır.</p>
      </Card>

      {confirm && (
        <Sheet title="Son onay" onClose={() => setConfirm(null)} footer={<><button className="btn" onClick={() => setConfirm(null)}>Vazgeç</button><button className="btn danger" onClick={() => { setConfirm(null); call({ mode: "live", capital: num(capL), confirm_phrase: phrase, password: pw }, "GERÇEK mod etkinleştirildi. Bot kapalı; Ana Sayfa'dan başlatabilirsiniz."); }}>Evet, gerçek parayla çalış</button></>}>
          <p className="muted">Bot, gerçek Binance hesabınızda en fazla <b>{usd(num(capL))} USDT</b> sermaye ile gerçek alım-satım emirleri verecek.</p>
        </Sheet>
      )}
    </>
  );
}
