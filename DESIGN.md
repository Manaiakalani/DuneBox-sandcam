---
name: DuneBox
description: The operator console for a live AR sandbox; one calm dark surface that runs both sandcam (Python) and DuneBox (C++).
colors:
  bg: "#0a0a0a"
  surface: "#111111"
  surface-2: "#171717"
  surface-3: "#1f1f1f"
  border: "#262626"
  border-strong: "#3a3a3a"
  text: "#ededed"
  text-2: "#a1a1a1"
  text-3: "#8a8a8a"
  accent: "#52a8ff"
  accent-bg: "rgba(82, 168, 255, 0.14)"
  accent-border: "rgba(82, 168, 255, 0.45)"
  ok: "#3fcf8e"
  warn: "#f5a524"
  err: "#ff6166"
  warn-bg: "rgba(245, 165, 36, 0.1)"
  err-bg: "rgba(255, 97, 102, 0.1)"
typography:
  headline:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.015em"
  title-lg:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.005em"
  body:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  control:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1
  body-sm:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Geist, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.5
  numeric:
    fontFamily: "Geist Mono, ui-monospace, Cascadia Mono, Consolas, monospace"
    fontSize: "1rem"
    fontWeight: 500
    lineHeight: 1.5
    fontFeature: "tnum"
  numeric-lg:
    fontFamily: "Geist Mono, ui-monospace, Cascadia Mono, Consolas, monospace"
    fontSize: "1.25rem"
    fontWeight: 500
    lineHeight: 1.5
    fontFeature: "tnum"
rounded:
  xs: "4px"
  sm: "6px"
  md: "8px"
  full: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  target: "44px"
  row: "52px"
components:
  button-primary:
    backgroundColor: "{colors.text}"
    textColor: "{colors.bg}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "{spacing.target}"
  button-secondary:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "{spacing.target}"
  button-secondary-hover:
    backgroundColor: "{colors.surface-3}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-2}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "{spacing.target}"
  button-ghost-hover:
    backgroundColor: "{colors.surface-3}"
    textColor: "{colors.text}"
  button-disabled:
    backgroundColor: "transparent"
    textColor: "{colors.text-3}"
  control-group:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "4px 16px 12px"
  control-row:
    textColor: "{colors.text}"
    typography: "{typography.body}"
    height: "{spacing.row}"
  switch-on:
    backgroundColor: "{colors.accent}"
    rounded: "{rounded.full}"
    size: "36px 20px"
  switch-off:
    backgroundColor: "{colors.surface-3}"
    rounded: "{rounded.full}"
    size: "36px 20px"
  segmented:
    backgroundColor: "{colors.bg}"
    rounded: "{rounded.sm}"
    padding: "2px"
  segmented-option-selected:
    backgroundColor: "{colors.surface-3}"
    textColor: "{colors.text}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.xs}"
    height: "40px"
  status-pill:
    textColor: "{colors.text-2}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.full}"
    padding: "0 12px"
    height: "32px"
  input-pin:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
    typography: "{typography.numeric-lg}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "{spacing.target}"
  game-live:
    backgroundColor: "{colors.accent-bg}"
    rounded: "{rounded.sm}"
    padding: "12px"
  popover:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "20px"
  toast:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "12px 14px"
---

# Design System: DuneBox

## Overview

**Creative North Star: "The Quiet Console"**

DuneBox's operator surfaces are a console, not a show. The sand under the projector is the spectacle; every screen an adult touches is calm, near-black, and legible at arm's length in a dim room, so it never competes with the projection. The direction is the category standard played straight (chosen by Max, 2026-10-03): a crisp dark product UI held to the craft level of Vercel and Linear. No themed or novelty world; no sand textures, no topo-line decoration in the chrome.

Density is moderate and job-grouped. The live sand view leads on the left with four honest facts beneath it; the right column holds controls grouped by job (World, Events, Games, Setup, DuneBox C++), each a hairline-bordered panel of 52px rows. Depth comes from stepped neutral layers, not shadows; color carries meaning only. A single blue says "on" or "selected"; green, amber and red say healthy, attention, broken, always paired with words.

The same tokens drive three surfaces: the web dashboard (the normative source, `web/assets/app.css`), the pygame settings sidebar, and the C++ ofxDatGui panel. When one of the native surfaces can't express a rule, it degrades toward the nearest honest equivalent described under Components, never toward a different look.

