"use strict";

/* ------------------------------------------------------------------ *
 *  Coach Running — frontend
 * ------------------------------------------------------------------ */

const state = {
  activities: [],
  selectedId: null,
  currentView: "activities",
  map: null,
  trackLayer: null,
  legendControl: null,
  heatmapMap: null,
  heatLayer: null,
  activeTab: "splits",
  currentDetail: null,
  coachingTab: "fitness",
  profile: null,
  shoes: [],
  weights: [],
  coachConfigured: false,
  chatHistory: [],
  plannerWeek: null,
  plannerSessions: [],
  plannerEditing: null,
  nutritionLogs: [],
  supplements: [],
};

const ACTIVITY_LABELS = {
  running: "Running",
  trail_running: "Trail",
  street_running: "Road",
  track_running: "Track",
  unknown: "Activity",
};

const PERIOD_LABELS = { weekly: "This week", monthly: "This month", yearly: "This year" };
const METRIC_LABELS = { distance: "Distance", time: "Time", elevation: "Elevation" };

/* ----------------------------- Helpers ---------------------------- */

function $(sel) { return document.querySelector(sel); }

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtDistance(m) {
  if (m == null) return "—";
  return m >= 1000 ? (m / 1000).toFixed(2) + " km" : Math.round(m) + " m";
}

