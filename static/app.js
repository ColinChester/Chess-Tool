"use strict";

const $ = (id) => document.getElementById(id);
let radarChart, ratingChart, gaugeChart;

const COLORS = {
  good: "#7cc66e", warn: "#e0a64a", bad: "#e06b6b",
  accent: "#7cc66e", accent2: "#5aa0e0", line: "#2c313c", muted: "#99a0ad",
};

function scoreColor(s) {
  if (s >= 65) return COLORS.good;
  if (s >= 45) return COLORS.warn;
  return COLORS.bad;
}

function show(id) {
  ["empty", "loading", "error", "report"].forEach((s) =>
    $(s).classList.toggle("hidden", s !== id)
  );
}

$("search").addEventListener("submit", (e) => {
  e.preventDefault();
  runReport();
});

let CURRENT_USER = "";

async function runReport() {
  const username = $("username").value.trim().replace(/^@/, "");
  if (!username) return;
  CURRENT_USER = username;
  const params = new URLSearchParams({
    username,
    limit: $("limit").value,
  });
  if ($("timeclass").value) params.set("time_class", $("timeclass").value);
  if ($("engine").checked) params.set("engine", "true");

  show("loading");
  $("loadtext").textContent = $("engine").checked
    ? "Fetching games and running Stockfish (this can take a while)…"
    : "Fetching and analyzing games…";

  try {
    const res = await fetch("/api/report?" + params.toString());
    const data = await res.json();
    if (!res.ok) {
      const det = data && data.detail;
      throw new Error(typeof det === "string" ? det
        : Array.isArray(det) ? det.map((e) => e.msg || JSON.stringify(e)).join("; ")
        : "Request failed (" + res.status + ")");
    }
    render(data);
    show("report");
  } catch (err) {
    $("error").textContent = "⚠ " + err.message;
    show("error");
  }
}

let DETAILS = null;
let detailChart = null;

function render(d) {
  DETAILS = d.details || {};
  renderPlayer(d.player, d.overall_skill);
  renderRecord(d.overall);
  renderSkills(d.skills);
  renderRadar(d.skills);
  renderRating(d.overall.rating_series);
  renderOpenings(d.skills.find((s) => s.key === "openings"));
  renderTips(d.tips);
  renderGames(d.games || []);
  startStatusPolling();
  const m = d.meta;
  $("metafoot").textContent =
    `Analyzed ${m.games_analyzed} games · ${d.engine_used ? `Stockfish deep pass on ${m.engine_games} games` : "statistical pass"}` +
    `${m.engine_available && !d.engine_used ? " · Stockfish available (tick “Deep” for engine metrics)" : ""}` +
    ` · data from the chess.com public API.`;
  // record card -> win-rate detail
  const rc = $("recordCard");
  if (rc) rc.onclick = () => openDetail("win_rate");
}

function renderPlayer(p, overall) {
  $("avatar").src = p.avatar || "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E";
  const title = p.title ? `<span style="color:var(--accent)">${p.title}</span> ` : "";
  $("pname").innerHTML = title + (p.name ? `${p.name} ` : "") + `<small style="color:var(--muted)">@${p.username}</small>`;
  const r = p.ratings || {};
  $("pratings").innerHTML = Object.entries(r)
    .map(([k, v]) => v.rating ? `${k}: <b>${v.rating}</b>${v.best ? ` <small>(best ${v.best})</small>` : ""}` : "")
    .filter(Boolean).join(" · ") || "<span>No published ratings</span>";
  drawGauge(overall);
  $("overallScore").textContent = Math.round(overall);
}

function renderRecord(o) {
  $("record").innerHTML = `
    <div class="recordpill w"><span class="n">${o.wins}</span><span class="l">Wins</span></div>
    <div class="recordpill d"><span class="n">${o.draws}</span><span class="l">Draws</span></div>
    <div class="recordpill l"><span class="n">${o.losses}</span><span class="l">Losses</span></div>
    <div class="recordpill"><span class="n">${o.score_pct}%</span><span class="l">Score</span></div>`;
}