**Key Characteristics:**
- Near-black neutral layers (five steps from page to raised control) with 1px hairline borders.
- One blue accent, reserved for on/selected state and focus.
- Geist for all UI text; Geist Mono only for measurements, PINs, URLs and key caps.
- 44px minimum touch targets; 52px control rows.
- Flat at rest; shadows only on floating layers (popovers, toasts) and the selected segment.
- Motion is short and functional (150–220ms, one ease-out curve), and drops away under reduced motion.

## Colors

A neutral, almost achromatic dark ramp with one cool blue accent and three status hues that only ever mean system state.

### Primary
- **Signal Blue** (`accent`): the only "on" color. Fills an enabled switch track, outlines and tints the live-game card (`accent-border`, `accent-bg`), and draws the 2px focus ring. Never used for decoration, headings or links-as-ornament.

### Neutral
- **Projector Black** (`bg`): page background, and the recessed wells inside controls (PIN input, segmented track, copy field, QR plate). Recessed elements go *darker* than their container.
- **Panel** (`surface`): control groups, the live-view frame, the facts strip, the PIN gate.
- **Raised** (`surface-2`): secondary buttons, popovers, toasts; anything that floats or presses up.
- **Pressed / Selected** (`surface-3`): hover on secondary and ghost buttons, the selected segment, the off-state switch track.
- **Hairline** (`border`): every container edge and row divider.
- **Strong Hairline** (`border-strong`): edges of interactive raised elements (secondary buttons, inputs, switches, popovers, toasts, key caps).
- **Ink** (`text`): primary text and the primary-button fill.
- **Muted Ink** (`text-2`): labels, meta lines, hints, values, ghost buttons.
- **Faint Ink** (`text-3`): disabled text and idle status dots only. It still clears 4.5:1 on `surface`; do not go dimmer.

### Status
- **Healthy Green** (`ok`): status dot and toast dot for healthy/connected/success.
- **Attention Amber** (`warn`, `warn-bg`): status pill text and dot when degraded; border at 35% alpha.
- **Fault Red** (`err`, `err-bg`): status pill, offline banner, error toast, field errors.

### Named Rules
**The One Signal Rule.** Signal Blue means "this is on, selected, or focused" and nothing else. If an element isn't stateful, it isn't blue.

**The Words-With-Color Rule.** Every status hue ships with text that says the same thing ("Sensor: waiting", "Can't reach the sandbox."). A dot alone is never the message.

**The Real Palette Exception.** The only multi-hue color on screen is the theme swatch strip in the World group, which is generated from the sandbox's actual terrain palette data. It is evidence, not decoration; never hand-pick hues for it.

## Typography

**Display Font:** none; the console has no display tier.
**Body Font:** Geist (with ui-sans-serif, system-ui, Segoe UI fallback)
**Label/Mono Font:** Geist Mono (with ui-monospace, Cascadia Mono, Consolas fallback)

**Character:** A neutral grotesk and its mono sibling: the pairing reads as engineered and quiet, with Mono marking anything that is a measured or typed value. Geist was chosen deliberately despite the detector's overused-font warning: it is the house face of the Vercel quality bar this direction targets, it is OFL-licensed, and it is vendored offline (`web/assets/fonts/`) because the sandbox often runs with no internet. Keep it.

### Hierarchy
- **Headline** (600, 20px, -0.015em): the PIN gate title; the one heading that stands alone on a screen.
- **Title Large** (600, 16px, -0.01em): the DuneBox wordmark in the top bar.
- **Title** (600, 14px, -0.005em): section heads: "Live sand", control group legends, popover titles. Same size as body; weight does the work.
- **Body** (400, 14px, 1.5): row labels, banners, popover copy, toasts. Base size of the system.
- **Control** (500, 14px, line-height 1): button text.
- **Body Small** (400, 13px): meta lines, hints, field labels, status pills, segmented options.
- **Label** (400, 12px): fact and stat captions (`dt`).
- **Numeric** (Mono 500, 16px, tabular): the four live facts.
- **Numeric Large** (Mono 500, 20px, tabular): game score and time, PIN entry and PIN display (PINs add 0.15–0.2em tracking).

The ramp is compact (12 / 13 / 14 / 16 / 20) because this is a console at arm's length, not a page; hierarchy comes from weight and ink level more than size.