function fmtDuration(s) {
  if (s == null || s <= 0) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.round(s % 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
}

function fmtPace(sPerKm) {
  if (sPerKm == null || sPerKm <= 0) return "—";
  const m = Math.floor(sPerKm / 60);
  const s = Math.round(sPerKm % 60);
  return `${m}'${String(s).padStart(2, "0")}" /km`;
}

function fmtSpeed(ms) {
  if (ms == null) return "—";
  return (ms * 3.6).toFixed(1) + " km/h";
}

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

function fmtDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
    + " · " + d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function fmtTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function fmtMonth(key) {
  const [y, m] = key.split("-");
  return new Date(parseInt(y, 10), parseInt(m, 10) - 1, 1)
    .toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function typeLabel(t) { return ACTIVITY_LABELS[t] || t; }

function percentile(values, p) {
  if (!values.length) return 0;
  const sorted = values.slice().sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
}

/* Speed color scale: green (slow) -> red (fast). */
function speedColor(speed, maxSpeed) {
  if (speed == null || speed <= 0) return "#94a3b8";
  const t = Math.min(1, Math.max(0, speed / maxSpeed));
  const hue = 120 - 120 * t;
  return `hsl(${hue.toFixed(0)}, 80%, 48%)`;
}

/* --------------------------- Navigation --------------------------- */

function switchView(name) {
  state.currentView = name;
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  document.querySelectorAll(".nav-btn").forEach((b) => {
    const active = b.dataset.view === name;
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  const view = document.getElementById("view-" + name);
  if (view) view.classList.remove("hidden");

  if (name === "home") showHome();
  if (name === "heatmap") showHeatmap();
  if (name === "records") loadRecords();
  if (name === "stats") loadMonthly();
  if (name === "goals") loadGoals();
  if (name === "coaching") loadCoaching();
  if (name === "profile") loadProfile();
  if (name === "planner") showPlanner();
  if (name === "fuel") showFuel();
  if (name === "activities" && state.map) setTimeout(() => state.map.invalidateSize(), 50);
}

/* ------------------------ Summary + list -------------------------- */

function renderSummary(summary) {
  $("#sum-activities").textContent = summary.activities;
  $("#sum-distance").textContent = fmtDistance(summary.distance_m);
  $("#sum-time").textContent = fmtDuration(summary.moving_time_s);
  $("#sum-elevation").textContent = Math.round(summary.elevation_gain_m) + " m";
}

function renderList(activities) {
  const ul = $("#activity-list");
  ul.innerHTML = "";
  $("#count").textContent = activities.length + " run" + (activities.length > 1 ? "s" : "");

  for (const a of activities) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "activity-item" + (a.id === state.selectedId ? " active" : "");
    btn.dataset.id = a.id;
    btn.setAttribute("aria-pressed", a.id === state.selectedId ? "true" : "false");

    const st = a.stats;
    const row1 = document.createElement("div");
    row1.className = "row1";
    const date = document.createElement("span");
    date.className = "date";
    date.textContent = fmtDate(a.start_time);
    const badge = document.createElement("span");
    badge.className = "badge " + esc(a.activity_type);
    badge.textContent = typeLabel(a.activity_type);
    row1.append(date, badge);

    const row2 = document.createElement("div");
    row2.className = "row2";
    row2.innerHTML =
      "<span><b>" + esc(fmtDistance(st.distance_m)) + "</b></span>" +
      "<span><b>" + esc(fmtDuration(st.moving_time_s)) + "</b></span>" +
      "<span>" + esc(fmtPace(st.avg_pace_s_per_km)) + "</span>" +
      "<span>⬆ " + Math.round(st.elevation_gain_m) + " m</span>";

    btn.append(row1, row2);

    if (a.has_note) {
      const note = document.createElement("div");
      note.className = "has-note";
      note.textContent = "📝 " + (a.note.length > 60 ? a.note.slice(0, 60) + "…" : a.note);
      btn.append(note);
    }

    btn.addEventListener("click", () => selectActivity(a.id));
    li.append(btn);
    ul.append(li);
  }
}

/* ----------------------------- Map -------------------------------- */

function initMap() {
  if (state.map) return;
  state.map = L.map("map", { zoomControl: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(state.map);
}

function drawTrack(detail) {
  if (state.trackLayer) {
    state.map.removeLayer(state.trackLayer);
    state.trackLayer = null;
  }
  removeLegend();

  const vp = [];
  for (const p of detail.points || []) {
    const [lat, lon, , , speed] = p;
    if (lat != null && lon != null) vp.push({ lat, lon, speed });
  }
  if (vp.length === 0) return;

  const group = L.featureGroup().addTo(state.map);

  const speeds = vp.map((p) => p.speed).filter((s) => s != null && s > 0);
  const maxSpeed = percentile(speeds, 0.95) || 4;

  const segments = [];
  let cur = null;
  for (let i = 1; i < vp.length; i++) {
    const a = vp[i - 1], b = vp[i];
    const speed = (a.speed != null && b.speed != null) ? (a.speed + b.speed) / 2 : (a.speed ?? b.speed);
    const bucket = speed == null ? -1 : Math.round(speed / maxSpeed * 40);
    if (!cur || cur.bucket !== bucket) {
      cur = { bucket, coords: [[a.lat, a.lon]], speed };
      segments.push(cur);
    }
    cur.coords.push([b.lat, b.lon]);
  }

  for (const seg of segments) {
    L.polyline(seg.coords, {
      color: seg.bucket === -1 ? "#94a3b8" : speedColor(seg.speed, maxSpeed),
      weight: 4, opacity: 0.85, lineJoin: "round", lineCap: "round",
    }).addTo(group);
  }

  const start = vp[0], end = vp[vp.length - 1];
  const startIcon = L.divIcon({ className: "marker-start", html: "<span>Start</span>", iconSize: [0, 0] });
  const endIcon = L.divIcon({ className: "marker-end", html: "<span>Finish</span>", iconSize: [0, 0] });
  L.marker([start.lat, start.lon], { icon: startIcon }).addTo(group);
  L.marker([end.lat, end.lon], { icon: endIcon }).addTo(group);

  for (const m of detail.markers || []) {
    if (m.lat == null || m.lon == null) continue;
    L.circleMarker([m.lat, m.lon], {
      radius: 5, color: "#1f2937", weight: 1, fillColor: "#fff", fillOpacity: 1,
    }).bindPopup(m.description || m.name || "Marker").addTo(group);
  }

  state.trackLayer = group;
  state.map.fitBounds(group.getBounds(), { padding: [30, 30] });

  showLegend(maxSpeed);
}

function showLegend(maxSpeed) {
  const maxKmh = maxSpeed * 3.6;
  state.legendControl = L.control({ position: "bottomright" });
  state.legendControl.onAdd = () => {
    const div = L.DomUtil.create("div", "speed-legend");
    div.innerHTML =
      '<div class="legend-title">Speed</div>' +
      '<div class="legend-gradient"></div>' +
      '<div class="legend-labels"><span>0 km/h</span><span>' + maxKmh.toFixed(1) + ' km/h</span></div>';
    return div;
  };
  state.legendControl.addTo(state.map);
}

function removeLegend() {
  if (state.legendControl) {
    state.map.removeControl(state.legendControl);
    state.legendControl = null;
  }
}

/* ------------------------- Detail + analyses ---------------------- */

function statHtml(value, label, cls) {
  return `<div class="stat ${cls || ""}"><span class="stat-value">${esc(value)}</span><span class="stat-label">${esc(label)}</span></div>`;
}

function renderDetail(detail) {
  $("#empty-state").classList.add("hidden");
  $("#detail").classList.remove("hidden");

  $("#d-type").className = "badge " + esc(detail.activity_type);
  $("#d-type").textContent = typeLabel(detail.activity_type);
  $("#d-title").textContent = detail.has_note && detail.note
    ? detail.note : ("Run of " + fmtDate(detail.start_time));
  $("#d-date").textContent = fmtDateTime(detail.start_time);

  const st = detail.stats;
  const gap = detail.analysis?.gap?.gap_pace_s_per_km;
  const statsHtml = [
    statHtml(fmtDistance(st.distance_m), "Distance"),
    statHtml(fmtDuration(st.moving_time_s), "Moving time"),
    statHtml(fmtPace(st.avg_pace_s_per_km), "Avg pace"),
    gap ? statHtml(fmtPace(gap), "GAP pace", "gap") : "",
    statHtml(Math.round(st.elevation_gain_m) + " m", "Elevation gain"),
    statHtml(fmtSpeed(st.max_speed_ms), "Max speed"),
  ];
  if (st.has_hr) {
    statsHtml.push(statHtml((st.avg_hr ?? "—") + " bpm", "Avg HR"));
    statsHtml.push(statHtml((st.max_hr ?? "—") + " bpm", "Max HR"));
  }
  $("#d-stats").innerHTML = statsHtml.join("");

  $("#note-input").value = detail.note || "";
  $("#notes-status").textContent = "";
  $("#notes-status").classList.remove("saved");
  populateShoeSelect(detail.shoe ? detail.shoe.id : null);

  state.currentDetail = detail;
  state.activeTab = "splits";
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === "splits"));
  renderTab();

  initMap();
  drawTrack(detail);
}

function renderTab() {
  const detail = state.currentDetail;
  if (!detail) return;
  const body = $("#analysis-tab-body");
  const tab = state.activeTab;
  if (tab === "splits") body.innerHTML = renderSplits(detail.analysis?.splits || []);
  else if (tab === "feedback") renderFeedbackTab(detail);
  else if (tab === "laps") body.innerHTML = renderLaps(detail.analysis?.laps || []);
  else if (tab === "zones") body.innerHTML = renderZones(detail.analysis?.zones);
  else if (tab === "gap") body.innerHTML = renderGap(detail);
}

function renderSplits(splits) {
  if (!splits.length) return '<p class="empty-note">No splits available.</p>';
  let rows = splits.map((s) => `
    <tr>
      <td class="num">${s.index}</td>
      <td class="num">${fmtDistance(s.distance_m)}</td>
      <td class="num">${fmtDuration(s.moving_time_s)}</td>
      <td class="num">${fmtPace(s.pace_s_per_km)}</td>
      <td class="num">${Math.round(s.elevation_gain_m)} m</td>
    </tr>`).join("");
  return `
    <table class="data" aria-label="Splits per kilometre">
      <thead><tr><th scope="col" class="num">Km</th><th scope="col" class="num">Distance</th><th scope="col" class="num">Time</th><th scope="col" class="num">Pace</th><th scope="col" class="num">Elev. gain</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderLaps(laps) {
  if (!laps.length) return '<p class="empty-note">No segment (lap) detected on this run.</p>';
  let rows = laps.map((l) => `
    <tr>
      <td class="num">${l.index}</td>
      <td>${fmtTime(l.start_time)}</td>
      <td class="num">${fmtDistance(l.distance_m)}</td>
      <td class="num">${fmtDuration(l.moving_time_s)}</td>
      <td class="num">${fmtPace(l.pace_s_per_km)}</td>
      <td class="num">${Math.round(l.elevation_gain_m)} m</td>
    </tr>`).join("");
  return `
    <table class="data" aria-label="Laps">
      <thead><tr><th scope="col" class="num">#</th><th scope="col">Start</th><th scope="col" class="num">Distance</th><th scope="col" class="num">Time</th><th scope="col" class="num">Pace</th><th scope="col" class="num">Elev. gain</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderZones(zones) {
  if (!zones || !zones.zones || !zones.zones.some((z) => z.time_s > 0)) {
    return '<p class="empty-note">No usable speed data for pace zones.</p>';
  }
  return zones.zones.map((z) => `
    <div class="zone-bar-row">
      <div class="zone-bar-label">${esc(z.name)}</div>
      <div class="zone-bar-track">
        <div class="zone-bar-fill" style="width:${z.percent}%;background:${z.color}"></div>
      </div>
      <div class="zone-bar-val">${fmtDuration(z.time_s)} · ${fmtDistance(z.distance_m)} (${z.percent}%)</div>
    </div>`).join("");
}

function renderGap(detail) {
  const g = detail.analysis?.gap;
  if (!g) return '<p class="empty-note">GAP not available.</p>';
  const real = detail.stats.avg_pace_s_per_km;
  const delta = Math.round(real - g.gap_pace_s_per_km);
  const sign = delta >= 0 ? "+" : "−";
  return `
    <p><strong>What is GAP (Grade-Adjusted Pace)?</strong> It estimates the pace you would have run
       on flat ground for the same effort, by correcting for the grade of each section.</p>
    <p>Concretely: a hilly 6:00/km run can be a <em>stronger</em> effort than a flat 5:40/km run —
       GAP makes them comparable. Use it to compare workouts run on different routes, gauge your
       true effort on hilly terrain, and set realistic pace targets for flat races.</p>
    <table class="data" style="max-width:480px">
      <tbody>
        <tr><td>Actual pace</td><td class="num">${fmtPace(real)}</td></tr>
        <tr><td>GAP pace (flat equivalent)</td><td class="num"><b>${fmtPace(g.gap_pace_s_per_km)}</b></td></tr>
        <tr><td>Difference due to terrain</td><td class="num">${sign}${fmtDuration(Math.abs(delta))} /km</td></tr>
        <tr><td>Average grade (signed)</td><td class="num">${g.avg_grade_pct} %</td></tr>
      </tbody>
    </table>
    <p class="muted" style="font-size:12px;margin-top:10px">A GAP faster than the actual pace means a hilly route.</p>`;
}

/* -------------------------- Selection ----------------------------- */

async function selectActivity(id) {
  state.selectedId = id;
  document.querySelectorAll(".activity-item").forEach((el) => {
    const active = el.dataset.id === id;
    el.classList.toggle("active", active);
    el.setAttribute("aria-pressed", active ? "true" : "false");
  });
  try {
    const res = await fetch(`/api/activities/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error("Not found");
    const detail = await res.json();
    renderDetail(detail);
  } catch (err) {
    console.error(err);
  }
}

/* ----------------------------- Notes ------------------------------ */

async function saveNote() {
  if (!state.selectedId) return;
  const note = $("#note-input").value.trim();
  const status = $("#notes-status");
  try {
    const res = await fetch(`/api/activities/${encodeURIComponent(state.selectedId)}/note`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    if (!res.ok) throw new Error("save failed");
    status.textContent = "Note saved ✓";
    status.classList.add("saved");
    await loadActivities(true);
  } catch (err) {
    status.textContent = "Error while saving";
    status.classList.remove("saved");
  }
}

/* ------------------------ RPE (perceived effort) ------------------ */

/* ---------------------------- Heatmap ----------------------------- */

function showHeatmap() {
  if (!state.heatmapMap) {
    state.heatmapMap = L.map("heatmap-map");
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(state.heatmapMap);
    fetch("/api/heatmap")
      .then((r) => r.json())
      .then((data) => {
        if (!data.points || !data.points.length) return;
        state.heatLayer = L.heatLayer(data.points.map((p) => [p[0], p[1], 0.6]), {
          radius: 22, blur: 14, maxZoom: 17, minOpacity: 0.25,
        }).addTo(state.heatmapMap);
        let minLat = 90, maxLat = -90, minLon = 180, maxLon = -180;
        for (const p of data.points) {
          if (p[0] < minLat) minLat = p[0];
          if (p[0] > maxLat) maxLat = p[0];
          if (p[1] < minLon) minLon = p[1];
          if (p[1] > maxLon) maxLon = p[1];
        }
        state.heatmapMap.fitBounds([[minLat, minLon], [maxLat, maxLon]], { padding: [20, 20] });
      })
      .catch(console.error);
  } else {
    setTimeout(() => state.heatmapMap.invalidateSize(), 50);
  }
}

/* ---------------------------- Records ----------------------------- */

async function loadRecords() {
  const [beRes, mrRes] = await Promise.all([
    fetch("/api/best-efforts"),
    fetch("/api/matched-runs"),
  ]);
  const be = await beRes.json();
  const mr = await mrRes.json();
  renderBestEfforts(be.best_efforts || []);
  renderMatchedRuns(mr.groups || []);
}

function renderBestEfforts(efforts) {
  const medals = ["🥇", "🥈", "🥉"];
  const el = $("#best-efforts");
  if (!efforts.length) { el.innerHTML = '<p class="empty-note">No record to display.</p>'; return; }
  el.innerHTML = efforts.map((e, i) => `
    <div class="record-row" data-id="${esc(e.activity_id)}">
      <span class="record-medal">${medals[i] || "🏅"}</span>
      <span class="record-dist">${esc(e.label)}</span>
      <span class="record-time">${fmtDuration(e.time_s)}</span>
      <span class="record-pace">${fmtPace(e.pace_s_per_km)} · ${fmtDate(e.date)}</span>
    </div>`).join("");
  el.querySelectorAll(".record-row").forEach((r) => {
    r.tabIndex = 0;
    r.setAttribute("role", "button");
    r.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); r.click(); }
    });
    r.addEventListener("click", () => {
      switchView("activities");
      selectActivity(r.dataset.id);
    });
  });
}

function renderMatchedRuns(groups) {
  const el = $("#matched-runs");
  if (!groups.length) {
    el.innerHTML = '<p class="empty-note">No repeated route detected (requires at least 2 runs on a similar route).</p>';
    return;
  }
  el.innerHTML = groups.map((g) => {
    const bestPace = Math.min(...g.map((m) => m.pace_s_per_km));
    const cards = g.map((m) => `
      <div class="match-card" data-id="${esc(m.id)}">
        <span class="match-date">${fmtDate(m.date)}</span>
        <span class="match-note">${esc(m.note || "Run")}</span>
        <span class="match-pace" ${m.pace_s_per_km === bestPace ? 'style="color:var(--orange)"' : ""}>${fmtPace(m.pace_s_per_km)}</span>
      </div>`).join("");
    return `<div class="match-group">
      <div class="match-group-head">${fmtDate(g[0].date)} → ${fmtDate(g[g.length - 1].date)} · ${g.length} runs · ${fmtDistance(g[0].distance_m)}</div>
      ${cards}
    </div>`;
  }).join("");
  el.querySelectorAll(".match-card").forEach((c) => {
    c.tabIndex = 0;
    c.setAttribute("role", "button");
    c.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); c.click(); }
    });
    c.addEventListener("click", () => {
      switchView("activities");
      selectActivity(c.dataset.id);
    });
  });
}

/* -------------------------- Statistics ---------------------------- */

async function loadMonthly() {
  const res = await fetch("/api/monthly");
  const data = await res.json();
  renderMonthly(data.months || []);
}

function renderMonthly(months) {
  const chart = $("#monthly-chart");
  const table = $("#monthly-table");
  if (!months.length) {
    chart.innerHTML = '<p class="empty-note">No monthly data.</p>';
    table.innerHTML = "";
    return;
  }
  const maxDist = Math.max(...months.map((m) => m.distance_m));
  chart.innerHTML = months.map((m) => {
    const short = new Date(parseInt(m.month.slice(0, 4), 10), parseInt(m.month.slice(5, 7), 10) - 1, 1)
      .toLocaleDateString("en-US", { month: "short" });
    return `
    <div class="month-col" title="${esc(fmtMonth(m.month))}: ${fmtDistance(m.distance_m)}">
      <span class="month-value">${(m.distance_m / 1000).toFixed(0)} km</span>
      <div class="month-bar ${m === months[months.length - 1] ? "" : "prev"}" style="height:${(m.distance_m / maxDist) * 100}%"></div>
      <span class="month-label">${esc(short)}</span>
    </div>`;
  }).join("");

  const rows = months.slice().reverse().map((m) => {
    let delta = "";
    if (m.delta_distance_m != null) {
      const cls = m.delta_distance_m >= 0 ? "delta-up" : "delta-down";
      const arrow = m.delta_distance_m >= 0 ? "▲" : "▼";
      delta = `<span class="${cls}">${arrow} ${fmtDistance(Math.abs(m.delta_distance_m))}</span>`;
    }
    return `<tr>
      <td>${esc(fmtMonth(m.month))}</td>
      <td class="num">${m.activities}</td>
      <td class="num">${fmtDistance(m.distance_m)}</td>
      <td class="num">${delta}</td>
      <td class="num">${fmtDuration(m.moving_time_s)}</td>
      <td class="num">${fmtPace(m.avg_pace_s_per_km)}</td>
      <td class="num">${m.elevation_gain_m} m</td>
    </tr>`;
  }).join("");

  table.innerHTML = `
    <table class="data" aria-label="Monthly statistics">
      <thead><tr><th scope="col">Month</th><th scope="col" class="num">Runs</th><th scope="col" class="num">Distance</th><th scope="col" class="num">Δ vs prev.</th><th scope="col" class="num">Time</th><th scope="col" class="num">Pace</th><th scope="col" class="num">Elev. gain</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

/* ---------------------------- Goals ------------------------------- */

function goalTargetUnit(metric) {
  return { distance: "km", time: "minutes", elevation: "m" }[metric] || "";
}

function goalToApi(metric, value) {
  if (metric === "distance") return value * 1000;   // km -> m
  if (metric === "time") return value * 60;          // min -> s
  return value;                                       // m
}

function fmtGoalValue(metric, canonical) {
  if (metric === "distance") return fmtDistance(canonical);
  if (metric === "time") return fmtDuration(canonical);
  return Math.round(canonical) + " m";
}

async function loadGoals() {
  const res = await fetch("/api/goals");
  const data = await res.json();
  renderGoals(data.goals || []);
}

function renderGoals(goals) {
  const el = $("#goals-list");
  if (!goals.length) {
    el.innerHTML = '<p class="empty-note">No goal defined yet. Add one on the left.</p>';
    return;
  }
  el.innerHTML = goals.map((g) => {
    const p = g.progress;
    const pct = Math.min(100, p.percent);
    return `
      <div class="goal-card">
        <div class="goal-card-head">
          <span class="goal-card-title">${esc(METRIC_LABELS[g.metric])} — ${esc(PERIOD_LABELS[g.period])}</span>
          <span class="badge running">${Math.round(pct)}%</span>
          <button class="btn ghost small goal-delete" data-id="${g.id}">✕</button>
        </div>
        <div class="goal-progress-track"><div class="goal-progress-fill" style="width:${pct}%"></div></div>
        <div class="goal-progress-text">
          <span>${fmtGoalValue(g.metric, p.current)}</span>
          <span>out of ${fmtGoalValue(g.metric, g.target)}</span>
        </div>
      </div>`;
  }).join("");
  el.querySelectorAll(".goal-delete").forEach((b) => b.addEventListener("click", async () => {
    await fetch(`/api/goals/${b.dataset.id}`, { method: "DELETE" });
    loadGoals();
  }));
}

function updateGoalLabel() {
  const metric = $("#goal-metric").value;
  $("#goal-target-label").firstChild.textContent = "Target (" + goalTargetUnit(metric) + ") ";
}

async function addGoal(e) {
  e.preventDefault();
  const period = $("#goal-period").value;
  const metric = $("#goal-metric").value;
  const raw = parseFloat($("#goal-target").value);
  if (!raw || raw <= 0) return;
  const target = goalToApi(metric, raw);
  await fetch("/api/goals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ period, metric, target }),
  });
  $("#goal-target").value = "";
  loadGoals();
}

/* --------------------------- Coaching ----------------------------- */

// Load-change bands. They describe the direction of the change, not a risk.
const ACWR_BAND_META = {
  ramping_down: { label: "Ramping down", color: "#3b82f6", textColor: "var(--accent-blue)" },
  steady: { label: "Steady", color: "#10b981", textColor: "var(--success)" },
  ramping_up: { label: "Ramping up", color: "#f59e0b", textColor: "var(--warning)" },
  sharp_increase: { label: "Sharp increase", color: "#ef4444", textColor: "var(--danger)" },
  after_gap: { label: "After a break", color: "#cbd5e1", textColor: "var(--text-subtle)" },
  no_data: { label: "No data", color: "#cbd5e1", textColor: "var(--text-subtle)" },
};

const WORKOUT_TYPE_META = {
  recovery: { label: "Recovery", icon: "🧘" },
  easy: { label: "Easy", icon: "🟢" },
  long_run: { label: "Long run", icon: "🛣️" },
  tempo: { label: "Tempo", icon: "🟡" },
  intervals: { label: "Intervals", icon: "🔴" },
};

async function loadCoaching() {
  renderCoachingTab();
}

function renderCoachingTab() {
  // Keep the tab buttons in sync when the tab is set programmatically
  // (e.g. from a home-page KPI card).
  document.querySelectorAll("#coaching-tabs .tab-btn").forEach((b) => {
    const active = b.dataset.ctab === state.coachingTab;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
    b.setAttribute("tabindex", active ? "0" : "-1");
  });
  const body = $("#coaching-body");
  const tab = state.coachingTab;
  if (tab === "fitness") { body.innerHTML = '<p class="empty-note">Loading…</p>'; loadFitness(); }
  else if (tab === "acwr") { body.innerHTML = '<p class="empty-note">Loading…</p>'; loadAcwr(); }
  else if (tab === "intensity") { body.innerHTML = '<p class="empty-note">Loading…</p>'; loadIntensity(); }
  else if (tab === "vo2max") { body.innerHTML = '<p class="empty-note">Loading…</p>'; loadVo2max(); }
  else if (tab === "plans") renderPlans();
  else if (tab === "coach") renderCoach();
}

/* --- SVG helpers --- */

function fmtAxis(v, fmt) {
  if (fmt === "int") return String(Math.round(v));
  if (fmt === "pct") return Math.round(v) + "%";
  return Number(v).toFixed(1);
}

function svgLineChart(el, datasets, opts = {}) {
  const width = Math.max(320, el.clientWidth || 800);
  const height = opts.height || 240;
  const padL = opts.padL || 44;
  const padR = 14, padT = 8, padB = 22;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;
  const n = Math.max(0, ...datasets.map((d) => d.points.length));
  if (n < 1) { el.innerHTML = '<p class="empty-note">Not enough data.</p>'; return; }

  let lo = Infinity, hi = -Infinity;
  for (const d of datasets) for (const p of d.points) {
    if (p.y == null) continue;
    if (p.y < lo) lo = p.y;
    if (p.y > hi) hi = p.y;
  }
  if (lo === Infinity) { lo = 0; hi = 1; }
  if (opts.includeZero !== false) lo = Math.min(0, lo);
  const pad = (hi - lo) * 0.08 || 1;
  const yMin = opts.yMin ?? lo - pad;
  const yMax = opts.yMax ?? hi + pad;

  const yFor = (y) => padT + plotH - ((y - yMin) / (yMax - yMin)) * plotH;
  const xFor = (i) => padL + (n <= 1 ? 0 : (i / (n - 1)) * plotW);

  const ariaLabel = opts.ariaLabel
    || datasets.map((d) => d.name).filter(Boolean).join(", ")
    || "Chart";
  el.setAttribute("role", "img");
  el.setAttribute("aria-label", ariaLabel);

  let svg = `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-hidden="true"><title>${esc(ariaLabel)}</title>`;
  const gridLines = opts.gridLines ?? 4;
  for (let g = 0; g <= gridLines; g++) {
    const yv = yMin + (yMax - yMin) * (g / gridLines);
    const y = yFor(yv);
    svg += `<line x1="${padL}" y1="${y}" x2="${width - padR}" y2="${y}" stroke="#eef0f2"/>`;
    svg += `<text x="${padL - 6}" y="${y + 3}" text-anchor="end" class="axis-label">${fmtAxis(yv, opts.yFormat)}</text>`;
  }
  if (yMin < 0 && yMax > 0) {
    svg += `<line x1="${padL}" y1="${yFor(0)}" x2="${width - padR}" y2="${yFor(0)}" stroke="#cbd5e1"/>`;
  }
  // Horizontal band (e.g. fresh/neutral/fatigued zones)
  if (opts.bands) {
    for (const b of opts.bands) {
      const y1 = yFor(Math.max(yMin, b.from));
      const y2 = yFor(Math.min(yMax, b.to));
      svg += `<rect x="${padL}" y="${Math.min(y1, y2)}" width="${plotW}" height="${Math.abs(y2 - y1)}" fill="${b.color}" opacity="0.07"/>`;
    }
  }
  if (opts.xLabels) {
    const step = Math.max(1, Math.floor(n / 8));
    for (let i = 0; i < n; i += step) {
      svg += `<text x="${xFor(i)}" y="${height - 6}" text-anchor="middle" class="axis-label">${esc(opts.xLabels[i] || "")}</text>`;
    }
  }
  for (const d of datasets) {
    const pts = d.points;
    let path = "";
    for (let i = 0; i < pts.length; i++) {
      if (pts[i].y == null) continue;
      path += (path ? " L" : "M") + xFor(i).toFixed(1) + " " + yFor(pts[i].y).toFixed(1);
    }
    if (!path) continue;
    const stroke = d.color || "#1e90ff";
    if (d.area) {
      const zeroY = yFor(0);
      svg += `<path d="${path} L${xFor(pts.length - 1).toFixed(1)} ${zeroY.toFixed(1)} L${xFor(0).toFixed(1)} ${zeroY.toFixed(1)} Z" fill="${stroke}" opacity="0.10"/>`;
    }
    svg += `<path d="${path}" fill="none" stroke="${stroke}" stroke-width="${d.width || 2}" ${d.dashed ? 'stroke-dasharray="5,4"' : ""} stroke-linejoin="round"/>`;
    if (d.dots && pts.length <= 120) {
      for (let i = 0; i < pts.length; i++) {
        if (pts[i].y == null) continue;
        svg += `<circle cx="${xFor(i).toFixed(1)}" cy="${yFor(pts[i].y).toFixed(1)}" r="2.5" fill="${stroke}"/>`;
      }
    }
  }
  svg += "</svg>";
  el.innerHTML = svg;
}

function renderLoadBars(el, days) {
  const width = Math.max(320, el.clientWidth || 800);
  const height = 120;
  const padL = 44, padR = 14, padT = 8, padB = 20;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;
  const n = days.length;
  if (n < 1) { el.innerHTML = '<p class="empty-note">No activity data.</p>'; return; }
  const maxLoad = Math.max(1, ...days.map((d) => d.load));
  const bw = plotW / n;
  el.setAttribute("role", "img");
  el.setAttribute("aria-label", "Daily training load");
  let svg = `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-hidden="true"><title>Daily training load</title>`;
  days.forEach((d, i) => {
    const h = (d.load / maxLoad) * plotH;
    const x = padL + i * bw;
    const y = padT + plotH - h;
    const source = d.source || (d.has_rpe ? "rpe" : "pace");
    const color = source === "rpe" ? "#f59e0b" : source === "mixed" ? "#a855f7" : "#1e90ff";
    svg += `<rect x="${x + 1}" y="${y}" width="${Math.max(1, bw - 2)}" height="${Math.max(0, h)}" fill="${color}" opacity="0.75"><title>${d.date} — ${d.load} (${source === "mixed" ? "RPE + pace" : source})</title></rect>`;
  });
  const step = Math.max(1, Math.floor(n / 8));
  for (let i = 0; i < n; i += step) {
    svg += `<text x="${padL + i * bw + bw / 2}" y="${height - 6}" text-anchor="middle" class="axis-label">${esc(shortDate(days[i].date))}</text>`;
  }
  svg += `<text x="${padL - 6}" y="${padT + 8}" text-anchor="end" class="axis-label">${Math.round(maxLoad)}</text>`;
  svg += `<text x="${padL - 6}" y="${padT + plotH}" text-anchor="end" class="axis-label">0</text>`;
  svg += "</svg>";
  el.innerHTML = svg;
}

function shortDate(iso) {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(iso);
  return d.toLocaleDateString("en-US", { day: "numeric", month: "short" });
}

/* --- Fitness (load + CTL/ATL/TSB) --- */

async function loadFitness() {
  const [load, fitness] = await Promise.all([
    fetch("/api/coaching/load").then((r) => r.json()),
    fetch("/api/coaching/fitness").then((r) => r.json()),
  ]);
  renderFitness(load, fitness);
}

function renderFitness(load, fitness) {
  const body = $("#coaching-body");
  const days = fitness.days || [];
  const cur = fitness.current;
  const html = [];
  html.push(`
    <div class="panel coaching-panel">
      <h3>Load &amp; fitness</h3>
      <p class="panel-sub">Fitness (CTL), fatigue (ATL) and form (TSB) follow the Coggan Performance Management Chart (Banister impulse-response model). Load comes from pace zones, or from your RPE × duration when you log an effort.</p>
      ${cur ? `
      <div class="metric-cards">
        <div class="metric-card"><span class="metric-value">${cur.ctl}</span><span class="metric-label">Chronic load (CTL)</span></div>
        <div class="metric-card"><span class="metric-value">${cur.atl}</span><span class="metric-label">Acute load (ATL)</span></div>
        <div class="metric-card"><span class="metric-value form-${cur.form}">${cur.tsb >= 0 ? "+" : ""}${cur.tsb}<small>${cur.tsb_pct != null && !cur.calibrating ? ` · ${cur.tsb_pct > 0 ? "+" : ""}${cur.tsb_pct}%` : ""}</small></span><span class="metric-label">Form (TSB)${cur.calibrating ? " — calibrating" : ""}</span></div>
      </div>` : ""}
      <h4 class="chart-title">Daily training load</h4>
      <div class="chart" id="load-bars"></div>
      <p class="muted legend-line"><span class="dot" style="background:#1e90ff"></span> pace-based load · <span class="dot" style="background:#f59e0b"></span> RPE-based load</p>
      <h4 class="chart-title">Fitness vs fatigue</h4>
      <div class="chart" id="fitness-chart"></div>
      <p class="muted legend-line"><span class="dot" style="background:#1e90ff"></span> Fitness (CTL) · <span class="dot" style="background:#ef4444"></span> Fatigue (ATL)</p>
      <h4 class="chart-title">Form (fresh / neutral / fatigued)</h4>
      <div class="chart" id="form-chart"></div>
      <p class="muted legend-line"><span class="dot" style="background:#10b981"></span> Form (TSB) — above +5 fresh, below −5 fatigued</p>
      <details class="explain"><summary>How is this computed?</summary>
        <p>Each day, Training Load (TL) = sum of your runs' load. Then:</p>
        <p><code>CTL = CTL + (TL − CTL) / 42</code> — long-term fitness (42-day constant).</p>
        <p><code>ATL = ATL + (TL − ATL) / 7</code> — short-term fatigue (7-day constant).</p>
        <p><code>Form = CTL − ATL</code>. Positive = fresh, negative = fatigued. Aim to be fresh (positive form) before key workouts or races.</p>
      </details>
    </div>`);

  body.innerHTML = html.join("");
  if (days.length) {
    renderLoadBars(document.getElementById("load-bars"), load.days || days);
    svgLineChart(document.getElementById("fitness-chart"), [
      { name: "CTL", color: "#1e90ff", points: days.map((d) => ({ y: d.ctl })) },
      { name: "ATL", color: "#ef4444", points: days.map((d) => ({ y: d.atl })) },
    ], {
      height: 220, includeZero: true, yFormat: "int",
      xLabels: days.map((d) => shortDate(d.date)),
    });
    svgLineChart(document.getElementById("form-chart"), [
      { name: "TSB", color: "#10b981", points: days.map((d) => ({ y: d.tsb })) },
    ], {
      height: 200, includeZero: true, yFormat: "int",
      xLabels: days.map((d) => shortDate(d.date)),
      bands: [{ from: 5, to: 1000, color: "#10b981" }, { from: -1000, to: -5, color: "#ef4444" }],
    });
  }
}

/* --- Load change (acute:chronic ratio) --- */

async function loadAcwr() {
  const res = await fetch("/api/coaching/acwr");
  renderAcwr(await res.json());
}

function renderAcwr(data) {
  const body = $("#coaching-body");
  const days = data.days || [];
  const cur = data.current;
  const band = cur ? ACWR_BAND_META[cur.band] || ACWR_BAND_META.no_data : ACWR_BAND_META.no_data;

  const html = [];
  html.push(`
    <div class="panel coaching-panel">
      <h3>Load change</h3>
      <p class="panel-sub">Your last 7 days of load compared with the 28 days before them. It describes how fast your training is changing — it is not a risk score and cannot predict an injury.</p>
      ${cur ? `
      <div class="acwr-gauge">
        <div class="acwr-value" style="color:${band.textColor}">${cur.acwr != null ? cur.acwr.toFixed(2) : "—"}</div>
        <div class="acwr-band-label" style="color:${band.textColor}">${band.label}</div>
        <div class="acwr-scale">
          <div class="acwr-seg" style="flex:0.8;background:#3b82f6" title="below 0.8: ramping down"></div>
          <div class="acwr-seg" style="flex:0.5;background:#10b981" title="0.8–1.3: steady"></div>
          <div class="acwr-seg" style="flex:0.2;background:#f59e0b" title="1.3–1.5: ramping up"></div>
          <div class="acwr-seg" style="flex:0.7;background:#ef4444" title="1.5 and above: sharp increase"></div>
          <div class="acwr-marker" style="left:${acwrMarkerLeft(cur.acwr)}%"></div>
        </div>
        <div class="acwr-scale-labels"><span>&lt; 0.8 ramping down</span><span>0.8–1.3 steady</span><span>1.3–1.5 ramping up</span><span>≥ 1.5 sharp increase</span></div>
      </div>
      <p class="muted" style="margin-top:10px">Acute (7d): <b>${cur.acute}</b> · Chronic (28d): <b>${cur.chronic}</b></p>` : ""}
      <h4 class="chart-title">ACWR over time</h4>
      <div class="chart" id="acwr-chart"></div>
      <details class="explain"><summary>How is this computed?</summary>
        <p><code>Recent = average load over the last 7 days</code></p>
        <p><code>Baseline = average load over the 28 days before that (the last week is excluded)</code></p>
        <p><code>Ratio = Recent / Baseline</code></p>
        <p>The week is excluded from the baseline on purpose: including it makes the denominator partly the numerator, which is the coupling criticised by Lolli et al. (2019). The ratio is hidden after more than a week without training, because a break is not a decrease in fitness.</p>
        <p><b>Not a risk score.</b> The injury-prediction claim attached to this metric does not replicate in running cohorts (Impellizzeri et al. 2020). Read it as "my load went up 40%", then decide.</p>
        <p>See <code>docs/research/04-acwr.md</code>.</p>
      </details>
    </div>`);
  body.innerHTML = html.join("");

  if (days.length) {
    const pts = days.map((d) => ({ y: d.acwr }));
    svgLineChart(document.getElementById("acwr-chart"), [
      { color: "#6366f1", points: pts, width: 2 },
    ], {
      height: 240, includeZero: false, yFormat: "num", yMin: 0,
      xLabels: days.map((d) => shortDate(d.date)),
      bands: [
        { from: 0.8, to: 1.3, color: "#10b981" },
        { from: 1.3, to: 1.5, color: "#f59e0b" },
        { from: 1.5, to: 100, color: "#ef4444" },
      ],
    });
  }
}

function acwrMarkerLeft(acwr) {
  if (acwr == null) return 0;
  // scale 0 -> 2.2 maps to 0 -> 100
  return Math.max(0, Math.min(100, (acwr / 2.2) * 100));
}

/* --- Intensity distribution (80/20) --- */

async function loadIntensity() {
  const res = await fetch("/api/coaching/intensity");
  renderIntensity(await res.json());
}

function intensityBar(label, group, targetPct) {
  const pct = group.time_pct;
  const target = Math.round(targetPct * 100);
  return `
    <div class="intensity-row">
      <div class="intensity-label">${label}</div>
      <div class="intensity-track">
        <div class="intensity-fill" style="width:${pct}%;background:${group.color}"></div>
        <div class="intensity-target" style="left:${target}%"></div>
      </div>
      <div class="intensity-val">${pct}% <span class="muted">(target ~${target}%)</span></div>
    </div>`;
}

function renderIntensity(data) {
  const body = $("#coaching-body");
  const rolling = data.rolling;
  const target = data.target;
  const g = rolling.groups;
  const html = `
    <div class="panel coaching-panel">
      <h3>Intensity distribution (80/20)</h3>
      <p class="panel-sub">Polarized training (Seiler 2010): most of your time should be easy (Z1+Z2), a little hard (Z4–Z6), and very little "grey zone" moderate (Z3). Below is the last ${rolling.window_days} days of training.</p>
      <div class="intensity-chart">
        ${intensityBar("Easy (Z1–Z2)", g.easy, target.easy)}
        ${intensityBar("Moderate (Z3)", g.moderate, target.moderate)}
        ${intensityBar("Hard (Z4–Z6)", g.hard, target.hard)}
      </div>
      <p class="muted" style="margin-top:14px">Total time: <b>${fmtDuration(rolling.total_time_s)}</b> · Total distance: <b>${fmtDistance(rolling.total_distance_m)}</b> — the dashed marker shows the polarized ideal.</p>
      <details class="explain"><summary>How is this computed?</summary>
        <p>Each moving second is assigned to a pace zone (Z1 recovery → Z6 sprint). Zones are grouped into <b>Easy</b> (Z1+Z2), <b>Moderate</b> (Z3) and <b>Hard</b> (Z4–Z6). The % is the share of moving time spent in each group.</p>
        <p>The 80/20 ideal: ~80% easy, and the remaining ~20% should favour hard work over moderate. Too much moderate ("grey zone") is the classic endurance-training mistake.</p>
      </details>
    </div>`;
  body.innerHTML = html;
}

/* --- VO2max & race prediction --- */

async function loadVo2max() {
  const res = await fetch("/api/coaching/vo2max");
  renderVo2max(await res.json());
}

function renderVo2max(data) {
  const body = $("#coaching-body");
  const seed = data.seed;
  const preds = data.predictions || [];
  let predRows = preds.map((p) => {
    const actual = p.actual_time_s != null
      ? `${fmtDuration(p.actual_time_s)} <span class="muted">(${fmtDate(p.actual_date)})</span>`
      : '<span class="muted">no race logged</span>';
    return `<tr>
      <td>${esc(p.label)}</td>
      <td class="num">${fmtDuration(p.predicted_time_s)}</td>
      <td class="num">${fmtPace(p.predicted_pace_s_per_km)}</td>
      <td class="num">${actual}</td>
    </tr>`;
  }).join("");

  const html = `
    <div class="panel coaching-panel">
      <h3>VO2max &amp; race predictor</h3>
      <p class="panel-sub">"Effective VO2max" is estimated from your best efforts using the Daniels VDOT model. Race times are predicted with the Riegel formula <code>T2 = T1 × (D2/D1)^1.06</code>.</p>
      <div class="vo2max-head">
        <div class="metric-card"><span class="metric-value">${data.effective_vo2max != null ? data.effective_vo2max.toFixed(1) : "—"}</span><span class="metric-label">Effective VO2max (ml/kg/min)</span></div>
        ${seed ? `<div class="metric-card"><span class="metric-value">${fmtDuration(seed.time_s)}</span><span class="metric-label">Best effort ${esc(seed.label)} (${fmtDate(seed.date)})</span></div>` : ""}
      </div>
      <table class="data" aria-label="Race time predictions" style="margin-top:12px">
        <thead><tr><th scope="col">Distance</th><th scope="col" class="num">Predicted</th><th scope="col" class="num">Predicted pace</th><th scope="col" class="num">Your best</th></tr></thead>
        <tbody>${predRows}</tbody>
      </table>
      <details class="explain"><summary>How is this computed?</summary>
        <p><b>VO2max (Daniels VDOT)</b>: from a performance (distance D, time T), velocity v = D/T and time t = T. Then:</p>
        <p><code>%VO2max = 0.8 + 0.1894·e^(−0.012778·t) + 0.2990·e^(−0.19326·t)</code></p>
        <p><code>VO2 = −4.60 + 0.1823·v + 0.000104·v²</code> and <code>VDOT = VO2 / %VO2max</code>.</p>
        <p>We take the highest VDOT across your best efforts. Predictions use the Riegel exponent 1.06. Short-distance efforts predict long races less reliably — use them as a rough guide.</p>
      </details>
    </div>`;
  body.innerHTML = html;
}

/* --- Plans --- */

function renderPlans() {
  const body = $("#coaching-body");
  body.innerHTML = `
    <div class="coaching-grid">
      <div class="panel">
        <h3>New training plan</h3>
        <p class="panel-sub">Build a periodized plan: 80/20 distribution, ~+10% weekly volume, deload every 4th week.</p>
        <form id="plan-form" class="goal-form">
          <label>Plan name
            <input type="text" id="plan-name" placeholder="e.g. Spring marathon" />
          </label>
          <label>Goal type
            <select id="plan-mode">
              <option value="race">Race (distance + date)</option>
              <option value="km">Weekly distance target</option>
              <option value="time">Weekly time target</option>
            </select>
          </label>
          <div id="plan-race-fields">
            <label>Race distance
              <select id="plan-distance">
                <option value="5000">5 km</option>
                <option value="10000">10 km</option>
                <option value="21097">Half marathon</option>
                <option value="42195">Marathon</option>
              </select>
            </label>
            <label>Race date
              <input type="date" id="plan-date" />
            </label>
          </div>
          <div id="plan-volume-fields" class="hidden">
            <label id="plan-volume-label">Weekly volume (km)
              <input type="number" id="plan-volume" step="1" min="5" placeholder="e.g. 40" />
            </label>
          </div>
          <label>Sessions per week
            <select id="plan-sessions">
              <option value="3">3</option>
              <option value="4" selected>4</option>
              <option value="5">5</option>
              <option value="6">6</option>
            </select>
          </label>
          <button type="submit" class="btn">Generate plan</button>
        </form>
      </div>
      <div class="panel">
        <h3>Saved plans</h3>
        <div id="plans-list"></div>
      </div>
    </div>
    <div id="plan-result"></div>`;
  loadPlansList();
  updatePlanMode();
  $("#plan-form").addEventListener("submit", submitPlan);
  $("#plan-mode").addEventListener("change", updatePlanMode);
}

function updatePlanMode() {
  const mode = $("#plan-mode").value;
  $("#plan-race-fields").classList.toggle("hidden", mode !== "race");
  $("#plan-volume-fields").classList.toggle("hidden", mode === "race");
  const volLabel = $("#plan-volume-label");
  if (mode === "km") { volLabel.innerHTML = "Weekly volume (km) <input type=\"number\" id=\"plan-volume\" step=\"1\" min=\"5\" placeholder=\"e.g. 40\" />"; }
  else if (mode === "time") { volLabel.innerHTML = "Weekly volume (minutes) <input type=\"number\" id=\"plan-volume\" step=\"15\" min=\"30\" placeholder=\"e.g. 240\" />"; }
}

async function submitPlan(e) {
  e.preventDefault();
  const name = $("#plan-name").value.trim();
  const mode = $("#plan-mode").value;
  const sessions = parseInt($("#plan-sessions").value, 10);
  const payload = { name, sessions_per_week: sessions };
  if (mode === "race") {
    payload.goal_distance_m = parseInt($("#plan-distance").value, 10);
    const d = $("#plan-date").value;
    if (!d) { alert("Please choose a race date."); return; }
    payload.goal_date = d;
  } else if (mode === "km") {
    const km = parseFloat($("#plan-volume").value);
    if (!km || km <= 0) { alert("Please enter a weekly volume."); return; }
    payload.weekly_target_m = km * 1000;
  } else {
    const min = parseFloat($("#plan-volume").value);
    if (!min || min <= 0) { alert("Please enter a weekly volume."); return; }
    payload.weekly_target_s = min * 60;
  }
  const res = await fetch("/api/coaching/plans", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) { console.error("plan failed"); return; }
  const plan = await res.json();
  renderPlanDetail(plan);
  loadPlansList();
}

function renderPlanDetail(plan) {
  const el = $("#plan-result");
  const weeks = plan.weeks_plan || [];
  const weekCards = weeks.map((w) => {
    const sessions = w.sessions.map((s) => {
      const meta = WORKOUT_TYPE_META[s.type] || { label: s.type, icon: "•" };
      return `<div class="plan-session">
        <span class="plan-session-type">${meta.icon} ${meta.label}</span>
        <span class="plan-session-meta">${s.duration_min} min · ${s.distance_km} km · ${esc(s.zones)}</span>
      </div>`;
    }).join("");
    return `<div class="plan-week ${w.type}">
      <div class="plan-week-head"><b>Week ${w.week}</b> <span class="badge ${w.type}">${w.type}</span> <span class="muted">${w.volume_min} min / week</span></div>
      ${sessions}
    </div>`;
  }).join("");

  el.innerHTML = `
    <div class="panel">
      <h3>${esc(plan.name)}</h3>
      <p class="panel-sub">${esc(plan.goal_description)} · ${plan.weeks} weeks · peak ${plan.peak_weekly_min} min/week (${(plan.peak_weekly_min / 60).toFixed(1)} h)</p>
      <p class="panel-sub">Strength, mobility and rest sessions are scheduled automatically — see the <b>Planner</b> tab to view, complete or edit them.</p>
      <div class="plan-weeks">${weekCards}</div>
    </div>`;
}

async function loadPlansList() {
  const res = await fetch("/api/coaching/plans");
  const data = await res.json();
  const el = $("#plans-list");
  const plans = data.plans || [];
  if (!plans.length) {
    el.innerHTML = '<p class="empty-note">No saved plan yet.</p>';
    return;
  }
  el.innerHTML = plans.map((p) => `
    <div class="plan-row" data-id="${p.id}">
      <div class="plan-row-info">
        <b>${esc(p.name)}</b>
        <span class="muted">${esc(p.goal_description)} · ${p.weeks} weeks</span>
      </div>
      <button class="btn ghost small plan-open">Open</button>
      <button class="btn ghost small plan-delete">✕</button>
    </div>`).join("");
  el.querySelectorAll(".plan-open").forEach((b) => b.addEventListener("click", async () => {
    const r = await fetch(`/api/coaching/plans/${b.closest(".plan-row").dataset.id}`);
    const plan = await r.json();
    renderPlanDetail(plan.data);
  }));
  el.querySelectorAll(".plan-delete").forEach((b) => b.addEventListener("click", async () => {
    await fetch(`/api/coaching/plans/${b.closest(".plan-row").dataset.id}`, { method: "DELETE" });
    loadPlansList();
  }));
}

/* --- Coach (insight cards + optional LLM chat) --- */

const COACH_SUGGESTIONS = [
  "What should I do this week?",
  "Why is my ACWR where it is?",
  "How is my 80/20 balance?",
  "Am I ready for a 10k?",
  "Review my last 4 weeks.",
];

/* --------------------------- Coach chat --------------------------- */

function renderChatPanel(hostId, prefix) {
  const host = document.getElementById(hostId);
  if (!host) return;
  host.innerHTML = `
    <div class="coach-status" id="${prefix}-status">Checking…</div>
    <div class="coach-model-row">
      <label class="coach-model-label" for="${prefix}-model">Model</label>
      <select id="${prefix}-model" class="coach-model"></select>
    </div>
    <div class="coach-messages" id="${prefix}-messages" role="log" aria-live="polite" aria-relevant="additions"></div>
    <div class="coach-suggestions" id="${prefix}-suggestions"></div>
    <form id="${prefix}-form" class="coach-input-row">
      <label class="sr-only" for="${prefix}-input">Message to the coach</label>
      <textarea id="${prefix}-input" rows="2" placeholder="Ask about your training, load, race readiness…"></textarea>
      <div class="coach-actions">
        <button class="btn" type="submit" id="${prefix}-send">Send</button>
        <button class="btn ghost" type="button" id="${prefix}-review">Weekly review</button>
        <button class="btn ghost" type="button" id="${prefix}-clear">Clear</button>
      </div>
    </form>`;
  renderChatHistory(prefix);
  renderChatSuggestions(prefix);
  const form = document.getElementById(prefix + "-form");
  if (form) form.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById(prefix + "-input");
    sendChatFrom(prefix, input ? input.value : "");
  });
  const review = document.getElementById(prefix + "-review");
  if (review) review.addEventListener("click", () => chatReviewFrom(prefix));
  const clear = document.getElementById(prefix + "-clear");
  if (clear) clear.addEventListener("click", () => {
    state.chatHistory = [];
    renderChatHistory(prefix);
  });
  loadChatStatus(prefix);
}

function renderChatSuggestions(prefix) {
  const el = document.getElementById(prefix + "-suggestions");
  if (!el) return;
  el.innerHTML = COACH_SUGGESTIONS.map((s) =>
    `<button type="button" class="coach-chip">${esc(s)}</button>`).join("");
  el.querySelectorAll(".coach-chip").forEach((b) =>
    b.addEventListener("click", () => sendChatFrom(prefix, b.textContent)));
}

function renderChatHistory(prefix) {
  const wrap = document.getElementById(prefix + "-messages");
  if (!wrap) return;
  wrap.innerHTML = "";
  for (const m of state.chatHistory) addChatBubble(prefix, m.role, m.content);
}

function addChatBubble(prefix, role, text) {
  const wrap = document.getElementById(prefix + "-messages");
  if (!wrap) return null;
  const el = document.createElement("div");
  el.className = "coach-msg " + role;
  el.innerHTML = renderCoachText(text);
  wrap.appendChild(el);
  wrap.scrollTop = wrap.scrollHeight;
  return el;
}

function addChatThinking(prefix) {
  return addChatBubble(prefix, "assistant thinking", "Coach is thinking…");
}

function renderCoachText(text) {
  const safe = esc(text || "");
  const lines = safe.split(/\r?\n/);
  let html = "";
  let inList = false;
  const bold = (s) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  for (const raw of lines) {
    const line = raw.trimEnd();
    const item = /^\s*[-*•]\s+(.*)$/.exec(line);
    if (item) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${bold(item[1])}</li>`;
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      if (line.trim() === "") html += "<br>";
      else html += `<p>${bold(line)}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html || "<p></p>";
}

async function loadChatStatus(prefix) {
  const el = document.getElementById(prefix + "-status");
  if (!el) return;
  try {
    const status = await fetch("/api/coaching/chat/status").then((r) => r.json());
    state.coachConfigured = !!status.configured;
    const select = document.getElementById(prefix + "-model");
    const chatModels = (status.models || []).filter((m) => (m.roles || []).includes("chat"));
    if (select) {
      select.innerHTML = chatModels.map((m) =>
        `<option value="${esc(m.id)}"${m.configured ? "" : " disabled"}>${esc(m.name)}${m.configured ? "" : " (missing key)"}</option>`
      ).join("");
      const stored = localStorage.getItem("coachModel");
      const preferred = chatModels.find((m) => m.id === stored && m.configured)
        || chatModels.find((m) => m.id === status.default && m.configured)
        || chatModels.find((m) => m.configured);
      if (preferred) select.value = preferred.id;
      select.addEventListener("change", () => {
        localStorage.setItem("coachModel", select.value);
        updateChatStatusLine(prefix, status);
      });
    }
    updateChatStatusLine(prefix, status);
    const disabled = !status.configured;
    [`#${prefix}-input`, `#${prefix}-send`, `#${prefix}-review`].forEach((sel) => {
      const node = document.querySelector(sel);
      if (node) node.disabled = disabled;
    });
  } catch (err) {
    console.error(err);
    el.textContent = "Could not check coach status.";
  }
}

function updateChatStatusLine(prefix, status) {
  const el = document.getElementById(prefix + "-status");
  const select = document.getElementById(prefix + "-model");
  if (!el) return;
  const chosen = select ? select.value : "";
  const model = (status.models || []).find((m) => m.id === chosen);
  if (status.configured) {
    el.innerHTML = `<span class="coach-ok">● Coach online</span>${model ? ` · ${esc(model.name)}` : ""}`;
    el.classList.remove("warn");
  } else {
    el.innerHTML = `<span class="coach-off">● Coach not configured</span> — add the model key in <code>.env</code> (see <code>models.json</code>) and restart. The insight cards still work offline.`;
    el.classList.add("warn");
  }
}

async function sendChatFrom(prefix, text) {
  text = (text || "").trim();
  if (!text) return;
  if (!state.coachConfigured) {
    addChatBubble(prefix, "assistant", "⚠️ The coach is not configured yet.");
    return;
  }
  const history = state.chatHistory.slice();
  state.chatHistory.push({ role: "user", content: text });
  addChatBubble(prefix, "user", text);
  const input = document.getElementById(prefix + "-input");
  if (input) input.value = "";
  const thinking = addChatThinking(prefix);
  const model = document.getElementById(prefix + "-model")?.value || null;
  try {
    const res = await fetch("/api/coaching/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history, model }),
    });
    const data = await res.json().catch(() => ({}));
    if (thinking) thinking.remove();
    if (!res.ok) {
      addChatBubble(prefix, "assistant", "⚠️ " + (data.detail || "The coach is unavailable right now."));
      return;
    }
    addChatBubble(prefix, "assistant", data.reply);
    state.chatHistory.push({ role: "assistant", content: data.reply });
  } catch (err) {
    if (thinking) thinking.remove();
    addChatBubble(prefix, "assistant", "⚠️ Network error while contacting the coach.");
  }
}

async function chatReviewFrom(prefix) {
  if (!state.coachConfigured) {
    addChatBubble(prefix, "assistant", "⚠️ The coach is not configured yet.");
    return;
  }
  const prompt = "Give me a weekly review.";
  addChatBubble(prefix, "user", prompt);
  const thinking = addChatThinking(prefix);
  const model = document.getElementById(prefix + "-model")?.value || null;
  try {
    const res = await fetch("/api/coaching/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    });
    const data = await res.json().catch(() => ({}));
    if (thinking) thinking.remove();
    if (!res.ok) {
      addChatBubble(prefix, "assistant", "⚠️ " + (data.detail || "The coach is unavailable right now."));
      return;
    }
    addChatBubble(prefix, "assistant", data.review);
    state.chatHistory.push({ role: "user", content: prompt });
    state.chatHistory.push({ role: "assistant", content: data.review });
  } catch (err) {
    if (thinking) thinking.remove();
    addChatBubble(prefix, "assistant", "⚠️ Network error while contacting the coach.");
  }
}

function renderCoach() {
  const body = $("#coaching-body");
  body.innerHTML = `
    <div class="coach-grid">
      <div class="panel coach-insights-panel">
        <h3>What your data says</h3>
        <p class="panel-sub">Automatic, rule-based observations — always available, even offline.</p>
        <div id="coach-insights"><p class="empty-note">Loading…</p></div>
      </div>
      <div class="panel coach-chat-panel">
        <h3>Ask your coach</h3>
        <div id="coach-chat"></div>
      </div>
    </div>`;
  renderChatPanel("coach-chat", "coach");
  loadCoachInsights();
}

async function loadCoachInsights() {
  const el = $("#coach-insights");
  if (!el) return;
  try {
    const data = await fetch("/api/coaching/insights").then((r) => r.json());
    const insights = data.insights || [];
    if (!insights.length) {
      el.innerHTML = '<p class="empty-note">Not enough training data yet.</p>';
      return;
    }
    el.innerHTML = insights.map((i) => `
      <div class="insight-card level-${esc(i.level)}">
        <div class="insight-title">${esc(i.title)}</div>
        <div class="insight-text">${esc(i.text)}</div>
      </div>`).join("");
  } catch (err) {
    console.error(err);
    el.innerHTML = '<p class="empty-note">Could not load insights.</p>';
  }
}

/* ----------------------------- Home ------------------------------- */

function goTo(view, ctab) {
  if (ctab) state.coachingTab = ctab;
  switchView(view);
}

function currentWeekIso() {
  const start = weekStartDate(null);
  const days = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    days.push(isoDateLocal(d));
  }
  return days;
}

async function showHome() {
  renderChatPanel("home-chat", "home");
  await Promise.all([loadHomeKpis(), loadHomeSchedule(), loadHomeRaces(), loadHomeStats()]);
}

function kpiCard(label, value, sub, view, ctab) {
  const attrs = `data-goto="${esc(view)}"${ctab ? ` data-ctab="${esc(ctab)}"` : ""}`;
  return `<button type="button" class="kpi-card" ${attrs}>
    <span class="kpi-label">${esc(label)}</span>
    <span class="kpi-value">${esc(value)}</span>
    ${sub ? `<span class="kpi-sub">${esc(sub)}</span>` : ""}
  </button>`;
}

async function loadHomeKpis() {
  const el = $("#home-kpis");
  if (!el) return;
  try {
    const [fit, acwr, inten, vo2, nut, sessions] = await Promise.all([
      fetch("/api/coaching/fitness").then((r) => r.json()),
      fetch("/api/coaching/acwr").then((r) => r.json()),
      fetch("/api/coaching/intensity").then((r) => r.json()),
      fetch("/api/coaching/vo2max").then((r) => r.json()),
      fetch("/api/nutrition").then((r) => r.json()),
      fetch("/api/sessions").then((r) => r.json()).catch(() => ({ sessions: [] })),
    ]);
    const cur = fit.current || {};
    const a = acwr.current || {};
    const g = (inten.rolling || {}).groups || {};
    const logs = nut.logs || [];
    const steps = logs.filter((n) => n.steps != null);
    const stepsAvg = steps.length
      ? Math.round(steps.reduce((sum, n) => sum + n.steps, 0) / steps.length)
      : null;
    const week = currentWeekIso();
    const supportCount = (sessions.sessions || [])
      .filter((s) => week.includes(s.date) && s.status !== "skipped").length;
    el.innerHTML = [
      kpiCard("Chronic load (CTL)", cur.ctl ?? "—", "what other apps call fitness", "coaching", "fitness"),
      kpiCard("Acute load (ATL)", cur.atl ?? "—", "short-term load", "coaching", "fitness"),
      kpiCard("Form (TSB)", cur.tsb != null ? `${cur.tsb >= 0 ? "+" : ""}${cur.tsb}` : "—", cur.calibrating ? "calibrating" : cur.form || "", "coaching", "fitness"),
      kpiCard("Load change (7d/28d)", a.acwr ?? "—", a.band || "", "coaching", "acwr"),
      kpiCard("Easy share", g.easy ? `${g.easy.time_pct}%` : "—", "80/10/10 target: 80% easy", "coaching", "intensity"),
      kpiCard("VO2max", vo2.effective_vo2max ?? "—", "ml/kg/min", "coaching", "vo2max"),
      kpiCard("Steps (7d avg)", stepsAvg != null ? stepsAvg.toLocaleString() : "—", "add in Fuel", "fuel"),
      kpiCard("Support this week", String(supportCount), "sessions", "planner"),
    ].join("");
  } catch (err) {
    console.error(err);
    el.innerHTML = '<p class="empty-note">Could not load KPIs.</p>';
  }
}

async function loadHomeSchedule() {
  const el = $("#home-schedule");
  if (!el) return;
  try {
    const data = await fetch("/api/sessions").then((r) => r.json()).catch(() => ({ sessions: [] }));
    const week = currentWeekIso();
    const sessions = (data.sessions || []).filter((s) => week.includes(s.date));
    const runs = (state.activities || []).filter((a) =>
      a.start_time && week.includes(isoDateLocal(new Date(a.start_time))));
    const items = [
      ...sessions.map((s) => ({
        date: s.date,
        label: `${SESSION_ICONS[s.kind] || "•"} ${s.title || SESSION_LABELS[s.kind] || s.kind}`,
        meta: `${s.status}${s.duration_min ? ` · ${s.duration_min} min` : ""}`,
      })),
      ...runs.map((a) => ({
        date: isoDateLocal(new Date(a.start_time)),
        label: `🏃 ${fmtDistance(a.stats.distance_m)}`,
        meta: fmtPace(a.stats.avg_pace_s_per_km),
      })),
    ].sort((x, y) => x.date.localeCompare(y.date));
    if (!items.length) {
      el.innerHTML = '<p class="empty-note">Nothing planned this week. Open the schedule to add a session.</p>';
      return;
    }
    el.innerHTML = `<ul class="home-list">${items.slice(0, 6).map((i) => `
      <li><span class="home-list-date">${esc(fmtDay(i.date))}</span>
      <span class="home-list-main">${esc(i.label)}</span>
      <span class="home-list-meta">${esc(i.meta)}</span></li>`).join("")}</ul>`;
  } catch (err) {
    console.error(err);
    el.innerHTML = '<p class="empty-note">Could not load the schedule.</p>';
  }
}

async function loadHomeRaces() {
  const racesEl = $("#home-races");
  const recordsEl = $("#home-records");
  if (!racesEl || !recordsEl) return;
  const recent = (state.activities || []).slice(0, 5);
  racesEl.innerHTML = `<h3>Recent runs</h3>` + (recent.length
    ? `<ul class="home-list">${recent.map((a) => `
      <li><span class="home-list-main">${esc(fmtDistance(a.stats.distance_m))} · ${esc(fmtPace(a.stats.avg_pace_s_per_km))}</span>
      <span class="home-list-meta">${esc(fmtDate(a.start_time))}</span></li>`).join("")}</ul>`
    : '<p class="empty-note">No run yet.</p>');
  try {
    const data = await fetch("/api/best-efforts").then((r) => r.json());
    const efforts = (data.best_efforts || [])
      .filter((e) => ["5 km", "10 km", "Half marathon", "Marathon"].includes(e.label));
    recordsEl.innerHTML = `<h3>Best efforts</h3>` + (efforts.length
      ? `<ul class="home-list">${efforts.map((e) => `
        <li><span class="home-list-main">${esc(e.label)}</span>
        <span class="home-list-meta">${esc(fmtDuration(e.time_s))}</span></li>`).join("")}</ul>`
      : '<p class="empty-note">No record yet.</p>');
  } catch (err) {
    console.error(err);
    recordsEl.innerHTML = '<h3>Best efforts</h3><p class="empty-note">Could not load records.</p>';
  }
}

async function loadHomeStats() {
  const el = $("#home-stats");
  if (!el) return;
  try {
    const [weights, goals] = await Promise.all([
      fetch("/api/weights").then((r) => r.json()).catch(() => ({ weights: [] })),
      fetch("/api/goals").then((r) => r.json()).catch(() => ({ goals: [] })),
    ]);
    const activities = state.activities || [];
    const total = activities.reduce((acc, a) => {
      acc.distance += a.stats.distance_m;
      acc.time += a.stats.moving_time_s;
      return acc;
    }, { distance: 0, time: 0 });
    const weight = weights.current_weight_kg;
    const goal = (goals.goals || [])[0];
    el.innerHTML = `
      <div class="home-stats-grid">
        <div class="home-stat"><span class="home-stat-value">${activities.length}</span><span class="home-stat-label">runs</span></div>
        <div class="home-stat"><span class="home-stat-value">${esc(fmtDistance(total.distance))}</span><span class="home-stat-label">distance</span></div>
        <div class="home-stat"><span class="home-stat-value">${esc(fmtDuration(total.time))}</span><span class="home-stat-label">time</span></div>
        <div class="home-stat"><span class="home-stat-value">${weight != null ? esc(`${weight} kg`) : "—"}</span><span class="home-stat-label">weight</span></div>
      </div>
      ${goal ? `<p class="panel-sub">Goal: ${esc(goal.metric)} — ${esc(String(goal.progress.percent))}% of target.</p>` : ""}`;
  } catch (err) {
    console.error(err);
    el.innerHTML = '<p class="empty-note">Could not load stats.</p>';
  }
}

/* --------------------- Athlete onboarding ------------------------- */

function showOnboarding() {
  $("#onboarding").classList.remove("hidden");
  document.body.classList.add("onboarding-open");
  setTimeout(() => { const el = $("#onboard-name"); if (el) el.focus(); }, 60);
}

function hideOnboarding() {
  $("#onboarding").classList.add("hidden");
  document.body.classList.remove("onboarding-open");
}

async function submitOnboarding(e) {
  e.preventDefault();
  const name = $("#onboard-name").value.trim();
  const birth = $("#onboard-birth").value;
  const height = $("#onboard-height").value;
  const err = $("#onboarding-error");
  if (!name) { err.textContent = "Please enter your name."; err.classList.remove("hidden"); return; }
  try {
    const res = await fetch("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, height_cm: height, birth_date: birth }),
    });
    if (!res.ok) throw new Error("save failed");
    state.profile = { name, height_cm: String(height), birth_date: birth };
    hideOnboarding();
    await loadShoes();
    await loadActivities();
    switchView("activities");
  } catch (ex) {
    err.textContent = "Could not save your profile. Please retry.";
    err.classList.remove("hidden");
  }
}

async function boot() {
  try {
    const profile = await fetch("/api/profile").then((r) => r.json());
    state.profile = profile || {};
    if (!profile.name || !String(profile.name).trim()) {
      showOnboarding();
      return;
    }
    await loadShoes();
    await loadActivities();
    if (!applyDeepLink()) {
      switchView("home");
    }
  } catch (err) {
    console.error(err);
    showOnboarding();
  }
}

function applyDeepLink() {
  const urlView = new URLSearchParams(window.location.search).get("view");
  if (urlView && ["home", "activities", "heatmap", "records", "stats", "goals", "coaching", "profile", "planner", "fuel", "import"].includes(urlView)) {
    switchView(urlView);
    return true;
  }
  return false;
}

/* --------------------------- Profile ------------------------------ */

function todayLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function shortDay(dateStr) {
  if (!dateStr) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(dateStr);
  return d.toLocaleDateString("en-US", { day: "numeric", month: "short" });
}

function fmtDay(dateStr) {
  if (!dateStr) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(dateStr);
  return d.toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

function computeAge(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  const now = new Date();
  let age = now.getFullYear() - d.getFullYear();
  const m = now.getMonth() - d.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < d.getDate())) age--;
  return age >= 0 && age < 130 ? age : null;
}

async function loadProfile() {
  // Independent requests: one failing endpoint must not blank the whole page.
  const get = (url) => fetch(url).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  const [profile, weights, shoes, defaultShoe, injuriesData] = await Promise.all([
    get("/api/profile"),
    get("/api/weights"),
    get("/api/shoes"),
    get("/api/shoes/default"),
    get("/api/injuries"),
  ]);
  state.profile = profile || {};
  $("#profile-name").value = profile.name || "";
  $("#profile-height").value = profile.height_cm || "";
  $("#profile-birth").value = profile.birth_date || "";
  if (!$("#weight-date").value) $("#weight-date").value = todayLocal();
  state.weights = weights.weights || [];
  renderWeights(state.weights, weights.current_weight_kg);
  state.shoes = shoes.shoes || [];
  renderShoes();
  renderDefaultShoe(defaultShoe);
  renderInjuries(injuriesData);
  renderProfileDerived();
  populateShoeSelect(state.currentDetail && state.currentDetail.shoe ? state.currentDetail.shoe.id : null);
}

function renderProfileDerived() {
  const el = $("#profile-derived");
  if (!el) return;
  const p = state.profile || {};
  const parts = [];
  const age = computeAge(p.birth_date);
  if (age != null) parts.push(`<span class="derived-item"><b>${age}</b> years</span>`);
  const w = state.weights.length ? state.weights[0].weight_kg : null;
  if (w != null) parts.push(`<span class="derived-item"><b>${w}</b> kg</span>`);
  const h = parseFloat(p.height_cm);
  if (w != null && h > 0) {
    const bmi = w / Math.pow(h / 100, 2);
    parts.push(`<span class="derived-item"><b>${bmi.toFixed(1)}</b> BMI</span>`);
  }
  el.innerHTML = parts.length ? parts.join("") : '<span class="muted">Complete your profile to see derived stats.</span>';
}

async function submitProfile(e) {
  e.preventDefault();
  const name = $("#profile-name").value.trim();
  const height = $("#profile-height").value;
  const birth = $("#profile-birth").value;
  const res = await fetch("/api/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, height_cm: height, birth_date: birth }),
  });
  if (!res.ok) return;
  await loadProfile();
}

