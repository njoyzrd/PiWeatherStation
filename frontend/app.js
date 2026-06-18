/* WeatherPi dashboard logic.
 *
 * - Clock ticks every second (feels live without faking weather data).
 * - Polls the LOCAL backend /api/all on an interval (default from /api/config).
 * - Animates the wind compass needle smoothly toward the latest direction.
 * The frontend never calls third-party APIs directly — only the local backend.
 */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const num = (v, digits = 0) =>
    v === null || v === undefined || Number.isNaN(v) ? "--" : Number(v).toFixed(digits);

  let cfg = { refresh: { frontend_seconds: 15 }, units: {} };
  let lastSuccess = null; // Date of last good payload, for "updated X ago"
  let liveWind = null; // { obs, receivedAt } — latest live wind reading, if any
  let lastForecastWind = null; // latest forecast current conditions, for gust fallback

  // --- Clock ---------------------------------------------------------------
  function tickClock() {
    const now = new Date();
    // Show the configured location's local time, not the Pi's system timezone
    // (e.g. McFarland is Central even if the Pi's clock is set to Eastern).
    const tz = (cfg.location && cfg.location.timezone) || undefined;
    $("clock").textContent = now.toLocaleTimeString(undefined, {
      timeZone: tz,
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
    $("date").textContent = now.toLocaleDateString(undefined, {
      timeZone: tz,
      weekday: "long",
      month: "long",
      day: "numeric",
    });
    updateAgo();
  }

  function updateAgo() {
    // Keep the live-wind "X min ago" label ticking for periodic (non-live) sources.
    if (isLiveWindFresh() && liveWind.obs && !liveWind.obs.live) {
      setWindSource(liveWind.obs);
    }
    if (!lastSuccess) return;
    const secs = Math.round((Date.now() - lastSuccess.getTime()) / 1000);
    let txt;
    if (secs < 60) txt = "Updated just now";
    else if (secs < 3600) txt = `Updated ${Math.floor(secs / 60)} min ago`;
    else txt = `Updated ${Math.floor(secs / 3600)} h ago`;
    $("updated").textContent = txt;
  }

  // --- Compass ticks (built once) -----------------------------------------
  function buildCompassTicks() {
    const g = $("compass-ticks");
    if (!g) return;
    for (let i = 0; i < 72; i++) {
      const major = i % 9 === 0;
      const angle = (i * 5 * Math.PI) / 180;
      const r1 = 92;
      const r2 = major ? 80 : 86;
      const x1 = 100 + r1 * Math.sin(angle);
      const y1 = 100 - r1 * Math.cos(angle);
      const x2 = 100 + r2 * Math.sin(angle);
      const y2 = 100 - r2 * Math.cos(angle);
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", x1.toFixed(1));
      line.setAttribute("y1", y1.toFixed(1));
      line.setAttribute("x2", x2.toFixed(1));
      line.setAttribute("y2", y2.toFixed(1));
      line.setAttribute("class", major ? "compass-tick major" : "compass-tick");
      g.appendChild(line);
    }
  }

  // Bearing the arrow should point to. Open-Meteo reports the direction the wind
  // comes FROM (meteorological convention). "from" mode points the arrow into the
  // wind — i.e. at the windward side being hit; "to" points the way it travels.
  function arrowBearing(deg) {
    if (deg === null || deg === undefined) return null;
    const mode = (cfg.wind && cfg.wind.arrow_mode) || "to";
    return mode === "to" ? (deg + 180) % 360 : deg;
  }

  // Track unwrapped rotation so the needle always takes the short way around.
  let needleAngle = 0;
  function setNeedle(deg) {
    if (deg === null || deg === undefined) return;
    let delta = ((deg - (needleAngle % 360)) + 540) % 360 - 180;
    needleAngle += delta;
    $("needle").style.transform = `rotate(${needleAngle.toFixed(1)}deg)`;
  }

  // Optional aerial/satellite image of the property behind the compass, oriented
  // north-up so the wind arrow lines up with the real-world layout of the house.
  function setupHouseImage() {
    const w = cfg.wind || {};
    if (!w.house_image) return;
    const img = $("compass-bg");
    img.style.setProperty("--house-rot", (Number(w.house_image_rotation_deg) || 0) + "deg");
    img.onload = () => {
      img.classList.remove("hidden");
      $("compass").classList.add("has-bg");
    };
    img.onerror = () => console.warn("compass house image failed to load:", w.house_image);
    img.src = w.house_image;
  }

  // --- Wind: live source (WebSocket) with forecast fallback ----------------
  const LIVE_STALE_MS = 12 * 60 * 1000; // fall back to forecast if no live msg this long

  function isLiveWindFresh() {
    return !!liveWind && Date.now() - liveWind.receivedAt < LIVE_STALE_MS;
  }

  // Render a wind reading from either the forecast (/api/all) or a live obs.
  function applyWind(w) {
    $("wind-speed").textContent = num(w.wind_speed_mph);
    // Live observations (e.g. NWS stations) frequently omit gusts; fall back to
    // the latest forecast gust so the field isn't blank when live wind is on.
    const gust = w.wind_gust_mph ?? (lastForecastWind && lastForecastWind.wind_gust_mph);
    $("wind-gust").textContent = num(gust);
    $("wind-cardinal").textContent = w.wind_direction_cardinal || "--";
    setNeedle(arrowBearing(w.wind_direction_deg));
    const gustEl = document.querySelector(".wind-gust");
    const gusty = gust && w.wind_speed_mph && gust - w.wind_speed_mph >= 8;
    gustEl.classList.toggle("high", !!gusty);
  }

  function srcLabel(source) {
    if (!source) return "";
    if (source === "simulator") return "Simulated";
    if (source.startsWith("nws-station:")) return source.split(":")[1];
    return source;
  }

  function agoText(iso) {
    if (!iso) return "";
    const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (secs < 90) return "just now";
    if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
    return `${Math.floor(secs / 3600)} h ago`;
  }

  function setWindSource(obs) {
    const el = $("wind-source");
    if (!obs) { el.textContent = "Forecast"; return; }
    if (obs.live) {
      el.innerHTML = `<span class="ld live"></span> LIVE · ${srcLabel(obs.source)}`;
    } else {
      const ago = agoText(obs.observed_at);
      el.innerHTML = `<span class="ld obs"></span> ${srcLabel(obs.source)}${ago ? " · " + ago : ""}`;
    }
  }

  function connectLiveWind() {
    let retry = 1000;
    const open = () => {
      let ws;
      try {
        const proto = location.protocol === "https:" ? "wss" : "ws";
        ws = new WebSocket(`${proto}://${location.host}/ws/live`);
      } catch (_) {
        scheduleReconnect();
        return;
      }
      ws.onmessage = (ev) => {
        try {
          const obs = JSON.parse(ev.data);
          liveWind = { obs, receivedAt: Date.now() };
          applyWind(obs);
          setWindSource(obs);
          retry = 1000;
        } catch (_) { /* ignore malformed */ }
      };
      ws.onclose = () => { liveWind = null; scheduleReconnect(); };
      ws.onerror = () => { try { ws.close(); } catch (_) {} };
    };
    const scheduleReconnect = () => {
      setTimeout(open, retry);
      retry = Math.min(retry * 2, 15000);
    };
    open();
  }

  // --- Time formatting from ISO --------------------------------------------
  function fmtHour(iso) {
    const d = new Date(iso);
    let h = d.getHours();
    const ampm = h >= 12 ? "p" : "a";
    h = h % 12 || 12;
    return `${h}${ampm}`;
  }
  function fmtClockTime(iso) {
    if (!iso) return "--:--";
    const d = new Date(iso);
    let h = d.getHours();
    const m = String(d.getMinutes()).padStart(2, "0");
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return `${h}:${m} ${ampm}`;
  }
  function dayName(iso, idx) {
    if (idx === 0) return "Today";
    // iso is a calendar date "YYYY-MM-DD"; parse the parts as a local date so the
    // weekday isn't shifted by UTC interpretation (which made tomorrow read as today).
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short" });
  }

  // --- Renderers -----------------------------------------------------------
  function renderCurrent(c, daily) {
    if (!c) return;
    $("location"); // location set separately
    $("temp").textContent = num(c.temperature_f);
    $("feels-like").textContent = num(c.feels_like_f);
    $("condition-text").textContent = c.condition_text || "—";
    $("condition-icon").textContent = c.condition_icon || "—";
    $("condition-summary").textContent = c.condition_text || "—";
    $("cloud-cover").textContent = num(c.cloud_cover_pct);
    $("humidity").textContent = num(c.humidity_pct);
    $("dew-point").textContent = num(c.dew_point_f);
    $("pressure").textContent = pressureValue(c.pressure_inhg);
    $("uv-index").textContent = num(c.uv_index);
    $("sunrise").textContent = fmtClockTime(c.sunrise);
    $("sunset").textContent = fmtClockTime(c.sunset);
    $("visibility").textContent = num(c.visibility_mi, 1);
    renderPressureTrend(c.pressure_trend);
    renderMoon(c);

    // Today's hi/lo from daily[0], precip chance from daily[0]
    if (daily && daily[0]) {
      $("hi-lo").innerHTML = `H: ${num(daily[0].temp_max_f)}°&nbsp;&nbsp;L: ${num(daily[0].temp_min_f)}°`;
      $("precip-chance").textContent = num(daily[0].precip_probability_pct);
    }

    // Wind — a fresh live source is authoritative; otherwise use the forecast.
    lastForecastWind = c; // remember for gust fallback when live wind lacks gusts
    if (!isLiveWindFresh()) {
      applyWind(c);
      setWindSource(null);
    }
  }

  function pressureValue(inhg) {
    const unit = (cfg.units && cfg.units.pressure) || "inhg";
    if (inhg === null || inhg === undefined) return "--";
    if (unit === "hpa") {
      $("pressure-unit").textContent = "hPa";
      return num(inhg / 0.0295299830714);
    }
    $("pressure-unit").textContent = "inHg";
    return num(inhg, 2);
  }

  function renderPressureTrend(trend) {
    const el = $("pressure-trend");
    if (trend === "rising") { el.textContent = "▲"; el.className = "trend up"; }
    else if (trend === "falling") { el.textContent = "▼"; el.className = "trend down"; }
    else if (trend === "steady") { el.textContent = "→"; el.className = "trend steady"; }
    else { el.textContent = ""; el.className = "trend"; }
  }

  function renderMoon(c) {
    const el = $("moon");
    if (!c.moon_icon) { el.innerHTML = ""; return; }
    el.innerHTML =
      `<span class="moon-icon">${c.moon_icon}</span>` +
      (c.moon_phase_name ? `<span class="moon-name">${c.moon_phase_name}</span>` : "");
  }

  function renderAirQuality(aq) {
    const metric = $("aqi-metric");
    if (!aq || aq.us_aqi === null || aq.us_aqi === undefined) {
      $("aqi").textContent = "--";
      $("aqi-cat").textContent = "";
      metric.className = "metric";
      return;
    }
    $("aqi").textContent = aq.us_aqi;
    $("aqi-cat").textContent = aq.category || "";
    metric.className = "metric aqi-" + (aq.level != null ? aq.level : 0);
  }

  function renderNowcast(nc) {
    const sumEl = $("nowcast-summary");
    const barEl = $("nowcast-bar");
    if (!nc) { sumEl.textContent = ""; barEl.innerHTML = ""; sumEl.className = "nowcast-summary"; return; }
    sumEl.textContent = nc.summary || "";
    const wet = nc.precipitating || nc.starts_in_min != null;
    sumEl.className = "nowcast-summary" + (wet ? " wet" : "");
    const pts = nc.points || [];
    const max = Math.max(0.02, ...pts.map((p) => p.precip_in || 0));
    barEl.innerHTML = pts
      .map((p) => {
        const v = p.precip_in || 0;
        const h = v > 0.001 ? Math.max(2, Math.round((v / max) * 14)) : 1;
        return `<i class="${v > 0.001 ? "" : "dry"}" style="height:${h}px"></i>`;
      })
      .join("");
  }

  // Catmull-Rom spline -> cubic Bézier, for smooth chart curves.
  function smoothPath(pts) {
    if (pts.length < 2) return "";
    const t = 0.18; // smoothing tension
    let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i === 0 ? 0 : i - 1];
      const p1 = pts[i];
      const p2 = pts[i + 1];
      const p3 = pts[i + 2 < pts.length ? i + 2 : i + 1];
      const c1x = p1[0] + (p2[0] - p0[0]) * t;
      const c1y = p1[1] + (p2[1] - p0[1]) * t;
      const c2x = p2[0] - (p3[0] - p1[0]) * t;
      const c2y = p2[1] - (p3[1] - p1[1]) * t;
      d += ` C${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
    }
    return d;
  }

  // Temp line + pressure bars over the next ~24h on one chart, drawn as SVG.
  function renderGraph(hourly) {
    const tEl = $("graph-temp-line");
    const gridEl = $("graph-grid");
    const barsEl = $("graph-pres-bars");
    const pts = (hourly || [])
      .slice(0, 24)
      .filter((h) => h.temperature_f != null && h.pressure_inhg != null);
    if (pts.length < 2) {
      tEl.removeAttribute("d");
      gridEl.innerHTML = "";
      barsEl.innerHTML = "";
      return;
    }
    const W = 1000, H = 300, pad = 22;
    const n = pts.length;
    const innerH = H - 2 * pad;
    const temps = pts.map((p) => p.temperature_f);
    const press = pts.map((p) => p.pressure_inhg);
    const tMin = Math.min(...temps), tMax = Math.max(...temps);
    const pMin = Math.min(...press), pMax = Math.max(...press);
    // Bars and the line share slot-centered x positions so they line up.
    const x = (i) => ((i + 0.5) / n) * W;
    const scaleY = (v, lo, hi) => H - pad - ((v - lo) / ((hi - lo) || 1)) * innerH;
    const toPts = (vals, lo, hi) => vals.map((v, i) => [x(i), scaleY(v, lo, hi)]);

    // Background grid: horizontal rows + a few vertical columns.
    const ROWS = 4, VCOLS = 6, lines = [];
    for (let r = 0; r <= ROWS; r++) {
      const y = (pad + (innerH * r) / ROWS).toFixed(1);
      lines.push(`<line x1="0" y1="${y}" x2="${W}" y2="${y}" />`);
    }
    for (let c = 0; c <= VCOLS; c++) {
      const gx = ((c / VCOLS) * W).toFixed(1);
      lines.push(`<line class="v" x1="${gx}" y1="${pad}" x2="${gx}" y2="${H - pad}" />`);
    }
    gridEl.innerHTML = lines.join("");

    // Pressure as bars. Pressure swings in a narrow band, so map it into a
    // 18%..90% height window rather than zeroing out the lowest reading.
    const pSpan = (pMax - pMin) || 1;
    const slot = W / n;
    const bw = slot * 0.6;
    barsEl.innerHTML = press
      .map((v, i) => {
        const h = (0.18 + 0.72 * ((v - pMin) / pSpan)) * innerH;
        const y = (H - pad - h).toFixed(1);
        const bx = (x(i) - bw / 2).toFixed(1);
        return `<rect x="${bx}" y="${y}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="2" />`;
      })
      .join("");

    // Temperature line on top.
    tEl.setAttribute("d", smoothPath(toPts(temps, tMin, tMax)));
    $("temp-hi").textContent = Math.round(tMax) + "°";
    $("temp-lo").textContent = Math.round(tMin) + "°";
    $("pres-hi").textContent = pMax.toFixed(2);
    $("pres-lo").textContent = pMin.toFixed(2);
    $("gx0").textContent = fmtHour(pts[0].time);
    $("gx1").textContent = fmtHour(pts[Math.floor((pts.length - 1) / 2)].time);
    $("gx2").textContent = fmtHour(pts[pts.length - 1].time);
  }

  function renderHourly(hourly) {
    const el = $("hourly");
    el.innerHTML = "";
    const maxCards = 12;
    (hourly || []).slice(0, maxCards).forEach((h) => {
      const div = document.createElement("div");
      div.className = "hour";
      const pop = h.precip_probability_pct;
      div.innerHTML = `
        <div class="h-time">${fmtHour(h.time)}</div>
        <div class="h-icon">${h.condition_icon || ""}</div>
        <div class="h-temp">${num(h.temperature_f)}°</div>
        <div class="h-pop ${pop >= 20 ? "" : "dry"}">${pop >= 5 ? num(pop) + "%" : ""}</div>`;
      el.appendChild(div);
    });
  }

  function renderDaily(daily) {
    const el = $("daily");
    el.innerHTML = "";
    (daily || []).slice(0, 7).forEach((d, i) => {
      const div = document.createElement("div");
      div.className = "day" + (i === 0 ? " today" : "");
      const pop = d.precip_probability_pct;
      div.innerHTML = `
        <div class="d-name">${dayName(d.date, i)}</div>
        <div class="d-icon">${d.condition_icon || ""}</div>
        <div class="d-temps"><span class="d-hi">${num(d.temp_max_f)}°</span>
          <span class="d-lo">${num(d.temp_min_f)}°</span></div>
        <div class="d-pop">${
          d.snowfall_in > 0
            ? "❄️ " + num(d.snowfall_in, 1) + "in"
            : pop >= 5
            ? "☔ " + num(pop) + "%"
            : ""
        }</div>`;
      el.appendChild(div);
    });
  }

  // NWS description text is hard-wrapped with newlines; collapse those within a
  // paragraph to spaces while keeping blank-line paragraph breaks.
  function cleanAlertText(s) {
    if (!s) return "";
    return s
      .split(/\n\s*\n/)
      .map((p) => p.replace(/\s*\n\s*/g, " ").trim())
      .filter(Boolean)
      .join("\n\n");
  }

  function renderAlerts(alerts) {
    const banner = $("alert-banner");
    if (!alerts || alerts.length === 0) {
      banner.classList.add("hidden");
      return;
    }
    const a = alerts[0];
    const sev = (a.severity || "").toLowerCase();
    banner.className = "alert-banner";
    if (sev.includes("extreme") || sev.includes("severe")) banner.classList.add("severe");
    else if (sev.includes("moderate")) banner.classList.add("moderate");
    const more = alerts.length > 1 ? ` (+${alerts.length - 1} more)` : "";
    $("alert-title").textContent = `⚠ ${a.event || a.headline || "Weather Alert"}${more}`;
    $("alert-body").textContent = cleanAlertText(a.description || a.headline || "");
  }

  function renderStatus(status) {
    const dot = $("status-dot");
    const text = $("status-text");
    dot.className = "status-dot";
    if (status && status.api_ok && !status.stale) {
      dot.classList.add("ok");
      text.textContent =
        status.source && status.source !== "open-meteo" ? `Live · via ${status.source}` : "Live";
    } else if (status && status.stale && status.last_successful_refresh) {
      dot.classList.add("stale");
      text.textContent = "Stale data";
    } else {
      dot.classList.add("bad");
      text.textContent = status && status.last_error ? "Offline" : "Connecting…";
    }
  }

  // --- Fetch loop ----------------------------------------------------------
  async function refresh() {
    try {
      const resp = await fetch("/api/all", { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      if (data.location) $("location").textContent = data.location.name;
      renderCurrent(data.current, data.daily);
      renderHourly(data.hourly);
      renderGraph(data.hourly);
      renderDaily(data.daily);
      renderAlerts(data.alerts);
      renderAirQuality(data.air_quality);
      renderNowcast(data.nowcast);
      renderStatus(data.status);

      if (data.status && data.status.api_ok && data.status.last_successful_refresh) {
        lastSuccess = new Date(data.status.last_successful_refresh);
      }
      updateAgo();
    } catch (err) {
      console.error("refresh failed", err);
      renderStatus({ api_ok: false, stale: true, last_error: String(err) });
    }
  }

  // Auto-reload the kiosk after a deploy: the backend reports its git revision,
  // which changes when the service restarts on a new version.
  let appVersion = null;
  async function checkVersion() {
    try {
      const r = await fetch("/api/version", { cache: "no-store" });
      if (!r.ok) return;
      const { version } = await r.json();
      if (!version || version === "unknown") return;
      if (appVersion && version !== appVersion) {
        console.info("New version deployed, reloading:", appVersion, "->", version);
        location.reload();
      }
      appVersion = version;
    } catch (_) {
      /* ignore — backend may be mid-restart */
    }
  }

  // --- Settings + status overlays ------------------------------------------
  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let settingsState = { active_location: null, presets: [], max_presets: 4 };

  function openOverlay(id) { $(id).classList.remove("hidden"); }
  function closeOverlay(id) { $(id).classList.add("hidden"); }

  function setMsg(text, kind) {
    const el = $("set-msg");
    el.textContent = text || "";
    el.className = "set-msg" + (kind ? " " + kind : "");
  }

  function locLabel(loc) {
    if (!loc) return "—";
    return loc.name;
  }
  function locCoords(loc) {
    if (!loc) return "";
    const lat = Number(loc.latitude).toFixed(4);
    const lon = Number(loc.longitude).toFixed(4);
    return `${lat}, ${lon}${loc.timezone ? " · " + loc.timezone : ""}`;
  }

  function renderSettings() {
    const s = settingsState;
    $("set-current").innerHTML =
      `${esc(locLabel(s.active_location))}<small>${esc(locCoords(s.active_location))}</small>`;

    const max = s.max_presets || 4;
    $("set-preset-count").textContent = `(${s.presets.length}/${max})`;
    const active = s.active_location || {};
    $("set-presets").innerHTML = s.presets
      .map((p, i) => {
        const isActive =
          Math.abs((p.latitude || 0) - (active.latitude || 0)) < 1e-4 &&
          Math.abs((p.longitude || 0) - (active.longitude || 0)) < 1e-4;
        return `<div class="preset${isActive ? " active" : ""}">
          <button class="preset-pick" data-pick="${i}" type="button">
            <span class="pn">${esc(p.name)}</span>
            <span class="pc">${esc(locCoords(p))}</span>
          </button>
          <button class="preset-del" data-del="${i}" type="button" title="Remove preset" aria-label="Remove">✕</button>
        </div>`;
      })
      .join("") || `<div class="set-dim">No presets saved yet.</div>`;

    // Disable "save preset" when full or the active location is already saved.
    const dupe = s.presets.some(
      (p) =>
        Math.abs((p.latitude || 0) - (active.latitude || 0)) < 1e-4 &&
        Math.abs((p.longitude || 0) - (active.longitude || 0)) < 1e-4
    );
    const full = s.presets.length >= max;
    const btn = $("set-save-preset");
    btn.disabled = dupe || full || !s.active_location;
    btn.textContent = full
      ? `Preset limit reached (${max})`
      : dupe
      ? "Current location is already a preset"
      : "＋ Save current location as a preset";
  }

  async function loadSettings() {
    try {
      const r = await fetch("/api/settings", { cache: "no-store" });
      if (r.ok) { settingsState = await r.json(); renderSettings(); }
    } catch (_) { /* ignore */ }
  }

  async function applyLocation(loc) {
    setMsg("Switching location…", "busy");
    try {
      const r = await fetch("/api/settings/location", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loc),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      settingsState = await r.json();
      setMsg("Location updated — refreshing…", "ok");
      setTimeout(() => location.reload(), 900);
    } catch (err) {
      setMsg("Could not change location: " + err.message, "err");
    }
  }

  async function putPresets(presets) {
    const r = await fetch("/api/settings/presets", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ presets }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    settingsState = await r.json();
    renderSettings();
  }

  async function searchLocation(q) {
    const box = $("set-results");
    box.innerHTML = `<div class="set-dim">Searching…</div>`;
    try {
      const r = await fetch(`/api/geocode?q=${encodeURIComponent(q)}`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const { results } = await r.json();
      if (!results || !results.length) { box.innerHTML = `<div class="set-dim">No matches.</div>`; return; }
      box.innerHTML = results
        .map(
          (x, i) => `<button class="set-result" data-res="${i}" type="button">
            <span class="rn">${esc(x.name)}</span>
            <span class="rc">${Number(x.latitude).toFixed(2)}, ${Number(x.longitude).toFixed(2)}</span>
          </button>`
        )
        .join("");
      box._results = results;
    } catch (err) {
      box.innerHTML = `<div class="set-dim">Search failed: ${esc(err.message)}</div>`;
    }
  }

  function wireSettings() {
    $("btn-settings").addEventListener("click", () => { loadSettings(); setMsg(""); openOverlay("settings-overlay"); });

    $("set-presets").addEventListener("click", async (e) => {
      const pick = e.target.closest("[data-pick]");
      const del = e.target.closest("[data-del]");
      if (pick) { applyLocation(settingsState.presets[+pick.dataset.pick]); return; }
      if (del) {
        const i = +del.dataset.del;
        const next = settingsState.presets.filter((_, idx) => idx !== i);
        try { await putPresets(next); } catch (err) { setMsg("Could not remove preset: " + err.message, "err"); }
      }
    });

    $("set-save-preset").addEventListener("click", async () => {
      if (!settingsState.active_location) return;
      const next = settingsState.presets.concat([settingsState.active_location]).slice(0, settingsState.max_presets);
      try { await putPresets(next); setMsg("Saved to presets.", "ok"); }
      catch (err) { setMsg("Could not save preset: " + err.message, "err"); }
    });

    $("set-search-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const q = $("set-search-input").value.trim();
      if (q.length >= 2) searchLocation(q);
    });

    $("set-results").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-res]");
      if (!btn) return;
      const results = $("set-results")._results || [];
      const x = results[+btn.dataset.res];
      if (x) applyLocation({ name: x.name, latitude: x.latitude, longitude: x.longitude, timezone: x.timezone });
    });

    $("man-apply").addEventListener("click", () => {
      const name = $("man-name").value.trim();
      const lat = parseFloat($("man-lat").value);
      const lon = parseFloat($("man-lon").value);
      const tz = $("man-tz").value.trim();
      if (!name || Number.isNaN(lat) || Number.isNaN(lon)) {
        setMsg("Enter a name, latitude, and longitude.", "err");
        return;
      }
      applyLocation({ name, latitude: lat, longitude: lon, timezone: tz || null });
    });
  }

  // --- Status / raw-data overlay -------------------------------------------
  function agoFromSeconds(s) {
    if (s == null) return "never";
    if (s < 90) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return `${Math.floor(s / 86400)} d ago`;
  }
  function freshClass(s) { return s != null && s < 1800 ? "src-fresh" : "src-stale"; }

  function humanKey(k) { return k.replace(/_/g, " ").replace(/\bpct\b/, "%").replace(/\binhg\b/i, "inHg").replace(/\bmph\b/i, "mph"); }
  function fmtVal(v) {
    if (v === null || v === undefined || v === "") return `<span class="v null">—</span>`;
    if (typeof v === "boolean") return `<span class="v">${v ? "yes" : "no"}</span>`;
    if (typeof v === "number") return `<span class="v">${Number.isInteger(v) ? v : v.toFixed(2)}</span>`;
    return `<span class="v">${esc(v)}</span>`;
  }
  function kvTable(obj, skip = []) {
    const rows = Object.entries(obj || {})
      .filter(([k]) => !skip.includes(k))
      .map(([k, v]) => `<div class="row"><span class="k">${esc(humanKey(k))}</span>${fmtVal(v)}</div>`)
      .join("");
    return `<div class="kv">${rows}</div>`;
  }

  function renderStatusData(d) {
    const body = $("status-body");
    const srcCards = (d.sources || [])
      .map((s) => {
        const cls = s.ok ? "ok" : "bad";
        const fresh = s.fetched_at ? `<span class="${freshClass(s.age_seconds)}">${agoFromSeconds(s.age_seconds)}</span>` : "never fetched";
        return `<div class="src-card">
          <div class="sn"><span class="src-dot ${cls}"></span>${esc(s.name)}</div>
          <div class="sr">${esc(s.role)}</div>
          <div class="sa">Updated ${fresh}${s.error ? ` · <span class="src-stale">${esc(s.error)}</span>` : ""}</div>
        </div>`;
      })
      .join("");

    const lw = d.live_wind || {};
    const lwHtml = lw.latest
      ? `<div class="data-section"><div class="data-h">Live wind · ${esc(lw.source)} · ${agoFromSeconds(lw.age_seconds)}</div>${kvTable(lw.latest)}</div>`
      : `<div class="data-section"><div class="data-h">Live wind</div><div class="set-dim">${lw.enabled ? "Waiting for first observation…" : "Disabled"}</div></div>`;

    const sections = [];
    sections.push(`<div class="src-grid">${srcCards}</div>`);
    sections.push(`<div class="data-section"><div class="data-h">Location</div>${kvTable(d.location)}</div>`);
    if (d.current) sections.push(`<div class="data-section"><div class="data-h">Current conditions (all fields)</div>${kvTable(d.current)}</div>`);
    if (d.air_quality) sections.push(`<div class="data-section"><div class="data-h">Air quality</div>${kvTable(d.air_quality)}</div>`);
    if (d.nowcast) sections.push(`<div class="data-section"><div class="data-h">Precipitation nowcast</div>${kvTable(d.nowcast, ["points"])}</div>`);
    sections.push(lwHtml);
    if (d.alerts && d.alerts.length) {
      const al = d.alerts.map((a) => kvTable(a)).join('<hr style="border:none;border-top:1px solid rgba(120,160,255,0.1);margin:0.6em 0">');
      sections.push(`<div class="data-section"><div class="data-h">Active alerts (${d.alerts.length})</div>${al}</div>`);
    }
    sections.push(`<details class="data-section"><summary>Hourly forecast — raw (${(d.hourly || []).length} points)</summary><div class="raw-json">${esc(JSON.stringify(d.hourly, null, 2))}</div></details>`);
    sections.push(`<details class="data-section"><summary>Daily forecast — raw (${(d.daily || []).length} days)</summary><div class="raw-json">${esc(JSON.stringify(d.daily, null, 2))}</div></details>`);
    body.innerHTML = sections.join("");
  }

  async function openStatus() {
    openOverlay("status-overlay");
    const body = $("status-body");
    body.innerHTML = `<div class="set-dim">Loading…</div>`;
    try {
      const r = await fetch("/api/raw", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      renderStatusData(await r.json());
    } catch (err) {
      body.innerHTML = `<div class="set-msg err">Could not load data: ${esc(err.message)}</div>`;
    }
  }

  function wireOverlays() {
    wireSettings();
    $("btn-status").addEventListener("click", openStatus);
    $("status-refresh").addEventListener("click", openStatus);
    document.querySelectorAll("[data-close]").forEach((b) =>
      b.addEventListener("click", () => closeOverlay(b.dataset.close)));
    // Click the dimmed backdrop or press Escape to close.
    document.querySelectorAll(".overlay").forEach((ov) =>
      ov.addEventListener("click", (e) => { if (e.target === ov) ov.classList.add("hidden"); }));
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") document.querySelectorAll(".overlay").forEach((ov) => ov.classList.add("hidden"));
    });
  }

  // --- Boot ----------------------------------------------------------------
  async function init() {
    buildCompassTicks();
    tickClock();
    setInterval(tickClock, 1000);

    try {
      const r = await fetch("/api/config", { cache: "no-store" });
      if (r.ok) cfg = Object.assign(cfg, await r.json());
    } catch (_) {
      /* fall back to defaults */
    }

    setupHouseImage();
    wireOverlays();
    await refresh();
    const everyMs = Math.max(5, (cfg.refresh && cfg.refresh.frontend_seconds) || 15) * 1000;
    setInterval(refresh, everyMs);
    connectLiveWind();
    checkVersion();
    setInterval(checkVersion, 60000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
