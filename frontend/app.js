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

    // Today's hi/lo from daily[0], precip chance from daily[0]
    if (daily && daily[0]) {
      $("hi-lo").innerHTML = `H: ${num(daily[0].temp_max_f)}°&nbsp;&nbsp;L: ${num(daily[0].temp_min_f)}°`;
      $("precip-chance").textContent = num(daily[0].precip_probability_pct);
    }

    // Wind
    $("wind-speed").textContent = num(c.wind_speed_mph);
    $("wind-gust").textContent = num(c.wind_gust_mph);
    $("wind-cardinal").textContent = c.wind_direction_cardinal || "--";
    setNeedle(arrowBearing(c.wind_direction_deg));
    const gustEl = document.querySelector(".wind-gust");
    const gusty = c.wind_gust_mph && c.wind_speed_mph && c.wind_gust_mph - c.wind_speed_mph >= 8;
    gustEl.classList.toggle("high", !!gusty);
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
        <div class="d-pop">${pop >= 5 ? "☔ " + num(pop) + "%" : ""}</div>`;
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
      text.textContent = "Live";
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
      renderDaily(data.daily);
      renderAlerts(data.alerts);
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
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