/* ---------------------------- Weight ------------------------------ */

async function loadWeights() {
  const data = await fetch("/api/weights").then((r) => r.json());
  state.weights = data.weights || [];
  renderWeights(state.weights, data.current_weight_kg);
  renderProfileDerived();
}

function renderWeights(weights, currentWeight) {
  const chart = $("#weight-chart");
  const list = $("#weight-list");
  if (!chart || !list) return;
  if (!weights.length) {
    chart.innerHTML = '<p class="empty-note">No weight entry yet. Add your first measurement above.</p>';
    list.innerHTML = "";
    return;
  }
  const asc = weights.slice().sort((a, b) => a.date.localeCompare(b.date));
  svgLineChart(chart, [{ color: "#10b981", points: asc.map((w) => ({ y: w.weight_kg })), area: true, dots: true }], {
    height: 160, includeZero: false, yFormat: "num",
    xLabels: asc.map((w) => shortDay(w.date)),
  });
  list.innerHTML = weights.map((w) => `
    <div class="weight-row">
      <span class="weight-date">${esc(fmtDay(w.date))}</span>
      <span class="weight-value">${w.weight_kg} kg</span>
      <button class="btn ghost small weight-delete" data-id="${w.id}">✕</button>
    </div>`).join("");
  list.querySelectorAll(".weight-delete").forEach((b) => b.addEventListener("click", async () => {
    await fetch(`/api/weights/${b.dataset.id}`, { method: "DELETE" });
    await loadWeights();
  }));
}

