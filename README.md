# 🏜️ DuneBox sandcam

> *The hackable Python AR sandbox.*

A lightweight augmented reality sandbox for Windows, built with Python and pygame. The default depth sensor is a Kinect v2 through the Kinect for Windows SDK. Features biome-aware creatures, ArUco marker triggers, and an AI guide.

![Status](https://img.shields.io/badge/status-proof%20of%20concept-orange)
![Language](https://img.shields.io/badge/lang-Python-yellow)

## Features

- **Elevation mapping** — real-time hillshading + contour lines at 60 FPS
- **Biome-aware creatures** — animals appear contextually based on terrain (ocean → fish, mountains → goats, etc.)
- **ArUco marker triggers** — place physical toys with ArUco markers on the sand to trigger themed events (volcano eruption, dinosaur, boat, etc.)
- **AI guide** — optional interactive narration
- **Mouse simulator** — develop and test with no hardware connected
- **Multi-display** — separate projector output window

## Hardware Requirements

| Component | Recommendation |
|---|---|
| **Depth Sensor** | Kinect v2 (Xbox One) with the Kinect for Windows SDK. That is the default. |
| **Projector** | Any with HDMI input |
| **PC** | Windows 10/11. Other systems can still run the mouse simulator. |

## Supported Sensors

The Windows install defaults to `kinect_v2_sdk`.

| Sensor | Config value | Library | Resolution | Range |
|---|---|---|---|---|
| Kinect v2 (Xbox One), Windows SDK, default | `kinect_v2_sdk` | pykinect2 + comtypes (Windows, `kinect-v2` extra) | 512×424 | 0.5–4.5 m |
| Kinect v1 (Xbox 360) | `kinect_v1` | libfreenect (bundled `freenect.dll`) | 640×480 | 0.4–4.0 m |
| Kinect v2 (Xbox One), native | `kinect_v2` | pylibfreenect2 (Linux/macOS, manual install) | 512×424 | 0.5–4.5 m |
| Orbbec Femto Bolt | `orbbec` | pyorbbecsdk or pyk4a | 640×576 | 0.25–5.5 m |
| Orbbec Astra | `orbbec` | pyorbbecsdk | 640×480 | 0.6–8.0 m |
| Intel RealSense D435 | `realsense` | pyrealsense2 | 1280×720 | 0.1–10 m |
| Intel RealSense L515 | `realsense` | pyrealsense2 | 1024×768 | 0.25–9 m |
| Mouse simulator | `mouse_simulator` | (built-in) | configurable | N/A |

### Switching sensors

Edit `sandcam-settings.json`:
```json
{
  "sensor_type": "kinect_v2_sdk",
  "sensor_fallback": "mouse_simulator"
}
```

### Installing sensor libraries

```bash
# Default: Kinect v2 on Windows via the Kinect for Windows SDK.
# `uv sync --extra kinect-v2` or `pip install sandcam[kinect-v2]` installs the Python bindings.
pip install pykinect2 comtypes
# Also install the Kinect for Windows SDK 2.0 (USB driver + Kinect20.dll):
#   https://www.microsoft.com/en-us/download/details.aspx?id=44561
# Requires the Kinect Adapter on a true USB 3.0 port.
# Once the sensor is mounted top-down over the sandbox, press the "A" key in the
# app to auto-calibrate the depth range from the flat sand surface.

# Kinect v1 on Windows uses the bundled freenect.dll and libusb-1.0.dll.
# Set "sensor_type": "kinect_v1". See THIRD_PARTY_LICENSES.md.

# Kinect v2 on Linux or macOS is not the default. Install pylibfreenect2
# yourself (it is not a pyproject extra) and the native libfreenect2 library:
#   https://github.com/OpenKinect/libfreenect2
# Then set "sensor_type": "kinect_v2".

# Orbbec (native SDK)
pip install pyorbbecsdk

# Orbbec Femto Bolt via Azure Kinect SDK
pip install pyk4a

# Intel RealSense
pip install pyrealsense2

# All sensors at once
pip install sandcam[all-sensors]
```

## Quick Start

### Windows (one click)
Double-click **`run.bat`** — it installs Python if needed, fast-forwards this checkout, syncs dependencies, then launches. A failed update still starts the copy already on disk.

### Put it on your desktop (easiest)
Double-click **`Install Desktop Shortcuts.cmd`** once. It adds a **DuneBox** icon
to your desktop (plus a **DuneBox (C++)** icon if that repo sits next
to this one). After that, just double-click **DuneBox** to run — no terminal,
no commands. The installer is safe to re-run; it refreshes the icons in place.

> Prefer PowerShell? Run `install-desktop-shortcuts.ps1` directly.

Or use the full setup script:
```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
git clone https://github.com/Manaiakalani/DuneBox-docs.git
cd DuneBox-docs\scripts; .\setup-windows.ps1
```

### Any platform (manual)
```bash
pip install uv
uv sync
uv run python main.py
```

Runs in **mouse simulator mode** if no Kinect is connected — no hardware needed to try it out.

## Controls

| Key | Action |
|---|---|
| Tab | Settings sidebar |
| A | Auto-calibrate Kinect v2 depth range from the flat sand |
| C | Toggle contour lines |
| G | Toggle creatures |
| V | Cycle creature set (modern / prehistoric / all / none) |
| O | Toggle volcano click-to-place |
| K | Trigger earthquake at centre |
| S | Mute / unmute |
| N | Toggle day/night cycle |
| E | Toggle ecosystem |
| +/- | Speed up / slow down day/night |
| P | Pause day/night |
| F1–F4 | Start dam / volcano / watershed / biome games |
| F5 | Save terrain snapshot |
| B | Toggle TCP bridge to DuneBox (C++) |
| U | Toggle local WebSocket depth server (`ws://127.0.0.1:8765`) |
| R | Reset simulated terrain |
| Esc / Q | Quit |

## ArUco marker IDs

Print the 4×4 markers in `calibration/` (dictionary **DICT_4X4_250**).

| IDs | Role |
|---|---|
| 1–5 | Toys: boat, dino, house, tree, volcano (guide + reactions) |
| 10–13 | Dinosaur spawn / extinction |
| 20 | Place a volcano at the tag |
| 21 | Trigger the nearest volcano |
| 100 / 101 / 102 / 103 | Corners: TL / TR / BR / BL (files `TL-100.svg` … `BL-103.svg`) |

## Project Structure

```
DuneBox-sandcam/
├── main.py              # Entry point + depth processing loop
├── renderer.py          # Elevation LUT + hillshading + contours
├── sensor_api.py        # Pluggable depth sensors
├── creatures.py         # Biome-aware creature system
├── webcam_observer.py   # ArUco marker detection via webcam
├── interaction_engine.py # Marker → event triggering
├── ai_guide.py          # Optional AI narration
├── ui.py                # Settings sidebar + display picker
├── calibration/         # Printed corner tags (100–103)
├── assets/              # Creature sprites + themes
└── sandcam-settings.example.json # Portable first-run defaults
```

## See Also

- **[DuneBox](https://github.com/Manaiakalani/DuneBox)** — C++/OpenFrameworks companion project with GPU water simulation

## Credits & Acknowledgments

- **[sandcam](https://github.com/martinellimakes/sandcam)** by martinellimakes — the Python AR sandbox this project is derived from.
- **[Magic-Sand](https://github.com/thomwolf/Magic-Sand)** by Thomas Wolf & Rasmus R. Paulsen — cross-platform AR sandbox inspiration
- **[SARndbox](https://github.com/KeckCAVES/SARndbox)** by Oliver Kreylos (UC Davis) — the original AR sandbox. [Official site](https://arsandbox.ucdavis.edu/)
- [r/arsandbox](https://reddit.com/r/arsandbox) — community subreddit

## License

Retains the original license from the [sandcam](https://github.com/martinellimakes/sandcam) project.

## Build Guide

See **[DuneBox-docs](https://github.com/Manaiakalani/DuneBox-docs)** for the complete build guide — hardware, physical construction, calibration, troubleshooting, and customization.
