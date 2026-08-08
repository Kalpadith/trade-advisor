/* Trade Advisor dashboard */
"use strict";

const $ = (id) => document.getElementById(id);
const fmt = (x, d = 6) => x == null ? "-" : Number(x).toLocaleString("en-US", { maximumSignificantDigits: d });
const fmtMoney = (x) => x == null ? "-" : Number(x).toLocaleString("en-US", { maximumFractionDigits: 2 });
const fmtTime = (ms) => new Date(ms).toISOString().slice(0, 16).replace("T", " ");

let mode = "analyze";
let chart = null, candleSeries = null, volumeSeries = null;
let overlaySeries = {}, priceLines = [];
let btChart = null, btSeries = null;

const CHART_OPTS = {
  layout: { background: { color: "#161b24" }, textColor: "#d7dde7" },
  grid: { vertLines: { color: "#20263166" }, horzLines: { color: "#20263166" } },
  timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#232a36" },
  rightPriceScale: { borderColor: "#232a36" },
  crosshair: { mode: 0 },
};

const OVERLAY_STYLE = {
  ema20: { color: "#e7b54a", lineWidth: 1, title: "EMA20" },
  ema50: { color: "#4a8fe7", lineWidth: 1, title: "EMA50" },
  ema200: { color: "#b04ae7", lineWidth: 2, title: "EMA200" },
  bb_upper: { color: "#7c869855", lineWidth: 1, title: "BB" },
  bb_lower: { color: "#7c869855", lineWidth: 1, title: "" },
};