async function addWeight(e) {
  e.preventDefault();
  const date = $("#weight-date").value || todayLocal();
  const kg = parseFloat($("#weight-kg").value);
  if (!kg || kg <= 0) return;
  await fetch("/api/weights", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date, weight_kg: kg }),
  });
  $("#weight-kg").value = "";
  await loadWeights();
}

/* ---------------------- Default shoe + injuries ------------------- */

function renderDefaultShoe(data) {
  const select = $("#shoe-default");
  const toggle = $("#shoe-auto");
  if (!select || !toggle) return;
  const options = state.shoes
    .filter((s) => !s.retired)
    .map((s) => `<option value="${s.id}">${esc(s.name)}</option>`)
    .join("");
  select.innerHTML = `<option value="">— none —</option>${options}`;
  select.value = data && data.shoe_id ? String(data.shoe_id) : "";
  toggle.checked = Boolean(data && data.auto_assign);
}

async function saveDefaultShoe() {
  const select = $("#shoe-default");
  const toggle = $("#shoe-auto");
  const status = $("#shoe-default-status");
  if (!select || !toggle) return;
  const shoeId = select.value ? Number(select.value) : null;
  const autoAssign = toggle.checked;
  const res = await fetch("/api/shoes/default", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shoe_id: shoeId, auto_assign: autoAssign }),
  });
  if (!res.ok) {
    if (status) status.textContent = "Could not save the default shoe.";
    return;
  }
  const data = await res.json();
  if (status) {
    status.textContent =
      data.assigned > 0
        ? `Assigned to ${data.assigned} run${data.assigned === 1 ? "" : "s"} that had no shoe.`
        : autoAssign
          ? "No unassigned run to update."
          : "Automatic assignment is off.";
  }
  if (data.assigned > 0) {
    await reloadData();
    await loadShoes();
  }
}

