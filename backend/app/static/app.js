"use strict";
const TABS = [
  ["home", "Ana Sayfa"], ["live", "Canlı"], ["chart", "Grafik"], ["radar", "Radar"], ["scanner", "Tarayıcı"], ["ai", "Analizler"], ["positions", "Pozisyonlar"],
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
    const m = $("#modeBadge");
    m.textContent = s.mode === "live" ? "GERÇEK PARA" : s.mode === "testnet" ? "TESTNET" : "SANAL İŞLEM";
    m.className = "badge " + (s.mode === "live" ? "off" : "");
    if (s.mode === "live") m.style.fontWeight = "700";
    window.MODE = s.mode;
    return s;
  } catch (e) { return null; }
}

const V = {};
V.home = async () => {
  const s = await updateBadge();
  if (!s) return `<div class="card">Sunucuya ulaşılamadı.</div>`;
  const stat = (k, v) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  return `
  ${s.mode === "live" ? `<div class="notice" style="border-color:var(--red);background:rgba(255,92,92,.1)"><b>GERÇEK PARA MODU.</b> Bot gerçek hesabınızla alım-satım yapar ve para kaybedebilirsiniz. Acil durdurma düğmesi aşağıdadır.</div>` : ""}
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
        : `<button class="btn green" onclick="startBot()">Botu başlat (${esc(s.mode_label || "sanal")})</button>`}
    <button class="btn red" onclick="emergency()">ACİL DURDUR</button>
  </div>
  <h2>En iyi fırsatlar</h2>
  <div class="card">${s.top_opportunities.length ? s.top_opportunities.map(o =>
    `<div class="row"><b>${esc(o.symbol)}</b><span>${esc(o.label)} <span class="score ${scoreCls(o.score)}">${o.score}</span></span></div>`).join("")
    : `<div class="small">Henüz analiz yok. İlk analiz birkaç dakika sürebilir.</div>`}</div>`;
};

V.live = async () => {
  const d = await api("/api/activity");
  const p = d.progress;
  const status = !d.running ? `<div class="notice">Bot <b>kapalı</b>. Analiz yapılır ama alım yapılmaz. Başlatmak için Ana Sayfa'ya git.</div>` : "";
  const prog = p.active ? `Analiz sürüyor: ${p.done}/${p.total} coin` : d.next_analysis_in == null ? "İlk analiz bekleniyor (bot başladıktan ~1-2 dk sonra)" : `Sonraki analiz ${d.next_analysis_in} sn sonra`;
  const cls = {alım: "pos", satış: "pos", red: "neg", bekle: "", bilgi: ""};
  const icon = {alım: "🟢 ALIM", satış: "🔴 SATIŞ", red: "⛔ ALINMADI", bekle: "⏸ BEKLE", bilgi: "ℹ"};
  const t = x => new Date(x * 1000).toLocaleTimeString("tr-TR");
  return `${status}<div class="card"><div class="row"><span>${prog}</span><span class="small">Takipte ${d.tracked} coin · alım eşiği ${d.min_score} puan</span></div></div>
  <div class="card">${d.items.map(i => `<div class="row"><div><b class="${cls[i.action] || ""}">${icon[i.action] || ""}</b> ${i.symbol !== "-" ? "<b>" + esc(i.symbol) + "</b>" : ""}${i.score != null ? ` <span class="score ${scoreCls(i.score)}">${i.score}</span>` : ""}
    <div class="small">${esc(i.text)}</div></div><span class="small">${t(i.at)}</span></div>`).join("") || "Henüz kayıt yok. Botu başlatınca burada kararlarını göreceksin."}</div>`;
};

