"use strict";

const ROUTE_NAMES = { ground: "國1平面", elevated: "五楊高架" };
const REASON_ZH = {
  ok: "符合推播條件",
  missing_data: "資料不足，無法預測",
  below_saving: "兩路線預測行車時間差距不足 5 分鐘，不推播",
  missing_volume: "入口流量缺漏，無法估算分流配額",
  no_benefit: "分流後替代道路無實質效益，不推播",
  cooldown: "冷卻期內（30 分鐘），不重複推播",
};
const LIVE = "__live__";

let data = null;          // 目前載入的 replay / live JSON
let mode = "actual";      // actual | pred
let map, polylines = {}, fitted = false;
let chart;
let liveTimer = null;

const $ = (id) => document.getElementById(id);

function speedColor(v) {
  if (v === null || v === undefined) return "#9aa0a6";
  if (v >= 80) return "#2e9e4f";
  if (v >= 60) return "#e6c229";
  if (v >= 40) return "#ef8a1e";
  return "#d6372f";
}

const min = (s) => (s === null || s === undefined ? "–" : (s / 60).toFixed(1));

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

function initMap(corridor) {
  if (!map) {
    map = L.map("map").setView([24.95, 121.12], 10);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
  }
  Object.values(polylines).forEach((p) => p.remove());
  polylines = {};
  const all = [];
  for (const s of corridor.segments) {
    if (!s.coords.length) continue;
    // 平面與高架在地圖上近乎重疊：高架畫粗線在底、平面細線在上以便區分
    const pl = L.polyline(s.coords, {
      color: "#9aa0a6", weight: s.route === "elevated" ? 9 : 4, opacity: s.route === "elevated" ? 0.55 : 0.95,
    }).bindTooltip("", { sticky: true });
    pl.addTo(map);
    polylines[s.id] = pl;
    all.push(...s.coords);
  }
  if (all.length && !fitted) {  // 只在第一次載入時縮放，之後保留使用者的視角
    map.invalidateSize();
    map.fitBounds(L.latLngBounds(all), { padding: [20, 20], animate: false });
    fitted = true;
  }
}