function renderInjuries(data) {
  const el = $("#injury-body");
  if (!el) return;
  const episodes = (data && data.episodes) || [];
  if (!episodes.length) {
    el.innerHTML =
      '<p class="empty-note">No pain reported yet. Pain is captured in the post-run check-in of each activity.</p>';
    return;
  }

  const links = (data && data.links) || [];
  const summary = (data && data.summary) || {};
  const byEpisode = new Map();
  links.forEach((link) => {
    const key = `${link.location}|${link.side}|${link.pain_first_date}`;
    if (!byEpisode.has(key)) byEpisode.set(key, []);
    byEpisode.get(key).push(link);
  });

  const lowerCount = summary.episodes_lower_limb || 0;
  const plural = lowerCount === 1 ? "" : "s";
  const verb = lowerCount === 1 ? "was" : "were";
  const summaryLine =
    lowerCount > 0
      ? `<p class="muted">${summary.episodes_with_hard_session} of ${lowerCount} lower-limb episode${plural} ${verb} preceded by a hard session (RPE ≥ ${summary.min_rpe}) within ${summary.lookback_hours} h. ${esc(summary.note || "")}</p>`
      : "";

  const cards = episodes
    .map((ep) => {
      const key = `${ep.location}|${ep.side}|${ep.first_date}`;
      const epLinks = byEpisode.get(key) || [];
      const linkHtml = epLinks
        .map(
          (l) => `
          <li>
            <b>${esc(l.session_title || "Session")}</b> on ${fmtDate(l.session_date)}
            (RPE ${l.session_rpe}) — ${esc(l.explanation)}
            <span class="muted">(${l.hours_before} h before the first report)</span>
          </li>`,
        )
        .join("");
      const badge = ep.active
        ? '<span class="badge caution">active</span>'
        : '<span class="badge unknown">settled</span>';
      return `
        <div class="injury-card ${ep.active ? "active" : ""}">
          <div class="injury-head">
            <b>${esc(ep.location)}${ep.side ? ` · ${esc(ep.side)}` : ""}</b>
            ${badge}
            ${ep.last_severity != null ? `<span class="muted">severity ${ep.last_severity}/10${ep.last_trend ? ` · ${esc(ep.last_trend)}` : ""}</span>` : ""}
          </div>
          <div class="muted">
            ${fmtDate(ep.first_date)} → ${fmtDate(ep.last_date)} ·
            ${ep.reports} report${ep.reports === 1 ? "" : "s"}${ep.max_severity != null ? ` · max ${ep.max_severity}/10` : ""}
          </div>
          ${linkHtml ? `<ul class="injury-links">${linkHtml}</ul>` : ep.explainable ? '<p class="muted">No hard session loading these muscles in the 48 h before.</p>' : ""}
        </div>`;
    })
    .join("");

  el.innerHTML = summaryLine + cards;
}