function fmtStat(skill) {
  const s = skill.stats;
  switch (skill.key) {
    case "time_management":
      if (!s.games_analyzed) return "No timed games.";
      return `${s.lost_on_time_pct}% lost on time · ${s.time_scramble_games_pct}% reached time scramble` +
        (s.avg_seconds_per_move != null ? ` · ${s.avg_seconds_per_move}s avg/move` : "");
    case "openings":
      return `${s.distinct_openings} openings played` +
        (s.best_opening ? ` · best: ${s.best_opening.name} (${s.best_opening.score_pct}%)` : "");
    case "endgames":
      if (!s.games_reached_endgame) return s.note || "";
      return `${s.games_reached_endgame} endgames · ${s.endgame_score_pct}% score`;
    case "advantage_capitalization":
      if (!s.qualifying_games) return s.note || "";
      return `Converted ${s.converted_wins}/${s.qualifying_games} better positions (${s.conversion_pct}%)`;
    case "resourcefulness":
      if (!s.qualifying_games) return s.note || "";
      return `Saved ${s.points_saved_games}/${s.qualifying_games} worse positions (${s.save_pct}%)`;
    case "tactics":
      return (s.avg_accuracy != null ? `${s.avg_accuracy}% avg accuracy · ` : "") +
        `${s.quick_wins} quick wins / ${s.quick_losses} quick losses`;
    default:
      return "";
  }
}

function renderSkills(skills) {
  $("skills").innerHTML = skills.map((sk) => {
    const c = scoreColor(sk.score);
    return `<div class="skill" data-key="${sk.key}">
      <div class="top">
        <span class="name">${sk.label}</span>
        <span class="conf ${sk.confidence}">${sk.confidence}</span>
      </div>
      <div class="top" style="margin-top:6px">
        <span class="score" style="color:${c}">${Math.round(sk.score)}</span>
        <span class="hintsm">details ›</span>
      </div>
      <div class="bar"><span style="width:${sk.score}%;background:${c}"></span></div>
      <div class="detail">${fmtStat(sk)}</div>
    </div>`;
  }).join("");
  document.querySelectorAll("#skills .skill").forEach((el) =>
    el.onclick = () => openDetail(el.dataset.key)
  );
}

