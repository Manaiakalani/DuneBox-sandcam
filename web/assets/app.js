// DuneBox dashboard client. Talks to depth_server.py: JSON state + PNG depth
// frames in, {"type": "command"} messages out, {"type": "ack"} replies back.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const THEME_LABELS = { terrain: "Terrain", heat: "Heat map", greyscale: "Greyscale", desert: "Desert" };
  const WATER_LEVEL = 0.46;        // renderer.WATER_LEVEL
  const CONTOUR_INTERVAL = 0.05;   // renderer.CONTOUR_INTERVAL (default)
  const RANGE_FORMAT = {
    set_contour_interval: (v) => `${Math.round(v * 100)}%`,
    set_sea_level: (v) => `${v >= 0 ? "+" : "−"}${Math.abs(Math.round(v * 100))}%`,
  };
  const ACK_TIMEOUT_MS = 4000;

  const params = new URLSearchParams(location.search);
  const httpBase = location.protocol.startsWith("http") ? location.origin : "http://127.0.0.1:8765";
  const wsUrl = params.get("ws") || httpBase.replace(/^http/, "ws") + "/ws";

  let pin = params.get("pin") || localStorage.getItem("dunebox.pin") || "";
  if (params.has("pin")) {
    localStorage.setItem("dunebox.pin", pin);
    params.delete("pin");
    history.replaceState(null, "", location.pathname + (params.size ? "?" + params : ""));
  }

  let ws = null;
  let state = null;
  let everConnected = false;
  let pinRequired = false;
  let retryDelay = 1000;
  let retryTimer = 0;
  let nextId = 1;
  const pending = new Map();

  // ── Connection ────────────────────────────────────────────────────
  function setStatus(el, tone, text) {
    el.dataset.tone = tone;
    el.querySelector(".status-text").textContent = text;
  }

  async function fetchJSON(path) {
    const res = await fetch(httpBase + path, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return res.json();
  }

  async function checkPin() {
    if (!pinRequired) return true;
    if (!pin) return false;
    const res = await fetch(`${httpBase}/api/auth?pin=${encodeURIComponent(pin)}`, { cache: "no-store" });
    if (res.status === 429) {
      $("pin-error").textContent = "Too many wrong PINs. Wait a minute, then try again.";
      return false;
    }
    return res.ok;
  }

  function showPinGate(message) {
    $("app").hidden = true;
    $("offline-banner").hidden = true;
    $("pin-gate").hidden = false;
    if (message) $("pin-error").textContent = message;
    setStatus($("conn-status"), "warn", "PIN needed");
    $("pin-input").focus();
  }

  async function start() {
    try {
      pinRequired = (await fetchJSON("/api/session")).pin_required;
    } catch {
      pinRequired = false; // server unreachable; connect() will report it
    }
    try {
      if (pinRequired && !(await checkPin())) {
        showPinGate(pin ? "That PIN didn't work." : "");
        return;
      }
    } catch {
      /* unreachable: fall through to connect() for the offline banner */
    }
    loadPalettes();
    connect();
  }

  function connect() {
    clearTimeout(retryTimer);
    if (ws) { ws.onclose = null; ws.close(); }
    setStatus($("conn-status"), "idle", everConnected ? "Reconnecting…" : "Connecting…");
    const url = pinRequired ? `${wsUrl}?pin=${encodeURIComponent(pin)}` : wsUrl;
    ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    let opened = false;

    ws.onopen = () => {
      opened = true;
      everConnected = true;
      retryDelay = 1000;
      setStatus($("conn-status"), "ok", "Connected");
      $("offline-banner").hidden = true;
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return handleFrame(ev.data);
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "state") handleState(msg);
      else if (msg.type === "ack") handleAck(msg);
      else if (msg.type === "activity") logActivity(msg.text, msg.ok);
    };
    ws.onclose = async () => {
      setOffline();
      if (!opened && pinRequired) {
        try {
          if (!(await checkPin())) return showPinGate("That PIN is no longer valid. sandcam may have restarted with a new one.");
        } catch { /* server down */ }
      }
      retryTimer = setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 10000);
    };
  }

  function setOffline() {
    setStatus($("conn-status"), "err", "Offline");
    $("offline-url").textContent = wsUrl;
    $("offline-banner").hidden = false;
    setEnabled(false);
    $("view-empty").hidden = false;
    $("view-meta").textContent = "No connection";
    setStatus($("sensor-status"), "idle", "Sensor: unknown");
    state = null;
    for (const [id, p] of pending) finishPending(id, p);
  }

  function setEnabled(on) {
    for (const id of ["sandcam-controls", "events-controls", "games-controls", "classroom-controls", "system-controls", "kiosk-controls", "buttons-controls", "terrain-controls"]) {
      $(id).disabled = !on;
    }
    if (!on) $("dunebox-controls").disabled = true;
  }

  $("retry-btn").addEventListener("click", () => { retryDelay = 1000; connect(); });

  $("pin-gate").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    pin = $("pin-input").value.trim();
    $("pin-error").textContent = "";
    let ok = false;
    try { ok = await checkPin(); } catch { $("pin-error").textContent = "Can't reach the sandbox."; return; }
    if (!ok) {
      if (!$("pin-error").textContent) $("pin-error").textContent = "That PIN didn't work.";
      return;
    }
    localStorage.setItem("dunebox.pin", pin);
    $("pin-gate").hidden = true;
    $("app").hidden = false;
    loadPalettes();
    connect();
  });

  // ── Palettes + live view ─────────────────────────────────────────
  let palettes = {};
  const luts = {};
  async function loadPalettes() {
    try {
      palettes = await fetchJSON("/api/palettes");
      for (const [name, colors] of Object.entries(palettes)) {
        const lut = new Uint32Array(256);
        colors.forEach((hex, i) => {
          const n = parseInt(hex, 16);
          lut[i] = 0xff000000 | ((n & 0xff) << 16) | (n & 0xff00) | (n >> 16); // RGBA little-endian
        });
        luts[name] = lut;
      }
      if (state) renderThemes(state);
    } catch { /* greyscale fallback until the next connect */ }
  }

  const canvas = $("depth");
  const ctx = canvas.getContext("2d");
  const scratch = document.createElement("canvas");
  const sctx = scratch.getContext("2d", { willReadFrequently: true });
  let decoding = false;
  let frameCount = 0;
  let frameWindowStart = performance.now();
  let streamFps = 0;

  async function handleFrame(buf) {
    if (decoding) return; // drop frames rather than queue them
    decoding = true;
    try {
      const view = new DataView(buf);
      const w = view.getUint16(0);
      const h = view.getUint16(2);
      const bitmap = await createImageBitmap(new Blob([buf.slice(4)], { type: "image/png" }));
      if (scratch.width !== w || scratch.height !== h) {
        scratch.width = canvas.width = w;
        scratch.height = canvas.height = h;
        canvas.parentElement.style.setProperty("--ar", String(w / h));
      }
      sctx.drawImage(bitmap, 0, 0);
      bitmap.close();
      if (viewMode === "3d" && view3d) {
        syncLut();
        view3d.update(scratch, w, h, {
          contour: state && state.contours ? state.contour_interval || CONTOUR_INTERVAL : 0,
          sea: WATER_LEVEL,
        });
      } else {
        const img = sctx.getImageData(0, 0, w, h);
        colorize(img, w, h);
        ctx.putImageData(img, 0, 0);
      }
      $("view-empty").hidden = true;

      frameCount++;
      const now = performance.now();
      if (now - frameWindowStart >= 1000) {
        streamFps = Math.round((frameCount * 1000) / (now - frameWindowStart));
        frameCount = 0;
        frameWindowStart = now;
        updateViewMeta();
      }
    } catch {
      /* corrupt frame: skip */
    } finally {
      decoding = false;
    }
  }

  // ── 2D / 3D view ──────────────────────────────────────────────────
  let viewMode = "2d";
  let view3d = null;
  let lutIn3d = "";

  function syncLut() {
    const theme = state && state.theme;
    if (!view3d || !theme || !luts[theme] || lutIn3d === theme) return;
    lutIn3d = theme;
    view3d.setLut(new Uint8Array(luts[theme].buffer.slice(0)));
  }

  function setViewMode(mode) {
    if (mode === "3d" && !view3d) {
      try { view3d = window.DuneView3D && window.DuneView3D.create($("depth3d")); } catch { view3d = null; }
      if (!view3d) {
        toast("3D needs WebGL 2, which this browser doesn't support.", "err");
        mode = "2d";
      }
    }
    viewMode = mode;
    localStorage.setItem("dunebox.view", mode);
    $("depth").hidden = mode === "3d";
    $("depth3d").hidden = mode !== "3d";
    for (const b of $("view-mode").children) {
      const on = b.dataset.view === mode;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
    }
    if (mode === "3d") { lutIn3d = ""; syncLut(); view3d.draw(); }
  }
  $("view-mode").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-view]");
    if (b) setViewMode(b.dataset.view);
  });
  window.addEventListener("resize", () => view3d && viewMode === "3d" && view3d.draw());

  function colorize(img, w, h) {
    const lut = state && luts[state.theme];
    if (!lut) return;
    const px = new Uint32Array(img.data.buffer);
    const n = w * h;
    const height = new Uint8Array(n);
    for (let i = 0; i < n; i++) height[i] = px[i] & 0xff;
    for (let i = 0; i < n; i++) px[i] = lut[height[i]];
    if (!state.contours) return;
    const sea = WATER_LEVEL * 255;
    const step = (state.contour_interval || CONTOUR_INTERVAL) * 255;
    for (let y = 1; y < h; y++) {
      for (let x = 1; x < w; x++) {
        const i = y * w + x;
        const v = height[i];
        if (v < sea) continue;
        const q = (v / step) | 0;
        if (q !== ((height[i - 1] / step) | 0) || q !== ((height[i - w] / step) | 0)) {
          const c = px[i];
          px[i] = 0xff000000
            | (((((c >> 16) & 0xff) * 0.35) | 0) << 16)
            | (((((c >> 8) & 0xff) * 0.35) | 0) << 8)
            | (((c & 0xff) * 0.35) | 0);
        }
      }
    }
  }

  function updateViewMeta() {
    if (!state) return;
    $("view-meta").textContent = `${THEME_LABELS[state.theme] || state.theme} theme · preview ${streamFps} fps`;
  }

  // ── State → UI ────────────────────────────────────────────────────
  function handleState(s) {
    state = s;
    setEnabled(true);
    renderSensor(s.sensor);
    renderFacts(s);
    renderThemes(s);
    renderWorld(s);
    renderGames(s);
    renderClassroom(s);
    renderSetup(s);
    renderTerrains(s);
    renderKiosk(s);
    renderButtons(s);
    renderDuneBox(s);
    renderPairing(s.dashboard);
    updateViewMeta();
  }

  function renderSensor(sensor) {
    const el = $("sensor-status");
    if (!sensor) return setStatus(el, "idle", "Sensor: unknown");
    const realConfigured = !["mouse_simulator", "dummy"].includes(sensor.configured);
    if (!sensor.connected) {
      setStatus(el, "err", `${sensor.name} disconnected. Replug USB and power.`);
    } else if (sensor.simulated && realConfigured) {
      setStatus(el, "warn", "Depth camera not found. Using simulator.");
    } else if (sensor.simulated) {
      setStatus(el, "warn", "Simulator (no depth camera)");
    } else {
      setStatus(el, "ok", sensor.name);
    }
  }

  function renderFacts(s) {
    $("f-sensor").textContent = !s.sensor ? "–" : s.sensor.simulated ? "Simulator" : s.sensor.name;
    $("f-fps").textContent = s.fps != null ? `${Math.round(s.fps)} fps` : "–";
    $("f-sea").textContent = s.below_sea_level != null ? `${Math.round(s.below_sea_level * 100)}%` : "–";
    $("f-uptime").textContent = s.uptime != null ? formatDuration(s.uptime) : "–";
  }

  function formatDuration(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${Math.floor(sec % 60)}s`;
    return `${Math.floor(sec)}s`;
  }

  let renderedThemes = "";
  function renderThemes(s) {
    const group = $("theme-group");
    const themes = s.themes || Object.keys(THEME_LABELS);
    const key = themes.join() + "|" + Object.keys(palettes).length;
    if (key !== renderedThemes) {
      renderedThemes = key;
      group.replaceChildren(...themes.map((t) => {
        const b = document.createElement("button");
        b.type = "button";
        b.setAttribute("role", "radio");
        b.dataset.action = "set_theme";
        b.dataset.value = t;
        const sw = document.createElement("span");
        sw.className = "swatch";
        sw.setAttribute("aria-hidden", "true");
        const colors = palettes[t];
        sw.style.background = colors
          ? `linear-gradient(90deg, ${[0, 64, 110, 120, 140, 180, 230, 255].map((i) => "#" + colors[i]).join(",")})`
          : "var(--border-strong)";
        b.append(sw, THEME_LABELS[t] || t);
        return b;
      }));
    }
    for (const b of group.children) {
      const on = b.dataset.value === s.theme;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
    }
  }

  function setSwitch(selector, on) {
    const el = document.querySelector(selector);
    if (el) el.setAttribute("aria-checked", String(Boolean(on)));
  }

  // Don't fight the user: a slider being dragged keeps its local value
  // until a second after the last input event.
  const lastRangeInput = new WeakMap();
  function setRange(el, value) {
    if (value == null) return;
    if (performance.now() - (lastRangeInput.get(el) || 0) > 1000) el.value = String(value);
    showRange(el);
  }
  function showRange(el) {
    const pct = ((Number(el.value) - Number(el.min)) / (Number(el.max) - Number(el.min))) * 100;
    el.style.setProperty("--pct", `${pct}%`);
    const out = el.parentElement.querySelector("output");
    if (out) out.textContent = RANGE_FORMAT[el.dataset.action](Number(el.value));
  }
  document.addEventListener("input", (ev) => {
    if (!ev.target.matches("input.range")) return;
    lastRangeInput.set(ev.target, performance.now());
    showRange(ev.target);
  });
  document.addEventListener("change", (ev) => {
    if (!ev.target.matches("input.range") || ev.target.closest("fieldset:disabled")) return;
    lastRangeInput.set(ev.target, performance.now());
    send(ev.target);
  });

  function renderWorld(s) {
    setSwitch('#sandcam-controls [data-action="toggle_contours"]', s.contours);
    setSwitch('#sandcam-controls [data-action="toggle_contour_labels"]', s.contour_labels);
    $("contour-options").hidden = !s.contours;
    setRange($("contour-interval"), s.contour_interval);
    setRange($("sea-level"), s.sea_level_offset);
    setSwitch('#sandcam-controls [data-action="toggle_creatures"]', s.creatures && s.creatures.enabled);
    setSwitch('#sandcam-controls [data-action="toggle_ecosystem"]', s.ecosystem);
    setSwitch('#sandcam-controls [data-action="toggle_day_night"]', s.day_night && s.day_night.enabled);
    setSwitch("#sound-switch", !s.sound_muted);

    if (s.creatures) {
      const set = s.creatures.set || "";
      $("creature-set").textContent = set ? set[0].toUpperCase() + set.slice(1) : "Set";
      $("creature-set").hidden = !s.creatures.enabled;
    }
    const dn = s.day_night || {};
    $("dn-speed").textContent = `${(dn.speed ?? 1).toFixed(1)}×`;
    $("dn-phase").textContent = dn.enabled
      ? `It's ${dn.phase || "day"} on the sand${dn.paused ? ", cycle paused" : ""}.`
      : "";

    const v = s.volcano || { count: 0 };
    $("volcano-hint").textContent = v.erupting
      ? "A volcano is erupting."
      : v.count
        ? `${v.count} ${v.count === 1 ? "volcano" : "volcanoes"} on the sand.`
        : "No volcanoes yet. Erupting places one at the centre.";
  }

  function smallButton(text, action, value, label) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-secondary btn-sm";
    b.dataset.action = action;
    b.dataset.value = value;
    b.textContent = text;
    if (label) b.setAttribute("aria-label", label);
    return b;
  }

  // "terrain_20261003_140512" -> "Oct 3, 2:05 PM"
  function snapshotLabel(name, time) {
    const d = time ? new Date(time * 1000) : null;
    return d && !isNaN(d) ? d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : name;
  }

  let renderedSnapshots = "";
  function renderTerrains(s) {
    const list = s.snapshots || [];
    const key = JSON.stringify(list) + "|" + s.can_load_terrain;
    if (key !== renderedSnapshots) {
      renderedSnapshots = key;
      $("snapshot-list").replaceChildren(...list.map((snap) => {
        const li = document.createElement("li");
        const label = document.createElement("span");
        label.className = "snapshot-name";
        label.textContent = snapshotLabel(snap.name, snap.time);
        label.title = snap.name;
        const files = document.createElement("span");
        files.className = "snapshot-files";
        for (const ext of snap.files) {
          const a = document.createElement("a");
          a.href = `${httpBase}/snapshots/${snap.name}${ext}${pin ? `?pin=${encodeURIComponent(pin)}` : ""}`;
          a.textContent = ext.slice(1);
          a.setAttribute("download", "");
          a.setAttribute("aria-label", `Download ${ext.slice(1).toUpperCase()} for ${label.textContent}`);
          files.append(a);
        }
        const end = document.createElement("span");
        end.className = "row-end";
        end.append(files);
        if (s.can_load_terrain) end.append(smallButton("Load", "load_snapshot", snap.name, `Load ${label.textContent} into the simulator`));
        end.append(smallButton("Rebuild", "start_challenge", snap.name, `Rebuild ${label.textContent} as a challenge`));
        li.append(label, end);
        return li;
      }));
    }
    const tl = s.timelapse || {};
    setSwitch('#terrain-controls [data-action="toggle_timelapse"]', tl.active);
    $("timelapse-hint").textContent = tl.active
      ? `Recording: ${tl.frames} ${tl.frames === 1 ? "frame" : "frames"}, one every ${Math.round(tl.interval)}s, in assets/timelapse/${tl.folder}.`
      : `Saves a frame every ${Math.round(tl.interval || 10)}s to assets/timelapse on the sandbox PC.`;
  }

  let renderedGames = "";
  function renderGames(s) {
    const games = s.games || {};
    const key = Object.keys(games).join();
    if (key !== renderedGames) {
      renderedGames = key;
      $("game-list").replaceChildren(...Object.entries(games).map(([id, name], i) => {
        const li = document.createElement("li");
        const label = document.createElement("span");
        label.className = "game-name";
        label.textContent = name;
        if (i < 9) {
          const k = document.createElement("kbd");
          k.textContent = String(i + 1);
          label.append(k);
        }
        if (id === "challenge" && s.challenge_targets) {
          // One button per target landscape instead of a single Start
          li.className = "game-challenge";
          label.append(Object.assign(document.createElement("span"), {
            className: "row-value", textContent: "pick a landscape to rebuild",
          }));
          const group = document.createElement("div");
          group.className = "target-row";
          Object.entries(s.challenge_targets).forEach(([target, targetName], j) => {
            const b = smallButton(targetName, "start_challenge", target, `Start ${name}: ${targetName}`);
            if (j === 0) b.dataset.gameIndex = String(i + 1);
            group.append(b);
          });
          li.append(label, group);
          return li;
        }
        const b = smallButton("Start", "start_game", id, `Start ${name}`);
        b.dataset.gameIndex = String(i + 1);
        li.append(label, b);
        return li;
      }));
    }
    const g = s.game || {};
    $("game-live").hidden = !g.active;
    if (g.active) {
      $("g-name").textContent = g.mode || "Game";
      $("g-score").textContent = g.score ?? "–";
      $("g-time").textContent = g.time_left != null ? `${Math.ceil(g.time_left)}s` : "No limit";
    }
  }

  function renderSetup(s) {
    const sensor = s.sensor || {};
    $("calibrate-btn").hidden = !sensor.can_calibrate;
    $("calibrate-hint").hidden = !sensor.can_calibrate;
    $("reset-btn").hidden = !sensor.can_reset;
    $("depth-range").textContent = sensor.depth_mm ? `${sensor.depth_mm[0]}–${sensor.depth_mm[1]} mm` : "–";
    for (const b of $("smoothing-group").children) {
      const on = b.dataset.value === s.smoothing;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on || (s.smoothing === "custom" && b.dataset.value === "balanced") ? 0 : -1;
    }
    $("smoothing-hint").textContent = s.smoothing === "custom"
      ? "Custom values from the sandcam sidebar. Pick a preset to replace them."
      : "Responsive follows hands quickly; Stable hides flicker but lags.";
    renderChecks(setupChecks(s));
  }

  // Each check: { name, tone: ok|warn|err|idle, detail, fix?: [label, action, value, target] }
  function setupChecks(s) {
    const sensor = s.sensor || {};
    const checks = [];
    checks.push(!sensor.connected
      ? { name: "Depth camera", tone: "err", detail: `${sensor.name || "Sensor"} disconnected. Replug USB and power.` }
      : sensor.simulated
        ? { name: "Depth camera", tone: "warn", detail: "Not found. The simulator is standing in." }
        : { name: "Depth camera", tone: "ok", detail: sensor.name });

    const range = sensor.depth_mm ? `${sensor.depth_mm[0]}–${sensor.depth_mm[1]} mm` : "the depth range";
    if (sensor.in_range_pct == null) {
      checks.push({ name: "Sand in view", tone: "idle", detail: "Measuring…" });
    } else {
      const pct = sensor.in_range_pct;
      checks.push({
        name: "Sand in view",
        tone: pct >= 95 ? "ok" : pct >= 80 ? "warn" : "err",
        detail: pct >= 95 ? `${Math.round(pct)}% inside ${range}` : `${Math.round(100 - pct)}% is outside ${range}. Flatten the sand and recalibrate.`,
        fix: pct < 95 && sensor.can_calibrate ? ["Calibrate", "calibrate_depth"] : null,
      });
    }

    if (sensor.simulated) {
      // Simulated terrain drifts on purpose, so flicker isn't meaningful
    } else if (sensor.noise_mm == null) {
      checks.push({ name: "Surface steadiness", tone: "idle", detail: "Measuring…" });
    } else {
      const n = sensor.noise_mm;
      checks.push({
        name: "Surface steadiness",
        tone: n <= 2 ? "ok" : n <= 5 ? "warn" : "err",
        detail: n <= 2 ? `Flicker under ${Math.max(1, Math.ceil(n))} mm` : `Flickers about ${Math.round(n)} mm. Keep hands clear, or smooth more.`,
        fix: n > 2 && s.smoothing !== "stable" ? ["Use Stable", "set_smoothing", "stable"] : null,
      });
    }

    if (s.fps != null) {
      checks.push({
        name: "Frame rate",
        tone: s.fps >= 25 ? "ok" : s.fps >= 15 ? "warn" : "err",
        detail: s.fps >= 25 ? `${Math.round(s.fps)} fps` : `${Math.round(s.fps)} fps. Close other apps or turn off creatures.`,
      });
    }

    const d = s.dunebox;
    if (d && d.roi_calibrated !== undefined) {
      checks.push(d.roi_calibrated
        ? { name: "Projector: sand area", tone: "ok", detail: "Detected" }
        : { name: "Projector: sand area", tone: "warn", detail: "Not detected yet",
            fix: ["Detect", "detect_sand_region", null, "dunebox"] });
      checks.push(d.projector_calibrated
        ? { name: "Projector: alignment", tone: "ok", detail: "Calibrated" }
        : { name: "Projector: alignment", tone: "warn", detail: "Not calibrated yet",
            fix: ["Calibrate", "calibrate_projector", null, "dunebox"] });
    }
    return checks;
  }

  let renderedChecks = "";
  function renderChecks(checks) {
    const key = JSON.stringify(checks);
    if (key === renderedChecks) return;
    renderedChecks = key;
    $("check-list").replaceChildren(...checks.map((c) => {
      const li = document.createElement("li");
      const dot = document.createElement("span");
      dot.className = "status-dot";
      dot.dataset.tone = c.tone;
      dot.setAttribute("aria-hidden", "true");
      const text = document.createElement("span");
      const name = Object.assign(document.createElement("span"), { className: "check-name", textContent: c.name });
      const detail = Object.assign(document.createElement("span"), { className: "check-detail", textContent: c.detail });
      text.append(name, detail);
      li.append(dot, text);
      if (c.fix) {
        const [label, action, value, target] = c.fix;
        const b = smallButton(label, action, value ?? "", `${label}: ${c.name}`);
        if (target) b.dataset.target = target;
        li.append(b);
      }
      return li;
    }));
  }

  // ── Unattended (opening hours, projector, reconnect) ──────────────
  const DAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"];
  const DAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  $("day-chips").replaceChildren(...DAY_LETTERS.map((letter, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "day-chip";
    b.dataset.day = String(i);
    b.textContent = letter;
    b.setAttribute("aria-label", DAY_FULL[i]);
    b.setAttribute("aria-pressed", "false");
    return b;
  }));
  $("day-chips").addEventListener("click", (ev) => {
    const chip = ev.target.closest(".day-chip");
    if (!chip || !state || !state.kiosk) return;
    const days = new Set(state.kiosk.days);
    if (days.has(chip.dataset.day)) days.delete(chip.dataset.day); else days.add(chip.dataset.day);
    if (!days.size) return toast("Pick at least one day", "err");
    chip.setAttribute("aria-pressed", String(days.has(chip.dataset.day)));
    sendCommand({ action: "set_days", value: [...days].sort().join("") });
  });

  function sendHours() {
    const open = $("open-time").value;
    const close = $("close-time").value;
    if (!open || !close) return;
    sendCommand({ action: "set_hours", value: `${open}-${close}` });
  }
  $("open-time").addEventListener("change", sendHours);
  $("close-time").addEventListener("change", sendHours);

  function sendProjectorHost() {
    const host = $("projector-host").value.trim();
    if (state && state.kiosk && host === state.kiosk.projector.host) return;
    sendCommand({ action: "set_projector_host", value: host });
  }
  $("projector-host").addEventListener("change", sendProjectorHost);
  $("projector-host").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); ev.target.blur(); }
  });

  // Inputs keep what the user is typing; state only fills them when idle
  function setInput(el, value) {
    if (document.activeElement !== el) el.value = value;
  }

  const POWER_LABELS = { on: "on", off: "off", warming: "warming up", cooling: "cooling down" };
  function renderKiosk(s) {
    const k = s.kiosk;
    if (!k) return;
    setSwitch('#kiosk-controls [data-action="toggle_schedule"]', k.enabled);
    setSwitch('#kiosk-controls [data-action="toggle_auto_reconnect"]', s.sensor && s.sensor.auto_reconnect);
    $("schedule-options").hidden = !k.enabled;
    const [open, close] = (k.hours || "").split("-");
    setInput($("open-time"), open || "");
    setInput($("close-time"), close || "");
    for (const chip of $("day-chips").children) {
      chip.setAttribute("aria-pressed", String(k.days.includes(chip.dataset.day)));
    }
    $("schedule-hint").textContent = !k.enabled
      ? "Outside opening hours the projection goes dark and the projector switches off."
      : k.asleep
        ? `Closed. Opens ${k.next_change || "on the next open day"}.`
        : k.open
          ? `Open now${k.next_change ? `. Closes ${k.next_change}` : ""}.`
          : `Woken outside opening hours${k.next_change ? `. Opens ${k.next_change}` : ""}.`;
    $("wake-row").hidden = !k.asleep;

    const p = k.projector;
    setInput($("projector-host"), p.host);
    $("projector-on").disabled = !p.configured;
    $("projector-off").disabled = !p.configured;
    $("projector-hint").textContent = !p.configured
      ? "Turns a networked projector on and off with the opening hours. Set a password in sandcam-settings.json if it needs one."
      : p.error
        ? `Couldn't switch the projector: ${p.error}`
        : p.power === "unknown"
          ? "Projector set. Power state appears after the first command."
          : `Projector ${POWER_LABELS[p.power] || p.power}.`;
  }

  // ── Classroom: lessons and team scores ────────────────────────────
  const TEAM_COLOURS = ["#52a8ff", "#f5a524", "#3fcf8e", "#ff6166"];
  const t = (text) => (window.DuneI18n ? window.DuneI18n.t(text) : text);

  let renderedLessons = "";
  let renderedDots = "";
  let renderedTeams = "";
  let renderedAward = "";
  let renderedLanguages = "";
  function renderClassroom(s) {
    const c = s.classroom;
    if (!c) return;
    const { catalogue, active } = c.lessons;

    const catKey = JSON.stringify(catalogue);
    if (catKey !== renderedLessons) {
      renderedLessons = catKey;
      $("lesson-list").replaceChildren(...catalogue.map((lesson) => {
        const li = document.createElement("li");
        const name = Object.assign(document.createElement("span"), { className: "lesson-name", textContent: lesson.title });
        const meta = Object.assign(document.createElement("span"), {
          className: "lesson-meta",
          textContent: [lesson.level, lesson.minutes ? `${lesson.minutes} min` : "", `${lesson.steps} ${lesson.steps === 1 ? "step" : "steps"}`]
            .filter(Boolean).join(" · "),
        });
        meta.title = lesson.summary;
        li.append(name, meta, smallButton("Start", "start_lesson", lesson.id, `Start lesson: ${lesson.title}`));
        return li;
      }));
    }
    $("lesson-list").hidden = Boolean(active);
    $("lesson-live").hidden = !active;
    if (active) {
      $("lesson-title").textContent = active.title;
      $("lesson-progress").textContent = `${active.index + 1} / ${active.count}`;
      const dotKey = `${active.count}|${active.index}`;
      if (dotKey !== renderedDots) {
        renderedDots = dotKey;
        $("lesson-dots").replaceChildren(...Array.from({ length: active.count }, (_, i) => {
          const li = document.createElement("li");
          li.className = i < active.index ? "past" : i === active.index ? "current" : "";
          return li;
        }));
      }
      $("lesson-step-title").textContent = active.step_title;
      $("lesson-text").textContent = active.text;
      const goal = $("lesson-goal");
      goal.hidden = !active.has_check;
      goal.dataset.done = String(active.done);
      goal.textContent = active.done ? `✓ ${t("Goal reached")}` : active.hint;
      $("lesson-prev").disabled = active.index === 0;
      $("lesson-next").disabled = active.index >= active.count - 1;
    }

    const langKey = JSON.stringify(c.languages);
    const langSelect = $("sand-language");
    if (langKey !== renderedLanguages) {
      renderedLanguages = langKey;
      langSelect.replaceChildren(...Object.entries(c.languages).map(([code, name]) => new Option(name, code)));
    }
    if (document.activeElement !== langSelect) langSelect.value = c.language;

    const sb = c.scoreboard;
    const n = sb.teams.length;
    for (const b of $("teams-group").children) {
      const on = Number(b.dataset.value) === n;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
    }
    $("teams-live").hidden = n === 0;
    const teamKey = JSON.stringify(sb.teams.map((x) => x.name));
    if (teamKey !== renderedTeams && !$("team-list").contains(document.activeElement)) {
      renderedTeams = teamKey;
      $("team-list").replaceChildren(...sb.teams.map((team, i) => {
        const li = document.createElement("li");
        const sw = Object.assign(document.createElement("span"), { className: "team-swatch" });
        sw.style.background = TEAM_COLOURS[i];
        const input = Object.assign(document.createElement("input"), {
          className: "input", type: "text", value: team.name, maxLength: 24,
        });
        input.setAttribute("aria-label", `Team ${i + 1} name`);
        input.addEventListener("change", () => {
          sendCommand({ action: "rename_team", value: { team: i, name: input.value } });
        });
        input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") input.blur(); });
        const score = Object.assign(document.createElement("span"), { className: "team-score num" });
        score.dataset.team = String(i);
        const minus = Object.assign(document.createElement("button"), {
          type: "button", className: "btn btn-secondary btn-sm", textContent: "−1",
        });
        minus.setAttribute("aria-label", `Take a point from ${team.name}`);
        minus.addEventListener("click", () => sendCommand({ action: "team_points", value: { team: i, points: -1 } }, minus));
        const plus = Object.assign(document.createElement("button"), {
          type: "button", className: "btn btn-secondary btn-sm", textContent: "+1",
        });
        plus.setAttribute("aria-label", `Give a point to ${team.name}`);
        plus.addEventListener("click", () => sendCommand({ action: "team_points", value: { team: i, points: 1 } }, plus));
        li.append(sw, input, score, minus, plus);
        return li;
      }));
    }
    for (const el of $("team-list").querySelectorAll(".team-score")) {
      const team = sb.teams[Number(el.dataset.team)];
      if (team) el.textContent = String(team.score);
    }

    const last = sb.last_game;
    const awardKey = last && n ? JSON.stringify([last, sb.teams.map((x) => x.name)]) : "";
    $("award").hidden = !awardKey;
    if (awardKey !== renderedAward) {
      renderedAward = awardKey;
      if (awardKey) {
        const result = Object.assign(document.createElement("strong"), { textContent: `${last.mode} · ${last.score}` });
        $("award-text").replaceChildren(result, document.createElement("br"), t("Give the last game's points to:"));
        $("award-row").replaceChildren(...sb.teams.map((team, i) => {
          const b = Object.assign(document.createElement("button"), {
            type: "button", className: "btn btn-secondary btn-sm", textContent: team.name,
          });
          b.addEventListener("click", () => sendCommand({ action: "award_game", value: i }, b));
          return b;
        }));
      }
    }
    setSwitch('#classroom-controls [data-action="toggle_scoreboard"]', sb.visible);
  }

  $("sand-language").addEventListener("change", (ev) => {
    sendCommand({ action: "set_language", value: ev.target.value });
  });

  // Dashboard language, remembered per device
  const uiLang = $("ui-lang");
  uiLang.value = localStorage.getItem("dunebox.lang") || (navigator.language.startsWith("es") ? "es" : "en");
  if (window.DuneI18n) window.DuneI18n.setLanguage(uiLang.value);
  uiLang.addEventListener("change", () => {
    localStorage.setItem("dunebox.lang", uiLang.value);
    window.DuneI18n && window.DuneI18n.setLanguage(uiLang.value);
  });

  // ── Physical buttons ──────────────────────────────────────────────
  function buttonName(id) {
    if (id.startsWith("keypad ")) return `Keypad ${id.slice(7)}`;
    return /^\d+$/.test(id) ? `Button ${id}` : id;
  }

  let renderedButtons = "";
  const lastPressed = new Map();
  function renderButtons(s) {
    const b = s.buttons;
    if (!b) return;
    const key = JSON.stringify(b.buttons.map((x) => [x.id, x.action])) + Object.keys(b.actions).join();
    if (key !== renderedButtons && !$("button-map").contains(document.activeElement)) {
      renderedButtons = key;
      $("button-map").replaceChildren(...b.buttons.map((btn) => {
        const li = document.createElement("li");
        li.dataset.button = btn.id;
        const name = Object.assign(document.createElement("label"), {
          className: "button-name", textContent: buttonName(btn.id), htmlFor: `btn-map-${btn.id}`,
        });
        const select = document.createElement("select");
        select.className = "input select";
        select.id = `btn-map-${btn.id}`;
        for (const [value, label] of Object.entries(b.actions)) {
          select.append(new Option(label, value, false, value === btn.action));
        }
        select.addEventListener("change", () => {
          sendCommand({ action: "set_button_action", button: btn.id, value: select.value });
        });
        li.append(name, select);
        return li;
      }));
    }
    // Flash a row when its button is pressed so people can find which is which
    for (const btn of b.buttons) {
      const prev = lastPressed.get(btn.id);
      lastPressed.set(btn.id, btn.pressed);
      if (prev !== undefined && btn.pressed > prev) {
        const li = $("button-map").querySelector(`li[data-button="${CSS.escape(btn.id)}"]`);
        if (li) {
          li.classList.remove("just-pressed");
          void li.offsetWidth;
          li.classList.add("just-pressed");
        }
      }
    }
    const serial = b.serial;
    setSwitch('#buttons-controls [data-action="toggle_button_serial"]', serial.enabled);
    $("serial-hint").textContent = !serial.enabled
      ? "For arcade buttons wired to an Arduino running hardware/buttons/buttons.ino."
      : serial.port
        ? `Listening on ${serial.port}.`
        : serial.error || "Looking for the Arduino…";
  }

  const DUNEBOX_STATES = {
    running: "Running",
    setup: "Setup: not calibrated yet",
    calibrating: "Calibrating",
    idle: "Starting",
  };
  function renderDuneBox(s) {
    const d = s.dunebox;
    $("dunebox-controls").disabled = !d;
    $("dunebox-empty").hidden = Boolean(d);
    $("dunebox-live").hidden = !d;
    const empty = $("dunebox-empty").querySelector("p");
    empty.innerHTML = s.bridge && !s.bridge.enabled
      ? "<strong>Link is off.</strong> Press <kbd>B</kbd> in sandcam to link with DuneBox (C++)."
      : "<strong>Not linked.</strong> Start DuneBox (Magic-Sand) on this PC. It links to sandcam automatically and its water, lava and theme controls appear here.";
    const linkOff = s.bridge && !s.bridge.enabled;
    if (!d) {
      setStatus($("db-state"), "idle", linkOff ? "Link off" : "Not linked");
      setStatus($("db-link-status"), "idle", linkOff ? "DuneBox: link off" : "DuneBox: not linked");
      return;
    }
    let text = DUNEBOX_STATES[d.app_state] || d.app_state;
    const healthy = d.app_state === "running" && d.kinect_connected;
    if (!d.kinect_connected) text += " · Kinect not found";
    setStatus($("db-state"), healthy ? "ok" : "warn", text);
    setStatus($("db-link-status"), healthy ? "ok" : "warn", healthy ? "DuneBox: running" : "DuneBox: needs setup");
    setSwitch('#dunebox-live [data-action="toggle_water"]', d.water);
    setSwitch('#dunebox-live [data-action="toggle_lava"]', d.lava);
    setSwitch('#dunebox-live [data-action="toggle_day_night"]', d.day_night);
    $("db-theme").textContent = d.theme ? `(${d.theme})` : "";
    $("db-start").hidden = d.app_state !== "setup";

    // Builds without water and calibration controls don't report these fields
    $("db-water-extra").hidden = d.evaporation === undefined;
    if (d.evaporation !== undefined) {
      for (const b of $("evap-group").children) {
        const on = b.dataset.value === d.evaporation;
        b.setAttribute("aria-checked", String(on));
        b.tabIndex = on ? 0 : -1;
      }
      setSwitch('#dunebox-live [data-action="toggle_hand_rain"]', d.hand_rain);
    }
    const calibrating = d.app_state === "calibrating";
    $("db-calib-actions").hidden = d.roi_calibrated === undefined || calibrating;
    $("db-calib").hidden = !calibrating;
    $("db-calib-text").textContent = d.calibration_text || "Follow the prompts on the projector.";
    $("db-calib-confirm").hidden = !d.awaiting_confirm;
  }

  function renderPairing(dash) {
    if (!dash) return;
    $("pair-lan").hidden = !dash.lan;
    $("pair-local").hidden = dash.lan;
    const shown = dash.url.replace(/\?pin=\d+$/, "");
    $("pair-url").textContent = shown;
    const m = dash.url.match(/\?pin=(\d+)$/);
    $("pair-pin").hidden = !m;
    if (m) $("pair-pin-value").textContent = m[1];
  }

  $("pair-popover").addEventListener("toggle", (ev) => {
    if (ev.newState === "open" && !$("pair-lan").hidden) {
      const qr = $("pair-qr");
      qr.hidden = false;
      qr.onerror = () => { qr.hidden = true; };
      qr.src = `${httpBase}/qr.svg?pin=${encodeURIComponent(pin)}&t=${Date.now()}`;
    }
  });

  $("copy-url").addEventListener("click", async () => {
    const text = $("pair-url").textContent;
    try {
      await navigator.clipboard.writeText(text);
      toast("Address copied");
    } catch {
      const range = document.createRange();
      range.selectNodeContents($("pair-url"));
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      toast("Address selected. Press Ctrl+C to copy.");
    }
  });

  // ── Commands ──────────────────────────────────────────────────────
  function send(el) {
    if (el.getAttribute("aria-busy") === "true") return;
    const cmd = { action: el.dataset.action, target: el.dataset.target };
    if (el.dataset.value) cmd.value = el.dataset.value;
    else if (el.matches("input.range")) cmd.value = Number(el.value);
    sendCommand(cmd, el);
  }

  // el is the control that triggered the command (null for voice)
  function sendCommand(cmd, el = null) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      toast("Not connected to the sandbox.", "err");
      return;
    }
    const id = nextId++;
    const msg = { type: "command", id, action: cmd.action, target: cmd.target || "sandcam" };
    if (cmd.value !== undefined) msg.value = cmd.value;
    if (cmd.button !== undefined) msg.button = cmd.button;
    ws.send(JSON.stringify(msg));
    if (el) el.setAttribute("aria-busy", "true");
    const timer = setTimeout(() => {
      finishPending(id, pending.get(id));
      toast("No response from the sandbox. Check that sandcam is still running.", "err");
    }, ACK_TIMEOUT_MS);
    pending.set(id, { el, timer });
  }

  function finishPending(id, p) {
    if (!p) return;
    clearTimeout(p.timer);
    if (p.el) p.el.removeAttribute("aria-busy");
    pending.delete(id);
  }

  function handleAck(msg) {
    const p = pending.get(msg.id);
    if (!p) return;
    finishPending(msg.id, p);
    const role = p.el ? p.el.getAttribute("role") : null;
    const activityShown = getComputedStyle($("activity")).display !== "none";
    const quiet = msg.ok && p.el && (activityShown || role === "switch" || role === "radio" || p.el.closest(".stepper"));
    if (!quiet && msg.message) toast(msg.message, msg.ok ? "ok" : "err");
    if (msg.message) logActivity(msg.message, msg.ok);
  }

  function logActivity(text, ok) {
    const list = $("activity-list");
    const li = document.createElement("li");
    li.dataset.tone = ok ? "ok" : "err";
    const time = document.createElement("time");
    const now = new Date();
    time.dateTime = now.toISOString();
    time.textContent = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    li.append(document.createTextNode(text), time);
    list.prepend(li);
    while (list.children.length > 8) list.lastElementChild.remove();
    $("activity-empty").hidden = true;
  }

  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-action]");
    if (el && !el.matches("input") && !el.disabled && !el.closest("fieldset:disabled")) send(el);
  });

  // Arrow keys move between theme options (radiogroup pattern)
  document.addEventListener("keydown", (ev) => {
    const group = ev.target.closest('.segmented[role="radiogroup"]');
    if (!group || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(ev.key)) return;
    ev.preventDefault();
    const items = [...group.children];
    const i = items.indexOf(document.activeElement);
    const next = items[(i + (ev.key === "ArrowLeft" || ev.key === "ArrowUp" ? -1 : 1) + items.length) % items.length];
    next.focus();
    if (next.dataset.action) send(next);
    else next.click();
  });

  // ── Keyboard shortcuts (same keys as sandcam) ────────────────────
  document.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.target.closest("input, textarea, select, [contenteditable]")) return;
    if (ev.key === "?") { $("keys-popover").togglePopover(); return; }
    if (ev.key === "Escape") {
      if (document.querySelector(":popover-open")) return;
      const end = document.querySelector('[data-action="end_game"]');
      if (state && state.game && state.game.active) send(end);
      return;
    }
    let el = null;
    if (/^[1-9]$/.test(ev.key)) el = document.querySelector(`[data-game-index="${ev.key}"]`);
    else el = document.querySelector(`[data-key="${ev.key.toLowerCase()}"]`);
    if (el && !el.closest("fieldset:disabled")) {
      ev.preventDefault();
      send(el);
    }
  });

  // ── Voice ─────────────────────────────────────────────────────────
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const voiceBtn = $("voice-btn");
  let recognizer = null;
  let listening = false;

  function voiceUnavailableReason() {
    if (!Recognition) return "Voice needs Chrome or Edge.";
    if (!window.isSecureContext) return "Voice only works on the sandbox PC (http://127.0.0.1) or over HTTPS.";
    return "";
  }

  function setListening(on) {
    listening = on;
    voiceBtn.setAttribute("aria-pressed", String(on));
    voiceBtn.querySelector(".voice-label").textContent = on ? "Listening…" : "Voice";
  }

  function onPhrase(text) {
    const cmd = window.DuneVoice.parse(text, state);
    if (!cmd) {
      toast(`Heard “${text}”, but it isn't a command. Try “erupt the volcano” or “heat map”.`, "err");
      logActivity(`Voice: “${text}” (not a command)`, false);
      return;
    }
    if (cmd.already) {
      toast(cmd.already);
      return;
    }
    logActivity(`Voice: “${text}”`, true);
    sendCommand(cmd);
  }

  voiceBtn.addEventListener("click", () => {
    const reason = voiceUnavailableReason();
    if (reason) { toast(reason, "err"); return; }
    if (listening) { setListening(false); recognizer && recognizer.stop(); return; }
    recognizer = new Recognition();
    // The phrase parser only understands English, whatever the dashboard language
    recognizer.lang = "en-US";
    recognizer.continuous = true;
    recognizer.interimResults = false;
    recognizer.onresult = (ev) => {
      const result = ev.results[ev.results.length - 1];
      if (result.isFinal) onPhrase(result[0].transcript.trim());
    };
    recognizer.onerror = (ev) => {
      if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
        toast("Microphone blocked. Allow it in the browser's site settings.", "err");
        setListening(false);
      }
    };
    // Browsers stop after a pause; keep listening until the user turns it off.
    recognizer.onend = () => { if (listening) { try { recognizer.start(); } catch { setListening(false); } } };
    setListening(true);
    recognizer.start();
  });
  if (voiceUnavailableReason()) {
    voiceBtn.setAttribute("aria-disabled", "true");
    voiceBtn.title = voiceUnavailableReason();
  }

  // ── Toasts ────────────────────────────────────────────────────────
  function toast(text, tone = "ok") {
    const list = $("toasts");
    const li = document.createElement("li");
    li.className = "toast";
    li.dataset.tone = tone;
    li.textContent = text;
    list.append(li);
    while (list.children.length > 3) list.firstElementChild.remove();
    setTimeout(() => li.remove(), tone === "err" ? 7000 : 3500);
  }

  if (localStorage.getItem("dunebox.view") === "3d") setViewMode("3d");
  start();
})();