/* ----------------------------- Shoes ------------------------------ */

async function loadShoes() {
  const data = await fetch("/api/shoes").then((r) => r.json());
  state.shoes = data.shoes || [];
  renderShoes();
  populateShoeSelect(state.currentDetail && state.currentDetail.shoe ? state.currentDetail.shoe.id : null);
}

function renderShoes() {
  const el = $("#shoes-list");
  if (!el) return;
  if (!state.shoes.length) {
    el.innerHTML = '<p class="empty-note">No shoe yet. Add your first pair above.</p>';
    return;
  }
  el.innerHTML = state.shoes.map((s) => {
    const km = s.distance_m / 1000;
    const pct = s.threshold_km > 0 ? Math.min(100, (km / s.threshold_km) * 100) : 0;
    const over = s.threshold_km > 0 && km >= s.threshold_km;
    const cls = over ? "over" : (pct > 80 ? "warn" : "");
    return `
      <div class="shoe-card ${s.retired ? "retired" : ""}" data-id="${s.id}">
        <div class="shoe-card-head">
          <b>${esc(s.name)}</b>
          ${s.retired ? '<span class="badge unknown">retired</span>' : ""}
          <span class="shoe-km">${km.toFixed(0)} / ${s.threshold_km.toFixed(0)} km</span>
        </div>
        ${s.notes ? `<div class="shoe-notes muted">${esc(s.notes)}</div>` : ""}
        <div class="shoe-bar"><div class="shoe-bar-fill ${cls}" style="width:${pct}%"></div></div>
        <div class="shoe-actions">
          <span class="muted">${s.activities_count} run${s.activities_count === 1 ? "" : "s"}</span>
          <button class="btn ghost small shoe-retire" data-id="${s.id}">${s.retired ? "Restore" : "Retire"}</button>
          <button class="btn ghost small shoe-delete" data-id="${s.id}">✕</button>
        </div>
      </div>`;
  }).join("");
  el.querySelectorAll(".shoe-retire").forEach((b) => b.addEventListener("click", () => toggleShoeRetired(b.dataset.id)));
  el.querySelectorAll(".shoe-delete").forEach((b) => b.addEventListener("click", () => deleteShoe(b.dataset.id)));
}

async function addShoe(e) {
  e.preventDefault();
  const name = $("#shoe-name").value.trim();
  const threshold = parseFloat($("#shoe-threshold").value) || 600;
  const notes = $("#shoe-notes").value.trim();
  if (!name) return;
  await fetch("/api/shoes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, notes, threshold_km: threshold }),
  });
  $("#shoe-name").value = "";
  $("#shoe-notes").value = "";
  await loadShoes();
}

async function toggleShoeRetired(id) {
  const shoe = state.shoes.find((s) => String(s.id) === String(id));
  if (!shoe) return;
  await fetch(`/api/shoes/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: shoe.name,
      notes: shoe.notes,
      threshold_km: shoe.threshold_km,
      retired: !shoe.retired,
    }),
  });
  await loadShoes();
}

async function deleteShoe(id) {
  await fetch(`/api/shoes/${id}`, { method: "DELETE" });
  await loadShoes();
  if (state.selectedId) selectActivity(state.selectedId);
}

/* --- Shoe assignment on an activity --- */

function populateShoeSelect(selectedId) {
  const sel = $("#shoe-select");
  if (!sel) return;
  let opts = '<option value="">No shoe</option>';
  for (const s of state.shoes) {
    // Hide retired shoes unless it is the one already assigned to this run.
    if (s.retired && String(s.id) !== String(selectedId)) continue;
    opts += `<option value="${s.id}">${esc(s.name)}${s.retired ? " (retired)" : ""}</option>`;
  }
  sel.innerHTML = opts;
  sel.value = selectedId != null ? String(selectedId) : "";
}

async function assignShoe() {
  if (!state.selectedId) return;
  const val = $("#shoe-select").value;
  const shoeId = val === "" ? null : parseInt(val, 10);
  const res = await fetch(`/api/activities/${encodeURIComponent(state.selectedId)}/shoe`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shoe_id: shoeId }),
  });
  if (!res.ok) { console.error("Could not assign shoe"); return; }
  const data = await res.json();
  if (state.currentDetail) state.currentDetail.shoe = data.shoe;
  // Refresh mileage in the profile panel and keep the selector in sync.
  await loadShoes();
}

/* --- Collapsible notes --- */

function toggleNotes() {
  const panel = $("#notes-panel");
  if (!panel) return;
  const collapsed = panel.classList.toggle("collapsed");
  const toggle = $("#notes-toggle");
  toggle.textContent = collapsed ? "▸" : "▾";
  toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  toggle.setAttribute("aria-label", collapsed ? "Expand notes" : "Collapse notes");
}

/* ------------------- Feedback (post-run check-in) ----------------- */

const FB_SESSION_TYPES = [["recovery", "Recovery"], ["easy", "Easy"], ["long", "Long run"], ["tempo", "Tempo"], ["intervals", "Intervals"], ["race", "Race"], ["other", "Other"]];
const FB_SURFACES = [["road", "Road"], ["trail", "Trail"], ["track", "Track"], ["treadmill", "Treadmill"], ["mixed", "Mixed"]];
const FB_COMPLETION = [["full", "Full"], ["partial", "Partial"], ["aborted", "Aborted"]];
const FB_LOCATIONS = [["knee", "Knee"], ["shin", "Shin"], ["calf", "Calf"], ["achilles", "Achilles"], ["foot", "Foot"], ["ankle", "Ankle"], ["hip", "Hip"], ["hamstring", "Hamstring"], ["quad", "Quad"], ["back", "Back"], ["other", "Other"]];
const FB_SIDES = [["left", "Left"], ["right", "Right"], ["both", "Both"]];
const FB_TIMINGS = [["during", "During"], ["after", "After"], ["next_morning", "Next morning"], ["multiple", "Multiple"]];
const FB_TRENDS = [["better", "Better"], ["same", "Same"], ["worse", "Worse"]];

function chipGroupHtml(id, options, selected, multi = false, label = "") {
  const sel = Array.isArray(selected) ? selected : (selected ? [selected] : []);
  const active = sel.map(String);
  return `<div class="fb-chips" id="${id}" role="group" aria-label="${esc(label || id)}" data-multi="${multi ? "true" : "false"}" data-value="${multi ? "" : (active[0] || "")}">`
    + options.map(([value, text]) => {
      const on = active.includes(String(value));
      return `<button type="button" class="fb-chip${on ? " active" : ""}" data-value="${value}" aria-pressed="${on}">${text}</button>`;
    }).join("")
    + "</div>";
}

function scaleHtml(id, max, selected, lowLabel, highLabel, min = 1) {
  let btns = "";
  for (let i = min; i <= max; i++) {
    const on = selected === i;
    btns += `<button type="button" class="fb-chip${on ? " active" : ""}" data-value="${i}" aria-pressed="${on}">${i}</button>`;
  }
  return `<div class="fb-scale-wrap">
    <div class="fb-chips fb-scale" id="${id}" role="group" aria-label="${esc(id)}" data-value="${selected ?? ""}">${btns}</div>
    <div class="fb-scale-labels"><span>${lowLabel}</span><span>${highLabel}</span></div>
  </div>`;
}

function initChipGroups(root) {
  root.querySelectorAll(".fb-chips").forEach((group) => {
    const multi = group.dataset.multi === "true";
    group.querySelectorAll(".fb-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        if (multi) {
          chip.classList.toggle("active");
          chip.setAttribute("aria-pressed", chip.classList.contains("active") ? "true" : "false");
          return;
        }
        const wasActive = chip.classList.contains("active");
        group.querySelectorAll(".fb-chip").forEach((c) => {
          c.classList.remove("active");
          c.setAttribute("aria-pressed", "false");
        });
        if (wasActive) {
          group.dataset.value = "";
        } else {
          chip.classList.add("active");
          chip.setAttribute("aria-pressed", "true");
          group.dataset.value = chip.dataset.value;
        }
      });
    });
  });
}

function chipValue(id) {
  const el = document.getElementById(id);
  if (!el || el.dataset.multi === "true") return "";
  return el.dataset.value || "";
}

function chipValues(id) {
  const el = document.getElementById(id);
  if (!el) return [];
  return [...el.querySelectorAll(".fb-chip.active")].map((c) => c.dataset.value);
}

function intVal(id) {
  const v = chipValue(id);
  return v === "" ? null : parseInt(v, 10);
}

function parseIntOrNull(value) {
  const n = parseInt(value, 10);
  return isNaN(n) ? null : n;
}

function renderFeedbackTab(detail) {
  const body = $("#analysis-tab-body");
  const fb = detail.feedback || {};
  const pain = !!fb.pain;
  body.innerHTML = `
    <div class="fb-form" id="fb-form">
      <div class="fb-field">
        <span class="fb-label">RPE — session effort (1–10)</span>
        ${scaleHtml("fb-rpe", 10, detail.rpe, "0 · rest", "10 · maximal", 0)}
        <p class="fb-help">Anchoring: compare this session with your hardest recent race — not with an easy day. Foster CR-10 scale.</p>
      </div>
      <div class="fb-grid">
        <div class="fb-field"><span class="fb-label">Session intent</span>${chipGroupHtml("fb-session", FB_SESSION_TYPES, fb.session_type, false, "Session intent")}</div>
        <div class="fb-field"><span class="fb-label">Surface</span>${chipGroupHtml("fb-surface", FB_SURFACES, fb.surface, false, "Surface")}</div>
        <div class="fb-field"><span class="fb-label">Completed as planned?</span>${chipGroupHtml("fb-completed", FB_COMPLETION, fb.completed, false, "Completed as planned")}</div>
        <div class="fb-field"><span class="fb-label">Race / time trial</span>
          <label class="fb-toggle"><input type="checkbox" id="fb-race" ${fb.is_race ? "checked" : ""}> This was a race</label>
        </div>
      </div>
      <div class="fb-grid">
        <div class="fb-field"><span class="fb-label">Readiness (before)</span>${scaleHtml("fb-readiness", 5, fb.readiness, "flat", "fresh")}</div>
        <div class="fb-field"><span class="fb-label">Sleep quality</span>${scaleHtml("fb-sleep", 5, fb.sleep_quality, "poor", "great")}</div>
        <div class="fb-field"><span class="fb-label">Life stress</span>${scaleHtml("fb-stress", 5, fb.stress, "low", "high")}</div>
        <div class="fb-field"><span class="fb-label">Legs</span>${scaleHtml("fb-legs", 5, fb.legs, "fresh", "heavy")}</div>
      </div>
      <label class="fb-toggle"><input type="checkbox" id="fb-pain" ${pain ? "checked" : ""}> Pain / discomfort</label>
      <div id="fb-pain-details" class="${pain ? "" : "hidden"}">
        <div class="fb-field"><span class="fb-label">Location</span>${chipGroupHtml("fb-pain-location", FB_LOCATIONS, fb.pain_location, false, "Pain location")}</div>
        <div class="fb-field"><span class="fb-label">Side</span>${chipGroupHtml("fb-pain-side", FB_SIDES, fb.pain_side, false, "Pain side")}</div>
        <div class="fb-field"><span class="fb-label">Severity (0–10)</span>
          <div class="fb-severity">
            <input type="range" id="fb-pain-severity" min="0" max="10" step="1" value="${fb.pain_severity ?? 0}">
            <span id="fb-pain-severity-val">${fb.pain_severity ?? 0}</span>
          </div>
        </div>
        <div class="fb-field"><span class="fb-label">Timing</span>${chipGroupHtml("fb-pain-timing", FB_TIMINGS, fb.pain_timing, false, "Pain timing")}</div>
        <div class="fb-field"><span class="fb-label">Trend</span>${chipGroupHtml("fb-pain-trend", FB_TRENDS, fb.pain_trend, false, "Pain trend")}</div>
      </div>
      <div class="fb-actions">
        <button class="btn" id="fb-save">Save feedback</button>
        <span class="fb-status" id="fb-status"></span>
      </div>
    </div>`;
  initChipGroups(body);
  const painToggle = $("#fb-pain");
  painToggle.addEventListener("change", () => $("#fb-pain-details").classList.toggle("hidden", !painToggle.checked));
  const sev = $("#fb-pain-severity");
  sev.addEventListener("input", () => { $("#fb-pain-severity-val").textContent = sev.value; });
  $("#fb-save").addEventListener("click", () => saveFeedback(detail.id));
}

async function saveFeedback(activityId) {
  if (!activityId) return;
  const status = $("#fb-status");
  const pain = $("#fb-pain").checked;
  const severity = $("#fb-pain-severity").value;
  const payload = {
    session_type: chipValue("fb-session"),
    surface: chipValue("fb-surface"),
    completed: chipValue("fb-completed"),
    readiness: intVal("fb-readiness"),
    sleep_quality: intVal("fb-sleep"),
    stress: intVal("fb-stress"),
    legs: intVal("fb-legs"),
    pain,
    pain_location: pain ? chipValue("fb-pain-location") : "",
    pain_side: pain ? chipValue("fb-pain-side") : "",
    pain_severity: pain ? parseInt(severity, 10) : null,
    pain_timing: pain ? chipValue("fb-pain-timing") : "",
    pain_trend: pain ? chipValue("fb-pain-trend") : "",
    is_race: $("#fb-race").checked,
    rpe: intVal("fb-rpe"),
  };
  try {
    const res = await fetch(`/api/activities/${encodeURIComponent(activityId)}/feedback`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("save failed");
    const data = await res.json();
    if (state.currentDetail) {
      state.currentDetail.feedback = data.feedback;
      state.currentDetail.rpe = data.rpe;
    }
    status.textContent = "Saved ✓";
    status.classList.add("saved");
  } catch (err) {
    status.textContent = "Error while saving";
    status.classList.remove("saved");
  }
}

/* ----------------------------- Planner ---------------------------- */

const SESSION_ICONS = { strength: "🏋️", mobility: "🧘", cross: "🚴", rest: "😴", physio: "🩺", other: "•" };
const SESSION_LABELS = { strength: "Strength", mobility: "Mobility", cross: "Cross-training", rest: "Rest", physio: "Physio", other: "Other" };
const SESSION_KINDS = [["strength", "Strength"], ["mobility", "Mobility"], ["cross", "Cross-training"], ["rest", "Rest"], ["physio", "Physio"], ["other", "Other"]];
const SESSION_STATUSES = [["planned", "Planned"], ["completed", "Completed"], ["skipped", "Skipped"]];
const BODY_AREAS = [
  ["glutes", "Glutes"], ["quads", "Quads"], ["hamstrings", "Hamstrings"],
  ["calves", "Calves"], ["achilles", "Achilles"], ["hip", "Hip"],
  ["hip_flexors", "Hip flexors"], ["adductors", "Adductors"], ["abductors", "Abductors"],
  ["ankle", "Ankle"], ["foot", "Foot"],
  ["core", "Core"], ["obliques", "Obliques"], ["back", "Back"],
  ["chest", "Chest"], ["shoulders", "Shoulders"], ["biceps", "Biceps"],
  ["triceps", "Triceps"], ["forearms", "Forearms"], ["lats", "Lats"], ["neck", "Neck"],
];

function isoDateLocal(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function weekStartDate(dateStr) {
  const d = dateStr ? new Date(dateStr + "T00:00:00") : new Date();
  const day = (d.getDay() + 6) % 7; // Monday = 0
  d.setDate(d.getDate() - day);
  d.setHours(0, 0, 0, 0);
  return d;
}

async function showPlanner() {
  if (!state.plannerWeek) state.plannerWeek = isoDateLocal(weekStartDate(null));
  await loadPlannerSessions();
  renderPlanner();
}

function shiftPlannerWeek(days) {
  const d = new Date(state.plannerWeek + "T00:00:00");
  d.setDate(d.getDate() + days);
  state.plannerWeek = isoDateLocal(d);
  showPlanner();
}

async function loadPlannerSessions() {
  try {
    const data = await fetch("/api/sessions").then((r) => r.json());
    state.plannerSessions = data.sessions || [];
  } catch (err) {
    console.error(err);
    state.plannerSessions = [];
  }
}

function sessionCardHtml(s) {
  const icon = SESSION_ICONS[s.kind] || "•";
  const label = s.title || SESSION_LABELS[s.kind] || s.kind;
  const meta = [];
  if (s.duration_min) meta.push(`${s.duration_min} min`);
  if (s.rpe) meta.push(`RPE ${s.rpe}`);
  const badge = s.status === "completed" ? "completed" : (s.status === "skipped" ? "skipped" : "planned");
  return `<div class="planner-session status-${badge}">
    <div class="planner-session-head"><span>${icon}</span><span class="planner-session-title">${esc(label)}</span></div>
    <div class="planner-session-meta">${esc(meta.join(" · "))} <span class="badge ${badge === "completed" ? "running" : "unknown"}">${badge}</span></div>
    ${exerciseSummary(s)}
    <div class="planner-session-actions">
      ${s.status !== "completed" ? `<button class="link-btn" data-session-action="complete" data-id="${s.id}">Done</button>` : ""}
      ${s.status !== "skipped" ? `<button class="link-btn" data-session-action="skip" data-id="${s.id}">Skip</button>` : ""}
      <button class="link-btn" data-session-action="edit" data-id="${s.id}">Edit</button>
      <button class="link-btn danger" data-session-action="delete" data-id="${s.id}">✕</button>
    </div>
  </div>`;
}

function renderPlanner() {
  const grid = $("#planner-grid");
  const label = $("#planner-week-label");
  const start = weekStartDate(state.plannerWeek);
  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  label.textContent = `${fmtDay(isoDateLocal(start))} – ${fmtDay(isoDateLocal(end))}`;

  const activitiesByDate = {};
  for (const a of state.activities) {
    if (!a.start_time) continue;
    const key = isoDateLocal(new Date(a.start_time));
    (activitiesByDate[key] = activitiesByDate[key] || []).push(a);
  }

  const todayIso = isoDateLocal(new Date());
  const days = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    days.push({ date: d, iso: isoDateLocal(d), isToday: isoDateLocal(d) === todayIso });
  }

  grid.innerHTML = days.map((day) => {
    const runs = activitiesByDate[day.iso] || [];
    const sessions = state.plannerSessions.filter((s) => s.date === day.iso);
    const runsHtml = runs.map((a) => `
      <div class="planner-run" data-id="${esc(a.id)}">
        <span>🏃</span>
        <span class="planner-run-main">${esc(fmtDistance(a.stats.distance_m))} · ${esc(fmtPace(a.stats.avg_pace_s_per_km))}</span>
      </div>`).join("");
    const sessionsHtml = sessions.map(sessionCardHtml).join("");
    const empty = !runs.length && !sessions.length ? '<div class="planner-empty">Rest / no entry</div>' : "";
    return `<div class="planner-day ${day.isToday ? "today" : ""}">
      <div class="planner-day-head">${esc(day.date.toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short" }))}</div>
      ${runsHtml}${sessionsHtml}${empty}
    </div>`;
  }).join("");

  grid.querySelectorAll(".planner-run").forEach((el) => {
    el.tabIndex = 0;
    el.setAttribute("role", "button");
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.click(); }
    });
    el.addEventListener("click", () => {
      switchView("activities");
      selectActivity(el.dataset.id);
    });
  });
  grid.querySelectorAll("[data-session-action]").forEach((el) => {
    el.addEventListener("click", () => handleSessionAction(el.dataset.sessionAction, parseInt(el.dataset.id, 10)));
  });
}

async function refreshPlanner() {
  await loadPlannerSessions();
  renderPlanner();
  $("#session-form-wrap").classList.add("hidden");
  state.plannerEditing = null;
}

async function handleSessionAction(action, id) {
  const session = state.plannerSessions.find((s) => s.id === id);
  if (!session) return;
  if (action === "edit") { renderSessionForm(session); return; }
  if (action === "delete") {
    if (!confirm("Delete this session?")) return;
    await fetch(`/api/sessions/${id}`, { method: "DELETE" });
    await refreshPlanner();
    return;
  }
  if (action === "complete" || action === "skip") {
    await fetch(`/api/sessions/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: session.date,
        time: session.time || "",
        kind: session.kind,
        title: session.title || "",
        duration_min: session.duration_min,
        rpe: session.rpe,
        focus: session.focus || [],
        notes: session.notes || "",
        status: action === "complete" ? "completed" : "skipped",
      }),
    });
    await refreshPlanner();
  }
}