function renderOpenings(op) {
  if (!op || !op.stats.top_families || !op.stats.top_families.length) {
    $("openings").innerHTML = `<p style="color:var(--muted)">No opening data.</p>`;
    return;
  }
  const best = op.stats.best_opening, worst = op.stats.worst_opening;
  const rows = op.stats.top_families.map((f) => {
    let badge = "";
    if (best && f.name === best.name) badge = `<span class="opbadge best">best</span>`;
    else if (worst && f.name === worst.name) badge = `<span class="opbadge worst">worst</span>`;
    const c = scoreColor(f.score_pct);
    return `<tr>
      <td>${f.name} ${badge}</td>
      <td>${f.games}</td>
      <td style="color:${c}">${f.score_pct}%</td>
      <td>${f.avg_accuracy != null ? f.avg_accuracy + "%" : "—"}</td>
    </tr>`;
  }).join("");
  $("openings").innerHTML = `<table class="optable">
    <thead><tr><th>Opening</th><th>Games</th><th>Score</th><th>Acc.</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

let TIPS = [];
function renderTips(tips) {
  TIPS = tips || [];
  if (!TIPS.length) { $("tips").innerHTML = `<p style="color:var(--muted)">No tips.</p>`; return; }
  $("tips").innerHTML = TIPS.map((t, i) => `
    <div class="tip clickabletip" data-i="${i}">
      <div class="tipdot ${t.priority}"></div>
      <div class="tipbody">
        <div class="ts">${t.skill} <span class="hintsm">— how to improve ›</span></div>
        <div class="tt">${t.text}</div>
      </div>
    </div>`).join("");
  document.querySelectorAll("#tips .clickabletip").forEach((el) =>
    el.onclick = () => openTip(+el.dataset.i));
}

/* ---- charts ---- */
function drawGauge(score) {
  const ctx = $("overallGauge");
  if (gaugeChart) gaugeChart.destroy();
  gaugeChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      datasets: [{
        data: [score, 100 - score],
        backgroundColor: [scoreColor(score), COLORS.line],
        borderWidth: 0, cutout: "78%",
      }],
    },
    options: { rotation: -90, circumference: 360, plugins: { tooltip: { enabled: false }, legend: { display: false } } },
  });
}

function renderRadar(skills) {
  const ctx = $("radar");
  if (radarChart) radarChart.destroy();
  radarChart = new Chart(ctx, {
    type: "radar",
    data: {
      labels: skills.map((s) => s.label),
      datasets: [{
        data: skills.map((s) => s.score),
        backgroundColor: "rgba(124,198,110,.20)",
        borderColor: COLORS.accent, borderWidth: 2,
        pointBackgroundColor: COLORS.accent,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        r: {
          min: 0, max: 100, ticks: { display: false, stepSize: 25 },
          grid: { color: COLORS.line }, angleLines: { color: COLORS.line },
          pointLabels: { color: COLORS.muted, font: { size: 12 } },
        },
      },
    },
  });
}

function renderRating(series) {
  const ctx = $("rating");
  if (ratingChart) ratingChart.destroy();
  if (!series || series.length < 2) {
    ctx.parentElement.querySelector("canvas").style.display = "none";
    return;
  }
  ratingChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: series.map((_, i) => i),
      datasets: [{
        data: series.map((p) => p.r),
        borderColor: COLORS.accent2, borderWidth: 2, fill: true,
        backgroundColor: "rgba(90,160,224,.12)", pointRadius: 0, tension: .25,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { grid: { color: COLORS.line }, ticks: { color: COLORS.muted } },
      },
    },
  });
}

/* ===================== skill drill-down modal ===================== */
const STATUS_ICON = { good: "✅", bad: "🔥", warn: "⚠️", neutral: "•" };

function closeModal() {
  $("modal").classList.add("hidden");
  if (detailChart) { detailChart.destroy(); detailChart = null; }
}
$("modalClose").onclick = closeModal;
$("modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

function openDetail(key) {
  const d = DETAILS && DETAILS[key];
  if (!d) return;
  $("modal").classList.remove("tipmode");
  $("modalTitle").textContent = d.label || key;
  $("modalExtra").innerHTML = "";
  $("modalInterpH").textContent = "Interpretation";
  $("modalImproveH").textContent = "How to improve";
  if (detailChart) { detailChart.destroy(); detailChart = null; }
  const canvas = $("modalCanvas");

  if (d.engine_required) {
    canvas.style.display = "none";
    $("modalExtra").innerHTML = `<div class="engineprompt">🔬 This breakdown needs the
      <b>engine pass</b>. Tick <b>“Deep (Stockfish)”</b> at the top and re-run Analyze to
      see real per-move numbers here.</div>`;
  } else {
    canvas.style.display = "";
    (DETAIL_RENDER[key] || (() => {}))(d, canvas);
  }

  $("modalInterp").innerHTML = (d.interpretation || []).map((c) => `
    <div class="callout">
      <span class="ico">${STATUS_ICON[c.status] || "•"}</span>
      <div><div class="ctitle">${c.title}</div><div class="ctext">${c.text}</div></div>
    </div>`).join("");
  if (key === "openings") $("modalInterp").innerHTML += openingsRightSide(d);
  $("modalImprove").innerHTML = (d.how_to_improve || []).map((t) => `<li>${t}</li>`).join("");
  $("modal").classList.remove("hidden");
}

function openTip(i) {
  const t = TIPS[i];
  if (!t) return;
  $("modalTitle").textContent = `${t.skill} — how to improve`;
  if (detailChart) { detailChart.destroy(); detailChart = null; }
  $("modalCanvas").style.display = "none";
  $("modalExtra").innerHTML = `
    <div class="tiphead">
      <span class="tippri ${t.priority}">${t.priority} priority</span>
      <div class="tipsummary">${t.text}</div>
    </div>`;
  $("modalInterpH").textContent = "Why this is worth your attention";
  $("modalInterp").innerHTML = (t.rationale || []).map((r) => `
    <div class="callout"><span class="ico">•</span><div class="ctext">${r}</div></div>`).join("");
  $("modalImproveH").textContent = "Concrete steps to improve";
  $("modalImprove").innerHTML = (t.steps || []).map((s) => `<li>${s}</li>`).join("");
  $("modal").classList.add("tipmode");
  $("modal").classList.remove("hidden");
}

function mkChart(canvas, config) {
  detailChart = new Chart(canvas, config);
}

// Right-side content for the Openings panel: targeted per-opening tips + verdicts.
function openingsRightSide(d) {
  let html = "";
  const tips = d.specific_tips || [];
  if (tips.length) {
    html += `<h4 class="mt">🎯 Targeted advice — your most-played openings</h4>`;
    html += tips.map((t) => `
      <div class="callout">
        <span class="ico">${t.color === "White" ? "♙" : "♟"}</span>
        <div>
          <div class="ctitle">${t.color}: ${t.name} <span style="color:var(--muted);font-weight:400">· ${t.games} games · ${t.score_pct}% score</span></div>
          <div class="ctext">${t.text}</div>
        </div>
      </div>`).join("");
  }
  const pop = d.popular_openings || [];
  if (pop.length) {
    html += `<h4 class="mt">Your popular openings</h4>`;
    html += pop.map((o) => `
      <div class="callout">
        <span class="ico">${STATUS_ICON[o.status] || "•"}</span>
        <div><div class="ctitle">${o.name}</div><div class="ctext">${o.text}</div></div>
      </div>`).join("");
  }
  return html;
}
const AX = (extra = {}) => Object.assign({
  grid: { color: COLORS.line }, ticks: { color: COLORS.muted },
}, extra);

const DETAIL_RENDER = {
  win_rate(d, canvas) {
    const D = d.data;
    const cats = ["white", "black", "both"];
    mkChart(canvas, {
      type: "bar",
      data: {
        labels: ["White", "Black", "Both"],
        datasets: [
          { label: "Win", data: cats.map((c) => D[c].win), backgroundColor: COLORS.good, stack: "s" },
          { label: "Draw", data: cats.map((c) => D[c].draw), backgroundColor: "#9aa3b0", stack: "s" },
          { label: "Lose", data: cats.map((c) => D[c].lose), backgroundColor: COLORS.bad, stack: "s" },
        ],
      },
      options: {
        plugins: { legend: { labels: { color: COLORS.muted } } },
        scales: { x: AX(), y: AX({ max: 100, title: { display: true, text: "%", color: COLORS.muted } }) },
      },
    });
  },

  openings(d, canvas) {
    const m = d.move15;
    mkChart(canvas, {
      type: "bar",
      data: {
        labels: ["Both", "White", "Black"],
        datasets: [{
          label: "Avg score after move 15 (pawns)",
          data: [m.both, m.white, m.black],
          backgroundColor: ["Both", "White", "Black"].map((_, i) =>
            [m.both, m.white, m.black][i] >= 0 ? COLORS.good : COLORS.bad),
        }],
      },
      options: {
        plugins: { legend: { display: false }, title: { display: true, text: "Score on move 15", color: COLORS.muted } },
        scales: { x: AX(), y: AX() },
      },
    });
    // Per-opening win/draw/loss bars, grouped by title and split White / Black.
    const oprow = (o) => `
      <div class="minirow">
        <div style="flex:1; min-width:0; padding-right:8px">
          <div class="mtitle" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis">${o.name}</div>
        </div>
        <span style="width:118px; flex:none; display:flex; height:15px; border-radius:5px; overflow:hidden; background:var(--panel2)">
          <span style="width:${o.win}%;background:${COLORS.good}"></span>
          <span style="width:${o.draw}%;background:#9aa3b0"></span>
          <span style="width:${o.lose}%;background:${COLORS.bad}"></span>
        </span>
        <span class="mtext" style="width:34px; flex:none; text-align:right">${o.games}g</span>
      </div>`;
    const section = (title, rows) => rows && rows.length
      ? `<h4 class="mt">${title}</h4><div class="minilist">${rows.map(oprow).join("")}</div>`
      : "";
    $("modalExtra").innerHTML =
      section("♙ White openings (win / draw / loss)", d.white_openings) +
      section("♟ Black openings (win / draw / loss)", d.black_openings);
  },

  advantage_capitalization(d, canvas) {
    bucketChart(canvas, d.buckets, "won", "% of advantages converted to wins", COLORS.good,
      (b) => `+${b.threshold}`);
  },
  resourcefulness(d, canvas) {
    bucketChart(canvas, d.buckets, "saved", "% of bad positions saved (win/draw)", COLORS.accent2,
      (b) => `${b.threshold}`);
  },

  tactics(d, canvas) {
    const keys = ["blunders", "mistakes", "inaccuracies"];
    mkChart(canvas, {
      type: "bar",
      data: {
        labels: ["Blunders", "Mistakes", "Inaccuracies"],
        datasets: [
          { label: "You", data: keys.map((k) => d.user[k]), backgroundColor: COLORS.accent },
          { label: "Opponents", data: keys.map((k) => d.opponent[k]), backgroundColor: "#c98b5a" },
        ],
      },
      options: {
        plugins: { legend: { labels: { color: COLORS.muted } }, title: { display: true, text: "Per game", color: COLORS.muted } },
        scales: { x: AX(), y: AX() },
      },
    });
    const st = d.per_stage || {};
    const row = (name) => st[name]
      ? `<div class="minirow"><span class="mtitle" style="width:110px;text-transform:capitalize">${name}</span>
         <span class="mtext">${st[name].blunders} blunders · ${st[name].mistakes} mistakes · ${st[name].inaccuracies} inaccuracies</span></div>`
      : "";
    $("modalExtra").innerHTML = `<h4 class="mt">Where your errors happen</h4>
      <div class="minilist">${row("opening")}${row("middlegame")}${row("endgame")}</div>
      <div class="mtext" style="margin-top:8px">Average centipawn loss: <b>${d.user.avg_cpl}</b> (you) vs <b>${d.opponent.avg_cpl}</b> (opponents).</div>`;
  },

  time_management(d, canvas) {
    const p = d.phases || {};
    mkChart(canvas, {
      type: "bar",
      data: {
        labels: ["Opening", "Middlegame", "Endgame"],
        datasets: [{ label: "Avg seconds per move", data: [p.opening, p.middlegame, p.endgame],
          backgroundColor: COLORS.accent2 }],
      },
      options: {
        plugins: { legend: { display: false }, title: { display: true, text: "Time spent per phase", color: COLORS.muted } },
        scales: { x: AX(), y: AX() },
      },
    });
  },

  endgames(d, canvas) {
    const s = d.summary || {}; const c = s.cats || {};
    mkChart(canvas, {
      type: "bar",
      data: {
        labels: [`Convert winning\n(${(c.winning||{}).games||0})`, `Hold equal\n(${(c.equal||{}).games||0})`, `Save losing\n(${(c.losing||{}).games||0})`],
        datasets: [{
          label: "Success %",
          data: [s.winning_conversion, s.equal_hold, s.losing_save],
          backgroundColor: [COLORS.good, COLORS.accent2, COLORS.warn],
        }],
      },
      options: {
        plugins: { legend: { display: false }, title: { display: true, text: `Endgame outcomes (${s.reached} reached)`, color: COLORS.muted } },
        scales: { x: AX(), y: AX({ max: 100 }) },
      },
    });
    const notable = (d.notable || []).map((nrow) => {
      const ico = nrow.type === "saved" ? "💪" : "🔥";
      const verb = nrow.type === "saved"
        ? `Saved a lost endgame (entered ${nrow.entry}) → ${nrow.result}`
        : `Threw a winning endgame (entered +${nrow.entry}) → ${nrow.result}`;
      return `<div class="minirow"><span class="ico">${ico}</span>
        <div><div class="mtitle">${nrow.opening || "Game"}</div>
        <div class="mtext"><a href="${nrow.url}" target="_blank" style="color:var(--accent2)">${verb}</a></div></div></div>`;
    }).join("");
    if (notable) $("modalExtra").innerHTML = `<h4 class="mt">Notable endgames</h4><div class="minilist">${notable}</div>`;
  },
};

function bucketChart(canvas, buckets, field, title, color, labeler) {
  mkChart(canvas, {
    type: "bar",
    data: {
      labels: buckets.map((b) => `${labeler(b)} (${b.games})`),
      datasets: [{ label: title, data: buckets.map((b) => b.pct), backgroundColor: color }],
    },
    options: {
      plugins: { legend: { display: false }, title: { display: true, text: title, color: COLORS.muted } },
      scales: { x: AX({ title: { display: true, text: "advantage threshold (pawns) · n games", color: COLORS.muted } }),
                y: AX({ max: 100 }) },
    },
  });
}

/* ===================== recent games + warming status ===================== */
function timeAgo(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
}

const GAMES_PAGE = 10;
function renderGames(games) {
  const gameRow = (g) => `
    <div class="gamerow">
      <span class="res ${g.result}">${g.result === "win" ? "W" : g.result === "draw" ? "½" : "L"}</span>
      <span class="opn"><span class="colordot ${g.color}"></span>${g.opening_name}</span>
      <span class="meta2">${g.time_class} · ${g.user_rating || "?"} vs ${g.opp_rating || "?"} · ${timeAgo(g.end_time)}</span>
      <button data-uuid="${g.uuid}">Review ›</button>
    </div>`;

  const list = $("gameslist");
  if (!games.length) {
    list.innerHTML = `<p style="color:var(--muted)">No games.</p>`;
    return;
  }

  let shown = GAMES_PAGE;
  const draw = () => {
    const rows = games.slice(0, shown).map(gameRow).join("");
    const more = shown < games.length
      ? `<button id="showmore" class="showmore">Show more (${games.length - shown})</button>`
      : "";
    list.innerHTML = rows + more;
    list.querySelectorAll(".gamerow button").forEach((b) =>
      b.onclick = () => openReview(b.dataset.uuid));
    const moreBtn = $("showmore");
    if (moreBtn) moreBtn.onclick = () => { shown = games.length; draw(); };
  };
  draw();
}

let statusTimer = null;
function startStatusPolling() {
  if (statusTimer) clearInterval(statusTimer);
  const poll = async () => {
    try {
      const r = await fetch("/api/engine-status?username=" + encodeURIComponent(CURRENT_USER));
      const s = await r.json();
      const badge = $("warmbadge");
      if (!s.available) { badge.classList.add("hidden"); return; }
      badge.classList.remove("hidden");
      if (s.cached >= s.total && s.total > 0) {
        badge.innerHTML = `✅ Deep engine analysis ready for all <b>${s.total}</b> recent games — tick “Deep (Stockfish)” and re-run for full engine metrics.`;
        if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
      } else {
        badge.innerHTML = `⚙ Analyzing games in the background… <b>${s.cached}/${s.total}</b> ready`;
      }
    } catch (e) { /* ignore */ }
  };
  poll();
  statusTimer = setInterval(poll, 4000);
}

/* ===================== game review overlay ===================== */
const PIECES = { K: "♔", Q: "♕", R: "♖", B: "♗", N: "♘", P: "♙",
                 k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
let REVIEW = null;   // {moves, ...}
let REVIEW_PLY = 0;  // 0 == initial position

function closeReview() { $("review").classList.add("hidden"); REVIEW = null; }
$("reviewClose").onclick = closeReview;

async function openReview(uuid) {
  $("review").classList.remove("hidden");
  $("reviewtitle").textContent = "Analyzing game with Stockfish…";
  $("movelist").innerHTML = `<div class="loading" style="padding:30px"><div class="spinner"></div>Reviewing every move…</div>`;
  $("moveinfo").innerHTML = ""; $("summarybar").innerHTML = ""; $("board").innerHTML = "";
  try {
    const r = await fetch(`/api/review?username=${encodeURIComponent(CURRENT_USER)}&uuid=${encodeURIComponent(uuid)}`);
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "Review failed");
    REVIEW = d; REVIEW_PLY = 0;
    const w = d.white.username || "White", b = d.black.username || "Black";
    $("reviewtitle").innerHTML = `${w} vs ${b} · <span style="color:var(--muted)">${d.opening_name} · depth ${d.depth} · your ACPL ${d.acpl}</span>`;
    renderSummary(d.summary);
    renderMoveList(d.moves);
    gotoPly(d.moves.length);  // jump to final position
  } catch (e) {
    $("reviewtitle").textContent = "Review failed";
    $("movelist").innerHTML = `<div class="errorbox">⚠ ${e.message}</div>`;
  }
}

function renderSummary(sum) {
  const order = ["Best", "Excellent", "Good", "Book", "Inaccuracy", "Mistake", "Blunder"];
  $("summarybar").innerHTML = order.filter((k) => sum[k]).map((k) =>
    `<span class="chip cls-${k}">${sum[k]} ${k}</span>`).join("");
}

function renderMoveList(moves) {
  let html = "", i = 0;
  while (i < moves.length) {
    const wm = moves[i], bm = moves[i + 1];
    const cell = (m) => m
      ? `<div class="mv" data-ply="${m.ply}"><span class="ic cls-${m.cls}"></span>${m.san}</div>`
      : `<div></div>`;
    html += `<div class="mvpair"><span class="mvno">${wm.move_no}.</span>${cell(wm)}${cell(bm)}</div>`;
    i += 2;
  }
  $("movelist").innerHTML = html;
  document.querySelectorAll("#movelist .mv").forEach((el) =>
    el.onclick = () => gotoPly(+el.dataset.ply));
}

function fenToBoard(fen, hl) {
  const rows = fen.split(" ")[0].split("/");
  let html = "";
  for (let r = 0; r < 8; r++) {
    let file = 0;
    for (const ch of rows[r]) {
      if (/\d/.test(ch)) {
        for (let k = 0; k < +ch; k++) { html += sq(r, file, ""); file++; }
      } else {
        const color = ch === ch.toUpperCase() ? "white" : "black";
        html += sq(r, file, `<span class="pc ${color}">${PIECES[ch]}</span>`, hl, r, file);
        file++;
      }
    }
  }
  function sq(r, f, inner, hlset, rr, ff) {
    const dark = (r + f) % 2 === 1;
    const sqName = "abcdefgh"[f] + (8 - r);
    const isHl = hl && (hl.from === sqName || hl.to === sqName);
    return `<div class="sq ${dark ? "dark" : "light"}${isHl ? " hl" : ""}">${inner}</div>`;
  }
  $("board").innerHTML = html;
}

// Center of a square (e.g. "e4") in board units, where the board is 8x8.
function sqCenter(name) {
  const f = "abcdefgh".indexOf(name[0]);
  const rank = +name[1];
  return { x: f + 0.5, y: (8 - rank) + 0.5 };
}

// Overlay best-move suggestion arrows on the board. arrows: [{from,to,color}].
function drawArrows(arrows) {
  const board = $("board");
  const prev = board.querySelector("svg.arrows");
  if (prev) prev.remove();
  if (!arrows || !arrows.length) return;
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "arrows");
  svg.setAttribute("viewBox", "0 0 8 8");
  svg.setAttribute("preserveAspectRatio", "none");
  for (const a of arrows) {
    const p0 = sqCenter(a.from), p1 = sqCenter(a.to);
    const dx = p1.x - p0.x, dy = p1.y - p0.y;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len, uy = dy / len;     // unit direction
    const px = -uy, py = ux;                  // perpendicular
    const head = 0.34, halfW = 0.19;          // arrowhead size
    const sx = p0.x + ux * 0.30, sy = p0.y + uy * 0.30;   // start (just off origin square)
    const tipX = p1.x - ux * 0.12, tipY = p1.y - uy * 0.12;
    const baseX = tipX - ux * head, baseY = tipY - uy * head;
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", sx); line.setAttribute("y1", sy);
    line.setAttribute("x2", baseX); line.setAttribute("y2", baseY);
    line.setAttribute("stroke", a.color); line.setAttribute("stroke-width", "0.15");
    line.setAttribute("stroke-linecap", "round");
    const headEl = document.createElementNS(NS, "polygon");
    headEl.setAttribute("points",
      `${tipX},${tipY} ${baseX + px * halfW},${baseY + py * halfW} ${baseX - px * halfW},${baseY - py * halfW}`);
    headEl.setAttribute("fill", a.color);
    svg.appendChild(line); svg.appendChild(headEl);
  }
  board.appendChild(svg);
}

function gotoPly(ply) {
  if (!REVIEW) return;
  REVIEW_PLY = Math.max(0, Math.min(REVIEW.moves.length, ply));
  const moves = REVIEW.moves;
  let fen, evalCp, hl = null, m = null;
  if (REVIEW_PLY === 0) {
    fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
    evalCp = REVIEW.initial_eval;
  } else {
    m = moves[REVIEW_PLY - 1];
    fen = m.fen; evalCp = m.eval;
    const uci = m.uci;
    hl = { from: uci.slice(0, 2), to: uci.slice(2, 4) };
  }
  fenToBoard(fen, hl);
  // Suggestion arrow: the engine's best move, when it differs from what was played.
  const arrows = [];
  if (m && m.best_uci && m.best_uci !== m.uci) {
    arrows.push({ from: m.best_uci.slice(0, 2), to: m.best_uci.slice(2, 4), color: "#7cc66e" });
  }
  drawArrows(arrows);
  // eval bar: white advantage; clamp display to +-600cp
  const frac = Math.max(0, Math.min(1, 0.5 + (Math.max(-600, Math.min(600, evalCp)) / 1200)));
  $("evalfill").style.height = (frac * 100) + "%";
  $("navLabel").textContent = REVIEW_PLY === 0 ? "Start"
    : `${m.move_no}${m.side === "w" ? "." : "…"} ${m.san}`;
  document.querySelectorAll("#movelist .mv").forEach((el) =>
    el.classList.toggle("sel", +el.dataset.ply === REVIEW_PLY));
  const selEl = document.querySelector(`#movelist .mv[data-ply="${REVIEW_PLY}"]`);
  if (selEl) selEl.scrollIntoView({ block: "nearest" });
  renderMoveInfo(m);
}