let chartSym = null, chartTf = "15m", chartTimer = null;
function drawChart(d) {
  const W = 600, H = 340, PL = 6, PR = 62, PT = 8, PB = 18, VH = 50;
  const cs = d.candles;
  if (!cs.length) return "<div class='card'>Veri yok.</div>";
  let lo = Math.min(...cs.map(c => c.l)), hi = Math.max(...cs.map(c => c.h));
  const lines = [];
  if (d.position) {
    [["entry", "Alış", "#4da3ff"], ["take_profit", "Hedef", "#2ecc71"], ["stop_loss", "Stop", "#ff5c5c"]].forEach(([k, l, col]) => {
      const v = d.position[k];
      if (v > lo * 0.9 && v < hi * 1.1) { lines.push([v, l, col]); lo = Math.min(lo, v); hi = Math.max(hi, v); }
    });
  }
  const pad = (hi - lo) * 0.05 || hi * 0.001; lo -= pad; hi += pad;
  const ph = H - PT - PB - VH, n = cs.length, cw = (W - PL - PR) / n;
  const X = i => PL + (i + 0.5) * cw, Y = v => PT + (hi - v) / (hi - lo) * ph;
  const vmax = Math.max(...cs.map(c => c.v)) || 1;
  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = lo + (hi - lo) * k / 4, y = Y(v);
    g += `<line x1="${PL}" x2="${W - PR}" y1="${y}" y2="${y}" stroke="#2a333d" stroke-width="0.5"/><text x="${W - PR + 4}" y="${y + 3}" fill="#8b98a5" font-size="10">${px(v)}</text>`;
  }
  cs.forEach((c, i) => {
    const up = c.c >= c.o, col = up ? "#2ecc71" : "#ff5c5c", x = X(i);
    g += `<line x1="${x}" x2="${x}" y1="${Y(c.h)}" y2="${Y(c.l)}" stroke="${col}" stroke-width="1"/>`;
    const y1 = Y(Math.max(c.o, c.c)), y2 = Y(Math.min(c.o, c.c));
    g += `<rect x="${x - cw * 0.35}" y="${y1}" width="${cw * 0.7}" height="${Math.max(1, y2 - y1)}" fill="${col}"/>`;
    const vh = c.v / vmax * VH;
    g += `<rect x="${x - cw * 0.35}" y="${H - PB - vh}" width="${cw * 0.7}" height="${vh}" fill="${col}" opacity="0.35"/>`;
  });
  [[d.ema21, "#f5b342"], [d.ema50, "#b07cff"]].forEach(([arr, col]) => {
    const pts = arr.map((v, i) => v == null ? null : `${X(i)},${Y(v)}`).filter(Boolean).join(" ");
    if (pts) g += `<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.3"/>`;
  });
  lines.forEach(([v, l, col]) => {
    const y = Y(v);
    g += `<line x1="${PL}" x2="${W - PR}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="1" stroke-dasharray="5 3"/><text x="${PL + 3}" y="${y - 3}" fill="${col}" font-size="10">${l} ${px(v)}</text>`;
  });
  const step = cs.length > 1 ? cs[1].t - cs[0].t : 1;
  d.markers.forEach(m => {
    const i = Math.min(n - 1, Math.max(0, Math.floor((m.time - cs[0].t) / step)));
    const x = X(i), y = Y(m.price), buy = m.side === "BUY";
    const tri = buy ? `${x},${y - 3} ${x - 7},${y + 11} ${x + 7},${y + 11}` : `${x},${y + 3} ${x - 7},${y - 11} ${x + 7},${y - 11}`;
    g += `<polygon points="${tri}" fill="${buy ? "#4da3ff" : "#ffffff"}" stroke="#000" stroke-width="0.8"><title>${buy ? "ALIŞ" : "SATIŞ"} ${px(m.price)} ${esc(m.note)}</title></polygon>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#12181e;border-radius:10px">${g}</svg>
  <div class="small" style="margin-top:6px"><span style="color:#f5b342">━ EMA21</span> · <span style="color:#b07cff">━ EMA50</span> · <span style="color:#4da3ff">▲ bot alış</span> · <span>▼ bot satış (beyaz)</span> · kesikli çizgiler: açık pozisyonun alış/hedef/stop seviyesi</div>`;
}

V.chart = async () => {
  const [sc, po] = await Promise.all([api("/api/scanner"), api("/api/positions?state=open")]);
  const syms = [...new Set([...po.map(p => p.symbol), ...sc.coins.map(c => c.symbol)])];
  if (!syms.length) return `<div class="card">Coin listesi henüz hazır değil. Birkaç dakika sonra tekrar bak.</div>`;
  if (!chartSym || !syms.includes(chartSym)) chartSym = syms[0];
  setTimeout(chartTick, 0);
  return `<div class="card"><select id="csym" onchange="chartSym=this.value.split(' ')[0];load()" style="width:100%;padding:10px;border-radius:8px;background:var(--bg);color:var(--text);border:1px solid var(--line);font-size:15px">
    ${syms.map(s => `<option ${s === chartSym ? "selected" : ""}>${s}${po.some(p => p.symbol === s) ? "  ● açık pozisyon" : ""}</option>`).join("")}</select>
    <div style="display:flex;gap:6px;margin-top:8px">${["5m", "15m", "1h", "4h"].map(t => `<button class="btn ${t === chartTf ? "" : "grey"}" style="margin:0;padding:8px" onclick="chartTf='${t}';load()">${t}</button>`).join("")}</div></div>
  <div id="chartlive" class="small" style="margin:4px 2px">Canlı veri bağlanıyor…</div>
  <div id="chartbox"></div><div id="chartinfo"></div>`;
};

let chartBusy = false;
async function chartTick() {
  if (tab !== "chart" || chartBusy || !$("#chartbox")) return;
  chartBusy = true;
  try {
    const d = await api(`/api/chart/${chartSym}?interval=${chartTf}`);
    if (tab !== "chart" || !$("#chartbox")) return;
    $("#chartbox").innerHTML = drawChart(d);
    const last = d.candles[d.candles.length - 1], first = d.candles[0];
    const chg = (last.c / last.o - 1) * 100;
    $("#chartlive").innerHTML = `<span class="pos">● CANLI</span> · ${esc(d.symbol)} <b>${px(last.c)}</b> (bu mum ${pnl(chg)}%) · ${new Date().toLocaleTimeString("tr-TR")} · 3 sn'de bir güncellenir`;
    const a = d.analysis;
    $("#chartinfo").innerHTML = a ? `<div class="card" style="margin-top:10px"><div class="row"><b>Botun puanı</b><span class="score ${scoreCls(a.score)}">${a.score} · ${esc(a.label)}</span></div>
      ${a.reasons.length ? `<ul>${a.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}${a.warnings.length ? `<ul class="neg">${a.warnings.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}</div>` : "";
  } catch (e) {
    if ($("#chartlive")) $("#chartlive").innerHTML = `<span class="neg">● Bağlantı sorunu: ${esc(e.message)}</span> (yeniden deneniyor)`;
  } finally {
    chartBusy = false;
    if (tab === "chart") { clearTimeout(chartTimer); chartTimer = setTimeout(chartTick, 3000); }
  }
}

V.radar = async () => {
  const d = await api("/api/radar");
  const tagc = t => `<span class="badge" style="margin:2px 2px 0 0">${esc(t)}</span>`;
  return `<div class="notice"><b>${esc(d.note)}</b><br>Bot Radar'daki coinlere kendiliğinden girmez. Yalnızca izleme içindir. Trend verisi: ${esc(d.trending_source)}.</div>
  <div class="small">Güncelleme: ${ago(d.updated_at)}</div>
  ${d.items.map(r => `<div class="card"><div class="row"><b>${esc(r.symbol)}</b><span><span class="small">İvme puanı</span> <span class="score ${scoreCls(r.score)}">${r.score}</span></span></div>
    <div class="small">Fiyat ${px(r.price)} · 24s ${pnl(r.change_24h)}% · hacim ${num(r.quote_volume / 1e6, 1)} M$ (${r.vol_ratio}× ortalama)${r.age_days != null ? ` · ${r.age_days} günlük` : ""}</div>
    <div>${r.tags.map(tagc).join("")}</div>
    ${r.warnings.length ? `<ul class="neg">${r.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    <button class="btn grey" style="margin-top:6px;padding:8px" onclick="chartSym='${r.symbol}';tab='chart';renderNav();load()">Grafiği aç</button></div>`).join("") || `<div class="card">Radar henüz hazır değil. Bot açıldıktan 1-2 dakika sonra tekrar bak.</div>`}`;
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
  const [c, k] = await Promise.all([api("/api/connections"), api("/api/keys")]);
  const row = (a, v) => `<div class="row"><span>${a}</span><b style="text-align:right">${esc(v)}</b></div>`;
  const paper = c.mode === "paper";
  const saved = k.configured
    ? (k.readable ? `<div class="notice" style="border-color:var(--green)">Kayıtlı ${esc(k.environment)} anahtarı: <b>${esc(k.api_key_masked)}</b><br>Secret şifreli saklanıyor ve bir daha gösterilmez.</div>
       <button class="btn grey" onclick="delKey()">Kayıtlı anahtarı sil</button>`
      : `<div class="notice">${esc(k.note)}</div><button class="btn grey" onclick="delKey()">Kayıtlı anahtarı sil</button>`)
    : "";
  const chk = c.exchange_check;
  const checks = chk ? `<div class="card">${chk.checks.map(x => `<div class="row"><span>${x.ok ? "✅" : "❌"} ${esc(x.text)}</span></div>`).join("")}
      ${(chk.warnings || []).map(w => `<div class="notice">${esc(w)}</div>`).join("")}</div>` : "";
  const lim = c.live_limits ? `${row("Bot bütçesi (azami)", c.live_limits.budget_usdt + " USDT")}${row("Tek alım üst sınırı", c.live_limits.max_order_usdt + " USDT")}` : "";
  return `<div class="card">${row("Borsa", c.exchange)}${row("Mod", c.mode_label)}${row("Piyasa verisi", c.market_data)}
    ${row("Canlı fiyat akışı", c.websocket_connected ? "Bağlı" : "Bağlı değil")}${row("Gerçek işlem", c.live_trading)}${lim}</div>
  ${paper ? `<div class="notice">Sanal modda API anahtarı <b>gerekmez</b>. Testnet veya gerçek mod için sunucudaki .env dosyasında TRADING_MODE değiştirilir.</div>` : `
  <h2>Binance API anahtarı (${esc(c.mode_label)})</h2>
  <div class="card">
    <div class="notice">Anahtarı Binance'te <b>sadece "Spot alım-satım"</b> iznine sahip olacak şekilde oluşturun. <b>Para çekme izni KAPALI</b> olmalı; açıksa bot gerçek modda çalışmayı reddeder. Anahtarı ayrıca bu bilgisayarın IP adresine kısıtlamanız önerilir.</div>
    ${saved}
    <label>API Key</label><input type="password" id="ak" autocomplete="off" style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--text)">
    <label>Secret Key</label><input type="password" id="as" autocomplete="off" style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--text)">
    <button class="btn" onclick="saveKey()">Şifreli kaydet</button>
    <button class="btn grey" onclick="verifyEx()">Güvenlik kontrolünü çalıştır</button>
  </div>
  <h2>Son güvenlik kontrolü</h2>${checks || '<div class="card small">Henüz çalıştırılmadı.</div>'}`}`;
};

V.logs = async () => {
  const d = await api("/api/logs");
  return `<div class="card">${d.map(l => `<div class="log ${l.level}">${date(l.at)} [${l.level}] ${esc(l.message)}</div>`).join("") || "Kayıt yok."}</div>`;
};

async function load() {
  clearTimeout(timer); clearTimeout(chartTimer);
  try { $("#view").innerHTML = await V[tab](); if (tab !== "home") updateBadge(); }
  catch (e) { $("#view").innerHTML = `<div class="card neg">${esc(e.message)}</div>`; }
  if (!["settings", "risk", "api", "chart"].includes(tab)) timer = setTimeout(load, tab === "live" ? 5000 : 10000);
}

async function act(path, body) {
  try { await api(path, {method: "POST", body: JSON.stringify(body)}); } catch (e) { alert(e.message); }
  load();
}
function startBot() {
  const body = {running: true};
  if (window.MODE === "live") {
    const t = prompt("GERÇEK PARA ile işlem başlayacak. Para kaybedebilirsiniz.\nDevam etmek için ONAYLIYORUM yazın:");
    if (t == null) return;
    body.confirm = t;
  }
  act("/api/bot/run", body);
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

async function saveKey() {
  const body = {environment: window.MODE || "testnet", api_key: $("#ak").value, api_secret: $("#as").value};
  try { await api("/api/keys", {method: "PUT", body: JSON.stringify(body)}); $("#ak").value = $("#as").value = ""; alert("Kaydedildi (şifreli)."); }
  catch (e) { alert("Kaydedilemedi: " + e.message); return; }
  load();
}
async function verifyEx() {
  try { await api("/api/exchange/verify", {method: "POST"}); } catch (e) { alert(e.message); }
  load();
}
async function delKey() {
  if (!confirm("Kayıtlı anahtar silinsin mi?")) return;
  try { await api("/api/keys", {method: "DELETE"}); } catch (e) { alert(e.message); }
  load();
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
renderNav(); load();