### Named Rules
**The Measured-Value Rule.** Geist Mono with tabular figures for anything that is a number from the system, a PIN, a URL or a key; Geist for everything a human wrote. Never set prose in Mono.

**The Weight-Not-Size Rule.** Section titles are body-size at 600. Don't escalate headings in size to create hierarchy inside the control column.

## Layout

A two-column operator grid: the live view (fluid, `minmax(0, 1fr)`) and a control column (340–400px), 24px gap and padding, max width 1440px, centered. The live view is sticky under the top bar so the sand stays visible while the operator scrolls controls; to stay shorter than the viewport, the frame is sized from height (`--frame-h`, `100vh − 370px` on desktop) times the source aspect ratio (`--ar`, set from each frame's width and height), so it never letterboxes. Under it sit the facts strip and a short Activity list. The control column is split by app: a **sandcam** header over its groups, then a **DuneBox** header with that app's status pill over its group, so both apps read as equals. The top bar is sticky, 10px × 24px padding, with brand left and status pills plus one action pushed right.

Spacing rhythm is a 4px base used mostly in 4 / 8 / 12 / 16 / 24 steps: 8 between inline items, 12 inside facts and cards, 16 between control groups and as panel side padding, 24 for page gutters.

Responsive behavior:
- **≤1023px:** single column, 16px gutters; the live view stops being sticky, caps at 52vh, and the Activity list is hidden.
- **≤640px:** top bar wraps with status pills on their own line; facts become a 2×2 grid; banner stacks; key-cap hints and the shortcut line disappear.
- **Touch (`hover: none`):** all key-cap hints are removed, since there's no keyboard to hint at.

### Named Rules
**The Arm's-Length Rule.** Interactive hit areas are never below 44px (`spacing.target`), and control rows are 52px. A switch's visible track is 36×20 inside a 52×44 hit area.

## Elevation & Depth

Flat by default, tonal layering for structure. Containers sit on the page by stepping one neutral lighter (`bg` to `surface` to `surface-2`) and drawing a 1px hairline; recessed wells step darker back to `bg`. Shadows exist only on things that genuinely float above the page, and they are neutral black, never colored.

### Shadow Vocabulary
- **Float** (`box-shadow: 0 16px 40px -8px rgba(0,0,0,0.7), 0 2px 6px rgba(0,0,0,0.4)`): popovers (pairing, keyboard shortcuts).
- **Toast** (`box-shadow: 0 12px 32px -8px rgba(0,0,0,0.7)`): notification toasts.
- **Seat** (`box-shadow: 0 1px 2px rgba(0,0,0,0.5)`): the selected option in a segmented control, so it reads as a raised key.

### Named Rules
**The No-Glow Rule.** No colored shadows, no blur halos, no backdrop-filter glass. Depth is tone plus hairline; a shadow is always black and only under something that floats.

## Shapes

Gently rounded rectangles throughout. Containers (groups, frames, popovers, toasts, banner) use 8px (`rounded.md`); controls inside them use 6px (`rounded.sm`); the smallest nested pieces (segmented options, key caps) use 4px (`rounded.xs`). Pills (status chips, switch tracks) and dots are fully round. Every edge is a 1px hairline; key caps alone get a 2px bottom edge to read as physical keys. The brand mark is two stroked dune curves, 1.8px stroke, round caps, second line at 50% opacity.

### Named Rules
**The Nesting Rule.** Radius steps down as you go inward: 8 for the container, 6 for the control, 4 for the part inside the control.

## Components

### Buttons
Quiet and solid; the label carries the action.
- **Shape:** gently rounded (`rounded.sm`), 44px minimum height, 14px side padding, 8px gap for an inline key cap.
- **Primary:** Ink fill with Projector Black text; brightens to pure white on hover. Used for at most one decisive action in view ("Connect", "Start sandbox").
- **Secondary:** the workhorse. Raised fill with a Strong Hairline; hover steps to Pressed/Selected and a lighter border.
- **Ghost:** no fill, Muted Ink; hover adds the Pressed/Selected fill and full Ink. For inline, low-stakes actions (Copy, creature set, stepper ±).
- **Small / Icon:** small drops text to 13px and padding to 10px but keeps the 44px height; icon buttons are 44px square.
- **Disabled / Busy:** disabled goes transparent with Faint Ink and a Hairline; busy (`aria-busy`) dims text to Muted Ink. Neither changes the cursor to pointer.
- **Transitions:** background, border and color at 150ms on the house ease-out curve.

### Chips (status pills)
- **Style:** 32px tall fully round pill, Hairline border, Muted Ink text at 13px, leading 8px dot.
- **State:** idle dot is Faint Ink; ok dot is Healthy Green; warn and err tint text, dot and border (35% alpha) in the status hue. Text always states the condition.

### Cards / Containers
- **Corner Style:** 8px (`rounded.md`).
- **Background:** Panel (`surface`).
- **Shadow Strategy:** none; see Elevation & Depth.
- **Border:** 1px Hairline.
- **Internal Padding:** control groups 4px top, 16px sides, 12px bottom with a title row; facts cells 12×16 with Hairline dividers between cells.
- **Disabled group:** contents (not the title or empty-state copy) drop to 50% opacity when the app behind it isn't linked.

### Inputs / Fields
- **Style:** recessed well: Projector Black fill, Strong Hairline, 6px radius, 44px tall. The PIN field is Numeric Large with wide tracking.
- **Focus:** border shifts to Signal Blue and the 2px focus ring sits flush (offset 0).
- **Error:** Fault Red message below the field in 13px, with reserved height so the layout doesn't jump.

### Navigation
The top bar is the only navigation: sticky, near-opaque Projector Black (92%), Hairline bottom edge. Brand mark plus wordmark left; status pills and a single secondary action ("Open on a tablet") right. On narrow screens the pills wrap to a full-width second line.

### Switch (signature control)
Binary settings use a switch, never a checkbox. 36×20 track, 14px knob, inside a 52×44 hit area. Off: Pressed/Selected track, Strong Hairline, Muted Ink knob. On: Signal Blue track and border, Projector Black knob slid 16px. Knob slides at 200ms; under reduced motion it snaps.

### Segmented Theme Picker (signature control)
A recessed 4-up radio group: Projector Black track, 2px padding and gap, 6px outer radius. Options are 40px tall, label over a 4px real-palette swatch strip; selected option takes the Pressed/Selected fill, full Ink and the Seat shadow. Arrow keys move selection.

### Control Row
A 52px row: label left (with a key-cap hint revealed on hover or focus-within, hidden on touch), control right, Hairline divider below. Stacked rows hold full-width controls; hints sit beneath in 13px Muted Ink.

### App Header
Above each app's groups: the app name at 16px/600 with muted meta (language and what it does) in 13px Faint Ink, and, for DuneBox, a status pill pushed right. The same app state appears as a pill in the top bar. Each app keeps its own name; never one generic "Sandbox" label.

### Activity List
Desktop only, under the facts. The last eight command acknowledgements, newest first, each with a 6px status dot, the sandbox's own message in 13px Muted Ink (Ink when it failed), and the time right-aligned in Mono. It scrolls after three rows so the sticky view still fits. Every row is a real reply; nothing is logged speculatively.

### Live Game Card
Inside Games, an active game gets a Signal Blue tinted card (`accent-bg` fill, `accent-border` edge, 6px radius) with the game name in 600 and score/time in Numeric Large. This is the one place the accent fills an area: a game running is the loudest "on" state the console has.

### Popovers and Toasts
Raised fill, Strong Hairline, 8px radius, Float or Toast shadow. Popovers are 360px max, anchored top-right (pairing) or bottom-right (shortcuts). Toasts stack bottom-right, lead with a status dot, and slide up 8px over 220ms (none under reduced motion).

### Key Caps
Geist Mono 11px in Muted Ink on Raised fill, Strong Hairline with a 2px bottom edge, 4px radius. Used for shortcut hints only.

### Native surfaces: pygame sidebar and ofxDatGui panel
The web tokens are normative; the two native panels reuse the same values. Fonts: Geist and Geist Mono TTFs in `assets/fonts/` (pygame) and `DuneBox/bin/data/fonts/` (ofxDatGui). Use static weight instances (Regular 400, Medium 500, SemiBold 600) since neither renderer selects variable-font axes.

| Token | Hex / ofColor | pygame RGB |
|---|---|---|
| bg | `0x0a0a0a` | `(10, 10, 10)` |
| surface | `0x111111` | `(17, 17, 17)` |
| surface-2 | `0x171717` | `(23, 23, 23)` |
| surface-3 | `0x1f1f1f` | `(31, 31, 31)` |
| border | `0x262626` | `(38, 38, 38)` |
| border-strong | `0x3a3a3a` | `(58, 58, 58)` |
| text | `0xededed` | `(237, 237, 237)` |
| text-2 | `0xa1a1a1` | `(161, 161, 161)` |
| text-3 | `0x8a8a8a` | `(138, 138, 138)` |
| accent | `0x52a8ff` | `(82, 168, 255)` |
| accent-bg on surface (pre-composited) | `0x1a2632` | `(26, 38, 50)` |
| ok | `0x3fcf8e` | `(63, 207, 142)` |
| warn | `0xf5a524` | `(245, 165, 36)` |
| err | `0xff6166` | `(255, 97, 102)` |
| err-bg on bg (pre-composited) | `0x231313` | `(35, 19, 19)` |

In C++ use `ofColor::fromHex(0x52a8ff)`; in pygame use the tuple directly. Alpha tokens are pre-composited because neither surface blends translucent fills over arbitrary backgrounds by default.

**pygame sidebar limits and equivalents:**
- No CSS focus ring: when a control has keyboard focus, draw a 2px Signal Blue rect around it with a 2px gap (`pygame.draw.rect(..., width=2, border_radius=8)`).
- Radius via `border_radius=` on `pygame.draw.rect` (8 panels, 6 controls, 4 parts). Hairlines are 1px `width=1` rects in `border` / `border-strong`.
- No letter-spacing, no `font-feature-settings`: Geist Mono already gives fixed-width figures, so render all numbers in Mono. Wordmark and title tracking are dropped.
- No hover on touch and no CSS transitions: switch knob position snaps; that matches the reduced-motion behavior and is acceptable.
- No box-shadow: popover-like overlays rely on `surface-2` plus `border-strong` only.
- Keep 52px rows and 44px hit rects even though the sidebar is mouse-driven.

**ofxDatGui panel limits and equivalents:**
- Map tokens through a custom `ofxDatGuiTheme` subclass (e.g. gui background to `bg`, component background to `surface`, input areas to `bg`, label text to `text`, slider fill and toggle-on to `accent`, mouse-over to `surface-2`, mouse-down to `surface-3`). Hide the colored left stripe or set it to `border`; it would otherwise break the One Signal Rule.
- One font file and one size per theme: use Geist Regular at the 14px-equivalent size; Mono and weight contrast aren't available per component.
- Components are square-cornered rectangles and toggles are checkboxes, not switches; accept both rather than faking radius with images.
- No keyboard focus ring and limited hover states; don't rely on hover to reveal anything.
- Keep component height at or above 44px where the panel is used on a touchscreen.

## Do's and Don'ts

### Do:
- **Do** let the live sand view lead the first viewport; controls sit beside it, grouped by job.
- **Do** step neutrals for depth: `bg` page, `surface` panel, `surface-2` raised, `surface-3` pressed, and recess wells back to `bg`.
- **Do** use Signal Blue only for on, selected and focus (`:focus-visible` is a 2px `accent` outline, 2px offset).
- **Do** pair every status color with text, and write error copy that names the fix.
- **Do** set every system number, PIN, URL and key in Geist Mono with tabular figures.
- **Do** keep hit areas at 44px and control rows at 52px on every surface, native panels included.
- **Do** use the single ease-out curve `cubic-bezier(0.16, 1, 0.3, 1)` at 150ms for color/border changes, 200–220ms for movement, and drop movement under `prefers-reduced-motion`.
- **Do** keep Geist and Geist Mono vendored locally; the dashboard must work offline.

### Don't:
- **Don't** build an admin-template stat-card grid; facts live in one hairline strip under the view.
- **Don't** add glow, colored shadows, gradients on chrome, or backdrop-filter glass.
- **Don't** introduce a second accent or use status hues decoratively.
- **Don't** hand-pick theme swatch colors; they come from the sandbox's real palettes.
- **Don't** show a control the connected app can't honor; hide it or disable its group with an explanation.
- **Don't** rely on hover to reveal anything essential; key-cap hints are the only hover reveal and they vanish on touch.
- **Don't** theme the operator UI with sand, terrain or novelty motifs; the projection owns that.
- **Don't** swap Geist for another face to satisfy an overused-font warning; it was chosen deliberately.
