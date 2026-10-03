# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

The operator surfaces are a browser dashboard (served by sandcam), the
in-app pygame settings sidebar, the C++ ofxDatGui panel, and a docs site.
The projected image on the sand is a separate, non-UI output.

## Users

- **Families and hobbyists** running a home-built sandbox for kids. The
  operator is a parent; the players are children with sandy hands.
- **Teachers** using it in a classroom for geography and earth-science lessons.
  They need to switch modes quickly while managing a group.
- **Museum, library and science-center staff** who run it unattended for
  hours and only check in when something looks wrong.
- **Makers and developers** who build the box, calibrate it, and extend the
  code (new creatures, themes, games, sensors).

## Product Purpose

DuneBox turns a box of sand, a depth camera and a projector into a live
topographic map. Kids shape terrain with their hands and the sandbox answers
with contour lines, water, lava, weather and creatures. Success is a sandbox
that a non-technical adult can set up, keep calibrated and run all day, while
kids stay engaged past the first five minutes.

## Positioning

Two first-class apps share one product:

- **DuneBox** (C++ / openFrameworks, derived from Magic-Sand + SARndbox):
  GPU shallow-water simulation, lava, themes, day/night, boid and map games,
  chessboard auto-calibration. Windows, Kinect v1/v2.
- **DuneBox-sandcam** (Python / pygame, derived from sandcam): runs on any
  PC with no GPU, supports Kinect v1/v2, Orbbec, RealSense and a mouse
  simulator; adds ArUco marker triggers, biome-aware creatures, ecosystem,
  volcano, earthquake, an AI guide, and the web dashboard.

Users pick either app; when both run, a TCP/NDJSON bridge links them. Few
open-source sandboxes combine multi-sensor support, a web/tablet controller,
water simulation, creatures and marker interaction.

## Operating Context

- The sandbox sits in a room lit for projection (often dim). The projector
  points down at white play sand from about 1 m.
- The operator controls it from the PC, a keyboard, or a phone/tablet on the
  same network. Text projected on sand is hard to read, so control belongs on
  a separate screen.
- Sessions range from 10-minute home play to 8-hour museum days.
- Calibration drifts when the box is bumped; recalibration must be guided.
- Windows is the primary platform. Setup is scripted via `DuneBox-docs/scripts`.

## Capabilities and Constraints

- Sensors: Kinect v1, Kinect v2 (SDK), Orbbec Femto/Astra and RealSense in
  sandcam; Kinect v1/v2 only in the C++ app.
- Dashboard transport: WebSocket on port 8765 (sandcam), JSON state plus
  PNG depth frames; bridge on TCP 9876.
- sandcam has no water simulation; its "contours" toggle is not water.
- Status: proof of concept. No production deployments claimed.
- Licenses: GPL-2.0 (C++ app), upstream sandcam license (Python),
  CC BY-SA 4.0 (docs).

## Brand Commitments

- Name: **DuneBox**. Tagline in use: "Like a sandbox, but epic." /
  "The hackable Python AR sandbox."
- Credit upstream projects (Magic-Sand, SARndbox, sandcam) visibly.
- Operator surfaces follow the category standard, played straight: a crisp
  dark product UI at the craft level of Vercel and Linear (chosen by Max,
  2026-10-03). No themed or novelty visual world.

## Evidence on Hand

- Creature assets (`assets/creatures/*.json`), terrain presets
  (`assets/terrains/*.npy`), ArUco corner markers (`calibration/*.svg`),
  app icons (`icon.ico`).
- No photos of the physical build, testimonials, or install counts are in the
  repos. Do not fabricate them.

## Product Principles

1. **The sand is the show; screens are for the operator.** Operator UI should
   be calm, legible at arm's length, and never compete with the projection.
2. **Honest state.** Every indicator reflects real system state; every control
   does what its label says or is hidden.
3. **Recoverable by a non-expert.** Errors name the fix (replug sensor,
   recalibrate, restart) in plain language.
4. **Hackable by design.** Makers can trace any UI control to the code that
   handles it.

## Accessibility & Inclusion

- Operators may use a tablet held at a distance in a dim room: large touch
  targets (44 px minimum), high contrast, no hover-only affordances.
- Respect `prefers-reduced-motion`. Status must not rely on color alone.
- Target WCAG 2.2 AA for the dashboard and docs.