function initChart() {
  if (chart) chart.destroy();
  const marker = {
    id: "marker",
    afterDatasetsDraw(c) {
      const i = Number($("slider").value);
      const x = c.scales.x.getPixelForValue(i);
      const { top, bottom } = c.chartArea;
      const ctx = c.ctx;
      ctx.save();
      ctx.strokeStyle = "#555";
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.restore();
    },
  };
  const frames = data.frames;
  const series = (kind, route) => frames.map((f) => (f.route_tt[kind][route] ?? null) === null ? null : f.route_tt[kind][route] / 60);
  chart = new Chart($("chart"), {
    type: "line",
    data: {
      labels: frames.map((f) => f.ts.slice(11)),
      datasets: [
        { label: "國1平面 實際", data: series("actual", "ground"), borderColor: "#d6372f", pointRadius: 0, tension: 0.2 },
        { label: "五楊高架 實際", data: series("actual", "elevated"), borderColor: "#0b6bcb", pointRadius: 0, tension: 0.2 },
        { label: "國1平面 預測+30", data: series("pred30", "ground"), borderColor: "#d6372f", borderDash: [5, 4], pointRadius: 0, tension: 0.2 },
        { label: "五楊高架 預測+30", data: series("pred30", "elevated"), borderColor: "#0b6bcb", borderDash: [5, 4], pointRadius: 0, tension: 0.2 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      scales: { y: { title: { display: true, text: "分鐘" } }, x: { ticks: { maxTicksLimit: 9 } } },
      plugins: { legend: { labels: { boxWidth: 18, font: { size: 11 } } } },
    },
    plugins: [marker],
  });
}

function renderPush(f) {
  const d = f.decision;
  const box = $("push");
  box.replaceChildren();
  if (d.push) {
    const badge = document.createElement("span");
    badge.className = "badge ok";
    badge.textContent = "推播";
    const lab = document.createElement("div");
    lab.className = "bubble-label";
    lab.textContent = "入選改道用戶收到的訊息";
    const b = document.createElement("div");
    b.className = "bubble";
    b.textContent = d.message;
    box.append(badge, lab, b);
    if (d.stay_message) {
      const lab2 = document.createElement("div");
      lab2.className = "bubble-label";
      lab2.textContent = "未入選用戶收到的訊息";
      const b2 = document.createElement("div");
      b2.className = "bubble stay";
      b2.textContent = d.stay_message;
      box.append(lab2, b2);
    }
    const t = document.createElement("table");
    t.style.marginTop = "12px";
    t.innerHTML = `<tr><th>情境</th><th>替代路線預測行車時間（分）</th><th>相對原預測增加（分）</th><th>節省（分）</th></tr>`;
    const base = d.tt_fast_s;
    const rows = [
      [`全部訂閱用戶改道（naive，30%）`, d.alt_tt_naive_s, d.alt_tt_naive_s - base, null],
      [`配額分流（p* = ${(d.p_star * 100).toFixed(0)}%）`, d.alt_tt_quota_s, d.alt_tt_quota_s - base, d.saving_quota_s],
    ];
    for (const [name, tt, inc, sav] of rows) {
      const tr = document.createElement("tr");
      [name, min(tt), min(inc), sav === null ? "–" : min(sav)].forEach((v) => {
        const td = document.createElement("td");
        td.textContent = v;
        tr.append(td);
      });
      t.append(tr);
    }
    box.append(t);
    const note = document.createElement("div");
    note.className = "reason";
    note.style.marginTop = "6px";
    note.textContent = `${ROUTE_NAMES[d.slow]} 預測比 ${ROUTE_NAMES[d.fast]} 多 ${min(d.saving_naive_s)} 分鐘（個人最快路線的預估節省）`;
    box.append(note);
  } else {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = "不推播";
    const p = document.createElement("span");
    p.className = "reason";
    p.textContent = REASON_ZH[d.reason] || d.reason;
    box.append(badge, p);
    if (d.saving_naive_s !== null && d.saving_naive_s !== undefined) {
      const q = document.createElement("div");
      q.className = "reason";
      q.style.marginTop = "8px";
      q.textContent = `${ROUTE_NAMES[d.slow]} 預測比 ${ROUTE_NAMES[d.fast]} 多 ${min(d.saving_naive_s)} 分鐘`;
      box.append(q);
    }
  }
}

function render() {
  if (!data || !data.frames.length) return;
  const i = Number($("slider").value);
  const f = data.frames[i];
  $("ts-label").textContent = f.ts.replace("T", " ");
  const speeds = mode === "actual" ? f.actual : f.pred["30"];
  for (const s of data.corridor.segments) {
    const pl = polylines[s.id];
    if (!pl) continue;
    const v = speeds[s.id];
    pl.setStyle({ color: speedColor(v) });
    pl.setTooltipContent(`${ROUTE_NAMES[s.route]} ${s.description}<br>${v === null || v === undefined ? "無資料" : v.toFixed(0) + " km/h"}`);
  }
  renderPush(f);
  chart.update("none");
}

function loadData(json, keepLatest) {
  const prev = Number($("slider").value);
  const wasLast = data && prev === data.frames.length - 1;
  data = json;
  const sl = $("slider");
  sl.max = String(Math.max(0, data.frames.length - 1));
  if (keepLatest || wasLast || prev > data.frames.length - 1) sl.value = sl.max;
  initMap(data.corridor);
  initChart();
  render();
}

async function selectSource(v) {
  clearInterval(liveTimer);
  liveTimer = null;
  if (v === LIVE) {
    try {
      loadData(await getJSON("data/live.json"), true);
    } catch (e) {
      $("push").textContent = "尚無即時資料：請先執行 uv run fcf live";
    }
    liveTimer = setInterval(async () => {
      try { loadData(await getJSON("data/live.json"), false); } catch (_) { /* 保留舊資料 */ }
    }, 60000);
    return;
  }
  const json = await getJSON(`data/replay-${v.replaceAll("-", "")}.json`);
  // 重播預設停在第一個推播 frame，沒有則停在起點
  const first = json.frames.findIndex((f) => f.decision.push);
  loadData(json, false);
  $("slider").value = String(first >= 0 ? first : 0);
  render();
}

function pctDiff(m, b) { return b ? ((m - b) / b) * 100 : null; }

function renderMetrics(m) {
  const box = $("metrics");
  const fmt = (x, d = 2) => (x === null || x === undefined ? "–" : x.toFixed(d));
  const pct = (x) => (x === null || x === undefined ? "–" : (x * 100).toFixed(1) + "%");
  let h = `<p class="reason">訓練期間 ${m.period.train.join(" ～ ")}；測試期間 ${m.period.test.join(" ～ ")}</p>`;
  h += `<h3>車速預測誤差 MAE（km/h，越低越好）</h3><table><tr><th>時距</th><th>子集</th><th>模型</th><th>持續法</th><th>歷史平均</th><th>相對持續法</th></tr>`;
  for (const [hz, subs] of Object.entries(m.speed_error)) {
    for (const [name, r] of Object.entries(subs)) {
      const best = Math.min(r.model.mae, r.persistence.mae, r.profile.mae);
      const c = (v) => `<td class="${v === best ? "better" : ""}">${fmt(v)}</td>`;
      const d = pctDiff(r.model.mae, r.persistence.mae);
      h += `<tr><td>${hz} 分</td><td>${name}</td>${c(r.model.mae)}${c(r.persistence.mae)}${c(r.profile.mae)}<td>${d === null ? "–" : d.toFixed(1) + "%"}</td></tr>`;
    }
  }
  h += `</table><h3>壅塞前預警（當下 ≥40 km/h，預測 t+h 是否 &lt;40）</h3><table><tr><th>時距</th><th>子集</th><th>Precision</th><th>Recall</th><th>F1</th><th>實際壅塞數</th></tr>`;
  for (const [hz, subs] of Object.entries(m.warning)) {
    for (const [name, r] of Object.entries(subs)) {
      h += `<tr><td>${hz} 分</td><td>${name}</td><td>${pct(r.model.precision)}</td><td>${pct(r.model.recall)}</td><td>${pct(r.model.f1)}</td><td>${r.model.n_pos}</td></tr>`;
    }
  }
  const o = m.onset, dv = m.diversion;
  h += `</table><h3>壅塞起點提前量</h3><table><tr><th>起點事件數</th><th>提前偵測數</th><th>偵測率</th><th>提前量中位數（分）</th></tr>
    <tr><td>${o.n}</td><td>${o.detected}</td><td>${pct(o.detection_rate)}</td><td>${fmt(o.median_lead_min, 1)}</td></tr></table>`;
  h += `<h3>分流模擬（TEST 期間上班日 06:00–10:00）</h3><table>
    <tr><td>推播事件數</td><td>${dv.push_events}</td></tr>
    <tr><td>平均預估節省：個人最快路線（naive，分鐘）</td><td>${fmt(dv.mean_saving_naive_min, 1)}</td></tr>
    <tr><td>平均預估節省：配額分流（分鐘）</td><td>${fmt(dv.mean_saving_quota_min, 1)}</td></tr>
    <tr><td>替代路線行車時間增加：全部改道（naive，分鐘）</td><td>${fmt(dv.mean_alt_increase_naive_min, 2)}</td></tr>
    <tr><td>替代路線行車時間增加：配額（分鐘）</td><td>${fmt(dv.mean_alt_increase_quota_min, 2)}</td></tr>
    <tr><td>平均 p*（上限 0.30）</td><td>${fmt(dv.mean_p_star, 3)}</td></tr>
    <tr><td>配額實際生效（p* &lt; 0.30）的推播數</td><td>${dv.quota_binding_pushes}</td></tr>
    <tr><td>系統車輛時間節省：配額分流（車輛小時，${dv.n_workdays} 個上班日估算）</td><td>${fmt(dv.veh_hours_saved_quota, 0)}</td></tr>
    <tr><td>系統車輛時間節省：全部改道 naive（車輛小時，估算）</td><td>${fmt(dv.veh_hours_saved_naive, 0)}</td></tr></table>`;
  box.innerHTML = h;
}

async function main() {
  const sel = $("source");
  let idx = { replays: [] };
  try { idx = await getJSON("data/index.json"); } catch (_) { /* 沒有重播檔 */ }
  for (const d of idx.replays) sel.append(new Option(`重播 ${d}`, d));
  sel.append(new Option("即時", LIVE));
  sel.addEventListener("change", () => selectSource(sel.value));
  $("slider").addEventListener("input", render);
  const setMode = (m) => {
    mode = m;
    $("mode-actual").classList.toggle("active", m === "actual");
    $("mode-pred").classList.toggle("active", m === "pred");
    render();
  };
  $("mode-actual").addEventListener("click", () => setMode("actual"));
  $("mode-pred").addEventListener("click", () => setMode("pred"));

  getJSON("data/metrics.json").then(renderMetrics).catch(() => { $("metrics").textContent = "尚無評估指標：請先執行 uv run fcf evaluate"; });
  if (sel.value) await selectSource(sel.value);
}

main();
