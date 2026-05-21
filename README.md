# 🏜️ DuneBox sandcam

> *The hackable Python AR sandbox.*

A lightweight, cross-platform augmented reality sandbox built with Python, pygame, and libfreenect. Features biome-aware creatures, ArUco marker triggers, and an AI guide — designed for rapid prototyping and easy customization.

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
| **Depth Sensor** | Kinect v1 (Xbox 360) — default, or see Supported Sensors below |
| **Projector** | Any with HDMI input |
| **PC** | Any modern computer — no GPU needed |

## Supported Sensors

| Sensor | Config value | Library | Resolution | Range |
|---|---|---|---|---|
| Kinect v1 (Xbox 360) | `kinect_v1` | libfreenect (bundled) | 640×480 | 0.4–4.0 m |
| Kinect v2 (Xbox One) | `kinect_v2` | pylibfreenect2 | 512×424 | 0.5–4.5 m |
| Orbbec Femto Bolt | `orbbec` | pyorbbecsdk or pyk4a | 640×576 | 0.25–5.5 m |
| Orbbec Astra | `orbbec` | pyorbbecsdk | 640×480 | 0.6–8.0 m |
| Intel RealSense D435 | `realsense` | pyrealsense2 | 1280×720 | 0.1–10 m |
| Intel RealSense L515 | `realsense` | pyrealsense2 | 1024×768 | 0.25–9 m |
| Mouse simulator | `mouse_simulator` | — (built-in) | configurable | N/A |

### Switching sensors

Edit `sandcam-settings.json`:
```json
{
  "sensor_type": "kinect_v2",
  "sensor_fallback": "mouse_simulator"
}
```

### Installing sensor libraries

```bash
# Kinect V2
pip install pylibfreenect2
# Also needs libfreenect2: brew install libfreenect2 (macOS) / see docs (Linux/Win)

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
Double-click **`run.bat`** — it installs Python and dependencies automatically, then launches.

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

## Project Structure

```
DuneBox-sandcam/
├── main.py              # Entry point + depth processing loop
├── renderer.py          # Elevation LUT + hillshading + contours
├── creatures.py         # Biome-aware creature system
├── webcam_observer.py   # ArUco marker detection via webcam
├── interaction_engine.py # Marker → event triggering
├── ai_guide.py          # Optional AI narration
├── ui.py                # Settings sidebar + display picker
├── depth_source.py      # Kinect v1 via libfreenect
├── calibration/         # Projector-Kinect alignment tools
├── assets/              # Creature sprites + themes
└── sandcam-settings.json # Runtime configuration
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