function initChart() {
  chart = LightweightCharts.createChart($("chart"), CHART_OPTS);
  candleSeries = chart.addCandlestickSeries({
    upColor: "#26a69a", downColor: "#ef5350",
    wickUpColor: "#26a69a", wickDownColor: "#ef5350", borderVisible: false,
  });
  volumeSeries = chart.addHistogramSeries({
    priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false,
  });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  for (const [key, style] of Object.entries(OVERLAY_STYLE)) {
    overlaySeries[key] = chart.addLineSeries({
      ...style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
  }
  new ResizeObserver(() => chart.applyOptions({
    width: $("chart").clientWidth - 8, height: $("chart").clientHeight - 8,
  })).observe($("chart"));
}

function clearPriceLines() {
  for (const pl of priceLines) candleSeries.removePriceLine(pl);
  priceLines = [];
}

function addPriceLine(price, color, title, style) {
  priceLines.push(candleSeries.createPriceLine({
    price, color, title,
    lineWidth: 1, lineStyle: style ?? LightweightCharts.LineStyle.Dashed,
    axisLabelVisible: true,
  }));
}

async function api(path, opts) {
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    let msg = resp.statusText;
    try { msg = (await resp.json()).detail || msg; } catch (e) { /* keep statusText */ }
    throw new Error(msg);
  }
  return resp.json();
}

async function loadSymbols() {
  try {
    const symbols = await api("/api/symbols");
    $("symbol-list").innerHTML = symbols.slice(0, 3000).map((s) => `<option value="${s}">`).join("");
  } catch (e) { /* datalist is a convenience; typing still works */ }
}

function setStatus(text, isError) {
  $("status").textContent = text;
  $("status").className = isError ? "error" : "";
}

function renderChart(data) {
  candleSeries.setData(data.candles);
  volumeSeries.setData(data.volume);
  for (const [key, series] of Object.entries(overlaySeries)) {
    series.setData(data.overlays[key] || []);
  }
  candleSeries.setMarkers((data.markers || []).slice(-60));
  chart.timeScale().fitContent();
}

function drawPlan(rec) {
  clearPriceLines();
  if (!rec.entry_zone) return;
  const solid = LightweightCharts.LineStyle.Solid;
  addPriceLine(rec.entry_zone[0], "#4a8fe7", "entry low");
  addPriceLine(rec.entry_zone[1], "#4a8fe7", "entry high");
  if (rec.stop_loss != null) addPriceLine(rec.stop_loss, "#ef5350", "SL", solid);
  (rec.take_profits || []).forEach((t, i) => addPriceLine(t.price, "#26a69a", "TP" + (i + 1)));
}

function renderCard(rec) {
  const badgeText = { long: "LONG", short: "SHORT", no_trade: "NO TRADE" }[rec.direction];
  let html = `
    <div class="badge ${rec.direction}">${badgeText}</div>
    <div class="muted" style="margin-top:6px">
      ${rec.symbol} &middot; ${rec.entry_timeframe} &middot; data as of ${rec.data_as_of.replace("T", " ").slice(0, 16)} UTC
    </div>
    <div style="margin-top:8px">Confidence ${rec.confidence}/100 (score ${rec.score_total >= 0 ? "+" : ""}${rec.score_total.toFixed(1)})</div>
    <div class="conf-track"><div class="conf-fill" style="width:${rec.confidence}%"></div></div>
    <div class="muted" style="font-size:12px">Suggested holding period: ${rec.holding_period}</div>`;

  if (rec.entry_zone) {
    html += `<table class="plan">
      <tr><td>Entry zone</td><td>${fmt(rec.entry_zone[0])} .. ${fmt(rec.entry_zone[1])}</td></tr>
      <tr><td>Stop loss</td><td>${fmt(rec.stop_loss)}</td></tr>`;
    (rec.take_profits || []).forEach((t, i) => {
      html += `<tr><td>TP${i + 1} (${t.r_multiple.toFixed(1)}R, ${t.close_pct}%)</td><td>${fmt(t.price)}</td></tr>`;
    });
    if (rec.position) {
      html += `<tr><td>Size</td><td>${fmt(rec.position.quantity, 4)} (&asymp;${fmtMoney(rec.position.notional)})</td></tr>
        <tr><td>Risk</td><td>${fmtMoney(rec.position.risk_amount)} (${rec.position.risk_pct}%)</td></tr>`;
    }
    html += `</table>`;
  }

  for (const w of rec.warnings.slice(0, -1)) html += `<div class="warn">${w}</div>`;

  html += `<h3 style="margin:12px 0 4px;font-size:13px">Reasoning</h3>`;
  const maxC = Math.max(...rec.rules.map((r) => Math.abs(r.contribution)), 1);
  for (const r of rec.rules) {
    const cls = r.contribution > 0 ? "pos" : r.contribution < 0 ? "neg" : "zero";
    const barColor = r.contribution > 0 ? "#26a69a" : r.contribution < 0 ? "#ef5350" : "#7c8698";
    const width = Math.round(Math.abs(r.contribution) / maxC * 100);
    html += `<div class="rule">
      <span class="tf">${r.timeframe}</span>
      <span><span class="name">${r.name}</span><br><span class="detail muted">${r.detail}</span>
        <div class="rule-bar" style="width:${width}%;background:${barColor}"></div></span>
      <span class="contrib ${cls}">${r.contribution >= 0 ? "+" : ""}${r.contribution.toFixed(1)}</span>
    </div>`;
  }
  html += `<div class="muted" style="margin-top:10px;font-size:11px">${rec.warnings[rec.warnings.length - 1]}</div>`;
  $("card").innerHTML = html;
}

async function runAnalyze() {
  const symbol = $("symbol").value.trim().toUpperCase();
  const tf = $("timeframe").value;
  if (!symbol) return;
  setStatus("Analyzing " + symbol + "...");
  $("run").disabled = true;
  try {
    const [klines, rec] = await Promise.all([
      api(`/api/klines?symbol=${symbol}&interval=${tf}&limit=300`),
      api("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol, entry_timeframe: tf,
          account_size: Number($("account").value) || 10000,
          risk_pct: Number($("risk").value) || 1,
        }),
      }),
    ]);
    renderChart(klines);
    renderCard(rec);
    drawPlan(rec);
    setStatus("");
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    $("run").disabled = false;
  }
}

/* ------------------------------ backtest ------------------------------ */