function renderSessionForm(session) {
  const s = session || {
    date: state.plannerWeek || todayLocal(),
    kind: "strength",
    title: "",
    duration_min: 45,
    rpe: 6,
    focus: [],
    notes: "",
    status: "completed",
  };
  state.plannerEditing = session ? session.id : null;
  const wrap = $("#session-form-wrap");
  wrap.classList.remove("hidden");
  wrap.innerHTML = `
    <h3>${session ? "Edit session" : "Log a session"}</h3>
    <div class="fb-grid">
      <div class="fb-field"><span class="fb-label">Date</span><input type="date" id="sf-date" value="${esc(s.date)}"></div>
      <div class="fb-field"><span class="fb-label">Kind</span>${chipGroupHtml("sf-kind", SESSION_KINDS, s.kind, false, "Session kind")}</div>
      <div class="fb-field"><span class="fb-label">Status</span>${chipGroupHtml("sf-status", SESSION_STATUSES, s.status, false, "Session status")}</div>
      <div class="fb-field"><span class="fb-label">Title</span><input type="text" id="sf-title" value="${esc(s.title || "")}" placeholder="e.g. Lower-body strength"></div>
      <div class="fb-field"><span class="fb-label">Duration (min)</span><input type="number" id="sf-duration" min="0" step="5" value="${s.duration_min ?? ""}"></div>
      <div class="fb-field"><span class="fb-label">RPE (0–10)</span><input type="number" id="sf-rpe" min="0" max="10" value="${s.rpe ?? ""}"></div>
    </div>
    <div class="fb-field"><span class="fb-label">Focus areas</span>${chipGroupHtml("sf-focus", BODY_AREAS, s.focus || [], true, "Focus areas")}</div>
    <div class="fb-field">
      <span class="fb-label">Exercises (one per line)</span>
      <textarea id="sf-exercises" rows="3" placeholder="Leg press | 3x10 @ 80 kg&#10;Hip flexor stretch | 2 min">${esc(formatExerciseLines(s.exercises || []))}</textarea>
      <span class="fb-help">Format: <code>Name | sets x reps @ weight</code> or <code>Name | 2 min</code>. Used to link a hard session to a later pain report.</span>
    </div>
    <div class="fb-field"><span class="fb-label">Notes</span><input type="text" id="sf-notes" value="${esc(s.notes || "")}" placeholder="optional"></div>
    <div class="fb-actions">
      <button class="btn" id="sf-save">${session ? "Save" : "Add session"}</button>
      <button class="btn ghost" id="sf-cancel">Cancel</button>
      <span class="fb-status" id="sf-status"></span>
    </div>`;
  initChipGroups(wrap);
  $("#sf-save").addEventListener("click", saveSession);
  $("#sf-cancel").addEventListener("click", () => {
    wrap.classList.add("hidden");
    state.plannerEditing = null;
  });
}

async function saveSession() {
  const payload = {
    date: $("#sf-date").value,
    time: "",
    kind: chipValue("sf-kind"),
    title: $("#sf-title").value.trim(),
    duration_min: parseIntOrNull($("#sf-duration").value),
    rpe: parseIntOrNull($("#sf-rpe").value),
    focus: chipValues("sf-focus"),
    notes: $("#sf-notes").value.trim(),
    status: chipValue("sf-status") || "completed",
    exercises: parseExerciseLines($("#sf-exercises").value),
  };
  const editing = state.plannerEditing;
  const res = await fetch(editing ? `/api/sessions/${editing}` : "/api/sessions", {
    method: editing ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "Could not save the session.");
    return;
  }
  await refreshPlanner();
}

/* --------------------- Exercises (session form) -------------------- */

function parseExerciseLines(text) {
  return String(text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [rawName, rawDetail] = line.split("|").map((part) => (part || "").trim());
      const exercise = { name: rawName };
      if (!rawDetail) return exercise;

      const setsReps = rawDetail.match(/(\d+)\s*[x×]\s*(\d+)/i);
      if (setsReps) {
        exercise.sets = Number(setsReps[1]);
        exercise.reps = Number(setsReps[2]);
      }
      const weight = rawDetail.match(/(\d+(?:[.,]\d+)?)\s*kg/i);
      if (weight) exercise.weight_kg = Number(weight[1].replace(",", "."));
      const duration = rawDetail.match(/(\d+)\s*(min|minutes?|s|sec|seconds?)\b/i);
      if (duration) {
        const unit = duration[2].toLowerCase();
        const value = Number(duration[1]);
        exercise.duration_s = unit.startsWith("m") ? value * 60 : value;
      }
      return exercise;
    })
    .filter((exercise) => exercise.name);
}

function formatExerciseLines(exercises) {
  return (exercises || [])
    .map((exercise) => {
      const parts = [];
      if (exercise.sets && exercise.reps) parts.push(`${exercise.sets}x${exercise.reps}`);
      if (exercise.weight_kg) parts.push(`${exercise.weight_kg} kg`);
      if (exercise.duration_s) parts.push(`${Math.round(exercise.duration_s / 60)} min`);
      return parts.length ? `${exercise.name} | ${parts.join(" ")}` : exercise.name;
    })
    .join("\n");
}

function exerciseSummary(session) {
  const list = session.exercises || [];
  if (!list.length) return "";
  const names = list.slice(0, 3).map((e) => esc(e.name));
  const more = list.length > 3 ? ` +${list.length - 3}` : "";
  const muscles = [...new Set(list.flatMap((e) => e.muscles || []))];
  return `<div class="session-exercises muted">${names.join(", ")}${more}${
    muscles.length ? ` · ${esc(muscles.join(", "))}` : ""
  }</div>`;
}

/* ------------------------- Fuel & recovery ------------------------ */

const SUPP_FREQ_LABELS = {
  daily: "daily",
  "5x_week": "5×/week",
  "3x_week": "3×/week",
  "2x_week": "2×/week",
  weekly: "weekly",
  as_needed: "as needed",
};

async function showFuel() {
  const dateInput = $("#nut-date");
  if (dateInput && !dateInput.value) dateInput.value = todayLocal();
  await loadFuel();
}

async function loadFuel() {
  const [nutrient, supp] = await Promise.all([
    fetch("/api/nutrition").then((r) => r.json()),
    fetch("/api/supplements").then((r) => r.json()),
  ]);
  state.nutritionLogs = nutrient.logs || [];
  state.supplements = supp.supplements || [];
  renderSupplementCheckboxes();
  populateNutritionForm($("#nut-date").value);
  renderNutritionList();
  renderSupplements();
}

function renderSupplementCheckboxes() {
  const el = $("#nut-supplements");
  if (!el) return;
  const active = state.supplements.filter((s) => s.active);
  if (!active.length) {
    el.innerHTML = '<span class="muted">No supplement defined.</span>';
    return;
  }
  el.innerHTML = active.map((s) =>
    `<label class="fb-check"><input type="checkbox" value="${s.id}"> ${esc(s.name)}</label>`
  ).join("");
}

function populateNutritionForm(date) {
  const log = state.nutritionLogs.find((n) => n.date === date);
  $("#nut-hydration").value = log && log.hydration_l != null ? log.hydration_l : "";
  $("#nut-energy").value = log && log.energy != null ? log.energy : "";
  $("#nut-appetite").value = log && log.appetite != null ? log.appetite : "";
  $("#nut-steps").value = log && log.steps != null ? log.steps : "";
  $("#nut-fueling-notes").value = log ? log.fueling_notes || "" : "";
  $("#nut-notes").value = log ? log.notes || "" : "";
  ["before", "during", "after"].forEach((v) => {
    const chip = document.querySelector(`#nut-fueling .fb-chip[data-value="${v}"]`);
    if (chip) {
      const on = !!(log && log["fueling_" + v]);
      chip.classList.toggle("active", on);
      chip.setAttribute("aria-pressed", on ? "true" : "false");
    }
  });
  document.querySelectorAll("#nut-supplements input[type=checkbox]").forEach((cb) => {
    const id = parseInt(cb.value, 10);
    cb.checked = !!(log && (log.supplements_taken || []).includes(id));
  });
  const status = $("#nut-status");
  if (status) { status.textContent = ""; status.classList.remove("saved"); }
}

