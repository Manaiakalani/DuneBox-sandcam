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
| **Kinect** | Kinect v1 (Xbox 360) |
| **Projector** | Any with HDMI input |
| **PC** | Any modern computer — no GPU needed |

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
