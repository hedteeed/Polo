const $ = (id) => document.getElementById(id);

function fmt(n, dec = 2) {
  if (n == null || isNaN(n)) return "—";
  return Number(n).toLocaleString("en-US", {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  });
}

function fmtUsd(n) {
  if (n == null || isNaN(n)) return "—";
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${fmt(Math.abs(n))}`;
}

function pnlClass(n) {
  if (n > 0) return "positive";
  if (n < 0) return "negative";
  return "";
}

function shortAddr(a) {
  if (!a) return "—";
  return `${a.slice(0, 6)}…${a.slice(-4)}`;
}

function formatResolution(hours) {
  if (hours == null) return "—";
  if (hours < 0) return "Past due";
  if (hours < 2) return `<span class="resolution-urgent">${hours.toFixed(1)}h</span>`;
  if (hours < 24) return `<span class="resolution-soon">${hours.toFixed(1)}h</span>`;
  const days = hours / 24;
  if (days < 7) return `${days.toFixed(1)}d`;
  return `${(days / 7).toFixed(1)}w`;
}

function formatTs(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3000);
}

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function renderPortfolio(data) {
  const t = data.totals;
  $("m-equity").textContent = `$${fmt(t.equity)}`;
  $("m-cash").textContent = `$${fmt(t.cash)}`;
  $("m-pnl").textContent = fmtUsd(t.total_pnl);
  $("m-pnl").className = `metric-value ${pnlClass(t.total_pnl)}`;
  $("m-return").textContent = `${t.return_pct >= 0 ? "+" : ""}${fmt(t.return_pct, 2)}%`;
  $("m-return").className = `metric-sub ${pnlClass(t.return_pct)}`;
  $("m-unrealized").textContent = fmtUsd(t.unrealized_pnl);
  $("m-unrealized").className = `metric-value ${pnlClass(t.unrealized_pnl)}`;
  $("m-realized").textContent = fmtUsd(t.realized_pnl);
  $("m-realized").className = `metric-value ${pnlClass(t.realized_pnl)}`;
  $("m-deployed").textContent = `$${fmt(t.deployed)}`;
  $("m-positions").textContent = `${t.open_count} / ${data.config.max_positions} positions`;

  $("updated-at").textContent = `Updated ${formatTs(data.updated_at)}`;

  const pauseBanner = $("pause-banner");
  if (data.paused) {
    pauseBanner.classList.remove("hidden");
    $("pause-reason").textContent = data.pause_reason || "";
    $("status-pill").textContent = "PAUSED";
    $("status-pill").className = "pill pill-paused";
  } else {
    pauseBanner.classList.add("hidden");
    $("status-pill").textContent = "LIVE PAPER";
    $("status-pill").className = "pill pill-live";
  }

  $("watchlist-count").textContent = data.watchlist.length;
  const wl = $("watchlist");
  if (!data.watchlist.length) {
    wl.innerHTML = '<p class="muted">No copy targets — click Refresh Copy Targets</p>';
  } else {
    wl.innerHTML = data.watchlist.map((w) => `
      <div class="wallet-card">
        <div>
          <div class="wallet-name">${w.username || "Anonymous"}</div>
          <div class="wallet-addr">${shortAddr(w.address)}</div>
        </div>
        <div class="wallet-stats">
          <div class="roi">ROI ${fmt(w.roi_pct, 1)}%</div>
          <div>Score ${fmt(w.copy_score, 0)} · ${w.strategy || "—"}</div>
        </div>
      </div>
    `).join("");
  }

  $("open-count").textContent = data.open_positions.length;
  const pb = $("positions-body");
  if (!data.open_positions.length) {
    pb.innerHTML = '<tr><td colspan="9" class="empty">No open positions — run Scan & Trade</td></tr>';
  } else {
    pb.innerHTML = data.open_positions.map((p) => `
      <tr>
        <td>
          <div class="market-title">${p.title}</div>
          <div class="market-slug">${p.market_slug}</div>
        </td>
        <td>${p.copy_username || "—"}<br/><span class="market-slug">${shortAddr(p.copy_wallet)}</span></td>
        <td>${fmt(p.entry_price, 3)}</td>
        <td>${fmt(p.current_price, 3)}</td>
        <td>${fmt(p.shares, 1)}</td>
        <td>$${fmt(p.cost_basis)}</td>
        <td class="${pnlClass(p.unrealized_pnl)}">${fmtUsd(p.unrealized_pnl)}</td>
        <td>${formatResolution(p.hours_to_resolution)}</td>
        <td><span class="tag ${p.signal_source === "conviction_yield" ? "conviction" : ""}">${p.signal_source}</span></td>
      </tr>
    `).join("");
  }

  $("closed-count").textContent = data.closed_trades.length;
  const cb = $("closed-body");
  if (!data.closed_trades.length) {
    cb.innerHTML = '<tr><td colspan="6" class="empty">No closed trades yet</td></tr>';
  } else {
    cb.innerHTML = data.closed_trades.map((t) => `
      <tr>
        <td><div class="market-title">${t.title}</div></td>
        <td>${t.copy_username || "—"}</td>
        <td>${fmt(t.entry_price, 3)} → ${fmt(t.exit_price, 3)}</td>
        <td class="${pnlClass(t.realized_pnl)}">${fmtUsd(t.realized_pnl)}</td>
        <td>${t.close_reason || "—"}</td>
        <td>${formatTs(t.closed_at)}</td>
      </tr>
    `).join("");
  }

  const al = $("activity-log");
  al.innerHTML = (data.activity_log || []).map((e) => `
    <div class="log-entry ${e.level}">
      <span class="muted">${formatTs(e.ts)}</span>
      <span class="msg">${e.message}</span>
    </div>
  `).join("") || '<div class="muted">No activity yet</div>';

  drawEquityChart(data.equity_history || []);
}

function drawEquityChart(history) {
  const canvas = $("equity-chart");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  if (history.length < 2) {
    ctx.fillStyle = "#8b95a8";
    ctx.font = "13px DM Sans";
    ctx.fillText("Equity history builds as prices update…", 16, h / 2);
    return;
  }

  const values = history.map((h) => h.equity);
  const min = Math.min(...values) * 0.998;
  const max = Math.max(...values) * 1.002;
  const pad = 12;

  const x = (i) => pad + (i / (values.length - 1)) * (w - pad * 2);
  const y = (v) => pad + (1 - (v - min) / (max - min || 1)) * (h - pad * 2);

  const start = values[0];
  ctx.strokeStyle = "rgba(139,149,168,0.3)";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(pad, y(start));
  ctx.lineTo(w - pad, y(start));
  ctx.stroke();
  ctx.setLineDash([]);

  const last = values[values.length - 1];
  ctx.strokeStyle = last >= start ? "#22c55e" : "#ef4444";
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((v, i) => {
    if (i === 0) ctx.moveTo(x(i), y(v));
    else ctx.lineTo(x(i), y(v));
  });
  ctx.stroke();

  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, last >= start ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)");
  grad.addColorStop(1, "transparent");
  ctx.fillStyle = grad;
  ctx.beginPath();
  values.forEach((v, i) => {
    if (i === 0) ctx.moveTo(x(i), y(v));
    else ctx.lineTo(x(i), y(v));
  });
  ctx.lineTo(x(values.length - 1), h);
  ctx.lineTo(x(0), h);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = "#e8ecf4";
  ctx.font = "11px JetBrains Mono";
  ctx.fillText(`$${fmt(last)}`, pad, 22);
  ctx.fillStyle = "#8b95a8";
  ctx.fillText(`$${fmt(start)} start`, w - 90, h - 8);
}

let refreshTimer = null;

async function loadPortfolio() {
  try {
    const data = await api("/api/portfolio");
    renderPortfolio(data);
  } catch (e) {
    toast("Failed to load: " + e.message);
  }
}

async function runAction(path, msg, method = "POST", body = null) {
  const btn = event?.target;
  if (btn) btn.disabled = true;
  try {
    const data = await api(path, method, body);
    renderPortfolio(data.portfolio || data);
    toast(msg);
  } catch (e) {
    toast("Error: " + e.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

$("btn-scan").onclick = () => runAction("/api/scan", "Scan complete");
$("btn-prices").onclick = () => runAction("/api/prices", "Prices updated");
$("btn-watchlist").onclick = () => runAction("/api/watchlist/refresh?fast=false", "Watchlist refreshed");
$("btn-reset").onclick = () => {
  if (confirm("Reset paper account to $1,000? All history will be cleared.")) {
    runAction("/api/reset", "Account reset", "POST", { balance: 1000 });
  }
};
$("btn-resume").onclick = () => runAction("/api/resume", "Trading resumed");

$("auto-refresh").onchange = (e) => {
  if (e.target.checked) {
    refreshTimer = setInterval(loadPortfolio, 15000);
  } else {
    clearInterval(refreshTimer);
  }
};

loadPortfolio();
refreshTimer = setInterval(loadPortfolio, 15000);
