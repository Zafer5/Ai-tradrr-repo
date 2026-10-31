"use strict";
const TABS = [
  ["home", "Ana Sayfa"], ["scanner", "Tarayıcı"], ["ai", "Analizler"], ["positions", "Pozisyonlar"],
  ["history", "Geçmiş"], ["report", "Kâr-Zarar"], ["settings", "Bot Ayarları"], ["risk", "Risk"],
  ["api", "Bağlantılar"], ["logs", "Günlükler"],
];
let tab = "home", timer = null;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = (v, d = 2) => v == null || isNaN(v) ? "—" : Number(v).toLocaleString("tr-TR", {minimumFractionDigits: d, maximumFractionDigits: d});
const px = v => v == null ? "—" : Number(v).toPrecision(6).replace(/\.?0+$/, "");
const pnl = (v, d = 2) => `<span class="${v > 0 ? "pos" : v < 0 ? "neg" : ""}">${v > 0 ? "+" : ""}${num(v, d)}</span>`;
const ago = t => !t ? "henüz yok" : `${Math.max(0, Math.round(Date.now() / 1000 - t))} sn önce`;
const date = s => s ? new Date(s + (s.endsWith("Z") ? "" : "Z")).toLocaleString("tr-TR") : "—";
const scoreCls = s => s >= 85 ? "s85" : s >= 70 ? "s70" : s >= 50 ? "s50" : "s0";

async function api(path, opts = {}) {
  const r = await fetch(path, {credentials: "same-origin", headers: {"Content-Type": "application/json"}, ...opts});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `Hata ${r.status}`);
  return j;
}

function renderNav() {
  $("#nav").innerHTML = TABS.map(([k, t]) => `<button data-t="${k}" class="${k === tab ? "active" : ""}">${t}</button>`).join("");
  $("#nav").querySelectorAll("button").forEach(b => b.onclick = () => { tab = b.dataset.t; renderNav(); load(); });
}

async function updateBadge() {
  try {
    const s = await api("/api/status");
    const b = $("#botBadge");
    b.textContent = s.emergency_stop ? "ACİL DURDU" : s.running ? "Bot açık" : "Bot kapalı";
    b.className = "badge " + (s.running && !s.emergency_stop ? "on" : "off");
    return s;
  } catch (e) { return null; }
}

const V = {};
V.home = async () => {
  const s = await updateBadge();
  if (!s) return `<div class="card">Sunucuya ulaşılamadı.</div>`;
  const stat = (k, v) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  return `
  ${s.halted_reason ? `<div class="notice">⚠ ${esc(s.halted_reason)}</div>` : ""}
  ${s.last_error ? `<div class="notice">Son hata: ${esc(s.last_error)}</div>` : ""}
  <div class="grid">
    ${stat("Toplam sanal bakiye", num(s.equity) + " $")}
    ${stat("Nakit", num(s.cash) + " $")}
    ${stat("Günlük kâr", pnl(s.daily_pnl))}
    ${stat("Toplam kâr-zarar", pnl(s.total_pnl))}
    ${stat("Açık işlemler", s.open_positions)}
    ${stat("Kapanan işlemler", s.closed_positions)}
    ${stat("Takip edilen coin", s.tracked_coins)}
    ${stat("Bugünkü işlem", s.trades_today)}
    ${stat("Komisyon toplamı", num(s.total_fees) + " $")}
    ${stat("Canlı fiyat akışı", s.ws_connected ? "Bağlı" : "Bağlı değil")}
  </div>
  <div class="card">
    <div class="small">Son tarama: ${ago(s.last_universe_at)} · Son analiz: ${ago(s.last_analysis_at)}</div>
    ${s.emergency_stop
      ? `<button class="btn grey" onclick="act('/api/bot/emergency',{active:false})">Acil durdurmayı kaldır</button>`
      : s.running
        ? `<button class="btn grey" onclick="act('/api/bot/run',{running:false})">Botu durdur</button>`
        : `<button class="btn green" onclick="act('/api/bot/run',{running:true})">Botu başlat (sanal)</button>`}
    <button class="btn red" onclick="emergency()">ACİL DURDUR</button>
  </div>
  <h2>En iyi fırsatlar</h2>
  <div class="card">${s.top_opportunities.length ? s.top_opportunities.map(o =>
    `<div class="row"><b>${esc(o.symbol)}</b><span>${esc(o.label)} <span class="score ${scoreCls(o.score)}">${o.score}</span></span></div>`).join("")
    : `<div class="small">Henüz analiz yok. İlk analiz birkaç dakika sürebilir.</div>`}</div>`;
};

