// Voice phrases -> dashboard commands. Pure function so it can be tested
// without a browser: DuneVoice.parse("erupt the volcano", state).
(() => {
  "use strict";

  const THEMES = { terrain: "terrain", heat: "heat", "heat map": "heat", desert: "desert", grey: "greyscale", gray: "greyscale", greyscale: "greyscale", grayscale: "greyscale" };
  const GAMES = { dam: "dam", "build a dam": "dam", volcano: "volcano", watershed: "watershed", biome: "biome", biomes: "biome" };
  const TARGETS = { island: "island", valley: "valley", "two peaks": "two_peaks", peaks: "two_peaks" };

  // "turn contours on" -> true, "... off" / "hide" -> false, neither -> null
  function wantOn(text) {
    if (/\b(off|hide|stop|disable|no more)\b/.test(text)) return false;
    if (/\b(on|show|start|enable)\b/.test(text)) return true;
    return null;
  }

  function toggle(action, current, text, label, target) {
    const want = wantOn(text);
    if (want !== null && want === Boolean(current)) return { already: `${label} ${want ? "already on" : "already off"}` };
    return target ? { action, target } : { action };
  }

  function find(text, table) {
    // Longest key first so "heat map" wins over "heat"
    for (const key of Object.keys(table).sort((a, b) => b.length - a.length)) {
      if (new RegExp(`\\b${key}\\b`).test(text)) return table[key];
    }
    return null;
  }

  function parse(raw, state) {
    const text = String(raw || "").toLowerCase().replace(/[.,!?]/g, " ").replace(/\s+/g, " ").trim();
    const s = state || {};
    if (!text) return null;

    if (/\b(end|stop|quit|finish)\b.*\bgame\b/.test(text)) return { action: "end_game" };
    if (/\b(challenge|rebuild)\b/.test(text)) return { action: "start_challenge", value: find(text, TARGETS) || "island" };
    if (/\b(start|play)\b.*\bgame\b|\bplay\b/.test(text)) {
      const game = find(text, GAMES);
      if (game) return { action: "start_game", value: game };
    }
    if (/\b(snapshot|save( the)? (sand|terrain))\b/.test(text)) return { action: "save_snapshot" };
    if (/\btime ?lapse\b/.test(text)) return toggle("toggle_timelapse", s.timelapse && s.timelapse.active, text, "Timelapse");

    if (/\bsea( level)?\b|\bwater level\b|\bflood\b/.test(text)) {
      const now = Number(s.sea_level_offset || 0);
      if (/\b(reset|normal)\b/.test(text)) return { action: "set_sea_level", value: 0 };
      const up = /\b(raise|up|higher|rise|flood|more)\b/.test(text);
      const down = /\b(lower|down|drain|less)\b/.test(text);
      if (up || down) {
        const next = Math.max(-0.2, Math.min(0.2, Math.round((now + (up ? 0.05 : -0.05)) * 100) / 100));
        return { action: "set_sea_level", value: next };
      }
    }

    if (/\b(earthquake|quake|shake)\b/.test(text)) return { action: "trigger_earthquake" };
    if (/\blava\b/.test(text) && s.dunebox) return toggle("toggle_lava", s.dunebox.lava, text, "Lava", "dunebox");
    if (/\b(erupt|eruption|volcano)\b/.test(text)) return { action: "erupt_volcano" };
    if (/\b(water|rain)\b/.test(text) && s.dunebox) return toggle("toggle_water", s.dunebox.water, text, "Water", "dunebox");

    if (/\blabels?\b/.test(text)) return toggle("toggle_contour_labels", s.contour_labels, text, "Elevation labels");
    if (/\b(contours?|contour lines|lines)\b/.test(text)) return toggle("toggle_contours", s.contours, text, "Contour lines");
    if (/\b(creatures?|animals?|sharks?|dinosaurs?)\b/.test(text)) return toggle("toggle_creatures", s.creatures && s.creatures.enabled, text, "Creatures");
    if (/\b(plants?|ecosystem|grass|trees?)\b/.test(text)) return toggle("toggle_ecosystem", s.ecosystem, text, "Plants");
    if (/\b(day|night|sun|sunset|sunrise)\b/.test(text)) return toggle("toggle_day_night", s.day_night && s.day_night.enabled, text, "Day and night");
    if (/\b(sound|music|mute|unmute|quiet)\b/.test(text)) {
      const muted = Boolean(s.sound_muted);
      if (/\bunmute\b/.test(text)) return muted ? { action: "toggle_sound" } : { already: "Sound already on" };
      if (/\b(mute|quiet)\b/.test(text)) return muted ? { already: "Sound already muted" } : { action: "toggle_sound" };
      return toggle("toggle_sound", !muted, text, "Sound");
    }

    const theme = find(text, THEMES);
    return theme ? { action: "set_theme", value: theme } : null;
  }

  const api = { parse };
  if (typeof window !== "undefined") window.DuneVoice = api;
  if (typeof module !== "undefined") module.exports = api;
})();