function renderMoveInfo(m) {
  if (!m) { $("moveinfo").innerHTML = `<div class="mibody">Starting position. Use ← / → to step through the game.</div>`; return; }
  const evalP = (m.eval / 100).toFixed(1);
  const who = m.is_user ? "You" : "Opponent";
  const hasLine = m.best_line && m.best_line.length;
  const lineBlock = hasLine
    ? `<button id="lineBtn" class="linebtn">Show engine line ▸</button>
       <div id="engineLine" class="line hidden">Engine line: <b>${m.best_san}</b> ${m.best_line.slice(1).join(" ")}</div>`
    : "";
  const body = m.explanation
    ? m.explanation
    : `${who} played <b>${m.san}</b>. Engine's choice: ${m.best_san || "—"}. Evaluation: ${evalP >= 0 ? "+" : ""}${evalP} (White).`;
  $("moveinfo").innerHTML = `
    <div class="mihead"><span class="tag cls-${m.cls}">${m.cls}</span>
      <b>${m.move_no}${m.side === "w" ? "." : "…"} ${m.san}</b>
      <span style="color:var(--muted);font-size:12px">${who}${m.cpl ? " · −" + (m.cpl/100).toFixed(1) + " pawns" : ""}</span>
    </div>
    <div class="mibody">${body}</div>${lineBlock}`;
  const lineBtn = $("lineBtn");
  if (lineBtn) lineBtn.onclick = () => {
    const hidden = $("engineLine").classList.toggle("hidden");
    lineBtn.textContent = hidden ? "Show engine line ▸" : "Hide engine line ▾";
  };
}

$("navFirst").onclick = () => gotoPly(0);
$("navPrev").onclick = () => gotoPly(REVIEW_PLY - 1);
$("navNext").onclick = () => gotoPly(REVIEW_PLY + 1);
$("navLast").onclick = () => gotoPly(REVIEW ? REVIEW.moves.length : 0);
document.addEventListener("keydown", (e) => {
  if ($("review").classList.contains("hidden")) return;
  if (e.key === "ArrowLeft") { gotoPly(REVIEW_PLY - 1); e.preventDefault(); }
  else if (e.key === "ArrowRight") { gotoPly(REVIEW_PLY + 1); e.preventDefault(); }
  else if (e.key === "Escape") closeReview();
});

// Allow ?u=username deep links.
const pre = new URLSearchParams(location.search).get("u");
if (pre) { $("username").value = pre; runReport(); }
