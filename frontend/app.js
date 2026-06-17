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

  // --- Clock ---------------------------------------------------------------
  function tickClock() {
    const now = new Date();
    let h = now.getHours();
    const m = String(now.getMinutes()).padStart(2, "0");
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    $("clock").textContent = `${h}:${m} ${ampm}`;
    $("date").textContent = now.toLocaleDateString(undefined, {
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
    const mode = (cfg.wind && cfg.wind.arrow_mode) || "from";
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
    $("wind-gust").textContent = num(w.wind_gust_mph);
    $("wind-cardinal").textContent = w.wind_direction_cardinal || "--";
    setNeedle(arrowBearing(w.wind_direction_deg));
    const gustEl = document.querySelector(".wind-gust");
    const gusty = w.wind_gust_mph && w.wind_speed_mph && w.wind_gust_mph - w.wind_speed_mph >= 8;
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
    return new Date(iso).toLocaleDateString(undefined, { weekday: "short" });
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
    $("moon").textContent = c.moon_icon ? `${c.moon_icon} ${c.moon_phase_name || ""}`.trim() : "";
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

  // Dual-line temp + pressure trend graph over the next ~24h, drawn as SVG.
  function renderGraph(hourly) {
    const tEl = $("graph-temp-line");
    const pEl = $("graph-pres-line");
    const pts = (hourly || [])
      .slice(0, 24)
      .filter((h) => h.temperature_f != null && h.pressure_inhg != null);
    if (pts.length < 2) {
      tEl.removeAttribute("d");
      pEl.removeAttribute("d");
      return;
    }
    const W = 1000, H = 300, pad = 22;
    const temps = pts.map((p) => p.temperature_f);
    const press = pts.map((p) => p.pressure_inhg);
    const tMin = Math.min(...temps), tMax = Math.max(...temps);
    const pMin = Math.min(...press), pMax = Math.max(...press);
    const x = (i) => (i / (pts.length - 1)) * W;
    const scaleY = (v, lo, hi) => H - pad - ((v - lo) / ((hi - lo) || 1)) * (H - 2 * pad);
    const path = (vals, lo, hi) =>
      vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${scaleY(v, lo, hi).toFixed(1)}`).join(" ");

    tEl.setAttribute("d", path(temps, tMin, tMax));
    pEl.setAttribute("d", path(press, pMin, pMax));
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
    const more = alerts.length > 1 ? `  (+${alerts.length - 1} more)` : "";
    banner.textContent = `⚠ ${a.event || a.headline || "Weather Alert"}${more}`;
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
