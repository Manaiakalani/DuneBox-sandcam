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
    for (const id of ["sandcam-controls", "events-controls", "games-controls", "system-controls"]) {
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
      const img = sctx.getImageData(0, 0, w, h);
      colorize(img, w, h);
      ctx.putImageData(img, 0, 0);
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
    renderSetup(s);
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
        const b = document.createElement("button");
        b.type = "button";
        b.className = "btn btn-secondary btn-sm";
        b.dataset.action = "start_game";
        b.dataset.value = id;
        b.dataset.gameIndex = String(i + 1);
        b.textContent = "Start";
        b.setAttribute("aria-label", `Start ${name}`);
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
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      toast("Not connected to the sandbox.", "err");
      return;
    }
    if (el.getAttribute("aria-busy") === "true") return;
    const id = nextId++;
    const msg = { type: "command", id, action: el.dataset.action, target: el.dataset.target || "sandcam" };
    if (el.dataset.value) msg.value = el.dataset.value;
    else if (el.matches("input.range")) msg.value = Number(el.value);
    ws.send(JSON.stringify(msg));
    el.setAttribute("aria-busy", "true");
    const timer = setTimeout(() => {
      finishPending(id, pending.get(id));
      toast("No response from the sandbox. Check that sandcam is still running.", "err");
    }, ACK_TIMEOUT_MS);
    pending.set(id, { el, timer });
  }

  function finishPending(id, p) {
    if (!p) return;
    clearTimeout(p.timer);
    p.el.removeAttribute("aria-busy");
    pending.delete(id);
  }

  function handleAck(msg) {
    const p = pending.get(msg.id);
    if (!p) return;
    finishPending(msg.id, p);
    const role = p.el.getAttribute("role");
    const activityShown = getComputedStyle($("activity")).display !== "none";
    const quiet = msg.ok && (activityShown || role === "switch" || role === "radio" || p.el.closest(".stepper"));
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
    send(next);
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

  start();
})();