async function saveNutrition(e) {
  e.preventDefault();
  const date = $("#nut-date").value;
  if (!date) return;
  const fueling = chipValues("nut-fueling");
  const payload = {
    hydration_l: $("#nut-hydration").value === "" ? null : parseFloat($("#nut-hydration").value),
    energy: parseIntOrNull($("#nut-energy").value),
    appetite: parseIntOrNull($("#nut-appetite").value),
    steps: parseIntOrNull($("#nut-steps").value),
    fueling_before: fueling.includes("before"),
    fueling_during: fueling.includes("during"),
    fueling_after: fueling.includes("after"),
    fueling_notes: $("#nut-fueling-notes").value.trim(),
    supplements_taken: [...document.querySelectorAll("#nut-supplements input[type=checkbox]:checked")]
      .map((cb) => parseInt(cb.value, 10)),
    notes: $("#nut-notes").value.trim(),
  };
  const status = $("#nut-status");
  const res = await fetch(`/api/nutrition/${encodeURIComponent(date)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    status.textContent = "Error while saving";
    status.classList.remove("saved");
    return;
  }
  await loadFuel();
  const fresh = $("#nut-status");
  fresh.textContent = "Saved ✓";
  fresh.classList.add("saved");
}

function renderNutritionList() {
  const el = $("#nutrition-list");
  if (!el) return;
  if (!state.nutritionLogs.length) {
    el.innerHTML = '<p class="empty-note">No check-in yet.</p>';
    return;
  }
  el.innerHTML = state.nutritionLogs.slice(0, 14).map((n) => {
    const flags = [];
    if (n.hydration_l != null) flags.push(`${n.hydration_l} L`);
    if (n.energy != null) flags.push(`energy ${n.energy}/5`);
    if (n.appetite != null) flags.push(`appetite ${n.appetite}/5`);
    if (n.steps != null) flags.push(`${Number(n.steps).toLocaleString()} steps`);
    const fueling = ["before", "during", "after"].filter((v) => n["fueling_" + v]);
    if (fueling.length) flags.push(`fueling ${fueling.join("/")}`);
    if ((n.supplements_taken || []).length) flags.push(`${n.supplements_taken.length} supp.`);
    const m = n.macros || {};
    if (m.calories != null) flags.push(`${Math.round(m.calories)} kcal`);
    if (m.protein_g != null) flags.push(`P ${Math.round(m.protein_g)}g`);
    if (m.carbs_g != null) flags.push(`C ${Math.round(m.carbs_g)}g`);
    if (m.fat_g != null) flags.push(`F ${Math.round(m.fat_g)}g`);
    return `<div class="nut-row">
      <div class="nut-row-head">
        <b>${esc(fmtDay(n.date))}</b>
        <button class="link-btn" data-nut-edit="${esc(n.date)}">Edit</button>
        <button class="link-btn danger" data-nut-delete="${n.id}">✕</button>
      </div>
      <div class="nut-row-meta">${esc(flags.join(" · ")) || "—"}</div>
      ${n.notes ? `<div class="nut-row-notes muted">${esc(n.notes)}</div>` : ""}
    </div>`;
  }).join("");
  el.querySelectorAll("[data-nut-edit]").forEach((b) => b.addEventListener("click", () => {
    $("#nut-date").value = b.dataset.nutEdit;
    populateNutritionForm(b.dataset.nutEdit);
    $("#nut-date").scrollIntoView({ behavior: "smooth", block: "center" });
  }));
  el.querySelectorAll("[data-nut-delete]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Delete this check-in?")) return;
    await fetch(`/api/nutrition/${b.dataset.nutDelete}`, { method: "DELETE" });
    await loadFuel();
  }));
}

function renderSupplements() {
  const el = $("#supplements-list");
  if (!el) return;
  if (!state.supplements.length) {
    el.innerHTML = '<p class="empty-note">No supplement defined.</p>';
    return;
  }
  el.innerHTML = state.supplements.map((s) => `
    <div class="supp-row">
      <div>
        <b>${esc(s.name)}</b>
        <span class="muted">${esc([s.dose, SUPP_FREQ_LABELS[s.frequency] || s.frequency].filter(Boolean).join(" · "))}</span>
      </div>
      <button class="link-btn danger" data-supp-delete="${s.id}">✕</button>
    </div>`).join("");
  el.querySelectorAll("[data-supp-delete]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Delete this supplement?")) return;
    await fetch(`/api/supplements/${b.dataset.suppDelete}`, { method: "DELETE" });
    await loadFuel();
  }));
}

async function addSupplement(e) {
  e.preventDefault();
  const name = $("#supp-name").value.trim();
  if (!name) return;
  await fetch("/api/supplements", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      dose: $("#supp-dose").value.trim(),
      frequency: $("#supp-frequency").value,
    }),
  });
  $("#supp-name").value = "";
  $("#supp-dose").value = "";
  await loadFuel();
}

/* ------------------------- Global loading ------------------------- */

async function loadActivities(keepSelection) {
  try {
    const res = await fetch("/api/activities");
    const data = await res.json();
    state.activities = data.activities;
    renderSummary(data.summary);
    renderList(data.activities);

    if (keepSelection && state.selectedId) {
      const still = data.activities.find((a) => a.id === state.selectedId);
      if (still) await selectActivity(state.selectedId);
    }
    const urlId = new URLSearchParams(window.location.search).get("id");
    if (urlId && data.activities.some((a) => a.id === urlId)) {
      await selectActivity(urlId);
    }
  } catch (err) {
    console.error(err);
  }
}

async function reloadData() {
  try {
    await fetch("/api/reload", { method: "POST" });
    await loadActivities(true);
    if (state.currentView === "heatmap") { state.heatmapMap = null; showHeatmap(); }
    if (state.currentView === "records") loadRecords();
    if (state.currentView === "stats") loadMonthly();
    if (state.currentView === "coaching") renderCoachingTab();
    if (state.currentView === "planner") showPlanner();
    if (state.currentView === "fuel") showFuel();
  } catch (err) {
    console.error(err);
  }
}

/* --------------------------- Import (drop) ------------------------ */

const UPLOAD = {
  running: { exts: [".kmz", ".gpx", ".tcx"] },
  nutrition: { exts: [".csv", ".json", ".zip"] },
  workout: { exts: [".csv", ".json"] },
};

function addDropStatus(status, kind, text) {
  const line = document.createElement("div");
  line.className = kind;
  line.textContent = text;
  status.appendChild(line);
  return line;
}

async function uploadOne(category, file) {
  const res = await fetch(
    `/api/upload/${category}?filename=${encodeURIComponent(file.name)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    },
  );
  let data = {};
  try {
    data = await res.json();
  } catch (err) {
    data = {};
  }
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

async function handleDroppedFiles(category, files) {
  const status = document.querySelector(`#status-${category}`);
  if (!status) return;
  status.textContent = "";
  const list = Array.from(files);
  if (!list.length) return;

  const allowed = UPLOAD[category].exts;
  let imported = 0;

  for (const file of list) {
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    if (!allowed.includes(ext)) {
      addDropStatus(
        status,
        "err",
        `✕ ${file.name}: ${ext === "." ? "no extension" : ext} is not accepted here (${allowed.join(", ")})`,
      );
      continue;
    }
    const pending = addDropStatus(status, "wait", `… ${file.name}`);
    try {
      const data = await uploadOne(category, file);
      pending.remove();
      addDropStatus(status, "ok", `✓ ${file.name} — ${data.summary}`);
      imported += 1;
    } catch (err) {
      pending.remove();
      addDropStatus(status, "err", `✕ ${file.name}: ${err.message}`);
    }
  }

  if (imported) await reloadData();
}

function initImport() {
  document.querySelectorAll(".drop-zone").forEach((zone) => {
    const category = zone.dataset.category;
    const target = zone.querySelector(".drop-target");
    const input = zone.querySelector("input[type=file]");
    if (!category || !target || !input) return;

    const openPicker = () => input.click();

    target.addEventListener("click", (event) => {
      // Clicking the hidden input bubbles back to this handler: ignoring it
      // prevents an infinite click loop.
      if (event.target === input) return;
      openPicker();
    });
    target.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openPicker();
      }
    });

    ["dragenter", "dragover"].forEach((type) => {
      zone.addEventListener(type, (event) => {
        event.preventDefault();
        zone.classList.add("is-dragover");
      });
    });
    zone.addEventListener("dragleave", (event) => {
      // Ignore the leave events fired when crossing child elements.
      if (event.relatedTarget && zone.contains(event.relatedTarget)) return;
      zone.classList.remove("is-dragover");
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("is-dragover");
      const files = event.dataTransfer ? event.dataTransfer.files : [];
      handleDroppedFiles(category, files);
    });

    input.addEventListener("change", () => {
      handleDroppedFiles(category, input.files || []);
      input.value = "";
    });
  });

  // Dropping outside a zone must not make the browser navigate to the file.
  ["dragover", "drop"].forEach((type) => {
    document.addEventListener(type, (event) => {
      if (!event.target.closest || !event.target.closest(".drop-zone")) {
        event.preventDefault();
      }
    });
  });
}

/* --------------------- Automatic import polling -------------------- */

let dataVersion = null;
let toastTimer = null;

function showDataToast(text) {
  const el = $("#data-toast");
  if (!el) return;
  el.textContent = text;
  el.classList.remove("hidden");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 6000);
}

async function pollDataVersion() {
  // Nothing to do while the tab is in the background: the server watcher has
  // already imported the files, the UI only needs to catch up on return.
  if (document.hidden) return;
  try {
    const res = await fetch("/api/data-version");
    if (!res.ok) return;
    const payload = await res.json();
    if (dataVersion === null) {
      dataVersion = payload.version;
      return;
    }
    if (payload.version === dataVersion) return;
    dataVersion = payload.version;
    await reloadData();
    showDataToast("New data imported");
  } catch (err) {
    /* offline or server restarting: try again on the next tick */
  }
}

function initDataWatcher() {
  pollDataVersion();
  setInterval(pollDataVersion, 10000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) pollDataVersion();
  });
}

/* --------------------------- Accessibility ------------------------ */

function initTabs(tablistId, panelId) {
  const tablist = document.getElementById(tablistId);
  const panel = document.getElementById(panelId);
  if (!tablist) return;
  if (panel) {
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("tabindex", "0");
  }
  const tabs = [...tablist.querySelectorAll(".tab-btn")];
  tabs.forEach((tab, index) => {
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", panelId);
    const selected = tab.classList.contains("active");
    tab.setAttribute("aria-selected", selected ? "true" : "false");
    tab.setAttribute("tabindex", selected ? "0" : "-1");
    tab.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const direction = e.key === "ArrowRight" ? 1 : -1;
      const next = tabs[(index + direction + tabs.length) % tabs.length];
      next.focus();
      next.click();
    });
  });
  tablist.addEventListener("click", () => {
    tabs.forEach((t) => {
      const selected = t.classList.contains("active");
      t.setAttribute("aria-selected", selected ? "true" : "false");
      t.setAttribute("tabindex", selected ? "0" : "-1");
    });
  });
}

/* ------------------------------ Init ------------------------------ */

document.querySelectorAll(".nav-btn").forEach((b) => {
  b.addEventListener("click", () => {
    if (!b.dataset.view) return;
    switchView(b.dataset.view);
    const details = b.closest("details");
    if (details) details.open = false;
  });
});
document.addEventListener("click", (e) => {
  const target = e.target.closest("[data-goto]");
  if (!target) return;
  goTo(target.dataset.goto, target.dataset.ctab || null);
});
document.querySelectorAll("#analysis-tabs .tab-btn").forEach((b) => {
  b.addEventListener("click", () => {
    state.activeTab = b.dataset.tab;
    document.querySelectorAll("#analysis-tabs .tab-btn").forEach((x) => x.classList.toggle("active", x === b));
    renderTab();
  });
});
document.querySelectorAll("#coaching-tabs .tab-btn").forEach((b) => {
  b.addEventListener("click", () => {
    state.coachingTab = b.dataset.ctab;
    document.querySelectorAll("#coaching-tabs .tab-btn").forEach((x) => x.classList.toggle("active", x === b));
    renderCoachingTab();
  });
});
/* --- Theme toggle ------------------------------------------------------- */
function applyThemeLabel() {
  const dark = document.documentElement.dataset.theme === "dark";
  const btn = $("#theme-toggle");
  if (!btn) return;
  btn.setAttribute("aria-pressed", dark ? "true" : "false");
  btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  btn.textContent = dark ? "☀️" : "🌙";
}

function initTheme() {
  const btn = $("#theme-toggle");
  if (!btn) return;
  applyThemeLabel();
  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch (e) {
      /* storage may be unavailable (private mode): the theme still applies */
    }
    // Drop a forced ?theme=... so the explicit choice wins on reload.
    try {
      const params = new URLSearchParams(location.search);
      if (params.has("theme")) {
        params.delete("theme");
        const qs = params.toString();
        history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
      }
    } catch (e) {
      /* history may be unavailable */
    }
    applyThemeLabel();
  });
  // Follow the operating system only while the athlete has not chosen a theme.
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  if (media.addEventListener) {
    media.addEventListener("change", (event) => {
      let stored = null;
      try {
        stored = localStorage.getItem("theme");
      } catch (e) {
        stored = null;
      }
      if (stored) return;
      document.documentElement.dataset.theme = event.matches ? "dark" : "light";
      applyThemeLabel();
    });
  }
}

initTheme();
initImport();
initDataWatcher();
initTabs("analysis-tabs", "analysis-tab-body");
initTabs("coaching-tabs", "coaching-body");
$("#save-note-btn").addEventListener("click", saveNote);
$("#reload-btn").addEventListener("click", reloadData);
$("#goal-form").addEventListener("submit", addGoal);
$("#goal-metric").addEventListener("change", updateGoalLabel);
$("#notes-toggle").addEventListener("click", toggleNotes);
$("#shoe-select").addEventListener("change", assignShoe);
$("#onboarding-form").addEventListener("submit", submitOnboarding);
$("#profile-form").addEventListener("submit", submitProfile);
$("#weight-form").addEventListener("submit", addWeight);
$("#shoe-form").addEventListener("submit", addShoe);
$("#shoe-default").addEventListener("change", saveDefaultShoe);
$("#shoe-auto").addEventListener("change", saveDefaultShoe);
$("#planner-prev").addEventListener("click", () => shiftPlannerWeek(-7));
$("#planner-next").addEventListener("click", () => shiftPlannerWeek(7));
$("#planner-today").addEventListener("click", () => { state.plannerWeek = null; showPlanner(); });
$("#planner-add").addEventListener("click", () => renderSessionForm(null));
$("#nutrition-form").addEventListener("submit", saveNutrition);
$("#supplement-form").addEventListener("submit", addSupplement);
$("#nut-date").addEventListener("change", () => populateNutritionForm($("#nut-date").value));
document.querySelectorAll("#nut-fueling .fb-chip").forEach((chip) => {
  chip.setAttribute("aria-pressed", "false");
  chip.addEventListener("click", () => {
    chip.classList.toggle("active");
    chip.setAttribute("aria-pressed", chip.classList.contains("active") ? "true" : "false");
  });
});

// First-run gate: show onboarding until an athlete profile exists in the DB.
boot();
