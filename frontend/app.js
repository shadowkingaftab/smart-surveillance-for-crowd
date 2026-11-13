/* ──────────────────────────────────────────────────────────────────────────
   Intelligent Video Intelligence · Operations Console
   Vanilla ES2020. Same-origin API by default; no build step, no dependencies.
   ────────────────────────────────────────────────────────────────────────── */
(() => {
  "use strict";

  const API_BASE = location.protocol === "file:" ? "http://127.0.0.1:8000" : "";

  const INCIDENT_TYPES = {
    accident:           { label: "Accident",             color: "#ff8a8a", soft: "rgba(255,95,109,.13)",  glyph: "⚠" },
    violence_fight:     { label: "Violence / Fight",     color: "#ff5f6d", soft: "rgba(255,95,109,.13)",  glyph: "⚡" },
    robbery_intrusion:  { label: "Robbery / Intrusion",  color: "#ffb454", soft: "rgba(255,180,84,.13)",  glyph: "⊘" },
    dangerous_activity: { label: "Dangerous Activity",   color: "#ff9f43", soft: "rgba(255,159,67,.13)",  glyph: "▲" },
    crowd_anomaly:      { label: "Crowd Anomaly",        color: "#a78bfa", soft: "rgba(167,139,250,.13)", glyph: "◉" },
    vehicle_incident:   { label: "Vehicle Incident",     color: "#57a6ff", soft: "rgba(87,166,255,.13)",  glyph: "▣" },
    other_configured:   { label: "Other configured",     color: "#8296aa", soft: "rgba(130,150,170,.12)", glyph: "•" },
  };

  const SEVERITIES = {
    candidate: { label: "Candidate", tag: "tag-critical", color: "#ff5f6d", min: 70 },
    review:    { label: "Review",    tag: "tag-warn",     color: "#ffb454", min: 35 },
    low:       { label: "Low",       tag: "tag-low",      color: "#6e91b4", min: 0 },
  };

  const VIEW_META = {
    overview: {
      eyebrow: "Live monitoring",
      title: "Overview",
      sub: "Multi-entity classification, tracking and temporal incident review.",
    },
    incidents: {
      eyebrow: "Review queue",
      title: "Incidents",
      sub: "Sustained, multi-signal candidates. Every row is evidence, not a verdict.",
    },
    cameras: {
      eyebrow: "Input fleet",
      title: "Cameras",
      sub: "Capture health, reconnect state and per-camera incident load.",
    },
    system: {
      eyebrow: "Platform",
      title: "System",
      sub: "Service health, retention policy and integration surface.",
    },
  };

  const RANGE_MS = {
    "1h": 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "48h": 48 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    all: Infinity,
  };

  const state = {
    incidents: [],
    cameras: [],
    health: null,
    apiOnline: null,
    loading: false,
    lastSync: null,
    view: "overview",
    activityRange: "24h",
    refreshSeconds: 5,
    selectedId: null,
    filters: { search: "", type: "", camera: "", range: "24h", severity: "all" },
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  /* ── Formatting helpers ───────────────────────────────────────────────── */

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));

  const parseTs = (iso) => {
    if (!iso) return null;
    const hasZone = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
    const d = new Date(hasZone ? iso : `${iso}Z`);
    return Number.isNaN(d.getTime()) ? null : d;
  };

  const fmtRel = (date) => {
    if (!date) return "never";
    let secs = Math.round((Date.now() - date.getTime()) / 1000);
    if (secs < 0) secs = 0;
    if (secs < 10) return "just now";
    if (secs < 60) return `${secs}s ago`;
    const mins = Math.floor(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return days === 1 ? "1d ago" : `${days}d ago`;
  };

  const fmtDateTime = new Intl.DateTimeFormat(undefined, {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const fmtClock = new Intl.DateTimeFormat(undefined, {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const fmtHourMin = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
  const fmtDayHour = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "2-digit" });
  const fmtDay = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short" });

  const fmtAbs = (date) => (date ? fmtDateTime.format(date) : "—");

  const humanize = (value) =>
    String(value || "unknown").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

  const typeInfo = (type) => INCIDENT_TYPES[type] || {
    label: humanize(type), color: "#8296aa", soft: "rgba(130,150,170,.12)", glyph: "•",
  };

  const severityOf = (confidence) => {
    const value = Number(confidence) || 0;
    if (value >= 70) return SEVERITIES.candidate;
    if (value >= 35) return SEVERITIES.review;
    return SEVERITIES.low;
  };

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  const fmtInt = (n) => new Intl.NumberFormat().format(n);

  /* ── Data access ──────────────────────────────────────────────────────── */

  async function fetchJson(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: "application/json" },
      ...options,
    });
    if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
    return res.json();
  }

  async function loadData({ manual = false } = {}) {
    if (state.loading) return;
    state.loading = true;
    const btn = $("#refreshBtn");
    if (manual) btn.classList.add("is-spinning");

    const results = await Promise.allSettled([
      fetchJson("/health"),
      fetchJson("/cameras"),
      fetchJson("/incidents?limit=500"),
    ]);
    const [healthR, camerasR, incidentsR] = results;

    let anySuccess = false;

    if (healthR.status === "fulfilled") {
      state.health = healthR.value;
      anySuccess = true;
    }
    if (camerasR.status === "fulfilled" && Array.isArray(camerasR.value)) {
      state.cameras = camerasR.value;
      anySuccess = true;
    }
    if (incidentsR.status === "fulfilled" && Array.isArray(incidentsR.value)) {
      state.incidents = incidentsR.value;
      anySuccess = true;
    }

    if (!anySuccess) {
      state.apiOnline = false;
      setApiStatus(false);
    } else {
      state.apiOnline = healthR.status === "fulfilled";
      setApiStatus(state.apiOnline);
      state.lastSync = new Date();
      if (healthR.status !== "fulfilled" || camerasR.status !== "fulfilled" || incidentsR.status !== "fulfilled") {
        toast("Some API resources failed to load. Showing partial data.", true);
      }
    }

    if (!state.apiOnline && anySuccess) {
      $("#offlineDetail").textContent = "Health check failed; camera or incident data may be stale.";
    }

    $("#offlineBanner").hidden = state.apiOnline !== false;
    if (state.lastSync) {
      $("#lastUpdated").textContent = fmtClock.format(state.lastSync);
    }

    state.loading = false;
    if (manual) {
      window.setTimeout(() => btn.classList.remove("is-spinning"), 450);
    } else {
      btn.classList.remove("is-spinning");
    }

    renderAll();
  }

  function setApiStatus(online) {
    const pill = $("#apiPill");
    pill.dataset.state = online ? "online" : "offline";
    $(".api-pill-label", pill).textContent = online ? "API connected" : "API unreachable";
  }

  /* ── Derived collections ──────────────────────────────────────────────── */

  const incidentsSorted = () => [...state.incidents].sort((a, b) => {
    const ta = parseTs(a.timestamp)?.getTime() ?? 0;
    const tb = parseTs(b.timestamp)?.getTime() ?? 0;
    return tb - ta;
  });

  const withinRange = (incident, rangeKey, now = Date.now()) => {
    const span = RANGE_MS[rangeKey] ?? RANGE_MS["24h"];
    if (span === Infinity) return true;
    const t = parseTs(incident.timestamp)?.getTime();
    return t != null && now - t <= span;
  };

  const cameraMap = () => new Map(state.cameras.map((c) => [c.camera_id, c]));

  const cameraStatusKey = (status) => {
    const s = String(status || "unknown").toLowerCase();
    if (s === "online") return "online";
    if (s === "reconnecting") return "reconnecting";
    if (s === "offline" || s === "stopped") return "offline";
    return "unknown";
  };

  const cameraStatusLabel = (status) => {
    const s = String(status || "unknown").toLowerCase();
    if (s === "stopped") return "stopped";
    return s;
  };

  /* ── Rendering: shell ─────────────────────────────────────────────────── */

  function renderAll() {
    renderNavBadge();
    renderKpis();
    renderActivity();
    renderTypeBreakdown();
    renderCameraStrip();
    renderRecentTable();
    renderFilters();
    renderIncidentsTable();
    renderCamerasView();
    renderSystem();

    if (state.selectedId != null) {
      const current = state.incidents.find((i) => i.id === state.selectedId);
      if (!current) closeDrawer(false);
    }
  }

  function renderNavBadge() {
    const badge = $("#navIncidentCount");
    const recent = state.incidents.filter((i) => withinRange(i, "24h")).length;
    badge.textContent = fmtInt(recent);
    badge.hidden = recent === 0;
  }

  function renderKpis() {
    const now = Date.now();
    const last24 = state.incidents.filter((i) => withinRange(i, "24h", now));
    const candidates = last24.filter((i) => Number(i.confidence) >= 70);
    const review = last24.filter((i) => {
      const c = Number(i.confidence);
      return c >= 35 && c < 70;
    });
    const camTotal = state.cameras.length;
    const camOnline = state.cameras.filter((c) => cameraStatusKey(c.status) === "online").length;
    const camReconnecting = state.cameras.filter((c) => cameraStatusKey(c.status) === "reconnecting").length;
    const camerasReporting = new Set(last24.map((i) => i.camera_id)).size;

    $("#kpiTotal").textContent = fmtInt(last24.length);
    $("#kpiTotalSub").textContent = last24.length
      ? `across ${camerasReporting} camera${camerasReporting === 1 ? "" : "s"}`
      : "no records in range";

    $("#kpiCandidates").textContent = fmtInt(candidates.length);
    $("#kpiCandidatesSub").textContent = last24.length
      ? `${Math.round((candidates.length / last24.length) * 100)}% of incidents in range`
      : "awaiting human review";

    $("#kpiReview").textContent = fmtInt(review.length);
    $("#kpiReviewSub").textContent = last24.length
      ? `${Math.round((review.length / last24.length) * 100)}% of incidents in range`
      : "sustained evidence, unconfirmed";

    $("#kpiCameras").textContent = fmtInt(camOnline);
    $("#kpiCamTotal").textContent = `${camTotal} configured`;
    $("#kpiCamerasSub").textContent = camTotal === 0
      ? "no cameras reporting"
      : camReconnecting
        ? `${camReconnecting} reconnecting · ${camTotal - camOnline - camReconnecting} offline`
        : `${camTotal - camOnline} offline · fleet healthy`;

    const hourly = bucketIncidents(state.incidents, 24 * 60 * 60 * 1000, 24, now);
    renderSpark($("#sparkTotal"), hourly.map((b) => b.total));
    renderSpark($("#sparkCandidates"), hourly.map((b) => b.critical), "critical");
    renderSpark($("#sparkReview"), hourly.map((b) => b.review), "warn");

    $("#cameraDots").innerHTML = state.cameras.length
      ? state.cameras.slice(0, 12).map((c) =>
          `<span class="camera-dot ${cameraStatusKey(c.status)}" title="${esc(c.camera_id)} · ${esc(c.status)}"></span>`
        ).join("")
      : "";
  }

  function renderSpark(el, values, variant) {
    el.classList.remove("critical", "warn");
    if (variant) el.classList.add(variant);
    if (!values.length || !values.some((v) => v > 0)) {
      el.innerHTML = `<path class="spark-empty" d="M1 15h94" />`;
      return;
    }
    const w = 96;
    const h = 30;
    const max = Math.max(...values, 1);
    const stepX = (w - 2) / Math.max(values.length - 1, 1);
    const pts = values.map((v, i) => [1 + i * stepX, h - 2 - (v / max) * (h - 6)]);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
    const area = `${line} L${w - 1} ${h} L1 ${h} Z`;
    el.innerHTML = `<path class="spark-area" d="${area}" /><path class="spark-line" d="${line}" />`;
  }

  function bucketIncidents(incidents, rangeMs, count, now = Date.now()) {
    const start = now - rangeMs;
    const span = rangeMs / count;
    const buckets = Array.from({ length: count }, (_, i) => ({
      start: start + i * span,
      end: start + (i + 1) * span,
      total: 0,
      critical: 0,
      review: 0,
    }));
    for (const incident of incidents) {
      const t = parseTs(incident.timestamp)?.getTime();
      if (t == null || t < start || t > now) continue;
      const idx = clamp(Math.floor((t - start) / span), 0, count - 1);
      const bucket = buckets[idx];
      bucket.total += 1;
      if (Number(incident.confidence) >= 70) bucket.critical += 1;
      else bucket.review += 1;
    }
    return buckets;
  }

  /* ── Rendering: activity chart ────────────────────────────────────────── */

  function renderActivity() {
    const container = $("#activityChart");
    const axis = $("#activityAxis");
    const range = state.activityRange;
    const config = range === "7d"
      ? { span: RANGE_MS["7d"], buckets: 28 }
      : range === "48h"
        ? { span: RANGE_MS["48h"], buckets: 24 }
        : { span: RANGE_MS["24h"], buckets: 24 };

    const buckets = bucketIncidents(state.incidents, config.span, config.buckets);
    const max = Math.max(...buckets.map((b) => b.total), 1);
    const labelFmt = range === "7d" ? fmtDay : range === "48h" ? fmtDayHour : fmtHourMin;

    let tip = $(".chart-tip", container);
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "chart-tip";
      container.appendChild(tip);
    }

    const bars = buckets.map((bucket, i) => {
      const total = bucket.total;
      const criticalH = total ? Math.max(3, (bucket.critical / max) * 100) : 0;
      const reviewH = total ? Math.max(2, (bucket.review / max) * 100) : 0;
      const label = `${labelFmt.format(new Date(bucket.start))} – ${labelFmt.format(new Date(bucket.end))}`;
      const barsHtml = total
        ? `<span class="bar bar-review" style="height:${reviewH}%"></span><span class="bar bar-critical" style="height:${criticalH}%"></span>`
        : `<span class="bar bar-empty"></span>`;
      return `<div class="bar-col" data-i="${i}"
        data-label="${esc(label)}"
        data-total="${total}"
        data-critical="${bucket.critical}"
        data-review="${bucket.review}"
        role="img"
        aria-label="${esc(`${label}: ${total} incidents, ${bucket.critical} candidates, ${bucket.review} review`)}">${barsHtml}</div>`;
    }).join("");
    container.innerHTML = bars;
    container.appendChild(tip);

    const start = new Date(buckets[0].start);
    const end = new Date(Date.now());
    const tickCount = 5;
    const labels = [];
    for (let i = 0; i < tickCount; i++) {
      const t = start.getTime() + ((end.getTime() - start.getTime()) * i) / (tickCount - 1);
      labels.push(`<span>${esc(labelFmt.format(new Date(t)))}</span>`);
    }
    axis.innerHTML = labels.join("");
  }

  function handleChartPointer(event) {
    const container = $("#activityChart");
    const col = event.target.closest(".bar-col");
    const tip = $(".chart-tip", container);
    if (!col || !tip) return;
    const total = Number(col.dataset.total);
    if (!total) {
      tip.classList.remove("is-visible");
      return;
    }
    tip.innerHTML = `<strong>${esc(col.dataset.label)}</strong><br>
      ${esc(col.dataset.total)} incident${total === 1 ? "" : "s"} ·
      ${esc(col.dataset.critical)} candidate · ${esc(col.dataset.review)} review`;
    const rect = container.getBoundingClientRect();
    tip.style.left = `${clamp(event.clientX - rect.left, 70, rect.width - 70)}px`;
    tip.style.top = `${event.clientY - rect.top - 12}px`;
    tip.classList.add("is-visible");
  }

  /* ── Rendering: type breakdown ────────────────────────────────────────── */

  function renderTypeBreakdown() {
    const el = $("#typeBreakdown");
    const last24 = state.incidents.filter((i) => withinRange(i, "24h"));
    if (!last24.length) {
      el.innerHTML = `<div class="type-empty">No incidents stored in the last 24 hours.<br>The taxonomy appears here once the fusion engine raises review events.</div>`;
      return;
    }
    const counts = new Map();
    for (const incident of last24) {
      counts.set(incident.incident_type, (counts.get(incident.incident_type) || 0) + 1);
    }
    const rows = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    const max = rows[0][1];
    el.innerHTML = rows.map(([type, count]) => {
      const info = typeInfo(type);
      return `<div class="type-row">
        <div class="type-row-head">
          <span class="type-dot" style="background:${info.color}"></span>
          <span class="type-name" title="${esc(type)}">${esc(info.label)}</span>
        </div>
        <span class="type-count">${fmtInt(count)}</span>
        <div class="type-track">
          <div class="type-fill" style="width:${Math.max(4, (count / max) * 100)}%;background:linear-gradient(90deg, ${info.color}bb, ${info.color})"></div>
        </div>
      </div>`;
    }).join("");
  }

  /* ── Rendering: cameras ───────────────────────────────────────────────── */

  function sortCameras(cameras) {
    const order = { online: 0, reconnecting: 1, offline: 2, unknown: 3 };
    return [...cameras].sort((a, b) => {
      const diff = (order[cameraStatusKey(a.status)] ?? 3) - (order[cameraStatusKey(b.status)] ?? 3);
      return diff || String(a.camera_id).localeCompare(String(b.camera_id));
    });
  }

  function cameraIncidentCount(cameraId, rangeKey = "24h") {
    return state.incidents.filter((i) => i.camera_id === cameraId && withinRange(i, rangeKey)).length;
  }

  function cameraCardHtml(camera) {
    const statusKey = cameraStatusKey(camera.status);
    const name = camera.name || camera.camera_id;
    const lastSeen = parseTs(camera.last_seen);
    const count = cameraIncidentCount(camera.camera_id);
    return `<article class="camera-card">
      <div class="camera-card-top">
        <div>
          <div class="camera-name">${esc(name)}</div>
          <div class="camera-id">${esc(camera.camera_id)}</div>
        </div>
        <span class="cam-status ${statusKey}"><span class="dot"></span>${esc(cameraStatusLabel(camera.status))}</span>
      </div>
      <div class="camera-meta">
        <span class="cam-tag">${esc(camera.group || "default")}</span>
        <span class="cam-seen">${lastSeen ? `seen ${esc(fmtRel(lastSeen))}` : "never seen"}</span>
      </div>
      <span class="camera-source" title="${esc(camera.source || "")}">${esc(camera.source || "no source configured")}</span>
      ${camera.last_error ? `<div class="camera-error" title="${esc(camera.last_error)}">${esc(camera.last_error)}</div>` : ""}
      <div class="camera-incidents"><b>${fmtInt(count)}</b> incident${count === 1 ? "" : "s"} · last 24h</div>
    </article>`;
  }

  function renderCameraStrip() {
    const el = $("#cameraStrip");
    const cameras = sortCameras(state.cameras).slice(0, 3);
    el.innerHTML = cameras.length
      ? cameras.map((c) => cameraCardHtml(c)).join("")
      : `<div class="type-empty" style="grid-column:1/-1">No camera streams have registered yet. Start a runner to populate the fleet.</div>`;
  }

  function renderCamerasView() {
    const grid = $("#cameraGrid");
    const summary = $("#fleetSummary");
    const empty = $("#camerasEmpty");
    const cameras = sortCameras(state.cameras);

    if (!cameras.length) {
      grid.innerHTML = "";
      grid.hidden = true;
      summary.innerHTML = "";
      empty.hidden = false;
      return;
    }
    grid.hidden = false;
    empty.hidden = true;

    const counts = { online: 0, reconnecting: 0, offline: 0, unknown: 0 };
    cameras.forEach((c) => { counts[cameraStatusKey(c.status)] += 1; });
    summary.innerHTML = `
      <span class="fleet-chip"><span class="dot" style="background:var(--muted)"></span><b>${cameras.length}</b> configured</span>
      <span class="fleet-chip online"><span class="dot"></span><b>${counts.online}</b> online</span>
      <span class="fleet-chip reconnecting"><span class="dot"></span><b>${counts.reconnecting}</b> reconnecting</span>
      <span class="fleet-chip offline"><span class="dot"></span><b>${counts.offline}</b> offline</span>`;

    grid.innerHTML = cameras.map((c) => cameraCardHtml(c)).join("");
  }

  /* ── Rendering: tables ────────────────────────────────────────────────── */

  function incidentTitle(incident) {
    const info = typeInfo(incident.incident_type);
    const reason = Array.isArray(incident.reasoning) ? incident.reasoning[0] : "";
    return { info, reason: reason || "no reasoning recorded" };
  }

  function incidentRowHtml(incident, { full = false } = {}) {
    const { info, reason } = incidentTitle(incident);
    const severity = severityOf(incident.confidence);
    const confidence = Math.round(Number(incident.confidence) || 0);
    const tracks = Array.isArray(incident.track_ids) ? incident.track_ids : [];
    const date = parseTs(incident.timestamp);
    const tracksHtml = tracks.length
      ? tracks.slice(0, 2).map((id) => `<span class="track-chip">#${esc(id)}</span>`).join("") +
        (tracks.length > 2 ? `<span class="track-chip more">+${tracks.length - 2}</span>` : "")
      : `<span class="track-chip more">—</span>`;
    const evidence = incident.evidence_path
      ? `<span class="evidence-mark has-clip" title="${esc(incident.evidence_path)}">
           <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 6 6 6-6 6"/><path d="M13 6h7v12h-7"/></svg>clip</span>`
      : `<span class="evidence-mark">none</span>`;

    const camera = cameraMap().get(incident.camera_id);
    const camStatus = camera ? cameraStatusKey(camera.status) : "unknown";

    return `<tr data-id="${incident.id}" tabindex="0" role="button" aria-label="Open ${esc(info.label)} incident ${incident.id}">
      <td>
        <div class="incident-cell">
          <span class="incident-icon" style="color:${info.color};background:${info.soft};border-color:${info.color}33">${esc(info.glyph)}</span>
          <div class="incident-text">
            <div class="incident-title">${esc(info.label)}</div>
            <div class="incident-reason" title="${esc(reason)}">${esc(reason)}</div>
          </div>
        </div>
      </td>
      <td>
        <span class="camera-chip"><span class="dot" style="background:${camStatus === "online" ? "var(--accent)" : camStatus === "reconnecting" ? "var(--warn)" : "#3c5068"}"></span>${esc(incident.camera_id)}</span>
      </td>
      <td><span class="tag ${severity.tag}">${severity.label}</span></td>
      <td>
        <div class="confidence-cell">
          <span class="mini-meter"><i style="width:${clamp(confidence, 0, 100)}%;background:${severity.color}"></i></span>
          <span class="confidence-num">${confidence}</span>
        </div>
      </td>
      ${full ? `<td class="col-tracks"><div class="track-list">${tracksHtml}</div></td><td class="col-evidence">${evidence}</td>` : `<td class="col-tracks"><div class="track-list">${tracksHtml}</div></td>`}
      <td class="time-cell">
        <span class="time-rel">${esc(fmtRel(date))}</span>
        <span class="time-abs">${esc(date ? fmtDateTime.format(date) : "—")}</span>
      </td>
    </tr>`;
  }

  function renderRecentTable() {
    const body = $("#recentTableBody");
    const empty = $("#recentEmpty");
    const table = body.closest("table");
    const rows = incidentsSorted().slice(0, 6);
    if (!rows.length) {
      body.innerHTML = "";
      table.hidden = true;
      empty.hidden = false;
      return;
    }
    table.hidden = false;
    empty.hidden = true;
    body.innerHTML = rows.map((i) => incidentRowHtml(i)).join("");
  }

  /* ── Rendering: filters + incident table ──────────────────────────────── */

  function renderFilters() {
    const typeSelect = $("#typeFilter");
    const cameraSelect = $("#cameraFilter");
    const currentType = state.filters.type;
    const currentCamera = state.filters.camera;

    const types = new Set(Object.keys(INCIDENT_TYPES));
    state.incidents.forEach((i) => { if (i.incident_type) types.add(i.incident_type); });
    typeSelect.innerHTML = `<option value="">All types</option>` + [...types].sort()
      .map((t) => `<option value="${esc(t)}">${esc(typeInfo(t).label)}</option>`).join("");
    typeSelect.value = currentType;

    const cameraIds = new Set(state.cameras.map((c) => c.camera_id));
    state.incidents.forEach((i) => { if (i.camera_id) cameraIds.add(i.camera_id); });
    cameraSelect.innerHTML = `<option value="">All cameras</option>` + [...cameraIds].sort()
      .map((id) => `<option value="${esc(id)}">${esc(id)}</option>`).join("");
    cameraSelect.value = currentCamera;
  }

  function filteredIncidents() {
    const { search, type, camera, range, severity } = state.filters;
    const needle = search.trim().toLowerCase();
    const cams = cameraMap();
    return incidentsSorted().filter((incident) => {
      if (!withinRange(incident, range)) return false;
      if (type && incident.incident_type !== type) return false;
      if (camera && incident.camera_id !== camera) return false;
      const sev = severityOf(incident.confidence).label.toLowerCase();
      if (severity !== "all" && sev !== severity) return false;
      if (needle) {
        const cam = cams.get(incident.camera_id);
        const haystack = [
          incident.incident_type,
          typeInfo(incident.incident_type).label,
          incident.camera_id,
          cam?.name || "",
          String(incident.id),
          ...(Array.isArray(incident.track_ids) ? incident.track_ids : []),
          ...(Array.isArray(incident.reasoning) ? incident.reasoning : []),
        ].join(" ").toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
  }

  function renderIncidentsTable() {
    const body = $("#incidentsTableBody");
    const empty = $("#incidentsEmpty");
    const table = body.closest("table");
    const rows = filteredIncidents();

    $("#resultCount").textContent = `${fmtInt(rows.length)} result${rows.length === 1 ? "" : "s"}`;

    if (!rows.length) {
      body.innerHTML = "";
      table.hidden = true;
      empty.hidden = false;
      return;
    }
    table.hidden = false;
    empty.hidden = true;
    body.innerHTML = rows.map((i) => incidentRowHtml(i, { full: true })).join("");
  }

  /* ── Rendering: system ────────────────────────────────────────────────── */

  function renderSystem() {
    const health = state.health;
    $("#healthTag").textContent = health ? (health.status === "ok" ? "operational" : health.status) : "unknown";
    $("#healthTag").className = `tag ${health && health.status === "ok" ? "tag-ok" : "tag-muted"}`;
    $("#healthStatus").textContent = health?.status ?? "—";
    $("#healthDatabase").textContent = health?.database ?? "—";
    $("#healthCamera").textContent = health?.camera_id ?? "—";
  }

  /* ── Drawer ───────────────────────────────────────────────────────────── */

  function openDrawer(id, trigger) {
    const incident = state.incidents.find((i) => i.id === id);
    if (!incident) return;
    state.selectedId = id;
    renderDrawer(incident);
    $("#drawerOverlay").hidden = false;
    $("#drawer").hidden = false;
    $("#drawer").setAttribute("aria-hidden", "false");
    document.body.classList.add("drawer-open");
    const closeBtn = $(".drawer-close");
    if (closeBtn) closeBtn.focus({ preventScroll: true });
    $$("tr[data-was-trigger]").forEach((el) => delete el.dataset.wasTrigger);
    if (trigger) trigger.dataset.wasTrigger = "true";
  }

  function closeDrawer(restoreFocus = true) {
    const drawer = $("#drawer");
    if (drawer.hidden) return;
    const active = document.activeElement;
    if (active && drawer.contains(active)) {
      const trigger = restoreFocus ? $('tr[data-was-trigger="true"]') : null;
      if (trigger) trigger.focus({ preventScroll: true });
      else active.blur();
    }
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    $("#drawerOverlay").hidden = true;
    document.body.classList.remove("drawer-open");
    state.selectedId = null;
    if (restoreFocus) {
      const trigger = $('tr[data-was-trigger="true"]');
      if (trigger) delete trigger.dataset.wasTrigger;
    } else {
      $$('tr[data-was-trigger="true"]').forEach((el) => delete el.dataset.wasTrigger);
    }
  }

  function renderDrawer(incident) {
    const { info } = incidentTitle(incident);
    const severity = severityOf(incident.confidence);
    const confidence = Math.round(Number(incident.confidence) || 0);
    const date = parseTs(incident.timestamp);
    const camera = cameraMap().get(incident.camera_id);
    const reasoning = Array.isArray(incident.reasoning) ? incident.reasoning : [];
    const tracks = Array.isArray(incident.track_ids) ? incident.track_ids : [];
    const links = Array.isArray(incident.cross_camera_links) ? incident.cross_camera_links : [];
    const metadata = incident.metadata && Object.keys(incident.metadata).length
      ? JSON.stringify(incident.metadata, null, 2)
      : "{\n  \n}";

    const meta = [
      ["Incident ID", `#${incident.id}`],
      ["Camera", camera ? `${camera.name || camera.camera_id} (${incident.camera_id})` : incident.camera_id],
      ["Detected", date ? fmtAbs(date) : "—"],
      ["Tracks", tracks.length ? tracks.map((t) => `#${t}`).join(", ") : "—"],
      ["Evidence clip", incident.evidence_path || "not attached"],
      ["Verification", incident.verified ? "verified by operator" : "unverified"],
    ];

    const linksHtml = links.length
      ? `<div class="drawer-section">
           <div class="drawer-section-title">Cross-camera candidate links</div>
           <div class="link-list">${links.map((link) => `
             <div class="link-row">
               <span>${esc(link.camera_id || "camera")} · track <span class="mono">#${esc(link.track_id || "?")}</span></span>
               <span class="tag tag-muted">${link.similarity != null ? `${Math.round(Number(link.similarity) * 100)}% sim` : "candidate"}</span>
             </div>`).join("")}</div>
         </div>`
      : "";

    $("#drawerContent").innerHTML = `
      <div class="drawer-head">
        <div>
          <div class="drawer-eyebrow">Incident #${esc(incident.id)} · ${esc(fmtRel(date))}</div>
          <h2 class="drawer-title">${esc(info.label)}</h2>
          <p class="drawer-sub">${esc(incident.camera_id)}${camera?.name ? ` · ${esc(camera.name)}` : ""} · ${esc(date ? fmtAbs(date) : "unknown time")}</p>
        </div>
        <button class="drawer-close" type="button" data-close-drawer aria-label="Close incident details">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>
        </button>
      </div>
      <div class="drawer-body">
        <div class="drawer-badges">
          <span class="tag ${severity.tag}">${severity.label}</span>
          <span class="tag ${incident.verified ? "tag-ok" : "tag-muted"}">${incident.verified ? "verified" : "unverified"}</span>
          <span class="tag tag-muted">${esc(incident.incident_type)}</span>
        </div>

        <div class="confidence-panel">
          <div class="confidence-ring" style="--pct:${clamp(confidence, 0, 100)};--ring-color:${severity.color}">
            <span>${confidence}</span>
          </div>
          <div class="confidence-meta">
            <strong>Fusion confidence</strong>
            <span>Accumulated across ${tracks.length || 1} tracked entit${tracks.length === 1 ? "y" : "ies"}; single-frame cues never reach this threshold alone.</span>
          </div>
        </div>

        <div class="drawer-section">
          <div class="drawer-section-title">Reasoning chain</div>
          ${reasoning.length
            ? `<ul class="reasoning-list">${reasoning.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`
            : `<p class="reasoning-empty">No reasoning recorded for this incident.</p>`}
        </div>

        <div class="drawer-section">
          <div class="drawer-section-title">Record</div>
          <dl class="kv-grid">
            ${meta.map(([k, v]) => `
              <div class="kv">
                <dt>${esc(k)}</dt>
                <dd>${k === "Evidence clip" && incident.evidence_path
                  ? `<span class="mono" title="${esc(v)}">${esc(v.split(/[\\\\/]/).pop())}</span>`
                  : esc(v)}</dd>
              </div>`).join("")}
          </dl>
        </div>

        ${linksHtml}

        <div class="drawer-section">
          <div class="drawer-section-title">Observation metadata</div>
          <pre class="json-block">${esc(metadata)}</pre>
        </div>

        <p class="drawer-note">
          Severity mirrors the stored fusion score: REVIEW ≥ 35, INCIDENT_CANDIDATE ≥ 70.
          Facial-expression cues and cross-camera links are contextual only — an operator
          confirms or dismisses every incident after reviewing the evidence clip.
        </p>
      </div>`;
  }

  /* ── Routing ──────────────────────────────────────────────────────────── */

  function setView(view, { fromHash = false } = {}) {
    if (!VIEW_META[view]) view = "overview";
    state.view = view;
    $$("[data-view-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.viewPanel !== view;
    });
    $$("[data-nav]").forEach((link) => {
      const active = link.dataset.nav === view;
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    $("#viewEyebrow").textContent = VIEW_META[view].eyebrow;
    $("#viewTitle").textContent = VIEW_META[view].title;
    $("#viewSub").textContent = VIEW_META[view].sub;
    document.title = `${VIEW_META[view].title} · Intelligent Video Intelligence`;
    closeDrawer(false);
    if (!fromHash && location.hash !== `#/${view}`) {
      history.pushState(null, "", `#/${view}`);
    }
  }

  function viewFromHash() {
    const view = (location.hash || "").replace(/^#\/?/, "");
    return VIEW_META[view] ? view : "overview";
  }

  /* ── Toast ────────────────────────────────────────────────────────────── */

  let toastTimer = null;
  function toast(message, isError = false) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.hidden = false;
    requestAnimationFrame(() => el.classList.add("is-visible"));
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
      el.classList.remove("is-visible");
      window.setTimeout(() => { el.hidden = true; }, 220);
    }, 3400);
  }

  /* ── Live camera ──────────────────────────────────────────────────────── */

  const LIVE_EXPRESSIONS = ["neutral", "happy", "surprised", "sad", "angry", "fearful", "disgusted"];
  const LIVE_RED = new Set(["sad", "angry", "fearful", "disgusted"]);
  // FER under-reports anger/upset on webcam faces (often splitting it with
  // neutral), so negative cues are weighted to keep clear distress out of the
  // green box without flipping genuinely calm faces.
  const LIVE_WEIGHT = {
    neutral: 1.0, happy: 0.9, surprised: 0.8,
    angry: 1.8, fearful: 1.5, sad: 1.35, disgusted: 1.25,
  };
  const LIVE_LABEL = {
    neutral: "Neutral", happy: "Happy", surprised: "Surprised",
    sad: "Sad", angry: "Angry", fearful: "Fearful", disgusted: "Disgusted",
  };
  const LIVE_CALM = "#2ee6c5";
  const LIVE_ALERT = "#ff5f6d";
  const LIVE_MODELS_URI = "vendor/face-api/models";

  const live = {
    open: false,
    loading: false,
    running: false,
    modelsReady: false,
    scriptPromise: null,
    stream: null,
    timer: null,
    token: 0,
    startToken: 0,
    options: null,
    smoothed: null,
    smoothedAt: 0,
    missedRuns: 0,
    backend: null,
    lastResults: null,
    lastFacesAt: 0,
    fps: 0,
    restoreFocus: null,
  };

  function loadFaceApi() {
    if (window.faceapi) return Promise.resolve(window.faceapi);
    if (live.scriptPromise) return live.scriptPromise;
    live.scriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "vendor/face-api/face-api.js";
      script.async = true;
      script.onload = () => {
        if (window.faceapi) resolve(window.faceapi);
        else reject(new Error("face-api script loaded without exposing its API"));
      };
      script.onerror = () => {
        live.scriptPromise = null;
        script.remove();
        reject(new Error("face-api script could not be loaded"));
      };
      document.head.appendChild(script);
    });
    return live.scriptPromise;
  }

  function setLiveBadge(kind, text) {
    const badge = $("#liveModelBadge");
    badge.classList.remove("state-idle", "state-loading", "state-ready", "state-error");
    badge.classList.add(`state-${kind}`);
    $("#liveModelText").textContent = text;
  }

  async function ensureLiveModels() {
    if (live.modelsReady) return;
    setLiveBadge("loading", "Loading models…");
    const api = await loadFaceApi();
    if (api.tf && api.tf.ready) await applyLiveBackend(api.tf);
    await api.nets.tinyFaceDetector.loadFromUri(LIVE_MODELS_URI);
    await api.nets.faceExpressionNet.loadFromUri(LIVE_MODELS_URI);
    live.modelsReady = true;
    live.backend = api.tf && api.tf.getBackend ? api.tf.getBackend() : "cpu";
    const detector = $("#liveDetector");
    if (detector) detector.textContent = live.backend === "webgl" ? "TinyFace · WebGL" : "TinyFace · CPU";
    setLiveBadge("ready", "On-device models ready");
  }

  // WebGL is the fast path. Without hardware acceleration tfjs would reject the
  // context and try to fetch a WASM backend that isn't vendored, so fall
  // straight to CPU and keep the console clean.
  async function applyLiveBackend(tf) {
    const candidates = [];
    try {
      const options = { failIfMajorPerformanceCaveat: true };
      const canvas2 = document.createElement("canvas");
      const accelerated = canvas2.getContext("webgl2", options)
        || document.createElement("canvas").getContext("webgl", options);
      if (accelerated) candidates.push("webgl");
    } catch (_) { /* no WebGL */ }
    candidates.push("cpu");
    for (const name of candidates) {
      try {
        await tf.setBackend(name);
        await tf.ready();
        if (tf.getBackend() === name) return;
      } catch (_) { /* try next backend */ }
    }
  }

  function openLiveModal() {
    if (live.open) return;
    live.open = true;
    live.restoreFocus = document.activeElement;
    $("#liveModal").hidden = false;
    document.body.classList.add("live-open");
    $("#liveCloseBtn").focus({ preventScroll: true });
    startLiveCamera();
  }

  function closeLiveModal() {
    if (!live.open) return;
    stopLiveCamera();
    live.open = false;
    $("#liveModal").hidden = true;
    document.body.classList.remove("live-open");
    if (live.restoreFocus && live.restoreFocus.isConnected) {
      live.restoreFocus.focus({ preventScroll: true });
    } else {
      $("#openLiveBtn").focus({ preventScroll: true });
    }
  }

  function showLivePlaceholder({ title, text, error = false, busy = false, action = "Enable camera" }) {
    const box = $("#livePlaceholder");
    box.hidden = false;
    box.classList.toggle("is-error", error);
    box.classList.toggle("is-busy", busy);
    $("#livePlaceholderTitle").textContent = title;
    $("#livePlaceholderText").textContent = text;
    $("#liveStartBtn").textContent = action;
  }

  function hideLivePlaceholder() {
    const box = $("#livePlaceholder");
    box.hidden = true;
    box.classList.remove("is-error", "is-busy");
  }

  function videoReady() {
    const video = $("#liveVideo");
    return video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0;
  }

  async function startLiveCamera() {
    if (live.running || live.loading) return;
    const attempt = ++live.startToken;
    live.loading = true;
    $("#liveNotice").hidden = true;
    showLivePlaceholder({
      busy: true,
      title: "Starting camera…",
      text: "Allow camera access in the browser prompt. Detection models load locally from this server.",
    });

    try {
      if (!window.isSecureContext) {
        throw Object.assign(new Error("This page is not a secure context"), { code: "insecure" });
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw Object.assign(new Error("Camera API unavailable"), { code: "unsupported" });
      }

      const [models, media] = await Promise.allSettled([
        ensureLiveModels(),
        navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        }),
      ]);

      const stream = media.status === "fulfilled" ? media.value : null;
      const cancelled = !live.open || attempt !== live.startToken;
      if (cancelled) {
        if (stream) stream.getTracks().forEach((track) => track.stop());
        return;
      }
      if (models.status === "rejected") {
        if (stream) stream.getTracks().forEach((track) => track.stop());
        live.loading = false;
        live.startToken += 1;
        showLiveError("model");
        return;
      }
      if (media.status === "rejected") throw media.reason;

      live.stream = stream;
      const video = $("#liveVideo");
      video.srcObject = stream;
      await new Promise((resolve) => {
        if (video.readyState >= 1) return resolve();
        video.addEventListener("loadedmetadata", resolve, { once: true });
        window.setTimeout(resolve, 1500);
      });
      try { await video.play(); } catch (_) { /* muted autoplay is allowed; ignore */ }

      if (!live.open || attempt !== live.startToken) {
        releaseMedia();
        return;
      }
      if (!videoReady()) {
        releaseMedia();
        throw Object.assign(new Error("Camera delivered no video frames"), { code: "noframes" });
      }

      $("#liveStage").style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
      live.options = new window.faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.25 });
      live.smoothed = null;
      live.smoothedAt = 0;
      live.missedRuns = 0;
      live.lastResults = null;
      live.lastFacesAt = 0;
      live.fps = 0;
      live.running = true;
      live.loading = false;
      live.token += 1;

      hideLivePlaceholder();
      $("#liveHud").hidden = false;
      $("#liveStopBtn").disabled = false;
      resetLiveReadout({ idleText: "Looking for a face", idleClass: "idle" });
      $("#liveHudFaces").textContent = "0 faces";
      $("#liveHudFps").textContent = "—";
      toast(live.backend === "cpu"
        ? "Camera live · on-device CPU mode. Enable browser hardware acceleration for smoother tracking."
        : "Camera live · analysis stays on this device");
      runLiveDetection(live.token);
    } catch (error) {
      if (!live.open || attempt !== live.startToken) {
        releaseMedia();
        return;
      }
      live.loading = false;
      releaseMedia();
      live.startToken += 1;
      const custom = typeof error.code === "string" && error.code;
      showLiveError(custom || mapCameraError(error));
    }
  }

  function showLiveError(code) {
    const copy = {
      insecure: {
        title: "Camera needs a secure origin",
        text: "Browsers only expose the camera on localhost or HTTPS. Open http://127.0.0.1:8000/ or http://localhost:8000/.",
      },
      unsupported: {
        title: "Camera API unavailable",
        text: "This browser does not expose getUserMedia here. Try a current Chrome, Edge, Firefox or Safari.",
      },
      permission: {
        title: "Camera permission blocked",
        text: "Allow camera access for this site in the browser address bar, then press Try again. Nothing is recorded or uploaded.",
      },
      notfound: {
        title: "No camera found",
        text: "No webcam is connected to this device, or the built-in camera is disabled.",
      },
      busy: {
        title: "Camera is busy",
        text: "Another app is using the webcam. Close it (video calls, camera apps) and press Try again.",
      },
      noframes: {
        title: "No video frames",
        text: "The camera opened but delivered no picture. Reconnect the camera or try again.",
      },
      model: {
        title: "Detection models failed to load",
        text: "The local face models under vendor/face-api/models could not be loaded. Reload the page and try again.",
      },
      camera: {
        title: "Could not start the camera",
        text: "The browser refused the camera without a specific reason. Check the address-bar camera permission, close other camera apps, then press Try again.",
      },
    };
    const entry = copy[code] || copy.model;
    if (code === "model") setLiveBadge("error", "Model load failed");
    setLiveModelIdle();
    $("#liveHud").hidden = true;
    $("#liveStopBtn").disabled = true;
    showLivePlaceholder({ title: entry.title, text: entry.text, error: true, action: "Try again" });
  }

  function mapCameraError(error) {
    const name = (error && error.name) || "";
    if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return "permission";
    if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError" || name === "NotSupportedError") return "notfound";
    if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") return "busy";
    return "camera";
  }

  function releaseMedia() {
    if (live.stream) {
      live.stream.getTracks().forEach((track) => track.stop());
      live.stream = null;
    }
    const video = $("#liveVideo");
    if (video) {
      video.pause();
      video.srcObject = null;
    }
  }

  function stopLiveCamera() {
    live.running = false;
    live.loading = false;
    live.startToken += 1;
    live.token += 1;
    window.clearTimeout(live.timer);
    live.timer = null;
    live.lastResults = null;
    live.lastFacesAt = 0;
    releaseMedia();
    clearLiveCanvas();
    $("#liveHud").hidden = true;
    $("#liveStopBtn").disabled = true;
    $("#liveStage").style.aspectRatio = "";
    resetLiveReadout();
    if (live.modelsReady) setLiveBadge("ready", "On-device models ready");
    else setLiveBadge("idle", "Model idle");
    showLivePlaceholder({
      title: "Camera is off",
      text: "Enable the camera to start on-device face detection. Video never leaves this browser tab.",
    });
  }

  async function runLiveDetection(token) {
    if (!live.running || token !== live.token) return;
    const started = performance.now();

    if (videoReady() && window.faceapi) {
      try {
        let results = await window.faceapi
          .detectAllFaces($("#liveVideo"), live.options)
          .withFaceExpressions();
        if (!live.running || token !== live.token) return;

        const now = performance.now();
        if (results.length) {
          live.lastResults = results;
          live.lastFacesAt = now;
          live.missedRuns = 0;
        } else if (live.lastResults && (live.missedRuns < 1 || now - live.lastFacesAt < 800)) {
          live.missedRuns += 1;
          results = live.lastResults;
        } else {
          live.lastResults = null;
          live.missedRuns = 0;
        }

        const elapsed = Math.max(1, now - started);
        const instant = 1000 / elapsed;
        live.fps = live.fps ? live.fps * 0.65 + instant * 0.35 : instant;
        $("#liveHudFps").textContent = `${live.fps.toFixed(1)} fps`;
        $("#liveFps").textContent = `${live.fps.toFixed(1)} fps`;
        $("#liveNotice").hidden = true;

        updateLiveReadout(results);
        drawLiveFaces(results);
      } catch (error) {
        if (!live.running || token !== live.token) return;
        const notice = $("#liveNotice");
        notice.textContent = "Inference hiccup — retrying. If this persists, stop and restart the camera.";
        notice.hidden = false;
      }
    }

    const spent = performance.now() - started;
    live.timer = window.setTimeout(() => runLiveDetection(token), Math.max(10, 100 - spent));
  }

  function clearLiveCanvas() {
    const canvas = $("#liveCanvas");
    const ctx = canvas.getContext("2d");
    if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  function classifyFace(expressions) {
    let red = 0;
    let calm = 0;
    for (const key of LIVE_EXPRESSIONS) {
      const value = (expressions[key] || 0) * (LIVE_WEIGHT[key] || 1);
      if (LIVE_RED.has(key)) red += value;
      else calm += value;
    }
    const pool = red > calm ? [...LIVE_RED] : LIVE_EXPRESSIONS.filter((key) => !LIVE_RED.has(key));
    let top = pool[0];
    for (const key of pool) {
      if ((expressions[key] || 0) > (expressions[top] || 0)) top = key;
    }
    return {
      distressed: red > calm,
      expression: top,
      confidence: expressions[top] || 0,
    };
  }

  function roundRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
  }

  function drawLiveFaces(results) {
    const stage = $("#liveStage");
    const video = $("#liveVideo");
    const canvas = $("#liveCanvas");
    const sw = stage.clientWidth;
    const sh = stage.clientHeight;
    if (!sw || !sh) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(sw * dpr) || canvas.height !== Math.round(sh * dpr)) {
      canvas.width = Math.round(sw * dpr);
      canvas.height = Math.round(sh * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, sw, sh);
    if (!results || !results.length) return;

    const vw = video.videoWidth;
    const vh = video.videoHeight;
    const scale = Math.max(sw / vw, sh / vh);
    const offX = (sw - vw * scale) / 2;
    const offY = (sh - vh * scale) / 2;
    const primaryResult = primaryFace(results);

    for (const result of results) {
      if (!result.detection) continue;
      const { box } = result.detection;
      const info = classifyFace(result === primaryResult && live.smoothed ? live.smoothed : result.expressions || {});
      const color = info.distressed ? LIVE_ALERT : LIVE_CALM;

      const x = sw - (offX + (box.x + box.width) * scale);
      const y = offY + box.y * scale;
      const width = box.width * scale;
      const height = box.height * scale;

      ctx.save();
      ctx.shadowColor = info.distressed ? "rgba(255,95,109,.55)" : "rgba(46,230,197,.5)";
      ctx.shadowBlur = 14;
      ctx.lineWidth = 3;
      ctx.strokeStyle = color;
      roundRect(ctx, x, y, width, height, 12);
      ctx.stroke();
      ctx.restore();

      const label = `${LIVE_LABEL[info.expression] || info.expression} ${Math.round(info.confidence * 100)}%`;
      ctx.font = "600 12px ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif";
      const textWidth = ctx.measureText(label).width;
      const chipWidth = Math.min(textWidth + 18, sw - 8);
      const chipHeight = 22;
      const chipX = Math.min(Math.max(4, x), Math.max(4, sw - chipWidth - 4));
      const chipY = y - chipHeight - 6 >= 4 ? y - chipHeight - 6 : y + 6;

      ctx.fillStyle = "rgba(4, 8, 13, .86)";
      roundRect(ctx, chipX, chipY, chipWidth, chipHeight, 6);
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.textBaseline = "middle";
      ctx.fillText(label, chipX + 9, chipY + chipHeight / 2 + 0.5);
    }
  }

  function primaryFace(results) {
    let primary = null;
    for (const result of results) {
      if (!result.detection) continue;
      const area = result.detection.box.width * result.detection.box.height;
      if (!primary || area > primary.area) primary = { result, area };
    }
    return primary ? primary.result : null;
  }

  function updateLiveReadout(results) {
    const faces = results ? results.length : 0;
    $("#liveFaces").textContent = String(faces);
    $("#liveHudFaces").textContent = faces === 1 ? "1 face" : `${faces} faces`;

    const primary = primaryFace(results || []);
    if (!primary) {
      live.smoothed = null;
      live.smoothedAt = 0;
      live.missedRuns = 0;
      $("#liveMood").textContent = "No face";
      setLiveState("idle", "Looking for a face");
      $("#liveExpressionBars").innerHTML = "";
      return;
    }

    // Time-aware smoothing: a fixed alpha would take several seconds to react
    // on slow (CPU) machines at ~0.5 fps, so derive alpha from elapsed time --
    // fast updates stay smooth, slow updates snap to the new read immediately.
    const now = performance.now();
    const dt = live.smoothedAt ? (now - live.smoothedAt) / 1000 : 0;
    live.smoothedAt = now;
    const expressions = primary.expressions || {};
    if (!live.smoothed) {
      live.smoothed = {};
      for (const key of LIVE_EXPRESSIONS) live.smoothed[key] = expressions[key] || 0;
    } else {
      const alpha = Math.min(1, 1 - Math.exp(-dt / 0.22));
      for (const key of LIVE_EXPRESSIONS) {
        live.smoothed[key] = live.smoothed[key] * (1 - alpha) + (expressions[key] || 0) * alpha;
      }
    }

    const info = classifyFace(live.smoothed);
    $("#liveMood").textContent = LIVE_LABEL[info.expression] || info.expression;
    if (info.distressed) setLiveState("distressed", "Distress signal · red box");
    else setLiveState("calm", "Calm · green box");

    const top = LIVE_EXPRESSIONS
      .map((key) => [key, live.smoothed[key] || 0])
      // Rank by the same weighted score used for the box decision so the bars
      // never contradict the readout, while the percentage stays the model's
      // raw estimate.
      .sort((a, b) => (b[1] * (LIVE_WEIGHT[b[0]] || 1)) - (a[1] * (LIVE_WEIGHT[a[0]] || 1)))
      .slice(0, 3);
    $("#liveExpressionBars").innerHTML = top.map(([key, value]) => {
      const color = LIVE_RED.has(key) ? LIVE_ALERT : LIVE_CALM;
      const pct = Math.round(value * 100);
      return `<div class="live-bar-row">
        <span class="live-bar-label">${esc(LIVE_LABEL[key] || key)}</span>
        <span class="live-bar-track"><span class="live-bar-fill" style="width:${Math.max(2, pct)}%;background:${color}"></span></span>
        <span class="live-bar-pct">${pct}%</span>
      </div>`;
    }).join("");
  }

  function setLiveState(kind, text) {
    const pill = $("#liveStatePill");
    pill.classList.remove("calm", "distressed", "idle");
    pill.classList.add(kind);
    pill.textContent = text;
  }

  function setLiveModelIdle() {
    $("#liveMood").textContent = "—";
    setLiveState("idle", "Waiting for camera");
  }

  function resetLiveReadout({ idleText = "Waiting for camera", idleClass = "idle" } = {}) {
    live.smoothed = null;
    live.smoothedAt = 0;
    live.missedRuns = 0;
    $("#liveMood").textContent = "—";
    setLiveState(idleClass, idleText);
    $("#liveExpressionBars").innerHTML = "";
    $("#liveFaces").textContent = "0";
    $("#liveFps").textContent = "—";
    $("#liveHudFaces").textContent = "0 faces";
    $("#liveHudFps").textContent = "—";
    $("#liveNotice").hidden = true;
  }

  /* ── Events ───────────────────────────────────────────────────────────── */

  function bindEvents() {
    // Routing
    window.addEventListener("hashchange", () => setView(viewFromHash(), { fromHash: true }));

    // Refresh
    $("#refreshBtn").addEventListener("click", () => loadData({ manual: true }));
    $("#offlineRetry").addEventListener("click", () => loadData({ manual: true }));

    let refreshTimer = null;
    const startTimer = () => {
      if (refreshTimer) window.clearInterval(refreshTimer);
      if (state.refreshSeconds > 0) {
        refreshTimer = window.setInterval(() => {
          if (!document.hidden) loadData();
        }, state.refreshSeconds * 1000);
      }
    };
    $("#refreshInterval").addEventListener("change", (e) => {
      state.refreshSeconds = Number(e.target.value);
      startTimer();
      toast(state.refreshSeconds ? `Auto-refresh every ${state.refreshSeconds}s` : "Auto-refresh paused");
    });
    startTimer();

    // Activity range
    $("#activityRange").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-range]");
      if (!btn) return;
      state.activityRange = btn.dataset.range;
      $$("#activityRange button").forEach((b) => b.classList.toggle("is-active", b === btn));
      renderActivity();
    });

    // Chart tooltip
    $("#activityChart").addEventListener("pointermove", handleChartPointer);
    $("#activityChart").addEventListener("pointerleave", () => {
      const tip = $(".chart-tip", $("#activityChart"));
      if (tip) tip.classList.remove("is-visible");
    });

    // Incident filters
    let searchTimer = null;
    $("#searchInput").addEventListener("input", (e) => {
      const value = e.target.value;
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        state.filters.search = value;
        renderIncidentsTable();
      }, 140);
    });
    $("#typeFilter").addEventListener("change", (e) => {
      state.filters.type = e.target.value;
      renderIncidentsTable();
    });
    $("#cameraFilter").addEventListener("change", (e) => {
      state.filters.camera = e.target.value;
      renderIncidentsTable();
    });
    $("#timeFilter").addEventListener("change", (e) => {
      state.filters.range = e.target.value;
      renderIncidentsTable();
    });
    $("#severityChips").addEventListener("click", (e) => {
      const chip = e.target.closest("button[data-severity]");
      if (!chip) return;
      state.filters.severity = chip.dataset.severity;
      $$("#severityChips .chip").forEach((c) => c.classList.toggle("is-active", c === chip));
      renderIncidentsTable();
    });
    $("#clearFilters").addEventListener("click", clearFilters);
    $("#incidentsEmpty").addEventListener("click", (e) => {
      if (e.target.closest("[data-clear-filters]")) clearFilters();
    });

    // Row selection → drawer
    const onRowActivate = (event) => {
      const row = event.target.closest("tr[data-id]");
      if (!row) return;
      if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
      if (event.type === "keydown") event.preventDefault();
      openDrawer(Number(row.dataset.id), row);
    };
    $("#recentTableBody").addEventListener("click", onRowActivate);
    $("#incidentsTableBody").addEventListener("click", onRowActivate);
    $("#recentTableBody").addEventListener("keydown", onRowActivate);
    $("#incidentsTableBody").addEventListener("keydown", onRowActivate);

    // Drawer close
    $("#drawerOverlay").addEventListener("click", () => closeDrawer());
    $("#drawer").addEventListener("click", (e) => {
      if (e.target.closest("[data-close-drawer]")) closeDrawer();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (live.open) {
        closeLiveModal();
        return;
      }
      if (!$("#drawer").hidden) closeDrawer();
    });

    // Live camera
    $("#openLiveBtn").addEventListener("click", openLiveModal);
    $("#liveCloseBtn").addEventListener("click", closeLiveModal);
    $("#liveModal").addEventListener("click", (e) => {
      if (e.target.closest("[data-close-live]")) closeLiveModal();
    });
    $("#liveStartBtn").addEventListener("click", startLiveCamera);
    $("#liveStopBtn").addEventListener("click", stopLiveCamera);
    window.addEventListener("beforeunload", () => {
      if (live.stream) live.stream.getTracks().forEach((track) => track.stop());
    });

    // Retention
    $("#retentionBtn").addEventListener("click", runRetention);

    // Footer clock
    const tick = () => { $("#footClock").textContent = fmtClock.format(new Date()); };
    tick();
    window.setInterval(tick, 1000);
  }

  function clearFilters() {
    state.filters = { search: "", type: "", camera: "", range: "24h", severity: "all" };
    $("#searchInput").value = "";
    $("#typeFilter").value = "";
    $("#cameraFilter").value = "";
    $("#timeFilter").value = "24h";
    $$("#severityChips .chip").forEach((c) => c.classList.toggle("is-active", c.dataset.severity === "all"));
    renderIncidentsTable();
  }

  async function runRetention() {
    const btn = $("#retentionBtn");
    const output = $("#retentionOutput");
    btn.disabled = true;
    btn.textContent = "Running sweep…";
    output.hidden = false;
    output.textContent = "POST /retention/run …";
    try {
      const result = await fetchJson("/retention/run", { method: "POST" });
      output.textContent = JSON.stringify(result, null, 2);
      toast("Retention sweep completed");
    } catch (error) {
      output.textContent = `Retention sweep failed:\n${error.message}`;
      toast("Retention sweep failed", true);
    } finally {
      btn.disabled = false;
      btn.textContent = "Run retention now";
    }
  }

  /* ── Boot ─────────────────────────────────────────────────────────────── */

  function boot() {
    bindEvents();
    setView(viewFromHash(), { fromHash: true });
    loadData({ manual: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