V.scanner = async () => {
  const d = await api("/api/scanner");
  return `<div class="small">Güncelleme: ${ago(d.updated_at)} · ${d.coins.length} coin seçildi, ${d.rejected} coin elendi</div>
  <div class="card">${d.coins.map((c, i) => `<div class="row"><div><b>${i + 1}. ${esc(c.symbol)}</b><div class="small">Hacim ${num(c.quote_volume / 1e6, 1)} M$ · Spread %${num(c.spread_pct, 3)}</div></div>
    <div style="text-align:right">${px(c.price)}<div class="small">${pnl(c.change_pct)}%</div></div></div>`).join("") || "Liste henüz hazır değil."}</div>`;
};

V.ai = async () => {
  const d = await api("/api/analyses");
  return `<div class="notice">Puanlar olasılık tahminidir, kesin değildir. Hiçbir strateji kâr garantisi vermez. Her işlem ayrıca risk kontrolünden geçer.</div>
  <div class="small">Son analiz: ${ago(d.updated_at)}</div>
  ${d.items.map(a => `<div class="card"><div class="row"><b>${esc(a.symbol)}</b><span>${esc(a.label)} <span class="score ${scoreCls(a.score)}">${a.score}</span></span></div>
    <div class="small">Fiyat ${px(a.price)} · Trend: ${esc(a.trend)} · Risk: ${esc(a.risk_level)} · Hedef ${px(a.take_profit)} · Stop ${px(a.stop_loss)}</div>
    ${a.reasons.length ? `<ul>${a.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
    ${a.warnings.length ? `<ul class="neg">${a.warnings.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}</div>`).join("") || `<div class="card">Henüz analiz yok.</div>`}`;
};

V.positions = async () => {
  const d = await api("/api/positions?state=open");
  return d.map(p => `<div class="card"><div class="row"><b>${esc(p.symbol)}</b><span>${p.unrealized_pnl != null ? pnl(p.unrealized_pnl) + " $" : ""}</span></div>
    <div class="small">Alış ${px(p.entry_price)} · Şimdi ${px(p.current_price)} · Miktar ${p.quantity}</div>
    <div class="small">Hedef ${px(p.take_profit)} · Stop ${px(p.stop_loss)} · Puan ${p.score}${p.scaled_out ? " · Kısmi satış yapıldı" : ""}</div>
    <div class="small">Gerekçe: ${esc(p.reason)}</div>
    <button class="btn grey" onclick="closePos(${p.id})">Pozisyonu kapat</button></div>`).join("") || `<div class="card">Açık pozisyon yok.</div>`;
};

V.history = async () => {
  const d = await api("/api/trades");
  return `<div class="card">${d.map(t => `<div class="row"><div><b class="${t.side === "BUY" ? "pos" : "neg"}">${t.side === "BUY" ? "ALIŞ" : "SATIŞ"}</b> ${esc(t.symbol)}
    <div class="small">${date(t.created_at)} · ${esc(t.note)}</div></div>
    <div style="text-align:right">${px(t.price)} × ${t.quantity}<div class="small">Komisyon ${num(t.fee, 4)}${t.side === "SELL" ? " · Net " + pnl(t.pnl) : ""}</div></div></div>`).join("") || "Henüz işlem yok."}</div>`;
};

V.report = async () => {
  const r = await api("/api/report");
  const row = (k, v) => `<div class="row"><span>${k}</span><b>${v}</b></div>`;
  return `<div class="card">
    ${row("Kapanan işlem", r.closed_trades)}${row("Net kâr-zarar", pnl(r.net_pnl) + " $")}
    ${row("Kazanç oranı", r.win_rate == null ? "—" : "%" + num(r.win_rate))}
    ${row("Ortalama kazanç", num(r.avg_win))}${row("Ortalama kayıp", num(r.avg_loss))}
    ${row("Kâr faktörü", r.profit_factor ?? "—")}${row("Azami düşüş", "%" + num(r.max_drawdown_pct))}
    ${row("Ödenen komisyon", num(r.total_fees, 4) + " $")}</div>
    <div class="notice">${esc(r.note)}</div>
    <h2>Günlük</h2><div class="card">${r.daily.map(d => row(d.day, pnl(d.pnl))).join("") || "Veri yok."}</div>`;
};

const FIELDS = {
  settings: [
    ["targets", "use_atr_targets", "Hedef/stop'u volatiliteye (ATR) göre hesapla", "bool"],
    ["targets", "atr_tp_mult", "Kâr hedefi = fiyat + ATR ×"], ["targets", "atr_sl_mult", "Stop = fiyat − ATR ×"],
    ["targets", "take_profit_pct", "Yüzdesel kâr hedefi (%) (ATR kapalıyken)"], ["targets", "stop_loss_pct", "Yüzdesel stop-loss (%) (ATR kapalıyken)"],
    ["trade", "trailing_enabled", "İz süren stop (trailing stop)", "bool"], ["trade", "trailing_activation_pct", "İz süren stop devreye girme kârı (%)"],
    ["trade", "trailing_pct", "En yüksekten geri çekilme (%)"], ["trade", "scale_out_enabled", "Kademeli satış", "bool"],
    ["trade", "scale_out_fraction", "İlk hedefte satılacak oran (0-1)"], ["trade", "analysis_interval_sec", "Analiz aralığı (sn)"],
    ["scan", "max_coins", "Taranacak coin sayısı"], ["scan", "min_quote_volume", "En düşük 24s hacim (USDT)"],
    ["scan", "max_spread_pct", "En yüksek spread (%)"], ["scan", "exclude_stablecoins", "Stablecoinleri dışla", "bool"],
    ["scan", "exclude_leveraged", "Kaldıraçlı tokenleri dışla", "bool"],
  ],
  risk: [
    ["risk", "risk_per_trade_pct", "İşlem başına azami risk (sermayenin %)"], ["risk", "daily_loss_limit_pct", "Günlük zarar limiti (%)"],
    ["risk", "max_open_positions", "Aynı anda en fazla açık pozisyon"], ["risk", "max_per_coin_pct", "Tek coine en fazla (%)"],
    ["risk", "max_total_exposure_pct", "Toplam açık işlem maruziyeti en fazla (%)"], ["risk", "min_score", "Alım için en düşük puan"],
    ["risk", "fee_pct", "Komisyon (%)"], ["risk", "slippage_pct", "Tahmini fiyat kayması (%)"],
  ],
};
let current = null;
const form = async which => {
  current = await api("/api/settings");
  return `<div class="card">${which === "risk" ? `<div class="notice">Kaldıraç ve vadeli işlemler kapalıdır. Zarar limiti aşılırsa yeni alımlar durur.</div>` : ""}
  ${FIELDS[which].map(([g, k, l, t]) => t === "bool"
    ? `<label class="chk"><input type="checkbox" data-g="${g}" data-k="${k}" ${current[g][k] ? "checked" : ""}> ${l}</label>`
    : `<label>${l}</label><input type="number" step="any" data-g="${g}" data-k="${k}" value="${current[g][k]}">`).join("")}
  <button class="btn" onclick="saveSettings()">Kaydet</button></div>`;
};
V.settings = () => form("settings");
V.risk = () => form("risk");

V.api = async () => {
  const c = await api("/api/connections");
  const row = (k, v) => `<div class="row"><span>${k}</span><b style="text-align:right">${esc(v)}</b></div>`;
  return `<div class="card">${row("Borsa", c.exchange)}${row("Mod", "Paper Trading (sanal)")}${row("Piyasa verisi", c.market_data)}
    ${row("Canlı fiyat akışı", c.websocket_connected ? "Bağlı" : "Bağlı değil")}${row("Gerçek işlem", c.live_trading)}</div>
    <div class="notice">Bu aşamada API anahtarı gerekmez. API anahtarları hiçbir zaman bu panele veya sohbete yazılmaz; ileride yalnızca sunucudaki .env dosyasına eklenecek.</div>`;
};

V.logs = async () => {
  const d = await api("/api/logs");
  return `<div class="card">${d.map(l => `<div class="log ${l.level}">${date(l.at)} [${l.level}] ${esc(l.message)}</div>`).join("") || "Kayıt yok."}</div>`;
};

async function load() {
  clearTimeout(timer);
  try { $("#view").innerHTML = await V[tab](); if (tab !== "home") updateBadge(); }
  catch (e) { $("#view").innerHTML = `<div class="card neg">${esc(e.message)}</div>`; }
  if (!["settings", "risk"].includes(tab)) timer = setTimeout(load, 10000);
}

async function act(path, body) {
  try { await api(path, {method: "POST", body: JSON.stringify(body)}); } catch (e) { alert(e.message); }
  load();
}
function emergency() {
  if (!confirm("Acil durdurma: yeni alımlar durur. Devam?")) return;
  const close = confirm("Açık pozisyonlar da hemen (sanal) satılsın mı?");
  act("/api/bot/emergency", {active: true, close_positions: close});
}
async function closePos(id) {
  if (!confirm("Bu pozisyon şimdiki fiyattan (sanal) satılsın mı?")) return;
  try { await api(`/api/positions/${id}/close`, {method: "POST"}); } catch (e) { alert(e.message); }
  load();
}
async function saveSettings() {
  const data = {};
  document.querySelectorAll("[data-g]").forEach(i => {
    (data[i.dataset.g] ||= {})[i.dataset.k] = i.type === "checkbox" ? i.checked : Number(i.value);
  });
  try { await api("/api/settings", {method: "PUT", body: JSON.stringify(data)}); alert("Kaydedildi"); }
  catch (e) { alert("Kaydedilemedi: " + e.message); }
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
renderNav(); load();
