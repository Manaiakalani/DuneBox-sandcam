// Run with: node --test web/voice.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const { parse } = require("./assets/voice.js");

const state = {
  contours: true, contour_labels: false, sea_level_offset: 0, sound_muted: false,
  creatures: { enabled: true }, day_night: { enabled: false }, ecosystem: false,
  timelapse: { active: false }, dunebox: { water: true, lava: false },
};

const cases = [
  ["Erupt the volcano!", { action: "erupt_volcano" }],
  ["start the volcano game", { action: "start_game", value: "volcano" }],
  ["let's play build a dam", { action: "start_game", value: "dam" }],
  ["end the game", { action: "end_game" }],
  ["terrain challenge valley", { action: "start_challenge", value: "valley" }],
  ["rebuild two peaks", { action: "start_challenge", value: "two_peaks" }],
  ["switch to the heat map", { action: "set_theme", value: "heat" }],
  ["make it grey", { action: "set_theme", value: "greyscale" }],
  ["earthquake", { action: "trigger_earthquake" }],
  ["raise the sea level", { action: "set_sea_level", value: 0.05 }],
  ["reset sea level", { action: "set_sea_level", value: 0 }],
  ["turn contours off", { action: "toggle_contours" }],
  ["show contour lines", { already: "Contour lines already on" }],
  ["show elevation labels", { action: "toggle_contour_labels" }],
  ["hide the animals", { action: "toggle_creatures" }],
  ["mute", { action: "toggle_sound" }],
  ["unmute", { already: "Sound already on" }],
  ["start day and night", { action: "toggle_day_night" }],
  ["turn on lava", { action: "toggle_lava", target: "dunebox" }],
  ["stop the water", { action: "toggle_water", target: "dunebox" }],
  ["save a snapshot", { action: "save_snapshot" }],
  ["start timelapse", { action: "toggle_timelapse" }],
  ["what time is it", null],
  ["", null],
];

for (const [phrase, expected] of cases) {
  test(JSON.stringify(phrase), () => assert.deepEqual(parse(phrase, state), expected));
}

test("sea level clamps at +20%", () => {
  assert.deepEqual(parse("raise the sea", { sea_level_offset: 0.2 }), { action: "set_sea_level", value: 0.2 });
});

test("water needs DuneBox linked", () => {
  assert.equal(parse("stop the water", { dunebox: null }), null);
});