function initBtChart() {
  btChart = LightweightCharts.createChart($("bt-chart"), CHART_OPTS);
  btSeries = btChart.addAreaSeries({
    lineColor: "#4a8fe7", topColor: "#4a8fe755", bottomColor: "#4a8fe700", lineWidth: 2,
  });
  new ResizeObserver(() => btChart.applyOptions({
    width: $("bt-chart").clientWidth - 8, height: $("bt-chart").clientHeight - 8,
  })).observe($("bt-chart"));
}

function stat(k, v, cls) {
  return `<div class="stat"><div class="v ${cls || ""}">${v}</div><div class="k">${k}</div></div>`;
}

function renderBacktest(rep) {
  const pf = rep.profit_factor;
  const exp = rep.expectancy_r;
  const ret = (rep.final_equity / rep.initial_equity - 1) * 100;
  $("bt-stats").innerHTML =
    stat("Trades", rep.trade_count) +
    stat("Win rate", rep.win_rate == null ? "-" : rep.win_rate.toFixed(1) + "%") +
    stat("Profit factor", pf == null ? "-" : pf.toFixed(2), pf > 1 ? "pos" : pf != null ? "neg" : "") +
    stat("Expectancy", exp == null ? "-" : exp.toFixed(2) + "R", exp > 0 ? "pos" : exp != null ? "neg" : "") +
    stat("Max drawdown", rep.max_drawdown_pct.toFixed(1) + "%", rep.max_drawdown_pct > 20 ? "neg" : "") +
    stat("Return", ret.toFixed(1) + "%", ret >= 0 ? "pos" : "neg") +
    stat("Exposure", rep.exposure_pct.toFixed(0) + "%");

  btSeries.setData(rep.equity_curve.map((p) => ({ time: Math.floor(p.time / 1000), value: p.equity })));
  btChart.timeScale().fitContent();

  const tbody = $("bt-trades").querySelector("tbody");
  tbody.innerHTML = rep.trades.slice(-100).reverse().map((t) => {
    const cls = t.pnl >= 0 ? "pos" : "neg";
    return `<tr>
      <td>${t.direction}</td>
      <td>${fmtTime(t.entry_time)}</td>
      <td>${fmt(t.entry_price)}</td>
      <td>${fmt(t.avg_exit_price)}</td>
      <td class="${cls}">${fmtMoney(t.pnl)}</td>
      <td class="${cls}">${t.pnl_r.toFixed(2)}</td>
      <td>${t.exit_reason}</td>
    </tr>`;
  }).join("");
}

async function runBacktest() {
  const symbol = $("symbol").value.trim().toUpperCase();
  if (!symbol) return;
  setStatus("Backtesting " + symbol + " (this can take a while)...");
  $("run").disabled = true;
  try {
    const body = {
      symbol,
      entry_timeframe: $("timeframe").value,
      start: $("bt-start").value || "2025-01-01",
      account_size: Number($("account").value) || 10000,
      risk_pct: Number($("risk").value) || 1,
    };
    if ($("bt-end").value) body.end = $("bt-end").value;
    const rep = await api("/api/backtest", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    renderBacktest(rep);
    setStatus(rep.warnings.join(" | "));
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    $("run").disabled = false;
  }
}

/* -------------------------------- tabs -------------------------------- */

function setMode(next) {
  mode = next;
  $("tab-analyze").classList.toggle("active", mode === "analyze");
  $("tab-backtest").classList.toggle("active", mode === "backtest");
  $("view-analyze").classList.toggle("hidden", mode !== "analyze");
  $("view-backtest").classList.toggle("hidden", mode !== "backtest");
  $("backtest-controls").classList.toggle("hidden", mode !== "backtest");
  $("run").textContent = mode === "analyze" ? "Analyze" : "Run backtest";
}

$("tab-analyze").addEventListener("click", () => setMode("analyze"));
$("tab-backtest").addEventListener("click", () => setMode("backtest"));
$("run").addEventListener("click", () => (mode === "analyze" ? runAnalyze() : runBacktest()));
$("symbol").addEventListener("keydown", (e) => { if (e.key === "Enter") $("run").click(); });

initChart();
initBtChart();
loadSymbols();
